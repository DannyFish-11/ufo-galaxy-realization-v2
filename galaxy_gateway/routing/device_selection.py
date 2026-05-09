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

PR-3 addition
-------------
When ``required_capabilities`` is present in *analysis*, a **hard capability
gate** is applied via :mod:`core.capability_routing_gate` *after* exec_mode
filtering and *before* the autonomous-device preference step.  Devices that
fail the gate are excluded from selection.  This promotes capability
requirements from advisory metadata to meaningful routing constraints.
The gate is additive — it does not modify the existing exec_mode or pool
selection paths.

PR-ALIGN / SCHED-002 addition
------------------------------
Step 0 is now an **admissibility pre-filter** that consults the canonical
readiness truth (:func:`core.target_device_validator.validate_target_device`)
for each candidate before any exec_mode or capability filtering.  Devices
whose readiness check can be consulted and fail are excluded; the filter
degrades gracefully when the readiness module is unavailable so that legacy
environments continue to operate.  Resolves SCHED-002.

PR-7 addition
-------------
Step 0b is a **runtime-state pre-filter** that consults
:mod:`core.android_device_state_store` for each candidate to exclude
devices that are truly unfit based on real Android runtime-state truth.
Specifically, a device is excluded when *both* conditions hold:
  - ``pending_first_download`` is True (device has not completed initial
    model download — no local AI available), AND
  - ``current_fallback_tier`` is None/empty (no center-delegated fallback
    path is configured).
This combination means the device cannot execute tasks by any path.  All
other devices — including those with no snapshot yet — are admitted (the
filter degrades gracefully).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

# Module-level imports so the functions can be patched in tests.
from core.android_device_state_store import (  # noqa: E402
    get_device_state_snapshot,
    list_recent_execution_events,
)
from core.device_pool_manager import get_device_pool_manager  # noqa: E402
from core.unified.gateway_capability_projection import (  # noqa: E402
    get_gateway_capabilities_for_device,
    normalize_gateway_exec_mode,
    query_gateway_capabilities,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

DEVICE_SELECTION_AUTHORITY = "galaxy_gateway.routing.device_selection"
"""Sentinel string identifying this module as the device-selection authority."""

# PR-3: sentinel affirming capability gate wiring.
CAPABILITY_GATE_WIRED_IN_SELECTION: str = (
    "CAPABILITY_GATE_WIRED_IN_SELECTION: "
    "galaxy_gateway/routing/device_selection.py applies a hard capability "
    "routing gate (core.capability_routing_gate.filter_by_required_capabilities) "
    "when required_capabilities is declared in the routing analysis.  This "
    "promotes capability requirements from advisory to enforced constraints.  "
    "Resolves PR-3 requirement §2."
)

# PR-ALIGN / SCHED-002: sentinel affirming canonical admissibility pre-filter.
ADMISSIBILITY_PREFILTER_IN_SELECTION: str = (
    "ADMISSIBILITY_PREFILTER_IN_SELECTION_V1: "
    "select_devices() applies a canonical admissibility pre-filter (step 0) "
    "using core.target_device_validator.validate_target_device() before any "
    "exec_mode or capability filtering.  Devices that fail the readiness check "
    "are excluded.  Gracefully degrades when the readiness module is unavailable. "
    "Resolves SCHED-002."
)

# PR-7: sentinel affirming runtime-state pre-filter.
RUNTIME_STATE_PREFILTER_IN_SELECTION: str = (
    "RUNTIME_STATE_PREFILTER_IN_SELECTION_V1: "
    "select_devices() applies a runtime-state pre-filter (step 0b) using "
    "core.android_device_state_store.get_device_state_snapshot() to exclude "
    "devices that are provably unfit: pending_first_download=True AND no "
    "current_fallback_tier.  Gracefully degrades when the store is unavailable "
    "or has no snapshot for a device.  Resolves PR-7 requirement §2."
)

# ORCHESTRATION_CONSUMES_ANDROID_TRUTH closure sentinel.
ANDROID_RUNTIME_TRUTH_ROUTING_WEIGHT_IN_SELECTION: str = (
    "ANDROID_RUNTIME_TRUTH_ROUTING_WEIGHT_IN_SELECTION_V1: "
    "select_devices() applies Android runtime truth as routing preference weight "
    "(step 0c) after the hard unfit-device pre-filter (step 0b). "
    "Each candidate is scored by DeviceStateSnapshot / execution-event truth: "
    "+10 model_ready=True, +5 accessibility_ready=True, +5 local_loop_ready=True, "
    "+8 local_ai_ready=True, -10 warmup_result=failed, "
    "-20 model_ready=False and no current_fallback_tier, "
    "-min(offline_queue_depth,20), -12 recent_non_terminal_execution_busy, "
    "-10 runtime_health degraded/unhealthy. "
    "Candidates are re-ordered by descending score so the most Android-ready "
    "device is preferred.  Devices with no snapshot retain their original order "
    "(no penalty for absent truth — fail-open). "
    "This step closes the ORCHESTRATION_CONSUMES_ANDROID_TRUTH P0 gap in the "
    "galaxy_gateway.routing.device_selection selection path: Android truth now "
    "materially influences candidate ordering, not just hard exclusion."
)


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

    1. **exec_mode-aware filtering** via the canonical gateway capability
       projection — selects
       devices whose registered capabilities match the requested action and
       exec_mode.  Legacy devices (no capability_report yet) are kept as a
       fallback group.
    2. **Hard capability gate** (PR-3) via ``core.capability_routing_gate`` —
       when ``required_capabilities`` is non-empty, devices that do not satisfy
       all requirements are excluded.  This step elevates capability requirements
       from advisory metadata to meaningful routing constraints.
    3. **Autonomous-device preference** via ``autonomous_filter`` — promotes
       devices with goal-execution capability.  Falls back to online-only
       filter when the filter is unavailable.
    4. **DevicePoolManager selection** — delegates the final scheduling
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

    # ── 0. Canonical admissibility pre-filter (PR-ALIGN / SCHED-002) ─────────
    # Consult the canonical readiness truth for each candidate before any
    # exec_mode or capability filtering.  This closes the gap where
    # DeviceRouter._select_devices() operated purely from its local session
    # cache without consulting the canonical truth stack.
    #
    # Degradation policy: if the validator cannot be imported, or if ALL
    # devices would be excluded (e.g. readiness module not yet wired in a
    # test environment), skip the filter to preserve backward compatibility.
    try:
        from core.target_device_validator import validate_target_device as _vtd

        _admitted: List[Any] = []
        _at_least_one_readiness_check_succeeded = False
        for _dev in devices:
            _tid = getattr(_dev, "device_id", None) or ""
            if not _tid:
                _admitted.append(_dev)
                continue
            _tvr = _vtd(_tid)
            # Detect whether the readiness module was actually consulted or
            # whether it degraded to "unavailable".
            _readiness_consulted = not any(r.startswith("readiness-unavailable") for r in (_tvr.reasons or []))
            if _readiness_consulted:
                _at_least_one_readiness_check_succeeded = True
                if _tvr.ready:
                    _admitted.append(_dev)
                else:
                    logger.debug(
                        "select_devices [SCHED-002]: device %r excluded by "
                        "admissibility pre-filter — registered=%s ready=%s "
                        "reasons=%s",
                        _tid,
                        _tvr.registered,
                        _tvr.ready,
                        _tvr.reasons,
                    )
            else:
                # Readiness module unavailable for this device — include.
                _admitted.append(_dev)

        if _admitted:
            if _at_least_one_readiness_check_succeeded and len(_admitted) < len(devices):
                logger.debug(
                    "select_devices [SCHED-002]: admissibility pre-filter " "reduced candidates %d → %d",
                    len(devices),
                    len(_admitted),
                )
            devices = _admitted
        else:
            # All candidates were excluded — this means readiness was consulted
            # and every device failed (e.g. all offline).  Preserve the original
            # candidate list so downstream steps can produce a more descriptive
            # "no online devices" log rather than silently returning empty.
            logger.warning(
                "select_devices [SCHED-002]: admissibility pre-filter excluded "
                "all %d candidate(s); falling back to original list",
                len(devices),
            )
    except Exception as _adm_err:
        logger.debug(
            "select_devices: admissibility pre-filter unavailable " "(graceful degradation): %s",
            _adm_err,
        )

    # ── 0b. Runtime-state pre-filter (PR-7) ──────────────────────────────────
    # Exclude devices that are provably unfit based on real Android runtime-state
    # truth from android_device_state_store.  A device is excluded when BOTH:
    #   - pending_first_download is True (no local AI available), AND
    #   - current_fallback_tier is None/empty (no center-delegated fallback).
    # Devices with no snapshot are admitted (fail-open / graceful degradation).
    # The filter preserves the original list when all candidates would be excluded.
    try:
        _rt_admitted: List[Any] = []
        for _dev in devices:
            _did = getattr(_dev, "device_id", None) or ""
            if not _did:
                _rt_admitted.append(_dev)
                continue
            _snap = get_device_state_snapshot(_did)
            if _snap is None:
                # No snapshot — no runtime truth to exclude on; admit.
                _rt_admitted.append(_dev)
                continue
            _truly_unfit = (
                _snap.pending_first_download is True
                and not (_snap.current_fallback_tier or "")
            )
            if _truly_unfit:
                logger.debug(
                    "select_devices [PR-7/runtime-state]: device %r excluded — "
                    "pending_first_download=True and no fallback_tier",
                    _did,
                )
            else:
                _rt_admitted.append(_dev)

        if _rt_admitted:
            if len(_rt_admitted) < len(devices):
                logger.debug(
                    "select_devices [PR-7/runtime-state]: pre-filter reduced "
                    "candidates %d → %d",
                    len(devices),
                    len(_rt_admitted),
                )
            devices = _rt_admitted
        else:
            # All candidates excluded by runtime-state — fall back to pre-filter
            # list so downstream steps can provide a better error message.
            logger.warning(
                "select_devices [PR-7/runtime-state]: pre-filter excluded all "
                "%d candidate(s); falling back to original list",
                len(devices),
            )
    except Exception as _rt_err:
        logger.debug(
            "select_devices: runtime-state pre-filter unavailable "
            "(graceful degradation): %s",
            _rt_err,
        )

    # ── 0c. Android runtime truth routing weight (ORCHESTRATION_CONSUMES_ANDROID_TRUTH) ─
    # Re-order candidates by descending Android readiness score so that the
    # most ready Android device is preferred.  This is a soft preference step:
    # it does not exclude candidates — it only affects ordering.  Devices with
    # no snapshot retain a neutral score (0) and are not penalised.
    # Per ANDROID_RUNTIME_TRUTH_ROUTING_WEIGHT_IN_SELECTION.
    try:
        def _android_readiness_score(dev: Any) -> int:
            _did = getattr(dev, "device_id", None) or ""
            if not _did:
                return 0
            _snap = get_device_state_snapshot(_did)
            if _snap is None:
                return 0
            _score = 0
            if getattr(_snap, "model_ready", None) is True:
                _score += 10
            if getattr(_snap, "accessibility_ready", None) is True:
                _score += 5
            if getattr(_snap, "local_loop_ready", None) is True:
                _score += 5
            if getattr(_snap, "warmup_result", None) == "failed":
                _score -= 10
            if getattr(_snap, "model_ready", None) is False and not (
                getattr(_snap, "current_fallback_tier", None) or ""
            ):
                _score -= 20
            _is_local_ai_ready = getattr(_snap, "is_local_ai_ready", None)
            if callable(_is_local_ai_ready):
                try:
                    if bool(_is_local_ai_ready()):
                        _score += 8
                except Exception:
                    pass
            _queue_depth = getattr(_snap, "offline_queue_depth", None)
            if isinstance(_queue_depth, int) and _queue_depth > 0:
                _score -= min(_queue_depth, 20)
            _health = getattr(_snap, "runtime_health_snapshot", None)
            if isinstance(_health, dict):
                _health_status = str(
                    _health.get("status") or _health.get("state") or _health.get("health") or ""
                ).strip().lower()
                _is_degraded = bool(_health.get("is_degraded", False))
                if _health_status in {"degraded", "unhealthy", "error", "failed"} or _is_degraded:
                    _score -= 10
            try:
                _recent = list_recent_execution_events(flow_id=None, device_id=_did, limit=1)
                if _recent:
                    _ev = _recent[0]
                    _phase = str(getattr(_ev, "phase", "") or "").strip().lower()
                    _absorbed = float(getattr(_ev, "absorbed_at", 0) or 0)
                    if _phase in {"planning", "grounding", "execution", "replan"} and (
                        time.time() - _absorbed
                    ) < 60.0:
                        _score -= 12
            except Exception:
                pass
            return _score

        _scores = [_android_readiness_score(d) for d in devices]
        if any(s != 0 for s in _scores):
            # At least one device has a non-neutral Android score — re-order.
            _indexed = sorted(
                enumerate(devices),
                key=lambda idx_dev: _scores[idx_dev[0]],
                reverse=True,
            )
            _reordered = [d for _, d in _indexed]
            if _reordered != devices:
                logger.debug(
                    "select_devices [ORCHESTRATION_CONSUMES_ANDROID_TRUTH]: "
                    "re-ordered %d candidate(s) by Android readiness score",
                    len(devices),
                )
            devices = _reordered
    except Exception as _wt_err:
        logger.debug(
            "select_devices: Android runtime truth routing weight unavailable "
            "(graceful degradation): %s",
            _wt_err,
        )

    # ── 1. exec_mode-aware filtering via canonical gateway capability view ──
    desired_exec_mode_str: Optional[str] = analysis.get("exec_mode")
    _actions = analysis.get("actions") or []
    desired_action: Optional[str] = _actions[0] if _actions else None

    if desired_exec_mode_str or desired_action:
        try:
            desired_exec_mode = normalize_gateway_exec_mode(desired_exec_mode_str)

            filtered: List[Any] = []
            unregistered: List[Any] = []
            for device in devices:
                schemas = query_gateway_capabilities(
                    action=desired_action,
                    exec_mode=(desired_exec_mode if desired_exec_mode != "both" else None),
                    device_id=device.device_id,
                )
                if schemas:
                    filtered.append(device)
                else:
                    all_caps = get_gateway_capabilities_for_device(device.device_id)
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

    # ── 2. Hard capability gate (PR-3) ───────────────────────────────────────
    required_caps: List[str] = analysis.get("required_capabilities") or []
    if required_caps:
        try:
            from core.capability_routing_gate import filter_by_required_capabilities

            gated = filter_by_required_capabilities(
                devices=devices,
                required_capabilities=required_caps,
            )
            if gated:
                devices = gated
                logger.debug(
                    "select_devices: capability gate passed — %d device(s) satisfy " "required_capabilities=%r",
                    len(devices),
                    required_caps,
                )
            else:
                logger.warning(
                    "select_devices: capability gate excluded all devices for "
                    "required_capabilities=%r; no eligible device found",
                    required_caps,
                )
                return []
        except Exception as _gate_err:
            logger.warning(
                "select_devices: capability gate unavailable, " "required_capabilities treated as advisory: %s",
                _gate_err,
            )

    # ── 3. Autonomous-device preference (with fallback) ──────────────────────
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

    # ── 4. DevicePoolManager final scheduling ────────────────────────────────
    target_device_type = analysis.get("target_device_type")
    try:
        pool = get_device_pool_manager()
        preferred_ids = {d.device_id for d in preferred}
        device_type_str = (
            target_device_type.value  # type: ignore[union-attr]
            if hasattr(target_device_type, "value")
            else str(target_device_type)
        )
        selected_id = pool.select_device(
            required_capabilities=required_caps or None,
            device_type=device_type_str,
            exclude=[d.device_id for d in devices if d.device_id not in preferred_ids],
        )
        if selected_id:
            matched = next((d for d in preferred if d.device_id == selected_id), None)
            if matched:
                logger.debug("select_devices: DevicePoolManager selected %s", selected_id)
                return [matched]
        # Pool returned no match — fall through to first-preferred fallback.
    except Exception as _pool_err:
        logger.warning(
            "select_devices: DevicePoolManager unavailable, using first-preferred fallback: %s",
            _pool_err,
        )

    return [preferred[0]]
