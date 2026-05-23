#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/distributed_release_gate_skeleton.py
==========================================
PR-7V2 (post-535 dual-repo runtime-unification master plan):
Canonical Distributed Release Gate Skeleton for Distributed Readiness Evidence.

Problem addressed
-----------------
The V2 repository now exposes a rich evidence surface (PR-6V2-EVIDENCE) with
canonical, advisory, and companion-repo (Android-originated) readiness evidence
across multiple gate dimensions.  However, those evidence categories still exist
only as an *aggregation surface* — there is no single canonical structure that
answers:

* What evidence **categories** does the distributed release gate define?
* Which categories are **gate-worthy** (may block release)?
* Which categories are **advisory** (observational only)?
* Which categories are **deferred** (not yet enforced; reserved for later PRs)?
* How is **Android companion evidence** represented as distributed input to the
  V2 canonical gate?
* What does the eventual **gate decision** shape look like before final policy
  is enforced?

This module introduces the minimal, safe V2-side **release gate skeleton** that:

1. Defines canonical evidence **categories** with explicit strength labels.
2. Evaluates each category from the PR-6 evidence surface (read-only).
3. Produces a stable, JSON-serialisable :class:`ReleaseGateReport` that
   reviewers, later PRs, and CI tooling can consume and extend.
4. Does NOT enforce hard blocking — it records a *skeleton verdict* that later
   PRs can promote to actual CI enforcement without redefining semantics.
5. Makes the distinction between gate-worthy, advisory, and deferred dimensions
   explicit at the **type level** via :class:`GateCategoryStrength`.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  DISTRIBUTED RELEASE GATE SKELETON  (this module — PR-7V2)         │
    │                                                                     │
    │  Consumes (read-only):                                              │
    │    • V2ReadinessGovernanceEvidenceSurface  (PR-6V2-EVIDENCE)        │
    │      └─ EvidenceSurfaceReport with classified dimension entries     │
    │                                                                     │
    │  Defines:                                                           │
    │    • GateCategoryStrength   (gate_worthy / advisory / deferred)     │
    │    • GateCategory           (one per evidence category)             │
    │    • GateCategoryEvaluation (per-category result + evidence link)   │
    │    • ReleaseGateVerdict     (open / blocked / deferred / unknown)   │
    │    • ReleaseGateReport      (full serialisable skeleton report)     │
    │                                                                     │
    │  Produces:                                                          │
    │    • evaluate_distributed_release_gate() → ReleaseGateReport       │
    │    • get_release_gate_report()           → ReleaseGateReport (cache)│
    │    • reset_release_gate_report()         → None (testing only)     │
    │                                                                     │
    │  Android companion evidence path:                                   │
    │    • Android evaluator artifacts → AndroidEvaluatorArtifactIngress │
    │      → FlowTruthAlignmentRuntime → DelegatedFlowReadinessGate       │
    │      truth_ownership dimension → classified 'companion_repo' in the │
    │      evidence surface → promoted to COMPANION_ANDROID gate category │
    │      in this skeleton (gate_worthy after V2 ingestion)              │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified.
2. **Skeleton-only verdict** — the gate produces a structured verdict but does
   NOT block CI or release by itself.  Enforcement is explicitly deferred.
3. **Projection-only** — all category evaluations are read-only; no canonical
   state is mutated.
4. **Fail-graceful** — if the evidence surface is unavailable, each category
   records a ``GateCategoryVerdict.unknown`` verdict; the report is still
   returned.
5. **Stable artifacts** — :class:`ReleaseGateReport` and
   :class:`GateCategoryEvaluation` are fully JSON-serialisable.
6. **Extension-first design** — later PRs can promote deferred categories to
   gate-worthy and add CI enforcement hooks without touching category
   definitions.

Public API
----------
Authority / policy sentinels::

    DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY
    DISTRIBUTED_RELEASE_GATE_SKELETON_PR7V2_SENTINEL
    GATE_SKELETON_IS_NON_ENFORCING_POLICY
    GATE_WORTHY_CATEGORIES_REQUIRE_CANONICAL_EVIDENCE_POLICY
    DEFERRED_CATEGORIES_MUST_NOT_BLOCK_RELEASE_POLICY
    ANDROID_COMPANION_EVIDENCE_IS_GATE_WORTHY_AFTER_V2_INGESTION_POLICY
    V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY

Enumerations::

    GateCategoryStrength
    GateCategory
    ReleaseGateVerdict

Data classes::

    GateCategoryEvaluation
    ReleaseGateReport

Primary class::

    DistributedReleaseGateSkeleton

Helpers::

    evaluate_distributed_release_gate() -> ReleaseGateReport
    get_release_gate_report()           -> ReleaseGateReport  (singleton)
    reset_release_gate_report()         -> None               (testing only)
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
    "GATE_SKELETON_IS_NON_ENFORCING_POLICY",
    "GATE_IS_NOW_CI_ENFORCING_AUTHORITY",
    "GATE_WORTHY_CATEGORIES_REQUIRE_CANONICAL_EVIDENCE_POLICY",
    "DEFERRED_CATEGORIES_MUST_NOT_BLOCK_RELEASE_POLICY",
    "ANDROID_COMPANION_EVIDENCE_IS_GATE_WORTHY_AFTER_V2_INGESTION_POLICY",
    "V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY",
    # Enumerations
    "GateCategoryStrength",
    "GateCategory",
    "ReleaseGateVerdict",
    # Data classes
    "GateCategoryEvaluation",
    "ReleaseGateReport",
    # Primary class
    "DistributedReleaseGateSkeleton",
    # Helpers
    "evaluate_distributed_release_gate",
    "get_release_gate_report",
    "reset_release_gate_report",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY: str = (
    "DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY::"
    "core.distributed_release_gate_skeleton::PR7V2::"
    "canonical-distributed-release-gate-skeleton::"
    "non-enforcing-structure-for-distributed-readiness-evidence"
)
"""Sentinel: this module is the canonical V2 distributed release gate skeleton.
Import to assert that a release pipeline, reviewer tool, or later CI hook is
consulting the correct canonical gate skeleton rather than an ad-hoc check."""

DISTRIBUTED_RELEASE_GATE_SKELETON_PR7V2_SENTINEL: str = (
    "DISTRIBUTED_RELEASE_GATE_SKELETON_PR7V2_SENTINEL::"
    "package=PR7V2::profile=distributed-release-gate-skeleton-v1::"
    "module=core.distributed_release_gate_skeleton"
)
"""Package sentinel for PR-7V2."""

GATE_SKELETON_IS_NON_ENFORCING_POLICY: str = (
    "POLICY::GATE_SKELETON_IS_NON_ENFORCING_V1: "
    "The DistributedReleaseGateSkeleton originally produced a structured gate "
    "verdict but did NOT block CI, reject releases, or raise exceptions based "
    "on the verdict.  This policy described the skeleton-only (non-enforcing) "
    "state.  As of PR Block 3, enforcement has been promoted: the gate now "
    "produces reports with is_enforcing=True and the CI workflow "
    "(.github/workflows/governance_gate_enforcement.yml) hard-blocks merges "
    "when gate_worthy categories are blocked.  This sentinel is preserved for "
    "downstream import compatibility and historical reference."
)
"""Policy: documents the original non-enforcing state; superseded by
GATE_IS_NOW_CI_ENFORCING_AUTHORITY which signals active enforcement."""

GATE_IS_NOW_CI_ENFORCING_AUTHORITY: str = (
    "GATE_IS_NOW_CI_ENFORCING_AUTHORITY::"
    "core.distributed_release_gate_skeleton::PR-Block3::"
    "governance-gate-ci-enforcement-promotion::"
    "is_enforcing=True::CI-workflow=governance_gate_enforcement.yml"
)
"""Sentinel: enforcement has been promoted from advisory skeleton to real CI gate.

As of PR Block 3 this module produces ReleaseGateReport instances with
``is_enforcing=True``.  The companion CI workflow
``.github/workflows/governance_gate_enforcement.yml`` runs the
:func:`core.governance_validation_gate.run_governance_verdict_ci` function
on every push/PR to main and exits non-zero when any gate_worthy category is
blocked, preventing merges that violate distributed governance invariants.

Import this sentinel to assert that the current code is running under the
PR Block 3 enforced governance posture rather than the original skeleton-only
advisory state.
"""

GATE_WORTHY_CATEGORIES_REQUIRE_CANONICAL_EVIDENCE_POLICY: str = (
    "POLICY::GATE_WORTHY_CATEGORIES_REQUIRE_CANONICAL_EVIDENCE_V1: "
    "A gate category may only be assigned GateCategoryStrength.gate_worthy "
    "if its backing evidence dimensions are classified 'canonical' in the "
    "V2ReadinessGovernanceEvidenceSurface.  Advisory-classified evidence "
    "dimensions must not back a gate_worthy category.  "
    "See: core.v2_readiness_governance_evidence_surface.CANONICAL_EVIDENCE_IS_GATE_INPUT_POLICY"
)
"""Policy: gate-worthy categories must be backed by canonical evidence."""

DEFERRED_CATEGORIES_MUST_NOT_BLOCK_RELEASE_POLICY: str = (
    "POLICY::DEFERRED_CATEGORIES_MUST_NOT_BLOCK_RELEASE_V1: "
    "Gate categories assigned GateCategoryStrength.deferred are explicitly "
    "out of scope for the current PR.  They appear in the skeleton so that "
    "later PRs can graduate them to gate_worthy without redefining semantics.  "
    "They MUST NOT block release in this PR or any PR that does not "
    "explicitly change their strength to gate_worthy."
)
"""Policy: deferred categories must not block release in this PR."""

ANDROID_COMPANION_EVIDENCE_IS_GATE_WORTHY_AFTER_V2_INGESTION_POLICY: str = (
    "POLICY::ANDROID_COMPANION_EVIDENCE_IS_GATE_WORTHY_AFTER_V2_INGESTION_V1: "
    "Android-originated evaluator artifacts become gate_worthy after V2 "
    "ingestion via AndroidEvaluatorArtifactIngress and classification by "
    "FlowTruthAlignmentRuntime.  The GateCategory.companion_android category "
    "is therefore gate_worthy (not advisory).  Raw Android truth kinds that "
    "are NOT promoted through the ingestion chain (e.g. readiness_assessment, "
    "runtime_state) remain advisory and must not back gate_worthy categories.  "
    "V2 is the authority for this classification; Android does not determine "
    "the gate strength of its own evidence."
)
"""Policy: Android companion evidence is gate-worthy after V2 ingestion."""

V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY: str = (
    "POLICY::V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_V1: "
    "V2 is the canonical orchestration authority for the distributed system.  "
    "The release gate skeleton is defined and owned by V2.  "
    "Android-originated evidence is consumed as companion distributed input "
    "but does not override V2 gate decisions.  The gate skeleton "
    "implementation lives exclusively in V2; Android's role is to produce "
    "evaluator artifacts that feed the V2 canonical gate via ingestion."
)
"""Policy: V2 is the canonical orchestration authority for the release gate."""


# ---------------------------------------------------------------------------
# GateCategoryStrength
# ---------------------------------------------------------------------------


class GateCategoryStrength(str, Enum):
    """Strength of a gate category — determines how the category verdict
    affects the overall release gate decision.

    Values
    ------
    gate_worthy
        This category's verdict MAY contribute to blocking the release once
        enforcement is enabled by a later PR.  The evidence backing this
        category is canonical.

    advisory
        This category's verdict is observational only and MUST NOT block the
        release regardless of enforcement state.

    deferred
        This category is registered in the skeleton for future use but is
        explicitly out of scope for current enforcement.  It will not
        contribute to blocking the release until a later PR graduates it
        to ``gate_worthy``.
    """

    gate_worthy = "gate_worthy"
    advisory = "advisory"
    deferred = "deferred"


# ---------------------------------------------------------------------------
# GateCategory
# ---------------------------------------------------------------------------


class GateCategory(str, Enum):
    """Canonical evidence categories in the distributed release gate.

    Each category maps to one or more evidence dimensions in the
    :class:`core.v2_readiness_governance_evidence_surface.EvidenceSurfaceReport`.

    Values
    ------
    canonical_runtime_lifecycle
        Delegated flow readiness gate (PR-9V2): five readiness dimensions
        covering continuity/replay, truth ownership, result convergence,
        operator surface, and compat/legacy.
        Strength: gate_worthy.

    canonical_graduation_acceptance
        Delegated flow acceptance gate (PR-10V2): six acceptance dimensions
        that must all pass before a delegated path can graduate.
        Strength: gate_worthy.

    canonical_post_graduation_governance
        Post-graduation governance evaluator (PR-11V2): continuous compliance
        monitoring across five governance dimensions.
        Strength: gate_worthy.

    canonical_continuity_recovery
        Continuity / recovery / durability closure validator (PR-5V2): 17
        recovery scenarios covering restart, transport reconnect, stale-signal
        guard, in-flight recovery, and runtime restart.
        Strength: gate_worthy.

    canonical_takeover_correctness
        Takeover request/response tracking: persisted accept/reject decisions
        for every V2-issued takeover request.
        Strength: gate_worthy.

    canonical_compat_blocking
        Compat / legacy path blocking canonicalization (PR-8V2): blocking-first
        gate ensuring no unresolved compat/legacy bypass risk.
        Strength: gate_worthy.

    companion_android
        Android-originated evaluator artifacts (governance, readiness,
        acceptance, strategy) ingested by V2 via AndroidEvaluatorArtifactIngress
        and classified via FlowTruthAlignmentRuntime.  Gate-worthy after
        ingestion.
        Strength: gate_worthy.

    advisory_audit_records
        Android delegated runtime audit ring: raw wire-event timeline.
        Observational; MUST NOT block release.
        Strength: advisory.

    advisory_participant_session
        Android participant session truth registry: phase-by-phase session
        bookkeeping.  Observational; MUST NOT block release.
        Strength: advisory.

    deferred_rollout_promotion
        Default-on delegated canonical path promotion policy.  Deferred until
        a later PR; not assessed by this skeleton.
        Strength: deferred.

    deferred_ci_enforcement
        Final CI pipeline enforcement (hard-blocking PRs on gate failure).
        Deferred until evidence surface and skeleton are stable.
        Strength: deferred.
    """

    canonical_runtime_lifecycle = "canonical_runtime_lifecycle"
    canonical_graduation_acceptance = "canonical_graduation_acceptance"
    canonical_post_graduation_governance = "canonical_post_graduation_governance"
    canonical_continuity_recovery = "canonical_continuity_recovery"
    canonical_takeover_correctness = "canonical_takeover_correctness"
    canonical_compat_blocking = "canonical_compat_blocking"
    companion_android = "companion_android"
    advisory_audit_records = "advisory_audit_records"
    advisory_participant_session = "advisory_participant_session"
    deferred_rollout_promotion = "deferred_rollout_promotion"
    deferred_ci_enforcement = "deferred_ci_enforcement"


# Canonical category → strength mapping (the single authoritative lookup)
_CATEGORY_STRENGTH: Dict[GateCategory, GateCategoryStrength] = {
    GateCategory.canonical_runtime_lifecycle: GateCategoryStrength.gate_worthy,
    GateCategory.canonical_graduation_acceptance: GateCategoryStrength.gate_worthy,
    GateCategory.canonical_post_graduation_governance: GateCategoryStrength.gate_worthy,
    GateCategory.canonical_continuity_recovery: GateCategoryStrength.gate_worthy,
    GateCategory.canonical_takeover_correctness: GateCategoryStrength.gate_worthy,
    GateCategory.canonical_compat_blocking: GateCategoryStrength.gate_worthy,
    GateCategory.companion_android: GateCategoryStrength.gate_worthy,
    GateCategory.advisory_audit_records: GateCategoryStrength.advisory,
    GateCategory.advisory_participant_session: GateCategoryStrength.advisory,
    GateCategory.deferred_rollout_promotion: GateCategoryStrength.deferred,
    GateCategory.deferred_ci_enforcement: GateCategoryStrength.deferred,
}

# Category → evidence surface dimension_id(s) it consumes
_CATEGORY_DIMENSION_IDS: Dict[GateCategory, List[str]] = {
    GateCategory.canonical_runtime_lifecycle: ["delegated_flow_readiness"],
    GateCategory.canonical_graduation_acceptance: ["delegated_flow_acceptance"],
    GateCategory.canonical_post_graduation_governance: ["post_graduation_governance"],
    GateCategory.canonical_continuity_recovery: ["continuity_recovery_closure"],
    GateCategory.canonical_takeover_correctness: ["takeover_tracking"],
    GateCategory.canonical_compat_blocking: ["compat_legacy_blocking"],
    GateCategory.companion_android: ["android_evaluator_artifact_ingestion"],
    GateCategory.advisory_audit_records: ["android_delegated_audit_ring"],
    GateCategory.advisory_participant_session: ["android_participant_session_truth"],
    GateCategory.deferred_rollout_promotion: [],
    GateCategory.deferred_ci_enforcement: [],
}

_CATEGORY_BLOCKING_CONDITION_TYPE: Dict[GateCategory, str] = {
    GateCategory.canonical_runtime_lifecycle: "continuity_risk",
    GateCategory.canonical_graduation_acceptance: "closure_quality_insufficiency",
    GateCategory.canonical_post_graduation_governance: "closure_quality_insufficiency",
    GateCategory.canonical_continuity_recovery: "replay_or_recovery_risk",
    GateCategory.canonical_takeover_correctness: "continuity_risk",
    GateCategory.canonical_compat_blocking: "schema_or_contract_compatibility_violation",
    GateCategory.companion_android: "cross_repo_evidence_failure",
    GateCategory.advisory_audit_records: "advisory_observation",
    GateCategory.advisory_participant_session: "advisory_observation",
    GateCategory.deferred_rollout_promotion: "deferred_scope",
    GateCategory.deferred_ci_enforcement: "deferred_scope",
}


# ---------------------------------------------------------------------------
# ReleaseGateVerdict
# ---------------------------------------------------------------------------


class ReleaseGateVerdict(str, Enum):
    """Overall release gate skeleton verdict.

    Values
    ------
    open
        All gate_worthy categories have present evidence; the skeleton finds
        no blocking evidence gaps.  (Note: this is a *skeleton* verdict —
        enforcement is not yet active; see GATE_SKELETON_IS_NON_ENFORCING_POLICY.)

    blocked
        One or more gate_worthy categories have absent or failed evidence.
        This signals that, once enforcement is enabled, the release would be
        blocked.  Currently non-enforcing.

    deferred
        All gate_worthy categories are either open or unknown (due to
        unavailability); no active blocks, but some evidence is unavailable.

    unknown
        The evidence surface itself was unavailable; the skeleton cannot
        produce a meaningful verdict.
    """

    open = "open"
    blocked = "blocked"
    deferred = "deferred"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# GateCategoryEvaluation
# ---------------------------------------------------------------------------


@dataclass
class GateCategoryEvaluation:
    """Per-category evaluation result in the release gate skeleton.

    Fields
    ------
    category
        :class:`GateCategory` value string.
    strength
        :class:`GateCategoryStrength` value string.
    verdict
        :class:`ReleaseGateVerdict` value string for this category.
    evidence_status
        Aggregated evidence status from the backing dimension(s):
        ``"present"`` / ``"absent"`` / ``"unavailable"`` / ``"deferred"`` /
        ``"unknown"``.
    evidence_dimension_ids
        List of evidence surface dimension IDs that back this category.
    summary
        Human-readable one-liner.
    gap_description
        Non-empty if verdict is ``"blocked"``; describes what is missing.
    notes
        Additional notes (deferral reason, extension guidance, etc.).
    """

    category: str
    strength: str
    verdict: str
    evidence_status: str
    evidence_dimension_ids: List[str] = field(default_factory=list)
    summary: str = ""
    gap_description: str = ""
    notes: str = ""
    blocking_condition_type: str = ""
    failure_state: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "strength": self.strength,
            "verdict": self.verdict,
            "evidence_status": self.evidence_status,
            "evidence_dimension_ids": list(self.evidence_dimension_ids),
            "summary": self.summary,
            "gap_description": self.gap_description,
            "notes": self.notes,
            "blocking_condition_type": self.blocking_condition_type,
            "failure_state": self.failure_state,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GateCategoryEvaluation":
        return cls(
            category=d.get("category", ""),
            strength=d.get("strength", GateCategoryStrength.advisory.value),
            verdict=d.get("verdict", ReleaseGateVerdict.unknown.value),
            evidence_status=d.get("evidence_status", "unknown"),
            evidence_dimension_ids=list(d.get("evidence_dimension_ids", [])),
            summary=d.get("summary", ""),
            gap_description=d.get("gap_description", ""),
            notes=d.get("notes", ""),
            blocking_condition_type=d.get("blocking_condition_type", ""),
            failure_state=d.get("failure_state", ""),
        )


# ---------------------------------------------------------------------------
# ReleaseGateReport
# ---------------------------------------------------------------------------


@dataclass
class ReleaseGateReport:
    """Canonical, serialisable distributed release gate skeleton report.

    Produced by :class:`DistributedReleaseGateSkeleton` or the module-level
    :func:`evaluate_distributed_release_gate` helper.

    Fields
    ------
    report_id
        Unique identifier for this report snapshot.
    generated_at
        Unix timestamp (float) when the report was assembled.
    authority
        Copy of :data:`DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY`.
    overall_verdict
        :class:`ReleaseGateVerdict` value string summarising the skeleton's
        assessment across all gate_worthy categories.
    is_enforcing
        Always ``False`` in this PR.  Later PRs may set this to ``True`` to
        enable actual release blocking.
    category_evaluations
        Ordered list of :class:`GateCategoryEvaluation` — one per
        :class:`GateCategory`.
    gate_worthy_count
        Number of categories with strength == ``"gate_worthy"``.
    advisory_count
        Number of categories with strength == ``"advisory"``.
    deferred_count
        Number of categories with strength == ``"deferred"``.
    blocked_gate_worthy_count
        Number of gate_worthy categories whose verdict is ``"blocked"``.
    open_gate_worthy_count
        Number of gate_worthy categories whose verdict is ``"open"``.
    evidence_surface_report_id
        ``report_id`` of the :class:`EvidenceSurfaceReport` consumed, or
        empty string if the surface was unavailable.
    deferred_notes
        List of human-readable notes about categories deferred to later PRs.
    """

    report_id: str
    generated_at: float
    authority: str
    overall_verdict: str
    is_enforcing: bool = False
    category_evaluations: List[GateCategoryEvaluation] = field(default_factory=list)
    gate_worthy_count: int = 0
    advisory_count: int = 0
    deferred_count: int = 0
    blocked_gate_worthy_count: int = 0
    open_gate_worthy_count: int = 0
    evidence_surface_report_id: str = ""
    deferred_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "authority": self.authority,
            "overall_verdict": self.overall_verdict,
            "is_enforcing": self.is_enforcing,
            "category_evaluations": [e.to_dict() for e in self.category_evaluations],
            "gate_worthy_count": self.gate_worthy_count,
            "advisory_count": self.advisory_count,
            "deferred_count": self.deferred_count,
            "blocked_gate_worthy_count": self.blocked_gate_worthy_count,
            "open_gate_worthy_count": self.open_gate_worthy_count,
            "evidence_surface_report_id": self.evidence_surface_report_id,
            "deferred_notes": list(self.deferred_notes),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ReleaseGateReport":
        evals = [
            GateCategoryEvaluation.from_dict(e)
            for e in d.get("category_evaluations", [])
        ]
        return cls(
            report_id=d.get("report_id", ""),
            generated_at=float(d.get("generated_at", 0.0)),
            authority=d.get("authority", ""),
            overall_verdict=d.get("overall_verdict", ReleaseGateVerdict.unknown.value),
            is_enforcing=bool(d.get("is_enforcing", False)),
            category_evaluations=evals,
            gate_worthy_count=int(d.get("gate_worthy_count", 0)),
            advisory_count=int(d.get("advisory_count", 0)),
            deferred_count=int(d.get("deferred_count", 0)),
            blocked_gate_worthy_count=int(d.get("blocked_gate_worthy_count", 0)),
            open_gate_worthy_count=int(d.get("open_gate_worthy_count", 0)),
            evidence_surface_report_id=d.get("evidence_surface_report_id", ""),
            deferred_notes=list(d.get("deferred_notes", [])),
        )


# ---------------------------------------------------------------------------
# Evidence surface availability guard
# ---------------------------------------------------------------------------

try:
    from core.v2_readiness_governance_evidence_surface import (
        build_evidence_surface_report as _build_evidence_surface_report,
        EvidenceSurfaceReport as _EvidenceSurfaceReport,
        EvidenceDimensionEntry as _EvidenceDimensionEntry,
    )
    _EVIDENCE_SURFACE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _EVIDENCE_SURFACE_AVAILABLE = False
    _build_evidence_surface_report = None  # type: ignore[assignment]
    _EvidenceSurfaceReport = None  # type: ignore[assignment,misc]
    _EvidenceDimensionEntry = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# DistributedReleaseGateSkeleton
# ---------------------------------------------------------------------------

_DEFERRED_NOTES: List[str] = [
    "DEFERRED: CI enforcement (hard PR-merge blocking on gate failure) is not "
    "enabled in this PR.  See DEFERRED_CATEGORIES_MUST_NOT_BLOCK_RELEASE_POLICY.  "
    "A later enforcement PR should import ReleaseGateReport, assert "
    "overall_verdict == 'open', and set is_enforcing=True.",
    "DEFERRED: GateCategory.deferred_rollout_promotion — default-on delegated "
    "canonical path promotion policy is out of scope for this PR.  "
    "The category is registered so that later PRs can graduate it to "
    "gate_worthy without redefining semantics.",
    "DEFERRED: GateCategory.deferred_ci_enforcement — final CI pipeline "
    "enforcement hook is out of scope for this PR.  The skeleton provides "
    "the ReleaseGateReport shape needed by that hook.",
    "DEFERRED: Offline Android queue ordering (RS-16 from RecoveryClosureReport) "
    "is already marked deferred in PR-5V2.  This skeleton inherits that deferral.",
]


class DistributedReleaseGateSkeleton:
    """Canonical V2 distributed release gate skeleton.

    Evaluates all :class:`GateCategory` dimensions using the PR-6
    evidence surface and produces a :class:`ReleaseGateReport` that:

    - Lists every category with its strength and verdict.
    - Aggregates an overall verdict across gate_worthy categories.
    - Produces reports with ``is_enforcing=True`` (PR Block 3 promotion).

    The companion CI workflow
    ``.github/workflows/governance_gate_enforcement.yml`` consumes the
    governance verdict and hard-blocks CI when gate_worthy categories are
    blocked, turning this from an advisory skeleton into a real release gate.

    Usage
    -----
    ::

        from core.distributed_release_gate_skeleton import (
            DistributedReleaseGateSkeleton,
            evaluate_distributed_release_gate,
        )

        report = evaluate_distributed_release_gate()
        print(report.overall_verdict)   # "open" | "blocked" | "deferred" | "unknown"
        print(report.is_enforcing)      # True — enforcement promoted in PR Block 3

    See :data:`GATE_IS_NOW_CI_ENFORCING_AUTHORITY` for the enforcement
    promotion sentinel.
    """

    def evaluate(self) -> ReleaseGateReport:
        """Run all category evaluations and return a fresh
        :class:`ReleaseGateReport`.  Never raises; on surface unavailability
        returns a report with ``overall_verdict == "unknown"``."""
        try:
            return self._evaluate_impl()
        except Exception as exc:  # noqa: BLE001  pragma: no cover
            logger.error("DistributedReleaseGateSkeleton.evaluate raised: %s", exc)
            return self._unknown_report(str(exc))

    # ------------------------------------------------------------------
    # Private implementation
    # ------------------------------------------------------------------

    def _evaluate_impl(self) -> ReleaseGateReport:
        if not _EVIDENCE_SURFACE_AVAILABLE or _build_evidence_surface_report is None:
            return self._unknown_report(
                "core.v2_readiness_governance_evidence_surface not importable; "
                "cannot evaluate gate categories."
            )

        surface_report = _build_evidence_surface_report()
        surface_report_id: str = getattr(surface_report, "report_id", "")

        # Index dimension entries by dimension_id for O(1) lookup
        dim_index: Dict[str, Any] = {}
        for entry in getattr(surface_report, "dimensions", []):
            dim_id = getattr(entry, "dimension_id", "")
            if dim_id:
                dim_index[dim_id] = entry

        evaluations: List[GateCategoryEvaluation] = []
        for category in GateCategory:
            eval_result = self._evaluate_category(category, dim_index)
            evaluations.append(eval_result)

        return self._build_report(
            evaluations=evaluations,
            surface_report_id=surface_report_id,
            is_enforcing=True,
        )

    def _evaluate_category(
        self,
        category: GateCategory,
        dim_index: Dict[str, Any],
    ) -> GateCategoryEvaluation:
        """Evaluate one :class:`GateCategory` against the evidence surface."""
        strength = _CATEGORY_STRENGTH[category]
        dim_ids = _CATEGORY_DIMENSION_IDS[category]
        blocking_condition_type = _CATEGORY_BLOCKING_CONDITION_TYPE[category]

        # Deferred categories always return a deferred verdict without
        # consulting the evidence surface.
        if strength == GateCategoryStrength.deferred:
            return GateCategoryEvaluation(
                category=category.value,
                strength=strength.value,
                verdict=ReleaseGateVerdict.deferred.value,
                evidence_status="deferred",
                evidence_dimension_ids=list(dim_ids),
                summary=f"Category '{category.value}' is explicitly deferred to a later PR.",
                notes=(
                    "See DEFERRED_CATEGORIES_MUST_NOT_BLOCK_RELEASE_POLICY and "
                    "GATE_SKELETON_IS_NON_ENFORCING_POLICY."
                ),
                blocking_condition_type=blocking_condition_type,
                failure_state="deferred_scope",
            )

        if not dim_ids:
            # No evidence dimensions mapped — treat as unavailable advisory
            return GateCategoryEvaluation(
                category=category.value,
                strength=strength.value,
                verdict=ReleaseGateVerdict.unknown.value,
                evidence_status="unknown",
                evidence_dimension_ids=[],
                summary=(
                    f"Category '{category.value}' has no evidence dimension mapping; "
                    "cannot evaluate."
                ),
                blocking_condition_type=blocking_condition_type,
                failure_state="mapping_missing",
            )

        # Aggregate evidence status across all mapped dimension IDs
        entries_found = [dim_index.get(did) for did in dim_ids if did in dim_index]
        all_statuses = [
            getattr(e, "evidence_status", "unknown") for e in entries_found
        ]

        if not entries_found:
            agg_status = "unavailable"
        elif all(s == "present" for s in all_statuses):
            agg_status = "present"
        elif any(s == "absent" for s in all_statuses):
            agg_status = "absent"
        else:
            agg_status = "unavailable"

        # Derive per-category verdict
        if agg_status == "present":
            verdict = ReleaseGateVerdict.open.value
            gap = ""
            failure_state = "none"
            summary = (
                f"Category '{category.value}' evidence is present "
                f"(dims: {dim_ids})."
            )
        elif agg_status == "absent":
            verdict = (
                ReleaseGateVerdict.blocked.value
                if strength == GateCategoryStrength.gate_worthy
                else ReleaseGateVerdict.deferred.value
            )
            failure_state = "evidence_absent"
            gap = (
                f"Evidence absent for category '{category.value}' "
                f"(dims: {dim_ids}).  "
                + ("Protected release/deploy path is blocked until this evidence is restored."
                   if strength == GateCategoryStrength.gate_worthy
                   else "Advisory gap; does not block release.")
            )
            summary = f"Category '{category.value}' evidence absent."
        else:
            if strength == GateCategoryStrength.gate_worthy:
                verdict = ReleaseGateVerdict.blocked.value
                failure_state = "evidence_unavailable"
                gap = (
                   f"Evidence unavailable for gate_worthy category '{category.value}' "
                   f"(dims: {dim_ids}).  Protected release/deploy path is blocked "
                   "until evidence becomes measurable."
                )
                summary = f"Category '{category.value}' evidence unavailable (blocking)."
            else:
                verdict = ReleaseGateVerdict.deferred.value
                failure_state = "evidence_unavailable"
                gap = ""
                summary = (
                   f"Category '{category.value}' evidence unavailable "
                   f"(dims: {dim_ids}); verdict deferred."
                )

        notes = ""
        if strength == GateCategoryStrength.advisory:
            notes = (
                "Advisory category: verdict does not affect overall gate decision.  "
                "See ADVISORY_EVIDENCE_IS_NOT_GATE_INPUT_POLICY in "
                "core.v2_readiness_governance_evidence_surface."
            )
        elif category == GateCategory.companion_android:
            notes = (
                "Android companion evidence is gate_worthy after V2 ingestion via "
                "AndroidEvaluatorArtifactIngress → FlowTruthAlignmentRuntime.  "
                "See ANDROID_COMPANION_EVIDENCE_IS_GATE_WORTHY_AFTER_V2_INGESTION_POLICY."
            )

        return GateCategoryEvaluation(
            category=category.value,
            strength=strength.value,
            verdict=verdict,
            evidence_status=agg_status,
            evidence_dimension_ids=list(dim_ids),
            summary=summary,
            gap_description=gap,
            notes=notes,
            blocking_condition_type=blocking_condition_type,
            failure_state=failure_state,
        )

    def _build_report(
        self,
        evaluations: List[GateCategoryEvaluation],
        surface_report_id: str,
        *,
        is_enforcing: bool = False,
    ) -> ReleaseGateReport:
        gate_worthy = [
            e for e in evaluations
            if e.strength == GateCategoryStrength.gate_worthy.value
        ]
        advisory = [
            e for e in evaluations
            if e.strength == GateCategoryStrength.advisory.value
        ]
        deferred = [
            e for e in evaluations
            if e.strength == GateCategoryStrength.deferred.value
        ]

        blocked_gw = [
            e for e in gate_worthy
            if e.verdict == ReleaseGateVerdict.blocked.value
        ]
        open_gw = [
            e for e in gate_worthy
            if e.verdict == ReleaseGateVerdict.open.value
        ]

        # Determine overall verdict
        if blocked_gw:
            overall = ReleaseGateVerdict.blocked.value
        elif not gate_worthy:
            overall = ReleaseGateVerdict.unknown.value
        elif all(
            e.verdict in (ReleaseGateVerdict.open.value, ReleaseGateVerdict.deferred.value)
            for e in gate_worthy
        ):
            if open_gw:
                overall = ReleaseGateVerdict.open.value
            else:
                overall = ReleaseGateVerdict.deferred.value
        else:
            overall = ReleaseGateVerdict.deferred.value

        return ReleaseGateReport(
            report_id=str(uuid.uuid4()),
            generated_at=time.time(),
            authority=DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY,
            overall_verdict=overall,
            is_enforcing=is_enforcing,
            category_evaluations=evaluations,
            gate_worthy_count=len(gate_worthy),
            advisory_count=len(advisory),
            deferred_count=len(deferred),
            blocked_gate_worthy_count=len(blocked_gw),
            open_gate_worthy_count=len(open_gw),
            evidence_surface_report_id=surface_report_id,
            deferred_notes=list(_DEFERRED_NOTES),
        )

    def _unknown_report(self, reason: str) -> ReleaseGateReport:
        """Return an all-unknown report when the evidence surface is unavailable."""
        evaluations = [
            GateCategoryEvaluation(
                category=category.value,
                strength=_CATEGORY_STRENGTH[category].value,
                verdict=ReleaseGateVerdict.unknown.value,
                evidence_status="unknown",
                evidence_dimension_ids=list(_CATEGORY_DIMENSION_IDS[category]),
                summary=f"Evidence surface unavailable: {reason}",
                blocking_condition_type=_CATEGORY_BLOCKING_CONDITION_TYPE[category],
                failure_state="surface_unavailable",
            )
            for category in GateCategory
        ]
        return ReleaseGateReport(
            report_id=str(uuid.uuid4()),
            generated_at=time.time(),
            authority=DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY,
            overall_verdict=ReleaseGateVerdict.unknown.value,
            is_enforcing=False,
            category_evaluations=evaluations,
            gate_worthy_count=sum(
                1 for c in GateCategory
                if _CATEGORY_STRENGTH[c] == GateCategoryStrength.gate_worthy
            ),
            advisory_count=sum(
                1 for c in GateCategory
                if _CATEGORY_STRENGTH[c] == GateCategoryStrength.advisory
            ),
            deferred_count=sum(
                1 for c in GateCategory
                if _CATEGORY_STRENGTH[c] == GateCategoryStrength.deferred
            ),
            blocked_gate_worthy_count=0,
            open_gate_worthy_count=0,
            evidence_surface_report_id="",
            deferred_notes=list(_DEFERRED_NOTES),
        )


# ---------------------------------------------------------------------------
# Module-level helpers (preferred public API)
# ---------------------------------------------------------------------------

_default_skeleton: Optional[DistributedReleaseGateSkeleton] = None
_cached_report: Optional[ReleaseGateReport] = None
_cache_lock: threading.Lock = threading.Lock()


def evaluate_distributed_release_gate() -> ReleaseGateReport:
    """Evaluate the distributed release gate skeleton and return a fresh
    :class:`ReleaseGateReport`.

    This is the preferred public entry point.  It always returns a new report
    (no caching).  Use :func:`get_release_gate_report` for a cached singleton.
    """
    skeleton = DistributedReleaseGateSkeleton()
    return skeleton.evaluate()


def get_release_gate_report() -> ReleaseGateReport:
    """Return a cached :class:`ReleaseGateReport`, building one if necessary.

    The cache is module-level.  Use :func:`reset_release_gate_report` to clear
    it (e.g. in tests).
    """
    global _cached_report
    with _cache_lock:
        if _cached_report is None:
            _cached_report = evaluate_distributed_release_gate()
        return _cached_report


def reset_release_gate_report() -> None:
    """Clear the cached report (for testing only)."""
    global _cached_report
    with _cache_lock:
        _cached_report = None
