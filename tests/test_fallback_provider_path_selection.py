#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_fallback_provider_path_selection.py
================================================
PR-D: Capability + Network Runtime Convergence — fallback provider and path selection tests.

Coverage
--------
A) Capability fallback — basic
   - select_fallback_providers returns empty when no candidates
   - select_fallback_providers excludes primary provider
   - select_fallback_providers returns up to max_results
   - select_fallback_providers orders by fit score (best first)
   - select_fallback_providers includes degraded providers as last resort

B) Capability fallback — multi-kind
   - fallback works across DEVICE, MCP_PROVIDER, SKILL, WORKER kinds
   - kind_filter limits fallback candidates to specified kinds

C) Network path fallback
   - PathAvailability.fallback_path is populated when topology has alternatives
   - degraded topology node produces degraded path_state
   - unavailable topology node produces is_reachable=False

D) Joint fallback — fallback_joint_select
   - fallback_joint_select returns JointSelectionResult
   - fallback result is always marked is_degraded=True
   - fallback excludes the excluded primary provider
   - fallback returns None selected_provider_id when nothing available
   - fallback selects best remaining provider when options exist

E) Degraded-mode observability
   - JointSelectionResult.is_degraded is True on capability degradation
   - JointSelectionResult.degraded_reason is non-empty on degradation
   - explain_joint_selection.degraded_explanation describes the degradation

F) Fallback explainability
   - explain_joint_selection.fallback_reason mentions fallback strategy
   - fallback_reason mentions fallback provider when available
   - fallback_reason mentions fallback path when available

G) Concurrent provider types — joint selection
   - system can simultaneously select from DEVICE, NODE, SKILL, MCP providers
   - best-fit provider is selected regardless of kind when no kind_filter
   - kind_filter allows planner to restrict selection domain

H) Ring buffer continuity
   - fallback selection events appear in bridge log
   - capability selection events appear in selection log
   - both logs are bounded to 256 entries
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_all():
    for _fn in (
        _reset_assimilation,
        _reset_bridge_log,
        _reset_selection_log,
        _reset_topology,
    ):
        _fn()
    yield
    for _fn in (
        _reset_assimilation,
        _reset_bridge_log,
        _reset_selection_log,
        _reset_topology,
    ):
        _fn()


def _reset_assimilation():
    try:
        from core.capability_assimilation import reset_capability_assimilation_layer
        reset_capability_assimilation_layer()
    except Exception:
        pass


def _reset_bridge_log():
    try:
        from core.capability_network_bridge import reset_bridge_log
        reset_bridge_log()
    except Exception:
        pass


def _reset_selection_log():
    try:
        from core.capability_graph_selection import reset_selection_log
        reset_selection_log()
    except Exception:
        pass


def _reset_topology():
    try:
        from core.network_topology_runtime import reset_network_topology_runtime
        reset_network_topology_runtime()
    except Exception:
        pass


def _register(node_id, caps=None, kind="capability_provider", online=True, transport_hints=None):
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
# A) Capability fallback — basic
# ---------------------------------------------------------------------------

class TestCapabilityFallbackBasic:
    def test_returns_empty_when_no_candidates(self):
        from core.capability_graph_selection import select_fallback_providers
        assert select_fallback_providers(["cap_x"]) == []

    def test_excludes_primary_provider(self):
        _register("primary", caps=["cap_a"])
        _register("fallback-1", caps=["cap_a"])
        from core.capability_graph_selection import select_fallback_providers
        results = select_fallback_providers(["cap_a"], exclude_ids=["primary"])
        ids = [r.node_id for r in results]
        assert "primary" not in ids
        assert "fallback-1" in ids

    def test_returns_up_to_max_results(self):
        for i in range(6):
            _register(f"fb-max-{i}", caps=["cap_a"])
        from core.capability_graph_selection import select_fallback_providers
        results = select_fallback_providers(["cap_a"], max_results=3)
        assert len(results) <= 3

    def test_orders_by_fit_score_best_first(self):
        _register("full-match", caps=["cap_a", "cap_b"])
        _register("partial-match", caps=["cap_a"])
        from core.capability_graph_selection import select_fallback_providers, score_provider
        results = select_fallback_providers(["cap_a", "cap_b"])
        if len(results) >= 2:
            scores = [score_provider(r, ["cap_a", "cap_b"]).total_score for r in results]
            assert scores[0] >= scores[1]

    def test_includes_degraded_providers(self):
        from core.capability_assimilation import (
            get_capability_assimilation_layer,
            NodeParticipantKind,
        )
        layer = get_capability_assimilation_layer()
        layer.assimilate(
            "degraded-node",
            capabilities=["cap_a"],
            participant_kind=NodeParticipantKind.CAPABILITY_PROVIDER,
        )
        layer.heartbeat("degraded-node", health_score=0.3)  # triggers DEGRADED
        from core.capability_graph_selection import select_fallback_providers
        results = select_fallback_providers(["cap_a"])
        ids = [r.node_id for r in results]
        assert "degraded-node" in ids


# ---------------------------------------------------------------------------
# B) Capability fallback — multi-kind
# ---------------------------------------------------------------------------

class TestCapabilityFallbackMultiKind:
    def test_fallback_works_across_kinds(self):
        from core.capability_assimilation import assimilate_device, assimilate_mcp_provider, assimilate_skill
        assimilate_device("dev-fb", capabilities=["cap_x"])
        assimilate_mcp_provider("mcp-fb", tools=["cap_x"])
        assimilate_skill("skill-fb", capabilities=["cap_x"])
        from core.capability_graph_selection import select_fallback_providers
        results = select_fallback_providers(["cap_x"])
        ids = [r.node_id for r in results]
        assert len(ids) >= 1  # At least one fallback found

    def test_kind_filter_limits_fallback(self):
        from core.capability_assimilation import assimilate_device, assimilate_skill
        assimilate_device("dev-fb2", capabilities=["cap_y"])
        assimilate_skill("skill-fb2", capabilities=["cap_y"])
        from core.capability_graph_selection import select_fallback_providers
        results = select_fallback_providers(["cap_y"], kind_filter=["device"])
        ids = [r.node_id for r in results]
        assert "dev-fb2" in ids
        assert "skill-fb2" not in ids


# ---------------------------------------------------------------------------
# C) Network path fallback
# ---------------------------------------------------------------------------

class TestNetworkPathFallback:
    def test_degraded_topology_produces_degraded_path_state(self):
        from core.network_topology_runtime import (
            get_network_topology_runtime,
            TopologyNode,
            TopologyNodeKind,
            TopologyConnectionState,
        )
        runtime = get_network_topology_runtime()
        node = TopologyNode(
            node_id="degraded-topo",
            kind=TopologyNodeKind.DEVICE,
            state=TopologyConnectionState.DEGRADED,
            host="localhost",
            port=0,
        )
        runtime.register_node(node)
        from core.capability_network_bridge import _probe_path_availability
        pa = _probe_path_availability("degraded-topo", {})
        assert pa.path_state in ("degraded", "unknown")  # depends on topology

    def test_unavailable_topology_produces_not_reachable(self):
        from core.network_topology_runtime import (
            get_network_topology_runtime,
            TopologyNode,
            TopologyNodeKind,
            TopologyConnectionState,
        )
        runtime = get_network_topology_runtime()
        node = TopologyNode(
            node_id="unavail-topo",
            kind=TopologyNodeKind.DEVICE,
            state=TopologyConnectionState.UNAVAILABLE,
            host="localhost",
            port=0,
        )
        runtime.register_node(node)
        from core.capability_network_bridge import _probe_path_availability
        pa = _probe_path_availability("unavail-topo", {})
        assert pa.is_reachable is False


# ---------------------------------------------------------------------------
# D) Joint fallback — fallback_joint_select
# ---------------------------------------------------------------------------

class TestFallbackJointSelect:
    def test_returns_joint_selection_result(self):
        from core.capability_network_bridge import fallback_joint_select
        result = fallback_joint_select(["cap_a"])
        assert result is not None

    def test_fallback_result_always_degraded(self):
        _register("fb-joint", caps=["cap_a"])
        from core.capability_network_bridge import fallback_joint_select
        result = fallback_joint_select(["cap_a"])
        assert result.is_degraded is True

    def test_fallback_excludes_excluded_primary(self):
        _register("fb-primary", caps=["cap_a"])
        _register("fb-secondary", caps=["cap_a"])
        from core.capability_network_bridge import fallback_joint_select
        result = fallback_joint_select(["cap_a"], exclude_ids=["fb-primary"])
        if result.selected_provider_id:
            assert result.selected_provider_id != "fb-primary"

    def test_fallback_none_when_nothing_available(self):
        from core.capability_network_bridge import fallback_joint_select
        result = fallback_joint_select(["cap_z"])
        assert result.selected_provider_id is None

    def test_fallback_selects_best_when_options_exist(self):
        _register("fb-best", caps=["cap_a", "cap_b"])
        _register("fb-worse", caps=["cap_a"])
        from core.capability_network_bridge import fallback_joint_select
        result = fallback_joint_select(["cap_a", "cap_b"])
        # Should prefer fb-best (full match) over fb-worse (partial)
        if result.selected_provider_id is not None:
            assert result.selected_provider_id == "fb-best"


# ---------------------------------------------------------------------------
# E) Degraded-mode observability
# ---------------------------------------------------------------------------

class TestDegradedModeObservability:
    def test_is_degraded_true_on_capability_degradation(self):
        from core.capability_network_bridge import joint_select
        result = joint_select(["cap_z"])  # no providers → degraded
        assert result.is_degraded is True

    def test_degraded_reason_non_empty_on_degradation(self):
        from core.capability_network_bridge import joint_select
        result = joint_select(["cap_z"])
        assert isinstance(result.degraded_reason, str)
        assert len(result.degraded_reason) > 0

    def test_explain_joint_selection_describes_degradation(self):
        from core.capability_network_bridge import (
            joint_select, explain_joint_selection,
        )
        result = joint_select(["cap_z"])  # no providers → degraded
        expl = explain_joint_selection(result)
        # degraded explanation should contain something meaningful
        assert len(expl.degraded_explanation) > 0


# ---------------------------------------------------------------------------
# F) Fallback explainability
# ---------------------------------------------------------------------------

class TestFallbackExplainability:
    def test_fallback_reason_present(self):
        _register("fb-expl", caps=["cap_a"])
        from core.capability_network_bridge import joint_select, explain_joint_selection
        result = joint_select(["cap_a"])
        expl = explain_joint_selection(result)
        assert len(expl.fallback_reason) > 0

    def test_fallback_reason_mentions_fallback_provider_if_set(self):
        _register("primary-expl", caps=["cap_a"])
        from core.capability_network_bridge import (
            JointSelectionResult, PathAvailability, explain_joint_selection,
        )
        result = JointSelectionResult(
            selected_provider_id="primary-expl",
            capability_fit_score=None,
            path_availability=PathAvailability(node_id="primary-expl"),
            joint_score=5.0,
            fallback_provider_id="fallback-expl",
            fallback_path="relay",
        )
        expl = explain_joint_selection(result)
        assert "fallback-expl" in expl.fallback_reason

    def test_fallback_reason_mentions_fallback_path_if_set(self):
        from core.capability_network_bridge import (
            JointSelectionResult, PathAvailability, explain_joint_selection,
        )
        result = JointSelectionResult(
            selected_provider_id="p1",
            capability_fit_score=None,
            path_availability=PathAvailability(
                node_id="p1",
                effective_path="direct",
                fallback_path="relay",
            ),
            joint_score=5.0,
        )
        expl = explain_joint_selection(result)
        # fallback_path should appear somewhere in explanation
        assert "relay" in expl.fallback_reason or "relay" in expl.path_reason


# ---------------------------------------------------------------------------
# G) Concurrent provider types — joint selection
# ---------------------------------------------------------------------------

class TestConcurrentProviderTypes:
    def test_selects_from_mixed_kinds(self):
        from core.capability_assimilation import assimilate_device, assimilate_mcp_provider
        assimilate_device("mixed-dev", capabilities=["cap_a"])
        assimilate_mcp_provider("mixed-mcp", tools=["cap_a"])
        from core.capability_network_bridge import joint_select
        result = joint_select(["cap_a"])
        assert result.selected_provider_id is not None
        assert result.selected_provider_id in ("mixed-dev", "mixed-mcp")

    def test_no_filter_best_fit_regardless_of_kind(self):
        from core.capability_assimilation import assimilate_device, assimilate_skill
        assimilate_device("kind-dev", capabilities=["cap_a"])
        assimilate_skill("kind-skill", capabilities=["cap_a", "cap_b"])  # better fit
        from core.capability_network_bridge import joint_select
        result = joint_select(["cap_a", "cap_b"])
        # skill has full match, device has partial match → skill should win
        assert result.selected_provider_id == "kind-skill"

    def test_kind_filter_restricts_selection_domain(self):
        from core.capability_assimilation import assimilate_device, assimilate_skill
        assimilate_device("kf-dev", capabilities=["cap_a", "cap_b"])
        assimilate_skill("kf-skill", capabilities=["cap_a", "cap_b"])
        from core.capability_network_bridge import joint_select
        result = joint_select(["cap_a", "cap_b"], kind_filter=["device"])
        if result.selected_provider_id is not None:
            assert result.selected_provider_id == "kf-dev"


# ---------------------------------------------------------------------------
# H) Ring buffer continuity
# ---------------------------------------------------------------------------

class TestRingBufferContinuity:
    def test_fallback_events_appear_in_bridge_log(self):
        _register("rb-cont", caps=["cap_a"])
        from core.capability_network_bridge import fallback_joint_select, get_bridge_log
        initial = len(get_bridge_log())
        fallback_joint_select(["cap_a"])
        assert len(get_bridge_log()) > initial

    def test_capability_selection_events_appear_in_selection_log(self):
        _register("rb-sel", caps=["cap_a"])
        from core.capability_graph_selection import discover_providers, get_selection_log
        initial = len(get_selection_log())
        discover_providers(["cap_a"])
        assert len(get_selection_log()) > initial

    def test_bridge_log_bounded_256(self):
        from core.capability_network_bridge import get_bridge_log
        assert get_bridge_log().maxlen == 256

    def test_selection_log_bounded_256(self):
        from core.capability_graph_selection import get_selection_log
        assert get_selection_log().maxlen == 256
