#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_prh_live_routing_explanation.py
===========================================

PR-H — Live Routing Explanation & Decision-Causality Wiring

Tests verifying that:
1.  SpineDecisionCollector accumulates live routing signals
2.  build_spine_explanation produces a RouteExplanation from live signals
3.  Live explanations correctly reflect path branch, posture gate,
    admissibility gate, capability graph, policy engine, and fallback signals
4.  Rejected candidates are populated from admissibility exclusions and
    capability-unconfirmed targets
5.  LIVE_ROUTING_EXPLANATION_WIRED sentinel is importable from both
    spine_explanation_builder and command_router
6.  SpineDecisionCollector is exception-safe (no signal recording ever raises)
7.  build_spine_explanation degrades gracefully with empty collector
8.  is_cross_device flag is correctly set for cross_device branches
9.  build_explanation_summary round-trip from a spine-produced explanation
10. The __init__.py re-exports new symbols correctly
"""

from __future__ import annotations

import pytest
from typing import Any, Dict


# ---------------------------------------------------------------------------
# 1. SpineDecisionCollector — basic construction
# ---------------------------------------------------------------------------

class TestSpineDecisionCollectorConstruction:
    def test_import(self):
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector(task_id="t1", trace_id="tr1")
        assert c.task_id == "t1"
        assert c.trace_id == "tr1"

    def test_defaults(self):
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector()
        assert c.task_id is None
        assert c.trace_id is None
        assert c._branch_kind is None
        assert c._adm_validated == []
        assert c._adm_excluded == []
        assert c._cap_confirmed == []
        assert c._cap_unconfirmed == []
        assert c._fallback_triggered is False
        assert c._success is None


# ---------------------------------------------------------------------------
# 2. SpineDecisionCollector — signal recording
# ---------------------------------------------------------------------------

class TestSpineDecisionCollectorSignals:
    def test_record_initial_targets(self):
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector()
        c.record_initial_targets(["dev-a", "dev-b"])
        assert c._original_targets == ["dev-a", "dev-b"]
        assert c._selected_target == "dev-a"

    def test_record_posture_gate(self):
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector()
        c.record_posture_gate(posture="join_runtime", eligible=True)
        assert c._posture_applied is True
        assert c._posture_value == "join_runtime"
        assert c._posture_eligible is True
        assert c._policy_posture == "join_runtime"

    def test_record_posture_gate_ineligible(self):
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector()
        c.record_posture_gate(posture="control_only", eligible=False)
        assert c._posture_eligible is False

    def test_record_admissibility(self):
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector()
        c.record_admissibility(validated=["dev-a"], excluded=["dev-b"])
        assert c._adm_applied is True
        assert c._adm_validated == ["dev-a"]
        assert c._adm_excluded == ["dev-b"]
        assert c._selected_target == "dev-a"

    def test_record_capability_check(self):
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector()
        c.record_capability_check(
            confirmed=["dev-a"], unconfirmed=["dev-c"], required_caps=["screen"]
        )
        assert c._cap_applied is True
        assert c._cap_confirmed == ["dev-a"]
        assert c._cap_unconfirmed == ["dev-c"]
        assert c._cap_required == ["screen"]
        assert c._selected_target == "dev-a"

    def test_record_path_branch(self):
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector()
        c.record_path_branch("local", reason="no cross-device signal")
        assert c._branch_kind == "local"
        assert c._branch_reason == "no cross-device signal"

    def test_record_policy_engine_decision(self):
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector()
        c.record_policy_engine_decision(
            policy_kind="single_device_local",
            decision_reason="single candidate",
            policy_band="bounded_execute",
            candidates=["dev-a"],
        )
        assert c._policy_kind == "single_device_local"
        assert c._policy_reason == "single candidate"
        assert c._policy_band == "bounded_execute"

    def test_record_result(self):
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector()
        c.record_result(success=True, selected_target="dev-a")
        assert c._success is True
        assert c._selected_target == "dev-a"

    def test_record_result_failure(self):
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector()
        c.record_result(
            success=False,
            error_code="DEVICE_UNAVAILABLE",
            failure_domain="device",
        )
        assert c._success is False
        assert c._error_code == "DEVICE_UNAVAILABLE"
        assert c._failure_domain == "device"

    def test_record_fallback(self):
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector()
        c.record_fallback(triggered=True, reason="primary route failed")
        assert c._fallback_triggered is True
        assert c._fallback_reason == "primary route failed"


# ---------------------------------------------------------------------------
# 3. SpineDecisionCollector — exception safety
# ---------------------------------------------------------------------------

class TestSpineDecisionCollectorExceptionSafety:
    """All record_* methods must be safe even with bad inputs."""

    def test_record_initial_targets_bad_input(self):
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector()
        # Should not raise
        c.record_initial_targets(None)  # type: ignore[arg-type]

    def test_record_posture_gate_bad_input(self):
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector()
        c.record_posture_gate(posture=None, eligible=None)  # type: ignore[arg-type]

    def test_record_admissibility_bad_input(self):
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector()
        c.record_admissibility(validated=None, excluded=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 4. build_spine_explanation — local path
# ---------------------------------------------------------------------------

class TestBuildSpineExplanationLocal:
    def _make_local_collector(self) -> Any:
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector(task_id="t-local", trace_id="tr-local")
        c.record_initial_targets(["device-1"])
        c.record_path_branch("local", reason="no cross-device signal")
        c.record_result(success=True, selected_target="device-1")
        return c

    def test_selected_target_is_correct(self):
        from core.routing_explanation.spine_explanation_builder import build_spine_explanation
        exp = build_spine_explanation(self._make_local_collector())
        assert exp.selected_target == "device-1"

    def test_task_id_trace_id_propagated(self):
        from core.routing_explanation.spine_explanation_builder import build_spine_explanation
        exp = build_spine_explanation(self._make_local_collector())
        assert exp.task_id == "t-local"
        assert exp.trace_id == "tr-local"

    def test_has_at_least_one_basis(self):
        from core.routing_explanation.spine_explanation_builder import build_spine_explanation
        exp = build_spine_explanation(self._make_local_collector())
        assert len(exp.decision_bases) >= 1

    def test_branch_basis_present(self):
        from core.routing_explanation.spine_explanation_builder import build_spine_explanation
        from core.routing_explanation.decision_basis import DecisionFactor
        exp = build_spine_explanation(self._make_local_collector())
        factors = [b.factor for b in exp.decision_bases]
        assert DecisionFactor.POLICY in factors

    def test_policy_posture_local(self):
        from core.routing_explanation.spine_explanation_builder import build_spine_explanation
        exp = build_spine_explanation(self._make_local_collector())
        # Without posture gate, posture should be "undecided" or "local_*"
        # (not forced to remote for local branch)
        assert exp.policy_posture in ("undecided", "local_preferred")

    def test_no_rejected_for_local_all_pass(self):
        from core.routing_explanation.spine_explanation_builder import build_spine_explanation
        exp = build_spine_explanation(self._make_local_collector())
        assert exp.rejected_candidates == []

    def test_owner_component(self):
        from core.routing_explanation.spine_explanation_builder import build_spine_explanation
        exp = build_spine_explanation(self._make_local_collector())
        assert exp.owner_component == "command_router.route_envelope"

    def test_to_dict_is_json_serialisable(self):
        import json
        from core.routing_explanation.spine_explanation_builder import build_spine_explanation
        exp = build_spine_explanation(self._make_local_collector())
        d = exp.to_dict()
        # Must not raise
        json.dumps(d)

    def test_fallback_none_when_not_triggered(self):
        from core.routing_explanation.spine_explanation_builder import build_spine_explanation
        exp = build_spine_explanation(self._make_local_collector())
        assert exp.fallback_plan is None


# ---------------------------------------------------------------------------
# 5. build_spine_explanation — cross-device path
# ---------------------------------------------------------------------------

class TestBuildSpineExplanationCrossDevice:
    def _make_cross_device_collector(self) -> Any:
        from core.routing_explanation.spine_explanation_builder import SpineDecisionCollector
        c = SpineDecisionCollector(task_id="t-cd", trace_id="tr-cd")
        c.record_initial_targets(["android-1"])
        c.record_path_branch(
            "cross_device",
            reason="explicit executor_target_type=android_device",
        )
        c.record_result(success=True, selected_target="android-1")
        return c

    def test_is_cross_device_true_in_summary(self):
        from core.routing_explanation.spine_explanation_builder import build_spine_explanation
        from core.routing_explanation.explanation_summary import build_explanation_summary
        exp = build_spine_explanation(self._make_cross_device_collector())
        summary = build_explanation_summary(exp)
        assert summary.is_cross_device is True

    def test_policy_posture_not_undecided(self):
        from core.routing_explanation.spine_explanation_builder import build_spine_explanation
        exp = build_spine_explanation(self._make_cross_device_collector())
        # cross_device branch should not leave posture as "undecided"
        assert exp.policy_posture != "undecided"

    def test_branch_description_mentions_cross_device(self):
        from core.routing_explanation.spine_explanation_builder import build_spine_explanation
        exp = build_spine_explanation(self._make_cross_device_collector())
        basis_descs = [b.description for b in exp.decision_bases]
        assert any("cross_device" in d.lower() or "cross-device" in d.lower() for d in basis_descs)


# ---------------------------------------------------------------------------
# 6. build_spine_explanation — admissibility exclusions → rejected candidates
# ---------------------------------------------------------------------------

class TestBuildSpineExplanationAdmissibility:
    def test_excluded_targets_become_rejected_candidates(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        c = SpineDecisionCollector(task_id="t-adm", trace_id="tr-adm")
        c.record_initial_targets(["dev-ok", "dev-bad"])
        c.record_admissibility(validated=["dev-ok"], excluded=["dev-bad"])
        c.record_path_branch("local")
        c.record_result(success=True)

        exp = build_spine_explanation(c)
        rejected_ids = [rc.candidate_id for rc in exp.rejected_candidates]
        assert "dev-bad" in rejected_ids

    def test_rejected_candidate_has_rejection_reason(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        c = SpineDecisionCollector()
        c.record_admissibility(validated=["dev-ok"], excluded=["dev-bad"])
        c.record_path_branch("local")
        exp = build_spine_explanation(c)
        for rc in exp.rejected_candidates:
            if rc.candidate_id == "dev-bad":
                assert rc.rejection_reason  # non-empty
                assert rc.was_available is False

    def test_all_excluded_graceful_degradation(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        c = SpineDecisionCollector()
        c.record_admissibility(validated=[], excluded=["dev-1", "dev-2"])
        c.record_path_branch("local")
        exp = build_spine_explanation(c)
        # Both should be rejected
        rejected_ids = [rc.candidate_id for rc in exp.rejected_candidates]
        assert "dev-1" in rejected_ids
        assert "dev-2" in rejected_ids
        # Basis should mention graceful degradation
        descs = [b.description for b in exp.decision_bases]
        assert any("degradation" in d.lower() or "failed" in d.lower() for d in descs)


# ---------------------------------------------------------------------------
# 7. build_spine_explanation — capability unconfirmed → rejected candidates
# ---------------------------------------------------------------------------

class TestBuildSpineExplanationCapability:
    def test_unconfirmed_become_rejected(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        c = SpineDecisionCollector()
        c.record_capability_check(
            confirmed=["dev-ok"],
            unconfirmed=["dev-no-cap"],
            required_caps=["camera"],
        )
        c.record_path_branch("local")
        exp = build_spine_explanation(c)
        rejected_ids = [rc.candidate_id for rc in exp.rejected_candidates]
        assert "dev-no-cap" in rejected_ids

    def test_unconfirmed_rejection_reason_mentions_capability(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        c = SpineDecisionCollector()
        c.record_capability_check(
            confirmed=["dev-ok"],
            unconfirmed=["dev-no-cap"],
            required_caps=["camera"],
        )
        c.record_path_branch("local")
        exp = build_spine_explanation(c)
        for rc in exp.rejected_candidates:
            if rc.candidate_id == "dev-no-cap":
                assert rc.capability_match is False
                assert "capability" in rc.rejection_reason.lower()


# ---------------------------------------------------------------------------
# 8. build_spine_explanation — fallback scenario
# ---------------------------------------------------------------------------

class TestBuildSpineExplanationFallback:
    def test_fallback_plan_set(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        c = SpineDecisionCollector()
        c.record_path_branch("cross_device")
        c.record_fallback(triggered=True, reason="device-B is the fallback")
        exp = build_spine_explanation(c)
        assert exp.fallback_plan == "device-B is the fallback"

    def test_fallback_basis_present(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        from core.routing_explanation.decision_basis import DecisionFactor
        c = SpineDecisionCollector()
        c.record_path_branch("cross_device")
        c.record_fallback(triggered=True, reason="primary unavailable")
        exp = build_spine_explanation(c)
        factors = [b.factor for b in exp.decision_bases]
        assert DecisionFactor.FALLBACK in factors

    def test_summary_has_fallback(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        from core.routing_explanation.explanation_summary import build_explanation_summary
        c = SpineDecisionCollector()
        c.record_path_branch("cross_device")
        c.record_fallback(triggered=True, reason="fallback engaged")
        exp = build_spine_explanation(c)
        summary = build_explanation_summary(exp)
        assert summary.has_fallback is True
        assert summary.fallback_plan == "fallback engaged"


# ---------------------------------------------------------------------------
# 9. build_spine_explanation — policy engine decision
# ---------------------------------------------------------------------------

class TestBuildSpineExplanationPolicyEngine:
    def test_policy_kind_in_basis(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        c = SpineDecisionCollector()
        c.record_path_branch("local")
        c.record_policy_engine_decision(
            policy_kind="multi_device_balanced",
            decision_reason="multiple healthy devices",
        )
        exp = build_spine_explanation(c)
        descs = [b.description for b in exp.decision_bases]
        assert any("multi_device_balanced" in d for d in descs)

    def test_policy_band_propagated(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        c = SpineDecisionCollector()
        c.record_path_branch("local")
        c.record_policy_engine_decision(
            policy_kind="single_device_local",
            decision_reason="single device",
            policy_band="bounded_execute",
        )
        exp = build_spine_explanation(c)
        assert exp.policy_band == "bounded_execute"


# ---------------------------------------------------------------------------
# 10. build_spine_explanation — failure outcome
# ---------------------------------------------------------------------------

class TestBuildSpineExplanationFailure:
    def test_failure_basis_present(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        from core.routing_explanation.decision_basis import DecisionFactor
        c = SpineDecisionCollector()
        c.record_path_branch("local")
        c.record_result(success=False, error_code="TIMEOUT", failure_domain="network")
        exp = build_spine_explanation(c)
        # An availability basis with accepted=False should be present
        failed_bases = [b for b in exp.decision_bases if not b.accepted]
        assert len(failed_bases) >= 1

    def test_failure_basis_mentions_error(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        c = SpineDecisionCollector()
        c.record_path_branch("local")
        c.record_result(success=False, error_code="TIMEOUT")
        exp = build_spine_explanation(c)
        descs = " ".join(b.description for b in exp.decision_bases)
        assert "TIMEOUT" in descs


# ---------------------------------------------------------------------------
# 11. build_spine_explanation — empty collector degrades gracefully
# ---------------------------------------------------------------------------

class TestBuildSpineExplanationEmptyCollector:
    def test_empty_collector_returns_explanation(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        from core.routing_explanation.route_explanation import RouteExplanation
        c = SpineDecisionCollector()
        exp = build_spine_explanation(c)
        assert isinstance(exp, RouteExplanation)

    def test_empty_collector_never_raises(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        c = SpineDecisionCollector()
        # Should not raise
        exp = build_spine_explanation(c)
        _ = exp.to_dict()


# ---------------------------------------------------------------------------
# 12. LIVE_ROUTING_EXPLANATION_WIRED sentinel importable
# ---------------------------------------------------------------------------

class TestLiveRoutingExplanationWiredSentinel:
    def test_sentinel_importable_from_builder(self):
        from core.routing_explanation.spine_explanation_builder import (
            LIVE_ROUTING_EXPLANATION_WIRED,
        )
        assert isinstance(LIVE_ROUTING_EXPLANATION_WIRED, str)
        assert "LIVE_ROUTING_EXPLANATION" in LIVE_ROUTING_EXPLANATION_WIRED

    def test_sentinel_importable_from_command_router(self):
        pytest.importorskip("pydantic", reason="pydantic not installed — skipping command_router import")
        from core.command_router import LIVE_ROUTING_EXPLANATION_WIRED
        assert isinstance(LIVE_ROUTING_EXPLANATION_WIRED, str)
        assert "LIVE_ROUTING_EXPLANATION" in LIVE_ROUTING_EXPLANATION_WIRED

    def test_sentinel_mentions_spine_collector(self):
        from core.routing_explanation.spine_explanation_builder import (
            LIVE_ROUTING_EXPLANATION_WIRED,
        )
        assert "SpineDecisionCollector" in LIVE_ROUTING_EXPLANATION_WIRED

    def test_sentinel_mentions_routing_explanation(self):
        pytest.importorskip("pydantic", reason="pydantic not installed — skipping command_router import")
        from core.command_router import LIVE_ROUTING_EXPLANATION_WIRED
        assert "routing_explanation" in LIVE_ROUTING_EXPLANATION_WIRED


# ---------------------------------------------------------------------------
# 13. __init__.py re-exports
# ---------------------------------------------------------------------------

class TestPackageReExports:
    def test_spine_collector_importable_from_package(self):
        from core.routing_explanation import SpineDecisionCollector
        assert SpineDecisionCollector is not None

    def test_build_spine_explanation_importable_from_package(self):
        from core.routing_explanation import build_spine_explanation
        assert build_spine_explanation is not None

    def test_live_routing_explanation_wired_importable_from_package(self):
        from core.routing_explanation import LIVE_ROUTING_EXPLANATION_WIRED
        assert LIVE_ROUTING_EXPLANATION_WIRED is not None


# ---------------------------------------------------------------------------
# 14. Full round-trip: collector → explanation → summary → to_dict
# ---------------------------------------------------------------------------

class TestFullRoundTrip:
    def test_full_round_trip_local(self):
        import json
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        from core.routing_explanation.explanation_summary import build_explanation_summary

        c = SpineDecisionCollector(task_id="rt-1", trace_id="tr-rt-1")
        c.record_initial_targets(["device-1", "device-2"])
        c.record_posture_gate(posture="join_runtime", eligible=True)
        c.record_admissibility(validated=["device-1"], excluded=["device-2"])
        c.record_capability_check(
            confirmed=["device-1"],
            unconfirmed=[],
            required_caps=["screen"],
        )
        c.record_path_branch("local", reason="single confirmed target")
        c.record_policy_engine_decision(
            policy_kind="single_device_local",
            decision_reason="device-1 only",
        )
        c.record_result(success=True, selected_target="device-1")

        exp = build_spine_explanation(c)
        assert exp.selected_target == "device-1"
        assert exp.task_id == "rt-1"
        assert exp.trace_id == "tr-rt-1"
        assert len(exp.decision_bases) >= 2
        assert len(exp.rejected_candidates) >= 1

        summary = build_explanation_summary(exp)
        assert summary.route_target == "device-1"
        assert summary.task_id == "rt-1"
        assert summary.trace_id == "tr-rt-1"
        assert summary.schema_version == 1

        d = summary.to_dict()
        # Must be JSON-serialisable
        json.dumps(d)
        # Must contain expected keys
        assert "route_target" in d
        assert "decision_basis_list" in d
        assert "rejected_alternatives" in d
        assert "confidence" in d

    def test_full_round_trip_cross_device_with_fallback(self):
        import json
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        from core.routing_explanation.explanation_summary import build_explanation_summary

        c = SpineDecisionCollector(task_id="rt-2", trace_id="tr-rt-2")
        c.record_initial_targets(["android-1"])
        c.record_path_branch("cross_device", reason="cross_device=true metadata")
        c.record_fallback(triggered=True, reason="fallback to android-2 available")
        c.record_result(success=True, selected_target="android-1")

        exp = build_spine_explanation(c)
        summary = build_explanation_summary(exp)

        assert summary.is_cross_device is True
        assert summary.has_fallback is True
        assert summary.fallback_plan is not None

        d = summary.to_dict()
        json.dumps(d)

    def test_explanation_hints_populated(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        from core.routing_explanation.explanation_summary import (
            build_explanation_summary, get_explanation_hints,
        )
        c = SpineDecisionCollector(task_id="rt-3", trace_id="tr-rt-3")
        c.record_initial_targets(["dev-1"])
        c.record_admissibility(validated=["dev-1"], excluded=["dev-2"])
        c.record_path_branch("local")
        c.record_result(success=True)

        exp = build_spine_explanation(c)
        summary = build_explanation_summary(exp)
        hints = get_explanation_hints(summary)

        assert "route_target" in hints
        assert "confidence_band" in hints
        assert "has_rejected_alternatives" in hints
        assert hints["has_rejected_alternatives"] is True
        assert hints["rejected_count"] >= 1


# ---------------------------------------------------------------------------
# 15. Decision causality — explanation reflects live signals, not defaults
# ---------------------------------------------------------------------------

class TestExplanationCausalityAlignment:
    """Verify that the explanation output is derived from actual live signals,
    not from static projection defaults."""

    def test_policy_posture_comes_from_posture_gate(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        c = SpineDecisionCollector()
        c.record_posture_gate(posture="remote_required", eligible=True)
        c.record_path_branch("cross_device")
        exp = build_spine_explanation(c)
        assert exp.policy_posture == "remote_required"

    def test_policy_reason_comes_from_policy_engine(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        c = SpineDecisionCollector()
        c.record_path_branch("local")
        c.record_policy_engine_decision(
            policy_kind="policy-abc",
            decision_reason="custom reason from engine",
        )
        exp = build_spine_explanation(c)
        assert exp.policy_reason == "custom reason from engine"

    def test_rejected_candidates_from_live_gates_not_static(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        c = SpineDecisionCollector()
        # No admissibility or capability exclusions → should have no rejected candidates
        c.record_path_branch("local")
        c.record_result(success=True)
        exp = build_spine_explanation(c)
        assert exp.rejected_candidates == []

    def test_multiple_rejection_sources_combined(self):
        from core.routing_explanation.spine_explanation_builder import (
            SpineDecisionCollector, build_spine_explanation,
        )
        c = SpineDecisionCollector()
        c.record_admissibility(validated=["dev-ok"], excluded=["dev-adm-fail"])
        c.record_capability_check(
            confirmed=["dev-ok"],
            unconfirmed=["dev-cap-fail"],
            required_caps=["screen"],
        )
        c.record_path_branch("local")
        exp = build_spine_explanation(c)
        rejected_ids = {rc.candidate_id for rc in exp.rejected_candidates}
        assert "dev-adm-fail" in rejected_ids
        assert "dev-cap-fail" in rejected_ids
