#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr8_desktop_status_board_integration_contract.py
============================================================

PR-8 — Final desktop status board integration contract after PR-7 merge.

Validates that the integration-oriented payload correctly composes canonical
sub-structures, that canonical authority layering is preserved, that
readiness/quality semantics remain intact, that OneAPI stays lower-horizon
only, and that clients can consume one stable integration contract without
reconstructing truth themselves.

Test index:
  1.  DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY importable from contracts.desktop_status_projection.
  2.  DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY is a non-empty string.
  3.  DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY importable from core.projection.projection_compiler.
  4.  DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY is consistent across both modules.
  5.  DesktopStatusBoardIntegrationPayload importable from contracts.desktop_status_projection.
  6.  DesktopStatusBoardIntegrationPayload has 'payload_id' field.
  7.  DesktopStatusBoardIntegrationPayload has 'integrated_at' field.
  8.  DesktopStatusBoardIntegrationPayload has 'topology_projection' field.
  9.  DesktopStatusBoardIntegrationPayload has 'model_routing_summary' field.
  10. DesktopStatusBoardIntegrationPayload has 'provider_health_summary' field.
  11. DesktopStatusBoardIntegrationPayload has 'oneapi_integration' field.
  12. DesktopStatusBoardIntegrationPayload has 'authority_indicators' field.
  13. DesktopStatusBoardIntegrationPayload has 'integration_authority' field.
  14. DesktopStatusBoardIntegrationPayload has 'integration_health' field.
  15. DesktopStatusBoardIntegrationPayload.integration_authority defaults to DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY.
  16. DesktopStatusBoardIntegrationPayload.to_dict() returns a dict.
  17. build_desktop_status_board_integration_payload importable from contracts.desktop_status_projection.
  18. build_desktop_status_board_integration_payload returns DesktopStatusBoardIntegrationPayload on canonical path.
  19. Integration payload topology_projection is a DesktopTopologyProjection on canonical path.
  20. Integration payload topology_projection.projection_quality is present on canonical path.
  21. Integration payload topology_projection.projection_quality.readiness is 'canonical' on canonical path.
  22. Integration payload model_routing_summary is a non-empty dict on canonical path.
  23. Integration payload model_routing_summary includes 'selected_provider' key.
  24. Integration payload model_routing_summary includes 'routing_authority_source' key.
  25. Integration payload model_routing_summary includes 'legacy_routing_fallback_active' key.
  26. Integration payload authority_indicators includes 'topology_authoritative' key.
  27. Integration payload authority_indicators 'topology_authoritative' is True on canonical path.
  28. Integration payload authority_indicators 'topology_canonical_source_present' is True on canonical path.
  29. Integration payload authority_indicators 'topology_legacy_fallback_active' is False on canonical path.
  30. Integration payload authority_indicators 'topology_readiness' is 'canonical' on canonical path.
  31. Integration payload authority_indicators 'oneapi_is_lower_horizon_only' is always True.
  32. Integration payload authority_indicators includes 'integration_contract_authority' key.
  33. Integration payload authority_indicators 'integration_contract_authority' equals DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY.
  34. Integration payload authority_indicators includes 'topology_delivery_contract_authority' key.
  35. Integration payload authority_indicators includes 'topology_readiness_contract_authority' key.
  36. Integration payload oneapi_integration system_layer is 'aggregator_integration' on canonical path.
  37. Integration payload integration_health is 'ok' on canonical path.
  38. Integration payload topology_projection is present on legacy fallback path.
  39. Integration payload authority_indicators 'topology_authoritative' is False on legacy fallback path.
  40. Integration payload authority_indicators 'topology_readiness' is 'degraded' on legacy fallback path.
  41. Integration payload authority_indicators 'topology_legacy_fallback_active' is True on legacy fallback path.
  42. Integration payload authority_indicators 'model_routing_legacy_fallback_active' is True on legacy fallback path.
  43. Integration payload topology_projection.projection_quality.readiness is 'unavailable' on empty UCP.
  44. Integration payload to_dict() includes 'topology_projection' key.
  45. Integration payload to_dict() includes 'authority_indicators' key.
  46. Integration payload to_dict() includes 'integration_authority' key.
  47. PR-7 topology readiness/quality semantics preserved in integration payload.
  48. PR-6 topology_ready contract_authority still set in topology_projection.
  49. PR-5 legacy_routing_fallback_active preserved in model_routing_summary.
  50. _minimal_desktop_status_board_fallback payload includes required keys.
  51. DesktopStatusBoardIntegrationPayload has 'readiness' convenience property.
  52. readiness property returns 'canonical' on canonical path.
  53. readiness property returns 'degraded' on legacy fallback path.
  54. readiness property returns 'unknown' on minimal payload with empty authority_indicators.
  55. DesktopStatusBoardIntegrationPayload has 'is_canonical' convenience property.
  56. is_canonical returns True on canonical path.
  57. is_canonical returns False on legacy fallback path.
  58. is_canonical returns False on minimal payload.
  59. build_desktop_status_board_integration_from_runtime importable from core.projection.projection_compiler.
  60. build_desktop_status_board_integration_from_runtime importable from core.projection package.
  61. DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY importable from core.projection package __all__.
  62. build_desktop_status_board_integration_from_runtime returns DesktopStatusBoardIntegrationPayload on canonical path.
  63. build_desktop_status_board_integration_from_runtime returns payload with correct integration_authority.
  64. build_desktop_status_board_integration_from_runtime returns non-None on empty/None inputs.
  65. DesktopStatusBoardIntegrationPayload uses ConfigDict (not deprecated class Config).
  66. to_dict() serialises readiness inside authority_indicators correctly.
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


# ---------------------------------------------------------------------------
# Shared fixture UCPs
# ---------------------------------------------------------------------------


def _canonical_ucp():
    """Minimal canonical UCP with a topology_route_plan block.

    Keys match the stable serialisation produced by
    ``TopologyRoutePlan.to_dict()`` (PR-2) and consumed by
    ``_build_topology_ready_projection`` (PR-6).
    """
    return {
        "topology_route_plan": {
            "primary_model": {
                "model_id": "gpt-4o",
                "provider_id": "openai",
                "vendor_source": "direct",
                "native_multimodal": False,
            },
            "support_models": [],
            "route_reason": "canonical test route",
            "phase": "manifest",
            "domain": "local",
            "active_weights": {},
            "authority": "core.model_topology.topology_router.CANONICAL_ROUTING_AUTHORITY",
        }
    }


def _legacy_ucp():
    """Legacy UCP using old-style keys (no topology_route_plan)."""
    return {
        "chosen_model": "gpt-4o",
        "chosen_provider": "openai",
        "route_reason": "legacy test route",
        "is_native_multimodal": False,
    }


def _empty_ucp():
    """Empty UCP (no routing data)."""
    return {}


# ===========================================================================
# 1–4: DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY sentinel
# ===========================================================================


def test_01_integration_authority_importable_from_contracts():
    from contracts.desktop_status_projection import DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY  # noqa: F401


def test_02_integration_authority_is_non_empty_string():
    from contracts.desktop_status_projection import DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY
    assert isinstance(DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY, str)
    assert len(DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY) > 0


def test_03_integration_authority_importable_from_compiler():
    from core.projection.projection_compiler import DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY  # noqa: F401


def test_04_integration_authority_consistent_across_modules():
    from contracts.desktop_status_projection import (
        DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY as contracts_auth,
    )
    from core.projection.projection_compiler import (
        DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY as compiler_auth,
    )
    assert contracts_auth == compiler_auth


# ===========================================================================
# 5–16: DesktopStatusBoardIntegrationPayload class
# ===========================================================================


def test_05_integration_payload_class_importable():
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload  # noqa: F401


def test_06_has_payload_id_field():
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload
    p = DesktopStatusBoardIntegrationPayload()
    assert hasattr(p, "payload_id")


def test_07_has_integrated_at_field():
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload
    p = DesktopStatusBoardIntegrationPayload()
    assert hasattr(p, "integrated_at")
    assert isinstance(p.integrated_at, float)


def test_08_has_topology_projection_field():
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload
    p = DesktopStatusBoardIntegrationPayload()
    assert hasattr(p, "topology_projection")


def test_09_has_model_routing_summary_field():
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload
    p = DesktopStatusBoardIntegrationPayload()
    assert hasattr(p, "model_routing_summary")
    assert isinstance(p.model_routing_summary, dict)


def test_10_has_provider_health_summary_field():
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload
    p = DesktopStatusBoardIntegrationPayload()
    assert hasattr(p, "provider_health_summary")


def test_11_has_oneapi_integration_field():
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload
    p = DesktopStatusBoardIntegrationPayload()
    assert hasattr(p, "oneapi_integration")


def test_12_has_authority_indicators_field():
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload
    p = DesktopStatusBoardIntegrationPayload()
    assert hasattr(p, "authority_indicators")
    assert isinstance(p.authority_indicators, dict)


def test_13_has_integration_authority_field():
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload
    p = DesktopStatusBoardIntegrationPayload()
    assert hasattr(p, "integration_authority")


def test_14_has_integration_health_field():
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload
    p = DesktopStatusBoardIntegrationPayload()
    assert hasattr(p, "integration_health")


def test_15_integration_authority_defaults_to_sentinel():
    from contracts.desktop_status_projection import (
        DesktopStatusBoardIntegrationPayload,
        DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
    )
    p = DesktopStatusBoardIntegrationPayload()
    assert p.integration_authority == DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY


def test_16_to_dict_returns_dict():
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload
    p = DesktopStatusBoardIntegrationPayload()
    d = p.to_dict()
    assert isinstance(d, dict)


# ===========================================================================
# 17–18: builder importable and returns correct type
# ===========================================================================


def test_17_builder_importable():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload  # noqa: F401


def test_18_builder_returns_integration_payload_on_canonical_path():
    from contracts.desktop_status_projection import (
        build_desktop_status_board_integration_payload,
        DesktopStatusBoardIntegrationPayload,
    )
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert isinstance(result, DesktopStatusBoardIntegrationPayload)


# ===========================================================================
# 19–21: topology_projection on canonical path
# ===========================================================================


def test_19_topology_projection_is_desktop_topology_projection_on_canonical():
    from contracts.desktop_status_projection import (
        build_desktop_status_board_integration_payload,
        DesktopTopologyProjection,
    )
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert result.topology_projection is not None
    assert isinstance(result.topology_projection, DesktopTopologyProjection)


def test_20_topology_projection_quality_present_on_canonical():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert result.topology_projection is not None
    assert result.topology_projection.projection_quality is not None


def test_21_topology_projection_quality_readiness_canonical():
    from contracts.desktop_status_projection import (
        build_desktop_status_board_integration_payload,
        TopologyProjectionReadiness,
    )
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    pq = result.topology_projection.projection_quality
    readiness = pq.readiness
    readiness_val = readiness.value if hasattr(readiness, "value") else str(readiness)
    assert readiness_val == TopologyProjectionReadiness.canonical.value


# ===========================================================================
# 22–25: model_routing_summary on canonical path
# ===========================================================================


def test_22_model_routing_summary_is_nonempty_dict_on_canonical():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert isinstance(result.model_routing_summary, dict)
    assert len(result.model_routing_summary) > 0


def test_23_model_routing_summary_includes_selected_provider():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert "selected_provider" in result.model_routing_summary


def test_24_model_routing_summary_includes_routing_authority_source():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert "routing_authority_source" in result.model_routing_summary


def test_25_model_routing_summary_includes_legacy_routing_fallback_active():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert "legacy_routing_fallback_active" in result.model_routing_summary


# ===========================================================================
# 26–35: authority_indicators on canonical path
# ===========================================================================


def test_26_authority_indicators_includes_topology_authoritative():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert "topology_authoritative" in result.authority_indicators


def test_27_authority_indicators_topology_authoritative_true_on_canonical():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert result.authority_indicators["topology_authoritative"] is True


def test_28_authority_indicators_canonical_source_present_true_on_canonical():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert result.authority_indicators["topology_canonical_source_present"] is True


def test_29_authority_indicators_legacy_fallback_false_on_canonical():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert result.authority_indicators["topology_legacy_fallback_active"] is False


def test_30_authority_indicators_topology_readiness_canonical():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert result.authority_indicators["topology_readiness"] == "canonical"


def test_31_authority_indicators_oneapi_is_lower_horizon_only_always_true():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    for ucp in [_canonical_ucp(), _legacy_ucp(), _empty_ucp()]:
        result = build_desktop_status_board_integration_payload(
            unified_control_plan=ucp
        )
        assert result.authority_indicators.get("oneapi_is_lower_horizon_only") is True


def test_32_authority_indicators_includes_integration_contract_authority():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert "integration_contract_authority" in result.authority_indicators


def test_33_authority_indicators_integration_contract_authority_equals_sentinel():
    from contracts.desktop_status_projection import (
        build_desktop_status_board_integration_payload,
        DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
    )
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert (
        result.authority_indicators["integration_contract_authority"]
        == DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY
    )


def test_34_authority_indicators_includes_topology_delivery_contract_authority():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert "topology_delivery_contract_authority" in result.authority_indicators


def test_35_authority_indicators_includes_topology_readiness_contract_authority():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert "topology_readiness_contract_authority" in result.authority_indicators


# ===========================================================================
# 36–37: OneAPI lower-horizon and integration_health on canonical path
# ===========================================================================


def test_36_oneapi_integration_system_layer_is_aggregator_on_canonical():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert result.oneapi_integration is not None
    assert result.oneapi_integration.get("system_layer") == "aggregator_integration"


def test_37_integration_health_ok_on_canonical():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    health = result.integration_health
    health_val = health.value if hasattr(health, "value") else str(health)
    assert health_val == "ok"


# ===========================================================================
# 38–42: legacy fallback path
# ===========================================================================


def test_38_topology_projection_present_on_legacy_fallback():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_legacy_ucp()
    )
    assert result.topology_projection is not None


def test_39_authority_indicators_topology_authoritative_false_on_legacy():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_legacy_ucp()
    )
    assert result.authority_indicators["topology_authoritative"] is False


def test_40_authority_indicators_topology_readiness_degraded_on_legacy():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_legacy_ucp()
    )
    assert result.authority_indicators["topology_readiness"] == "degraded"


def test_41_authority_indicators_legacy_fallback_true_on_legacy():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_legacy_ucp()
    )
    assert result.authority_indicators["topology_legacy_fallback_active"] is True


def test_42_model_routing_legacy_fallback_true_on_legacy():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_legacy_ucp()
    )
    assert result.authority_indicators.get("model_routing_legacy_fallback_active") is True


# ===========================================================================
# 43: empty UCP path
# ===========================================================================


def test_43_topology_projection_quality_readiness_unavailable_on_empty():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_empty_ucp()
    )
    assert result.topology_projection is not None
    pq = result.topology_projection.projection_quality
    assert pq is not None
    readiness = pq.readiness
    readiness_val = readiness.value if hasattr(readiness, "value") else str(readiness)
    assert readiness_val == "unavailable"


# ===========================================================================
# 44–46: to_dict() includes required keys
# ===========================================================================


def test_44_to_dict_includes_topology_projection():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    d = result.to_dict()
    assert "topology_projection" in d


def test_45_to_dict_includes_authority_indicators():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    d = result.to_dict()
    assert "authority_indicators" in d
    assert isinstance(d["authority_indicators"], dict)


def test_46_to_dict_includes_integration_authority():
    from contracts.desktop_status_projection import (
        build_desktop_status_board_integration_payload,
        DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
    )
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    d = result.to_dict()
    assert "integration_authority" in d
    assert d["integration_authority"] == DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY


# ===========================================================================
# 47–49: Backward-compat — PR-4, PR-5, PR-6, PR-7 guarantees preserved
# ===========================================================================


def test_47_pr7_readiness_semantics_preserved_in_integration_payload():
    from contracts.desktop_status_projection import (
        build_desktop_status_board_integration_payload,
        TopologyProjectionReadiness,
    )
    canonical = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    legacy = build_desktop_status_board_integration_payload(
        unified_control_plan=_legacy_ucp()
    )
    empty = build_desktop_status_board_integration_payload(
        unified_control_plan=_empty_ucp()
    )

    def _readiness(payload):
        pq = payload.topology_projection.projection_quality
        r = pq.readiness
        return r.value if hasattr(r, "value") else str(r)

    assert _readiness(canonical) == TopologyProjectionReadiness.canonical.value
    assert _readiness(legacy) == TopologyProjectionReadiness.degraded.value
    assert _readiness(empty) == TopologyProjectionReadiness.unavailable.value


def test_48_pr6_contract_authority_still_set_in_topology_projection():
    from contracts.desktop_status_projection import (
        build_desktop_status_board_integration_payload,
        TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY,
    )
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert result.topology_projection is not None
    assert result.topology_projection.contract_authority == TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY


def test_49_pr5_legacy_routing_fallback_active_preserved_in_model_routing_summary():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_legacy_ucp()
    )
    assert "legacy_routing_fallback_active" in result.model_routing_summary
    assert result.model_routing_summary["legacy_routing_fallback_active"] is True


# ===========================================================================
# 50: _minimal_desktop_status_board_fallback payload includes required keys
# ===========================================================================


def test_50_minimal_fallback_payload_includes_required_keys():
    import importlib
    routes_mod = importlib.import_module("core.routes.projection")
    fallback_fn = getattr(routes_mod, "_minimal_desktop_status_board_fallback", None)
    assert fallback_fn is not None, "_minimal_desktop_status_board_fallback not found"
    payload = fallback_fn()
    for key in (
        "payload_id",
        "integrated_at",
        "topology_projection",
        "model_routing_summary",
        "oneapi_integration",
        "authority_indicators",
        "integration_authority",
        "integration_health",
        "authority_source_fingerprint",
    ):
        assert key in payload, f"missing key: {key}"
    # Authority indicators in fallback
    ai = payload["authority_indicators"]
    assert ai.get("oneapi_is_lower_horizon_only") is True
    assert ai.get("topology_readiness") == "unavailable"
    assert ai.get("topology_authoritative") is False


def test_50b_minimal_fallback_payload_includes_operational_state_keys():
    import importlib
    routes_mod = importlib.import_module("core.routes.projection")
    fallback_fn = getattr(routes_mod, "_minimal_desktop_status_board_fallback", None)
    payload = fallback_fn()
    assert "operational_state_board" in payload
    assert "source_of_truth_boundaries" in payload
    assert "shared_execution_visibility" in payload


def test_50c_desktop_status_board_assembly_includes_unified_operational_state_board():
    import importlib
    routes_mod = importlib.import_module("core.routes.projection")
    assemble_fn = getattr(routes_mod, "_assemble_desktop_status_board_payload", None)
    payload = assemble_fn(route_paths={"/api/v1/health", "/api/v1/chat", "/api/v1/projection/runtime"})
    assert "operational_state_board" in payload
    board = payload["operational_state_board"]
    assert "categories" in board and isinstance(board["categories"], list)
    category_ids = {item.get("category_id") for item in board["categories"]}
    assert "registration_state" in category_ids
    assert "result_closure_state" in category_ids
    assert "minimum_access_admission_verdict" in category_ids
    assert "shared_execution_visibility" in payload
    fingerprint = payload.get("authority_source_fingerprint")
    assert isinstance(fingerprint, dict)
    assert fingerprint.get("surface_path") == "/api/v1/projection/desktop-status-board"
    assert fingerprint.get("primary_source_kind") == "compiled_outward_truth"
    assert fingerprint.get("acts_as_authority_layer") is False


def test_50d_desktop_board_prefers_compiled_outward_truth_for_task_truth(monkeypatch):
    import importlib

    routes_mod = importlib.import_module("core.routes.projection")

    class _FakeOutwardSnapshot:
        def to_dict(self):
            return {
                "surfacing_complete": True,
                "unavailable_source_count": 0,
                "operator_snapshot": {
                    "active_task_count": 9,
                    "recent_failure_count": 4,
                    "reachable_executor_count": 7,
                },
            }

    monkeypatch.setattr(routes_mod, "_compile_outward_truth", lambda: _FakeOutwardSnapshot())
    monkeypatch.setattr(
        routes_mod,
        "_assemble_runtime_truth_payload",
        lambda: {
            "task_truth": {
                "active_task_count": 1,
                "recent_failure_count": 0,
                "reachable_executor_count": 0,
                "source": "runtime_truth_fallback",
            },
        },
    )

    payload = routes_mod._assemble_desktop_status_board_payload(route_paths={"/api/v1/projection/runtime"})
    assert payload["task_truth"]["active_task_count"] == 9
    evidence = payload.get("truth_compilation_evidence")
    assert isinstance(evidence, dict)
    assert evidence.get("primary_path") == "core.outward_runtime_truth.compile_outward_truth"
    assert evidence.get("assembly_mode") == "compiled_outward_truth_primary"


def test_50e_desktop_board_mixed_source_fallback_is_explicitly_marked(monkeypatch):
    import importlib

    routes_mod = importlib.import_module("core.routes.projection")

    monkeypatch.setattr(
        routes_mod,
        "_compile_outward_truth",
        lambda: (_ for _ in ()).throw(RuntimeError("outward unavailable")),
    )

    payload = routes_mod._assemble_desktop_status_board_payload(route_paths={"/api/v1/projection/runtime"})
    evidence = payload.get("truth_compilation_evidence")
    assert isinstance(evidence, dict)
    assert evidence.get("assembly_mode") == "mixed_source_fallback"
    assert evidence.get("fallback_used") is True
    assert evidence.get("mixed_source") is True
    assert "outward unavailable" in str(evidence.get("fallback_reason"))


# ===========================================================================
# 51-58: readiness and is_canonical convenience properties (PR-8 final)
# ===========================================================================


def test_51_payload_has_readiness_property():
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload
    payload = DesktopStatusBoardIntegrationPayload(
        model_routing_summary={},
        authority_indicators={"topology_readiness": "canonical"},
    )
    assert hasattr(payload, "readiness"), "DesktopStatusBoardIntegrationPayload missing 'readiness' property"


def test_52_readiness_property_canonical_on_canonical_path():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert result.readiness == "canonical"


def test_53_readiness_property_degraded_on_legacy_path():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_legacy_ucp()
    )
    assert result.readiness == "degraded"


def test_54_readiness_property_unknown_on_empty_authority_indicators():
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload
    payload = DesktopStatusBoardIntegrationPayload(
        model_routing_summary={},
        authority_indicators={},
    )
    assert payload.readiness == "unknown"


def test_55_payload_has_is_canonical_property():
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload
    payload = DesktopStatusBoardIntegrationPayload(
        model_routing_summary={},
        authority_indicators={"topology_authoritative": True},
    )
    assert hasattr(payload, "is_canonical"), "DesktopStatusBoardIntegrationPayload missing 'is_canonical' property"


def test_56_is_canonical_true_on_canonical_path():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    assert result.is_canonical is True


def test_57_is_canonical_false_on_legacy_path():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_legacy_ucp()
    )
    assert result.is_canonical is False


def test_58_is_canonical_false_on_minimal_payload():
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload
    payload = DesktopStatusBoardIntegrationPayload(
        model_routing_summary={},
        authority_indicators={},
    )
    assert payload.is_canonical is False


# ===========================================================================
# 59-65: build_desktop_status_board_integration_from_runtime bridge (PR-8)
# ===========================================================================


def test_59_bridge_importable_from_projection_compiler():
    from core.projection.projection_compiler import (  # noqa: F401
        build_desktop_status_board_integration_from_runtime,
    )


def test_60_bridge_importable_from_core_projection_package():
    from core.projection import (  # noqa: F401
        build_desktop_status_board_integration_from_runtime,
    )


def test_61_desktop_status_board_integration_authority_in_package_all():
    import core.projection as pkg
    assert "DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY" in pkg.__all__, (
        "DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY should be in core.projection.__all__"
    )
    assert "build_desktop_status_board_integration_from_runtime" in pkg.__all__, (
        "build_desktop_status_board_integration_from_runtime should be in core.projection.__all__"
    )


def test_62_bridge_returns_integration_payload_on_canonical_path():
    from core.projection.projection_compiler import build_desktop_status_board_integration_from_runtime
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload
    try:
        from core.continuum.types import ContinuumState, ContinuumPhase
        state = ContinuumState(phase=ContinuumPhase.MANIFEST)
        result = build_desktop_status_board_integration_from_runtime(continuum_state=state)
        assert isinstance(result, DesktopStatusBoardIntegrationPayload), (
            f"Expected DesktopStatusBoardIntegrationPayload, got {type(result)}"
        )
    except ImportError:
        pytest.skip("ContinuumState not available in this environment")


def test_63_bridge_returns_payload_with_correct_integration_authority():
    from core.projection.projection_compiler import build_desktop_status_board_integration_from_runtime
    from contracts.desktop_status_projection import (
        DesktopStatusBoardIntegrationPayload,
        DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
    )
    try:
        from core.continuum.types import ContinuumState, ContinuumPhase
        state = ContinuumState(phase=ContinuumPhase.MANIFEST)
        result = build_desktop_status_board_integration_from_runtime(continuum_state=state)
        assert isinstance(result, DesktopStatusBoardIntegrationPayload)
        assert result.integration_authority == DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY
    except ImportError:
        pytest.skip("ContinuumState not available in this environment")


def test_64_bridge_returns_non_none_on_empty_inputs():
    from core.projection.projection_compiler import build_desktop_status_board_integration_from_runtime
    try:
        from core.continuum.types import ContinuumState, ContinuumPhase
        state = ContinuumState(phase=ContinuumPhase.LIMINAL)
        result = build_desktop_status_board_integration_from_runtime(continuum_state=state)
        assert result is not None, "bridge must never return None"
    except ImportError:
        pytest.skip("ContinuumState not available in this environment")


def test_65_payload_uses_config_dict_not_deprecated_class_config():
    """DesktopStatusBoardIntegrationPayload must use model_config = ConfigDict() not class Config."""
    from contracts.desktop_status_projection import DesktopStatusBoardIntegrationPayload
    # model_config should be a dict (ConfigDict instance) on the class
    model_cfg = getattr(DesktopStatusBoardIntegrationPayload, "model_config", None)
    assert model_cfg is not None, "model_config attribute missing — class Config may still be in use"
    assert isinstance(model_cfg, dict), (
        f"model_config should be a dict (ConfigDict), got {type(model_cfg)}"
    )
    # Confirm the old class-based Config is gone
    inner_config = DesktopStatusBoardIntegrationPayload.__dict__.get("Config")
    assert inner_config is None, (
        "Deprecated 'class Config' inner class still present in DesktopStatusBoardIntegrationPayload"
    )


def test_66_to_dict_serialises_readiness_in_authority_indicators():
    from contracts.desktop_status_projection import build_desktop_status_board_integration_payload
    result = build_desktop_status_board_integration_payload(
        unified_control_plan=_canonical_ucp()
    )
    d = result.to_dict()
    ai = d.get("authority_indicators", {})
    assert "topology_readiness" in ai, "authority_indicators missing 'topology_readiness' in to_dict()"
    assert ai["topology_readiness"] == "canonical"
