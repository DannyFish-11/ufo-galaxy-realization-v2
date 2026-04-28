#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/release_governance_taxonomy.py
=====================================
PR-8 (taxonomy unification track):
Unified Release / Readiness / Governance / Final-Acceptance Taxonomy.

Background
----------
The V2 repository has accumulated several gate / verdict / report surfaces
over successive PRs:

* ``release_blocking_gate``             — hard CI blocking via CriterionStatus
* ``governance_validation_gate``        — ValidationOutcome / ValidationFailReason
* ``distributed_release_gate_skeleton`` — GateCategoryStrength / ReleaseGateVerdict
* ``system_final_acceptance_verdict``   — DimensionStatus / SystemAcceptanceVerdict

These surfaces are individually well-designed, but as audit, recovery,
Android participant, delegated flow, and dual-repo reality content has grown,
the following friction points have emerged:

* **advisory vs blocking** — no single authoritative definition; each
  surface uses its own terminology.
* **skeleton readiness vs final acceptance** — the relationship between
  non-enforcing skeleton verdicts and binding final-acceptance verdicts
  is implicit rather than stated.
* **unresolved / evidence_gap / deferred / accepted_limitation** — these
  four concepts are semantically distinct but easily conflated when
  reading scattered surface outputs.
* **automated_verified** — no formal definition shared across surfaces.
* **fully_operational / partially_operational / not_ready** — used in
  different places without a single canonical mapping.

This module establishes the **single authoritative taxonomy** for all of
these concepts.  It:

1. Defines canonical :class:`IssueClassification` values for every
   term that appears across gate / verdict / report surfaces.
2. Provides :class:`TerminologyRegistry` — a formal lookup that maps
   every term to its canonical definition, blocking status, and surface
   applicability.
3. Exposes ``TAXONOMY_AUTHORITY`` and per-term policy sentinels that
   downstream surfaces import to document their alignment with the
   unified taxonomy.
4. Provides :func:`classify_issue` — a helper that maps unstructured
   strings from any existing surface to the canonical classification.
5. Provides :func:`verdict_to_classification` — maps legacy verdict
   strings (e.g. ``"blocked"``, ``"deferred"``, ``"unresolved"``) to
   their :class:`IssueClassification`.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │  UNIFIED TAXONOMY  (this module, PR-8)                           │
    │                                                                  │
    │  Consumed by (import only — no mutations):                       │
    │    • release_blocking_gate         (CriterionStatus → taxonomy)  │
    │    • governance_validation_gate    (ValidationFailReason → tax.) │
    │    • system_final_acceptance_verdict (DimensionStatus → tax.)    │
    │    • distributed_release_gate_skeleton (GateCategoryStrength)    │
    │                                                                  │
    │  Defines:                                                        │
    │    • IssueClassification  — 9-value canonical enum               │
    │    • OperationalStatus    — 3-value canonical enum                │
    │    • TaxonomyEntry        — definition record per term           │
    │    • TerminologyRegistry  — full lookup table                    │
    │                                                                  │
    │  Helpers:                                                        │
    │    • classify_issue(text) → IssueClassification                  │
    │    • verdict_to_classification(verdict) → IssueClassification    │
    │    • operational_from_verdict(verdict) → OperationalStatus       │
    │    • is_blocking_classification(cls) → bool                      │
    └──────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified to remove
   existing constants; this module only adds the shared foundation.
2. **Fail-conservative** — any unrecognised term maps to
   :attr:`IssueClassification.unresolved`, not to ``advisory`` or
   ``accepted``.
3. **No semantic upgrade** — this module does NOT optimistically
   upgrade any existing gate verdict.  Terms that represent gaps
   continue to represent gaps.
4. **Import-safe** — no heavy dependencies; only the standard library.

Public API
----------
Authority / policy sentinels::

    TAXONOMY_AUTHORITY
    TAXONOMY_PR8_SENTINEL
    BLOCKING_VS_ADVISORY_BOUNDARY_POLICY
    SKELETON_VS_FINAL_ACCEPTANCE_BOUNDARY_POLICY
    EVIDENCE_GAP_VS_DEFERRED_VS_UNRESOLVED_BOUNDARY_POLICY
    ACCEPTED_LIMITATION_MUST_NOT_SUPPRESS_BLOCKING_POLICY
    AUTOMATED_VERIFIED_REQUIRES_EXPLICIT_EVIDENCE_POLICY
    FAIL_CONSERVATIVE_UNKNOWN_IS_UNRESOLVED_POLICY

Enumerations::

    IssueClassification
    OperationalStatus

Data classes::

    TaxonomyEntry
    TerminologyRegistry

Functions::

    classify_issue(text) -> IssueClassification
    verdict_to_classification(verdict_str) -> IssueClassification
    operational_from_verdict(verdict_str) -> OperationalStatus
    is_blocking_classification(cls) -> bool
    get_terminology_registry() -> TerminologyRegistry
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger("Galaxy.ReleaseGovernanceTaxonomy")

__all__ = [
    # Sentinels
    "TAXONOMY_AUTHORITY",
    "TAXONOMY_PR8_SENTINEL",
    "BLOCKING_VS_ADVISORY_BOUNDARY_POLICY",
    "SKELETON_VS_FINAL_ACCEPTANCE_BOUNDARY_POLICY",
    "EVIDENCE_GAP_VS_DEFERRED_VS_UNRESOLVED_BOUNDARY_POLICY",
    "ACCEPTED_LIMITATION_MUST_NOT_SUPPRESS_BLOCKING_POLICY",
    "AUTOMATED_VERIFIED_REQUIRES_EXPLICIT_EVIDENCE_POLICY",
    "FAIL_CONSERVATIVE_UNKNOWN_IS_UNRESOLVED_POLICY",
    # Enumerations
    "IssueClassification",
    "OperationalStatus",
    # Data classes
    "TaxonomyEntry",
    "TerminologyRegistry",
    # Functions
    "classify_issue",
    "verdict_to_classification",
    "operational_from_verdict",
    "is_blocking_classification",
    "get_terminology_registry",
    "reset_terminology_registry",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

TAXONOMY_AUTHORITY: str = (
    "TAXONOMY_AUTHORITY::"
    "core.release_governance_taxonomy::PR8::"
    "unified-release-readiness-governance-final-acceptance-taxonomy::"
    "single-authoritative-semantic-boundary-definition"
)
"""Sentinel: this module is the canonical taxonomy authority for the V2
release / readiness / governance / final-acceptance surface.  Import this
sentinel to assert that downstream surfaces are aligned with the unified
taxonomy rather than maintaining ad-hoc term definitions."""

TAXONOMY_PR8_SENTINEL: str = (
    "TAXONOMY_PR8_SENTINEL::"
    "package=PR8::profile=release-governance-taxonomy-v1::"
    "module=core.release_governance_taxonomy"
)
"""Package sentinel for PR-8 unified taxonomy."""

BLOCKING_VS_ADVISORY_BOUNDARY_POLICY: str = (
    "POLICY::BLOCKING_VS_ADVISORY_BOUNDARY_V1: "
    "A condition is BLOCKING if and only if it MUST prevent a release, "
    "readiness upgrade, or acceptance conclusion from proceeding.  "
    "A condition is ADVISORY if it SHOULD be surfaced to operators but "
    "MUST NOT by itself prevent a release or readiness upgrade.  "
    "The distinction is binary and authoritative: a condition cannot be "
    "both blocking and advisory.  Callers MUST NOT treat an advisory "
    "condition as blocking without explicit escalation logic.  "
    "See: IssueClassification.blocking vs IssueClassification.advisory."
)
"""Policy: blocking and advisory are mutually exclusive and precisely defined."""

SKELETON_VS_FINAL_ACCEPTANCE_BOUNDARY_POLICY: str = (
    "POLICY::SKELETON_VS_FINAL_ACCEPTANCE_BOUNDARY_V1: "
    "A SKELETON / FOUNDATIONAL readiness verdict is non-enforcing: it "
    "structures evidence and signals *potential* blocking but does NOT "
    "itself constitute a final acceptance decision.  "
    "A FINAL ACCEPTANCE verdict is enforcing: it represents the "
    "authoritative system-level conclusion after all evidence has been "
    "evaluated.  A skeleton verdict of 'blocked' does NOT equal a final "
    "acceptance verdict of 'not_fully_operational'; the two surfaces "
    "have different evidence thresholds and enforcement semantics.  "
    "See: IssueClassification.skeleton_foundational vs the "
    "SystemAcceptanceVerdict hierarchy."
)
"""Policy: skeleton readiness and final acceptance are distinct surfaces."""

EVIDENCE_GAP_VS_DEFERRED_VS_UNRESOLVED_BOUNDARY_POLICY: str = (
    "POLICY::EVIDENCE_GAP_VS_DEFERRED_VS_UNRESOLVED_BOUNDARY_V1: "
    "EVIDENCE_GAP: evidence for a dimension exists but is incomplete or "
    "insufficient to meet acceptance criteria.  The gap is known and "
    "acknowledged; work is expected to close it.  "
    "DEFERRED: evaluation of a dimension has been explicitly postponed to "
    "a future PR or release cycle.  The dimension is out-of-scope for the "
    "current gate evaluation; it MUST NOT block the current release.  "
    "UNRESOLVED: the dimension signal is absent, the probe raised an "
    "exception, or the sub-system is unavailable.  Treated "
    "conservatively as a blocking gap until evidence is restored.  "
    "These three classifications MUST NOT be used interchangeably.  "
    "See: IssueClassification.evidence_gap / deferred / unresolved."
)
"""Policy: evidence_gap, deferred, and unresolved are semantically distinct."""

ACCEPTED_LIMITATION_MUST_NOT_SUPPRESS_BLOCKING_POLICY: str = (
    "POLICY::ACCEPTED_LIMITATION_MUST_NOT_SUPPRESS_BLOCKING_V1: "
    "An ACCEPTED_LIMITATION is a known constraint that stakeholders have "
    "explicitly acknowledged and agreed to live with.  It MUST NOT be "
    "used to suppress or reclassify a BLOCKING condition.  A blocking "
    "condition can only be downgraded to accepted_limitation after explicit "
    "stakeholder sign-off that is recorded in the audit trail.  "
    "Using accepted_limitation to silently hide blocking issues violates "
    "the fail-conservative principle.  "
    "See: IssueClassification.accepted_limitation."
)
"""Policy: accepted_limitation cannot suppress blocking conditions."""

AUTOMATED_VERIFIED_REQUIRES_EXPLICIT_EVIDENCE_POLICY: str = (
    "POLICY::AUTOMATED_VERIFIED_REQUIRES_EXPLICIT_EVIDENCE_V1: "
    "A dimension may only be marked AUTOMATED_VERIFIED if there is a "
    "concrete, reproducible automated test or CI artifact that "
    "demonstrates the required property.  Self-attestation, import "
    "checks alone, or absence of failure are insufficient for "
    "automated_verified status.  The automated evidence MUST be linked "
    "in the evidence_linkage of the report or checklist item.  "
    "See: IssueClassification.automated_verified."
)
"""Policy: automated_verified requires concrete, linked automated evidence."""

FAIL_CONSERVATIVE_UNKNOWN_IS_UNRESOLVED_POLICY: str = (
    "POLICY::FAIL_CONSERVATIVE_UNKNOWN_IS_UNRESOLVED_V1: "
    "When a classification cannot be determined (e.g. unrecognised "
    "verdict string, unavailable sub-system, missing evidence), the "
    "taxonomy MUST default to IssueClassification.unresolved rather "
    "than advisory or accepted.  This fail-conservative default prevents "
    "unknown states from being silently treated as non-blocking.  "
    "See: classify_issue() and verdict_to_classification()."
)
"""Policy: unknown/unrecognised states default to unresolved (fail-conservative)."""


# ---------------------------------------------------------------------------
# IssueClassification
# ---------------------------------------------------------------------------


class IssueClassification(str, Enum):
    """Canonical 9-value classification for any condition surfaced in a
    release / readiness / governance / final-acceptance gate or report.

    Values
    ------
    blocking
        The condition MUST prevent release, readiness upgrade, or
        acceptance conclusion from proceeding.  Corresponds to:
        ``CriterionStatus.FAILED`` (is_blocking=True) in
        ``release_blocking_gate``; ``ValidationOutcome.FAIL`` in
        ``governance_validation_gate``; ``DimensionStatus.unresolved``
        (when the unresolved dimension is critical) in
        ``system_final_acceptance_verdict``;
        ``GateCategoryStrength.gate_worthy`` + verdict ``blocked`` in
        ``distributed_release_gate_skeleton``.

    advisory
        The condition SHOULD be surfaced to operators but MUST NOT by
        itself prevent release or readiness upgrade.  Corresponds to:
        ``ValidationOutcome.WARN`` in ``governance_validation_gate``;
        ``GateCategoryStrength.advisory`` in
        ``distributed_release_gate_skeleton``.

    skeleton_foundational
        The condition is reported by a non-enforcing skeleton / readiness
        surface.  It signals *potential* future blocking but does not
        itself constitute a hard gate.  Corresponds to:
        ``GateCategoryStrength.gate_worthy`` + ``ReleaseGateVerdict.open``
        or ``deferred`` in ``distributed_release_gate_skeleton`` (before
        enforcement is activated by a later PR).

    unresolved
        The dimension signal is absent, the probe raised an exception, or
        the sub-system is unavailable.  Treated conservatively as
        blocking.  Corresponds to: ``DimensionStatus.unresolved`` in
        ``system_final_acceptance_verdict``;
        ``ReleaseGateVerdict.unknown`` in
        ``distributed_release_gate_skeleton``.

    evidence_gap
        Evidence for a dimension exists but is incomplete or insufficient
        to meet the acceptance bar.  The gap is known; work is expected
        to close it.  Maps to ``DimensionStatus.pending`` in
        ``system_final_acceptance_verdict`` when at least one gap
        description is non-empty.

    deferred
        Evaluation of a dimension has been explicitly postponed to a
        future PR or release cycle.  MUST NOT block the current release.
        Corresponds to: ``GateCategoryStrength.deferred`` in
        ``distributed_release_gate_skeleton``;
        ``ReleaseGateVerdict.deferred``.

    accepted_limitation
        A known constraint explicitly acknowledged by stakeholders.
        Cannot be used to downgrade a blocking condition without formal
        sign-off.  Not represented by a single existing enum value; this
        classification is used in audit/report surfaces only.

    automated_verified
        The condition has been positively verified by a reproducible
        automated test or CI artifact.  Corresponds to a ``PASSED``
        criterion with linked CI evidence; ``DimensionStatus.accepted``
        in ``system_final_acceptance_verdict`` when backed by automated
        tests.

    pass_no_issue
        No issue detected; the gate or dimension passed cleanly.
        Corresponds to: ``CriterionStatus.PASSED`` in
        ``release_blocking_gate``; ``ValidationOutcome.PASS``;
        ``DimensionStatus.accepted``; ``ReleaseGateVerdict.open``.
    """

    blocking = "blocking"
    advisory = "advisory"
    skeleton_foundational = "skeleton_foundational"
    unresolved = "unresolved"
    evidence_gap = "evidence_gap"
    deferred = "deferred"
    accepted_limitation = "accepted_limitation"
    automated_verified = "automated_verified"
    pass_no_issue = "pass_no_issue"

    @property
    def is_blocking(self) -> bool:
        """Return ``True`` when this classification represents a hard block.

        ``blocking`` and ``unresolved`` are the two hard-blocking
        classifications.  All others are non-blocking (advisory,
        deferred, evidence_gap, etc. do not prevent release by themselves).
        """
        return self in (
            IssueClassification.blocking,
            IssueClassification.unresolved,
        )

    @property
    def is_advisory_only(self) -> bool:
        """Return ``True`` when this classification is strictly advisory."""
        return self == IssueClassification.advisory

    @property
    def is_deferred(self) -> bool:
        """Return ``True`` when this classification is explicitly deferred."""
        return self == IssueClassification.deferred

    @property
    def is_positive(self) -> bool:
        """Return ``True`` for clearly positive outcomes (verified or pass)."""
        return self in (
            IssueClassification.automated_verified,
            IssueClassification.pass_no_issue,
        )


# ---------------------------------------------------------------------------
# OperationalStatus
# ---------------------------------------------------------------------------


class OperationalStatus(str, Enum):
    """Canonical 3-value operational status for a system, subsystem, or
    platform.  Used to translate gate verdicts into a single operational
    posture.

    Values
    ------
    fully_operational
        All required gates pass, all acceptance dimensions are accepted,
        and no blocking or unresolved conditions remain.

    partially_operational
        At least one dimension has an evidence_gap, advisory issue, or
        deferred evaluation, but no blocking or unresolved condition
        exists.  The system is running but not at full acceptance.

    not_ready
        At least one dimension is blocking or unresolved.  The system
        MUST NOT be treated as ready for production release or
        formal acceptance.
    """

    fully_operational = "fully_operational"
    partially_operational = "partially_operational"
    not_ready = "not_ready"

    @property
    def is_ready_for_release(self) -> bool:
        """Return ``True`` only when ``fully_operational``."""
        return self == OperationalStatus.fully_operational

    @property
    def blocks_release(self) -> bool:
        """Return ``True`` when the status prevents release."""
        return self == OperationalStatus.not_ready


# ---------------------------------------------------------------------------
# TaxonomyEntry
# ---------------------------------------------------------------------------


@dataclass
class TaxonomyEntry:
    """Definition record for a single taxonomy term.

    Fields
    ------
    term
        The canonical :class:`IssueClassification` value this entry
        describes.
    short_definition
        One-sentence definition of the term.
    is_blocking
        Whether this classification constitutes a hard release block.
    surface_examples
        List of (module_name, surface_constant_or_value) pairs showing
        how existing surfaces map to this term.
    must_not_confuse_with
        List of :class:`IssueClassification` values that are easily
        confused with this term but have distinct semantics.
    """

    term: IssueClassification
    short_definition: str
    is_blocking: bool
    surface_examples: List[Tuple[str, str]] = field(default_factory=list)
    must_not_confuse_with: List[IssueClassification] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "term": self.term.value,
            "short_definition": self.short_definition,
            "is_blocking": self.is_blocking,
            "surface_examples": self.surface_examples,
            "must_not_confuse_with": [c.value for c in self.must_not_confuse_with],
        }


# ---------------------------------------------------------------------------
# TerminologyRegistry
# ---------------------------------------------------------------------------


class TerminologyRegistry:
    """Formal lookup table for all taxonomy terms.

    Usage
    -----
    ::

        registry = get_terminology_registry()
        entry = registry.get(IssueClassification.blocking)
        print(entry.short_definition)

        # Check if a term is blocking
        assert registry.is_blocking(IssueClassification.advisory) is False
        assert registry.is_blocking(IssueClassification.blocking) is True

        # Get all blocking terms
        blocking_terms = registry.blocking_terms()
    """

    _entries: Dict[IssueClassification, TaxonomyEntry]

    def __init__(self) -> None:
        self._entries = _build_registry_entries()

    def get(self, term: IssueClassification) -> Optional[TaxonomyEntry]:
        """Return the :class:`TaxonomyEntry` for *term*, or ``None``."""
        return self._entries.get(term)

    def is_blocking(self, term: IssueClassification) -> bool:
        """Return ``True`` when *term* represents a hard release block."""
        entry = self._entries.get(term)
        return entry.is_blocking if entry is not None else True  # fail-conservative

    def blocking_terms(self) -> FrozenSet[IssueClassification]:
        """Return the set of all :class:`IssueClassification` values that
        are hard release blocks."""
        return frozenset(
            term for term, entry in self._entries.items() if entry.is_blocking
        )

    def advisory_only_terms(self) -> FrozenSet[IssueClassification]:
        """Return the set of all strictly advisory (non-blocking) terms."""
        return frozenset(
            term for term, entry in self._entries.items()
            if not entry.is_blocking and term == IssueClassification.advisory
        )

    def all_entries(self) -> List[TaxonomyEntry]:
        """Return all :class:`TaxonomyEntry` objects in canonical order."""
        return [self._entries[t] for t in IssueClassification if t in self._entries]

    def summary_lines(self) -> List[str]:
        """Return human-readable summary lines for all taxonomy terms."""
        lines = []
        for entry in self.all_entries():
            blocking_tag = "[BLOCKING]" if entry.is_blocking else "[advisory]"
            lines.append(
                f"  {blocking_tag:<12} {entry.term.value:<22} — "
                f"{entry.short_definition}"
            )
        return lines


def _build_registry_entries() -> Dict[IssueClassification, TaxonomyEntry]:
    """Build the canonical taxonomy entry table."""
    return {
        IssueClassification.blocking: TaxonomyEntry(
            term=IssueClassification.blocking,
            short_definition=(
                "A condition that MUST prevent release, readiness upgrade, or "
                "acceptance conclusion from proceeding.  Hard gate; non-negotiable."
            ),
            is_blocking=True,
            surface_examples=[
                ("release_blocking_gate", "CriterionStatus.FAILED + is_blocking=True"),
                ("governance_validation_gate", "ValidationOutcome.FAIL"),
                ("distributed_release_gate_skeleton",
                 "GateCategoryStrength.gate_worthy + ReleaseGateVerdict.blocked"),
                ("system_final_acceptance_verdict",
                 "DimensionStatus.unresolved (critical dimension)"),
            ],
            must_not_confuse_with=[
                IssueClassification.advisory,
                IssueClassification.evidence_gap,
            ],
        ),
        IssueClassification.advisory: TaxonomyEntry(
            term=IssueClassification.advisory,
            short_definition=(
                "A condition that SHOULD be surfaced to operators but MUST NOT "
                "by itself prevent release or readiness upgrade.  Observational."
            ),
            is_blocking=False,
            surface_examples=[
                ("governance_validation_gate",
                 "ValidationOutcome.WARN / CI_ADVISORY_DIMENSIONS"),
                ("distributed_release_gate_skeleton",
                 "GateCategoryStrength.advisory"),
                ("governance_validation_gate",
                 "ValidationFailReason.evidence_surface_unavailable"),
            ],
            must_not_confuse_with=[
                IssueClassification.blocking,
                IssueClassification.unresolved,
            ],
        ),
        IssueClassification.skeleton_foundational: TaxonomyEntry(
            term=IssueClassification.skeleton_foundational,
            short_definition=(
                "A condition reported by a non-enforcing skeleton or foundational "
                "readiness surface.  Signals potential future blocking but does "
                "not constitute a hard gate.  Enforcement is deferred."
            ),
            is_blocking=False,
            surface_examples=[
                ("distributed_release_gate_skeleton",
                 "GATE_SKELETON_IS_NON_ENFORCING_POLICY"),
                ("distributed_release_gate_skeleton",
                 "ReleaseGateVerdict.open (skeleton, not final acceptance)"),
            ],
            must_not_confuse_with=[
                IssueClassification.blocking,
                IssueClassification.pass_no_issue,
            ],
        ),
        IssueClassification.unresolved: TaxonomyEntry(
            term=IssueClassification.unresolved,
            short_definition=(
                "A dimension signal is absent, probe raised an exception, or "
                "the sub-system is unavailable.  Treated conservatively as "
                "a blocking gap until evidence is restored."
            ),
            is_blocking=True,
            surface_examples=[
                ("system_final_acceptance_verdict", "DimensionStatus.unresolved"),
                ("distributed_release_gate_skeleton", "ReleaseGateVerdict.unknown"),
                ("governance_validation_gate",
                 "ValidationFailReason.evidence_surface_unavailable"
                 " (strict_on_unavailable=True)"),
            ],
            must_not_confuse_with=[
                IssueClassification.evidence_gap,
                IssueClassification.deferred,
            ],
        ),
        IssueClassification.evidence_gap: TaxonomyEntry(
            term=IssueClassification.evidence_gap,
            short_definition=(
                "Evidence for a dimension exists but is incomplete or insufficient "
                "to meet the acceptance bar.  The gap is known and acknowledged; "
                "work is expected to close it."
            ),
            is_blocking=False,
            surface_examples=[
                ("system_final_acceptance_verdict",
                 "DimensionStatus.pending (with non-empty gap_description)"),
                ("distributed_release_gate_skeleton",
                 "GateCategoryEvaluation with partial evidence"),
            ],
            must_not_confuse_with=[
                IssueClassification.unresolved,
                IssueClassification.deferred,
            ],
        ),
        IssueClassification.deferred: TaxonomyEntry(
            term=IssueClassification.deferred,
            short_definition=(
                "Evaluation of a dimension has been explicitly postponed to a "
                "future PR or release cycle.  MUST NOT block the current release.  "
                "Out of scope for the current gate evaluation."
            ),
            is_blocking=False,
            surface_examples=[
                ("distributed_release_gate_skeleton",
                 "GateCategoryStrength.deferred"),
                ("distributed_release_gate_skeleton",
                 "ReleaseGateVerdict.deferred"),
                ("distributed_release_gate_skeleton",
                 "DEFERRED_CATEGORIES_MUST_NOT_BLOCK_RELEASE_POLICY"),
            ],
            must_not_confuse_with=[
                IssueClassification.unresolved,
                IssueClassification.evidence_gap,
            ],
        ),
        IssueClassification.accepted_limitation: TaxonomyEntry(
            term=IssueClassification.accepted_limitation,
            short_definition=(
                "A known constraint that stakeholders have explicitly acknowledged "
                "and agreed to live with.  Cannot be used to downgrade a blocking "
                "condition without formal sign-off recorded in the audit trail."
            ),
            is_blocking=False,
            surface_examples=[
                ("system_final_acceptance_verdict",
                 "unresolved_risk_summary with explicit stakeholder annotation"),
                ("governance_validation_gate",
                 "ValidationResult.details['accepted_limitation'] (by convention)"),
            ],
            must_not_confuse_with=[
                IssueClassification.blocking,
                IssueClassification.deferred,
            ],
        ),
        IssueClassification.automated_verified: TaxonomyEntry(
            term=IssueClassification.automated_verified,
            short_definition=(
                "The condition has been positively verified by a reproducible "
                "automated test or CI artifact.  Requires linked evidence in "
                "the report's evidence_linkage."
            ),
            is_blocking=False,
            surface_examples=[
                ("release_blocking_gate", "CriterionStatus.PASSED (with CI evidence)"),
                ("system_final_acceptance_verdict",
                 "DimensionStatus.accepted (backed by automated tests)"),
                ("governance_validation_gate", "ValidationOutcome.PASS"),
            ],
            must_not_confuse_with=[
                IssueClassification.pass_no_issue,
                IssueClassification.skeleton_foundational,
            ],
        ),
        IssueClassification.pass_no_issue: TaxonomyEntry(
            term=IssueClassification.pass_no_issue,
            short_definition=(
                "No issue detected; the gate or dimension passed cleanly.  "
                "Does not require linked automated evidence (unlike "
                "automated_verified)."
            ),
            is_blocking=False,
            surface_examples=[
                ("release_blocking_gate", "CriterionStatus.PASSED (general)"),
                ("governance_validation_gate", "ValidationOutcome.PASS"),
                ("distributed_release_gate_skeleton", "ReleaseGateVerdict.open"),
                ("system_final_acceptance_verdict", "DimensionStatus.accepted"),
            ],
            must_not_confuse_with=[
                IssueClassification.automated_verified,
                IssueClassification.skeleton_foundational,
            ],
        ),
    }


# ---------------------------------------------------------------------------
# Singleton registry
# ---------------------------------------------------------------------------

_registry_lock = __import__("threading").Lock()
_registry_instance: Optional[TerminologyRegistry] = None


def get_terminology_registry() -> TerminologyRegistry:
    """Return the shared :class:`TerminologyRegistry` singleton.

    Thread-safe; creates the registry on first call.
    """
    global _registry_instance
    if _registry_instance is None:
        with _registry_lock:
            if _registry_instance is None:
                _registry_instance = TerminologyRegistry()
    return _registry_instance


def reset_terminology_registry() -> None:
    """Reset the singleton registry.  **Testing only.**"""
    global _registry_instance
    with _registry_lock:
        _registry_instance = None


# ---------------------------------------------------------------------------
# Public helper functions
# ---------------------------------------------------------------------------

# Canonical verdict-string → IssueClassification mappings
# (covers all values used across existing gate surfaces)
_VERDICT_TO_CLASSIFICATION: Dict[str, IssueClassification] = {
    # release_blocking_gate / CriterionStatus
    "passed": IssueClassification.pass_no_issue,
    "failed": IssueClassification.blocking,
    "unknown": IssueClassification.unresolved,
    # governance_validation_gate / ValidationOutcome
    "pass": IssueClassification.pass_no_issue,
    "warn": IssueClassification.advisory,
    "fail": IssueClassification.blocking,
    # distributed_release_gate_skeleton / ReleaseGateVerdict
    "open": IssueClassification.pass_no_issue,
    "blocked": IssueClassification.blocking,
    "deferred": IssueClassification.deferred,
    # system_final_acceptance_verdict / DimensionStatus
    "accepted": IssueClassification.automated_verified,
    "pending": IssueClassification.evidence_gap,
    "unresolved": IssueClassification.unresolved,
    # system_final_acceptance_verdict / SystemAcceptanceVerdict
    "fully_operational": IssueClassification.pass_no_issue,
    "not_fully_operational_pending_dimensions": IssueClassification.evidence_gap,
    "not_fully_operational_critical_risk": IssueClassification.blocking,
    "acceptance_unknown_insufficient_evidence": IssueClassification.unresolved,
    # governance_validation_gate / ValidationFailReason
    "governance_blocked": IssueClassification.blocking,
    "readiness_blocked": IssueClassification.blocking,
    "delegated_readiness_not_ready": IssueClassification.blocking,
    "capability_tier_experimental": IssueClassification.advisory,
    "capability_tier_quasi_main_chain": IssueClassification.advisory,
    "evidence_surface_unavailable": IssueClassification.advisory,
    "none": IssueClassification.pass_no_issue,
    # GateCategoryStrength
    "gate_worthy": IssueClassification.blocking,  # when the verdict is blocked
    "advisory": IssueClassification.advisory,
    # explicit taxonomy terms
    "evidence_gap": IssueClassification.evidence_gap,
    "accepted_limitation": IssueClassification.accepted_limitation,
    "automated_verified": IssueClassification.automated_verified,
    "skeleton_foundational": IssueClassification.skeleton_foundational,
    "not_ready": IssueClassification.blocking,
    "partially_operational": IssueClassification.evidence_gap,
}

# Keyword fragments → IssueClassification (for free-text classify_issue)
_KEYWORD_PATTERNS: List[Tuple[str, IssueClassification]] = [
    ("blocking", IssueClassification.blocking),
    ("blocked", IssueClassification.blocking),
    ("not_ready", IssueClassification.blocking),
    ("not ready", IssueClassification.blocking),
    ("critical_risk", IssueClassification.blocking),
    ("critical risk", IssueClassification.blocking),
    ("unresolved", IssueClassification.unresolved),
    ("unavailable", IssueClassification.unresolved),
    ("missing signal", IssueClassification.unresolved),
    ("evidence_gap", IssueClassification.evidence_gap),
    ("evidence gap", IssueClassification.evidence_gap),
    ("pending", IssueClassification.evidence_gap),
    ("incomplete evidence", IssueClassification.evidence_gap),
    ("deferred", IssueClassification.deferred),
    ("out of scope", IssueClassification.deferred),
    ("advisory", IssueClassification.advisory),
    ("warn", IssueClassification.advisory),
    ("observational", IssueClassification.advisory),
    ("accepted_limitation", IssueClassification.accepted_limitation),
    ("accepted limitation", IssueClassification.accepted_limitation),
    ("accepted risk", IssueClassification.accepted_limitation),
    ("skeleton", IssueClassification.skeleton_foundational),
    ("foundational", IssueClassification.skeleton_foundational),
    ("non-enforcing", IssueClassification.skeleton_foundational),
    ("non enforcing", IssueClassification.skeleton_foundational),
    ("automated_verified", IssueClassification.automated_verified),
    ("automated verified", IssueClassification.automated_verified),
    ("ci artifact", IssueClassification.automated_verified),
    ("fully_operational", IssueClassification.pass_no_issue),
    ("fully operational", IssueClassification.pass_no_issue),
    ("passed", IssueClassification.pass_no_issue),
    ("open", IssueClassification.pass_no_issue),
    ("accepted", IssueClassification.automated_verified),
]


def classify_issue(text: str) -> IssueClassification:
    """Classify a free-text condition description using the unified taxonomy.

    Performs case-insensitive substring matching against canonical keyword
    patterns.  Returns :attr:`IssueClassification.unresolved` when no
    pattern matches (fail-conservative).

    Parameters
    ----------
    text
        Any human-readable condition description, verdict string, or
        gate output token.

    Returns
    -------
    IssueClassification
        The canonical classification.  Defaults to ``unresolved`` on no
        match (per FAIL_CONSERVATIVE_UNKNOWN_IS_UNRESOLVED_POLICY).
    """
    if not isinstance(text, str) or not text.strip():
        return IssueClassification.unresolved
    normalised = text.strip().lower()
    for fragment, classification in _KEYWORD_PATTERNS:
        if fragment in normalised:
            return classification
    return IssueClassification.unresolved


def verdict_to_classification(verdict_str: str) -> IssueClassification:
    """Map a verdict string from any existing gate surface to the canonical
    :class:`IssueClassification`.

    Covers all verdict tokens from:
    - ``CriterionStatus`` (release_blocking_gate)
    - ``ValidationOutcome`` / ``ValidationFailReason`` (governance_validation_gate)
    - ``ReleaseGateVerdict`` / ``GateCategoryStrength`` (distributed_release_gate_skeleton)
    - ``DimensionStatus`` / ``SystemAcceptanceVerdict`` (system_final_acceptance_verdict)

    Unknown tokens default to ``unresolved`` (fail-conservative).

    Parameters
    ----------
    verdict_str
        Raw verdict token string (case-insensitive).

    Returns
    -------
    IssueClassification
    """
    if not isinstance(verdict_str, str):
        return IssueClassification.unresolved
    normalised = verdict_str.strip().lower()
    return _VERDICT_TO_CLASSIFICATION.get(normalised, IssueClassification.unresolved)


def operational_from_verdict(verdict_str: str) -> OperationalStatus:
    """Map a verdict string to a canonical :class:`OperationalStatus`.

    Parameters
    ----------
    verdict_str
        Any verdict token from an existing gate surface.

    Returns
    -------
    OperationalStatus
        - ``fully_operational``  — when verdict is pass / open / fully_operational /
          accepted / automated_verified
        - ``not_ready``          — when verdict is blocking / blocked / unresolved /
          failed / not_fully_operational_critical_risk
        - ``partially_operational`` — when verdict is advisory / warn / deferred /
          pending / evidence_gap / not_fully_operational_pending_dimensions
    """
    cls = verdict_to_classification(verdict_str)
    if cls.is_blocking:
        return OperationalStatus.not_ready
    if cls.is_positive:
        return OperationalStatus.fully_operational
    # advisory, evidence_gap, deferred, accepted_limitation, skeleton_foundational
    return OperationalStatus.partially_operational


def is_blocking_classification(cls: IssueClassification) -> bool:
    """Return ``True`` when *cls* represents a hard release block.

    Equivalent to :attr:`IssueClassification.is_blocking` but available
    as a standalone function for callers that prefer the functional style.
    """
    return cls.is_blocking
