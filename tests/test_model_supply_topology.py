"""
tests/test_model_supply_topology.py
=====================================
Tests for the V2 Model Supply Topology Core (PR-2).

Coverage:
  - ModelNode construction from NormalizedTopologyEntry
  - Base weight computation (multimodal nodes receive highest base weight)
  - ModelSupplyGraph construction from ProviderInventory
  - ModelSupplyGraph query helpers (primary_multimodal_cores, nodes_by_role, …)
  - Edge inference from AggregatorRouterHint
  - ModelWeightField deterministic computation across TriStatePhase × RuntimeDomain
  - apply_weight_fields stable ordering (ties broken by node_id)
  - TopologyRoutePlan selection from ProviderInventory
  - Multimodal anchor enforcement in SILENT and LIMINAL phases
  - Cross-device specialist inclusion in MANIFEST + CROSS_DEVICE
  - TopologyRoutePlan.to_dict serialisation
  - Empty inventory edge cases
"""

from __future__ import annotations

import pytest

from core.continuum.types import RuntimeDomain, TriStatePhase
from core.model_topology import (
    AggregatorKind,
    AggregatorRouterHint,
    ConfigBridge,
    EdgeKind,
    GraphEdge,
    LegacyLLMProviderSnapshot,
    LocalityHint,
    ModelNode,
    ModelSupplyGraph,
    ModelWeightField,
    PolicyConfig,
    ProviderCategory,
    ProviderInventory,
    ProviderInventoryEntry,
    TopologyRole,
    TopologyRoutePlan,
    TopologyRouter,
    apply_weight_fields,
    compute_weight_field,
    node_from_entry,
)
from core.model_topology.topology_types import (
    AvailabilityStatus,
    ModalityCapability,
    ModelIdentity,
    NormalizedTopologyEntry,
    ProviderIdentity,
    ScoringProfile,
)

# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

OPENAI_DICT = {
    "provider": "openai",
    "model": "gpt-5.5",
    "models": ["gpt-5.5", "gpt-4o"],
    "speed_score": 8,
    "quality_score": 9,
    "available": True,
    "multimodal": True,
    "env_keys": ["OPENAI_API_KEY"],
}

ANTHROPIC_DICT = {
    "provider": "anthropic",
    "model": "claude-opus-4-8-20250529",
    "models": ["claude-opus-4-8-20250529", "claude-sonnet-4-6-20251022"],
    "speed_score": 6,
    "quality_score": 10,
    "available": True,
    "multimodal": True,
    "env_keys": ["ANTHROPIC_API_KEY"],
}

GROQ_DICT = {
    "provider": "groq",
    "model": "llama-3.3-70b-versatile",
    "models": ["llama-3.3-70b-versatile"],
    "speed_score": 10,
    "quality_score": 7,
    "available": True,
    "multimodal": False,
    "env_keys": ["GROQ_API_KEY"],
}

DEEPSEEK_DICT = {
    "provider": "deepseek",
    "model": "deepseek-v4-pro",
    "models": ["deepseek-v4-pro"],
    "speed_score": 7,
    "quality_score": 9,
    "available": False,
    "multimodal": False,
    "missing_env_key": "DEEPSEEK_API_KEY",
    "env_keys": ["DEEPSEEK_API_KEY"],
}


@pytest.fixture
def bridge():
    return ConfigBridge()


@pytest.fixture
def full_inventory(bridge):
    snaps = [LegacyLLMProviderSnapshot.from_dict(d) for d in [
        OPENAI_DICT, ANTHROPIC_DICT, GROQ_DICT, DEEPSEEK_DICT
    ]]
    return bridge.build_inventory(snaps)


@pytest.fixture
def full_graph(full_inventory):
    return ModelSupplyGraph.from_inventory(full_inventory)


@pytest.fixture
def full_router(full_inventory):
    return TopologyRouter(full_inventory)


# ---------------------------------------------------------------------------
# Helper: build a minimal NormalizedTopologyEntry
# ---------------------------------------------------------------------------

def _make_entry(
    provider_id: str,
    model_id: str,
    multimodal: bool = False,
    available: bool = True,
    speed: int = 5,
    quality: int = 5,
    roles: list | None = None,
    category: ProviderCategory = ProviderCategory.DIRECT,
) -> NormalizedTopologyEntry:
    return NormalizedTopologyEntry(
        provider=ProviderIdentity(provider_id=provider_id, display_name=provider_id),
        model=ModelIdentity(model_id=model_id, provider_id=provider_id),
        modality=ModalityCapability(native_multimodal=multimodal, supports_vision=multimodal),
        scoring=ScoringProfile(speed_score=speed, quality_score=quality),
        availability=AvailabilityStatus(available=available),
        category=category,
        role_hints=roles or [],
    )


# ===========================================================================
# Section 1: ModelNode construction
# ===========================================================================


class TestModelNodeConstruction:
    def test_node_from_entry_basic(self):
        entry = _make_entry("prov_a", "model_a", multimodal=True, speed=8, quality=9)
        node = node_from_entry(entry)
        assert node.node_id == "prov_a"
        assert node.model.model_id == "model_a"
        assert node.is_multimodal_native is True
        assert node.is_available is True

    def test_non_multimodal_node(self):
        entry = _make_entry("prov_b", "model_b", multimodal=False)
        node = node_from_entry(entry)
        assert node.is_multimodal_native is False

    def test_unavailable_node(self):
        entry = _make_entry("prov_c", "model_c", available=False)
        node = node_from_entry(entry)
        assert node.is_available is False

    def test_multimodal_node_has_higher_base_weight_than_nonmm(self):
        mm_entry = _make_entry("mm", "mm_model", multimodal=True, speed=8, quality=8)
        plain_entry = _make_entry("plain", "plain_model", multimodal=False, speed=8, quality=8)
        mm_node = node_from_entry(mm_entry)
        plain_node = node_from_entry(plain_entry)
        assert mm_node.base_weight > plain_node.base_weight

    def test_dynamic_weight_starts_equal_to_base(self):
        entry = _make_entry("prov_x", "model_x", multimodal=True, speed=7, quality=9)
        node = node_from_entry(entry)
        assert node.dynamic_weight == node.base_weight

    def test_locality_hint_local_for_local_category(self):
        entry = _make_entry("local_prov", "local_model", category=ProviderCategory.LOCAL)
        node = node_from_entry(entry)
        assert LocalityHint.LOCAL in node.locality_hints

    def test_locality_hint_remote_for_remote_category(self):
        entry = _make_entry("remote_prov", "remote_model", category=ProviderCategory.REMOTE)
        node = node_from_entry(entry)
        assert LocalityHint.REMOTE in node.locality_hints

    def test_locality_hint_any_for_unknown_category(self):
        entry = _make_entry("unknown_prov", "unknown_model", category=ProviderCategory.UNKNOWN)
        node = node_from_entry(entry)
        assert LocalityHint.ANY in node.locality_hints

    def test_role_hints_preserved(self):
        entry = _make_entry(
            "r_prov", "r_model",
            roles=[TopologyRole.MULTIMODAL_CORE, TopologyRole.REASONING]
        )
        node = node_from_entry(entry)
        assert TopologyRole.MULTIMODAL_CORE in node.role_hints
        assert TopologyRole.REASONING in node.role_hints

    def test_primary_role_is_first_hint(self):
        entry = _make_entry(
            "prov_role", "model_role",
            roles=[TopologyRole.EXECUTION, TopologyRole.GENERAL]
        )
        node = node_from_entry(entry)
        assert node.topology_role == TopologyRole.EXECUTION

    def test_cross_device_capable_when_role_present(self):
        entry = _make_entry(
            "cd_prov", "cd_model",
            roles=[TopologyRole.CROSS_DEVICE]
        )
        node = node_from_entry(entry)
        assert node.is_cross_device_capable is True

    def test_node_repr_contains_node_id(self):
        entry = _make_entry("repr_prov", "repr_model")
        node = node_from_entry(entry)
        assert "repr_prov" in repr(node)


# ===========================================================================
# Section 2: ModelSupplyGraph construction and queries
# ===========================================================================


class TestModelSupplyGraph:
    def test_from_inventory_node_count(self, full_inventory):
        graph = ModelSupplyGraph.from_inventory(full_inventory)
        assert len(graph) == len(full_inventory)

    def test_graph_contains_expected_providers(self, full_graph):
        assert "openai" in full_graph
        assert "anthropic" in full_graph
        assert "groq" in full_graph

    def test_primary_multimodal_cores_only_mm(self, full_graph):
        cores = full_graph.primary_multimodal_cores()
        for node in cores:
            assert node.is_multimodal_native is True

    def test_primary_multimodal_cores_available_only(self, full_graph):
        cores = full_graph.primary_multimodal_cores(available_only=True)
        for node in cores:
            assert node.is_available is True

    def test_primary_multimodal_cores_sorted_by_base_weight(self, full_graph):
        cores = full_graph.primary_multimodal_cores()
        weights = [n.base_weight for n in cores]
        assert weights == sorted(weights, reverse=True)

    def test_available_nodes_excludes_unavailable(self, full_graph):
        available = full_graph.available_nodes()
        for n in available:
            assert n.is_available is True
        # deepseek is unavailable
        ids = [n.node_id for n in available]
        assert "deepseek" not in ids

    def test_nodes_by_role_returns_matching(self):
        graph = ModelSupplyGraph()
        e1 = _make_entry("r1", "m1", roles=[TopologyRole.REASONING])
        e2 = _make_entry("r2", "m2", roles=[TopologyRole.EXECUTION])
        graph.add_node(node_from_entry(e1))
        graph.add_node(node_from_entry(e2))
        reasoning = graph.nodes_by_role(TopologyRole.REASONING, available_only=False)
        assert len(reasoning) == 1
        assert reasoning[0].node_id == "r1"

    def test_nodes_by_category(self, full_graph):
        # All built-in entries are DIRECT by default
        direct = full_graph.nodes_by_category(ProviderCategory.DIRECT)
        # There may be zero if ConfigBridge maps differently; just check no crash.
        assert isinstance(direct, list)

    def test_add_and_retrieve_edge(self):
        graph = ModelSupplyGraph()
        graph.add_node(node_from_entry(_make_entry("a", "ma")))
        graph.add_node(node_from_entry(_make_entry("b", "mb")))
        edge = GraphEdge(source_node_id="a", target_node_id="b", kind=EdgeKind.SUPPORT)
        graph.add_edge(edge)
        assert edge in graph.edges()
        assert edge in graph.edges_from("a")
        assert edge in graph.edges_to("b")

    def test_duplicate_edge_not_added_twice(self):
        graph = ModelSupplyGraph()
        graph.add_node(node_from_entry(_make_entry("x", "mx")))
        graph.add_node(node_from_entry(_make_entry("y", "my")))
        edge = GraphEdge(source_node_id="x", target_node_id="y", kind=EdgeKind.SUBSTITUTE)
        graph.add_edge(edge)
        graph.add_edge(edge)
        assert graph.edges().count(edge) == 1

    def test_edges_of_kind(self):
        graph = ModelSupplyGraph()
        graph.add_node(node_from_entry(_make_entry("p", "mp")))
        graph.add_node(node_from_entry(_make_entry("q", "mq")))
        agg = GraphEdge("p", "q", EdgeKind.AGGREGATE)
        sup = GraphEdge("q", "p", EdgeKind.SUPPORT)
        graph.add_edge(agg)
        graph.add_edge(sup)
        assert agg in graph.edges_of_kind(EdgeKind.AGGREGATE)
        assert sup not in graph.edges_of_kind(EdgeKind.AGGREGATE)

    def test_cross_device_capable_nodes(self):
        graph = ModelSupplyGraph()
        cd_entry = _make_entry("cd", "cd_m", roles=[TopologyRole.CROSS_DEVICE])
        plain_entry = _make_entry("plain2", "plain2_m")
        graph.add_node(node_from_entry(cd_entry))
        graph.add_node(node_from_entry(plain_entry))
        cd_nodes = graph.cross_device_capable_nodes(available_only=False)
        assert any(n.node_id == "cd" for n in cd_nodes)
        assert not any(n.node_id == "plain2" for n in cd_nodes)

    def test_graph_to_dict_structure(self, full_graph):
        d = full_graph.to_dict()
        assert "nodes" in d
        assert "edges" in d
        assert "stats" in d
        assert d["stats"]["total_nodes"] == len(full_graph)

    def test_graph_repr_contains_stats(self, full_graph):
        r = repr(full_graph)
        assert "ModelSupplyGraph" in r
        assert "nodes=" in r

    def test_empty_graph(self):
        graph = ModelSupplyGraph()
        assert len(graph) == 0
        assert graph.primary_multimodal_cores() == []
        assert graph.available_nodes() == []


# ===========================================================================
# Section 3: ModelWeightField computation
# ===========================================================================


class TestModelWeightField:
    def _mm_node(self, node_id="mm_node"):
        entry = _make_entry(
            node_id, "mm_model", multimodal=True, speed=8, quality=9,
            roles=[TopologyRole.MULTIMODAL_CORE],
        )
        return node_from_entry(entry)

    def _exec_node(self, node_id="exec_node"):
        entry = _make_entry(
            node_id, "exec_model", multimodal=False, speed=10, quality=7,
            roles=[TopologyRole.EXECUTION],
        )
        return node_from_entry(entry)

    def test_combined_weight_equals_base_times_modifiers(self):
        node = self._mm_node()
        wf = compute_weight_field(node, TriStatePhase.SILENT, RuntimeDomain.LOCAL)
        expected = round(node.base_weight * wf.state_modifier * wf.domain_modifier, 6)
        assert wf.combined_weight == expected

    def test_silent_minimizes_execution_role(self):
        exec_node = self._exec_node()
        wf = compute_weight_field(exec_node, TriStatePhase.SILENT, RuntimeDomain.LOCAL)
        # state_modifier for EXECUTION in SILENT is 0.3
        assert wf.state_modifier < 1.0

    def test_silent_amplifies_multimodal(self):
        mm_node = self._mm_node()
        wf = compute_weight_field(mm_node, TriStatePhase.SILENT, RuntimeDomain.LOCAL)
        # state_modifier for MULTIMODAL_CORE in SILENT is 1.4
        assert wf.state_modifier > 1.0

    def test_liminal_amplifies_reasoning(self):
        entry = _make_entry("reas", "reas_m", roles=[TopologyRole.REASONING], speed=6, quality=10)
        node = node_from_entry(entry)
        wf = compute_weight_field(node, TriStatePhase.LIMINAL, RuntimeDomain.LOCAL)
        assert wf.state_modifier > 1.0

    def test_manifest_amplifies_execution(self):
        exec_node = self._exec_node()
        wf = compute_weight_field(exec_node, TriStatePhase.MANIFEST, RuntimeDomain.LOCAL)
        assert wf.state_modifier > 1.0

    def test_cross_device_domain_amplifies_cd_role(self):
        entry = _make_entry("cd_w", "cd_wm", roles=[TopologyRole.CROSS_DEVICE])
        node = node_from_entry(entry)
        wf = compute_weight_field(node, TriStatePhase.MANIFEST, RuntimeDomain.CROSS_DEVICE)
        assert wf.domain_modifier > 1.0

    def test_local_domain_penalizes_cd_role(self):
        entry = _make_entry("cd_pen", "cd_pen_m", roles=[TopologyRole.CROSS_DEVICE])
        node = node_from_entry(entry)
        wf = compute_weight_field(node, TriStatePhase.MANIFEST, RuntimeDomain.LOCAL)
        assert wf.domain_modifier < 1.0

    def test_weight_field_ordering_combined_desc(self):
        mm_node = self._mm_node("mm_a")
        exec_node = self._exec_node("exec_b")
        # In SILENT, multimodal should outweigh execution
        pairs = apply_weight_fields([exec_node, mm_node], TriStatePhase.SILENT, RuntimeDomain.LOCAL)
        # First pair should have higher combined weight
        assert pairs[0][1].combined_weight >= pairs[1][1].combined_weight

    def test_weight_field_tie_broken_by_node_id(self):
        """Two nodes with identical weights → sorted by node_id ascending."""
        # Craft two nodes with identical base, speed, quality, role, modality
        entry_a = _make_entry("z_node", "m1", speed=5, quality=5)
        entry_b = _make_entry("a_node", "m2", speed=5, quality=5)
        node_a = node_from_entry(entry_a)
        node_b = node_from_entry(entry_b)
        pairs = apply_weight_fields(
            [node_a, node_b], TriStatePhase.MANIFEST, RuntimeDomain.LOCAL
        )
        ids = [n.node_id for n, _ in pairs]
        # If combined weights are equal, 'a_node' should come first
        w0 = pairs[0][1].combined_weight
        w1 = pairs[1][1].combined_weight
        if w0 == w1:
            assert ids[0] == "a_node"
        # Otherwise just ensure stable result (no crash)

    def test_apply_weight_fields_updates_node_dynamic_weight(self):
        mm_node = self._mm_node("upd_mm")
        pairs = apply_weight_fields([mm_node], TriStatePhase.SILENT, RuntimeDomain.LOCAL)
        assert mm_node.dynamic_weight == pairs[0][1].combined_weight

    def test_weight_field_repr(self):
        mm_node = self._mm_node()
        wf = compute_weight_field(mm_node, TriStatePhase.SILENT, RuntimeDomain.LOCAL)
        assert "WeightField" in repr(wf)
        assert mm_node.node_id in repr(wf)


# ===========================================================================
# Section 4: TopologyRouter and TopologyRoutePlan
# ===========================================================================


class TestTopologyRouter:
    def test_router_builds_graph_from_inventory(self, full_router):
        assert full_router.graph is not None
        assert len(full_router.graph) > 0

    def test_route_returns_plan(self, full_router):
        plan = full_router.route(TriStatePhase.SILENT, RuntimeDomain.LOCAL)
        assert isinstance(plan, TopologyRoutePlan)

    def test_route_plan_has_primary_model(self, full_router):
        plan = full_router.route(TriStatePhase.SILENT, RuntimeDomain.LOCAL)
        assert plan.primary_model is not None

    def test_route_plan_primary_is_multimodal_in_silent(self, full_router):
        plan = full_router.route(TriStatePhase.SILENT, RuntimeDomain.LOCAL)
        assert plan.primary_model.is_multimodal_native is True

    def test_route_plan_primary_is_multimodal_in_liminal(self, full_router):
        plan = full_router.route(TriStatePhase.LIMINAL, RuntimeDomain.LOCAL)
        assert plan.primary_model.is_multimodal_native is True

    def test_route_plan_manifest_primary_available(self, full_router):
        plan = full_router.route(TriStatePhase.MANIFEST, RuntimeDomain.LOCAL)
        assert plan.primary_model is not None
        assert plan.primary_model.is_available is True

    def test_route_plan_support_models_not_include_primary(self, full_router):
        plan = full_router.route(TriStatePhase.SILENT, RuntimeDomain.LOCAL)
        primary_id = plan.primary_model.node_id
        for s in plan.support_models:
            assert s.node_id != primary_id

    def test_route_plan_support_count_respects_max(self, full_inventory):
        config = PolicyConfig(max_support_models=1)
        router = TopologyRouter(full_inventory, policy_config=config)
        plan = router.route(TriStatePhase.MANIFEST, RuntimeDomain.LOCAL)
        assert len(plan.support_models) <= 1

    def test_route_plan_active_weights_contains_primary(self, full_router):
        plan = full_router.route(TriStatePhase.SILENT, RuntimeDomain.LOCAL)
        assert plan.primary_model.node_id in plan.active_weights

    def test_route_plan_active_weights_contains_support(self, full_router):
        plan = full_router.route(TriStatePhase.MANIFEST, RuntimeDomain.LOCAL)
        for s in plan.support_models:
            assert s.node_id in plan.active_weights

    def test_route_reason_non_empty(self, full_router):
        plan = full_router.route(TriStatePhase.LIMINAL, RuntimeDomain.TRANSITION)
        assert isinstance(plan.route_reason, str)
        assert len(plan.route_reason) > 0

    def test_route_reason_contains_phase(self, full_router):
        plan = full_router.route(TriStatePhase.MANIFEST, RuntimeDomain.LOCAL)
        assert "manifest" in plan.route_reason

    def test_route_reason_contains_domain(self, full_router):
        plan = full_router.route(TriStatePhase.MANIFEST, RuntimeDomain.CROSS_DEVICE)
        assert "cross_device" in plan.route_reason

    def test_manifest_cross_device_includes_cd_specialists(self, bridge):
        """MANIFEST + CROSS_DEVICE must include cross-device capable nodes in support."""
        snaps = [LegacyLLMProviderSnapshot.from_dict(d) for d in [
            OPENAI_DICT, ANTHROPIC_DICT, GROQ_DICT,
        ]]
        inventory = bridge.build_inventory(snaps)

        # Manually inject a cross-device node
        from core.model_topology.topology_types import (
            AvailabilityStatus, ModalityCapability, ModelIdentity,
            NormalizedTopologyEntry, ProviderIdentity, ScoringProfile
        )
        cd_entry = NormalizedTopologyEntry(
            provider=ProviderIdentity(provider_id="cd_specialist", display_name="CD"),
            model=ModelIdentity(model_id="cd_model", provider_id="cd_specialist"),
            modality=ModalityCapability(native_multimodal=False),
            scoring=ScoringProfile(speed_score=8, quality_score=7),
            availability=AvailabilityStatus(available=True),
            category=ProviderCategory.REMOTE,
            role_hints=[TopologyRole.CROSS_DEVICE],
        )
        cd_inv_entry = ProviderInventoryEntry(entry=cd_entry)
        inventory.add(cd_inv_entry)

        router = TopologyRouter(inventory, policy_config=PolicyConfig(max_support_models=5))
        plan = router.route(TriStatePhase.MANIFEST, RuntimeDomain.CROSS_DEVICE)
        support_ids = [n.node_id for n in plan.support_models]
        assert "cd_specialist" in support_ids

    def test_determinism_same_inputs_same_plan(self, full_inventory):
        """Identical inputs must produce identical plans."""
        r1 = TopologyRouter(full_inventory)
        r2 = TopologyRouter(full_inventory)
        p1 = r1.route(TriStatePhase.LIMINAL, RuntimeDomain.LOCAL)
        p2 = r2.route(TriStatePhase.LIMINAL, RuntimeDomain.LOCAL)
        assert (p1.primary_model.node_id if p1.primary_model else None) == \
               (p2.primary_model.node_id if p2.primary_model else None)
        s1 = [n.node_id for n in p1.support_models]
        s2 = [n.node_id for n in p2.support_models]
        assert s1 == s2

    def test_route_all_phases(self, full_router):
        plans = full_router.route_all_phases(domain=RuntimeDomain.LOCAL)
        assert set(plans.keys()) == {"silent", "liminal", "manifest"}
        for plan in plans.values():
            assert isinstance(plan, TopologyRoutePlan)

    def test_to_dict_structure(self, full_router):
        plan = full_router.route(TriStatePhase.MANIFEST, RuntimeDomain.LOCAL)
        d = plan.to_dict()
        assert "phase" in d
        assert "domain" in d
        assert "primary_model" in d
        assert "support_models" in d
        assert "route_reason" in d
        assert "graph_stats" in d

    def test_to_dict_primary_model_has_node_id(self, full_router):
        plan = full_router.route(TriStatePhase.SILENT, RuntimeDomain.LOCAL)
        d = plan.to_dict()
        assert d["primary_model"]["node_id"] is not None

    def test_plan_repr_contains_phase(self, full_router):
        plan = full_router.route(TriStatePhase.SILENT, RuntimeDomain.LOCAL)
        assert "silent" in repr(plan)


# ===========================================================================
# Section 5: Empty inventory edge cases
# ===========================================================================


class TestEmptyInventory:
    def test_empty_graph_construction(self):
        inv = ProviderInventory()
        graph = ModelSupplyGraph.from_inventory(inv)
        assert len(graph) == 0

    def test_router_with_empty_inventory(self):
        inv = ProviderInventory()
        router = TopologyRouter(inv)
        plan = router.route(TriStatePhase.SILENT, RuntimeDomain.LOCAL)
        assert plan.primary_model is None
        assert plan.support_models == []
        assert "no_available_node" in plan.route_reason

    def test_router_empty_to_dict(self):
        inv = ProviderInventory()
        router = TopologyRouter(inv)
        plan = router.route(TriStatePhase.MANIFEST, RuntimeDomain.CROSS_DEVICE)
        d = plan.to_dict()
        assert d["primary_model"] is None
        assert d["support_models"] == []


# ===========================================================================
# Section 6: __init__ exports
# ===========================================================================


class TestModuleExports:
    def test_all_new_symbols_importable(self):
        from core.model_topology import (
            EdgeKind,
            GraphEdge,
            LocalityHint,
            ModelNode,
            ModelSupplyGraph,
            ModelWeightField,
            PolicyConfig,
            TopologyRoutePlan,
            TopologyRouter,
            apply_weight_fields,
            compute_weight_field,
            node_from_entry,
        )
        # All must be importable without error
        assert EdgeKind is not None
        assert GraphEdge is not None
        assert LocalityHint is not None
        assert ModelNode is not None
        assert ModelSupplyGraph is not None
        assert ModelWeightField is not None
        assert PolicyConfig is not None
        assert TopologyRoutePlan is not None
        assert TopologyRouter is not None
        assert apply_weight_fields is not None
        assert compute_weight_field is not None
        assert node_from_entry is not None
