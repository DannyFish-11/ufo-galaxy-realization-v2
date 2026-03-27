#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr7_desktop_constellation_consumption_hardening.py
=============================================================

PR-7 — Desktop constellation consumption hardening after PR-6 merge.

Validates that the topology projection readiness/quality semantics are
correctly structured, explicitly distinguish canonical vs degraded vs partial
vs unavailable states, and that downstream consumers are protected from
silently misusing degraded fallback data as authoritative routing truth.

Test index:
  1.  TOPOLOGY_READINESS_CONTRACT_AUTHORITY importable from contracts.desktop_status_projection.
  2.  TOPOLOGY_READINESS_CONTRACT_AUTHORITY is a non-empty string.
  3.  TOPOLOGY_READINESS_CONTRACT_AUTHORITY importable from core.projection.projection_compiler.
  4.  TOPOLOGY_READINESS_CONTRACT_AUTHORITY is consistent across both modules.
  5.  TopologyProjectionReadiness importable from contracts.desktop_status_projection.
  6.  TopologyProjectionReadiness has 'canonical' value.
  7.  TopologyProjectionReadiness has 'degraded' value.
  8.  TopologyProjectionReadiness has 'partial' value.
  9.  TopologyProjectionReadiness has 'unavailable' value.
  10. TopologyProjectionReadiness is a str Enum (values are strings).
  11. TopologyProjectionQualityBlock importable from contracts.desktop_status_projection.
  12. TopologyProjectionQualityBlock has 'readiness' field.
  13. TopologyProjectionQualityBlock has 'authoritative' field.
  14. TopologyProjectionQualityBlock has 'degraded' field.
  15. TopologyProjectionQualityBlock has 'partial' field.
  16. TopologyProjectionQualityBlock has 'quality_note' field.
  17. TopologyProjectionQualityBlock has 'quality_authority' field.
  18. TopologyProjectionQualityBlock.quality_authority defaults to TOPOLOGY_READINESS_CONTRACT_AUTHORITY.
  19. TopologyProjectionQualityBlock.to_dict() returns a dict.
  20. DesktopTopologyProjection has 'projection_quality' field.
  21. DesktopTopologyProjection.projection_quality defaults to None on bare construction.
  22. Canonical route-plan path sets readiness='canonical'.
  23. Canonical route-plan path sets authoritative=True.
  24. Canonical route-plan path sets degraded=False.
  25. Canonical route-plan path sets partial=False.
  26. Legacy fallback path sets readiness='degraded'.
  27. Legacy fallback path sets authoritative=False.
  28. Legacy fallback path sets degraded=True.
  29. Legacy fallback path sets partial=False.
  30. Empty UCP (no routing data) sets readiness='unavailable'.
  31. Empty UCP sets authoritative=False.
  32. Empty UCP sets degraded=False.
  33. Canonical path with provider unavailable sets readiness='partial'.
  34. Canonical path with provider unavailable sets authoritative=False.
  35. Canonical path with provider unavailable sets partial=True.
  36. projection_quality.quality_note is a non-empty string on all paths.
  37. projection_quality.quality_note differs between canonical and degraded.
  38. projection_quality.to_dict() includes 'readiness' key.
  39. projection_quality.to_dict() includes 'authoritative' key.
  40. projection_quality.to_dict() includes 'quality_authority' key.
  41. DesktopTopologyProjection.to_dict() includes 'projection_quality' key.
  42. topology_ready.projection_quality is present (not None) on canonical path.
  43. topology_ready.projection_quality is present (not None) on legacy fallback path.
  44. topology_ready.projection_quality is present (not None) on empty UCP.
  45. PR-6 topology_ready.contract_authority still equals TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY.
  46. PR-6 topology_ready.oneapi_integration remains lower-horizon (system_layer check).
  47. PR-4 oneapi_integration in DesktopStatusProjection preserved after PR-7.
  48. PR-5 legacy_routing_fallback_active in ModelRoutingProjection preserved after PR-7.
  49. _minimal_desktop_topology_fallback payload includes 'projection_quality' key.
  50. docs/SERVER_SIDE_CANONICALIZATION.md mentions PR-7.
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
# 1–4: TOPOLOGY_READINESS_CONTRACT_AUTHORITY sentinel
# ===========================================================================


def test_01_topology_readiness_authority_importable_from_contracts():
    from contracts.desktop_status_projection import TOPOLOGY_READINESS_CONTRACT_AUTHORITY  # noqa: F401


def test_02_topology_readiness_authority_is_non_empty_string():
    from contracts.desktop_status_projection import TOPOLOGY_READINESS_CONTRACT_AUTHORITY
    assert isinstance(TOPOLOGY_READINESS_CONTRACT_AUTHORITY, str)
    assert len(TOPOLOGY_READINESS_CONTRACT_AUTHORITY) > 0


def test_03_topology_readiness_authority_importable_from_compiler():
    from core.projection.projection_compiler import TOPOLOGY_READINESS_CONTRACT_AUTHORITY  # noqa: F401


def test_04_topology_readiness_authority_consistent_across_modules():
    from contracts.desktop_status_projection import TOPOLOGY_READINESS_CONTRACT_AUTHORITY as A
    from core.projection.projection_compiler import TOPOLOGY_READINESS_CONTRACT_AUTHORITY as B
    assert A == B


# ===========================================================================
# 5–10: TopologyProjectionReadiness enum
# ===========================================================================


def test_05_topology_projection_readiness_importable():
    from contracts.desktop_status_projection import TopologyProjectionReadiness  # noqa: F401


def test_06_readiness_has_canonical_value():
    from contracts.desktop_status_projection import TopologyProjectionReadiness
    assert TopologyProjectionReadiness.canonical.value == "canonical"


def test_07_readiness_has_degraded_value():
    from contracts.desktop_status_projection import TopologyProjectionReadiness
    assert TopologyProjectionReadiness.degraded.value == "degraded"


def test_08_readiness_has_partial_value():
    from contracts.desktop_status_projection import TopologyProjectionReadiness
    assert TopologyProjectionReadiness.partial.value == "partial"


def test_09_readiness_has_unavailable_value():
    from contracts.desktop_status_projection import TopologyProjectionReadiness
    assert TopologyProjectionReadiness.unavailable.value == "unavailable"


def test_10_readiness_is_str_enum():
    from contracts.desktop_status_projection import TopologyProjectionReadiness
    for val in TopologyProjectionReadiness:
        assert isinstance(val.value, str)


# ===========================================================================
# 11–19: TopologyProjectionQualityBlock model
# ===========================================================================


def test_11_topology_quality_block_importable():
    from contracts.desktop_status_projection import TopologyProjectionQualityBlock  # noqa: F401


def test_12_quality_block_has_readiness_field():
    from contracts.desktop_status_projection import TopologyProjectionQualityBlock
    assert "readiness" in TopologyProjectionQualityBlock.model_fields


def test_13_quality_block_has_authoritative_field():
    from contracts.desktop_status_projection import TopologyProjectionQualityBlock
    assert "authoritative" in TopologyProjectionQualityBlock.model_fields


def test_14_quality_block_has_degraded_field():
    from contracts.desktop_status_projection import TopologyProjectionQualityBlock
    assert "degraded" in TopologyProjectionQualityBlock.model_fields


def test_15_quality_block_has_partial_field():
    from contracts.desktop_status_projection import TopologyProjectionQualityBlock
    assert "partial" in TopologyProjectionQualityBlock.model_fields


def test_16_quality_block_has_quality_note_field():
    from contracts.desktop_status_projection import TopologyProjectionQualityBlock
    assert "quality_note" in TopologyProjectionQualityBlock.model_fields


def test_17_quality_block_has_quality_authority_field():
    from contracts.desktop_status_projection import TopologyProjectionQualityBlock
    assert "quality_authority" in TopologyProjectionQualityBlock.model_fields


def test_18_quality_block_authority_defaults_to_sentinel():
    from contracts.desktop_status_projection import (
        TopologyProjectionQualityBlock,
        TOPOLOGY_READINESS_CONTRACT_AUTHORITY,
        TopologyProjectionReadiness,
    )
    block = TopologyProjectionQualityBlock()
    assert block.quality_authority == TOPOLOGY_READINESS_CONTRACT_AUTHORITY
    assert block.readiness == TopologyProjectionReadiness.unavailable
    assert block.authoritative is False
    assert block.degraded is False
    assert block.partial is False


def test_19_quality_block_to_dict_returns_dict():
    from contracts.desktop_status_projection import TopologyProjectionQualityBlock
    block = TopologyProjectionQualityBlock()
    result = block.to_dict()
    assert isinstance(result, dict)
    assert "readiness" in result
    assert "authoritative" in result
    assert "degraded" in result
    assert "partial" in result
    assert "quality_note" in result
    assert "quality_authority" in result


# ===========================================================================
# 20–21: DesktopTopologyProjection has projection_quality field
# ===========================================================================


def test_20_desktop_topology_projection_has_projection_quality_field():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    assert "projection_quality" in DesktopTopologyProjection.model_fields


def test_21_desktop_topology_projection_quality_defaults_to_none():
    from contracts.desktop_status_projection import DesktopTopologyProjection
    topo = DesktopTopologyProjection()
    assert topo.projection_quality is None


# ===========================================================================
# Helper: build projections for various paths
# ===========================================================================

def _canonical_ucp():
    return {
        "topology_route_plan": {
            "primary_model": {
                "model_id": "gpt-4o",
                "provider_id": "openai",
                "vendor_source": "direct",
                "native_multimodal": False,
            },
            "support_models": [],
            "route_reason": "test canonical",
            "phase": "manifest",
            "domain": "local",
            "authority": "core.model_topology.topology_router.CANONICAL_ROUTING_AUTHORITY",
        }
    }


def _legacy_ucp():
    return {
        "chosen_model": "gpt-4",
        "chosen_provider": "openai",
        "route_reason": "legacy test",
    }


def _empty_ucp():
    return {}


def _canonical_ucp_provider_unavailable():
    ucp = _canonical_ucp()
    ucp["canonical_model_supply"] = {
        "providers": [
            {"provider_id": "openai", "health_status": "unavailable"}
        ]
    }
    return ucp


# ===========================================================================
# 22–25: Canonical route-plan path readiness/quality
# ===========================================================================


def test_22_canonical_path_sets_readiness_canonical():
    from contracts.desktop_status_projection import (
        build_desktop_status_projection,
        TopologyProjectionReadiness,
    )
    proj = build_desktop_status_projection(unified_control_plan=_canonical_ucp())
    assert proj.topology_ready is not None
    assert proj.topology_ready.projection_quality is not None
    assert proj.topology_ready.projection_quality.readiness == TopologyProjectionReadiness.canonical


def test_23_canonical_path_sets_authoritative_true():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_canonical_ucp())
    assert proj.topology_ready.projection_quality.authoritative is True


def test_24_canonical_path_sets_degraded_false():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_canonical_ucp())
    assert proj.topology_ready.projection_quality.degraded is False


def test_25_canonical_path_sets_partial_false():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_canonical_ucp())
    assert proj.topology_ready.projection_quality.partial is False


# ===========================================================================
# 26–29: Legacy fallback path
# ===========================================================================


def test_26_legacy_path_sets_readiness_degraded():
    from contracts.desktop_status_projection import (
        build_desktop_status_projection,
        TopologyProjectionReadiness,
    )
    proj = build_desktop_status_projection(unified_control_plan=_legacy_ucp())
    assert proj.topology_ready.projection_quality.readiness == TopologyProjectionReadiness.degraded


def test_27_legacy_path_sets_authoritative_false():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_legacy_ucp())
    assert proj.topology_ready.projection_quality.authoritative is False


def test_28_legacy_path_sets_degraded_true():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_legacy_ucp())
    assert proj.topology_ready.projection_quality.degraded is True


def test_29_legacy_path_sets_partial_false():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_legacy_ucp())
    assert proj.topology_ready.projection_quality.partial is False


# ===========================================================================
# 30–32: Empty UCP (unavailable)
# ===========================================================================


def test_30_empty_ucp_sets_readiness_unavailable():
    from contracts.desktop_status_projection import (
        build_desktop_status_projection,
        TopologyProjectionReadiness,
    )
    proj = build_desktop_status_projection(unified_control_plan=_empty_ucp())
    assert proj.topology_ready.projection_quality.readiness == TopologyProjectionReadiness.unavailable


def test_31_empty_ucp_sets_authoritative_false():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_empty_ucp())
    assert proj.topology_ready.projection_quality.authoritative is False


def test_32_empty_ucp_sets_degraded_false():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_empty_ucp())
    assert proj.topology_ready.projection_quality.degraded is False


# ===========================================================================
# 33–35: Canonical path with provider unavailable (partial)
# ===========================================================================


def test_33_canonical_unavailable_provider_sets_readiness_partial():
    from contracts.desktop_status_projection import (
        build_desktop_status_projection,
        TopologyProjectionReadiness,
    )
    proj = build_desktop_status_projection(
        unified_control_plan=_canonical_ucp_provider_unavailable()
    )
    assert proj.topology_ready.projection_quality.readiness == TopologyProjectionReadiness.partial


def test_34_canonical_unavailable_provider_sets_authoritative_false():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(
        unified_control_plan=_canonical_ucp_provider_unavailable()
    )
    assert proj.topology_ready.projection_quality.authoritative is False


def test_35_canonical_unavailable_provider_sets_partial_true():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(
        unified_control_plan=_canonical_ucp_provider_unavailable()
    )
    assert proj.topology_ready.projection_quality.partial is True


# ===========================================================================
# 36–37: quality_note is meaningful on all paths
# ===========================================================================


def test_36_quality_note_is_non_empty_on_all_paths():
    from contracts.desktop_status_projection import build_desktop_status_projection
    ucps = [
        _canonical_ucp(),
        _legacy_ucp(),
        _empty_ucp(),
        _canonical_ucp_provider_unavailable(),
    ]
    for ucp in ucps:
        proj = build_desktop_status_projection(unified_control_plan=ucp)
        note = proj.topology_ready.projection_quality.quality_note
        assert isinstance(note, str) and len(note) > 0, (
            f"quality_note was empty for ucp={ucp}"
        )


def test_37_quality_note_differs_between_canonical_and_degraded():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj_canonical = build_desktop_status_projection(unified_control_plan=_canonical_ucp())
    proj_degraded = build_desktop_status_projection(unified_control_plan=_legacy_ucp())
    note_canonical = proj_canonical.topology_ready.projection_quality.quality_note
    note_degraded = proj_degraded.topology_ready.projection_quality.quality_note
    assert note_canonical != note_degraded


# ===========================================================================
# 38–41: to_dict() includes quality fields
# ===========================================================================


def test_38_quality_to_dict_includes_readiness():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_canonical_ucp())
    d = proj.topology_ready.projection_quality.to_dict()
    assert "readiness" in d


def test_39_quality_to_dict_includes_authoritative():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_canonical_ucp())
    d = proj.topology_ready.projection_quality.to_dict()
    assert "authoritative" in d


def test_40_quality_to_dict_includes_quality_authority():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_canonical_ucp())
    d = proj.topology_ready.projection_quality.to_dict()
    assert "quality_authority" in d


def test_41_topology_projection_to_dict_includes_projection_quality():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_canonical_ucp())
    d = proj.topology_ready.to_dict()
    assert "projection_quality" in d
    assert isinstance(d["projection_quality"], dict)


# ===========================================================================
# 42–44: projection_quality is always populated (never None) on built paths
# ===========================================================================


def test_42_projection_quality_not_none_on_canonical_path():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_canonical_ucp())
    assert proj.topology_ready.projection_quality is not None


def test_43_projection_quality_not_none_on_legacy_fallback_path():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_legacy_ucp())
    assert proj.topology_ready.projection_quality is not None


def test_44_projection_quality_not_none_on_empty_ucp():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_empty_ucp())
    assert proj.topology_ready.projection_quality is not None


# ===========================================================================
# 45–48: Backward-compat — PR-4, PR-5, PR-6 guarantees preserved
# ===========================================================================


def test_45_pr6_contract_authority_still_equals_topology_delivery_authority():
    from contracts.desktop_status_projection import (
        build_desktop_status_projection,
        TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY,
    )
    proj = build_desktop_status_projection(unified_control_plan=_canonical_ucp())
    assert proj.topology_ready.contract_authority == TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY


def test_46_oneapi_integration_remains_lower_horizon():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_canonical_ucp())
    topo = proj.topology_ready
    assert topo.oneapi_integration is not None
    assert topo.oneapi_integration.get("system_layer") == "aggregator_integration"
    # OneAPI must NOT be a provider in the route fields
    assert topo.primary_provider_id != "oneapi_aggregator"
    assert topo.primary_vendor_source != "system_layer"


def test_47_pr4_oneapi_integration_in_desktop_status_projection_preserved():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_canonical_ucp())
    # PR-4 field on DesktopStatusProjection (top-level block, separate from topology)
    assert hasattr(proj, "oneapi_integration")
    assert proj.oneapi_integration is not None
    assert proj.oneapi_integration.get("system_layer") == "aggregator_integration"


def test_48_pr5_legacy_routing_fallback_active_preserved():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan=_legacy_ucp())
    # PR-5 field on ModelRoutingProjection
    assert hasattr(proj.model_routing, "legacy_routing_fallback_active")
    assert proj.model_routing.legacy_routing_fallback_active is True


# ===========================================================================
# 49: _minimal_desktop_topology_fallback includes projection_quality
# ===========================================================================


def test_49_minimal_fallback_payload_includes_projection_quality():
    # Import the internal helper via the module
    import importlib
    routes_mod = importlib.import_module("core.routes.projection")
    fallback_fn = getattr(routes_mod, "_minimal_desktop_topology_fallback", None)
    assert fallback_fn is not None, "_minimal_desktop_topology_fallback not found"
    payload = fallback_fn()
    assert "projection_quality" in payload
    pq = payload["projection_quality"]
    assert isinstance(pq, dict)
    assert pq.get("readiness") == "unavailable"
    assert pq.get("authoritative") is False


# ===========================================================================
# 50: docs/SERVER_SIDE_CANONICALIZATION.md mentions PR-7
# ===========================================================================


def test_50_server_side_canonicalization_doc_mentions_pr7():
    content = _read_file("docs", "SERVER_SIDE_CANONICALIZATION.md")
    assert "PR-7" in content, (
        "docs/SERVER_SIDE_CANONICALIZATION.md does not mention PR-7. "
        "Please add a PR-7 section documenting the readiness/quality semantics."
    )
