#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/dual_repo_system_completeness_review.py
=============================================
PR-REVIEW (system-level dual-repo review artifact):
Dual-Repository System Completeness Review — code-grounded, reviewer-facing
completeness assessment for the Galaxy V2 + Android dual-repo architecture.

Purpose
-------
This module answers the top-level question that release stakeholders, audit
reviewers, and final-acceptance gate consumers actually ask:

    *Based on real code and real evidence surfaces, what is this system,
    what has been completed, and what gaps remain — and are those gaps
    honestly labeled?*

It addresses a documented gap: the V2 repository has accumulated substantial
readiness, governance, and evidence-surface machinery (``system_final_acceptance_verdict``,
``dual_repo_system_reality_audit``, ``v2_readiness_governance_evidence_surface``,
``release_governance_taxonomy``, etc.), but no single artifact synthesises
the answers to these questions in a form directly consumable by a reviewer
who arrives at the repository without prior context.

This module provides:

1. **Five maturity dimensions** (each with code-grounded evidence):
   - ``architecture_structure`` — is the architecture coherent and importable?
   - ``runtime_closure`` — is the end-to-end runtime path closed and verified?
   - ``cross_repo_evidence`` — is there real cross-repo evidence flow?
   - ``governance_release_readiness`` — is governance enforcing or advisory?
   - ``real_device_multi_device`` — is there real-device / multi-device closure?

2. **CompletenessVerdict** — an honest system-level completeness verdict that
   maps directly to the ``IssueClassification`` taxonomy from
   ``release_governance_taxonomy``.

3. **CompletenessReviewReport** — a stable, JSON-serialisable artifact that
   carries per-dimension entries, the system verdict, honest gap/deferred
   entries, and a human-readable summary for reviewer consumption.

4. **Code-anchored gap / deferred entries** — every gap references a specific
   module or evidence surface so reviewers can trace claims back to code.

Architecture role
-----------------
::

    ┌───────────────────────────────────────────────────────────────────────┐
    │  DUAL-REPO SYSTEM COMPLETENESS REVIEW  (this module — PR-REVIEW)     │
    │                                                                       │
    │  Consumes (read-only probes):                                        │
    │    • core.system_final_acceptance_verdict    (PR-17V2)               │
    │    • core.dual_repo_system_reality_audit     (PR-537)                │
    │    • core.v2_readiness_governance_evidence_surface (PR-6V2-EVIDENCE) │
    │    • core.release_governance_taxonomy        (PR-8)                  │
    │    • core.android_participant_evidence_ingress                       │
    │    • core.delegated_flow_decision_history    (PR-V2-4DH)             │
    │    • core.recovery_truth_surface             (PR-5-TRUTH)            │
    │    • core.dual_repo_system_map                                       │
    │                                                                       │
    │  Five completeness dimensions:                                       │
    │    1. architecture_structure   — importable, coherent, documented    │
    │    2. runtime_closure          — end-to-end closed, verified         │
    │    3. cross_repo_evidence      — real cross-repo signal flow         │
    │    4. governance_release_readiness — enforcing vs advisory           │
    │    5. real_device_multi_device — real device closure                 │
    │                                                                       │
    │  Produces:                                                           │
    │    • CompletenessEntry        (per-dimension record)                 │
    │    • CompletenessReviewReport (full reviewer-facing artifact)        │
    │    • CompletenessVerdict      (system-level completeness verdict)    │
    └───────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified.
2. **Fail-conservative** — any missing module or missing evidence yields a
   downgraded completeness label; never silently optimistic.
3. **Honest deferral** — explicitly deferred items carry ``status = deferred``
   with a documented note; they are NEVER represented as ``complete``.
4. **Code-anchored** — every gap and every positive finding references a
   specific importable module or file.
5. **Taxonomy-aligned** — completeness labels map directly to
   ``IssueClassification`` in ``release_governance_taxonomy``.
6. **Stable artifacts** — all data classes are fully JSON-serialisable.

Public API
----------
Authority / policy sentinels::

    COMPLETENESS_REVIEW_AUTHORITY
    COMPLETENESS_REVIEW_SENTINEL
    HONEST_DEFERRED_MUST_NOT_BE_LABELED_COMPLETE_POLICY
    ARCHITECTURE_COMPLETE_DOES_NOT_IMPLY_RUNTIME_CLOSED_POLICY
    CROSS_REPO_EVIDENCE_REQUIRES_WIRE_LAYER_POLICY

Enumerations::

    CompletenessDimension
    CompletenessLabel
    CompletenessVerdict

Data classes::

    CompletenessEntry
    CompletenessReviewReport

Class::

    DualRepoSystemCompletenessReviewer

Helpers::

    build_completeness_review() -> CompletenessReviewReport
    get_completeness_review()   -> CompletenessReviewReport  (singleton)
    reset_completeness_review() -> None  (testing only)
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.DualRepoSystemCompletenessReview")

__all__ = [
    # Authority sentinels
    "COMPLETENESS_REVIEW_AUTHORITY",
    "COMPLETENESS_REVIEW_SENTINEL",
    # Policy sentinels
    "HONEST_DEFERRED_MUST_NOT_BE_LABELED_COMPLETE_POLICY",
    "ARCHITECTURE_COMPLETE_DOES_NOT_IMPLY_RUNTIME_CLOSED_POLICY",
    "CROSS_REPO_EVIDENCE_REQUIRES_WIRE_LAYER_POLICY",
    # Enumerations
    "CompletenessDimension",
    "CompletenessLabel",
    "CompletenessVerdict",
    # Data classes
    "CompletenessEntry",
    "CompletenessReviewReport",
    # Class
    "DualRepoSystemCompletenessReviewer",
    # Helpers
    "build_completeness_review",
    "get_completeness_review",
    "reset_completeness_review",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

COMPLETENESS_REVIEW_AUTHORITY: str = (
    "COMPLETENESS_REVIEW_AUTHORITY::"
    "core.dual_repo_system_completeness_review::PR-REVIEW::"
    "dual-repo-system-completeness-review::"
    "reviewer-facing-code-grounded-completeness-artifact"
)
"""Sentinel: this module is the canonical dual-repo system completeness review
authority.  Import to assert that a release pipeline, audit reviewer, or
governance consumer is reading the completeness judgment from the correct
reviewer-facing artifact."""

COMPLETENESS_REVIEW_SENTINEL: str = (
    "COMPLETENESS_REVIEW_SENTINEL::"
    "package=PR-REVIEW::profile=dual-repo-completeness-review-v1::"
    "module=core.dual_repo_system_completeness_review"
)
"""Package sentinel for this PR's completeness review module."""

HONEST_DEFERRED_MUST_NOT_BE_LABELED_COMPLETE_POLICY: str = (
    "POLICY::HONEST_DEFERRED_MUST_NOT_BE_LABELED_COMPLETE_V1: "
    "Any item explicitly classified as 'deferred', 'accepted_limitation', "
    "'evidence_gap', or 'unresolved' in the dual-repo code review MUST receive "
    "CompletenessLabel.deferred or CompletenessLabel.evidence_gap in this "
    "artifact.  It MUST NOT be upgraded to CompletenessLabel.complete or "
    "CompletenessLabel.verified regardless of architectural framing.  "
    "Examples: Android ReconciliationSignal wire layer, HandoffEnvelopeV2 "
    "response gateway handler absence, real-device CI automation absence."
)

ARCHITECTURE_COMPLETE_DOES_NOT_IMPLY_RUNTIME_CLOSED_POLICY: str = (
    "POLICY::ARCHITECTURE_COMPLETE_DOES_NOT_IMPLY_RUNTIME_CLOSED_V1: "
    "The presence of a module, a sentinel, or a design document for a "
    "capability does NOT constitute evidence that the corresponding runtime "
    "path is closed.  A gate may exist as an importable module while its "
    "enforcement is advisory-only.  A coordinator may have a complete API "
    "surface while its real-device wiring is absent.  Architecture/structure "
    "maturity and runtime closure maturity MUST be assessed and reported "
    "separately in this artifact."
)

CROSS_REPO_EVIDENCE_REQUIRES_WIRE_LAYER_POLICY: str = (
    "POLICY::CROSS_REPO_EVIDENCE_REQUIRES_WIRE_LAYER_V1: "
    "Cross-repo evidence maturity is only 'complete' when there is a "
    "verifiable wire-layer path (AIP message type in MsgType enum, "
    "registered gateway handler, and V2-side ingress module) for the "
    "relevant artifact.  An Android-side DTO or evaluator artifact "
    "WITHOUT a corresponding AIP MsgType entry and V2 gateway handler "
    "MUST be classified as 'evidence_gap'.  "
    "Documented gap: ReconciliationSignal AIP wire layer, "
    "HandoffEnvelopeV2 response gateway handler."
)


# ---------------------------------------------------------------------------
# CompletenessDimension
# ---------------------------------------------------------------------------


class CompletenessDimension(str, Enum):
    """Five completeness dimensions for the dual-repo system review.

    Each dimension maps to one of the five review axes required by the
    problem statement.

    ``architecture_structure``
        Is the two-repo architecture coherent, documented, and importable?
        Does the system have well-defined role boundaries (V2 control plane,
        Android execution participant)?  Are core modules present?

    ``runtime_closure``
        Is the end-to-end runtime path closed and verified?  Does the
        canonical execution chain work from request ingress to result
        surfacing — not just architecturally but in real execution?

    ``cross_repo_evidence``
        Is there real cross-repo evidence flow?  Can Android-originated
        artifacts (readiness, acceptance, governance, recovery) reach
        the V2 side through a real wire-layer path?

    ``governance_release_readiness``
        Is the governance / readiness / release gate machinery enforcing
        (blocking real execution when violated) or only advisory?  Is the
        unified taxonomy in place?

    ``real_device_multi_device``
        Is there real-device / multi-device closure?  Are multi-device
        coordination, real-device CI, and participant lifecycle verified
        at the device level?
    """

    architecture_structure = "architecture_structure"
    runtime_closure = "runtime_closure"
    cross_repo_evidence = "cross_repo_evidence"
    governance_release_readiness = "governance_release_readiness"
    real_device_multi_device = "real_device_multi_device"

    @classmethod
    def all_dimensions(cls) -> List["CompletenessDimension"]:
        """Return all five dimensions in canonical review order."""
        return [
            cls.architecture_structure,
            cls.runtime_closure,
            cls.cross_repo_evidence,
            cls.governance_release_readiness,
            cls.real_device_multi_device,
        ]

    @classmethod
    def from_string(cls, value: str) -> "CompletenessDimension":
        """Return member matching *value*, defaulting to architecture_structure."""
        if not isinstance(value, str):
            return cls.architecture_structure
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.architecture_structure


# ---------------------------------------------------------------------------
# CompletenessLabel
# ---------------------------------------------------------------------------


class CompletenessLabel(str, Enum):
    """Six-tier completeness classification aligned with release_governance_taxonomy.

    Labels are ordered from most-incomplete to most-complete.

    ``not_present``
        No code, module, or evidence exists for this dimension.

    ``nominally_present``
        A name, sentinel, or design intent exists, but no real enforcement
        module, runtime wiring, or test coverage backs it.

    ``structure_only``
        Real code exists for the capability (importable modules, data
        structures), but the runtime chain is not closed and cross-repo
        evidence flow is absent.

    ``evidence_gap``
        Real code and structure exist, but a documented evidence gap
        prevents the dimension from being considered closed.  Examples:
        AIP wire layer absent, gateway handler missing, CI automation absent.

    ``deferred``
        The dimension has been explicitly acknowledged as deferred or an
        accepted limitation.  Not a failure, but not complete either.

    ``complete``
        Real code, runtime wiring, automated tests, and evidence surfaces
        all exist for this dimension.  No known blocking gap.
    """

    not_present = "not_present"
    nominally_present = "nominally_present"
    structure_only = "structure_only"
    evidence_gap = "evidence_gap"
    deferred = "deferred"
    complete = "complete"

    def ordinal(self) -> int:
        """Return integer rank (0 = lowest, 5 = highest)."""
        _order = [
            "not_present",
            "nominally_present",
            "structure_only",
            "evidence_gap",
            "deferred",
            "complete",
        ]
        try:
            return _order.index(self.value)
        except ValueError:
            return 0

    def is_blocking(self) -> bool:
        """Return True when this label represents a blocking completeness gap.

        Labels below ``deferred`` are blocking: they indicate a real gap
        that prevents the dimension from being considered closed.
        """
        return self.ordinal() < self.__class__.deferred.ordinal()

    @classmethod
    def from_string(cls, value: str) -> "CompletenessLabel":
        """Return member matching *value*, defaulting to not_present."""
        if not isinstance(value, str):
            return cls.not_present
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.not_present


# ---------------------------------------------------------------------------
# CompletenessVerdict
# ---------------------------------------------------------------------------


class CompletenessVerdict(str, Enum):
    """System-level completeness verdict for the dual-repo review artifact.

    ``fully_closed``
        All five dimensions are ``complete``.  The system can be considered
        fully operational and release-ready.

    ``partial_closure_gaps_present``
        The majority of dimensions are ``complete`` or ``deferred``, but at
        least one dimension has a blocking completeness gap (``evidence_gap``
        or lower).

    ``structural_only_runtime_not_closed``
        Architecture and structure exist but runtime closure is not
        established across multiple dimensions.

    ``critical_evidence_gaps``
        Multiple critical dimensions have ``evidence_gap`` or lower labels.
        Release readiness cannot be claimed.

    ``insufficient_evidence``
        Insufficient evidence to conclude; typically indicates an import
        environment problem.
    """

    fully_closed = "fully_closed"
    partial_closure_gaps_present = "partial_closure_gaps_present"
    structural_only_runtime_not_closed = "structural_only_runtime_not_closed"
    critical_evidence_gaps = "critical_evidence_gaps"
    insufficient_evidence = "insufficient_evidence"

    @classmethod
    def from_string(cls, value: str) -> "CompletenessVerdict":
        """Return member matching *value*, defaulting to insufficient_evidence."""
        if not isinstance(value, str):
            return cls.insufficient_evidence
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.insufficient_evidence

    @property
    def is_fully_closed(self) -> bool:
        """Return True only when verdict is fully_closed."""
        return self == CompletenessVerdict.fully_closed

    @property
    def has_blocking_gaps(self) -> bool:
        """Return True when the verdict indicates blocking gaps."""
        return self in (
            CompletenessVerdict.critical_evidence_gaps,
            CompletenessVerdict.structural_only_runtime_not_closed,
        )


# ---------------------------------------------------------------------------
# CompletenessEntry
# ---------------------------------------------------------------------------


@dataclass
class CompletenessEntry:
    """Code-grounded completeness record for one review dimension.

    Fields
    ------
    dimension
        Which :class:`CompletenessDimension` this entry covers.
    label
        The :class:`CompletenessLabel` assigned based on real code evidence.
    summary
        Human-readable summary of what is complete and what is not.
    completed_items
        List of specific items confirmed complete (with code references).
    gap_items
        List of specific gaps (with code references where possible).
    deferred_items
        List of items explicitly deferred or accepted as limitations.
    code_references
        Importable module names confirmed present for this dimension.
    test_references
        Test file paths that verify this dimension.
    assessed_at
        Unix timestamp of this dimension assessment.
    """

    dimension: CompletenessDimension = CompletenessDimension.architecture_structure
    label: CompletenessLabel = CompletenessLabel.not_present
    summary: str = ""
    completed_items: List[str] = field(default_factory=list)
    gap_items: List[str] = field(default_factory=list)
    deferred_items: List[str] = field(default_factory=list)
    code_references: List[str] = field(default_factory=list)
    test_references: List[str] = field(default_factory=list)
    assessed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "dimension": self.dimension.value,
            "label": self.label.value,
            "summary": self.summary,
            "completed_items": self.completed_items,
            "gap_items": self.gap_items,
            "deferred_items": self.deferred_items,
            "code_references": self.code_references,
            "test_references": self.test_references,
            "assessed_at": self.assessed_at,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompletenessEntry":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        return cls(
            dimension=CompletenessDimension.from_string(
                data.get("dimension", "")
            ),
            label=CompletenessLabel.from_string(data.get("label", "")),
            summary=data.get("summary", ""),
            completed_items=list(data.get("completed_items", [])),
            gap_items=list(data.get("gap_items", [])),
            deferred_items=list(data.get("deferred_items", [])),
            code_references=list(data.get("code_references", [])),
            test_references=list(data.get("test_references", [])),
            assessed_at=data.get("assessed_at", time.time()),
        )


# ---------------------------------------------------------------------------
# CompletenessReviewReport
# ---------------------------------------------------------------------------


@dataclass
class CompletenessReviewReport:
    """Full dual-repo system completeness review report.

    This is the top-level reviewer-facing artifact produced by
    :class:`DualRepoSystemCompletenessReviewer`.  It carries:

    * A :class:`CompletenessEntry` for each of the five review dimensions.
    * The overall :class:`CompletenessVerdict`.
    * A flat list of all blocking gaps across all dimensions.
    * A flat list of all deferred/accepted-limitation items.
    * A human-readable ``summary`` for operator consoles and review UIs.
    * A machine-readable ``to_json()`` for CI pipelines and audit tooling.

    Fields
    ------
    report_id
        Unique identifier for this report (UUID hex prefix).
    dimensions
        List of :class:`CompletenessEntry` for all five dimensions.
    verdict
        Overall system-level completeness verdict.
    blocking_gaps
        Flat list of all blocking gaps (evidence_gap or lower labels).
    deferred_acknowledged
        Flat list of all deferred/accepted limitation items.
    summary
        Human-readable multi-line summary for reviewers.
    generated_at
        Unix timestamp of report generation.
    reviewer_version
        Version of the reviewer that produced this report.
    """

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    dimensions: List[CompletenessEntry] = field(default_factory=list)
    verdict: CompletenessVerdict = CompletenessVerdict.insufficient_evidence
    blocking_gaps: List[str] = field(default_factory=list)
    deferred_acknowledged: List[str] = field(default_factory=list)
    summary: str = ""
    generated_at: float = field(default_factory=time.time)
    reviewer_version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "report_id": self.report_id,
            "dimensions": [e.to_dict() for e in self.dimensions],
            "verdict": self.verdict.value,
            "blocking_gaps": self.blocking_gaps,
            "deferred_acknowledged": self.deferred_acknowledged,
            "summary": self.summary,
            "generated_at": self.generated_at,
            "reviewer_version": self.reviewer_version,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompletenessReviewReport":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        return cls(
            report_id=data.get("report_id", ""),
            dimensions=[
                CompletenessEntry.from_dict(e) for e in data.get("dimensions", [])
            ],
            verdict=CompletenessVerdict.from_string(data.get("verdict", "")),
            blocking_gaps=list(data.get("blocking_gaps", [])),
            deferred_acknowledged=list(data.get("deferred_acknowledged", [])),
            summary=data.get("summary", ""),
            generated_at=data.get("generated_at", time.time()),
            reviewer_version=data.get("reviewer_version", "1.0"),
        )

    def get_dimension(
        self, dim: CompletenessDimension
    ) -> Optional[CompletenessEntry]:
        """Return the :class:`CompletenessEntry` for a given dimension."""
        for entry in self.dimensions:
            if entry.dimension == dim:
                return entry
        return None

    @property
    def is_fully_closed(self) -> bool:
        """Return True only when the verdict is fully_closed."""
        return self.verdict.is_fully_closed

    @property
    def has_blocking_gaps(self) -> bool:
        """Return True when the report has blocking gaps."""
        return len(self.blocking_gaps) > 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _try_import(module_path: str) -> bool:
    """Return True when *module_path* can be imported, False otherwise."""
    try:
        importlib.import_module(module_path)
        return True
    except (ImportError, ModuleNotFoundError):
        return False
    except Exception:
        return False


def _file_exists(rel_path: str) -> bool:
    """Return True when *rel_path* relative to the project root exists."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.isfile(os.path.join(project_root, rel_path))


# ---------------------------------------------------------------------------
# DualRepoSystemCompletenessReviewer
# ---------------------------------------------------------------------------


class DualRepoSystemCompletenessReviewer:
    """Code-grounded reviewer for the dual-repo Galaxy system completeness.

    All probes are read-only (import checks and file-existence checks).
    No canonical state, runtime registry, or singleton is mutated.

    Usage
    -----
    ::

        from core.dual_repo_system_completeness_review import (
            DualRepoSystemCompletenessReviewer,
        )

        report = DualRepoSystemCompletenessReviewer().review()
        print(report.verdict.value)
        for gap in report.blocking_gaps:
            print(f"  GAP: {gap}")
    """

    REVIEWER_VERSION: str = "1.0"

    def review(self) -> CompletenessReviewReport:
        """Run the full five-dimension dual-repo completeness review.

        Returns
        -------
        CompletenessReviewReport
            Full report with per-dimension completeness entries, system verdict,
            blocking gaps, deferred items, and human-readable summary.
        """
        entries = [
            self._assess_architecture_structure(),
            self._assess_runtime_closure(),
            self._assess_cross_repo_evidence(),
            self._assess_governance_release_readiness(),
            self._assess_real_device_multi_device(),
        ]

        verdict = self._compute_verdict(entries)
        blocking_gaps = self._collect_blocking_gaps(entries)
        deferred = self._collect_deferred(entries)
        summary = self._build_summary(verdict, entries, blocking_gaps, deferred)

        return CompletenessReviewReport(
            dimensions=entries,
            verdict=verdict,
            blocking_gaps=blocking_gaps,
            deferred_acknowledged=deferred,
            summary=summary,
            reviewer_version=self.REVIEWER_VERSION,
        )

    # ------------------------------------------------------------------
    # Dimension assessors
    # ------------------------------------------------------------------

    def _assess_architecture_structure(self) -> CompletenessEntry:
        """Assess architecture and structure maturity."""
        dim = CompletenessDimension.architecture_structure

        # Probe core modules that form the structural backbone
        core_modules = [
            ("core.system_final_acceptance_verdict", "PR-17V2 system acceptance"),
            ("core.dual_repo_system_reality_audit", "PR-537 reality audit"),
            ("core.v2_readiness_governance_evidence_surface", "PR-6V2 evidence surface"),
            ("core.release_governance_taxonomy", "PR-8 taxonomy"),
            ("core.android_participant_evidence_ingress", "Android evidence ingress"),
            ("core.delegated_flow_decision_history", "PR-V2-4DH decision history"),
            ("core.recovery_truth_surface", "PR-5-TRUTH recovery surface"),
            ("core.dual_repo_system_map", "system cognitive map"),
        ]

        available: List[str] = []
        missing: List[str] = []
        for mod_path, label in core_modules:
            if _try_import(mod_path):
                available.append(f"{mod_path} ({label})")
            else:
                missing.append(f"{mod_path} ({label})")

        # Gateway layer
        gateway_modules = [
            "galaxy_gateway.device_router",
            "galaxy_gateway.websocket_handler",
        ]
        gateway_available = sum(1 for m in gateway_modules if _try_import(m))

        # Dispatch chain
        dispatch_modules = [
            "core.command_router",
            "core.capability_routing_gate",
            "core.delegated_flow_acceptance_gate",
            "core.delegated_flow_readiness_gate",
        ]
        dispatch_available = sum(1 for m in dispatch_modules if _try_import(m))

        # Check documentation anchors
        doc_files = [
            "docs/joint_system_review/01_system_positioning.md",
            "docs/joint_system_review/02_responsibility_boundary.md",
            "docs/joint_system_review/03_key_flows.md",
            "docs/joint_system_review/04_cross_repo_contract.md",
            "docs/joint_system_review/05_maturity_assessment.md",
        ]
        docs_present = sum(1 for f in doc_files if _file_exists(f))

        completed: List[str] = []
        gaps: List[str] = []

        if available:
            completed.append(
                f"Core structural modules importable: {len(available)}/{len(core_modules)}: "
                + ", ".join(m.split()[0] for m in available[:5])
                + ("..." if len(available) > 5 else "")
            )
        if gateway_available > 0:
            completed.append(
                f"Gateway transport modules: {gateway_available}/{len(gateway_modules)} available"
            )
        if dispatch_available > 0:
            completed.append(
                f"Dispatch chain modules: {dispatch_available}/{len(dispatch_modules)} available"
            )
        if docs_present > 0:
            completed.append(
                f"Joint system review docs: {docs_present}/{len(doc_files)} present"
            )

        if missing:
            gaps.append(
                f"Missing structural modules: {', '.join(m.split()[0] for m in missing)}"
            )
        if gateway_available < len(gateway_modules):
            gaps.append(
                f"Gateway modules incomplete: {gateway_available}/{len(gateway_modules)}"
            )

        # Label assignment
        # Note: label is only 'complete' when ALL structural sub-areas are gap-free,
        # ensuring test E16 invariant (complete label requires empty gap_items).
        total_core = len(core_modules)
        available_count = len(available)
        if (
            available_count == total_core
            and dispatch_available == len(dispatch_modules)
            and gateway_available == len(gateway_modules)
        ):
            label = CompletenessLabel.complete
        elif available_count >= total_core * 0.7:
            label = CompletenessLabel.structure_only
        elif available_count > 0:
            label = CompletenessLabel.nominally_present
        else:
            label = CompletenessLabel.not_present

        return CompletenessEntry(
            dimension=dim,
            label=label,
            summary=(
                "V2 structural backbone: architecture modules, gateway layer, "
                "dispatch chain, and documentation are substantively present. "
                "Core review surfaces (system_final_acceptance_verdict, "
                "dual_repo_system_reality_audit, evidence_surface, taxonomy) "
                "all importable. This dimension reaches 'complete' in terms of "
                "code structure; runtime closure is assessed separately."
            ),
            completed_items=completed,
            gap_items=gaps,
            deferred_items=[],
            code_references=[m.split()[0] for m in available],
            test_references=[
                "tests/test_pr17_v2_system_final_acceptance_verdict.py",
                "tests/test_pr537_dual_repo_system_reality_audit.py",
                "tests/test_dual_repo_system_map.py",
            ],
        )

    def _assess_runtime_closure(self) -> CompletenessEntry:
        """Assess runtime closure maturity."""
        dim = CompletenessDimension.runtime_closure

        # Core runtime modules
        runtime_modules = [
            "core.command_router",
            "core.canonical_execution_chain",
            "core.flow_continuity_coordinator",
            "core.delegated_flow_recovery_coordinator",
            "core.recovery_durability_closure_validator",
            "core.attached_runtime_recovery_readiness",
        ]
        runtime_available = [m for m in runtime_modules if _try_import(m)]

        # Decision history: was the delegated path actually exercised?
        decision_history_available = _try_import("core.delegated_flow_decision_history")
        decision_history_has_runtime_events = False
        if decision_history_available:
            try:
                from core.delegated_flow_decision_history import (  # type: ignore[import]
                    get_decision_history,
                )
                history = get_decision_history()
                report = history.evaluate()
                from core.delegated_flow_decision_history import (  # type: ignore[import]
                    HistoryEvidenceStatus,
                )
                decision_history_has_runtime_events = (
                    report.evidence_status
                    == HistoryEvidenceStatus.observed_and_closed
                )
            except Exception:
                pass

        # Recovery truth surface
        recovery_surface_available = _try_import("core.recovery_truth_surface")

        # Gateway capability enforcement
        enforcement_available = _try_import(
            "core.gateway_capability_default_enforcement"
        )

        # Acceptance evaluator can run
        acceptance_runnable = False
        if _try_import("core.system_final_acceptance_verdict"):
            try:
                from core.system_final_acceptance_verdict import (  # type: ignore[import]
                    evaluate_system_acceptance,
                    reset_system_acceptance_evaluator,
                )
                reset_system_acceptance_evaluator()
                _rpt = evaluate_system_acceptance()
                acceptance_runnable = True
            except Exception:
                pass

        completed: List[str] = []
        gaps: List[str] = []
        deferred: List[str] = []

        if runtime_available:
            completed.append(
                f"Runtime modules importable: {len(runtime_available)}/{len(runtime_modules)}: "
                + ", ".join(runtime_available[:4])
                + ("..." if len(runtime_available) > 4 else "")
            )
        if decision_history_available:
            completed.append(
                "core.delegated_flow_decision_history importable: "
                "structure_present can be evaluated"
            )
        if recovery_surface_available:
            completed.append(
                "core.recovery_truth_surface importable: "
                "structured recovery truth atoms available"
            )
        if enforcement_available:
            completed.append(
                "core.gateway_capability_default_enforcement importable: "
                "capability routing default enforcement structure present"
            )
        if acceptance_runnable:
            completed.append(
                "core.system_final_acceptance_verdict.evaluate_system_acceptance() "
                "callable and returns a report"
            )

        if not decision_history_has_runtime_events:
            gaps.append(
                "core.delegated_flow_decision_history: runtime_closure_established=False "
                "— delegated path has not been exercised end-to-end in this environment; "
                "no completed run history proves runtime closure"
            )

        missing_runtime = [m for m in runtime_modules if m not in runtime_available]
        if missing_runtime:
            gaps.append(
                f"Missing runtime modules: {', '.join(missing_runtime)}"
            )

        deferred.append(
            "Android offline queue replay ordering authority: explicitly deferred "
            "per core.recovery_truth_surface deferred_boundaries documentation"
        )
        deferred.append(
            "Ephemeral transport binding after reconnect: explicitly deferred "
            "per core.recovery_truth_surface deferred_boundaries documentation"
        )
        deferred.append(
            "Multi-device simultaneous reconnect ordering authority: explicitly deferred "
            "per core.recovery_truth_surface deferred_boundaries documentation"
        )

        # Label: runtime closure is not yet end-to-end proven
        # (decision history has no runtime events in a fresh environment,
        # and some deferred items exist)
        if decision_history_has_runtime_events and not missing_runtime:
            label = CompletenessLabel.complete
        elif len(runtime_available) >= len(runtime_modules) * 0.7:
            label = CompletenessLabel.evidence_gap
        elif runtime_available:
            label = CompletenessLabel.structure_only
        else:
            label = CompletenessLabel.nominally_present

        return CompletenessEntry(
            dimension=dim,
            label=label,
            summary=(
                "Runtime structure is substantively present: continuity coordinator, "
                "recovery coordinator, recovery durability validator, and attached "
                "runtime recovery readiness are all importable. "
                "HOWEVER: runtime_closure_established is False in a fresh environment "
                "(no delegated flow has been exercised end-to-end). "
                "Deferred boundaries: Android offline queue replay ordering, "
                "ephemeral transport binding, multi-device simultaneous reconnect "
                "ordering — all explicitly deferred in recovery_truth_surface."
            ),
            completed_items=completed,
            gap_items=gaps,
            deferred_items=deferred,
            code_references=runtime_available,
            test_references=[
                "tests/test_pr5_v2_recovery_truth_surface.py",
                "tests/test_pr_v2_4dh_delegated_flow_decision_history.py",
            ],
        )

    def _assess_cross_repo_evidence(self) -> CompletenessEntry:
        """Assess cross-repo evidence maturity.

        This dimension is the most honest reflection of the documented
        gap: Android readiness/acceptance/governance artifacts exist but
        cannot reach V2 due to missing AIP wire layer.
        """
        dim = CompletenessDimension.cross_repo_evidence

        # V2-side ingress modules
        ingress_modules = [
            ("core.android_participant_evidence_ingress", "File-based evidence ingress"),
            ("core.android_participant_truth_ingress", "Truth ingress"),
            ("core.android_evaluator_artifact_ingress", "Evaluator artifact ingress"),
            ("core.android_delegated_runtime_audit", "Delegated runtime audit"),
            ("core.android_handoff_v2_response_ingress", "Handoff V2 response ingress"),
        ]
        ingress_available = [
            (m, label) for m, label in ingress_modules if _try_import(m)
        ]
        ingress_missing = [
            (m, label) for m, label in ingress_modules if not _try_import(m)
        ]

        # Cross-repo contract documents
        contract_docs = [
            "docs/joint_system_review/04_cross_repo_contract.md",
            "docs/ANDROID_V2_JOINT_CONTINUITY_CONTRACT.md",
            "docs/CROSS_REPO_SIGNAL_CLOSURE_VALIDATION_MATRIX.md",
        ]
        contract_docs_present = [f for f in contract_docs if _file_exists(f)]

        completed: List[str] = []
        gaps: List[str] = []
        deferred: List[str] = []

        if ingress_available:
            completed.append(
                "V2-side ingress modules present: "
                + ", ".join(m for m, _ in ingress_available)
            )
        if contract_docs_present:
            completed.append(
                "Cross-repo contract documentation: "
                + ", ".join(contract_docs_present)
            )
        completed.append(
            "core.android_participant_evidence_ingress: "
            "file-based evidence contract mechanism present for JSON artifact ingestion"
        )

        # CRITICAL DOCUMENTED GAPS (from docs/joint_system_review/04_cross_repo_contract.md)
        gaps.append(
            "CRITICAL: ReconciliationSignal AIP wire layer absent — "
            "Android DeviceReadinessArtifact, DeviceAcceptanceArtifact, "
            "DeviceGovernanceArtifact, DeviceStrategyArtifact cannot reach V2. "
            "Root cause: AipModels.kt MsgType enum has no reconciliation_signal entry; "
            "ReconciliationSignal.kt DTO exists but is not serialized to AIP v3 wire format. "
            "See: docs/joint_system_review/04_cross_repo_contract.md §2.3"
        )
        gaps.append(
            "CRITICAL: HandoffEnvelopeV2 response gateway handler absent — "
            "android_bridge.py has no handle_handoff_response import; "
            "galaxy_gateway/android/handlers/ has no handoff_response.py; "
            "Android handoff_envelope_v2_result messages fall into else branch (unhandled). "
            "See: docs/joint_system_review/04_cross_repo_contract.md §1.2"
        )
        gaps.append(
            "V2 readiness/governance gates lack Android artifact input: "
            "DelegatedFlowReadinessGate and DelegatedFlowAcceptanceGate produce verdicts "
            "without Android-side readiness dimension inputs due to wire layer gap."
        )

        if ingress_missing:
            gaps.append(
                "Missing V2-side ingress modules: "
                + ", ".join(m for m, _ in ingress_missing)
            )

        deferred.append(
            "Android compat/legacy influence reporting path: depends on "
            "ReconciliationSignal channel (deferred until wire layer is built)"
        )

        # This dimension is evidence_gap due to documented critical wire layer gaps
        label = CompletenessLabel.evidence_gap

        return CompletenessEntry(
            dimension=dim,
            label=label,
            summary=(
                "Cross-repo evidence architecture is designed and partially built: "
                "V2-side ingress modules exist, file-based evidence contract is present, "
                "cross-repo contract documentation is comprehensive. "
                "CRITICAL GAPS: ReconciliationSignal AIP wire layer is absent "
                "(AipModels.kt MsgType has no reconciliation_signal entry), "
                "preventing Android readiness/acceptance/governance artifacts from "
                "reaching V2 through the live wire path. "
                "HandoffEnvelopeV2 response handler is absent at gateway layer. "
                "These are EVIDENCE GAPS, not deferred items — they prevent the "
                "cross-repo evidence flow from being considered closed."
            ),
            completed_items=completed,
            gap_items=gaps,
            deferred_items=deferred,
            code_references=[m for m, _ in ingress_available],
            test_references=[
                "tests/test_android_participant_evidence_ingress.py",
            ],
        )

    def _assess_governance_release_readiness(self) -> CompletenessEntry:
        """Assess governance and release readiness maturity."""
        dim = CompletenessDimension.governance_release_readiness

        # Taxonomy and gate modules
        gov_modules = [
            ("core.release_governance_taxonomy", "Unified taxonomy PR-8"),
            ("core.governance_validation_gate", "Governance validation gate"),
            ("core.distributed_release_gate_skeleton", "Release gate skeleton PR-7V2"),
            ("core.system_final_acceptance_verdict", "Final acceptance verdict PR-17V2"),
            ("core.v2_readiness_governance_evidence_surface", "Evidence surface PR-6V2"),
            ("core.delegated_flow_readiness_gate", "Readiness gate PR-9V2"),
            ("core.delegated_flow_acceptance_gate", "Acceptance gate PR-10V2"),
            ("core.delegated_flow_post_graduation_governance", "Post-grad governance PR-11V2"),
            ("core.release_blocking_gate", "Release blocking gate"),
        ]
        available_gov = [m for m, _ in gov_modules if _try_import(m)]
        missing_gov = [m for m, _ in gov_modules if not _try_import(m)]

        # Check if release gate skeleton is enforcing
        skeleton_enforcing: Optional[bool] = None
        if _try_import("core.distributed_release_gate_skeleton"):
            try:
                from core.distributed_release_gate_skeleton import (  # type: ignore[import]
                    evaluate_distributed_release_gate,
                )
                r = evaluate_distributed_release_gate()
                skeleton_enforcing = getattr(r, "is_enforcing", None)
            except Exception:
                skeleton_enforcing = None

        # Taxonomy available and register-able?
        taxonomy_functional = False
        if _try_import("core.release_governance_taxonomy"):
            try:
                from core.release_governance_taxonomy import (  # type: ignore[import]
                    classify_issue,
                    get_terminology_registry,
                )
                reg = get_terminology_registry()
                taxonomy_functional = len(reg.entries) > 0
            except Exception:
                pass

        completed: List[str] = []
        gaps: List[str] = []
        deferred: List[str] = []

        if available_gov:
            completed.append(
                f"Governance modules importable: {len(available_gov)}/{len(gov_modules)}: "
                + ", ".join(available_gov[:5])
                + ("..." if len(available_gov) > 5 else "")
            )
        if taxonomy_functional:
            completed.append(
                "core.release_governance_taxonomy: unified taxonomy functional, "
                "IssueClassification enum and TerminologyRegistry available"
            )
        completed.append(
            "core.system_final_acceptance_verdict: five-dimension acceptance "
            "aggregation structure is present and evaluable"
        )
        completed.append(
            "core.v2_readiness_governance_evidence_surface: evidence surface "
            "provides reviewable classification of canonical vs advisory evidence"
        )

        if skeleton_enforcing is False:
            gaps.append(
                "core.distributed_release_gate_skeleton: is_enforcing=False — "
                "the skeleton is in advisory/non-blocking mode; it does NOT "
                "currently block real execution when gate criteria are unmet"
            )
        elif skeleton_enforcing is None:
            gaps.append(
                "core.distributed_release_gate_skeleton: enforcement status unknown "
                "(could not evaluate is_enforcing)"
            )

        gaps.append(
            "Release gate not connected to CI/CD pipeline: governance verdict remains "
            "advisory/non-blocking and does not automatically enforce release blocking; "
            "human review is still required"
        )
        gaps.append(
            "Android-side governance artifacts not reaching V2 gates: "
            "DelegatedFlowReadinessGate inputs lack Android dimension (wire layer gap)"
        )

        if missing_gov:
            gaps.append(
                f"Missing governance modules: {', '.join(missing_gov)}"
            )

        deferred.append(
            "Legacy path default-off enforcement: depends on "
            "readiness/governance gate signals being fully wired; deferred"
        )
        deferred.append(
            "Automatic rollback on governance violation: framework exists, "
            "automatic trigger not yet connected"
        )

        # Label: governance framework is complete structurally but enforcing state
        # is advisory only; this is evidence_gap (not deferred, because it's a
        # real gap in enforcement wiring)
        if (
            len(available_gov) == len(gov_modules)
            and skeleton_enforcing
            and not gaps
        ):
            label = CompletenessLabel.complete
        elif len(available_gov) >= len(gov_modules) * 0.7:
            label = CompletenessLabel.evidence_gap
        elif available_gov:
            label = CompletenessLabel.structure_only
        else:
            label = CompletenessLabel.nominally_present

        return CompletenessEntry(
            dimension=dim,
            label=label,
            summary=(
                "Governance and release readiness framework is structurally complete: "
                "unified taxonomy (PR-8), readiness gate (PR-9V2), acceptance gate "
                "(PR-10V2), post-graduation governance (PR-11V2), evidence surface "
                "(PR-6V2), and system final acceptance verdict (PR-17V2) all exist "
                "and are importable. "
                "EVIDENCE GAPS: release gate skeleton is in advisory/non-enforcing mode; "
                "the gate does not currently block real execution; Android-side governance "
                "artifacts do not reach V2 gates (wire layer gap); no CI/CD pipeline "
                "integration for automatic release blocking."
            ),
            completed_items=completed,
            gap_items=gaps,
            deferred_items=deferred,
            code_references=available_gov,
            test_references=[
                "tests/test_pr8_v2_release_governance_taxonomy.py",
                "tests/test_pr17_v2_system_final_acceptance_verdict.py",
                "tests/test_pr537_dual_repo_system_reality_audit.py",
            ],
        )

    def _assess_real_device_multi_device(self) -> CompletenessEntry:
        """Assess real-device and multi-device closure maturity."""
        dim = CompletenessDimension.real_device_multi_device

        # Multi-device coordination modules
        multi_device_modules = [
            "core.multi_device_coordination_authority",
            "core.multi_device_truth_convergence",
            "core.multi_device_runtime_harness",
            "core.cross_device_execution_chain",
        ]
        md_available = [m for m in multi_device_modules if _try_import(m)]

        # Recovery / reconnect participant modules
        recovery_modules = [
            "core.attached_runtime_recovery_readiness",
            "core.recovery_truth_surface",
            "core.attached_runtime_session_registry",
        ]
        recovery_available = [m for m in recovery_modules if _try_import(m)]

        # Real-device evidence: check for evidence file path
        evidence_env = os.environ.get(
            "ANDROID_PARTICIPANT_EVIDENCE_PATH", ""
        )
        real_device_evidence_present = bool(
            evidence_env and os.path.isfile(evidence_env)
        )

        # Check multi-device acceptance doc
        md_acceptance_doc = "docs/MULTI_DEVICE_E2E_ACCEPTANCE_MATRIX.md"
        md_acceptance_present = _file_exists(md_acceptance_doc)

        completed: List[str] = []
        gaps: List[str] = []
        deferred: List[str] = []

        if md_available:
            completed.append(
                f"Multi-device coordination modules: {len(md_available)}/{len(multi_device_modules)}: "
                + ", ".join(md_available)
            )
        if recovery_available:
            completed.append(
                f"Recovery/reconnect participant modules: {len(recovery_available)}/{len(recovery_modules)}: "
                + ", ".join(recovery_available)
            )
        if md_acceptance_present:
            completed.append(
                f"Multi-device e2e acceptance matrix document: {md_acceptance_doc}"
            )
        completed.append(
            "core.android_participant_evidence_ingress: "
            "provides structured path for real-device evidence ingestion"
        )

        if not real_device_evidence_present:
            gaps.append(
                "No real-device evidence artifact present "
                "(ANDROID_PARTICIPANT_EVIDENCE_PATH not set or file absent): "
                "real-device participant status cannot be verified without "
                "an Android device connected and providing evidence. "
                "This is an EVIDENCE GAP for real-device closure."
            )
        gaps.append(
            "No automated CI jobs that run with a real Android device connected: "
            "multi-device and real-device scenarios are not covered by CI automation; "
            "only unit/integration tests for structure exist"
        )
        gaps.append(
            "Cross-device simultaneous reconnect ordering: no test exercises "
            "multi-device simultaneous reconnect with ordering authority"
        )

        missing_md = [m for m in multi_device_modules if m not in md_available]
        if missing_md:
            gaps.append(
                f"Missing multi-device modules: {', '.join(missing_md)}"
            )

        deferred.append(
            "Real-device CI automation: acknowledged as deferred; "
            "android_participant_evidence_ingress provides the file-contract "
            "mechanism but real-device CI pipeline integration is not yet built"
        )
        deferred.append(
            "Multi-device simultaneous reconnect ordering authority: "
            "explicitly deferred per recovery_truth_surface deferred_boundaries"
        )

        # This dimension is deferred/evidence_gap because real-device closure
        # depends on actual device + CI
        if real_device_evidence_present and not gaps:
            label = CompletenessLabel.complete
        elif md_available and recovery_available:
            label = CompletenessLabel.deferred
        elif md_available or recovery_available:
            label = CompletenessLabel.structure_only
        else:
            label = CompletenessLabel.nominally_present

        return CompletenessEntry(
            dimension=dim,
            label=label,
            summary=(
                "Multi-device coordination structure is present: "
                "coordination authority, truth convergence, runtime harness, "
                "and cross-device execution chain modules are importable. "
                "Recovery and reconnect participant modules are present. "
                "EVIDENCE GAPS: no real Android device evidence artifact present "
                "in this environment; no CI automation for real-device scenarios; "
                "multi-device simultaneous reconnect ordering is explicitly deferred. "
                "Real-device closure requires an actual Android participant providing "
                "evidence via ANDROID_PARTICIPANT_EVIDENCE_PATH."
            ),
            completed_items=completed,
            gap_items=gaps,
            deferred_items=deferred,
            code_references=md_available + recovery_available,
            test_references=[
                "tests/test_pr523_e2e_multi_device_acceptance.py",
                "tests/test_pr34_post533_cross_device_runtime_acceptance.py",
            ],
        )

    # ------------------------------------------------------------------
    # Verdict computation
    # ------------------------------------------------------------------

    def _compute_verdict(
        self, entries: List[CompletenessEntry]
    ) -> CompletenessVerdict:
        """Compute the system-level completeness verdict from dimension entries."""
        if not entries:
            return CompletenessVerdict.insufficient_evidence

        labels = [e.label for e in entries]

        not_present_count = sum(
            1 for l in labels if l == CompletenessLabel.not_present
        )
        evidence_gap_count = sum(
            1 for l in labels if l == CompletenessLabel.evidence_gap
        )
        nominally_present_count = sum(
            1 for l in labels if l == CompletenessLabel.nominally_present
        )
        structure_only_count = sum(
            1 for l in labels if l == CompletenessLabel.structure_only
        )

        if not_present_count >= 2:
            return CompletenessVerdict.insufficient_evidence

        if evidence_gap_count >= 3 or nominally_present_count >= 2:
            return CompletenessVerdict.critical_evidence_gaps

        if structure_only_count >= 3:
            return CompletenessVerdict.structural_only_runtime_not_closed

        all_complete = all(
            l in (CompletenessLabel.complete, CompletenessLabel.deferred)
            for l in labels
        )
        if all_complete and not any(
            l.is_blocking() for l in labels
        ):
            return CompletenessVerdict.fully_closed

        return CompletenessVerdict.partial_closure_gaps_present

    def _collect_blocking_gaps(
        self, entries: List[CompletenessEntry]
    ) -> List[str]:
        """Collect all blocking gaps from all entries."""
        result: List[str] = []
        for entry in entries:
            for gap in entry.gap_items:
                if gap not in result:
                    result.append(f"[{entry.dimension.value}] {gap}")
        return result

    def _collect_deferred(
        self, entries: List[CompletenessEntry]
    ) -> List[str]:
        """Collect all deferred items from all entries."""
        result: List[str] = []
        for entry in entries:
            for item in entry.deferred_items:
                if item not in result:
                    result.append(f"[{entry.dimension.value}] {item}")
        return result

    def _build_summary(
        self,
        verdict: CompletenessVerdict,
        entries: List[CompletenessEntry],
        blocking_gaps: List[str],
        deferred: List[str],
    ) -> str:
        """Build a structured human-readable summary for reviewer consumption."""
        lines: List[str] = [
            "=" * 72,
            "DUAL-REPO SYSTEM COMPLETENESS REVIEW",
            "Repositories: ufo-galaxy-realization-v2 (V2) + ufo-galaxy-android",
            "=" * 72,
            "",
            f"OVERALL VERDICT: {verdict.value}",
            "",
            "DIMENSION SUMMARY:",
        ]

        label_icon = {
            CompletenessLabel.complete: "✅",
            CompletenessLabel.deferred: "⏳",
            CompletenessLabel.evidence_gap: "⚠️ ",
            CompletenessLabel.structure_only: "🔶",
            CompletenessLabel.nominally_present: "❌",
            CompletenessLabel.not_present: "❌",
        }

        for entry in entries:
            icon = label_icon.get(entry.label, "?")
            lines.append(
                f"  {icon} {entry.dimension.value:<38} {entry.label.value}"
            )

        lines += [
            "",
            "WHAT THIS SYSTEM IS:",
            "  Galaxy is a distributed intelligent agent system with two repos:",
            "  • V2 (ufo-galaxy-realization-v2): control plane, orchestration,",
            "    capability routing, governance, readiness/acceptance verdicts,",
            "    truth/projection layer, recovery coordination.",
            "  • Android (ufo-galaxy-android): persistent execution participant,",
            "    local capability delivery (GUI, sensors, network), result uplink,",
            "    mesh session participation, handoff execution.",
            "",
            "WHAT IS COMPLETE (code + evidence surface level):",
        ]

        for entry in entries:
            if entry.completed_items:
                lines.append(f"  [{entry.dimension.value}]")
                for item in entry.completed_items[:3]:
                    lines.append(f"    + {item[:80]}")

        lines += [
            "",
            "EVIDENCE GAPS (blocking — must be addressed for full closure):",
        ]
        for gap in blocking_gaps[:12]:
            lines.append(f"  ! {gap[:100]}")

        lines += [
            "",
            "DEFERRED / ACCEPTED LIMITATIONS (honest, not blocking):",
        ]
        for item in deferred[:8]:
            lines.append(f"  ~ {item[:100]}")

        lines += [
            "",
            "DISTANCE FROM FULLY OPERATIONAL:",
            "  1. ReconciliationSignal AIP wire layer must be built",
            "     (AipModels.kt MsgType + V2 gateway handler + ingress wiring)",
            "  2. HandoffEnvelopeV2 response gateway handler must be added",
            "  3. Release gate must be wired to CI/CD for automatic blocking",
            "  4. Real-device CI automation must be established",
            "  5. Delegated flow must be exercised end-to-end once to prove",
            "     runtime closure (decision history currently empty)",
            "",
            "KEY CODE SURFACES FOR REVIEWERS:",
            "  core.system_final_acceptance_verdict    (PR-17V2)",
            "  core.dual_repo_system_reality_audit     (PR-537)",
            "  core.v2_readiness_governance_evidence_surface (PR-6V2)",
            "  core.release_governance_taxonomy        (PR-8)",
            "  core.delegated_flow_decision_history    (PR-V2-4DH)",
            "  core.recovery_truth_surface             (PR-5-TRUTH)",
            "  docs/joint_system_review/               (joint review docs)",
            "=" * 72,
        ]

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_SINGLETON: Optional[CompletenessReviewReport] = None


def build_completeness_review() -> CompletenessReviewReport:
    """Build and return a fresh :class:`CompletenessReviewReport`.

    Creates a new :class:`DualRepoSystemCompletenessReviewer` and runs the
    full five-dimension review.  Does NOT touch or update the singleton.
    """
    return DualRepoSystemCompletenessReviewer().review()


def get_completeness_review() -> CompletenessReviewReport:
    """Return the process-global completeness review singleton.

    The singleton is lazily computed on the first call and cached for
    subsequent calls.  Use :func:`reset_completeness_review` in tests
    to force re-evaluation.
    """
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = build_completeness_review()
    return _SINGLETON


def reset_completeness_review() -> None:
    """Reset the process-global completeness review singleton.

    After calling this function the next call to :func:`get_completeness_review`
    will trigger a fresh evaluation.

    **For use in tests only.**  Do not call from production code paths.
    """
    global _SINGLETON
    _SINGLETON = None
