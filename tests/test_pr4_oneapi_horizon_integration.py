#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr4_oneapi_horizon_integration.py
=============================================

PR-4 — OneAPI Horizon and Global Integration Cleanup.

This PR supersedes prior PR-4 attempts, including PR #408 and any earlier
replacement attempt related to OneAPI horizon cleanup.

Validates:
  1.  OneAPIStatusSummary is importable from core.oneapi_system_position.
  2.  build_oneapi_status_summary is importable from core.oneapi_system_position.
  3.  build_oneapi_status_summary returns an OneAPIStatusSummary.
  4.  OneAPIStatusSummary.system_layer is always ONEAPI_SYSTEM_LAYER.
  5.  build_oneapi_status_summary with configured=True sets configured=True.
  6.  build_oneapi_status_summary with configured=False sets configured=False.
  7.  build_oneapi_status_summary with health="healthy" sets health="healthy".
  8.  build_oneapi_status_summary with health="skipped" sets health="skipped".
  9.  build_oneapi_status_summary sets base_url_hint when provided.
  10. build_oneapi_status_summary sets base_url_hint=None by default.
  11. build_oneapi_status_summary sets model_count when provided.
  12. build_oneapi_status_summary sets gateway_identity when provided.
  13. OneAPIStatusSummary.to_dict() includes "system_layer" key.
  14. OneAPIStatusSummary.to_dict() includes "configured" key.
  15. OneAPIStatusSummary.to_dict() includes "health" key.
  16. OneAPIStatusSummary.to_dict() includes "base_url_hint" key.
  17. OneAPIStatusSummary.to_dict() includes "model_count" key.
  18. OneAPIStatusSummary.to_dict() includes "gateway_identity" key.
  19. OneAPIStatusSummary.to_dict()["system_layer"] is "aggregator_integration".
  20. DesktopStatusProjection has oneapi_integration field.
  21. DesktopStatusProjection.oneapi_integration defaults to None.
  22. build_desktop_status_projection always produces oneapi_integration block.
  23. oneapi_integration block has "system_layer" key.
  24. oneapi_integration block has "configured" key.
  25. oneapi_integration block has "health" key.
  26. oneapi_integration["system_layer"] is "aggregator_integration".
  27. build_desktop_status_projection with empty UCP produces oneapi_integration.
  28. OneAPI not mixed into model_routing when no OneAPI route.
  29. model_routing.oneapi_source is None when vendor_source is "direct".
  30. model_routing.oneapi_source is not None when vendor_source is "oneapi".
  31. oneapi_integration block is separate from model_routing block.
  32. oneapi_integration block present even when UCP has no oneapi data.
  33. oneapi_integration block present when ucp has oneapi_status block.
  34. ucp-provided oneapi_status is forwarded to oneapi_integration.
  35. oneapi_integration block present when ucp has oneapi_summary block.
  36. Node_01_OneAPI /status response includes oneapi_integration key (static check).
  37. Node_01_OneAPI /health response includes oneapi_integration key (static check).
  38. Node_01_OneAPI main.py imports build_oneapi_status_summary.
  39. docs/ONEAPI_SYSTEM_POSITION.md mentions "PR-4".
  40. docs/ONEAPI_SYSTEM_POSITION.md mentions "supersedes".
  41. docs/ONEAPI_SYSTEM_POSITION.md mentions "oneapi_integration".
  42. docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md mentions PR-4 enforcement.
  43. docs/STATUS_BOARD_V2.md mentions oneapi_integration.
  44. build_oneapi_status_summary NOT configured has health="skipped" by default.
  45. build_oneapi_integration_summary still works (backward compat).
  46. DesktopStatusProjection.to_dict() includes oneapi_integration key.
  47. Serialised projection oneapi_integration is dict or None.
  48. oneapi_integration system_layer never equals "direct" or "top_layer".
  49. model_routing.support_model_hints does not include "oneapi" sentinel.
  50. _build_oneapi_integration_projection returns dict with aggregator_integration layer.
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
# 1–19: core.oneapi_system_position — OneAPIStatusSummary & builder
# ===========================================================================


def test_01_oneapi_status_summary_importable():
    from core.oneapi_system_position import OneAPIStatusSummary  # noqa: F401


def test_02_build_oneapi_status_summary_importable():
    from core.oneapi_system_position import build_oneapi_status_summary  # noqa: F401


def test_03_build_oneapi_status_summary_returns_oneapi_status_summary():
    from core.oneapi_system_position import (
        OneAPIStatusSummary,
        build_oneapi_status_summary,
    )
    result = build_oneapi_status_summary()
    assert isinstance(result, OneAPIStatusSummary)


def test_04_oneapi_status_summary_system_layer_is_sentinel():
    from core.oneapi_system_position import (
        ONEAPI_SYSTEM_LAYER,
        build_oneapi_status_summary,
    )
    result = build_oneapi_status_summary()
    assert result.system_layer == ONEAPI_SYSTEM_LAYER


def test_05_build_oneapi_status_summary_configured_true():
    from core.oneapi_system_position import build_oneapi_status_summary
    result = build_oneapi_status_summary(configured=True)
    assert result.configured is True


def test_06_build_oneapi_status_summary_configured_false():
    from core.oneapi_system_position import build_oneapi_status_summary
    result = build_oneapi_status_summary(configured=False)
    assert result.configured is False


def test_07_build_oneapi_status_summary_health_healthy():
    from core.oneapi_system_position import build_oneapi_status_summary
    result = build_oneapi_status_summary(health="healthy")
    assert result.health == "healthy"


def test_08_build_oneapi_status_summary_health_skipped():
    from core.oneapi_system_position import build_oneapi_status_summary
    result = build_oneapi_status_summary(health="skipped")
    assert result.health == "skipped"


def test_09_build_oneapi_status_summary_base_url_hint():
    from core.oneapi_system_position import build_oneapi_status_summary
    result = build_oneapi_status_summary(base_url_hint="http://host:3000")
    assert result.base_url_hint == "http://host:3000"


def test_10_build_oneapi_status_summary_base_url_hint_default_none():
    from core.oneapi_system_position import build_oneapi_status_summary
    result = build_oneapi_status_summary()
    assert result.base_url_hint is None


def test_11_build_oneapi_status_summary_model_count():
    from core.oneapi_system_position import build_oneapi_status_summary
    result = build_oneapi_status_summary(model_count=42)
    assert result.model_count == 42


def test_12_build_oneapi_status_summary_gateway_identity():
    from core.oneapi_system_position import build_oneapi_status_summary
    result = build_oneapi_status_summary(gateway_identity="oneapi-gateway")
    assert result.gateway_identity == "oneapi-gateway"


def test_13_oneapi_status_summary_to_dict_includes_system_layer():
    from core.oneapi_system_position import build_oneapi_status_summary
    d = build_oneapi_status_summary().to_dict()
    assert "system_layer" in d


def test_14_oneapi_status_summary_to_dict_includes_configured():
    from core.oneapi_system_position import build_oneapi_status_summary
    d = build_oneapi_status_summary().to_dict()
    assert "configured" in d


def test_15_oneapi_status_summary_to_dict_includes_health():
    from core.oneapi_system_position import build_oneapi_status_summary
    d = build_oneapi_status_summary().to_dict()
    assert "health" in d


def test_16_oneapi_status_summary_to_dict_includes_base_url_hint():
    from core.oneapi_system_position import build_oneapi_status_summary
    d = build_oneapi_status_summary().to_dict()
    assert "base_url_hint" in d


def test_17_oneapi_status_summary_to_dict_includes_model_count():
    from core.oneapi_system_position import build_oneapi_status_summary
    d = build_oneapi_status_summary().to_dict()
    assert "model_count" in d


def test_18_oneapi_status_summary_to_dict_includes_gateway_identity():
    from core.oneapi_system_position import build_oneapi_status_summary
    d = build_oneapi_status_summary().to_dict()
    assert "gateway_identity" in d


def test_19_oneapi_status_summary_to_dict_system_layer_is_aggregator_integration():
    from core.oneapi_system_position import build_oneapi_status_summary
    d = build_oneapi_status_summary().to_dict()
    assert d["system_layer"] == "aggregator_integration"


# ===========================================================================
# 20–35: contracts.desktop_status_projection — oneapi_integration block
# ===========================================================================


def test_20_desktop_status_projection_has_oneapi_integration_field():
    from contracts.desktop_status_projection import DesktopStatusProjection
    proj = DesktopStatusProjection()
    assert hasattr(proj, "oneapi_integration")


def test_21_desktop_status_projection_oneapi_integration_default_none():
    from contracts.desktop_status_projection import DesktopStatusProjection
    proj = DesktopStatusProjection()
    assert proj.oneapi_integration is None


def test_22_build_desktop_status_projection_always_produces_oneapi_integration():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection()
    assert proj.oneapi_integration is not None


def test_23_oneapi_integration_block_has_system_layer():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection()
    assert "system_layer" in proj.oneapi_integration


def test_24_oneapi_integration_block_has_configured():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection()
    assert "configured" in proj.oneapi_integration


def test_25_oneapi_integration_block_has_health():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection()
    assert "health" in proj.oneapi_integration


def test_26_oneapi_integration_system_layer_is_aggregator_integration():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection()
    assert proj.oneapi_integration["system_layer"] == "aggregator_integration"


def test_27_build_desktop_status_projection_with_empty_ucp_produces_oneapi_integration():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection(unified_control_plan={})
    assert proj.oneapi_integration is not None
    assert proj.oneapi_integration.get("system_layer") == "aggregator_integration"


def test_28_oneapi_not_mixed_into_model_routing_when_no_oneapi_route():
    """When the active route is a direct provider, model_routing must not
    include oneapi data in selected_provider or support_model_hints."""
    from contracts.desktop_status_projection import build_desktop_status_projection

    ucp = {
        "topology_route_plan": {
            "primary_model": {
                "node_id": "openai_gpt4o",
                "model_id": "gpt-4o",
                "provider_id": "openai",
                "vendor_source": "direct",
                "native_multimodal": True,
            },
            "support_models": [],
            "route_reason": "direct provider",
        }
    }
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    # Top-layer route must be direct provider, not oneapi
    assert proj.model_routing.selected_provider == "openai"
    assert proj.model_routing.vendor_source == "direct"
    # oneapi_source must be None when NOT routing through OneAPI
    assert proj.model_routing.oneapi_source is None


def test_29_model_routing_oneapi_source_none_when_vendor_source_direct():
    from contracts.desktop_status_projection import build_desktop_status_projection

    ucp = {
        "topology_route_plan": {
            "primary_model": {
                "node_id": "node_openai",
                "model_id": "gpt-4o",
                "provider_id": "openai",
                "vendor_source": "direct",
            },
            "support_models": [],
        }
    }
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    assert proj.model_routing.oneapi_source is None


def test_30_model_routing_oneapi_source_not_none_when_vendor_source_oneapi():
    from contracts.desktop_status_projection import build_desktop_status_projection

    ucp = {
        "topology_route_plan": {
            "primary_model": {
                "node_id": "node_01_oneapi",
                "model_id": "openrouter/gpt-4",
                "provider_id": "oneapi",
                "vendor_source": "oneapi",
            },
            "support_models": [],
        }
    }
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    assert proj.model_routing.oneapi_source is not None


def test_31_oneapi_integration_block_separate_from_model_routing_block():
    """oneapi_integration must not be the same object as model_routing."""
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection()
    # They are different types: model_routing is a Pydantic model, oneapi_integration is a dict
    assert type(proj.oneapi_integration) is dict


def test_32_oneapi_integration_present_when_no_oneapi_data_in_ucp():
    """The block must be present even when the UCP has no OneAPI data at all."""
    from contracts.desktop_status_projection import build_desktop_status_projection
    ucp = {"topology_route_plan": {}}
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    assert proj.oneapi_integration is not None
    assert proj.oneapi_integration.get("system_layer") == "aggregator_integration"


def test_33_oneapi_integration_present_when_ucp_has_oneapi_status():
    from contracts.desktop_status_projection import build_desktop_status_projection
    ucp = {
        "oneapi_status": {
            "system_layer": "aggregator_integration",
            "configured": True,
            "health": "healthy",
            "base_url_hint": "http://oneapi.local:3000",
            "model_count": 10,
            "gateway_identity": "oneapi-gateway",
        }
    }
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    assert proj.oneapi_integration is not None
    assert proj.oneapi_integration.get("system_layer") == "aggregator_integration"


def test_34_ucp_provided_oneapi_status_forwarded_to_oneapi_integration():
    from contracts.desktop_status_projection import build_desktop_status_projection
    ucp = {
        "oneapi_status": {
            "system_layer": "aggregator_integration",
            "configured": True,
            "health": "healthy",
            "base_url_hint": "http://oneapi.local:3000",
            "model_count": 7,
            "gateway_identity": "test-gateway",
        }
    }
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    assert proj.oneapi_integration.get("configured") is True
    assert proj.oneapi_integration.get("base_url_hint") == "http://oneapi.local:3000"
    assert proj.oneapi_integration.get("model_count") == 7
    assert proj.oneapi_integration.get("gateway_identity") == "test-gateway"


def test_35_oneapi_integration_present_when_ucp_has_oneapi_summary():
    from contracts.desktop_status_projection import build_desktop_status_projection
    ucp = {
        "oneapi_summary": {
            "system_layer": "aggregator_integration",
            "configured": False,
            "health": "skipped",
            "base_url_hint": None,
            "model_count": None,
            "gateway_identity": None,
        }
    }
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    assert proj.oneapi_integration is not None
    assert proj.oneapi_integration.get("system_layer") == "aggregator_integration"


# ===========================================================================
# 36–38: Node_01_OneAPI /status and /health endpoints — static code check
# ===========================================================================


def test_36_node_01_oneapi_status_endpoint_includes_oneapi_integration():
    """Static check: main.py node_status function includes oneapi_integration in return."""
    content = _read_file("nodes", "Node_01_OneAPI", "main.py")
    # The /status endpoint must return an oneapi_integration key
    assert '"oneapi_integration"' in content or "'oneapi_integration'" in content


def test_37_node_01_oneapi_health_endpoint_includes_oneapi_integration():
    """Static check: main.py health function includes oneapi_integration in return."""
    content = _read_file("nodes", "Node_01_OneAPI", "main.py")
    assert '"oneapi_integration"' in content or "'oneapi_integration'" in content


def test_38_node_01_oneapi_main_imports_build_oneapi_status_summary():
    """Static check: main.py references build_oneapi_status_summary."""
    content = _read_file("nodes", "Node_01_OneAPI", "main.py")
    assert "build_oneapi_status_summary" in content


# ===========================================================================
# 39–43: Documentation — PR-4 language enforcement
# ===========================================================================


def test_39_oneapi_system_position_doc_mentions_pr4():
    content = _read_file("docs", "ONEAPI_SYSTEM_POSITION.md")
    assert "PR-4" in content


def test_40_oneapi_system_position_doc_mentions_supersedes():
    content = _read_file("docs", "ONEAPI_SYSTEM_POSITION.md")
    assert "supersedes" in content.lower()


def test_41_oneapi_system_position_doc_mentions_oneapi_integration():
    content = _read_file("docs", "ONEAPI_SYSTEM_POSITION.md")
    assert "oneapi_integration" in content


def test_42_right_status_board_doc_mentions_pr4_enforcement():
    content = _read_file("docs", "RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md")
    assert "PR-4" in content


def test_43_status_board_v2_doc_mentions_oneapi_integration():
    content = _read_file("docs", "STATUS_BOARD_V2.md")
    assert "oneapi_integration" in content


# ===========================================================================
# 44–50: Regression / invariant guards
# ===========================================================================


def test_44_build_oneapi_status_summary_not_configured_defaults_to_skipped():
    from core.oneapi_system_position import build_oneapi_status_summary
    result = build_oneapi_status_summary(configured=False)
    # default health when not configured should indicate "skipped" or similar
    # (the caller may pass health explicitly; default is "skipped")
    result2 = build_oneapi_status_summary()
    assert result2.health == "skipped"


def test_45_build_oneapi_integration_summary_still_works():
    """Backward compatibility: build_oneapi_integration_summary must still work."""
    from core.oneapi_system_position import build_oneapi_integration_summary
    snapshot = build_oneapi_integration_summary()
    assert snapshot.system_layer == "aggregator_integration"


def test_46_desktop_status_projection_to_dict_includes_oneapi_integration():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection()
    d = proj.to_dict()
    assert "oneapi_integration" in d


def test_47_serialised_projection_oneapi_integration_is_dict_or_none():
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection()
    d = proj.to_dict()
    val = d.get("oneapi_integration")
    assert val is None or isinstance(val, dict)


def test_48_oneapi_integration_system_layer_never_direct():
    """system_layer must always be 'aggregator_integration', never 'direct' or
    'top_layer'."""
    from contracts.desktop_status_projection import build_desktop_status_projection
    proj = build_desktop_status_projection()
    sl = proj.oneapi_integration.get("system_layer", "")
    assert sl != "direct"
    assert sl != "top_layer"
    assert sl == "aggregator_integration"


def test_49_model_routing_support_model_hints_not_contains_oneapi_sentinel():
    """support_model_hints must never carry the raw string 'oneapi'
    as a sentinel value — it carries model IDs."""
    from contracts.desktop_status_projection import build_desktop_status_projection

    ucp = {
        "topology_route_plan": {
            "primary_model": {
                "node_id": "node_openai",
                "model_id": "gpt-4o",
                "provider_id": "openai",
                "vendor_source": "direct",
            },
            "support_models": [
                {
                    "node_id": "node_anthropic",
                    "model_id": "claude-3-5-sonnet",
                    "provider_id": "anthropic",
                    "vendor_source": "direct",
                }
            ],
        }
    }
    proj = build_desktop_status_projection(unified_control_plan=ucp)
    # support_model_hints should contain model IDs, not "oneapi"
    assert "oneapi" not in proj.model_routing.support_model_hints


def test_50_build_oneapi_integration_projection_returns_aggregator_integration():
    """Indirect test of the lower-horizon projection builder via
    build_desktop_status_projection."""
    from contracts.desktop_status_projection import build_desktop_status_projection
    # With no UCP data, the builder should still produce an aggregator_integration block
    proj = build_desktop_status_projection(unified_control_plan={})
    assert isinstance(proj.oneapi_integration, dict)
    assert proj.oneapi_integration.get("system_layer") == "aggregator_integration"
    # Must have the required PR-4 keys
    required_keys = {"system_layer", "configured", "health", "base_url_hint",
                     "model_count", "gateway_identity"}
    assert required_keys.issubset(proj.oneapi_integration.keys())
