#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/verification_evidence_closure_contract.py
===============================================
PR-12 (verification/evidence closure semantics):
Verification / Evidence Closure Contract — formal taxonomy and contract
for determining whether verification closure has been authoritatively
established, distinguishing evidence presence from closure completion.

Problem addressed
-----------------
The Galaxy V2 system accumulates substantial evidence from multiple sources:
result artifacts, participant lifecycle truth, Android evaluator readiness
artifacts, delegated runtime audit events, signal surfaces, and acceptance
reviews.  However, before this module the system had no formal contract that
distinguished:

* **Evidence present** (some evidence artifact exists, a signal was emitted,
  or a review step was triggered) from **Verification complete** (all required
  verification checks have been executed and confirmed).
* **Partial substantiation** (a subset of evidence sources confirm a subset
  of claims) from **Conditional closure** (all claims verified subject to
  explicitly scoped conditions) from **Full closure** (all claims verified
  unconditionally).
* **Review passed** (a review gate was traversed) from **Evidence complete**
  (the underlying evidence base is comprehensive and sufficient).

This mismatch means the system could optimistically report "verification
closure established" merely because:
- An evidence artifact exists in a registry, OR
- A review step was marked complete for a subset of claims, OR
- Some signals were observed without comprehensive verification.

None of those conditions alone justify claiming authoritative verification
closure.

This module closes that gap by defining a formal **Verification / Evidence
Closure Contract** that:

1. Establishes five mutually exclusive and exhaustive
   :class:`VerificationClosureClass` verdicts.
2. Defines precise evidence requirements for each class.
3. Enforces conservative *downgrade semantics*: insufficient evidence always
   yields the lowest defensible class rather than the optimistic one.
4. Prohibits treating evidence presence, partial verification, or review
   traversal as equivalent to full closure.
5. Provides a :class:`VerificationClosureVerdict` dataclass consumable by
   truth / acceptance / readiness / governance pipelines.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  VERIFICATION / EVIDENCE CLOSURE CONTRACT  (this module — PR-12)   │
    │                                                                     │
    │  Five closure classes (strictly ordered by closure confidence):    │
    │    1. fully_closed               (highest — all verification        │
    │       checks complete, all evidence sources confirmed, no open      │
    │       conditions or deferred items)                                 │
    │    2. conditionally_closed       (all claims verified subject to    │
    │       explicitly documented, bounded conditions; conditions are      │
    │       formal, not vague; no unscoped open items)                   │
    │    3. partially_substantiated    (a meaningful subset of evidence   │
    │       sources and verification checks are confirmed; some gaps      │
    │       remain; cannot claim closure at any level yet)               │
    │    4. evidence_present_verification_pending  (evidence artifacts    │
    │       exist but verification checks have not yet been executed      │
    │       or confirmed; evidence presence does NOT imply closure)       │
    │    5. unverified                 (lowest — no confirmed evidence    │
    │       or verification; default fail-conservative baseline)          │
    │                                                                     │
    │  Evidence dimensions evaluated:                                    │
    │    • evidence_sources_confirmed  — ≥1 confirmed evidence source    │
    │    • all_evidence_sources_present — all required sources present   │
    │    • verification_checks_executed — all required checks run        │
    │    • verification_checks_passed   — all executed checks passed     │
    │    • review_completed            — review gate traversed           │
    │    • review_accepted             — review gate accepted result     │
    │    • conditions_documented       — any conditions explicitly noted │
    │    • conditions_bounded          — conditions are formally bounded │
    │    • no_open_verification_items  — no unresolved verification gaps │
    │    • multiple_source_convergence — ≥2 independent sources agree    │
    │                                                                     │
    │  Downgrade semantics:                                              │
    │    • no evidence at all → ALWAYS unverified                        │
    │    • evidence present but checks not executed →                    │
    │      NEVER partially_substantiated or higher                       │
    │    • checks executed but not all passed → at most                  │
    │      partially_substantiated                                       │
    │    • review passed but evidence incomplete → downgrade             │
    │    • conditions undocumented or unbounded → downgrade from        │
    │      conditionally_closed to partially_substantiated               │
    │    • open verification items present → NEVER fully_closed          │
    │                                                                     │
    │  Produces:                                                         │
    │    • VerificationClosureVerdict  (structured output)               │
    │                                                                     │
    │  Consumed by:                                                      │
    │    • system_final_acceptance_verdict (verification_evidence_closure │
    │      dimension)                                                     │
    │    • truth / acceptance / readiness / governance surfaces          │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified by this file.
2. **Fail-conservative** — missing or ambiguous evidence yields the lowest
   defensible class (``unverified``) rather than the optimistic one.
3. **No optimistic promotion** — evidence presence, partial review traversal,
   and check execution alone are explicitly excluded from being promoted to
   ``fully_closed`` or ``conditionally_closed``.
4. **Taxonomy boundary enforcement** — evidence presence, verification
   completion, and acceptance closure are treated as *separate* evidence
   dimensions.  Presence of any one does not imply the others.
5. **Projection-only** — this module evaluates evidence fed to it; it never
   mutates external state.

Critical boundary: what counts as fully_closed vs what does not
---------------------------------------------------------------
- **Evidence artifact exists** — does NOT constitute verification closure; the
  artifact may exist before any checks are executed.
- **Review gate traversed** — does NOT constitute fully_closed if evidence is
  incomplete or conditions are undocumented.
- **Partial verification passed** — does NOT constitute conditionally_closed;
  conditions must be explicitly documented and formally bounded.
- **Multiple signals observed** — does NOT constitute fully_closed; signals
  require correlated verification checks against defined criteria.
- **Checks executed but failures present** — MUST downgrade to
  partially_substantiated; a mix of pass/fail never constitutes closure.

Public API
----------
Authority sentinels::

    VERIFICATION_EVIDENCE_CLOSURE_CONTRACT_AUTHORITY
    VERIFICATION_EVIDENCE_CLOSURE_CONTRACT_PR12_SENTINEL

Policy sentinels::

    EVIDENCE_PRESENCE_IS_NOT_VERIFICATION_CLOSURE_POLICY
    PARTIAL_VERIFICATION_IS_NOT_CONDITIONAL_CLOSURE_POLICY
    REVIEW_PASSED_WITHOUT_COMPLETE_EVIDENCE_MUST_DOWNGRADE_POLICY
    EVIDENCE_ABSENCE_DEFAULTS_TO_UNVERIFIED_POLICY
    OPEN_VERIFICATION_ITEMS_BLOCK_FULLY_CLOSED_POLICY
    UNDOCUMENTED_CONDITIONS_BLOCK_CONDITIONAL_CLOSURE_POLICY
    MULTIPLE_SOURCE_CONVERGENCE_REQUIRED_FOR_FULLY_CLOSED_POLICY

Enumerations::

    VerificationClosureClass
    EvidenceSourceStatus
    VerificationCheckStatus

Data classes::

    VerificationClosureEvidence
    VerificationClosureVerdict

Functions::

    classify_verification_closure(evidence) -> VerificationClosureVerdict
    build_verification_closure_verdict(evidence) -> VerificationClosureVerdict
    build_baseline_verification_closure_verdict() -> VerificationClosureVerdict
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.VerificationEvidenceClosureContract")

__all__ = [
    # Authority sentinels
    "VERIFICATION_EVIDENCE_CLOSURE_CONTRACT_AUTHORITY",
    "VERIFICATION_EVIDENCE_CLOSURE_CONTRACT_PR12_SENTINEL",
    # Policy sentinels
    "EVIDENCE_PRESENCE_IS_NOT_VERIFICATION_CLOSURE_POLICY",
    "PARTIAL_VERIFICATION_IS_NOT_CONDITIONAL_CLOSURE_POLICY",
    "REVIEW_PASSED_WITHOUT_COMPLETE_EVIDENCE_MUST_DOWNGRADE_POLICY",
    "EVIDENCE_ABSENCE_DEFAULTS_TO_UNVERIFIED_POLICY",
    "OPEN_VERIFICATION_ITEMS_BLOCK_FULLY_CLOSED_POLICY",
    "UNDOCUMENTED_CONDITIONS_BLOCK_CONDITIONAL_CLOSURE_POLICY",
    "MULTIPLE_SOURCE_CONVERGENCE_REQUIRED_FOR_FULLY_CLOSED_POLICY",
    # Enumerations
    "VerificationClosureClass",
    "EvidenceSourceStatus",
    "VerificationCheckStatus",
    # Data classes
    "VerificationClosureEvidence",
    "VerificationClosureVerdict",
    # Functions
    "classify_verification_closure",
    "build_verification_closure_verdict",
    "build_baseline_verification_closure_verdict",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

VERIFICATION_EVIDENCE_CLOSURE_CONTRACT_AUTHORITY: str = (
    "VERIFICATION_EVIDENCE_CLOSURE_CONTRACT_AUTHORITY::"
    "core.verification_evidence_closure_contract::PR12::"
    "verification-evidence-closure-taxonomy::"
    "formal-closure-contract-for-galaxy-v2-platform"
)
"""Sentinel: this module is the canonical authority for verification /
evidence closure classification in Galaxy V2.

Import this sentinel to assert that a release gate, governance surface,
acceptance evaluator, or runtime truth layer is consuming a formal
closure classification rather than an implicit "evidence present" flag."""

VERIFICATION_EVIDENCE_CLOSURE_CONTRACT_PR12_SENTINEL: str = (
    "VERIFICATION_EVIDENCE_CLOSURE_CONTRACT_PR12_SENTINEL::"
    "package=PR12::profile=verification-evidence-closure-contract-v1::"
    "module=core.verification_evidence_closure_contract"
)
"""Package sentinel for PR-12 verification/evidence closure contract."""

EVIDENCE_PRESENCE_IS_NOT_VERIFICATION_CLOSURE_POLICY: str = (
    "POLICY::EVIDENCE_PRESENCE_IS_NOT_VERIFICATION_CLOSURE_V1: "
    "The existence of evidence artifacts, signals, or review records does NOT "
    "constitute verification closure.  Evidence must be confirmed as complete, "
    "all required verification checks must have been executed and passed, and "
    "no open verification items may remain.  Surfaces MUST NOT report "
    "'verification closure established' merely because an evidence artifact "
    "is present in a registry or a signal was observed.  "
    "See: VerificationClosureClass taxonomy in "
    "core.verification_evidence_closure_contract (PR-12)."
)
"""Policy: evidence presence alone does not constitute verification closure."""

PARTIAL_VERIFICATION_IS_NOT_CONDITIONAL_CLOSURE_POLICY: str = (
    "POLICY::PARTIAL_VERIFICATION_IS_NOT_CONDITIONAL_CLOSURE_V1: "
    "When only a subset of verification checks have been executed or passed, "
    "the closure class MUST be at most partially_substantiated.  "
    "Conditional closure (conditionally_closed) requires ALL claims to be "
    "verified subject to explicitly documented, formally bounded conditions.  "
    "Partial verification — where some checks are incomplete or failed — MUST "
    "NOT be promoted to conditionally_closed by wrapping unverified claims "
    "as 'conditions'.  "
    "See: VerificationClosureClass.conditionally_closed vs "
    "VerificationClosureClass.partially_substantiated in "
    "core.verification_evidence_closure_contract (PR-12)."
)
"""Policy: partial verification must not be promoted to conditional closure."""

REVIEW_PASSED_WITHOUT_COMPLETE_EVIDENCE_MUST_DOWNGRADE_POLICY: str = (
    "POLICY::REVIEW_PASSED_WITHOUT_COMPLETE_EVIDENCE_MUST_DOWNGRADE_V1: "
    "When a review gate has been traversed (review_completed=True, "
    "review_accepted=True) but the underlying evidence base is incomplete "
    "(all_evidence_sources_present=False or verification_checks_passed=False), "
    "the closure class MUST be downgraded.  A review passing without complete "
    "evidence does NOT constitute closure at any level above "
    "evidence_present_verification_pending.  "
    "See: downgrade_reasons in VerificationClosureVerdict (PR-12)."
)
"""Policy: review passed without complete evidence must downgrade class."""

EVIDENCE_ABSENCE_DEFAULTS_TO_UNVERIFIED_POLICY: str = (
    "POLICY::EVIDENCE_ABSENCE_DEFAULTS_TO_UNVERIFIED_V1: "
    "When no confirmed evidence source is available and no verification check "
    "has been executed, the closure class MUST default to unverified.  "
    "The absence of evidence is NOT a signal of verification closure; it is "
    "a signal of unknown / worst-case state.  Silence is not verification.  "
    "See: VerificationClosureClass.unverified in "
    "core.verification_evidence_closure_contract (PR-12)."
)
"""Policy: absence of evidence defaults to unverified (fail-conservative)."""

OPEN_VERIFICATION_ITEMS_BLOCK_FULLY_CLOSED_POLICY: str = (
    "POLICY::OPEN_VERIFICATION_ITEMS_BLOCK_FULLY_CLOSED_V1: "
    "When any open verification items remain (no_open_verification_items=False), "
    "the closure class MUST NOT be fully_closed.  Every open or unresolved "
    "verification item represents a gap that prevents unconditional closure.  "
    "The class MUST be at most conditionally_closed (if conditions are "
    "formally documented and bounded) or partially_substantiated.  "
    "See: VerificationClosureClass.fully_closed requirements in "
    "core.verification_evidence_closure_contract (PR-12)."
)
"""Policy: open verification items block fully_closed classification."""

UNDOCUMENTED_CONDITIONS_BLOCK_CONDITIONAL_CLOSURE_POLICY: str = (
    "POLICY::UNDOCUMENTED_CONDITIONS_BLOCK_CONDITIONAL_CLOSURE_V1: "
    "Conditional closure (conditionally_closed) requires that ALL conditions "
    "under which closure holds be explicitly documented "
    "(conditions_documented=True) AND formally bounded (conditions_bounded=True).  "
    "Vague or unbounded conditions do NOT qualify; they downgrade the class "
    "to partially_substantiated.  Conditions such as 'works in practice' or "
    "'probably fine' are not formally documented or bounded.  "
    "See: VerificationClosureClass.conditionally_closed requirements in "
    "core.verification_evidence_closure_contract (PR-12)."
)
"""Policy: undocumented or unbounded conditions block conditional closure."""

MULTIPLE_SOURCE_CONVERGENCE_REQUIRED_FOR_FULLY_CLOSED_POLICY: str = (
    "POLICY::MULTIPLE_SOURCE_CONVERGENCE_REQUIRED_FOR_FULLY_CLOSED_V1: "
    "fully_closed requires evidence convergence from multiple independent "
    "sources (multiple_source_convergence=True).  A single evidence source, "
    "even if fully verified, does NOT satisfy fully_closed.  Multiple "
    "independent source families (e.g. result artifacts + participant "
    "lifecycle truth + audit events) must independently confirm the same "
    "verification claims.  "
    "See: VerificationClosureClass.fully_closed requirements in "
    "core.verification_evidence_closure_contract (PR-12)."
)
"""Policy: multiple independent source convergence required for fully_closed."""


# ---------------------------------------------------------------------------
# VerificationClosureClass
# ---------------------------------------------------------------------------


class VerificationClosureClass(str, Enum):
    """Five-class taxonomy for verification / evidence closure semantics.

    String values are stable identifiers safe for serialisation, logging,
    and API responses.

    Ordering (from most closed to least):
      fully_closed > conditionally_closed > partially_substantiated >
      evidence_present_verification_pending > unverified
    """

    fully_closed = "fully_closed"
    """All verification checks are complete and passed.  All required evidence
    sources are present, confirmed, and converge from multiple independent
    sources.  No open verification items remain.  No conditions or deferrals.

    Requirements (ALL must hold):
    - evidence_sources_confirmed = True (at least one confirmed source)
    - all_evidence_sources_present = True (all required sources present)
    - verification_checks_executed = True (all checks have been run)
    - verification_checks_passed = True (all executed checks passed)
    - no_open_verification_items = True (no unresolved gaps)
    - multiple_source_convergence = True (≥2 independent sources agree)
    - conditions_documented = False (no conditions — unconditional closure)
      OR conditions_documented = True with conditions_bounded = True AND
      all conditions are confirmed to hold (no remaining uncertainty)
    """

    conditionally_closed = "conditionally_closed"
    """All claims have been verified subject to explicitly documented,
    formally bounded conditions.  Conditions are not vague; they are precise,
    scoped, and recorded.  No unscoped open verification items remain.
    This is NOT the same as partial verification — all claims are verified,
    but only within the documented scope.

    Requirements (ALL must hold):
    - evidence_sources_confirmed = True
    - verification_checks_executed = True (all checks run within conditions)
    - verification_checks_passed = True (all checks passed within conditions)
    - no_open_verification_items = True (no unscoped open items)
    - conditions_documented = True (conditions explicitly recorded)
    - conditions_bounded = True (conditions are formally bounded, not vague)

    NOT satisfied when:
    - any check failed (even if conditions are documented)
    - conditions are undocumented or unbounded ("generally works", "usually ok")
    - evidence is incomplete for the conditioned scope
    """

    partially_substantiated = "partially_substantiated"
    """A meaningful subset of evidence sources and verification checks are
    confirmed and passed.  Some gaps remain.  The evidence base provides
    partial confidence but is insufficient to claim closure at any level.

    Requirements (at least some of):
    - evidence_sources_confirmed = True
    - verification_checks_executed = True (some checks have run)
    - verification_checks_passed = True (some of those checks passed)

    NOT satisfied when:
    - no evidence sources are confirmed (→ evidence_present_verification_pending
      or unverified)
    - checks have not been executed at all (→ evidence_present_verification_pending)
    - no checks have passed (→ evidence_present_verification_pending if evidence
      exists, otherwise unverified)
    """

    evidence_present_verification_pending = "evidence_present_verification_pending"
    """Evidence artifacts or signals exist but verification checks have not
    yet been executed or their results have not been confirmed.  Evidence
    presence alone does NOT imply any level of verification closure.

    Requirements:
    - evidence_sources_confirmed = True (some evidence artifacts exist)
    - verification_checks_executed = False (checks not yet run)
      OR verification_checks_passed = False (checks run but none passed yet)

    NOT satisfied when:
    - no evidence sources are confirmed (→ unverified)
    """

    unverified = "unverified"
    """No confirmed evidence source and no executed verification check.
    This is the fail-conservative default when evidence is absent.

    Requirements (any of):
    - evidence_sources_confirmed = False (no confirmed evidence)
    - AND verification_checks_executed = False
    - No positive evidence signal at all (fail-conservative baseline)
    """

    @property
    def rank(self) -> int:
        """Numeric rank (higher is better / more closed)."""
        return _CLASS_RANK.get(self.value, 0)

    @property
    def is_fully_closed(self) -> bool:
        """Return ``True`` only for ``fully_closed``."""
        return self == VerificationClosureClass.fully_closed

    @property
    def is_closed(self) -> bool:
        """Return ``True`` for ``fully_closed`` or ``conditionally_closed``."""
        return self in (
            VerificationClosureClass.fully_closed,
            VerificationClosureClass.conditionally_closed,
        )

    @property
    def is_evidence_present(self) -> bool:
        """Return ``True`` when at least some evidence is present."""
        return self != VerificationClosureClass.unverified

    @classmethod
    def from_string(cls, value: str) -> "VerificationClosureClass":
        """Return the member matching *value*, defaulting to ``unverified``."""
        if not isinstance(value, str):
            return cls.unverified
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.unverified


# Numeric rank for comparison (lower = worse / less closed)
_CLASS_RANK: Dict[str, int] = {
    VerificationClosureClass.unverified.value: 0,
    VerificationClosureClass.evidence_present_verification_pending.value: 1,
    VerificationClosureClass.partially_substantiated.value: 2,
    VerificationClosureClass.conditionally_closed.value: 3,
    VerificationClosureClass.fully_closed.value: 4,
}


# ---------------------------------------------------------------------------
# EvidenceSourceStatus
# ---------------------------------------------------------------------------


class EvidenceSourceStatus(str, Enum):
    """Status of an individual evidence source family.

    Provides a structured way to describe the state of a single evidence
    source (e.g. result artifacts, participant lifecycle truth, audit events)
    within the overall evidence picture.
    """

    confirmed = "confirmed"
    """Evidence from this source has been received, validated, and confirmed
    as authoritative.  This source contributes positively to the evidence
    picture."""

    present_unconfirmed = "present_unconfirmed"
    """Evidence artifact from this source exists but has not yet been
    validated or confirmed as authoritative.  The artifact may be stale,
    malformed, or pending review.  MUST NOT be treated as confirmed."""

    absent = "absent"
    """No evidence artifact from this source exists.  Conservative default."""

    stale = "stale"
    """Evidence from this source exists but exceeds the freshness window.
    Stale evidence MUST NOT be treated as confirmed."""

    conflicting = "conflicting"
    """Evidence from this source conflicts with evidence from another source.
    Conflicting evidence MUST NOT contribute to closure at any level."""

    unknown = "unknown"
    """Evidence source status cannot be determined.  Conservative default."""


# ---------------------------------------------------------------------------
# VerificationCheckStatus
# ---------------------------------------------------------------------------


class VerificationCheckStatus(str, Enum):
    """Status of an executed verification check.

    Allows precise description of whether a check ran, what it found,
    and whether its result counts toward closure.
    """

    passed = "passed"
    """Check was executed and its result met the pass criterion.  This
    check contributes positively to verification closure."""

    failed = "failed"
    """Check was executed and its result did NOT meet the pass criterion.
    A failed check MUST downgrade the closure class."""

    not_executed = "not_executed"
    """Check has not yet been run.  Evidence may exist but this check
    outcome is unknown.  Conservative default."""

    skipped_with_justification = "skipped_with_justification"
    """Check was intentionally skipped with a documented, formally bounded
    justification.  This is acceptable for conditionally_closed if all
    other conditions are met, but NEVER acceptable for fully_closed."""

    error = "error"
    """Check encountered an error during execution.  An errored check
    MUST be treated as failed for closure purposes."""


# ---------------------------------------------------------------------------
# VerificationClosureEvidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerificationClosureEvidence:
    """Structured evidence input for the verification/evidence closure classifier.

    All fields have safe (fail-conservative) defaults so that an absent
    signal does not silently produce an optimistic classification.

    Attributes
    ----------
    evidence_sources_confirmed:
        True when at least one evidence source has been confirmed as
        authoritative (status = EvidenceSourceStatus.confirmed).
        Defaults to False (conservative).
    all_evidence_sources_present:
        True when ALL required evidence source families are present and
        confirmed.  A subset of sources being present does NOT satisfy
        this flag.  Defaults to False (conservative).
    verification_checks_executed:
        True when ALL required verification checks have been executed
        (not merely scheduled or acknowledged).  Defaults to False
        (conservative).
    verification_checks_passed:
        True when ALL executed verification checks have passed.  A mix
        of pass and fail MUST NOT set this to True.  Defaults to False
        (conservative).
    review_completed:
        True when a formal review gate has been traversed (the review
        process ran to completion).  Defaults to False.  Note: review
        completion alone does NOT imply verification closure; it must
        be combined with complete evidence and passed checks.
    review_accepted:
        True when the review gate produced an accepted / approved result.
        Only meaningful when review_completed=True.  Defaults to False.
    conditions_documented:
        True when conditions under which closure holds are explicitly
        documented.  Required for conditionally_closed.  Defaults to
        False (conservative — absence of documentation blocks conditional
        closure).
    conditions_bounded:
        True when documented conditions are formally bounded (precise,
        scoped, not vague).  Only meaningful when conditions_documented=True.
        Defaults to False (conservative).
    no_open_verification_items:
        True when there are no open, unresolved, or deferred verification
        items.  Any open item blocks fully_closed and conditionally_closed.
        Defaults to False (conservative).
    multiple_source_convergence:
        True when at least two independent evidence source families
        independently confirm the same verification claims.  Required for
        fully_closed.  Defaults to False (conservative).
    participant_id:
        Optional participant or context identifier for traceability.
    trace_id:
        Optional distributed-trace identifier.
    extra_context:
        Optional dict of additional context signals.  Not used in
        classification logic but included in the verdict for auditability.
    """

    evidence_sources_confirmed: bool = False
    all_evidence_sources_present: bool = False
    verification_checks_executed: bool = False
    verification_checks_passed: bool = False
    review_completed: bool = False
    review_accepted: bool = False
    conditions_documented: bool = False
    conditions_bounded: bool = False
    no_open_verification_items: bool = False
    multiple_source_convergence: bool = False
    participant_id: Optional[str] = None
    trace_id: Optional[str] = None
    extra_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "evidence_sources_confirmed": self.evidence_sources_confirmed,
            "all_evidence_sources_present": self.all_evidence_sources_present,
            "verification_checks_executed": self.verification_checks_executed,
            "verification_checks_passed": self.verification_checks_passed,
            "review_completed": self.review_completed,
            "review_accepted": self.review_accepted,
            "conditions_documented": self.conditions_documented,
            "conditions_bounded": self.conditions_bounded,
            "no_open_verification_items": self.no_open_verification_items,
            "multiple_source_convergence": self.multiple_source_convergence,
            "participant_id": self.participant_id,
            "trace_id": self.trace_id,
            "extra_context": dict(self.extra_context),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VerificationClosureEvidence":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        return cls(
            evidence_sources_confirmed=bool(
                data.get("evidence_sources_confirmed", False)
            ),
            all_evidence_sources_present=bool(
                data.get("all_evidence_sources_present", False)
            ),
            verification_checks_executed=bool(
                data.get("verification_checks_executed", False)
            ),
            verification_checks_passed=bool(
                data.get("verification_checks_passed", False)
            ),
            review_completed=bool(data.get("review_completed", False)),
            review_accepted=bool(data.get("review_accepted", False)),
            conditions_documented=bool(data.get("conditions_documented", False)),
            conditions_bounded=bool(data.get("conditions_bounded", False)),
            no_open_verification_items=bool(
                data.get("no_open_verification_items", False)
            ),
            multiple_source_convergence=bool(
                data.get("multiple_source_convergence", False)
            ),
            participant_id=data.get("participant_id"),
            trace_id=data.get("trace_id"),
            extra_context=dict(data.get("extra_context", {})),
        )


# ---------------------------------------------------------------------------
# VerificationClosureVerdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerificationClosureVerdict:
    """Formal verification / evidence closure verdict.

    Produced by :func:`classify_verification_closure`.

    Attributes
    ----------
    closure_class:
        The classified :class:`VerificationClosureClass` for this context.
    rationale:
        Human-readable explanation of why this class was assigned.
        Always non-empty.
    downgrade_reasons:
        List of specific reasons that caused the class to be downgraded from
        an optimistic baseline.  Empty when no downgrade occurred.
    is_fully_closed:
        True only for ``fully_closed`` class.  MUST NOT be set for any
        other class.
    is_closed:
        True for ``fully_closed`` or ``conditionally_closed``.  Indicates
        the verification picture is closed (possibly with conditions).
    is_evidence_present:
        True for all classes except ``unverified``.
    participant_id:
        Identifier of the participant or context this verdict applies to.
    classified_at:
        Unix timestamp (float) when this verdict was produced.
    verdict_id:
        Unique identifier for this verdict instance.
    trace_id:
        Optional distributed-trace identifier.
    """

    closure_class: VerificationClosureClass
    rationale: str
    downgrade_reasons: List[str] = field(default_factory=list)
    is_fully_closed: bool = False
    is_closed: bool = False
    is_evidence_present: bool = False
    participant_id: Optional[str] = None
    classified_at: float = field(default_factory=time.time)
    verdict_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    trace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "closure_class": self.closure_class.value,
            "rationale": self.rationale,
            "downgrade_reasons": list(self.downgrade_reasons),
            "is_fully_closed": self.is_fully_closed,
            "is_closed": self.is_closed,
            "is_evidence_present": self.is_evidence_present,
            "participant_id": self.participant_id,
            "classified_at": self.classified_at,
            "verdict_id": self.verdict_id,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VerificationClosureVerdict":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        class_raw = data.get("closure_class", "unverified")
        try:
            closure_class = VerificationClosureClass(class_raw)
        except ValueError:
            closure_class = VerificationClosureClass.unverified
        return cls(
            closure_class=closure_class,
            rationale=data.get("rationale", ""),
            downgrade_reasons=list(data.get("downgrade_reasons", [])),
            is_fully_closed=bool(data.get("is_fully_closed", False)),
            is_closed=bool(data.get("is_closed", False)),
            is_evidence_present=bool(data.get("is_evidence_present", False)),
            participant_id=data.get("participant_id"),
            classified_at=float(data.get("classified_at", time.time())),
            verdict_id=data.get("verdict_id", uuid.uuid4().hex[:12]),
            trace_id=data.get("trace_id"),
        )


# ---------------------------------------------------------------------------
# Internal classification logic
# ---------------------------------------------------------------------------


def _classify(evidence: VerificationClosureEvidence) -> VerificationClosureVerdict:
    """Internal classification logic (separated for testability)."""
    downgrade_reasons: List[str] = []

    # ------------------------------------------------------------------
    # Rule 0: No evidence at all → unverified (fail-conservative baseline)
    # ------------------------------------------------------------------
    if not evidence.evidence_sources_confirmed:
        return VerificationClosureVerdict(
            closure_class=VerificationClosureClass.unverified,
            rationale=(
                "No confirmed evidence source present.  "
                "EVIDENCE_ABSENCE_DEFAULTS_TO_UNVERIFIED_POLICY requires the "
                "conservative default of unverified when no evidence source "
                "has been confirmed.  Absence of evidence is not a signal of "
                "verification closure."
            ),
            downgrade_reasons=["evidence_sources_confirmed=False"],
            is_fully_closed=False,
            is_closed=False,
            is_evidence_present=False,
            participant_id=evidence.participant_id,
            trace_id=evidence.trace_id,
        )

    # From here, at least one evidence source is confirmed.
    # is_evidence_present = True for all remaining classes.

    # ------------------------------------------------------------------
    # Rule 1: Evidence present but checks not executed →
    #         evidence_present_verification_pending
    # ------------------------------------------------------------------
    if not evidence.verification_checks_executed:
        return VerificationClosureVerdict(
            closure_class=(
                VerificationClosureClass.evidence_present_verification_pending
            ),
            rationale=(
                "Evidence artifacts are present but verification checks have "
                "not been executed.  EVIDENCE_PRESENCE_IS_NOT_VERIFICATION_"
                "CLOSURE_POLICY requires that checks must be executed and "
                "passed before any closure level can be claimed.  Evidence "
                "presence alone does not imply verification closure."
            ),
            downgrade_reasons=["verification_checks_executed=False"],
            is_fully_closed=False,
            is_closed=False,
            is_evidence_present=True,
            participant_id=evidence.participant_id,
            trace_id=evidence.trace_id,
        )

    # ------------------------------------------------------------------
    # Rule 2: Checks executed but not passed →
    #         evidence_present_verification_pending (none passed)
    #         or partially_substantiated (some passed)
    # ------------------------------------------------------------------
    if not evidence.verification_checks_passed:
        # We cannot distinguish "none passed" vs "some passed" from the
        # boolean flags alone.  Conservatively: checks ran but not all passed.
        # If review was also done and accepted, we treat it as providing
        # partial signal — still partially_substantiated at most.
        if evidence.review_completed and evidence.review_accepted:
            downgrade_reasons.append("verification_checks_passed=False")
            downgrade_reasons.append(
                "REVIEW_PASSED_WITHOUT_COMPLETE_EVIDENCE_MUST_DOWNGRADE_POLICY "
                "prevents promoting review_accepted to closure"
            )
            return VerificationClosureVerdict(
                closure_class=VerificationClosureClass.partially_substantiated,
                rationale=(
                    "Verification checks have not all passed, but a review was "
                    "completed and accepted.  "
                    "REVIEW_PASSED_WITHOUT_COMPLETE_EVIDENCE_MUST_DOWNGRADE_POLICY "
                    "prevents this from being promoted to conditionally_closed or "
                    "higher.  "
                    "PARTIAL_VERIFICATION_IS_NOT_CONDITIONAL_CLOSURE_POLICY "
                    "requires at most partially_substantiated when not all checks "
                    "pass."
                ),
                downgrade_reasons=downgrade_reasons,
                is_fully_closed=False,
                is_closed=False,
                is_evidence_present=True,
                participant_id=evidence.participant_id,
                trace_id=evidence.trace_id,
            )
        # Checks executed but not passed, no accepted review — pending
        return VerificationClosureVerdict(
            closure_class=(
                VerificationClosureClass.evidence_present_verification_pending
            ),
            rationale=(
                "Verification checks have been executed but have not all passed.  "
                "PARTIAL_VERIFICATION_IS_NOT_CONDITIONAL_CLOSURE_POLICY requires "
                "that all checks pass before any closure level can be claimed.  "
                "Failed checks must not be wrapped as conditions."
            ),
            downgrade_reasons=["verification_checks_passed=False"],
            is_fully_closed=False,
            is_closed=False,
            is_evidence_present=True,
            participant_id=evidence.participant_id,
            trace_id=evidence.trace_id,
        )

    # From here: evidence_sources_confirmed=True AND
    #            verification_checks_executed=True AND
    #            verification_checks_passed=True.

    # ------------------------------------------------------------------
    # Rule 3: Open verification items block fully_closed and
    #         conditionally_closed → at most partially_substantiated
    # ------------------------------------------------------------------
    if not evidence.no_open_verification_items:
        downgrade_reasons.append("no_open_verification_items=False")
        # Review passed with complete evidence but open items → partial
        return VerificationClosureVerdict(
            closure_class=VerificationClosureClass.partially_substantiated,
            rationale=(
                "Evidence sources are confirmed and checks have passed, but "
                "open verification items remain.  "
                "OPEN_VERIFICATION_ITEMS_BLOCK_FULLY_CLOSED_POLICY prevents "
                "claiming fully_closed or conditionally_closed while open items "
                "are present.  The class is at most partially_substantiated."
            ),
            downgrade_reasons=downgrade_reasons,
            is_fully_closed=False,
            is_closed=False,
            is_evidence_present=True,
            participant_id=evidence.participant_id,
            trace_id=evidence.trace_id,
        )

    # From here: all checks passed AND no open items.
    # The question is whether we have full closure or conditional closure.

    # ------------------------------------------------------------------
    # Rule 4: Insufficient evidence sources for fully_closed →
    #         at most conditionally_closed (if conditions documented)
    #         or partially_substantiated
    # ------------------------------------------------------------------
    if not evidence.all_evidence_sources_present:
        downgrade_reasons.append("all_evidence_sources_present=False")

    if not evidence.multiple_source_convergence:
        downgrade_reasons.append(
            "multiple_source_convergence=False: "
            "MULTIPLE_SOURCE_CONVERGENCE_REQUIRED_FOR_FULLY_CLOSED_POLICY "
            "requires ≥2 independent sources for fully_closed"
        )

    # ------------------------------------------------------------------
    # Rule 5: Determine fully_closed vs conditionally_closed
    # ------------------------------------------------------------------
    can_be_fully_closed = (
        evidence.all_evidence_sources_present
        and evidence.multiple_source_convergence
        and not downgrade_reasons
    )

    if can_be_fully_closed:
        return VerificationClosureVerdict(
            closure_class=VerificationClosureClass.fully_closed,
            rationale=(
                "All verification checks passed, all evidence sources confirmed "
                "and present, multiple independent sources converge, and no "
                "open verification items remain.  Verification closure is "
                "formally established without conditions."
            ),
            downgrade_reasons=[],
            is_fully_closed=True,
            is_closed=True,
            is_evidence_present=True,
            participant_id=evidence.participant_id,
            trace_id=evidence.trace_id,
        )

    # Not fully_closed — check for conditionally_closed
    if evidence.conditions_documented and evidence.conditions_bounded:
        return VerificationClosureVerdict(
            closure_class=VerificationClosureClass.conditionally_closed,
            rationale=(
                "All verification checks passed and no open items remain, but "
                "closure holds subject to explicitly documented, formally bounded "
                "conditions.  "
                + (
                    "Not all evidence sources are present or multiple-source "
                    "convergence was not established.  "
                    if downgrade_reasons
                    else ""
                )
                + "Conditions are documented and bounded; "
                "conditionally_closed is the correct class."
            ),
            downgrade_reasons=downgrade_reasons,
            is_fully_closed=False,
            is_closed=True,
            is_evidence_present=True,
            participant_id=evidence.participant_id,
            trace_id=evidence.trace_id,
        )

    # Conditions present but not documented/bounded, or downgrade from above
    if evidence.conditions_documented and not evidence.conditions_bounded:
        downgrade_reasons.append(
            "conditions_bounded=False: "
            "UNDOCUMENTED_CONDITIONS_BLOCK_CONDITIONAL_CLOSURE_POLICY requires "
            "conditions to be formally bounded for conditionally_closed"
        )
    elif not evidence.conditions_documented and downgrade_reasons:
        downgrade_reasons.append(
            "conditions_documented=False: "
            "UNDOCUMENTED_CONDITIONS_BLOCK_CONDITIONAL_CLOSURE_POLICY requires "
            "conditions to be documented for conditionally_closed when not "
            "all sources are present"
        )

    return VerificationClosureVerdict(
        closure_class=VerificationClosureClass.partially_substantiated,
        rationale=(
            "Evidence sources are confirmed and checks have passed, but the "
            "evidence base is not comprehensive enough for full or conditional "
            "closure.  "
            + (
                "Conditions are not fully documented or bounded.  "
                if not (evidence.conditions_documented and evidence.conditions_bounded)
                else ""
            )
            + "The class is partially_substantiated: meaningful evidence "
            "exists but closure cannot be formally claimed."
        ),
        downgrade_reasons=downgrade_reasons,
        is_fully_closed=False,
        is_closed=False,
        is_evidence_present=True,
        participant_id=evidence.participant_id,
        trace_id=evidence.trace_id,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_verification_closure(
    evidence: VerificationClosureEvidence,
) -> VerificationClosureVerdict:
    """Classify the verification/evidence closure class for a context.

    This is the canonical entry point for verification / evidence closure
    classification.  It applies the fail-conservative downgrade rules defined
    in the module docstring and enforced by the policy sentinels.

    Classification logic (evaluated in priority order):
    0. ``evidence_sources_confirmed=False`` → **unverified** (always)
    1. ``verification_checks_executed=False`` →
       **evidence_present_verification_pending**
    2. ``verification_checks_passed=False`` →
       **evidence_present_verification_pending** or
       **partially_substantiated** (if review also accepted)
    3. ``no_open_verification_items=False`` → **partially_substantiated**
    4. ``all_evidence_sources_present=True`` AND
       ``multiple_source_convergence=True`` → **fully_closed**
    5. ``conditions_documented=True`` AND ``conditions_bounded=True`` →
       **conditionally_closed**
    6. All other cases → **partially_substantiated** (conservative)

    Parameters
    ----------
    evidence:
        :class:`VerificationClosureEvidence` describing the verification and
        evidence state.

    Returns
    -------
    VerificationClosureVerdict
        Immutable verdict recording the class, rationale, and any downgrade
        reasons.  Never raises; returns ``unverified`` on unexpected input.
    """
    try:
        return _classify(evidence)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "classify_verification_closure: unexpected error: %s", exc
        )
        return VerificationClosureVerdict(
            closure_class=VerificationClosureClass.unverified,
            rationale=(
                f"Classification raised an unexpected error: {exc!r}.  "
                "Returning unverified (fail-conservative)."
            ),
            downgrade_reasons=[f"classification_error: {exc!r}"],
            is_fully_closed=False,
            is_closed=False,
            is_evidence_present=False,
        )


def build_verification_closure_verdict(
    evidence: VerificationClosureEvidence,
) -> VerificationClosureVerdict:
    """Convenience alias for :func:`classify_verification_closure`.

    Provides a name consistent with the ``build_*_verdict`` pattern used
    in other contract modules for consumption by acceptance evaluators.

    Parameters
    ----------
    evidence:
        :class:`VerificationClosureEvidence` to classify.

    Returns
    -------
    VerificationClosureVerdict
    """
    return classify_verification_closure(evidence)


def build_baseline_verification_closure_verdict() -> VerificationClosureVerdict:
    """Return the zero-evidence (fail-conservative baseline) verdict.

    This is the verdict produced when no evidence signals are available.
    It always returns ``unverified`` per
    EVIDENCE_ABSENCE_DEFAULTS_TO_UNVERIFIED_POLICY.

    Used by acceptance evaluators and test harnesses to confirm that the
    contract correctly defaults to the conservative baseline rather than
    producing an optimistic closure class.

    Returns
    -------
    VerificationClosureVerdict
        Always returns a verdict with ``closure_class=unverified``.
    """
    return classify_verification_closure(VerificationClosureEvidence())
