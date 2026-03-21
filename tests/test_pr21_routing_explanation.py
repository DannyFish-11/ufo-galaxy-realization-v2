#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr21_routing_explanation.py
=======================================

PR-21 (V4) — Routing Explanation & Decision Surface

Tests covering:
1.  DecisionFactor enum — values and serialisation stability
2.  DecisionBasis — construction, to_dict, from_dict round-trip
3.  DecisionBasis — accepted flag propagation
4.  make_decision_basis — coercion of factor strings and unknown values
5.  make_decision_basis — weight clamping
6.  Convenience builders — basis_from_health_score
7.  Convenience builders — basis_from_policy_posture
8.  Convenience builders — basis_from_availability
9.  Convenience builders — basis_from_capability
10. ConfidenceBand enum — values and serialisation stability
11. RouteConfidence — construction, to_dict, from_dict round-trip
12. compute_confidence — empty bases → UNDETERMINED_CONFIDENCE
13. compute_confidence — all accepted bases → HIGH band
14. compute_confidence — all rejected bases → LOW or UNDETERMINED band
15. compute_confidence — mixed bases → intermediate score
16. UNDETERMINED_CONFIDENCE — sentinel field values
17. RejectedCandidate — construction, to_dict, from_dict round-trip
18. RouteExplanation — construction, to_dict, from_dict round-trip
19. RouteExplanation — from_dict with partial/missing data degrades gracefully
20. build_route_explanation — auto-computes confidence
21. EMPTY_ROUTE_EXPLANATION — sentinel field values
22. RoutingExplanationSummary — construction, to_dict, from_dict round-trip
23. RoutingExplanationSummary — from_dict with partial data degrades gracefully
24. build_explanation_summary — builds from a full RouteExplanation
25. build_explanation_summary — builds from EMPTY_ROUTE_EXPLANATION
26. IDLE_EXPLANATION_SUMMARY — sentinel field values
27. resolve_explanation_from_projection — minimal projection (no keys)
28. resolve_explanation_from_projection — with cross_device_routing block
29. resolve_explanation_from_projection — with execution_policy block
30. resolve_explanation_from_projection — with device_formation fallback
31. resolve_explanation_from_projection — with agent_dispatch block
32. attach_explanation_to_projection — additive, non-mutating
33. get_explanation_hints — shape and required keys
34. get_explanation_hints — reflects summary fields correctly
35. Integration endpoint output shape — GET /api/v1/projection/routing-explanation
36. Integration endpoint — routing_explanation and explanation_hints keys present
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
# 1. DecisionFactor enum — values and serialisation stability
# ---------------------------------------------------------------------------

class TestDecisionFactor:
    def test_all_values_are_strings(self):
        from core.routing_explanation.decision_basis import DecisionFactor
        for member in DecisionFactor:
            assert isinstance(member.value, str)
            assert member.value  # non-empty

    def test_known_values_stable(self):
        from core.routing_explanation.decision_basis import DecisionFactor
        assert DecisionFactor.POLICY.value == "policy"
        assert DecisionFactor.HEALTH.value == "health"
        assert DecisionFactor.CAPABILITY.value == "capability"
        assert DecisionFactor.LATENCY.value == "latency"
        assert DecisionFactor.AVAILABILITY.value == "availability"
        assert DecisionFactor.FALLBACK.value == "fallback"
        assert DecisionFactor.EXECUTION_BUDGET.value == "execution_budget"

    def test_roundtrip_via_value(self):
        from core.routing_explanation.decision_basis import DecisionFactor
        for member in DecisionFactor:
            assert DecisionFactor(member.value) is member

    def test_factor_description_non_empty(self):
        from core.routing_explanation.decision_basis import DecisionFactor, factor_description
        for member in DecisionFactor:
            desc = factor_description(member)
            assert isinstance(desc, str)
            assert len(desc) > 10


# ---------------------------------------------------------------------------
# 2. DecisionBasis — construction, to_dict, from_dict round-trip
# ---------------------------------------------------------------------------

class TestDecisionBasis:
    def test_construction_defaults(self):
        from core.routing_explanation.decision_basis import DecisionBasis, DecisionFactor
        b = DecisionBasis(factor=DecisionFactor.HEALTH)
        assert b.factor is DecisionFactor.HEALTH
        assert b.accepted is True
        assert b.weight is None
        assert b.signal_value is None

    def test_to_dict_keys(self):
        from core.routing_explanation.decision_basis import DecisionBasis, DecisionFactor
        b = DecisionBasis(
            factor=DecisionFactor.POLICY,
            signal_value="local_preferred",
            description="test description",
            accepted=True,
            weight=0.30,
        )
        d = b.to_dict()
        assert d["factor"] == "policy"
        assert d["signal_value"] == "local_preferred"
        assert d["description"] == "test description"
        assert d["accepted"] is True
        assert d["weight"] == 0.30

    def test_to_dict_json_serialisable(self):
        from core.routing_explanation.decision_basis import DecisionBasis, DecisionFactor
        b = DecisionBasis(factor=DecisionFactor.HEALTH, signal_value=0.87, weight=0.35)
        # Must not raise
        json.dumps(b.to_dict())

    def test_from_dict_roundtrip(self):
        from core.routing_explanation.decision_basis import DecisionBasis, DecisionFactor
        original = DecisionBasis(
            factor=DecisionFactor.CAPABILITY,
            signal_value=True,
            description="cap check",
            accepted=False,
            weight=0.15,
        )
        restored = DecisionBasis.from_dict(original.to_dict())
        assert restored.factor is DecisionFactor.CAPABILITY
        assert restored.signal_value is True
        assert restored.accepted is False
        assert restored.weight == 0.15

    def test_from_dict_unknown_factor_defaults_to_policy(self):
        from core.routing_explanation.decision_basis import DecisionBasis, DecisionFactor
        b = DecisionBasis.from_dict({"factor": "nonexistent_xyz"})
        assert b.factor is DecisionFactor.POLICY


# ---------------------------------------------------------------------------
# 3 & 4. make_decision_basis — coercion
# ---------------------------------------------------------------------------

class TestMakeDecisionBasis:
    def test_accepts_enum(self):
        from core.routing_explanation.decision_basis import make_decision_basis, DecisionFactor
        b = make_decision_basis(factor=DecisionFactor.LATENCY)
        assert b.factor is DecisionFactor.LATENCY

    def test_accepts_string(self):
        from core.routing_explanation.decision_basis import make_decision_basis, DecisionFactor
        b = make_decision_basis(factor="health")
        assert b.factor is DecisionFactor.HEALTH

    def test_unknown_string_defaults_to_policy(self):
        from core.routing_explanation.decision_basis import make_decision_basis, DecisionFactor
        b = make_decision_basis(factor="totally_unknown_xyz")
        assert b.factor is DecisionFactor.POLICY

    def test_weight_clamped_to_zero_one(self):
        from core.routing_explanation.decision_basis import make_decision_basis
        b1 = make_decision_basis(factor="policy", weight=-0.5)
        b2 = make_decision_basis(factor="policy", weight=1.5)
        assert b1.weight == 0.0
        assert b2.weight == 1.0

    def test_accepted_flag_preserved(self):
        from core.routing_explanation.decision_basis import make_decision_basis
        b = make_decision_basis(factor="fallback", accepted=False)
        assert b.accepted is False


# ---------------------------------------------------------------------------
# 5-8. Convenience builders
# ---------------------------------------------------------------------------

class TestConvenienceBuilders:
    def test_basis_from_health_score_healthy(self):
        from core.routing_explanation.decision_basis import basis_from_health_score, DecisionFactor
        b = basis_from_health_score("dev_a", health_score=0.9)
        assert b.factor is DecisionFactor.HEALTH
        assert b.accepted is True
        assert b.signal_value == pytest.approx(0.9, abs=0.001)

    def test_basis_from_health_score_unhealthy(self):
        from core.routing_explanation.decision_basis import basis_from_health_score, DecisionFactor
        b = basis_from_health_score("dev_b", health_score=0.2, threshold=0.5)
        assert b.factor is DecisionFactor.HEALTH
        assert b.accepted is False

    def test_basis_from_policy_posture(self):
        from core.routing_explanation.decision_basis import basis_from_policy_posture, DecisionFactor
        b = basis_from_policy_posture("remote_required", "must dispatch remotely")
        assert b.factor is DecisionFactor.POLICY
        assert "remote_required" in b.description

    def test_basis_from_availability_online(self):
        from core.routing_explanation.decision_basis import basis_from_availability, DecisionFactor
        b = basis_from_availability("dev_x", is_available=True)
        assert b.factor is DecisionFactor.AVAILABILITY
        assert b.accepted is True

    def test_basis_from_availability_offline(self):
        from core.routing_explanation.decision_basis import basis_from_availability, DecisionFactor
        b = basis_from_availability("dev_y", is_available=False)
        assert b.accepted is False

    def test_basis_from_capability(self):
        from core.routing_explanation.decision_basis import basis_from_capability, DecisionFactor
        b = basis_from_capability("screen_control", is_available=True)
        assert b.factor is DecisionFactor.CAPABILITY
        assert b.accepted is True


# ---------------------------------------------------------------------------
# 10-11. ConfidenceBand and RouteConfidence
# ---------------------------------------------------------------------------

class TestConfidenceBand:
    def test_all_values_are_strings(self):
        from core.routing_explanation.route_confidence import ConfidenceBand
        for member in ConfidenceBand:
            assert isinstance(member.value, str)

    def test_known_values_stable(self):
        from core.routing_explanation.route_confidence import ConfidenceBand
        assert ConfidenceBand.HIGH.value == "high"
        assert ConfidenceBand.MEDIUM.value == "medium"
        assert ConfidenceBand.LOW.value == "low"
        assert ConfidenceBand.UNDETERMINED.value == "undetermined"


class TestRouteConfidence:
    def test_construction_defaults(self):
        from core.routing_explanation.route_confidence import RouteConfidence, ConfidenceBand
        rc = RouteConfidence()
        assert rc.score == 0.0
        assert rc.band is ConfidenceBand.UNDETERMINED

    def test_to_dict_json_serialisable(self):
        from core.routing_explanation.route_confidence import RouteConfidence
        rc = RouteConfidence(score=0.8, basis_count=3)
        json.dumps(rc.to_dict())

    def test_from_dict_roundtrip(self):
        from core.routing_explanation.route_confidence import RouteConfidence, ConfidenceBand
        original = RouteConfidence(
            score=0.8,
            band=ConfidenceBand.HIGH,
            basis_count=4,
            accepted_factor_count=3,
            rejected_factor_count=1,
            contributing_factors=["policy", "health"],
            reason="test",
        )
        restored = RouteConfidence.from_dict(original.to_dict())
        assert restored.score == pytest.approx(0.8, abs=0.001)
        assert restored.band is ConfidenceBand.HIGH
        assert restored.basis_count == 4
        assert "policy" in restored.contributing_factors

    def test_from_dict_unknown_band_defaults_to_undetermined(self):
        from core.routing_explanation.route_confidence import RouteConfidence, ConfidenceBand
        rc = RouteConfidence.from_dict({"band": "nonexistent_xyz"})
        assert rc.band is ConfidenceBand.UNDETERMINED


# ---------------------------------------------------------------------------
# 12-15. compute_confidence
# ---------------------------------------------------------------------------

class TestComputeConfidence:
    def test_empty_returns_undetermined(self):
        from core.routing_explanation.route_confidence import compute_confidence, ConfidenceBand
        rc = compute_confidence([])
        assert rc.band is ConfidenceBand.UNDETERMINED
        assert rc.score == 0.0

    def test_all_accepted_high_weight_gives_high_band(self):
        from core.routing_explanation.decision_basis import make_decision_basis
        from core.routing_explanation.route_confidence import compute_confidence, ConfidenceBand
        bases = [
            make_decision_basis("policy", signal_value="local_preferred", accepted=True, weight=0.40),
            make_decision_basis("health", signal_value=0.95, accepted=True, weight=0.35),
            make_decision_basis("availability", signal_value=True, accepted=True, weight=0.25),
        ]
        rc = compute_confidence(bases)
        assert rc.band is ConfidenceBand.HIGH
        assert rc.score >= 0.75
        assert rc.accepted_factor_count == 3
        assert rc.rejected_factor_count == 0

    def test_all_rejected_gives_low_or_undetermined_band(self):
        from core.routing_explanation.decision_basis import make_decision_basis
        from core.routing_explanation.route_confidence import compute_confidence, ConfidenceBand
        bases = [
            make_decision_basis("fallback", accepted=False, weight=0.50),
            make_decision_basis("availability", accepted=False, weight=0.50),
        ]
        rc = compute_confidence(bases)
        assert rc.band in (ConfidenceBand.LOW, ConfidenceBand.UNDETERMINED)

    def test_mixed_bases_intermediate(self):
        from core.routing_explanation.decision_basis import make_decision_basis
        from core.routing_explanation.route_confidence import compute_confidence, ConfidenceBand
        bases = [
            make_decision_basis("policy", accepted=True, weight=0.40),
            make_decision_basis("fallback", accepted=False, weight=0.30),
            make_decision_basis("health", accepted=True, weight=0.30),
        ]
        rc = compute_confidence(bases)
        # Score should be between 0 and 1 and not undetermined
        assert 0.0 <= rc.score <= 1.0
        assert rc.basis_count == 3

    def test_contributing_factors_deduped(self):
        from core.routing_explanation.decision_basis import make_decision_basis
        from core.routing_explanation.route_confidence import compute_confidence
        bases = [
            make_decision_basis("policy", accepted=True, weight=0.20),
            make_decision_basis("policy", accepted=True, weight=0.20),
            make_decision_basis("health", accepted=True, weight=0.60),
        ]
        rc = compute_confidence(bases)
        assert rc.contributing_factors.count("policy") == 1
        assert "health" in rc.contributing_factors


# ---------------------------------------------------------------------------
# 16. UNDETERMINED_CONFIDENCE sentinel
# ---------------------------------------------------------------------------

class TestUndeterminedConfidenceSentinel:
    def test_sentinel_fields(self):
        from core.routing_explanation.route_confidence import UNDETERMINED_CONFIDENCE, ConfidenceBand
        assert UNDETERMINED_CONFIDENCE.score == 0.0
        assert UNDETERMINED_CONFIDENCE.band is ConfidenceBand.UNDETERMINED
        assert UNDETERMINED_CONFIDENCE.basis_count == 0


# ---------------------------------------------------------------------------
# 17. RejectedCandidate — construction, to_dict, from_dict round-trip
# ---------------------------------------------------------------------------

class TestRejectedCandidate:
    def test_construction(self):
        from core.routing_explanation.route_explanation import RejectedCandidate
        rc = RejectedCandidate(
            candidate_id="dev_old",
            rejection_reason="health score too low",
            health_score=0.2,
            capability_match=True,
            was_available=True,
        )
        assert rc.candidate_id == "dev_old"
        assert rc.health_score == pytest.approx(0.2, abs=0.001)

    def test_to_dict_json_serialisable(self):
        from core.routing_explanation.route_explanation import RejectedCandidate
        rc = RejectedCandidate(candidate_id="dev_z", health_score=0.3)
        json.dumps(rc.to_dict())

    def test_from_dict_roundtrip(self):
        from core.routing_explanation.route_explanation import RejectedCandidate
        original = RejectedCandidate(
            candidate_id="dev_abc",
            rejection_reason="offline",
            health_score=0.0,
            capability_match=False,
            was_available=False,
        )
        restored = RejectedCandidate.from_dict(original.to_dict())
        assert restored.candidate_id == "dev_abc"
        assert restored.was_available is False
        assert restored.capability_match is False

    def test_from_dict_none_health_score(self):
        from core.routing_explanation.route_explanation import RejectedCandidate
        rc = RejectedCandidate.from_dict({"candidate_id": "x"})
        assert rc.health_score is None


# ---------------------------------------------------------------------------
# 18-20. RouteExplanation
# ---------------------------------------------------------------------------

class TestRouteExplanation:
    def _make_bases(self):
        from core.routing_explanation.decision_basis import make_decision_basis
        return [
            make_decision_basis("policy", signal_value="local_preferred", accepted=True, weight=0.4),
            make_decision_basis("health", signal_value=0.9, accepted=True, weight=0.35),
        ]

    def test_construction_defaults(self):
        from core.routing_explanation.route_explanation import RouteExplanation
        exp = RouteExplanation()
        assert exp.selected_target is None
        assert exp.decision_bases == []
        assert exp.policy_posture == "undecided"

    def test_to_dict_json_serialisable(self):
        from core.routing_explanation.route_explanation import RouteExplanation
        from core.routing_explanation.route_confidence import UNDETERMINED_CONFIDENCE
        exp = RouteExplanation(
            selected_target="dev_01",
            decision_bases=self._make_bases(),
            confidence=UNDETERMINED_CONFIDENCE,
        )
        json.dumps(exp.to_dict())

    def test_from_dict_roundtrip(self):
        from core.routing_explanation.route_explanation import RouteExplanation
        from core.routing_explanation.route_confidence import UNDETERMINED_CONFIDENCE
        original = RouteExplanation(
            selected_target="dev_02",
            decision_bases=self._make_bases(),
            confidence=UNDETERMINED_CONFIDENCE,
            policy_posture="remote_required",
            policy_reason="test reason",
            policy_band="bounded_execute",
            fallback_plan="use dev_03",
            owner_agent="planner",
            owner_component="DeviceRouter",
            task_id="t-1",
            trace_id="tr-1",
        )
        restored = RouteExplanation.from_dict(original.to_dict())
        assert restored.selected_target == "dev_02"
        assert restored.policy_posture == "remote_required"
        assert restored.policy_band == "bounded_execute"
        assert restored.fallback_plan == "use dev_03"
        assert len(restored.decision_bases) == 2

    def test_from_dict_partial_data_graceful(self):
        from core.routing_explanation.route_explanation import RouteExplanation
        # Only required-ish field
        exp = RouteExplanation.from_dict({"selected_target": "dev_x"})
        assert exp.selected_target == "dev_x"
        assert exp.decision_bases == []
        assert exp.rejected_candidates == []


class TestBuildRouteExplanation:
    def test_auto_computes_confidence(self):
        from core.routing_explanation.decision_basis import make_decision_basis
        from core.routing_explanation.route_explanation import build_route_explanation
        from core.routing_explanation.route_confidence import ConfidenceBand
        bases = [
            make_decision_basis("policy", accepted=True, weight=0.5),
            make_decision_basis("health", accepted=True, weight=0.5),
        ]
        exp = build_route_explanation(
            selected_target="dev_primary",
            decision_bases=bases,
            policy_posture="local_preferred",
            policy_reason="default",
        )
        assert exp.selected_target == "dev_primary"
        assert exp.confidence.band is ConfidenceBand.HIGH

    def test_empty_bases_returns_undetermined_confidence(self):
        from core.routing_explanation.route_explanation import build_route_explanation
        from core.routing_explanation.route_confidence import ConfidenceBand
        exp = build_route_explanation()
        assert exp.confidence.band is ConfidenceBand.UNDETERMINED

    def test_never_raises_on_bad_input(self):
        from core.routing_explanation.route_explanation import build_route_explanation
        # Should not raise even with nonsense input
        exp = build_route_explanation(
            decision_bases=None,
            rejected_candidates=None,
        )
        assert exp is not None


class TestEmptyRouteExplanationSentinel:
    def test_sentinel_fields(self):
        from core.routing_explanation.route_explanation import EMPTY_ROUTE_EXPLANATION
        assert EMPTY_ROUTE_EXPLANATION.selected_target is None
        assert EMPTY_ROUTE_EXPLANATION.decision_bases == []
        assert EMPTY_ROUTE_EXPLANATION.policy_posture == "undecided"


# ---------------------------------------------------------------------------
# 22-26. RoutingExplanationSummary and builders
# ---------------------------------------------------------------------------

class TestRoutingExplanationSummary:
    def _idle_dict(self):
        from core.routing_explanation.explanation_summary import IDLE_EXPLANATION_SUMMARY
        return IDLE_EXPLANATION_SUMMARY.to_dict()

    def test_construction_defaults(self):
        from core.routing_explanation.explanation_summary import RoutingExplanationSummary
        s = RoutingExplanationSummary()
        assert s.schema_version == 1
        assert s.route_target is None
        assert s.is_cross_device is False
        assert s.has_fallback is False

    def test_to_dict_json_serialisable(self):
        from core.routing_explanation.explanation_summary import IDLE_EXPLANATION_SUMMARY
        json.dumps(IDLE_EXPLANATION_SUMMARY.to_dict())

    def test_from_dict_roundtrip(self):
        from core.routing_explanation.explanation_summary import RoutingExplanationSummary
        original = RoutingExplanationSummary(
            route_target="dev_01",
            policy_posture="remote_required",
            policy_band="full_execute",
            policy_reason="must dispatch remotely",
            is_cross_device=True,
            has_fallback=True,
            fallback_plan="use dev_02",
            owner_agent="planner",
            owner_component="DeviceRouter",
            task_id="t-001",
            trace_id="tr-001",
        )
        restored = RoutingExplanationSummary.from_dict(original.to_dict())
        assert restored.route_target == "dev_01"
        assert restored.is_cross_device is True
        assert restored.policy_band == "full_execute"
        assert restored.has_fallback is True
        assert restored.fallback_plan == "use dev_02"

    def test_from_dict_partial_degrades_gracefully(self):
        from core.routing_explanation.explanation_summary import RoutingExplanationSummary
        s = RoutingExplanationSummary.from_dict({})
        assert s.schema_version == 1
        assert s.route_target is None
        assert s.is_cross_device is False


class TestBuildExplanationSummary:
    def test_from_full_explanation(self):
        from core.routing_explanation.decision_basis import make_decision_basis
        from core.routing_explanation.route_explanation import build_route_explanation
        from core.routing_explanation.route_explanation import RejectedCandidate
        from core.routing_explanation.explanation_summary import build_explanation_summary
        from core.routing_explanation.route_confidence import ConfidenceBand

        bases = [
            make_decision_basis("policy", signal_value="remote_required", accepted=True, weight=0.5),
            make_decision_basis("health", signal_value=0.85, accepted=True, weight=0.5),
        ]
        rejected = [
            RejectedCandidate(candidate_id="dev_old", rejection_reason="offline")
        ]
        exp = build_route_explanation(
            selected_target="dev_new",
            decision_bases=bases,
            rejected_candidates=rejected,
            policy_posture="remote_required",
            policy_reason="must dispatch remotely",
            policy_band="full_execute",
            fallback_plan="use dev_backup",
            owner_agent="planner",
        )
        summary = build_explanation_summary(exp)
        assert summary.route_target == "dev_new"
        assert summary.policy_posture == "remote_required"
        assert summary.is_cross_device is True
        assert summary.has_fallback is True
        assert summary.fallback_plan == "use dev_backup"
        assert summary.owner_agent == "planner"
        assert len(summary.rejected_alternatives) == 1
        assert len(summary.decision_basis_list) == 2
        assert summary.confidence["band"] == ConfidenceBand.HIGH.value

    def test_from_empty_explanation(self):
        from core.routing_explanation.route_explanation import EMPTY_ROUTE_EXPLANATION
        from core.routing_explanation.explanation_summary import build_explanation_summary
        summary = build_explanation_summary(EMPTY_ROUTE_EXPLANATION)
        assert summary.route_target is None
        assert summary.decision_basis_list == []
        assert summary.is_cross_device is False


class TestIdleExplanationSummarySentinel:
    def test_sentinel_fields(self):
        from core.routing_explanation.explanation_summary import IDLE_EXPLANATION_SUMMARY
        assert IDLE_EXPLANATION_SUMMARY.schema_version == 1
        assert IDLE_EXPLANATION_SUMMARY.route_target is None
        assert IDLE_EXPLANATION_SUMMARY.is_cross_device is False
        assert IDLE_EXPLANATION_SUMMARY.has_fallback is False
        assert IDLE_EXPLANATION_SUMMARY.owner_component == "routing_explanation"


# ---------------------------------------------------------------------------
# 27-31. resolve_explanation_from_projection
# ---------------------------------------------------------------------------

class TestResolveExplanationFromProjection:
    def test_minimal_projection_no_keys(self):
        from core.routing_explanation.explanation_summary import resolve_explanation_from_projection
        summary = resolve_explanation_from_projection({})
        assert summary.policy_posture == "undecided"
        assert summary.is_cross_device is False

    def test_with_cross_device_routing_block(self):
        from core.routing_explanation.explanation_summary import resolve_explanation_from_projection
        projection = {
            "cross_device_routing": {
                "posture": "remote_required",
                "policy_reason": "must dispatch remotely for this task",
                "is_cross_device": True,
                "expansion_allowed_by_execution_policy": True,
                "primary_execution_device_id": "android_01",
            }
        }
        summary = resolve_explanation_from_projection(projection)
        assert summary.policy_posture == "remote_required"
        assert summary.is_cross_device is True
        assert summary.route_target == "android_01"
        # Should have at least one policy basis
        assert any(b["factor"] == "policy" for b in summary.decision_basis_list)

    def test_with_execution_policy_block(self):
        from core.routing_explanation.explanation_summary import resolve_explanation_from_projection
        projection = {
            "execution_policy": {
                "policy_band": "bounded_execute",
                "can_execute": True,
            }
        }
        summary = resolve_explanation_from_projection(projection)
        assert summary.policy_band == "bounded_execute"
        assert any(b["factor"] == "execution_budget" for b in summary.decision_basis_list)

    def test_with_device_formation_fallback(self):
        from core.routing_explanation.explanation_summary import resolve_explanation_from_projection
        projection = {
            "device_formation": {
                "fallback_available": True,
                "fallback_device_ids": ["dev_fallback_1"],
                "formation_reason": "multi-device required by policy",
                "is_multi_device": True,
            }
        }
        summary = resolve_explanation_from_projection(projection)
        assert summary.has_fallback is True
        assert summary.fallback_plan is not None
        assert "dev_fallback_1" in summary.fallback_plan

    def test_with_agent_dispatch_block(self):
        from core.routing_explanation.explanation_summary import resolve_explanation_from_projection
        projection = {
            "agent_dispatch": {
                "dispatch_role": "planner",
                "handoff_valid": True,
            }
        }
        summary = resolve_explanation_from_projection(projection)
        assert summary.owner_agent == "planner"
        assert any(b["factor"] == "agent_handoff" for b in summary.decision_basis_list)

    def test_expansion_blocked_adds_rejected_basis(self):
        from core.routing_explanation.explanation_summary import resolve_explanation_from_projection
        projection = {
            "cross_device_routing": {
                "posture": "remote_required",
                "is_cross_device": True,
                "expansion_allowed_by_execution_policy": False,
            }
        }
        summary = resolve_explanation_from_projection(projection)
        # Should have a rejected (accepted=False) policy entry
        rejected_bases = [b for b in summary.decision_basis_list if not b["accepted"]]
        assert len(rejected_bases) >= 1


# ---------------------------------------------------------------------------
# 32. attach_explanation_to_projection
# ---------------------------------------------------------------------------

class TestAttachExplanationToProjection:
    def test_additive_non_mutating(self):
        from core.routing_explanation.explanation_summary import (
            attach_explanation_to_projection,
            IDLE_EXPLANATION_SUMMARY,
        )
        original = {"tri_state_phase": "silent", "runtime_domain": None}
        result = attach_explanation_to_projection(original, IDLE_EXPLANATION_SUMMARY)

        # Original not modified
        assert "routing_explanation" not in original
        # Result has the key
        assert "routing_explanation" in result
        # Original keys preserved
        assert result["tri_state_phase"] == "silent"

    def test_explanation_key_is_dict(self):
        from core.routing_explanation.explanation_summary import (
            attach_explanation_to_projection,
            IDLE_EXPLANATION_SUMMARY,
        )
        result = attach_explanation_to_projection({}, IDLE_EXPLANATION_SUMMARY)
        assert isinstance(result["routing_explanation"], dict)


# ---------------------------------------------------------------------------
# 33-34. get_explanation_hints
# ---------------------------------------------------------------------------

class TestGetExplanationHints:
    _REQUIRED_HINT_KEYS = {
        "route_target", "policy_posture", "policy_band",
        "confidence_score", "confidence_band",
        "is_cross_device", "has_fallback", "has_rejected_alternatives",
        "rejected_count", "basis_count", "owner_agent",
    }

    def test_all_required_keys_present(self):
        from core.routing_explanation.explanation_summary import (
            get_explanation_hints,
            IDLE_EXPLANATION_SUMMARY,
        )
        hints = get_explanation_hints(IDLE_EXPLANATION_SUMMARY)
        for key in self._REQUIRED_HINT_KEYS:
            assert key in hints, f"Missing hint key: {key}"

    def test_reflects_summary_fields(self):
        from core.routing_explanation.explanation_summary import (
            RoutingExplanationSummary,
            get_explanation_hints,
        )
        s = RoutingExplanationSummary(
            route_target="dev_01",
            policy_posture="remote_required",
            policy_band="full_execute",
            is_cross_device=True,
            has_fallback=True,
            owner_agent="planner",
        )
        hints = get_explanation_hints(s)
        assert hints["route_target"] == "dev_01"
        assert hints["policy_posture"] == "remote_required"
        assert hints["policy_band"] == "full_execute"
        assert hints["is_cross_device"] is True
        assert hints["has_fallback"] is True
        assert hints["owner_agent"] == "planner"

    def test_hints_json_serialisable(self):
        from core.routing_explanation.explanation_summary import (
            get_explanation_hints,
            IDLE_EXPLANATION_SUMMARY,
        )
        hints = get_explanation_hints(IDLE_EXPLANATION_SUMMARY)
        json.dumps(hints)


# ---------------------------------------------------------------------------
# 35-36. Integration endpoint
# ---------------------------------------------------------------------------

class TestRoutingExplanationEndpoint:
    def _get_router(self):
        from core.routes.projection import create_router
        return create_router()

    def test_endpoint_registered(self):
        from fastapi import APIRouter
        router = self._get_router()
        routes = [r.path for r in router.routes]
        assert "/api/v1/projection/routing-explanation" in routes

    def test_endpoint_returns_required_keys(self):
        """Use the internal assemble function directly to verify payload shape."""
        from core.routes.projection import _assemble_projection_with_routing_explanation
        payload = _assemble_projection_with_routing_explanation()

        assert "routing_explanation" in payload, "routing_explanation key missing"
        assert "explanation_hints" in payload, "explanation_hints key missing"

        re_block = payload["routing_explanation"]
        assert isinstance(re_block, dict)
        assert "schema_version" in re_block
        assert "route_target" in re_block
        assert "decision_basis_list" in re_block
        assert "confidence" in re_block
        assert "rejected_alternatives" in re_block
        assert "policy_posture" in re_block
        assert "is_cross_device" in re_block
        assert "has_fallback" in re_block

        hints = payload["explanation_hints"]
        assert isinstance(hints, dict)
        assert "confidence_score" in hints
        assert "confidence_band" in hints
        assert "is_cross_device" in hints

    def test_endpoint_payload_json_serialisable(self):
        from core.routes.projection import _assemble_projection_with_routing_explanation
        payload = _assemble_projection_with_routing_explanation()
        # Must not raise
        json.dumps(payload)

    def test_explanation_schema_version_is_1(self):
        from core.routes.projection import _assemble_projection_with_routing_explanation
        payload = _assemble_projection_with_routing_explanation()
        assert payload["routing_explanation"]["schema_version"] == 1

    def test_all_prior_layers_still_present(self):
        """Regression: adding routing_explanation must not remove prior layer keys."""
        from core.routes.projection import _assemble_projection_with_routing_explanation
        payload = _assemble_projection_with_routing_explanation()
        # Check for keys added by earlier projection layers
        assert "agent_dispatch" in payload, "agent_dispatch key missing (regression)"
        assert "device_formation" in payload, "device_formation key missing (regression)"
        assert "cross_device_routing" in payload, "cross_device_routing key missing (regression)"
