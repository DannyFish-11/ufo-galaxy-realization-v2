"""core/android_mode_gate_policy.py
====================================
Android Local / Cross-Device Mode Gate Policy — unified governance layer.

Background
----------
Prior to this module the three Android-side execution gates
(``crossDeviceEnabled``, ``goalExecutionEnabled``,
``parallelExecutionEnabled``) were only enforced in the Android-side
``AutonomousExecutionPipeline`` and partially reflected in V2 routing via
``galaxy_gateway.cross_device_switch``.  The V2 side had no single,
authoritative surface that:

* Described the **current** Android device mode (local vs cross_device).
* Evaluated all three gates as a **unified policy** rather than three
  scattered boolean checks.
* Managed **AttachedRuntimeSessionRegistry** consistency when the mode
  changed (local → cross_device or cross_device → local).
* Exposed the mode/readiness state to the **V2 operator panel** in a stable,
  serialisable form.

This module closes those four gaps.

Design principles
-----------------
1. **Additive only** — does not modify any existing module; only adds new
   public API that callers opt into.
2. **Composing, not duplicating** — delegates to existing canonical
   authorities:
   - ``core.android_device_state_store`` for runtime readiness truth.
   - ``core.attached_runtime_session_registry`` for session state.
   - ``galaxy_gateway.cross_device_switch`` for V2-side cross-device flag.
3. **Unified gate evaluation** — :func:`evaluate_android_mode_readiness`
   evaluates all three gates (runtime mode, goal execution, parallel
   execution) in one call and returns a single, typed verdict.
4. **Session registry consistency** — :func:`apply_mode_switch_to_registry`
   records the mode transition in the active session entry's metadata and,
   for cross_device → local transitions, updates the posture to
   ``control_only`` (conservative safe default).  For local → cross_device
   transitions the posture is promoted to ``join_runtime`` when the device
   passes the readiness gate.
5. **Graceful degradation** — all optional imports are wrapped; gate
   evaluations degrade to conservative verdicts when sub-systems are
   unavailable.
6. **Stable, serialisable contracts** — all dataclasses expose
   ``to_dict()`` for panel/operator consumption.

Authority sentinels
-------------------
:data:`ANDROID_MODE_GATE_POLICY_AUTHORITY`
:data:`UNIFIED_GATE_POLICY_SENTINELS`

Enums / constants
-----------------
:class:`AndroidDeviceMode`

Dataclasses
-----------
:class:`AndroidModeState`
:class:`GateEvalResult`
:class:`AndroidModeReadinessVerdict`

Functions
---------
``evaluate_android_mode_readiness(device_id, ...)``
    Unified gate evaluation: returns :class:`AndroidModeReadinessVerdict`.
``apply_mode_switch_to_registry(device_id, from_mode, to_mode, ...)``
    Applies mode-switch semantics to the session registry entry.
``build_mode_state_for_device(device_id, ...)``
    Read-only: assembles :class:`AndroidModeState` from the store.
``build_cross_device_readiness_panel_dict(device_ids, ...)``
    Aggregates per-device readiness into a panel-ready summary dict.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.AndroidModeGatePolicy")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

ANDROID_MODE_GATE_POLICY_AUTHORITY: str = (
    "ANDROID_MODE_GATE_POLICY_V1: "
    "core.android_mode_gate_policy is the single, authoritative unified "
    "governance layer for Android local / cross-device mode gates.  It "
    "evaluates crossDeviceEnabled, goalExecutionEnabled, and "
    "parallelExecutionEnabled as a unified policy rather than three "
    "scattered boolean checks, manages session registry consistency on "
    "mode switch, and exposes the authoritative mode / readiness state to "
    "the V2 operator panel."
)

UNIFIED_GATE_POLICY_SENTINELS: str = (
    "POLICY::UNIFIED_GATE_POLICY: "
    "All code that needs to determine Android device mode eligibility for "
    "cross-device dispatch, takeover, or goal execution MUST use "
    "evaluate_android_mode_readiness() rather than reading individual "
    "AppSettings booleans or DeviceStateSnapshot fields directly.  This is "
    "the canonical authority for the unified gate verdict."
)

MODE_SWITCH_SESSION_CONSISTENCY_POLICY: str = (
    "POLICY::MODE_SWITCH_SESSION_CONSISTENCY: "
    "Any code that changes the Android device mode (local↔cross_device) MUST "
    "call apply_mode_switch_to_registry() to propagate the change into the "
    "AttachedRuntimeSessionRegistry.  The registry entry metadata carries the "
    "mode transition history and the posture field is updated to reflect the "
    "new mode requirements."
)

CROSS_DEVICE_READINESS_GATE_POLICY: str = (
    "POLICY::CROSS_DEVICE_READINESS_GATE: "
    "A device is cross-device ready only when ALL of the following hold: "
    "(1) V2-side cross_device_enabled switch is ON, "
    "(2) DeviceStateSnapshot.local_loop_ready is True (or no snapshot exists "
    "    and the device has an active session with join_runtime posture), "
    "(3) the device has an active session in AttachedRuntimeSessionRegistry, "
    "(4) that session's posture is join_runtime."
)

CANONICAL_ANDROID_EXECUTION_GATE_POLICY: str = (
    "POLICY::CANONICAL_ANDROID_EXECUTION_GATE: "
    "resolve_android_execution_gate_decision() is the canonical gate contract "
    "for allow/deny/defer outcomes from unified Android policy eligibility, "
    "readiness, capability availability, busy state, fallback tier, and "
    "local inference availability."
)

ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY: str = (
    "POLICY::ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS: "
    "When Android-originated capability truth quality is 'missing', 'stale', "
    "'conflicting', 'partial', 'malformed', 'unknown', 'incompatible', or "
    "'downgraded', resolve_android_execution_gate_decision() MUST return "
    "'deny' rather than allowing execution to proceed on absent, malformed, "
    "drifted, incompatible, or otherwise unverified evidence.  Absent Android "
    "truth is NOT treated as implicit positive evidence.  The decision reason "
    "will include "
    "'android_capability_truth_degraded:<quality>' for observability."
)

ANDROID_MODE_GATE_POLICY_PR_SENTINEL: str = (
    "ANDROID_MODE_GATE_POLICY_PR_SENTINEL::v1 present"
)

# Truth-quality classes that degrade the canonical execution gate decision.
# Any proof_input_class from classify_canonical_proof_input_diagnosis() that
# falls in this set will cause resolve_android_execution_gate_decision() to
# return decision="deny" regardless of other gate inputs.
_ANDROID_CAPABILITY_TRUTH_DEGRADING_CLASSES: frozenset = frozenset({
    "missing",
    "stale",
    "conflicting",
    "partial",
    "malformed",
    "unknown",
    "incompatible",
    "downgraded",
})

# ---------------------------------------------------------------------------
# AndroidDeviceMode
# ---------------------------------------------------------------------------


class AndroidDeviceMode(str, Enum):
    """Canonical Android device operating mode.

    Values
    ------
    local
        Device operates as a local-only agent carrier.  Cross-device
        execution gates (goal_execution, parallel_subtask, takeover_request)
        are disabled.  Device uses its own NL / inference pipeline locally
        or delegates to V2 without accepting V2-driven takeover.
    cross_device
        Device participates in the V2-driven cross-device execution protocol.
        All three gates (crossDeviceEnabled, goalExecutionEnabled,
        parallelExecutionEnabled) are enabled on the Android side and the
        V2 cross-device switch is ON.
    transitioning
        Mode change is in progress; no dispatch or takeover should be
        attempted until the device reaches a stable mode.
    unknown
        Mode could not be determined (e.g. no snapshot available).
    """

    local = "local"
    cross_device = "cross_device"
    transitioning = "transitioning"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "AndroidDeviceMode":
        """Return the enum member for *value*, or ``unknown`` if not found."""
        try:
            return cls(value)
        except ValueError:
            return cls.unknown


# ---------------------------------------------------------------------------
# GateEvalResult
# ---------------------------------------------------------------------------


@dataclass
class GateEvalResult:
    """Result of evaluating a single mode gate.

    Attributes
    ----------
    gate_name
        Name of the evaluated gate (e.g. ``"cross_device_enabled"``).
    passed
        ``True`` if the gate condition is satisfied.
    reason
        Human-readable explanation.
    source
        Where the gate value was read from.
    """

    gate_name: str
    passed: bool
    reason: str = ""
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_name": self.gate_name,
            "passed": self.passed,
            "reason": self.reason,
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# AndroidModeState
# ---------------------------------------------------------------------------


@dataclass
class AndroidModeState:
    """Authoritative V2-side snapshot of a single Android device's mode state.

    Assembled from DeviceStateSnapshot and AttachedRuntimeSessionRegistry.
    This is the canonical representation that panel/operator surfaces MUST
    consume rather than reading individual fields from scattered sources.

    Attributes
    ----------
    device_id
        Android device identifier.
    mode
        Current inferred :class:`AndroidDeviceMode`.
    cross_device_enabled
        Whether the Android-side crossDeviceEnabled gate is ON.  Inferred
        from DeviceStateSnapshot.local_loop_config when available.
    goal_execution_enabled
        Whether the Android-side goalExecutionEnabled gate is ON.  Inferred
        from DeviceStateSnapshot.local_loop_config when available.
    parallel_execution_enabled
        Whether the Android-side parallelExecutionEnabled gate is ON.
        Inferred from DeviceStateSnapshot.local_loop_config when available.
    session_active
        Whether an active AttachedRuntimeSessionRegistry entry exists.
    session_posture
        The posture field of the active session (``"join_runtime"`` or
        ``"control_only"``).  Empty string when no active session.
    session_id
        The active session's ``runtime_session_id``, or empty string.
    local_loop_ready
        From DeviceStateSnapshot.local_loop_ready.
    model_ready
        From DeviceStateSnapshot.model_ready.
    accessibility_ready
        From DeviceStateSnapshot.accessibility_ready.
    snapshot_age_s
        Age of the DeviceStateSnapshot in seconds at the time this object
        was built.  ``None`` if no snapshot exists.
    assembled_at
        Unix epoch seconds when this object was assembled.
    """

    device_id: str
    mode: AndroidDeviceMode = AndroidDeviceMode.unknown
    cross_device_enabled: bool = False
    goal_execution_enabled: bool = False
    parallel_execution_enabled: bool = False
    session_active: bool = False
    session_posture: str = ""
    session_id: str = ""
    local_loop_ready: Optional[bool] = None
    model_ready: Optional[bool] = None
    accessibility_ready: Optional[bool] = None
    snapshot_age_s: Optional[float] = None
    assembled_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "mode": self.mode.value,
            "cross_device_enabled": self.cross_device_enabled,
            "goal_execution_enabled": self.goal_execution_enabled,
            "parallel_execution_enabled": self.parallel_execution_enabled,
            "session_active": self.session_active,
            "session_posture": self.session_posture,
            "session_id": self.session_id,
            "local_loop_ready": self.local_loop_ready,
            "model_ready": self.model_ready,
            "accessibility_ready": self.accessibility_ready,
            "snapshot_age_s": self.snapshot_age_s,
            "assembled_at": self.assembled_at,
            "_authority": ANDROID_MODE_GATE_POLICY_AUTHORITY,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))


# ---------------------------------------------------------------------------
# AndroidModeReadinessVerdict
# ---------------------------------------------------------------------------


@dataclass
class AndroidModeReadinessVerdict:
    """Unified mode gate evaluation result for a single Android device.

    Returned by :func:`evaluate_android_mode_readiness`.

    Attributes
    ----------
    device_id
        The evaluated device.
    mode
        Current inferred :class:`AndroidDeviceMode`.
    is_cross_device_ready
        ``True`` iff all gates required for cross-device operation pass.
    is_dispatch_eligible
        ``True`` iff the device can receive a dispatched goal execution task.
    is_takeover_eligible
        ``True`` iff the device can accept a takeover_request.
    gate_results
        Individual :class:`GateEvalResult` objects, one per gate evaluated.
    blocking_gates
        Names of gates that did not pass (subset of gate_results).
    evaluated_at
        Unix epoch seconds when this verdict was produced.
    """

    device_id: str
    mode: AndroidDeviceMode = AndroidDeviceMode.unknown
    is_cross_device_ready: bool = False
    is_dispatch_eligible: bool = False
    is_takeover_eligible: bool = False
    gate_results: List[GateEvalResult] = field(default_factory=list)
    blocking_gates: List[str] = field(default_factory=list)
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "mode": self.mode.value,
            "is_cross_device_ready": self.is_cross_device_ready,
            "is_dispatch_eligible": self.is_dispatch_eligible,
            "is_takeover_eligible": self.is_takeover_eligible,
            "gate_results": [g.to_dict() for g in self.gate_results],
            "blocking_gates": list(self.blocking_gates),
            "evaluated_at": self.evaluated_at,
            "_authority": ANDROID_MODE_GATE_POLICY_AUTHORITY,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))


@dataclass(frozen=True)
class AndroidCanonicalExecutionGateDecision:
    """Canonical execution gate decision for cross-repo allow/deny/defer semantics."""

    decision: str = "deny"
    policy_eligible: bool = False
    readiness_ready: bool = False
    capability_ready: bool = False
    execution_busy: bool = False
    local_inference_available: bool = False
    fallback_tier: Optional[str] = None
    model_ready: Optional[bool] = None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    # PR-7A: Android capability truth quality that influenced this decision.
    # None when the caller did not supply truth quality information.
    android_capability_truth_quality: Optional[str] = None
    # PR-7A: True when absent/stale/conflicting Android truth caused a deny.
    android_capability_truth_degraded: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "policy_eligible": self.policy_eligible,
            "readiness_ready": self.readiness_ready,
            "capability_ready": self.capability_ready,
            "execution_busy": self.execution_busy,
            "local_inference_available": self.local_inference_available,
            "fallback_tier": self.fallback_tier,
            "model_ready": self.model_ready,
            "reasons": list(self.reasons),
            "android_capability_truth_quality": self.android_capability_truth_quality,
            "android_capability_truth_degraded": self.android_capability_truth_degraded,
            "_policy": CANONICAL_ANDROID_EXECUTION_GATE_POLICY,
        }


def resolve_android_execution_gate_decision(
    *,
    policy_eligible: bool,
    readiness_ready: bool,
    execution_busy: bool,
    local_inference_available: bool,
    fallback_tier: Optional[str],
    model_ready: Optional[bool] = None,
    android_capability_truth_quality: Optional[str] = None,
) -> AndroidCanonicalExecutionGateDecision:
    """Resolve canonical allow/deny/defer decision from unified Android gate inputs.

    Parameters
    ----------
    policy_eligible:
        Whether the device is policy-eligible for dispatch.
    readiness_ready:
        Whether the device passed all readiness gates.
    execution_busy:
        Whether the device is currently busy with an execution.
    local_inference_available:
        Whether local inference is available on the device.
    fallback_tier:
        Optional fallback tier name.
    model_ready:
        Whether the model is ready (optional).
    android_capability_truth_quality:
        The ``proof_input_class`` from
        :func:`~core.unified_execution_governance.classify_canonical_proof_input_diagnosis`.
        When this is any non-complete or incompatible capability-truth class
        (``'missing'``, ``'stale'``, ``'conflicting'``, ``'partial'``,
        ``'malformed'``, ``'unknown'``, ``'incompatible'``, or
        ``'downgraded'``), the gate decision is immediately forced to
        ``'deny'`` regardless of other gate inputs.  Absent Android truth is
        NOT treated as positive evidence — see
        :data:`ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY`.
    """
    normalized_fallback_tier = str(fallback_tier or "").strip() or None
    has_fallback = bool(normalized_fallback_tier)
    capability_ready = bool(local_inference_available or has_fallback or model_ready is True)
    reasons: List[str] = []

    # PR-7A: Check Android capability truth quality first.
    # Any non-complete, incompatible, or otherwise degraded Android truth
    # degrades the gate decision to "deny" — absence is not positive evidence.
    normalized_truth_quality = str(android_capability_truth_quality or "").strip().lower() or None
    truth_degraded = normalized_truth_quality in _ANDROID_CAPABILITY_TRUTH_DEGRADING_CLASSES
    if truth_degraded:
        reasons.append(
            f"android_capability_truth_degraded:{normalized_truth_quality}"
        )
        return AndroidCanonicalExecutionGateDecision(
            decision="deny",
            policy_eligible=bool(policy_eligible),
            readiness_ready=bool(readiness_ready),
            capability_ready=capability_ready,
            execution_busy=bool(execution_busy),
            local_inference_available=bool(local_inference_available),
            fallback_tier=normalized_fallback_tier,
            model_ready=model_ready,
            reasons=tuple(reasons),
            android_capability_truth_quality=normalized_truth_quality,
            android_capability_truth_degraded=True,
        )

    decision = "allow"

    if not policy_eligible:
        decision = "deny"
        reasons.append("policy_ineligible")
    elif not readiness_ready:
        decision = "deny"
        reasons.append("readiness_not_ready")
    elif not capability_ready:
        decision = "deny"
        reasons.append("capability_unavailable")
    elif execution_busy:
        decision = "defer"
        reasons.append("execution_busy")
    else:
        reasons.append("all_gate_conditions_satisfied")

    if local_inference_available:
        reasons.append("local_inference_available")
    if has_fallback:
        reasons.append(f"fallback_tier:{normalized_fallback_tier}")

    return AndroidCanonicalExecutionGateDecision(
        decision=decision,
        policy_eligible=bool(policy_eligible),
        readiness_ready=bool(readiness_ready),
        capability_ready=capability_ready,
        execution_busy=bool(execution_busy),
        local_inference_available=bool(local_inference_available),
        fallback_tier=normalized_fallback_tier,
        model_ready=model_ready,
        reasons=tuple(reasons),
        android_capability_truth_quality=normalized_truth_quality,
        android_capability_truth_degraded=False,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_V2_CROSS_DEVICE_SWITCH_GATE = "v2_cross_device_switch"
_ANDROID_CROSS_DEVICE_GATE = "android_cross_device_enabled"
_ANDROID_GOAL_EXEC_GATE = "android_goal_execution_enabled"
_ANDROID_PARALLEL_GATE = "android_parallel_execution_enabled"
_SESSION_ACTIVE_GATE = "session_active"
_SESSION_POSTURE_GATE = "session_posture_join_runtime"
_DEVICE_LOCAL_LOOP_GATE = "device_local_loop_ready"

_POSTURE_JOIN_RUNTIME = "join_runtime"
_POSTURE_CONTROL_ONLY = "control_only"

# Maximum number of mode-switch history entries kept per session entry.
# Older entries are evicted (FIFO) when the limit is reached.
_MODE_SWITCH_HISTORY_MAX_LEN = 10


def _coerce_optional_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value in (0, 0.0):
            return False
        if value in (1, 1.0):
            return True
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    return None


def _read_explicit_gate_bool(config: Dict[str, Any], *keys: str) -> Optional[bool]:
    for key in keys:
        if key in config:
            return _coerce_optional_bool(config.get(key))
    return None


def _check_v2_cross_device_switch() -> GateEvalResult:
    """Check whether the V2-side cross-device switch is ON."""
    try:
        from galaxy_gateway.cross_device_switch import is_cross_device_enabled
        enabled = is_cross_device_enabled()
        return GateEvalResult(
            gate_name=_V2_CROSS_DEVICE_SWITCH_GATE,
            passed=enabled,
            reason="V2 cross-device switch is ON" if enabled else "V2 cross-device switch is OFF",
            source="galaxy_gateway.cross_device_switch.is_cross_device_enabled",
        )
    except Exception as exc:
        logger.debug("_check_v2_cross_device_switch: unavailable: %s", exc)
        return GateEvalResult(
            gate_name=_V2_CROSS_DEVICE_SWITCH_GATE,
            passed=False,
            reason=f"V2 cross-device switch module unavailable: {exc}",
            source="unavailable",
        )


def _check_session_gate(device_id: str) -> tuple:
    """Return (session_active_result, session_posture_result, session_id)."""
    session_id = ""
    try:
        from core.attached_runtime_session_registry import lookup_session_by_device
        entry = lookup_session_by_device(device_id)
        if entry is None or not entry.is_active():
            return (
                GateEvalResult(
                    gate_name=_SESSION_ACTIVE_GATE,
                    passed=False,
                    reason="No active session in AttachedRuntimeSessionRegistry",
                    source="core.attached_runtime_session_registry",
                ),
                GateEvalResult(
                    gate_name=_SESSION_POSTURE_GATE,
                    passed=False,
                    reason="No active session; posture unknown",
                    source="core.attached_runtime_session_registry",
                ),
                session_id,
            )
        session_id = entry.runtime_session_id
        active_result = GateEvalResult(
            gate_name=_SESSION_ACTIVE_GATE,
            passed=True,
            reason=f"Active session: runtime_session_id={session_id!r}",
            source="core.attached_runtime_session_registry",
        )
        posture = (entry.posture or "").strip().lower()
        posture_ok = posture == _POSTURE_JOIN_RUNTIME
        posture_result = GateEvalResult(
            gate_name=_SESSION_POSTURE_GATE,
            passed=posture_ok,
            reason=(
                f"Posture is {posture!r} (join_runtime required for cross-device)"
            ),
            source="core.attached_runtime_session_registry",
        )
        return active_result, posture_result, session_id
    except Exception as exc:
        logger.debug("_check_session_gate: error for device_id=%r: %s", device_id, exc)
        err_result = GateEvalResult(
            gate_name=_SESSION_ACTIVE_GATE,
            passed=False,
            reason=f"Session registry unavailable: {exc}",
            source="unavailable",
        )
        err_posture = GateEvalResult(
            gate_name=_SESSION_POSTURE_GATE,
            passed=False,
            reason=f"Session registry unavailable: {exc}",
            source="unavailable",
        )
        return err_result, err_posture, session_id


def _check_snapshot_gates(device_id: str) -> tuple:
    """Return (cross_device_gate, goal_exec_gate, parallel_gate, local_loop_gate, snapshot_age_s).

    Prefers normalized Android capability-report semantics when available.
    Falls back to explicit DeviceStateSnapshot.local_loop_config booleans when
    no capability-report semantics have been absorbed yet.
    """
    snapshot_age_s: Optional[float] = None
    now = time.time()
    semantics: Dict[str, Any] = {}

    try:
        from core.android_device_state_store import (
            get_device_capability_report_semantics,
            get_device_state_snapshot,
        )
        snap = get_device_state_snapshot(device_id)
        semantics = get_device_capability_report_semantics(device_id) or {}
    except Exception as exc:
        logger.debug("_check_snapshot_gates: store unavailable for %r: %s", device_id, exc)
        snap = None
        semantics = {}

    if isinstance(semantics, dict) and semantics:
        semantics_state = str(
            semantics.get("canonical_gate_metadata_state") or "missing"
        ).strip().lower()
        if semantics_state != "complete":
            diagnosis = semantics.get("canonical_gate_contract_diagnosis")
            reason = (
                "Android capability_report canonical gate contract is "
                f"{semantics_state}; diagnosis={diagnosis!r}; "
                f"missing={semantics.get('missing_canonical_gate_metadata_keys', [])}; "
                f"malformed={semantics.get('malformed_canonical_gate_metadata_keys', [])}; "
                f"unknown={semantics.get('unknown_canonical_gate_metadata_keys', [])}; "
                f"conflicts={semantics.get('canonical_gate_semantic_conflicts', [])}; "
                f"downgraded={semantics.get('downgraded_canonical_gate_metadata_reasons', [])}; "
                "readiness_impact="
                f"{semantics.get('canonical_gate_governance_readiness_impact', 'block')}"
            )
            local_loop_reason = reason
            if snap is None:
                local_loop_reason += "; local_loop_ready unavailable without DeviceStateSnapshot"
            return (
                GateEvalResult(_ANDROID_CROSS_DEVICE_GATE, False, reason, "android_capability_report_semantics"),
                GateEvalResult(_ANDROID_GOAL_EXEC_GATE, False, reason, "android_capability_report_semantics"),
                GateEvalResult(_ANDROID_PARALLEL_GATE, False, reason, "android_capability_report_semantics"),
                GateEvalResult(
                    _DEVICE_LOCAL_LOOP_GATE,
                    False,
                    local_loop_reason,
                    "android_capability_report_semantics",
                ),
                snapshot_age_s,
            )

        reported_mode = str(semantics.get("canonical_mode") or "").strip().lower() or "unknown"
        reported_mode_state = semantics.get("reported_mode_state")
        if reported_mode == AndroidDeviceMode.cross_device.value:
            cross_device_ok = bool(semantics.get("cross_device_eligibility") is True)
            goal_exec_ok = bool(semantics.get("goal_execution_eligibility") is True)
            parallel_ok = bool(semantics.get("parallel_execution_eligibility") is True)
            cross_reason_prefix = (
                f"Android capability_report mode_state={reported_mode_state!r} "
                f"canonical_mode={reported_mode!r}"
            )
        else:
            cross_device_ok = False
            goal_exec_ok = False
            parallel_ok = False
            cross_reason_prefix = (
                f"Android capability_report canonical_mode={reported_mode!r} "
                "does not permit cross-device dispatch"
            )

        local_loop_ok = bool(getattr(snap, "local_loop_ready", None))
        if snap is not None:
            snapshot_age_s = now - (snap.absorbed_at or now)
            local_loop_reason = (
                "DeviceStateSnapshot.local_loop_ready="
                + str(local_loop_ok)
            )
        else:
            local_loop_ok = False
            local_loop_reason = (
                "DeviceStateSnapshot.local_loop_ready unavailable while consuming "
                "Android capability_report semantics"
            )

        return (
            GateEvalResult(
                _ANDROID_CROSS_DEVICE_GATE,
                cross_device_ok,
                f"{cross_reason_prefix}; cross_device_eligibility={semantics.get('cross_device_eligibility')!r}",
                "android_capability_report_semantics",
            ),
            GateEvalResult(
                _ANDROID_GOAL_EXEC_GATE,
                goal_exec_ok,
                f"{cross_reason_prefix}; goal_execution_eligibility={semantics.get('goal_execution_eligibility')!r}",
                "android_capability_report_semantics",
            ),
            GateEvalResult(
                _ANDROID_PARALLEL_GATE,
                parallel_ok,
                f"{cross_reason_prefix}; "
                "parallel_execution_eligibility="
                f"{semantics.get('parallel_execution_eligibility')!r}",
                "android_capability_report_semantics",
            ),
            GateEvalResult(
                _DEVICE_LOCAL_LOOP_GATE,
                local_loop_ok,
                local_loop_reason,
                "DeviceStateSnapshot",
            ),
            snapshot_age_s,
        )

    if snap is None:
        # No snapshot — cannot confirm Android-side gates.
        # Conservative: all Android gates fail; local_loop unknown.
        na_reason = "No DeviceStateSnapshot available for this device"
        return (
            GateEvalResult(_ANDROID_CROSS_DEVICE_GATE, False, na_reason, "no_snapshot"),
            GateEvalResult(_ANDROID_GOAL_EXEC_GATE, False, na_reason, "no_snapshot"),
            GateEvalResult(_ANDROID_PARALLEL_GATE, False, na_reason, "no_snapshot"),
            GateEvalResult(_DEVICE_LOCAL_LOOP_GATE, False, na_reason, "no_snapshot"),
            None,
        )

    snapshot_age_s = now - (snap.absorbed_at or now)
    cfg: Dict[str, Any] = snap.local_loop_config or {}
    cross_device_ok = _read_explicit_gate_bool(
        cfg,
        "crossDeviceEnabled",
        "cross_device_enabled",
    )
    goal_exec_ok = _read_explicit_gate_bool(
        cfg,
        "goalExecutionEnabled",
        "goal_execution_enabled",
    )
    parallel_ok = _read_explicit_gate_bool(
        cfg,
        "parallelExecutionEnabled",
        "parallel_execution_enabled",
    )

    local_loop_ok = bool(snap.local_loop_ready)

    return (
        GateEvalResult(
            _ANDROID_CROSS_DEVICE_GATE,
            cross_device_ok is True,
            (
                "Android crossDeviceEnabled=" + str(cross_device_ok)
                if cross_device_ok is not None
                else "Android crossDeviceEnabled missing from DeviceStateSnapshot.local_loop_config"
            ),
            "DeviceStateSnapshot.local_loop_config",
        ),
        GateEvalResult(
            _ANDROID_GOAL_EXEC_GATE,
            goal_exec_ok is True,
            (
                "Android goalExecutionEnabled=" + str(goal_exec_ok)
                if goal_exec_ok is not None
                else "Android goalExecutionEnabled missing from DeviceStateSnapshot.local_loop_config"
            ),
            "DeviceStateSnapshot.local_loop_config",
        ),
        GateEvalResult(
            _ANDROID_PARALLEL_GATE,
            parallel_ok is True,
            (
                "Android parallelExecutionEnabled=" + str(parallel_ok)
                if parallel_ok is not None
                else "Android parallelExecutionEnabled missing from DeviceStateSnapshot.local_loop_config"
            ),
            "DeviceStateSnapshot.local_loop_config",
        ),
        GateEvalResult(
            _DEVICE_LOCAL_LOOP_GATE, local_loop_ok,
            "DeviceStateSnapshot.local_loop_ready=" + str(local_loop_ok),
            "DeviceStateSnapshot",
        ),
        snapshot_age_s,
    )


# ---------------------------------------------------------------------------
# build_mode_state_for_device
# ---------------------------------------------------------------------------


def build_mode_state_for_device(
    device_id: str,
    *,
    registry: Optional[Any] = None,
) -> AndroidModeState:
    """Assemble a read-only :class:`AndroidModeState` for *device_id*.

    Reads from DeviceStateSnapshot (for gate booleans / readiness) and
    AttachedRuntimeSessionRegistry (for session state).  Does not evaluate
    the full readiness verdict — see :func:`evaluate_android_mode_readiness`
    for the decision-grade output.

    Parameters
    ----------
    device_id
        Android device identifier.
    registry
        Optional registry override (for testing).

    Returns
    -------
    AndroidModeState
        Always returns a valid object; fields default to safe values when
        sources are unavailable.
    """
    state = AndroidModeState(device_id=device_id)

    # ── Session ────────────────────────────────────────────────────────────
    try:
        from core.attached_runtime_session_registry import lookup_session_by_device
        entry = lookup_session_by_device(device_id, registry=registry)
        if entry is not None and entry.is_active():
            state.session_active = True
            state.session_posture = (entry.posture or "").strip().lower()
            state.session_id = entry.runtime_session_id
    except Exception as exc:
        logger.debug("build_mode_state_for_device: session lookup failed: %s", exc)

    # ── Snapshot gates ─────────────────────────────────────────────────────
    reported_mode: Optional[str] = None
    try:
        from core.android_device_state_store import (
            get_device_capability_report_semantics,
            get_device_state_snapshot,
        )
        snap = get_device_state_snapshot(device_id)
        semantics = get_device_capability_report_semantics(device_id)
        if isinstance(semantics, dict):
            _reported_mode = semantics.get("canonical_mode")
            if isinstance(_reported_mode, str) and _reported_mode:
                reported_mode = _reported_mode
        if snap is not None:
            cfg = snap.local_loop_config or {}
            state.cross_device_enabled = bool(
                cfg.get("crossDeviceEnabled", cfg.get("cross_device_enabled", False))
            )
            state.goal_execution_enabled = bool(
                cfg.get("goalExecutionEnabled", cfg.get("goal_execution_enabled", False))
            )
            state.parallel_execution_enabled = bool(
                cfg.get("parallelExecutionEnabled", cfg.get("parallel_execution_enabled", False))
            )
            state.local_loop_ready = snap.local_loop_ready
            state.model_ready = snap.model_ready
            state.accessibility_ready = snap.accessibility_ready
            state.snapshot_age_s = time.time() - (snap.absorbed_at or time.time())
    except Exception as exc:
        logger.debug("build_mode_state_for_device: snapshot read failed: %s", exc)

    # ── Infer mode ────────────────────────────────────────────────────────
    if reported_mode and (state.session_active or state.snapshot_age_s is not None):
        state.mode = AndroidDeviceMode.from_string(reported_mode)
    elif state.cross_device_enabled and state.session_active:
        state.mode = AndroidDeviceMode.cross_device
    elif state.session_active:
        state.mode = AndroidDeviceMode.local
    else:
        state.mode = AndroidDeviceMode.unknown

    return state


# ---------------------------------------------------------------------------
# evaluate_android_mode_readiness
# ---------------------------------------------------------------------------


def evaluate_android_mode_readiness(
    device_id: str,
    *,
    require_goal_execution: bool = True,
    require_parallel_execution: bool = False,
    require_local_loop_ready: bool = True,
    registry: Optional[Any] = None,
) -> AndroidModeReadinessVerdict:
    """Evaluate the unified mode gate policy for *device_id*.

    This is the **canonical pre-dispatch authority** for Android cross-device
    mode eligibility.  Callers that need to decide whether a device can
    accept ``goal_execution``, ``parallel_subtask``, or
    ``takeover_request`` MUST call this function rather than checking
    individual gate booleans.

    Parameters
    ----------
    device_id
        Android device identifier.
    require_goal_execution
        When ``True`` (default), fail if the goal_execution gate is OFF.
    require_parallel_execution
        When ``True``, fail if the parallel_execution gate is OFF.
        Default ``False`` because parallel execution is an optional feature.
    require_local_loop_ready
        When ``True`` (default), fail if local_loop_ready is False or None.
    registry
        Optional registry override (for testing).

    Returns
    -------
    AndroidModeReadinessVerdict
        Always returns a valid verdict; never raises.
    """
    try:
        return _evaluate_readiness_impl(
            device_id=device_id,
            require_goal_execution=require_goal_execution,
            require_parallel_execution=require_parallel_execution,
            require_local_loop_ready=require_local_loop_ready,
            registry=registry,
        )
    except Exception as exc:
        logger.warning(
            "evaluate_android_mode_readiness: internal error for device_id=%r: %s",
            device_id, exc, exc_info=True,
        )
        return AndroidModeReadinessVerdict(
            device_id=device_id,
            mode=AndroidDeviceMode.unknown,
            is_cross_device_ready=False,
            is_dispatch_eligible=False,
            is_takeover_eligible=False,
            gate_results=[
                GateEvalResult(
                    gate_name="policy_eval",
                    passed=False,
                    reason=f"Internal error: {exc}",
                    source="android_mode_gate_policy",
                )
            ],
            blocking_gates=["policy_eval"],
        )


def _evaluate_readiness_impl(
    device_id: str,
    *,
    require_goal_execution: bool,
    require_parallel_execution: bool,
    require_local_loop_ready: bool,
    registry: Optional[Any],
) -> AndroidModeReadinessVerdict:
    """Internal implementation — evaluates gates in priority order."""
    gates: List[GateEvalResult] = []
    blocking: List[str] = []

    # Gate 1: V2-side cross-device switch
    v2_switch = _check_v2_cross_device_switch()
    gates.append(v2_switch)
    if not v2_switch.passed:
        blocking.append(v2_switch.gate_name)

    # Gate 2: session active + posture
    session_active_r, session_posture_r, session_id = _check_session_gate(device_id)
    gates.extend([session_active_r, session_posture_r])
    if not session_active_r.passed:
        blocking.append(session_active_r.gate_name)
    if not session_posture_r.passed:
        blocking.append(session_posture_r.gate_name)

    # Gate 3: Android-side snapshot gates + readiness
    (
        android_cross_device_r,
        android_goal_exec_r,
        android_parallel_r,
        local_loop_r,
        snapshot_age_s,
    ) = _check_snapshot_gates(device_id)
    gates.append(android_cross_device_r)
    if not android_cross_device_r.passed:
        blocking.append(android_cross_device_r.gate_name)

    if require_goal_execution:
        gates.append(android_goal_exec_r)
        if not android_goal_exec_r.passed:
            blocking.append(android_goal_exec_r.gate_name)

    if require_parallel_execution:
        gates.append(android_parallel_r)
        if not android_parallel_r.passed:
            blocking.append(android_parallel_r.gate_name)

    if require_local_loop_ready:
        gates.append(local_loop_r)
        if not local_loop_r.passed:
            blocking.append(local_loop_r.gate_name)

    # Derive mode
    cross_device_v2_on = v2_switch.passed
    android_cross_on = android_cross_device_r.passed
    posture_join = session_posture_r.passed
    if cross_device_v2_on and android_cross_on and session_active_r.passed and posture_join:
        inferred_mode = AndroidDeviceMode.cross_device
    elif session_active_r.passed:
        inferred_mode = AndroidDeviceMode.local
    else:
        inferred_mode = AndroidDeviceMode.unknown

    is_cross_device_ready = len(blocking) == 0

    # dispatch eligibility: cross_device_ready AND (goal_execution gate passes
    # when required)
    is_dispatch_eligible = (
        v2_switch.passed
        and session_active_r.passed
        and session_posture_r.passed
        and android_cross_device_r.passed
        and (android_goal_exec_r.passed if require_goal_execution else True)
    )

    # takeover eligibility: same as dispatch + local_loop_ready
    is_takeover_eligible = is_dispatch_eligible and local_loop_r.passed

    return AndroidModeReadinessVerdict(
        device_id=device_id,
        mode=inferred_mode,
        is_cross_device_ready=is_cross_device_ready,
        is_dispatch_eligible=is_dispatch_eligible,
        is_takeover_eligible=is_takeover_eligible,
        gate_results=gates,
        blocking_gates=blocking,
    )


# ---------------------------------------------------------------------------
# apply_mode_switch_to_registry
# ---------------------------------------------------------------------------


def apply_mode_switch_to_registry(
    device_id: str,
    from_mode: AndroidDeviceMode,
    to_mode: AndroidDeviceMode,
    *,
    session_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    registry: Optional[Any] = None,
) -> Optional[Any]:
    """Apply mode-switch semantics to the AttachedRuntimeSessionRegistry entry.

    This is the canonical function that MUST be called whenever the Android
    device mode changes.  It updates the session entry's posture and records
    the mode transition in the entry's metadata.

    Transition semantics
    --------------------
    local → cross_device:
        Promotes the session posture to ``join_runtime`` so the device
        becomes eligible for dispatch and takeover.  The mode transition is
        recorded in metadata under ``mode_switch_history``.

    cross_device → local:
        Demotes the session posture to ``control_only`` (safe conservative
        default) to prevent the device from being dispatched to while in
        local mode.  The mode transition is recorded in metadata.

    Any other transition (e.g. unknown → local, local → local):
        Records the transition in metadata but does NOT change the posture.
        Callers can force a posture update by calling
        :func:`~core.attached_runtime_session_registry.update_session_posture`
        directly.

    Parameters
    ----------
    device_id
        Android device identifier.
    from_mode
        Previous :class:`AndroidDeviceMode`.
    to_mode
        New :class:`AndroidDeviceMode`.
    session_id
        Optional external session identifier to cross-check.  When supplied
        and the active session's session_id does not match, the update is
        skipped and ``None`` is returned.
    metadata
        Additional metadata to merge into the entry.
    registry
        Optional registry override (for testing).

    Returns
    -------
    AttachedSessionRegistryEntry | None
        The updated entry, or ``None`` when no active session exists for
        the device (or when the session_id cross-check fails).
    """
    try:
        return _apply_mode_switch_impl(
            device_id=device_id,
            from_mode=from_mode,
            to_mode=to_mode,
            session_id=session_id,
            metadata=metadata,
            registry=registry,
        )
    except Exception as exc:
        logger.warning(
            "apply_mode_switch_to_registry: error for device_id=%r %s→%s: %s",
            device_id, from_mode.value, to_mode.value, exc, exc_info=True,
        )
        return None


def _apply_mode_switch_impl(
    device_id: str,
    from_mode: AndroidDeviceMode,
    to_mode: AndroidDeviceMode,
    *,
    session_id: str,
    metadata: Optional[Dict[str, Any]],
    registry: Optional[Any],
) -> Optional[Any]:
    """Internal implementation of mode switch registry update."""
    from core.attached_runtime_session_registry import (
        lookup_session_by_device,
        update_session_posture,
    )

    entry = lookup_session_by_device(device_id, registry=registry)
    if entry is None or not entry.is_active():
        logger.debug(
            "apply_mode_switch_to_registry: no active session for device_id=%r",
            device_id,
        )
        return None

    # Optional cross-check: if the caller provided a session_id we verify it
    # against both the external session_id and the runtime_session_id.
    if session_id:
        if session_id not in (entry.session_id, entry.runtime_session_id):
            logger.debug(
                "apply_mode_switch_to_registry: session_id mismatch for "
                "device_id=%r (provided=%r, stored=%r/%r) — skipping",
                device_id, session_id, entry.session_id, entry.runtime_session_id,
            )
            return None

    # Build the merged metadata including mode transition history.
    now = time.time()
    switch_record = {
        "from_mode": from_mode.value,
        "to_mode": to_mode.value,
        "switched_at": now,
    }
    existing_meta = dict(entry.metadata)
    history: List[Dict[str, Any]] = list(existing_meta.get("mode_switch_history", []))
    history.append(switch_record)
    # Keep last _MODE_SWITCH_HISTORY_MAX_LEN transitions at most.
    if len(history) > _MODE_SWITCH_HISTORY_MAX_LEN:
        history = history[-_MODE_SWITCH_HISTORY_MAX_LEN:]
    merged_meta: Dict[str, Any] = {
        **existing_meta,
        "current_mode": to_mode.value,
        "mode_switch_history": history,
        **(metadata or {}),
    }

    # Determine the new posture based on the mode transition.
    if from_mode == AndroidDeviceMode.local and to_mode == AndroidDeviceMode.cross_device:
        new_posture = _POSTURE_JOIN_RUNTIME
    elif to_mode == AndroidDeviceMode.local:
        new_posture = _POSTURE_CONTROL_ONLY
    else:
        # No posture change for other transitions; just update metadata.
        new_posture = None

    if new_posture is not None:
        updated = update_session_posture(
            device_id,
            new_posture,
            metadata=merged_meta,
            registry=registry,
        )
    else:
        # Only metadata update — use update_session_posture with the existing posture.
        updated = update_session_posture(
            device_id,
            entry.posture,
            metadata=merged_meta,
            registry=registry,
        )

    logger.info(
        "apply_mode_switch_to_registry: device_id=%r %s→%s posture=%s",
        device_id, from_mode.value, to_mode.value, new_posture or entry.posture,
    )
    return updated


# ---------------------------------------------------------------------------
# build_cross_device_readiness_panel_dict
# ---------------------------------------------------------------------------


def build_cross_device_readiness_panel_dict(
    device_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Aggregate per-device mode readiness into a panel-ready summary dict.

    When *device_ids* is None, all devices with an active session in the
    registry are evaluated.

    Returns a dict suitable for inclusion in the unified panel payload.  Keys:
    ``devices`` (list of per-device dicts), ``cross_device_ready_count``,
    ``dispatch_eligible_count``, ``takeover_eligible_count``,
    ``total_devices``, ``_source``.
    """
    resolved_ids: List[str] = []
    if device_ids is None:
        try:
            from core.attached_runtime_session_registry import list_active_sessions
            resolved_ids = [e.device_id for e in list_active_sessions()]
        except Exception as exc:
            logger.debug("build_cross_device_readiness_panel_dict: registry unavailable: %s", exc)
    else:
        resolved_ids = list(device_ids)

    devices: List[Dict[str, Any]] = []
    cross_device_ready = 0
    dispatch_eligible = 0
    takeover_eligible = 0

    for did in resolved_ids:
        try:
            verdict = evaluate_android_mode_readiness(did)
            devices.append(verdict.to_dict())
            if verdict.is_cross_device_ready:
                cross_device_ready += 1
            if verdict.is_dispatch_eligible:
                dispatch_eligible += 1
            if verdict.is_takeover_eligible:
                takeover_eligible += 1
        except Exception as exc:
            logger.debug(
                "build_cross_device_readiness_panel_dict: error for %r: %s", did, exc
            )

    return {
        "devices": devices,
        "cross_device_ready_count": cross_device_ready,
        "dispatch_eligible_count": dispatch_eligible,
        "takeover_eligible_count": takeover_eligible,
        "total_devices": len(resolved_ids),
        "_source": ANDROID_MODE_GATE_POLICY_AUTHORITY,
    }


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Authority sentinels
    "ANDROID_MODE_GATE_POLICY_AUTHORITY",
    "UNIFIED_GATE_POLICY_SENTINELS",
    "MODE_SWITCH_SESSION_CONSISTENCY_POLICY",
    "CROSS_DEVICE_READINESS_GATE_POLICY",
    "CANONICAL_ANDROID_EXECUTION_GATE_POLICY",
    "ANDROID_MODE_GATE_POLICY_PR_SENTINEL",
    # Enums
    "AndroidDeviceMode",
    # Dataclasses
    "GateEvalResult",
    "AndroidModeState",
    "AndroidModeReadinessVerdict",
    "AndroidCanonicalExecutionGateDecision",
    # Functions
    "evaluate_android_mode_readiness",
    "resolve_android_execution_gate_decision",
    "apply_mode_switch_to_registry",
    "build_mode_state_for_device",
    "build_cross_device_readiness_panel_dict",
]
