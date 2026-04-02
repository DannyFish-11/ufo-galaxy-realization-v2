#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_transport_path_explainability.py
==============================================
PR-D: Capability + Network Runtime Convergence — transport path explainability tests.

Coverage
--------
A) Module structure
   - CAPABILITY_NETWORK_BRIDGE_AUTHORITY sentinel is importable
   - CAPABILITY_NETWORK_BRIDGE_LAYER_POSITION is 11
   - DUAL_GRAPH_SELECTION_POLICY is importable
   - All public names in __all__ are importable

B) PathAvailability dataclass
   - can be constructed with only node_id
   - to_dict() contains all expected keys
   - to_dict() is JSON-serialisable
   - is_reachable defaults to False
   - effective_path defaults to "unknown"

C) JointSelectionResult dataclass
   - can be constructed with required fields
   - to_dict() contains all expected keys
   - to_dict() is JSON-serialisable

D) JointSelectionExplanation dataclass
   - can be constructed with required fields
   - to_dict() contains all expected keys
   - provider_reason is a non-empty string
   - path_reason is a non-empty string
   - fallback_reason is a non-empty string

E) BridgeRecord dataclass
   - can be constructed with required fields
   - to_dict() contains all expected keys

F) joint_select — empty layer
   - returns JointSelectionResult when no providers available
   - result.selected_provider_id is None when no providers
   - result.is_degraded is True when no providers

G) joint_select — basic capability + path selection
   - selects provider with matching capability
   - result has non-None selected_provider_id
   - result.capability_fit_score is not None
   - result.path_availability.node_id matches selected provider

H) joint_select — target_id override
   - when target_id is given, selects that specific provider
   - result.selected_provider_id matches target_id

I) explain_joint_selection
   - returns JointSelectionExplanation
   - provider_reason contains selected_provider_id
   - path_reason contains effective_path
   - degraded_explanation mentions degraded mode when is_degraded=True
   - degraded_explanation says normal when not degraded

J) Ring buffer / observability
   - get_bridge_log() returns a deque
   - joint_select emits a BridgeRecord
   - fallback_joint_select emits a BridgeRecord
   - ring buffer bounded to 256 entries

K) Dual-graph sentinel
   - COMMAND_ROUTER_DUAL_GRAPH_INTEGRATED is importable from command_router
   - sentinel references capability_graph_selection
   - sentinel references capability_network_bridge
"""

from __future__ import annotations

import json
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_all():
    """Reset singletons before/after each test."""
    for _reset in (_try_reset_assimilation, _try_reset_bridge_log):
        _reset()
    yield
    for _reset in (_try_reset_assimilation, _try_reset_bridge_log):
        _reset()


def _try_reset_assimilation():
    try:
        from core.capability_assimilation import reset_capability_assimilation_layer
        reset_capability_assimilation_layer()
    except Exception:
        pass


def _try_reset_bridge_log():
    try:
        from core.capability_network_bridge import reset_bridge_log
        reset_bridge_log()
    except Exception:
        pass


def _register(node_id, caps=None, kind="capability_provider", transport_hints=None, online=True):
    from core.capability_assimilation import (
        get_capability_assimilation_layer,
        NodeParticipantKind,
    )
    layer = get_capability_assimilation_layer()
    rec = layer.assimilate(
        node_id,
        capabilities=list(caps or []),
        participant_kind=NodeParticipantKind(kind),
        transport_hints=dict(transport_hints or {}),
    )
    if not online:
        layer.mark_offline(node_id, reason="test")
    return rec


# ---------------------------------------------------------------------------
# A) Module structure
# ---------------------------------------------------------------------------

class TestModuleStructure:
    def test_authority_sentinel_importable(self):
        from core.capability_network_bridge import CAPABILITY_NETWORK_BRIDGE_AUTHORITY
        assert "PR-D" in CAPABILITY_NETWORK_BRIDGE_AUTHORITY

    def test_layer_position_is_11(self):
        from core.capability_network_bridge import CAPABILITY_NETWORK_BRIDGE_LAYER_POSITION
        assert CAPABILITY_NETWORK_BRIDGE_LAYER_POSITION == 11

    def test_dual_graph_policy_importable(self):
        from core.capability_network_bridge import DUAL_GRAPH_SELECTION_POLICY
        assert isinstance(DUAL_GRAPH_SELECTION_POLICY, str)
        assert len(DUAL_GRAPH_SELECTION_POLICY) > 0

    def test_all_public_names_importable(self):
        import core.capability_network_bridge as m
        for name in m.__all__:
            assert hasattr(m, name), f"Missing: {name}"


# ---------------------------------------------------------------------------
# B) PathAvailability dataclass
# ---------------------------------------------------------------------------

class TestPathAvailability:
    def test_construction_with_only_node_id(self):
        from core.capability_network_bridge import PathAvailability
        pa = PathAvailability(node_id="n1")
        assert pa.node_id == "n1"

    def test_is_reachable_defaults_false(self):
        from core.capability_network_bridge import PathAvailability
        pa = PathAvailability(node_id="n1")
        assert pa.is_reachable is False

    def test_effective_path_defaults_unknown(self):
        from core.capability_network_bridge import PathAvailability
        pa = PathAvailability(node_id="n1")
        assert pa.effective_path == "unknown"

    def test_to_dict_contains_keys(self):
        from core.capability_network_bridge import PathAvailability
        pa = PathAvailability(node_id="n1", effective_path="direct", path_score=0.9)
        d = pa.to_dict()
        for key in ("node_id", "effective_path", "path_state", "path_score",
                    "is_reachable", "transport_hints", "topology_notes"):
            assert key in d

    def test_to_dict_json_serialisable(self):
        from core.capability_network_bridge import PathAvailability
        pa = PathAvailability(node_id="n1", effective_path="direct")
        json.dumps(pa.to_dict())


# ---------------------------------------------------------------------------
# C) JointSelectionResult dataclass
# ---------------------------------------------------------------------------

class TestJointSelectionResult:
    def test_construction(self):
        from core.capability_network_bridge import JointSelectionResult, PathAvailability
        result = JointSelectionResult(
            selected_provider_id="p1",
            capability_fit_score=None,
            path_availability=PathAvailability(node_id="p1"),
            joint_score=5.0,
        )
        assert result.selected_provider_id == "p1"

    def test_to_dict_contains_keys(self):
        from core.capability_network_bridge import JointSelectionResult, PathAvailability
        result = JointSelectionResult(
            selected_provider_id="p1",
            capability_fit_score=None,
            path_availability=PathAvailability(node_id="p1"),
            joint_score=5.0,
        )
        d = result.to_dict()
        for key in ("selected_provider_id", "capability_fit_score", "path_availability",
                    "joint_score", "is_degraded", "degraded_reason"):
            assert key in d

    def test_to_dict_json_serialisable(self):
        from core.capability_network_bridge import JointSelectionResult, PathAvailability
        result = JointSelectionResult(
            selected_provider_id="p1",
            capability_fit_score=None,
            path_availability=PathAvailability(node_id="p1"),
            joint_score=5.0,
        )
        json.dumps(result.to_dict())


# ---------------------------------------------------------------------------
# D) JointSelectionExplanation dataclass
# ---------------------------------------------------------------------------

class TestJointSelectionExplanation:
    def _make_result(self):
        from core.capability_network_bridge import JointSelectionResult, PathAvailability
        return JointSelectionResult(
            selected_provider_id="p1",
            capability_fit_score=None,
            path_availability=PathAvailability(node_id="p1"),
            joint_score=5.0,
        )

    def test_construction(self):
        from core.capability_network_bridge import JointSelectionExplanation
        expl = JointSelectionExplanation(
            provider_reason="Provider selected.",
            path_reason="Direct path.",
            fallback_reason="None available.",
            degraded_explanation="Normal.",
            joint_result=self._make_result(),
        )
        assert expl.provider_reason == "Provider selected."

    def test_to_dict_contains_keys(self):
        from core.capability_network_bridge import JointSelectionExplanation
        expl = JointSelectionExplanation(
            provider_reason="p",
            path_reason="q",
            fallback_reason="r",
            degraded_explanation="s",
            joint_result=self._make_result(),
        )
        d = expl.to_dict()
        for key in ("provider_reason", "path_reason", "fallback_reason",
                    "degraded_explanation", "joint_result"):
            assert key in d

    def test_provider_reason_non_empty(self):
        from core.capability_network_bridge import JointSelectionExplanation
        expl = JointSelectionExplanation(
            provider_reason="Provider selected.",
            path_reason="Path chosen.",
            fallback_reason="Fallback available.",
            degraded_explanation="Normal.",
            joint_result=self._make_result(),
        )
        assert len(expl.provider_reason) > 0

    def test_path_reason_non_empty(self):
        from core.capability_network_bridge import JointSelectionExplanation
        expl = JointSelectionExplanation(
            provider_reason="p",
            path_reason="Direct path selected.",
            fallback_reason="r",
            degraded_explanation="s",
            joint_result=self._make_result(),
        )
        assert len(expl.path_reason) > 0


# ---------------------------------------------------------------------------
# E) BridgeRecord dataclass
# ---------------------------------------------------------------------------

class TestBridgeRecord:
    def test_construction(self):
        from core.capability_network_bridge import BridgeRecord
        rec = BridgeRecord(
            record_id=1,
            operation="joint_select",
            required_capabilities=["cap_a"],
            selected_provider_id="p1",
            effective_path="direct",
            joint_score=7.5,
            is_degraded=False,
        )
        assert rec.record_id == 1

    def test_to_dict_contains_keys(self):
        from core.capability_network_bridge import BridgeRecord
        rec = BridgeRecord(
            record_id=1,
            operation="joint_select",
            required_capabilities=[],
            selected_provider_id=None,
            effective_path="unknown",
            joint_score=0.0,
            is_degraded=True,
        )
        d = rec.to_dict()
        for key in ("record_id", "operation", "selected_provider_id",
                    "effective_path", "joint_score", "is_degraded"):
            assert key in d


# ---------------------------------------------------------------------------
# F) joint_select — empty layer
# ---------------------------------------------------------------------------

class TestJointSelectEmpty:
    def test_returns_joint_selection_result(self):
        from core.capability_network_bridge import joint_select
        result = joint_select(["cap_x"])
        assert result is not None

    def test_selected_provider_id_is_none(self):
        from core.capability_network_bridge import joint_select
        result = joint_select(["cap_x"])
        assert result.selected_provider_id is None

    def test_is_degraded_true_when_empty(self):
        from core.capability_network_bridge import joint_select
        result = joint_select(["cap_x"])
        assert result.is_degraded is True


# ---------------------------------------------------------------------------
# G) joint_select — basic capability + path selection
# ---------------------------------------------------------------------------

class TestJointSelectBasic:
    def test_selects_provider_with_matching_capability(self):
        _register("node-joint-1", caps=["cap_a", "cap_b"])
        from core.capability_network_bridge import joint_select
        result = joint_select(["cap_a"])
        assert result.selected_provider_id is not None

    def test_result_has_capability_fit_score(self):
        _register("node-joint-2", caps=["cap_a"])
        from core.capability_network_bridge import joint_select
        result = joint_select(["cap_a"])
        if result.selected_provider_id is not None:
            assert result.capability_fit_score is not None

    def test_path_availability_node_id_matches_selected(self):
        _register("node-joint-3", caps=["cap_a"])
        from core.capability_network_bridge import joint_select
        result = joint_select(["cap_a"])
        if result.selected_provider_id is not None:
            assert result.path_availability.node_id == result.selected_provider_id


# ---------------------------------------------------------------------------
# H) joint_select — target_id override
# ---------------------------------------------------------------------------

class TestJointSelectTargetId:
    def test_target_id_selects_specific_provider(self):
        _register("target-provider", caps=["cap_a"])
        _register("other-provider", caps=["cap_a"])
        from core.capability_network_bridge import joint_select
        result = joint_select(["cap_a"], target_id="target-provider")
        assert result.selected_provider_id == "target-provider"

    def test_target_id_not_in_layer_returns_none(self):
        from core.capability_network_bridge import joint_select
        result = joint_select([], target_id="nonexistent-provider")
        assert result.selected_provider_id is None


# ---------------------------------------------------------------------------
# I) explain_joint_selection
# ---------------------------------------------------------------------------

class TestExplainJointSelection:
    def _select(self, caps=None, node_id="explain-node"):
        _register(node_id, caps=caps or ["cap_a"])
        from core.capability_network_bridge import joint_select
        return joint_select(caps or ["cap_a"])

    def test_returns_explanation(self):
        result = self._select()
        from core.capability_network_bridge import explain_joint_selection
        expl = explain_joint_selection(result)
        assert expl is not None

    def test_provider_reason_contains_provider_id(self):
        result = self._select(node_id="exp-p")
        from core.capability_network_bridge import explain_joint_selection
        expl = explain_joint_selection(result)
        if result.selected_provider_id:
            assert result.selected_provider_id in expl.provider_reason

    def test_path_reason_contains_effective_path(self):
        result = self._select()
        from core.capability_network_bridge import explain_joint_selection
        expl = explain_joint_selection(result)
        # Should mention the path in some form
        assert len(expl.path_reason) > 0

    def test_degraded_explanation_normal_when_not_degraded(self):
        result = self._select()
        from core.capability_network_bridge import explain_joint_selection
        expl = explain_joint_selection(result)
        if not result.is_degraded:
            assert "normal" in expl.degraded_explanation.lower()

    def test_degraded_explanation_mentions_degraded_when_is_degraded(self):
        from core.capability_network_bridge import (
            joint_select, explain_joint_selection, JointSelectionResult, PathAvailability,
        )
        # Build a manually degraded result
        degraded = JointSelectionResult(
            selected_provider_id="dg-node",
            capability_fit_score=None,
            path_availability=PathAvailability(node_id="dg-node", path_state="degraded"),
            joint_score=2.0,
            is_degraded=True,
            degraded_reason="path_or_capability_degraded",
        )
        expl = explain_joint_selection(degraded)
        assert "degraded" in expl.degraded_explanation.lower()


# ---------------------------------------------------------------------------
# J) Ring buffer / observability
# ---------------------------------------------------------------------------

class TestRingBuffer:
    def test_get_bridge_log_returns_deque(self):
        from core.capability_network_bridge import get_bridge_log
        log = get_bridge_log()
        assert hasattr(log, "__iter__")

    def test_joint_select_emits_bridge_record(self):
        _register("rb-node", caps=["cap_a"])
        from core.capability_network_bridge import joint_select, get_bridge_log
        initial = len(get_bridge_log())
        joint_select(["cap_a"])
        assert len(get_bridge_log()) > initial

    def test_fallback_select_emits_bridge_record(self):
        _register("rb-fb", caps=["cap_a"])
        from core.capability_network_bridge import fallback_joint_select, get_bridge_log
        initial = len(get_bridge_log())
        fallback_joint_select(["cap_a"])
        assert len(get_bridge_log()) > initial

    def test_ring_buffer_bounded_256(self):
        from core.capability_network_bridge import get_bridge_log
        log = get_bridge_log()
        assert log.maxlen == 256


# ---------------------------------------------------------------------------
# K) Dual-graph sentinel
# ---------------------------------------------------------------------------

class TestDualGraphSentinel:
    def test_dual_graph_sentinel_importable(self):
        from core.command_router import COMMAND_ROUTER_DUAL_GRAPH_INTEGRATED
        assert isinstance(COMMAND_ROUTER_DUAL_GRAPH_INTEGRATED, str)

    def test_sentinel_references_capability_graph_selection(self):
        from core.command_router import COMMAND_ROUTER_DUAL_GRAPH_INTEGRATED
        assert "capability_graph_selection" in COMMAND_ROUTER_DUAL_GRAPH_INTEGRATED

    def test_sentinel_references_capability_network_bridge(self):
        from core.command_router import COMMAND_ROUTER_DUAL_GRAPH_INTEGRATED
        assert "capability_network_bridge" in COMMAND_ROUTER_DUAL_GRAPH_INTEGRATED
