#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/distributed_release_gate_skeleton.py
==========================================
PR-7V2 (post-533 dual-repo runtime-unification master plan):
Canonical Distributed Release Gate Skeleton for Distributed Readiness Evidence.

Problem addressed
-----------------
The dual-repo system now has substantial readiness evidence distributed across
multiple V2 modules and surfaced through the PR-6V2 evidence aggregation
layer.  However, all these evidence sources are still reviewable only in
isolation — there is no single canonical gate skeleton that defines:

* what evidence **categories** exist across the distributed system,
* which categories are **gate-worthy** (may block release),
* which are **advisory / observation-only** (must not gate release),
* which are **intentionally deferred** to later release-policy PRs,
* how **Android-originated (companion-repo) evidence** is represented
  alongside V2-canonical evidence as distributed input to the gate, and
* what an eventual release/blocking decision will later be built from.

Without that skeleton, later release-gating or CI-enforcement work risks
being ad hoc, semantically inconsistent across repositories, and difficult to
review.

This module closes that gap by establishing the **Distributed Release Gate
Skeleton** — the minimal canonical meta-gate shape over the full set of
distributed readiness evidence dimensions surfaced by PR-6V2.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────────┐
    │  DISTRIBUTED RELEASE GATE SKELETON  (this module, PR-7V2)           │
    │                                                                      │
    │  Consumes (read-only):                                               │
    │    V2ReadinessGovernanceEvidenceSurface (PR-6V2)                     │
    │      ├── delegated_flow_readiness      → category: runtime_lifecycle │
    │      ├── delegated_flow_acceptance     → category: governance_accept │
    │      ├── post_graduation_governance    → category: runtime_lifecycle │
    │      ├── android_evaluator_artifacts   → category: android_companion │
    │      ├── takeover_tracking             → category: takeover_delegation│
    │      ├── android_delegated_audit       → category: takeover_delegation│
    │      ├── continuity_recovery_closure   → category: continuity_recovery│
    │      ├── compat_legacy_blocking        → category: authoritative_path │
    │      └── participant_session_truth     → category: participant_truth  │
    │                                                                      │
    │  Defines:                                                            │
    │    • DistributedReadinessCategory  — 7 evidence category enums      │
    │    • EvidenceStrength              — gate_worthy / advisory / deferred│
    │    • CategoryEvidenceResult        — per-category structured result  │
    │    • DistributedReleaseGateReport  — full skeleton gate report       │
    │    • DistributedReleaseGateSkeleton— evaluator class                 │
    │                                                                      │
    │  Skeleton gate verdict:                                              │
    │    • all_gate_worthy_present       — all gate-worthy categories OK   │
    │    • overall_skeleton_status       — summary status string           │
    │    • deferred_policy_notes         — what is not yet enforced        │
    └──────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified.
2. **Projection-only** — the skeleton consumes existing evidence surfaces
   read-only; it never mutates canonical state or sub-system registries.
3. **Fail-graceful** — when the evidence surface or any category probe is
   unavailable the report records ``category_status="unavailable"`` and the
   skeleton still returns a complete report.
4. **Explicit strength semantics** — every category carries a declared
   :class:`EvidenceStrength` so downstream CI tools can distinguish
   gate-worthy from advisory from deferred without consulting the code.
5. **Android evidence as distributed input** — Android-originated evidence
   is represented as a named category (``android_companion_readiness``) with
   an explicit ``companion_repo`` authority note.  V2 remains the canonical
   classification authority.
6. **Deferred-explicit** — dimensions not yet policy-enforced are listed in
   ``deferred_policy_notes``; CI tooling can skip them by name without
   guessing.
7. **Stable artifacts** — :class:`DistributedReleaseGateReport` is fully
   JSON-serialisable (``to_dict`` / ``to_json``) so it can be persisted,
   diffed, and included as a release artefact.
8. **Extensible** — later PRs can tighten policy by changing a category's
   ``strength`` from ``deferred`` → ``advisory`` → ``gate_worthy`` without
   redefining the semantic model from scratch.

Public API
----------
Authority / policy sentinels::

    DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY
    DISTRIBUTED_RELEASE_GATE_SKELETON_PR7V2_SENTINEL
    GATE_WORTHY_CATEGORIES_MAY_BLOCK_RELEASE_POLICY
    ADVISORY_CATEGORIES_MUST_NOT_BLOCK_RELEASE_POLICY
    ANDROID_COMPANION_EVIDENCE_IS_DISTRIBUTED_INPUT_POLICY
    DEFERRED_CATEGORIES_REQUIRE_EXPLICIT_POLICY_PR_POLICY
    SKELETON_IS_PROJECTION_ONLY_POLICY

Enumerations::

    DistributedReadinessCategory
    EvidenceStrength
    CategoryStatus

Data classes::

    CategoryEvidenceResult
    DistributedReleaseGateReport

Helpers::

    evaluate_distributed_release_gate() -> DistributedReleaseGateReport
    get_distributed_release_gate_report() -> DistributedReleaseGateReport  (singleton)
    reset_distributed_release_gate_report() -> None                        (testing only)
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DistributedReleaseGateSkeleton")

__all__ = [
    # Authority / policy sentinels
    "DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY",
    "DISTRIBUTED_RELEASE_GATE_SKELETON_PR7V2_SENTINEL",
    "GATE_WORTHY_CATEGORIES_MAY_BLOCK_RELEASE_POLICY",
    "ADVISORY_CATEGORIES_MUST_NOT_BLOCK_RELEASE_POLICY",
    "ANDROID_COMPANION_EVIDENCE_IS_DISTRIBUTED_INPUT_POLICY",
    "DEFERRED_CATEGORIES_REQUIRE_EXPLICIT_POLICY_PR_POLICY",
    "SKELETON_IS_PROJECTION_ONLY_POLICY",
    # Enumerations
    "DistributedReadinessCategory",
    "EvidenceStrength",
    "CategoryStatus",
    # Data classes
    "CategoryEvidenceResult",
    "DistributedReleaseGateReport",
    # Evaluator class
    "DistributedReleaseGateSkeleton",
    # Helpers
    "evaluate_distributed_release_gate",
    "get_distributed_release_gate_report",
    "reset_distributed_release_gate_report",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY: str = (
    "DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY::"
    "core.distributed_release_gate_skeleton::PR7V2::"
    "canonical-distributed-release-gate-skeleton::"
    "evidence-category-meta-gate"
)
"""Sentinel: this module is the canonical V2 distributed release gate skeleton.
Import this sentinel to assert that a release pipeline, CI hook, or reviewer
tool is consulting the correct canonical meta-gate rather than an individual
sub-system gate or ad hoc evidence check."""

DISTRIBUTED_RELEASE_GATE_SKELETON_PR7V2_SENTINEL: str = (
    "DISTRIBUTED_RELEASE_GATE_SKELETON_PR7V2_SENTINEL::"
    "package=PR7V2::profile=distributed-release-gate-skeleton-v1::"
    "module=core.distributed_release_gate_skeleton"
)
"""Package sentinel for PR-7V2."""

GATE_WORTHY_CATEGORIES_MAY_BLOCK_RELEASE_POLICY: str = (
    "POLICY::GATE_WORTHY_CATEGORIES_MAY_BLOCK_RELEASE_V1: "
    "Evidence categories with strength='gate_worthy' are eligible to block "
    "release when their category_status is not 'present'.  These categories "
    "are backed by canonical V2 gate modules or by companion-repo evidence "
    "that has been formally ingested and classified by V2.  A future "
    "enforcement PR may assert all_gate_worthy_present=True as a CI gate."
)
"""Policy: gate_worthy categories are the release-blocking candidates."""

ADVISORY_CATEGORIES_MUST_NOT_BLOCK_RELEASE_POLICY: str = (
    "POLICY::ADVISORY_CATEGORIES_MUST_NOT_BLOCK_RELEASE_V1: "
    "Evidence categories with strength='advisory' are observational only. "
    "They provide debugging context and operator visibility but MUST NOT be "
    "used to block release or to substitute for gate-worthy evidence.  "
    "Advisory categories include raw audit records and local-only signals."
)
"""Policy: advisory categories must not gate release."""

ANDROID_COMPANION_EVIDENCE_IS_DISTRIBUTED_INPUT_POLICY: str = (
    "POLICY::ANDROID_COMPANION_EVIDENCE_IS_DISTRIBUTED_INPUT_V1: "
    "Android-originated readiness evidence (companion-repo) is represented "
    "as a named category 'android_companion_readiness' in this skeleton.  "
    "V2 is the canonical classification authority: Android evidence is "
    "ingested via AndroidEvaluatorArtifactIngress, classified, and "
    "promoted to canonical gate input through FlowTruthAlignmentRuntime.  "
    "The companion-repo category feeds the gate_worthy 'runtime_lifecycle' "
    "category via the truth_ownership dimension.  Android-side evidence "
    "classification is V2's authority, not Android's."
)
"""Policy: Android companion evidence is a named distributed input to the gate."""

DEFERRED_CATEGORIES_REQUIRE_EXPLICIT_POLICY_PR_POLICY: str = (
    "POLICY::DEFERRED_CATEGORIES_REQUIRE_EXPLICIT_POLICY_PR_V1: "
    "Evidence categories with strength='deferred' represent dimensions whose "
    "release-blocking policy has not yet been formally decided.  Each deferred "
    "category MUST carry an explicit deferral note in the report.  A later PR "
    "that promotes a category from 'deferred' to 'gate_worthy' MUST update "
    "this module and reference the policy PR.  Deferred categories must never "
    "silently become gate blockers without an explicit policy change."
)
"""Policy: deferred categories require an explicit policy PR to become gate-worthy."""

SKELETON_IS_PROJECTION_ONLY_POLICY: str = (
    "POLICY::SKELETON_IS_PROJECTION_ONLY_V1: "
    "DistributedReleaseGateSkeleton.evaluate() reads from "
    "V2ReadinessGovernanceEvidenceSurface (PR-6V2) and from the individual "
    "gate modules it references.  It MUST NOT mutate canonical state, "
    "sub-system registries, or the evidence surface.  It is a read-only, "
    "additive meta-gate projection."
)
"""Policy: the skeleton is a read-only projection."""


# ---------------------------------------------------------------------------
# DistributedReadinessCategory
# ---------------------------------------------------------------------------


class DistributedReadinessCategory(str, Enum):
    """The seven distributed readiness evidence categories in the gate skeleton.

    Each category groups one or more evidence dimensions from the PR-6V2
    evidence surface.  Categories are the unit of policy assignment; their
    :class:`EvidenceStrength` determines whether they may gate release.

    Values
    ------
    runtime_lifecycle
        Canonical runtime lifecycle and delegated-flow readiness correctness.
        Maps to: ``delegated_flow_readiness`` (PR-9V2),
        ``post_graduation_governance`` (PR-11V2).

    takeover_delegation
        Takeover request/response execution and audit trail correctness.
        Maps to: ``takeover_tracking``,
        ``android_delegated_audit`` (advisory sub-dimension).

    participant_truth
        Participant session truth and reconciliation state visibility.
        Maps to: ``participant_session_truth``.

    android_companion_readiness
        Android-originated readiness and evaluator artifact evidence,
        transported to V2 and classified by V2.
        Maps to: ``android_evaluator_artifacts`` (companion_repo dimension).

    continuity_recovery
        Continuity, recovery, and offline durability safety.
        Maps to: ``continuity_recovery_closure`` (PR-5V2).

    authoritative_path_convergence
        Authoritative-path convergence and compat/legacy path blocking.
        Maps to: ``compat_legacy_blocking`` (PR-8V2).

    governance_acceptance
        Governance, acceptance, and graduation evidence.
        Maps to: ``delegated_flow_acceptance`` (PR-10V2).
    """

    runtime_lifecycle = "runtime_lifecycle"
    takeover_delegation = "takeover_delegation"
    participant_truth = "participant_truth"
    android_companion_readiness = "android_companion_readiness"
    continuity_recovery = "continuity_recovery"
    authoritative_path_convergence = "authoritative_path_convergence"
    governance_acceptance = "governance_acceptance"


# ---------------------------------------------------------------------------
# EvidenceStrength
# ---------------------------------------------------------------------------


class EvidenceStrength(str, Enum):
    """Declared release-gate strength for an evidence category.

    Values
    ------
    gate_worthy
        The category is backed by canonical V2 gate modules (or by formally
        ingested companion-repo evidence) and is **eligible to block release**
        in a future enforcement PR.  A category with this strength appearing
        as ``category_status != 'present'`` signals that the release gate
        should not pass.

    advisory
        The category provides observational / debugging context only.  It
        **MUST NOT block release** regardless of its status.  Advisory
        categories are included in the report for operator visibility.

    deferred
        The release-blocking policy for this category has not yet been
        formally decided.  The category is included in the skeleton for
        structural completeness but will not influence the gate verdict until
        a later policy PR promotes it to ``gate_worthy``.
    """

    gate_worthy = "gate_worthy"
    advisory = "advisory"
    deferred = "deferred"


# ---------------------------------------------------------------------------
# CategoryStatus
# ---------------------------------------------------------------------------


class CategoryStatus(str, Enum):
    """Aggregated status for an evidence category.

    Values
    ------
    present
        All contributing evidence dimensions for this category report status
        ``present`` (or better).

    partial
        Some but not all contributing dimensions are ``present``; at least
        one reports ``absent`` or ``unavailable``.

    absent
        All contributing dimensions report ``absent``.

    unavailable
        The contributing evidence modules could not be reached (import error
        or runtime unavailability); the category status cannot be determined.

    deferred
        The category is intentionally deferred; no evaluation is performed.
    """

    present = "present"
    partial = "partial"
    absent = "absent"
    unavailable = "unavailable"
    deferred = "deferred"


# ---------------------------------------------------------------------------
# CategoryEvidenceResult
# ---------------------------------------------------------------------------

# Evidence dimension IDs contributed by each category (for mapping).
_CATEGORY_DIMENSION_MAP: Dict[str, List[str]] = {
    DistributedReadinessCategory.runtime_lifecycle.value: [
        "delegated_flow_readiness",
        "post_graduation_governance",
    ],
    DistributedReadinessCategory.takeover_delegation.value: [
        "takeover_tracking",
        "android_delegated_audit",
    ],
    DistributedReadinessCategory.participant_truth.value: [
        "participant_session_truth",
    ],
    DistributedReadinessCategory.android_companion_readiness.value: [
        "android_evaluator_artifacts",
    ],
    DistributedReadinessCategory.continuity_recovery.value: [
        "continuity_recovery_closure",
    ],
    DistributedReadinessCategory.authoritative_path_convergence.value: [
        "compat_legacy_blocking",
    ],
    DistributedReadinessCategory.governance_acceptance.value: [
        "delegated_flow_acceptance",
    ],
}

# Strength declarations for each category.
_CATEGORY_STRENGTH_MAP: Dict[str, str] = {
    DistributedReadinessCategory.runtime_lifecycle.value: EvidenceStrength.gate_worthy.value,
    DistributedReadinessCategory.takeover_delegation.value: EvidenceStrength.gate_worthy.value,
    DistributedReadinessCategory.participant_truth.value: EvidenceStrength.advisory.value,
    DistributedReadinessCategory.android_companion_readiness.value: EvidenceStrength.gate_worthy.value,
    DistributedReadinessCategory.continuity_recovery.value: EvidenceStrength.gate_worthy.value,
    DistributedReadinessCategory.authoritative_path_convergence.value: EvidenceStrength.gate_worthy.value,
    DistributedReadinessCategory.governance_acceptance.value: EvidenceStrength.gate_worthy.value,
}

# Authority notes for companion-repo categories.
_CATEGORY_AUTHORITY_NOTE: Dict[str, str] = {
    DistributedReadinessCategory.android_companion_readiness.value: (
        "Evidence originates in DannyFish-11/ufo-galaxy-android; "
        "transported to V2 via AndroidEvaluatorArtifactIngress and "
        "classified by V2 per COMPANION_REPO_EVIDENCE_IS_CLASSIFIED_BY_V2_POLICY."
    ),
}

# Deferral notes for deferred categories (future extensibility).
_CATEGORY_DEFERRAL_NOTE: Dict[str, str] = {
    # No categories are deferred in the initial skeleton; this mapping exists
    # so later PRs can add deferred categories by inserting an entry here.
}


@dataclass
class CategoryEvidenceResult:
    """One row in the distributed release gate report — per-category result.

    Fields
    ------
    category
        :class:`DistributedReadinessCategory` value string.
    strength
        :class:`EvidenceStrength` value string.
    category_status
        :class:`CategoryStatus` value string — aggregated from contributing
        evidence dimensions.
    contributing_dimension_ids
        List of evidence dimension IDs from the PR-6V2 surface that feed
        this category.
    contributing_dimension_statuses
        Mapping from dimension_id → evidence_status string, as reported by
        the PR-6V2 evidence surface.
    summary
        Human-readable summary of the category's evidence state.
    authority_note
        Optional note describing the authority model for this category
        (e.g. companion-repo provenance).
    deferral_note
        Non-empty when ``strength == 'deferred'``: explains what is deferred
        and which future PR should address it.
    """

    category: str
    strength: str
    category_status: str
    contributing_dimension_ids: List[str] = field(default_factory=list)
    contributing_dimension_statuses: Dict[str, str] = field(default_factory=dict)
    summary: str = ""
    authority_note: str = ""
    deferral_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "category": self.category,
            "strength": self.strength,
            "category_status": self.category_status,
            "contributing_dimension_ids": list(self.contributing_dimension_ids),
            "contributing_dimension_statuses": dict(self.contributing_dimension_statuses),
            "summary": self.summary,
            "authority_note": self.authority_note,
            "deferral_note": self.deferral_note,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CategoryEvidenceResult":
        """Reconstruct from a ``to_dict()`` output (round-trip)."""
        return cls(
            category=data.get("category", ""),
            strength=data.get("strength", ""),
            category_status=data.get("category_status", ""),
            contributing_dimension_ids=list(data.get("contributing_dimension_ids", [])),
            contributing_dimension_statuses=dict(
                data.get("contributing_dimension_statuses", {})
            ),
            summary=data.get("summary", ""),
            authority_note=data.get("authority_note", ""),
            deferral_note=data.get("deferral_note", ""),
        )


# ---------------------------------------------------------------------------
# DistributedReleaseGateReport
# ---------------------------------------------------------------------------


@dataclass
class DistributedReleaseGateReport:
    """Full report produced by :class:`DistributedReleaseGateSkeleton`.

    Fields
    ------
    report_id
        Unique UUID for this report instance; stable within a single
        ``evaluate_distributed_release_gate()`` call.
    generated_at
        Unix timestamp (float) when the report was produced.
    authority
        Copy of :data:`DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY`.
    categories
        Ordered list of :class:`CategoryEvidenceResult` — one per
        :class:`DistributedReadinessCategory`.
    gate_worthy_count
        Number of categories with ``strength='gate_worthy'``.
    advisory_count
        Number of categories with ``strength='advisory'``.
    deferred_count
        Number of categories with ``strength='deferred'``.
    gate_worthy_present_count
        Number of gate-worthy categories whose ``category_status='present'``.
    all_gate_worthy_present
        True when every gate-worthy category reports ``category_status='present'``.
        This is the primary signal a future enforcement PR can assert as a CI gate.
    overall_skeleton_status
        High-level status string:
        ``"all_gate_worthy_present"`` — all gate-worthy categories OK,
        ``"gate_worthy_gap"``         — at least one gate-worthy category not present,
        ``"advisory_only_gaps"``      — only advisory/deferred gaps remain,
        ``"unknown"``                 — skeleton could not evaluate.
    deferred_policy_notes
        Explicit list of what is not yet enforced.  CI tooling must not
        treat these as blocking until a policy PR removes them.
    evidence_surface_available
        Whether the PR-6V2 evidence surface was successfully loaded.
    """

    report_id: str
    generated_at: float
    authority: str
    categories: List[CategoryEvidenceResult] = field(default_factory=list)
    gate_worthy_count: int = 0
    advisory_count: int = 0
    deferred_count: int = 0
    gate_worthy_present_count: int = 0
    all_gate_worthy_present: bool = False
    overall_skeleton_status: str = "unknown"
    deferred_policy_notes: List[str] = field(default_factory=list)
    evidence_surface_available: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "authority": self.authority,
            "categories": [c.to_dict() for c in self.categories],
            "gate_worthy_count": self.gate_worthy_count,
            "advisory_count": self.advisory_count,
            "deferred_count": self.deferred_count,
            "gate_worthy_present_count": self.gate_worthy_present_count,
            "all_gate_worthy_present": self.all_gate_worthy_present,
            "overall_skeleton_status": self.overall_skeleton_status,
            "deferred_policy_notes": list(self.deferred_policy_notes),
            "evidence_surface_available": self.evidence_surface_available,
        }

    def to_json(self, indent: int = 2) -> str:
        """Return a pretty-printed JSON string representation."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DistributedReleaseGateReport":
        """Reconstruct from a ``to_dict()`` output (round-trip)."""
        cats = [
            CategoryEvidenceResult.from_dict(c)
            for c in data.get("categories", [])
        ]
        return cls(
            report_id=data.get("report_id", ""),
            generated_at=float(data.get("generated_at", 0.0)),
            authority=data.get("authority", ""),
            categories=cats,
            gate_worthy_count=int(data.get("gate_worthy_count", 0)),
            advisory_count=int(data.get("advisory_count", 0)),
            deferred_count=int(data.get("deferred_count", 0)),
            gate_worthy_present_count=int(data.get("gate_worthy_present_count", 0)),
            all_gate_worthy_present=bool(data.get("all_gate_worthy_present", False)),
            overall_skeleton_status=data.get("overall_skeleton_status", "unknown"),
            deferred_policy_notes=list(data.get("deferred_policy_notes", [])),
            evidence_surface_available=bool(
                data.get("evidence_surface_available", False)
            ),
        )


# ---------------------------------------------------------------------------
# Deferred policy notes (canonical list for PR-7V2)
# ---------------------------------------------------------------------------

_DEFERRED_POLICY_NOTES: List[str] = [
    (
        "DEFERRED: Final CI enforcement (blocking PR merges when gate-worthy "
        "categories are not present) is deferred to a later enforcement PR.  "
        "This skeleton provides the evidence-category structure that future "
        "CI gates can build on without ad hoc evidence interpretation."
    ),
    (
        "DEFERRED: Default-on release policy (automatically promoting the "
        "delegated canonical path to default when all_gate_worthy_present=True) "
        "is deferred; the acceptance and governance gates provide the evidence "
        "foundation for that decision."
    ),
    (
        "DEFERRED: participant_truth category strength is 'advisory' in this "
        "skeleton.  A later PR may promote it to 'gate_worthy' once the "
        "participant session state feeds a formal gate module rather than "
        "remaining an observational registry."
    ),
    (
        "DEFERRED: Android offline queue ordering authority is deferred "
        "(see RecoveryClosureReport RS-16).  Until that is resolved the "
        "android_companion_readiness category relies on evaluator-artifact "
        "ingestion evidence only."
    ),
]


# ---------------------------------------------------------------------------
# DistributedReleaseGateSkeleton
# ---------------------------------------------------------------------------


class DistributedReleaseGateSkeleton:
    """Canonical distributed release gate skeleton evaluator.

    Consumes the PR-6V2 evidence surface and maps its dimensions into the
    seven :class:`DistributedReadinessCategory` buckets.  Produces a
    :class:`DistributedReleaseGateReport` with per-category strength and
    status annotations.

    This class is a stateless evaluator; create a new instance or use the
    module-level :func:`evaluate_distributed_release_gate` helper.
    """

    def evaluate(self) -> DistributedReleaseGateReport:
        """Run the skeleton evaluation and return a :class:`DistributedReleaseGateReport`."""
        dimension_status_map: Dict[str, str] = {}
        surface_available = False

        # ------------------------------------------------------------------
        # Step 1: Load the PR-6V2 evidence surface (fail-graceful)
        # ------------------------------------------------------------------
        try:
            from core.v2_readiness_governance_evidence_surface import (
                build_evidence_surface_report,
            )

            surface_report = build_evidence_surface_report()
            surface_available = True
            for entry in surface_report.dimensions:
                dimension_status_map[entry.dimension_id] = entry.evidence_status
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DistributedReleaseGateSkeleton: PR-6V2 evidence surface "
                "unavailable: %s",
                exc,
            )

        # ------------------------------------------------------------------
        # Step 2: Build per-category results
        # ------------------------------------------------------------------
        category_results: List[CategoryEvidenceResult] = []
        for cat_enum in DistributedReadinessCategory:
            cat_id = cat_enum.value
            strength = _CATEGORY_STRENGTH_MAP.get(cat_id, EvidenceStrength.advisory.value)
            contributing_ids = _CATEGORY_DIMENSION_MAP.get(cat_id, [])
            authority_note = _CATEGORY_AUTHORITY_NOTE.get(cat_id, "")
            deferral_note = _CATEGORY_DEFERRAL_NOTE.get(cat_id, "")

            if strength == EvidenceStrength.deferred.value:
                cat_status = CategoryStatus.deferred.value
                summary = f"Category {cat_id!r} is intentionally deferred: {deferral_note}"
            elif not surface_available:
                cat_status = CategoryStatus.unavailable.value
                summary = (
                    f"Category {cat_id!r}: evidence surface unavailable; "
                    "cannot assess contributing dimensions."
                )
                deferral_note = ""
            else:
                dim_statuses: Dict[str, str] = {
                    dim_id: dimension_status_map.get(dim_id, "unavailable")
                    for dim_id in contributing_ids
                }
                cat_status = _aggregate_category_status(
                    strength=strength,
                    dim_statuses=dim_statuses,
                )
                summary = _build_category_summary(cat_id, strength, cat_status, dim_statuses)

            category_results.append(
                CategoryEvidenceResult(
                    category=cat_id,
                    strength=strength,
                    category_status=cat_status,
                    contributing_dimension_ids=list(contributing_ids),
                    contributing_dimension_statuses={
                        dim_id: dimension_status_map.get(dim_id, "unavailable")
                        for dim_id in contributing_ids
                    } if surface_available else {},
                    summary=summary,
                    authority_note=authority_note,
                    deferral_note=deferral_note,
                )
            )

        # ------------------------------------------------------------------
        # Step 3: Compute aggregate gate metrics
        # ------------------------------------------------------------------
        gate_worthy_cats = [
            r for r in category_results if r.strength == EvidenceStrength.gate_worthy.value
        ]
        advisory_cats = [
            r for r in category_results if r.strength == EvidenceStrength.advisory.value
        ]
        deferred_cats = [
            r for r in category_results if r.strength == EvidenceStrength.deferred.value
        ]
        gate_worthy_present = [
            r for r in gate_worthy_cats if r.category_status == CategoryStatus.present.value
        ]
        all_gate_worthy_present = (
            len(gate_worthy_present) == len(gate_worthy_cats) and bool(gate_worthy_cats)
        )

        if not surface_available:
            overall_status = "unknown"
        elif all_gate_worthy_present:
            overall_status = "all_gate_worthy_present"
        elif any(
            r.category_status not in (
                CategoryStatus.present.value, CategoryStatus.deferred.value
            )
            for r in gate_worthy_cats
        ):
            overall_status = "gate_worthy_gap"
        else:
            overall_status = "advisory_only_gaps"

        return DistributedReleaseGateReport(
            report_id=str(uuid.uuid4()),
            generated_at=time.time(),
            authority=DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY,
            categories=category_results,
            gate_worthy_count=len(gate_worthy_cats),
            advisory_count=len(advisory_cats),
            deferred_count=len(deferred_cats),
            gate_worthy_present_count=len(gate_worthy_present),
            all_gate_worthy_present=all_gate_worthy_present,
            overall_skeleton_status=overall_status,
            deferred_policy_notes=list(_DEFERRED_POLICY_NOTES),
            evidence_surface_available=surface_available,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _aggregate_category_status(
    strength: str,
    dim_statuses: Dict[str, str],
) -> str:
    """Derive a :class:`CategoryStatus` string from contributing dimension statuses."""
    if not dim_statuses:
        return CategoryStatus.unavailable.value

    statuses = list(dim_statuses.values())
    present_count = sum(1 for s in statuses if s == "present")
    absent_count = sum(1 for s in statuses if s == "absent")
    unavailable_count = sum(1 for s in statuses if s in ("unavailable", "unknown"))
    total = len(statuses)

    if present_count == total:
        return CategoryStatus.present.value
    if absent_count == total:
        return CategoryStatus.absent.value
    if unavailable_count == total:
        return CategoryStatus.unavailable.value
    # Mixed
    return CategoryStatus.partial.value


def _build_category_summary(
    cat_id: str,
    strength: str,
    cat_status: str,
    dim_statuses: Dict[str, str],
) -> str:
    """Build a human-readable summary string for a category result."""
    dim_list = ", ".join(
        f"{k}={v}" for k, v in dim_statuses.items()
    )
    return (
        f"Category {cat_id!r} [{strength}]: status={cat_status}; "
        f"dimensions=[{dim_list}]"
    )


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

_GATE_LOCK = threading.Lock()
_cached_gate_report: Optional[DistributedReleaseGateReport] = None


def evaluate_distributed_release_gate() -> DistributedReleaseGateReport:
    """Evaluate and return a fresh :class:`DistributedReleaseGateReport` (not cached).

    Every call runs all category evaluations against the current live evidence
    surface state.
    """
    return DistributedReleaseGateSkeleton().evaluate()


def get_distributed_release_gate_report() -> DistributedReleaseGateReport:
    """Return a cached :class:`DistributedReleaseGateReport`, building if needed.

    The cache is invalidated by :func:`reset_distributed_release_gate_report`.
    Use :func:`evaluate_distributed_release_gate` when a fresh snapshot is
    required (e.g. in CI).
    """
    global _cached_gate_report
    with _GATE_LOCK:
        if _cached_gate_report is None:
            _cached_gate_report = DistributedReleaseGateSkeleton().evaluate()
        return _cached_gate_report


def reset_distributed_release_gate_report() -> None:
    """Invalidate the cached report.  Intended for test isolation only."""
    global _cached_gate_report
    with _GATE_LOCK:
        _cached_gate_report = None
