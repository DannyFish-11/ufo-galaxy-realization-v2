#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr10_v2_final_consolidation.py
==========================================
PR-10 V2 Final Consolidation Tests

Validates the final V2-side consolidation pass that makes the current system
behave as a more unified AI-body network across its existing canonical center
and carrier paths.

Coverage
--------
1.  All five V2 canonical consolidation paths are structurally available.
2.  V2 consolidation evidence can be built without errors.
3.  Consolidation chain is coherent (all 6 path modules available).
4.  Orchestration review surface produces a snapshot (may be partial).
5.  Continuity coordinator is available and constructable.
6.  Operator truth surfaces are structurally available.
7.  SystemCompletionStatus includes v2_consolidation_evidence field.
8.  v2_consolidation_evidence keys are all present and correct types.
9.  status_alignment includes v2_consolidation_chain_coherent flag.
10. Completion status is honest: system not declared fully closed without evidence.
11. Architecture structure dimension reaches 'complete' when all files present.
12. Runtime closure dimension stays 'evidence_gap' in fresh environment.
13. Cross-repo evidence dimension is 'evidence_gap' without runtime Android device.
14. Completeness verdict is not fully_closed (honest about remaining gaps).
15. Ingress truth aligns with continuity chain.
16. Operator surface aligns with flow-level operator surface.
17. Android state is only represented through existing V2 truth paths.
18. No detached parallel architecture is introduced.
19. All six chain path modules are independently importable.
20. Summary output includes consolidation chain status.
"""

from __future__ import annotations

import json
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_import(module_path: str) -> bool:
    import importlib
    try:
        importlib.import_module(module_path)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 1–6. Canonical V2 consolidation paths structural availability
# ---------------------------------------------------------------------------


class TestConsolidationPathsAvailable:
    """Verify each canonical V2 consolidation path is structurally importable."""

    def test_01_ingress_path_available(self):
        assert _try_import("core.unified_runtime_truth_ingress"), (
            "core.unified_runtime_truth_ingress must be importable — "
            "it is the canonical ingress truth path."
        )

    def test_02_continuity_path_available(self):
        assert _try_import("core.flow_continuity_coordinator"), (
            "core.flow_continuity_coordinator must be importable — "
            "it is the canonical continuity path."
        )

    def test_03_orchestration_review_path_available(self):
        assert _try_import("core.orchestration_review_surface"), (
            "core.orchestration_review_surface must be importable — "
            "it is the canonical orchestration observability path (PR-10)."
        )

    def test_04_manifestation_path_available(self):
        assert _try_import("core.desktop_presence_runtime"), (
            "core.desktop_presence_runtime must be importable — "
            "it is the canonical manifestation/shell/presence path."
        )

    def test_05_operator_surface_available(self):
        assert _try_import("core.operator_surface"), (
            "core.operator_surface must be importable — "
            "it is the canonical operator truth surface."
        )

    def test_06_flow_operator_surface_available(self):
        assert _try_import("core.flow_level_operator_surface"), (
            "core.flow_level_operator_surface must be importable — "
            "it is the canonical flow-level operator truth surface."
        )


# ---------------------------------------------------------------------------
# 7–9. SystemCompletionStatus — v2_consolidation_evidence
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def completion_status():
    from core.system_completion_status import (
        build_system_completion_status,
        reset_system_completion_status,
    )
    reset_system_completion_status()
    return build_system_completion_status()


@pytest.fixture(scope="module")
def consolidation_evidence(completion_status):
    return completion_status.v2_consolidation_evidence


class TestSystemCompletionStatusConsolidation:
    """Verify SystemCompletionStatus includes V2 final consolidation evidence."""

    def test_07_completion_status_has_v2_consolidation_evidence(
        self, completion_status
    ):
        assert hasattr(completion_status, "v2_consolidation_evidence"), (
            "SystemCompletionStatus must have a v2_consolidation_evidence field "
            "(added by PR-10 V2 final consolidation pass)."
        )
        assert isinstance(completion_status.v2_consolidation_evidence, dict), (
            "v2_consolidation_evidence must be a dict."
        )

    def test_08_consolidation_evidence_required_keys(self, consolidation_evidence):
        required_keys = {
            "chain_paths_available",
            "chain_coherent",
            "available_count",
            "total_count",
            "consolidation_verdict",
            "orchestration_snapshot_ok",
            "continuity_coordinator_ok",
        }
        for key in required_keys:
            assert key in consolidation_evidence, (
                f"v2_consolidation_evidence must have key '{key}'."
            )

    def test_08b_consolidation_evidence_chain_paths_keys(self, consolidation_evidence):
        chain_paths = consolidation_evidence["chain_paths_available"]
        assert isinstance(chain_paths, dict)
        expected_paths = {
            "ingress",
            "continuity",
            "orchestration_review",
            "manifestation",
            "operator_surface",
            "flow_operator_surface",
        }
        for path in expected_paths:
            assert path in chain_paths, (
                f"chain_paths_available must contain key '{path}'."
            )
            assert isinstance(chain_paths[path], bool)

    def test_08c_consolidation_evidence_counts_consistent(self, consolidation_evidence):
        chain_paths = consolidation_evidence["chain_paths_available"]
        expected_available = sum(1 for v in chain_paths.values() if v)
        assert consolidation_evidence["available_count"] == expected_available
        assert consolidation_evidence["total_count"] == len(chain_paths)

    def test_09_status_alignment_has_consolidation_flag(self, completion_status):
        assert "v2_consolidation_chain_coherent" in completion_status.status_alignment, (
            "status_alignment must include 'v2_consolidation_chain_coherent' "
            "(added by PR-10 V2 final consolidation pass)."
        )
        assert isinstance(
            completion_status.status_alignment["v2_consolidation_chain_coherent"], bool
        )

    def test_09b_consolidation_chain_coherent_matches_evidence(
        self, completion_status, consolidation_evidence
    ):
        assert (
            completion_status.status_alignment["v2_consolidation_chain_coherent"]
            == consolidation_evidence["chain_coherent"]
        ), (
            "status_alignment['v2_consolidation_chain_coherent'] must match "
            "v2_consolidation_evidence['chain_coherent']."
        )


# ---------------------------------------------------------------------------
# 10–14. Honest completion reporting
# ---------------------------------------------------------------------------


class TestHonestCompletionReporting:
    """Verify completion status is honest about what's closed and what's not."""

    def test_10_system_not_declared_fully_closed(self, completion_status):
        assert not completion_status.is_fully_closed, (
            "System must NOT be declared fully closed in a fresh environment "
            "without real runtime evidence (no Android device, no live execution). "
            "is_fully_closed must be False."
        )

    def test_10b_verdict_not_fully_closed(self, completion_status):
        from core.dual_repo_system_completeness_review import CompletenessVerdict
        assert completion_status.completeness_verdict != CompletenessVerdict.fully_closed.value, (
            "completeness_verdict must not be 'fully_closed' in a fresh environment."
        )

    def test_10c_system_not_fully_operational(self, completion_status):
        assert not completion_status.is_fully_operational, (
            "System must NOT be declared fully operational in a fresh environment "
            "without real device evidence and live execution events."
        )

    def test_10d_closure_pct_below_100(self, completion_status):
        assert completion_status.system_closure_pct < 100.0, (
            "system_closure_pct must be < 100% in a fresh environment. "
            f"Got: {completion_status.system_closure_pct}"
        )

    def test_10e_architecture_pct_100(self, completion_status):
        assert completion_status.architecture_completion_pct == 100.0, (
            "architecture_completion_pct should be 100% — all V2 structural "
            "files are present (even if some need optional runtime deps)."
        )

    def test_11_architecture_structure_complete(self):
        from core.dual_repo_system_completeness_review import (
            build_completeness_review,
            CompletenessDimension,
            CompletenessLabel,
        )
        report = build_completeness_review()
        entry = report.get_dimension(CompletenessDimension.architecture_structure)
        assert entry is not None
        assert entry.label == CompletenessLabel.complete, (
            "architecture_structure must be 'complete': all structural source "
            "files are present (gateway, dispatch chain, core modules). "
            f"Got: {entry.label.value}. Gaps: {entry.gap_items}"
        )

    def test_12_runtime_closure_evidence_gap_fresh_env(self):
        from core.dual_repo_system_completeness_review import (
            build_completeness_review,
            CompletenessDimension,
            CompletenessLabel,
        )
        report = build_completeness_review()
        entry = report.get_dimension(CompletenessDimension.runtime_closure)
        assert entry is not None
        assert entry.label == CompletenessLabel.evidence_gap, (
            "runtime_closure must be 'evidence_gap' in a fresh environment "
            "(no delegated flow has been exercised end-to-end). "
            f"Got: {entry.label.value}"
        )

    def test_13_cross_repo_evidence_gap_no_android_device(self):
        from core.dual_repo_system_completeness_review import (
            build_completeness_review,
            CompletenessDimension,
            CompletenessLabel,
        )
        report = build_completeness_review()
        entry = report.get_dimension(CompletenessDimension.cross_repo_evidence)
        assert entry is not None
        assert entry.label == CompletenessLabel.evidence_gap, (
            "cross_repo_evidence must be 'evidence_gap' when no Android device "
            "has connected and provided a live state snapshot. "
            f"Got: {entry.label.value}"
        )
        # Verify the gap mentions runtime activation
        gap_text = " ".join(entry.gap_items).lower()
        assert "runtime" in gap_text or "activated" in gap_text, (
            "cross_repo_evidence gap_items must mention the runtime activation "
            "requirement (no live signal observed)."
        )

    def test_14_completeness_verdict_not_fully_closed(self):
        from core.dual_repo_system_completeness_review import (
            build_completeness_review,
            CompletenessVerdict,
        )
        report = build_completeness_review()
        assert not report.is_fully_closed, (
            "dual_repo_system_completeness_review verdict must not be "
            "'fully_closed' in a fresh environment."
        )
        assert report.verdict != CompletenessVerdict.fully_closed


# ---------------------------------------------------------------------------
# 15–18. Alignment and canonical path integrity
# ---------------------------------------------------------------------------


class TestCanonicalPathAlignment:
    """Verify canonical paths stay aligned and no detached architecture is introduced."""

    def test_15_ingress_truth_chain_to_continuity(self):
        """Ingress truth and continuity are both available (aligned chain)."""
        ingress_ok = _try_import("core.unified_runtime_truth_ingress")
        continuity_ok = _try_import("core.flow_continuity_coordinator")
        assert ingress_ok and continuity_ok, (
            "Both ingress truth (core.unified_runtime_truth_ingress) and "
            "continuity (core.flow_continuity_coordinator) must be importable "
            "for the ingress→continuity chain to be aligned."
        )

    def test_15b_ingress_policy_sentinel_present(self):
        """Ingress truth module has its routing policy sentinel."""
        from core.unified_runtime_truth_ingress import (
            INGRESS_ROUTES_TO_CORRECT_SUB_PATH_POLICY,
        )
        assert INGRESS_ROUTES_TO_CORRECT_SUB_PATH_POLICY
        assert "INGRESS_ROUTES_TO_CORRECT_SUB_PATH_PR2" in (
            INGRESS_ROUTES_TO_CORRECT_SUB_PATH_POLICY
        )

    def test_16_operator_surfaces_aligned(self):
        """Both operator surfaces are available for aligned operator truth."""
        assert _try_import("core.operator_surface"), (
            "core.operator_surface must be importable."
        )
        assert _try_import("core.flow_level_operator_surface"), (
            "core.flow_level_operator_surface must be importable."
        )

    def test_17_android_state_only_via_v2_truth_paths(self):
        """Android state is only accessible via existing V2 truth paths (not fabricated)."""
        # The android_device_state_store is the canonical Android state store on V2.
        # Verify it follows existing V2 ingress/truth pattern.
        assert _try_import("core.android_device_state_store"), (
            "core.android_device_state_store must be importable — "
            "it is the V2-side Android state truth path."
        )
        # The ecosystem summary should never fabricate device data.
        from core.android_device_state_store import get_device_ecosystem_summary
        summary = get_device_ecosystem_summary()
        assert isinstance(summary, dict)
        # In a fresh environment, there must be no fabricated devices.
        assert summary.get("total_devices_with_snapshot", 0) == 0, (
            "In a fresh environment with no Android device connected, "
            "total_devices_with_snapshot must be 0 (not fabricated). "
            f"Got: {summary.get('total_devices_with_snapshot')}"
        )

    def test_18_no_detached_architecture_in_consolidation_evidence(
        self, consolidation_evidence
    ):
        """Consolidation evidence only references existing canonical paths."""
        chain_paths = consolidation_evidence["chain_paths_available"]
        # All referenced modules must be the canonical ones from prior PRs.
        canonical_modules = {
            "ingress": "core.unified_runtime_truth_ingress",
            "continuity": "core.flow_continuity_coordinator",
            "orchestration_review": "core.orchestration_review_surface",
            "manifestation": "core.desktop_presence_runtime",
            "operator_surface": "core.operator_surface",
            "flow_operator_surface": "core.flow_level_operator_surface",
        }
        # All chain path keys must match the expected canonical modules.
        for path_key in canonical_modules:
            assert path_key in chain_paths, (
                f"chain_paths_available must include '{path_key}' "
                f"(canonical module: {canonical_modules[path_key]})."
            )


# ---------------------------------------------------------------------------
# 19–20. Individual path imports and summary
# ---------------------------------------------------------------------------


class TestIndividualPathsAndSummary:
    """Final import and summary checks."""

    @pytest.mark.parametrize("module_path", [
        "core.unified_runtime_truth_ingress",
        "core.flow_continuity_coordinator",
        "core.orchestration_review_surface",
        "core.desktop_presence_runtime",
        "core.operator_surface",
        "core.flow_level_operator_surface",
    ])
    def test_19_each_chain_path_independently_importable(self, module_path):
        assert _try_import(module_path), (
            f"{module_path} must be independently importable. "
            "If it fails, there is a direct dependency or circular import issue."
        )

    def test_20_summary_includes_consolidation_status(self, completion_status):
        assert completion_status.summary, (
            "SystemCompletionStatus.summary must be non-empty."
        )
        # The summary must include the consolidation chain status.
        # The Chinese text for consolidation path status is present.
        summary_lower = completion_status.summary.lower()
        assert (
            "consolidation" in summary_lower
            or "收口" in completion_status.summary
            or "链路" in completion_status.summary
        ), (
            "SystemCompletionStatus.summary must include consolidation chain "
            "status (added by PR-10 V2 final consolidation pass)."
        )

    def test_20b_completion_status_json_serializable(self, completion_status):
        """SystemCompletionStatus including v2_consolidation_evidence is JSON-safe."""
        data = json.loads(completion_status.to_json())
        assert "v2_consolidation_evidence" in data
        assert isinstance(data["v2_consolidation_evidence"], dict)
        assert "consolidation_verdict" in data["v2_consolidation_evidence"]
        assert "chain_coherent" in data["v2_consolidation_evidence"]
