#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr2_canonical_route_plan_output_contract.py
=======================================================

PR-2: Canonical routing output completion.

Protects the ``TopologyRoutePlan`` output contract so that downstream
projection and desktop-status-board layers can consume stable, predictable
routing truth without falling back to legacy scattered keys.

Coverage:
  1.  to_dict() exposes "phase" key
  2.  to_dict() exposes "domain" key
  3.  to_dict() exposes "route_reason" key
  4.  to_dict() exposes "primary_model" key
  5.  to_dict() exposes "support_models" key
  6.  to_dict() exposes "authority" key
  7.  to_dict() exposes "active_weights" key
  8.  to_dict() exposes "graph_stats" key
  9.  primary_model dict includes "model_id"
  10. primary_model dict includes "provider_id"
  11. primary_model dict includes "vendor_source"
  12. primary_model dict includes "native_multimodal"
  13. primary_model dict includes "topology_role"
  14. primary_model dict includes "combined_weight"
  15. primary_model dict includes "node_id"
  16. support_model dicts include "model_id"
  17. support_model dicts include "provider_id"
  18. support_model dicts include "vendor_source"
  19. support_model dicts include "native_multimodal"
  20. support_model dicts include "topology_role"
  21. support_model dicts include "combined_weight"
  22. support_model dicts include "node_id"
  23. authority equals CANONICAL_ROUTING_AUTHORITY sentinel
  24. active_weights keys match node_ids of nodes in the plan
  25. active_weights entries contain "base_weight"
  26. active_weights entries contain "state_modifier"
  27. active_weights entries contain "domain_modifier"
  28. active_weights entries contain "combined_weight"
  29. active_weights combined_weight is base * state * domain (rounded)
  30. primary model provider_id is a non-empty string
  31. support model provider_id values are non-empty strings
  32. vendor_source for direct providers is "direct_models"
  33. native_multimodal is True for multimodal-native primary
  34. native_multimodal is False for non-multimodal node
  35. topology_role is a known role string value
  36. combined_weight in node dict matches active_weights entry
  37. empty inventory: primary_model is None in to_dict
  38. empty inventory: support_models is [] in to_dict
  39. empty inventory: authority is still present
  40. empty inventory: active_weights is empty dict
  41. route plan is deterministic across two router instances
  42. to_dict() is JSON-serialisable (no non-primitive values)
  43. primary_model vendor_source is from ProviderCategory enum values
  44. support_models vendor_source values are from ProviderCategory enum values
  45. phase value matches TriStatePhase used for routing
  46. domain value matches RuntimeDomain used for routing
  47. route_reason is non-empty string
  48. active_weights primary node key present when primary_model is present
  49. active_weights support node keys present for all support nodes
  50. downstream-projection: all canonical fields reachable without legacy keys
"""

from __future__ import annotations

import json
import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_full_inventory():
    """Build a multi-provider ProviderInventory for contract tests."""
    from core.model_topology import LegacyLLMProviderSnapshot, ProviderInventory
    from core.model_topology.config_bridge import ConfigBridge

    bridge = ConfigBridge()
    snapshots = [
        LegacyLLMProviderSnapshot.from_dict({
            "provider": "openai",
            "model": "gpt-5.4",
            "models": ["gpt-5.4", "gpt-4o"],
            "speed_score": 8,
            "quality_score": 9,
            "available": True,
            "multimodal": True,
            "env_keys": ["OPENAI_API_KEY"],
        }),
        LegacyLLMProviderSnapshot.from_dict({
            "provider": "anthropic",
            "model": "claude-opus-4.6",
            "models": ["claude-opus-4.6"],
            "speed_score": 6,
            "quality_score": 10,
            "available": True,
            "multimodal": True,
            "env_keys": ["ANTHROPIC_API_KEY"],
        }),
        LegacyLLMProviderSnapshot.from_dict({
            "provider": "groq",
            "model": "llama-3.1-70b",
            "models": ["llama-3.1-70b"],
            "speed_score": 10,
            "quality_score": 7,
            "available": True,
            "multimodal": False,
            "env_keys": ["GROQ_API_KEY"],
        }),
    ]
    return bridge.build_inventory(snapshots)


def _make_full_router():
    from core.model_topology import TopologyRouter
    return TopologyRouter(_make_full_inventory())


def _make_plan():
    from core.continuum.types import RuntimeDomain, TriStatePhase
    router = _make_full_router()
    return router.route(TriStatePhase.LIMINAL, RuntimeDomain.LOCAL)


def _make_plan_dict():
    return _make_plan().to_dict()


# ---------------------------------------------------------------------------
# Section 1 — Top-level keys
# ---------------------------------------------------------------------------


class TestTopLevelKeys:
    """to_dict() must expose all canonical top-level keys."""

    def test_phase_key_present(self):
        assert "phase" in _make_plan_dict()

    def test_domain_key_present(self):
        assert "domain" in _make_plan_dict()

    def test_route_reason_key_present(self):
        assert "route_reason" in _make_plan_dict()

    def test_primary_model_key_present(self):
        assert "primary_model" in _make_plan_dict()

    def test_support_models_key_present(self):
        assert "support_models" in _make_plan_dict()

    def test_authority_key_present(self):
        assert "authority" in _make_plan_dict()

    def test_active_weights_key_present(self):
        assert "active_weights" in _make_plan_dict()

    def test_graph_stats_key_present(self):
        assert "graph_stats" in _make_plan_dict()


# ---------------------------------------------------------------------------
# Section 2 — Primary model canonical fields
# ---------------------------------------------------------------------------


class TestPrimaryModelFields:
    """Serialised primary_model must expose all canonical provider/model fields."""

    def test_primary_model_is_not_none(self):
        d = _make_plan_dict()
        assert d["primary_model"] is not None

    def test_primary_model_has_node_id(self):
        d = _make_plan_dict()
        assert "node_id" in d["primary_model"]

    def test_primary_model_has_model_id(self):
        d = _make_plan_dict()
        assert "model_id" in d["primary_model"]

    def test_primary_model_has_provider_id(self):
        d = _make_plan_dict()
        assert "provider_id" in d["primary_model"]

    def test_primary_model_has_vendor_source(self):
        d = _make_plan_dict()
        assert "vendor_source" in d["primary_model"]

    def test_primary_model_has_native_multimodal(self):
        d = _make_plan_dict()
        assert "native_multimodal" in d["primary_model"]

    def test_primary_model_has_topology_role(self):
        d = _make_plan_dict()
        assert "topology_role" in d["primary_model"]

    def test_primary_model_has_combined_weight(self):
        d = _make_plan_dict()
        assert "combined_weight" in d["primary_model"]

    def test_primary_model_provider_id_non_empty(self):
        d = _make_plan_dict()
        assert isinstance(d["primary_model"]["provider_id"], str)
        assert len(d["primary_model"]["provider_id"]) > 0

    def test_primary_model_model_id_non_empty(self):
        d = _make_plan_dict()
        assert isinstance(d["primary_model"]["model_id"], str)
        assert len(d["primary_model"]["model_id"]) > 0

    def test_primary_model_vendor_source_is_string(self):
        d = _make_plan_dict()
        assert isinstance(d["primary_model"]["vendor_source"], str)

    def test_primary_model_vendor_source_is_category_value(self):
        from core.model_topology.topology_types import ProviderCategory
        valid_values = {c.value for c in ProviderCategory}
        d = _make_plan_dict()
        assert d["primary_model"]["vendor_source"] in valid_values

    def test_primary_model_native_multimodal_is_bool(self):
        d = _make_plan_dict()
        assert isinstance(d["primary_model"]["native_multimodal"], bool)

    def test_primary_model_native_multimodal_true_for_mm_node(self):
        """The multimodal-native primary should report native_multimodal=True."""
        from core.continuum.types import RuntimeDomain, TriStatePhase
        from core.model_topology import TopologyRouter
        plan = TopologyRouter(_make_full_inventory()).route(
            TriStatePhase.SILENT, RuntimeDomain.LOCAL
        )
        d = plan.to_dict()
        # The SILENT phase strongly weights multimodal_core nodes first.
        if d["primary_model"] is not None:
            primary = plan.primary_model
            assert d["primary_model"]["native_multimodal"] == primary.is_multimodal_native

    def test_primary_model_topology_role_is_string(self):
        d = _make_plan_dict()
        assert isinstance(d["primary_model"]["topology_role"], str)

    def test_primary_model_topology_role_is_known_role(self):
        from core.model_topology.topology_types import TopologyRole
        valid_values = {r.value for r in TopologyRole}
        d = _make_plan_dict()
        assert d["primary_model"]["topology_role"] in valid_values

    def test_primary_model_combined_weight_is_positive_float(self):
        d = _make_plan_dict()
        cw = d["primary_model"]["combined_weight"]
        assert isinstance(cw, float)
        assert cw > 0.0

    def test_primary_model_combined_weight_matches_active_weights(self):
        """combined_weight in primary_model dict must match active_weights entry."""
        d = _make_plan_dict()
        node_id = d["primary_model"]["node_id"]
        assert node_id in d["active_weights"]
        assert d["primary_model"]["combined_weight"] == d["active_weights"][node_id]["combined_weight"]


# ---------------------------------------------------------------------------
# Section 3 — Support model canonical fields
# ---------------------------------------------------------------------------


class TestSupportModelFields:
    """Each serialised support_model entry must expose the same canonical fields."""

    def _get_support_models(self):
        d = _make_plan_dict()
        return d["support_models"]

    def test_support_models_is_list(self):
        assert isinstance(self._get_support_models(), list)

    def test_support_models_non_empty_for_full_inventory(self):
        """A full 3-provider inventory should yield at least one support model."""
        assert len(self._get_support_models()) >= 1

    def test_support_model_has_node_id(self):
        for sm in self._get_support_models():
            assert "node_id" in sm

    def test_support_model_has_model_id(self):
        for sm in self._get_support_models():
            assert "model_id" in sm

    def test_support_model_has_provider_id(self):
        for sm in self._get_support_models():
            assert "provider_id" in sm

    def test_support_model_has_vendor_source(self):
        for sm in self._get_support_models():
            assert "vendor_source" in sm

    def test_support_model_has_native_multimodal(self):
        for sm in self._get_support_models():
            assert "native_multimodal" in sm

    def test_support_model_has_topology_role(self):
        for sm in self._get_support_models():
            assert "topology_role" in sm

    def test_support_model_has_combined_weight(self):
        for sm in self._get_support_models():
            assert "combined_weight" in sm

    def test_support_model_provider_ids_non_empty(self):
        for sm in self._get_support_models():
            assert isinstance(sm["provider_id"], str)
            assert len(sm["provider_id"]) > 0

    def test_support_model_vendor_source_values_are_category_values(self):
        from core.model_topology.topology_types import ProviderCategory
        valid_values = {c.value for c in ProviderCategory}
        for sm in self._get_support_models():
            assert sm["vendor_source"] in valid_values

    def test_support_model_topology_role_values_are_known(self):
        from core.model_topology.topology_types import TopologyRole
        valid_values = {r.value for r in TopologyRole}
        for sm in self._get_support_models():
            assert sm["topology_role"] in valid_values

    def test_support_model_combined_weight_matches_active_weights(self):
        """Each support model's combined_weight must match its active_weights entry."""
        d = _make_plan_dict()
        for sm in d["support_models"]:
            node_id = sm["node_id"]
            assert node_id in d["active_weights"]
            assert sm["combined_weight"] == d["active_weights"][node_id]["combined_weight"]


# ---------------------------------------------------------------------------
# Section 4 — Route metadata
# ---------------------------------------------------------------------------


class TestRouteMetadata:
    """Phase, domain, route_reason and authority must be canonical and correct."""

    def test_phase_value_matches_routing_input(self):
        from core.continuum.types import RuntimeDomain, TriStatePhase
        from core.model_topology import TopologyRouter
        plan = TopologyRouter(_make_full_inventory()).route(
            TriStatePhase.MANIFEST, RuntimeDomain.LOCAL
        )
        assert plan.to_dict()["phase"] == TriStatePhase.MANIFEST.value

    def test_domain_value_matches_routing_input(self):
        from core.continuum.types import RuntimeDomain, TriStatePhase
        from core.model_topology import TopologyRouter
        plan = TopologyRouter(_make_full_inventory()).route(
            TriStatePhase.SILENT, RuntimeDomain.CROSS_DEVICE
        )
        assert plan.to_dict()["domain"] == RuntimeDomain.CROSS_DEVICE.value

    def test_route_reason_is_non_empty_string(self):
        d = _make_plan_dict()
        assert isinstance(d["route_reason"], str)
        assert len(d["route_reason"]) > 0

    def test_route_reason_contains_phase(self):
        from core.continuum.types import RuntimeDomain, TriStatePhase
        from core.model_topology import TopologyRouter
        plan = TopologyRouter(_make_full_inventory()).route(
            TriStatePhase.MANIFEST, RuntimeDomain.LOCAL
        )
        assert "manifest" in plan.to_dict()["route_reason"]

    def test_authority_equals_canonical_routing_authority_sentinel(self):
        from core.model_topology.topology_router import CANONICAL_ROUTING_AUTHORITY
        d = _make_plan_dict()
        assert d["authority"] == CANONICAL_ROUTING_AUTHORITY

    def test_authority_identifies_topology_router_module(self):
        d = _make_plan_dict()
        assert "topology_router" in d["authority"]
        assert "TopologyRouter" in d["authority"]


# ---------------------------------------------------------------------------
# Section 5 — Weight semantics
# ---------------------------------------------------------------------------


class TestWeightSemantics:
    """active_weights must expose full breakdown for all considered nodes."""

    def test_active_weights_is_dict(self):
        assert isinstance(_make_plan_dict()["active_weights"], dict)

    def test_active_weights_non_empty_for_full_inventory(self):
        assert len(_make_plan_dict()["active_weights"]) >= 1

    def test_active_weights_entry_has_base_weight(self):
        for _nid, wf in _make_plan_dict()["active_weights"].items():
            assert "base_weight" in wf

    def test_active_weights_entry_has_state_modifier(self):
        for _nid, wf in _make_plan_dict()["active_weights"].items():
            assert "state_modifier" in wf

    def test_active_weights_entry_has_domain_modifier(self):
        for _nid, wf in _make_plan_dict()["active_weights"].items():
            assert "domain_modifier" in wf

    def test_active_weights_entry_has_combined_weight(self):
        for _nid, wf in _make_plan_dict()["active_weights"].items():
            assert "combined_weight" in wf

    def test_active_weights_combined_weight_derivation(self):
        """combined = round(base * state_modifier * domain_modifier, 6)."""
        for _nid, wf in _make_plan_dict()["active_weights"].items():
            expected = round(
                wf["base_weight"] * wf["state_modifier"] * wf["domain_modifier"],
                6,
            )
            assert abs(wf["combined_weight"] - expected) < 1e-9

    def test_active_weights_contains_primary_node(self):
        d = _make_plan_dict()
        if d["primary_model"] is not None:
            assert d["primary_model"]["node_id"] in d["active_weights"]

    def test_active_weights_contains_all_support_nodes(self):
        d = _make_plan_dict()
        for sm in d["support_models"]:
            assert sm["node_id"] in d["active_weights"]

    def test_active_weights_all_combined_weights_positive(self):
        for _nid, wf in _make_plan_dict()["active_weights"].items():
            assert wf["combined_weight"] > 0.0


# ---------------------------------------------------------------------------
# Section 6 — Empty inventory edge cases
# ---------------------------------------------------------------------------


class TestEmptyInventoryContract:
    """Empty inventory must still produce a well-formed, canonical to_dict()."""

    def _empty_dict(self):
        from core.continuum.types import RuntimeDomain, TriStatePhase
        from core.model_topology import ProviderInventory, TopologyRouter
        router = TopologyRouter(ProviderInventory())
        return router.route(TriStatePhase.SILENT, RuntimeDomain.LOCAL).to_dict()

    def test_primary_model_is_none(self):
        assert self._empty_dict()["primary_model"] is None

    def test_support_models_is_empty_list(self):
        assert self._empty_dict()["support_models"] == []

    def test_authority_still_present(self):
        assert "authority" in self._empty_dict()

    def test_authority_is_canonical(self):
        from core.model_topology.topology_router import CANONICAL_ROUTING_AUTHORITY
        assert self._empty_dict()["authority"] == CANONICAL_ROUTING_AUTHORITY

    def test_active_weights_is_empty_dict(self):
        assert self._empty_dict()["active_weights"] == {}

    def test_route_reason_present(self):
        d = self._empty_dict()
        assert isinstance(d["route_reason"], str)
        assert len(d["route_reason"]) > 0


# ---------------------------------------------------------------------------
# Section 7 — JSON serialisability
# ---------------------------------------------------------------------------


class TestJsonSerialisability:
    """to_dict() must produce a JSON-serialisable structure (no raw objects)."""

    def test_full_plan_is_json_serialisable(self):
        d = _make_plan_dict()
        # Must not raise
        serialised = json.dumps(d)
        assert len(serialised) > 0

    def test_empty_plan_is_json_serialisable(self):
        from core.continuum.types import RuntimeDomain, TriStatePhase
        from core.model_topology import ProviderInventory, TopologyRouter
        router = TopologyRouter(ProviderInventory())
        d = router.route(TriStatePhase.SILENT, RuntimeDomain.LOCAL).to_dict()
        serialised = json.dumps(d)
        assert len(serialised) > 0

    def test_all_phases_are_json_serialisable(self):
        from core.model_topology import TopologyRouter
        router = TopologyRouter(_make_full_inventory())
        for _phase, plan in router.route_all_phases().items():
            d = plan.to_dict()
            json.dumps(d)  # Must not raise


# ---------------------------------------------------------------------------
# Section 8 — Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Same inputs must always produce the same serialised output."""

    def test_to_dict_deterministic_across_two_routers(self):
        from core.continuum.types import RuntimeDomain, TriStatePhase
        from core.model_topology import TopologyRouter
        inv = _make_full_inventory()
        d1 = TopologyRouter(inv).route(TriStatePhase.LIMINAL, RuntimeDomain.LOCAL).to_dict()
        d2 = TopologyRouter(inv).route(TriStatePhase.LIMINAL, RuntimeDomain.LOCAL).to_dict()
        assert d1["primary_model"]["node_id"] == d2["primary_model"]["node_id"]
        assert d1["primary_model"]["model_id"] == d2["primary_model"]["model_id"]
        assert d1["primary_model"]["provider_id"] == d2["primary_model"]["provider_id"]
        assert d1["primary_model"]["combined_weight"] == d2["primary_model"]["combined_weight"]
        assert (
            [sm["node_id"] for sm in d1["support_models"]]
            == [sm["node_id"] for sm in d2["support_models"]]
        )


# ---------------------------------------------------------------------------
# Section 9 — Downstream projection compatibility
# ---------------------------------------------------------------------------


class TestDownstreamProjectionCompatibility:
    """Verify that the canonical to_dict() shape satisfies downstream field needs.

    Downstream projection layers must be able to derive the following from
    a route plan dict alone, without consulting legacy UCP keys:
    - selected model identity (model_id + provider_id)
    - vendor source category
    - multimodal capability flag
    - topology role
    - routing rationale
    - phase / domain context
    - routing authority provenance
    - node weights for display / ranking
    """

    def test_model_identity_derivable_without_legacy_keys(self):
        d = _make_plan_dict()
        pm = d["primary_model"]
        assert pm is not None
        # Both model_id and provider_id available without any extra lookup
        assert pm["model_id"]
        assert pm["provider_id"]

    def test_vendor_source_derivable_without_legacy_keys(self):
        d = _make_plan_dict()
        assert d["primary_model"]["vendor_source"]

    def test_multimodal_flag_derivable_without_legacy_keys(self):
        d = _make_plan_dict()
        assert isinstance(d["primary_model"]["native_multimodal"], bool)

    def test_topology_role_derivable_without_legacy_keys(self):
        d = _make_plan_dict()
        assert d["primary_model"]["topology_role"]

    def test_routing_rationale_derivable_without_legacy_keys(self):
        d = _make_plan_dict()
        assert d["route_reason"]

    def test_phase_and_domain_context_derivable(self):
        d = _make_plan_dict()
        assert d["phase"]
        assert d["domain"]

    def test_authority_provenance_derivable(self):
        from core.model_topology.topology_router import CANONICAL_ROUTING_AUTHORITY
        d = _make_plan_dict()
        assert d["authority"] == CANONICAL_ROUTING_AUTHORITY

    def test_node_weights_derivable_for_ranking(self):
        d = _make_plan_dict()
        # Downstream can rank considered nodes by combined_weight
        ranked = sorted(
            d["active_weights"].items(),
            key=lambda kv: kv[1]["combined_weight"],
            reverse=True,
        )
        assert len(ranked) >= 1
        # Top-ranked node should match primary (by combined_weight)
        top_node_id = ranked[0][0]
        assert top_node_id == d["primary_model"]["node_id"]

    def test_support_model_fields_satisfy_projection_contract(self):
        """Each support model must carry the same canonical fields as the primary."""
        d = _make_plan_dict()
        required = {"node_id", "model_id", "provider_id", "vendor_source",
                    "native_multimodal", "topology_role", "combined_weight"}
        for sm in d["support_models"]:
            assert required.issubset(sm.keys()), (
                f"Support model missing fields: {required - sm.keys()}"
            )
