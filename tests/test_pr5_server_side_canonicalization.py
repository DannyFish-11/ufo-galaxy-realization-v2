#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr5_server_side_canonicalization.py
==============================================

PR-5 — Final server-side canonicalization after PR-4 merge.

This PR builds on PR-4 (OneAPI lower-horizon cleanup) and completes the
server-side canonicalization phase by demoting remaining legacy/non-canonical
projection and routing outputs.

Validates:
  1.  LEGACY_UCP_ROUTING_KEYS is importable from contracts.desktop_status_projection.
  2.  LEGACY_UCP_ROUTING_KEYS is a frozenset.
  3.  LEGACY_UCP_ROUTING_KEYS contains "chosen_model".
  4.  LEGACY_UCP_ROUTING_KEYS contains "chosen_provider".
  5.  LEGACY_UCP_ROUTING_KEYS contains "is_native_multimodal".
  6.  LEGACY_UCP_ROUTING_KEYS contains "support_model_ids".
  7.  LEGACY_UCP_ROUTING_KEYS contains "route_reason".
  8.  LEGACY_UCP_ROUTING_KEYS contains "multimodal_route".
  9.  PROJECTION_CONTRACT_AUTHORITY is importable from contracts.desktop_status_projection.
  10. PROJECTION_CONTRACT_AUTHORITY is a non-empty string.
  11. ModelRoutingProjection has legacy_routing_fallback_active field.
  12. ModelRoutingProjection.legacy_routing_fallback_active defaults to False.
  13. legacy_routing_fallback_active is True when routing_authority_source == legacy_ucp_keys.
  14. legacy_routing_fallback_active is False when routing_authority_source == topology_router.
  15. legacy_routing_fallback_active is False when no routing data (source == none).
  16. LEGACY_ROUTING_FIELDS is importable from core.model_topology.topology_router.
  17. LEGACY_ROUTING_FIELDS is a tuple.
  18. LEGACY_ROUTING_FIELDS contains "chosen_model".
  19. LEGACY_ROUTING_FIELDS contains "chosen_provider".
  20. LEGACY_ROUTING_FIELDS contains "MultiLLMRouter".
  21. LEGACY_PROJECTION_UCP_KEYS is importable from core.projection.projection_compiler.
  22. LEGACY_PROJECTION_UCP_KEYS is a tuple.
  23. LEGACY_PROJECTION_UCP_KEYS contains "chosen_model".
  24. LEGACY_PROJECTION_UCP_KEYS contains "chosen_provider".
  25. PROJECTION_COMPILER_AUTHORITY is importable from core.projection.projection_compiler.
  26. PROJECTION_COMPILER_AUTHORITY is a non-empty string.
  27. build_desktop_status_projection with topology_route_plan sets legacy_routing_fallback_active=False.
  28. build_desktop_status_projection with only legacy UCP keys sets legacy_routing_fallback_active=True.
  29. build_desktop_status_projection with empty UCP sets legacy_routing_fallback_active=False.
  30. to_dict() of ModelRoutingProjection includes legacy_routing_fallback_active key.
  31. PR-4 oneapi_integration guarantee intact: field still present in DesktopStatusProjection.
  32. PR-4 oneapi_integration still separate from model_routing block.
  33. model_routing.oneapi_source still None when vendor_source is "direct" (PR-4 intact).
  34. CANONICAL_ROUTING_AUTHORITY is importable and unchanged from topology_router.
  35. CANONICAL_ROUTING_AUTHORITY value matches expected sentinel string.
  36. docs/SERVER_SIDE_CANONICALIZATION.md exists.
  37. docs/SERVER_SIDE_CANONICALIZATION.md mentions "PR-5".
  38. docs/SERVER_SIDE_CANONICALIZATION.md mentions "LEGACY_UCP_ROUTING_KEYS".
  39. docs/SERVER_SIDE_CANONICALIZATION.md mentions "legacy_routing_fallback_active".
  40. docs/SERVER_SIDE_CANONICALIZATION.md mentions "PR-4".
  41. docs/SERVER_SIDE_CANONICALIZATION.md mentions "topology_route_plan".
  42. _assemble_server_canonicalization_status returns a dict.
  43. _assemble_server_canonicalization_status has "canonicalization_stage" key.
  44. _assemble_server_canonicalization_status has "legacy_ucp_routing_keys" key.
  45. _assemble_server_canonicalization_status has "pr4_guarantees_intact" key.
  46. _assemble_server_canonicalization_status pr4_guarantees_intact is True.
  47. _assemble_server_canonicalization_status has "consumer_guidance" key.
  48. consumer_guidance has "prefer_topology_route_plan" == True.
  49. consumer_guidance has "avoid_legacy_ucp_keys" == True.
  50. LEGACY_UCP_ROUTING_KEYS and LEGACY_PROJECTION_UCP_KEYS are consistent (same keys).
"""

from __future__ import annotations

import os
import sys

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _doc_path(*parts: str) -> str:
    return os.path.join(_REPO_ROOT, *parts)


def _read_file(*parts: str) -> str:
    with open(os.path.join(_REPO_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# ===========================================================================
# 1–10: LEGACY_UCP_ROUTING_KEYS and PROJECTION_CONTRACT_AUTHORITY
# ===========================================================================


def test_01_legacy_ucp_routing_keys_importable():
    from contracts.desktop_status_projection import LEGACY_UCP_ROUTING_KEYS  # noqa: F401


def test_02_legacy_ucp_routing_keys_is_frozenset():
    from contracts.desktop_status_projection import LEGACY_UCP_ROUTING_KEYS
    assert isinstance(LEGACY_UCP_ROUTING_KEYS, frozenset)


def test_03_legacy_ucp_routing_keys_has_chosen_model():
    from contracts.desktop_status_projection import LEGACY_UCP_ROUTING_KEYS
    assert "chosen_model" in LEGACY_UCP_ROUTING_KEYS


def test_04_legacy_ucp_routing_keys_has_chosen_provider():
    from contracts.desktop_status_projection import LEGACY_UCP_ROUTING_KEYS
    assert "chosen_provider" in LEGACY_UCP_ROUTING_KEYS


def test_05_legacy_ucp_routing_keys_has_is_native_multimodal():
    from contracts.desktop_status_projection import LEGACY_UCP_ROUTING_KEYS
    assert "is_native_multimodal" in LEGACY_UCP_ROUTING_KEYS


def test_06_legacy_ucp_routing_keys_has_support_model_ids():
    from contracts.desktop_status_projection import LEGACY_UCP_ROUTING_KEYS
    assert "support_model_ids" in LEGACY_UCP_ROUTING_KEYS


def test_07_legacy_ucp_routing_keys_has_route_reason():
    from contracts.desktop_status_projection import LEGACY_UCP_ROUTING_KEYS
    assert "route_reason" in LEGACY_UCP_ROUTING_KEYS


def test_08_legacy_ucp_routing_keys_has_multimodal_route():
    from contracts.desktop_status_projection import LEGACY_UCP_ROUTING_KEYS
    assert "multimodal_route" in LEGACY_UCP_ROUTING_KEYS


def test_09_projection_contract_authority_importable():
    from contracts.desktop_status_projection import PROJECTION_CONTRACT_AUTHORITY  # noqa: F401


def test_10_projection_contract_authority_is_non_empty_string():
    from contracts.desktop_status_projection import PROJECTION_CONTRACT_AUTHORITY
    assert isinstance(PROJECTION_CONTRACT_AUTHORITY, str)
    assert len(PROJECTION_CONTRACT_AUTHORITY) > 0


# ===========================================================================
# 11–15: ModelRoutingProjection.legacy_routing_fallback_active
# ===========================================================================


def test_11_model_routing_projection_has_legacy_routing_fallback_active():
    from contracts.desktop_status_projection import ModelRoutingProjection
    proj = ModelRoutingProjection()
    assert hasattr(proj, "legacy_routing_fallback_active")


def test_12_legacy_routing_fallback_active_defaults_to_false():
    from contracts.desktop_status_projection import ModelRoutingProjection
    proj = ModelRoutingProjection()
    assert proj.legacy_routing_fallback_active is False


def test_13_legacy_routing_fallback_active_true_when_legacy_ucp_keys():
    from contracts.desktop_status_projection import build_desktop_status_projection
    # UCP with only legacy chosen_model/chosen_provider, no topology_route_plan
    ucp = {"chosen_model": "gpt-4o", "chosen_provider": "openai"}
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    assert proj.model_routing.legacy_routing_fallback_active is True


def test_14_legacy_routing_fallback_active_false_when_topology_router():
    from contracts.desktop_status_projection import build_desktop_status_projection
    # UCP with topology_route_plan (canonical path)
    ucp = {
        "topology_route_plan": {
            "primary_model": {
                "model_id": "gpt-4o",
                "provider_id": "openai",
                "vendor_source": "direct",
                "native_multimodal": False,
            },
            "support_models": [],
            "route_reason": "test",
        }
    }
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    assert proj.model_routing.legacy_routing_fallback_active is False


def test_15_legacy_routing_fallback_active_false_when_no_routing_data():
    from contracts.desktop_status_projection import build_desktop_status_projection
    # Empty UCP → routing_authority_source == "none"
    proj = build_desktop_status_projection(unified_control_plan={})
    assert proj.model_routing.legacy_routing_fallback_active is False


# ===========================================================================
# 16–20: LEGACY_ROUTING_FIELDS in topology_router
# ===========================================================================


def test_16_legacy_routing_fields_importable():
    from core.model_topology.topology_router import LEGACY_ROUTING_FIELDS  # noqa: F401


def test_17_legacy_routing_fields_is_tuple():
    from core.model_topology.topology_router import LEGACY_ROUTING_FIELDS
    assert isinstance(LEGACY_ROUTING_FIELDS, tuple)


def test_18_legacy_routing_fields_contains_chosen_model():
    from core.model_topology.topology_router import LEGACY_ROUTING_FIELDS
    assert "chosen_model" in LEGACY_ROUTING_FIELDS


def test_19_legacy_routing_fields_contains_chosen_provider():
    from core.model_topology.topology_router import LEGACY_ROUTING_FIELDS
    assert "chosen_provider" in LEGACY_ROUTING_FIELDS


def test_20_legacy_routing_fields_contains_multi_llm_router():
    from core.model_topology.topology_router import LEGACY_ROUTING_FIELDS
    assert "MultiLLMRouter" in LEGACY_ROUTING_FIELDS


# ===========================================================================
# 21–26: LEGACY_PROJECTION_UCP_KEYS and PROJECTION_COMPILER_AUTHORITY
# ===========================================================================


def test_21_legacy_projection_ucp_keys_importable():
    from core.projection.projection_compiler import LEGACY_PROJECTION_UCP_KEYS  # noqa: F401


def test_22_legacy_projection_ucp_keys_is_tuple():
    from core.projection.projection_compiler import LEGACY_PROJECTION_UCP_KEYS
    assert isinstance(LEGACY_PROJECTION_UCP_KEYS, tuple)


def test_23_legacy_projection_ucp_keys_contains_chosen_model():
    from core.projection.projection_compiler import LEGACY_PROJECTION_UCP_KEYS
    assert "chosen_model" in LEGACY_PROJECTION_UCP_KEYS


def test_24_legacy_projection_ucp_keys_contains_chosen_provider():
    from core.projection.projection_compiler import LEGACY_PROJECTION_UCP_KEYS
    assert "chosen_provider" in LEGACY_PROJECTION_UCP_KEYS


def test_25_projection_compiler_authority_importable():
    from core.projection.projection_compiler import PROJECTION_COMPILER_AUTHORITY  # noqa: F401


def test_26_projection_compiler_authority_is_non_empty_string():
    from core.projection.projection_compiler import PROJECTION_COMPILER_AUTHORITY
    assert isinstance(PROJECTION_COMPILER_AUTHORITY, str)
    assert len(PROJECTION_COMPILER_AUTHORITY) > 0


# ===========================================================================
# 27–30: build_desktop_status_projection with various UCP inputs
# ===========================================================================


def test_27_topology_route_plan_sets_fallback_false():
    from contracts.desktop_status_projection import build_desktop_status_projection
    ucp = {
        "topology_route_plan": {
            "primary_model": {
                "model_id": "claude-3-5-sonnet",
                "provider_id": "anthropic",
                "vendor_source": "direct",
                "native_multimodal": True,
            },
            "support_models": [],
            "route_reason": "canonical test",
        }
    }
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    assert proj.model_routing.routing_authority_source == "topology_router"
    assert proj.model_routing.legacy_routing_fallback_active is False


def test_28_legacy_ucp_keys_sets_fallback_true():
    from contracts.desktop_status_projection import build_desktop_status_projection
    ucp = {
        "chosen_model": "claude-3-5-sonnet",
        "chosen_provider": "anthropic",
        "is_native_multimodal": True,
    }
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    assert proj.model_routing.routing_authority_source == "legacy_ucp_keys"
    assert proj.model_routing.legacy_routing_fallback_active is True


def test_29_empty_ucp_sets_fallback_false():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan={})
    assert proj.model_routing.routing_authority_source == "none"
    assert proj.model_routing.legacy_routing_fallback_active is False


def test_30_to_dict_includes_legacy_routing_fallback_active():
    from contracts.desktop_status_projection import ModelRoutingProjection
    proj = ModelRoutingProjection()
    d = proj.to_dict()
    assert "legacy_routing_fallback_active" in d


# ===========================================================================
# 31–35: PR-4 guarantees intact
# ===========================================================================


def test_31_pr4_oneapi_integration_field_still_present():
    from contracts.desktop_status_projection import DesktopStatusProjection
    proj = DesktopStatusProjection()
    assert hasattr(proj, "oneapi_integration")


def test_32_pr4_oneapi_integration_separate_from_model_routing():
    from contracts.desktop_status_projection import (
        DesktopStatusProjection,
        ModelRoutingProjection,
    )
    # oneapi_integration is on DesktopStatusProjection, not ModelRoutingProjection
    assert hasattr(DesktopStatusProjection(), "oneapi_integration")
    # ModelRoutingProjection has oneapi_source (per-route context), not oneapi_integration
    mr = ModelRoutingProjection()
    assert not hasattr(mr, "oneapi_integration")
    assert hasattr(mr, "oneapi_source")


def test_33_pr4_oneapi_source_none_for_direct_vendor():
    from contracts.desktop_status_projection import build_desktop_status_projection
    ucp = {
        "topology_route_plan": {
            "primary_model": {
                "model_id": "gpt-4o",
                "provider_id": "openai",
                "vendor_source": "direct",
                "native_multimodal": False,
            },
            "support_models": [],
            "route_reason": "direct vendor test",
        }
    }
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    assert proj.model_routing.oneapi_source is None


def test_34_canonical_routing_authority_importable_unchanged():
    from core.model_topology.topology_router import CANONICAL_ROUTING_AUTHORITY  # noqa: F401
    assert isinstance(CANONICAL_ROUTING_AUTHORITY, str)
    assert len(CANONICAL_ROUTING_AUTHORITY) > 0


def test_35_canonical_routing_authority_expected_value():
    from core.model_topology.topology_router import CANONICAL_ROUTING_AUTHORITY
    assert CANONICAL_ROUTING_AUTHORITY == (
        "core.model_topology.topology_router.TopologyRouter"
    )


# ===========================================================================
# 36–41: docs/SERVER_SIDE_CANONICALIZATION.md
# ===========================================================================


def test_36_server_side_canonicalization_doc_exists():
    assert os.path.isfile(_doc_path("docs", "SERVER_SIDE_CANONICALIZATION.md"))


def test_37_doc_mentions_pr5():
    content = _read_file("docs", "SERVER_SIDE_CANONICALIZATION.md")
    assert "PR-5" in content


def test_38_doc_mentions_legacy_ucp_routing_keys():
    content = _read_file("docs", "SERVER_SIDE_CANONICALIZATION.md")
    assert "LEGACY_UCP_ROUTING_KEYS" in content


def test_39_doc_mentions_legacy_routing_fallback_active():
    content = _read_file("docs", "SERVER_SIDE_CANONICALIZATION.md")
    assert "legacy_routing_fallback_active" in content


def test_40_doc_mentions_pr4():
    content = _read_file("docs", "SERVER_SIDE_CANONICALIZATION.md")
    assert "PR-4" in content


def test_41_doc_mentions_topology_route_plan():
    content = _read_file("docs", "SERVER_SIDE_CANONICALIZATION.md")
    assert "topology_route_plan" in content


# ===========================================================================
# 42–49: _assemble_server_canonicalization_status
# ===========================================================================


def test_42_assemble_server_canonicalization_status_returns_dict():
    from core.routes.projection import _assemble_server_canonicalization_status
    result = _assemble_server_canonicalization_status()
    assert isinstance(result, dict)


def test_43_assemble_server_canonicalization_status_has_stage_key():
    from core.routes.projection import _assemble_server_canonicalization_status
    result = _assemble_server_canonicalization_status()
    assert "canonicalization_stage" in result


def test_44_assemble_server_canonicalization_status_has_legacy_keys():
    from core.routes.projection import _assemble_server_canonicalization_status
    result = _assemble_server_canonicalization_status()
    assert "legacy_ucp_routing_keys" in result


def test_45_assemble_server_canonicalization_status_has_pr4_key():
    from core.routes.projection import _assemble_server_canonicalization_status
    result = _assemble_server_canonicalization_status()
    assert "pr4_guarantees_intact" in result


def test_46_assemble_server_canonicalization_status_pr4_guarantees_intact():
    from core.routes.projection import _assemble_server_canonicalization_status
    result = _assemble_server_canonicalization_status()
    assert result["pr4_guarantees_intact"] is True


def test_47_assemble_server_canonicalization_status_has_consumer_guidance():
    from core.routes.projection import _assemble_server_canonicalization_status
    result = _assemble_server_canonicalization_status()
    assert "consumer_guidance" in result


def test_48_consumer_guidance_prefer_topology_route_plan_true():
    from core.routes.projection import _assemble_server_canonicalization_status
    result = _assemble_server_canonicalization_status()
    assert result["consumer_guidance"]["prefer_topology_route_plan"] is True


def test_49_consumer_guidance_avoid_legacy_ucp_keys_true():
    from core.routes.projection import _assemble_server_canonicalization_status
    result = _assemble_server_canonicalization_status()
    assert result["consumer_guidance"]["avoid_legacy_ucp_keys"] is True


# ===========================================================================
# 50: Consistency check: LEGACY_UCP_ROUTING_KEYS == set(LEGACY_PROJECTION_UCP_KEYS)
# ===========================================================================


def test_50_legacy_keys_consistent_between_modules():
    from contracts.desktop_status_projection import LEGACY_UCP_ROUTING_KEYS
    from core.projection.projection_compiler import LEGACY_PROJECTION_UCP_KEYS
    assert LEGACY_UCP_ROUTING_KEYS == set(LEGACY_PROJECTION_UCP_KEYS)
