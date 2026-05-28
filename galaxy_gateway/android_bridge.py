"""
Android Bridge Service — Android 动作适配器（PR-S4）
=======================================================

架构角色
--------
``AndroidBridge`` 是一个 **Android-specific action / payload 翻译适配器**，
不是独立的 presence 或 dispatch authority。

职责（保留）:
  1. 处理 AIP v3 WebSocket 协议的收发与规范化。
  2. 将服务端任务翻译为 Android 可执行的 AIP 命令（action/payload translation）。
  3. 处理安卓端返回的结果并触发记忆回流。
  4. 维护 WebSocket 连接句柄的 **传输/会话层本地缓存**（transport session cache）。

职责（已移除 — PR-2 / PR-S3 / PR-S4）:
  ✗ 不持有独立的设备 presence 权威（presence authority 在 UDM + UCM）。
  ✗ 不持有独立的任务 dispatch 权威（dispatch authority 在 DeviceRouter）。
  ✗ ``self._devices`` 不是设备事实来源（SSOT 在 UDM）。

模块结构（PR-3 modularization）:
  - galaxy_gateway.android.capabilities  — DeviceCapability
  - galaxy_gateway.android.models        — Rect, UIElement, AndroidDevice
  - galaxy_gateway.android.message_builder — MessageBuilder
  - galaxy_gateway.android.handlers.*   — isolated handler functions

与安卓端 AIPMessageV3.kt 完全对齐。

Author: Galaxy Team
Version: 3.0.0
"""

import asyncio
import logging
import time
import uuid
from typing import Dict, List, Optional, Any, Callable

# =============================================================================
# 模块导入 — 从拆分后的子模块导入（PR-3）
# =============================================================================

# 设备类型 — 单一事实来源
from core.device_types import (  # noqa: E402
    AIPDeviceType as DeviceType,
    DevicePlatform,
)

# 协议枚举 — 单一事实来源
from galaxy_gateway.protocol.aip_v3 import (  # noqa: E402
    MessageType,
    TaskStatus,
    ResultStatus,
)

# 子模块：能力、模型、消息构建器
from galaxy_gateway.android.capabilities import DeviceCapability
from galaxy_gateway.android.models import Rect, UIElement, AndroidDevice
from galaxy_gateway.android.message_builder import MessageBuilder

# 子模块：处理器
from galaxy_gateway.android.handlers.registration import (
    handle_device_register,
    handle_unregistered,
)
from galaxy_gateway.android.handlers.heartbeat import (
    handle_heartbeat,
    handle_device_status,
    handle_agent_ping,
    handle_agent_status,
)
from galaxy_gateway.android.handlers.task_lifecycle import (
    handle_task_result,
    handle_task_end,
    handle_task_progress,
    handle_command_result,
    handle_error,
    handle_task_cancel,
    handle_task_status,
)
from galaxy_gateway.android.handlers.task_submit import (
    handle_task_execute,
    handle_task_submit,
)
from galaxy_gateway.android.handlers.goal_execution import (
    handle_goal_execution,
    handle_parallel_subtask,
    handle_goal_execution_result,
)
from galaxy_gateway.android.handlers.capability_report import handle_capability_report
from galaxy_gateway.android.handlers.diagnostics import handle_diagnostics_payload
from galaxy_gateway.android.handlers.vision import handle_vision_request
from galaxy_gateway.android.handlers.generic import (
    handle_generic_forward,
    get_generic_forward_compat_allowlist,
)
from galaxy_gateway.android.handlers.delegated_signal import handle_delegated_execution_signal
from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result
from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
from galaxy_gateway.android.handlers.file_transfer import handle_file_transfer
from galaxy_gateway.android.handlers.peer_exchange import handle_peer_announce, handle_peer_exchange
from galaxy_gateway.android.handlers.mesh_topology import handle_mesh_topology
from galaxy_gateway.android.handlers.mesh_lifecycle import (
    handle_mesh_join,
    handle_mesh_result,
    handle_mesh_leave,
)
from galaxy_gateway.android.handlers.reconciliation_signal import handle_reconciliation_signal
from galaxy_gateway.android.handlers.acceptance_report import handle_device_acceptance_report
from galaxy_gateway.android.handlers.evaluator_artifact_report import (
    handle_evaluator_artifact_report,
)
from galaxy_gateway.android.handlers.device_state_snapshot import (
    handle_device_state_snapshot,
    handle_device_execution_event,
)
from galaxy_gateway.android.handlers.session_flow import handle_session_migrate
from galaxy_gateway.android.runtime_ws_profile import classify_android_runtime_ws_mapping

try:
    from contracts.cross_repo_schema_version_gate import (
        evaluate_android_uplink_schema_gate as _evaluate_android_uplink_schema_gate,
    )
except Exception as _schema_gate_import_exc:
    _evaluate_android_uplink_schema_gate = None  # type: ignore[assignment]
    logging.getLogger(__name__).debug(
        "android_bridge: cross-repo schema/version gate unavailable: %s",
        _schema_gate_import_exc,
    )

# Bufferable message types for the pending-delivery buffer.  Only task-dispatch
# message types are buffered; interactive/GUI/control messages are timing-sensitive
# and must NOT be re-delivered after a reconnect because the window for their
# execution would have long passed.
_BUFFERABLE_MESSAGE_TYPES: frozenset = frozenset({
    "task_assign",
    "task_execute",
    "task_submit",
    "goal_execution",
    "action_execute",
    "action_sequence_execute",
    "system_command",
})

# =============================================================================
# OpenClawd 记忆回流 — 顶层导入使测试可以通过 patch() 注入 mock
# =============================================================================
try:
    from core.openclawd_memory_backflow import store_task_result
except ImportError:
    store_task_result = None  # type: ignore[assignment]

# =============================================================================
# PR-11-V2-takeover: Lifecycle coordinator — module-level reference so callers
# can patch it in tests.  Used by send_takeover_request to record the
# outbound request as a canonical orchestrated lifecycle event.
# =============================================================================
try:
    from core.android_delegated_runtime_lifecycle_coordinator import (
        get_lifecycle_coordinator as _get_lifecycle_coordinator,
    )
except ImportError:  # pragma: no cover
    _get_lifecycle_coordinator = None  # type: ignore[assignment]

# Pending-delivery buffer — re-delivers buffered messages to devices that
# reconnect after a brief disconnect (fixes INFLIGHT_TASK_LOSS_ON_DISCONNECT).
from galaxy_gateway.pending_delivery_buffer import pending_delivery_buffer as _pending_delivery_buffer

# =============================================================================
# Axis-1 + Axis-7: Cross-device mode gate — takeover is only permitted when
# the system is running in ``desktop-cross-device`` mode.  The switch helper
# is imported at module level so tests can patch it without reloading the
# entire bridge.
# =============================================================================
try:
    from galaxy_gateway.cross_device_switch import (
        is_cross_device_enabled as _is_cross_device_enabled,
    )
except ImportError:  # pragma: no cover
    _is_cross_device_enabled = lambda: True  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# =============================================================================
# PR-3: Execution Spine Integration — bridge dispatch authority sentinel

#: Affirms that AndroidBridge no longer holds independent dispatch authority.
#: Dispatch authority belongs exclusively to CommandRouter (via the canonical
#: execution spine).  AndroidBridge retains its protocol-translation and
#: session-cache roles only.
ANDROID_BRIDGE_EXECUTION_SPINE_APPLIED: str = "ANDROID_BRIDGE_EXECUTION_SPINE_V1"

# =============================================================================
# Canonical Android reconnect path declaration
# =============================================================================

#: Affirms the canonical Android reconnect path and eliminates the ambiguity
#: between the explicit ``device_reconnect`` message handler (which is NOT used
#: in the Android production path) and the real reconnect flow.
#:
#: **Canonical Android reconnect path:**
#:   1. Android client opens a new WebSocket connection (new ``onOpen``).
#:   2. Android sends ``device_register`` with the same
#:      ``runtime_attachment_session_id`` that was echoed in the previous
#:      ``device_register_ack``.
#:   3. :func:`~galaxy_gateway.android.handlers.registration.handle_device_register`
#:      calls :func:`~core.attached_runtime_session_registry.classify_reconnect_outcome`
#:      to determine whether this is a *continuity resume* (same attachment ID →
#:      preserve ``runtime_session_id``) or a *new attachment* (different / absent
#:      ID → fresh session).
#:   4. The ack includes ``continuity_outcome`` so the caller can observe the
#:      server-side decision.
#:
#: The explicit ``device_reconnect`` wire message handler
#: (:func:`~galaxy_gateway.android.handlers.registration.handle_device_reconnect`)
#: is retained for backward-compatibility only and is **not** the production
#: canonical path.  :meth:`AndroidBridge.reconnect_device` is a bridge-level
#: transport helper (used in tests / external callers); it is also not the
#: primary inbound reconnect path.
ANDROID_RECONNECT_CANONICAL_PATH_SENTINEL: str = (
    "RECONNECT_CANONICAL_PATH_V1: "
    "Android reconnects via new WebSocket + device_register with the same "
    "runtime_attachment_session_id.  handle_device_register() calls "
    "classify_reconnect_outcome() to decide continuity_resume vs new_attachment. "
    "handle_device_reconnect() and reconnect_device() are NOT the production "
    "canonical reconnect path."
)

# =============================================================================
# PR-G4: Android trace round-trip hook — stable entry point for cross-repo
# trace correlation.
# =============================================================================

#: Affirms that AndroidBridge exposes a stable observability hook for Android
#: dispatch trace round-trips.  Callers can extract the dispatch_trace_id from
#: an inbound AIP message via :func:`get_android_bridge_trace_id` and match it
#: against the :class:`~core.runtime.runtime_observability_sink.RuntimeObservabilitySink`
#: dispatch decision events for end-to-end correlation.
ANDROID_BRIDGE_TRACE_HOOK_SENTINEL: str = (
    "ANDROID_BRIDGE_TRACE_HOOK_V1: "
    "galaxy_gateway.android_bridge exposes get_android_bridge_trace_id() as "
    "the canonical stable hook for Android trace round-trip correlation.  "
    "Use this function to extract the dispatch_trace_id from an inbound AIP "
    "message dict and correlate it with RuntimeObservabilitySink events.  PR-G4."
)


def get_android_bridge_trace_id(message: Dict[str, Any]) -> Optional[str]:
    """Extract the dispatch trace ID from an inbound AIP message.

    This is the canonical stable hook for Android trace round-trip correlation.
    It returns the first non-empty string value found by checking these keys in
    order:

    1. ``trace_id`` (top-level)
    2. ``dispatch_trace_id`` (top-level)
    3. ``message_id`` (top-level)
    4. ``trace_id`` (inside nested ``payload`` dict)
    5. ``dispatch_trace_id`` (inside nested ``payload`` dict)

    Parameters
    ----------
    message:
        Inbound AIP message dict (already normalised to v3 shape, or raw).

    Returns
    -------
    str or None
        The trace ID string, or ``None`` when no trace identifier is present.
    """
    if not isinstance(message, dict):
        return None
    for key in ("trace_id", "dispatch_trace_id", "message_id"):
        val = message.get(key)
        if val and isinstance(val, str):
            return val
    # Also check inside nested payload dict
    payload = message.get("payload")
    if isinstance(payload, dict):
        for key in ("trace_id", "dispatch_trace_id"):
            val = payload.get(key)
            if val and isinstance(val, str):
                return val
    return None


class AndroidBridge:
    """
    Android 桥接服务 — transport registration + runtime presence adapter。

    负责管理所有安卓设备的连接、任务分发和结果收集。

    架构角色 (PR-2)
    ---------------
    AndroidBridge 是 **transport/session adapter**，不是独立的设备事实源。

    - 设备注册 / 心跳 / 断联 / 重连的 **canonical 状态写入** 经由
      ``UnifiedDeviceManager`` (UDM) 完成，UDM 是唯一的写入 SSOT。
    - ``self._devices`` 仅保留为 **transport/session operational cache**，
      用于维护 WebSocket 连接句柄与轻量级连接态，不再充当主设备注册表。
    - 所有外部代码若需要权威设备状态，应查询 UDM，而非直接读取 ``_devices``。

    模块结构 (PR-3)
    ---------------
    handler 逻辑已拆分到 ``galaxy_gateway.android.handlers.*`` 子包；
    此类仅保留 transport/session cache、UDM 辅助方法和消息分发逻辑。
    """

    def __init__(self):
        # transport/session operational cache — NOT the canonical device registry.
        # PR-UDM-UNIFY: ``_devices`` 是 **transport-layer WebSocket handle cache**，
        # 用于维护 WebSocket 连接句柄与轻量级连接态。它是 operational cache，
        # 不是设备事实来源 (SSOT)。权威设备注册表在 UnifiedDeviceManager (UDM)。
        #
        # 读取路径（应逐步迁移至 UDM 查询）：
        #   - get_android_devices()   → 应查询 UDM.list_devices(platform=ANDROID)
        #   - cleanup_stale_devices() → 应查询 UDM.get_stale_devices()
        #   - get_device_health()     → 应查询 UDM + UCM 心跳状态
        #
        # 写入路径（保留，因为涉及 WebSocket 句柄清理）：
        #   - disconnect_device()     → 修改 connected/websocket + 同步 UDM
        #   - reconnect_device()      → 修改 websocket/connected/last_heartbeat
        #   - assign_task()           → 修改 current_task_id（transport context）
        #
        # TODO(PR-UDM-UNIFY): 当 UDM 提供实时设备查询 API 后，逐步将读取路径
        # 迁移至 UDM；_devices 仅保留 WebSocket 句柄和 connected 标志。
        self._devices: Dict[str, AndroidDevice] = {}
        self._pending_responses: Dict[str, asyncio.Future] = {}
        self._message_handlers: Dict[MessageType, Callable] = {}
        self._lock = asyncio.Lock()

        # 注册默认处理器
        self._register_default_handlers()

        logger.info("AndroidBridge initialized")

    # =========================================================================
    # UDM canonical write/patch helpers (PR-2)
    # =========================================================================

    def _write_registration_to_udm(self, device_id: str, message: Dict[str, Any]) -> None:
        """Write canonical device identity/state to UnifiedDeviceManager on registration."""
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            from core.unified.models import UnifiedDevice, UnifiedDeviceType

            udm = UnifiedDeviceManager()

            raw_caps = message.get("capabilities", 0)
            if isinstance(raw_caps, int):
                caps_list = DeviceCapability.to_list(raw_caps)
            elif isinstance(raw_caps, (list, tuple)):
                caps_list = [str(c) for c in raw_caps]
            else:
                caps_list = []

            raw_device_type = str(message.get("device_type", "android_phone")).lower()
            try:
                utype = UnifiedDeviceType(raw_device_type)
            except ValueError:
                utype = UnifiedDeviceType.ANDROID

            metadata = {
                "model": message.get("model", ""),
                "os_version": message.get("os_version", ""),
                "sdk_version": message.get("sdk_version"),
                "screen_width": message.get("screen_width"),
                "screen_height": message.get("screen_height"),
                "platform": message.get("platform", "android"),
                "app_version": message.get("app_version", ""),
            }
            metadata = {k: v for k, v in metadata.items() if v is not None}

            device = UnifiedDevice(
                device_id=device_id,
                device_name=str(message.get("name") or "Android Device"),
                device_type=utype,
                capabilities=caps_list,
                metadata=metadata,
                source="android_bridge",
            )
            udm.register_device(device)
            logger.info(
                "android_bridge: wrote registration to UDM (SSOT): device_id=%s",
                device_id,
                extra={"event": "android_bridge_udm_register", "device_id": device_id},
            )
        except Exception as exc:
            logger.warning(
                "android_bridge: UDM registration write failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

    def _patch_runtime_state_to_udm(
        self,
        device_id: str,
        patch: Dict[str, Any],
        source: str = "android_bridge",
    ) -> None:
        """Patch canonical runtime state in UnifiedDeviceManager."""
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            udm = UnifiedDeviceManager()
            result = udm.upsert_device_state(device_id, patch, source=source)
            if result is None:
                logger.debug(
                    "android_bridge: _patch_runtime_state_to_udm: device not in UDM yet, skipping: %s",
                    device_id,
                )
        except Exception as exc:
            logger.warning(
                "android_bridge: UDM state patch failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

    def _patch_heartbeat_to_udm(self, device_id: str) -> None:
        """Record heartbeat in UDM canonical state (updates last_heartbeat + keeps ONLINE)."""
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            UnifiedDeviceManager().heartbeat(device_id)
        except Exception as exc:
            logger.debug(
                "android_bridge: UDM heartbeat patch failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

        try:
            from core.unified.connection_manager import get_unified_connection_manager
            get_unified_connection_manager().update_heartbeat(device_id)
        except Exception as exc:
            logger.debug(
                "android_bridge: UCM heartbeat patch failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

    def _patch_disconnect_to_udm(self, device_id: str) -> None:
        """Mark device as DISCONNECTED in UDM without removing canonical identity."""
        self._patch_runtime_state_to_udm(
            device_id,
            {"status": "disconnected"},
            source="android_bridge_disconnect",
        )

        try:
            from core.unified.connection_manager import get_unified_connection_manager
            get_unified_connection_manager().mark_offline(device_id)
        except Exception as exc:
            logger.debug(
                "android_bridge: UCM mark_offline failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

        # PR-B: Terminate any active/pending mesh sessions associated with this
        # device so the MeshSessionLifecycleCoordinator reflects the disconnect.
        try:
            from core.mesh.mesh_session_lifecycle import (
                get_lifecycle_coordinator,
                terminate_durable_session,
            )
            _coord = get_lifecycle_coordinator()
            _session_ids = _coord.find_sessions_for_device(device_id)
            for _sid in _session_ids:
                terminate_durable_session(
                    _sid,
                    outcome="cancelled",
                    reason=f"device_disconnect:{device_id}",
                )
                logger.info(
                    "Mesh session terminated on device disconnect: device_id=%s session_id=%s",
                    device_id, _sid,
                )
        except Exception as _mesh_exc:
            logger.debug(
                "android_bridge: mesh session terminate non-fatal: device_id=%s error=%s",
                device_id, _mesh_exc,
            )

        # V2 lifecycle mainline: detach attached session in AttachedSessionRegistry
        # so that the registry reflects the transport-level disconnect.
        try:
            from core.attached_runtime_session_registry import (
                lookup_session_by_device,
                detach_session,
                InvalidationReason,
            )
            _entry = lookup_session_by_device(device_id)
            if _entry is not None:
                detach_session(
                    _entry,
                    reason=InvalidationReason.disconnected,
                    metadata={"disconnect_source": "android_bridge"},
                )
                logger.info(
                    "AttachedSessionRegistry: session detached on device disconnect: "
                    "device_id=%s runtime_session_id=%s",
                    device_id, _entry.runtime_session_id,
                )
        except Exception as _asr_exc:
            logger.debug(
                "android_bridge: attached session detach non-fatal: device_id=%s error=%s",
                device_id, _asr_exc,
            )

        # PR-A: Notify multi-device runtime harness of the device disconnect so
        # that formation rebalance evaluation and readiness tracking are active.
        try:
            from core.multi_device_runtime_harness import (
                on_device_health_changed,
                on_participant_readiness_changed,
                DeviceHealthEvent,
            )
            on_device_health_changed(
                DeviceHealthEvent(
                    device_id=device_id,
                    health_score=0.0,
                    is_reachable=False,
                    event_type="disconnect",
                )
            )
            on_participant_readiness_changed(
                device_id, "lost", reason="android_disconnect"
            )
        except Exception as _harn_exc:
            logger.debug(
                "android_bridge: harness disconnect notification failed (non-fatal): "
                "device_id=%s error=%s",
                device_id, _harn_exc,
            )

        # Invalidate V2-side Android snapshot truth immediately on disconnect so
        # stale readiness does not continue affecting routing/participation.
        try:
            from core.android_device_state_store import invalidate_device_state_snapshot

            invalidate_device_state_snapshot(device_id)
        except Exception as _snapshot_exc:
            logger.debug(
                "android_bridge: snapshot invalidation on disconnect failed (non-fatal): "
                "device_id=%s error=%s",
                device_id, _snapshot_exc,
            )

        # 统一设备生命周期状态：WebSocket 断开时将设备生命周期重置为 unregistered。
        try:
            from core.device_lifecycle_state import (  # noqa: PLC0415
                transition_device_lifecycle,
                DeviceLifecycleTransitionEvent,
            )
            transition_device_lifecycle(
                device_id,
                DeviceLifecycleTransitionEvent.websocket_disconnected,
            )
        except Exception as _lc_disc_exc:
            logger.debug(
                "android_bridge: device_lifecycle disconnect transition non-fatal: "
                "device_id=%s error=%s",
                device_id, _lc_disc_exc,
            )

    def _patch_reconnect_to_udm(self, device_id: str) -> None:
        """Mark device as ONLINE in UDM on reconnect (no duplicate identity created)."""
        self._patch_runtime_state_to_udm(
            device_id,
            {"status": "online"},
            source="android_bridge_reconnect",
        )

        try:
            from core.unified.connection_manager import get_unified_connection_manager
            ucm = get_unified_connection_manager()
            ucm.update_heartbeat(device_id)
        except Exception as exc:
            logger.debug(
                "android_bridge: UCM reconnect patch failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

        # PR-A: Notify multi-device runtime harness of the device reconnect so
        # that formation readiness tracking reflects the restored participant.
        try:
            from core.multi_device_runtime_harness import (
                on_device_health_changed,
                on_participant_readiness_changed,
                DeviceHealthEvent,
            )
            on_device_health_changed(
                DeviceHealthEvent(
                    device_id=device_id,
                    health_score=1.0,
                    is_reachable=True,
                    event_type="reconnect",
                )
            )
            on_participant_readiness_changed(
                device_id, "ready", reason="android_reconnect"
            )
        except Exception as _harn_exc:
            logger.debug(
                "android_bridge: harness reconnect notification failed (non-fatal): "
                "device_id=%s error=%s",
                device_id, _harn_exc,
            )

    def _sync_device_router_session(
        self,
        device_id: str,
        *,
        websocket: Any = None,
        connected: bool,
    ) -> None:
        """Mirror Android live session state into DeviceRouter without creating a new truth source.

        Args:
            device_id: Canonical Android device identifier.
            websocket: Optional live websocket handle to attach to the router session.
            connected: Whether the router session should be marked connected or disconnected.
        """
        try:
            from galaxy_gateway.device_router import device_router as _device_router

            if not connected:
                _device_router.on_device_disconnected(device_id, transport="websocket")
                return

            device = self._devices.get(device_id)
            if device is None:
                logger.debug(
                    "android_bridge: device_router sync skipped; no transport cache for device_id=%s",
                    device_id,
                )
                return

            if _device_router.get_device(device_id) is None:
                from galaxy_gateway.device_router import map_device_type_to_platform

                metadata = {
                    "name": device.name,
                    "model": device.model,
                    "os_version": device.os_version,
                    "sdk_version": device.sdk_version,
                    "screen_width": device.screen_width,
                    "screen_height": device.screen_height,
                    "platform": device.platform.value,
                }
                metadata = {k: v for k, v in metadata.items() if v is not None}
                _device_router.ensure_live_session(
                    device_id=device.device_id,
                    device_type=map_device_type_to_platform(device.device_type.value),
                    capabilities=DeviceCapability.to_list(device.capabilities),
                    websocket=websocket if websocket is not None else device.websocket,
                    metadata=metadata,
                    transport="websocket",
                )
                return

            router_device = _device_router.get_device(device_id)
            _device_router.ensure_live_session(
                device_id=device_id,
                device_type=router_device.device_type,
                capabilities=list(router_device.capabilities),
                websocket=websocket if websocket is not None else device.websocket,
                metadata=router_device.metadata,
                transport="websocket",
            )
        except Exception as exc:
            logger.debug(
                "android_bridge: device_router session sync failed (non-fatal): device_id=%s error=%s",
                device_id,
                exc,
            )

    # ─────────────────────────────────────────────────────────────────────────
    #  设备 Fan-out 辅助方法（PARALLEL_SUBTASK / 多设备协作）
    # ─────────────────────────────────────────────────────────────────────────

    async def _fan_out_task_assign(
        self,
        task_id: str,
        task_type: str,
        goal: str,
        device_ids: List[str],
        session_id: str,
        trace_id: str,
        max_steps: int = 10,
        constraints: Optional[List[str]] = None,
        group_id: Optional[str] = None,
        require_local_agent: bool = True,
    ) -> Dict[str, Any]:
        """将 task_assign 扇出（fan-out）到多台设备。

        每台设备在发送前必须通过统一派发就绪检查
        (:func:`~core.unified_dispatch_readiness_gate.evaluate_dispatch_readiness`)。
        未通过检查的设备被标记为 failed 并跳过，不发送任务。
        """
        constraints = constraints or []
        results: Dict[str, Any] = {"fanout": 0, "failed": 0, "device_ids": [], "errors": []}

        try:
            from core.unified.connection_manager import get_unified_connection_manager
            ucm = get_unified_connection_manager()
        except Exception as ucm_err:
            logger.warning(
                "PARALLEL_SUBTASK fan-out: UCM 不可用，跳过 fan-out | error=%s", ucm_err,
            )
            return {"fanout": 0, "failed": len(device_ids), "device_ids": [], "errors": [str(ucm_err)]}

        # --- Import the unified dispatch readiness gate (additive; non-fatal if unavailable) ---
        _readiness_gate_fn = None
        try:
            from core.unified_dispatch_readiness_gate import evaluate_dispatch_readiness as _readiness_gate_fn  # noqa: N812
        except Exception as _gate_import_err:
            logger.debug(
                "PARALLEL_SUBTASK fan-out: unified readiness gate unavailable "
                "(non-fatal, proceeding without per-device gating): %s",
                _gate_import_err,
            )

        for idx, did in enumerate(device_ids):
            # ------------------------------------------------------------------
            # PR: Unified dispatch readiness gate — skip non-ready devices
            # ------------------------------------------------------------------
            if _readiness_gate_fn is not None:
                try:
                    _readiness = _readiness_gate_fn(
                        did,
                        session_id=session_id,
                        execution_mode="parallel_fanout",
                    )
                    if not _readiness.dispatch_ready:
                        results["failed"] += 1
                        _err_msg = (
                            f"device {did}: dispatch blocked by readiness gate "
                            f"(status={_readiness.status!r}, "
                            f"reason={_readiness.reason!r})"
                        )
                        results["errors"].append(_err_msg)
                        logger.info(
                            "PARALLEL_SUBTASK fan-out: device_id=%s blocked by "
                            "unified readiness gate | status=%s reason=%r",
                            did,
                            _readiness.status,
                            _readiness.reason,
                        )
                        continue
                except Exception as _gate_err:
                    logger.debug(
                        "PARALLEL_SUBTASK fan-out: readiness gate check failed "
                        "for device_id=%s (non-fatal, proceeding): %s",
                        did,
                        _gate_err,
                    )

            try:
                task_assign_payload: Dict[str, Any] = {
                    "task_id": task_id,
                    "goal": goal,
                    "constraints": constraints,
                    "max_steps": max_steps,
                    "require_local_agent": require_local_agent,
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "runtime_session_id": trace_id,
                    "success": True,
                    "group_id": group_id,
                    "subtask_index": idx,
                    "device_ids": device_ids,
                }

                msg = MessageBuilder.task_assign(
                    device_id=did,
                    task_id=task_id,
                    task_type=task_type,
                    payload=task_assign_payload,
                )
                msg["trace_id"] = trace_id
                msg["session_id"] = session_id

                sent = await ucm.send_to_device(did, msg)
                if sent:
                    results["fanout"] += 1
                    results["device_ids"].append(did)
                    logger.debug(
                        "PARALLEL_SUBTASK fan-out → device_id=%s subtask_index=%s", did, idx,
                    )
                else:
                    results["failed"] += 1
                    results["errors"].append(f"device {did}: WebSocket not connected")

            except Exception as fan_err:
                results["failed"] += 1
                results["errors"].append(f"device {did}: {fan_err}")
                logger.warning(
                    "PARALLEL_SUBTASK fan-out → device_id=%s failed: %s", did, fan_err,
                )

        logger.info(
            "PARALLEL_SUBTASK fan-out 完成: fanout=%s failed=%s total=%s",
            results["fanout"], results["failed"], len(device_ids),
        )
        return results

    # =========================================================================
    # Handler registration and dispatch
    # =========================================================================

    def _register_default_handlers(self):
        """注册默认消息处理器，将消息类型映射到对应的处理函数。"""

        def _wrap(fn):
            """Wrap a standalone handler function as a bound-style coroutine."""
            async def _wrapped_handler(websocket, message):
                return await fn(self, websocket, message)
            return _wrapped_handler

        self._message_handlers[MessageType.DEVICE_REGISTER] = _wrap(handle_device_register)
        self._message_handlers[MessageType.DEVICE_HEARTBEAT] = _wrap(handle_heartbeat)
        self._message_handlers[MessageType.TASK_RESULT] = _wrap(handle_task_result)
        self._message_handlers[MessageType.TASK_PROGRESS] = _wrap(handle_task_progress)
        self._message_handlers[MessageType.COMMAND_RESULT] = _wrap(handle_command_result)
        self._message_handlers[MessageType.ERROR] = _wrap(handle_error)

        # AgentMessageHandler.kt 对齐类型
        self._message_handlers[MessageType.TASK_EXECUTE] = _wrap(handle_task_execute)
        self._message_handlers[MessageType.TASK_SUBMIT] = _wrap(handle_task_submit)
        self._message_handlers[MessageType.GOAL_EXECUTION] = _wrap(handle_goal_execution)
        self._message_handlers[MessageType.PARALLEL_SUBTASK] = _wrap(handle_parallel_subtask)
        self._message_handlers[MessageType.GOAL_EXECUTION_RESULT] = _wrap(handle_goal_execution_result)
        # Android error-path alias: some flows emit "goal_result" instead of
        # "goal_execution_result" on failure/cancellation.  Route to the same
        # handler so the canonical result path is not silently discarded.
        self._message_handlers[MessageType.GOAL_RESULT] = _wrap(handle_goal_execution_result)
        self._message_handlers[MessageType.TASK_CANCEL] = _wrap(handle_task_cancel)
        self._message_handlers[MessageType.TASK_STATUS] = _wrap(handle_task_status)
        self._message_handlers[MessageType.SESSION_MIGRATE] = _wrap(handle_session_migrate)
        self._message_handlers[MessageType.AGENT_PING] = _wrap(handle_agent_ping)
        self._message_handlers[MessageType.AGENT_STATUS] = _wrap(handle_agent_status)
        # Bounded compat path: generic-forward is an explicit allowlist gate,
        # not an open fallback for unclassified message semantics.
        for _compat_message_type in get_generic_forward_compat_allowlist():
            self._message_handlers[MessageType(_compat_message_type)] = _wrap(
                handle_generic_forward
            )
        self._message_handlers[MessageType.FILE_TRANSFER] = _wrap(handle_file_transfer)
        self._message_handlers[MessageType.PEER_ANNOUNCE] = _wrap(handle_peer_announce)
        self._message_handlers[MessageType.PEER_EXCHANGE] = _wrap(handle_peer_exchange)
        self._message_handlers[MessageType.MESH_TOPOLOGY] = _wrap(handle_mesh_topology)

        # PR-13: Android Mesh 生命周期上行处理器
        # mesh_join / mesh_result / mesh_leave 均由专用处理器接收，落盘至
        # core.mesh.android_mesh_lifecycle_store，并更新 MeshSessionLifecycleCoordinator。
        self._message_handlers[MessageType.MESH_JOIN] = _wrap(handle_mesh_join)
        self._message_handlers[MessageType.MESH_RESULT] = _wrap(handle_mesh_result)
        self._message_handlers[MessageType.MESH_LEAVE] = _wrap(handle_mesh_leave)

        # 设备状态上报
        self._message_handlers[MessageType.DEVICE_STATUS] = _wrap(handle_device_status)

        # 任务生命周期：task_end 结束确认
        self._message_handlers[MessageType.TASK_END] = _wrap(handle_task_end)

        # 能力/诊断上报
        self._message_handlers[MessageType.CAPABILITY_REPORT] = _wrap(handle_capability_report)
        self._message_handlers[MessageType.DIAGNOSTICS_PAYLOAD] = _wrap(handle_diagnostics_payload)

        # 视觉请求
        self._message_handlers[MessageType.VISION_REQUEST] = _wrap(handle_vision_request)

        # PR-16: Android delegated execution signal canonical ingress
        self._message_handlers[MessageType.DELEGATED_EXECUTION_SIGNAL] = _wrap(
            handle_delegated_execution_signal
        )

        # PR-02-V2: Android HandoffEnvelopeV2 uplink responses — canonical ingress
        # All three uplink wire types (ack / result / failure) plus the unified
        # envelope result type are routed through the same handler, which delegates
        # to core.android_handoff_v2_response_ingress.ingest_android_handoff_response().
        self._message_handlers[MessageType.HANDOFF_ACK] = _wrap(handle_handoff_v2_result)
        self._message_handlers[MessageType.HANDOFF_RESULT] = _wrap(handle_handoff_v2_result)
        self._message_handlers[MessageType.HANDOFF_FAILURE] = _wrap(handle_handoff_v2_result)
        self._message_handlers[MessageType.HANDOFF_ENVELOPE_V2_RESULT] = _wrap(
            handle_handoff_v2_result
        )

        # Android Takeover Protocol: uplink takeover_response from Android
        self._message_handlers[MessageType.TAKEOVER_RESPONSE] = _wrap(handle_takeover_response)

        # PR-7-V2: Android reconciliation signal canonical ingress
        self._message_handlers[MessageType.RECONCILIATION_SIGNAL] = _wrap(
            handle_reconciliation_signal
        )

        # PR-RT: Android Runtime-State Transparency Uplink handlers
        # DEVICE_STATE_SNAPSHOT — periodic full Android runtime-state snapshot
        # DEVICE_EXECUTION_EVENT — per-step execution phase event
        # Both are absorbed via core.android_device_state_store and made
        # available to V2 operator surfaces.
        self._message_handlers[MessageType.DEVICE_STATE_SNAPSHOT] = _wrap(
            handle_device_state_snapshot
        )
        self._message_handlers[MessageType.DEVICE_EXECUTION_EVENT] = _wrap(
            handle_device_execution_event
        )

        # Android Lifecycle / Governance Uplink Reports
        # readiness/governance/strategy are canonical policy inputs and must
        # enter Android evaluator artifact ingress (not generic forwarding).
        for _android_report_type in (
            MessageType.DEVICE_READINESS_REPORT,
            MessageType.DEVICE_GOVERNANCE_REPORT,
            MessageType.DEVICE_STRATEGY_REPORT,
        ):
            self._message_handlers[_android_report_type] = _wrap(
                handle_evaluator_artifact_report
            )
        self._message_handlers[MessageType.DEVICE_ACCEPTANCE_REPORT] = _wrap(
            handle_device_acceptance_report
        )

        # Catch-all: 为所有未注册的消息类型添加通用日志处理器
        for msg_type in MessageType:
            if msg_type not in self._message_handlers:
                self._message_handlers[msg_type] = _wrap(handle_unregistered)

    # Fields that are hard requirements
    _V3_MANDATORY_FIELDS: tuple = ("type", "device_id")

    # Fields auto-generated for backward compatibility when absent
    _V3_AUTO_FILL_FIELDS: tuple = ("version", "timestamp", "message_id")

    async def handle_message(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理来自安卓设备的消息。

        验证流程：
        1. 通过 compat 层将所有协议版本规范化为 AIP v3 dict。
        2. 检查强制字段（type、device_id）。
        3. 派发到对应处理器。
        """
        device_id_pre = message.get("device_id", "unknown") if isinstance(message, dict) else "unknown"
        try:
            from galaxy_gateway.protocol.compat import normalise_to_v3_dict
            message = normalise_to_v3_dict(message)
        except Exception as norm_err:
            logger.warning(
                "android_bridge: failed to normalise message via compat: %s", norm_err,
                extra={
                    "event": "aip_normalise_error",
                    "device_id": device_id_pre,
                    "reason": str(norm_err),
                },
            )
            return MessageBuilder.error(
                device_id_pre,
                "PROTOCOL_PARSE_ERROR",
                f"Failed to parse message: {norm_err}",
                details={"reason": str(norm_err)},
            )

        device_id = message.get("device_id")
        msg_type_str = message.get("type")

        missing = [f for f in self._V3_MANDATORY_FIELDS if not message.get(f)]
        if missing:
            logger.warning(
                "handle_message: malformed message from %s — missing required fields: %s",
                device_id or "unknown",
                missing,
            )
            return MessageBuilder.error(
                device_id or "unknown",
                "MISSING_REQUIRED_FIELDS",
                f"AIP v3.0 required fields missing: {missing}",
                details={"missing_fields": missing, "received_type": msg_type_str},
            )

        try:
            msg_type = MessageType(msg_type_str)
        except ValueError:
            logger.warning("Unknown message type: %s", msg_type_str)
            return MessageBuilder.error(
                device_id or "unknown",
                "UNKNOWN_MESSAGE_TYPE",
                f"Unknown message type: {msg_type_str}",
            )

        schema_gate_evidence = None
        if _evaluate_android_uplink_schema_gate is not None:
            try:
                gate_decision = _evaluate_android_uplink_schema_gate(
                    message_type=msg_type.value,
                    message=message,
                )
                if gate_decision is not None:
                    schema_gate_evidence = gate_decision.to_dict()
                    message["_cross_repo_schema_version_gate"] = schema_gate_evidence
                    if gate_decision.action == "reject":
                        logger.warning(
                            "android_bridge: schema/version gate rejected inbound message "
                            "type=%s device_id=%s reason=%s observed_schema=%s observed_contract=%s",
                            msg_type.value,
                            device_id,
                            gate_decision.reason,
                            gate_decision.observed_schema_version,
                            gate_decision.observed_contract_version,
                        )
                        return MessageBuilder.error(
                            device_id or "unknown",
                            "CROSS_REPO_SCHEMA_VERSION_GATE_REJECTED",
                            (
                                "Inbound Android message rejected by cross-repo "
                                f"schema/version gate ({gate_decision.reason})"
                            ),
                            details={
                                "schema_version_gate": schema_gate_evidence,
                                "message_type": msg_type.value,
                            },
                            correlation_id=str(message.get("message_id") or ""),
                        )
                    if gate_decision.action == "degrade":
                        logger.warning(
                            "android_bridge: schema/version gate compat-degraded inbound message "
                            "type=%s device_id=%s reason=%s observed_schema=%s",
                            msg_type.value,
                            device_id,
                            gate_decision.reason,
                            gate_decision.observed_schema_version,
                        )
            except Exception as gate_exc:
                logger.warning(
                    "android_bridge: schema/version gate evaluation failed (non-fatal): "
                    "type=%s device_id=%s error=%s",
                    msg_type.value,
                    device_id,
                    gate_exc,
                    exc_info=True,
                )

        profile_mapping = classify_android_runtime_ws_mapping(msg_type.value)
        logger.debug(
            "android runtime-ws ingress mapped: device_id=%s type=%s family=%s handling=%s",
            device_id,
            msg_type.value,
            profile_mapping.semantic_family,
            profile_mapping.handling_level,
        )

        handler = self._message_handlers.get(msg_type)
        if handler:
            response = await handler(websocket, message)
            # Propagate trace_id/route_mode into the response
            if response and isinstance(response, dict):
                trace_id = message.get("trace_id", "")
                route_mode = message.get("route_mode", "")
                resp_payload = response.get("payload")
                if isinstance(resp_payload, dict):
                    if trace_id:
                        resp_payload.setdefault("trace_id", trace_id)
                    if route_mode:
                        resp_payload.setdefault("route_mode", route_mode)
                if schema_gate_evidence:
                    response.setdefault("schema_version_gate", schema_gate_evidence)
            return response
        else:
            logger.debug("No handler for message type: %s", msg_type)
            return None

    # =========================================================================
    # 公共 API
    # =========================================================================

    async def send_to_device(self, device_id: str, message: Dict[str, Any],
                             wait_response: bool = False,
                             timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """发送消息到设备.

        Return values
        -------------
        * ``{"success": True}`` — message delivered to live WebSocket (no wait).
        * Response dict — when *wait_response* is True and a response arrived.
        * ``{"buffered": True, "device_id": ..., "type": ...}`` — device is
          temporarily offline **and** the message type is bufferable; the message
          was enqueued in the pending-delivery buffer for re-delivery on reconnect.
          Callers that need to distinguish "sent" from "buffered" should check for
          the ``"buffered"`` key.
        * ``None`` — device is offline and the message type is not bufferable, or
          the device WebSocket send raised an exception.

        When the device is temporarily offline, task-type messages are enqueued
        in the pending-delivery buffer (``_BUFFERABLE_MESSAGE_TYPES``) so that
        they can be re-delivered when the device reconnects.  Control messages
        (heartbeats, pings, GUI interactions that require an immediate interactive
        response) are NOT buffered because re-delivering them after a reconnect
        would be semantically incorrect.
        """
        async with self._lock:
            device = self._devices.get(device_id)

        if not device or not device.connected:
            msg_type = message.get("type", "")
            if msg_type in _BUFFERABLE_MESSAGE_TYPES:
                await _pending_delivery_buffer.enqueue(device_id, message)
                logger.warning(
                    "send_to_device: device_id=%s offline — message buffered for "
                    "redelivery on reconnect (type=%s)",
                    device_id, msg_type,
                )
                return {"buffered": True, "device_id": device_id, "type": msg_type}
            logger.warning("Device not connected: %s", device_id)
            return None

        try:
            await device.websocket.send_json(message)

            if wait_response:
                message_id = message.get("message_id") or message.get("task_id")
                future = asyncio.get_event_loop().create_future()
                self._pending_responses[message_id] = future

                try:
                    return await asyncio.wait_for(future, timeout=timeout)
                except asyncio.TimeoutError:
                    self._pending_responses.pop(message_id, None)
                    logger.warning("Response timeout for message: %s", message_id)
                    return None

            return {"success": True}

        except Exception as e:
            logger.error("Failed to send message to %s: %s", device_id, e)
            return None

    async def click(self, device_id: str, x: int, y: int,
                    element_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """PR-S3 Android GUI action adapter — translate click to AIP protocol and send."""
        msg = MessageBuilder.gui_click(device_id, x, y, element_id)
        return await self.send_to_device(device_id, msg, wait_response=True)

    async def swipe(self, device_id: str, start_x: int, start_y: int,
                    end_x: int, end_y: int, duration_ms: int = 300) -> Optional[Dict[str, Any]]:
        """PR-S3 Android GUI action adapter — translate swipe to AIP protocol and send."""
        msg = MessageBuilder.gui_swipe(device_id, start_x, start_y, end_x, end_y, duration_ms)
        return await self.send_to_device(device_id, msg, wait_response=True)

    async def input_text(self, device_id: str, text: str,
                         element_id: Optional[str] = None,
                         clear_first: bool = False) -> Optional[Dict[str, Any]]:
        """Android GUI action adapter — translate text input to AIP protocol and send."""
        msg = MessageBuilder.gui_input(device_id, text, element_id, clear_first)
        return await self.send_to_device(device_id, msg, wait_response=True)

    async def screenshot(self, device_id: str, quality: int = 80,
                         scale: float = 1.0) -> Optional[Dict[str, Any]]:
        """Android GUI action adapter — translate screenshot request to AIP protocol and send."""
        msg = MessageBuilder.gui_screenshot(device_id, quality, scale)
        return await self.send_to_device(device_id, msg, wait_response=True, timeout=60.0)

    async def query_elements(self, device_id: str,
                             text: Optional[str] = None,
                             class_name: Optional[str] = None,
                             view_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Android GUI action adapter — translate element query to AIP protocol and send."""
        msg = MessageBuilder.gui_element_query(device_id, text, class_name, view_id)
        return await self.send_to_device(device_id, msg, wait_response=True)

    async def assign_task(self, device_id: str, task_id: str, task_type: str,
                          payload: Dict[str, Any], priority: int = 5,
                          timeout: int = 300) -> Optional[Dict[str, Any]]:
        """分配任务到设备 — delegates dispatch authority to DeviceRouter (PR-S3).

        Dispatch chain (canonical path):
            SourceDispatchOrchestrator
                → _try_android_bridge_dispatch()
                    → AndroidBridge.assign_task()          ← here
                        → DeviceRouter.dispatch_task()     (primary)
                        → MessageBuilder.task_assign()     (fallback send)
                            → send_to_device()

        The ``trace_id`` embedded in *payload* by the orchestrator dispatch
        path is surfaced as a top-level AIP message field for end-to-end
        observability (see PR-G4 / ``get_android_bridge_trace_id``).

        Registration gap guard
        ----------------------
        Before dispatching, the registration completeness of *device_id* is
        checked via :func:`~galaxy_gateway.android.handlers.registration.is_registration_fully_attached`.
        If downstream registration steps (``attach_runtime_session``,
        ``attached_runtime_session_registry``, etc.) failed for this device,
        :class:`~galaxy_gateway.android.handlers.registration.DispatchBlockedByRegistrationGapError`
        is raised rather than silently proceeding with an incompletely attached
        device.  This converts what was previously a best-effort gap into an
        explicit machine-observable dispatch block.

        Note: the guard only fires when gaps were *recorded* for this
        device_id.  Devices that were never registered through the canonical
        handler (e.g. in unit tests that construct devices directly) are
        considered gap-free and pass through unaffected.
        """
        # Registration completeness guard — raises DispatchBlockedByRegistrationGapError
        # when the device has recorded attachment gaps from its registration attempt.
        try:
            from galaxy_gateway.android.handlers.registration import (
                get_registration_gaps,
                DispatchBlockedByRegistrationGapError,
            )
            _gaps = get_registration_gaps(device_id)
            if _gaps:
                logger.warning(
                    "AndroidBridge.assign_task: DISPATCH BLOCKED — device_id=%s has "
                    "incomplete registration attachment gaps=%s; raising "
                    "DispatchBlockedByRegistrationGapError",
                    device_id, _gaps,
                )
                raise DispatchBlockedByRegistrationGapError(device_id, _gaps)
        except DispatchBlockedByRegistrationGapError:
            raise
        except Exception as _gap_check_err:
            logger.debug(
                "AndroidBridge.assign_task: registration gap check skipped "
                "(registration module unavailable or import failed) — %s",
                _gap_check_err,
            )

        # Extract trace_id from payload if the orchestrator embedded it there.
        # Surfacing it at the top level makes it visible to get_android_bridge_trace_id
        # and to any log-line inspection without needing to unwrap the payload.
        _trace_id: Optional[str] = None
        if isinstance(payload, dict):
            _trace_id = payload.get("trace_id") or payload.get("dispatch_trace_id")

        async with self._lock:
            if device_id in self._devices:
                self._devices[device_id].current_task_id = task_id

        logger.debug(
            "AndroidBridge.assign_task: device_id=%s task_id=%s task_type=%s "
            "trace_id=%s orchestrator_dispatch=%s",
            device_id,
            task_id,
            task_type,
            _trace_id,
            payload.get("orchestrator_dispatch") if isinstance(payload, dict) else False,
        )

        try:
            from galaxy_gateway.device_router import device_router as _device_router
            router_device = _device_router.devices.get(device_id)
            if router_device is not None:
                task_dict = {
                    "task_id": task_id,
                    "payload": {
                        "task_type": task_type,
                        "priority": priority,
                        **payload,
                    },
                }
                logger.debug(
                    "AndroidBridge.assign_task: routing via DeviceRouter "
                    "device_id=%s task_id=%s trace_id=%s",
                    device_id, task_id, _trace_id,
                )
                return await _device_router.dispatch_task(task_dict, router_device)
        except Exception as _router_err:
            logger.warning(
                "AndroidBridge.assign_task: DeviceRouter dispatch failed, "
                "falling back to send_to_device — %s", _router_err
            )

        logger.debug(
            "AndroidBridge.assign_task: fallback to send_to_device "
            "device_id=%s task_id=%s trace_id=%s",
            device_id, task_id, _trace_id,
        )
        msg = MessageBuilder.task_assign(
            device_id, task_id, task_type, payload, priority, timeout,
            trace_id=_trace_id,
        )
        return await self.send_to_device(device_id, msg, wait_response=True, timeout=float(timeout))

    async def send_takeover_request(
        self,
        device_id: str,
        takeover_id: str,
        *,
        session_id: Optional[str] = None,
        task_context: Optional[Dict[str, Any]] = None,
        reason: Optional[str] = None,
        trace_id: Optional[str] = None,
        timeout: int = 60,
    ) -> Optional[Dict[str, Any]]:
        """Send a ``takeover_request`` downlink to an Android device.

        V2 calls this to ask Android to accept a takeover.  Android will reply
        with a ``takeover_response`` uplink (accepted / rejected) which is
        processed by
        :func:`~galaxy_gateway.android.handlers.takeover_response.handle_takeover_response`.

        Parameters
        ----------
        device_id:
            Target Android device identifier.
        takeover_id:
            Unique identifier for this takeover request, used to correlate the
            incoming ``takeover_response``.
        session_id:
            Optional session to associate the takeover with.
        task_context:
            Optional dict carrying the task or goal context for the takeover.
        reason:
            Human-readable reason for the takeover request.
        trace_id:
            Optional distributed trace identifier for end-to-end observability.
        timeout:
            How long (seconds) Android should wait before auto-rejecting.
            This value is embedded in the message payload for Android's own
            timeout logic; it is not used as the network send timeout (sends
            are fire-and-forget: ``wait_response=False``).

        Returns
        -------
        dict or None
            ``{"success": True}`` on successful send, or a structured error
            dict when the system mode prevents takeover (e.g. not in
            ``desktop-cross-device`` mode), or ``None`` when the device is not
            connected / send fails.
        """
        # Axis-1 + Axis-7: Takeover is mode-gated.  It must not be initiated
        # unless the system is running in cross-device mode.  In local mode,
        # Android acts as a standalone device and takeover semantics are not
        # applicable.  Return a structured error so callers can surface the
        # refusal without raising.
        if not _is_cross_device_enabled():
            _tid = trace_id or str(uuid.uuid4())
            logger.warning(
                "send_takeover_request blocked: cross-device mode is disabled "
                "takeover_id=%s device_id=%s trace_id=%s",
                takeover_id,
                device_id,
                _tid,
            )
            return {
                "success": False,
                "blocked": True,
                "reason": "cross_device_mode_disabled",
                "takeover_id": takeover_id,
                "device_id": device_id,
                "trace_id": _tid,
            }
        msg = MessageBuilder.takeover_request(
            device_id=device_id,
            takeover_id=takeover_id,
            session_id=session_id,
            task_context=task_context,
            reason=reason,
            trace_id=trace_id,
            timeout=timeout,
        )
        logger.debug(
            "AndroidBridge.send_takeover_request: device_id=%s takeover_id=%s trace_id=%s",
            device_id,
            takeover_id,
            trace_id,
        )
        result = await self.send_to_device(device_id, msg, wait_response=False)

        # Notify the lifecycle coordinator so the takeover request is recorded
        # as a canonical orchestrated lifecycle event (session state transition
        # + audit) — not just a raw message send.
        if _get_lifecycle_coordinator is not None:
            try:
                _ctx_task_id = task_context.get("task_id", "") if isinstance(task_context, dict) else ""
                _get_lifecycle_coordinator().on_takeover_requested(
                    session_id=session_id or "",
                    takeover_id=takeover_id,
                    device_id=device_id,
                    task_id=_ctx_task_id,
                    trace_id=trace_id or "",
                )
            except Exception as _exc:  # noqa: BLE001
                logger.debug(
                    "send_takeover_request: coordinator notification failed "
                    "(non-fatal): takeover_id=%s exc=%s", takeover_id, _exc
                )

        return result

    def get_device(self, device_id: str) -> Optional[AndroidDevice]:
        """获取设备的传输/会话层缓存条目（transport cache view）."""
        return self._devices.get(device_id)

    def get_all_devices(self) -> List[AndroidDevice]:
        """获取所有设备的传输/会话层缓存列表（transport cache view）."""
        return list(self._devices.values())

    def get_connected_devices(self) -> List[AndroidDevice]:
        """获取已连接设备的传输/会话层缓存列表（transport cache view）."""
        return [d for d in self._devices.values() if d.connected]

    def get_android_devices(self) -> List[AndroidDevice]:
        """获取 Android 平台设备的传输/会话层缓存列表（transport cache view）.

        .. todo:: (PR-UDM-UNIFY) 此方法当前从本地 ``_devices`` 读取，而非 UDM。
            权威设备列表应在 UDM (UnifiedDeviceManager) 中查询：

                from core.unified.device_manager import UnifiedDeviceManager
                udm = UnifiedDeviceManager()
                udm_devices = udm.list_devices(platform=DevicePlatform.ANDROID)

            保留本地 ``_devices`` 仅用于 WebSocket 句柄查找（transport cache）。
            外部调用者应迁移至 UDM 查询。
        """
        return [d for d in self._devices.values()
                if d.platform == DevicePlatform.ANDROID and d.connected]

    async def disconnect_device(self, device_id: str):
        """断开设备连接。

        .. note:: (PR-UDM-UNIFY) 此方法保留对 ``_devices`` 的修改，因为需要同步
            关闭 WebSocket 连接句柄（transport session cleanup）。但权威状态
            变更已通过 ``_patch_disconnect_to_udm()`` 同步写入 UDM。
            ``_devices`` 中的状态是 **transport cache mirror**，不是 SSOT。
        """
        async with self._lock:
            if device_id in self._devices:
                self._devices[device_id].connected = False
                self._devices[device_id].websocket = None
                logger.info("Device disconnected: %s", device_id)
            self._sync_device_router_session(device_id, connected=False)
            self._patch_disconnect_to_udm(device_id)

        # PR-G: emit device lifecycle (detach) so the observability sink records
        # the disconnect event in the production path.
        try:
            from core.runtime.runtime_observability_sink import emit_device_lifecycle_event
            emit_device_lifecycle_event(
                device_id,
                event_kind="detach",
                prior_state="online",
                new_state="disconnected",
                reason="android_bridge_disconnect",
            )
        except Exception:
            pass

    async def cleanup_stale_devices(self, timeout_seconds: float = 120.0):
        """清理超时的设备。

        .. todo:: (PR-UDM-UNIFY) 此方法当前从本地 ``_devices`` 遍历心跳超时。
            权威设备在线状态和心跳信息应在 UDM / UCM 中查询：

                from core.unified.device_manager import UnifiedDeviceManager
                from core.unified.connection_manager import get_unified_connection_manager
                udm = UnifiedDeviceManager()
                stale = udm.get_stale_devices(timeout_seconds)  # 理想 UDM API

            当前实现保留本地遍历作为 operational fallback，但未来应迁移至
            UDM 统一查询，避免 transport cache 与权威状态之间的不一致。
        """
        current_time = time.time()
        stale_devices = []

        async with self._lock:
            for device_id, device in self._devices.items():
                if device.connected and (current_time - device.last_heartbeat) > timeout_seconds:
                    stale_devices.append(device_id)

        for device_id in stale_devices:
            await self.disconnect_device(device_id)
            # Discard buffered messages for permanently-stale devices so they
            # do not accumulate memory across long disconnections.
            await _pending_delivery_buffer.discard_device(device_id)
            logger.warning("Device timed out: %s", device_id)

        # Also sweep expired entries across all device queues.
        await _pending_delivery_buffer.purge_expired()

    async def reconnect_device(self, device_id: str, websocket: Any) -> bool:
        """重新连接设备（WebSocket 断线重连时调用）."""
        async with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                logger.warning("重连失败: 设备 %s 未曾注册", device_id)
                return False
            device.websocket = websocket
            device.connected = True
            device.last_heartbeat = time.time()

        self._patch_reconnect_to_udm(device_id)
        self._sync_device_router_session(device_id, websocket=websocket, connected=True)

        # V2 lifecycle mainline: reconnect attached session in AttachedSessionRegistry
        # so that runtime_session_id is preserved and the session returns to active.
        try:
            from core.attached_runtime_session_registry import (
                lookup_session_by_device,
                reconnect_session,
                get_session_registry,
            )
            # First try the active pointer; fall back to the most-recent
            # non-terminal entry (e.g. detached after a prior disconnect).
            _entry = lookup_session_by_device(device_id)
            if _entry is None:
                _reg = get_session_registry()
                for _e in _reg.list_all():
                    if _e.device_id == device_id and not _e.is_terminal():
                        _entry = _e
                        break
            if _entry is not None and not _entry.is_terminal():
                _updated = reconnect_session(
                    _entry,
                    metadata={"reconnect_source": "android_bridge"},
                )
                logger.info(
                    "AttachedSessionRegistry: session reconnected: "
                    "device_id=%s runtime_session_id=%s reconnect_count=%d",
                    device_id, _updated.runtime_session_id, _updated.reconnect_count,
                )
        except Exception as _asr_exc:
            logger.debug(
                "android_bridge: attached session reconnect non-fatal: device_id=%s error=%s",
                device_id, _asr_exc,
            )

        # V2 lifecycle mainline: restore any suspended mesh sessions associated
        # with this device so that mesh state comes back to ACTIVE after reconnect.
        try:
            from core.mesh.mesh_session_lifecycle import (
                get_lifecycle_coordinator,
                restore_durable_session,
            )
            _coord = get_lifecycle_coordinator()
            _session_ids = _coord.find_sessions_for_device(device_id)
            for _sid in _session_ids:
                _rec = _coord.get_record(_sid)
                if _rec is not None and _rec.status == "suspended":
                    restore_durable_session(_sid)
                    logger.info(
                        "Mesh session restored on device reconnect: device_id=%s session_id=%s",
                        device_id, _sid,
                    )
        except Exception as _mesh_exc:
            logger.debug(
                "android_bridge: mesh session restore non-fatal: device_id=%s error=%s",
                device_id, _mesh_exc,
            )

        logger.info("设备重连成功: %s", device_id)

        # Flush any messages that were buffered while the device was offline.
        # This re-delivers task-type messages that arrived during the disconnect
        # window, closing the INFLIGHT_TASK_LOSS_ON_DISCONNECT gap.
        try:
            async def _ws_send(msg: Dict[str, Any]) -> None:
                async with self._lock:
                    dev = self._devices.get(device_id)
                if dev and dev.connected and dev.websocket is not None:
                    await dev.websocket.send_json(msg)
                else:
                    raise RuntimeError(f"device {device_id} not connected during buffer flush")

            _delivered, _skipped = await _pending_delivery_buffer.flush(device_id, _ws_send)
            if _delivered or _skipped:
                logger.info(
                    "android_bridge: reconnect buffer flush — device_id=%s "
                    "delivered=%d skipped(expired)=%d",
                    device_id, _delivered, _skipped,
                )
        except Exception as _buf_exc:
            logger.warning(
                "android_bridge: reconnect buffer flush failed (non-fatal): "
                "device_id=%s error=%s",
                device_id, _buf_exc,
            )

        # PR-G: emit device lifecycle (reconnect) so the observability sink records
        # the reconnect event in the production path.
        try:
            from core.runtime.runtime_observability_sink import emit_device_lifecycle_event
            emit_device_lifecycle_event(
                device_id,
                event_kind="reconnect",
                prior_state="disconnected",
                new_state="online",
                reason="android_bridge_reconnect",
            )
        except Exception:
            pass

        return True

    def get_device_health(self) -> Dict[str, Any]:
        """获取所有设备的健康状态摘要（transport cache view）."""
        now = time.time()
        healthy = 0
        stale = 0
        disconnected = 0
        device_details = []
        for d in self._devices.values():
            if not d.connected:
                disconnected += 1
                status = "disconnected"
            elif now - d.last_heartbeat > 60:
                stale += 1
                status = "stale"
            else:
                healthy += 1
                status = "healthy"
            device_details.append({
                "device_id": d.device_id,
                "model": d.model,
                "status": status,
                "last_heartbeat_ago_s": round(now - d.last_heartbeat, 1) if d.last_heartbeat else None,
            })
        return {
            "total": len(self._devices),
            "healthy": healthy,
            "stale": stale,
            "disconnected": disconnected,
            "devices": device_details,
        }

    # =========================================================================
    # Backward-compatible _handle_* method wrappers (PR-3)
    # These preserve the old method-based API for tests and any callers that
    # invoke _handle_* directly on the AndroidBridge instance.
    # =========================================================================

    async def _handle_device_register(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_device_register(self, websocket, message)

    async def _handle_heartbeat(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_heartbeat(self, websocket, message)

    async def _handle_device_status(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_device_status(self, websocket, message)

    async def _handle_agent_ping(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_agent_ping(self, websocket, message)

    async def _handle_task_result(self, websocket: Any, message: Dict[str, Any]) -> None:
        return await handle_task_result(self, websocket, message)

    async def _handle_task_end(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_task_end(self, websocket, message)

    async def _handle_task_progress(self, websocket: Any, message: Dict[str, Any]) -> None:
        return await handle_task_progress(self, websocket, message)

    async def _handle_command_result(self, websocket: Any, message: Dict[str, Any]) -> None:
        return await handle_command_result(self, websocket, message)

    async def _handle_error(self, websocket: Any, message: Dict[str, Any]) -> None:
        return await handle_error(self, websocket, message)

    async def _handle_task_execute(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await handle_task_execute(self, websocket, message)

    async def _handle_task_submit(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await handle_task_submit(self, websocket, message)

    async def _handle_goal_execution(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await handle_goal_execution(self, websocket, message)

    async def _handle_parallel_subtask(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await handle_parallel_subtask(self, websocket, message)

    async def _handle_goal_execution_result(self, websocket: Any, message: Dict[str, Any]) -> None:
        return await handle_goal_execution_result(self, websocket, message)

    async def _handle_capability_report(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_capability_report(self, websocket, message)

    async def _handle_diagnostics_payload(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_diagnostics_payload(self, websocket, message)

    async def _handle_vision_request(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await handle_vision_request(self, websocket, message)

    async def _handle_generic_forward(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_generic_forward(self, websocket, message)

    async def _handle_task_cancel(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_task_cancel(self, websocket, message)

    async def _handle_task_status(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_task_status(self, websocket, message)

    async def _handle_session_migrate(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_session_migrate(self, websocket, message)

    async def _handle_unregistered(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_unregistered(self, websocket, message)


# =============================================================================
# 全局实例
# =============================================================================

android_bridge = AndroidBridge()
