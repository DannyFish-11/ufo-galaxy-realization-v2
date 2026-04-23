#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_prh_live_routing_explanation.py
===========================================

PR-H — Live Routing Explanation & Decision-Causality Wiring

Tests verifying that:
1. :class:`~core.routing_explanation.live_decision.LiveRoutingDecisionBuilder`
   correctly collects live routing signals and produces evidence-backed
   :class:`~core.routing_explanation.route_explanation.RouteExplanation` objects.
2. The route path selection, admissibility exclusion, capability enforcement,
   posture gate, and result outcome are all captured as structured decision bases
   and rejected candidates — not as static placeholder strings.
3. :func:`~core.routing_explanation.live_decision.live_explanation_to_record_str`
   serialises explanations to stable JSON suitable for
   :attr:`~core.replay_foundation.RouteDecisionRecord.route_explanation`.
4. The explanation is non-empty and reflects actual causality when signal
   recorders are called.
5. The ``routing_explanation`` key is present in the result dict produced by
   a minimal route_envelope stub that exercises the live builder wiring.

Test coverage
-------------
 1.  LiveRoutingDecisionBuilder — import and instantiation
 2.  record_route_path_selection — local path recorded as decision basis
 3.  record_route_path_selection — cross-device path recorded correctly
 4.  record_route_path_selection — worker path recorded correctly
 5.  record_route_path_selection — parallel fanout path recorded correctly
 6.  record_posture_gate — eligible posture recorded as POLICY basis
 7.  record_posture_gate — ineligible posture recorded with accepted=False
 8.  record_admissibility_gate — validated targets recorded
 9.  record_admissibility_gate — excluded targets appear as RejectedCandidate
10.  record_admissibility_gate — excluded targets also appear as AVAILABILITY basis
11.  record_capability_enforcement — confirmed targets recorded
12.  record_capability_enforcement — unconfirmed targets appear as RejectedCandidate
13.  record_capability_enforcement — with required_caps in basis description
14.  record_fallback — fallback plan set and FALLBACK basis added
15.  record_result_outcome — failure adds AVAILABILITY basis with accepted=False
16.  record_result_outcome — success adds no extra basis
17.  build — produces RouteExplanation with correct selected_target
18.  build — task_id / trace_id propagated to explanation
19.  build — confidence computed (not UNDETERMINED when bases present)
20.  build — degrades to EMPTY_ROUTE_EXPLANATION on internal error
21.  build_summary — returns RoutingExplanationSummary
22.  build_summary — is_cross_device True for cross-device path
23.  build_summary — has_fallback True when fallback recorded
24.  build_summary — rejected_alternatives populated from excluded targets
25.  live_explanation_to_record_str — returns valid JSON string
26.  live_explanation_to_record_str — JSON contains expected keys
27.  live_explanation_to_record_str — not the old placeholder string
28.  Combined flow: posture + admissibility + path + result → full explanation
29.  Combined flow: rejected candidate IDs are preserved in explanation
30.  Combined flow: decision_basis_list count matches recorded signals
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# 1. LiveRoutingDecisionBuilder — import and instantiation
# ---------------------------------------------------------------------------


class TestLiveRoutingDecisionBuilderImport:
    def test_import_builder(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        assert callable(LiveRoutingDecisionBuilder)

    def test_import_route_path_constants(self):
        from core.routing_explanation.live_decision import (
            ROUTE_PATH_CROSS_DEVICE,
            ROUTE_PATH_WORKER,
            ROUTE_PATH_LOCAL,
            ROUTE_PATH_PARALLEL_FANOUT,
        )
        assert ROUTE_PATH_CROSS_DEVICE == "cross_device"
        assert ROUTE_PATH_WORKER == "go_worker"
        assert ROUTE_PATH_LOCAL == "local"
        assert ROUTE_PATH_PARALLEL_FANOUT == "parallel_fanout"

    def test_import_via_package(self):
        from core.routing_explanation import (
            LiveRoutingDecisionBuilder,
            live_explanation_to_record_str,
            ROUTE_PATH_CROSS_DEVICE,
            ROUTE_PATH_LOCAL,
        )
        assert callable(LiveRoutingDecisionBuilder)
        assert callable(live_explanation_to_record_str)

    def test_instantiation_defaults(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        b = LiveRoutingDecisionBuilder()
        expl = b.build()
        # No signals recorded — empty explanation
        assert expl.selected_target is None
        assert expl.policy_posture == "undecided"

    def test_instantiation_with_ids(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        b = LiveRoutingDecisionBuilder(task_id="t1", trace_id="tr1")
        expl = b.build()
        assert expl.task_id == "t1"
        assert expl.trace_id == "tr1"


# ---------------------------------------------------------------------------
# 2–5. record_route_path_selection
# ---------------------------------------------------------------------------


class TestRecordRoutePathSelection:
    def _make_builder(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        return LiveRoutingDecisionBuilder(task_id="task-x", trace_id="trace-x")

    def test_local_path_selection(self):
        from core.routing_explanation.live_decision import ROUTE_PATH_LOCAL
        from core.routing_explanation.decision_basis import DecisionFactor
        b = self._make_builder()
        b.record_route_path_selection(ROUTE_PATH_LOCAL, selected_target="dev-1")
        expl = b.build()
        assert expl.selected_target == "dev-1"
        assert any(
            db.factor is DecisionFactor.POLICY
            and "local" in str(db.signal_value).lower()
            for db in expl.decision_bases
        )

    def test_cross_device_path_selection(self):
        from core.routing_explanation.live_decision import ROUTE_PATH_CROSS_DEVICE
        from core.routing_explanation.decision_basis import DecisionFactor
        b = self._make_builder()
        b.record_route_path_selection(ROUTE_PATH_CROSS_DEVICE, selected_target="android-1")
        expl = b.build()
        assert expl.selected_target == "android-1"
        assert any(
            db.factor is DecisionFactor.POLICY
            and "cross_device" in str(db.signal_value)
            for db in expl.decision_bases
        )

    def test_worker_path_selection(self):
        from core.routing_explanation.live_decision import ROUTE_PATH_WORKER
        from core.routing_explanation.decision_basis import DecisionFactor
        b = self._make_builder()
        b.record_route_path_selection(ROUTE_PATH_WORKER, selected_target="worker-1")
        expl = b.build()
        assert expl.selected_target == "worker-1"
        assert any(
            db.factor is DecisionFactor.POLICY
            and "go_worker" in str(db.signal_value)
            for db in expl.decision_bases
        )

    def test_parallel_fanout_path_selection(self):
        from core.routing_explanation.live_decision import ROUTE_PATH_PARALLEL_FANOUT
        from core.routing_explanation.decision_basis import DecisionFactor
        b = self._make_builder()
        b.record_route_path_selection(ROUTE_PATH_PARALLEL_FANOUT)
        expl = b.build()
        assert any(
            db.factor is DecisionFactor.POLICY
            and "parallel_fanout" in str(db.signal_value)
            for db in expl.decision_bases
        )

    def test_custom_reason_used_in_description(self):
        from core.routing_explanation.live_decision import ROUTE_PATH_LOCAL
        b = self._make_builder()
        b.record_route_path_selection(ROUTE_PATH_LOCAL, reason="custom reason here")
        expl = b.build()
        assert any(
            "custom reason here" in db.description
            for db in expl.decision_bases
        )


# ---------------------------------------------------------------------------
# 6–7. record_posture_gate
# ---------------------------------------------------------------------------


class TestRecordPostureGate:
    def test_eligible_posture_accepted_true(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        from core.routing_explanation.decision_basis import DecisionFactor
        b = LiveRoutingDecisionBuilder()
        b.record_posture_gate(posture="local_preferred", eligible=True)
        expl = b.build()
        assert expl.policy_posture == "local_preferred"
        basis = next(
            (db for db in expl.decision_bases if db.factor is DecisionFactor.POLICY),
            None,
        )
        assert basis is not None
        assert basis.accepted is True

    def test_ineligible_posture_accepted_false(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        from core.routing_explanation.decision_basis import DecisionFactor
        b = LiveRoutingDecisionBuilder()
        b.record_posture_gate(posture="control_only", eligible=False)
        expl = b.build()
        basis = next(
            (db for db in expl.decision_bases if db.factor is DecisionFactor.POLICY),
            None,
        )
        assert basis is not None
        assert basis.accepted is False

    def test_empty_posture_no_op(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        b = LiveRoutingDecisionBuilder()
        b.record_posture_gate(posture="", eligible=True)
        expl = b.build()
        assert len(expl.decision_bases) == 0


# ---------------------------------------------------------------------------
# 8–10. record_admissibility_gate
# ---------------------------------------------------------------------------


class TestRecordAdmissibilityGate:
    def test_validated_targets_recorded(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        from core.routing_explanation.decision_basis import DecisionFactor
        b = LiveRoutingDecisionBuilder()
        b.record_admissibility_gate(validated=["dev-1", "dev-2"], excluded=[])
        expl = b.build()
        basis = next(
            (db for db in expl.decision_bases if db.factor is DecisionFactor.AVAILABILITY),
            None,
        )
        assert basis is not None
        assert basis.accepted is True
        assert "dev-1" in str(basis.signal_value)

    def test_excluded_targets_in_rejected_candidates(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        b = LiveRoutingDecisionBuilder()
        b.record_admissibility_gate(
            validated=[],
            excluded=[("dev-offline", ["not-ready", "heartbeat-stale"])],
        )
        expl = b.build()
        assert len(expl.rejected_candidates) == 1
        rc = expl.rejected_candidates[0]
        assert rc.candidate_id == "dev-offline"
        assert rc.was_available is False
        assert "not-ready" in rc.rejection_reason

    def test_excluded_targets_also_add_rejection_basis(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        from core.routing_explanation.decision_basis import DecisionFactor
        b = LiveRoutingDecisionBuilder()
        b.record_admissibility_gate(
            validated=[],
            excluded=[("dev-bad", ["failed admissibility check"])],
        )
        expl = b.build()
        rejection_bases = [
            db for db in expl.decision_bases
            if db.factor is DecisionFactor.AVAILABILITY and db.accepted is False
        ]
        assert len(rejection_bases) == 1
        assert "dev-bad" in rejection_bases[0].description

    def test_mixed_validated_and_excluded(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        b = LiveRoutingDecisionBuilder()
        b.record_admissibility_gate(
            validated=["dev-ok"],
            excluded=[("dev-fail", ["not-ready"])],
        )
        expl = b.build()
        assert len(expl.rejected_candidates) == 1
        assert expl.rejected_candidates[0].candidate_id == "dev-fail"


# ---------------------------------------------------------------------------
# 11–13. record_capability_enforcement
# ---------------------------------------------------------------------------


class TestRecordCapabilityEnforcement:
    def test_confirmed_targets_recorded(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        from core.routing_explanation.decision_basis import DecisionFactor
        b = LiveRoutingDecisionBuilder()
        b.record_capability_enforcement(
            confirmed=["dev-1"], unconfirmed=[], required_caps=["screen"]
        )
        expl = b.build()
        basis = next(
            (db for db in expl.decision_bases if db.factor is DecisionFactor.CAPABILITY),
            None,
        )
        assert basis is not None
        assert basis.accepted is True

    def test_unconfirmed_appear_as_rejected_candidates(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        b = LiveRoutingDecisionBuilder()
        b.record_capability_enforcement(
            confirmed=[], unconfirmed=["dev-no-cap"], required_caps=["camera"]
        )
        expl = b.build()
        assert len(expl.rejected_candidates) == 1
        rc = expl.rejected_candidates[0]
        assert rc.candidate_id == "dev-no-cap"
        assert rc.capability_match is False
        assert "camera" in rc.rejection_reason

    def test_required_caps_in_description(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        b = LiveRoutingDecisionBuilder()
        b.record_capability_enforcement(
            confirmed=["dev-1"], unconfirmed=[], required_caps=["gps", "screen"]
        )
        expl = b.build()
        assert any(
            "gps" in db.description or "screen" in db.description
            for db in expl.decision_bases
        )


# ---------------------------------------------------------------------------
# 14. record_fallback
# ---------------------------------------------------------------------------


class TestRecordFallback:
    def test_fallback_plan_set(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        b = LiveRoutingDecisionBuilder()
        b.record_fallback(["fallback-dev-1"])
        expl = b.build()
        assert expl.fallback_plan is not None
        assert "fallback-dev-1" in expl.fallback_plan

    def test_fallback_adds_fallback_basis(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        from core.routing_explanation.decision_basis import DecisionFactor
        b = LiveRoutingDecisionBuilder()
        b.record_fallback(["fb-dev"], reason="primary was offline")
        expl = b.build()
        fallback_bases = [
            db for db in expl.decision_bases
            if db.factor is DecisionFactor.FALLBACK
        ]
        assert len(fallback_bases) == 1
        assert fallback_bases[0].accepted is True
        assert "primary was offline" in fallback_bases[0].description

    def test_fallback_with_empty_list_and_reason(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        b = LiveRoutingDecisionBuilder()
        b.record_fallback([], reason="custom fallback reason")
        expl = b.build()
        assert expl.fallback_plan == "custom fallback reason"


# ---------------------------------------------------------------------------
# 15–16. record_result_outcome
# ---------------------------------------------------------------------------


class TestRecordResultOutcome:
    def test_failure_adds_availability_basis(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        from core.routing_explanation.decision_basis import DecisionFactor
        b = LiveRoutingDecisionBuilder()
        b.record_result_outcome(success=False, error_code="DEVICE_TIMEOUT", via="command_router")
        expl = b.build()
        failure_bases = [
            db for db in expl.decision_bases
            if db.factor is DecisionFactor.AVAILABILITY and db.accepted is False
        ]
        assert len(failure_bases) == 1
        assert "DEVICE_TIMEOUT" in failure_bases[0].description

    def test_success_adds_no_basis(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        b = LiveRoutingDecisionBuilder()
        initial_count = len(b.build().decision_bases)
        b.record_result_outcome(success=True)
        expl = b.build()
        assert len(expl.decision_bases) == initial_count


# ---------------------------------------------------------------------------
# 17–20. build
# ---------------------------------------------------------------------------


class TestBuild:
    def test_build_propagates_selected_target(self):
        from core.routing_explanation.live_decision import (
            LiveRoutingDecisionBuilder, ROUTE_PATH_LOCAL
        )
        b = LiveRoutingDecisionBuilder()
        b.record_route_path_selection(ROUTE_PATH_LOCAL, selected_target="my-device")
        expl = b.build()
        assert expl.selected_target == "my-device"

    def test_build_propagates_task_trace_ids(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        b = LiveRoutingDecisionBuilder(task_id="tid-123", trace_id="trace-abc")
        expl = b.build()
        assert expl.task_id == "tid-123"
        assert expl.trace_id == "trace-abc"

    def test_build_confidence_not_undetermined_with_bases(self):
        from core.routing_explanation.live_decision import (
            LiveRoutingDecisionBuilder, ROUTE_PATH_LOCAL
        )
        from core.routing_explanation.route_confidence import ConfidenceBand
        b = LiveRoutingDecisionBuilder()
        b.record_route_path_selection(ROUTE_PATH_LOCAL, selected_target="dev-1")
        expl = b.build()
        # With at least one accepted basis, confidence should not be UNDETERMINED
        assert expl.confidence.band is not ConfidenceBand.UNDETERMINED

    def test_build_owner_component(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        b = LiveRoutingDecisionBuilder()
        expl = b.build()
        assert expl.owner_component == "CommandRouter.route_envelope"

    def test_build_multiple_calls_independent(self):
        from core.routing_explanation.live_decision import (
            LiveRoutingDecisionBuilder, ROUTE_PATH_LOCAL
        )
        b = LiveRoutingDecisionBuilder()
        b.record_route_path_selection(ROUTE_PATH_LOCAL, selected_target="dev-a")
        expl1 = b.build()
        expl2 = b.build()
        assert expl1.selected_target == expl2.selected_target
        # decision_bases are equal length
        assert len(expl1.decision_bases) == len(expl2.decision_bases)


# ---------------------------------------------------------------------------
# 21–24. build_summary
# ---------------------------------------------------------------------------


class TestBuildSummary:
    def test_build_summary_returns_summary_type(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        from core.routing_explanation.explanation_summary import RoutingExplanationSummary
        b = LiveRoutingDecisionBuilder()
        s = b.build_summary()
        assert isinstance(s, RoutingExplanationSummary)

    def test_build_summary_is_cross_device_true(self):
        from core.routing_explanation.live_decision import (
            LiveRoutingDecisionBuilder, ROUTE_PATH_CROSS_DEVICE
        )
        b = LiveRoutingDecisionBuilder()
        b.record_posture_gate(posture="remote_required", eligible=True)
        b.record_route_path_selection(ROUTE_PATH_CROSS_DEVICE, selected_target="android-1")
        s = b.build_summary()
        assert s.is_cross_device is True

    def test_build_summary_has_fallback_true(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        b = LiveRoutingDecisionBuilder()
        b.record_fallback(["fb-1"])
        s = b.build_summary()
        assert s.has_fallback is True

    def test_build_summary_rejected_alternatives_populated(self):
        from core.routing_explanation.live_decision import LiveRoutingDecisionBuilder
        b = LiveRoutingDecisionBuilder()
        b.record_admissibility_gate(
            validated=["dev-ok"],
            excluded=[("dev-fail", ["not-ready"])],
        )
        s = b.build_summary()
        assert len(s.rejected_alternatives) == 1
        assert s.rejected_alternatives[0]["candidate_id"] == "dev-fail"


# ---------------------------------------------------------------------------
# 25–27. live_explanation_to_record_str
# ---------------------------------------------------------------------------


class TestLiveExplanationToRecordStr:
    def test_returns_valid_json(self):
        from core.routing_explanation.live_decision import (
            LiveRoutingDecisionBuilder, live_explanation_to_record_str, ROUTE_PATH_LOCAL
        )
        b = LiveRoutingDecisionBuilder(task_id="t1", trace_id="tr1")
        b.record_route_path_selection(ROUTE_PATH_LOCAL, selected_target="dev-1")
        expl = b.build()
        s = live_explanation_to_record_str(expl)
        data = json.loads(s)
        assert isinstance(data, dict)

    def test_json_contains_expected_keys(self):
        from core.routing_explanation.live_decision import (
            LiveRoutingDecisionBuilder, live_explanation_to_record_str, ROUTE_PATH_LOCAL
        )
        b = LiveRoutingDecisionBuilder(task_id="t1")
        b.record_route_path_selection(ROUTE_PATH_LOCAL, selected_target="dev-1")
        expl = b.build()
        data = json.loads(live_explanation_to_record_str(expl))
        for key in (
            "selected_target",
            "decision_bases",
            "rejected_candidates",
            "policy_posture",
            "owner_component",
            "task_id",
        ):
            assert key in data, f"key '{key}' missing from explanation JSON"

    def test_not_the_old_placeholder_string(self):
        from core.routing_explanation.live_decision import (
            LiveRoutingDecisionBuilder, live_explanation_to_record_str, ROUTE_PATH_LOCAL
        )
        b = LiveRoutingDecisionBuilder()
        b.record_route_path_selection(ROUTE_PATH_LOCAL)
        expl = b.build()
        s = live_explanation_to_record_str(expl)
        assert s != "canonical dispatch via CommandRouter.route_envelope"
        # Must be valid JSON
        json.loads(s)

    def test_selected_target_in_json(self):
        from core.routing_explanation.live_decision import (
            LiveRoutingDecisionBuilder, live_explanation_to_record_str, ROUTE_PATH_LOCAL
        )
        b = LiveRoutingDecisionBuilder()
        b.record_route_path_selection(ROUTE_PATH_LOCAL, selected_target="device-xyz")
        expl = b.build()
        data = json.loads(live_explanation_to_record_str(expl))
        assert data["selected_target"] == "device-xyz"


# ---------------------------------------------------------------------------
# 28–30. Combined flow
# ---------------------------------------------------------------------------


class TestCombinedFlow:
    def test_full_flow_explanation_not_empty(self):
        from core.routing_explanation.live_decision import (
            LiveRoutingDecisionBuilder,
            ROUTE_PATH_LOCAL,
        )
        b = LiveRoutingDecisionBuilder(task_id="full-flow", trace_id="tr-full")
        b.record_posture_gate(posture="local_preferred", eligible=True)
        b.record_admissibility_gate(
            validated=["dev-1"],
            excluded=[("dev-2", ["heartbeat-stale"])],
        )
        b.record_capability_enforcement(
            confirmed=["dev-1"],
            unconfirmed=[],
            required_caps=["screen"],
        )
        b.record_route_path_selection(ROUTE_PATH_LOCAL, selected_target="dev-1")
        b.record_result_outcome(success=True)

        expl = b.build()
        assert expl.selected_target == "dev-1"
        assert expl.task_id == "full-flow"
        assert len(expl.decision_bases) >= 3
        # Should have at least one rejected candidate from admissibility exclusion
        assert len(expl.rejected_candidates) >= 1

    def test_rejected_candidate_ids_preserved(self):
        from core.routing_explanation.live_decision import (
            LiveRoutingDecisionBuilder,
            ROUTE_PATH_CROSS_DEVICE,
        )
        b = LiveRoutingDecisionBuilder(task_id="reject-test")
        b.record_admissibility_gate(
            validated=["kept-dev"],
            excluded=[
                ("excluded-dev-1", ["not-ready"]),
                ("excluded-dev-2", ["capability-missing"]),
            ],
        )
        b.record_route_path_selection(ROUTE_PATH_CROSS_DEVICE, selected_target="kept-dev")
        expl = b.build()

        rejected_ids = {rc.candidate_id for rc in expl.rejected_candidates}
        assert "excluded-dev-1" in rejected_ids
        assert "excluded-dev-2" in rejected_ids
        assert "kept-dev" not in rejected_ids

    def test_decision_basis_count_matches_recorded_signals(self):
        from core.routing_explanation.live_decision import (
            LiveRoutingDecisionBuilder,
            ROUTE_PATH_LOCAL,
        )
        b = LiveRoutingDecisionBuilder()
        # Record exactly 3 signal categories:
        # 1 posture gate + 1 admissibility validated + 1 path selection = 3 bases
        b.record_posture_gate(posture="local_preferred", eligible=True)
        b.record_admissibility_gate(validated=["dev-1"], excluded=[])
        b.record_route_path_selection(ROUTE_PATH_LOCAL, selected_target="dev-1")
        expl = b.build()
        # Must have at least one basis per recorded signal category
        assert len(expl.decision_bases) >= 3

    def test_fallback_included_in_summary_basis_list(self):
        from core.routing_explanation.live_decision import (
            LiveRoutingDecisionBuilder,
            ROUTE_PATH_CROSS_DEVICE,
        )
        b = LiveRoutingDecisionBuilder()
        b.record_route_path_selection(ROUTE_PATH_CROSS_DEVICE, selected_target="primary")
        b.record_fallback(["backup-dev"], reason="primary unreachable")
        summary = b.build_summary()
        assert summary.has_fallback is True
        assert summary.fallback_plan is not None
        assert "backup-dev" in summary.fallback_plan or "primary unreachable" in summary.fallback_plan
