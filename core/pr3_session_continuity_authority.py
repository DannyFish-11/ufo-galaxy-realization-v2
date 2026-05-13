"""core/pr3_session_continuity_authority.py
=============================================
PR-3 (V2 side): Unified authority, session, continuity, and
takeover/recovery convergence.

This module is the **center-side convergence layer** for PR-3 of the
5-part full-system convergence plan.  It does NOT replace any existing
authority module; instead it **binds** the existing modules into a single
enforceable runtime rule system by:

1. Exposing a *unified session axis assertion* that classifies every
   reconnect/rebind event into an explicit
   :class:`ContinuityReconnectClass` value:
   ``resume``, ``replay``, ``restart``, ``attachment_only``, or ``duplicate``.

2. Defining and enforcing *true continuity semantics* — every
   classification is produced by an explicit rule, not inferred from
   implicit state.

3. Declaring the *authority boundary* between Android local AI and V2
   center AI: local AI proposals are classified before they may influence
   center decisions.

4. Providing *hard takeover and recovery governance*: explicit runtime
   rules determine whether degraded-evidence takeovers may proceed.

5. Producing *traceable audit snapshots* so every decision is inspectable
   and auditable at any time.

Background
----------
The existing modules provide the necessary infrastructure:

* :mod:`core.canonical_session_axis` — five session families and their
  role boundaries.
* :mod:`core.flow_continuity_coordinator` — unified continuity decision
  entry-point returning :class:`~core.flow_continuity_coordinator.ContinuityDecision`.
* :mod:`core.attached_runtime_session_registry` — authoritative registry for
  runtime attachment sessions.
* :mod:`core.android_originated_authority_boundary` — Android participation
  classification and permission levels.
* :mod:`core.center_authority_boundary` — V2 center authority domain
  closure.
* :mod:`core.takeover_tracking` — canonical takeover accept/reject tracking.
* :mod:`core.ownership_transfer_proof_quality` — proof quality classifier for
  ownership transfer evidence.
* :mod:`core.v2_android_recovery_continuity_hardening` — session reuse
  hardening, recovery closure quality, and duplicate result detection.
* :mod:`core.continuation_rebind_registry` — continuation rebind tracking
  after V2 restart.

What PR-3 adds
--------------
This module adds the *convergence layer* that:

1. Classifies any reconnect/rebind event into ``resume``, ``replay``,
   ``restart``, ``attachment_only``, or ``duplicate`` — the classification
   is explicit, machine-checkable, and auditable.

2. Enforces that duplicate, replayed, and stale results are not conflated.

3. Classifies Android local-AI proposals relative to center authority and
   enforces the boundary in runtime decisions.

4. Governs degraded takeover: a takeover with degraded evidence triggers
   explicit governance rules (revalidate / reject / operator escalate) rather
   than silently continuing.

5. Builds a :class:`PR3ConvergenceAuditSnapshot` that records all four
   dimensions so operator observability and audit surfaces can inspect the
   state of the convergence rules at any time.

Android integration points
--------------------------
This module is the **V2 side** of a dual-repository convergence item.  The
corresponding Android-side integration requires:

- ``runtime/CanonicalSessionAxis.kt`` — Android session axis must align
  with V2's five session families and use the same canonical field names.
- ``runtime/AndroidContinuityIntegration.kt`` — Android must report
  continuity events using the reconnect classes defined here.
- ``network/OfflineTaskQueue.kt`` — offline replay sequences must carry
  sequence position and epoch so V2 can classify each item as
  ``convergence_eligible``, ``gap_exposed``, ``stale_dropped``, or
  ``duplicate_suppressed``.
- ``agent/DelegatedTakeoverExecutor.kt`` — takeover responses must include
  proof quality metadata so V2 can apply the takeover governance rules
  defined here.
- ``agent/TakeoverEligibilityAssessor.kt`` — Android must pre-check
  takeover eligibility using the same proof quality thresholds.
- ``inference/LocalPlannerService.kt`` — local planner proposals must
  carry an explicit ``authority_level`` field that V2 uses to classify
  them via :func:`classify_local_ai_proposal`.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Binding, not replacing** — composes existing authority modules rather
  than duplicating their logic.
- **Explicit over implicit** — every classification is produced by a named
  rule and recorded in an audit snapshot.
- **Fail-closed** — when classification cannot be determined, the
  conservative default is applied and recorded.
- **Android-explicit** — Android integration requirements are named and
  linked from every public function.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`PR3_CONVERGENCE_AUTHORITY`
:data:`PR3_CONVERGENCE_CONTRACT_VERSION`
:data:`RECONNECT_CLASSIFICATION_IS_EXPLICIT_POLICY`
:data:`DUPLICATE_STALE_REPLAY_MUST_NOT_BE_CONFLATED_POLICY`
:data:`LOCAL_AI_AUTHORITY_BOUNDARY_IS_ENFORCED_POLICY`
:data:`DEGRADED_TAKEOVER_REQUIRES_EXPLICIT_GOVERNANCE_POLICY`
:data:`CENTER_IS_SESSION_COMPLETION_AUTHORITY_POLICY`

Enums
~~~~~
:class:`ContinuityReconnectClass`
:class:`TakeoverGovernanceDecision`
:class:`LocalAIProposalClass`

Data classes
~~~~~~~~~~~~
:class:`ReconnectClassificationResult`
:class:`TakeoverGovernanceResult`
:class:`LocalAIProposalClassificationResult`
:class:`PR3ConvergenceAuditSnapshot`

Functions
~~~~~~~~~
:func:`classify_reconnect_event`
:func:`classify_local_ai_proposal`
:func:`govern_takeover_decision`
:func:`build_pr3_convergence_audit_snapshot`
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.PR3.SessionContinuityAuthority")

# ---------------------------------------------------------------------------
# PR-3 contract sentinels
# ---------------------------------------------------------------------------

PR3_CONVERGENCE_AUTHORITY: str = (
    "PR3_CONVERGENCE_AUTHORITY::V2::present "
    "core.pr3_session_continuity_authority is the V2-side convergence layer "
    "for PR-3 of the 5-part full-system convergence plan. It unifies authority, "
    "session identity, continuity semantics, takeover/recovery governance, "
    "and audit surfaces into one enforceable runtime rule system."
)

PR3_CONVERGENCE_CONTRACT_VERSION: str = "3.0.0"

PR3_CONVERGENCE_PR3_SENTINEL: str = (
    "PR3_SENTINEL::pr3_session_continuity_authority::3.0.0 "
    "This sentinel confirms that the PR-3 convergence layer is loaded and "
    "that the five session families, reconnect classification, local-AI "
    "authority boundary, takeover governance, and audit snapshot are all "
    "present in the V2 runtime."
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

RECONNECT_CLASSIFICATION_IS_EXPLICIT_POLICY: str = (
    "POLICY::RECONNECT_CLASSIFICATION_IS_EXPLICIT_V1: "
    "Every reconnect or rebind event MUST produce an explicit "
    "ContinuityReconnectClass value. Implicit/inferred classification is not "
    "permitted. The classification MUST be recorded in an audit snapshot."
)

DUPLICATE_STALE_REPLAY_MUST_NOT_BE_CONFLATED_POLICY: str = (
    "POLICY::DUPLICATE_STALE_REPLAY_MUST_NOT_BE_CONFLATED_V1: "
    "duplicate, stale_result, and replay MUST be classified as distinct "
    "categories. Center-side handling MUST NOT treat a stale result as a "
    "duplicate, or a replayed result as a fresh delivery."
)

LOCAL_AI_AUTHORITY_BOUNDARY_IS_ENFORCED_POLICY: str = (
    "POLICY::LOCAL_AI_AUTHORITY_BOUNDARY_IS_ENFORCED_V1: "
    "Android local-AI proposals are classified into one of three authority "
    "levels before they may influence center decisions: suggestion_only, "
    "fallback_eligible, or sub_agent_decision. Only sub_agent_decision "
    "proposals may influence center planning; all others are advisory."
)

DEGRADED_TAKEOVER_REQUIRES_EXPLICIT_GOVERNANCE_POLICY: str = (
    "POLICY::DEGRADED_TAKEOVER_REQUIRES_EXPLICIT_GOVERNANCE_V1: "
    "A takeover with degraded ownership-transfer proof quality (any class "
    "other than confirmed_strong) MUST NOT silently proceed. It MUST "
    "trigger one of: revalidate_ownership, reject_takeover, "
    "operator_escalate, or forced_suspend."
)

CENTER_IS_SESSION_COMPLETION_AUTHORITY_POLICY: str = (
    "POLICY::CENTER_IS_SESSION_COMPLETION_AUTHORITY_V1: "
    "V2 center is the sole authority for session identity, completion "
    "truth, and continuity legality decisions. Android signals are "
    "participant-level inputs; they do not override center authority."
)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ContinuityReconnectClass(str, Enum):
    """Explicit classification for every reconnect / rebind event.

    This enum ensures that reconnect, rebind, and recovery events are
    classified into unambiguous categories rather than inferred from
    implicit state.
    """

    resume = "resume"
    """Prior session is alive; attachment is restored without restarting tasks."""

    replay = "replay"
    """Tasks are replayed from an offline queue; not a fresh dispatch."""

    restart = "restart"
    """Session continuity is broken; tasks must restart from scratch."""

    attachment_only = "attachment_only"
    """Transport reconnect only; no task continuity is implied."""

    duplicate = "duplicate"
    """The event is a duplicate of one already processed; suppress it."""


class TakeoverGovernanceDecision(str, Enum):
    """Explicit runtime governance decision for a takeover with given proof quality."""

    proceed = "proceed"
    """Proof is confirmed_strong; takeover may proceed."""

    revalidate_ownership = "revalidate_ownership"
    """Proof is degraded; request owner revalidation before proceeding."""

    reject_takeover = "reject_takeover"
    """Proof is insufficient; reject the takeover."""

    operator_escalate = "operator_escalate"
    """Conflicting or unresolved proof; escalate to operator for decision."""

    forced_suspend = "forced_suspend"
    """Stale evidence with no viable revalidation path; suspend execution."""


class LocalAIProposalClass(str, Enum):
    """Authority classification for an Android local-AI-originated proposal."""

    suggestion_only = "suggestion_only"
    """Advisory only; center may ignore without explanation."""

    fallback_eligible = "fallback_eligible"
    """Eligible for use as a fallback when center orchestration is unavailable."""

    sub_agent_decision = "sub_agent_decision"
    """Authorized sub-agent scoped decision within an explicitly granted scope."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconnectClassificationResult:
    """Result of classifying a reconnect/rebind event."""

    reconnect_class: ContinuityReconnectClass
    """The explicit classification for this reconnect event."""

    device_id: Optional[str]
    """Device identifier, if available."""

    runtime_session_id: Optional[str]
    """Runtime session ID at the time of classification."""

    runtime_attachment_session_id: Optional[str]
    """Attachment session ID, if available."""

    policy: str
    """Policy sentinel that drove this decision."""

    reason: str
    """Human-readable explanation of the classification decision."""

    evidence: Dict[str, Any] = field(default_factory=dict)
    """Supporting evidence used to reach this decision."""

    classified_at: float = field(default_factory=time.time)
    """Wall-clock timestamp of classification."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reconnect_class": self.reconnect_class.value,
            "device_id": self.device_id,
            "runtime_session_id": self.runtime_session_id,
            "runtime_attachment_session_id": self.runtime_attachment_session_id,
            "policy": self.policy,
            "reason": self.reason,
            "evidence": self.evidence,
            "classified_at": self.classified_at,
        }


@dataclass(frozen=True)
class TakeoverGovernanceResult:
    """Result of applying takeover governance rules to a proof quality assessment."""

    governance_decision: TakeoverGovernanceDecision
    """The explicit governance decision for this takeover."""

    proof_class: str
    """The proof quality class that drove this decision."""

    takeover_id: Optional[str]
    """Takeover identifier, if available."""

    device_id: Optional[str]
    """Device identifier, if available."""

    policy: str
    """Policy sentinel that drove this decision."""

    reason: str
    """Human-readable explanation."""

    is_execution_blocked: bool
    """True when this decision prevents execution from proceeding."""

    governed_at: float = field(default_factory=time.time)
    """Wall-clock timestamp of governance decision."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "governance_decision": self.governance_decision.value,
            "proof_class": self.proof_class,
            "takeover_id": self.takeover_id,
            "device_id": self.device_id,
            "policy": self.policy,
            "reason": self.reason,
            "is_execution_blocked": self.is_execution_blocked,
            "governed_at": self.governed_at,
        }


@dataclass(frozen=True)
class LocalAIProposalClassificationResult:
    """Result of classifying an Android local-AI proposal against center authority."""

    proposal_class: LocalAIProposalClass
    """The authority class for this proposal."""

    may_influence_center_planning: bool
    """True only for sub_agent_decision proposals with explicit scope grant."""

    requires_center_review: bool
    """True when the proposal must be reviewed by center before any action."""

    policy: str
    """Policy sentinel."""

    reason: str
    """Human-readable explanation."""

    proposal_source: Optional[str] = None
    """Source module / component on Android that produced this proposal."""

    scope: Optional[str] = None
    """Explicitly granted scope for sub_agent_decision proposals."""

    classified_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_class": self.proposal_class.value,
            "may_influence_center_planning": self.may_influence_center_planning,
            "requires_center_review": self.requires_center_review,
            "policy": self.policy,
            "reason": self.reason,
            "proposal_source": self.proposal_source,
            "scope": self.scope,
            "classified_at": self.classified_at,
        }


@dataclass
class PR3ConvergenceAuditSnapshot:
    """Full PR-3 convergence state snapshot for operator observability and audit."""

    snapshot_id: str = field(
        default_factory=lambda: f"pr3snap_{uuid.uuid4().hex[:12]}"
    )
    created_at: float = field(default_factory=time.time)

    # Session axis
    session_axis_loaded: bool = False
    session_family_count: int = 0

    # Center authority boundary
    center_authority_intact: bool = False
    center_authority_diagnosis: List[str] = field(default_factory=list)

    # Android authority boundary
    android_boundary_loaded: bool = False

    # Continuity coordinator
    continuity_coordinator_loaded: bool = False

    # Session registry
    session_registry_loaded: bool = False

    # Takeover tracking
    takeover_tracking_loaded: bool = False

    # Ownership transfer proof quality
    ownership_proof_quality_loaded: bool = False

    # Recovery hardening
    recovery_hardening_loaded: bool = False

    # Continuation rebind registry
    rebind_registry_loaded: bool = False

    # Policy sentinels affirmed
    policies_affirmed: List[str] = field(default_factory=list)

    # Android integration points status
    android_integration_points: Dict[str, str] = field(default_factory=dict)

    # Errors encountered during snapshot build
    errors: List[str] = field(default_factory=list)

    def is_fully_converged(self) -> bool:
        """Return True if all core convergence components are loaded and healthy."""
        return (
            self.session_axis_loaded
            and self.center_authority_intact
            and self.android_boundary_loaded
            and self.continuity_coordinator_loaded
            and self.session_registry_loaded
            and self.takeover_tracking_loaded
            and self.ownership_proof_quality_loaded
            and self.recovery_hardening_loaded
            and self.rebind_registry_loaded
        )

    def convergence_gaps(self) -> List[str]:
        """Return a list of convergence gap descriptions."""
        gaps = []
        if not self.session_axis_loaded:
            gaps.append("session_axis_not_loaded")
        if not self.center_authority_intact:
            gaps.append("center_authority_not_intact")
            gaps.extend(self.center_authority_diagnosis)
        if not self.android_boundary_loaded:
            gaps.append("android_boundary_not_loaded")
        if not self.continuity_coordinator_loaded:
            gaps.append("continuity_coordinator_not_loaded")
        if not self.session_registry_loaded:
            gaps.append("session_registry_not_loaded")
        if not self.takeover_tracking_loaded:
            gaps.append("takeover_tracking_not_loaded")
        if not self.ownership_proof_quality_loaded:
            gaps.append("ownership_proof_quality_not_loaded")
        if not self.recovery_hardening_loaded:
            gaps.append("recovery_hardening_not_loaded")
        if not self.rebind_registry_loaded:
            gaps.append("rebind_registry_not_loaded")
        return gaps

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "is_fully_converged": self.is_fully_converged(),
            "convergence_gaps": self.convergence_gaps(),
            "session_axis_loaded": self.session_axis_loaded,
            "session_family_count": self.session_family_count,
            "center_authority_intact": self.center_authority_intact,
            "center_authority_diagnosis": self.center_authority_diagnosis,
            "android_boundary_loaded": self.android_boundary_loaded,
            "continuity_coordinator_loaded": self.continuity_coordinator_loaded,
            "session_registry_loaded": self.session_registry_loaded,
            "takeover_tracking_loaded": self.takeover_tracking_loaded,
            "ownership_proof_quality_loaded": self.ownership_proof_quality_loaded,
            "recovery_hardening_loaded": self.recovery_hardening_loaded,
            "rebind_registry_loaded": self.rebind_registry_loaded,
            "policies_affirmed": self.policies_affirmed,
            "android_integration_points": self.android_integration_points,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Reconnect / rebind classification
# ---------------------------------------------------------------------------

def classify_reconnect_event(
    *,
    device_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
    runtime_attachment_session_id: Optional[str] = None,
    has_active_registry_entry: Optional[bool] = None,
    is_duplicate: Optional[bool] = None,
    is_replay: Optional[bool] = None,
    session_is_terminal: Optional[bool] = None,
    durable_session_id: Optional[str] = None,
) -> ReconnectClassificationResult:
    """Classify a reconnect/rebind event into an explicit
    :class:`ContinuityReconnectClass`.

    This is the canonical V2-side classification function for PR-3.  Every
    reconnect/rebind event that arrives at V2 MUST be passed through this
    function so the continuity semantics are explicit and auditable.

    Parameters
    ----------
    device_id:
        The Android device identifier.
    runtime_session_id:
        The stable runtime session ID (authority anchor).
    runtime_attachment_session_id:
        The attachment-layer session ID (transport-level).
    has_active_registry_entry:
        Whether the :mod:`core.attached_runtime_session_registry` has an
        active entry for this device/session.  ``None`` means unknown.
    is_duplicate:
        Whether this event has already been processed for this session.
        ``None`` means unknown.
    is_replay:
        Whether this event comes from an offline replay queue rather than
        real-time Android.  ``None`` means unknown.
    session_is_terminal:
        Whether the session in the registry is in a terminal state
        (``replaced`` / ``invalidated``).  ``None`` means unknown.
    durable_session_id:
        Durable session identifier, if available.

    Returns
    -------
    ReconnectClassificationResult
        Explicit classification with reason and evidence.
    """
    evidence: Dict[str, Any] = {
        "device_id": device_id,
        "runtime_session_id": runtime_session_id,
        "runtime_attachment_session_id": runtime_attachment_session_id,
        "has_active_registry_entry": has_active_registry_entry,
        "is_duplicate": is_duplicate,
        "is_replay": is_replay,
        "session_is_terminal": session_is_terminal,
        "durable_session_id": durable_session_id,
    }

    # Rule 1: Duplicate signal — suppress before any state change.
    if is_duplicate is True:
        return ReconnectClassificationResult(
            reconnect_class=ContinuityReconnectClass.duplicate,
            device_id=device_id,
            runtime_session_id=runtime_session_id,
            runtime_attachment_session_id=runtime_attachment_session_id,
            policy=DUPLICATE_STALE_REPLAY_MUST_NOT_BE_CONFLATED_POLICY,
            reason=(
                "Event is a known duplicate: already processed for this session. "
                "Classified as duplicate per DUPLICATE_STALE_REPLAY_MUST_NOT_BE_CONFLATED_POLICY. "
                "Suppress without applying state changes."
            ),
            evidence=evidence,
        )

    # Rule 2: Replay from offline queue — replay semantics, not fresh dispatch.
    if is_replay is True:
        return ReconnectClassificationResult(
            reconnect_class=ContinuityReconnectClass.replay,
            device_id=device_id,
            runtime_session_id=runtime_session_id,
            runtime_attachment_session_id=runtime_attachment_session_id,
            policy=DUPLICATE_STALE_REPLAY_MUST_NOT_BE_CONFLATED_POLICY,
            reason=(
                "Event originates from an offline replay queue, not real-time Android. "
                "Classified as replay per DUPLICATE_STALE_REPLAY_MUST_NOT_BE_CONFLATED_POLICY. "
                "Must not be treated as a fresh delivery."
            ),
            evidence=evidence,
        )

    # Rule 3: Terminal session — cannot resume; must restart.
    if session_is_terminal is True:
        return ReconnectClassificationResult(
            reconnect_class=ContinuityReconnectClass.restart,
            device_id=device_id,
            runtime_session_id=runtime_session_id,
            runtime_attachment_session_id=runtime_attachment_session_id,
            policy=RECONNECT_CLASSIFICATION_IS_EXPLICIT_POLICY,
            reason=(
                "Session is in terminal state (replaced or invalidated). "
                "Continuity cannot be resumed; the event is classified as restart. "
                "Tasks must be restarted from scratch."
            ),
            evidence=evidence,
        )

    # Rule 4: No runtime session ID — transport reconnect only.
    if not runtime_session_id and not runtime_attachment_session_id:
        return ReconnectClassificationResult(
            reconnect_class=ContinuityReconnectClass.attachment_only,
            device_id=device_id,
            runtime_session_id=runtime_session_id,
            runtime_attachment_session_id=runtime_attachment_session_id,
            policy=RECONNECT_CLASSIFICATION_IS_EXPLICIT_POLICY,
            reason=(
                "No runtime_session_id or runtime_attachment_session_id present. "
                "This is a transport-layer reconnect only; no task continuity is implied."
            ),
            evidence=evidence,
        )

    # Rule 5: Active registry entry — resume.
    if has_active_registry_entry is True:
        return ReconnectClassificationResult(
            reconnect_class=ContinuityReconnectClass.resume,
            device_id=device_id,
            runtime_session_id=runtime_session_id,
            runtime_attachment_session_id=runtime_attachment_session_id,
            policy=RECONNECT_CLASSIFICATION_IS_EXPLICIT_POLICY,
            reason=(
                "Active registry entry found for this device/session. "
                "Prior session is alive; attachment is restored. "
                "Classified as resume: in-flight tasks remain active."
            ),
            evidence=evidence,
        )

    # Rule 6: No active registry entry but session IDs provided — restart.
    if has_active_registry_entry is False:
        return ReconnectClassificationResult(
            reconnect_class=ContinuityReconnectClass.restart,
            device_id=device_id,
            runtime_session_id=runtime_session_id,
            runtime_attachment_session_id=runtime_attachment_session_id,
            policy=RECONNECT_CLASSIFICATION_IS_EXPLICIT_POLICY,
            reason=(
                "No active registry entry found for this device/session, but session "
                "IDs were provided. Session continuity is broken; classified as restart."
            ),
            evidence=evidence,
        )

    # Default: cannot determine — attachment_only (conservative).
    return ReconnectClassificationResult(
        reconnect_class=ContinuityReconnectClass.attachment_only,
        device_id=device_id,
        runtime_session_id=runtime_session_id,
        runtime_attachment_session_id=runtime_attachment_session_id,
        policy=RECONNECT_CLASSIFICATION_IS_EXPLICIT_POLICY,
        reason=(
            "Insufficient evidence to determine continuity class. "
            "Defaulting to attachment_only (conservative). "
            "Callers should provide has_active_registry_entry for a more specific result."
        ),
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Takeover governance
# ---------------------------------------------------------------------------

# Mapping from proof class to governance decision and execution-blocked status
_TAKEOVER_GOVERNANCE_RULES: Dict[str, tuple] = {
    # (TakeoverGovernanceDecision, is_execution_blocked, reason)
    "confirmed_strong": (
        TakeoverGovernanceDecision.proceed,
        False,
        "Ownership transfer proof is confirmed_strong; takeover may proceed.",
    ),
    "degraded_partial": (
        TakeoverGovernanceDecision.revalidate_ownership,
        True,
        (
            "Ownership transfer proof is degraded_partial (structurally incomplete). "
            "Execution is blocked. Revalidation required before proceeding."
        ),
    ),
    "degraded_stale": (
        TakeoverGovernanceDecision.forced_suspend,
        True,
        (
            "Ownership transfer proof is degraded_stale (evidence too old to trust). "
            "Execution is suspended. Stale evidence cannot grant ownership."
        ),
    ),
    "degraded_conflicting": (
        TakeoverGovernanceDecision.operator_escalate,
        True,
        (
            "Ownership transfer proof is degraded_conflicting (accepted + rejected). "
            "Execution is blocked. Operator must resolve the conflict."
        ),
    ),
    "degraded_unresolved": (
        TakeoverGovernanceDecision.revalidate_ownership,
        True,
        (
            "Ownership transfer proof is degraded_unresolved (no convergence yet). "
            "Execution is blocked. Revalidation required to reach convergence."
        ),
    ),
    "incomplete": (
        TakeoverGovernanceDecision.reject_takeover,
        True,
        (
            "Ownership transfer proof is incomplete (missing or unclassifiable). "
            "Takeover is rejected. Center authority is not transferred without proof."
        ),
    ),
}


def govern_takeover_decision(
    proof_class: str,
    *,
    takeover_id: Optional[str] = None,
    device_id: Optional[str] = None,
) -> TakeoverGovernanceResult:
    """Apply takeover governance rules for the given proof quality class.

    This is the canonical PR-3 governance function.  Any takeover that
    is not ``confirmed_strong`` MUST be routed through this function so
    the governance decision is explicit and auditable.

    Parameters
    ----------
    proof_class:
        The :class:`~core.ownership_transfer_proof_quality.OwnershipTransferProofClass`
        value string (e.g. ``"confirmed_strong"``, ``"degraded_partial"``).
    takeover_id:
        Takeover correlation ID from :mod:`core.takeover_tracking`.
    device_id:
        Android device identifier.

    Returns
    -------
    TakeoverGovernanceResult
        Explicit governance decision with reason and execution-blocked flag.
    """
    rule = _TAKEOVER_GOVERNANCE_RULES.get(proof_class)
    if rule is None:
        # Unknown proof class — treat as incomplete (safest).
        rule = _TAKEOVER_GOVERNANCE_RULES["incomplete"]
        reason = (
            f"Unknown proof_class={proof_class!r}; treated as incomplete. "
            + rule[2]
        )
    else:
        reason = rule[2]

    governance_decision, is_execution_blocked, _ = rule

    return TakeoverGovernanceResult(
        governance_decision=governance_decision,
        proof_class=proof_class,
        takeover_id=takeover_id,
        device_id=device_id,
        policy=DEGRADED_TAKEOVER_REQUIRES_EXPLICIT_GOVERNANCE_POLICY,
        reason=reason,
        is_execution_blocked=is_execution_blocked,
    )


# ---------------------------------------------------------------------------
# Local AI proposal classification
# ---------------------------------------------------------------------------

# Known LocalPlannerService authority levels and their classification
_LOCAL_AI_AUTHORITY_LEVELS: Dict[str, LocalAIProposalClass] = {
    "suggestion": LocalAIProposalClass.suggestion_only,
    "suggestion_only": LocalAIProposalClass.suggestion_only,
    "fallback": LocalAIProposalClass.fallback_eligible,
    "fallback_eligible": LocalAIProposalClass.fallback_eligible,
    "sub_agent": LocalAIProposalClass.sub_agent_decision,
    "sub_agent_decision": LocalAIProposalClass.sub_agent_decision,
}


def classify_local_ai_proposal(
    authority_level: str,
    *,
    proposal_source: Optional[str] = None,
    scope: Optional[str] = None,
) -> LocalAIProposalClassificationResult:
    """Classify an Android local-AI proposal against center authority.

    Android ``LocalPlannerService`` and related local-AI components must
    carry an ``authority_level`` field in their proposals.  This function
    classifies that level against the center authority boundary.

    Parameters
    ----------
    authority_level:
        The authority level declared by the Android local-AI component.
        Must be one of ``"suggestion"``, ``"fallback"``, or ``"sub_agent"``.
    proposal_source:
        Source component name on Android (e.g. ``"LocalPlannerService"``).
    scope:
        Explicitly granted scope for ``sub_agent_decision`` proposals.

    Returns
    -------
    LocalAIProposalClassificationResult
        Authority class with may_influence_center_planning and
        requires_center_review flags.
    """
    normalized = (authority_level or "").lower().strip()
    proposal_class = _LOCAL_AI_AUTHORITY_LEVELS.get(
        normalized, LocalAIProposalClass.suggestion_only
    )

    if proposal_class == LocalAIProposalClass.suggestion_only:
        may_influence = False
        requires_review = False
        reason = (
            f"Local AI proposal classified as suggestion_only "
            f"(authority_level={authority_level!r}). "
            "Center may ignore without explanation."
        )
        if normalized not in _LOCAL_AI_AUTHORITY_LEVELS:
            reason = (
                f"Unknown authority_level={authority_level!r}; "
                "defaulting to suggestion_only per LOCAL_AI_AUTHORITY_BOUNDARY_IS_ENFORCED_POLICY. "
                "Center may ignore without explanation."
            )

    elif proposal_class == LocalAIProposalClass.fallback_eligible:
        may_influence = False
        requires_review = True
        reason = (
            f"Local AI proposal classified as fallback_eligible "
            f"(authority_level={authority_level!r}). "
            "Eligible for use only when center orchestration is unavailable. "
            "Center must review before applying."
        )

    else:  # sub_agent_decision
        if scope:
            may_influence = True
            requires_review = True
            reason = (
                f"Local AI proposal classified as sub_agent_decision "
                f"(authority_level={authority_level!r}, scope={scope!r}). "
                "Authorized within explicitly granted scope. "
                "Center must validate scope before applying."
            )
        else:
            # sub_agent_decision without scope — treat as fallback_eligible.
            proposal_class = LocalAIProposalClass.fallback_eligible
            may_influence = False
            requires_review = True
            reason = (
                f"Local AI proposal declared sub_agent_decision "
                f"(authority_level={authority_level!r}) but no scope was provided. "
                "Downgraded to fallback_eligible. Scope is required for "
                "sub_agent_decision to influence center planning."
            )

    return LocalAIProposalClassificationResult(
        proposal_class=proposal_class,
        may_influence_center_planning=may_influence,
        requires_center_review=requires_review,
        policy=LOCAL_AI_AUTHORITY_BOUNDARY_IS_ENFORCED_POLICY,
        reason=reason,
        proposal_source=proposal_source,
        scope=scope,
    )


# ---------------------------------------------------------------------------
# Convergence audit snapshot builder
# ---------------------------------------------------------------------------

def build_pr3_convergence_audit_snapshot() -> PR3ConvergenceAuditSnapshot:
    """Build a point-in-time PR-3 convergence audit snapshot.

    Probes all core convergence modules and records their status in a single
    :class:`PR3ConvergenceAuditSnapshot` for operator observability and audit.

    Returns
    -------
    PR3ConvergenceAuditSnapshot
        Complete snapshot of the PR-3 convergence state.
    """
    snap = PR3ConvergenceAuditSnapshot()

    errors: List[str] = []
    policies_affirmed: List[str] = []
    android_points: Dict[str, str] = {}

    # ── Session axis ───────────────────────────────────────────────────────
    try:
        from core.canonical_session_axis import (
            CANONICAL_SESSION_AXIS_AUTHORITY,
            get_session_family_catalogue,
        )
        families = get_session_family_catalogue()
        snap.session_axis_loaded = True
        snap.session_family_count = len(families)
        policies_affirmed.append(CANONICAL_SESSION_AXIS_AUTHORITY[:80])
    except Exception as exc:
        errors.append(f"canonical_session_axis unavailable: {exc}")

    # ── Center authority boundary ──────────────────────────────────────────
    try:
        from core.center_authority_boundary import (
            CENTER_AUTHORITY_BOUNDARY_AUTHORITY,
            assert_center_authority_intact,
            CenterAuthorityViolation,
        )
        try:
            assert_center_authority_intact()
            snap.center_authority_intact = True
            policies_affirmed.append(CENTER_AUTHORITY_BOUNDARY_AUTHORITY[:80])
        except CenterAuthorityViolation as viol:
            snap.center_authority_intact = False
            snap.center_authority_diagnosis.append(str(viol)[:200])
    except Exception as exc:
        errors.append(f"center_authority_boundary unavailable: {exc}")

    # ── Android authority boundary ─────────────────────────────────────────
    try:
        from core.android_originated_authority_boundary import (
            ANDROID_CANNOT_OVERRIDE_CENTER_AUTHORITY_POLICY,
        )
        snap.android_boundary_loaded = True
        policies_affirmed.append(ANDROID_CANNOT_OVERRIDE_CENTER_AUTHORITY_POLICY[:80])
    except Exception as exc:
        errors.append(f"android_originated_authority_boundary unavailable: {exc}")

    # ── Flow continuity coordinator ────────────────────────────────────────
    try:
        from core.flow_continuity_coordinator import (
            FLOW_CONTINUITY_COORDINATOR_IS_AUTHORITY,
            get_flow_continuity_coordinator,
        )
        _coord = get_flow_continuity_coordinator()
        snap.continuity_coordinator_loaded = (_coord is not None)
        if snap.continuity_coordinator_loaded:
            policies_affirmed.append(FLOW_CONTINUITY_COORDINATOR_IS_AUTHORITY[:80])
    except Exception as exc:
        errors.append(f"flow_continuity_coordinator unavailable: {exc}")

    # ── Session registry ───────────────────────────────────────────────────
    try:
        from core.attached_runtime_session_registry import (
            ATTACHED_SESSION_REGISTRY_IS_AUTHORITY,
            get_session_registry,
        )
        _registry = get_session_registry()
        snap.session_registry_loaded = (_registry is not None)
        if snap.session_registry_loaded:
            policies_affirmed.append(ATTACHED_SESSION_REGISTRY_IS_AUTHORITY[:80])
    except Exception as exc:
        errors.append(f"attached_runtime_session_registry unavailable: {exc}")

    # ── Takeover tracking ──────────────────────────────────────────────────
    try:
        from core.takeover_tracking import (
            TAKEOVER_TRACKING_AUTHORITY,
            get_takeover_tracking_runtime,
        )
        _tracking = get_takeover_tracking_runtime()
        snap.takeover_tracking_loaded = (_tracking is not None)
        if snap.takeover_tracking_loaded:
            policies_affirmed.append(TAKEOVER_TRACKING_AUTHORITY[:80])
    except Exception as exc:
        errors.append(f"takeover_tracking unavailable: {exc}")

    # ── Ownership transfer proof quality ──────────────────────────────────
    try:
        from core.ownership_transfer_proof_quality import (
            OWNERSHIP_TRANSFER_PROOF_QUALITY_SENTINEL,
        )
        snap.ownership_proof_quality_loaded = True
        policies_affirmed.append(OWNERSHIP_TRANSFER_PROOF_QUALITY_SENTINEL[:80])
    except Exception as exc:
        errors.append(f"ownership_transfer_proof_quality unavailable: {exc}")

    # ── Recovery continuity hardening ─────────────────────────────────────
    try:
        from core.v2_android_recovery_continuity_hardening import (
            V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_AUTHORITY,
        )
        snap.recovery_hardening_loaded = True
        policies_affirmed.append(
            V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_AUTHORITY[:80]
        )
    except Exception as exc:
        errors.append(f"v2_android_recovery_continuity_hardening unavailable: {exc}")

    # ── Continuation rebind registry ───────────────────────────────────────
    try:
        from core.continuation_rebind_registry import (
            CONTINUATION_REBIND_REGISTRY_IS_AUTHORITY,
            get_continuation_rebind_registry,
        )
        _rebind = get_continuation_rebind_registry()
        snap.rebind_registry_loaded = (_rebind is not None)
        if snap.rebind_registry_loaded:
            policies_affirmed.append(CONTINUATION_REBIND_REGISTRY_IS_AUTHORITY[:80])
    except Exception as exc:
        errors.append(f"continuation_rebind_registry unavailable: {exc}")

    # ── PR-3 own policies ─────────────────────────────────────────────────
    policies_affirmed.append(RECONNECT_CLASSIFICATION_IS_EXPLICIT_POLICY[:80])
    policies_affirmed.append(
        DUPLICATE_STALE_REPLAY_MUST_NOT_BE_CONFLATED_POLICY[:80]
    )
    policies_affirmed.append(LOCAL_AI_AUTHORITY_BOUNDARY_IS_ENFORCED_POLICY[:80])
    policies_affirmed.append(
        DEGRADED_TAKEOVER_REQUIRES_EXPLICIT_GOVERNANCE_POLICY[:80]
    )
    policies_affirmed.append(CENTER_IS_SESSION_COMPLETION_AUTHORITY_POLICY[:80])

    # ── Android integration points ─────────────────────────────────────────
    android_points["CanonicalSessionAxis.kt"] = (
        "REQUIRED: Android session axis must align with V2 five session families. "
        "canonical_field_names must match V2 session identifier catalogue."
    )
    android_points["AndroidContinuityIntegration.kt"] = (
        "REQUIRED: Android must report continuity events using ContinuityReconnectClass "
        "values: resume, replay, restart, attachment_only, duplicate."
    )
    android_points["OfflineTaskQueue.kt"] = (
        "REQUIRED: Offline replay sequences must carry sequence_position and epoch "
        "for V2 duplicate/stale/gap classification."
    )
    android_points["DelegatedTakeoverExecutor.kt"] = (
        "REQUIRED: Takeover responses must include proof_quality metadata "
        "so V2 governance rules can be applied."
    )
    android_points["TakeoverEligibilityAssessor.kt"] = (
        "REQUIRED: Android must pre-check takeover eligibility using "
        "OwnershipTransferProofClass thresholds."
    )
    android_points["LocalPlannerService.kt"] = (
        "REQUIRED: Local planner proposals must carry authority_level field "
        "(suggestion|fallback|sub_agent) for V2 authority boundary classification."
    )

    snap.errors = errors
    snap.policies_affirmed = list(dict.fromkeys(policies_affirmed))  # deduplicate
    snap.android_integration_points = android_points

    if errors:
        logger.warning(
            "PR3 convergence audit: %d error(s) during snapshot build: %s",
            len(errors),
            errors,
        )

    return snap


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "PR3_CONVERGENCE_AUTHORITY",
    "PR3_CONVERGENCE_CONTRACT_VERSION",
    "PR3_CONVERGENCE_PR3_SENTINEL",
    "RECONNECT_CLASSIFICATION_IS_EXPLICIT_POLICY",
    "DUPLICATE_STALE_REPLAY_MUST_NOT_BE_CONFLATED_POLICY",
    "LOCAL_AI_AUTHORITY_BOUNDARY_IS_ENFORCED_POLICY",
    "DEGRADED_TAKEOVER_REQUIRES_EXPLICIT_GOVERNANCE_POLICY",
    "CENTER_IS_SESSION_COMPLETION_AUTHORITY_POLICY",
    # Enums
    "ContinuityReconnectClass",
    "TakeoverGovernanceDecision",
    "LocalAIProposalClass",
    # Data classes
    "ReconnectClassificationResult",
    "TakeoverGovernanceResult",
    "LocalAIProposalClassificationResult",
    "PR3ConvergenceAuditSnapshot",
    # Functions
    "classify_reconnect_event",
    "govern_takeover_decision",
    "classify_local_ai_proposal",
    "build_pr3_convergence_audit_snapshot",
]
