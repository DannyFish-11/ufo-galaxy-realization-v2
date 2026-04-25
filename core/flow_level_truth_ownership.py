"""core/flow_level_truth_ownership.py
========================================
PR-5V2 (post-533 dual-repo runtime host unification track):
Flow-Level Truth Ownership and Local/Central Truth Alignment.

Background
----------
The Android runtime already reports local execution facts to V2 via execution
signals, truth ingress messages, and result / failure / cancel / task_phase
structures.  V2 already absorbs these through
:mod:`~core.android_participant_truth_ingress`,
:mod:`~core.canonical_session_truth`, and
:func:`~core.canonical_session_truth.filter_result_units_by_posture`.

However, the system has not yet established a **flow-level** truth authority
model that answers:

* Which Android truth is *authoritative upward* (must update V2 canonical)?
* Which truth is *advisory* (noted but does not alter V2 canonical state)?
* Which truth is only *execution evidence* (recorded for audit, not action)?
* Which terminal states must always be decided by V2 canonical truth?
* Where does partial result truth live in the canonical record?
* How should posture changes mid-flow affect already-received evidence?
* When must compat-fallback influence be blocked from the truth path?

Without these answers the system is vulnerable to the classic distributed
consistency drift: Android may have advanced a flow locally, while V2 has
not canonically confirmed the same state — or V2 has already terminal-ised
a flow while Android still holds an older execution truth.

This module closes that gap by providing a **flow-level truth ownership and
runtime alignment skeleton** for the V2 side.

Responsibilities
----------------
1. **Truth semantic classification** — :class:`FlowTruthSemanticKind` names
   the six distinct truth categories:
   ``authoritative``, ``advisory``, ``execution_evidence``,
   ``canonical_terminal_decision``, ``partial_result``,
   ``posture_sensitive``.

2. **Truth decision artifacts** — :class:`FlowTruthDecisionKind` enumerates
   the six canonical dispositions that may be assigned to any incoming Android
   truth:
   ``accept_as_authoritative``, ``accept_as_advisory``,
   ``record_as_execution_evidence``, ``reject_due_to_canonical_terminal``,
   ``quarantine_due_to_posture_conflict``, ``block_due_to_compat_influence``.

3. **Flow truth ownership model** — :class:`FlowTruthOwnerKind` distinguishes
   ``v2_canonical`` (orchestration authority), ``android_execution``
   (device-scope execution authority), and ``joint`` (agreed by both sides).

4. **Runtime alignment context** — :class:`FlowTruthAlignmentContext` captures
   all inputs needed to produce a deterministic alignment decision: incoming
   Android truth kind, the current V2 canonical flow phase, device posture,
   posture-change flag, and compat-influence flag.

5. **Flow truth decision artifact** — :class:`FlowTruthDecisionArtifact`
   is the typed, serialisable output of every alignment decision: the
   :class:`FlowTruthDecisionKind`, the resolved :class:`FlowTruthSemanticKind`,
   the owner of canonical truth for this decision, the policy reference, and
   a full evidence dictionary suitable for operator inspection.

6. **Runtime alignment rules** — :func:`align_android_truth_with_canonical`
   applies the deterministic alignment ruleset, covering:

   * partial / final / cancel / failure / task_phase / signal absorption bounds
   * posture-change handling for existing evidence / partial / final truth
   * Android truth that has advanced ahead of V2 canonical confirmation
   * V2-terminal flow receiving late Android truth arrivals
   * compat-fallback influence blocking on the truth path

7. **Posture change impact evaluation** — :func:`evaluate_posture_change_impact`
   determines, for a list of already-recorded truth items, which ones must be
   quarantined or re-evaluated because device posture changed mid-flow.

8. **Alignment runtime** — :class:`FlowTruthAlignmentRuntime` is an
   in-process ring-buffer singleton that records every
   :class:`FlowTruthDecisionArtifact` so operator surfaces and audit tools can
   inspect the alignment history without re-deriving it.

Integration points
------------------
This module is a **pure consumer** of existing modules — it never mutates
their internal state.  It integrates with:

* :mod:`~core.android_participant_truth_ingress` — uses
  :class:`~core.android_participant_truth_ingress.AndroidParticipantTruthKind`
  as the primary vocabulary for incoming Android truth.
* :mod:`~core.delegated_flow_entity` — uses
  :class:`~core.delegated_flow_entity.DelegatedFlowPhase` to determine
  whether the V2 canonical flow is already in a terminal state.
* :mod:`~core.canonical_session_truth` — uses
  :func:`~core.canonical_session_truth.filter_result_units_by_posture` as the
  authoritative posture-aware filter, and references
  :class:`~core.canonical_session_truth.CanonicalSessionTruthRuntime` as the
  canonical session truth store.
* :mod:`~core.compat_fallback_authority_guard` — uses
  :class:`~core.compat_fallback_authority_guard.CompatInfluenceRole` to
  determine whether an incoming truth arrives through a compat-influence path
  that must be blocked.
* :mod:`~core.flow_continuity_coordinator` — shares vocabulary with
  ``ContinuityDecision`` but does not inherit from it; alignment decisions
  are truth-domain artefacts, not continuity decisions.

Design principles
-----------------
- **Additive only** — does not modify any prior module.
- **Explicit over implicit** — every authority decision is stated as a policy
  sentinel, not an inline comment.
- **Decision-first** — every public function returns a
  :class:`FlowTruthDecisionArtifact` carrying the full decision chain.
- **Fail-safe** — when inputs are insufficient to make a safe decision the
  module returns a ``quarantine_due_to_posture_conflict`` artifact so the
  caller can apply a conservative default.
- **Non-destructive** — if no matching V2 flow context is found the module
  returns an ``accept_as_advisory`` artifact so the truth is not silently
  discarded but is also not applied as authoritative.

PR package
----------
PR-5V2 of the dual-repo truth ownership and alignment closure.
Companion Android-repo PR: ``Add Android local execution truth and
central canonical truth alignment skeleton``.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Any, Deque, Dict, List, Optional, Sequence

logger = logging.getLogger("Galaxy.FlowLevelTruthOwnership")

# ---------------------------------------------------------------------------
# Optional integration imports — all guarded to keep the module self-contained
# ---------------------------------------------------------------------------

try:
    from core.android_participant_truth_ingress import (
        AndroidParticipantTruthKind as _AndroidTruthKind,
    )
    _ANDROID_TRUTH_KIND_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ANDROID_TRUTH_KIND_AVAILABLE = False
    _AndroidTruthKind = None  # type: ignore[assignment]

try:
    from core.delegated_flow_entity import DelegatedFlowPhase as _FlowPhase
    _FLOW_PHASE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _FLOW_PHASE_AVAILABLE = False
    _FlowPhase = None  # type: ignore[assignment]

try:
    from core.compat_fallback_authority_guard import (
        CompatInfluenceRole as _CompatRole,
    )
    _COMPAT_ROLE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _COMPAT_ROLE_AVAILABLE = False
    _CompatRole = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Module authority marker
# ---------------------------------------------------------------------------

FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY: str = (
    "FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY::"
    "core.flow_level_truth_ownership::PR5V2::"
    "flow-level-truth-ownership-and-local-central-truth-alignment-skeleton::"
    "v2-canonical-truth-authority-over-terminal-and-orchestration-decisions"
)

FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL: str = (
    "FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL::"
    "package=PR-5V2::profile=flow-level-truth-ownership-v1::"
    "module=core.flow_level_truth_ownership"
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

V2_CANONICAL_OWNS_TERMINAL_FLOW_DECISION_POLICY: str = (
    "POLICY::V2_CANONICAL_OWNS_TERMINAL_FLOW_DECISION_V1: "
    "Once V2 canonical flow phase reaches a terminal state "
    "(completed / failed / cancelled / suspended), no subsequent Android "
    "truth — regardless of kind — may reopen, modify, or supersede that "
    "terminal decision.  Late-arriving Android truth is recorded as "
    "reject_due_to_canonical_terminal.  V2 terminal state is immutable "
    "from Android's perspective.  "
    "PR-5V2, post-533 dual-repo truth ownership closure."
)

ANDROID_CANCEL_FAILURE_RESULT_ARE_AUTHORITATIVE_UPWARD_POLICY: str = (
    "POLICY::ANDROID_CANCEL_FAILURE_RESULT_AUTHORITATIVE_UPWARD_V1: "
    "Android-originated cancel, failure, and result truth (including final "
    "task_phase=completed/failed/cancelled) are classified as authoritative "
    "truth for the device-scope execution and MUST be applied upward to V2 "
    "canonical state when V2 is not yet in a terminal phase.  These truths "
    "are not advisory — they materially alter the V2 canonical tracking "
    "record per "
    "CANCEL_FAILURE_RESULT_AFFECT_CANONICAL_STATE_POLICY.  "
    "PR-5V2, post-533 dual-repo truth ownership closure."
)

PARTIAL_RESULT_LIVES_IN_EXECUTION_TRACKING_RECORD_POLICY: str = (
    "POLICY::PARTIAL_RESULT_LIVES_IN_EXECUTION_TRACKING_RECORD_V1: "
    "Partial result truth reported by Android is classified as "
    "partial_result semantic and stored on the V2 execution tracking record "
    "without closing it.  A partial result does NOT advance the canonical "
    "flow phase to terminal.  Only a final result / failure / cancel "
    "signal closes the tracking record.  "
    "PR-5V2, post-533 dual-repo truth ownership closure."
)

ADVISORY_TRUTH_IS_NOTED_NOT_APPLIED_POLICY: str = (
    "POLICY::ADVISORY_TRUTH_IS_NOTED_NOT_APPLIED_V1: "
    "Android advisory truth (session_snapshot, readiness_assessment, "
    "runtime_state, status/progress) is classified as advisory and is "
    "noted for audit purposes but does NOT alter V2 canonical orchestration "
    "state (dispatch eligibility, flow phase, or tracking record terminal "
    "transitions).  "
    "PR-5V2, post-533 dual-repo truth ownership closure."
)

EXECUTION_EVIDENCE_IS_AUDIT_ONLY_POLICY: str = (
    "POLICY::EXECUTION_EVIDENCE_IS_AUDIT_ONLY_V1: "
    "Android execution evidence (signals that confirm local execution "
    "activity but do not constitute a final result or explicit lifecycle "
    "transition) is recorded as execution_evidence and forwarded to "
    "ReplayFoundation for the audit trail.  It is never applied as a "
    "canonical state change.  "
    "PR-5V2, post-533 dual-repo truth ownership closure."
)

POSTURE_CHANGE_QUARANTINES_PRIOR_EVIDENCE_POLICY: str = (
    "POLICY::POSTURE_CHANGE_QUARANTINES_PRIOR_EVIDENCE_V1: "
    "When device posture changes mid-flow (e.g. join_runtime → control_only "
    "or vice versa), all Android truth items already classified as "
    "execution_evidence or partial_result are moved to "
    "quarantine_due_to_posture_conflict.  This prevents evidence gathered "
    "under one posture assumption from being silently promoted under a "
    "different assumption.  Authoritative terminal truths (cancel/failure/"
    "result) received before the posture change are NOT quarantined — they "
    "remain canonical.  "
    "PR-5V2, post-533 dual-repo truth ownership closure."
)

COMPAT_INFLUENCE_BLOCKS_AUTHORITATIVE_TRUTH_PATH_POLICY: str = (
    "POLICY::COMPAT_INFLUENCE_BLOCKS_AUTHORITATIVE_TRUTH_PATH_V1: "
    "When an incoming Android truth arrives through a compat-fallback or "
    "legacy path that carries unbound compat influence "
    "(CompatInfluenceRole.unbound_influence), the truth is classified as "
    "block_due_to_compat_influence and is not applied to V2 canonical "
    "state.  Only truth that arrives through the canonical ingress path "
    "(android_participant_truth_ingress / android_execution_signal_reconciler) "
    "may reach authoritative or advisory classification.  "
    "PR-5V2, post-533 dual-repo truth ownership closure."
)

ANDROID_ADVANCED_AHEAD_OF_V2_CONFIRMATION_POLICY: str = (
    "POLICY::ANDROID_ADVANCED_AHEAD_OF_V2_CONFIRMATION_V1: "
    "When Android truth indicates a state advance (e.g. task_phase=completed) "
    "but V2 canonical has not yet confirmed that same advance, the truth is "
    "accepted with a 'pending_v2_confirmation' annotation in the artifact "
    "metadata.  This intermediate state is visible to operators but does NOT "
    "constitute a canonical V2 terminal decision.  V2 must separately confirm "
    "the terminal state for it to be canonical.  "
    "PR-5V2, post-533 dual-repo truth ownership closure."
)

UNKNOWN_TRUTH_KIND_DEFAULTS_TO_ADVISORY_POLICY: str = (
    "POLICY::UNKNOWN_TRUTH_KIND_DEFAULTS_TO_ADVISORY_V1: "
    "When the kind of incoming Android truth cannot be resolved to a known "
    "FlowTruthSemanticKind, the truth is classified as advisory (never "
    "authoritative) and is noted for audit purposes only.  This is the "
    "safe-default to prevent misclassification of unknown truth types as "
    "authoritative state changes.  "
    "PR-5V2, post-533 dual-repo truth ownership closure."
)

# ===========================================================================
# Enumerations
# ===========================================================================


class FlowTruthSemanticKind(str, Enum):
    """Canonical classification of the *semantic meaning* of a truth item.

    Values
    ------
    authoritative
        This truth is the definitive statement for its scope.  It MUST be
        applied to the relevant canonical record.
    advisory
        This truth informs but does not alter canonical state.  It is noted
        and forwarded to the audit trail.
    execution_evidence
        This truth confirms that execution activity occurred (e.g. a heartbeat
        or progress ping) but does not constitute a lifecycle decision.  Audit
        only.
    canonical_terminal_decision
        This truth represents a V2-side decision that a flow has reached a
        terminal state.  It is owned exclusively by V2 canonical and cannot
        be overridden by Android truth.
    partial_result
        This truth carries a partial (intermediate) result for an in-flight
        delegated execution.  It is stored on the tracking record but does not
        close it.
    posture_sensitive
        This truth was collected under a specific device posture assumption.
        It must be re-evaluated if posture changes.
    """

    authoritative = "authoritative"
    advisory = "advisory"
    execution_evidence = "execution_evidence"
    canonical_terminal_decision = "canonical_terminal_decision"
    partial_result = "partial_result"
    posture_sensitive = "posture_sensitive"

    @classmethod
    def from_string(cls, value: Optional[str]) -> "FlowTruthSemanticKind":
        """Return the enum value for *value*, defaulting to ``advisory``."""
        if value is None:
            return cls.advisory
        try:
            return cls(value)
        except ValueError:
            return cls.advisory


class FlowTruthDecisionKind(str, Enum):
    """Canonical decision disposition assigned to every incoming Android truth.

    Values
    ------
    accept_as_authoritative
        The truth is applied to the V2 canonical tracking record / flow phase
        as authoritative.
    accept_as_advisory
        The truth is noted and forwarded to the audit trail; V2 canonical state
        is not altered.
    record_as_execution_evidence
        The truth is recorded to ReplayFoundation as execution evidence;
        it does not affect V2 canonical state.
    reject_due_to_canonical_terminal
        The V2 canonical flow is already terminal; the incoming Android truth
        is rejected non-destructively.
    quarantine_due_to_posture_conflict
        Device posture changed mid-flow; the truth is quarantined pending
        re-evaluation under the new posture.
    block_due_to_compat_influence
        The truth arrived via an unbound compat/legacy path and is blocked
        from the canonical ingress.
    """

    accept_as_authoritative = "accept_as_authoritative"
    accept_as_advisory = "accept_as_advisory"
    record_as_execution_evidence = "record_as_execution_evidence"
    reject_due_to_canonical_terminal = "reject_due_to_canonical_terminal"
    quarantine_due_to_posture_conflict = "quarantine_due_to_posture_conflict"
    block_due_to_compat_influence = "block_due_to_compat_influence"

    @classmethod
    def from_string(cls, value: Optional[str]) -> "FlowTruthDecisionKind":
        """Return the enum value for *value*, defaulting to ``accept_as_advisory``."""
        if value is None:
            return cls.accept_as_advisory
        try:
            return cls(value)
        except ValueError:
            return cls.accept_as_advisory


class FlowTruthOwnerKind(str, Enum):
    """Who holds canonical authority for a particular truth surface.

    Values
    ------
    v2_canonical
        V2 orchestration layer holds canonical truth authority for this
        surface (orchestration decisions, terminal state, dispatch authority).
    android_execution
        Android execution runtime holds canonical truth authority for this
        surface (what is happening on the device during local execution).
    joint
        Both sides agreed on this truth and it is reflected canonically on
        both sides (e.g. a successfully completed flow whose result has been
        confirmed and echoed back).
    """

    v2_canonical = "v2_canonical"
    android_execution = "android_execution"
    joint = "joint"


class PostureChangeHandling(str, Enum):
    """How an existing truth item should be handled after a posture change.

    Values
    ------
    retain
        The truth item is posture-independent and can be retained as-is.
    quarantine
        The truth item was collected under the old posture and must be
        quarantined until re-evaluated.
    promote
        The truth item was waiting for posture confirmation and can now be
        promoted to authoritative.
    discard
        The truth item is incompatible with the new posture and must be
        discarded.
    """

    retain = "retain"
    quarantine = "quarantine"
    promote = "promote"
    discard = "discard"


# ===========================================================================
# Data types
# ===========================================================================


# Internal terminal phase strings — kept in sync with DelegatedFlowPhase
_V2_TERMINAL_PHASES: frozenset = frozenset(
    {"completed", "failed", "cancelled", "suspended"}
)

# Android truth kinds that are authoritative upward when V2 is non-terminal
# PR-4V2-GOV: governance_artifact is a first-class canonical gate input (not advisory).
# Android evaluator governance/readiness/acceptance/strategy artifacts are authoritative
# upward so that DelegatedFlowReadinessGate.truth_ownership dimension can reflect them.
_AUTHORITATIVE_TRUTH_KINDS: frozenset = frozenset(
    {"cancel", "failure", "result", "governance_artifact"}
)

# Android truth kinds that are advisory (do not alter V2 canonical state)
_ADVISORY_TRUTH_KINDS: frozenset = frozenset(
    {
        "session_snapshot",
        "readiness_assessment",
        "runtime_state",
        "status",
        "unknown",
    }
)

# Android truth kinds that are partial results
_PARTIAL_RESULT_KINDS: frozenset = frozenset({"partial_result"})

# task_phase terminal values that should be treated as authoritative
_AUTHORITATIVE_TASK_PHASES: frozenset = frozenset(
    {"completed", "failed", "cancelled"}
)


@dataclass
class FlowTruthAlignmentContext:
    """All inputs needed to make a deterministic flow truth alignment decision.

    Attributes
    ----------
    truth_kind
        The kind of Android-originated truth being ingested (string matching
        :class:`~core.android_participant_truth_ingress.AndroidParticipantTruthKind`
        values, or ``"partial_result"``).
    task_phase_value
        For ``task_phase`` truth: the Android-reported phase string
        (``pending`` / ``running`` / ``completed`` / ``failed`` / ``cancelled``).
        Empty string for non-task-phase kinds.
    v2_canonical_flow_phase
        Current V2 canonical :class:`~core.delegated_flow_entity.DelegatedFlowPhase`
        string for the flow in question.  Empty string if unknown.
    device_posture
        Current device posture string (``join_runtime`` / ``control_only``).
        Empty string if unknown.
    posture_changed
        ``True`` if the device posture changed at any point during this flow.
    compat_influence_active
        ``True`` if this truth arrived through a compat/legacy path that carries
        unbound compat influence.
    delegated_flow_id
        The canonical delegated flow identifier.  May be empty if the flow has
        not yet been registered.
    session_id
        Attached runtime session identifier.
    contract_id
        Delegated execution contract identifier.
    task_id
        Task identifier.
    trace_id
        End-to-end trace identifier.
    truth_payload
        Opaque snapshot of the raw Android truth payload.  Used to populate
        the artifact evidence dictionary.
    """

    truth_kind: str = ""
    task_phase_value: str = ""
    v2_canonical_flow_phase: str = ""
    device_posture: str = ""
    posture_changed: bool = False
    compat_influence_active: bool = False
    delegated_flow_id: str = ""
    session_id: str = ""
    contract_id: str = ""
    task_id: str = ""
    trace_id: str = ""
    truth_payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable dict representation."""
        return {
            "truth_kind": self.truth_kind,
            "task_phase_value": self.task_phase_value,
            "v2_canonical_flow_phase": self.v2_canonical_flow_phase,
            "device_posture": self.device_posture,
            "posture_changed": self.posture_changed,
            "compat_influence_active": self.compat_influence_active,
            "delegated_flow_id": self.delegated_flow_id,
            "session_id": self.session_id,
            "contract_id": self.contract_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
        }


@dataclass
class FlowTruthDecisionArtifact:
    """Typed, serialisable result of a flow truth alignment decision.

    Every call to :func:`align_android_truth_with_canonical` and
    :func:`evaluate_posture_change_impact` produces one of these artifacts.
    They are the stable, inspectable record of every truth authority decision
    made at the flow level.

    Attributes
    ----------
    artifact_id
        Unique identifier for this artifact (``ftda_`` prefix + UUID4 hex).
    decision
        The :class:`FlowTruthDecisionKind` assigned to the incoming truth.
    semantic_kind
        The :class:`FlowTruthSemanticKind` resolved for this truth item.
    truth_owner
        The :class:`FlowTruthOwnerKind` that holds canonical authority for
        the decided truth surface.
    policy_reference
        The policy sentinel name that drove the decision.
    reason
        Human-readable explanation of the decision.
    delegated_flow_id
        Delegated flow identifier for correlation.
    session_id
        Runtime session identifier for correlation.
    contract_id
        Execution contract identifier for correlation.
    task_id
        Task identifier for correlation.
    trace_id
        End-to-end trace identifier for correlation.
    pending_v2_confirmation
        ``True`` when Android truth has advanced ahead of V2 canonical
        confirmation (intermediate state per
        ANDROID_ADVANCED_AHEAD_OF_V2_CONFIRMATION_POLICY).
    posture_at_decision
        Device posture string at the time of this decision.
    timestamp
        Unix epoch seconds when this artifact was produced.
    evidence
        Free-form evidence dictionary forwarded to operator surfaces.
    """

    artifact_id: str = field(
        default_factory=lambda: f"ftda_{uuid.uuid4().hex[:12]}"
    )
    decision: FlowTruthDecisionKind = FlowTruthDecisionKind.accept_as_advisory
    semantic_kind: FlowTruthSemanticKind = FlowTruthSemanticKind.advisory
    truth_owner: FlowTruthOwnerKind = FlowTruthOwnerKind.v2_canonical
    policy_reference: str = ""
    reason: str = ""
    delegated_flow_id: str = ""
    session_id: str = ""
    contract_id: str = ""
    task_id: str = ""
    trace_id: str = ""
    pending_v2_confirmation: bool = False
    posture_at_decision: str = ""
    timestamp: float = field(default_factory=time.time)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable dict representation."""
        return {
            "artifact_id": self.artifact_id,
            "decision": self.decision.value,
            "semantic_kind": self.semantic_kind.value,
            "truth_owner": self.truth_owner.value,
            "policy_reference": self.policy_reference,
            "reason": self.reason,
            "delegated_flow_id": self.delegated_flow_id,
            "session_id": self.session_id,
            "contract_id": self.contract_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "pending_v2_confirmation": self.pending_v2_confirmation,
            "posture_at_decision": self.posture_at_decision,
            "timestamp": self.timestamp,
            "evidence": self.evidence,
        }


@dataclass
class PostureChangeImpactRecord:
    """Describes how a single prior truth item is affected by a posture change.

    Attributes
    ----------
    prior_artifact_id
        The artifact ID of the truth item being re-evaluated.
    truth_kind
        The truth kind of the affected item.
    original_decision
        The :class:`FlowTruthDecisionKind` assigned when the item was first
        received.
    revised_handling
        The :class:`PostureChangeHandling` to apply after the posture change.
    reason
        Human-readable explanation of the re-evaluation result.
    """

    prior_artifact_id: str = ""
    truth_kind: str = ""
    original_decision: FlowTruthDecisionKind = (
        FlowTruthDecisionKind.accept_as_advisory
    )
    revised_handling: PostureChangeHandling = PostureChangeHandling.retain
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prior_artifact_id": self.prior_artifact_id,
            "truth_kind": self.truth_kind,
            "original_decision": self.original_decision.value,
            "revised_handling": self.revised_handling.value,
            "reason": self.reason,
        }


@dataclass
class FlowTruthAlignmentSnapshot:
    """Point-in-time snapshot of the alignment runtime's ring buffer.

    Attributes
    ----------
    snapshot_id
        Unique identifier for this snapshot.
    total_decisions
        Total number of alignment decisions recorded since process start.
    recent_artifacts
        Most recent :class:`FlowTruthDecisionArtifact` records (newest-first,
        up to ``_RING_BUFFER_SIZE``).
    decision_counts
        Mapping of :class:`FlowTruthDecisionKind` value → count in the ring.
    timestamp
        Unix epoch seconds when this snapshot was produced.
    """

    snapshot_id: str = field(
        default_factory=lambda: f"ftas_{uuid.uuid4().hex[:8]}"
    )
    total_decisions: int = 0
    recent_artifacts: List[FlowTruthDecisionArtifact] = field(
        default_factory=list
    )
    decision_counts: Dict[str, int] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "total_decisions": self.total_decisions,
            "recent_artifacts": [a.to_dict() for a in self.recent_artifacts],
            "decision_counts": self.decision_counts,
            "timestamp": self.timestamp,
        }


# ===========================================================================
# Core classification helpers
# ===========================================================================


def _is_v2_terminal(v2_canonical_flow_phase: str) -> bool:
    """Return ``True`` when *v2_canonical_flow_phase* is a terminal phase.

    Accepts both :class:`~core.delegated_flow_entity.DelegatedFlowPhase`
    string values and bare strings.  When the phase is empty the function
    returns ``False`` (non-terminal is the safe assumption).
    """
    if not v2_canonical_flow_phase:
        return False
    return v2_canonical_flow_phase.lower() in _V2_TERMINAL_PHASES


def _resolve_semantic_kind(truth_kind: str, task_phase_value: str) -> FlowTruthSemanticKind:
    """Map an Android truth kind string to a :class:`FlowTruthSemanticKind`.

    Parameters
    ----------
    truth_kind:
        String from :class:`~core.android_participant_truth_ingress.AndroidParticipantTruthKind`.
    task_phase_value:
        For ``task_phase`` kind: the phase value string (may be empty).
    """
    kind = truth_kind.lower() if truth_kind else ""

    if kind in _AUTHORITATIVE_TRUTH_KINDS:
        return FlowTruthSemanticKind.authoritative

    if kind in _ADVISORY_TRUTH_KINDS:
        return FlowTruthSemanticKind.advisory

    if kind in _PARTIAL_RESULT_KINDS:
        return FlowTruthSemanticKind.partial_result

    if kind == "task_phase":
        phase = (task_phase_value or "").lower()
        if phase in _AUTHORITATIVE_TASK_PHASES:
            return FlowTruthSemanticKind.authoritative
        return FlowTruthSemanticKind.execution_evidence

    # execution signals / unrecognised — treat as posture-sensitive evidence
    if kind in ("signal", "execution_signal"):
        return FlowTruthSemanticKind.posture_sensitive

    # safe default
    return FlowTruthSemanticKind.advisory


def _build_artifact(
    ctx: FlowTruthAlignmentContext,
    decision: FlowTruthDecisionKind,
    semantic_kind: FlowTruthSemanticKind,
    truth_owner: FlowTruthOwnerKind,
    policy_reference: str,
    reason: str,
    *,
    pending_v2_confirmation: bool = False,
    extra_evidence: Optional[Dict[str, Any]] = None,
) -> FlowTruthDecisionArtifact:
    """Construct a :class:`FlowTruthDecisionArtifact` from the given inputs."""
    evidence: Dict[str, Any] = {
        "truth_kind": ctx.truth_kind,
        "task_phase_value": ctx.task_phase_value,
        "v2_canonical_flow_phase": ctx.v2_canonical_flow_phase,
        "device_posture": ctx.device_posture,
        "posture_changed": ctx.posture_changed,
        "compat_influence_active": ctx.compat_influence_active,
    }
    if ctx.truth_payload:
        evidence["truth_payload_keys"] = sorted(ctx.truth_payload.keys())
    if extra_evidence:
        evidence.update(extra_evidence)

    return FlowTruthDecisionArtifact(
        decision=decision,
        semantic_kind=semantic_kind,
        truth_owner=truth_owner,
        policy_reference=policy_reference,
        reason=reason,
        delegated_flow_id=ctx.delegated_flow_id,
        session_id=ctx.session_id,
        contract_id=ctx.contract_id,
        task_id=ctx.task_id,
        trace_id=ctx.trace_id,
        pending_v2_confirmation=pending_v2_confirmation,
        posture_at_decision=ctx.device_posture,
        evidence=evidence,
    )


# ===========================================================================
# Public API
# ===========================================================================


def classify_flow_truth_kind(
    truth_kind: str,
    *,
    task_phase_value: str = "",
) -> FlowTruthSemanticKind:
    """Classify an Android truth kind string into a :class:`FlowTruthSemanticKind`.

    This is a stateless helper suitable for call sites that need the semantic
    classification without a full alignment context.

    Parameters
    ----------
    truth_kind:
        String matching a
        :class:`~core.android_participant_truth_ingress.AndroidParticipantTruthKind`
        value, or ``"partial_result"``.
    task_phase_value:
        For ``task_phase`` kind: the Android-reported phase string.
        Ignored for other kinds.

    Returns
    -------
    FlowTruthSemanticKind
        The resolved semantic category.
    """
    return _resolve_semantic_kind(truth_kind, task_phase_value)


def align_android_truth_with_canonical(
    ctx: FlowTruthAlignmentContext,
) -> FlowTruthDecisionArtifact:
    """Produce a :class:`FlowTruthDecisionArtifact` for the given alignment context.

    This is the **primary runtime alignment entry-point**.  It applies the
    full deterministic ruleset described in the module docstring and returns a
    typed artifact that downstream modules (ingress reconciler, operator
    surface, replay audit) can consume without re-deriving the decision.

    Alignment ruleset (evaluated in priority order)
    -----------------------------------------------
    1. **Compat influence block** — if ``ctx.compat_influence_active`` is
       ``True`` the truth is immediately classified as
       ``block_due_to_compat_influence``.

    2. **V2 canonical terminal wins** — if the V2 canonical flow phase is
       terminal, any incoming Android truth is classified as
       ``reject_due_to_canonical_terminal``.

    3. **Posture conflict quarantine** — if ``ctx.posture_changed`` is
       ``True`` *and* the truth kind resolves to ``execution_evidence`` or
       ``partial_result``, the truth is quarantined as
       ``quarantine_due_to_posture_conflict``.

    4. **Authoritative terminal Android truth** — ``cancel``, ``failure``,
       ``result``, or authoritative ``task_phase`` truths are accepted as
       ``accept_as_authoritative`` (applies upward to V2 canonical).
       If V2 has not yet confirmed the same terminal state, the artifact
       carries ``pending_v2_confirmation=True``.

    5. **Partial result** — ``partial_result`` kind is accepted as
       ``accept_as_advisory`` with ``semantic_kind=partial_result``.

    6. **Advisory truth** — advisory truth kinds are classified as
       ``accept_as_advisory``.

    7. **Execution evidence / posture-sensitive** — remaining truth kinds
       are classified as ``record_as_execution_evidence``.

    8. **Unknown fallback** — anything not matched above is classified as
       ``accept_as_advisory`` per UNKNOWN_TRUTH_KIND_DEFAULTS_TO_ADVISORY_POLICY.

    Parameters
    ----------
    ctx:
        Full alignment context for the incoming Android truth.

    Returns
    -------
    FlowTruthDecisionArtifact
        The typed alignment decision artifact.
    """
    semantic_kind = _resolve_semantic_kind(ctx.truth_kind, ctx.task_phase_value)

    # ------------------------------------------------------------------
    # Rule 1: Compat influence block
    # ------------------------------------------------------------------
    if ctx.compat_influence_active:
        artifact = _build_artifact(
            ctx,
            FlowTruthDecisionKind.block_due_to_compat_influence,
            semantic_kind,
            FlowTruthOwnerKind.v2_canonical,
            "COMPAT_INFLUENCE_BLOCKS_AUTHORITATIVE_TRUTH_PATH_POLICY",
            (
                f"truth_kind={ctx.truth_kind!r} arrived via unbound compat/legacy "
                f"influence path; blocked from canonical ingress"
            ),
        )
        logger.debug(
            "flow_truth_align: block_due_to_compat_influence "
            "flow=%s kind=%s",
            ctx.delegated_flow_id,
            ctx.truth_kind,
        )
        return artifact

    # ------------------------------------------------------------------
    # Rule 2: V2 canonical terminal wins
    # ------------------------------------------------------------------
    if _is_v2_terminal(ctx.v2_canonical_flow_phase):
        artifact = _build_artifact(
            ctx,
            FlowTruthDecisionKind.reject_due_to_canonical_terminal,
            semantic_kind,
            FlowTruthOwnerKind.v2_canonical,
            "V2_CANONICAL_OWNS_TERMINAL_FLOW_DECISION_POLICY",
            (
                f"V2 canonical flow is already terminal "
                f"(phase={ctx.v2_canonical_flow_phase!r}); "
                f"incoming Android truth_kind={ctx.truth_kind!r} rejected"
            ),
        )
        logger.debug(
            "flow_truth_align: reject_due_to_canonical_terminal "
            "flow=%s phase=%s kind=%s",
            ctx.delegated_flow_id,
            ctx.v2_canonical_flow_phase,
            ctx.truth_kind,
        )
        return artifact

    # ------------------------------------------------------------------
    # Rule 3: Posture conflict quarantine (evidence / partial only)
    # ------------------------------------------------------------------
    if ctx.posture_changed and semantic_kind in (
        FlowTruthSemanticKind.execution_evidence,
        FlowTruthSemanticKind.partial_result,
        FlowTruthSemanticKind.posture_sensitive,
    ):
        artifact = _build_artifact(
            ctx,
            FlowTruthDecisionKind.quarantine_due_to_posture_conflict,
            semantic_kind,
            FlowTruthOwnerKind.v2_canonical,
            "POSTURE_CHANGE_QUARANTINES_PRIOR_EVIDENCE_POLICY",
            (
                f"posture changed mid-flow; truth_kind={ctx.truth_kind!r} "
                f"(semantic={semantic_kind.value}) quarantined pending re-evaluation"
            ),
        )
        logger.debug(
            "flow_truth_align: quarantine_due_to_posture_conflict "
            "flow=%s kind=%s posture=%s",
            ctx.delegated_flow_id,
            ctx.truth_kind,
            ctx.device_posture,
        )
        return artifact

    # ------------------------------------------------------------------
    # Rule 4: Authoritative Android terminal truth
    # ------------------------------------------------------------------
    if semantic_kind == FlowTruthSemanticKind.authoritative:
        # Android has reported a terminal truth (cancel/failure/result or
        # completed/failed/cancelled task_phase).  V2 canonical phase is
        # not yet terminal, so this truth must be applied upward.
        # Flag pending_v2_confirmation to mark the intermediate state where
        # Android has advanced but V2 has not yet confirmed.
        artifact = _build_artifact(
            ctx,
            FlowTruthDecisionKind.accept_as_authoritative,
            semantic_kind,
            FlowTruthOwnerKind.android_execution,
            "ANDROID_CANCEL_FAILURE_RESULT_ARE_AUTHORITATIVE_UPWARD_POLICY",
            (
                f"Android truth_kind={ctx.truth_kind!r} is authoritative for "
                f"device-scope execution; applied upward to V2 canonical tracking"
            ),
            pending_v2_confirmation=True,
        )
        logger.debug(
            "flow_truth_align: accept_as_authoritative "
            "flow=%s kind=%s",
            ctx.delegated_flow_id,
            ctx.truth_kind,
        )
        return artifact

    # ------------------------------------------------------------------
    # Rule 5: Partial result
    # ------------------------------------------------------------------
    if semantic_kind == FlowTruthSemanticKind.partial_result:
        artifact = _build_artifact(
            ctx,
            FlowTruthDecisionKind.accept_as_advisory,
            FlowTruthSemanticKind.partial_result,
            FlowTruthOwnerKind.android_execution,
            "PARTIAL_RESULT_LIVES_IN_EXECUTION_TRACKING_RECORD_POLICY",
            (
                "partial result preserved on execution tracking record; "
                "flow not closed — awaiting final result / failure / cancel"
            ),
        )
        logger.debug(
            "flow_truth_align: accept_as_advisory (partial_result) "
            "flow=%s",
            ctx.delegated_flow_id,
        )
        return artifact

    # ------------------------------------------------------------------
    # Rule 6: Advisory truth
    # ------------------------------------------------------------------
    if semantic_kind == FlowTruthSemanticKind.advisory:
        artifact = _build_artifact(
            ctx,
            FlowTruthDecisionKind.accept_as_advisory,
            semantic_kind,
            FlowTruthOwnerKind.android_execution,
            "ADVISORY_TRUTH_IS_NOTED_NOT_APPLIED_POLICY",
            (
                f"Android truth_kind={ctx.truth_kind!r} is advisory; "
                "noted for audit — V2 canonical state unaffected"
            ),
        )
        logger.debug(
            "flow_truth_align: accept_as_advisory (advisory) "
            "flow=%s kind=%s",
            ctx.delegated_flow_id,
            ctx.truth_kind,
        )
        return artifact

    # ------------------------------------------------------------------
    # Rule 7: Execution evidence / posture-sensitive
    # ------------------------------------------------------------------
    if semantic_kind in (
        FlowTruthSemanticKind.execution_evidence,
        FlowTruthSemanticKind.posture_sensitive,
    ):
        artifact = _build_artifact(
            ctx,
            FlowTruthDecisionKind.record_as_execution_evidence,
            semantic_kind,
            FlowTruthOwnerKind.android_execution,
            "EXECUTION_EVIDENCE_IS_AUDIT_ONLY_POLICY",
            (
                f"Android truth_kind={ctx.truth_kind!r} is execution evidence; "
                "recorded to ReplayFoundation — V2 canonical state unaffected"
            ),
        )
        logger.debug(
            "flow_truth_align: record_as_execution_evidence "
            "flow=%s kind=%s",
            ctx.delegated_flow_id,
            ctx.truth_kind,
        )
        return artifact

    # ------------------------------------------------------------------
    # Rule 8: Unknown fallback — safe advisory default
    # ------------------------------------------------------------------
    artifact = _build_artifact(
        ctx,
        FlowTruthDecisionKind.accept_as_advisory,
        FlowTruthSemanticKind.advisory,
        FlowTruthOwnerKind.v2_canonical,
        "UNKNOWN_TRUTH_KIND_DEFAULTS_TO_ADVISORY_POLICY",
        (
            f"truth_kind={ctx.truth_kind!r} could not be resolved; "
            "defaulting to advisory per safe-default policy"
        ),
    )
    logger.debug(
        "flow_truth_align: accept_as_advisory (unknown fallback) "
        "flow=%s kind=%s",
        ctx.delegated_flow_id,
        ctx.truth_kind,
    )
    return artifact


def evaluate_posture_change_impact(
    prior_artifacts: Sequence[FlowTruthDecisionArtifact],
    *,
    new_posture: str,
    old_posture: str,
    delegated_flow_id: str = "",
) -> List[PostureChangeImpactRecord]:
    """Re-evaluate prior truth items after a device posture change.

    For each artifact in *prior_artifacts* this function determines whether
    the item must be quarantined, retained, or can be promoted under the new
    posture.

    Rules
    -----
    * Artifacts with decision ``reject_due_to_canonical_terminal`` or
      ``block_due_to_compat_influence`` are always retained as-is (they are
      final and posture-independent).
    * Artifacts with semantic kind ``execution_evidence``, ``partial_result``,
      or ``posture_sensitive`` are quarantined per
      POSTURE_CHANGE_QUARANTINES_PRIOR_EVIDENCE_POLICY.
    * Artifacts with decision ``accept_as_authoritative`` (terminal truths
      already applied) are retained — they have already updated canonical state
      and cannot be un-applied.
    * All other artifacts (advisory, etc.) are retained.

    Parameters
    ----------
    prior_artifacts:
        Sequence of :class:`FlowTruthDecisionArtifact` records already
        produced for this flow.
    new_posture:
        The new device posture string after the change.
    old_posture:
        The device posture string before the change.
    delegated_flow_id:
        Flow identifier for logging correlation.

    Returns
    -------
    list[PostureChangeImpactRecord]
        One record per input artifact describing the revised handling.
    """
    _quarantine_semantics = frozenset({
        FlowTruthSemanticKind.execution_evidence,
        FlowTruthSemanticKind.partial_result,
        FlowTruthSemanticKind.posture_sensitive,
    })
    _retain_decisions = frozenset({
        FlowTruthDecisionKind.reject_due_to_canonical_terminal,
        FlowTruthDecisionKind.block_due_to_compat_influence,
        FlowTruthDecisionKind.accept_as_authoritative,
    })

    records: List[PostureChangeImpactRecord] = []
    for art in prior_artifacts:
        if art.decision in _retain_decisions:
            records.append(PostureChangeImpactRecord(
                prior_artifact_id=art.artifact_id,
                truth_kind=art.evidence.get("truth_kind", ""),
                original_decision=art.decision,
                revised_handling=PostureChangeHandling.retain,
                reason=(
                    f"decision={art.decision.value} is posture-independent; "
                    "retained after posture change"
                ),
            ))
        elif art.semantic_kind in _quarantine_semantics:
            records.append(PostureChangeImpactRecord(
                prior_artifact_id=art.artifact_id,
                truth_kind=art.evidence.get("truth_kind", ""),
                original_decision=art.decision,
                revised_handling=PostureChangeHandling.quarantine,
                reason=(
                    f"posture changed {old_posture!r} → {new_posture!r}; "
                    f"semantic={art.semantic_kind.value} must be quarantined "
                    "per POSTURE_CHANGE_QUARANTINES_PRIOR_EVIDENCE_POLICY"
                ),
            ))
        else:
            records.append(PostureChangeImpactRecord(
                prior_artifact_id=art.artifact_id,
                truth_kind=art.evidence.get("truth_kind", ""),
                original_decision=art.decision,
                revised_handling=PostureChangeHandling.retain,
                reason=(
                    f"advisory truth retained after posture change "
                    f"{old_posture!r} → {new_posture!r}"
                ),
            ))

    logger.debug(
        "evaluate_posture_change_impact: flow=%s old=%s new=%s "
        "items=%d quarantined=%d",
        delegated_flow_id,
        old_posture,
        new_posture,
        len(records),
        sum(1 for r in records if r.revised_handling == PostureChangeHandling.quarantine),
    )
    return records


# ===========================================================================
# Alignment runtime (ring-buffer singleton)
# ===========================================================================

_RING_BUFFER_SIZE: int = 256


class FlowTruthAlignmentRuntime:
    """In-process ring-buffer singleton accumulating :class:`FlowTruthDecisionArtifact` records.

    All calls to :func:`align_android_truth_with_canonical` that pass through
    :func:`record_flow_truth_decision` are stored here.  Operator surfaces and
    audit tools can inspect the alignment history via
    :func:`build_flow_truth_alignment_snapshot`.

    Parameters
    ----------
    capacity:
        Maximum number of artifacts to retain (newest-first ring buffer).
        Defaults to ``_RING_BUFFER_SIZE`` (256).
    """

    def __init__(self, capacity: int = _RING_BUFFER_SIZE) -> None:
        self._capacity = capacity
        self._ring: Deque[FlowTruthDecisionArtifact] = deque(maxlen=capacity)
        self._total: int = 0
        self._lock: Lock = Lock()

    def record(self, artifact: FlowTruthDecisionArtifact) -> None:
        """Append *artifact* to the ring buffer."""
        with self._lock:
            self._ring.appendleft(artifact)
            self._total += 1

    def list_recent(self, n: int = 20) -> List[FlowTruthDecisionArtifact]:
        """Return up to *n* most-recent artifacts (newest-first)."""
        with self._lock:
            return list(self._ring)[:n]

    def get_by_artifact_id(
        self, artifact_id: str
    ) -> Optional[FlowTruthDecisionArtifact]:
        """Return the artifact matching *artifact_id*, or ``None``."""
        with self._lock:
            for art in self._ring:
                if art.artifact_id == artifact_id:
                    return art
        return None

    def get_by_flow_id(
        self, delegated_flow_id: str
    ) -> List[FlowTruthDecisionArtifact]:
        """Return all artifacts for *delegated_flow_id*, newest-first."""
        with self._lock:
            return [
                a for a in self._ring if a.delegated_flow_id == delegated_flow_id
            ]

    def build_snapshot(self) -> FlowTruthAlignmentSnapshot:
        """Build and return a :class:`FlowTruthAlignmentSnapshot`."""
        with self._lock:
            ring_copy = list(self._ring)
            total = self._total

        counts: Dict[str, int] = {}
        for art in ring_copy:
            counts[art.decision.value] = counts.get(art.decision.value, 0) + 1

        return FlowTruthAlignmentSnapshot(
            total_decisions=total,
            recent_artifacts=ring_copy[:20],
            decision_counts=counts,
        )


# Module-level singleton
_RUNTIME: Optional[FlowTruthAlignmentRuntime] = None
_RUNTIME_LOCK: Lock = Lock()


def get_flow_truth_alignment_runtime() -> FlowTruthAlignmentRuntime:
    """Return the module-level :class:`FlowTruthAlignmentRuntime` singleton."""
    global _RUNTIME  # noqa: PLW0603
    if _RUNTIME is None:
        with _RUNTIME_LOCK:
            if _RUNTIME is None:
                _RUNTIME = FlowTruthAlignmentRuntime()
    return _RUNTIME


def reset_flow_truth_alignment_runtime() -> None:
    """Reset the singleton (test isolation only)."""
    global _RUNTIME  # noqa: PLW0603
    with _RUNTIME_LOCK:
        _RUNTIME = None


def record_flow_truth_decision(
    artifact: FlowTruthDecisionArtifact,
) -> None:
    """Record *artifact* to the module-level alignment runtime.

    Convenience wrapper combining :func:`align_android_truth_with_canonical`
    output with :meth:`FlowTruthAlignmentRuntime.record`.

    Parameters
    ----------
    artifact:
        The :class:`FlowTruthDecisionArtifact` to record.
    """
    get_flow_truth_alignment_runtime().record(artifact)


def align_and_record(ctx: FlowTruthAlignmentContext) -> FlowTruthDecisionArtifact:
    """Align Android truth with V2 canonical **and** record the artifact.

    Convenience wrapper: calls :func:`align_android_truth_with_canonical`
    then :func:`record_flow_truth_decision`.

    Parameters
    ----------
    ctx:
        Full alignment context for the incoming Android truth.

    Returns
    -------
    FlowTruthDecisionArtifact
        The typed alignment decision artifact (already recorded).
    """
    artifact = align_android_truth_with_canonical(ctx)
    record_flow_truth_decision(artifact)
    return artifact


def build_flow_truth_alignment_snapshot() -> FlowTruthAlignmentSnapshot:
    """Return a point-in-time snapshot of the alignment runtime.

    Suitable for operator surfaces, diagnostic endpoints, and CI gates.
    """
    return get_flow_truth_alignment_runtime().build_snapshot()


# ===========================================================================
# __all__
# ===========================================================================

__all__ = [
    # Authority / PR sentinels
    "FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY",
    "FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL",
    # Policy sentinels
    "V2_CANONICAL_OWNS_TERMINAL_FLOW_DECISION_POLICY",
    "ANDROID_CANCEL_FAILURE_RESULT_ARE_AUTHORITATIVE_UPWARD_POLICY",
    "PARTIAL_RESULT_LIVES_IN_EXECUTION_TRACKING_RECORD_POLICY",
    "ADVISORY_TRUTH_IS_NOTED_NOT_APPLIED_POLICY",
    "EXECUTION_EVIDENCE_IS_AUDIT_ONLY_POLICY",
    "POSTURE_CHANGE_QUARANTINES_PRIOR_EVIDENCE_POLICY",
    "COMPAT_INFLUENCE_BLOCKS_AUTHORITATIVE_TRUTH_PATH_POLICY",
    "ANDROID_ADVANCED_AHEAD_OF_V2_CONFIRMATION_POLICY",
    "UNKNOWN_TRUTH_KIND_DEFAULTS_TO_ADVISORY_POLICY",
    # Enums
    "FlowTruthSemanticKind",
    "FlowTruthDecisionKind",
    "FlowTruthOwnerKind",
    "PostureChangeHandling",
    # Data classes
    "FlowTruthAlignmentContext",
    "FlowTruthDecisionArtifact",
    "PostureChangeImpactRecord",
    "FlowTruthAlignmentSnapshot",
    # Runtime
    "FlowTruthAlignmentRuntime",
    # Functions
    "classify_flow_truth_kind",
    "align_android_truth_with_canonical",
    "evaluate_posture_change_impact",
    "align_and_record",
    "record_flow_truth_decision",
    "build_flow_truth_alignment_snapshot",
    "get_flow_truth_alignment_runtime",
    "reset_flow_truth_alignment_runtime",
]
