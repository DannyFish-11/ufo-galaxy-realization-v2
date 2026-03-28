#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr9_desktop_consumption_adapter.py
==============================================

PR-9 — Desktop client consumption adapter after PR-8 merge.

Validates that the desktop consumption adapter correctly converts the PR-8
integrated payload into a stable, flat client view-model; that canonical /
degraded / partial / unavailable readiness states map correctly; that OneAPI
remains lower-horizon only; that legacy fallback remains explicitly
non-authoritative; and that the adapter eliminates the need for ad-hoc field
inspection and reassembly.

Test index:
  1.  DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY importable from core.desktop_consumption_adapter.
  2.  DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY is a non-empty string.
  3.  DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY importable from core.projection package __all__.
  4.  DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY consistent across both import paths.
  5.  DesktopReadinessState importable from core.desktop_consumption_adapter.
  6.  DesktopReadinessState has 'canonical' value.
  7.  DesktopReadinessState has 'degraded' value.
  8.  DesktopReadinessState has 'partial' value.
  9.  DesktopReadinessState has 'unavailable' value.
  10. DesktopReadinessState has 'unknown' value.
  11. DesktopReadinessState is a str Enum (values are strings).
  12. DesktopClientViewModel importable from core.desktop_consumption_adapter.
  13. DesktopClientViewModel importable from core.projection package __all__.
  14. DesktopProviderRoutingSummary importable from core.desktop_consumption_adapter.
  15. DesktopOneAPIHorizonSummary importable from core.desktop_consumption_adapter.
  16. adapt_integration_payload importable from core.desktop_consumption_adapter.
  17. adapt_integration_payload importable from core.projection package __all__.
  18. adapt_integration_payload returns DesktopClientViewModel on canonical path.
  19. DesktopClientViewModel has 'view_model_id' attribute.
  20. DesktopClientViewModel has 'adapted_at' attribute.
  21. DesktopClientViewModel has 'readiness_state' attribute.
  22. DesktopClientViewModel has 'is_canonical' attribute.
  23. DesktopClientViewModel has 'is_degraded' attribute.
  24. DesktopClientViewModel has 'is_partial' attribute.
  25. DesktopClientViewModel has 'is_unavailable' attribute.
  26. DesktopClientViewModel has 'topology_legacy_fallback_active' attribute.
  27. DesktopClientViewModel has 'routing_legacy_fallback_active' attribute.
  28. DesktopClientViewModel has 'topology_provider_id' attribute.
  29. DesktopClientViewModel has 'topology_primary_model_id' attribute.
  30. DesktopClientViewModel has 'topology_route_reason' attribute.
  31. DesktopClientViewModel has 'routing_authority_source' attribute.
  32. DesktopClientViewModel has 'provider_routing' attribute (DesktopProviderRoutingSummary).
  33. DesktopClientViewModel has 'oneapi_horizon' attribute (DesktopOneAPIHorizonSummary).
  34. DesktopClientViewModel has 'oneapi_is_lower_horizon_only' attribute always True.
  35. DesktopClientViewModel has 'integration_health' attribute.
  36. DesktopClientViewModel has 'authority_indicators' attribute.
  37. DesktopClientViewModel has 'adapter_authority' attribute.
  38. adapter_authority equals DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY.
  39. DesktopClientViewModel has 'readiness_label()' method.
  40. DesktopClientViewModel has 'to_dict()' method.
  41. DesktopClientViewModel has 'to_json()' method.
  42. to_dict() returns a dict.
  43. to_dict() includes 'readiness_state' key.
  44. to_dict() includes 'is_canonical' key.
  45. to_dict() includes 'authority_indicators' key.
  46. to_dict() includes 'adapter_authority' key.
  47. to_json() returns a JSON string.
  48. Canonical path: is_canonical=True on canonical integrated payload.
  49. Canonical path: readiness_state == DesktopReadinessState.canonical.
  50. Canonical path: is_degraded=False.
  51. Canonical path: is_partial=False.
  52. Canonical path: is_unavailable=False.
  53. Canonical path: topology_legacy_fallback_active=False.
  54. Canonical path: routing_legacy_fallback_active=False.
  55. Canonical path: integration_health == 'ok'.
  56. Canonical path: readiness_label() returns 'Canonical'.
  57. Degraded/legacy path: is_canonical=False.
  58. Degraded/legacy path: readiness_state == DesktopReadinessState.degraded.
  59. Degraded/legacy path: is_degraded=True.
  60. Degraded/legacy path: topology_legacy_fallback_active=True.
  61. Degraded/legacy path: readiness_label() returns 'Degraded (legacy fallback)'.
  62. Partial path: readiness_state == DesktopReadinessState.partial.
  63. Partial path: is_partial=True.
  64. Partial path: is_canonical=False.
  65. Unavailable path: readiness_state == DesktopReadinessState.unavailable.
  66. Unavailable path: is_unavailable=True.
  67. Unavailable path: is_canonical=False.
  68. OneAPI is_lower_horizon_only always True on canonical path.
  69. OneAPI is_lower_horizon_only always True on degraded path.
  70. OneAPI is_lower_horizon_only always True on minimal/None payload.
  71. oneapi_horizon.to_dict() includes 'is_lower_horizon_only' key set to True.
  72. oneapi_horizon.system_layer is 'aggregator_integration' on canonical path.
  73. provider_routing.to_dict() includes 'selected_provider' key.
  74. provider_routing.to_dict() includes 'legacy_routing_fallback_active' key.
  75. provider_routing.legacy_routing_fallback_active=False on canonical path.
  76. provider_routing.legacy_routing_fallback_active=True on degraded path.
  77. adapt_integration_payload(None) returns DesktopClientViewModel safely.
  78. adapt_integration_payload(None) returns unknown readiness state.
  79. adapt_integration_payload(None) view-model has adapter_authority set.
  80. adapt_integration_payload on minimal payload returns DesktopClientViewModel.
  81. PR-8 authority_indicators preserved in vm.authority_indicators.
  82. PR-8 integration_authority not lost (accessible via authority_indicators).
  83. PR-7 projection_quality readiness preserved via readiness_state.
  84. PR-5 legacy_routing_fallback_active preserved in provider_routing.
  85. PR-4 OneAPI remains lower-horizon (is_lower_horizon_only always True).
  86. view_model_id starts with 'dcvm_'.
  87. adapted_at is a positive float.
  88. to_dict()['readiness_state'] is a string (enum value, not object).
  89. Canonical path: authority_indicators['topology_authoritative'] is True.
  90. Degraded path: authority_indicators['topology_authoritative'] is False.
"""

import json
import sys
import os

import pytest

# ---------------------------------------------------------------------------
# Ensure the repository root is on sys.path.
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# Helpers — build test payloads using the PR-8 builder
# ---------------------------------------------------------------------------

def _build_canonical_payload():
    """Build a canonical-path integrated payload using the same UCP format as PR-8 tests."""
    from contracts.desktop_status_projection import (
        build_desktop_status_board_integration_payload,
    )

    ucp = {
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
    return build_desktop_status_board_integration_payload(
        unified_control_plan=ucp,
        tristate="manifest",
    )


def _build_legacy_fallback_payload():
    """Build a legacy-fallback-path integrated payload."""
    from contracts.desktop_status_projection import (
        build_desktop_status_board_integration_payload,
    )

    # Use legacy UCP keys only — no canonical route plan
    ucp: dict = {
        "chosen_model": "legacy-model",
        "chosen_provider": "legacy-provider",
        "is_native_multimodal": False,
        "route_reason": "legacy_path",
    }
    return build_desktop_status_board_integration_payload(
        unified_control_plan=ucp,
    )


def _build_empty_ucp_payload():
    """Build a payload with an empty UCP (unavailable/minimal readiness)."""
    from contracts.desktop_status_projection import (
        build_desktop_status_board_integration_payload,
    )
    return build_desktop_status_board_integration_payload(
        unified_control_plan={},
    )


def _build_minimal_payload():
    """Build the minimal fallback payload (no UCP at all)."""
    from contracts.desktop_status_projection import (
        build_desktop_status_board_integration_payload,
    )
    return build_desktop_status_board_integration_payload()


# ===========================================================================
# 1–11: Sentinel and enum imports
# ===========================================================================

def test_01_adapter_authority_importable():
    from core.desktop_consumption_adapter import DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY
    assert DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY is not None


def test_02_adapter_authority_is_nonempty_string():
    from core.desktop_consumption_adapter import DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY
    assert isinstance(DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY, str)
    assert len(DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY) > 0


def test_03_adapter_authority_importable_from_projection_package():
    from core.projection import DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY
    assert DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY is not None


def test_04_adapter_authority_consistent_across_imports():
    from core.desktop_consumption_adapter import (
        DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY as A1,
    )
    from core.projection import DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY as A2
    assert A1 == A2


def test_05_readiness_state_importable():
    from core.desktop_consumption_adapter import DesktopReadinessState
    assert DesktopReadinessState is not None


def test_06_readiness_state_has_canonical():
    from core.desktop_consumption_adapter import DesktopReadinessState
    assert DesktopReadinessState.canonical.value == "canonical"


def test_07_readiness_state_has_degraded():
    from core.desktop_consumption_adapter import DesktopReadinessState
    assert DesktopReadinessState.degraded.value == "degraded"


def test_08_readiness_state_has_partial():
    from core.desktop_consumption_adapter import DesktopReadinessState
    assert DesktopReadinessState.partial.value == "partial"


def test_09_readiness_state_has_unavailable():
    from core.desktop_consumption_adapter import DesktopReadinessState
    assert DesktopReadinessState.unavailable.value == "unavailable"


def test_10_readiness_state_has_unknown():
    from core.desktop_consumption_adapter import DesktopReadinessState
    assert DesktopReadinessState.unknown.value == "unknown"


def test_11_readiness_state_is_str_enum():
    from core.desktop_consumption_adapter import DesktopReadinessState
    for member in DesktopReadinessState:
        assert isinstance(member.value, str)


# ===========================================================================
# 12–17: Class and function imports
# ===========================================================================

def test_12_client_view_model_importable_from_adapter():
    from core.desktop_consumption_adapter import DesktopClientViewModel
    assert DesktopClientViewModel is not None


def test_13_client_view_model_importable_from_projection_package():
    from core.projection import DesktopClientViewModel
    assert DesktopClientViewModel is not None


def test_14_provider_routing_summary_importable():
    from core.desktop_consumption_adapter import DesktopProviderRoutingSummary
    assert DesktopProviderRoutingSummary is not None


def test_15_oneapi_horizon_summary_importable():
    from core.desktop_consumption_adapter import DesktopOneAPIHorizonSummary
    assert DesktopOneAPIHorizonSummary is not None


def test_16_adapt_importable_from_adapter():
    from core.desktop_consumption_adapter import adapt_integration_payload
    assert callable(adapt_integration_payload)


def test_17_adapt_importable_from_projection_package():
    from core.projection import adapt_integration_payload
    assert callable(adapt_integration_payload)


# ===========================================================================
# 18: Returns DesktopClientViewModel on canonical path
# ===========================================================================

def test_18_adapt_returns_view_model_on_canonical_path():
    from core.desktop_consumption_adapter import (
        adapt_integration_payload,
        DesktopClientViewModel,
    )
    payload = _build_canonical_payload()
    vm = adapt_integration_payload(payload)
    assert isinstance(vm, DesktopClientViewModel)


# ===========================================================================
# 19–41: DesktopClientViewModel attribute presence
# ===========================================================================

def test_19_view_model_has_view_model_id():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "view_model_id")


def test_20_view_model_has_adapted_at():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "adapted_at")


def test_21_view_model_has_readiness_state():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "readiness_state")


def test_22_view_model_has_is_canonical():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "is_canonical")


def test_23_view_model_has_is_degraded():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "is_degraded")


def test_24_view_model_has_is_partial():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "is_partial")


def test_25_view_model_has_is_unavailable():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "is_unavailable")


def test_26_view_model_has_topology_legacy_fallback_active():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "topology_legacy_fallback_active")


def test_27_view_model_has_routing_legacy_fallback_active():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "routing_legacy_fallback_active")


def test_28_view_model_has_topology_provider_id():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "topology_provider_id")


def test_29_view_model_has_topology_primary_model_id():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "topology_primary_model_id")


def test_30_view_model_has_topology_route_reason():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "topology_route_reason")


def test_31_view_model_has_routing_authority_source():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "routing_authority_source")


def test_32_view_model_has_provider_routing():
    from core.desktop_consumption_adapter import (
        adapt_integration_payload,
        DesktopProviderRoutingSummary,
    )
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "provider_routing")
    assert isinstance(vm.provider_routing, DesktopProviderRoutingSummary)


def test_33_view_model_has_oneapi_horizon():
    from core.desktop_consumption_adapter import (
        adapt_integration_payload,
        DesktopOneAPIHorizonSummary,
    )
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "oneapi_horizon")
    assert isinstance(vm.oneapi_horizon, DesktopOneAPIHorizonSummary)


def test_34_view_model_oneapi_is_lower_horizon_only_always_true():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert vm.oneapi_is_lower_horizon_only is True


def test_35_view_model_has_integration_health():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "integration_health")


def test_36_view_model_has_authority_indicators():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "authority_indicators")
    assert isinstance(vm.authority_indicators, dict)


def test_37_view_model_has_adapter_authority():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert hasattr(vm, "adapter_authority")


def test_38_adapter_authority_value_correct():
    from core.desktop_consumption_adapter import (
        adapt_integration_payload,
        DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )
    vm = adapt_integration_payload(_build_canonical_payload())
    assert vm.adapter_authority == DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY


def test_39_view_model_has_readiness_label_method():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert callable(getattr(vm, "readiness_label", None))


def test_40_view_model_has_to_dict_method():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert callable(getattr(vm, "to_dict", None))


def test_41_view_model_has_to_json_method():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert callable(getattr(vm, "to_json", None))


# ===========================================================================
# 42–47: Serialisation
# ===========================================================================

def test_42_to_dict_returns_dict():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    d = vm.to_dict()
    assert isinstance(d, dict)


def test_43_to_dict_includes_readiness_state_key():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert "readiness_state" in vm.to_dict()


def test_44_to_dict_includes_is_canonical_key():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert "is_canonical" in vm.to_dict()


def test_45_to_dict_includes_authority_indicators_key():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert "authority_indicators" in vm.to_dict()


def test_46_to_dict_includes_adapter_authority_key():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert "adapter_authority" in vm.to_dict()


def test_47_to_json_returns_string():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    s = vm.to_json()
    assert isinstance(s, str)
    # Must be valid JSON
    parsed = json.loads(s)
    assert isinstance(parsed, dict)


# ===========================================================================
# 48–56: Canonical path behaviour
# ===========================================================================

def test_48_canonical_path_is_canonical_true():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert vm.is_canonical is True


def test_49_canonical_path_readiness_state_canonical():
    from core.desktop_consumption_adapter import (
        adapt_integration_payload,
        DesktopReadinessState,
    )
    vm = adapt_integration_payload(_build_canonical_payload())
    assert vm.readiness_state == DesktopReadinessState.canonical


def test_50_canonical_path_is_degraded_false():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert vm.is_degraded is False


def test_51_canonical_path_is_partial_false():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert vm.is_partial is False


def test_52_canonical_path_is_unavailable_false():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert vm.is_unavailable is False


def test_53_canonical_path_topology_legacy_fallback_active_false():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert vm.topology_legacy_fallback_active is False


def test_54_canonical_path_routing_legacy_fallback_active_false():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert vm.routing_legacy_fallback_active is False


def test_55_canonical_path_integration_health_ok():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert vm.integration_health == "ok"


def test_56_canonical_path_readiness_label_canonical():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert vm.readiness_label() == "Canonical"


# ===========================================================================
# 57–61: Degraded / legacy fallback path
# ===========================================================================

def test_57_degraded_path_is_canonical_false():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_legacy_fallback_payload())
    assert vm.is_canonical is False


def test_58_degraded_path_readiness_state_degraded():
    from core.desktop_consumption_adapter import (
        adapt_integration_payload,
        DesktopReadinessState,
    )
    vm = adapt_integration_payload(_build_legacy_fallback_payload())
    assert vm.readiness_state == DesktopReadinessState.degraded


def test_59_degraded_path_is_degraded_true():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_legacy_fallback_payload())
    assert vm.is_degraded is True


def test_60_degraded_path_topology_legacy_fallback_active_true():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_legacy_fallback_payload())
    assert vm.topology_legacy_fallback_active is True


def test_61_degraded_path_readiness_label():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_legacy_fallback_payload())
    assert vm.readiness_label() == "Degraded (legacy fallback)"


# ===========================================================================
# 62–64: Partial path
# ===========================================================================

def test_62_partial_path_readiness_state_partial():
    """Build a payload that triggers 'partial' readiness via direct authority_indicators."""
    from core.desktop_consumption_adapter import (
        adapt_integration_payload,
        DesktopReadinessState,
    )
    from contracts.desktop_status_projection import (
        DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
        DesktopStatusBoardIntegrationPayload,
        ProjectionHealthSeverity,
    )

    # Manually construct a payload with partial readiness indicators
    payload = DesktopStatusBoardIntegrationPayload(
        model_routing_summary={"selected_provider": "openai"},
        authority_indicators={
            "topology_readiness": "partial",
            "topology_authoritative": False,
            "topology_legacy_fallback_active": False,
            "model_routing_legacy_fallback_active": False,
            "oneapi_is_lower_horizon_only": True,
            "integration_contract_authority": DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
        },
        integration_authority=DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
        integration_health=ProjectionHealthSeverity.advisory,
    )
    vm = adapt_integration_payload(payload)
    assert vm.readiness_state == DesktopReadinessState.partial


def test_63_partial_path_is_partial_true():
    from core.desktop_consumption_adapter import adapt_integration_payload
    from contracts.desktop_status_projection import (
        DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
        DesktopStatusBoardIntegrationPayload,
        ProjectionHealthSeverity,
    )
    payload = DesktopStatusBoardIntegrationPayload(
        model_routing_summary={},
        authority_indicators={
            "topology_readiness": "partial",
            "topology_authoritative": False,
            "oneapi_is_lower_horizon_only": True,
            "integration_contract_authority": DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
        },
        integration_authority=DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
        integration_health=ProjectionHealthSeverity.advisory,
    )
    vm = adapt_integration_payload(payload)
    assert vm.is_partial is True


def test_64_partial_path_is_canonical_false():
    from core.desktop_consumption_adapter import adapt_integration_payload
    from contracts.desktop_status_projection import (
        DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
        DesktopStatusBoardIntegrationPayload,
        ProjectionHealthSeverity,
    )
    payload = DesktopStatusBoardIntegrationPayload(
        model_routing_summary={},
        authority_indicators={
            "topology_readiness": "partial",
            "topology_authoritative": False,
            "oneapi_is_lower_horizon_only": True,
            "integration_contract_authority": DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
        },
        integration_authority=DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
        integration_health=ProjectionHealthSeverity.advisory,
    )
    vm = adapt_integration_payload(payload)
    assert vm.is_canonical is False


# ===========================================================================
# 65–67: Unavailable path
# ===========================================================================

def test_65_unavailable_path_readiness_state():
    from core.desktop_consumption_adapter import (
        adapt_integration_payload,
        DesktopReadinessState,
    )
    vm = adapt_integration_payload(_build_empty_ucp_payload())
    assert vm.readiness_state == DesktopReadinessState.unavailable


def test_66_unavailable_path_is_unavailable_true():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_empty_ucp_payload())
    assert vm.is_unavailable is True


def test_67_unavailable_path_is_canonical_false():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_empty_ucp_payload())
    assert vm.is_canonical is False


# ===========================================================================
# 68–72: OneAPI lower-horizon enforcement
# ===========================================================================

def test_68_oneapi_is_lower_horizon_only_canonical():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert vm.oneapi_is_lower_horizon_only is True
    assert vm.oneapi_horizon.is_lower_horizon_only is True


def test_69_oneapi_is_lower_horizon_only_degraded():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_legacy_fallback_payload())
    assert vm.oneapi_is_lower_horizon_only is True
    assert vm.oneapi_horizon.is_lower_horizon_only is True


def test_70_oneapi_is_lower_horizon_only_none_payload():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(None)
    assert vm.oneapi_is_lower_horizon_only is True
    assert vm.oneapi_horizon.is_lower_horizon_only is True


def test_71_oneapi_to_dict_lower_horizon_true():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    d = vm.oneapi_horizon.to_dict()
    assert "is_lower_horizon_only" in d
    assert d["is_lower_horizon_only"] is True


def test_72_oneapi_system_layer_on_canonical_path():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    # system_layer should be 'aggregator_integration' from PR-4 OneAPI block
    assert vm.oneapi_horizon.system_layer == "aggregator_integration"


# ===========================================================================
# 73–76: DesktopProviderRoutingSummary
# ===========================================================================

def test_73_provider_routing_to_dict_has_selected_provider():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    d = vm.provider_routing.to_dict()
    assert "selected_provider" in d


def test_74_provider_routing_to_dict_has_legacy_fallback_key():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    d = vm.provider_routing.to_dict()
    assert "legacy_routing_fallback_active" in d


def test_75_provider_routing_legacy_fallback_false_canonical():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert vm.provider_routing.legacy_routing_fallback_active is False


def test_76_provider_routing_legacy_fallback_true_degraded():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_legacy_fallback_payload())
    assert vm.provider_routing.legacy_routing_fallback_active is True


# ===========================================================================
# 77–80: Safe handling of None / minimal payload
# ===========================================================================

def test_77_adapt_none_returns_view_model_safely():
    from core.desktop_consumption_adapter import (
        adapt_integration_payload,
        DesktopClientViewModel,
    )
    vm = adapt_integration_payload(None)
    assert isinstance(vm, DesktopClientViewModel)


def test_78_adapt_none_readiness_unknown():
    from core.desktop_consumption_adapter import (
        adapt_integration_payload,
        DesktopReadinessState,
    )
    vm = adapt_integration_payload(None)
    assert vm.readiness_state == DesktopReadinessState.unknown


def test_79_adapt_none_has_adapter_authority():
    from core.desktop_consumption_adapter import (
        adapt_integration_payload,
        DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )
    vm = adapt_integration_payload(None)
    assert vm.adapter_authority == DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY


def test_80_adapt_minimal_payload_returns_view_model():
    from core.desktop_consumption_adapter import (
        adapt_integration_payload,
        DesktopClientViewModel,
    )
    vm = adapt_integration_payload(_build_minimal_payload())
    assert isinstance(vm, DesktopClientViewModel)


# ===========================================================================
# 81–85: PR-4 through PR-8 contract preservation
# ===========================================================================

def test_81_pr8_authority_indicators_preserved():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    ai = vm.authority_indicators
    assert isinstance(ai, dict)
    assert "topology_authoritative" in ai


def test_82_pr8_integration_authority_in_authority_indicators():
    from core.desktop_consumption_adapter import adapt_integration_payload
    from contracts.desktop_status_projection import (
        DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
    )
    vm = adapt_integration_payload(_build_canonical_payload())
    ai = vm.authority_indicators
    assert ai.get("integration_contract_authority") == DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY


def test_83_pr7_projection_quality_readiness_preserved():
    """Verify that PR-7 topology readiness is correctly mapped to readiness_state."""
    from core.desktop_consumption_adapter import (
        adapt_integration_payload,
        DesktopReadinessState,
    )
    # Canonical payload → readiness must be canonical
    vm = adapt_integration_payload(_build_canonical_payload())
    assert vm.readiness_state in (
        DesktopReadinessState.canonical,
        DesktopReadinessState.partial,
    )
    # Degraded payload → readiness must be degraded or worse
    vm_deg = adapt_integration_payload(_build_legacy_fallback_payload())
    assert vm_deg.readiness_state in (
        DesktopReadinessState.degraded,
        DesktopReadinessState.unavailable,
        DesktopReadinessState.unknown,
    )


def test_84_pr5_legacy_routing_fallback_preserved():
    """Verify PR-5 legacy_routing_fallback_active is preserved via provider_routing."""
    from core.desktop_consumption_adapter import adapt_integration_payload
    # Canonical: no legacy fallback
    vm_can = adapt_integration_payload(_build_canonical_payload())
    assert vm_can.provider_routing.legacy_routing_fallback_active is False
    # Legacy: has legacy fallback
    vm_leg = adapt_integration_payload(_build_legacy_fallback_payload())
    assert vm_leg.provider_routing.legacy_routing_fallback_active is True


def test_85_pr4_oneapi_remains_lower_horizon():
    """Verify PR-4 OneAPI lower-horizon contract is never broken by the adapter."""
    from core.desktop_consumption_adapter import adapt_integration_payload

    for payload in [
        _build_canonical_payload(),
        _build_legacy_fallback_payload(),
        _build_empty_ucp_payload(),
        _build_minimal_payload(),
        None,
    ]:
        vm = adapt_integration_payload(payload)
        assert vm.oneapi_is_lower_horizon_only is True, (
            f"oneapi_is_lower_horizon_only must always be True — failed for {type(payload)}"
        )
        assert vm.oneapi_horizon.is_lower_horizon_only is True


# ===========================================================================
# 86–90: Misc / formatting
# ===========================================================================

def test_86_view_model_id_starts_with_dcvm():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert vm.view_model_id.startswith("dcvm_")


def test_87_adapted_at_is_positive_float():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert isinstance(vm.adapted_at, float)
    assert vm.adapted_at > 0


def test_88_to_dict_readiness_state_is_string():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    d = vm.to_dict()
    assert isinstance(d["readiness_state"], str)


def test_89_canonical_path_authority_indicators_topology_authoritative_true():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_canonical_payload())
    assert vm.authority_indicators.get("topology_authoritative") is True


def test_90_degraded_path_authority_indicators_topology_authoritative_false():
    from core.desktop_consumption_adapter import adapt_integration_payload
    vm = adapt_integration_payload(_build_legacy_fallback_payload())
    assert vm.authority_indicators.get("topology_authoritative") is False
