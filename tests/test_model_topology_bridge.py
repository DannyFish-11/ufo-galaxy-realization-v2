"""
tests/test_model_topology_bridge.py
=====================================
Unit tests for the V2 Model Topology Bridge layer (core/model_topology/).

Coverage:
  - Provider inventory normalisation from dashboard-era snapshots
  - Preservation of multimodal / availability / speed / quality semantics
  - Category and source mapping (direct / oneapi / tools / local / node_backed)
  - Bridge output stability for missing / partial fields
  - Aggregator / router semantic hint extraction
  - ProviderInventory queries (available, multimodal, by_category, by_role, top_N)
  - Serialisation round-trip (to_dict)
  - LegacyNodeAPIEntry bridge
  - LegacyRouterSemantics overrides
"""

from __future__ import annotations

import pytest

from core.model_topology import (
    AggregatorKind,
    ConfigBridge,
    LegacyLLMProviderSnapshot,
    LegacyNodeAPIEntry,
    LegacyNodeAPIKeySpec,
    LegacyProviderHealthDetail,
    LegacyRouterSemantics,
    ModalityCapability,
    NormalizedTopologyEntry,
    ProviderCategory,
    ProviderInventory,
    ProviderInventoryEntry,
    ScoringProfile,
    TopologyRole,
)
from core.model_topology.topology_types import AvailabilityStatus, ModelIdentity, ProviderIdentity

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

OPENAI_DICT = {
    "provider": "openai",
    "model": "gpt-5.5",
    "models": ["gpt-5.5", "gpt-5.5-thinking", "gpt-4.1", "gpt-4o"],
    "speed_score": 8,
    "quality_score": 9,
    "available": True,
    "multimodal": True,
    "env_keys": ["OPENAI_API_KEY"],
}

ANTHROPIC_DICT = {
    "provider": "anthropic",
    "model": "claude-sonnet-4-6-20251022",
    "models": ["claude-opus-4-8-20250529", "claude-sonnet-4-6-20251022", "claude-haiku-4-5-20251001"],
    "speed_score": 7,
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
    "available": False,
    "multimodal": False,
    "missing_env_key": "GROQ_API_KEY",
    "env_keys": ["GROQ_API_KEY"],
}

DEEPSEEK_DICT = {
    "provider": "deepseek",
    "model": "deepseek-v4-pro",
    "models": ["deepseek-v4-pro", "deepseek-ai/DeepSeek-V3", "deepseek-chat", "deepseek-reasoner"],
    "speed_score": 9,
    "quality_score": 8,
    "available": False,
    "multimodal": False,
    "missing_env_key": "DEEPSEEK_API_KEY",
    "env_keys": ["DEEPSEEK_API_KEY"],
}

ALL_PROVIDER_DICTS = [OPENAI_DICT, ANTHROPIC_DICT, GROQ_DICT, DEEPSEEK_DICT]

NODE_ONEAPI = {
    "node_id": "01",
    "name": "OneAPI 聚合器",
    "category": "llm",
    "keys": [
        {"env_var": "OPENROUTER_API_KEY", "label": "OpenRouter", "configured": True},
        {"env_var": "XAI_API_KEY", "label": "xAI", "configured": False},
    ],
    "all_configured": False,
}

NODE_LOCAL_LLM = {
    "node_id": "79",
    "name": "本地 LLM",
    "category": "local_llm",
    "keys": [
        {"env_var": "OLLAMA_URL", "label": "Ollama URL", "configured": True},
    ],
    "all_configured": True,
}

NODE_VISION = {
    "node_id": "90",
    "name": "多模态视觉",
    "category": "vision",
    "keys": [
        {"env_var": "GEMINI_API_KEY", "label": "Gemini", "configured": True},
    ],
    "all_configured": True,
}


@pytest.fixture
def bridge() -> ConfigBridge:
    return ConfigBridge()


@pytest.fixture
def all_snapshots() -> list:
    return [LegacyLLMProviderSnapshot.from_dict(d) for d in ALL_PROVIDER_DICTS]


# ===========================================================================
# 1. LegacyLLMProviderSnapshot construction
# ===========================================================================


class TestLegacyLLMProviderSnapshot:
    def test_from_dict_complete(self):
        s = LegacyLLMProviderSnapshot.from_dict(OPENAI_DICT)
        assert s.provider == "openai"
        assert s.model == "gpt-5.5"
        assert len(s.models) == 4
        assert s.speed_score == 8
        assert s.quality_score == 9
        assert s.available is True
        assert s.multimodal is True
        assert s.missing_env_key is None

    def test_from_dict_unavailable(self):
        s = LegacyLLMProviderSnapshot.from_dict(GROQ_DICT)
        assert s.available is False
        assert s.missing_env_key == "GROQ_API_KEY"

    def test_from_dict_partial_fields(self):
        s = LegacyLLMProviderSnapshot.from_dict({"provider": "minimal", "model": "m1", "models": []})
        assert s.speed_score == 5
        assert s.quality_score == 5
        assert s.available is False
        assert s.multimodal is False

    def test_to_dict_roundtrip(self):
        s = LegacyLLMProviderSnapshot.from_dict(OPENAI_DICT)
        d = s.to_dict()
        assert d["provider"] == "openai"
        assert d["available"] is True
        assert "missing_env_key" not in d

    def test_to_dict_includes_missing_env_key_when_unavailable(self):
        s = LegacyLLMProviderSnapshot.from_dict(GROQ_DICT)
        d = s.to_dict()
        assert d["missing_env_key"] == "GROQ_API_KEY"


# ===========================================================================
# 2. bridge_provider – single-entry normalisation
# ===========================================================================


class TestBridgeProvider:
    def test_provider_identity_set(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(OPENAI_DICT)
        entry = bridge.bridge_provider(snap)
        assert entry.provider.provider_id == "openai"
        assert isinstance(entry.provider, ProviderIdentity)

    def test_model_identity_set(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(OPENAI_DICT)
        entry = bridge.bridge_provider(snap)
        assert entry.model.model_id == "gpt-5.5"
        assert entry.model.provider_id == "openai"
        assert "gpt-4o" in entry.model.alternatives

    def test_multimodal_preserved(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(OPENAI_DICT)
        entry = bridge.bridge_provider(snap)
        assert entry.modality.native_multimodal is True
        assert entry.modality.supports_vision is True

    def test_non_multimodal_preserved(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(GROQ_DICT)
        entry = bridge.bridge_provider(snap)
        assert entry.modality.native_multimodal is False
        assert entry.modality.supports_vision is False

    def test_speed_quality_preserved(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(OPENAI_DICT)
        entry = bridge.bridge_provider(snap)
        assert entry.scoring.speed_score == 8
        assert entry.scoring.quality_score == 9

    def test_availability_available(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(OPENAI_DICT)
        entry = bridge.bridge_provider(snap)
        assert entry.is_available is True
        assert entry.availability.missing_env_key is None

    def test_availability_unavailable(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(GROQ_DICT)
        entry = bridge.bridge_provider(snap)
        assert entry.is_available is False
        assert entry.availability.missing_env_key == "GROQ_API_KEY"

    def test_category_is_direct_for_regular_provider(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(OPENAI_DICT)
        entry = bridge.bridge_provider(snap)
        assert entry.category == ProviderCategory.DIRECT

    def test_raw_metadata_preserved(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(OPENAI_DICT)
        entry = bridge.bridge_provider(snap)
        assert entry.raw_metadata["provider"] == "openai"

    def test_health_enriches_vision_flag(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(GROQ_DICT)  # non-multimodal
        health = LegacyProviderHealthDetail(provider="groq", supports_vision=True)
        entry = bridge.bridge_provider(snap, health=health)
        # static flag is False but health says vision is supported
        assert entry.modality.supports_vision is True

    def test_repr_contains_provider_id(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(OPENAI_DICT)
        entry = bridge.bridge_provider(snap)
        assert "openai" in repr(entry)


# ===========================================================================
# 3. Role hints derivation
# ===========================================================================


class TestRoleHints:
    def test_multimodal_provider_gets_multimodal_core_hint(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(OPENAI_DICT)
        entry = bridge.bridge_provider(snap)
        assert TopologyRole.MULTIMODAL_CORE in entry.role_hints

    def test_quality_10_gets_reasoning_hint(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(ANTHROPIC_DICT)
        entry = bridge.bridge_provider(snap)
        assert TopologyRole.REASONING in entry.role_hints

    def test_speed_10_gets_execution_hint(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(GROQ_DICT)
        entry = bridge.bridge_provider(snap)
        assert TopologyRole.EXECUTION in entry.role_hints

    def test_no_duplicate_hints(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(ANTHROPIC_DICT)
        entry = bridge.bridge_provider(snap)
        assert len(entry.role_hints) == len(set(entry.role_hints))

    def test_non_multimodal_non_special_gets_general(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict({
            "provider": "plain",
            "model": "plain-model",
            "models": ["plain-model"],
            "speed_score": 5,
            "quality_score": 5,
            "available": True,
            "multimodal": False,
        })
        entry = bridge.bridge_provider(snap)
        assert TopologyRole.GENERAL in entry.role_hints


# ===========================================================================
# 4. Partial / missing field robustness
# ===========================================================================


class TestPartialFields:
    def test_empty_models_list(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict({
            "provider": "sparse",
            "model": "sparse-m",
            "models": [],
            "speed_score": 5,
            "quality_score": 5,
            "available": False,
        })
        entry = bridge.bridge_provider(snap)
        assert entry.model.model_id == "sparse-m"
        assert entry.model.alternatives == []

    def test_missing_model_field_defaults_to_provider_default(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict({
            "provider": "nomodel",
            "model": "",
            "models": [],
            "speed_score": 5,
            "quality_score": 5,
            "available": False,
        })
        entry = bridge.bridge_provider(snap)
        assert entry.model.model_id == "nomodel-default"

    def test_speed_score_clamped_above_10(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict({
            "provider": "fast",
            "model": "fast-m",
            "models": [],
            "speed_score": 99,
            "quality_score": 5,
            "available": True,
            "multimodal": False,
        })
        entry = bridge.bridge_provider(snap)
        assert entry.scoring.speed_score == 10

    def test_speed_score_clamped_below_1(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict({
            "provider": "slow",
            "model": "slow-m",
            "models": [],
            "speed_score": -5,
            "quality_score": 5,
            "available": True,
            "multimodal": False,
        })
        entry = bridge.bridge_provider(snap)
        assert entry.scoring.speed_score == 1

    def test_available_true_no_missing_env_key(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(OPENAI_DICT)
        entry = bridge.bridge_provider(snap)
        assert entry.availability.missing_env_key is None


# ===========================================================================
# 5. Node-API bridge
# ===========================================================================


class TestBridgeNodeAPI:
    def test_oneapi_node_gets_oneapi_category(self, bridge):
        node = LegacyNodeAPIEntry.from_dict(NODE_ONEAPI)
        entry = bridge.bridge_node_api(node)
        assert entry.category == ProviderCategory.ONEAPI

    def test_oneapi_node_gets_routing_role(self, bridge):
        node = LegacyNodeAPIEntry.from_dict(NODE_ONEAPI)
        entry = bridge.bridge_node_api(node)
        assert TopologyRole.ROUTING in entry.role_hints

    def test_local_llm_node_gets_local_category(self, bridge):
        node = LegacyNodeAPIEntry.from_dict(NODE_LOCAL_LLM)
        entry = bridge.bridge_node_api(node)
        assert entry.category == ProviderCategory.LOCAL

    def test_local_llm_node_gets_execution_and_memory_roles(self, bridge):
        node = LegacyNodeAPIEntry.from_dict(NODE_LOCAL_LLM)
        entry = bridge.bridge_node_api(node)
        assert TopologyRole.EXECUTION in entry.role_hints
        assert TopologyRole.MEMORY in entry.role_hints

    def test_vision_node_is_multimodal(self, bridge):
        node = LegacyNodeAPIEntry.from_dict(NODE_VISION)
        entry = bridge.bridge_node_api(node)
        assert entry.modality.native_multimodal is True
        assert entry.modality.supports_vision is True

    def test_vision_node_availability_reflects_all_configured(self, bridge):
        node = LegacyNodeAPIEntry.from_dict(NODE_VISION)
        entry = bridge.bridge_node_api(node)
        assert entry.is_available is True

    def test_oneapi_node_unavailable_when_not_fully_configured(self, bridge):
        node = LegacyNodeAPIEntry.from_dict(NODE_ONEAPI)
        entry = bridge.bridge_node_api(node)
        assert entry.is_available is False


# ===========================================================================
# 6. build_inventory – batch normalisation
# ===========================================================================


class TestBuildInventory:
    def test_inventory_contains_all_providers(self, bridge, all_snapshots):
        inventory = bridge.build_inventory(all_snapshots)
        assert len(inventory) == len(all_snapshots)

    def test_inventory_with_node_entries(self, bridge, all_snapshots):
        nodes = [
            LegacyNodeAPIEntry.from_dict(NODE_ONEAPI),
            LegacyNodeAPIEntry.from_dict(NODE_LOCAL_LLM),
        ]
        inventory = bridge.build_inventory(all_snapshots, node_entries=nodes)
        assert len(inventory) == len(all_snapshots) + 2

    def test_inventory_available_entries(self, bridge, all_snapshots):
        inventory = bridge.build_inventory(all_snapshots)
        available = inventory.available_entries()
        # openai and anthropic are available; groq and deepseek are not
        available_ids = {e.provider_id for e in available}
        assert "openai" in available_ids
        assert "anthropic" in available_ids
        assert "groq" not in available_ids
        assert "deepseek" not in available_ids

    def test_inventory_multimodal_entries(self, bridge, all_snapshots):
        inventory = bridge.build_inventory(all_snapshots)
        mm = inventory.multimodal_entries()
        mm_ids = {e.provider_id for e in mm}
        assert "openai" in mm_ids
        assert "anthropic" in mm_ids
        assert "groq" not in mm_ids

    def test_inventory_by_category_direct(self, bridge, all_snapshots):
        inventory = bridge.build_inventory(all_snapshots)
        directs = inventory.by_category(ProviderCategory.DIRECT)
        assert len(directs) == len(all_snapshots)

    def test_inventory_top_by_quality(self, bridge, all_snapshots):
        inventory = bridge.build_inventory(all_snapshots)
        top = inventory.top_by_quality(n=1, available_only=False)
        assert top[0].entry.scoring.quality_score == 10  # anthropic

    def test_inventory_top_by_speed(self, bridge, all_snapshots):
        inventory = bridge.build_inventory(all_snapshots)
        top = inventory.top_by_speed(n=1, available_only=False)
        assert top[0].entry.scoring.speed_score == 10  # groq

    def test_inventory_get_by_provider_id(self, bridge, all_snapshots):
        inventory = bridge.build_inventory(all_snapshots)
        entry = inventory.get("openai")
        assert entry is not None
        assert entry.provider_id == "openai"

    def test_inventory_contains_operator(self, bridge, all_snapshots):
        inventory = bridge.build_inventory(all_snapshots)
        assert "openai" in inventory
        assert "nonexistent_provider" not in inventory

    def test_inventory_to_dict_is_serialisable(self, bridge, all_snapshots):
        import json
        inventory = bridge.build_inventory(all_snapshots)
        d = inventory.to_dict()
        # Should be JSON-serialisable (no non-serialisable types)
        serialised = json.dumps(d)
        recovered = json.loads(serialised)
        assert recovered["stats"]["total"] == len(all_snapshots)

    def test_inventory_stats_counts(self, bridge, all_snapshots):
        inventory = bridge.build_inventory(all_snapshots)
        stats = inventory.to_dict()["stats"]
        assert stats["total"] == 4
        assert stats["available"] == 2
        assert stats["multimodal"] == 2

    def test_inventory_skips_bad_snapshots_gracefully(self, bridge):
        # Snapshot with invalid provider_id (empty string) – bridge should skip it
        bad = LegacyLLMProviderSnapshot(
            provider="",  # will cause ProviderIdentity ValueError
            model="m",
            models=[],
            speed_score=5,
            quality_score=5,
            available=False,
        )
        good = LegacyLLMProviderSnapshot.from_dict(OPENAI_DICT)
        inventory = bridge.build_inventory([bad, good])
        # Only good entry should be in inventory
        assert len(inventory) == 1
        assert "openai" in inventory


# ===========================================================================
# 7. Aggregator / router semantic hint extraction
# ===========================================================================


class TestAggregatorHints:
    def test_multimodal_core_aggregator_hint_present(self, bridge, all_snapshots):
        inventory = bridge.build_inventory(all_snapshots)
        kinds = {h.kind for h in inventory.aggregator_hints}
        assert AggregatorKind.MULTIMODAL_CORE_AGGREGATOR in kinds

    def test_reasoning_aggregator_hint_contains_anthropic(self, bridge, all_snapshots):
        inventory = bridge.build_inventory(all_snapshots)
        reasoning_hints = [h for h in inventory.aggregator_hints if h.kind == AggregatorKind.REASONING_AGGREGATOR]
        assert len(reasoning_hints) == 1
        assert "anthropic" in reasoning_hints[0].candidate_provider_ids

    def test_execution_aggregator_hint_contains_groq(self, bridge, all_snapshots):
        inventory = bridge.build_inventory(all_snapshots)
        exec_hints = [h for h in inventory.aggregator_hints if h.kind == AggregatorKind.EXECUTION_AGGREGATOR]
        assert len(exec_hints) == 1
        assert "groq" in exec_hints[0].candidate_provider_ids

    def test_route_arbiter_hint_populated_from_node(self, bridge, all_snapshots):
        nodes = [LegacyNodeAPIEntry.from_dict(NODE_ONEAPI)]
        inventory = bridge.build_inventory(all_snapshots, node_entries=nodes)
        arbiter_hints = [h for h in inventory.aggregator_hints if h.kind == AggregatorKind.ROUTE_ARBITER]
        assert len(arbiter_hints) == 1
        assert "node_01" in arbiter_hints[0].candidate_provider_ids

    def test_router_semantics_merges_into_hints(self, bridge, all_snapshots):
        semantics = LegacyRouterSemantics(
            multi_llm_router_providers=["openai"],
            memory_providers=["anthropic"],
        )
        inventory = bridge.build_inventory(all_snapshots, router_semantics=semantics)
        arbiter_hints = [h for h in inventory.aggregator_hints if h.kind == AggregatorKind.ROUTE_ARBITER]
        assert "openai" in arbiter_hints[0].candidate_provider_ids
        mem_hints = [h for h in inventory.aggregator_hints if h.kind == AggregatorKind.MEMORY_AGGREGATOR]
        assert "anthropic" in mem_hints[0].candidate_provider_ids

    def test_all_six_aggregator_kinds_present(self, bridge, all_snapshots):
        inventory = bridge.build_inventory(all_snapshots)
        kinds = {h.kind for h in inventory.aggregator_hints}
        assert kinds == set(AggregatorKind)

    def test_hint_repr_contains_kind(self, bridge, all_snapshots):
        inventory = bridge.build_inventory(all_snapshots)
        for hint in inventory.aggregator_hints:
            assert hint.kind.value in repr(hint)


# ===========================================================================
# 8. ScoringProfile and ModalityCapability unit tests
# ===========================================================================


class TestValueObjects:
    def test_scoring_profile_composite(self):
        sp = ScoringProfile(speed_score=8, quality_score=9)
        assert sp.composite_score == 8.5

    def test_scoring_profile_invalid_range(self):
        with pytest.raises(ValueError):
            ScoringProfile(speed_score=0, quality_score=5)
        with pytest.raises(ValueError):
            ScoringProfile(speed_score=5, quality_score=11)

    def test_modality_from_flag_true(self):
        m = ModalityCapability.from_multimodal_flag(True)
        assert m.native_multimodal is True
        assert m.supports_vision is True

    def test_modality_from_flag_false(self):
        m = ModalityCapability.from_multimodal_flag(False)
        assert m.native_multimodal is False
        assert m.supports_vision is False

    def test_availability_from_dashboard_entry_available(self):
        a = AvailabilityStatus.from_dashboard_entry(True, None, ["OPENAI_API_KEY"])
        assert a.available is True
        assert a.missing_env_key is None

    def test_availability_from_dashboard_entry_unavailable(self):
        a = AvailabilityStatus.from_dashboard_entry(False, "GROQ_API_KEY", ["GROQ_API_KEY"])
        assert a.available is False
        assert a.missing_env_key == "GROQ_API_KEY"

    def test_provider_identity_empty_id_raises(self):
        with pytest.raises(ValueError):
            ProviderIdentity(provider_id="")

    def test_model_identity_empty_model_id_raises(self):
        with pytest.raises(ValueError):
            ModelIdentity(model_id="", provider_id="openai")


# ===========================================================================
# 9. ProviderInventory edge cases
# ===========================================================================


class TestProviderInventoryEdgeCases:
    def test_empty_inventory(self):
        inv = ProviderInventory()
        assert len(inv) == 0
        assert inv.available_entries() == []
        assert inv.multimodal_entries() == []

    def test_get_nonexistent_returns_none(self):
        inv = ProviderInventory()
        assert inv.get("nonexistent") is None

    def test_duplicate_provider_overwrites(self, bridge):
        snap1 = LegacyLLMProviderSnapshot.from_dict(OPENAI_DICT)
        snap2 = LegacyLLMProviderSnapshot.from_dict({**OPENAI_DICT, "quality_score": 6})
        inventory = bridge.build_inventory([snap1, snap2])
        assert len(inventory) == 1
        assert inventory.get("openai").entry.scoring.quality_score == 6

    def test_inventory_entry_to_dict_has_all_keys(self, bridge):
        snap = LegacyLLMProviderSnapshot.from_dict(OPENAI_DICT)
        entry = bridge.bridge_provider(snap)
        inv_entry = ProviderInventoryEntry(entry=entry)
        d = inv_entry.to_dict()
        for key in [
            "provider_id", "model_id", "category", "available",
            "native_multimodal", "speed_score", "quality_score", "composite_score",
        ]:
            assert key in d, f"Missing key: {key}"

    def test_by_role_returns_matching_entries(self, bridge, all_snapshots):
        inventory = bridge.build_inventory(all_snapshots)
        mm_entries = inventory.by_role(TopologyRole.MULTIMODAL_CORE)
        mm_ids = {e.provider_id for e in mm_entries}
        assert "openai" in mm_ids
        assert "anthropic" in mm_ids
        assert "groq" not in mm_ids
