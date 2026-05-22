"""core/android_continuity_recovery_state_router.py
====================================================
PR-4v2-Recovery (cross-repo continuity recovery-state contract) — V2 side:
Android Continuity Recovery-State Router and Canonical Consumption Path.
==========================================================================

Background
----------
Android carries meaningful continuity recovery semantics through its
``AndroidContinuityRecoveryStateModel``, which emits recovery phases during
reconnect, replay, and recovery workflows.  Prior to this module, V2 received
recovery-bearing evidence from Android without an explicit routing layer that
mapped Android recovery-state categories to canonical V2-side handling behaviors.

This created several concrete risks:
- Android recovery-phase meaning was treated as generic metadata rather than
  explicitly routed continuity evidence.
- Stale recovery artifacts could pass into canonical handling without being
  rejected or downgraded.
- ``reconciliation_required`` states did not reliably trigger the V2-side
  reconciliation path.
- ``recovered_inflight`` advisory evidence could potentially bypass the advisory
  boundary and directly influence canonical closure.
- Lost-inflight states were not differentiated from active-inflight states in
  canonical handling.

Purpose
-------
This module provides the **V2-side Android continuity recovery-state router** that
closes the gap between Android recovery-state semantics and explicit V2 canonical
consumption.  It does NOT introduce new storage and does NOT duplicate any existing
authority.  Instead it:

1. Defines :class:`AndroidRecoveryPhase` — an explicit enum for the Android-emitted
   recovery phase categories.  These map directly to Android's
   ``AndroidContinuityRecoveryStateModel`` phases so the cross-repo contract is
   explicit and machine-verifiable.

2. Defines :class:`V2RecoveryRoute` — the canonical V2-side handling route that each
   Android recovery phase maps to.  Each route corresponds to a distinct canonical
   behavior rather than a vague "recovery" flag.

3. Defines :class:`RecoveryStateRoutingDecision` — a typed, serialisable routing
   decision that records the incoming phase, the assigned V2 route, the policy
   reference that drove the assignment, and a diagnosis describing why.

4. Implements :func:`route_android_recovery_state` — the canonical routing entry-point
   that maps an Android recovery phase (or raw phase string) to an explicit
   :class:`RecoveryStateRoutingDecision`.

5. Implements :func:`extract_recovery_phase_from_payload` — extracts the Android
   recovery phase from a raw payload dict, tolerating absent or malformed values
   by returning :attr:`AndroidRecoveryPhase.unknown`.

6. Implements :func:`route_recovery_state_from_payload` — convenience wrapper that
   extracts the phase from a payload dict and routes it in one call.

7. Defines seven policy sentinels that document the canonical rules for each recovery
   route category, making the cross-repo contract observable and testable.

Design invariants
-----------------
I-RS1  Each Android recovery phase MUST map to exactly one V2 route.  There is no
       catch-all "recovery" route — every phase has an explicit consequence.

I-RS2  ``stale_recovery_artifact`` MUST be rejected or downgraded; it MUST NOT
       produce canonical state mutation.

I-RS3  ``reconciliation_required`` MUST trigger the V2 reconciliation path; it MUST
       NOT be silently accepted as canonical completion.

I-RS4  ``lost_inflight`` MUST trigger reconciliation or closure review; it MUST NOT
       be treated as equivalent to ``recovered_inflight``.

I-RS5  ``recovered_inflight`` is advisory evidence only.  It MUST NOT directly produce
       canonical closure by itself.  V2 remains the closure authority.

I-RS6  ``reconnect_initiated`` MUST NOT be treated as completion; it marks the start
       of recovery, not its end.

I-RS7  ``recovery_in_progress`` is a transient state; it MUST NOT be treated as a
       terminal recovery outcome.

I-RS8  Android recovery-state routing MUST be observable — every routing decision
       MUST produce a structured :class:`RecoveryStateRoutingDecision` that is
       serialisable and can be emitted for audit or telemetry.

Authority sentinel
------------------
``ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_SENTINEL`` — import this constant to
assert that this module is present.

Public API
----------
Sentinels / version::

    ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_SENTINEL
    ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_CONTRACT_VERSION
    STALE_RECOVERY_ARTIFACT_MUST_BE_REJECTED_POLICY
    RECONCILIATION_REQUIRED_MUST_TRIGGER_RECONCILIATION_PATH_POLICY
    LOST_INFLIGHT_REQUIRES_RECONCILIATION_OR_CLOSURE_REVIEW_POLICY
    RECOVERED_INFLIGHT_IS_ADVISORY_ONLY_POLICY
    RECONNECT_INITIATED_IS_NOT_COMPLETION_POLICY
    RECOVERY_IN_PROGRESS_IS_TRANSIENT_POLICY
    UNKNOWN_RECOVERY_PHASE_MUST_BE_HANDLED_CONSERVATIVELY_POLICY

Enums::

    AndroidRecoveryPhase
    V2RecoveryRoute

Dataclasses::

    RecoveryStateRoutingDecision

Functions::

    route_android_recovery_state
    extract_recovery_phase_from_payload
    route_recovery_state_from_payload
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.AndroidContinuityRecoveryStateRouter")

# ---------------------------------------------------------------------------
# Authority sentinel & contract version
# ---------------------------------------------------------------------------

ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_SENTINEL: str = (
    "ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_SENTINEL::PR4V2_RECOVERY::present "
    "core.android_continuity_recovery_state_router is the canonical V2-side router "
    "for Android continuity recovery-state semantics.  It maps Android recovery "
    "phases (from AndroidContinuityRecoveryStateModel) to explicit V2 canonical "
    "handling routes so recovery-state meaning is consumed through structured "
    "canonical paths rather than remaining as declared-but-unconsumed metadata. "
    "All recovery-state routing MUST reference this sentinel to confirm the "
    "cross-repo recovery contract is in effect."
)

ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_CONTRACT_VERSION: str = "4v2.recovery.1.0"

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

STALE_RECOVERY_ARTIFACT_MUST_BE_REJECTED_POLICY: str = (
    "POLICY::STALE_RECOVERY_ARTIFACT_REJECTION_PR4V2_RECOVERY: "
    "Android-emitted recovery evidence classified as stale_recovery_artifact MUST be "
    "rejected or downgraded before reaching canonical state.  Stale recovery artifacts "
    "arise when Android replays recovery evidence from a prior session epoch that does "
    "not correspond to the current V2 canonical epoch.  Accepting them would introduce "
    "stale truth into canonical state.  Route: V2RecoveryRoute.reject_stale_artifact."
)

RECONCILIATION_REQUIRED_MUST_TRIGGER_RECONCILIATION_PATH_POLICY: str = (
    "POLICY::RECONCILIATION_REQUIRED_TRIGGER_PR4V2_RECOVERY: "
    "Android-emitted recovery evidence classified as reconciliation_required MUST "
    "trigger the V2-side reconciliation path.  It MUST NOT be silently accepted as "
    "canonical completion.  This phase signals that Android cannot confirm execution "
    "continuity and V2 must adjudicate the canonical outcome.  "
    "Route: V2RecoveryRoute.trigger_reconciliation."
)

LOST_INFLIGHT_REQUIRES_RECONCILIATION_OR_CLOSURE_REVIEW_POLICY: str = (
    "POLICY::LOST_INFLIGHT_RECONCILIATION_PR4V2_RECOVERY: "
    "Android-emitted recovery evidence classified as lost_inflight indicates that "
    "Android cannot account for an in-flight execution after a recovery event.  V2 "
    "MUST route this to reconciliation or closure review rather than treating it as "
    "equivalent to a confirmed inflight or completed execution.  "
    "Route: V2RecoveryRoute.require_closure_review."
)

RECOVERED_INFLIGHT_IS_ADVISORY_ONLY_POLICY: str = (
    "POLICY::RECOVERED_INFLIGHT_ADVISORY_PR4V2_RECOVERY: "
    "Android-emitted recovery evidence classified as recovered_inflight is advisory "
    "evidence only.  It MUST NOT directly produce canonical closure.  Android's report "
    "that an inflight execution was recovered is input to V2 adjudication, not a "
    "unilateral closure claim.  V2 remains the canonical closure authority and must "
    "confirm the recovery before allowing canonical completion.  "
    "Route: V2RecoveryRoute.accept_advisory_evidence."
)

RECONNECT_INITIATED_IS_NOT_COMPLETION_POLICY: str = (
    "POLICY::RECONNECT_INITIATED_NOT_COMPLETION_PR4V2_RECOVERY: "
    "Android-emitted recovery evidence classified as reconnect_initiated signals the "
    "start of the Android reconnect/recovery sequence.  It MUST NOT be treated as "
    "recovery completion.  V2 should mark the session as recovery-pending and await "
    "further recovery evidence or timeout.  "
    "Route: V2RecoveryRoute.mark_recovery_pending."
)

RECOVERY_IN_PROGRESS_IS_TRANSIENT_POLICY: str = (
    "POLICY::RECOVERY_IN_PROGRESS_TRANSIENT_PR4V2_RECOVERY: "
    "Android-emitted recovery evidence classified as recovery_in_progress is a "
    "transient state indicator.  It MUST NOT be treated as a terminal recovery outcome. "
    "V2 should maintain the recovery-pending state and continue to await recovery "
    "completion or timeout.  "
    "Route: V2RecoveryRoute.mark_recovery_pending."
)

UNKNOWN_RECOVERY_PHASE_MUST_BE_HANDLED_CONSERVATIVELY_POLICY: str = (
    "POLICY::UNKNOWN_RECOVERY_PHASE_CONSERVATIVE_PR4V2_RECOVERY: "
    "Android-emitted recovery evidence with an unrecognised or absent recovery phase "
    "MUST be handled conservatively.  V2 MUST NOT assume continuity-resume for unknown "
    "recovery phases.  The evidence is treated as advisory and routed to "
    "V2RecoveryRoute.accept_advisory_evidence with degraded status so callers can "
    "detect and surface the unknown phase.  "
    "Route: V2RecoveryRoute.accept_advisory_evidence (degraded=True)."
)

# ---------------------------------------------------------------------------
# AndroidRecoveryPhase enum
# ---------------------------------------------------------------------------


class AndroidRecoveryPhase(str, Enum):
    """Canonical enum for Android-emitted continuity recovery phases.

    These values correspond directly to Android's ``AndroidContinuityRecoveryStateModel``
    phases, making the cross-repo contract explicit and machine-verifiable.

    Values
    ------
    reconnect_initiated
        Android has initiated a reconnect/recovery sequence after a disconnection or
        process recreation.  This is the entry point to the recovery flow.  It does
        NOT indicate recovery completion.

    recovery_in_progress
        Android is actively performing recovery steps (replaying queued items,
        verifying inflight state, etc.).  This is a transient state; further
        recovery evidence will follow.

    recovered_inflight
        Android reports that an in-flight execution was recovered and is believed
        to have completed or to be in a recoverable state.  This is ADVISORY evidence
        only — it does not constitute canonical closure authority.

    stale_recovery_artifact
        Android reports recovery evidence from a prior session epoch or recovery
        attempt that is no longer current.  This evidence is stale and MUST be
        rejected or downgraded before reaching canonical V2 state.

    reconciliation_required
        Android cannot confirm execution continuity and requests that V2 adjudicate
        the canonical outcome.  This MUST trigger the V2-side reconciliation path.

    lost_inflight
        Android cannot account for an in-flight execution after the recovery event.
        The execution may have been lost during the disconnect period.  V2 MUST
        route this to reconciliation or closure review.

    unknown
        Unrecognised or absent recovery phase.  Handled conservatively as advisory
        evidence with degraded status.
    """

    reconnect_initiated = "reconnect_initiated"
    recovery_in_progress = "recovery_in_progress"
    recovered_inflight = "recovered_inflight"
    stale_recovery_artifact = "stale_recovery_artifact"
    reconciliation_required = "reconciliation_required"
    lost_inflight = "lost_inflight"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: Optional[str]) -> "AndroidRecoveryPhase":
        """Return the matching phase or ``unknown`` for unrecognised values."""
        if not value:
            return cls.unknown
        normalised = str(value).strip().lower()
        for member in cls:
            if member.value == normalised:
                return member
        return cls.unknown


# ---------------------------------------------------------------------------
# V2RecoveryRoute enum
# ---------------------------------------------------------------------------


class V2RecoveryRoute(str, Enum):
    """Canonical V2-side handling route for each Android recovery phase.

    Each route corresponds to a distinct V2 canonical behavior.  There is no
    generic "recovery" catch-all — every phase has an explicit consequence
    (per I-RS1).

    Values
    ------
    reject_stale_artifact
        The recovery evidence is stale and must be rejected without canonical
        state mutation.  Applies to ``stale_recovery_artifact`` phase.

    trigger_reconciliation
        V2 must run the reconciliation path to adjudicate the canonical outcome.
        Applies to ``reconciliation_required`` phase.

    require_closure_review
        V2 must perform closure review — the execution may be lost and the
        canonical record must be reviewed for appropriate closure.
        Applies to ``lost_inflight`` phase.

    accept_advisory_evidence
        The recovery evidence is advisory.  It may inform V2 adjudication but
        MUST NOT directly produce canonical closure.  Applies to
        ``recovered_inflight`` and ``unknown`` phases.

    mark_recovery_pending
        V2 marks the session/execution as recovery-pending and awaits further
        evidence.  Applies to ``reconnect_initiated`` and ``recovery_in_progress``
        phases.
    """

    reject_stale_artifact = "reject_stale_artifact"
    trigger_reconciliation = "trigger_reconciliation"
    require_closure_review = "require_closure_review"
    accept_advisory_evidence = "accept_advisory_evidence"
    mark_recovery_pending = "mark_recovery_pending"


# ---------------------------------------------------------------------------
# Phase → Route mapping
# ---------------------------------------------------------------------------

_PHASE_TO_ROUTE: Dict[AndroidRecoveryPhase, V2RecoveryRoute] = {
    AndroidRecoveryPhase.reconnect_initiated: V2RecoveryRoute.mark_recovery_pending,
    AndroidRecoveryPhase.recovery_in_progress: V2RecoveryRoute.mark_recovery_pending,
    AndroidRecoveryPhase.recovered_inflight: V2RecoveryRoute.accept_advisory_evidence,
    AndroidRecoveryPhase.stale_recovery_artifact: V2RecoveryRoute.reject_stale_artifact,
    AndroidRecoveryPhase.reconciliation_required: V2RecoveryRoute.trigger_reconciliation,
    AndroidRecoveryPhase.lost_inflight: V2RecoveryRoute.require_closure_review,
    AndroidRecoveryPhase.unknown: V2RecoveryRoute.accept_advisory_evidence,
}

_PHASE_TO_POLICY: Dict[AndroidRecoveryPhase, str] = {
    AndroidRecoveryPhase.reconnect_initiated: RECONNECT_INITIATED_IS_NOT_COMPLETION_POLICY,
    AndroidRecoveryPhase.recovery_in_progress: RECOVERY_IN_PROGRESS_IS_TRANSIENT_POLICY,
    AndroidRecoveryPhase.recovered_inflight: RECOVERED_INFLIGHT_IS_ADVISORY_ONLY_POLICY,
    AndroidRecoveryPhase.stale_recovery_artifact: STALE_RECOVERY_ARTIFACT_MUST_BE_REJECTED_POLICY,
    AndroidRecoveryPhase.reconciliation_required: (
        RECONCILIATION_REQUIRED_MUST_TRIGGER_RECONCILIATION_PATH_POLICY
    ),
    AndroidRecoveryPhase.lost_inflight: (
        LOST_INFLIGHT_REQUIRES_RECONCILIATION_OR_CLOSURE_REVIEW_POLICY
    ),
    AndroidRecoveryPhase.unknown: UNKNOWN_RECOVERY_PHASE_MUST_BE_HANDLED_CONSERVATIVELY_POLICY,
}


# ---------------------------------------------------------------------------
# RecoveryStateRoutingDecision dataclass
# ---------------------------------------------------------------------------


@dataclass
class RecoveryStateRoutingDecision:
    """Typed, serialisable routing decision for an Android recovery-state payload.

    Attributes
    ----------
    recovery_phase
        The :class:`AndroidRecoveryPhase` extracted from the Android payload.
    v2_route
        The :class:`V2RecoveryRoute` assigned by the router for this phase.
    policy_reference
        The policy sentinel that drove the routing decision.
    diagnosis
        Human-readable explanation of why this routing decision was made.
    is_canonical_closure_blocked
        True iff this routing decision explicitly blocks canonical closure.
        True for ``reject_stale_artifact``, ``trigger_reconciliation``, and
        ``require_closure_review`` routes.  False for ``accept_advisory_evidence``
        and ``mark_recovery_pending`` (advisory/pending do not directly close).
    is_advisory_only
        True iff the recovery evidence is advisory and MUST NOT by itself produce
        canonical closure.  True for ``accept_advisory_evidence`` route.
    is_degraded
        True iff the evidence was classified as degraded (e.g. unknown phase).
    device_id
        The Android device identifier associated with the recovery evidence.
    session_id
        The session identifier associated with the recovery evidence, if available.
    task_id
        The task identifier associated with the recovery evidence, if available.
    raw_phase_str
        The raw phase string from the Android payload before normalisation.
    decided_at
        Unix timestamp when this decision was made.
    """

    recovery_phase: AndroidRecoveryPhase
    v2_route: V2RecoveryRoute
    policy_reference: str
    diagnosis: str
    is_canonical_closure_blocked: bool
    is_advisory_only: bool
    is_degraded: bool = False
    device_id: str = ""
    session_id: str = ""
    task_id: str = ""
    raw_phase_str: str = ""
    decided_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recovery_phase": self.recovery_phase.value,
            "v2_route": self.v2_route.value,
            "policy_reference": self.policy_reference,
            "diagnosis": self.diagnosis,
            "is_canonical_closure_blocked": self.is_canonical_closure_blocked,
            "is_advisory_only": self.is_advisory_only,
            "is_degraded": self.is_degraded,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "raw_phase_str": self.raw_phase_str,
            "decided_at": self.decided_at,
            "_sentinel": ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_SENTINEL,
            "_contract_version": ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_CONTRACT_VERSION,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ---------------------------------------------------------------------------
# route_android_recovery_state — canonical routing entry-point
# ---------------------------------------------------------------------------

# Routes where canonical closure is explicitly blocked
_CLOSURE_BLOCKED_ROUTES = frozenset({
    V2RecoveryRoute.reject_stale_artifact,
    V2RecoveryRoute.trigger_reconciliation,
    V2RecoveryRoute.require_closure_review,
})

# Routes where evidence is strictly advisory
_ADVISORY_ONLY_ROUTES = frozenset({
    V2RecoveryRoute.accept_advisory_evidence,
})


def route_android_recovery_state(
    phase: AndroidRecoveryPhase,
    *,
    device_id: str = "",
    session_id: str = "",
    task_id: str = "",
    raw_phase_str: str = "",
) -> RecoveryStateRoutingDecision:
    """Map an Android recovery phase to an explicit V2 canonical handling route.

    This is the canonical routing entry-point for Android continuity recovery-state
    semantics.  Every phase maps to exactly one :class:`V2RecoveryRoute` with an
    explicit policy reference and diagnosis (per I-RS1).

    Parameters
    ----------
    phase
        The :class:`AndroidRecoveryPhase` emitted by Android.
    device_id
        The Android device identifier (for diagnosis and audit).
    session_id
        The session identifier (for diagnosis and audit).
    task_id
        The task identifier (for diagnosis and audit).
    raw_phase_str
        The raw phase string from Android before normalisation (for audit).

    Returns
    -------
    RecoveryStateRoutingDecision
        Typed, serialisable routing decision.
    """
    route = _PHASE_TO_ROUTE.get(phase, V2RecoveryRoute.accept_advisory_evidence)
    policy = _PHASE_TO_POLICY.get(
        phase, UNKNOWN_RECOVERY_PHASE_MUST_BE_HANDLED_CONSERVATIVELY_POLICY
    )
    is_blocked = route in _CLOSURE_BLOCKED_ROUTES
    is_advisory = route in _ADVISORY_ONLY_ROUTES
    is_degraded = phase == AndroidRecoveryPhase.unknown

    diagnosis = _build_diagnosis(phase, route, device_id, session_id, task_id)

    decision = RecoveryStateRoutingDecision(
        recovery_phase=phase,
        v2_route=route,
        policy_reference=policy,
        diagnosis=diagnosis,
        is_canonical_closure_blocked=is_blocked,
        is_advisory_only=is_advisory,
        is_degraded=is_degraded,
        device_id=device_id,
        session_id=session_id,
        task_id=task_id,
        raw_phase_str=raw_phase_str,
    )

    logger.debug(
        "recovery_state_routed phase=%r route=%r device_id=%r session_id=%r task_id=%r "
        "closure_blocked=%r advisory=%r degraded=%r",
        phase.value,
        route.value,
        device_id,
        session_id,
        task_id,
        is_blocked,
        is_advisory,
        is_degraded,
    )

    return decision


def _build_diagnosis(
    phase: AndroidRecoveryPhase,
    route: V2RecoveryRoute,
    device_id: str,
    session_id: str,
    task_id: str,
) -> str:
    """Build a human-readable routing diagnosis string."""
    ctx_parts = []
    if device_id:
        ctx_parts.append(f"device_id={device_id!r}")
    if session_id:
        ctx_parts.append(f"session_id={session_id!r}")
    if task_id:
        ctx_parts.append(f"task_id={task_id!r}")
    ctx = " ".join(ctx_parts) if ctx_parts else "(no context)"

    if phase == AndroidRecoveryPhase.reconnect_initiated:
        return (
            f"Android emitted reconnect_initiated; recovery sequence has started. "
            f"V2 marks session as recovery-pending and awaits further evidence. "
            f"This is NOT completion. {ctx}"
        )
    if phase == AndroidRecoveryPhase.recovery_in_progress:
        return (
            f"Android emitted recovery_in_progress; recovery is underway but not "
            f"complete. V2 maintains recovery-pending state. {ctx}"
        )
    if phase == AndroidRecoveryPhase.recovered_inflight:
        return (
            f"Android emitted recovered_inflight; this is advisory evidence only. "
            f"V2 receives the evidence but MUST NOT directly produce canonical closure "
            f"from it. V2 adjudicates the closure outcome. {ctx}"
        )
    if phase == AndroidRecoveryPhase.stale_recovery_artifact:
        return (
            f"Android emitted stale_recovery_artifact; evidence is stale and MUST be "
            f"rejected. V2 blocks canonical state mutation for this evidence. {ctx}"
        )
    if phase == AndroidRecoveryPhase.reconciliation_required:
        return (
            f"Android emitted reconciliation_required; Android cannot confirm continuity "
            f"and V2 must adjudicate the canonical outcome via reconciliation path. {ctx}"
        )
    if phase == AndroidRecoveryPhase.lost_inflight:
        return (
            f"Android emitted lost_inflight; an in-flight execution cannot be accounted "
            f"for after recovery. V2 must perform closure review. {ctx}"
        )
    # unknown
    return (
        f"Android emitted unknown or unrecognised recovery phase. "
        f"V2 handles conservatively as advisory evidence (degraded). "
        f"Route={route.value}. {ctx}"
    )


# ---------------------------------------------------------------------------
# extract_recovery_phase_from_payload — extract phase from raw payload dict
# ---------------------------------------------------------------------------

_RECOVERY_PHASE_FIELD_ALIASES = (
    "recovery_phase",
    "recovery_state",
    "continuity_recovery_phase",
    "android_recovery_phase",
    "phase",
)


def extract_recovery_phase_from_payload(
    payload: Dict[str, Any],
) -> AndroidRecoveryPhase:
    """Extract the Android recovery phase from a raw payload dict.

    Checks several field name aliases in order.  Returns
    :attr:`AndroidRecoveryPhase.unknown` when no recognisable phase value is
    present.

    Parameters
    ----------
    payload
        Raw payload dict from an Android recovery-state message.

    Returns
    -------
    AndroidRecoveryPhase
    """
    if not isinstance(payload, dict):
        return AndroidRecoveryPhase.unknown

    for alias in _RECOVERY_PHASE_FIELD_ALIASES:
        raw = payload.get(alias)
        if raw and isinstance(raw, str):
            phase = AndroidRecoveryPhase.from_string(raw)
            if phase != AndroidRecoveryPhase.unknown:
                return phase

    # Try nested under "recovery_state" sub-dict
    sub = payload.get("recovery_state")
    if isinstance(sub, dict):
        for alias in _RECOVERY_PHASE_FIELD_ALIASES:
            raw = sub.get(alias)
            if raw and isinstance(raw, str):
                phase = AndroidRecoveryPhase.from_string(raw)
                if phase != AndroidRecoveryPhase.unknown:
                    return phase

    return AndroidRecoveryPhase.unknown


# ---------------------------------------------------------------------------
# route_recovery_state_from_payload — convenience wrapper
# ---------------------------------------------------------------------------


def route_recovery_state_from_payload(
    payload: Dict[str, Any],
    *,
    device_id: str = "",
    session_id: str = "",
    task_id: str = "",
) -> RecoveryStateRoutingDecision:
    """Extract the Android recovery phase from a payload dict and route it.

    Convenience wrapper combining :func:`extract_recovery_phase_from_payload`
    and :func:`route_android_recovery_state` in one call.

    Parameters
    ----------
    payload
        Raw payload dict from an Android recovery-state or participant-truth message.
    device_id
        The Android device identifier (for diagnosis and audit).
    session_id
        The session identifier (for diagnosis and audit).
    task_id
        The task identifier (for diagnosis and audit).

    Returns
    -------
    RecoveryStateRoutingDecision
        Typed, serialisable routing decision.
    """
    raw_phase_str = ""
    if isinstance(payload, dict):
        for alias in _RECOVERY_PHASE_FIELD_ALIASES:
            v = payload.get(alias)
            if v and isinstance(v, str):
                raw_phase_str = v
                break

    phase = extract_recovery_phase_from_payload(payload)
    return route_android_recovery_state(
        phase,
        device_id=device_id,
        session_id=session_id,
        task_id=task_id,
        raw_phase_str=raw_phase_str,
    )
