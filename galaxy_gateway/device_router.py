"""
galaxy_gateway/device_router.py — Runtime Session / Routing Adapter
=====================================================================

**Unified-Subject Architecture — Runtime Session Adapter over Canonical State**
--------------------------------------------------------------------------------
``DeviceRouter`` is the **runtime session and routing substrate** for the
cross-device execution layer.  It is NOT a canonical device registry and must
not be treated as an alternate source of truth for device identity or state.

Authority model (PR-3)
----------------------
- **Canonical write SSOT**: :class:`~core.unified.device_manager.UnifiedDeviceManager`
  (UDM) — the only authoritative registry for device identity and mutable state.
- **Canonical read contract**: :class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice`
  — the stable projection of a runtime-capable device.
- **This module**: runtime session adapter — manages active WebSocket/transport
  connections, routes live tasks, and **patches canonical runtime state in UDM**
  for every connection lifecycle event (connect / disconnect).

Architectural boundary (PR-10) — routing substrate, NOT orchestration selector
-------------------------------------------------------------------------------
``DeviceRouter`` is a **routing and dispatch substrate**.  It selects the
transport path to a specific device and sends a pre-built task envelope.

NOT responsible for
~~~~~~~~~~~~~~~~~~~
- **Entry-mode decisioning** — which execution mode to use for a session.
  Resolved by the canonical orchestration layer in ``core/``.
- **Orchestration eligibility** — whether a device may participate in
  multi-device orchestration.  Assessed by
  :mod:`core.device_selection.canonical_device_selector`.
- **Formation / session truth** — the authoritative set of participating devices.
  Owned by UDM; see :class:`~core.unified.device_manager.UnifiedDeviceManager`.
- **Global readiness truth** — whether the full stack is ready to serve requests.
  Owned by :mod:`core.system_orchestrator`.

Any future code that needs to gate dispatch on orchestration eligibility or
readiness must call the canonical core layer first, then pass the resolved
target to this module for transport.

Local state policy
------------------
``DeviceRouter`` maintains a local ``self.devices`` table exclusively as an
**operational cache** for:

- active WebSocket / transport session handles needed for live task dispatch
- per-connection transport metadata (reconnect counters, etc.)
- routing feasibility checks against live connections

This local cache **must not** be treated as the device truth source.  All
connection lifecycle events (connect, disconnect) write canonical runtime state
through UDM via :meth:`_sync_connection_state_to_udm` before updating the
local cache.

Read paths
----------
Router code that needs to present device state should prefer UDM canonical
state via :meth:`get_canonical_device` and use router-local session data only
for runtime/transport enrichment via :meth:`get_enriched_device_view`.

数据流说明
----------
此模块是 ``galaxy_gateway/main.py`` 和 ``websocket_handler.py`` 使用的路由层。
设备注册状态由 :class:`DeviceRouter` 维护（运行时 WebSocket 连接表），
仅在连接活跃期间有效。

内部消息处理使用 AIP v3 标准字段；向设备发送的命令也使用 AIP v3 格式。
接入层（``websocket_handler.py``）负责通过 compat 层将所有 incoming 消息
规范化为 v3 格式后再传入此模块。

标准端点（参见 galaxy_gateway/app.py）
--------------------------------------
- WebSocket : ``/ws/device/{device_id}`` (primary), ``/ws/android`` (initial)
- REST      : ``/api/v1/devices/*``

Author: Manus AI
Version: 2.0 (PR-3: runtime session adapter normalisation)
Date: 2026-03-07
"""

# ---------------------------------------------------------------------------
# PR-10 transport-layer boundary sentinel
# Importing this sentinel from outside the gateway package signals that the
# import site is consuming routing/transport primitives only — not canonical
# readiness, orchestration eligibility, or formation truth.
# ---------------------------------------------------------------------------
DEVICE_ROUTER_TRANSPORT_AUTHORITY = "DEVICE_ROUTER::ROUTING_SUBSTRATE_ONLY"

# ---------------------------------------------------------------------------
# PR-518 / GAP-517-003: substrate-only enforcement for cross-device dispatch.
#
# DeviceRouter._dispatch_cross_device_task() is internal substrate execution
# plumbing invoked by route_task().  Direct calls from outside DeviceRouter
# (i.e. not originating from CommandRouter → DeviceRouter.route_task()) are
# legacy bypasses and must emit structured LEGACY_DISPATCH warnings.
# ---------------------------------------------------------------------------
DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY = (
    "DEVICE_ROUTER::CROSS_DEVICE_SUBSTRATE_ONLY_V1: "
    "_dispatch_cross_device_task() is internal substrate called by route_task(). "
    "External calls are legacy bypasses and emit LEGACY_DISPATCH warnings. "
    "Resolves GAP-517-003."
)

# ---------------------------------------------------------------------------
# PR-520 / GAP-517-004: explicit formation descriptor attachment sentinel.
#
# DeviceRouter._dispatch_cross_device_task() now calls resolve_formation()
# from core.device_formation at the start of every multi-device dispatch to
# produce an explicit canonical DeviceFormationGroup.  The group is attached
# to the result payload under the "formation" key so that callers and audit
# surfaces can inspect source device, primary execution device, participating
# members, and role assignments.  Resolves GAP-517-004.
# ---------------------------------------------------------------------------
DEVICE_ROUTER_FORMATION_DESCRIPTOR_ATTACHED = (
    "DEVICE_ROUTER::FORMATION_DESCRIPTOR_ATTACHED_V1: "
    "_dispatch_cross_device_task() resolves and attaches a canonical "
    "DeviceFormationGroup at the start of every cross-device dispatch. "
    "Resolves GAP-517-004."
)

# ---------------------------------------------------------------------------
# PR-519 / GAP-517-007: result surface closure sentinel.
#
# DeviceRouter.route_task() now calls surface_cross_device_result() on all
# representative result return paths so that cross-device outcomes are
# normalised into ResultEnvelope and surfaced through TaskGraphRuntime,
# ReplayFoundation, and CrossDeviceChainSingleton.  Resolves GAP-517-007.
# ---------------------------------------------------------------------------
from core.cross_device_result_surface import (  # noqa: E402
    CROSS_DEVICE_RESULT_SURFACE_INTEGRATED,
    surface_cross_device_result,
)

CROSS_DEVICE_RESULT_SURFACE_INTEGRATED  # re-export / sentinel reference

# ---------------------------------------------------------------------------
# PR-521 / GAP-517-006: control semantic separation sentinel.
#
# DeviceRouter.route_task() now explicitly separates source_device_id
# (the device that originated the request) from target_device_id (the
# device that executes it).  The execution mode (local, remote dispatch,
# takeover, hybrid) is derived and recorded in a ControlSemanticRecord via
# the multi-device control integrity runtime.
#
# Backward-compatibility: callers that only provide device_id (legacy) have
# it mapped to source_device_id so the semantic gap becomes visible without
# breaking existing call sites.  Resolves GAP-517-006.
# ---------------------------------------------------------------------------
DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION = (
    "DEVICE_ROUTER::CONTROL_SEMANTIC_SEPARATION_V1: "
    "route_task() and dispatch_task() now carry explicit source_device_id "
    "(originating device) and target_device_id (executing device) in task "
    "context, TaskEnvelope metadata, and ControlSemanticRecord integrity "
    "records.  Legacy callers providing only device_id are adapted "
    "transparently.  Resolves GAP-517-006."
)

import asyncio
import json
import logging
import time as _time
from typing import Dict, List, Optional, Any
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PR-4: Delegate routing concerns to specialised sub-modules under
# galaxy_gateway/routing/.  DeviceRouter remains the canonical public API;
# internal logic is now implemented in the sub-modules and called from here.
# ---------------------------------------------------------------------------
from galaxy_gateway.routing.policy import analyze_command as _routing_analyze_command  # noqa: E402
from galaxy_gateway.routing.device_selection import select_devices as _routing_select_devices  # noqa: E402
from galaxy_gateway.routing.dispatch import (  # noqa: E402
    build_aip_message as _routing_build_aip_message,
    dispatch_to_websocket as _routing_dispatch_to_websocket,
)
from galaxy_gateway.routing.health_policy import (  # noqa: E402
    is_device_available as _routing_is_device_available,
    is_device_online as _routing_is_device_online,
    filter_eligible_devices as _routing_filter_eligible_devices,
)

# Cross-device feature-flag (Round 4) — checked before any cross-device path.
from galaxy_gateway.cross_device_switch import (  # noqa: E402
    is_cross_device_enabled,
    make_disabled_response,
)
from galaxy_gateway.observability import (  # noqa: E402
    TraceContext,
    emit_gateway_log,
    get_gateway_metrics,
)

# 延迟导入以避免循环依赖
cross_device_coordinator = None

def get_cross_device_coordinator():
    global cross_device_coordinator
    if cross_device_coordinator is None:
        from galaxy_gateway.cross_device_coordinator import cross_device_coordinator as cdc
        cross_device_coordinator = cdc
    return cross_device_coordinator


from core.device_types import DeviceType, resolve_device_type  # noqa: E402

# Module-level import so the function can be patched in tests
from galaxy_gateway.capability_registry import get_gateway_capability_registry  # noqa: E402

# ---------------------------------------------------------------------------
# PR-S3: Single dispatch and orchestration authority sentinel.
#
# DeviceRouter is the canonical single entry for all device-bound task
# dispatch and cross-device orchestration decisions.  All callers that
# previously owned independent dispatch authority (AndroidBridge.assign_task,
# RepoCoordinator.dispatch_agent_to_android, etc.) must delegate to
# DeviceRouter.route_task() or DeviceRouter.dispatch_task().
# ---------------------------------------------------------------------------
CANONICAL_DISPATCH_AUTHORITY = "galaxy_gateway.device_router.DeviceRouter"


def _get_udm():
    """Lazily return the UnifiedDeviceManager singleton (avoids circular imports)."""
    try:
        from core.unified.device_manager import get_unified_device_manager
        return get_unified_device_manager()
    except Exception as _e:
        logger.debug("_get_udm: failed to obtain UDM singleton — %s", _e)
        return None


def map_device_type_to_platform(aip_device_type: str) -> str:
    """将 AIP v3 DeviceType 字符串映射为路由层平台大类（公共接口）。

    Example::

        >>> map_device_type_to_platform("android_phone")
        'android'
        >>> map_device_type_to_platform("windows_desktop")
        'windows'
    """
    return resolve_device_type(aip_device_type).value


class TaskType:
    """任务类型"""
    UI_AUTOMATION = "ui_automation"
    APP_CONTROL = "app_control"
    SYSTEM_CONTROL = "system_control"
    QUERY = "query"
    COMPOUND = "compound"
    CROSS_DEVICE = "cross_device"


class Device:
    """设备信息 — gateway 运行时包装层。

    内部使用 core.schemas.device.DeviceModel 存储设备数据，
    额外维护 WebSocket 连接引用（不可序列化，不放入 Pydantic 模型）。
    ``metadata`` 存储设备注册时上报的任意扩展字段（如自主执行能力标志）。
    """

    def __init__(
        self,
        device_id: str,
        device_type: str,
        capabilities: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ):
        from core.schemas.device import DeviceModel, DeviceCapabilityModel
        from core.device_types import DeviceStatus

        cap_models = [DeviceCapabilityModel(name=c) for c in capabilities]
        self._model = DeviceModel(
            device_id=device_id,
            device_type=device_type,
            name=device_id,
            status=DeviceStatus.ONLINE,
            capabilities=cap_models,
        )
        self.websocket = None
        # Free-form metadata dict (e.g. goal_execution_enabled, device_role)
        self.metadata: Dict[str, Any] = metadata or {}

    @property
    def device_id(self) -> str:
        return self._model.device_id

    @property
    def device_type(self) -> str:
        return self._model.device_type.value

    @property
    def capabilities(self) -> List[str]:
        return self._model.capability_names()

    @property
    def status(self) -> str:
        return self._model.status.value

    @status.setter
    def status(self, value: str) -> None:
        from core.device_types import DeviceStatus
        try:
            self._model.status = DeviceStatus(value.lower())
        except ValueError:
            self._model.status = DeviceStatus.UNKNOWN

    @property
    def last_seen(self) -> datetime:
        return datetime.fromtimestamp(self._model.last_seen)

    @last_seen.setter
    def last_seen(self, value: datetime) -> None:
        self._model.last_seen = value.timestamp()

    def to_dict(self) -> Dict[str, Any]:
        d = self._model.to_api_dict()
        d["last_seen"] = datetime.fromtimestamp(self._model.last_seen).isoformat()
        return d


class DeviceRouter:
    """Single dispatch and cross-device orchestration entry for the gateway.

    **Role (PR-3, PR-S3)**
    ----------------------
    ``DeviceRouter`` is the **canonical single entry for all device-bound task
    dispatch and cross-device orchestration decisions** (PR-S3 consolidation).
    It is also a **runtime session adapter** over canonical device state
    maintained by :class:`~core.unified.device_manager.UnifiedDeviceManager`
    (UDM).  It is NOT a peer device truth source.

    Dispatch authority (PR-S3)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~
    All device-bound tasks, commands, and actions must ultimately pass through
    :meth:`route_task` or :meth:`dispatch_task`.  Previously fragmented paths
    that held independent dispatch authority now delegate here:

    - ``AndroidBridge.assign_task`` → delegates to :meth:`dispatch_task`
    - ``RepoCoordinator.dispatch_agent_to_android`` → delegates to :meth:`route_task`
    - ``CrossDeviceCoordinator.execute_cross_device_task`` → DeviceRouter-internal
      coordinator only; external callers use :meth:`route_task`

    Android-specific action translation (click, swipe, etc.) remains in
    :class:`~galaxy_gateway.android_bridge.AndroidBridge` as an adapter layer;
    those adapters do not hold independent dispatch authority.

    Responsibilities
    ~~~~~~~~~~~~~~~~
    1. Manage active WebSocket / transport session handles for live task
       dispatch — the ``self.devices`` table is an **operational cache only**.
    2. Patch canonical runtime state in UDM for every connection lifecycle
       event via :meth:`_sync_connection_state_to_udm`.
    3. Route tasks to live connected devices using local session handles.
    4. Produce enriched device views by layering router-local session info
       on top of canonical UDM state via :meth:`get_enriched_device_view`.

    What it must NOT do
    ~~~~~~~~~~~~~~~~~~~
    - Act as the final authority for device identity or persistent state.
    - Allow loss of local session state to imply device deregistration.
    - Bypass UDM for canonical lifecycle writes.
    """

    def __init__(self):
        # Operational session cache — active WebSocket handles and transport metadata.
        # This is NOT the canonical device registry; it mirrors only live connections.
        self.devices: Dict[str, Device] = {}
        self.task_queue: Dict[str, Dict] = {}
        self.task_results: Dict[str, Dict] = {}
        self._task_events: Dict[str, asyncio.Event] = {}
        # Idempotency: seen task-result IDs.
        self._seen_task_result_ids: set = set()
    
    # ------------------------------------------------------------------
    # PR-3: Runtime lifecycle helpers — canonical state sync into UDM
    # ------------------------------------------------------------------

    def _build_runtime_presence_patch(
        self,
        connected: bool,
        transport: str = "websocket",
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a UDM ``upsert_device_state`` patch representing current
        runtime connection presence.

        This patch contains only the runtime-presence fields that the router
        is authorised to write (connection state, online/offline status, and
        last_seen).  It does NOT overwrite identity, capabilities, or any
        field outside the router's authority.

        Args:
            connected: ``True`` if the device has an active transport session;
                       ``False`` when the session has ended.
            transport: Transport mechanism label (default ``"websocket"``).
            session_id: Optional session identifier for the current connection.

        Returns:
            Dict ready for ``udm.upsert_device_state(device_id, patch, source)``.
        """
        status = "online" if connected else "offline"
        patch: Dict[str, Any] = {
            "status": status,
            "runtime_connection": {
                "connected": connected,
                "transport": transport,
                "last_seen": _time.time(),
            },
        }
        if session_id:
            patch["runtime_connection"]["session_id"] = session_id
        return patch

    def _sync_connection_state_to_udm(
        self,
        device_id: str,
        connected: bool,
        transport: str = "websocket",
        session_id: Optional[str] = None,
    ) -> bool:
        """Patch canonical runtime connection state into UDM.

        This is the central lifecycle write path that must be called for every
        connect and disconnect event so that canonical device state reflects
        the router's runtime observations.

        The patch writes only runtime-presence fields; it does NOT delete the
        device from UDM.  Loss of the router-local session entry must never
        erase the canonical device registration.

        Args:
            device_id: Device being updated.
            connected: ``True`` for connect events; ``False`` for disconnect.
            transport: Transport label (default ``"websocket"``).
            session_id: Optional active session identifier.

        Returns:
            ``True`` if the UDM patch succeeded; ``False`` otherwise (warning
            already logged — caller should still proceed with local cleanup).
        """
        udm = _get_udm()
        if udm is None:
            logger.debug(
                "_sync_connection_state_to_udm: UDM unavailable for %s connected=%s",
                device_id, connected,
            )
            return False
        try:
            patch = self._build_runtime_presence_patch(
                connected=connected, transport=transport, session_id=session_id
            )
            udm.upsert_device_state(device_id, patch, source="device_router")
            logger.debug(
                "_sync_connection_state_to_udm: patched UDM for %s connected=%s",
                device_id, connected,
            )
            return True
        except Exception as _e:
            logger.warning(
                "_sync_connection_state_to_udm: UDM patch failed for %s connected=%s — %s",
                device_id, connected, _e,
            )
            return False

    # ------------------------------------------------------------------
    # PR-3: Explicit connection lifecycle methods
    # ------------------------------------------------------------------

    def on_device_connected(
        self,
        device_id: str,
        websocket: Any = None,
        transport: str = "websocket",
        session_id: Optional[str] = None,
    ) -> None:
        """Record that a device transport session has been established.

        Patches canonical runtime state in UDM (online / connected) and
        updates the router-local session cache with the live transport handle.

        This is the preferred hook for connection-establishment events.
        Callers who go through :meth:`register_device` do not need to call
        this separately — ``register_device`` invokes it internally.
        """
        self._sync_connection_state_to_udm(
            device_id, connected=True, transport=transport, session_id=session_id
        )
        if device_id in self.devices and websocket is not None:
            self.devices[device_id].websocket = websocket

    def on_device_disconnected(
        self,
        device_id: str,
        transport: str = "websocket",
    ) -> None:
        """Record that a device transport session has ended.

        Patches canonical runtime state in UDM (offline / disconnected)
        WITHOUT deleting the canonical device registration, then removes
        the device from the router-local session cache.

        This preserves the invariant that loss of router-local session state
        must not erase canonical device registration.
        """
        self._sync_connection_state_to_udm(
            device_id, connected=False, transport=transport
        )
        # Remove from local operational cache (session handle gone)
        self.devices.pop(device_id, None)

    # ------------------------------------------------------------------
    # PR-3: Canonical read helpers
    # ------------------------------------------------------------------

    def get_canonical_device(self, device_id: str) -> Optional[Any]:
        """Fetch the canonical device record from UDM.

        Prefer this over ``self.devices.get(device_id)`` when you need
        identity / registration data rather than live session handles.

        Returns:
            A :class:`~core.unified.models.UnifiedDevice` instance if found,
            or ``None`` when UDM is unavailable or the device is not registered.
        """
        udm = _get_udm()
        if udm is None:
            return None
        try:
            return udm.get_device(device_id)
        except Exception as _e:
            logger.debug("get_canonical_device: UDM read failed for %s — %s", device_id, _e)
            return None

    def get_enriched_device_view(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Return a merged view of canonical UDM state enriched with router-local
        runtime session metadata.

        The canonical UDM record is the base; router-local data (WebSocket
        connection state, session_id, last_seen from local observation) is
        layered on top.  The result is suitable for status APIs and observability
        surfaces but must NOT be used as a writable state source.

        Returns:
            A plain dict with merged fields, or ``None`` if neither UDM nor
            local session cache has an entry for ``device_id``.
        """
        udm_device = self.get_canonical_device(device_id)
        local_device = self.devices.get(device_id)

        if udm_device is None and local_device is None:
            return None

        # Start with canonical UDM fields
        if udm_device is not None:
            view: Dict[str, Any] = {
                "device_id": udm_device.device_id,
                "device_name": getattr(udm_device, "device_name", ""),
                "device_type": (
                    udm_device.device_type.value
                    if hasattr(udm_device.device_type, "value")
                    else str(udm_device.device_type)
                ),
                "status": (
                    udm_device.status.value
                    if hasattr(udm_device.status, "value")
                    else str(udm_device.status)
                ),
                "capabilities": list(getattr(udm_device, "capabilities", []) or []),
                "source": "udm",
            }
        else:
            # Fallback: local session cache only
            view = local_device.to_dict()  # type: ignore[union-attr]
            view["source"] = "router_local"

        # Layer router-local runtime session enrichment on top
        if local_device is not None:
            view["router_session"] = {
                "has_active_websocket": local_device.websocket is not None,
                "local_status": local_device.status,
                "last_seen": local_device.last_seen.isoformat()
                if hasattr(local_device.last_seen, "isoformat")
                else str(local_device.last_seen),
            }

        return view

    def register_device(self, device_id: str, device_type: str,
                       capabilities: List[str], websocket=None,
                       metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Register a device and establish its runtime session in the router.

        Write order (PR-3):
        1. UDM SSOT write (canonical identity registration).
        2. Canonical runtime presence patch via ``_sync_connection_state_to_udm``
           (marks device as online / connected in canonical state).
        3. Local operational cache update (WebSocket session handle).
        """
        try:
            # ── SSOT: write to UDM first (identity registration) ──────────
            udm = _get_udm()
            if udm is not None:
                try:
                    udm.register_device_from_dict(device_id, {
                        "device_name": device_id,
                        "device_type": device_type,
                        "capabilities": capabilities,
                        "source": "device_router",
                        **(metadata or {}),
                    })
                    logger.debug("DeviceRouter.register_device: UDM write succeeded for %s", device_id)
                except Exception as _udm_err:
                    logger.warning(
                        "DeviceRouter.register_device: UDM write failed for %s — %s",
                        device_id, _udm_err,
                    )

            # ── PR-3: patch canonical runtime presence into UDM ───────────
            self._sync_connection_state_to_udm(device_id, connected=True)

            # ── Operational cache: store WebSocket session handle ─────────
            device = Device(device_id, device_type, capabilities, metadata=metadata)
            device.websocket = websocket
            self.devices[device_id] = device

            # 同步设备能力到 CapabilityRegistry
            try:
                from core.routes.devices import _sync_device_to_capability_registry
                device_info = {
                    "device_id": device_id,
                    "device_type": device_type,
                    "device_name": device_id,
                    "capabilities": capabilities,
                }
                _sync_device_to_capability_registry(device_info)
            except Exception as _sync_err:
                logger.warning(f"设备能力同步到 CapabilityRegistry 失败（不影响注册）: {_sync_err}")

            logger.info(f"✅ 设备注册成功: {device_id} ({device_type})")
            return True
            
        except Exception as e:
            logger.error(f"❌ 设备注册失败: {e}")
            return False
    
    def unregister_device(self, device_id: str) -> bool:
        """Remove the device's runtime session from the router.

        PR-3 authority model:
        - Patches canonical runtime state in UDM (offline / disconnected)
          via ``_sync_connection_state_to_udm``.  The canonical device
          registration is **preserved** in UDM — this call must never erase
          device identity from the canonical registry.
        - Removes the device from the local operational session cache.
        - Purges per-device entries from GatewayCapabilityRegistry.
        """
        try:
            # ── PR-3: patch canonical runtime presence (offline) into UDM ──
            # Do NOT call udm.unregister_device(); that would erase the canonical
            # device registration.  Loss of router-local session state must not
            # imply device deregistration.
            self._sync_connection_state_to_udm(device_id, connected=False)

            if device_id in self.devices:
                del self.devices[device_id]

                # Purge capabilities from GatewayCapabilityRegistry
                try:
                    purged = get_gateway_capability_registry().purge(device_id)
                    logger.debug(
                        "unregister_device: purged %d capabilities for device %s",
                        purged,
                        device_id,
                    )
                except Exception as _purge_err:
                    logger.warning(
                        "unregister_device: capability registry purge failed: %s", _purge_err
                    )

                logger.info(f"✅ 设备注销成功: {device_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"❌ 设备注销失败: {e}")
            return False
    
    def get_device(self, device_id: str) -> Optional[Device]:
        """获取设备"""
        return self.devices.get(device_id)
    
    def get_devices_by_type(self, device_type: str) -> List[Device]:
        """根据类型获取设备列表"""
        return [d for d in self.devices.values() if d.device_type == device_type]
    
    def get_devices_by_capability(self, capability: str) -> List[Device]:
        """根据能力获取设备列表"""
        return [d for d in self.devices.values() if capability in d.capabilities]
    
    async def route_task(self, command: str, context: Dict = None) -> Dict:
        """路由任务到合适的设备。

        PR-1: 在进入内部路由逻辑前，将 command/context 转换为 TaskEnvelope，
        用于统一 trace_id/task_id 传播。原有 context 字段与 AIP compat 规则
        保持兼容。

        PR-521 / GAP-517-006: context now explicitly carries ``source_device_id``
        (the device that originated the request) and ``target_device_id`` is
        derived from the routing decision.  Legacy callers that only supply
        ``device_id`` are adapted transparently: ``device_id`` is treated as
        the originating source.  A :class:`ControlSemanticRecord` is emitted
        to the integrity runtime after every routing decision so that
        local-execution, remote-dispatch, takeover, and hybrid paths are
        distinguishable in audit records.

        Args:
            command: 用户命令
            context: 上下文信息（支持 trace_id, route_mode, device_id,
                source_device_id, target_device_id, is_takeover 等字段）

        Returns:
            任务执行结果
        """
        metrics = get_gateway_metrics()
        metrics.inc("routing_total")
        _route_start = _time.monotonic()

        # Extract / generate trace context from incoming context dict.
        ctx = context or {}
        trace_ctx = TraceContext.from_message(ctx)
        # Propagate trace_id back into context so downstream callers can read it.
        if not ctx.get("trace_id"):
            ctx = dict(ctx)
            ctx["trace_id"] = trace_ctx.trace_id
            emit_gateway_log(
                "trace_id_injected",
                trace_ctx=trace_ctx,
                reason="missing_in_context",
                route_mode=ctx.get("route_mode", ""),
            )

        # PR-1: build a TaskEnvelope at the entry point for unified trace propagation.
        # The envelope carries trace_id/task_id/route_mode through the routing chain.
        # PR-521 / GAP-517-006: extract source_device_id before envelope construction
        # so it can be embedded in the envelope metadata for downstream audit.
        _entry_source_device_id = ctx.get("source_device_id", "") or ctx.get("device_id", "")
        try:
            from core.schemas.task_envelope import TaskEnvelope as _TaskEnvelope

            _task_id = ctx.get("task_id") or f"task_{uuid.uuid4().hex[:16]}"
            _device_id = ctx.get("device_id", "")
            _route_mode = ctx.get("route_mode", "")
            _route_envelope = _TaskEnvelope(
                task_id=_task_id,
                trace_id=trace_ctx.trace_id,
                source=ctx.get("source", "device_router"),
                targets=[_device_id] if _device_id else [],
                tool_name=command,
                args=ctx.get("payload") or {},
                metadata={
                    "route_mode": _route_mode,
                    "task_type": ctx.get("task_type", ""),
                    "context": ctx,
                    "source_device_id": _entry_source_device_id,
                },
            )
            # Propagate unified task_id and trace_id back into context so the
            # internal task dict and AIP messages share the same identifiers.
            ctx = dict(ctx)
            ctx["task_id"] = _route_envelope.task_id
            ctx["trace_id"] = _route_envelope.trace_id
            logger.debug(
                "DeviceRouter.route_task envelope | task_id=%s trace_id=%s "
                "route_mode=%s source_device_id=%s",
                _route_envelope.task_id,
                _route_envelope.trace_id,
                _route_mode,
                _entry_source_device_id,
            )
        except Exception as _env_err:
            # Never block routing on envelope construction failure.
            logger.debug("DeviceRouter.route_task: TaskEnvelope construction skipped — %s", _env_err)

        try:
            logger.info(f"🎯 开始路由任务: {command}")
            
            # 1. 分析命令，确定目标设备和任务类型
            analysis = await self._analyze_command(command, ctx)

            route_mode = ctx.get("route_mode", "")
            exec_mode = analysis.get("exec_mode", "both")
            capability = analysis.get("task_type", "")
            device_id = ctx.get("device_id", "")

            # PR-521 / GAP-517-006: resolve explicit source/target semantics.
            # source_device_id = device that originated the request.
            # If the caller provides source_device_id, prefer it.  For legacy
            # callers that only supply device_id, adapt it as the source so the
            # ambiguity is visible and non-preferred without breaking compat.
            source_device_id = ctx.get("source_device_id", "") or device_id

            emit_gateway_log(
                "dispatcher_selection",
                trace_ctx=trace_ctx,
                command=command[:120],
                route_mode=route_mode,
                exec_mode=exec_mode,
                capability=capability,
                device_id=device_id,
                source_device_id=source_device_id,
                requires_cross_device=analysis.get("requires_cross_device", False),
            )
            
            # 2. 判断是否需要跨设备协同
            if analysis.get("requires_cross_device", False):
                # --- Round 4: hard constraint — check cross-device switch ---
                if not is_cross_device_enabled():
                    emit_gateway_log(
                        "cross_device_blocked",
                        trace_ctx=trace_ctx,
                        level="warning",
                        reason="switch_disabled",
                        route_mode=route_mode,
                        exec_mode=exec_mode,
                        capability=capability,
                        device_id=device_id,
                    )
                    metrics.inc("routing_failure")
                    return make_disabled_response(trace_id=trace_ctx.trace_id)

                # --- Round 5: Agent Bridge handoff ---
                # Try delegating to the agent runtime before falling back to the
                # local cross-device coordinator.
                try:
                    from galaxy_gateway.agent_bridge import (
                        AgentBridge,
                        HandoffContract,
                        get_agent_bridge,
                    )

                    bridge = get_agent_bridge()
                    # Only attempt handoff when the bridge is configured and enabled.
                    if bridge._config.enabled:
                        contract = HandoffContract(
                            trace_id=trace_ctx.trace_id,
                            task={
                                "command": command,
                                "analysis": analysis,
                                "context": ctx,
                            },
                            capability=capability,
                            exec_mode=exec_mode,
                            route_mode=route_mode or "direct",
                            session=ctx.get("session", {}),
                            callback_channel=ctx.get("callback_channel", "ws"),
                        )

                        emit_gateway_log(
                            "bridge_handoff_start",
                            trace_ctx=trace_ctx,
                            device_id=device_id,
                            route_mode=route_mode,
                            exec_mode=exec_mode,
                            capability=capability,
                        )

                        async def _local_coordinator_fallback(task: dict) -> dict:
                            coordinator = get_cross_device_coordinator()
                            return await coordinator.execute_cross_device_task(
                                task.get("command", command),
                                task.get("context", ctx),
                                _substrate_caller="device_router.route_task",
                            )

                        result = await bridge.handoff(
                            contract=contract,
                            local_fallback=_local_coordinator_fallback,
                        )
                        _elapsed_ms = (_time.monotonic() - _route_start) * 1000
                        metrics.routing_latency_ms.observe(_elapsed_ms)
                        metrics.inc("routing_success")
                        return result
                except Exception as _bridge_err:
                    logger.warning(
                        "agent_bridge_import_error trace_id=%s error=%s; using coordinator",
                        trace_ctx.trace_id,
                        _bridge_err,
                    )

                # Use cross-device coordinator (fallback when bridge import failed)
                coordinator = get_cross_device_coordinator()
                result = await coordinator.execute_cross_device_task(
                    command, ctx,
                    _substrate_caller="device_router.route_task",
                )
                _elapsed_ms = (_time.monotonic() - _route_start) * 1000
                metrics.routing_latency_ms.observe(_elapsed_ms)
                metrics.inc("routing_success")
                return result
            
            # 3. 选择合适的设备
            target_devices = self._select_devices(analysis)
            
            if not target_devices:
                emit_gateway_log(
                    "routing_failed",
                    trace_ctx=trace_ctx,
                    level="warning",
                    reason="no_available_device",
                    route_mode=route_mode,
                    exec_mode=exec_mode,
                    capability=capability,
                )
                metrics.inc("routing_failure")
                return {
                    "success": False,
                    "error": "没有可用的设备执行此任务"
                }
            
            # 3. 创建任务
            task = self._create_task(command, analysis, target_devices)
            # Propagate trace context into the task payload
            task.update(trace_ctx.to_dict())
            # PR-521 / GAP-517-006: propagate explicit source_device_id into the
            # task dict so that downstream dispatch and audit surfaces can
            # distinguish origin from execution target.
            if source_device_id:
                task["source_device_id"] = source_device_id
            
            # 4. 分发任务
            if len(target_devices) == 1:
                # 单设备任务
                result = await self.dispatch_task(task, target_devices[0])
            else:
                # 多设备协同任务 (PR-518: pass substrate-caller sentinel)
                result = await self._dispatch_cross_device_task(
                    task, target_devices,
                    _substrate_caller="device_router.route_task",
                )

            _elapsed_ms = (_time.monotonic() - _route_start) * 1000
            metrics.routing_latency_ms.observe(_elapsed_ms)
            if result.get("success", False):
                metrics.inc("routing_success")
            else:
                metrics.inc("routing_failure")

            # PR-519 / GAP-517-007: surface result through canonical layers
            # before returning to caller.
            _task_id = task.get("task_id", ctx.get("task_id", ""))
            _target_ids = [getattr(d, "device_id", str(d)) for d in target_devices]
            surface_cross_device_result(
                result,
                task_id=_task_id,
                device_id=_target_ids[0] if _target_ids else "",
                trace_id=trace_ctx.trace_id,
                session_id=ctx.get("session_id"),
                route_mode=route_mode or ctx.get("route_mode", "cross_device"),
                source_device_id=source_device_id,
                target_device_ids=_target_ids,
            )

            # PR-521 / GAP-517-006: emit ControlSemanticRecord to the integrity
            # runtime with explicit source_device_id, target_device_id, and
            # execution mode.  This makes local-execution, remote-dispatch,
            # takeover, and hybrid (multi-device) paths distinguishable in audit
            # records without relying on an overloaded device_id field.
            try:
                from core.multi_device_control_integrity import (
                    record_integrity_event,
                    build_control_semantic_record,
                    ControlSemanticKind,
                )
                _primary_target_id = _target_ids[0] if _target_ids else ""
                _is_takeover = bool(ctx.get("is_takeover", False))
                if _is_takeover:
                    _ctl_kind = ControlSemanticKind.TAKEOVER
                elif len(_target_ids) > 1:
                    _ctl_kind = ControlSemanticKind.HYBRID
                elif (
                    source_device_id
                    and _primary_target_id
                    and source_device_id == _primary_target_id
                ):
                    _ctl_kind = ControlSemanticKind.LOCAL_EXECUTION
                elif _primary_target_id:
                    _ctl_kind = ControlSemanticKind.REMOTE_DISPATCH
                else:
                    _ctl_kind = ControlSemanticKind.UNKNOWN
                _crec = build_control_semantic_record(
                    task_id=_task_id,
                    trace_id=trace_ctx.trace_id,
                    source_device_id=source_device_id,
                    target_device_id=_primary_target_id,
                    control_kind=_ctl_kind,
                    is_takeover=_is_takeover,
                )
                record_integrity_event(control_record=_crec)
                logger.debug(
                    "DeviceRouter.route_task ControlSemanticRecord | "
                    "task_id=%s source=%s target=%s kind=%s clear=%s",
                    _task_id,
                    source_device_id,
                    _primary_target_id,
                    _ctl_kind.value,
                    _crec.is_semantically_clear,
                )
            except Exception as _csrec_err:
                logger.debug(
                    "DeviceRouter.route_task: ControlSemanticRecord recording skipped — %s",
                    _csrec_err,
                )  # integrity recording is advisory

            return result

        except Exception as e:
            _elapsed_ms = (_time.monotonic() - _route_start) * 1000
            metrics.routing_latency_ms.observe(_elapsed_ms)
            metrics.inc("routing_failure")
            emit_gateway_log(
                "routing_failed",
                trace_ctx=trace_ctx,
                level="error",
                cause=str(e),
                route_mode=(context or {}).get("route_mode", ""),
            )
            logger.error(f"❌ 任务路由失败: {e}")
            _err_result = {
                "success": False,
                "error": f"任务路由失败: {str(e)}"
            }
            # PR-519: surface failure results for audit visibility
            surface_cross_device_result(
                _err_result,
                task_id=ctx.get("task_id", ""),
                trace_id=trace_ctx.trace_id,
                route_mode=(context or {}).get("route_mode", "cross_device"),
            )
            return _err_result

    async def _analyze_command(self, command: str, context: Dict = None) -> Dict:
        """分析命令，确定目标设备和任务类型。

        Delegates to :func:`galaxy_gateway.routing.policy.analyze_command`
        (PR-4: routing policy separation).
        """
        return _routing_analyze_command(command, context)
    
    def _select_devices(self, analysis: Dict) -> List[Device]:
        """选择合适的设备（优先选择自主执行能力的设备），并尊重 exec_mode。

        PR-4: Delegates to :func:`galaxy_gateway.routing.device_selection.select_devices`
        for the exec_mode filtering, autonomous preference, and pool-manager
        selection steps.  This method retains responsibility for resolving
        ``target_device_type`` and obtaining the candidate list from the
        local session cache.
        """
        target_device_type = analysis["target_device_type"]

        if target_device_type == DeviceType.UNKNOWN:
            # 如果未指定设备，默认选择 Windows
            target_device_type = DeviceType.WINDOWS

        # Obtain candidate devices of the required type from the session cache.
        candidates = self.get_devices_by_type(target_device_type)

        if not candidates:
            logger.warning("⚠️ 没有在线的 %s 设备", target_device_type)
            return []

        # Ensure target_device_type is reflected in the analysis passed down.
        effective_analysis = dict(analysis)
        effective_analysis["target_device_type"] = target_device_type

        return _routing_select_devices(effective_analysis, candidates)
    
    def _create_task(self, command: str, analysis: Dict, target_devices: List[Device]) -> Dict:
        """创建任务"""
        task_id = str(uuid.uuid4())
        
        task = {
            "task_id": task_id,
            "command": command,
            "analysis": analysis,
            "target_devices": [d.device_id for d in target_devices],
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "payload": self._build_task_payload(analysis)
        }
        
        self.task_queue[task_id] = task
        return task
    
    def _build_task_payload(self, analysis: Dict) -> Dict:
        """构建任务 Payload"""
        payload = {
            "task_type": analysis["task_type"],
            "action": analysis["actions"][0] if analysis["actions"] else "",
            "target": "",
            "params": {}
        }
        
        # 根据任务类型构建具体参数
        # 这里是简化版本，实际应该更复杂
        
        return payload

    @staticmethod
    def _extract_tool_name(task: Dict) -> str:
        """PR-2: 从任务字典中提取工具名称（按优先级：action > task_type > command > 默认）。"""
        payload = task.get("payload") or {}
        return (
            payload.get("action")
            or payload.get("task_type")
            or task.get("command", "execute")
        )

    async def dispatch_task(self, task: Dict, device: Device) -> Dict:
        """分发单设备任务（公共 API，供跨模块调用）。

        PR-2：内部优先使用 TaskEnvelope + route_envelope 统一链路；
        仅当 CommandRouter 不可用时才降级到 WebSocket 直发。

        PR-7: ``remote_execution_mode`` is propagated from the task dict into
        the TaskEnvelope so that both ``command_only`` and ``agent_runtime``
        dispatches traverse the same substrate path with the mode label intact.
        """
        try:
            logger.info(f"📤 分发任务到设备: {device.device_id}")

            # PR-2: convert task dict → TaskEnvelope → route_envelope
            # (replaces the legacy CommandRequest + dispatch path).
            try:
                from core.schemas.task_envelope import TaskEnvelope as _TaskEnvelope
                from core.command_router import get_command_router
                cmd_router = get_command_router()
                if cmd_router._executor is not None:
                    _tool = self._extract_tool_name(task)
                    _args = task.get("payload", {}).get("params") or task.get("payload", {})
                    # PR-7: carry remote_execution_mode through the substrate envelope
                    _rem_mode_str = task.get("remote_execution_mode", "")
                    _rem_mode = None
                    if _rem_mode_str:
                        try:
                            from core.schemas.remote_execution import RemoteExecutionMode as _REM
                            _rem_mode = _REM(_rem_mode_str)
                        except Exception:
                            pass
                    _task_envelope = _TaskEnvelope(
                        task_id=task.get("task_id") or str(uuid.uuid4()),
                        trace_id=task.get("trace_id"),
                        source="device_router",
                        targets=[device.device_id],
                        tool_name=_tool,
                        args=_args if isinstance(_args, dict) else {},
                        remote_execution_mode=_rem_mode,
                        metadata={
                            "command": task.get("command", ""),
                            "device_router": "true",
                            "source_device_id": task.get("source_device_id", ""),
                            "target_device_id": device.device_id,
                        },
                    )
                    logger.debug(
                        "DeviceRouter.dispatch_task envelope | task_id=%s trace_id=%s "
                        "tool=%s device=%s mode=%s",
                        _task_envelope.task_id,
                        _task_envelope.trace_id,
                        _task_envelope.tool_name,
                        device.device_id,
                        _rem_mode_str or "unset",
                    )
                    cr_result = await cmd_router.route_envelope(_task_envelope)
                    return {
                        "success": cr_result.get("success", False),
                        "result": cr_result.get("result"),
                        "error": cr_result.get("error_message"),
                        "task_id": cr_result.get("task_id"),
                        "trace_id": cr_result.get("trace_id"),
                        "remote_execution_mode": cr_result.get("remote_execution_mode", _rem_mode_str),
                    }
            except Exception as route_err:
                logger.debug(f"route_envelope 路由失败，回退 WebSocket: {route_err}")

            # PR-4: WebSocket fallback — delegate send/wait to routing.dispatch.
            if device.websocket:
                task_id = task["task_id"]

                # PR-S5: use envelope timeout if available; fall back to 30 s.
                _ws_timeout = 30.0
                try:
                    if _task_envelope is not None:
                        _ws_timeout = _task_envelope.timeout
                except Exception:
                    pass

                _ws_message = _routing_build_aip_message(
                    device_id=device.device_id,
                    task_id=task_id,
                    trace_id=task.get("trace_id", ""),
                    command=task.get("command", ""),
                    payload=task.get("payload"),
                )
                ws_result = await _routing_dispatch_to_websocket(
                    device=device,
                    message=_ws_message,
                    task_id=task_id,
                    task_events=self._task_events,
                    task_results=self.task_results,
                    timeout=_ws_timeout,
                )
                if not ws_result.get("success") and ws_result.get("error") == "timeout":
                    return {"success": False, "error": "任务执行超时"}
                return ws_result
            else:
                return {"success": False, "error": "设备未连接"}

        except Exception as e:
            logger.error(f"❌ 任务分发失败: {e}")
            return {"success": False, "error": f"任务分发失败: {str(e)}"}

    # ------------------------------------------------------------------
    # Canonical transport method — called by CommandRouter (canonical chain)
    # ------------------------------------------------------------------

    async def send_command_to_device(
        self,
        device_id: str,
        command: str,
        payload: Dict,
        task_id: str = "",
        trace_id: str = "",
        timeout: float = 30.0,
    ) -> Optional[Dict]:
        """Send a command directly to a device via its live WebSocket session.

        **Canonical chain role**: This is the terminal transport step in the
        canonical execution chain::

            CommandRouter._dispatch_via_device_router()
                → DeviceRouter.send_command_to_device()  ← here
                    → device.websocket.send()

        This method is the single point where ``DeviceRouter`` performs
        device-targeted WebSocket dispatch on behalf of ``CommandRouter``.
        It intentionally does **not** call back into ``CommandRouter`` to
        avoid circular invocation.

        Args:
            device_id: Target device identifier.
            command:   Command name / action.
            payload:   Command parameters dict.
            task_id:   Task identifier (propagated for tracing).
            trace_id:  Distributed trace identifier.
            timeout:   WebSocket send / wait timeout in seconds.

        Returns:
            ``{"success": True/False, "result": ..., "task_id": ...,
               "trace_id": ..., "via": "device_router"}``
            or ``None`` when the device is not found in the live session
            table (caller should fall back to ``connection_manager``).
        """
        device = self.get_device(device_id)
        if device is None:
            logger.debug(
                "DeviceRouter.send_command_to_device: device %s not in session table",
                device_id,
            )
            return None

        _task_id = task_id or str(uuid.uuid4())
        _trace_id = trace_id or f"trace_{uuid.uuid4().hex[:12]}"

        if not device.websocket:
            logger.debug(
                "DeviceRouter.send_command_to_device: device %s has no websocket",
                device_id,
            )
            return {
                "success": False,
                "result": None,
                "error": f"device {device_id} has no active websocket",
                "task_id": _task_id,
                "trace_id": _trace_id,
                "via": "device_router",
            }

        # PR-4: delegate AIP message construction and send/wait to routing.dispatch.
        message = _routing_build_aip_message(
            device_id=device_id,
            task_id=_task_id,
            trace_id=_trace_id,
            command=command,
            payload=payload,
        )
        return await _routing_dispatch_to_websocket(
            device=device,
            message=message,
            task_id=_task_id,
            task_events=self._task_events,
            task_results=self.task_results,
            timeout=timeout,
        )

    async def _dispatch_cross_device_task(
        self,
        task: Dict,
        devices: List[Device],
        *,
        _substrate_caller: str = "",
    ) -> Dict:
        """分发跨设备协同任务 (gated by cross-device switch — Round 4).

        PR-2：将任务字典转换为 TaskEnvelope 进行子任务分解和结果汇总，
        确保内部唯一任务格式。

        PR-518/GAP-517-003: This method is internal substrate execution
        plumbing invoked only by :meth:`route_task`.  External calls that
        arrive without ``_substrate_caller`` set are non-canonical legacy
        bypasses; they emit a structured ``LEGACY_DISPATCH`` warning and
        record an integrity event before proceeding (fail-open).
        """
        # ── PR-518/GAP-517-003: Substrate-caller guard ───────────────────────
        _is_canonical_call = bool(_substrate_caller)
        if not _is_canonical_call:
            logger.warning(
                "LEGACY_DISPATCH | DeviceRouter._dispatch_cross_device_task "
                "called without a canonical substrate caller.  "
                "Callers must route through CommandRouter.route_envelope() → "
                "DeviceRouter.route_task() → this method. "
                "task_id=%r  (GAP-517-003 bypass detected)",
                task.get("task_id", ""),
            )
            try:
                from core.multi_device_control_integrity import (
                    record_integrity_event,
                    build_dispatch_authority_record,
                    DispatchPathKind,
                )
                _rec = build_dispatch_authority_record(
                    task_id=task.get("task_id", ""),
                    dispatch_path=DispatchPathKind.PARALLEL_LEGACY,
                    is_canonical=False,
                    caller_module="unknown",
                )
                record_integrity_event(_rec)
            except Exception:
                pass  # integrity recording is advisory

        # --- Round 4: hard constraint — single dispatcher guard ---
        if not is_cross_device_enabled():
            trace_id = task.get("trace_id")
            return make_disabled_response(trace_id=trace_id)
        try:
            logger.info(f"🔄 分发跨设备任务到 {len(devices)} 个设备")

            # PR-2: create a parent TaskEnvelope for cross-device coordination.
            try:
                from core.schemas.task_envelope import TaskEnvelope as _TaskEnvelope
                _parent_envelope = _TaskEnvelope(
                    task_id=task.get("task_id") or str(uuid.uuid4()),
                    trace_id=task.get("trace_id"),
                    source="device_router.cross_device",
                    targets=[d.device_id for d in devices],
                    tool_name=task.get("command", "cross_device"),
                    args=task.get("payload", {}),
                    metadata={"cross_device": "true", "device_count": str(len(devices))},
                )
                logger.debug(
                    "DeviceRouter._dispatch_cross_device_task envelope | "
                    "task_id=%s trace_id=%s devices=%s",
                    _parent_envelope.task_id,
                    _parent_envelope.trace_id,
                    [d.device_id for d in devices],
                )
                # Propagate envelope ids into the task dict for subtask creation.
                task = dict(task)
                task["task_id"] = _parent_envelope.task_id
                task["trace_id"] = _parent_envelope.trace_id
            except Exception as _env_err:
                logger.debug(
                    "DeviceRouter._dispatch_cross_device_task: TaskEnvelope skipped — %s", _env_err
                )

            # PR-520 / GAP-517-004: resolve and attach an explicit canonical
            # DeviceFormationGroup before dispatching sub-tasks.  The group
            # captures source device, primary execution device, all participating
            # members, and their role assignments so that formation truth is
            # explicit and auditable rather than implicit.
            _formation_group = None
            _formation_dict: dict = {}
            try:
                from core.device_formation.formation_resolver import resolve_formation
                _device_ids = [d.device_id for d in devices]
                _source_device_id = task.get("source_device_id", "")
                _primary_device_id = _device_ids[0] if _device_ids else ""
                _formation_group, _formation_policy = resolve_formation(
                    runtime_domain="cross_device",
                    source_device_id=_source_device_id,
                    primary_device_id=_primary_device_id,
                    target_device_ids=_device_ids,
                    task_id=task.get("task_id", ""),
                    trace_id=task.get("trace_id"),
                    formation_reason="DeviceRouter._dispatch_cross_device_task",
                )
                _formation_dict = _formation_group.to_dict()
                logger.debug(
                    "DeviceRouter._dispatch_cross_device_task formation | "
                    "formation_id=%s source=%s primary=%s members=%d",
                    _formation_group.formation_id,
                    _formation_group.source_device_id,
                    _formation_group.primary_execution_device_id,
                    len(_formation_group.members),
                )
                # Record formation truth in integrity runtime
                try:
                    from core.multi_device_control_integrity import (
                        record_integrity_event,
                        build_formation_truth_record,
                        FormationTruthConsistency,
                    )
                    _frec = build_formation_truth_record(
                        task_id=task.get("task_id", ""),
                        trace_id=task.get("trace_id"),
                        formation_id=_formation_group.formation_id,
                        consistency=FormationTruthConsistency.CONSISTENT,
                        member_device_ids=_device_ids,
                        source_device_id=_source_device_id,
                        primary_device_id=_primary_device_id,
                    )
                    record_integrity_event(formation_record=_frec)
                except Exception as _rec_err:
                    logger.debug(
                        "DeviceRouter._dispatch_cross_device_task: "
                        "integrity recording skipped — %s",
                        _rec_err,
                    )  # integrity recording is advisory
            except Exception as _form_err:
                logger.warning(
                    "DeviceRouter._dispatch_cross_device_task: formation resolution failed — %s "
                    "(GAP-517-004: proceeding without explicit formation descriptor)",
                    _form_err,
                )

            # 将任务分解为多个子任务
            subtasks = self._decompose_task(task, devices)
            
            # 并行执行所有子任务
            results = await asyncio.gather(
                *[self.dispatch_task(subtask, device) 
                  for subtask, device in zip(subtasks, devices)],
                return_exceptions=True
            )
            
            # 汇总结果
            success = all(r.get("success", False) for r in results if isinstance(r, dict))

            _result: dict = {
                "success": success,
                "subtask_results": results,
                "message": "跨设备任务执行完成" if success else "部分子任务执行失败",
            }
            # PR-520 / GAP-517-004: attach the canonical formation descriptor
            # to the result so that callers and audit surfaces can inspect it.
            if _formation_dict:
                _result["formation"] = _formation_dict
            return _result
            
        except Exception as e:
            logger.error(f"❌ 跨设备任务分发失败: {e}")
            return {
                "success": False,
                "error": f"跨设备任务分发失败: {str(e)}"
            }
    
    def _decompose_task(self, task: Dict, devices: List[Device]) -> List[Dict]:
        """将跨设备任务分解为多个子任务"""
        # 简化版本：每个设备执行相同的任务
        # 实际应该根据任务类型智能分解
        return [task.copy() for _ in devices]
    
    async def handle_task_result(self, task_id: str, result: Dict):
        """处理任务执行结果（幂等：同一 task_id 的重复结果将被忽略）。"""
        try:
            # ── Idempotency: ignore duplicate task results ──
            if task_id in self._seen_task_result_ids:
                logger.info(
                    "Duplicate task result ignored by device_router",
                    extra={
                        "event": "task_result_duplicate_ignored",
                        "task_id": task_id,
                    },
                )
                return
            self._seen_task_result_ids.add(task_id)

            self.task_results[task_id] = result

            # Signal the waiting event if any
            event = self._task_events.get(task_id)
            if event:
                event.set()

            if task_id in self.task_queue:
                task = self.task_queue[task_id]
                task["status"] = "completed" if result.get("success") else "failed"
                task["result"] = result
                task["completed_at"] = datetime.now().isoformat()

            # ── 并行闭环：secondary coverage — 若 result 携带并行字段则记录 ──
            if result.get("group_id"):
                try:
                    from galaxy_gateway.orchestrator.parallel_tracker import record_parallel_fields
                    parallel_payload = {
                        **result,
                        # derive status from success field when not explicitly set
                        "status": result.get("status") or (
                            "success" if result.get("success") else "failed"
                        ),
                    }
                    await record_parallel_fields(parallel_payload)
                except Exception as _pt_err:
                    logger.warning("parallel_tracker[device_router]: record failed: %s", _pt_err)

            logger.info(f"✅ 任务结果已记录: {task_id}")
            
        except Exception as e:
            logger.error(f"❌ 处理任务结果失败: {e}")
    
    @staticmethod
    def aggregate_results(results: List[Dict]) -> Dict:
        """Aggregate multi-device task results into a unified summary."""
        success_count = sum(1 for r in results if r.get("success"))
        failure_count = len(results) - success_count
        results_by_device = {}
        for r in results:
            device_id = r.get("device_id", "unknown")
            results_by_device[device_id] = r
        return {
            "total": len(results),
            "success_count": success_count,
            "failure_count": failure_count,
            "overall_success": failure_count == 0 and len(results) > 0,
            "results_by_device": results_by_device,
        }

    def get_device_status(self) -> Dict:
        """获取所有设备状态（SSOT: UDM，本地 self.devices 补充遗留 WebSocket 连接信息）"""
        udm = _get_udm()
        if udm is not None:
            try:
                udm_devices = udm.list_devices()
                # Build result from UDM as SSOT
                udm_result = {
                    "total_devices": len(udm_devices),
                    "online_devices": sum(
                        1 for d in udm_devices
                        if str(getattr(d.status, "value", d.status)).lower() in ("online", "busy")
                    ),
                    "devices": [
                        {
                            "device_id": d.device_id,
                            "device_name": d.device_name,
                            "device_type": d.device_type.value if hasattr(d.device_type, "value") else str(d.device_type),
                            "status": d.status.value if hasattr(d.status, "value") else str(d.status),
                            "capabilities": list(d.capabilities or []),
                            "source": "udm",
                        }
                        for d in udm_devices
                    ],
                }
                # Merge in WebSocket connection info from local table (read-only supplement)
                local_ids = {d["device_id"] for d in udm_result["devices"]}
                for did, dev in self.devices.items():
                    if did not in local_ids:
                        udm_result["devices"].append(dev.to_dict())
                        udm_result["total_devices"] += 1
                        if dev.status == "online":
                            udm_result["online_devices"] += 1
                return udm_result
            except Exception as _udm_err:
                logger.warning("get_device_status: UDM read failed, falling back to local table — %s", _udm_err)

        # Fallback: local connection table only
        return {
            "total_devices": len(self.devices),
            "online_devices": len([d for d in self.devices.values() if d.status == "online"]),
            "devices": [d.to_dict() for d in self.devices.values()]
        }


# 全局设备路由器实例
device_router = DeviceRouter()
