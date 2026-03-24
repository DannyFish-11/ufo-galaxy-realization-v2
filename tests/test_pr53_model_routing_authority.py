#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr53_model_routing_authority.py
==========================================

PR-routing-authority — Canonical model-routing authority unification.

Validates:
  1.  CANONICAL_ROUTING_AUTHORITY sentinel is importable from topology_router.
  2.  CANONICAL_ROUTING_AUTHORITY is a non-empty string.
  3.  CANONICAL_ROUTING_AUTHORITY identifies TopologyRouter by module path.
  4.  TopologyRoutePlan.to_dict() includes "primary_model" key.
  5.  TopologyRoutePlan.to_dict() includes "support_models" key.
  6.  TopologyRoutePlan.to_dict() includes "route_reason" key.
  7.  TopologyRoutePlan.to_dict() "primary_model" dict includes "model_id".
  8.  TopologyRoutePlan.to_dict() "primary_model" dict includes "native_multimodal".
  9.  build_runtime_projection with route_plan sets routing_authority to CANONICAL.
  10. build_runtime_projection without route_plan sets routing_authority to "none".
  11. RuntimeProjection.routing_authority field exists with default "none".
  12. RuntimeProjection.to_dict() includes "routing_authority" key.
  13. ModelRoutingProjection has routing_authority_source field.
  14. ModelRoutingProjection default routing_authority_source is "none".
  15. _build_model_routing_projection with topology_route_plan sets source to "topology_router".
  16. _build_model_routing_projection without topology_route_plan falls back to legacy keys.
  17. _build_model_routing_projection legacy path sets source to "legacy_ucp_keys".
  18. _build_model_routing_projection empty UCP sets source to "none".
  19. topology_route_plan primary model_id is used as selected_model (canonical path).
  20. topology_route_plan native_multimodal is used as is_native_multimodal (canonical path).
  21. topology_route_plan route_reason is used as route_reason (canonical path).
  22. topology_route_plan support_models produce support_model_hints (canonical path).
  23. legacy chosen_model is used when topology_route_plan absent.
  24. legacy chosen_provider is used when topology_route_plan absent.
  25. legacy multimodal_route block used when topology_route_plan absent.
  26. topology_route_plan takes precedence over legacy chosen_model key.
  27. topology_route_plan takes precedence over legacy chosen_provider key.
  28. topology_route_plan takes precedence over legacy multimodal_route block.
  29. build_desktop_status_projection model_routing reflects canonical path.
  30. build_desktop_status_projection model_routing routing_authority_source "topology_router".
  31. build_desktop_status_projection model_routing routing_authority_source "legacy_ucp_keys".
  32. build_desktop_status_projection model_routing routing_authority_source "none" on empty UCP.
  33. ModelRoutingProjection.to_dict() includes routing_authority_source.
  34. MultiLLMRouter is in LEGACY_PATH_REGISTRY.
  35. core.multi_llm_router is in LEGACY_PATH_REGISTRY.
  36. dashboard.backend.main.llm_providers is in LEGACY_PATH_REGISTRY.
  37. MultiLLMRouter entry status is LEGACY_COMPATIBILITY.
  38. core.multi_llm_router entry status is LEGACY_COMPATIBILITY.
  39. dashboard.backend.main.llm_providers entry status is LEGACY_COMPATIBILITY.
  40. MultiLLMRouter entry pr_guardrail_added is "PR-routing-authority".
  41. LEGACY_PATH_REGISTRY contains at least 3 PR-routing-authority entries.
  42. is_legacy_path returns True for core.multi_llm_router.MultiLLMRouter.
  43. is_legacy_path returns True for core.multi_llm_router.
  44. is_legacy_path returns True for dashboard.backend.main.llm_providers.
  45. classify_path_status returns LEGACY_COMPATIBILITY for MultiLLMRouter.
  46. emit_legacy_guardrail does not raise for legacy routing paths.
  47. docs/MODEL_ROUTING_AUTHORITY.md exists.
  48. docs/MODEL_ROUTING_AUTHORITY.md mentions TopologyRouter.
  49. docs/MODEL_ROUTING_AUTHORITY.md mentions TopologyRoutePlan.
  50. docs/MODEL_ROUTING_AUTHORITY.md mentions RuntimeProjection.
  51. docs/MODEL_ROUTING_AUTHORITY.md mentions DesktopStatusProjection.
  52. docs/MODEL_ROUTING_AUTHORITY.md mentions CANONICAL_ROUTING_AUTHORITY.
  53. docs/MODEL_ROUTING_AUTHORITY.md mentions legacy_ucp_keys.
  54. docs/MODEL_ROUTING_AUTHORITY.md mentions MultiLLMRouter.
  55. routing_authority_source "topology_router" on empty primary model.
  56. support_model_hints filtered to non-None model_ids from topology plan.
  57. topology_route_plan with no primary_model still sets authority to "topology_router".
  58. legacy path does not activate when topology_route_plan key present but empty dict.
  59. RuntimeProjection.routing_authority set correctly when built with route_plan.
  60. DesktopStatusProjection.to_dict() includes model_routing.routing_authority_source.
"""

from __future__ import annotations

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
# Helpers
# ---------------------------------------------------------------------------


def _make_minimal_inventory():
    """Build a minimal ProviderInventory for TopologyRouter tests."""
    from core.model_topology import LegacyLLMProviderSnapshot, ProviderInventory
    from core.model_topology.config_bridge import ConfigBridge

    bridge = ConfigBridge()
    snapshots = [
        LegacyLLMProviderSnapshot.from_dict({
            "provider": "openai",
            "model": "gpt-4o",
            "models": ["gpt-4o"],
            "speed_score": 8,
            "quality_score": 9,
            "available": True,
            "multimodal": True,
            "env_keys": ["OPENAI_API_KEY"],
        }),
    ]
    return bridge.build_inventory(snapshots)


def _make_route_plan():
    """Build a minimal TopologyRoutePlan."""
    from core.continuum.types import RuntimeDomain, TriStatePhase
    from core.model_topology.topology_router import TopologyRouter

    inventory = _make_minimal_inventory()
    router = TopologyRouter(inventory)
    return router.route(TriStatePhase.LIMINAL, RuntimeDomain.LOCAL)


def _make_continuum_state():
    from core.continuum.types import ContinuumPhase, ContinuumState

    return ContinuumState(phase=ContinuumPhase.LIMINAL, coherence=0.7)


# ---------------------------------------------------------------------------
# 1-3: CANONICAL_ROUTING_AUTHORITY sentinel
# ---------------------------------------------------------------------------


def test_01_canonical_authority_importable():
    from core.model_topology.topology_router import CANONICAL_ROUTING_AUTHORITY

    assert CANONICAL_ROUTING_AUTHORITY is not None


def test_02_canonical_authority_non_empty():
    from core.model_topology.topology_router import CANONICAL_ROUTING_AUTHORITY

    assert isinstance(CANONICAL_ROUTING_AUTHORITY, str)
    assert len(CANONICAL_ROUTING_AUTHORITY) > 0


def test_03_canonical_authority_identifies_topology_router():
    from core.model_topology.topology_router import CANONICAL_ROUTING_AUTHORITY

    assert "TopologyRouter" in CANONICAL_ROUTING_AUTHORITY
    assert "topology_router" in CANONICAL_ROUTING_AUTHORITY


# ---------------------------------------------------------------------------
# 4-8: TopologyRoutePlan.to_dict() output structure
# ---------------------------------------------------------------------------


def test_04_route_plan_to_dict_has_primary_model():
    plan = _make_route_plan()
    d = plan.to_dict()
    assert "primary_model" in d


def test_05_route_plan_to_dict_has_support_models():
    plan = _make_route_plan()
    d = plan.to_dict()
    assert "support_models" in d


def test_06_route_plan_to_dict_has_route_reason():
    plan = _make_route_plan()
    d = plan.to_dict()
    assert "route_reason" in d


def test_07_route_plan_primary_model_has_model_id():
    plan = _make_route_plan()
    d = plan.to_dict()
    if d["primary_model"] is not None:
        assert "model_id" in d["primary_model"]


def test_08_route_plan_primary_model_has_native_multimodal():
    plan = _make_route_plan()
    d = plan.to_dict()
    if d["primary_model"] is not None:
        assert "native_multimodal" in d["primary_model"]


# ---------------------------------------------------------------------------
# 9-12: RuntimeProjection routing_authority field
# ---------------------------------------------------------------------------


def test_09_build_runtime_projection_with_route_plan_sets_canonical_authority():
    from core.model_topology.topology_router import CANONICAL_ROUTING_AUTHORITY
    from core.projection.projection_compiler import build_runtime_projection

    state = _make_continuum_state()
    plan = _make_route_plan()
    proj = build_runtime_projection(state, route_plan=plan)
    assert proj.routing_authority == CANONICAL_ROUTING_AUTHORITY


def test_10_build_runtime_projection_without_route_plan_sets_none_authority():
    from core.projection.projection_compiler import build_runtime_projection

    state = _make_continuum_state()
    proj = build_runtime_projection(state)
    assert proj.routing_authority == "none"


def test_11_runtime_projection_routing_authority_field_exists():
    from core.projection.runtime_projection import RuntimeProjection
    from core.continuum.types import TriStatePhase

    proj = RuntimeProjection(tri_state_phase=TriStatePhase.SILENT)
    assert hasattr(proj, "routing_authority")
    assert proj.routing_authority == "none"


def test_12_runtime_projection_to_dict_includes_routing_authority():
    from core.continuum.types import TriStatePhase
    from core.projection.runtime_projection import RuntimeProjection

    proj = RuntimeProjection(tri_state_phase=TriStatePhase.SILENT)
    d = proj.to_dict()
    assert "routing_authority" in d


# ---------------------------------------------------------------------------
# 13-14: ModelRoutingProjection.routing_authority_source field
# ---------------------------------------------------------------------------


def test_13_model_routing_projection_has_routing_authority_source():
    from contracts.desktop_status_projection import ModelRoutingProjection

    mrp = ModelRoutingProjection()
    assert hasattr(mrp, "routing_authority_source")


def test_14_model_routing_projection_default_source_is_none():
    from contracts.desktop_status_projection import ModelRoutingProjection

    mrp = ModelRoutingProjection()
    assert mrp.routing_authority_source == "none"


# ---------------------------------------------------------------------------
# 15-32: _build_model_routing_projection source priority logic
# ---------------------------------------------------------------------------


def _mrp(ucp):
    """Call the internal builder directly via the public contract module."""
    from contracts.desktop_status_projection import _build_model_routing_projection

    return _build_model_routing_projection(ucp)


def test_15_topology_route_plan_sets_source_to_topology_router():
    ucp = {
        "topology_route_plan": {
            "primary_model": {"model_id": "gpt-4o", "native_multimodal": True},
            "support_models": [],
            "route_reason": "top-ranked model",
        }
    }
    mrp = _mrp(ucp)
    assert mrp.routing_authority_source == "topology_router"


def test_16_no_topology_route_plan_falls_back_to_legacy():
    ucp = {"chosen_model": "gpt-4", "chosen_provider": "openai"}
    mrp = _mrp(ucp)
    assert mrp.routing_authority_source == "legacy_ucp_keys"


def test_17_legacy_path_sets_source_to_legacy_ucp_keys():
    ucp = {"chosen_provider": "anthropic", "chosen_model": "claude-3"}
    mrp = _mrp(ucp)
    assert mrp.routing_authority_source == "legacy_ucp_keys"


def test_18_empty_ucp_sets_source_to_none():
    mrp = _mrp({})
    assert mrp.routing_authority_source == "none"


def test_19_topology_plan_primary_model_id_used_as_selected_model():
    ucp = {
        "topology_route_plan": {
            "primary_model": {"model_id": "gpt-4o", "native_multimodal": False},
            "support_models": [],
            "route_reason": "test",
        }
    }
    mrp = _mrp(ucp)
    assert mrp.selected_model == "gpt-4o"


def test_20_topology_plan_native_multimodal_used():
    ucp = {
        "topology_route_plan": {
            "primary_model": {"model_id": "gemini-1.5-pro", "native_multimodal": True},
            "support_models": [],
            "route_reason": "test",
        }
    }
    mrp = _mrp(ucp)
    assert mrp.is_native_multimodal is True


def test_21_topology_plan_route_reason_used():
    ucp = {
        "topology_route_plan": {
            "primary_model": {"model_id": "gpt-4o", "native_multimodal": False},
            "support_models": [],
            "route_reason": "canonical reason from topology",
        }
    }
    mrp = _mrp(ucp)
    assert mrp.route_reason == "canonical reason from topology"


def test_22_topology_plan_support_models_produce_hints():
    ucp = {
        "topology_route_plan": {
            "primary_model": {"model_id": "gpt-4o", "native_multimodal": False},
            "support_models": [
                {"model_id": "claude-3", "native_multimodal": False},
                {"model_id": "gemini-pro", "native_multimodal": True},
            ],
            "route_reason": "test",
        }
    }
    mrp = _mrp(ucp)
    assert "claude-3" in mrp.support_model_hints
    assert "gemini-pro" in mrp.support_model_hints


def test_23_legacy_chosen_model_used_without_topology_plan():
    ucp = {"chosen_model": "gpt-3.5-turbo"}
    mrp = _mrp(ucp)
    assert mrp.selected_model == "gpt-3.5-turbo"


def test_24_legacy_chosen_provider_used_without_topology_plan():
    ucp = {"chosen_provider": "openai", "chosen_model": "gpt-4"}
    mrp = _mrp(ucp)
    assert mrp.selected_provider == "openai"


def test_25_legacy_multimodal_route_used_without_topology_plan():
    ucp = {
        "multimodal_route": {
            "selected_model": "gemini-1.5-flash",
            "selected_provider": "google",
            "is_native_multimodal": True,
            "route_reason": "native mm route",
        }
    }
    mrp = _mrp(ucp)
    assert mrp.selected_model == "gemini-1.5-flash"
    assert mrp.selected_provider == "google"
    assert mrp.is_native_multimodal is True
    assert mrp.routing_authority_source == "legacy_ucp_keys"


def test_26_topology_plan_overrides_legacy_chosen_model():
    ucp = {
        "chosen_model": "legacy-model",
        "topology_route_plan": {
            "primary_model": {"model_id": "canonical-model", "native_multimodal": False},
            "support_models": [],
            "route_reason": "canonical",
        },
    }
    mrp = _mrp(ucp)
    assert mrp.selected_model == "canonical-model"


def test_27_topology_plan_overrides_legacy_chosen_provider():
    ucp = {
        "chosen_provider": "legacy-provider",
        "topology_route_plan": {
            "primary_model": {"model_id": "gpt-4o", "native_multimodal": False},
            "support_models": [],
            "route_reason": "canonical",
        },
    }
    mrp = _mrp(ucp)
    # Provider from topology_route_plan path: None (not present in to_dict)
    assert mrp.routing_authority_source == "topology_router"
    # Legacy chosen_provider must NOT be used when topology plan is present
    assert mrp.selected_provider is None


def test_28_topology_plan_overrides_multimodal_route_block():
    ucp = {
        "multimodal_route": {
            "selected_model": "legacy-mm-model",
            "is_native_multimodal": False,
            "route_reason": "legacy reason",
        },
        "topology_route_plan": {
            "primary_model": {"model_id": "canonical-mm-model", "native_multimodal": True},
            "support_models": [],
            "route_reason": "canonical reason",
        },
    }
    mrp = _mrp(ucp)
    assert mrp.selected_model == "canonical-mm-model"
    assert mrp.is_native_multimodal is True
    assert mrp.route_reason == "canonical reason"
    assert mrp.routing_authority_source == "topology_router"


def test_29_build_desktop_status_projection_canonical_model_routing():
    from contracts.desktop_status_projection import build_desktop_status_projection

    ucp = {
        "topology_route_plan": {
            "primary_model": {"model_id": "gpt-4o", "native_multimodal": False},
            "support_models": [],
            "route_reason": "canonical routing",
        }
    }
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    assert proj.model_routing.selected_model == "gpt-4o"


def test_30_build_desktop_status_projection_authority_source_topology_router():
    from contracts.desktop_status_projection import build_desktop_status_projection

    ucp = {
        "topology_route_plan": {
            "primary_model": {"model_id": "gpt-4o", "native_multimodal": False},
            "support_models": [],
            "route_reason": "test",
        }
    }
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    assert proj.model_routing.routing_authority_source == "topology_router"


def test_31_build_desktop_status_projection_authority_source_legacy():
    from contracts.desktop_status_projection import build_desktop_status_projection

    ucp = {"chosen_model": "gpt-4", "chosen_provider": "openai"}
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    assert proj.model_routing.routing_authority_source == "legacy_ucp_keys"


def test_32_build_desktop_status_projection_authority_source_none_on_empty():
    from contracts.desktop_status_projection import build_desktop_status_projection

    proj = build_desktop_status_projection(unified_control_plan={})
    assert proj.model_routing.routing_authority_source == "none"


def test_33_model_routing_to_dict_includes_routing_authority_source():
    from contracts.desktop_status_projection import ModelRoutingProjection

    mrp = ModelRoutingProjection(routing_authority_source="topology_router")
    d = mrp.to_dict()
    assert "routing_authority_source" in d
    assert d["routing_authority_source"] == "topology_router"


# ---------------------------------------------------------------------------
# 34-46: Legacy path registry entries
# ---------------------------------------------------------------------------


def test_34_multi_llm_router_in_legacy_registry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    assert "core.multi_llm_router.MultiLLMRouter" in LEGACY_PATH_REGISTRY


def test_35_multi_llm_router_module_in_legacy_registry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    assert "core.multi_llm_router" in LEGACY_PATH_REGISTRY


def test_36_dashboard_llm_providers_in_legacy_registry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    assert "dashboard.backend.main.llm_providers" in LEGACY_PATH_REGISTRY


def test_37_multi_llm_router_status_is_legacy_compatibility():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY, LegacyPathStatus

    entry = LEGACY_PATH_REGISTRY["core.multi_llm_router.MultiLLMRouter"]
    assert entry.status == LegacyPathStatus.LEGACY_COMPATIBILITY


def test_38_multi_llm_router_module_status_is_legacy_compatibility():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY, LegacyPathStatus

    entry = LEGACY_PATH_REGISTRY["core.multi_llm_router"]
    assert entry.status == LegacyPathStatus.LEGACY_COMPATIBILITY


def test_39_dashboard_llm_providers_status_is_legacy_compatibility():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY, LegacyPathStatus

    entry = LEGACY_PATH_REGISTRY["dashboard.backend.main.llm_providers"]
    assert entry.status == LegacyPathStatus.LEGACY_COMPATIBILITY


def test_40_multi_llm_router_pr_guardrail_is_routing_authority():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    entry = LEGACY_PATH_REGISTRY["core.multi_llm_router.MultiLLMRouter"]
    assert entry.pr_guardrail_added == "PR-routing-authority"


def test_41_legacy_registry_has_three_routing_authority_entries():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    count = sum(
        1
        for e in LEGACY_PATH_REGISTRY.values()
        if e.pr_guardrail_added == "PR-routing-authority"
    )
    assert count >= 3


def test_42_is_legacy_path_true_for_multi_llm_router():
    from core.orchestration_authority.legacy_paths import is_legacy_path

    assert is_legacy_path("core.multi_llm_router.MultiLLMRouter") is True


def test_43_is_legacy_path_true_for_multi_llm_router_module():
    from core.orchestration_authority.legacy_paths import is_legacy_path

    assert is_legacy_path("core.multi_llm_router") is True


def test_44_is_legacy_path_true_for_dashboard_llm_providers():
    from core.orchestration_authority.legacy_paths import is_legacy_path

    assert is_legacy_path("dashboard.backend.main.llm_providers") is True


def test_45_classify_path_status_returns_legacy_for_multi_llm_router():
    from core.orchestration_authority.legacy_paths import LegacyPathStatus, classify_path_status

    status = classify_path_status("core.multi_llm_router.MultiLLMRouter")
    assert status == LegacyPathStatus.LEGACY_COMPATIBILITY


def test_46_emit_legacy_guardrail_does_not_raise():
    from core.orchestration_authority.legacy_paths import emit_legacy_guardrail

    # Should not raise
    emit_legacy_guardrail("core.multi_llm_router.MultiLLMRouter", trace_id="test-trace")


# ---------------------------------------------------------------------------
# 47-54: docs/MODEL_ROUTING_AUTHORITY.md presence and content
# ---------------------------------------------------------------------------


def _doc_path():
    return os.path.join(_REPO_ROOT, "docs", "MODEL_ROUTING_AUTHORITY.md")


def test_47_routing_authority_doc_exists():
    assert os.path.isfile(_doc_path()), "docs/MODEL_ROUTING_AUTHORITY.md must exist"


def _doc_content():
    with open(_doc_path(), encoding="utf-8") as fh:
        return fh.read()


def test_48_doc_mentions_topology_router():
    assert "TopologyRouter" in _doc_content()


def test_49_doc_mentions_topology_route_plan():
    assert "TopologyRoutePlan" in _doc_content()


def test_50_doc_mentions_runtime_projection():
    assert "RuntimeProjection" in _doc_content()


def test_51_doc_mentions_desktop_status_projection():
    assert "DesktopStatusProjection" in _doc_content()


def test_52_doc_mentions_canonical_routing_authority_sentinel():
    assert "CANONICAL_ROUTING_AUTHORITY" in _doc_content()


def test_53_doc_mentions_legacy_ucp_keys():
    assert "legacy_ucp_keys" in _doc_content()


def test_54_doc_mentions_multi_llm_router():
    assert "MultiLLMRouter" in _doc_content()


# ---------------------------------------------------------------------------
# 55-60: Edge cases
# ---------------------------------------------------------------------------


def test_55_topology_plan_with_no_primary_model_sets_topology_authority():
    ucp = {
        "topology_route_plan": {
            "primary_model": None,
            "support_models": [],
            "route_reason": "no primary available",
        }
    }
    mrp = _mrp(ucp)
    assert mrp.routing_authority_source == "topology_router"
    assert mrp.selected_model is None


def test_56_support_model_hints_filtered_to_non_none_ids():
    ucp = {
        "topology_route_plan": {
            "primary_model": {"model_id": "gpt-4o", "native_multimodal": False},
            "support_models": [
                {"model_id": "claude-3", "native_multimodal": False},
                {"model_id": None},
                {"other_key": "irrelevant"},
            ],
            "route_reason": "test",
        }
    }
    mrp = _mrp(ucp)
    assert "claude-3" in mrp.support_model_hints
    # None model_id should not appear in hints
    assert None not in mrp.support_model_hints


def test_57_topology_plan_empty_dict_still_activates_canonical_path():
    """An empty topology_route_plan dict activates canonical path (key present)."""
    ucp = {
        "topology_route_plan": {},
        "chosen_model": "should-not-be-used",
    }
    mrp = _mrp(ucp)
    assert mrp.routing_authority_source == "topology_router"
    # Legacy chosen_model must NOT be used
    assert mrp.selected_model is None


def test_58_legacy_path_not_active_when_topology_plan_present():
    """Ensure legacy UCP keys are not consulted when topology_route_plan is present."""
    ucp = {
        "topology_route_plan": {
            "primary_model": {"model_id": "canonical-gpt", "native_multimodal": False},
            "support_models": [],
            "route_reason": "canonical",
        },
        "chosen_model": "should-be-ignored",
        "chosen_provider": "should-be-ignored",
        "multimodal_route": {
            "selected_model": "should-be-ignored",
            "route_reason": "should-be-ignored",
        },
    }
    mrp = _mrp(ucp)
    assert mrp.selected_model == "canonical-gpt"
    assert mrp.routing_authority_source == "topology_router"


def test_59_runtime_projection_routing_authority_in_to_dict_after_route_plan():
    from core.model_topology.topology_router import CANONICAL_ROUTING_AUTHORITY
    from core.projection.projection_compiler import build_runtime_projection

    state = _make_continuum_state()
    plan = _make_route_plan()
    proj = build_runtime_projection(state, route_plan=plan)
    d = proj.to_dict()
    assert d["routing_authority"] == CANONICAL_ROUTING_AUTHORITY


def test_60_desktop_status_projection_to_dict_includes_routing_authority_source():
    from contracts.desktop_status_projection import build_desktop_status_projection

    ucp = {
        "topology_route_plan": {
            "primary_model": {"model_id": "gpt-4o", "native_multimodal": True},
            "support_models": [],
            "route_reason": "topology driven",
        }
    }
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    d = proj.to_dict()
    assert d["model_routing"]["routing_authority_source"] == "topology_router"
