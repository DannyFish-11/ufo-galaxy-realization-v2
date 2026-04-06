"""core/delegated_target_selection_policy.py
=============================================
PR package 20 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Canonical Delegated Target Selection Policy.

This module is the **canonical authority** for the delegated target selection
policy layer that sits above the authoritative attached runtime session
registry (PR-19) and decides *which* attached runtime session candidate the
dispatch layer should target when multiple candidates are eligible.

Background
----------
Prior to PR-20 the main repo held authoritative session state (via the PR-19
registry) but lacked a canonical, stable, and explainable mechanism for
choosing *which* session to dispatch to when multiple attached runtime
candidates exist.  That gap meant that:

- Multi-candidate scenarios had no stable, deterministic ranking.
- High-risk candidates (many recent failures, bad posture, invalid reuse)
  could be selected over healthier alternatives.
- There was no explicit degrade / local-fallback decision when *no* valid
  candidate existed.
- The selection result was opaque — callers could not inspect *why* a
  candidate was chosen or rejected.

PR-20 closes this gap by introducing the :func:`select_delegated_target`
function as the canonical pre-dispatch selection gate.  All delegated dispatch
paths MUST call this function (or supply its :class:`SelectionDecision` result)
before committing to a dispatch target.

Design
------
1. **Candidate context** — callers supply a list of
   :class:`SelectionCandidateContext` objects, each wrapping an
   :class:`~core.attached_runtime_session_registry.AttachedSessionRegistryEntry`
   from PR-19 plus optional contextual signals: ``is_reuse_valid``,
   ``delegated_execution_count``, ``recent_failure_count``,
   ``recent_detach_count``.
2. **Evaluation gate** — :func:`evaluate_candidate` inspects every candidate
   and produces a :class:`CandidateEvaluation` capturing a numeric score, a
   rejection reason (or ``none`` when the candidate is acceptable), and a
   human-readable explanation fragment.
3. **Ranking** — :func:`rank_candidates` sorts the list of valid (accepted)
   candidates from highest score to lowest score so that the
   :func:`select_delegated_target` call can simply pick the first element.
4. **Selection decision** — :func:`select_delegated_target` combines
   evaluation + ranking and returns a :class:`SelectionDecision` with:

   - ``outcome``: :class:`SelectionOutcome` (``selected_attached``,
     ``local_fallback``, or ``degrade``).
   - ``selected_candidate``: the winning :class:`SelectionCandidateContext`,
     or ``None`` on fallback / degrade.
   - ``selected_evaluation``: the winning :class:`CandidateEvaluation`, or
     ``None`` on fallback / degrade.
   - ``rejected_evaluations``: evaluations for all rejected candidates.
   - ``fallback_reason``: human-readable reason when outcome is not
     ``selected_attached``.
   - ``explanation``: structured dict for debug / observability.

5. **Explanation surface** — :func:`build_selection_explanation` converts a
   :class:`SelectionDecision` into a fully serialisable dict that callers can
   log, surface in a projection endpoint, or emit via telemetry.

Scoring heuristics (higher is better)
--------------------------------------
Starting from a baseline score of 100 for every candidate that passes the
eligibility gate (active + join_runtime posture + no invalidation), the
following adjustments are applied:

+30   is_reuse_valid == True  (stable, established reuse surface)
-10   per ``recent_failure_count`` (capped at −50; max 5 failures penalised)
-10   per ``recent_detach_count``  (capped at −30; max 3 detaches penalised)
- 5   per 10 ``delegated_execution_count`` (load signal; capped at −20)

A candidate whose adjusted score drops below
:data:`DEGRADATION_SCORE_THRESHOLD` (default 40) is treated as *high-risk*
and is eligible for demotion to local-fallback even if it technically passes
the eligibility gate.  If the single best candidate is high-risk and no
healthier alternative exists, :func:`select_delegated_target` returns
``outcome=degrade`` instead of ``selected_attached``.

Public API
----------
Sentinels::

    DELEGATED_TARGET_SELECTION_POLICY_AUTHORITY
    SELECTION_MUST_CONSULT_REGISTRY_POLICY
    SELECTION_REQUIRES_ACTIVE_ATTACHMENT_STATE_POLICY
    SELECTION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY
    SELECTION_REQUIRES_NO_INVALIDATION_REASON_POLICY
    SELECTION_REUSE_VALID_IS_PREFERRED_POLICY
    SELECTION_HIGH_FAILURE_COUNT_DEMOTES_CANDIDATE_POLICY
    SELECTION_HIGH_DETACH_COUNT_DEMOTES_CANDIDATE_POLICY
    SELECTION_NO_VALID_CANDIDATE_TRIGGERS_LOCAL_FALLBACK_POLICY
    SELECTION_HIGH_RISK_CANDIDATE_MAY_DEGRADE_POLICY
    SELECTION_DECISION_IS_EXPLAINABLE_POLICY
    SELECTION_RANKING_IS_DETERMINISTIC_POLICY
    DELEGATED_TARGET_SELECTION_POLICY_PR20_SENTINEL

Constants::

    DEGRADATION_SCORE_THRESHOLD
    BASE_CANDIDATE_SCORE
    REUSE_VALID_BONUS
    FAILURE_COUNT_PENALTY_PER_UNIT
    FAILURE_COUNT_MAX_PENALTY
    DETACH_COUNT_PENALTY_PER_UNIT
    DETACH_COUNT_MAX_PENALTY
    LOAD_PENALTY_PER_10_EXECUTIONS
    LOAD_MAX_PENALTY

Enums::

    SelectionOutcome
    CandidateRejectionReason

Dataclasses::

    SelectionCandidateContext
    CandidateEvaluation
    SelectionDecision

Functions::

    evaluate_candidate(ctx) -> CandidateEvaluation
    rank_candidates(candidates) -> list[SelectionCandidateContext]
    select_delegated_target(candidates, ...) -> SelectionDecision
    build_selection_explanation(decision) -> dict[str, Any]
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from core.attached_runtime_session_registry import (
    AttachedSessionRegistryEntry,
    InvalidationReason,
    RegistryEntryState,
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

DELEGATED_TARGET_SELECTION_POLICY_AUTHORITY: str = (
    "DELEGATED_TARGET_SELECTION_POLICY_AUTHORITY::"
    "core.delegated_target_selection_policy is the canonical authority for "
    "the delegated target selection policy layer (PR package 20, post-533 "
    "dual-repo runtime unification).  All delegated dispatch paths MUST "
    "consult select_delegated_target() before committing to a dispatch target."
)

SELECTION_MUST_CONSULT_REGISTRY_POLICY: str = (
    "POLICY::SELECTION_MUST_CONSULT_REGISTRY: candidate contexts MUST be "
    "sourced from the authoritative attached runtime session registry "
    "(core.attached_runtime_session_registry, PR-19).  Callers must call "
    "list_active_sessions() or supply entries retrieved via "
    "lookup_active_session() / lookup_session_by_device() before invoking "
    "select_delegated_target()."
)

SELECTION_REQUIRES_ACTIVE_ATTACHMENT_STATE_POLICY: str = (
    "POLICY::SELECTION_REQUIRES_ACTIVE_ATTACHMENT_STATE: a candidate is "
    "eligible for selection only when its registry entry carries "
    "attachment_state == 'active'.  Entries in 'detached', 'replaced', or "
    "'invalidated' state MUST be rejected regardless of other signals."
)

SELECTION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY: str = (
    "POLICY::SELECTION_REQUIRES_JOIN_RUNTIME_POSTURE: a candidate is "
    "eligible for selection only when its posture is 'join_runtime'.  "
    "Devices in 'control_only' or any other non-join posture MUST be "
    "rejected as delegated execution targets."
)

SELECTION_REQUIRES_NO_INVALIDATION_REASON_POLICY: str = (
    "POLICY::SELECTION_REQUIRES_NO_INVALIDATION_REASON: a candidate whose "
    "registry entry carries any invalidation_reason other than 'none' MUST "
    "be rejected, even if its attachment_state appears active.  The "
    "invalidation_reason field captures explicit reason signals that "
    "supersede state alone."
)

SELECTION_REUSE_VALID_IS_PREFERRED_POLICY: str = (
    "POLICY::SELECTION_REUSE_VALID_IS_PREFERRED: among otherwise equal "
    "candidates, a candidate with is_reuse_valid=True MUST receive a scoring "
    "bonus (+30) and rank above a candidate with is_reuse_valid=False.  A "
    "valid reuse surface signals that an established, healthy dispatch binding "
    "already exists for this session."
)

SELECTION_HIGH_FAILURE_COUNT_DEMOTES_CANDIDATE_POLICY: str = (
    "POLICY::SELECTION_HIGH_FAILURE_COUNT_DEMOTES_CANDIDATE: each unit of "
    "recent_failure_count deducts 10 points from the candidate score (capped "
    "at -50).  A candidate with a high recent failure count is deprioritised "
    "relative to healthier alternatives and may fall below the degradation "
    "threshold."
)

SELECTION_HIGH_DETACH_COUNT_DEMOTES_CANDIDATE_POLICY: str = (
    "POLICY::SELECTION_HIGH_DETACH_COUNT_DEMOTES_CANDIDATE: each unit of "
    "recent_detach_count deducts 10 points from the candidate score (capped "
    "at -30).  Frequent recent detaches indicate an unstable attachment and "
    "lower the dispatch priority of that candidate."
)

SELECTION_NO_VALID_CANDIDATE_TRIGGERS_LOCAL_FALLBACK_POLICY: str = (
    "POLICY::SELECTION_NO_VALID_CANDIDATE_TRIGGERS_LOCAL_FALLBACK: when the "
    "evaluated candidate list contains no accepted candidate, "
    "select_delegated_target() MUST return outcome='local_fallback'.  The "
    "dispatch layer MUST then execute the task locally rather than attempting "
    "a delegated dispatch to a potentially stale or invalid session."
)

SELECTION_HIGH_RISK_CANDIDATE_MAY_DEGRADE_POLICY: str = (
    "POLICY::SELECTION_HIGH_RISK_CANDIDATE_MAY_DEGRADE: when the best "
    "available candidate has a score below DEGRADATION_SCORE_THRESHOLD (40) "
    "and no healthier alternative exists, select_delegated_target() MUST "
    "return outcome='degrade' rather than 'selected_attached', signalling to "
    "the dispatch layer that it should prefer local execution over the "
    "high-risk candidate."
)

SELECTION_DECISION_IS_EXPLAINABLE_POLICY: str = (
    "POLICY::SELECTION_DECISION_IS_EXPLAINABLE: every SelectionDecision "
    "carries a structured explanation dict that records why each candidate "
    "was accepted or rejected, what score it received, and what outcome was "
    "reached.  Callers MUST surface this explanation in logs or projection "
    "endpoints to enable debugging and auditability."
)

SELECTION_RANKING_IS_DETERMINISTIC_POLICY: str = (
    "POLICY::SELECTION_RANKING_IS_DETERMINISTIC: rank_candidates() produces "
    "a stable, deterministic ordering.  When two candidates have equal scores, "
    "the one with the lexicographically smaller session_id wins.  This "
    "ensures that repeated calls with the same inputs produce the same ranking."
)

DELEGATED_TARGET_SELECTION_POLICY_PR20_SENTINEL: str = (
    "DELEGATED_TARGET_SELECTION_POLICY_PR20::canonical-delegated-target-"
    "selection-policy::package=20::post-533-dual-repo-runtime-unification"
)

# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------

DEGRADATION_SCORE_THRESHOLD: int = 40
"""Minimum acceptable score.  Candidates below this are treated as high-risk."""

BASE_CANDIDATE_SCORE: int = 100
"""Starting score for every candidate that passes the eligibility gate."""

REUSE_VALID_BONUS: int = 30
"""Score bonus for candidates with is_reuse_valid=True."""

FAILURE_COUNT_PENALTY_PER_UNIT: int = 10
"""Score penalty per unit of recent_failure_count."""

FAILURE_COUNT_MAX_PENALTY: int = 50
"""Maximum score penalty from recent_failure_count alone."""

DETACH_COUNT_PENALTY_PER_UNIT: int = 10
"""Score penalty per unit of recent_detach_count."""

DETACH_COUNT_MAX_PENALTY: int = 30
"""Maximum score penalty from recent_detach_count alone."""

LOAD_PENALTY_PER_10_EXECUTIONS: int = 5
"""Score penalty per 10 units of delegated_execution_count (load signal)."""

LOAD_MAX_PENALTY: int = 20
"""Maximum score penalty from delegated_execution_count alone."""

# Internal posture constant
_POSTURE_JOIN_RUNTIME: str = "join_runtime"


# ---------------------------------------------------------------------------
# SelectionOutcome
# ---------------------------------------------------------------------------


class SelectionOutcome(str, Enum):
    """Outcome of a :func:`select_delegated_target` call.

    Values
    ------
    selected_attached
        A suitable attached runtime candidate was found and selected.  The
        dispatch layer SHOULD proceed with delegated execution targeting the
        ``selected_candidate`` in the returned :class:`SelectionDecision`.
    local_fallback
        No valid attached runtime candidate exists (all candidates failed the
        eligibility gate).  The dispatch layer MUST execute the task locally.
    degrade
        One or more candidates passed the eligibility gate but the best
        available candidate scored below :data:`DEGRADATION_SCORE_THRESHOLD`,
        indicating high dispatch risk.  The dispatch layer SHOULD prefer local
        execution unless it explicitly opts into high-risk dispatch.
    """

    selected_attached = "selected_attached"
    local_fallback = "local_fallback"
    degrade = "degrade"

    @classmethod
    def from_string(
        cls,
        value: str,
        default: "SelectionOutcome" = None,
    ) -> "SelectionOutcome":
        """Parse *value* into a :class:`SelectionOutcome`."""
        try:
            return cls(value.lower().strip())
        except (ValueError, AttributeError):
            if default is not None:
                return default
            return cls.local_fallback

    def is_attached(self) -> bool:
        """Return True if this outcome selects an attached candidate."""
        return self == SelectionOutcome.selected_attached

    def is_fallback(self) -> bool:
        """Return True if this outcome implies local execution."""
        return self in (SelectionOutcome.local_fallback, SelectionOutcome.degrade)


# ---------------------------------------------------------------------------
# CandidateRejectionReason
# ---------------------------------------------------------------------------


class CandidateRejectionReason(str, Enum):
    """Reason why a candidate was rejected during evaluation.

    Values
    ------
    none
        The candidate was accepted (no rejection).
    not_active
        The entry's attachment_state is not 'active'.
    bad_posture
        The entry's posture is not 'join_runtime'.
    explicit_invalidation
        The entry's invalidation_reason is not 'none'.
    high_risk_score
        The candidate passed the eligibility gate but its score is below
        DEGRADATION_SCORE_THRESHOLD, making it a degrade-level candidate.
    """

    none = "none"
    not_active = "not_active"
    bad_posture = "bad_posture"
    explicit_invalidation = "explicit_invalidation"
    high_risk_score = "high_risk_score"

    @classmethod
    def from_string(
        cls,
        value: str,
        default: "CandidateRejectionReason" = None,
    ) -> "CandidateRejectionReason":
        """Parse *value* into a :class:`CandidateRejectionReason`."""
        try:
            return cls(value.lower().strip())
        except (ValueError, AttributeError):
            if default is not None:
                return default
            return cls.none


# ---------------------------------------------------------------------------
# SelectionCandidateContext
# ---------------------------------------------------------------------------


@dataclass
class SelectionCandidateContext:
    """Context wrapper for a single attached runtime selection candidate.

    Callers supply one :class:`SelectionCandidateContext` per candidate
    retrieved from the authoritative session registry (PR-19).  In addition
    to the raw registry entry, callers MAY supply optional contextual signals
    to allow the selection policy to make more informed decisions.

    Attributes
    ----------
    entry
        The :class:`~core.attached_runtime_session_registry.AttachedSessionRegistryEntry`
        from the authoritative registry.  This is the primary source of truth
        for attachment state, posture, and invalidation reason.
    is_reuse_valid
        Whether the candidate's reuse binding (PR-14 / PR-17) is currently
        eligible.  Defaults to False when unknown.
    delegated_execution_count
        Total number of delegated executions completed by this session so far.
        A proxy for current load on the candidate.  Defaults to 0.
    recent_failure_count
        Number of recent delegated execution failures associated with this
        session.  Higher values indicate a less reliable candidate.
        Defaults to 0.
    recent_detach_count
        Number of recent detach signals received for this session.  Higher
        values indicate an unstable attachment.  Defaults to 0.
    metadata
        Arbitrary caller-supplied metadata dict.
    """

    entry: AttachedSessionRegistryEntry
    is_reuse_valid: bool = False
    delegated_execution_count: int = 0
    recent_failure_count: int = 0
    recent_detach_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Convenience pass-through properties

    @property
    def session_id(self) -> str:
        """Shortcut to entry.session_id."""
        return self.entry.session_id

    @property
    def device_id(self) -> str:
        """Shortcut to entry.device_id."""
        return self.entry.device_id

    @property
    def attachment_state(self) -> RegistryEntryState:
        """Shortcut to entry.attachment_state."""
        return self.entry.attachment_state

    @property
    def posture(self) -> str:
        """Shortcut to entry.posture."""
        return self.entry.posture

    @property
    def invalidation_reason(self) -> InvalidationReason:
        """Shortcut to entry.invalidation_reason."""
        return self.entry.invalidation_reason

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable dict representation."""
        return {
            "session_id": self.session_id,
            "device_id": self.device_id,
            "attachment_state": self.attachment_state.value,
            "posture": self.posture,
            "invalidation_reason": self.invalidation_reason.value,
            "is_reuse_valid": self.is_reuse_valid,
            "delegated_execution_count": self.delegated_execution_count,
            "recent_failure_count": self.recent_failure_count,
            "recent_detach_count": self.recent_detach_count,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict(), default=str)


# ---------------------------------------------------------------------------
# CandidateEvaluation
# ---------------------------------------------------------------------------


@dataclass
class CandidateEvaluation:
    """Evaluation result for a single :class:`SelectionCandidateContext`.

    Attributes
    ----------
    candidate
        The evaluated :class:`SelectionCandidateContext`.
    score
        Numeric score assigned to the candidate (higher is better).  Only
        meaningful when ``is_accepted`` is True.
    is_accepted
        True if the candidate passed the eligibility gate; False if it was
        rejected outright.
    rejection_reason
        :class:`CandidateRejectionReason` explaining why this candidate was
        rejected.  ``none`` when the candidate is accepted.
    explanation_fragments
        List of human-readable strings explaining the scoring decisions.
    """

    candidate: SelectionCandidateContext
    score: int
    is_accepted: bool
    rejection_reason: CandidateRejectionReason
    explanation_fragments: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable dict representation."""
        return {
            "session_id": self.candidate.session_id,
            "device_id": self.candidate.device_id,
            "score": self.score,
            "is_accepted": self.is_accepted,
            "rejection_reason": self.rejection_reason.value,
            "explanation_fragments": list(self.explanation_fragments),
        }


# ---------------------------------------------------------------------------
# SelectionDecision
# ---------------------------------------------------------------------------


@dataclass
class SelectionDecision:
    """The overall output of :func:`select_delegated_target`.

    Attributes
    ----------
    decision_id
        Unique identifier for this decision (for correlation / tracing).
    outcome
        :class:`SelectionOutcome` describing whether a candidate was selected,
        or a local-fallback / degrade decision was made.
    selected_candidate
        The winning :class:`SelectionCandidateContext`, or ``None`` when
        outcome is ``local_fallback`` or ``degrade``.
    selected_evaluation
        The :class:`CandidateEvaluation` for the winner, or ``None`` when no
        candidate was selected.
    rejected_evaluations
        :class:`CandidateEvaluation` entries for all rejected candidates (in
        evaluation order).
    fallback_reason
        Human-readable explanation of why a local-fallback or degrade decision
        was reached.  Empty string when outcome is ``selected_attached``.
    decided_at
        Unix epoch seconds when this decision was made.
    explanation
        Structured dict produced by :func:`build_selection_explanation`.
        Populated lazily the first time it is requested via
        :func:`build_selection_explanation`.
    """

    outcome: SelectionOutcome
    selected_candidate: Optional[SelectionCandidateContext]
    selected_evaluation: Optional[CandidateEvaluation]
    rejected_evaluations: List[CandidateEvaluation]
    fallback_reason: str
    decided_at: float = field(default_factory=time.time)
    decision_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    explanation: Dict[str, Any] = field(default_factory=dict)

    def is_attached(self) -> bool:
        """Return True if an attached candidate was selected."""
        return self.outcome == SelectionOutcome.selected_attached

    def is_fallback(self) -> bool:
        """Return True if a local-fallback or degrade outcome was reached."""
        return self.outcome in (
            SelectionOutcome.local_fallback,
            SelectionOutcome.degrade,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable dict representation."""
        return {
            "decision_id": self.decision_id,
            "outcome": self.outcome.value,
            "selected_candidate": (
                self.selected_candidate.to_dict()
                if self.selected_candidate is not None
                else None
            ),
            "selected_evaluation": (
                self.selected_evaluation.to_dict()
                if self.selected_evaluation is not None
                else None
            ),
            "rejected_evaluations": [e.to_dict() for e in self.rejected_evaluations],
            "fallback_reason": self.fallback_reason,
            "decided_at": self.decided_at,
            "explanation": self.explanation,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict(), default=str)


# ---------------------------------------------------------------------------
# Core policy functions
# ---------------------------------------------------------------------------


def evaluate_candidate(ctx: SelectionCandidateContext) -> CandidateEvaluation:
    """Evaluate a single selection candidate and return a :class:`CandidateEvaluation`.

    Eligibility gate (hard rejections)
    -----------------------------------
    The following checks are applied first.  A failure at any check produces
    an immediately rejected evaluation with score 0:

    1. ``attachment_state`` must be ``active``.
    2. ``posture`` must be ``join_runtime``.
    3. ``invalidation_reason`` must be ``none``.

    Scoring (for candidates that pass the eligibility gate)
    -------------------------------------------------------
    Starting from :data:`BASE_CANDIDATE_SCORE` (100), the following
    adjustments are applied:

    * +30 if ``is_reuse_valid`` is True.
    * -10 per ``recent_failure_count`` (capped at -50).
    * -10 per ``recent_detach_count`` (capped at -30).
    * -5 per 10 units of ``delegated_execution_count`` (capped at -20).

    Parameters
    ----------
    ctx
        The candidate context to evaluate.

    Returns
    -------
    CandidateEvaluation
        Evaluation with score, is_accepted flag, rejection_reason, and
        explanation_fragments.
    """
    fragments: List[str] = []

    # ------------------------------------------------------------------
    # Hard eligibility checks
    # ------------------------------------------------------------------

    if ctx.attachment_state != RegistryEntryState.active:
        fragments.append(
            f"REJECTED::not_active: attachment_state={ctx.attachment_state.value!r} "
            "is not 'active'."
        )
        return CandidateEvaluation(
            candidate=ctx,
            score=0,
            is_accepted=False,
            rejection_reason=CandidateRejectionReason.not_active,
            explanation_fragments=fragments,
        )

    if ctx.posture != _POSTURE_JOIN_RUNTIME:
        fragments.append(
            f"REJECTED::bad_posture: posture={ctx.posture!r} is not 'join_runtime'."
        )
        return CandidateEvaluation(
            candidate=ctx,
            score=0,
            is_accepted=False,
            rejection_reason=CandidateRejectionReason.bad_posture,
            explanation_fragments=fragments,
        )

    if ctx.invalidation_reason != InvalidationReason.none:
        fragments.append(
            f"REJECTED::explicit_invalidation: invalidation_reason="
            f"{ctx.invalidation_reason.value!r} is not 'none'."
        )
        return CandidateEvaluation(
            candidate=ctx,
            score=0,
            is_accepted=False,
            rejection_reason=CandidateRejectionReason.explicit_invalidation,
            explanation_fragments=fragments,
        )

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    score = BASE_CANDIDATE_SCORE
    fragments.append(f"BASE_SCORE={BASE_CANDIDATE_SCORE}")

    if ctx.is_reuse_valid:
        score += REUSE_VALID_BONUS
        fragments.append(f"+{REUSE_VALID_BONUS} is_reuse_valid=True")
    else:
        fragments.append("+0 is_reuse_valid=False")

    failure_penalty = min(
        ctx.recent_failure_count * FAILURE_COUNT_PENALTY_PER_UNIT,
        FAILURE_COUNT_MAX_PENALTY,
    )
    if failure_penalty > 0:
        score -= failure_penalty
        fragments.append(
            f"-{failure_penalty} recent_failure_count={ctx.recent_failure_count}"
        )

    detach_penalty = min(
        ctx.recent_detach_count * DETACH_COUNT_PENALTY_PER_UNIT,
        DETACH_COUNT_MAX_PENALTY,
    )
    if detach_penalty > 0:
        score -= detach_penalty
        fragments.append(
            f"-{detach_penalty} recent_detach_count={ctx.recent_detach_count}"
        )

    load_penalty = min(
        (ctx.delegated_execution_count // 10) * LOAD_PENALTY_PER_10_EXECUTIONS,
        LOAD_MAX_PENALTY,
    )
    if load_penalty > 0:
        score -= load_penalty
        fragments.append(
            f"-{load_penalty} load(delegated_execution_count={ctx.delegated_execution_count})"
        )

    fragments.append(f"FINAL_SCORE={score}")

    return CandidateEvaluation(
        candidate=ctx,
        score=score,
        is_accepted=True,
        rejection_reason=CandidateRejectionReason.none,
        explanation_fragments=fragments,
    )


def rank_candidates(
    candidates: List[SelectionCandidateContext],
) -> List[SelectionCandidateContext]:
    """Rank *candidates* from most preferred to least preferred.

    Only candidates that pass the eligibility gate are included in the output;
    candidates that would be rejected by :func:`evaluate_candidate` are
    silently omitted.

    Ranking criteria (primary → secondary)
    ---------------------------------------
    1. Score (descending) — higher score wins.
    2. session_id (ascending) — lexicographic tie-break for determinism.

    Parameters
    ----------
    candidates
        Unordered list of :class:`SelectionCandidateContext` objects.

    Returns
    -------
    list[SelectionCandidateContext]
        Accepted candidates ordered from best to worst.  Empty list when no
        candidate passes the eligibility gate.
    """
    evaluations = [evaluate_candidate(ctx) for ctx in candidates]
    accepted = [(ev.score, ev.candidate) for ev in evaluations if ev.is_accepted]
    accepted.sort(key=lambda t: (-t[0], t[1].session_id))
    return [ctx for _, ctx in accepted]


def select_delegated_target(
    candidates: List[SelectionCandidateContext],
    *,
    allow_high_risk: bool = False,
) -> SelectionDecision:
    """Select the best delegated execution target from *candidates*.

    This is the canonical pre-dispatch selection gate.  All delegated dispatch
    paths MUST call this function (or consume its :class:`SelectionDecision`)
    before forming a dispatch identity.

    Decision flow
    -------------
    1. Evaluate all candidates via :func:`evaluate_candidate`.
    2. Partition into accepted and rejected lists.
    3. If no accepted candidate exists → ``outcome=local_fallback``.
    4. Sort accepted candidates by score (descending), then session_id
       (ascending) for determinism.
    5. If the best accepted candidate's score is below
       :data:`DEGRADATION_SCORE_THRESHOLD` and ``allow_high_risk`` is False
       → ``outcome=degrade``.
    6. Otherwise → ``outcome=selected_attached`` with the highest-scoring
       candidate.

    Parameters
    ----------
    candidates
        List of :class:`SelectionCandidateContext` objects (sourced from the
        authoritative registry, PR-19).  May be empty.
    allow_high_risk
        If True, a high-risk candidate (score < :data:`DEGRADATION_SCORE_THRESHOLD`)
        will still produce ``outcome=selected_attached`` rather than ``degrade``.
        Use with caution; the dispatch layer takes full responsibility for any
        resulting instability.

    Returns
    -------
    SelectionDecision
        The full selection decision including outcome, selected candidate (if
        any), all candidate evaluations, and a structured explanation dict.
    """
    evaluations = [evaluate_candidate(ctx) for ctx in candidates]
    accepted_evals = [ev for ev in evaluations if ev.is_accepted]
    rejected_evals = [ev for ev in evaluations if not ev.is_accepted]

    if not accepted_evals:
        fallback_reason = (
            f"No valid attached runtime candidate found among "
            f"{len(candidates)} candidate(s).  All candidates failed the "
            "eligibility gate (active attachment state + join_runtime posture "
            "+ no invalidation reason required)."
        )
        decision = SelectionDecision(
            outcome=SelectionOutcome.local_fallback,
            selected_candidate=None,
            selected_evaluation=None,
            rejected_evaluations=rejected_evals,
            fallback_reason=fallback_reason,
        )
        decision.explanation = build_selection_explanation(decision)
        return decision

    # Sort: highest score first, then lexicographic session_id for ties.
    accepted_evals.sort(key=lambda ev: (-ev.score, ev.candidate.session_id))
    best_eval = accepted_evals[0]

    if not allow_high_risk and best_eval.score < DEGRADATION_SCORE_THRESHOLD:
        fallback_reason = (
            f"Best candidate (session_id={best_eval.candidate.session_id!r}, "
            f"device_id={best_eval.candidate.device_id!r}) has score "
            f"{best_eval.score} which is below the degradation threshold "
            f"({DEGRADATION_SCORE_THRESHOLD}).  Returning 'degrade' to signal "
            "high dispatch risk."
        )
        # Mark accepted-but-high-risk candidates with high_risk_score reason
        degraded_evals: List[CandidateEvaluation] = []
        for ev in accepted_evals:
            degraded_evals.append(
                CandidateEvaluation(
                    candidate=ev.candidate,
                    score=ev.score,
                    is_accepted=False,
                    rejection_reason=CandidateRejectionReason.high_risk_score,
                    explanation_fragments=ev.explanation_fragments
                    + [
                        f"DEMOTED::high_risk_score: score={ev.score} < "
                        f"threshold={DEGRADATION_SCORE_THRESHOLD}"
                    ],
                )
            )
        decision = SelectionDecision(
            outcome=SelectionOutcome.degrade,
            selected_candidate=None,
            selected_evaluation=None,
            rejected_evaluations=rejected_evals + degraded_evals,
            fallback_reason=fallback_reason,
        )
        decision.explanation = build_selection_explanation(decision)
        return decision

    # Happy path: a valid, healthy candidate is selected.
    remaining_rejected = rejected_evals + [
        CandidateEvaluation(
            candidate=ev.candidate,
            score=ev.score,
            is_accepted=False,
            rejection_reason=CandidateRejectionReason.none,
            explanation_fragments=ev.explanation_fragments
            + ["NOT_SELECTED::lower_score: another candidate ranked higher."],
        )
        for ev in accepted_evals[1:]
    ]

    decision = SelectionDecision(
        outcome=SelectionOutcome.selected_attached,
        selected_candidate=best_eval.candidate,
        selected_evaluation=best_eval,
        rejected_evaluations=remaining_rejected,
        fallback_reason="",
    )
    decision.explanation = build_selection_explanation(decision)
    return decision


def build_selection_explanation(decision: SelectionDecision) -> Dict[str, Any]:
    """Build a fully serialisable explanation dict from a :class:`SelectionDecision`.

    The explanation dict is suitable for:

    - Structured logging (e.g. JSON log lines).
    - Projection endpoint responses (operator / debug surface).
    - Test assertions (verifying why a candidate was or was not selected).

    Parameters
    ----------
    decision
        The :class:`SelectionDecision` to explain.

    Returns
    -------
    dict[str, Any]
        A dict with the following top-level keys:

        ``decision_id``
            Unique identifier for the decision.
        ``outcome``
            The :class:`SelectionOutcome` value string.
        ``selected``
            Dict with ``session_id``, ``device_id``, ``score`` for the winner,
            or ``None`` when no candidate was selected.
        ``fallback_reason``
            Human-readable fallback reason (empty string when selected).
        ``candidate_count``
            Total number of candidates evaluated.
        ``accepted_count``
            Number of candidates that passed the eligibility gate.
        ``rejected_count``
            Number of candidates that failed the eligibility gate or were
            demoted.
        ``candidates``
            List of per-candidate dicts (session_id, device_id, score,
            is_accepted, rejection_reason, explanation_fragments).
        ``policy_sentinels``
            List of policy sentinel strings to confirm which policies governed
            this decision.
        ``decided_at``
            Unix epoch seconds.
    """
    selected_info: Optional[Dict[str, Any]] = None
    if decision.selected_candidate is not None and decision.selected_evaluation is not None:
        selected_info = {
            "session_id": decision.selected_candidate.session_id,
            "device_id": decision.selected_candidate.device_id,
            "score": decision.selected_evaluation.score,
            "is_reuse_valid": decision.selected_candidate.is_reuse_valid,
            "posture": decision.selected_candidate.posture,
            "delegated_execution_count": decision.selected_candidate.delegated_execution_count,
            "recent_failure_count": decision.selected_candidate.recent_failure_count,
            "recent_detach_count": decision.selected_candidate.recent_detach_count,
        }

    # Build per-candidate list: winner first, then rejected.
    all_evaluations: List[CandidateEvaluation] = []
    if decision.selected_evaluation is not None:
        all_evaluations.append(decision.selected_evaluation)
    all_evaluations.extend(decision.rejected_evaluations)

    candidates_info = [ev.to_dict() for ev in all_evaluations]
    accepted_count = sum(1 for ev in all_evaluations if ev.is_accepted)

    return {
        "decision_id": decision.decision_id,
        "outcome": decision.outcome.value,
        "selected": selected_info,
        "fallback_reason": decision.fallback_reason,
        "candidate_count": len(all_evaluations),
        "accepted_count": accepted_count,
        "rejected_count": len(all_evaluations) - accepted_count,
        "candidates": candidates_info,
        "policy_sentinels": [
            DELEGATED_TARGET_SELECTION_POLICY_AUTHORITY,
            SELECTION_MUST_CONSULT_REGISTRY_POLICY,
            SELECTION_REQUIRES_ACTIVE_ATTACHMENT_STATE_POLICY,
            SELECTION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
            SELECTION_REQUIRES_NO_INVALIDATION_REASON_POLICY,
            SELECTION_REUSE_VALID_IS_PREFERRED_POLICY,
            SELECTION_HIGH_FAILURE_COUNT_DEMOTES_CANDIDATE_POLICY,
            SELECTION_HIGH_DETACH_COUNT_DEMOTES_CANDIDATE_POLICY,
            SELECTION_NO_VALID_CANDIDATE_TRIGGERS_LOCAL_FALLBACK_POLICY,
            SELECTION_HIGH_RISK_CANDIDATE_MAY_DEGRADE_POLICY,
            SELECTION_DECISION_IS_EXPLAINABLE_POLICY,
            SELECTION_RANKING_IS_DETERMINISTIC_POLICY,
        ],
        "decided_at": decision.decided_at,
    }
