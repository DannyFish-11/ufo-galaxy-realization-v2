"""
Galaxy Agentic OS — NATS JetStream Message Bus
================================================

Wraps ``nats-py`` async client providing typed pub/sub for distributed task
dispatch between the MasterBrain (control plane) and Edge Workers (data plane).

Constraints (see plan 强约束):
  C1  — module-level singleton ``nats_bus``
  C2  — emits events to EventBus (NATS_CONNECTED / DISCONNECTED / RECONNECTING)
  C5  — configured via ``GALAXY_NATS_URL`` env var; embedded NATS if not set
  C7  — all methods return ``{"success": bool, "error": str | None, ...}``
  C8  — exposes ``is_connected()`` and ``get_stats()``
  C11 — uses stdlib ``logging`` (matching codebase convention)
  C12 — JSON wire format matching Pydantic model field names (snake_case)

PR-NATS-CORE: NATS is a core component. Embedded NATS server starts automatically
when no external GALAXY_NATS_URL is configured. No-op mode is removed — all
publish/subscribe calls use real NATS transport.

PR-4 — Agent Bus & Fabric Convergence
--------------------------------------
NATS is the **distributed carrier / fabric layer** for the Galaxy Agent Bus.
It carries canonical ``TaskEnvelope`` / ``ResultEnvelope`` contracts across
cluster boundaries but does NOT define message semantics.

The authority sentinel ``NATS_FABRIC_CARRIER_AUTHORITY`` identifies this
module as the canonical NATS carrier layer implementation.  All messages
published via this bus must carry the ``_nats_schema`` discriminator field
(set automatically by ``publish_task_envelope`` /
``publish_task_result_envelope``) so that consumers can verify the envelope
format.

Layer identity (from core.agent_bus_fabric):
    NATS_CARRIER_LAYER = "NATS::CARRIER_FABRIC_LAYER"
"""

from __future__ import annotations

# PR-4: NATS carrier / fabric layer authority sentinel.
# Identifies this module as the canonical distributed carrier implementation
# for the Galaxy Agent Bus.  NATS carries TaskEnvelope/ResultEnvelope
# contracts but does NOT define message semantics.
NATS_FABRIC_CARRIER_AUTHORITY: str = "NATS::CARRIER_FABRIC_LAYER_V1"

# PR-8: Network Topology Runtime integration sentinel.
# Affirms that this module's connectivity state is absorbed into the canonical
# NetworkTopologyRuntime via assimilate_nats_state() / absorb_nats_state().
NETWORK_TOPOLOGY_RUNTIME_INTEGRATED: str = (
    "NATS_BUS::NETWORK_TOPOLOGY_RUNTIME_INTEGRATED_V1"
)

# PR-509: Capability + Network Runtime Assimilation integration sentinel.
# Affirms that NATSBus.connect() and .disconnect() now call
# absorb_nats_connectivity_event() so that NATS fabric state is reliably
# populated in the canonical NetworkTopologyRuntime on every connection
# lifecycle change.
CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED: str = (
    "NATS_BUS::CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED_V1"
)

import asyncio
import json
import logging
import os
import socket
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("nats_bus")

from core.schemas.contracts import (
    AgentEventModel,
    MCPCallRequestModel,
    TaskDispatchModel,
    TaskResultModel,
    WorkerHeartbeatModel,
    WorkerRegistrationModel,
    WorkerShutdownModel,
)

# PR-AIPV3-NATS: Unified AIP v3 models — NATS transports canonical AIP v3 messages
from core.schemas.aip_v3 import (
    AIPMessage,
    AckMsg,
    CancelResultMsg,
    CapabilityQueryMsg,
    CapabilityReportMsg,
    CoordSyncMsg,
    DelegatedExecutionSignalMsg,
    DeviceRegisterMsg,
    DeviceUnregisterMsg,
    GoalExecutionMsg,
    GoalExecutionResultMsg,
    HeartbeatAckMsg,
    HeartbeatMsg,
    MeshJoinMsg,
    MeshLeaveMsg,
    MeshResultMsg,
    MeshTopologyMsg,
    MsgType,
    PeerAnnounceMsg,
    PeerExchangeMsg,
    ReconciliationSignalMsg,
    StateEventMsg,
    TakeoverRequestMsg,
    TakeoverResponseMsg,
    TaskAssignMsg,
    TaskCancelMsg,
    TaskResultMsg,
    WebRTCBindMsg,
    WebRTCUnbindMsg,
    WebRTCTransportStateMsg,
    create_aip_message,
    parse_aip_message,
)

# NATS import — may not be installed
try:
    import nats
    from nats.aio.client import Client as NATSClient
    from nats.js import JetStreamContext

    _HAS_NATS = True
except ImportError:
    _HAS_NATS = False
    NATSClient = None  # type: ignore[assignment,misc]
    JetStreamContext = None  # type: ignore[assignment,misc]


def _get_lan_ip() -> str:
    """Return the host's primary LAN IPv4 address, or empty string if unavailable.

    Uses a UDP socket pointed at a public address to discover which local
    interface the OS would route outbound traffic through.  No data is
    actually transmitted.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return ""


def _try_emit_event(event_type_name: str, data: dict) -> None:
    """Best-effort emit to EventBus.  Never raises."""
    try:
        from integration.event_bus import event_bus, EventType

        et = getattr(EventType, event_type_name, None)
        if et is not None:
            event_bus.publish_sync(et, "agentic_os", data)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# JetStream stream definitions
# ═══════════════════════════════════════════════════════════════════════════════

_STREAMS = {
    "GALAXY_TASKS": {
        "subjects": ["galaxy.tasks.>"],
        "max_msgs": 100_000,
        "max_bytes": 1_073_741_824,  # 1 GB
    },
    "GALAXY_MCP": {
        "subjects": ["galaxy.mcp.>"],
        "max_msgs": 50_000,
        "max_bytes": 536_870_912,  # 512 MB
    },
    "GALAXY_EVENTS": {
        "subjects": ["galaxy.events.>", "galaxy.workers.>"],
        "max_msgs": 200_000,
        "max_bytes": 536_870_912,
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# PR-2: Standardized topic namespace
# ═══════════════════════════════════════════════════════════════════════════════

class NATSTopics:
    """Canonical NATS subject prefixes for PR-2 unified bus.

    All internal publishers and subscribers MUST use these constants so that
    the topic contract is a single source of truth.

    Topic hierarchy:
      task.*          — task lifecycle (dispatch, result, cancel, status)
      device.*        — device events (register, heartbeat, status, presence)
      presence.*      — presence/projection events
      capability.*    — capability registration and resolution events
      audit.*         — audit log entries
    """

    # ── Task plane ───────────────────────────────────────────────────────────
    TASK_DISPATCH = "galaxy.task.dispatch"
    TASK_RESULT = "galaxy.task.result"
    TASK_CANCEL = "galaxy.task.cancel"
    TASK_STATUS = "galaxy.task.status"

    # ── Device plane ─────────────────────────────────────────────────────────
    DEVICE_REGISTER = "galaxy.device.register"
    DEVICE_HEARTBEAT = "galaxy.device.heartbeat"
    DEVICE_STATUS = "galaxy.device.status"
    DEVICE_PRESENCE = "galaxy.device.presence"

    # ── Presence plane ───────────────────────────────────────────────────────
    PRESENCE_STATE = "galaxy.presence.state"
    PRESENCE_PROJECTION = "galaxy.presence.projection"

    # ── Capability plane ─────────────────────────────────────────────────────
    CAPABILITY_REGISTERED = "galaxy.capability.registered"
    CAPABILITY_REMOVED = "galaxy.capability.removed"

    # ── Audit plane ──────────────────────────────────────────────────────────
    AUDIT_COMMAND = "galaxy.audit.command"
    AUDIT_RESULT = "galaxy.audit.result"
    AUDIT_VIOLATION = "galaxy.audit.violation"

    @classmethod
    def task_dispatch(cls, target: str) -> str:
        return f"{cls.TASK_DISPATCH}.{target}"

    @classmethod
    def task_result(cls, task_id: str) -> str:
        return f"{cls.TASK_RESULT}.{task_id}"

    @classmethod
    def device_heartbeat(cls, device_id: str) -> str:
        return f"{cls.DEVICE_HEARTBEAT}.{device_id}"

    @classmethod
    def capability_registered(cls, source: str) -> str:
        return f"{cls.CAPABILITY_REGISTERED}.{source}"


class WorkerLifecycleSubjects:
    """Canonical worker lifecycle subjects used by both publishers and consumers."""

    REGISTER = "galaxy.workers.register"
    HEARTBEAT = "galaxy.workers.heartbeat"
    SHUTDOWN = "galaxy.workers.shutdown"
    RESULT = "galaxy.tasks.result.*"


class NATSBus:
    """NATS JetStream client for distributed task dispatch.

    PR-NATS-CORE: NATS is now a core component. If ``GALAXY_NATS_URL`` is not
    set, the embedded NATS server is started automatically. No-op mode is
    removed — all publish/subscribe calls use real NATS transport.
    """

    _instance: Optional[NATSBus] = None

    def __init__(self) -> None:
        # PR-NATS-CORE: NATS is now a core component
        self._url = os.environ.get("GALAXY_NATS_URL", "")
        self._auto_local = False  # True when URL was auto-defaulted to localhost
        self._nc: Optional[Any] = None  # NATSClient
        self._js: Optional[Any] = None  # JetStreamContext
        self._connected = False
        self._embedded: Optional[Any] = None  # EmbeddedNATSServer instance
        self._subscriptions: list = []
        self._subscription_metadata: Dict[int, Dict[str, str]] = {}
        self._stats = {
            "published": 0,
            "received": 0,
            "errors": 0,
            "reconnects": 0,
        }

        # 不再接受no-op — 如果没有URL，准备启动内置服务器
        if not self._url:
            if _HAS_NATS:
                self._url = "nats://localhost:4222"
                self._auto_local = True
            else:
                logger.warning(
                    "NATSBus: nats-py not installed. "
                    "Install: pip install nats-py[nats]"
                )

    @classmethod
    def get_instance(cls) -> NATSBus:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Connection lifecycle ────────────────────────────────────────────────

    async def connect(self, url: str = "") -> dict:
        """Connect to NATS server and create JetStream streams.

        PR-NATS-CORE: If no external NATS is available, automatically starts
        the embedded NATS server.
        """
        if self._connected:
            return {"success": True, "already_connected": True}

        target = url or self._url

        # PR-NATS-CORE: If no URL configured, try to start embedded server
        if not target and not self._embedded:
            from core.nats_server import EmbeddedNATSServer
            self._embedded = EmbeddedNATSServer()
            if await self._embedded.start():
                target = os.environ.get("GALAXY_NATS_URL", "nats://localhost:4222")
                self._url = target
                self._auto_local = False
                logger.info("NATSBus: using embedded NATS server at %s", target)
            else:
                logger.error("NATSBus: embedded NATS server failed to start")
                return {"success": False, "error": "Embedded NATS server failed to start"}

        try:
            self._nc = await nats.connect(
                target,
                reconnected_cb=self._on_reconnect,
                disconnected_cb=self._on_disconnect,
                error_cb=self._on_error,
                # Auto-local default: limited retries for auto-detected URLs,
                # unlimited retries for explicitly configured URLs.
                max_reconnect_attempts=3 if self._auto_local else -1,
            )
            self._js = self._nc.jetstream()

            # Ensure JetStream streams exist
            for name, cfg in _STREAMS.items():
                try:
                    await self._js.find_stream_name_by_subject(cfg["subjects"][0].replace(">", "*"))
                except Exception:
                    from nats.js.api import StreamConfig

                    await self._js.add_stream(
                        StreamConfig(
                            name=name,
                            subjects=cfg["subjects"],
                            max_msgs=cfg["max_msgs"],
                            max_bytes=cfg["max_bytes"],
                            retention="limits",
                            storage="file",
                        )
                    )
                    logger.info(f"NATSBus: created stream {name}")

            self._connected = True
            _try_emit_event("NATS_CONNECTED", {"url": target})
            # PR-509: Absorb NATS connectivity state into the canonical
            # NetworkTopologyRuntime so that topology consumers see a live
            # NATS fabric node.
            _absorb_nats_state(is_connected=True, url=target)
            logger.info(f"NATSBus: connected to {target}")
            return {"success": True}

        except Exception as exc:
            self._stats["errors"] += 1
            if self._auto_local:
                # Auto-local default failed — try embedded server as fallback
                if not self._embedded:
                    from core.nats_server import EmbeddedNATSServer
                    self._embedded = EmbeddedNATSServer()
                if await self._embedded.start():
                    target = os.environ.get("GALAXY_NATS_URL", "nats://localhost:4222")
                    self._url = target
                    self._auto_local = False
                    return await self.connect(target)
                lan_ip = _get_lan_ip()
                hint = (
                    f" For cross-device support set: GALAXY_NATS_URL=nats://{lan_ip}:4222"
                    if lan_ip
                    else " Set GALAXY_NATS_URL=nats://<LAN_IP>:4222 for cross-device support."
                )
                logger.warning(
                    "NATSBus: could not reach nats://localhost:4222 — embedded server also failed.%s",
                    hint,
                )
                return {"success": False, "error": f"NATS connection failed: {exc}"}
            logger.error(f"NATSBus: connection failed — {exc}")
            return {"success": False, "error": str(exc)}

    async def disconnect(self) -> dict:
        """Gracefully close NATS connection and stop embedded server if running."""
        if not self._connected:
            return {"success": True}
        try:
            for sub in self._subscriptions:
                try:
                    await sub.unsubscribe()
                except Exception:
                    pass
            self._subscriptions.clear()
            self._subscription_metadata.clear()
            await self._nc.drain()
            self._connected = False
            # PR-509: Absorb disconnected state into the canonical
            # NetworkTopologyRuntime so that topology consumers see the NATS
            # fabric node as unavailable.
            _absorb_nats_state(is_connected=False)
            logger.info("NATSBus: disconnected")
            return {"success": True}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        finally:
            # PR-NATS-CORE: Stop embedded server if we started it
            if self._embedded:
                self._embedded.stop()
                self._embedded = None

    # ── Publish methods ─────────────────────────────────────────────────────

    # ═══════════════════════════════════════════════════════════════════════
    # PR-AIPV3-NATS: AIP v3 unified publish methods (direct model usage)
    # ═══════════════════════════════════════════════════════════════════════
    # All NATS messages now carry canonical AIP v3 format.
    # Publishers use AIPMessage subclasses directly; legacy models auto-convert.

    async def publish_aip_v3(self, subject: str, aip_message: "AIPMessage") -> dict:
        """Publish a canonical AIP v3 message to NATS.

        This is the PRIMARY publish method. All other publish_* methods delegate
        here after converting their input to AIPMessage subclasses.

        Args:
            subject: NATS subject (e.g. "galaxy.tasks.dispatch.worker_01")
            aip_message: An AIPMessage subclass instance (TaskAssignMsg, HeartbeatMsg, etc.)

        Returns:
            {"success": bool, "seq": int} or {"success": False, "error": str}
        """
        data = aip_message.model_dump(mode="json", exclude_none=True)
        return await self._publish(subject, data)

    # ── Device lifecycle ──

    async def publish_device_register(self, msg: "DeviceRegisterMsg") -> dict:
        """Publish DEVICE_REGISTER to ``galaxy.device.register``.

        Used for: Worker registration, Mesh peer enrollment, device discovery.
        """
        return await self.publish_aip_v3(NATSTopics.DEVICE_REGISTER, msg)

    async def publish_device_unregister(self, msg: "DeviceUnregisterMsg") -> dict:
        """Publish DEVICE_UNREGISTER to ``galaxy.device.register`` (status=offline)."""
        return await self.publish_aip_v3(NATSTopics.DEVICE_REGISTER, msg)

    async def publish_heartbeat(self, heartbeat: "HeartbeatMsg") -> dict:
        """Publish HEARTBEAT to ``galaxy.device.heartbeat.{device_id}``."""
        subject = NATSTopics.device_heartbeat(heartbeat.device_id)
        return await self.publish_aip_v3(subject, heartbeat)

    async def publish_heartbeat_ack(self, ack: "HeartbeatAckMsg") -> dict:
        """Publish HEARTBEAT_ACK back to device."""
        return await self.publish_aip_v3(f"galaxy.device.heartbeat_ack.{ack.device_id}", ack)

    async def publish_capability_report(self, msg: "CapabilityReportMsg") -> dict:
        """Publish CAPABILITY_REPORT to ``galaxy.capability.registered``.

        Announces device capabilities to the system.
        """
        return await self.publish_aip_v3(NATSTopics.CAPABILITY_REGISTERED, msg)

    # ── Task / execution ──

    async def publish_task_assign(self, msg: "TaskAssignMsg") -> dict:
        """Publish TASK_ASSIGN to ``galaxy.tasks.dispatch.{device_id}``."""
        subject = NATSTopics.task_dispatch(msg.device_id)
        return await self.publish_aip_v3(subject, msg)

    async def publish_task_result(self, msg: "TaskResultMsg") -> dict:
        """Publish TASK_RESULT to ``galaxy.tasks.result.{task_id}``."""
        subject = NATSTopics.task_result(msg.task_id or msg.device_id)
        return await self.publish_aip_v3(subject, msg)

    async def publish_task_cancel(self, msg: "TaskCancelMsg") -> dict:
        """Publish TASK_CANCEL to ``galaxy.tasks.cancel.{task_id}``."""
        return await self.publish_aip_v3(f"galaxy.task.cancel.{msg.task_id}", msg)

    async def publish_goal_execution(self, msg: "GoalExecutionMsg") -> dict:
        """Publish GOAL_EXECUTION to ``galaxy.tasks.dispatch.{device_id}``."""
        subject = NATSTopics.task_dispatch(msg.device_id)
        return await self.publish_aip_v3(subject, msg)

    async def publish_goal_result(self, msg: "GoalExecutionResultMsg") -> dict:
        """Publish GOAL_EXECUTION_RESULT to ``galaxy.tasks.result.{task_id}``."""
        subject = NATSTopics.task_result(msg.task_id)
        return await self.publish_aip_v3(subject, msg)

    # ── Mesh coordination ──

    async def publish_mesh_join(self, msg: "MeshJoinMsg") -> dict:
        """Publish MESH_JOIN to ``galaxy.mesh.join``."""
        return await self.publish_aip_v3("galaxy.mesh.join", msg)

    async def publish_mesh_leave(self, msg: "MeshLeaveMsg") -> dict:
        """Publish MESH_LEAVE to ``galaxy.mesh.leave``."""
        return await self.publish_aip_v3("galaxy.mesh.leave", msg)

    async def publish_mesh_result(self, msg: "MeshResultMsg") -> dict:
        """Publish MESH_RESULT to ``galaxy.mesh.result.{mesh_id}``."""
        return await self.publish_aip_v3(f"galaxy.mesh.result.{msg.mesh_id}", msg)

    async def publish_mesh_topology(self, msg: "MeshTopologyMsg") -> dict:
        """Publish MESH_TOPOLOGY to ``galaxy.mesh.topology`` or reply."""
        return await self.publish_aip_v3("galaxy.mesh.topology", msg)

    async def publish_coord_sync(self, msg: "CoordSyncMsg") -> dict:
        """Publish COORD_SYNC to ``galaxy.mesh.sync.{mesh_id}``."""
        return await self.publish_aip_v3(f"galaxy.mesh.sync.{msg.mesh_id}", msg)

    # ── Peer / takeover ──

    async def publish_takeover_request(self, msg: "TakeoverRequestMsg") -> dict:
        """Publish TAKEOVER_REQUEST to ``galaxy.device.takeover``.

        Requests target device to take over task execution.
        """
        return await self.publish_aip_v3(f"galaxy.device.takeover.{msg.target_device_id}", msg)

    async def publish_takeover_response(self, msg: "TakeoverResponseMsg") -> dict:
        """Publish TAKEOVER_RESPONSE back to requester."""
        return await self.publish_aip_v3(f"galaxy.device.takeover_response.{msg.device_id}", msg)

    async def publish_peer_announce(self, msg: "PeerAnnounceMsg") -> dict:
        """Publish PEER_ANNOUNCE to ``galaxy.mesh.peers``.

        Announces a new peer device to the mesh.
        """
        return await self.publish_aip_v3("galaxy.mesh.peers", msg)

    async def publish_peer_exchange(self, msg: "PeerExchangeMsg") -> dict:
        """Publish PEER_EXCHANGE to ``galaxy.mesh.peers.{peer_device_id}``."""
        return await self.publish_aip_v3(f"galaxy.mesh.peers.{msg.peer_device_id}", msg)

    # ── Signals ──

    async def publish_delegated_signal(self, msg: "DelegatedExecutionSignalMsg") -> dict:
        """Publish DELEGATED_EXECUTION_SIGNAL to ``galaxy.signals.delegated``.

        Carries ACK / PROGRESS / RESULT / TIMEOUT / CANCELLED lifecycle events.
        """
        return await self.publish_aip_v3("galaxy.signals.delegated", msg)

    async def publish_reconciliation(self, msg: "ReconciliationSignalMsg") -> dict:
        """Publish RECONCILIATION_SIGNAL to ``galaxy.signals.reconciliation``.

        Cross-device state reconciliation signal.
        """
        return await self.publish_aip_v3("galaxy.signals.reconciliation", msg)

    # ── State events ──

    async def publish_state_event(self, msg: "StateEventMsg") -> dict:
        """Publish STATE_EVENT to ``galaxy.events.{event_category}``."""
        subject = f"galaxy.events.{msg.event_category or 'generic'}"
        return await self.publish_aip_v3(subject, msg)

    # ── WebRTC control ──

    async def publish_webrtc_bind(self, msg: "WebRTCBindMsg") -> dict:
        """Publish WEBRTC_BIND to ``galaxy.webrtc.bind``.

        Binds a WebRTC session to a task or device.
        """
        return await self.publish_aip_v3("galaxy.webrtc.bind", msg)

    async def publish_webrtc_unbind(self, msg: "WebRTCUnbindMsg") -> dict:
        """Publish WEBRTC_UNBIND to ``galaxy.webrtc.unbind``.

        Unbinds a WebRTC session.
        """
        return await self.publish_aip_v3("galaxy.webrtc.unbind", msg)

    async def publish_webrtc_transport_state(self, msg: "WebRTCTransportStateMsg") -> dict:
        """Publish WEBRTC_TRANSPORT_STATE to ``galaxy.webrtc.state``.

        Notifies of WebRTC transport state changes.
        """
        return await self.publish_aip_v3("galaxy.webrtc.state", msg)

    # ── Generic ACK ──

    async def publish_ack(self, msg: "AckMsg") -> dict:
        """Publish ACK to acknowledge a message."""
        return await self.publish_aip_v3(f"galaxy.ack.{msg.ack_for_correlation_id}", msg)

    # ═══════════════════════════════════════════════════════════════════════
    # Legacy compatibility methods (auto-convert to AIP v3)
    # ═══════════════════════════════════════════════════════════════════════
    # These methods accept the old contracts.py models and automatically
    # convert them to AIP v3 before publishing. Existing callers work
    # without modification.

    async def publish_task_dispatch(self, worker_id: str, task: TaskDispatchModel) -> dict:
        """[Legacy] Publish TaskDispatch — auto-converts to AIP v3 TASK_ASSIGN."""
        try:
            data = task.model_dump(mode="json", exclude_none=True)
            msg = TaskAssignMsg(
                device_id=worker_id,
                task_id=data.get("task_id", ""),
                action=data.get("action", ""),
                params=data.get("params", {}),
                priority=data.get("priority", "normal"),
                timeout_ms=data.get("timeout_ms", 30000),
                trace_id=data.get("trace_id", ""),
            )
            return await self.publish_task_assign(msg)
        except Exception as exc:
            logger.debug("AIP v3 convert failed for task_dispatch, legacy fallback: %s", exc)
            subject = f"galaxy.tasks.dispatch.{worker_id}"
            return await self._publish(subject, task.model_dump(mode="json", exclude_none=True))

    async def publish_legacy_task_result(self, task_id: str, result: TaskResultModel) -> dict:
        """[Legacy] Publish TaskResult — auto-converts to AIP v3 TASK_RESULT."""
        try:
            data = result.model_dump(mode="json", exclude_none=True)
            msg = TaskResultMsg(
                device_id=data.get("worker_id", ""),
                task_id=task_id,
                status=data.get("status", ""),
                result=data.get("result"),
                error=data.get("error", ""),
                duration_ms=data.get("duration_ms", 0),
                trace_id=data.get("trace_id", ""),
            )
            return await self.publish_task_result(msg)
        except Exception as exc:
            logger.debug("AIP v3 convert failed for task_result, legacy fallback: %s", exc)
            subject = f"galaxy.tasks.result.{task_id}"
            return await self._publish(subject, result.model_dump(mode="json", exclude_none=True))

    async def publish_legacy_heartbeat(self, heartbeat: WorkerHeartbeatModel) -> dict:
        """[Legacy] Publish WorkerHeartbeat — auto-converts to AIP v3 HEARTBEAT."""
        try:
            data = heartbeat.model_dump(mode="json", exclude_none=True)
            msg = HeartbeatMsg(
                device_id=data.get("worker_id", ""),
                status=data.get("status", "online"),
                metadata=data.get("metadata", {}),
                timestamp=data.get("timestamp", int(time.time() * 1000)),
            )
            return await self.publish_heartbeat(msg)
        except Exception as exc:
            logger.debug("AIP v3 convert failed for heartbeat, legacy fallback: %s", exc)
            return await self._publish(
                WorkerLifecycleSubjects.HEARTBEAT,
                heartbeat.model_dump(mode="json", exclude_none=True),
            )

    async def publish_legacy_worker_registration(self, registration: WorkerRegistrationModel) -> dict:
        """[Legacy] Publish WorkerRegistration — auto-converts to AIP v3 DEVICE_REGISTER."""
        try:
            data = registration.model_dump(mode="json", exclude_none=True)
            msg = DeviceRegisterMsg(
                device_id=data.get("worker_id", ""),
                device_type=data.get("worker_type", "worker"),
                capabilities=data.get("capabilities", []),
                metadata=data.get("metadata", {}),
                status="online",
            )
            return await self.publish_device_register(msg)
        except Exception as exc:
            logger.debug("AIP v3 convert failed for worker_registration, legacy fallback: %s", exc)
            return await self._publish(
                WorkerLifecycleSubjects.REGISTER,
                registration.model_dump(mode="json", exclude_none=True),
            )

    async def publish_legacy_worker_shutdown(self, shutdown: WorkerShutdownModel) -> dict:
        """[Legacy] Publish WorkerShutdown — auto-converts to AIP v3 DEVICE_UNREGISTER."""
        try:
            data = shutdown.model_dump(mode="json", exclude_none=True)
            msg = DeviceUnregisterMsg(
                device_id=data.get("worker_id", ""),
                reason=data.get("reason", "shutdown"),
            )
            return await self.publish_device_unregister(msg)
        except Exception as exc:
            logger.debug("AIP v3 convert failed for worker_shutdown, legacy fallback: %s", exc)
            return await self._publish(
                WorkerLifecycleSubjects.SHUTDOWN,
                shutdown.model_dump(mode="json", exclude_none=True),
            )

    async def publish_event(self, event: AgentEventModel) -> dict:
        """[Legacy] Publish AgentEvent — auto-converts to AIP v3 STATE_EVENT."""
        try:
            data = event.model_dump(mode="json", exclude_none=True)
            msg = StateEventMsg(
                event_category=data.get("event_type", "generic"),
                event_action="triggered",
                payload=data.get("payload", {}),
                trace_id=data.get("trace_id", ""),
            )
            return await self.publish_state_event(msg)
        except Exception as exc:
            logger.debug("AIP v3 convert failed for event, legacy fallback: %s", exc)
            subject = f"galaxy.events.{event.event_type}"
            return await self._publish(subject, event.model_dump(mode="json", exclude_none=True))

    async def publish_mcp_call(self, request: MCPCallRequestModel) -> dict:
        """Publish MCP call to ``galaxy.mcp.calls``.

        MCP uses its own standard protocol (JSON-RPC); it does NOT convert to AIP v3.
        MCP messages are bridged via the MCP Gateway Adapter, not the NATS AIP v3 adapter.
        """
        return await self._publish(
            "galaxy.mcp.calls",
            request.model_dump(mode="json", exclude_none=True),
        )

    async def publish_task_envelope(self, target: str, envelope: Any) -> dict:
        """Publish a TaskEnvelope to ``galaxy.tasks.dispatch.{target}``.

        PR-3: TaskEnvelope is the primary NATS transport format.  The
        ``_nats_schema`` discriminator field allows subscribers to detect and
        parse the envelope format before falling back to legacy TaskDispatch.
        """
        subject = f"galaxy.tasks.dispatch.{target}"
        data = envelope.model_dump(mode="json", exclude_none=True)
        data["_nats_schema"] = "TaskEnvelope"
        return await self._publish(subject, data)

    async def publish_task_result_envelope(self, task_id: str, envelope: Any) -> dict:
        """Publish a TaskEnvelope-shaped result to ``galaxy.tasks.result.{task_id}``.

        PR-3: Publishes a unified result payload that carries both the legacy
        ``status`` field (for backward-compatible consumers) and a full
        TaskEnvelope representation.
        """
        subject = f"galaxy.tasks.result.{task_id}"
        data = envelope.model_dump(mode="json", exclude_none=True)
        data["_nats_schema"] = "TaskEnvelope"
        return await self._publish(subject, data)

    # ── PR-2: Canonical trace-propagating publish methods ───────────────────

    def _ensure_trace_fields(
        self,
        data: dict,
        trace_id: str = "",
        runtime_session_id: str = "",
        remote_execution_mode: str = "",
        lifecycle_state: str = "",
    ) -> dict:
        """Ensure *data* carries trace_id, runtime_session_id, and remote_execution_mode.

        This method is the NATS-layer equivalent of
        :func:`~galaxy_gateway.protocol.compat.inject_trace_metadata`
        and enforces the PR-2 unified envelope contract on every published
        message.

        PR-7: ``remote_execution_mode`` is propagated alongside trace fields so
        that both ``command_only`` and ``agent_runtime`` dispatches carry the
        same substrate metadata through the NATS transport layer.

        PR-12: ``lifecycle_state`` is propagated so that NATS consumers can
        observe canonical execution lifecycle state without inspecting payload
        shapes.
        """
        import uuid as _uuid_lib
        out = dict(data)
        if not out.get("trace_id"):
            out["trace_id"] = trace_id or f"trace_{_uuid_lib.uuid4().hex[:12]}"
        if not out.get("runtime_session_id"):
            out["runtime_session_id"] = runtime_session_id or f"session_{_uuid_lib.uuid4().hex[:12]}"
        if remote_execution_mode and not out.get("remote_execution_mode"):
            out["remote_execution_mode"] = remote_execution_mode
        # PR-12: propagate lifecycle state through transport layer
        if lifecycle_state and not out.get("lifecycle_state"):
            out["lifecycle_state"] = lifecycle_state
        return out

    async def publish_task_event(
        self,
        topic_suffix: str,
        data: dict,
        *,
        trace_id: str = "",
        runtime_session_id: str = "",
        remote_execution_mode: str = "",
        lifecycle_state: str = "",
    ) -> dict:
        """Publish to the canonical ``galaxy.task.*`` namespace with trace propagation.

        Args:
            topic_suffix: Sub-topic path (e.g. ``"dispatch.worker_01"``).
            data:          Message payload dict (will be augmented with trace fields).
            trace_id:      Distributed trace identifier.
            runtime_session_id: Session scope identifier.
            remote_execution_mode: PR-7 substrate mode label (``"agent_runtime"``
                or ``"command_only"``).  When provided, the value is propagated
                alongside trace fields so that NATS consumers can route or
                observe by mode without inspecting payload shapes.
            lifecycle_state: PR-12 canonical lifecycle state label.  When
                provided, the value is propagated so that NATS consumers can
                observe execution lifecycle state without inspecting payload
                shapes.
        """
        payload = self._ensure_trace_fields(
            data, trace_id, runtime_session_id, remote_execution_mode
        )
        payload["_nats_schema"] = "UnifiedTaskEvent"
        # PR-12: propagate lifecycle_state through transport layer (additive).
        if lifecycle_state and not payload.get("lifecycle_state"):
            payload["lifecycle_state"] = lifecycle_state
        return await self._publish(f"galaxy.task.{topic_suffix}", payload)

    async def publish_device_event(
        self,
        topic_suffix: str,
        data: dict,
        *,
        trace_id: str = "",
        runtime_session_id: str = "",
    ) -> dict:
        """Publish to the canonical ``galaxy.device.*`` namespace with trace propagation."""
        payload = self._ensure_trace_fields(data, trace_id, runtime_session_id)
        payload["_nats_schema"] = "UnifiedDeviceEvent"
        return await self._publish(f"galaxy.device.{topic_suffix}", payload)

    async def publish_presence_event(
        self,
        topic_suffix: str,
        data: dict,
        *,
        trace_id: str = "",
        runtime_session_id: str = "",
    ) -> dict:
        """Publish to the canonical ``galaxy.presence.*`` namespace with trace propagation."""
        payload = self._ensure_trace_fields(data, trace_id, runtime_session_id)
        payload["_nats_schema"] = "UnifiedPresenceEvent"
        return await self._publish(f"galaxy.presence.{topic_suffix}", payload)

    async def publish_capability_event(
        self,
        topic_suffix: str,
        data: dict,
        *,
        trace_id: str = "",
        runtime_session_id: str = "",
    ) -> dict:
        """Publish to the canonical ``galaxy.capability.*`` namespace with trace propagation."""
        payload = self._ensure_trace_fields(data, trace_id, runtime_session_id)
        payload["_nats_schema"] = "UnifiedCapabilityEvent"
        return await self._publish(f"galaxy.capability.{topic_suffix}", payload)

    async def publish_audit_event(
        self,
        topic_suffix: str,
        data: dict,
        *,
        trace_id: str = "",
        runtime_session_id: str = "",
    ) -> dict:
        """Publish to the canonical ``galaxy.audit.*`` namespace with trace propagation."""
        payload = self._ensure_trace_fields(data, trace_id, runtime_session_id)
        payload["_nats_schema"] = "UnifiedAuditEvent"
        return await self._publish(f"galaxy.audit.{topic_suffix}", payload)

    # ── Subscribe methods ───────────────────────────────────────────────────

    async def subscribe_task_dispatches(
        self, worker_id: str, callback: Callable
    ) -> dict:
        """Subscribe to task dispatches for a specific worker.

        PR-AIPV3-NATS: Received AIP v3 messages are automatically converted to
        legacy format before passing to the callback.
        """
        subject = f"galaxy.tasks.dispatch.{worker_id}"
        wrapped = self._wrap_aip_v3_callback(callback)
        return await self._subscribe(subject, wrapped, durable=f"worker-{worker_id}")

    async def subscribe_task_results(
        self,
        callback: Callable,
        *,
        include_subscription: bool = False,
    ) -> dict:
        """Subscribe to all task results.

        PR-AIPV3-NATS: Received AIP v3 messages are automatically converted to
        legacy format before passing to the callback.
        """
        wrapped = self._wrap_aip_v3_callback(callback)
        return await self._subscribe(
            WorkerLifecycleSubjects.RESULT,
            wrapped,
            durable="brain-results",
            return_subscription=include_subscription,
        )

    async def subscribe_heartbeats(self, callback: Callable) -> dict:
        """Subscribe to worker heartbeats.

        PR-AIPV3-NATS: Received AIP v3 HEARTBEAT messages are automatically
        converted to legacy WorkerHeartbeatModel format.
        """
        wrapped = self._wrap_aip_v3_callback(callback)
        return await self._subscribe(
            WorkerLifecycleSubjects.HEARTBEAT,
            wrapped,
            durable="brain-heartbeats",
        )

    async def subscribe_worker_registrations(self, callback: Callable) -> dict:
        """Subscribe to worker registration lifecycle messages.

        PR-AIPV3-NATS: Received AIP v3 DEVICE_REGISTER messages are automatically
        converted to legacy WorkerRegistrationModel format.
        """
        wrapped = self._wrap_aip_v3_callback(callback)
        return await self._subscribe(
            WorkerLifecycleSubjects.REGISTER,
            wrapped,
            durable="brain-worker-register",
        )

    async def subscribe_worker_shutdowns(self, callback: Callable) -> dict:
        """Subscribe to worker shutdown lifecycle messages.

        PR-AIPV3-NATS: Received AIP v3 messages are automatically converted to
        legacy format before passing to the callback.
        """
        wrapped = self._wrap_aip_v3_callback(callback)
        return await self._subscribe(
            WorkerLifecycleSubjects.SHUTDOWN,
            wrapped,
            durable="brain-worker-shutdown",
        )

    async def subscribe_task_deadletters(self, callback: Callable) -> dict:
        """Subscribe to task dead-letter messages."""
        subject = os.environ.get("GALAXY_GW_ADAPTER_DLQ_SUBJECT", "galaxy.tasks.deadletter")
        return await self._subscribe(subject, callback, durable="brain-task-deadletter")

    async def subscribe_events(self, event_type: str, callback: Callable) -> dict:
        """Subscribe to events of a specific type."""
        subject = f"galaxy.events.{event_type}" if event_type != "*" else "galaxy.events.>"
        return await self._subscribe(subject, callback, durable=f"events-{event_type}")

    async def subscribe_mcp_results(self, callback: Callable) -> dict:
        """Subscribe to MCP call results."""
        return await self._subscribe("galaxy.mcp.results", callback, durable="brain-mcp-results")

    # ── PR-AIPV3-NATS: AIP v3 callback wrapper ──────────────────────────────

    @staticmethod
    def _wrap_aip_v3_callback(callback: Callable) -> Callable:
        """Wrap a callback so AIP v3 messages are auto-converted to legacy format.

        When a subscriber receives an AIP v3 message (has "type" and "_aip_version"),
        it is converted to a flat dict matching the legacy format before being
        passed to the callback. Non-AIP-v3 messages pass through unchanged.

        This ensures all existing consumers work without modification even though
        NATS now transports AIP v3 messages.
        """
        try:
            from core.aip_v3_nats_adapter import from_aip_to_legacy  # noqa: PLC0415
        except Exception:
            # Adapter unavailable — return callback as-is
            return callback

        async def _async_wrapper(data: dict):
            if isinstance(data, dict) and data.get("_aip_version"):
                data = from_aip_to_legacy(data)
            if asyncio.iscoroutinefunction(callback):
                await callback(data)
            else:
                callback(data)

        def _sync_wrapper(data: dict):
            if isinstance(data, dict) and data.get("_aip_version"):
                data = from_aip_to_legacy(data)
            callback(data)

        if asyncio.iscoroutinefunction(callback):
            return _async_wrapper
        return _sync_wrapper

    # ── Health / Stats (constraint C8) ──────────────────────────────────────

    def is_connected(self) -> bool:
        """Check if NATS connection is alive."""
        return self._connected and self._nc is not None and self._nc.is_connected

    def get_stats(self) -> dict:
        """Return bus statistics."""
        subscription_metadata = getattr(self, "_subscription_metadata", {})
        return {
            "connected": self.is_connected(),
            "url": self._url,
            "embedded": self._embedded is not None,
            "subscriptions": len(self._subscriptions),
            "active_subjects": [meta["subject"] for meta in subscription_metadata.values()],
            "canonical_worker_subjects": {
                "register": WorkerLifecycleSubjects.REGISTER,
                "heartbeat": WorkerLifecycleSubjects.HEARTBEAT,
                "shutdown": WorkerLifecycleSubjects.SHUTDOWN,
                "result": WorkerLifecycleSubjects.RESULT,
            },
            **self._stats,
        }

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _ensure_connected(self) -> bool:
        """PR-NATS-CORE: Auto-connect if not connected.

        If NATS is not connected, attempt to connect (which may start
        the embedded server). Returns True if connected, False otherwise.
        """
        if self._connected and self._js is not None:
            return True
        result = await self.connect()
        return result.get("success", False)

    async def _publish(self, subject: str, data: dict) -> dict:
        """Serialize and publish a message to NATS JetStream.

        PR-NATS-CORE: Auto-connects if not connected. No no-op mode.
        """
        # Auto-connect if not connected
        if not self._connected or self._js is None:
            if not await self._ensure_connected():
                return {"success": False, "error": "NATS not available (embedded server failed)"}

        try:
            payload = json.dumps(data, default=str).encode("utf-8")
            ack = await self._js.publish(subject, payload)
            self._stats["published"] += 1
            logger.debug(f"NATSBus: published to {subject} (seq={ack.seq})")
            return {"success": True, "seq": ack.seq}
        except Exception as exc:
            self._stats["errors"] += 1
            logger.error(f"NATSBus: publish failed on {subject} — {exc}")
            return {"success": False, "error": str(exc)}

    async def _subscribe(
        self,
        subject: str,
        callback: Callable,
        durable: str = "",
        *,
        return_subscription: bool = False,
    ) -> dict:
        """Create a JetStream pull/push subscription.

        PR-NATS-CORE: Auto-connects if not connected. No no-op mode.
        """
        # Auto-connect if not connected
        if not self._connected or self._js is None:
            if not await self._ensure_connected():
                return {"success": False, "error": "NATS not available (embedded server failed)"}

        try:
            async def _handler(msg):
                try:
                    data = json.loads(msg.data.decode("utf-8"))
                    self._stats["received"] += 1
                    if asyncio.iscoroutinefunction(callback):
                        await callback(data)
                    else:
                        callback(data)
                    await msg.ack()
                except Exception as exc:
                    logger.error(f"NATSBus: handler error on {subject} — {exc}")
                    self._stats["errors"] += 1

            sub = await self._js.subscribe(
                subject,
                durable=durable if durable else None,
                cb=_handler,
            )
            self._subscriptions.append(sub)
            self._subscription_metadata[id(sub)] = {"subject": subject, "durable": durable}
            logger.info(f"NATSBus: subscribed to {subject} (durable={durable})")
            result = {"success": True, "subject": subject, "durable": durable}
            if return_subscription:
                result["subscription"] = sub
            return result
        except Exception as exc:
            self._stats["errors"] += 1
            logger.error(f"NATSBus: subscribe failed on {subject} — {exc}")
            return {"success": False, "error": str(exc)}

    async def unsubscribe(self, subscription: Any) -> dict:
        """Unsubscribe a tracked subscription and keep internal bookkeeping aligned.

        Accepts ``None`` as a no-op, supports subscription objects whose
        ``unsubscribe`` method is synchronous or async, and removes the
        subscription from the tracked in-memory metadata after cleanup.
        """
        if subscription is None:
            return {"success": True}
        try:
            unsubscribe = getattr(subscription, "unsubscribe", None)
            if callable(unsubscribe):
                result = unsubscribe()
                if asyncio.iscoroutine(result):
                    await result
            if subscription in self._subscriptions:
                self._subscriptions.remove(subscription)
            self._subscription_metadata.pop(id(subscription), None)
            return {"success": True}
        except Exception as exc:
            self._stats["errors"] += 1
            return {"success": False, "error": str(exc)}

    # ── NATS callbacks ──────────────────────────────────────────────────────

    async def _on_reconnect(self) -> None:
        self._stats["reconnects"] += 1
        _try_emit_event("NATS_RECONNECTING", {"reconnects": self._stats["reconnects"]})
        # PR-509: Re-absorb connected state on reconnect so topology runtime
        # reflects the live NATS fabric state after a transient disconnect.
        _absorb_nats_state(is_connected=True)
        logger.warning(f"NATSBus: reconnected (attempt #{self._stats['reconnects']})")

    async def _on_disconnect(self) -> None:
        _try_emit_event("NATS_DISCONNECTED", {})
        # PR-509: Absorb disconnected state on unexpected disconnect.
        _absorb_nats_state(is_connected=False)
        logger.warning("NATSBus: disconnected")

    async def _on_error(self, exc: Exception) -> None:
        self._stats["errors"] += 1
        logger.error(f"NATSBus: error — {exc}")


# ── Module-level singleton (constraint C1) ─────────────────────────────────
nats_bus = NATSBus.get_instance()


def get_nats_bus() -> NATSBus:
    """Return the module-level NATSBus singleton.

    PR-NATS-CORE: All consumers should use this accessor rather than
    constructing NATSBus directly.
    """
    return nats_bus


# ---------------------------------------------------------------------------
# PR-509: Runtime event absorption helper (non-blocking, failure-isolated)
# ---------------------------------------------------------------------------


def _absorb_nats_state(is_connected: bool, url: str = "") -> None:
    """Absorb NATS connectivity state into the canonical NetworkTopologyRuntime.

    PR-509: Called from :meth:`NATSBus.connect`, :meth:`NATSBus.disconnect`,
    :meth:`NATSBus._on_reconnect`, and :meth:`NATSBus._on_disconnect` to keep
    the network topology runtime populated with live NATS fabric state.

    All errors are swallowed so that topology absorption never interrupts
    the NATS connection lifecycle.
    """
    try:
        host = ""
        port = 0
        if url:
            # Use urllib.parse to handle all NATS-supported URL schemes
            # (nats://, tls://, ws://, wss://) robustly.
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if parsed.hostname:
                host = parsed.hostname
            if parsed.port:
                port = parsed.port

        from core.capability_network_runtime_policy import absorb_nats_connectivity_event
        absorb_nats_connectivity_event(is_connected=is_connected, host=host, port=port)
    except Exception:
        pass
