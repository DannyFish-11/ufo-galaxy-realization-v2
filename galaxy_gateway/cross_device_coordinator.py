"""
galaxy_gateway/cross_device_coordinator.py — Internal Cross-Device Task Coordinator
======================================================================================

**Unified-Subject Architecture — Internal Cross-Device Substrate**
------------------------------------------------------------------
``CrossDeviceCoordinator`` is an internal coordinator within the gateway's
cross-device execution substrate.  It is NOT a primary subject entrypoint.

Cross-device coordination is part of the subject's liminal cross-device
execution loop: ``OpenClawd`` decides to expand cross-device, routes via
:class:`~core.command_router.CommandRouter`, which uses this coordinator as
internal plumbing to orchestrate multi-device tasks.

Cross-Device Coordinator - 跨设备协同协调器

实现多设备协同任务的编排和执行
支持设备间数据传递和状态同步

PR-6: Device-input authority model
------------------------------------
Device **selection** (deciding *which* devices to use) is now based on
canonical projected device views (``RegisteredRuntimeDevice``), not on
router-local device tables.

The :class:`device_router` is still used for **routing/dispatch** (the
transport substrate: WebSocket send, task dispatch), but it is not the
authority for device identity or cross-device eligibility.

Internal helpers that need the canonical device set call
:meth:`_get_canonical_devices` which projects each router-registered device
through :func:`~contracts.registered_runtime_device.from_router_device` and
assesses participation via
:func:`~core.device_selection.canonical_device_selector.assess_device_participation`.

Architectural boundary (PR-10) — convenience coordination layer
----------------------------------------------------------------
``CrossDeviceCoordinator`` is a **convenience/legacy coordination layer** for
gateway-internal multi-device tasks (clipboard sync, file transfer, media
control, notification broadcast).  It runs *within* the transport layer and
must not be promoted to a canonical orchestration authority.

NOT responsible for
~~~~~~~~~~~~~~~~~~~~
- **Orchestration eligibility** — whether a device may be included in a
  multi-device orchestration session.  Assessed by
  :mod:`core.device_selection.canonical_device_selector`.
- **Formation truth** — the canonical participation set for a session.
  Owned by :class:`~core.unified.device_manager.UnifiedDeviceManager` (UDM).
- **Entry-mode decisioning** — resolved by the canonical orchestration layer.
- **Global readiness truth** — owned by :mod:`core.system_orchestrator`.

Any future logic that needs to gate cross-device tasks on canonical readiness
or eligibility must call the core layer first, then pass the resolved device
set to this coordinator for transport execution.

Author: Manus AI
Version: 1.0
Date: 2026-01-22
"""

# ---------------------------------------------------------------------------
# PR-10 transport-layer boundary sentinel
# Importing this sentinel from outside the gateway package signals that the
# import site is consuming cross-device transport primitives only — not
# canonical orchestration eligibility, formation truth, or readiness.
# ---------------------------------------------------------------------------
CROSS_DEVICE_COORDINATOR_TRANSPORT_AUTHORITY = "CROSS_DEVICE_COORDINATOR::CONVENIENCE_TRANSPORT_LAYER_ONLY"

# ---------------------------------------------------------------------------
# PR-518 / GAP-517-003: substrate-only enforcement sentinel
#
# ``CrossDeviceCoordinator`` is internal substrate called exclusively by
# ``DeviceRouter`` (which in turn is invoked by ``CommandRouter``).
# Direct calls from outside the gateway substrate are legacy bypasses and
# must be made explicitly visible via structured warnings.
# ---------------------------------------------------------------------------
CROSS_DEVICE_COORDINATOR_SUBSTRATE_ONLY = (
    "CROSS_DEVICE_COORDINATOR::SUBSTRATE_ONLY_V1: "
    "execute_cross_device_task() must only be called from DeviceRouter "
    "substrate, which is invoked by CommandRouter.route_envelope(). "
    "Direct external calls are legacy bypasses — they emit structured "
    "LEGACY_DISPATCH warnings and are recorded as integrity events. "
    "Resolves GAP-517-003."
)

# ---------------------------------------------------------------------------
# PR-519 / GAP-517-007: result surface closure sentinel
#
# execute_cross_device_task() now calls surface_cross_device_result() before
# returning so that every cross-device outcome is normalised into a
# ResultEnvelope and surfaced through TaskGraphRuntime, ReplayFoundation, and
# CrossDeviceChainSingleton.  Resolves GAP-517-007.
# ---------------------------------------------------------------------------
from core.cross_device_result_surface import (  # noqa: E402
    CROSS_DEVICE_RESULT_SURFACE_INTEGRATED,
    surface_cross_device_result,
)

CROSS_DEVICE_RESULT_SURFACE_INTEGRATED  # re-export / sentinel reference

# ---------------------------------------------------------------------------
# PR-520 / GAP-517-004: explicit formation descriptor attachment sentinel
#
# execute_cross_device_task() now calls resolve_formation() from
# core.device_formation at the start of execution to produce an explicit
# canonical DeviceFormationGroup.  The group is attached to the result
# payload under the "formation" key and recorded as a FormationTruthRecord
# in the integrity runtime.  Resolves GAP-517-004.
# ---------------------------------------------------------------------------
CROSS_DEVICE_COORDINATOR_FORMATION_DESCRIPTOR_ATTACHED = (
    "CROSS_DEVICE_COORDINATOR::FORMATION_DESCRIPTOR_ATTACHED_V1: "
    "execute_cross_device_task() resolves and attaches a canonical "
    "DeviceFormationGroup before executing any cross-device sub-task. "
    "Resolves GAP-517-004."
)

# Module-level key used in the context dict passed by DeviceRouter when it
# delegates to this coordinator.  Presence of this key signals a canonical
# invocation; absence triggers a LEGACY_DISPATCH warning.
_SUBSTRATE_CALLER_CTX_KEY = "_galaxy_cross_device_substrate_caller"

import asyncio
import logging
import os
import shutil
import hashlib
import tempfile
from typing import Dict, List, Optional, Any
from datetime import datetime
from galaxy_gateway.device_router import device_router
from galaxy_gateway.observability import get_gateway_metrics
from core.device_types import DeviceType

logger = logging.getLogger(__name__)


class CrossDeviceCoordinator:
    """跨设备协同协调器 — DeviceRouter-internal cross-device substrate (PR-S3).

    **Architecture role (PR-S3)**
    -----------------------------
    ``CrossDeviceCoordinator`` is an **internal coordinator** called by
    :class:`~galaxy_gateway.device_router.DeviceRouter` when it determines
    that a task requires cross-device coordination.  It is NOT a public
    dispatch entry; external callers must use
    :meth:`~galaxy_gateway.device_router.DeviceRouter.route_task` instead.

    DeviceRouter is the canonical single entry for all device-bound dispatch
    and cross-device orchestration decisions (``CANONICAL_DISPATCH_AUTHORITY``).
    This coordinator provides the implementation substrate for cross-device
    tasks once DeviceRouter has made the routing decision.

    PR-6: Device-selection authority model
    ----------------------------------------
    Device *selection* (which devices participate) is based on canonical
    projected device views (``RegisteredRuntimeDevice``).  The router is
    used for dispatch/transport only.
    """

    def __init__(self):
        self.shared_clipboard: Dict[str, Any] = {}
        self.device_states: Dict[str, Dict] = {}

    # ------------------------------------------------------------------
    # PR-6: Canonical device resolution helpers
    # ------------------------------------------------------------------

    def _get_canonical_devices(
        self,
        router_liveness: Optional[Dict[str, bool]] = None,
    ) -> list:
        """Return the current device set as canonical projected device views.

        Projects every device registered in the router through
        :func:`~contracts.registered_runtime_device.from_router_device`,
        giving a ``RegisteredRuntimeDevice`` for each.  The router is used
        as a *source* here (it holds the current transport-level registration),
        but the canonical contract — not the raw router object — is the
        truth source for all downstream selection logic.

        Router liveness (WebSocket connected / disconnected) is passed as
        *enrichment* to :func:`~core.device_selection.assess_device_participation`
        so that it can refine the ``routable`` flag without replacing canonical
        identity.

        Parameters
        ----------
        router_liveness:
            Optional ``device_id → bool`` mapping.  When ``None`` the
            function derives liveness from each device's WebSocket presence.

        Returns
        -------
        list of RegisteredRuntimeDevice
        """
        try:
            from contracts.registered_runtime_device import from_router_device

            if router_liveness is None:
                # Derive liveness from router websocket state as enrichment.
                router_liveness = {
                    dev_id: (getattr(dev, "websocket", None) is not None)
                    for dev_id, dev in device_router.devices.items()
                }

            canonical_devices = [from_router_device(dev) for dev in device_router.devices.values()]
            return canonical_devices
        except Exception as exc:
            logger.warning("_get_canonical_devices: error projecting devices: %s", exc)
            return []

    def _get_canonical_devices_by_type(
        self,
        device_type: DeviceType,
        cross_device_eligible_only: bool = True,
    ) -> list:
        """Return canonical devices filtered by device type and eligibility.

        Parameters
        ----------
        device_type:
            The :class:`~core.device_types.DeviceType` to filter on.
            Matching is performed against ``RegisteredRuntimeDevice.platform``
            / ``device_type`` field.
        cross_device_eligible_only:
            When ``True`` (default), only devices assessed as
            ``cross_device_eligible`` are returned.  When ``False`` all
            devices matching *device_type* are returned regardless of
            eligibility.

        Returns
        -------
        list of RegisteredRuntimeDevice
        """
        from core.device_selection import assess_device_participation

        # Build liveness map from router for enrichment
        router_liveness: Dict[str, bool] = {
            dev_id: (getattr(dev, "websocket", None) is not None) for dev_id, dev in device_router.devices.items()
        }

        canonical_devices = self._get_canonical_devices(router_liveness=router_liveness)

        # Normalise device_type to a lower-case string for matching
        type_str = str(device_type.value if hasattr(device_type, "value") else device_type).lower()

        results = []
        for device in canonical_devices:
            # Match against platform or device_type field
            platform_val = str(getattr(device, "platform", "")).lower()
            dev_type_val = str(getattr(device, "device_type", "")).lower()
            if type_str not in (platform_val, dev_type_val) and type_str not in dev_type_val:
                continue

            if cross_device_eligible_only:
                participation = assess_device_participation(device, router_liveness=router_liveness)
                if not participation.cross_device_eligible:
                    continue

            results.append(device)

        return results

    def _get_canonical_online_devices(self) -> list:
        """Return all canonical devices that are cross-device eligible.

        Used by broadcast-style operations (media control, notification sync)
        that need to reach all currently reachable devices.

        Returns
        -------
        list of RegisteredRuntimeDevice
        """
        from core.device_selection import (
            assess_device_participation,
            select_cross_device_candidates,
        )

        router_liveness: Dict[str, bool] = {
            dev_id: (getattr(dev, "websocket", None) is not None) for dev_id, dev in device_router.devices.items()
        }
        canonical_devices = self._get_canonical_devices(router_liveness=router_liveness)
        entries = select_cross_device_candidates(canonical_devices, router_liveness=router_liveness)
        return [entry.device for entry in entries]

    async def execute_cross_device_task(
        self,
        command: str,
        context: Dict = None,
        *,
        _substrate_caller: str = "",
    ) -> Dict:
        """执行跨设备协同任务 — DeviceRouter-internal coordinator (PR-S3).

        **Called by DeviceRouter only (PR-518/GAP-517-003).**
        External code must route through
        :meth:`~galaxy_gateway.device_router.DeviceRouter.route_task` and let
        DeviceRouter decide whether to delegate here.

        The canonical call chain is::

            CommandRouter.route_envelope()
                → DeviceRouter.route_task()        (substrate)
                    → CrossDeviceCoordinator.execute_cross_device_task()
                          (internal plumbing, _substrate_caller set)

        Calls that arrive without ``_substrate_caller`` set OR without
        ``_SUBSTRATE_CALLER_CTX_KEY`` in ``context`` are treated as
        **non-canonical legacy invocations**.  They are allowed to proceed
        (fail-open) but emit a ``LEGACY_DISPATCH`` structured warning and
        record an integrity event so the bypass is observable.

        典型场景：
        1. 从手机复制文本到电脑
        2. 在电脑上打开手机拍的照片
        3. 手机和电脑同步播放控制
        4. 跨设备剪贴板共享
        """
        # ── PR-518/GAP-517-003: Substrate-caller guard ───────────────────────
        _ctx = dict(context or {})
        _caller = _substrate_caller or _ctx.get(_SUBSTRATE_CALLER_CTX_KEY, "")
        _route_mode = str(_ctx.get("route_mode") or "cross_device")
        _fallback_reason = str(_ctx.get("fallback_reason") or "")
        _compat_legacy_bypass = str(_ctx.get("_compat_legacy_bypass") or "")
        _compat_path_used = str(_ctx.get("compat_path_used") or "")
        _dispatch_path = str(_ctx.get("dispatch_path") or "")
        _is_canonical = _caller == "device_router.route_task"
        if not _dispatch_path:
            if _is_canonical:
                _dispatch_path = "canonical_fallback" if _fallback_reason else "canonical_dispatch"
            elif _caller:
                _dispatch_path = "compat_fallback"
            else:
                _dispatch_path = "legacy_bypass"
        _is_legacy_bypass = _dispatch_path == "legacy_bypass"
        _legacy_path_used = None
        if _dispatch_path == "compat_fallback":
            _legacy_path_used = (
                _compat_legacy_bypass
                or _compat_path_used
                or _caller
                or "cross_device_coordinator.compat_fallback"
            )
        elif _is_legacy_bypass:
            _legacy_path_used = "cross_device_coordinator.execute_cross_device_task"
        if _is_legacy_bypass:
            get_gateway_metrics().inc("legacy_dispatch_total")
            logger.warning(
                "LEGACY_DISPATCH | CrossDeviceCoordinator.execute_cross_device_task "
                "called without a canonical substrate caller.  "
                "Callers must route through CommandRouter.route_envelope() → "
                "DeviceRouter.route_task() → this method. "
                "command=%r  (GAP-517-003 bypass detected)",
                command,
            )
            try:
                from core.multi_device_control_integrity import (
                    record_integrity_event,
                    build_dispatch_authority_record,
                    DispatchPathKind,
                )

                _rec = build_dispatch_authority_record(
                    task_id=_ctx.get("task_id", ""),
                    dispatch_path=DispatchPathKind.COORDINATOR_LEGACY,
                    is_canonical=False,
                    caller_module="unknown",
                )
                record_integrity_event(_rec)
            except Exception:
                pass  # integrity recording is advisory, never blocks execution

        try:
            logger.info(f"🔄 开始执行跨设备任务: {command}")

            # PR-520 / GAP-517-004: resolve and attach an explicit canonical
            # DeviceFormationGroup before executing any cross-device sub-task.
            # This ensures formation truth is explicit and auditable.
            _formation_group = None
            _formation_dict: dict = {}
            try:
                from core.device_formation.formation_resolver import resolve_formation
                from core.source_runtime_posture import (
                    resolve_source_runtime_posture,
                    record_source_runtime_posture,
                )

                _ctx_inner = context or {}
                _source_device_id = _ctx_inner.get("source_device_id", "")
                _source_runtime_posture = resolve_source_runtime_posture(_ctx_inner.get("source_runtime_posture"))
                _target_device_ids = _ctx_inner.get("target_device_ids") or []
                if isinstance(_target_device_ids, str):
                    _target_device_ids = [_target_device_ids]
                _primary_device_id = _ctx_inner.get("device_id", "") or (
                    _target_device_ids[0] if _target_device_ids else ""
                )
                _formation_group, _formation_policy = resolve_formation(
                    runtime_domain="cross_device",
                    source_device_id=_source_device_id,
                    source_runtime_posture=_source_runtime_posture.value,
                    primary_device_id=_primary_device_id,
                    target_device_ids=list(_target_device_ids),
                    task_id=_ctx_inner.get("task_id", ""),
                    trace_id=_ctx_inner.get("trace_id"),
                    formation_reason="CrossDeviceCoordinator.execute_cross_device_task",
                )
                record_source_runtime_posture(
                    task_id=_ctx_inner.get("task_id", ""),
                    trace_id=_ctx_inner.get("trace_id"),
                    source_device_id=_source_device_id,
                    posture=_source_runtime_posture,
                    target_device_ids=list(_target_device_ids),
                    entry_mode=_ctx_inner.get("route_mode", "cross_device"),
                    reason="CrossDeviceCoordinator.execute_cross_device_task",
                )
                _formation_dict = _formation_group.to_dict()
                logger.debug(
                    "CrossDeviceCoordinator.execute_cross_device_task formation | "
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
                        task_id=_ctx_inner.get("task_id", ""),
                        trace_id=_ctx_inner.get("trace_id"),
                        formation_id=_formation_group.formation_id,
                        consistency=FormationTruthConsistency.CONSISTENT,
                        member_device_ids=list(_target_device_ids),
                        source_device_id=_source_device_id,
                        primary_device_id=_primary_device_id,
                        extra={"source_runtime_posture": _source_runtime_posture.value},
                    )
                    record_integrity_event(formation_record=_frec)
                except Exception as _rec_err:
                    logger.debug(
                        "CrossDeviceCoordinator.execute_cross_device_task: " "integrity recording skipped — %s",
                        _rec_err,
                    )  # integrity recording is advisory
                # PR-A: Notify the runtime harness that all formation participants
                # are ready so readiness-driven formation tracking is active from
                # the start of this cross-device task.
                try:
                    from core.multi_device_runtime_harness import on_participant_readiness_changed

                    _session_id = _ctx_inner.get("session_id")
                    for _member_id in _formation_group.all_member_device_ids:
                        on_participant_readiness_changed(
                            _member_id,
                            "ready",
                            formation=_formation_group,
                            session_id=_session_id,
                            reason="cross_device_task_start",
                        )
                except Exception as _harn_err:
                    logger.debug(
                        "CrossDeviceCoordinator.execute_cross_device_task: "
                        "harness readiness notification skipped — %s",
                        _harn_err,
                    )  # harness notification is advisory
            except Exception as _form_err:
                logger.warning(
                    "CrossDeviceCoordinator.execute_cross_device_task: "
                    "formation resolution failed — %s "
                    "(GAP-517-004: proceeding without explicit formation descriptor)",
                    _form_err,
                )

            # 分析任务类型
            task_type = self._analyze_cross_device_task(command)

            # 根据任务类型执行
            if task_type == "clipboard_sync":
                result = await self._sync_clipboard(command, context)
            elif task_type == "file_transfer":
                result = await self._transfer_file(command, context)
            elif task_type == "media_control":
                result = await self._sync_media_control(command, context)
            elif task_type == "notification_sync":
                result = await self._sync_notification(command, context)
            else:
                result = await self._execute_generic_cross_device_task(command, context)

            if isinstance(result, dict):
                result = result.copy()
            else:
                result = {"success": False, "error": str(result)}
            result.setdefault("route_mode", _route_mode)
            result.setdefault("dispatch_path", _dispatch_path)
            if _fallback_reason:
                result.setdefault("fallback_reason", _fallback_reason)
            if _compat_path_used:
                result.setdefault("compat_path_used", _compat_path_used)
            if _compat_legacy_bypass:
                result.setdefault("compat_legacy_bypass", _compat_legacy_bypass)
            if _dispatch_path == "legacy_bypass":
                result.setdefault("legacy_bypass", True)

            # PR-519 / GAP-517-007: normalise result into canonical surfaces
            # before returning so that outcomes are visible through
            # TaskGraphRuntime, ReplayFoundation, and CrossDeviceChainSingleton.
            surface_cross_device_result(
                result,
                task_id=_ctx.get("task_id", ""),
                device_id=_ctx.get("device_id", ""),
                trace_id=_ctx.get("trace_id"),
                session_id=_ctx.get("session_id"),
                route_mode=_route_mode,
                source_device_id=_ctx.get("source_device_id", ""),
                target_device_ids=_ctx.get("target_device_ids"),
                legacy_path_used=_legacy_path_used,
                extra={
                    key: value
                    for key, value in {
                        "dispatch_path": _dispatch_path,
                        "fallback_reason": _fallback_reason,
                        "compat_path_used": _compat_path_used,
                        "compat_legacy_bypass": _compat_legacy_bypass,
                        "substrate_caller": _caller,
                    }.items()
                    if value
                },
            )

            # PR-520 / GAP-517-004: attach the canonical formation descriptor
            # to the result so callers and audit surfaces can inspect it.
            if _formation_dict:
                result = dict(result)
                result["formation"] = _formation_dict
            return result

        except Exception as e:
            logger.error(f"❌ 跨设备任务执行失败: {e}")
            _err_result = {
                "success": False,
                "error": f"跨设备任务执行失败: {str(e)}",
                "route_mode": _route_mode,
                "dispatch_path": _dispatch_path,
            }
            if _fallback_reason:
                _err_result["fallback_reason"] = _fallback_reason
            if _compat_path_used:
                _err_result["compat_path_used"] = _compat_path_used
            if _compat_legacy_bypass:
                _err_result["compat_legacy_bypass"] = _compat_legacy_bypass
            if _dispatch_path == "legacy_bypass":
                _err_result["legacy_bypass"] = True
            # PR-519: surface even failure results so they appear in audit logs
            surface_cross_device_result(
                _err_result,
                task_id=_ctx.get("task_id", ""),
                device_id=_ctx.get("device_id", ""),
                trace_id=_ctx.get("trace_id"),
                route_mode=_route_mode,
                legacy_path_used=_legacy_path_used,
                extra={
                    key: value
                    for key, value in {
                        "dispatch_path": _dispatch_path,
                        "fallback_reason": _fallback_reason,
                        "compat_path_used": _compat_path_used,
                        "compat_legacy_bypass": _compat_legacy_bypass,
                        "substrate_caller": _caller,
                    }.items()
                    if value
                },
            )
            # PR-A: Mark the source device as degraded so the harness and formation
            # rebalance engine are aware that this cross-device task failed.
            try:
                from core.multi_device_runtime_harness import on_participant_readiness_changed

                _src_id = _ctx.get("source_device_id", "")
                if _src_id:
                    on_participant_readiness_changed(
                        _src_id,
                        "degraded",
                        session_id=_ctx.get("session_id"),
                        reason="cross_device_task_failure",
                    )
            except Exception:
                pass  # advisory only
            return _err_result

    def _analyze_cross_device_task(self, command: str) -> str:
        """分析跨设备任务类型"""
        command_lower = command.lower()

        if any(kw in command_lower for kw in ["复制", "粘贴", "剪贴板", "clipboard"]):
            return "clipboard_sync"
        elif any(kw in command_lower for kw in ["传输", "发送", "transfer", "send"]):
            return "file_transfer"
        elif any(kw in command_lower for kw in ["播放", "暂停", "音乐", "视频", "media"]):
            return "media_control"
        elif any(kw in command_lower for kw in ["通知", "提醒", "notification"]):
            return "notification_sync"
        else:
            return "generic"

    async def _sync_clipboard(self, command: str, context: Dict = None) -> Dict:
        """
        同步剪贴板

        场景：
        - "把手机上的文本复制到电脑"
        - "把电脑上的链接发送到手机"
        """
        try:
            logger.info("📋 执行剪贴板同步")

            # 解析源设备和目标设备
            source_type, target_type = self._parse_devices_from_command(command)

            # 步骤 1: 从源设备获取剪贴板内容
            source_task = {"task_type": "query", "action": "get_clipboard", "target": "", "params": {}}

            # PR-6: resolve source devices from canonical projections
            source_devices = self._get_canonical_devices_by_type(source_type)
            if not source_devices:
                return {"success": False, "error": f"没有可用的{source_type}设备"}

            # Dispatch uses the router (transport substrate); identity from canonical device
            source_device_id = source_devices[0].device_id
            source_router_device = device_router.devices.get(source_device_id)
            if source_router_device is None:
                return {"success": False, "error": f"没有可用的{source_type}设备"}

            # 发送查询任务到源设备
            source_result = await device_router.dispatch_task(
                {"task_id": "clipboard_get", "payload": source_task}, source_router_device
            )

            if not source_result.get("success"):
                return {"success": False, "error": "获取剪贴板内容失败"}

            clipboard_content = source_result.get("data", {}).get("clipboard", "")

            # 步骤 2: 将内容设置到目标设备剪贴板
            target_task = {
                "task_type": "system_control",
                "action": "set_clipboard",
                "target": "",
                "params": {"content": clipboard_content},
            }

            # PR-6: resolve target devices from canonical projections
            target_devices = self._get_canonical_devices_by_type(target_type)
            if not target_devices:
                return {"success": False, "error": f"没有可用的{target_type}设备"}

            target_device_id = target_devices[0].device_id
            target_router_device = device_router.devices.get(target_device_id)
            if target_router_device is None:
                return {"success": False, "error": f"没有可用的{target_type}设备"}

            target_result = await device_router.dispatch_task(
                {"task_id": "clipboard_set", "payload": target_task}, target_router_device
            )

            return {
                "success": target_result.get("success", False),
                "message": "剪贴板同步完成",
                "content_length": len(clipboard_content),
            }

        except Exception as e:
            logger.error(f"❌ 剪贴板同步失败: {e}")
            return {"success": False, "error": str(e)}

    async def _transfer_file(self, command: str, context: Dict = None) -> Dict:
        """
        跨设备文件传输 - 通过中转目录实现

        场景：
        - "把手机上的照片发送到电脑"
        - "把电脑上的文档传到手机"
        """
        try:
            logger.info("📁 执行文件传输")
            context = context or {}

            # 解析源设备和目标设备
            source_type, target_type = self._parse_devices_from_command(command)

            # 创建中转目录
            transfer_dir = os.path.join(tempfile.gettempdir(), "galaxy_transfers")
            os.makedirs(transfer_dir, exist_ok=True)

            # 从上下文获取文件路径
            file_path = context.get("file_path", "")
            file_name = context.get("file_name", os.path.basename(file_path) if file_path else "")

            # 获取源设备和目标设备
            # PR-6: resolve devices from canonical projections; router used for dispatch only
            source_canonical = self._get_canonical_devices_by_type(source_type)
            target_canonical = self._get_canonical_devices_by_type(target_type)

            if not source_canonical:
                return {"success": False, "error": f"没有可用的{source_type}设备"}
            if not target_canonical:
                return {"success": False, "error": f"没有可用的{target_type}设备"}

            source_device_id = source_canonical[0].device_id
            target_device_id = target_canonical[0].device_id
            source_device = device_router.devices.get(source_device_id)
            target_device = device_router.devices.get(target_device_id)

            if source_device is None:
                return {"success": False, "error": f"没有可用的{source_type}设备"}
            if target_device is None:
                return {"success": False, "error": f"没有可用的{target_type}设备"}

            # 步骤 1: 从源设备拉取文件到中转目录
            transfer_path = os.path.join(transfer_dir, f"{hashlib.md5(file_name.encode()).hexdigest()}_{file_name}")

            if source_type == DeviceType.ANDROID:
                # ADB pull 从安卓设备拉取
                pull_task = {
                    "task_type": "system_control",
                    "action": "shell",
                    "target": "",
                    "params": {"command": f"pull {file_path} {transfer_path}"},
                }
                pull_result = await device_router.dispatch_task(
                    {"task_id": "file_pull", "payload": pull_task}, source_device
                )
            elif source_type == DeviceType.WINDOWS:
                # 本地文件复制
                if os.path.exists(file_path):
                    shutil.copy2(file_path, transfer_path)
                    pull_result = {"success": True}
                else:
                    pull_result = {"success": False, "error": f"文件不存在: {file_path}"}
            else:
                pull_result = {"success": False, "error": f"不支持的源设备类型: {source_type}"}

            if not pull_result.get("success") and not os.path.exists(transfer_path):
                # 如果文件传输失败但没有错误信息，尝试查找最新的文件
                return {"success": False, "error": f"从源设备获取文件失败: {pull_result.get('error', '未知错误')}"}

            # 步骤 2: 将文件推送到目标设备
            if target_type == DeviceType.ANDROID:
                # ADB push 推送到安卓设备
                target_path = context.get("target_path", f"/sdcard/Download/{file_name}")
                push_task = {
                    "task_type": "system_control",
                    "action": "shell",
                    "target": "",
                    "params": {"command": f"push {transfer_path} {target_path}"},
                }
                push_result = await device_router.dispatch_task(
                    {"task_id": "file_push", "payload": push_task}, target_device
                )
            elif target_type == DeviceType.WINDOWS:
                # 本地文件复制
                target_path = context.get("target_path", os.path.join(os.path.expanduser("~"), "Downloads", file_name))
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                shutil.copy2(transfer_path, target_path)
                push_result = {"success": True}
            else:
                push_result = {"success": False, "error": f"不支持的目标设备类型: {target_type}"}

            # 清理中转文件
            try:
                if os.path.exists(transfer_path):
                    os.remove(transfer_path)
            except OSError:
                pass

            # 记录传输到共享数据
            if push_result.get("success"):
                self.set_shared_data(
                    "last_transfer",
                    {
                        "file_name": file_name,
                        "source": source_type,
                        "target": target_type,
                        "target_path": (
                            target_path if target_type == DeviceType.WINDOWS else context.get("target_path", "")
                        ),
                        "timestamp": datetime.now().isoformat(),
                    },
                )

            return {
                "success": push_result.get("success", False),
                "message": "文件传输完成" if push_result.get("success") else "文件传输失败",
                "file_name": file_name,
                "source_device": source_type,
                "target_device": target_type,
                "target_path": target_path if target_type == DeviceType.WINDOWS else context.get("target_path", ""),
            }

        except Exception as e:
            logger.error(f"❌ 文件传输失败: {e}")
            return {"success": False, "error": str(e)}

    async def _sync_media_control(self, command: str, context: Dict = None) -> Dict:
        """
        同步媒体控制

        场景：
        - "手机开始放音乐，电脑暂停视频"
        - "所有设备静音"
        """
        try:
            logger.info("🎵 执行媒体控制同步")

            # PR-6: get online devices via canonical projections; router used for dispatch only
            canonical_online = self._get_canonical_online_devices()
            all_devices = [
                device_router.devices[d.device_id] for d in canonical_online if d.device_id in device_router.devices
            ]

            # 解析媒体控制命令
            action = self._parse_media_action(command)

            # 并行发送到所有设备
            tasks = []
            for device in all_devices:
                task = {"task_type": "system_control", "action": action, "target": "", "params": {}}

                tasks.append(
                    device_router.dispatch_task({"task_id": f"media_{device.device_id}", "payload": task}, device)
                )

            results = await asyncio.gather(*tasks, return_exceptions=True)

            success_count = sum(1 for r in results if isinstance(r, dict) and r.get("success"))

            return {
                "success": success_count > 0,
                "message": f"媒体控制已同步到 {success_count}/{len(all_devices)} 个设备",
            }

        except Exception as e:
            logger.error(f"❌ 媒体控制同步失败: {e}")
            return {"success": False, "error": str(e)}

    async def _sync_notification(self, command: str, context: Dict = None) -> Dict:
        """
        同步通知

        场景：
        - "把手机的通知显示在电脑上"
        - "所有设备显示提醒"
        """
        try:
            logger.info("🔔 执行通知同步")

            # 提取通知内容
            notification_text = context.get("notification_text", command)

            # PR-6: get online devices via canonical projections; router used for dispatch only
            canonical_online = self._get_canonical_online_devices()
            all_devices = [
                device_router.devices[d.device_id] for d in canonical_online if d.device_id in device_router.devices
            ]

            # 并行发送通知到所有设备
            tasks = []
            for device in all_devices:
                task = {
                    "task_type": "system_control",
                    "action": "show_notification",
                    "target": "",
                    "params": {"title": "Galaxy", "message": notification_text},
                }

                tasks.append(
                    device_router.dispatch_task({"task_id": f"notify_{device.device_id}", "payload": task}, device)
                )

            results = await asyncio.gather(*tasks, return_exceptions=True)

            success_count = sum(1 for r in results if isinstance(r, dict) and r.get("success"))

            return {"success": success_count > 0, "message": f"通知已发送到 {success_count}/{len(all_devices)} 个设备"}

        except Exception as e:
            logger.error(f"❌ 通知同步失败: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_generic_cross_device_task(self, command: str, context: Dict = None) -> Dict:
        """执行通用跨设备任务"""
        try:
            logger.info("🔄 执行通用跨设备任务")

            # 将任务分解为多个子任务
            # 每个子任务指定目标设备

            # 简化实现：路由到主设备
            return await device_router.route_task(command, context)

        except Exception as e:
            logger.error(f"❌ 通用跨设备任务执行失败: {e}")
            return {"success": False, "error": str(e)}

    def _parse_devices_from_command(self, command: str) -> tuple:
        """从命令中解析源设备和目标设备"""
        command_lower = command.lower()

        source_type = DeviceType.UNKNOWN
        target_type = DeviceType.UNKNOWN

        # 解析源设备
        if "手机" in command_lower or "android" in command_lower:
            if command_lower.index("手机") < len(command_lower) // 2:
                source_type = DeviceType.ANDROID
            else:
                target_type = DeviceType.ANDROID

        # 解析目标设备
        if "电脑" in command_lower or "pc" in command_lower or "windows" in command_lower:
            if "电脑" in command_lower and command_lower.index("电脑") > len(command_lower) // 2:
                target_type = DeviceType.WINDOWS
            else:
                source_type = DeviceType.WINDOWS

        # 默认值
        if source_type == DeviceType.UNKNOWN:
            source_type = DeviceType.ANDROID
        if target_type == DeviceType.UNKNOWN:
            target_type = DeviceType.WINDOWS

        return source_type, target_type

    def _parse_media_action(self, command: str) -> str:
        """解析媒体控制动作"""
        command_lower = command.lower()

        if "暂停" in command_lower or "pause" in command_lower:
            return "pause_media"
        elif "播放" in command_lower or "play" in command_lower:
            return "play_media"
        elif "静音" in command_lower or "mute" in command_lower:
            return "mute"
        elif "音量" in command_lower or "volume" in command_lower:
            return "volume"
        else:
            return "pause_media"

    def set_shared_data(self, key: str, value: Any):
        """设置共享数据"""
        self.shared_clipboard[key] = {"value": value, "timestamp": datetime.now().isoformat()}
        logger.info(f"✅ 共享数据已设置: {key}")

    def get_shared_data(self, key: str) -> Optional[Any]:
        """获取共享数据"""
        data = self.shared_clipboard.get(key)
        if data:
            return data.get("value")
        return None

    def update_device_state(self, device_id: str, state: Dict):
        """更新设备状态"""
        self.device_states[device_id] = {**state, "updated_at": datetime.now().isoformat()}

    def get_device_state(self, device_id: str) -> Optional[Dict]:
        """获取设备状态"""
        return self.device_states.get(device_id)


# 全局跨设备协调器实例
cross_device_coordinator = CrossDeviceCoordinator()
