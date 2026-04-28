#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/v2_readiness_governance_evidence_surface.py
=================================================
PR-6V2-EVIDENCE (post-533 dual-repo runtime-unification master plan):
V2 Canonical Readiness / Governance Evidence Surface.

Problem addressed
-----------------
The V2 repository contains substantial readiness and governance evidence
distributed across multiple layers (delegated-flow readiness gate,
acceptance gate, post-graduation governance evaluator, takeover tracking,
Android evaluator artifact ingress, continuity/recovery validator, and audit
records).  A reviewer asked to assess release confidence cannot easily
determine:

* which signals count as **canonical / gate-worthy** evidence,
* which signals are **advisory or observational** only,
* how **Android-originated artifacts** are represented on the V2 side, and
* what concrete code/tests back each evidence dimension.

This module closes that reviewability gap by providing a single,
read-only, additive **evidence surface** that:

1. Aggregates evidence from all authoritative V2 evidence sources (read-only
   projection — no mutations).
2. Classifies each evidence dimension as **canonical**, **advisory**, or
   **companion_repo** (Android-originated, consumed by V2).
3. Produces a stable, JSON-serialisable :class:`EvidenceSurfaceReport` that
   reviewers, release pipelines, and CI hooks can consume.
4. Exposes policy sentinels so downstream tooling can assert the correct
   module is being consulted.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  V2 READINESS / GOVERNANCE EVIDENCE SURFACE  (this module)         │
    │                                                                     │
    │  Read-only aggregation over:                                       │
    │    • DelegatedFlowReadinessGate      (PR-9V2)                      │
    │    • DelegatedFlowAcceptanceGate     (PR-10V2)                     │
    │    • DelegatedFlowGovernanceEvaluator (PR-11V2)                    │
    │    • AndroidEvaluatorArtifactRegistry (PR-4V2-GOV)                 │
    │    • TakeoverTrackingRuntime         (takeover_tracking)           │
    │    • AndroidDelegatedRuntimeAuditRecorder (android_delegated_audit)│
    │    • RecoveryDurabilityClosureValidator (PR-5V2)                   │
    │                                                                     │
    │  Produces:                                                         │
    │    • EvidenceDimensionEntry   (per-dimension evidence summary)     │
    │    • EvidenceSurfaceReport    (full reviewable evidence surface)   │
    │                                                                     │
    │  Evidence classifications:                                         │
    │    • canonical   — gate-worthy; consumed by release gate           │
    │    • advisory    — observational; does not gate release            │
    │    • companion_repo — Android-originated; V2 classifies and stores │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified.
2. **Projection-only** — all probes are read-only; canonical state is never
   mutated by this module.
3. **Fail-graceful** — when a source module is unavailable the corresponding
   dimension entry records ``evidence_status = "unavailable"`` with a
   human-readable explanation; the report is still returned.
4. **Stable artifacts** — :class:`EvidenceSurfaceReport` and
   :class:`EvidenceDimensionEntry` are fully JSON-serialisable so they can
   be persisted, diffed, and included in release artifacts.
5. **Reviewer-friendly** — every entry carries ``code_reference`` and
   ``test_reference`` strings so a reviewer can trace the evidence back to
   concrete code without reconstructing the full architecture.

Public API
----------
Authority / policy sentinels::

    V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_AUTHORITY
    V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_PR6V2_SENTINEL
    CANONICAL_EVIDENCE_IS_GATE_INPUT_POLICY
    ADVISORY_EVIDENCE_IS_NOT_GATE_INPUT_POLICY
    COMPANION_REPO_EVIDENCE_IS_CLASSIFIED_BY_V2_POLICY
    EVIDENCE_SURFACE_IS_PROJECTION_ONLY_POLICY
    EVIDENCE_SURFACE_IS_REVIEWER_FRIENDLY_POLICY

Enumerations::

    EvidenceClassification

Data classes::

    EvidenceDimensionEntry
    EvidenceSurfaceReport

Helpers::

    build_evidence_surface_report() -> EvidenceSurfaceReport
    get_evidence_surface_report()   -> EvidenceSurfaceReport  (singleton)
    reset_evidence_surface_report() -> None                   (testing only)
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

logger = logging.getLogger("Galaxy.V2ReadinessGovernanceEvidenceSurface")

__all__ = [
    # Authority / policy sentinels
    "V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_AUTHORITY",
    "V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_PR6V2_SENTINEL",
    "CANONICAL_EVIDENCE_IS_GATE_INPUT_POLICY",
    "ADVISORY_EVIDENCE_IS_NOT_GATE_INPUT_POLICY",
    "COMPANION_REPO_EVIDENCE_IS_CLASSIFIED_BY_V2_POLICY",
    "EVIDENCE_SURFACE_IS_PROJECTION_ONLY_POLICY",
    "EVIDENCE_SURFACE_IS_REVIEWER_FRIENDLY_POLICY",
    # Enumerations
    "EvidenceClassification",
    # Data classes
    "EvidenceDimensionEntry",
    "EvidenceSurfaceReport",
    # Helpers
    "build_evidence_surface_report",
    "get_evidence_surface_report",
    "reset_evidence_surface_report",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_AUTHORITY: str = (
    "V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_AUTHORITY::"
    "core.v2_readiness_governance_evidence_surface::PR6V2-EVIDENCE::"
    "canonical-readiness-governance-evidence-aggregation-surface::"
    "reviewer-friendly-release-gate-ready"
)
"""Sentinel: this module is the canonical V2 readiness/governance evidence
surface.  Import to assert that a release pipeline, reviewer tool, or CI
hook is consulting the correct canonical evidence aggregator rather than
individual sub-system state."""

V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_PR6V2_SENTINEL: str = (
    "V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_PR6V2_SENTINEL::"
    "package=PR6V2-EVIDENCE::profile=v2-readiness-governance-evidence-surface-v1::"
    "module=core.v2_readiness_governance_evidence_surface"
)
"""Package sentinel for PR-6V2-EVIDENCE."""

CANONICAL_EVIDENCE_IS_GATE_INPUT_POLICY: str = (
    "POLICY::CANONICAL_EVIDENCE_IS_GATE_INPUT_V1: "
    "Evidence classified as 'canonical' is gate-worthy and may be consumed "
    "by release gates, rollout controllers, and CI enforcement pipelines.  "
    "Canonical evidence originates from authoritative V2 gate modules "
    "(DelegatedFlowReadinessGate, DelegatedFlowAcceptanceGate, "
    "DelegatedFlowGovernanceEvaluator) or from Android evaluator artifacts "
    "that have been formally ingested and classified via the "
    "AndroidEvaluatorArtifactIngress pipeline.  Only canonical evidence "
    "dimensions may block release."
)
"""Policy: only canonical evidence may be used as a release gate input."""

ADVISORY_EVIDENCE_IS_NOT_GATE_INPUT_POLICY: str = (
    "POLICY::ADVISORY_EVIDENCE_IS_NOT_GATE_INPUT_V1: "
    "Evidence classified as 'advisory' is observational only.  It MAY "
    "provide useful debugging context but MUST NOT be used to block release "
    "or to substitute for canonical gate evidence.  Advisory signals include "
    "raw audit ring snapshots, per-task lifecycle records, and Android "
    "readiness_assessment truth kind (local-only by design)."
)
"""Policy: advisory evidence must not gate release."""

COMPANION_REPO_EVIDENCE_IS_CLASSIFIED_BY_V2_POLICY: str = (
    "POLICY::COMPANION_REPO_EVIDENCE_IS_CLASSIFIED_BY_V2_V1: "
    "Android-originated evaluator artifacts (governance, readiness, "
    "acceptance, strategy) are transported to V2 as 'governance_artifact' "
    "truth kind and ingested via AndroidEvaluatorArtifactIngress.  V2 "
    "classifies and stores these artifacts; they become canonical gate "
    "inputs to DelegatedFlowReadinessGate._evaluate_truth_ownership().  "
    "The V2 side is the authority for how companion-repo evidence is "
    "classified and represented; the Android side originates the evidence "
    "but does not determine its gate classification."
)
"""Policy: companion-repo (Android) evidence classification is V2's authority."""

EVIDENCE_SURFACE_IS_PROJECTION_ONLY_POLICY: str = (
    "POLICY::EVIDENCE_SURFACE_IS_PROJECTION_ONLY_V1: "
    "V2ReadinessGovernanceEvidenceSurface.build() reads from existing runtime "
    "modules; it MUST NOT mutate canonical state, sub-system registries, or "
    "gate module state.  It is a read-only, additive projection."
)
"""Policy: the evidence surface is a read-only projection."""

EVIDENCE_SURFACE_IS_REVIEWER_FRIENDLY_POLICY: str = (
    "POLICY::EVIDENCE_SURFACE_IS_REVIEWER_FRIENDLY_V1: "
    "Every evidence dimension entry MUST carry a non-empty code_reference "
    "and test_reference so a reviewer can trace evidence back to concrete "
    "code and tests without reconstructing the full V2 architecture.  "
    "Opaque evidence without traceability is not acceptable."
)
"""Policy: every evidence dimension must carry traceability references."""


# ---------------------------------------------------------------------------
# EvidenceClassification
# ---------------------------------------------------------------------------


class EvidenceClassification(str, Enum):
    """Canonical classification for an evidence dimension.

    Values
    ------
    canonical
        Gate-worthy evidence from an authoritative V2 gate module.  May be
        used by release gates and CI enforcement.

    advisory
        Observational / local-only evidence.  Useful for debugging and
        auditing but MUST NOT gate release.

    companion_repo
        Evidence that originates in the companion Android repository but is
        transported to V2, ingested, classified, and stored here.  After
        ingestion the evidence feeds a canonical gate dimension
        (``truth_ownership`` in DelegatedFlowReadinessGate).
    """

    canonical = "canonical"
    advisory = "advisory"
    companion_repo = "companion_repo"


# ---------------------------------------------------------------------------
# EvidenceDimensionEntry
# ---------------------------------------------------------------------------


@dataclass
class EvidenceDimensionEntry:
    """One row in the reviewable evidence surface.

    Fields
    ------
    dimension_id
        Short, stable identifier (e.g. ``"delegated_flow_readiness"``).
    display_name
        Human-readable name for the dimension.
    classification
        :class:`EvidenceClassification` value string.
    evidence_status
        ``"present"`` / ``"absent"`` / ``"unavailable"`` / ``"unknown"``.
    evidence_summary
        Human-readable one-liner describing what evidence was found.
    code_reference
        Canonical module or class path that produces this evidence.
    test_reference
        Test file / test group that exercises this dimension.
    raw_evidence
        Optional dict of machine-readable evidence from the source module.
    notes
        Optional additional notes (deferral reasons, caveats, etc.).
    """

    dimension_id: str
    display_name: str
    classification: str  # EvidenceClassification.value
    evidence_status: str  # "present" | "absent" | "unavailable" | "unknown"
    evidence_summary: str
    code_reference: str
    test_reference: str
    raw_evidence: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension_id": self.dimension_id,
            "display_name": self.display_name,
            "classification": self.classification,
            "evidence_status": self.evidence_status,
            "evidence_summary": self.evidence_summary,
            "code_reference": self.code_reference,
            "test_reference": self.test_reference,
            "raw_evidence": self.raw_evidence,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvidenceDimensionEntry":
        return cls(
            dimension_id=d.get("dimension_id", ""),
            display_name=d.get("display_name", ""),
            classification=d.get("classification", EvidenceClassification.advisory.value),
            evidence_status=d.get("evidence_status", "unknown"),
            evidence_summary=d.get("evidence_summary", ""),
            code_reference=d.get("code_reference", ""),
            test_reference=d.get("test_reference", ""),
            raw_evidence=d.get("raw_evidence", {}),
            notes=d.get("notes", ""),
        )


# ---------------------------------------------------------------------------
# EvidenceSurfaceReport
# ---------------------------------------------------------------------------


@dataclass
class EvidenceSurfaceReport:
    """Canonical, serialisable V2 readiness/governance evidence surface report.

    Produced by :class:`V2ReadinessGovernanceEvidenceSurface` or the
    module-level :func:`build_evidence_surface_report` helper.

    Fields
    ------
    report_id
        Unique identifier for this report snapshot.
    generated_at
        Unix timestamp (float) when the report was assembled.
    authority
        Copy of :data:`V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_AUTHORITY`.
    dimensions
        Ordered list of :class:`EvidenceDimensionEntry` covering all
        evidence dimensions surveyed.
    canonical_count
        Number of dimensions with classification == ``"canonical"``.
    advisory_count
        Number of dimensions with classification == ``"advisory"``.
    companion_repo_count
        Number of dimensions with classification == ``"companion_repo"``.
    present_count
        Number of dimensions with evidence_status == ``"present"``.
    absent_count
        Number of dimensions with evidence_status == ``"absent"``.
    unavailable_count
        Number of dimensions with evidence_status == ``"unavailable"`` or
        ``"unknown"`` (source module not importable).
    all_canonical_present
        ``True`` when every canonical-classified dimension has
        ``evidence_status == "present"``.
    deferred_notes
        List of human-readable notes about evidence dimensions that are
        explicitly deferred to later PRs.
    """

    report_id: str
    generated_at: float
    authority: str
    dimensions: List[EvidenceDimensionEntry] = field(default_factory=list)
    canonical_count: int = 0
    advisory_count: int = 0
    companion_repo_count: int = 0
    present_count: int = 0
    absent_count: int = 0
    unavailable_count: int = 0
    all_canonical_present: bool = False
    deferred_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "authority": self.authority,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "canonical_count": self.canonical_count,
            "advisory_count": self.advisory_count,
            "companion_repo_count": self.companion_repo_count,
            "present_count": self.present_count,
            "absent_count": self.absent_count,
            "unavailable_count": self.unavailable_count,
            "all_canonical_present": self.all_canonical_present,
            "deferred_notes": list(self.deferred_notes),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvidenceSurfaceReport":
        dims = [
            EvidenceDimensionEntry.from_dict(entry)
            for entry in d.get("dimensions", [])
        ]
        return cls(
            report_id=d.get("report_id", ""),
            generated_at=float(d.get("generated_at", 0.0)),
            authority=d.get("authority", ""),
            dimensions=dims,
            canonical_count=int(d.get("canonical_count", 0)),
            advisory_count=int(d.get("advisory_count", 0)),
            companion_repo_count=int(d.get("companion_repo_count", 0)),
            present_count=int(d.get("present_count", 0)),
            absent_count=int(d.get("absent_count", 0)),
            unavailable_count=int(d.get("unavailable_count", 0)),
            all_canonical_present=bool(d.get("all_canonical_present", False)),
            deferred_notes=list(d.get("deferred_notes", [])),
        )


# ---------------------------------------------------------------------------
# Internal probe helpers (read-only projections)
# ---------------------------------------------------------------------------


def _probe_delegated_flow_readiness() -> EvidenceDimensionEntry:
    """Probe DelegatedFlowReadinessGate (PR-9V2)."""
    dim_id = "delegated_flow_readiness"
    code_ref = "core.delegated_flow_readiness_gate.DelegatedFlowReadinessGate"
    test_ref = "tests/test_pr10_v2_delegated_flow_acceptance_gate.py"
    try:
        from core.delegated_flow_readiness_gate import (
            evaluate_delegated_flow_readiness,
            DelegatedFlowReadinessVerdict,
        )
        report = evaluate_delegated_flow_readiness()
        verdict = getattr(report, "verdict", "")
        dimensions_raw: Dict[str, Any] = {}
        if hasattr(report, "dimensions"):
            dimensions_raw = {
                d.dimension.value if hasattr(d, "dimension") else str(i): {
                    "status": d.status.value if hasattr(d.status, "value") else str(d.status),
                    "gap": getattr(d, "gap_description", ""),
                }
                for i, d in enumerate(report.dimensions)
            }
        evidence_status = "present"
        summary = f"DelegatedFlowReadinessGate verdict={verdict!r}; {len(dimensions_raw)} dimensions evaluated"
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Delegated Flow Readiness Gate (PR-9V2)",
            classification=EvidenceClassification.canonical.value,
            evidence_status=evidence_status,
            evidence_summary=summary,
            code_reference=code_ref,
            test_reference=test_ref,
            raw_evidence={"verdict": verdict, "dimensions": dimensions_raw},
        )
    except Exception as exc:  # noqa: BLE001
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Delegated Flow Readiness Gate (PR-9V2)",
            classification=EvidenceClassification.canonical.value,
            evidence_status="unavailable",
            evidence_summary=f"DelegatedFlowReadinessGate unavailable: {exc}",
            code_reference=code_ref,
            test_reference=test_ref,
            notes="Module import failed; ensure core.delegated_flow_readiness_gate is importable.",
        )


def _probe_delegated_flow_acceptance() -> EvidenceDimensionEntry:
    """Probe DelegatedFlowAcceptanceGate (PR-10V2)."""
    dim_id = "delegated_flow_acceptance"
    code_ref = "core.delegated_flow_acceptance_gate.DelegatedFlowAcceptanceGate"
    test_ref = "tests/test_pr10_v2_delegated_flow_acceptance_gate.py"
    try:
        from core.delegated_flow_acceptance_gate import (
            evaluate_delegated_flow_acceptance,
        )
        report = evaluate_delegated_flow_acceptance()
        verdict = getattr(report, "verdict", "")
        dimensions_raw: Dict[str, Any] = {}
        if hasattr(report, "dimensions"):
            dimensions_raw = {
                d.dimension.value if hasattr(d, "dimension") else str(i): {
                    "status": d.status.value if hasattr(d.status, "value") else str(d.status),
                    "gap": getattr(d, "gap_description", ""),
                }
                for i, d in enumerate(report.dimensions)
            }
        summary = f"DelegatedFlowAcceptanceGate verdict={verdict!r}; {len(dimensions_raw)} dimensions evaluated"
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Delegated Flow Acceptance / Graduation Gate (PR-10V2)",
            classification=EvidenceClassification.canonical.value,
            evidence_status="present",
            evidence_summary=summary,
            code_reference=code_ref,
            test_reference=test_ref,
            raw_evidence={"verdict": verdict, "dimensions": dimensions_raw},
        )
    except Exception as exc:  # noqa: BLE001
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Delegated Flow Acceptance / Graduation Gate (PR-10V2)",
            classification=EvidenceClassification.canonical.value,
            evidence_status="unavailable",
            evidence_summary=f"DelegatedFlowAcceptanceGate unavailable: {exc}",
            code_reference=code_ref,
            test_reference=test_ref,
            notes="Module import failed; ensure core.delegated_flow_acceptance_gate is importable.",
        )


def _probe_post_graduation_governance() -> EvidenceDimensionEntry:
    """Probe DelegatedFlowGovernanceEvaluator (PR-11V2)."""
    dim_id = "post_graduation_governance"
    code_ref = "core.delegated_flow_post_graduation_governance.DelegatedFlowGovernanceEvaluator"
    test_ref = "tests/test_pr11_v2_delegated_flow_post_graduation_governance.py"
    try:
        from core.delegated_flow_post_graduation_governance import (
            evaluate_post_graduation_governance,
        )
        report = evaluate_post_graduation_governance()
        verdict = getattr(report, "verdict", "")
        dimensions_raw: Dict[str, Any] = {}
        if hasattr(report, "dimensions"):
            dimensions_raw = {
                d.dimension.value if hasattr(d, "dimension") else str(i): {
                    "status": d.status.value if hasattr(d.status, "value") else str(d.status),
                    "violation": getattr(d, "violation_description", ""),
                }
                for i, d in enumerate(report.dimensions)
            }
        summary = f"PostGraduationGovernanceEvaluator verdict={verdict!r}; {len(dimensions_raw)} dimensions"
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Post-Graduation Governance Evaluator (PR-11V2)",
            classification=EvidenceClassification.canonical.value,
            evidence_status="present",
            evidence_summary=summary,
            code_reference=code_ref,
            test_reference=test_ref,
            raw_evidence={"verdict": verdict, "dimensions": dimensions_raw},
        )
    except Exception as exc:  # noqa: BLE001
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Post-Graduation Governance Evaluator (PR-11V2)",
            classification=EvidenceClassification.canonical.value,
            evidence_status="unavailable",
            evidence_summary=f"DelegatedFlowGovernanceEvaluator unavailable: {exc}",
            code_reference=code_ref,
            test_reference=test_ref,
            notes="Module import failed; ensure core.delegated_flow_post_graduation_governance is importable.",
        )


def _probe_android_evaluator_artifacts() -> EvidenceDimensionEntry:
    """Probe AndroidEvaluatorArtifactRegistry (PR-4V2-GOV)."""
    dim_id = "android_evaluator_artifact_ingestion"
    code_ref = "core.android_evaluator_artifact_ingress.AndroidEvaluatorArtifactRegistry"
    test_ref = "tests/test_pr03_v2_android_bridge_canonical_ingress.py"
    try:
        from core.android_evaluator_artifact_ingress import (
            get_android_evaluator_artifact_registry,
            AndroidEvaluatorArtifactKind,
        )
        registry = get_android_evaluator_artifact_registry()
        snapshot = registry.snapshot() if hasattr(registry, "snapshot") else []
        kind_counts: Dict[str, int] = {}
        for artifact in snapshot:
            k = getattr(artifact, "kind", None)
            key = k.value if hasattr(k, "value") else str(k)
            kind_counts[key] = kind_counts.get(key, 0) + 1
        total = len(snapshot)
        summary = (
            f"AndroidEvaluatorArtifactRegistry: {total} artifact(s) in registry; "
            f"kinds present: {list(kind_counts.keys()) or 'none (registry empty — nominal at startup)'}"
        )
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Android Evaluator Artifact Ingestion (PR-4V2-GOV)",
            classification=EvidenceClassification.companion_repo.value,
            evidence_status="present",
            evidence_summary=summary,
            code_reference=code_ref,
            test_reference=test_ref,
            raw_evidence={"total_artifacts": total, "kind_counts": kind_counts},
            notes=(
                "Registry is empty at startup; populates when Android runtime "
                "emits governance/readiness/acceptance/strategy evaluator artifacts.  "
                "After ingestion these become canonical gate inputs via "
                "truth_ownership dimension of DelegatedFlowReadinessGate."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Android Evaluator Artifact Ingestion (PR-4V2-GOV)",
            classification=EvidenceClassification.companion_repo.value,
            evidence_status="unavailable",
            evidence_summary=f"AndroidEvaluatorArtifactRegistry unavailable: {exc}",
            code_reference=code_ref,
            test_reference=test_ref,
            notes="Module import failed; ensure core.android_evaluator_artifact_ingress is importable.",
        )


def _probe_takeover_tracking() -> EvidenceDimensionEntry:
    """Probe TakeoverTrackingRuntime."""
    dim_id = "takeover_tracking"
    code_ref = "core.takeover_tracking.TakeoverTrackingRuntime"
    test_ref = "tests/test_android_takeover_protocol.py, tests/test_android_delegated_runtime_audit.py"
    try:
        from core.takeover_tracking import get_takeover_tracking_runtime
        runtime = get_takeover_tracking_runtime()
        snap = runtime.snapshot() if hasattr(runtime, "snapshot") else []
        total = len(snap)
        accepted = sum(1 for r in snap if getattr(r, "was_accepted", False))
        rejected = total - accepted
        summary = (
            f"TakeoverTrackingRuntime: {total} record(s); "
            f"{accepted} accepted, {rejected} rejected/unknown"
        )
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Takeover Request/Response Tracking",
            classification=EvidenceClassification.canonical.value,
            evidence_status="present",
            evidence_summary=summary,
            code_reference=code_ref,
            test_reference=test_ref,
            raw_evidence={"total": total, "accepted": accepted, "rejected": rejected},
            notes=(
                "Ring buffer is empty at startup; populates as Android devices "
                "respond to V2-issued takeover requests.  Records are canonical "
                "audit evidence for takeover lifecycle correctness."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Takeover Request/Response Tracking",
            classification=EvidenceClassification.canonical.value,
            evidence_status="unavailable",
            evidence_summary=f"TakeoverTrackingRuntime unavailable: {exc}",
            code_reference=code_ref,
            test_reference=test_ref,
        )


def _probe_android_delegated_audit() -> EvidenceDimensionEntry:
    """Probe AndroidDelegatedRuntimeAuditRecorder."""
    dim_id = "android_delegated_runtime_audit"
    code_ref = "core.android_delegated_runtime_audit.AndroidDelegatedRuntimeAuditRecorder"
    test_ref = "tests/test_android_delegated_runtime_audit.py"
    try:
        from core.android_delegated_runtime_audit import android_audit_snapshot
        snap = android_audit_snapshot()
        total = len(snap)
        summary = (
            f"AndroidDelegatedRuntimeAuditRecorder: {total} record(s) in ring buffer"
        )
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Android Delegated Runtime Audit Records",
            classification=EvidenceClassification.advisory.value,
            evidence_status="present",
            evidence_summary=summary,
            code_reference=code_ref,
            test_reference=test_ref,
            raw_evidence={"total_records": total},
            notes=(
                "Advisory: audit ring provides observability and debugging context "
                "for the full handoff/takeover/reconciliation chain but MUST NOT "
                "be used as a release gate input.  Use TakeoverTrackingRuntime "
                "and the delegated flow readiness/acceptance gates for gate decisions."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Android Delegated Runtime Audit Records",
            classification=EvidenceClassification.advisory.value,
            evidence_status="unavailable",
            evidence_summary=f"AndroidDelegatedRuntimeAuditRecorder unavailable: {exc}",
            code_reference=code_ref,
            test_reference=test_ref,
        )


def _probe_continuity_recovery_closure() -> EvidenceDimensionEntry:
    """Probe RecoveryDurabilityClosureValidator (PR-5V2)."""
    dim_id = "continuity_recovery_closure"
    code_ref = "core.recovery_durability_closure_validator.RecoveryClosureReport"
    test_ref = "tests/test_pr534_continuity_recovery_durability_closure.py"
    try:
        from core.recovery_durability_closure_validator import (
            build_recovery_closure_report,
            RecoveryScenarioStatus,
        )
        closure_report = build_recovery_closure_report()
        all_closed = getattr(closure_report, "all_closed", False)
        total_scenarios = len(getattr(closure_report, "scenarios", []))
        fail_closed_count = sum(
            1 for s in getattr(closure_report, "scenarios", [])
            if getattr(s, "status", None) == RecoveryScenarioStatus.fail_closed
        )
        deferred_count = sum(
            1 for s in getattr(closure_report, "scenarios", [])
            if getattr(s, "status", None) == RecoveryScenarioStatus.deferred
        )
        summary = (
            f"RecoveryClosureReport: {total_scenarios} scenario(s); "
            f"all_closed={all_closed}; fail_closed={fail_closed_count}; "
            f"deferred={deferred_count}"
        )
        status = "present"
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Continuity / Recovery / Durability Closure (PR-5V2)",
            classification=EvidenceClassification.canonical.value,
            evidence_status=status,
            evidence_summary=summary,
            code_reference=code_ref,
            test_reference=test_ref,
            raw_evidence={
                "all_closed": all_closed,
                "total_scenarios": total_scenarios,
                "fail_closed_count": fail_closed_count,
                "deferred_count": deferred_count,
            },
            notes=(
                "Deferred scenarios (offline queue ordering) are documented "
                "explicitly in the closure report with deferral reason."
            ) if deferred_count > 0 else "",
        )
    except Exception as exc:  # noqa: BLE001
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Continuity / Recovery / Durability Closure (PR-5V2)",
            classification=EvidenceClassification.canonical.value,
            evidence_status="unavailable",
            evidence_summary=f"RecoveryDurabilityClosureValidator unavailable: {exc}",
            code_reference=code_ref,
            test_reference=test_ref,
        )


def _probe_compat_legacy_blocking() -> EvidenceDimensionEntry:
    """Probe CompatLegacyPathBlockingCanonicalization (PR-8V2)."""
    dim_id = "compat_legacy_blocking"
    code_ref = "core.compat_legacy_path_blocking_canonicalization"
    test_ref = "tests/test_pr10_v2_delegated_flow_acceptance_gate.py"
    try:
        from core.compat_legacy_path_blocking_canonicalization import (
            get_compat_blocking_snapshot,
        )
        snap = get_compat_blocking_snapshot()
        has_active_bypass = getattr(snap, "has_active_bypass", None)
        total_vectors = getattr(snap, "total_vectors_evaluated", 0)
        blocked = getattr(snap, "blocked_vector_count", 0)
        summary = (
            f"CompatLegacyPathBlocking: {total_vectors} vector(s) evaluated; "
            f"active_bypass={has_active_bypass}; blocked={blocked}"
        )
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Compat / Legacy Path Blocking (PR-8V2)",
            classification=EvidenceClassification.canonical.value,
            evidence_status="present",
            evidence_summary=summary,
            code_reference=code_ref,
            test_reference=test_ref,
            raw_evidence={
                "has_active_bypass": has_active_bypass,
                "total_vectors": total_vectors,
                "blocked": blocked,
            },
        )
    except Exception as exc:  # noqa: BLE001
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Compat / Legacy Path Blocking (PR-8V2)",
            classification=EvidenceClassification.canonical.value,
            evidence_status="unavailable",
            evidence_summary=f"CompatLegacyPathBlockingCanonicalization unavailable: {exc}",
            code_reference=code_ref,
            test_reference=test_ref,
        )


def _probe_participant_session_truth() -> EvidenceDimensionEntry:
    """Probe AndroidParticipantSessionState truth store."""
    dim_id = "participant_session_truth"
    code_ref = "core.android_participant_session_state.AndroidParticipantSessionRegistry"
    test_ref = "tests/test_android_delegated_runtime_structural_consolidation.py"
    try:
        from core.android_participant_session_state import (
            get_participant_session_registry,
        )
        registry = get_participant_session_registry()
        snap = registry.snapshot() if hasattr(registry, "snapshot") else []
        total = len(snap)
        summary = f"ParticipantSessionRegistry: {total} session record(s)"
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Android Participant Session Truth (reconciliation state)",
            classification=EvidenceClassification.advisory.value,
            evidence_status="present",
            evidence_summary=summary,
            code_reference=code_ref,
            test_reference=test_ref,
            raw_evidence={"total_sessions": total},
            notes=(
                "Advisory: session state supports reconciliation bookkeeping "
                "and debugging.  Phase transitions feed into lifecycle coordinator "
                "outcomes which are canonical; the raw session registry itself "
                "is observational."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Android Participant Session Truth (reconciliation state)",
            classification=EvidenceClassification.advisory.value,
            evidence_status="unavailable",
            evidence_summary=f"ParticipantSessionRegistry unavailable: {exc}",
            code_reference=code_ref,
            test_reference=test_ref,
        )

def _probe_delegated_flow_decision_history() -> "EvidenceDimensionEntry":
    """Probe DelegatedFlowDecisionHistory (PR-V2-4DH)."""
    dim_id = "delegated_flow_decision_history"
    code_ref = "core.delegated_flow_decision_history.DelegatedFlowDecisionHistory"
    test_ref = "tests/test_pr_v2_delegated_flow_decision_history.py"
    try:
        from core.delegated_flow_decision_history import (
            get_decision_history,
            evaluate_delegated_flow_history,
        )
        h_report = evaluate_delegated_flow_history()
        evidence_status_val = h_report.evidence_status.value
        summary = (
            f"DelegatedFlowDecisionHistory: status={evidence_status_val!r}; "
            f"total_entries={h_report.total_entries}; "
            f"structure_present={h_report.structure_present}; "
            f"runtime_closure_established={h_report.runtime_closure_established}"
        )
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Delegated Flow Decision History / Evidence Closure (PR-V2-4DH)",
            classification=EvidenceClassification.canonical.value,
            evidence_status="present",
            evidence_summary=summary,
            code_reference=code_ref,
            test_reference=test_ref,
            raw_evidence=h_report.to_dict(),
            notes=(
                "Five-tier history status: no_history_yet / insufficient_evidence / "
                "observed_but_incomplete / observed_and_closed / historical_evidence_stale.  "
                "runtime_closure_established=True only when status=observed_and_closed.  "
                "structure_present reflects static deployment availability, not run history."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Delegated Flow Decision History / Evidence Closure (PR-V2-4DH)",
            classification=EvidenceClassification.canonical.value,
            evidence_status="unavailable",
            evidence_summary=f"DelegatedFlowDecisionHistory unavailable: {exc}",
            code_reference=code_ref,
            test_reference=test_ref,
            notes="Module import failed; ensure core.delegated_flow_decision_history is importable.",
        )


def _probe_recovery_truth_surface() -> "EvidenceDimensionEntry":
    """Probe RecoveryTruthSurface (PR-5-TRUTH)."""
    dim_id = "recovery_truth_surface"
    code_ref = "core.recovery_truth_surface.build_recovery_truth_report"
    test_ref = "tests/test_recovery_truth_surface.py"
    try:
        from core.recovery_truth_surface import (
            build_recovery_truth_report,
            RECOVERY_TRUTH_SURFACE_AUTHORITY,
        )
        report = build_recovery_truth_report()
        report_dict = report.to_dict()
        open_dims = report_dict.get("open_dimensions", [])
        deferred_dims = report_dict.get("deferred_dimensions", [])
        closed_dims = report_dict.get("closed_dimensions", [])
        v2_ok = report_dict.get("v2_internal_success", False)
        p_ok = report_dict.get("participant_reconnect_success", False)
        tc_ok = report_dict.get("task_continuity_success", False)
        aa_ok = report_dict.get("authority_alignment_success", False)
        total_entries = len(report_dict.get("entries", []))
        summary = (
            f"RecoveryTruthSurface: {total_entries} truth atoms evaluated; "
            f"closed={len(closed_dims)}, open={len(open_dims)}, "
            f"deferred={len(deferred_dims)}.  "
            f"Layer results: v2_internal={v2_ok}, "
            f"participant_reconnect={p_ok}, "
            f"task_continuity={tc_ok}, "
            f"authority_alignment={aa_ok}."
        )
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name=(
                "Recovery Truth Surface — reconnect / redispatch / "
                "continuity structured evidence (PR-5-TRUTH)"
            ),
            classification=EvidenceClassification.canonical.value,
            evidence_status="present",
            evidence_summary=summary,
            code_reference=code_ref,
            test_reference=test_ref,
            raw_evidence={
                "total_entries": total_entries,
                "closed_dimensions": closed_dims,
                "open_dimensions": open_dims,
                "deferred_dimensions": deferred_dims,
                "v2_internal_success": v2_ok,
                "participant_reconnect_success": p_ok,
                "task_continuity_success": tc_ok,
                "authority_alignment_success": aa_ok,
            },
            notes=(
                "Six truth atoms (participant_disconnect_observed, "
                "reconnect_observed, redispatch_triggered, "
                "in_flight_task_continuity_preserved, "
                "duplicate_dispatch_avoided, recovered_state_aligned) "
                "across four recovery levels.  "
                "Deferred boundaries: Android offline queue replay ordering, "
                "ephemeral transport binding identity.  "
                "'partial' status = structural wiring verified, no live event "
                "in this process instance (honest, not a failure)."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name=(
                "Recovery Truth Surface — reconnect / redispatch / "
                "continuity structured evidence (PR-5-TRUTH)"
            ),
            classification=EvidenceClassification.canonical.value,
            evidence_status="unavailable",
            evidence_summary=f"RecoveryTruthSurface unavailable: {exc}",
            code_reference=code_ref,
            test_reference=test_ref,
            notes="Module import failed; ensure core.recovery_truth_surface is importable.",
        )


def _probe_canonical_cross_repo_pipeline() -> "EvidenceDimensionEntry":
    """Probe the canonical cross-repo evidence ingestion pipeline (PR-05)."""
    dim_id = "canonical_cross_repo_evidence_pipeline"
    code_ref = (
        "core.canonical_cross_repo_evidence_pipeline."
        "CanonicalCrossRepoEvidencePipeline"
    )
    test_ref = "tests/test_canonical_cross_repo_evidence_pipeline.py"
    try:
        from core.canonical_cross_repo_evidence_pipeline import (
            build_canonical_cross_repo_evidence_report,
            PipelineVerdict,
            CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY,
        )
        report = build_canonical_cross_repo_evidence_report()
        verdict_val = report.pipeline_verdict.value
        source_statuses = {
            s.source_id.value: s.status.value for s in report.sources
        }
        summary = (
            f"CanonicalCrossRepoEvidencePipeline: verdict={verdict_val}; "
            f"is_complete={report.is_complete}; "
            f"primary_complete={report.primary_sources_complete}; "
            f"primary_fresh={report.primary_sources_fresh}; "
            f"sources={source_statuses}"
        )
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name=(
                "Canonical Cross-Repo Evidence Ingestion Pipeline (PR-05)"
            ),
            classification=EvidenceClassification.canonical.value,
            evidence_status="present",
            evidence_summary=summary,
            code_reference=code_ref,
            test_reference=test_ref,
            raw_evidence=report.to_dict(),
            notes=(
                "Unified canonical pipeline that converges all cross-repo "
                "evidence surfaces (real-device verification, readiness "
                "evaluator artifacts, participant lifecycle truth, task-result "
                "runtime, delegated runtime audit) into a single "
                "final-acceptance-ready report with explicit authority, "
                "freshness, completeness, and stale-handling semantics.  "
                "verdict=complete only when all PRIMARY sources are present "
                "and fresh.  "
                + (
                    "Pipeline not fully closed — verdict=" + verdict_val + ".  "
                    "Downgrade reasons: " + "; ".join(report.downgrade_reasons) + ".  "
                    if report.downgrade_reasons else
                    "Pipeline verdict: " + verdict_val + ".  "
                )
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return EvidenceDimensionEntry(
            dimension_id=dim_id,
            display_name="Canonical Cross-Repo Evidence Ingestion Pipeline (PR-05)",
            classification=EvidenceClassification.canonical.value,
            evidence_status="unavailable",
            evidence_summary=(
                f"CanonicalCrossRepoEvidencePipeline unavailable: {exc}"
            ),
            code_reference=code_ref,
            test_reference=test_ref,
            notes=(
                "Module import failed; ensure "
                "core/canonical_cross_repo_evidence_pipeline.py is present."
            ),
        )


# ---------------------------------------------------------------------------
# V2ReadinessGovernanceEvidenceSurface
# ---------------------------------------------------------------------------


class V2ReadinessGovernanceEvidenceSurface:
    """Assembles the V2 canonical readiness / governance evidence surface.

    This class is a stateless builder; call :meth:`build` to produce a fresh
    :class:`EvidenceSurfaceReport`.  The module-level singletons
    :func:`get_evidence_surface_report` and
    :func:`build_evidence_surface_report` are the recommended entry points.
    """

    #: Ordered list of (probe_function, deferred_note_if_unavailable_is_ok)
    _PROBES = [
        (_probe_delegated_flow_readiness, None),
        (_probe_delegated_flow_acceptance, None),
        (_probe_post_graduation_governance, None),
        (_probe_android_evaluator_artifacts, None),
        (_probe_takeover_tracking, None),
        (_probe_android_delegated_audit, None),
        (_probe_continuity_recovery_closure, None),
        (_probe_compat_legacy_blocking, None),
        (_probe_participant_session_truth, None),
        (_probe_delegated_flow_decision_history, None),
        (_probe_recovery_truth_surface, None),
        (_probe_canonical_cross_repo_pipeline, None),
    ]

    _DEFERRED_NOTES: List[str] = [
        (
            "DEFERRED: Final release-gate CI enforcement (blocking PR merges on "
            "evidence failure) is deferred to a later PR.  This surface provides "
            "the evidence layer that future CI gates can build on."
        ),
        (
            "DEFERRED: Android offline queue ordering authority is deferred to a "
            "later PR (documented in RecoveryClosureReport RS-16 scenario and "
            "RecoveryTruthSurface OFFLINE_QUEUE_REPLAY_ORDERING_IS_DEFERRED_TRUTH_POLICY)."
        ),
        (
            "DEFERRED: Formal default-on / rollout promotion policy for the "
            "delegated canonical path is deferred; the acceptance and governance "
            "gates provide the evidence foundation for that decision."
        ),
        (
            "DEFERRED: Ephemeral transport binding identity proof (whether the "
            "reconnected session is provably the same participant via "
            "cryptographic/token-based identity) is deferred "
            "(RecoveryTruthSurface EPHEMERAL_TRANSPORT_BINDING_IS_DEFERRED_TRUTH_POLICY)."
        ),
        (
            "DEFERRED: Multi-device simultaneous reconnect ordering authority "
            "is deferred; the RecoveryTruthSurface records this boundary "
            "explicitly as deferred rather than closed."
        ),
    ]

    def build(self) -> EvidenceSurfaceReport:
        """Run all probes and return a fresh :class:`EvidenceSurfaceReport`."""
        dimensions: List[EvidenceDimensionEntry] = []
        for probe_fn, _ in self._PROBES:
            try:
                entry = probe_fn()
            except Exception as exc:  # noqa: BLE001  pragma: no cover
                logger.warning("EvidenceSurface: probe %s raised: %s", probe_fn.__name__, exc)
                continue
            dimensions.append(entry)

        canonical_count = sum(
            1 for d in dimensions if d.classification == EvidenceClassification.canonical.value
        )
        advisory_count = sum(
            1 for d in dimensions if d.classification == EvidenceClassification.advisory.value
        )
        companion_count = sum(
            1 for d in dimensions if d.classification == EvidenceClassification.companion_repo.value
        )
        present_count = sum(1 for d in dimensions if d.evidence_status == "present")
        absent_count = sum(1 for d in dimensions if d.evidence_status == "absent")
        unavailable_count = sum(
            1 for d in dimensions if d.evidence_status in ("unavailable", "unknown")
        )
        canonical_dims = [
            d for d in dimensions if d.classification == EvidenceClassification.canonical.value
        ]
        all_canonical_present = all(
            d.evidence_status == "present" for d in canonical_dims
        ) if canonical_dims else False

        return EvidenceSurfaceReport(
            report_id=str(uuid.uuid4()),
            generated_at=time.time(),
            authority=V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_AUTHORITY,
            dimensions=dimensions,
            canonical_count=canonical_count,
            advisory_count=advisory_count,
            companion_repo_count=companion_count,
            present_count=present_count,
            absent_count=absent_count,
            unavailable_count=unavailable_count,
            all_canonical_present=all_canonical_present,
            deferred_notes=list(self._DEFERRED_NOTES),
        )


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

_SURFACE_LOCK = threading.Lock()
_cached_report: Optional[EvidenceSurfaceReport] = None


def build_evidence_surface_report() -> EvidenceSurfaceReport:
    """Build and return a fresh :class:`EvidenceSurfaceReport` (not cached).

    Every call runs all probes against the current live module state.
    """
    return V2ReadinessGovernanceEvidenceSurface().build()


def get_evidence_surface_report() -> EvidenceSurfaceReport:
    """Return a cached :class:`EvidenceSurfaceReport`, building if needed.

    The cache is invalidated by :func:`reset_evidence_surface_report`.
    Use :func:`build_evidence_surface_report` when a fresh snapshot is
    required (e.g. in CI).
    """
    global _cached_report
    with _SURFACE_LOCK:
        if _cached_report is None:
            _cached_report = V2ReadinessGovernanceEvidenceSurface().build()
        return _cached_report


def reset_evidence_surface_report() -> None:
    """Invalidate the cached report.  Intended for test isolation only."""
    global _cached_report
    with _SURFACE_LOCK:
        _cached_report = None
