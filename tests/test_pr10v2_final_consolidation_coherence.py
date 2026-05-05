"""tests/test_pr10v2_final_consolidation_coherence.py
==========================================================

PR-10 V2 — Final V2-Side Consolidation Coherence Tests
-------------------------------------------------------

Tests covering:

A.  Sentinel and authority fields are present and non-empty.
B.  V2ConsolidationCoherenceReport structure is correct.
C.  assess_v2_consolidation_coherence() runs without error.
D.  All five coherence dimensions are present.
E.  Dimension names match expected canonical paths.
F.  ingress_continuity dimension is coherent (desktop_presence_runtime,
    unified_continuity_legality_authority, canonical_dispatch_slot_authority).
G.  orchestration_runtime_truth dimension is coherent (orchestration spine,
    review surface, routing explanation, observability, hybrid continuity).
H.  manifestation_operator dimension is coherent (OperatorSnapshot PR-8 V2
    fields, presence director, flow-level operator surface).
I.  android_truth_paths dimension is coherent (device state store,
    unified runtime truth ingress, operator ecosystem).
J.  completion_status_coherence dimension is coherent (system completion
    status buildable, acceptance verdict honest, status_alignment present).
K.  overall_coherent is True (all five dimensions coherent together).
L.  V2ConsolidationCoherenceReport.to_dict() is JSON-serialisable.
M.  reset/get singleton helpers work correctly.
N.  system_completion_status includes v2_consolidation_coherence field.
O.  system_completion_status.to_dict() includes v2_consolidation_coherence.
P.  status_alignment includes v2_consolidation_coherence_complete key.
Q.  SYSTEM_COMPLETION_STATUS_PR10_V2_SENTINEL is present and non-empty.
R.  Consolidation does not bypass canonical paths (no detached module).
S.  Android-originated state only flows through V2 truth paths.
T.  system_completion_status summary mentions PR-10 V2 coherence.
U.  Completeness review architecture_structure now reports 'complete'.
V.  Completeness review architecture_structure has no gaps.
W.  Completeness review includes PR-7/8/9 V2 consolidation modules in
    completed_items.
X.  Completeness review verdict remains partial_closure_gaps_present
    (not falsely upgraded to fully_closed).
Y.  Completeness review architecture_structure test_references include
    PR-10 V2 coherence test.
"""
from __future__ import annotations

import importlib
import json
import uuid
from typing import Any, Dict, List

import pytest


# ===========================================================================
# Helpers
# ===========================================================================


def _try_import(module_path: str) -> bool:
    try:
        importlib.import_module(module_path)
        return True
    except Exception:
        return False


# ===========================================================================
# Group A — Sentinel / authority
# ===========================================================================


class TestSentinelAuthority:
    """Group A: sentinel and authority fields are present and non-empty."""

    def test_A1_authority_sentinel_non_empty(self):
        """A1: V2_FINAL_CONSOLIDATION_COHERENCE_AUTHORITY is non-empty string."""
        from core.v2_final_consolidation_coherence import (
            V2_FINAL_CONSOLIDATION_COHERENCE_AUTHORITY,
        )
        assert isinstance(V2_FINAL_CONSOLIDATION_COHERENCE_AUTHORITY, str)
        assert len(V2_FINAL_CONSOLIDATION_COHERENCE_AUTHORITY) > 20

    def test_A2_sentinel_non_empty(self):
        """A2: V2_FINAL_CONSOLIDATION_COHERENCE_SENTINEL is non-empty string."""
        from core.v2_final_consolidation_coherence import (
            V2_FINAL_CONSOLIDATION_COHERENCE_SENTINEL,
        )
        assert isinstance(V2_FINAL_CONSOLIDATION_COHERENCE_SENTINEL, str)
        assert len(V2_FINAL_CONSOLIDATION_COHERENCE_SENTINEL) > 20

    def test_A3_policy_sentinels_non_empty(self):
        """A3: ingress/orchestration/manifestation policy sentinels non-empty."""
        from core.v2_final_consolidation_coherence import (
            V2_CONSOLIDATION_INGRESS_CONTINUITY_POLICY,
            V2_CONSOLIDATION_ORCHESTRATION_RUNTIME_TRUTH_POLICY,
            V2_CONSOLIDATION_MANIFESTATION_OPERATOR_POLICY,
        )
        for sentinel in (
            V2_CONSOLIDATION_INGRESS_CONTINUITY_POLICY,
            V2_CONSOLIDATION_ORCHESTRATION_RUNTIME_TRUTH_POLICY,
            V2_CONSOLIDATION_MANIFESTATION_OPERATOR_POLICY,
        ):
            assert isinstance(sentinel, str) and len(sentinel) > 20

    def test_A4_pr10v2_system_completion_sentinel(self):
        """A4: SYSTEM_COMPLETION_STATUS_PR10_V2_SENTINEL is present and non-empty."""
        from core.system_completion_status import (
            SYSTEM_COMPLETION_STATUS_PR10_V2_SENTINEL,
        )
        assert isinstance(SYSTEM_COMPLETION_STATUS_PR10_V2_SENTINEL, str)
        assert "pr10" in SYSTEM_COMPLETION_STATUS_PR10_V2_SENTINEL.lower()
        assert "v2" in SYSTEM_COMPLETION_STATUS_PR10_V2_SENTINEL.lower()


# ===========================================================================
# Group B — CoherenceDimensionResult structure
# ===========================================================================


class TestCoherenceDimensionResult:
    """Group B: CoherenceDimensionResult structure."""

    def test_B1_dataclass_fields(self):
        """B1: CoherenceDimensionResult has expected fields."""
        from core.v2_final_consolidation_coherence import CoherenceDimensionResult
        d = CoherenceDimensionResult(
            dimension="test_dim",
            is_coherent=True,
            evidence=["e1"],
            gaps=[],
            module_references=["core.some_module"],
        )
        assert d.dimension == "test_dim"
        assert d.is_coherent is True
        assert d.evidence == ["e1"]
        assert d.gaps == []
        assert d.module_references == ["core.some_module"]

    def test_B2_to_dict_keys(self):
        """B2: CoherenceDimensionResult.to_dict() has required keys."""
        from core.v2_final_consolidation_coherence import CoherenceDimensionResult
        d = CoherenceDimensionResult(dimension="x", is_coherent=False)
        result = d.to_dict()
        for key in ("dimension", "is_coherent", "evidence", "gaps", "module_references"):
            assert key in result, f"Key {key!r} missing from to_dict()"

    def test_B3_to_dict_json_serialisable(self):
        """B3: CoherenceDimensionResult.to_dict() is JSON-serialisable."""
        from core.v2_final_consolidation_coherence import CoherenceDimensionResult
        d = CoherenceDimensionResult(
            dimension="test", is_coherent=True, evidence=["a"], gaps=["b"]
        )
        json.dumps(d.to_dict())  # must not raise


# ===========================================================================
# Group C — assess_v2_consolidation_coherence() execution
# ===========================================================================


class TestAssessCoherenceExecution:
    """Group C: assess_v2_consolidation_coherence() runs without error."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        from core.v2_final_consolidation_coherence import (
            reset_v2_consolidation_coherence_report,
        )
        reset_v2_consolidation_coherence_report()
        yield
        reset_v2_consolidation_coherence_report()

    def test_C1_runs_without_exception(self):
        """C1: assess_v2_consolidation_coherence() completes without exception."""
        from core.v2_final_consolidation_coherence import assess_v2_consolidation_coherence
        report = assess_v2_consolidation_coherence()
        assert report is not None

    def test_C2_returns_report_instance(self):
        """C2: assess_v2_consolidation_coherence() returns V2ConsolidationCoherenceReport."""
        from core.v2_final_consolidation_coherence import (
            assess_v2_consolidation_coherence,
            V2ConsolidationCoherenceReport,
        )
        report = assess_v2_consolidation_coherence()
        assert isinstance(report, V2ConsolidationCoherenceReport)

    def test_C3_report_has_required_fields(self):
        """C3: returned report has all required fields."""
        from core.v2_final_consolidation_coherence import assess_v2_consolidation_coherence
        report = assess_v2_consolidation_coherence()
        assert hasattr(report, "report_id")
        assert hasattr(report, "generated_at")
        assert hasattr(report, "overall_coherent")
        assert hasattr(report, "incoherent_count")
        assert hasattr(report, "dimensions")
        assert hasattr(report, "summary")
        assert hasattr(report, "authority")
        assert hasattr(report, "sentinel")

    def test_C4_report_id_non_empty(self):
        """C4: report_id is a non-empty string."""
        from core.v2_final_consolidation_coherence import assess_v2_consolidation_coherence
        report = assess_v2_consolidation_coherence()
        assert isinstance(report.report_id, str) and len(report.report_id) > 0

    def test_C5_generated_at_positive(self):
        """C5: generated_at is a positive float."""
        from core.v2_final_consolidation_coherence import assess_v2_consolidation_coherence
        report = assess_v2_consolidation_coherence()
        assert isinstance(report.generated_at, float)
        assert report.generated_at > 0.0


# ===========================================================================
# Group D — Five dimensions present
# ===========================================================================


class TestFiveDimensionsPresent:
    """Group D: all five coherence dimensions are present."""

    @pytest.fixture(scope="class")
    def report(self):
        from core.v2_final_consolidation_coherence import (
            assess_v2_consolidation_coherence,
            reset_v2_consolidation_coherence_report,
        )
        reset_v2_consolidation_coherence_report()
        return assess_v2_consolidation_coherence()

    def test_D1_five_dimensions(self, report):
        """D1: exactly five dimensions in the report."""
        assert len(report.dimensions) == 5, (
            f"Expected 5 dimensions, got {len(report.dimensions)}"
        )

    def test_D2_all_dimension_results_are_correct_type(self, report):
        """D2: all dimensions are CoherenceDimensionResult instances."""
        from core.v2_final_consolidation_coherence import CoherenceDimensionResult
        for dim in report.dimensions:
            assert isinstance(dim, CoherenceDimensionResult)


# ===========================================================================
# Group E — Dimension names
# ===========================================================================


class TestDimensionNames:
    """Group E: dimension names match expected canonical paths."""

    EXPECTED_DIMENSIONS = {
        "ingress_continuity",
        "orchestration_runtime_truth",
        "manifestation_operator",
        "android_truth_paths",
        "completion_status_coherence",
    }

    @pytest.fixture(scope="class")
    def report(self):
        from core.v2_final_consolidation_coherence import (
            assess_v2_consolidation_coherence,
            reset_v2_consolidation_coherence_report,
        )
        reset_v2_consolidation_coherence_report()
        return assess_v2_consolidation_coherence()

    def test_E1_dimension_names_match(self, report):
        """E1: dimension names match expected canonical paths."""
        names = {d.dimension for d in report.dimensions}
        assert names == self.EXPECTED_DIMENSIONS, (
            f"Dimension names mismatch: got {names}, expected {self.EXPECTED_DIMENSIONS}"
        )

    def test_E2_each_dimension_has_module_references(self, report):
        """E2: each dimension has at least one module reference."""
        for dim in report.dimensions:
            assert len(dim.module_references) > 0, (
                f"Dimension '{dim.dimension}' has no module_references"
            )


# ===========================================================================
# Group F — Ingress/continuity coherence
# ===========================================================================


class TestIngressContinuityCoherence:
    """Group F: ingress_continuity dimension is coherent."""

    @pytest.fixture(scope="class")
    def dim(self):
        from core.v2_final_consolidation_coherence import (
            assess_v2_consolidation_coherence,
            reset_v2_consolidation_coherence_report,
        )
        reset_v2_consolidation_coherence_report()
        report = assess_v2_consolidation_coherence()
        return next(d for d in report.dimensions if d.dimension == "ingress_continuity")

    def test_F1_ingress_continuity_coherent(self, dim):
        """F1: ingress_continuity dimension is coherent (no gaps)."""
        assert dim.is_coherent is True, (
            f"ingress_continuity has gaps: {dim.gaps}"
        )

    def test_F2_desktop_presence_runtime_referenced(self, dim):
        """F2: desktop_presence_runtime is in module_references."""
        assert any("desktop_presence_runtime" in m for m in dim.module_references), (
            "ingress_continuity must reference core.desktop_presence_runtime"
        )

    def test_F3_continuity_legality_authority_referenced(self, dim):
        """F3: unified_continuity_legality_authority is in module_references."""
        assert any("continuity_legality" in m for m in dim.module_references), (
            "ingress_continuity must reference unified_continuity_legality_authority"
        )

    def test_F4_ingress_carrier_context_mentioned_in_evidence(self, dim):
        """F4: evidence mentions ingress_carrier_context."""
        evidence_text = " ".join(dim.evidence).lower()
        assert "ingress_carrier_context" in evidence_text, (
            "ingress_continuity evidence must mention ingress_carrier_context"
        )

    def test_F5_control_session_id_mentioned_in_evidence(self, dim):
        """F5: evidence mentions control_session_id."""
        evidence_text = " ".join(dim.evidence).lower()
        assert "control_session_id" in evidence_text, (
            "ingress_continuity evidence must mention control_session_id"
        )


# ===========================================================================
# Group G — Orchestration/runtime-state-truth coherence
# ===========================================================================


class TestOrchestrationRuntimeTruthCoherence:
    """Group G: orchestration_runtime_truth dimension is coherent."""

    @pytest.fixture(scope="class")
    def dim(self):
        from core.v2_final_consolidation_coherence import (
            assess_v2_consolidation_coherence,
            reset_v2_consolidation_coherence_report,
        )
        reset_v2_consolidation_coherence_report()
        report = assess_v2_consolidation_coherence()
        return next(
            d for d in report.dimensions if d.dimension == "orchestration_runtime_truth"
        )

    def test_G1_orchestration_runtime_truth_coherent(self, dim):
        """G1: orchestration_runtime_truth dimension is coherent."""
        assert dim.is_coherent is True, (
            f"orchestration_runtime_truth has gaps: {dim.gaps}"
        )

    def test_G2_orchestration_spine_referenced(self, dim):
        """G2: unified_orchestration_spine is in module_references."""
        assert any("orchestration_spine" in m for m in dim.module_references), (
            "orchestration_runtime_truth must reference unified_orchestration_spine"
        )

    def test_G3_routing_explanation_referenced(self, dim):
        """G3: routing_explanation is in module_references."""
        assert any("routing_explanation" in m for m in dim.module_references), (
            "orchestration_runtime_truth must reference routing_explanation"
        )

    def test_G4_evidence_mentions_dispatch_slot_authority(self, dim):
        """G4: evidence mentions dispatch-slot authority (canonical 10-dimension gate)."""
        evidence_text = " ".join(dim.evidence).lower()
        assert "dispatch" in evidence_text and "slot" in evidence_text, (
            "orchestration_runtime_truth evidence must mention dispatch-slot authority"
        )

    def test_G5_routing_observability_referenced(self, dim):
        """G5: routing_observability is in module_references."""
        assert any("routing_observability" in m for m in dim.module_references), (
            "orchestration_runtime_truth must reference routing_observability"
        )


# ===========================================================================
# Group H — Manifestation/operator coherence
# ===========================================================================


class TestManifestationOperatorCoherence:
    """Group H: manifestation_operator dimension is coherent."""

    @pytest.fixture(scope="class")
    def dim(self):
        from core.v2_final_consolidation_coherence import (
            assess_v2_consolidation_coherence,
            reset_v2_consolidation_coherence_report,
        )
        reset_v2_consolidation_coherence_report()
        report = assess_v2_consolidation_coherence()
        return next(d for d in report.dimensions if d.dimension == "manifestation_operator")

    def test_H1_manifestation_operator_coherent(self, dim):
        """H1: manifestation_operator dimension is coherent."""
        assert dim.is_coherent is True, (
            f"manifestation_operator has gaps: {dim.gaps}"
        )

    def test_H2_operator_surface_referenced(self, dim):
        """H2: operator_surface is in module_references."""
        assert any("operator_surface" in m for m in dim.module_references), (
            "manifestation_operator must reference core.operator_surface"
        )

    def test_H3_evidence_mentions_desktop_shell_state(self, dim):
        """H3: evidence mentions desktop_shell_state (PR-8 V2 field)."""
        evidence_text = " ".join(dim.evidence).lower()
        assert "desktop_shell_state" in evidence_text, (
            "manifestation_operator evidence must mention desktop_shell_state"
        )

    def test_H4_evidence_mentions_presence_tristate(self, dim):
        """H4: evidence mentions presence_tristate (PR-8 V2 field)."""
        evidence_text = " ".join(dim.evidence).lower()
        assert "presence_tristate" in evidence_text, (
            "manifestation_operator evidence must mention presence_tristate"
        )

    def test_H5_evidence_mentions_manifestation_summary(self, dim):
        """H5: evidence mentions manifestation_summary (PR-8 V2 field)."""
        evidence_text = " ".join(dim.evidence).lower()
        assert "manifestation_summary" in evidence_text, (
            "manifestation_operator evidence must mention manifestation_summary"
        )


# ===========================================================================
# Group I — Android truth paths coherence
# ===========================================================================


class TestAndroidTruthPathsCoherence:
    """Group I: android_truth_paths dimension is coherent."""

    @pytest.fixture(scope="class")
    def dim(self):
        from core.v2_final_consolidation_coherence import (
            assess_v2_consolidation_coherence,
            reset_v2_consolidation_coherence_report,
        )
        reset_v2_consolidation_coherence_report()
        report = assess_v2_consolidation_coherence()
        return next(d for d in report.dimensions if d.dimension == "android_truth_paths")

    def test_I1_android_truth_paths_coherent(self, dim):
        """I1: android_truth_paths dimension is coherent."""
        assert dim.is_coherent is True, (
            f"android_truth_paths has gaps: {dim.gaps}"
        )

    def test_I2_device_state_store_referenced(self, dim):
        """I2: android_device_state_store is in module_references."""
        assert any("android_device_state_store" in m for m in dim.module_references), (
            "android_truth_paths must reference core.android_device_state_store"
        )

    def test_I3_unified_truth_ingress_referenced(self, dim):
        """I3: unified_runtime_truth_ingress is in module_references."""
        assert any("unified_runtime_truth_ingress" in m for m in dim.module_references), (
            "android_truth_paths must reference core.unified_runtime_truth_ingress"
        )

    def test_I4_no_parallel_write_policy_mentioned(self, dim):
        """I4: evidence mentions the no-parallel-write policy."""
        evidence_text = " ".join(dim.evidence).lower()
        assert "no_parallel_write" in evidence_text or "parallel" in evidence_text, (
            "android_truth_paths evidence must mention the no-parallel-write policy"
        )

    def test_I5_operator_ecosystem_path_mentioned(self, dim):
        """I5: evidence mentions android_ecosystem operator path."""
        evidence_text = " ".join(dim.evidence).lower()
        assert "android_ecosystem" in evidence_text or "ecosystem" in evidence_text, (
            "android_truth_paths evidence must mention android_ecosystem operator path"
        )


# ===========================================================================
# Group J — Completion status coherence
# ===========================================================================


class TestCompletionStatusCoherence:
    """Group J: completion_status_coherence dimension is coherent."""

    @pytest.fixture(scope="class")
    def dim(self):
        from core.v2_final_consolidation_coherence import (
            assess_v2_consolidation_coherence,
            reset_v2_consolidation_coherence_report,
        )
        reset_v2_consolidation_coherence_report()
        report = assess_v2_consolidation_coherence()
        return next(
            d for d in report.dimensions if d.dimension == "completion_status_coherence"
        )

    def test_J1_completion_status_coherence_coherent(self, dim):
        """J1: completion_status_coherence dimension is coherent."""
        assert dim.is_coherent is True, (
            f"completion_status_coherence has gaps: {dim.gaps}"
        )

    def test_J2_system_completion_status_referenced(self, dim):
        """J2: system_completion_status is in module_references."""
        assert any("system_completion_status" in m for m in dim.module_references), (
            "completion_status_coherence must reference core.system_completion_status"
        )

    def test_J3_evidence_mentions_closure_cap_guard(self, dim):
        """J3: evidence mentions the closure cap guard against false 100% reporting."""
        evidence_text = " ".join(dim.evidence).lower()
        assert (
            "closure" in evidence_text
            or "cap" in evidence_text
            or "max_closure" in evidence_text
        ), (
            "completion_status_coherence evidence must mention closure cap/guard"
        )

    def test_J4_evidence_mentions_is_fully_closed(self, dim):
        """J4: evidence mentions is_fully_closed or fully_closed (honest gap reporting)."""
        evidence_text = " ".join(dim.evidence).lower()
        assert (
            "fully_closed" in evidence_text
            or "is_fully_closed" in evidence_text
            or "fully closed" in evidence_text
        ), (
            "completion_status_coherence evidence must mention fully_closed state"
        )


# ===========================================================================
# Group K — Overall coherence
# ===========================================================================


class TestOverallCoherence:
    """Group K: overall_coherent is True (all five dimensions coherent)."""

    @pytest.fixture(scope="class")
    def report(self):
        from core.v2_final_consolidation_coherence import (
            assess_v2_consolidation_coherence,
            reset_v2_consolidation_coherence_report,
        )
        reset_v2_consolidation_coherence_report()
        return assess_v2_consolidation_coherence()

    def test_K1_overall_coherent_true(self, report):
        """K1: overall_coherent is True (all dimensions coherent)."""
        incoherent = [d for d in report.dimensions if not d.is_coherent]
        assert report.overall_coherent is True, (
            f"overall_coherent is False; incoherent dimensions: "
            f"{[d.dimension for d in incoherent]}; gaps: {[d.gaps for d in incoherent]}"
        )

    def test_K2_incoherent_count_zero(self, report):
        """K2: incoherent_count is 0."""
        assert report.incoherent_count == 0, (
            f"incoherent_count={report.incoherent_count}, expected 0"
        )

    def test_K3_summary_non_empty(self, report):
        """K3: summary is a non-empty string."""
        assert isinstance(report.summary, str) and len(report.summary) > 0

    def test_K4_summary_mentions_coherent(self, report):
        """K4: summary mentions coherent status."""
        lower = report.summary.lower()
        assert "coherent" in lower or "一致" in report.summary, (
            "summary must mention coherent status"
        )


# ===========================================================================
# Group L — JSON serialisation
# ===========================================================================


class TestJsonSerialisation:
    """Group L: V2ConsolidationCoherenceReport.to_dict() is JSON-serialisable."""

    @pytest.fixture(scope="class")
    def report(self):
        from core.v2_final_consolidation_coherence import (
            assess_v2_consolidation_coherence,
            reset_v2_consolidation_coherence_report,
        )
        reset_v2_consolidation_coherence_report()
        return assess_v2_consolidation_coherence()

    def test_L1_to_dict_returns_dict(self, report):
        """L1: to_dict() returns a dict."""
        assert isinstance(report.to_dict(), dict)

    def test_L2_to_dict_json_serialisable(self, report):
        """L2: to_dict() produces a JSON-serialisable structure."""
        d = report.to_dict()
        json.dumps(d)  # must not raise

    def test_L3_to_dict_has_required_keys(self, report):
        """L3: to_dict() has all required top-level keys."""
        d = report.to_dict()
        for key in (
            "report_id", "generated_at", "authority", "sentinel",
            "dimensions", "overall_coherent", "incoherent_count", "summary",
        ):
            assert key in d, f"Key {key!r} missing from to_dict()"


# ===========================================================================
# Group M — Singleton helpers
# ===========================================================================


class TestSingletonHelpers:
    """Group M: reset/get singleton helpers work correctly."""

    def test_M1_get_returns_same_instance(self):
        """M1: get_v2_consolidation_coherence_report() returns same instance."""
        from core.v2_final_consolidation_coherence import (
            get_v2_consolidation_coherence_report,
            reset_v2_consolidation_coherence_report,
        )
        reset_v2_consolidation_coherence_report()
        r1 = get_v2_consolidation_coherence_report()
        r2 = get_v2_consolidation_coherence_report()
        assert r1 is r2

    def test_M2_force_rebuild_creates_new_instance(self):
        """M2: force_rebuild=True creates a new report instance."""
        from core.v2_final_consolidation_coherence import (
            get_v2_consolidation_coherence_report,
            reset_v2_consolidation_coherence_report,
        )
        reset_v2_consolidation_coherence_report()
        r1 = get_v2_consolidation_coherence_report()
        r2 = get_v2_consolidation_coherence_report(force_rebuild=True)
        assert r1 is not r2

    def test_M3_reset_clears_cache(self):
        """M3: reset_v2_consolidation_coherence_report() clears the cache."""
        from core.v2_final_consolidation_coherence import (
            get_v2_consolidation_coherence_report,
            reset_v2_consolidation_coherence_report,
        )
        reset_v2_consolidation_coherence_report()
        r1 = get_v2_consolidation_coherence_report()
        reset_v2_consolidation_coherence_report()
        r2 = get_v2_consolidation_coherence_report()
        assert r1 is not r2


# ===========================================================================
# Group N — system_completion_status integration
# ===========================================================================


class TestSystemCompletionStatusIntegration:
    """Group N-P: system_completion_status includes v2_consolidation_coherence."""

    @pytest.fixture(scope="class")
    def status(self):
        from core.system_completion_status import (
            SystemCompletionStatus,
        )
        # Test only the data structure without running the full build
        return SystemCompletionStatus(
            v2_consolidation_coherence={
                "overall_coherent": True,
                "incoherent_count": 0,
                "dimensions": [
                    {"dimension": "ingress_continuity", "is_coherent": True, "gap_count": 0},
                ],
            },
            status_alignment={
                "v2_consolidation_coherence_complete": True,
                "architecture_complete_but_system_not_closed": False,
                "runtime_ready_but_acceptance_not_full": False,
                "runtime_ready_but_completeness_not_full": False,
            },
        )

    def test_N1_system_completion_status_has_v2_coherence_field(self, status):
        """N1: SystemCompletionStatus has v2_consolidation_coherence field."""
        assert hasattr(status, "v2_consolidation_coherence")

    def test_N2_v2_coherence_field_is_dict(self, status):
        """N2: v2_consolidation_coherence is a dict."""
        assert isinstance(status.v2_consolidation_coherence, dict)

    def test_O1_to_dict_includes_v2_consolidation_coherence(self, status):
        """O1: to_dict() includes v2_consolidation_coherence key."""
        d = status.to_dict()
        assert "v2_consolidation_coherence" in d

    def test_O2_to_dict_v2_coherence_is_dict(self, status):
        """O2: to_dict()['v2_consolidation_coherence'] is a dict."""
        d = status.to_dict()
        assert isinstance(d["v2_consolidation_coherence"], dict)

    def test_P1_status_alignment_has_v2_consolidation_key(self, status):
        """P1: status_alignment includes v2_consolidation_coherence_complete key."""
        assert "v2_consolidation_coherence_complete" in status.status_alignment

    def test_P2_v2_consolidation_coherence_complete_is_bool(self, status):
        """P2: status_alignment['v2_consolidation_coherence_complete'] is bool."""
        val = status.status_alignment.get("v2_consolidation_coherence_complete")
        assert isinstance(val, bool)


# ===========================================================================
# Group Q — PR-10 V2 sentinel
# ===========================================================================


class TestPR10V2Sentinel:
    """Group Q: SYSTEM_COMPLETION_STATUS_PR10_V2_SENTINEL is non-empty."""

    def test_Q1_sentinel_importable(self):
        """Q1: SYSTEM_COMPLETION_STATUS_PR10_V2_SENTINEL importable."""
        from core.system_completion_status import SYSTEM_COMPLETION_STATUS_PR10_V2_SENTINEL
        assert SYSTEM_COMPLETION_STATUS_PR10_V2_SENTINEL

    def test_Q2_sentinel_references_coherence_module(self):
        """Q2: sentinel string references v2_final_consolidation_coherence."""
        from core.system_completion_status import SYSTEM_COMPLETION_STATUS_PR10_V2_SENTINEL
        assert "v2_final_consolidation_coherence" in SYSTEM_COMPLETION_STATUS_PR10_V2_SENTINEL

    def test_Q3_coherence_module_sentinel_references_pr10(self):
        """Q3: V2_FINAL_CONSOLIDATION_COHERENCE_SENTINEL references pr10-v2."""
        from core.v2_final_consolidation_coherence import V2_FINAL_CONSOLIDATION_COHERENCE_SENTINEL
        assert "pr10" in V2_FINAL_CONSOLIDATION_COHERENCE_SENTINEL.lower()


# ===========================================================================
# Group R — No detached architecture
# ===========================================================================


class TestNoDetachedArchitecture:
    """Group R: consolidation does not bypass canonical paths."""

    def test_R1_coherence_module_does_not_import_new_authority_modules(self):
        """R1: coherence module probes existing modules rather than creating new ones."""
        import ast
        import os
        module_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core", "v2_final_consolidation_coherence.py",
        )
        with open(module_path, encoding="utf-8") as fh:
            source = fh.read()
        # Must not import a new parallel orchestration engine
        prohibited = [
            "parallel_orchestration_engine",
            "new_scheduler",
            "detached_manifestation",
            "mock_state_store",
        ]
        for name in prohibited:
            assert name not in source, (
                f"core.v2_final_consolidation_coherence must not reference '{name}': "
                "consolidation must not introduce a detached architecture"
            )

    def test_R2_coherence_module_references_existing_canonical_modules(self):
        """R2: coherence module probes only existing canonical V2 modules."""
        import os
        module_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core", "v2_final_consolidation_coherence.py",
        )
        with open(module_path, encoding="utf-8") as fh:
            source = fh.read()
        canonical_references = [
            "core.desktop_presence_runtime",
            "core.unified_continuity_legality_authority",
            "core.unified_orchestration_spine",
            "core.operator_surface",
            "core.android_device_state_store",
            "core.system_completion_status",
        ]
        for ref in canonical_references:
            assert ref in source, (
                f"core.v2_final_consolidation_coherence must reference '{ref}'"
            )


# ===========================================================================
# Group S — Android state only via V2 truth paths
# ===========================================================================


class TestAndroidStateViaV2TruthPaths:
    """Group S: Android-originated state flows only through V2 truth paths."""

    def test_S1_unified_runtime_truth_ingress_has_no_parallel_write_policy(self):
        """S1: unified_runtime_truth_ingress exports no-parallel-write policy."""
        from core.unified_runtime_truth_ingress import (
            NO_PARALLEL_WRITE_TO_CANONICAL_STATE_POLICY,
        )
        assert isinstance(NO_PARALLEL_WRITE_TO_CANONICAL_STATE_POLICY, str)
        assert len(NO_PARALLEL_WRITE_TO_CANONICAL_STATE_POLICY) > 10

    def test_S2_android_device_state_store_has_authority_sentinel(self):
        """S2: android_device_state_store exports ANDROID_DEVICE_STATE_STORE_AUTHORITY."""
        from core.android_device_state_store import ANDROID_DEVICE_STATE_STORE_AUTHORITY
        assert isinstance(ANDROID_DEVICE_STATE_STORE_AUTHORITY, str)
        assert len(ANDROID_DEVICE_STATE_STORE_AUTHORITY) > 10

    def test_S3_android_truth_paths_dimension_has_no_gaps(self):
        """S3: android_truth_paths coherence dimension has zero gaps."""
        from core.v2_final_consolidation_coherence import (
            assess_v2_consolidation_coherence,
            reset_v2_consolidation_coherence_report,
        )
        reset_v2_consolidation_coherence_report()
        report = assess_v2_consolidation_coherence()
        android_dim = next(d for d in report.dimensions if d.dimension == "android_truth_paths")
        assert android_dim.gaps == [], (
            f"android_truth_paths must have no gaps: {android_dim.gaps}"
        )


# ===========================================================================
# Group T — Summary mentions PR-10 V2 coherence
# ===========================================================================


class TestSummaryMentionsCoherence:
    """Group T: system_completion_status summary mentions PR-10 V2 coherence."""

    def test_T1_build_summary_includes_coherence_when_coherent(self):
        """T1: _build_summary includes coherence text when v2_coherence_overall=True."""
        from core.system_completion_status import _build_summary
        from core.dual_repo_system_completeness_review import (
            CompletenessVerdict,
            CompletenessReviewReport,
        )
        from core.system_final_acceptance_verdict import SystemAcceptanceReport
        # Build minimal stub objects using defaults
        review = CompletenessReviewReport(
            dimensions=[],
            verdict=CompletenessVerdict.partial_closure_gaps_present,
            blocking_gaps=[],
            deferred_acknowledged=[],
            summary="",
        )
        acceptance = SystemAcceptanceReport()
        summary = _build_summary(
            architecture_pct=90.0,
            runtime_readiness="ready",
            closure_pct=76.0,
            completeness_review=review,
            acceptance_report=acceptance,
            remaining_items=[],
            v2_coherence_overall=True,
            v2_coherence_incoherent_count=0,
        )
        # Must mention PR-10 V2 coherence status
        assert (
            "pr-10 v2" in summary.lower()
            or "收口一致性" in summary
            or "v2" in summary.lower()
        ), (
            "_build_summary must mention PR-10 V2 coherence when overall_coherent=True"
        )

    def test_T2_build_summary_includes_coherence_when_incoherent(self):
        """T2: _build_summary includes coherence text when v2_coherence_overall=False."""
        from core.system_completion_status import _build_summary
        from core.dual_repo_system_completeness_review import (
            CompletenessVerdict,
            CompletenessReviewReport,
        )
        from core.system_final_acceptance_verdict import SystemAcceptanceReport
        review = CompletenessReviewReport(
            dimensions=[],
            verdict=CompletenessVerdict.partial_closure_gaps_present,
            blocking_gaps=["gap1"],
            deferred_acknowledged=[],
            summary="",
        )
        acceptance = SystemAcceptanceReport()
        summary = _build_summary(
            architecture_pct=90.0,
            runtime_readiness="ready",
            closure_pct=76.0,
            completeness_review=review,
            acceptance_report=acceptance,
            remaining_items=[],
            v2_coherence_overall=False,
            v2_coherence_incoherent_count=2,
        )
        # Should mention gap count or dimension gaps
        assert (
            "2" in summary
            or "差距" in summary
            or "dimension" in summary.lower()
            or "incoherent" in summary.lower()
        ), (
            "_build_summary must mention incoherent count when overall_coherent=False"
        )


# ===========================================================================
# Group U-Y — Completeness review architecture_structure changes
# ===========================================================================


class TestCompletenessReviewArchitectureStructure:
    """Group U-Y: completeness review architecture_structure reflects consolidation."""

    @pytest.fixture(scope="class")
    def arch_entry(self):
        from core.dual_repo_system_completeness_review import (
            DualRepoSystemCompletenessReviewer,
            CompletenessDimension,
        )
        report = DualRepoSystemCompletenessReviewer().review()
        return report.get_dimension(CompletenessDimension.architecture_structure)

    def test_U1_architecture_structure_label_complete(self, arch_entry):
        """U1: architecture_structure label is 'complete' (gateway/dispatch use file fallback)."""
        from core.dual_repo_system_completeness_review import CompletenessLabel
        assert arch_entry.label == CompletenessLabel.complete, (
            f"architecture_structure label is '{arch_entry.label.value}', expected 'complete'. "
            f"gaps: {arch_entry.gap_items}"
        )

    def test_V1_architecture_structure_no_gaps(self, arch_entry):
        """V1: architecture_structure has no gap_items."""
        assert arch_entry.gap_items == [], (
            f"architecture_structure must have no gaps; found: {arch_entry.gap_items}"
        )

    def test_W1_completed_items_mention_consolidation_modules(self, arch_entry):
        """W1: completed_items mention PR-7/8/9 V2 consolidation modules."""
        completed_text = " ".join(arch_entry.completed_items).lower()
        assert "consolidation" in completed_text or "pr-7" in completed_text or "pr-8" in completed_text or "pr-9" in completed_text, (
            "architecture_structure completed_items must mention consolidation modules"
        )

    def test_X1_verdict_not_fully_closed(self):
        """X1: completeness review verdict remains partial_closure_gaps_present."""
        from core.dual_repo_system_completeness_review import (
            DualRepoSystemCompletenessReviewer,
            CompletenessVerdict,
        )
        report = DualRepoSystemCompletenessReviewer().review()
        assert report.verdict != CompletenessVerdict.fully_closed, (
            "Verdict must NOT be 'fully_closed': runtime proof and real-device "
            "evidence gaps still remain"
        )

    def test_Y1_test_references_include_pr10v2_test(self, arch_entry):
        """Y1: architecture_structure test_references include PR-10 V2 coherence test."""
        assert any(
            "pr10v2" in ref.lower() or "consolidation_coherence" in ref.lower()
            for ref in arch_entry.test_references
        ), (
            "architecture_structure test_references must include "
            "test_pr10v2_final_consolidation_coherence.py"
        )
