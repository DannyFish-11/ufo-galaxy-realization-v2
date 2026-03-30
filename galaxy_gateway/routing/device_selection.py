"""galaxy_gateway/routing/device_selection.py — Device eligibility and selection.

This module owns the decision of *which* specific device(s) should handle a
given task.  It is intentionally separate from routing *policy* (what the
command needs) and *dispatch* (how to send the task to the chosen device).

Separation of concerns
-----------------------
- ``select_devices`` — apply exec_mode filtering, autonomous preference, and
  DevicePoolManager scheduling to a pre-typed candidate list.

The implementation is extracted from ``DeviceRouter._select_devices``.
Callers that hold a ``DeviceRouter`` instance continue to use
``DeviceRouter._select_devices``, which now delegates here.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

# Module-level imports so the functions can be patched in tests.
from galaxy_gateway.capability_registry import get_gateway_capability_registry  # noqa: E402
from core.device_pool_manager import get_device_pool_manager  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

DEVICE_SELECTION_AUTHORITY = "galaxy_gateway.routing.device_selection"
"""Sentinel string identifying this module as the device-selection authority."""


# ---------------------------------------------------------------------------
# Core selection function
# ---------------------------------------------------------------------------


def select_devices(
    analysis: Dict[str, Any],
    candidates: List[Any],
) -> List[Any]:
    """Select the best device(s) from *candidates* for the task described by *analysis*.

    This function is the extracted implementation of
    ``DeviceRouter._select_devices``.  It applies, in order:

    1. **exec_mode-aware filtering** via ``GatewayCapabilityRegistry`` — selects
       devices whose registered capabilities match the requested action and
       exec_mode.  Legacy devices (no capability_report yet) are kept as a
       fallback group.
    2. **Autonomous-device preference** via ``autonomous_filter`` — promotes
       devices with goal-execution capability.  Falls back to online-only
       filter when the filter is unavailable.
    3. **DevicePoolManager selection** — delegates the final scheduling
       decision (health scoring, circuit-breaker, strategy) to the pool.
       Falls back to the first preferred candidate when the pool is
       unavailable.

    Args:
        analysis: Routing-policy analysis dict produced by
                  :func:`galaxy_gateway.routing.policy.analyze_command`.
                  Consumed keys: ``exec_mode``, ``actions``,
                  ``requires_cross_device``, ``task_role``,
                  ``required_capabilities``, ``target_device_type``.
        candidates: Pre-typed list of :class:`~galaxy_gateway.device_router.Device`
                    objects — i.e. devices whose ``device_type`` already matches
                    the target type.  Obtained by calling
                    ``DeviceRouter.get_devices_by_type``.

    Returns:
        A list of selected devices (usually a single element).  An empty list
        means no eligible device was found.
    """
    devices: List[Any] = list(candidates)

    if not devices:
        return []

    # ── 1. exec_mode-aware filtering via GatewayCapabilityRegistry ──────────
    desired_exec_mode_str: Optional[str] = analysis.get("exec_mode")
    _actions = analysis.get("actions") or []
    desired_action: Optional[str] = _actions[0] if _actions else None

    if desired_exec_mode_str or desired_action:
        try:
            from galaxy_gateway.capability_registry import ExecMode

            gw_reg = get_gateway_capability_registry()
            desired_exec_mode = ExecMode.from_str(desired_exec_mode_str)

            filtered: List[Any] = []
            unregistered: List[Any] = []
            for device in devices:
                schemas = gw_reg.query(
                    action=desired_action,
                    exec_mode=(
                        desired_exec_mode
                        if desired_exec_mode != ExecMode.BOTH
                        else None
                    ),
                    device_id=device.device_id,
                )
                if schemas:
                    filtered.append(device)
                else:
                    all_caps = gw_reg.get_by_device(device.device_id)
                    if not all_caps:
                        # Legacy device — no capability_report yet → keep
                        unregistered.append(device)
                    # else: device has caps but none match → exclude

            if filtered:
                devices = filtered
                logger.debug(
                    "select_devices: exec_mode=%s action=%s → %d matching device(s)",
                    desired_exec_mode_str,
                    desired_action,
                    len(filtered),
                )
            elif unregistered:
                devices = unregistered
                logger.debug(
                    "select_devices: no schema matches; falling back to %d legacy device(s)",
                    len(unregistered),
                )
            else:
                logger.debug(
                    "select_devices: no devices match exec_mode=%s action=%s; using all",
                    desired_exec_mode_str,
                    desired_action,
                )
                # devices already holds the full list — no further filtering

        except Exception as _reg_err:
            logger.warning(
                "select_devices: capability registry unavailable, skipping exec_mode filter: %s",
                _reg_err,
            )

    # ── 2. Autonomous-device preference (with fallback) ──────────────────────
    require_cross = analysis.get("requires_cross_device", False)
    task_role = analysis.get("task_role")
    try:
        from galaxy_gateway.autonomous_filter import filter_autonomous_devices

        preferred: List[Any] = filter_autonomous_devices(
            devices,
            get_metadata=lambda d: d.metadata,
            get_status=lambda d: d.status,
            require_cross_device=require_cross,
            task_role=task_role,
        )
    except Exception as _filter_err:
        logger.warning(
            "select_devices: autonomous_filter unavailable, using online-only fallback: %s",
            _filter_err,
        )
        preferred = [d for d in devices if d.status == "online"]

    if not preferred:
        target_device_type = analysis.get("target_device_type", "")
        logger.warning("select_devices: no online %s devices", target_device_type)
        return []

    # ── 3. DevicePoolManager final scheduling ────────────────────────────────
    required_caps: List[str] = analysis.get("required_capabilities") or []
    target_device_type = analysis.get("target_device_type")
    try:
        pool = get_device_pool_manager()
        preferred_ids = {d.device_id for d in preferred}
        device_type_str = (
            target_device_type.value
            if hasattr(target_device_type, "value")
            else str(target_device_type)
        )
        selected_id = pool.select_device(
            required_capabilities=required_caps or None,
            device_type=device_type_str,
            exclude=[
                d.device_id
                for d in devices
                if d.device_id not in preferred_ids
            ],
        )
        if selected_id:
            matched = next(
                (d for d in preferred if d.device_id == selected_id), None
            )
            if matched:
                logger.debug(
                    "select_devices: DevicePoolManager selected %s", selected_id
                )
                return [matched]
        # Pool returned no match — fall through to first-preferred fallback.
    except Exception as _pool_err:
        logger.warning(
            "select_devices: DevicePoolManager unavailable, using first-preferred fallback: %s",
            _pool_err,
        )

    return [preferred[0]]
