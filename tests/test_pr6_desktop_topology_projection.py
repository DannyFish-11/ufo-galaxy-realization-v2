#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr6_desktop_topology_projection.py
=============================================

PR-6 — Final desktop topology projection delivery after PR-5 merge.

Validates that the canonical desktop topology-ready projection contract is
correctly built, exposes the right structure, and that PR-4 / PR-5 guarantees
are preserved throughout.

Test index:
  1.  TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY importable from contracts.desktop_status_projection.
  2.  TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY is a non-empty string.
  3.  TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY importable from core.projection.projection_compiler.
  4.  TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY is consistent across both modules.
  5.  DesktopTopologyProjection is importable from contracts.desktop_status_projection.
  6.  DesktopTopologyProjection has primary_model_id field.
  7.  DesktopTopologyProjection has primary_provider_id field.
  8.  DesktopTopologyProjection has primary_vendor_source field.
  9.  DesktopTopologyProjection has primary_is_native_multimodal field.
  10. DesktopTopologyProjection has support_model_ids field.
  11. DesktopTopologyProjection has route_reason field.
  12. DesktopTopologyProjection has route_phase field.
  13. DesktopTopologyProjection has route_domain field.
  14. DesktopTopologyProjection has primary_provider_available field.
  15. DesktopTopologyProjection has routing_authority_source field.
  16. DesktopTopologyProjection has canonical_source_present field.
  17. DesktopTopologyProjection has legacy_fallback_active field.
  18. DesktopTopologyProjection has oneapi_integration field.
  19. DesktopTopologyProjection has health_severity field.
  20. DesktopTopologyProjection has contract_authority field.
  21. DesktopStatusProjection has topology_ready field.
  22. DesktopStatusProjection.topology_ready defaults to None.
  23. build_desktop_status_projection with topology_route_plan populates topology_ready.
  24. topology_ready.primary_model_id sourced from canonical topology_route_plan.
  25. topology_ready.primary_provider_id sourced from canonical topology_route_plan.
  26. topology_ready.primary_vendor_source sourced from canonical topology_route_plan.
  27. topology_ready.route_phase sourced from canonical topology_route_plan.
  28. topology_ready.route_domain sourced from canonical topology_route_plan.
  29. topology_ready.route_reason sourced from canonical topology_route_plan.
  30. topology_ready.support_model_ids sourced from canonical topology_route_plan.
  31. topology_ready.canonical_source_present is True on canonical path.
  32. topology_ready.legacy_fallback_active is False on canonical path.
  33. topology_ready.routing_authority_source is 'topology_router' on canonical path.
  34. topology_ready with legacy UCP keys sets legacy_fallback_active=True.
  35. topology_ready with legacy UCP keys sets canonical_source_present=False.
  36. topology_ready with legacy UCP keys sets routing_authority_source='legacy_ucp_keys'.
  37. topology_ready with empty UCP sets routing_authority_source='none'.
  38. topology_ready.oneapi_integration is always present (never None).
  39. topology_ready.oneapi_integration['system_layer'] is 'aggregator_integration'.
  40. topology_ready.oneapi_integration is separate from primary_route fields.
  41. topology_ready.contract_authority equals TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY.
  42. topology_ready.to_dict() includes 'primary_model_id' key.
  43. topology_ready.to_dict() includes 'canonical_source_present' key.
  44. topology_ready.to_dict() includes 'legacy_fallback_active' key.
  45. topology_ready.to_dict() includes 'oneapi_integration' key.
  46. topology_ready.to_dict() includes 'contract_authority' key.
  47. topology_ready has no UI-specific rendering fields (no color/coords/pixel).
  48. PR-5 legacy_routing_fallback_active intact in model_routing after PR-6.
  49. PR-4 oneapi_integration intact in DesktopStatusProjection after PR-6.
  50. docs/SERVER_SIDE_CANONICALIZATION.md mentions PR-6 topology-ready delivery.
"""

from __future__ import annotations

import os
import sys

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _read_file(*parts: str) -> str:
    with open(os.path.join(_REPO_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# ===========================================================================
# 1–4: TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY
# ===========================================================================


def test_01_topology_delivery_authority_importable_from_contracts():
    from contracts.desktop_status_projection import TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY  # noqa: F401


def test_02_topology_delivery_authority_is_non_empty_string():
    from contracts.desktop_status_projection import TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY
    assert isinstance(TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY, str)
    assert len(TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY) > 0


def test_03_topology_delivery_authority_importable_from_compiler():
    from core.projection.projection_compiler import TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY  # noqa: F401


def test_04_topology_delivery_authority_consistent_across_modules():
    from contracts.desktop_status_projection import (
        TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY as contracts_auth,
    )
    from core.projection.projection_compiler import (
        TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY as compiler_auth,
    )
    assert contracts_auth == compiler_auth


# ===========================================================================
# 5–20: DesktopTopologyProjection fields
# ===========================================================================


def test_05_desktop_topology_projection_importable():
    from contracts.desktop_status_projection import DesktopTopologyProjection  # noqa: F401


def test_06_has_primary_model_id():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    assert hasattr(DesktopTopologyProjection, "model_fields")
    assert "primary_model_id" in DesktopTopologyProjection.model_fields


def test_07_has_primary_provider_id():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    assert "primary_provider_id" in DesktopTopologyProjection.model_fields


def test_08_has_primary_vendor_source():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    assert "primary_vendor_source" in DesktopTopologyProjection.model_fields


def test_09_has_primary_is_native_multimodal():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    assert "primary_is_native_multimodal" in DesktopTopologyProjection.model_fields


def test_10_has_support_model_ids():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    assert "support_model_ids" in DesktopTopologyProjection.model_fields


def test_11_has_route_reason():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    assert "route_reason" in DesktopTopologyProjection.model_fields


def test_12_has_route_phase():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    assert "route_phase" in DesktopTopologyProjection.model_fields


def test_13_has_route_domain():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    assert "route_domain" in DesktopTopologyProjection.model_fields


def test_14_has_primary_provider_available():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    assert "primary_provider_available" in DesktopTopologyProjection.model_fields


def test_15_has_routing_authority_source():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    assert "routing_authority_source" in DesktopTopologyProjection.model_fields


def test_16_has_canonical_source_present():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    assert "canonical_source_present" in DesktopTopologyProjection.model_fields


def test_17_has_legacy_fallback_active():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    assert "legacy_fallback_active" in DesktopTopologyProjection.model_fields


def test_18_has_oneapi_integration():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    assert "oneapi_integration" in DesktopTopologyProjection.model_fields


def test_19_has_health_severity():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    assert "health_severity" in DesktopTopologyProjection.model_fields


def test_20_has_contract_authority():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    assert "contract_authority" in DesktopTopologyProjection.model_fields


# ===========================================================================
# 21–22: DesktopStatusProjection.topology_ready field
# ===========================================================================


def test_21_desktop_status_projection_has_topology_ready():
    from contracts.desktop_status_projection import DesktopStatusProjection
    assert "topology_ready" in DesktopStatusProjection.model_fields


def test_22_topology_ready_defaults_to_none():
    from contracts.desktop_status_projection import DesktopStatusProjection
    proj = DesktopStatusProjection()
    assert proj.topology_ready is None


# ===========================================================================
# 23–33: Canonical path — topology_route_plan present
# ===========================================================================

_CANONICAL_UCP = {
    "topology_route_plan": {
        "primary_model": {
            "model_id": "gpt-4o",
            "provider_id": "openai",
            "vendor_source": "direct",
            "native_multimodal": True,
        },
        "support_models": [
            {"model_id": "claude-3-5-sonnet", "provider_id": "anthropic", "vendor_source": "direct"},
        ],
        "route_reason": "canonical routing test",
        "phase": "manifest",
        "domain": "local",
        "authority": "core.model_topology.topology_router.TopologyRouter",
    }
}


def test_23_build_with_topology_route_plan_populates_topology_ready():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    assert proj.topology_ready is not None


def test_24_primary_model_id_from_canonical():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    assert proj.topology_ready.primary_model_id == "gpt-4o"


def test_25_primary_provider_id_from_canonical():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    assert proj.topology_ready.primary_provider_id == "openai"


def test_26_primary_vendor_source_from_canonical():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    assert proj.topology_ready.primary_vendor_source == "direct"


def test_27_route_phase_from_canonical():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    assert proj.topology_ready.route_phase == "manifest"


def test_28_route_domain_from_canonical():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    assert proj.topology_ready.route_domain == "local"


def test_29_route_reason_from_canonical():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    assert proj.topology_ready.route_reason == "canonical routing test"


def test_30_support_model_ids_from_canonical():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    assert "claude-3-5-sonnet" in proj.topology_ready.support_model_ids


def test_31_canonical_source_present_true_on_canonical_path():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    assert proj.topology_ready.canonical_source_present is True


def test_32_legacy_fallback_active_false_on_canonical_path():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    assert proj.topology_ready.legacy_fallback_active is False


def test_33_routing_authority_source_topology_router_on_canonical_path():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    assert proj.topology_ready.routing_authority_source == "topology_router"


# ===========================================================================
# 34–37: Legacy fallback path
# ===========================================================================

_LEGACY_UCP = {
    "chosen_model": "gpt-3.5-turbo",
    "chosen_provider": "openai",
    "route_reason": "legacy routing test",
}


def test_34_legacy_ucp_sets_legacy_fallback_active_true():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_LEGACY_UCP)
    assert proj.topology_ready.legacy_fallback_active is True


def test_35_legacy_ucp_sets_canonical_source_present_false():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_LEGACY_UCP)
    assert proj.topology_ready.canonical_source_present is False


def test_36_legacy_ucp_sets_routing_authority_legacy_ucp_keys():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_LEGACY_UCP)
    assert proj.topology_ready.routing_authority_source == "legacy_ucp_keys"


def test_37_empty_ucp_sets_routing_authority_none():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan={})
    assert proj.topology_ready.routing_authority_source == "none"


# ===========================================================================
# 38–40: OneAPI lower-horizon integration block
# ===========================================================================


def test_38_topology_ready_oneapi_integration_always_present():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    assert proj.topology_ready.oneapi_integration is not None


def test_39_topology_ready_oneapi_system_layer_is_aggregator_integration():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    oi = proj.topology_ready.oneapi_integration
    assert oi.get("system_layer") == "aggregator_integration"


def test_40_oneapi_integration_separate_from_primary_route_fields():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    topo = proj.topology_ready
    # OneAPI must not be in primary_model_id or support_model_ids
    assert topo.primary_model_id != "oneapi"
    assert "oneapi" not in (topo.support_model_ids or [])
    assert isinstance(topo.oneapi_integration, dict)


# ===========================================================================
# 41–46: topology_ready.to_dict() serialisation
# ===========================================================================


def test_41_contract_authority_equals_delivery_sentinel():
    from contracts.desktop_status_projection import (
        build_desktop_status_projection,
        TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY,
    )
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    assert proj.topology_ready.contract_authority == TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY


def test_42_to_dict_includes_primary_model_id():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    d = proj.topology_ready.to_dict()
    assert "primary_model_id" in d


def test_43_to_dict_includes_canonical_source_present():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    d = proj.topology_ready.to_dict()
    assert "canonical_source_present" in d


def test_44_to_dict_includes_legacy_fallback_active():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    d = proj.topology_ready.to_dict()
    assert "legacy_fallback_active" in d


def test_45_to_dict_includes_oneapi_integration():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    d = proj.topology_ready.to_dict()
    assert "oneapi_integration" in d


def test_46_to_dict_includes_contract_authority():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    d = proj.topology_ready.to_dict()
    assert "contract_authority" in d


# ===========================================================================
# 47: No UI-specific rendering fields in topology_ready
# ===========================================================================

_UI_HINT_FIELDS = {
    "color",
    "colour",
    "pixel",
    "position",
    "x",
    "y",
    "animation",
    "css",
    "style",
    "icon",
    "badge_color",
    "badge_colour",
    "coord",
    "coords",
    "rgb",
    "hex_color",
    "hex_colour",
}


def test_47_no_ui_specific_rendering_fields_in_topology_ready():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    field_names = set(DesktopTopologyProjection.model_fields.keys())
    ui_fields_found = field_names & _UI_HINT_FIELDS
    assert ui_fields_found == set(), (
        f"UI-specific rendering fields found in DesktopTopologyProjection: {ui_fields_found}"
    )


# ===========================================================================
# 48–49: PR-4 / PR-5 guarantee preservation
# ===========================================================================


def test_48_pr5_legacy_routing_fallback_active_intact_in_model_routing():
    """PR-5 guarantee: legacy_routing_fallback_active still present in model_routing."""
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    assert hasattr(proj.model_routing, "legacy_routing_fallback_active")
    assert proj.model_routing.legacy_routing_fallback_active is False


def test_49_pr4_oneapi_integration_intact_in_desktop_status_projection():
    """PR-4 guarantee: top-level oneapi_integration still present in DesktopStatusProjection."""
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_CANONICAL_UCP)
    assert proj.oneapi_integration is not None
    assert proj.oneapi_integration.get("system_layer") == "aggregator_integration"


# ===========================================================================
# 50: Documentation
# ===========================================================================


def test_50_server_side_canonicalization_doc_mentions_pr6_topology():
    content = _read_file("docs", "SERVER_SIDE_CANONICALIZATION.md")
    assert "PR-6" in content
    assert "topology" in content.lower()
    assert "TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY" in content
    assert "desktop-topology" in content
