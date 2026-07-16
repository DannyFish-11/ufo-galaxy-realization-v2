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
# ---------------------------------------------------------------------------
DEVICE_ROUTER_TRANSPORT_AUTHORITY = "DEVICE_ROUTER::ROUTING_SUBSTRATE_ONLY"

# ---------------------------------------------------------------------------
# PR-518 / GAP-517-003: substrate-only enforcement for cross-device dispatch.
# ---------------------------------------------------------------------------
DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY = (
    "DEVICE_ROUTER::CROSS_DEVICE_SUBSTRATE_ONLY_V1: "
    "_dispatch_cross_device_task() is internal substrate called by route_task(). "
    "External calls are legacy bypasses and emit LEGACY_DISPATCH warnings. "
    "Resolves GAP-517-003."
)

# ---------------------------------------------------------------------------
# PR-520 / GAP-517-004: explicit formation descriptor attachment sentinel.
# ---------------------------------------------------------------------------
DEVICE_ROUTER_FORMATION_DESCRIPTOR_ATTACHED = (
    "DEVICE_ROUTER::FORMATION_DESCRIPTOR_ATTACHED_V1: "
    "_dispatch_cross_device_task() resolves and attaches a canonical "
    "DeviceFormationGroup at the start of every cross-device dispatch. "
    "Resolves GAP-517-004."
)

# ---------------------------------------------------------------------------
# PR-519 / GAP-517-007: result surface closure sentinel.
# ---------------------------------------------------------------------------
from core.cross_device_result_surface import (  # noqa: E402
    CROSS_DEVICE_RESULT_SURFACE_INTEGRATED,
    surface_cross_device_result,
)

CROSS_DEVICE_RESULT_SURFACE_INTEGRATED  # re-export / sentinel reference

# ---------------------------------------------------------------------------
# PR-521 / GAP-517-006: control semantic separation sentinel.
# ---------------------------------------------------------------------------
DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION = (
    "DEVICE_ROUTER::CONTROL_SEMANTIC_SEPARATION_V1: "
    "route_task() and dispatch_task() now carry explicit source_device_id "
    "(originating device) and target_device_id (executing device) in task "
    "context, TaskEnvelope metadata, and ControlSemanticRecord integrity "
    "records.  Legacy callers providing only device_id are adapted "
    "transparently.  Resolves GAP-517-006."
)

# PR-3 (UCS follow-up): CommandRouter pre-analysis passthrough sentinel.
DEVICE_ROUTER_COMMAND_ANALYSIS_GOVERNANCE_SENTINEL: str = (
    "DEVICE_ROUTER::COMMAND_ANALYSIS_GOVERNANCE_V1: "
    "_analyze_command() is policy logic that belongs in CommandRouter "
    "(decision authority layer), not DeviceRouter (dispatch substrate). "
    "When context['_command_router_pre_analyzed']==True and "
    "context['_pre_analysis'] is present, route_task() uses the pre-resolved "
    "analysis and skips re-analysis to reduce duplicated policy authority. "
    "Partially closes SCHED-003."
)

# ---------------------------------------------------------------------------
# PR-2 (post-533 dual-repo runtime host unification): posture-aware dispatch
# sentinel.
# ---------------------------------------------------------------------------
DEVICE_ROUTER_POSTURE_AWARE_DISPATCH = (
    "DEVICE_ROUTER::POSTURE_AWARE_DISPATCH_V1: "
    "route_task() evaluates source_runtime_posture via "
    "core.source_execution_eligibility.check_source_execution_eligibility(). "
    "'control_only' gates source-side local execution off. "
    "'join_runtime' allows source participation if otherwise eligible. "
    "PR-2, post-533 dual-repo runtime host unification track."
)

# PR-ALIGN / ADMIT-003: Participation eligibility filter before formation.
DEVICE_ROUTER_FORMATION_PARTICIPATION_FILTERED: str = (
    "DEVICE_ROUTER::FORMATION_PARTICIPATION_FILTERED_V1: "
    "_dispatch_cross_device_task() filters device list through "
    "core.device_participation.get_device_participation() before calling "
    "resolve_formation().  Non-eligible devices are excluded with a structured "
    "warning.  Graceful degradation if participation module unavailable. "
    "Resolves ADMIT-003."
)

# PR-3 (post-533 dual-repo runtime host unification): canonical handoff path
# authority propagation sentinel.
DEVICE_ROUTER_HANDOFF_AUTHORITY_PROPAGATION = (
    "DEVICE_ROUTER::HANDOFF_AUTHORITY_PROPAGATION_V1: "
    "route_task() derives coordination_role from posture via "
    "core.multi_device_coordination_authority.derive_coordination_role() "
    "and passes it to HandoffContract so authority flows without loss through "
    "the canonical bridge handoff path (NO_AUTHORITY_SILENT_DROP_POLICY). "
    "PR-3, post-533 dual-repo runtime host unification track."
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
from core.unified.gateway_capability_projection import (  # noqa: E402
    purge_gateway_capabilities_for_device,
)

# ---------------------------------------------------------------------------
# PR-02: Import dispatch boundary constants from the single authoritative
# source of truth.  These constants replace inline string literals that were
# previously scattered throughout route_task() and related methods.
# ---------------------------------------------------------------------------
from core.cross_device_dispatch_boundary import (  # noqa: E402
    DISPATCH_PATH_CANONICAL,
    DISPATCH_PATH_CONTROLLED_FALLBACK,
    CROSS_DEVICE_DISPATCH_PR02_SENTINEL,
)

CROSS_DEVICE_DISPATCH_PR02_SENTINEL  # re-export / module-level reference

# ---------------------------------------------------------------------------
# PR-S3: Single dispatch and orchestration authority sentinel.
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
                device_id,
                connected,
            )
            return False
        try:
            patch = self._build_runtime_presence_patch(connected=connected, transport=transport, session_id=session_id)
            udm.upsert_device_state(device_id, patch, source="device_router")
            logger.debug(
                "_sync_connection_state_to_udm: patched UDM for %s connected=%s",
                device_id,
                connected,
            )
            return True
        except Exception as _e:
            logger.warning(
                "_sync_connection_state_to_udm: UDM patch failed for %s connected=%s — %s",
                device_id,
                connected,
                _e,
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
        self._sync_connection_state_to_udm(device_id, connected=True, transport=transport, session_id=session_id)
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
        self._sync_connection_state_to_udm(device_id, connected=False, transport=transport)
        # Remove from local operational cache (session handle gone)
        self.clear_live_session(device_id)

    def ensure_live_session(
        self,
        device_id: str,
        device_type: str,
        capabilities: List[str],
        websocket: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
        transport: str = "websocket",
        session_id: Optional[str] = None,
    ) -> None:
        """Ensure the router has a live transport session without rewriting canonical identity.

        Creates a router-local operational cache entry when the device is absent
        from ``self.devices`` and otherwise updates the existing one in place.
        This method is intended for transport/session adapters that already
        wrote canonical identity to UDM and only need DeviceRouter to become
        live-routable.

        Args:
            device_id: Canonical device identifier.
            device_type: Router platform type (for example ``android``).
            capabilities: Device capabilities for the router-local cache entry.
            websocket: Active transport handle to attach to the session.
            metadata: Optional transport/runtime metadata for the cache entry.
            transport: Transport label propagated into canonical runtime presence.
            session_id: Optional runtime session identifier for UDM presence sync.
        """
        if device_id not in self.devices:
            self.devices[device_id] = Device(
                device_id,
                device_type,
                capabilities,
                metadata=metadata,
            )
        else:
            self.devices[device_id].device_type = device_type
            self.devices[device_id].capabilities = list(capabilities)
            self.devices[device_id].metadata = dict(metadata or {})
        if websocket is not None:
            self.devices[device_id].websocket = websocket
        self.on_device_connected(
            device_id,
            websocket=websocket,
            transport=transport,
            session_id=session_id,
        )

    def clear_live_session(self, device_id: str) -> None:
        """Remove an in-memory router-local live session cache entry.

        This only mutates ``self.devices`` and does not persist anything to UDM
        or any external store. Use this when transport/session state must be
        cleared while canonical device identity remains unchanged elsewhere.
        """
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
                "status": (udm_device.status.value if hasattr(udm_device.status, "value") else str(udm_device.status)),
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
                "last_seen": (
                    local_device.last_seen.isoformat()
                    if hasattr(local_device.last_seen, "isoformat")
                    else str(local_device.last_seen)
                ),
            }

        return view

    def register_device(
        self,
        device_id: str,
        device_type: str,
        capabilities: List[str],
        websocket=None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
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
                    udm.register_device_from_dict(
                        device_id,
                        {
                            "device_name": device_id,
                            "device_type": device_type,
                            "capabilities": capabilities,
                            "source": "device_router",
                            **(metadata or {}),
                        },
                    )
                    logger.debug("DeviceRouter.register_device: UDM write succeeded for %s", device_id)
                except Exception as _udm_err:
                    logger.warning(
                        "DeviceRouter.register_device: UDM write failed for %s — %s",
                        device_id,
                        _udm_err,
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
        - Purges per-device gateway capabilities through the canonical capability plane.
        """
        try:
            # ── PR-3: patch canonical runtime presence (offline) into UDM ──
            # Do NOT call udm.unregister_device(); that would erase the canonical
            # device registration.  Loss of router-local session state must not
            # imply device deregistration.
            self._sync_connection_state_to_udm(device_id, connected=False)

            if device_id in self.devices:
                del self.devices[device_id]

                # Purge gateway capabilities from the canonical capability plane
                try:
                    purged = purge_gateway_capabilities_for_device(device_id)
                    logger.debug(
                        "unregister_device: purged %d capabilities for device %s",
                        purged,
                        device_id,
                    )
                except Exception as _purge_err:
                    logger.warning("unregister_device: capability registry purge failed: %s", _purge_err)

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

    def _resolve_explicit_target_devices(
        self,
        analysis: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Device]:
        """Resolve externally selected target devices before substrate-side selection."""

        ctx = context or {}
        explicit_target_ids = list(ctx.get("target_device_ids") or []) or list(analysis.get("target_device_ids") or [])
        explicit_target_id = ctx.get("target_device_id") or analysis.get("target_device_id")
        explicit_target_id_str = str(explicit_target_id) if explicit_target_id else ""
        if explicit_target_id_str and explicit_target_id_str not in explicit_target_ids:
            explicit_target_ids.append(explicit_target_id_str)

        deduped_ids: List[str] = []
        seen_ids = set()
        for device_id in explicit_target_ids:
            if not device_id or device_id in seen_ids:
                continue
            seen_ids.add(device_id)
            deduped_ids.append(str(device_id))

        if not deduped_ids:
            return []

        resolved_devices: List[Device] = []
        missing_ids: List[str] = []
        for device_id in deduped_ids:
            device = self.get_device(device_id)
            if device is None:
                missing_ids.append(device_id)
                continue
            resolved_devices.append(device)

        if missing_ids:
            logger.warning(
                "DeviceRouter.route_task: explicit target device(s) not present in router "
                "session cache and were skipped: %s",
                missing_ids,
            )

        if resolved_devices:
            logger.debug(
                "DeviceRouter.route_task: using externally resolved target devices=%s",
                [d.device_id for d in resolved_devices],
            )

        return resolved_devices

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
        _entry_source_runtime_posture = ctx.get("source_runtime_posture", "control_only")
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
                    "source_runtime_posture": _entry_source_runtime_posture,
                },
            )
            # Propagate unified task_id and trace_id back into context so the
            # internal task dict and AIP messages share the same identifiers.
            ctx = dict(ctx)
            ctx["task_id"] = _route_envelope.task_id
            ctx["trace_id"] = _route_envelope.trace_id
            logger.debug(
                "DeviceRouter.route_task envelope | task_id=%s trace_id=%s " "route_mode=%s source_device_id=%s",
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
            # PR-3 / SCHED-003 partial closure: when CommandRouter has already
            # analysed the command and stamped _command_router_pre_analyzed=True
            # in context, use the pre-resolved analysis directly to avoid
            # duplicated policy authority.
            if ctx.get("_command_router_pre_analyzed") and "_pre_analysis" in ctx:
                analysis: Dict[str, Any] = ctx["_pre_analysis"]
                logger.debug("DeviceRouter.route_task: using CommandRouter pre-analysis (SCHED-003)")
            else:
                analysis = _routing_analyze_command(command, ctx)

            task_type: str = analysis.get("task_type", TaskType.COMPOUND)
            target_devices: List[Device] = []

            # 2. 检查是否有外部已解析的目标设备
            explicit_targets = self._resolve_explicit_target_devices(analysis, ctx)
            if explicit_targets:
                target_devices = explicit_targets
                logger.info(
                    "Using %d explicit target device(s): %s",
                    len(target_devices),
                    [d.device_id for d in target_devices],
                )
            else:
                # 3. 根据分析结果选择设备
                if task_type == TaskType.CROSS_DEVICE:
                    # Cross-device path
                    if not is_cross_device_enabled():
                        return make_disabled_response(command)
                    return await self._dispatch_cross_device_task(command, ctx, analysis)
                else:
                    # Single-device path
                    target_devices = _routing_select_devices(
                        self.devices, analysis, _routing_filter_eligible_devices
                    )

            if not target_devices:
                return {"success": False, "error": "没有可用的目标设备", "command": command}

            # 4. 构建并发送 AIP 消息
            results: List[Dict[str, Any]] = []
            for device in target_devices:
                if not _routing_is_device_available(device):
                    logger.warning("Device %s is not available, skipping", device.device_id)
                    continue

                message = _routing_build_aip_message(command, ctx, analysis)
                result = await _routing_dispatch_to_websocket(device, message)
                results.append(result)

            # 5. 聚合结果
            if not results:
                return {"success": False, "error": "所有目标设备都不可用", "command": command}

            # PR-519 / GAP-517-007: surface cross-device results
            surface_cross_device_result(
                results[0] if len(results) == 1 else {"success": True, "results": results},
                task_id=ctx.get("task_id", ""),
                device_id=ctx.get("device_id", ""),
                trace_id=ctx.get("trace_id"),
                route_mode=ctx.get("route_mode", ""),
                source_device_id=_entry_source_device_id,
            )

            return results[0] if len(results) == 1 else {"success": True, "results": results}

        except Exception as e:
            logger.error(f"❌ 路由任务失败: {e}")
            return {"success": False, "error": str(e), "command": command}

    async def dispatch_task(self, task: Dict[str, Any], device: Device) -> Dict[str, Any]:
        """Dispatch a pre-built task to a specific device.

        This is the low-level dispatch entry that does NOT perform command
        analysis or device selection — it sends the task envelope directly
        to the specified device via its WebSocket handle.

        Args:
            task: Pre-built task envelope (must contain ``task_id`` and ``payload``).
            device: Target :class:`Device` with an active WebSocket.

        Returns:
            Execution result dict from the device.
        """
        if not device or not _routing_is_device_online(device):
            return {"success": False, "error": "Device not connected", "device_id": getattr(device, "device_id", None)}

        message = _routing_build_aip_message(
            task.get("payload", {}).get("command", ""),
            task,
            {"task_type": task.get("payload", {}).get("task_type", TaskType.UI_AUTOMATION)},
        )
        return await _routing_dispatch_to_websocket(device, message)

    async def _dispatch_cross_device_task(
        self,
        command: str,
        ctx: Dict[str, Any],
        analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Internal substrate: cross-device dispatch implementation.

        PR-518 / GAP-517-003: This method is internal substrate called by
        route_task().  Direct external calls are legacy bypasses.

        PR-520 / GAP-517-004: Resolves and attaches an explicit canonical
        DeviceFormationGroup before executing any cross-device sub-task.

        PR-ALIGN / ADMIT-003: Filters device list through participation
        eligibility before formation.
        """
        logger.info("Dispatching cross-device task: %s", command)

        # PR-ALIGN / ADMIT-003: filter by participation eligibility
        try:
            from core.device_participation import get_device_participation

            eligible_devices: List[Device] = []
            for d in self.devices.values():
                participation = get_device_participation(d.device_id)
                if participation.is_eligible:
                    eligible_devices.append(d)
            if not eligible_devices:
                logger.warning("No participation-eligible devices found for cross-device task")
                eligible_devices = list(self.devices.values())  # graceful degradation
        except Exception as _part_err:
            logger.debug("Participation filter unavailable, using all devices: %s", _part_err)
            eligible_devices = list(self.devices.values())

        # PR-520 / GAP-517-004: resolve formation
        _formation_group = None
        _formation_dict: dict = {}
        try:
            from core.device_formation.formation_resolver import resolve_formation

            _target_ids = [d.device_id for d in eligible_devices]
            _source_id = ctx.get("source_device_id", "") or ctx.get("device_id", "")
            _formation_group, _ = resolve_formation(
                runtime_domain="cross_device",
                source_device_id=_source_id,
                primary_device_id=_target_ids[0] if _target_ids else "",
                target_device_ids=_target_ids,
                task_id=ctx.get("task_id", ""),
                trace_id=ctx.get("trace_id"),
                formation_reason="DeviceRouter._dispatch_cross_device_task",
            )
            _formation_dict = _formation_group.to_dict()
        except Exception as _form_err:
            logger.warning("Formation resolution failed: %s", _form_err)

        # Delegate to CrossDeviceCoordinator
        cdc = get_cross_device_coordinator()
        result = await cdc.execute_cross_device_task(
            command,
            {**ctx, **analysis, "_SUBSTRATE_CALLER_CTX_KEY": "device_router"},
            _substrate_caller="device_router",
        )

        # Attach formation descriptor
        if _formation_dict and isinstance(result, dict):
            result = dict(result)
            result["formation"] = _formation_dict

        # PR-519 / GAP-517-007: surface result
        surface_cross_device_result(
            result if isinstance(result, dict) else {"success": bool(result)},
            task_id=ctx.get("task_id", ""),
            device_id=ctx.get("device_id", ""),
            trace_id=ctx.get("trace_id"),
            route_mode=ctx.get("route_mode", ""),
            source_device_id=ctx.get("source_device_id", ""),
        )

        return result if isinstance(result, dict) else {"success": bool(result)}

    def get_device_count(self) -> int:
        """Return the number of devices in the local operational cache."""
        return len(self.devices)

    def get_online_device_count(self) -> int:
        """Return the number of devices with active WebSocket connections."""
        return sum(1 for d in self.devices.values() if d.websocket is not None)


# Global singleton instance
device_router = DeviceRouter()
