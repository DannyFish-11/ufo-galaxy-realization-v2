"""
Galaxy Agentic OS — NATS JetStream Message Bus
================================================

Wraps ``nats-py`` async client providing typed pub/sub for distributed task
dispatch between the MasterBrain (control plane) and Edge Workers (data plane).

Constraints (see plan 强约束):
  C1  — module-level singleton ``nats_bus``
  C2  — emits events to EventBus (NATS_CONNECTED / DISCONNECTED / RECONNECTING)
  C5  — configured via ``GALAXY_NATS_URL`` env var; no-op mode if not set
  C7  — all methods return ``{"success": bool, "error": str | None, ...}``
  C8  — exposes ``is_connected()`` and ``get_stats()``
  C11 — uses stdlib ``logging`` (matching codebase convention)
  C12 — JSON wire format matching Pydantic model field names (snake_case)
"""

from __future__ import annotations

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


class NATSBus:
    """NATS JetStream client for distributed task dispatch.

    Operates in **no-op mode** when ``GALAXY_NATS_URL`` is not set or when
    the ``nats-py`` package is not installed.  In no-op mode all publish
    calls return immediately and no subscriptions are created.
    """

    _instance: Optional[NATSBus] = None

    def __init__(self) -> None:
        self._url = os.environ.get("GALAXY_NATS_URL", "")
        self._auto_local = False  # True when URL was auto-defaulted to localhost
        if not self._url and _HAS_NATS:
            self._url = "nats://localhost:4222"
            self._auto_local = True
        self._nc: Optional[Any] = None  # NATSClient
        self._js: Optional[Any] = None  # JetStreamContext
        self._connected = False
        self._noop = not self._url or not _HAS_NATS
        self._subscriptions: list = []
        self._stats = {
            "published": 0,
            "received": 0,
            "errors": 0,
            "reconnects": 0,
        }

        if self._noop:
            reason = "nats-py not installed" if not _HAS_NATS else "GALAXY_NATS_URL not set"
            logger.warning(f"NATSBus: operating in no-op mode ({reason})")

    @classmethod
    def get_instance(cls) -> NATSBus:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Connection lifecycle ────────────────────────────────────────────────

    async def connect(self, url: str = "") -> dict:
        """Connect to NATS server and create JetStream streams."""
        if self._noop:
            return {"success": True, "noop": True}
        if self._connected:
            return {"success": True, "already_connected": True}

        target = url or self._url
        try:
            self._nc = await nats.connect(
                target,
                reconnected_cb=self._on_reconnect,
                disconnected_cb=self._on_disconnect,
                error_cb=self._on_error,
                # Auto-local default: fail fast on first attempt so we don't
                # spam errors in a tight reconnect loop before switching to
                # no-op.  Explicit GALAXY_NATS_URL keeps unlimited retries.
                max_reconnect_attempts=0 if self._auto_local else -1,
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
            logger.info(f"NATSBus: connected to {target}")
            return {"success": True}

        except Exception as exc:
            self._stats["errors"] += 1
            if self._auto_local:
                # Auto-local default failed — fall back to no-op gracefully.
                self._noop = True
                lan_ip = _get_lan_ip()
                hint = (
                    f" For cross-device support set: GALAXY_NATS_URL=nats://{lan_ip}:4222"
                    if lan_ip
                    else " Set GALAXY_NATS_URL=nats://<LAN_IP>:4222 for cross-device support."
                )
                logger.warning(
                    "NATSBus: could not reach nats://localhost:4222 — running in no-op mode "
                    "(single-machine). To enable NATS locally: nats-server -p 4222.%s",
                    hint,
                )
                return {"success": True, "noop": True, "auto_local_failed": True}
            logger.error(f"NATSBus: connection failed — {exc}")
            return {"success": False, "error": str(exc)}

    async def disconnect(self) -> dict:
        """Gracefully close NATS connection."""
        if self._noop or not self._connected:
            return {"success": True}
        try:
            for sub in self._subscriptions:
                try:
                    await sub.unsubscribe()
                except Exception:
                    pass
            self._subscriptions.clear()
            await self._nc.drain()
            self._connected = False
            logger.info("NATSBus: disconnected")
            return {"success": True}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ── Publish methods ─────────────────────────────────────────────────────

    async def publish_task_dispatch(self, worker_id: str, task: TaskDispatchModel) -> dict:
        """Publish TaskDispatch to ``galaxy.tasks.dispatch.{worker_id}``."""
        subject = f"galaxy.tasks.dispatch.{worker_id}"
        return await self._publish(subject, task.model_dump(mode="json", exclude_none=True))

    async def publish_task_result(self, task_id: str, result: TaskResultModel) -> dict:
        """Publish TaskResult to ``galaxy.tasks.result.{task_id}``."""
        subject = f"galaxy.tasks.result.{task_id}"
        return await self._publish(subject, result.model_dump(mode="json", exclude_none=True))

    async def publish_heartbeat(self, heartbeat: WorkerHeartbeatModel) -> dict:
        """Publish heartbeat to ``galaxy.workers.heartbeat``."""
        return await self._publish(
            "galaxy.workers.heartbeat",
            heartbeat.model_dump(mode="json", exclude_none=True),
        )

    async def publish_event(self, event: AgentEventModel) -> dict:
        """Publish event to ``galaxy.events.{event_type}``."""
        subject = f"galaxy.events.{event.event_type}"
        return await self._publish(subject, event.model_dump(mode="json", exclude_none=True))

    async def publish_mcp_call(self, request: MCPCallRequestModel) -> dict:
        """Publish MCP call to ``galaxy.mcp.calls``."""
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
    ) -> dict:
        """Ensure *data* carries trace_id, runtime_session_id, and remote_execution_mode.

        This method is the NATS-layer equivalent of
        :func:`~galaxy_gateway.protocol.compat.inject_trace_metadata`
        and enforces the PR-2 unified envelope contract on every published
        message.

        PR-7: ``remote_execution_mode`` is propagated alongside trace fields so
        that both ``command_only`` and ``agent_runtime`` dispatches carry the
        same substrate metadata through the NATS transport layer.
        """
        import uuid as _uuid_lib
        out = dict(data)
        if not out.get("trace_id"):
            out["trace_id"] = trace_id or f"trace_{_uuid_lib.uuid4().hex[:12]}"
        if not out.get("runtime_session_id"):
            out["runtime_session_id"] = runtime_session_id or f"session_{_uuid_lib.uuid4().hex[:12]}"
        if remote_execution_mode and not out.get("remote_execution_mode"):
            out["remote_execution_mode"] = remote_execution_mode
        return out

    async def publish_task_event(
        self,
        topic_suffix: str,
        data: dict,
        *,
        trace_id: str = "",
        runtime_session_id: str = "",
        remote_execution_mode: str = "",
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
        """
        payload = self._ensure_trace_fields(
            data, trace_id, runtime_session_id, remote_execution_mode
        )
        payload["_nats_schema"] = "UnifiedTaskEvent"
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
        """Subscribe to task dispatches for a specific worker."""
        subject = f"galaxy.tasks.dispatch.{worker_id}"
        return await self._subscribe(subject, callback, durable=f"worker-{worker_id}")

    async def subscribe_task_results(self, callback: Callable) -> dict:
        """Subscribe to all task results."""
        return await self._subscribe("galaxy.tasks.result.*", callback, durable="brain-results")

    async def subscribe_heartbeats(self, callback: Callable) -> dict:
        """Subscribe to worker heartbeats."""
        return await self._subscribe("galaxy.workers.heartbeat", callback, durable="brain-heartbeats")

    async def subscribe_events(self, event_type: str, callback: Callable) -> dict:
        """Subscribe to events of a specific type."""
        subject = f"galaxy.events.{event_type}" if event_type != "*" else "galaxy.events.>"
        return await self._subscribe(subject, callback, durable=f"events-{event_type}")

    async def subscribe_mcp_results(self, callback: Callable) -> dict:
        """Subscribe to MCP call results."""
        return await self._subscribe("galaxy.mcp.results", callback, durable="brain-mcp-results")

    # ── Health / Stats (constraint C8) ──────────────────────────────────────

    def is_connected(self) -> bool:
        """Check if NATS connection is alive."""
        if self._noop:
            return False
        return self._connected and self._nc is not None and self._nc.is_connected

    def get_stats(self) -> dict:
        """Return bus statistics."""
        return {
            "connected": self.is_connected(),
            "noop_mode": self._noop,
            "url": self._url,
            "subscriptions": len(self._subscriptions),
            **self._stats,
        }

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _publish(self, subject: str, data: dict) -> dict:
        """Serialize and publish a message to NATS JetStream."""
        if self._noop:
            # Bridge to in-process EventBus so subscribers still receive messages
            try:
                from integration.event_bus import EventBus, EventType
                bus = EventBus()
                # Use a generic event type; include NATS subject for routing
                et = getattr(EventType, "NATS_FALLBACK", None) or EventType.COMMAND_DISPATCHED
                bus.publish_sync(
                    et,
                    source="nats_bus",
                    data={"subject": subject, "payload": data},
                )
            except Exception:
                pass
            return {"success": True, "noop": True}
        if not self._connected or self._js is None:
            return {"success": False, "error": "Not connected to NATS"}

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
        self, subject: str, callback: Callable, durable: str = ""
    ) -> dict:
        """Create a JetStream pull/push subscription."""
        if self._noop:
            return {"success": True, "noop": True}
        if not self._connected or self._js is None:
            return {"success": False, "error": "Not connected to NATS"}

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
            logger.info(f"NATSBus: subscribed to {subject} (durable={durable})")
            return {"success": True}
        except Exception as exc:
            self._stats["errors"] += 1
            logger.error(f"NATSBus: subscribe failed on {subject} — {exc}")
            return {"success": False, "error": str(exc)}

    # ── NATS callbacks ──────────────────────────────────────────────────────

    async def _on_reconnect(self) -> None:
        self._stats["reconnects"] += 1
        _try_emit_event("NATS_RECONNECTING", {"reconnects": self._stats["reconnects"]})
        logger.warning(f"NATSBus: reconnected (attempt #{self._stats['reconnects']})")

    async def _on_disconnect(self) -> None:
        _try_emit_event("NATS_DISCONNECTED", {})
        logger.warning("NATSBus: disconnected")

    async def _on_error(self, exc: Exception) -> None:
        self._stats["errors"] += 1
        logger.error(f"NATSBus: error — {exc}")


# ── Module-level singleton (constraint C1) ─────────────────────────────────
nats_bus = NATSBus.get_instance()
