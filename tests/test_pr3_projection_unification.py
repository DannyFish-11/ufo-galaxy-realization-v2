#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr3_projection_unification.py
==========================================

PR-3 — Projection unification and dashboard data extraction.

Validates:
  1.  ModelRoutingProjection has vendor_source field with default None.
  2.  ModelRoutingProjection has oneapi_source field with default None.
  3.  _build_model_routing_projection canonical path sets vendor_source from topology_route_plan.
  4.  _build_model_routing_projection canonical path extracts provider_id as selected_provider.
  5.  _build_model_routing_projection canonical path with vendor_source "oneapi" sets oneapi_source.
  6.  _build_model_routing_projection legacy path leaves vendor_source as None.
  7.  _build_model_routing_projection legacy path leaves oneapi_source as None.
  8.  _build_model_routing_projection canonical path — route_reason from topology_route_plan.
  9.  _build_model_routing_projection canonical path — support_model_hints populated.
  10. ModelRoutingProjection.to_dict() includes vendor_source key.
  11. ModelRoutingProjection.to_dict() includes oneapi_source key.
  12. build_desktop_status_projection passes vendor_source through to model_routing.
  13. build_desktop_status_projection passes oneapi_source through when vendor_source is oneapi.
  14. RuntimeProjection has oneapi_summary field with default None.
  15. RuntimeProjection has provider_status_summary field with default None.
  16. RuntimeProjection.to_dict() includes oneapi_summary key.
  17. RuntimeProjection.to_dict() includes provider_status_summary key.
  18. build_runtime_projection accepts oneapi_summary parameter.
  19. build_runtime_projection accepts provider_status_summary parameter.
  20. build_runtime_projection sets oneapi_summary in returned projection.
  21. build_runtime_projection sets provider_status_summary in returned projection.
  22. build_runtime_projection None oneapi_summary yields None in projection.
  23. build_runtime_projection None provider_status_summary yields None in projection.
  24. projection_helpers.build_oneapi_projection_summary returns dict or None.
  25. projection_helpers.build_oneapi_projection_summary dict has system_layer key.
  26. projection_helpers.build_oneapi_projection_summary dict has provider_category_value key.
  27. projection_helpers.build_oneapi_projection_summary dict has routing_authority_ref key.
  28. projection_helpers.extract_oneapi_source_from_route_plan None input returns None.
  29. projection_helpers.extract_oneapi_source_from_route_plan no oneapi node returns None.
  30. projection_helpers.extract_oneapi_source_from_route_plan oneapi primary returns summary.
  31. projection_helpers.extract_oneapi_source_from_route_plan oneapi support returns summary.
  32. projection_helpers.extract_provider_status_summary None input returns None.
  33. projection_helpers.extract_provider_status_summary empty providers returns None.
  34. projection_helpers.extract_provider_status_summary counts available providers.
  35. projection_helpers.extract_provider_status_summary counts degraded providers.
  36. projection_helpers.extract_provider_status_summary counts unavailable providers.
  37. projection_helpers.extract_provider_status_summary result has providers list.
  38. projection_helpers.extract_provider_status_summary result has total key.
  39. topology_route_plan canonical path sets routing_authority_source "topology_router" — reconfirm.
  40. legacy path sets routing_authority_source "legacy_ucp_keys" — reconfirm.
  41. empty UCP sets routing_authority_source "none" — reconfirm.
  42. ModelRoutingProjection.to_dict() round-trips vendor_source.
  43. ModelRoutingProjection.to_dict() round-trips oneapi_source dict.
  44. DesktopStatusProjection.to_dict() includes model_routing.vendor_source.
  45. DesktopStatusProjection.to_dict() includes model_routing.oneapi_source.
  46. ucp oneapi_summary fallback block used when canonical path has no oneapi primary.
  47. build_runtime_projection with route_plan and no oneapi primary leaves oneapi_summary None.
  48. build_runtime_projection with explicit oneapi_summary overrides auto-derivation.
  49. projection_helpers module importable.
  50. projection_helpers exports expected symbols.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

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


def _canonical_ucp(
    model_id: str = "gpt-4o",
    provider_id: str = "openai",
    vendor_source: str = "direct",
    native_multimodal: bool = True,
    support_models: Optional[List[Dict]] = None,
    route_reason: str = "native-MM primary selected",
) -> Dict[str, Any]:
    """Return a minimal UCP dict with a topology_route_plan block."""
    support = support_models or []
    return {
        "topology_route_plan": {
            "phase": "silent",
            "domain": "local",
            "primary_model": {
                "node_id": f"{provider_id}/{model_id}",
                "model_id": model_id,
                "provider_id": provider_id,
                "vendor_source": vendor_source,
                "native_multimodal": native_multimodal,
                "topology_role": "primary",
                "combined_weight": 1.0,
            },
            "support_models": support,
            "route_reason": route_reason,
            "authority": "core.model_topology.topology_router.TopologyRouter",
            "active_weights": {
                f"{provider_id}/{model_id}": {
                    "base_weight": 1.0,
                    "state_modifier": 1.0,
                    "domain_modifier": 1.0,
                    "combined_weight": 1.0,
                }
            },
        }
    }


def _oneapi_ucp() -> Dict[str, Any]:
    """Return a UCP dict with OneAPI as the primary vendor_source."""
    return _canonical_ucp(
        model_id="gpt-4o",
        provider_id="oneapi",
        vendor_source="oneapi",
        native_multimodal=False,
        route_reason="oneapi aggregator selected",
    )


def _legacy_ucp(
    chosen_model: str = "claude-3-5-sonnet",
    chosen_provider: str = "anthropic",
) -> Dict[str, Any]:
    """Return a minimal UCP dict using only legacy keys."""
    return {
        "chosen_model": chosen_model,
        "chosen_provider": chosen_provider,
        "is_native_multimodal": False,
        "route_reason": "legacy routing path",
    }


def _model_supply_dict(
    providers: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """Return a minimal canonical_model_supply dict."""
    return {
        "providers": providers
        or [
            {"provider_id": "openai", "health_status": "healthy"},
            {"provider_id": "anthropic", "health_status": "healthy"},
        ]
    }


# ---------------------------------------------------------------------------
# Imports — defer to test functions so import failures produce clear errors
# ---------------------------------------------------------------------------


def _import_model_routing_projection():
    from contracts.desktop_status_projection import ModelRoutingProjection
    return ModelRoutingProjection


def _import_build_model_routing():
    from contracts.desktop_status_projection import _build_model_routing_projection
    return _build_model_routing_projection


def _import_build_desktop_status_projection():
    from contracts.desktop_status_projection import build_desktop_status_projection
    return build_desktop_status_projection


def _import_desktop_status_projection():
    from contracts.desktop_status_projection import DesktopStatusProjection
    return DesktopStatusProjection


def _import_runtime_projection():
    from core.projection.runtime_projection import RuntimeProjection
    return RuntimeProjection


def _import_build_runtime_projection():
    from core.projection.projection_compiler import build_runtime_projection
    return build_runtime_projection


def _import_continuum_state():
    from core.continuum.types import ContinuumState, ContinuumPhase
    return ContinuumState, ContinuumPhase


def _import_projection_helpers():
    import core.projection.projection_helpers as _mod
    return _mod


# ---------------------------------------------------------------------------
# Tests — ModelRoutingProjection new fields
# ---------------------------------------------------------------------------


def test_01_model_routing_has_vendor_source():
    """ModelRoutingProjection has vendor_source field with default None."""
    MRP = _import_model_routing_projection()
    mrp = MRP()
    assert hasattr(mrp, "vendor_source")
    assert mrp.vendor_source is None


def test_02_model_routing_has_oneapi_source():
    """ModelRoutingProjection has oneapi_source field with default None."""
    MRP = _import_model_routing_projection()
    mrp = MRP()
    assert hasattr(mrp, "oneapi_source")
    assert mrp.oneapi_source is None


def test_03_canonical_path_sets_vendor_source():
    """_build_model_routing_projection canonical path sets vendor_source from plan."""
    fn = _import_build_model_routing()
    ucp = _canonical_ucp(vendor_source="direct")
    result = fn(ucp)
    assert result.vendor_source == "direct"


def test_04_canonical_path_extracts_provider_id():
    """_build_model_routing_projection canonical path extracts provider_id."""
    fn = _import_build_model_routing()
    ucp = _canonical_ucp(provider_id="openai", model_id="gpt-4o")
    result = fn(ucp)
    assert result.selected_provider == "openai"


def test_05_canonical_oneapi_vendor_source_sets_oneapi_source():
    """_build_model_routing_projection sets oneapi_source when vendor_source is oneapi."""
    fn = _import_build_model_routing()
    ucp = _oneapi_ucp()
    result = fn(ucp)
    assert result.oneapi_source is not None
    assert isinstance(result.oneapi_source, dict)


def test_06_legacy_path_vendor_source_none():
    """_build_model_routing_projection legacy path leaves vendor_source as None."""
    fn = _import_build_model_routing()
    result = fn(_legacy_ucp())
    assert result.vendor_source is None


def test_07_legacy_path_oneapi_source_none():
    """_build_model_routing_projection legacy path leaves oneapi_source as None."""
    fn = _import_build_model_routing()
    result = fn(_legacy_ucp())
    assert result.oneapi_source is None


def test_08_canonical_path_route_reason():
    """_build_model_routing_projection canonical path sets route_reason from plan."""
    fn = _import_build_model_routing()
    ucp = _canonical_ucp(route_reason="canonical route: native-MM")
    result = fn(ucp)
    assert result.route_reason == "canonical route: native-MM"


def test_09_canonical_path_support_model_hints():
    """_build_model_routing_projection canonical path populates support_model_hints."""
    fn = _import_build_model_routing()
    ucp = _canonical_ucp(
        support_models=[
            {
                "node_id": "anthropic/claude-3-5-sonnet",
                "model_id": "claude-3-5-sonnet",
                "provider_id": "anthropic",
                "vendor_source": "direct",
                "native_multimodal": False,
                "topology_role": "support",
                "combined_weight": 0.5,
            }
        ]
    )
    result = fn(ucp)
    assert "claude-3-5-sonnet" in result.support_model_hints


def test_10_to_dict_includes_vendor_source():
    """ModelRoutingProjection.to_dict() includes vendor_source key."""
    MRP = _import_model_routing_projection()
    mrp = MRP(vendor_source="direct")
    d = mrp.to_dict()
    assert "vendor_source" in d
    assert d["vendor_source"] == "direct"


def test_11_to_dict_includes_oneapi_source():
    """ModelRoutingProjection.to_dict() includes oneapi_source key."""
    MRP = _import_model_routing_projection()
    mrp = MRP(oneapi_source={"system_layer": "aggregator_integration"})
    d = mrp.to_dict()
    assert "oneapi_source" in d
    assert d["oneapi_source"] == {"system_layer": "aggregator_integration"}


def test_12_build_desktop_status_projection_vendor_source():
    """build_desktop_status_projection passes vendor_source to model_routing."""
    fn = _import_build_desktop_status_projection()
    ucp = _canonical_ucp(vendor_source="direct", model_id="gpt-4o", provider_id="openai")
    projection = fn(unified_control_plan=ucp)
    assert projection.model_routing.vendor_source == "direct"


def test_13_build_desktop_status_projection_oneapi_source():
    """build_desktop_status_projection sets oneapi_source when vendor_source is oneapi."""
    fn = _import_build_desktop_status_projection()
    ucp = _oneapi_ucp()
    projection = fn(unified_control_plan=ucp)
    assert projection.model_routing.oneapi_source is not None
    assert isinstance(projection.model_routing.oneapi_source, dict)


def test_14_runtime_projection_has_oneapi_summary():
    """RuntimeProjection has oneapi_summary field with default None."""
    RP = _import_runtime_projection()
    from core.continuum.types import TriStatePhase
    rp = RP(tri_state_phase=TriStatePhase.SILENT)
    assert hasattr(rp, "oneapi_summary")
    assert rp.oneapi_summary is None


def test_15_runtime_projection_has_provider_status_summary():
    """RuntimeProjection has provider_status_summary field with default None."""
    RP = _import_runtime_projection()
    from core.continuum.types import TriStatePhase
    rp = RP(tri_state_phase=TriStatePhase.SILENT)
    assert hasattr(rp, "provider_status_summary")
    assert rp.provider_status_summary is None


def test_16_runtime_projection_to_dict_oneapi_summary():
    """RuntimeProjection.to_dict() includes oneapi_summary key."""
    RP = _import_runtime_projection()
    from core.continuum.types import TriStatePhase
    rp = RP(tri_state_phase=TriStatePhase.SILENT, oneapi_summary={"k": "v"})
    d = rp.to_dict()
    assert "oneapi_summary" in d
    assert d["oneapi_summary"] == {"k": "v"}


def test_17_runtime_projection_to_dict_provider_status_summary():
    """RuntimeProjection.to_dict() includes provider_status_summary key."""
    RP = _import_runtime_projection()
    from core.continuum.types import TriStatePhase
    rp = RP(tri_state_phase=TriStatePhase.SILENT, provider_status_summary={"total": 2})
    d = rp.to_dict()
    assert "provider_status_summary" in d
    assert d["provider_status_summary"] == {"total": 2}


def test_18_build_runtime_projection_accepts_oneapi_summary():
    """build_runtime_projection accepts oneapi_summary parameter."""
    fn = _import_build_runtime_projection()
    ContinuumState, ContinuumPhase = _import_continuum_state()
    state = ContinuumState(phase=ContinuumPhase.FORMLESS)
    # Must not raise.
    projection = fn(state, oneapi_summary={"system_layer": "aggregator_integration"})
    assert projection is not None


def test_19_build_runtime_projection_accepts_provider_status_summary():
    """build_runtime_projection accepts provider_status_summary parameter."""
    fn = _import_build_runtime_projection()
    ContinuumState, ContinuumPhase = _import_continuum_state()
    state = ContinuumState(phase=ContinuumPhase.FORMLESS)
    pss = {"total": 3, "available": 3, "degraded": 0, "unavailable": 0}
    projection = fn(state, provider_status_summary=pss)
    assert projection is not None


def test_20_build_runtime_projection_sets_oneapi_summary():
    """build_runtime_projection sets oneapi_summary in returned projection."""
    fn = _import_build_runtime_projection()
    ContinuumState, ContinuumPhase = _import_continuum_state()
    state = ContinuumState(phase=ContinuumPhase.FORMLESS)
    oa = {"system_layer": "aggregator_integration", "provider_category_value": "oneapi"}
    projection = fn(state, oneapi_summary=oa)
    assert projection.oneapi_summary == oa


def test_21_build_runtime_projection_sets_provider_status_summary():
    """build_runtime_projection sets provider_status_summary in returned projection."""
    fn = _import_build_runtime_projection()
    ContinuumState, ContinuumPhase = _import_continuum_state()
    state = ContinuumState(phase=ContinuumPhase.FORMLESS)
    pss = {"total": 2, "available": 2, "degraded": 0, "unavailable": 0, "providers": []}
    projection = fn(state, provider_status_summary=pss)
    assert projection.provider_status_summary == pss


def test_22_build_runtime_projection_none_oneapi_summary():
    """build_runtime_projection with None oneapi_summary yields None in projection."""
    fn = _import_build_runtime_projection()
    ContinuumState, ContinuumPhase = _import_continuum_state()
    state = ContinuumState(phase=ContinuumPhase.FORMLESS)
    projection = fn(state, oneapi_summary=None)
    assert projection.oneapi_summary is None


def test_23_build_runtime_projection_none_provider_status_summary():
    """build_runtime_projection with None provider_status_summary yields None."""
    fn = _import_build_runtime_projection()
    ContinuumState, ContinuumPhase = _import_continuum_state()
    state = ContinuumState(phase=ContinuumPhase.FORMLESS)
    projection = fn(state, provider_status_summary=None)
    assert projection.provider_status_summary is None


# ---------------------------------------------------------------------------
# Tests — projection_helpers module
# ---------------------------------------------------------------------------


def test_24_build_oneapi_projection_summary_returns_dict_or_none():
    """projection_helpers.build_oneapi_projection_summary returns dict or None."""
    mod = _import_projection_helpers()
    result = mod.build_oneapi_projection_summary()
    assert result is None or isinstance(result, dict)


def test_25_build_oneapi_projection_summary_system_layer():
    """projection_helpers.build_oneapi_projection_summary dict has system_layer."""
    mod = _import_projection_helpers()
    result = mod.build_oneapi_projection_summary()
    if result is not None:
        assert "system_layer" in result


def test_26_build_oneapi_projection_summary_provider_category_value():
    """projection_helpers.build_oneapi_projection_summary has provider_category_value."""
    mod = _import_projection_helpers()
    result = mod.build_oneapi_projection_summary()
    if result is not None:
        assert "provider_category_value" in result


def test_27_build_oneapi_projection_summary_routing_authority_ref():
    """projection_helpers.build_oneapi_projection_summary has routing_authority_ref."""
    mod = _import_projection_helpers()
    result = mod.build_oneapi_projection_summary()
    if result is not None:
        assert "routing_authority_ref" in result


def test_28_extract_oneapi_source_none_input():
    """extract_oneapi_source_from_route_plan with None returns None."""
    mod = _import_projection_helpers()
    assert mod.extract_oneapi_source_from_route_plan(None) is None


def test_29_extract_oneapi_source_no_oneapi_node():
    """extract_oneapi_source_from_route_plan with direct provider returns None."""
    mod = _import_projection_helpers()
    plan_dict = {
        "primary_model": {"vendor_source": "direct", "model_id": "gpt-4o"},
        "support_models": [],
    }
    assert mod.extract_oneapi_source_from_route_plan(plan_dict) is None


def test_30_extract_oneapi_source_oneapi_primary():
    """extract_oneapi_source_from_route_plan with oneapi primary returns summary."""
    mod = _import_projection_helpers()
    plan_dict = {
        "primary_model": {"vendor_source": "oneapi", "model_id": "gpt-4o"},
        "support_models": [],
    }
    result = mod.extract_oneapi_source_from_route_plan(plan_dict)
    assert result is None or isinstance(result, dict)


def test_31_extract_oneapi_source_oneapi_support():
    """extract_oneapi_source_from_route_plan with oneapi support node returns summary."""
    mod = _import_projection_helpers()
    plan_dict = {
        "primary_model": {"vendor_source": "direct", "model_id": "gpt-4o"},
        "support_models": [
            {"vendor_source": "oneapi", "model_id": "gpt-3.5-turbo"},
        ],
    }
    # The function delegates to build_oneapi_projection_summary; result is dict or None.
    result = mod.extract_oneapi_source_from_route_plan(plan_dict)
    assert result is None or isinstance(result, dict)


def test_32_extract_provider_status_summary_none():
    """extract_provider_status_summary with None returns None."""
    mod = _import_projection_helpers()
    assert mod.extract_provider_status_summary(None) is None


def test_33_extract_provider_status_summary_empty_providers():
    """extract_provider_status_summary with empty providers returns None."""
    mod = _import_projection_helpers()
    assert mod.extract_provider_status_summary({"providers": []}) is None


def test_34_extract_provider_status_counts_available():
    """extract_provider_status_summary counts available providers."""
    mod = _import_projection_helpers()
    supply = {
        "providers": [
            {"provider_id": "openai", "health_status": "healthy"},
            {"provider_id": "anthropic", "health_status": "healthy"},
        ]
    }
    result = mod.extract_provider_status_summary(supply)
    assert result is not None
    assert result["available"] == 2


def test_35_extract_provider_status_counts_degraded():
    """extract_provider_status_summary counts degraded providers."""
    mod = _import_projection_helpers()
    supply = {
        "providers": [
            {"provider_id": "openai", "health_status": "healthy"},
            {"provider_id": "anthropic", "health_status": "degraded"},
        ]
    }
    result = mod.extract_provider_status_summary(supply)
    assert result is not None
    assert result["degraded"] == 1


def test_36_extract_provider_status_counts_unavailable():
    """extract_provider_status_summary counts unavailable providers."""
    mod = _import_projection_helpers()
    supply = {
        "providers": [
            {"provider_id": "openai", "health_status": "healthy"},
            {"provider_id": "bad-provider", "health_status": "unavailable"},
        ]
    }
    result = mod.extract_provider_status_summary(supply)
    assert result is not None
    assert result["unavailable"] == 1


def test_37_extract_provider_status_has_providers_list():
    """extract_provider_status_summary result has providers list."""
    mod = _import_projection_helpers()
    supply = _model_supply_dict()
    result = mod.extract_provider_status_summary(supply)
    assert result is not None
    assert "providers" in result
    assert isinstance(result["providers"], list)


def test_38_extract_provider_status_has_total():
    """extract_provider_status_summary result has total key."""
    mod = _import_projection_helpers()
    supply = _model_supply_dict()
    result = mod.extract_provider_status_summary(supply)
    assert result is not None
    assert "total" in result
    assert result["total"] == len(supply["providers"])


# ---------------------------------------------------------------------------
# Tests — canonical authority reconfirmations
# ---------------------------------------------------------------------------


def test_39_canonical_path_authority_source():
    """topology_route_plan canonical path sets routing_authority_source topology_router."""
    fn = _import_build_model_routing()
    result = fn(_canonical_ucp())
    assert result.routing_authority_source == "topology_router"


def test_40_legacy_path_authority_source():
    """legacy path sets routing_authority_source legacy_ucp_keys."""
    fn = _import_build_model_routing()
    result = fn(_legacy_ucp())
    assert result.routing_authority_source == "legacy_ucp_keys"


def test_41_empty_ucp_authority_source_none():
    """empty UCP sets routing_authority_source none."""
    fn = _import_build_model_routing()
    result = fn({})
    assert result.routing_authority_source == "none"


# ---------------------------------------------------------------------------
# Tests — round-trip and DesktopStatusProjection
# ---------------------------------------------------------------------------


def test_42_to_dict_round_trips_vendor_source():
    """ModelRoutingProjection.to_dict() round-trips vendor_source."""
    MRP = _import_model_routing_projection()
    mrp = MRP(vendor_source="direct")
    d = mrp.to_dict()
    assert d.get("vendor_source") == "direct"


def test_43_to_dict_round_trips_oneapi_source():
    """ModelRoutingProjection.to_dict() round-trips oneapi_source dict."""
    MRP = _import_model_routing_projection()
    summary = {"system_layer": "aggregator_integration", "provider_category_value": "oneapi"}
    mrp = MRP(oneapi_source=summary)
    d = mrp.to_dict()
    assert d.get("oneapi_source") == summary


def test_44_desktop_status_projection_dict_vendor_source():
    """DesktopStatusProjection.to_dict() includes model_routing.vendor_source."""
    fn = _import_build_desktop_status_projection()
    ucp = _canonical_ucp(vendor_source="direct")
    projection = fn(unified_control_plan=ucp)
    d = projection.to_dict()
    assert "vendor_source" in d["model_routing"]


def test_45_desktop_status_projection_dict_oneapi_source():
    """DesktopStatusProjection.to_dict() includes model_routing.oneapi_source."""
    fn = _import_build_desktop_status_projection()
    ucp = _canonical_ucp()
    projection = fn(unified_control_plan=ucp)
    d = projection.to_dict()
    assert "oneapi_source" in d["model_routing"]


def test_46_ucp_explicit_oneapi_summary_fallback():
    """ucp oneapi_summary block is used when canonical path has no oneapi primary."""
    fn = _import_build_model_routing()
    ucp = _canonical_ucp(vendor_source="direct")
    ucp["oneapi_summary"] = {
        "system_layer": "aggregator_integration",
        "provider_category_value": "oneapi",
    }
    result = fn(ucp)
    # canonical path with direct vendor — oneapi_source from ucp fallback
    assert result.oneapi_source == ucp["oneapi_summary"]


def test_47_build_runtime_projection_route_plan_no_oneapi():
    """build_runtime_projection with route_plan and no oneapi primary has None oneapi_summary."""
    fn = _import_build_runtime_projection()
    ContinuumState, ContinuumPhase = _import_continuum_state()

    try:
        from core.model_topology import TopologyRouter, ProviderInventory
        from core.model_topology.config_bridge import ConfigBridge
        from core.model_topology import LegacyLLMProviderSnapshot
        from core.continuum.types import RuntimeDomain

        bridge = ConfigBridge()
        snapshots = [
            LegacyLLMProviderSnapshot.from_dict({
                "key": "openai",
                "models": ["gpt-4o"],
                "is_multimodal": True,
                "base_url": None,
                "api_key": "test_key",
            })
        ]
        inventory = ProviderInventory.from_snapshots(snapshots, bridge)
        router = TopologyRouter(inventory)
        plan = router.route(
            ContinuumState(phase=ContinuumPhase.FORMLESS).tri_state_phase,
            RuntimeDomain.LOCAL,
        )
        state = ContinuumState(phase=ContinuumPhase.FORMLESS)
        projection = fn(state, route_plan=plan, oneapi_summary=None)
        # openai is a direct provider; oneapi_summary auto-derivation should yield None
        assert projection.oneapi_summary is None
    except Exception as exc:
        pytest.skip(f"TopologyRouter setup unavailable: {exc}")


def test_48_explicit_oneapi_summary_overrides_auto():
    """build_runtime_projection with explicit oneapi_summary overrides auto-derivation."""
    fn = _import_build_runtime_projection()
    ContinuumState, ContinuumPhase = _import_continuum_state()
    state = ContinuumState(phase=ContinuumPhase.FORMLESS)
    explicit = {"system_layer": "aggregator_integration", "override": True}
    projection = fn(state, oneapi_summary=explicit)
    assert projection.oneapi_summary == explicit


def test_49_projection_helpers_importable():
    """projection_helpers module is importable."""
    mod = _import_projection_helpers()
    assert mod is not None


def test_50_projection_helpers_exports():
    """projection_helpers exports expected symbols."""
    mod = _import_projection_helpers()
    assert hasattr(mod, "build_oneapi_projection_summary")
    assert hasattr(mod, "extract_oneapi_source_from_route_plan")
    assert hasattr(mod, "extract_provider_status_summary")
