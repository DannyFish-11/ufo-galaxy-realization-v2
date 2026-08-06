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

Layer identity (原引自 core.agent_bus_fabric —— 该声明模块已删，语义保留于此):
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
NETWORK_TOPOLOGY_RUNTIME_INTEGRATED: str = "NATS_BUS::NETWORK_TOPOLOGY_RUNTIME_INTEGRATED_V1"

# PR-509: Capability + Network Runtime Assimilation integration sentinel.
# Affirms that NATSBus.connect() and .disconnect() now call
# absorb_nats_connectivity_event() so that NATS fabric state is reliably
# populated in the canonical NetworkTopologyRuntime on every connection
# lifecycle change.
CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED: str = (
    "NATS_BUS::CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED_V1"
)

import asyncio  # noqa: E402  哨兵权威声明置顶是本仓设计习语
import json  # noqa: E402  哨兵权威声明置顶是本仓设计习语
import logging  # noqa: E402  哨兵权威声明置顶是本仓设计习语
import os  # noqa: E402  哨兵权威声明置顶是本仓设计习语
import socket  # noqa: E402  哨兵权威声明置顶是本仓设计习语
from typing import Any, Callable, Dict, Optional  # noqa: E402  哨兵权威声明置顶是本仓设计习语

logger = logging.getLogger("nats_bus")

# PR-AIPV3-NATS: Unified AIP v3 models — NATS transports canonical AIP v3 messages
from core.schemas.aip_v3 import (  # noqa: E402  哨兵权威声明置顶是本仓设计习语
    AckMsg,
    AIPMessage,
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
    WebRTCTransportStateMsg,
    WebRTCUnbindMsg,
)
from core.schemas.contracts import (  # noqa: E402  哨兵权威声明置顶是本仓设计习语
    AgentEventModel,
    MCPCallRequestModel,
    TaskDispatchModel,
    TaskResultModel,
    WorkerHeartbeatModel,
    WorkerRegistrationModel,
    WorkerShutdownModel,
)

# GALAXY_NATS_URL 是**带凭据的**:nats.connect(target, ...) 没有传任何 user/password/token
# 参数,也就是说本仓库里 NATS 鉴权只能靠 nats://user:pass@host:4222 这种 URL 内嵌形式。
# 所以任何把它原样打进日志的地方都是明文泄露 —— 一律先过 safe_endpoint 只留 host:port。
from core.url_redaction import safe_endpoint  # noqa: E402

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
        from integration.event_bus import EventType, event_bus

        et = getattr(EventType, event_type_name, None)
        if et is not None:
            event_bus.publish_sync(et, "agentic_os", data)
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)


# ═══════════════════════════════════════════════════════════════════════════════
# 主题与流定义 —— 见 core/nats_subjects.py
# ═══════════════════════════════════════════════════════════════════════════════
#
# 拆出去的是**名字**,不是行为。理由写在那个模块的开头:这一层踩过两次
# 「同一个主题被定义了两次」(单复数分裂、网关自己拼主题),名字有独立的家之后,
# 「这个主题在哪定义的」才是个只有一个答案的问题。
#
# 这里 re-export 是为了不动既有的 `from core.nats_bus import NATSTopics` 之类的
# 导入 —— 拆分不该顺带变成一次全仓改名。
from core.nats_subjects import (  # noqa: E402,F401  哨兵权威声明置顶是本仓设计习语
    _STREAMS,
    NATSTopics,
    WorkerLifecycleSubjects,
)


def _envelope_payload(envelope: Any) -> Dict[str, Any]:
    """把 envelope 归一成可发布的 dict —— pydantic 模型或已经是 dict 都收。

    为什么要收 dict
    ---------------
    真实的生产者不一定手上有 pydantic 模型。``GatewayNATSAdapter._publish_result``
    就是自己拼一个"legacy 字段 + TaskEnvelope 判别器"的 dict —— 它拼得完全正确,
    却因为这两个发布器只认 ``.model_dump()``,只能绕过它们直接调**私有的**
    ``nats_bus._publish``。结果是:主题、判别器、trace 字段这几件事在网关里
    各拼一遍,发布器这边改了主题(比如 C7 那次任务平面收敛到单数),网关那边
    不会跟着变 —— 两处各自为政,正是漂移的温床。

    收 dict 之后网关走公开发布器,主题只有这一处定义。
    """
    if hasattr(envelope, "model_dump"):
        return envelope.model_dump(mode="json", exclude_none=True)
    if isinstance(envelope, dict):
        return dict(envelope)
    raise TypeError(f"envelope 必须是 pydantic 模型或 dict,收到 {type(envelope).__name__}")


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
        self._noop = False  # test/conformance no-op mode: publish succeeds without NATS
        # 进程内降级总线(所有者 Windows 真机 WinError 4551 实证):nats-server 被
        # 智能应用控制/WDAC 拦截、或未安装且自动安装失败时,不能让"总线整个失效"
        # ——单机场景里发布者和订阅者本来就在同一进程,纯 Python 内存分发即可
        # 保住全部单机语义(此前每次 publish 都反复触发 auto-connect 重试并失败)。
        # _local_mode=True 后 publish/subscribe 走 _local_subs 内存匹配分发,
        # 不再碰网络;仅跨设备分发不可用,由启动横幅如实展示。
        self._local_mode = False
        self._local_reason = ""
        self._local_subs: list = []  # [(subject_pattern, callback), ...]
        self._embedded: Optional[Any] = None  # EmbeddedNATSServer instance
        self._subscriptions: list = []
        self._subscription_metadata: Dict[int, Dict[str, str]] = {}
        self._stats = {
            "published": 0,
            "received": 0,
            "errors": 0,
            "reconnects": 0,
        }

        # PR-28: Auto-detect Tailscale IP for cross-device NATS connectivity
        if not self._url:
            ts_url = self._detect_tailscale_nats_url()
            if ts_url:
                self._url = ts_url
                self._auto_local = True
                logger.info("NATSBus: auto-configured Tailscale URL: %s", safe_endpoint(ts_url))
            elif _HAS_NATS:
                self._url = "nats://localhost:4222"
                self._auto_local = True
            else:
                logger.warning("NATSBus: nats-py not installed. " "Install: pip install nats-py[nats]")

    # PR-28: Tailscale auto-detection for cross-device NATS
    @staticmethod
    def _detect_tailscale_nats_url() -> str:
        """Detect if Tailscale is available and return NATS URL using Tailscale IP.

        Returns nats://<tailscale-ip>:4222 if Tailscale is running,
        empty string otherwise.
        """
        import shutil
        import subprocess

        if not shutil.which("tailscale"):
            return ""

        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            if result.returncode == 0:
                import json

                status = json.loads(result.stdout)
                ts_ips = status.get("Self", {}).get("TailscaleIPs", [])
                if ts_ips:
                    return f"nats://{ts_ips[0]}:4222"
        except Exception:
            pass
        return ""

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

        # 已切进程内降级总线:不再尝试网络连接/拉起 embedded server(避免每个
        # 后来的调用方都重演一遍注定失败的启动 + 刷错);内存总线即"可用"。
        if getattr(self, "_local_mode", False):
            return {"success": True, "local": True, "reason": self._local_reason}

        # 显式关闭跨设备总线时,直接切进程内总线,不连网、更不拉起内置服务器。
        # 此前这个开关只有 unified_launcher 认;任何绕过启动器的调用方(HTTP 端点、
        # 后台任务、测试)照样会走完自动安装 + 拉起常驻进程的链路。见
        # core.nats_server.nats_disabled_by_config 的说明。
        from core.nats_server import nats_disabled_by_config

        if nats_disabled_by_config():
            self.enable_local_fallback("GALAXY_NATS_ENABLED=false(按配置显式关闭)")
            return {"success": True, "local": True, "reason": self._local_reason}

        target = url or self._url

        # PR-NATS-CORE: If no URL configured, try to start embedded server
        if not target and not self._embedded:
            from core.nats_server import EmbeddedNATSServer

            self._embedded = EmbeddedNATSServer()
            if await self._embedded.start():
                target = os.environ.get("GALAXY_NATS_URL", "nats://localhost:4222")
                self._url = target
                self._auto_local = False
                logger.info("NATSBus: using embedded NATS server at %s", safe_endpoint(target))
            else:
                logger.error("NATSBus: embedded NATS server failed to start")
                # 启动失败也是「中心不在」—— 必须进链路观测器,否则分区可见化
                # 恰好漏掉最重要的一种情况:中心从一开始就没起来。
                _absorb_nats_state(is_connected=False)
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

            # Ensure JetStream streams exist **and cover every configured subject**.
            #
            # 此前这里只有"不存在就建"一条路:流一旦建起来,后来往 _STREAMS 里加的
            # 前缀就永远进不去。新前缀在全新部署上生效、在已跑的部署上静默失效,
            # 是最难查的一类不一致 —— 同一份代码两种行为。
            #
            # 往流里**加** subject 是安全操作(删才危险),所以这里只做并集,
            # 绝不移除已有 subject:线上可能还有消费者挂在上面。
            await self._ensure_streams()

            self._connected = True
            _try_emit_event("NATS_CONNECTED", {"url": target})
            # PR-509: Absorb NATS connectivity state into the canonical
            # NetworkTopologyRuntime so that topology consumers see a live
            # NATS fabric node.
            _absorb_nats_state(is_connected=True, url=target)
            logger.info(f"NATSBus: connected to {target}")
            return {"success": True}

        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
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
                _absorb_nats_state(is_connected=False)
                return {"success": False, "error": f"NATS connection failed: {exc}"}
            logger.error(f"NATSBus: connection failed — {exc}")
            _absorb_nats_state(is_connected=False)
            return {"success": False, "error": str(exc)}

    async def disconnect(self) -> dict:
        """Gracefully close NATS connection and stop embedded server if running."""
        if not self._connected:
            return {"success": True}
        try:
            for sub in list(self._subscriptions):
                try:
                    await sub.unsubscribe()
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)
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
        """Publish a canonical AIP v3 message to NATS JetStream.

        PR-AIP-UNIFIED: NATS is a task distribution layer, NOT a transport layer.
        NATS messages go directly to JetStream, NOT through AIPTransport.
        AIPTransport handles physical transports (WS/MQTT/BLE/TCP/UDP/Serial).
        NATS handles logical pub/sub for task dispatch and mesh state sync.

        Args:
            subject: NATS subject (e.g. "galaxy.task.dispatch.worker_01")
            aip_message: An AIPMessage subclass instance

        Returns:
            {"success": bool, "seq": int} or {"success": False, "error": str}
        """
        data = aip_message.model_dump(mode="json", exclude_none=True)
        # Mark internal transport hint for tracing (not used by AIPTransport)
        data["_transport"] = "nats"

        # NATS is independent layer — direct JetStream publish
        # Do NOT route through AIPTransport (no "nats" adapter registered)
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
        """Publish HEARTBEAT to ``galaxy.device.heartbeat.{device_id}``.

        Accepts both device-style heartbeats (``device_id``) and worker-style
        ``WorkerHeartbeatModel`` heartbeats (``worker_id``).
        """
        source_id = getattr(heartbeat, "device_id", "") or getattr(heartbeat, "worker_id", "")
        subject = NATSTopics.device_heartbeat(source_id)
        return await self.publish_aip_v3(subject, heartbeat)

    async def publish_heartbeat_ack(self, ack: "HeartbeatAckMsg") -> dict:
        """Publish HEARTBEAT_ACK back to device."""
        return await self.publish_aip_v3(f"galaxy.device.heartbeat_ack.{ack.device_id}", ack)

    async def publish_capability_report(self, msg: "CapabilityReportMsg") -> dict:
        """Publish CAPABILITY_REPORT to ``galaxy.capability.registered``.

        Announces device capabilities to the system.
        """
        return await self.publish_aip_v3(NATSTopics.CAPABILITY_REGISTERED, msg)

    async def publish_capability_query(self, msg: "CapabilityQueryMsg") -> dict:
        """Publish CAPABILITY_QUERY to ``galaxy.capability.query``.

        Asks the mesh which devices provide a capability.  Replies come back
        as CAPABILITY_REPORT on ``galaxy.capability.registered``.
        """
        return await self.publish_aip_v3(NATSTopics.CAPABILITY_QUERY, msg)

    # ── Task / execution ──

    async def publish_task_assign(self, msg: "TaskAssignMsg") -> dict:
        """Publish TASK_ASSIGN to ``galaxy.task.dispatch.{device_id}``."""
        subject = NATSTopics.task_dispatch(msg.device_id)
        return await self.publish_aip_v3(subject, msg)

    async def publish_task_result(self, msg: "TaskResultMsg") -> dict:
        """Publish TASK_RESULT to ``galaxy.task.result.{task_id}``."""
        subject = NATSTopics.task_result(msg.task_id or msg.device_id)
        return await self.publish_aip_v3(subject, msg)

    async def publish_task_cancel(self, msg: "TaskCancelMsg") -> dict:
        """Publish TASK_CANCEL to ``galaxy.task.cancel.{task_id}``."""
        return await self.publish_aip_v3(f"{NATSTopics.TASK_CANCEL}.{msg.task_id}", msg)

    async def publish_cancel_result(self, msg: "CancelResultMsg") -> dict:
        """Publish CANCEL_RESULT to ``galaxy.task.cancel_result.{task_id}``.

        The reply half of :meth:`publish_task_cancel` — tells the requester
        whether the cancellation actually took, and how clean the teardown was.
        """
        return await self.publish_aip_v3(f"{NATSTopics.TASK_CANCEL_RESULT}.{msg.task_id}", msg)

    async def publish_goal_execution(self, msg: "GoalExecutionMsg") -> dict:
        """Publish GOAL_EXECUTION to ``galaxy.task.dispatch.{device_id}``."""
        subject = NATSTopics.task_dispatch(msg.device_id)
        return await self.publish_aip_v3(subject, msg)

    async def publish_goal_result(self, msg: "GoalExecutionResultMsg") -> dict:
        """Publish GOAL_EXECUTION_RESULT to ``galaxy.task.result.{task_id}``."""
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
    #
    # 例外:worker 生命周期那三条(register / heartbeat / shutdown)**不转**。
    # ────────────────────────────────────────────────────────────────────
    # 这里其实是两个平面,不是一个平面的新旧两版:
    #
    #   galaxy.device.*   设备协议平面,载 AIP v3 消息类,对端是各种设备;
    #   galaxy.workers.*  MasterBrain ↔ Edge Worker 平面,载 contracts.py 的
    #                     WorkerHeartbeatModel / WorkerRegistrationModel …
    #
    # 这三条原先先转成 AIP v3、再调设备平面的 publish_device_* —— 于是消息落到
    # galaxy.device.*,而 MasterBrain 的 subscribe_worker_* 在 galaxy.workers.*
    # 上等,两端根本不在一个主题上。
    #
    # 而它们当时看起来"是好的",是因为转换**恰好抛异常**:WorkerHeartbeatModel
    # 的 timestamp 序列化成 {seconds, nanos} 而 HeartbeatMsg.timestamp 要 int;
    # WorkerRegistrationModel 的 capabilities 是对象列表而 DeviceRegisterMsg 要
    # 字符串列表。异常把它们打进 except 分支,原样发去了 galaxy.workers.* ——
    # 对的结果,错的理由。三条里唯一转换会成功的 shutdown,就是真的断的那条。
    #
    # 反方向同样是坏的:from_aip_to_legacy 还原出来的 timestamp 是 int,
    # WorkerHeartbeatModel.model_validate 照样不认(见
    # tests/test_worker_lifecycle_subjects.py 里钉住的那条)。
    #
    # 所以正确做法不是"把转换修好",是**别转**:worker 平面的消息发到 worker
    # 平面,格式就是消费方认的那个。

    # ── 关于本节里"全仓没有调用方"的那几个发布器 ──────────────────────────
    #
    # 接线守卫(scripts/check_wiring.py)会把它们记进基线。逐条查过之后,结论
    # 不是"忘了接",各有各的理由,写在这里省得下一个人再查一遍:
    #
    #   publish_task_event / publish_device_event / publish_capability_event
    #       —— 这三个是**带 trace 传播的通用入口**,由 tests/conformance/
    #       test_nats_trace.py 钉住(subject 前缀 + _nats_schema + trace 字段),
    #       publish_task_event 还额外承载 PR-7 的 remote_execution_mode 与
    #       PR-12 的 lifecycle_state。它们指向的三个命名空间**已经由带类型的
    #       AIP v3 发布器占着**(publish_device_register / publish_task_assign /
    #       publish_capability_report …),消费方按 AIP v3 消息类解析。往这些主题
    #       上再灌无类型 dict 不是"接线",是往消费方嘴里塞它不认识的东西。
    #       保留:它们是契约面(远端/跨仓生产者要对齐的形状),不是待接的能力。
    #
    #   publish_task_envelope
    #       —— 派发方向的 TaskEnvelope。消费侧是活的:
    #       GatewayNATSAdapter 那条 `_nats_schema == "TaskEnvelope"` 分支。
    #       本仓的派发方手上拿的是 TaskDispatchModel(走 publish_task_dispatch,
    #       3 处生产调用)或本地 CommandRouter.route_envelope,没有"有 envelope
    #       且要发去远端"的路径。这是给**别的仓/别的设备**留的入口。
    #
    #   publish_legacy_task_result
    #       —— 结果方向的 legacy 半边。本仓生产代码**从不构造 TaskResultModel**:
    #       结果要么是 AIP v3 的 TaskResultMsg(worker_runtime / swarm_coordinator /
    #       task_graph / node_invocation 四处),要么是网关那个 envelope dict。
    #       它与 publish_task_dispatch(legacy,有 3 处调用)是对称的一对,
    #       MasterBrain 侧的 ACL.validate_task_result 也确实收 legacy 形状 ——
    #       删掉就是把一对里的一半拆了。保留,理由记在这。
    #
    # 反例(同一节里真的断了、已修的):publish_task_result_envelope 曾经也是
    # "零调用方",但它的生产者其实一直存在 —— 网关自己拼主题、绕过它直接调私有
    # 的 _publish。那不是"用不上",是**接错了**,已改回走发布器。
    # 判据是"有没有真实生产者",不是"有没有人调过"。

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
            subject = NATSTopics.task_dispatch(worker_id)
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
            subject = NATSTopics.task_result(task_id)
            return await self._publish(subject, result.model_dump(mode="json", exclude_none=True))

    async def publish_legacy_heartbeat(self, heartbeat: WorkerHeartbeatModel) -> dict:
        """Publish a worker heartbeat to ``galaxy.workers.heartbeat``.

        见本节开头「两个平面」的说明:worker 心跳走 worker 平面,不转 AIP v3、
        不走设备平面的 :meth:`publish_heartbeat`。
        """
        return await self._publish(
            WorkerLifecycleSubjects.HEARTBEAT,
            heartbeat.model_dump(mode="json", exclude_none=True),
        )

    async def publish_legacy_worker_registration(self, registration: WorkerRegistrationModel) -> dict:
        """Publish a worker registration to ``galaxy.workers.register``。"""
        return await self._publish(
            WorkerLifecycleSubjects.REGISTER,
            registration.model_dump(mode="json", exclude_none=True),
        )

    async def publish_legacy_worker_shutdown(self, shutdown: WorkerShutdownModel) -> dict:
        """Publish a worker shutdown to ``galaxy.workers.shutdown``。

        这条此前是**真的断的**:它的 AIP v3 转换是三条里唯一会成功的,于是消息被
        发去了设备平面的 ``galaxy.device.register``,而 MasterBrain 在
        ``galaxy.workers.shutdown`` 上等 —— 它永远等不到,只能靠心跳超时把 worker
        判死、再把它手上的在途任务标成 ``worker_lost``。干净下线与崩溃从此不可区分。
        """
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

    async def publish_mcp_result(self, response: Any) -> dict:
        """Publish an MCPCallResponse to ``galaxy.mcp.results``.

        回程的那一半。修之前 ``galaxy.mcp.results`` 只有 :meth:`subscribe_mcp_results`
        这个订阅器、**没有任何发布方** —— 与 ``galaxy.mcp.calls`` 只有发布器没有
        订阅方正好对称,契约(contracts/proto/galaxy/v1/mcp.proto)里写的那个
        Brain ↔ MCP Gateway 回路两头都断着,一次也没跑通过。
        """
        return await self._publish(
            "galaxy.mcp.results",
            response.model_dump(mode="json", exclude_none=True),
        )

    async def publish_task_envelope(self, target: str, envelope: Any) -> dict:
        """Publish a TaskEnvelope to ``galaxy.task.dispatch.{target}``.

        PR-3: TaskEnvelope is the primary NATS transport format.  The
        ``_nats_schema`` discriminator field allows subscribers to detect and
        parse the envelope format before falling back to legacy TaskDispatch.

        主题由 :meth:`NATSTopics.task_dispatch` 唯一决定(C7 之后是单数
        ``galaxy.task.*``);订阅侧 :meth:`subscribe_task_dispatches` 单复数都收。
        """
        subject = NATSTopics.task_dispatch(target)
        data = _envelope_payload(envelope)
        data["_nats_schema"] = "TaskEnvelope"
        return await self._publish(subject, data)

    async def publish_task_result_envelope(self, task_id: str, envelope: Any) -> dict:
        """Publish a TaskEnvelope-shaped result to ``galaxy.task.result.{task_id}``.

        PR-3: Publishes a unified result payload that carries both the legacy
        ``status`` field (for backward-compatible consumers) and a full
        TaskEnvelope representation.

        消费侧 ``NATSExecutor._on_task_result`` 早就写好了
        ``_nats_schema == "TaskEnvelope"`` 那条分支(从 metadata 里读
        success/result/error),但在这个发布器有真实调用方之前,那条分支是死的 ——
        网关虽然发的是同一个形状,却绕过发布器直接调私有 ``_publish``。
        """
        subject = NATSTopics.task_result(task_id)
        data = _envelope_payload(envelope)
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
        payload = self._ensure_trace_fields(data, trace_id, runtime_session_id, remote_execution_mode)
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

    async def subscribe(self, subject: str, callback: Callable, durable: str = "") -> dict:
        """订阅任意主题 —— 给总线之外的调用方用的公开入口。

        为什么补这个方法
        ----------------
        ``galaxy_gateway/gateway_nats_adapter.py`` 一直在调 ``nats_bus.subscribe(...)``,
        而 NATSBus 上**从来没有**这个方法:调用抛 AttributeError,被 ``start()`` 外面
        那个 ``except Exception`` 吞成一行日志,``self._started`` 保持 False ——
        网关适配器从此静默地不工作,派给 ``gateway`` 的任务一条也收不到。

        实测:``await GatewayNATSAdapter().start()`` 之后 ``_started`` 恒为 False,
        被吞掉的异常是 ``AttributeError: 'NATSBus' object has no attribute 'subscribe'``。

        总线内部用 ``_subscribe``;跨模块调用方用这个。名字带下划线的私有方法不该
        成为外部契约 —— 那正是这次能静默这么久的原因之一。
        """
        return await self._subscribe(subject, callback, durable=durable)

    async def subscribe_task_dispatches(self, worker_id: str, callback: Callable) -> dict:
        """Subscribe to task dispatches for *worker_id* —— 单复数两个前缀都收。

        见 :data:`_STREAMS` 的说明:``NATSTopics.task_dispatch()`` 走单数,而
        ``publish_task_dispatch`` / ``publish_task_envelope`` / 网关适配器走复数。
        只订一个前缀就会漏掉另一半 —— 修复前这里只订复数,于是
        ``publish_task_assign`` / ``publish_goal_execution`` 派出去的任务
        **一条也到不了 worker**。
        """
        wrapped = self._wrap_aip_v3_callback(callback)
        return await self._subscribe_both(
            f"galaxy.tasks.dispatch.{worker_id}",
            f"{NATSTopics.TASK_DISPATCH}.{worker_id}",
            wrapped,
            durable=f"worker-{worker_id}",
        )

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
        return await self._subscribe_both(
            WorkerLifecycleSubjects.RESULT,
            f"{NATSTopics.TASK_RESULT}.*",
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
        """Subscribe to task dead-letter messages —— 单复数两个主题都收。

        死信是最后一道网,漏在这里等于任务失败了都没人知道。网关适配器是**独立
        进程**,可能与本进程不同版本 —— 灰度期间两边默认值不一致,死信就会掉进
        没人听的主题。所以两个都订,直到迁移收尾。
        """
        override = os.environ.get("GALAXY_GW_ADAPTER_DLQ_SUBJECT", "")
        if override:
            # 显式配置过就只认它 —— 运维指定了主题,不该再自作主张多订一个。
            return await self._subscribe(override, callback, durable="brain-task-deadletter")
        return await self._subscribe_both(
            "galaxy.tasks.deadletter",
            NATSTopics.TASK_DEADLETTER,
            callback,
            durable="brain-task-deadletter",
        )

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

        When a subscriber receives an AIP v3 message (has "type" and "aip_version"),
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
            if isinstance(data, dict) and data.get("aip_version"):
                data = from_aip_to_legacy(data)
            if asyncio.iscoroutinefunction(callback):
                await callback(data)
            else:
                callback(data)

        def _sync_wrapper(data: dict):
            if isinstance(data, dict) and data.get("aip_version"):
                data = from_aip_to_legacy(data)
            callback(data)

        if asyncio.iscoroutinefunction(callback):
            return _async_wrapper
        return _sync_wrapper

    # ── Health / Stats (constraint C8) ──────────────────────────────────────

    def is_connected(self) -> bool:
        """Check if NATS connection is alive."""
        return self._connected and self._nc is not None and self._nc.is_connected

    # ── 进程内降级总线(单机模式) ────────────────────────────────────────────
    # 根因(所有者 Windows 真机日志):nats-server.exe 被智能应用控制(WinError
    # 4551)拦截/未安装时,旧行为是每次 publish/subscribe 都再走一遍
    # auto-connect → 再启一次注定失败的 embedded server → 刷错误日志,
    # 且单机内的消息也全部丢失。启用本模式后改为纯 Python 内存 pub/sub:
    # 单机语义完整保留(同进程内订阅者照常收到消息),零网络、零重试刷屏。

    def enable_local_fallback(self, reason: str = "") -> None:
        """切换到进程内内存总线(诚实降级:单机正常,跨设备分发不可用)。"""
        # getattr 防御:既有测试用 __new__ 绕过 __init__ 构造 NATSBus,
        # 新增属性可能不存在——按未启用处理并补建,不让旧测试路径炸 AttributeError。
        if not getattr(self, "_local_mode", False):
            self._local_mode = True
            self._local_reason = reason or "NATS 不可用"
            if not hasattr(self, "_local_subs"):
                self._local_subs = []
            logger.info("NATSBus: 已切换进程内总线(单机模式正常)— %s", self._local_reason)

    def is_local_mode(self) -> bool:
        """当前是否运行在进程内降级总线上。"""
        return bool(getattr(self, "_local_mode", False))

    def is_usable(self) -> bool:
        """总线现在**能不能用** —— 这才是"要不要发/要不要订"该问的那个问题。

        与 :meth:`is_connected` 的区别
        ------------------------------
        ``is_connected()`` 判的是**网络**连接(``self._nc is not None and
        self._nc.is_connected``),用于状态上报是对的。但拿它当闸门就错了:
        进程内降级总线下它恒为 False,而那条总线是完全可用的 —— 本地降级的
        全部意义正是"单机语义完整保留:同进程内订阅者照常收到消息"。

        这个区别不是理论问题。全仓有二十多处 ``if nats.is_connected():`` 形式的
        闸门,单机模式下它们**全部静默跳过** —— 心跳不发、任务不派、结果不回、
        网格事件不广播,而日志里什么异常都没有,因为那不是异常,是 if 判 False。
        单机跑起来看着一切正常,实际上整条 NATS 依赖面是黑的。

        所以:**上报状态用 is_connected(),决定要不要走总线用 is_usable()。**
        """
        return self.is_connected() or self.is_local_mode()

    @staticmethod
    def _subject_matches(pattern: str, subject: str) -> bool:
        """NATS 通配符匹配:``*`` 匹配单个 token,``>`` 匹配其后全部 token。"""
        p_tokens = pattern.split(".")
        s_tokens = subject.split(".")
        for i, pt in enumerate(p_tokens):
            if pt == ">":
                return len(s_tokens) >= i  # ">" 吞掉剩余全部(至少 0 个)
            if i >= len(s_tokens):
                return False
            if pt != "*" and pt != s_tokens[i]:
                return False
        return len(p_tokens) == len(s_tokens)

    def _local_publish(self, subject: str, data: dict) -> dict:
        """内存分发:把消息投给所有匹配的本进程订阅者(与 NATS 回调同签名)。"""
        delivered = 0
        for pattern, cb in list(self._local_subs):
            if not self._subject_matches(pattern, subject):
                continue
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.get_running_loop().create_task(cb(data))
                else:
                    cb(data)
                delivered += 1
                self._stats["received"] += 1
            except RuntimeError:
                # 无运行中事件循环(同步上下文)→ 只投同步回调,协程回调丢弃并计错
                self._stats["errors"] += 1
            except Exception as exc:  # noqa: BLE001
                self._stats["errors"] += 1
                logger.debug("NATSBus(local): handler error on %s — %s", subject, exc)
        self._stats["published"] += 1
        return {"success": True, "seq": 0, "local": True, "delivered": delivered}

    def get_stats(self) -> dict:
        """Return bus statistics."""
        subscription_metadata = getattr(self, "_subscription_metadata", {})
        return {
            "connected": self.is_connected(),
            "noop_mode": bool(getattr(self, "_noop", False)),
            "local_mode": bool(getattr(self, "_local_mode", False)),
            "local_reason": getattr(self, "_local_reason", ""),
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

        PR-NATS-CORE: Auto-connects if not connected.
        """
        # Conformance/test no-op mode: accept the publish without a broker.
        if getattr(self, "_noop", False):
            self._stats["published"] += 1
            return {"success": True, "seq": 0, "noop": True}

        # 进程内降级总线:不碰网络、不再反复 auto-connect 刷错,内存直投。
        if getattr(self, "_local_mode", False):
            return self._local_publish(subject, data)

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
            logger.debug("Fallback triggered: %s", exc)
            self._stats["errors"] += 1
            logger.error(f"NATSBus: publish failed on {subject} — {exc}")
            return {"success": False, "error": str(exc)}

    async def _subscribe_both(
        self,
        legacy_subject: str,
        canonical_subject: str,
        callback: Callable,
        *,
        durable: str = "",
        return_subscription: bool = False,
    ) -> dict:
        """同时订阅遗留(复数)与规范(单数)两个主题。

        为什么必须订两个
        ----------------
        NATS 逐 token 精确匹配,``galaxy.task.*`` 与 ``galaxy.tasks.*`` 之间没有
        任何通配符能搭桥。而本仓这两个前缀**同时有真实发布方**:``NATSTopics``
        常量(新规范)走单数,``command_router`` / ``scheduler`` /
        ``gateway_nats_adapter`` / 各 legacy 发布器走复数。只订一个,另一半的
        消息就永远收不到 —— 修复前实测任务结果 0 条到得了主脑。

        durable 名必须分开
        ------------------
        JetStream 的 durable consumer 绑死一个 filter subject。两个订阅共用一个
        durable 名会冲突(报错,或两边互相抢消息)。所以规范那条统一加 ``-canonical``
        后缀,遗留那条保持原名 —— 已在跑的部署里那个 durable 不会被动到。

        不会重复投递
        ------------
        没有任何一条发布路径同时往两个前缀发,所以同一条消息只会经其中一个到达。
        """
        legacy = await self._subscribe(
            legacy_subject, callback, durable=durable, return_subscription=return_subscription
        )
        canonical = await self._subscribe(
            canonical_subject,
            callback,
            durable=f"{durable}-canonical" if durable else "",
            return_subscription=return_subscription,
        )

        subs = [r.get("subscription") for r in (legacy, canonical) if r.get("subscription") is not None]
        result: Dict[str, Any] = {
            # 两条里有一条成了就算订上了 —— 单机/降级场景下另一条失败不该让
            # 整个订阅报失败。两条都失败才是真失败。
            "success": bool(legacy.get("success") or canonical.get("success")),
            "subject": legacy_subject,
            "subjects": [legacy_subject, canonical_subject],
            "durable": durable,
        }
        if not result["success"]:
            result["error"] = legacy.get("error") or canonical.get("error") or "subscribe failed"
        if return_subscription:
            # ``subscription`` 保持单个对象(老调用方按这个字段拿);
            # ``subscriptions`` 给出全部,unsubscribe() 两种都收。
            result["subscription"] = subs[0] if subs else None
            result["subscriptions"] = subs
        return result

    async def _ensure_streams(self) -> None:
        """建流,并把配置里新增的 subject 补进已存在的流。

        只做并集:``update_stream`` 传的是"现有 subjects ∪ 配置 subjects",
        永不移除。已在跑的消费者可能挂在任何一个旧 subject 上。
        """
        from nats.js.api import StreamConfig  # noqa: PLC0415

        for name, cfg in _STREAMS.items():
            wanted = list(cfg["subjects"])
            try:
                info = await self._js.stream_info(name)
            except Exception:
                info = None

            if info is None:
                try:
                    await self._js.add_stream(
                        StreamConfig(
                            name=name,
                            subjects=wanted,
                            max_msgs=cfg["max_msgs"],
                            max_bytes=cfg["max_bytes"],
                            # 按时间淘汰只对遥测类平面设(心跳/在场),审计不设。
                            max_age=cfg.get("max_age_s"),
                            retention="limits",
                            storage="file",
                        )
                    )
                    logger.info("NATSBus: created stream %s subjects=%s", name, wanted)
                except Exception as exc:
                    # 建流失败分两种,不能一概当作"不是错误":
                    #
                    #   并发启动:另一个进程刚好抢先建好了 —— 真不是错误。
                    #   真失败:  比如 `insufficient storage resources available`
                    #            (所有流的 max_bytes 之和超过服务器 store 上限,
                    #            见 core/nats_subjects.py 的 TOTAL_STREAM_MAX_BYTES)。
                    #            这时**这个平面上的每一条 publish 都会失败**,
                    #            报 `no response from stream`。
                    #
                    # 原来两种都记 debug,于是后者在生产上完全无声:整条协议平面
                    # 发不出去,日志里什么都看不到。这里用 stream_info 复核一次 ——
                    # 流真在,是并发;不在,就必须响亮。
                    try:
                        await self._js.stream_info(name)
                        logger.debug("NATSBus: add_stream %s 已由其它进程建好: %s", name, exc)
                    except Exception:
                        logger.error(
                            "NATSBus: 建流 %s 失败,%s 上的消息一条也发不出去"
                            "(publish 会报 no response from stream)。原因:%s",
                            name,
                            wanted,
                            exc,
                        )
                continue

            existing = list(getattr(info.config, "subjects", None) or [])
            missing = [s for s in wanted if s not in existing]
            if not missing:
                continue
            try:
                cfg_obj = info.config
                cfg_obj.subjects = existing + missing
                await self._js.update_stream(cfg_obj)
                logger.info("NATSBus: stream %s 补入 subjects=%s", name, missing)
            except Exception as exc:
                # 补不进去要**响亮**:这意味着那些 subject 上的消息没有持久化,
                # 而不是"慢一点"。不抛(启动不该因此失败),但必须留下证据。
                logger.error(
                    "NATSBus: 无法把 %s 补进流 %s —— 这些主题上的消息将没有 "
                    "JetStream 持久化。请手动 `nats stream edit %s`。原因:%s",
                    missing,
                    name,
                    name,
                    exc,
                )

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
        # 进程内降级总线:订阅登记进内存表,由 _local_publish 匹配分发。
        if getattr(self, "_local_mode", False):
            self._local_subs.append((subject, callback))
            logger.debug("NATSBus(local): subscribed to %s", subject)
            result = {"success": True, "subject": subject, "durable": durable, "local": True}
            if return_subscription:
                result["subscription"] = None
            return result

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
            logger.debug("Fallback triggered: %s", exc)
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
        # ``_subscribe_both`` 会交出两个订阅(单/复数各一);调用方把整个列表传回来
        # 时要逐个退订,否则会漏掉一半、留下悬空的 durable consumer。
        if isinstance(subscription, (list, tuple, set)):
            results = [await self.unsubscribe(one) for one in subscription]
            failed = [r for r in results if not r.get("success")]
            if failed:
                return {"success": False, "error": failed[0].get("error", "unsubscribe failed")}
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
            logger.debug("Fallback triggered: %s", exc)
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
        # nats-py 在向【可选/未就绪】的 NATS 反复重连时会不断回调此处,而 exc 常
        # stringify 为空 —— 真机上刷出一串刺眼的 "NATSBus: error —"(消息为空)。
        # 桌面单机默认 NATS 可选(GALAXY_NATS_ENABLED=false,见 .env.example),
        # 这类重连期错误降噪:用 repr 保证信息不为空;非 fabric 严格模式降到 debug,
        # 严格模式仍保留 error,不掩盖真正需要 NATS 时的故障。
        detail = repr(exc) if not str(exc).strip() else str(exc)
        _strict = os.environ.get("GALAXY_FABRIC_STRICT", "").strip().lower() in ("1", "true", "yes", "on")
        if _strict:
            logger.error("NATSBus: error — %s", detail)
        else:
            logger.debug("NATSBus: error(重连期,NATS 桌面单机可选,已降噪)— %s", detail)


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
    # 阶段 0（分区可见化）：同一状态同时喂给链路态观测器 —— 本函数是
    # 连接/断开/重连/意外断开四条路径的共同出口，一处覆盖全部。
    try:
        from core.node_communication import get_link_observer  # noqa: PLC0415

        get_link_observer().record_center_link("nats", is_connected, detail=url)
    except Exception as _lo_exc:  # noqa: BLE001
        logger.debug("link observer unavailable (non-fatal): %s", _lo_exc)
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
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)
