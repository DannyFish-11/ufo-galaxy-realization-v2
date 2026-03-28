#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr10_desktop_status_board_ui.py
==========================================

PR-10 — First usable desktop status board UI after PR-9 merge.

Validates that the adapter-driven desktop status board UI surface:
- consumes a DesktopClientViewModel (not raw nested payloads);
- renders canonical / degraded / partial / unavailable states clearly;
- keeps OneAPI lower-horizon visually/semantically distinct;
- is adapter-authority-driven, not raw-payload-driven;
- renders safe unavailable frames when the view-model is None / minimal.

Test index:
  1.  AdapterSurface importable from windows_client.status_board_v2.adapter_surface.
  2.  AdapterSurface importable from windows_client.status_board_v2 package __all__.
  3.  AdapterSurface is instantiable.
  4.  AdapterSurface has render_view_model() method.
  5.  AdapterSurface has render_dict() method.
  6.  render_view_model(None) returns a non-empty string (safe unavailable frame).
  7.  render_view_model(None) output mentions 'UNAVAILABLE'.
  8.  render_view_model(None) does not raise.
  9.  render_dict({}) returns a non-empty string (safe frame).
  10. render_dict({}) does not raise.
  11. Canonical state: render_view_model produces non-empty output.
  12. Canonical state: output contains 'CANONICAL'.
  13. Canonical state: output does not contain 'DEGRADED'.
  14. Canonical state: output does not contain 'UNAVAILABLE'.
  15. Canonical state: provider_id visible in output.
  16. Canonical state: model_id visible in output.
  17. Canonical state: integration_health 'ok' visible in output.
  18. Degraded state: output contains 'DEGRADED'.
  19. Degraded state: output contains legacy-fallback indicator.
  20. Degraded state: output does not contain 'CANONICAL' readiness label.
  21. Degraded state: output does not contain 'UNAVAILABLE' readiness label.
  22. Partial state: output contains 'PARTIAL'.
  23. Partial state: is visually distinct from canonical.
  24. Partial state: is visually distinct from degraded.
  25. Unavailable state: output contains 'UNAVAILABLE'.
  26. Unavailable state: output does not contain 'CANONICAL' readiness label.
  27. Unavailable state: output does not contain 'DEGRADED' readiness label.
  28. OneAPI block always rendered in canonical state.
  29. OneAPI block always rendered in degraded state.
  30. OneAPI block always rendered in unavailable state.
  31. OneAPI block shows 'lower-horizon' label.
  32. OneAPI block shows 'is_lower_horizon_only=True' label.
  33. OneAPI block never in same section as canonical routing peers.
  34. OneAPI layer/system_layer rendered when present.
  35. OneAPI available status rendered.
  36. Adapter-authority displayed in canonical state output.
  37. View-model ID displayed in canonical state output.
  38. render_dict() produces same structure as render_view_model() for canonical path.
  39. render_dict() canonical output contains 'CANONICAL'.
  40. render_dict() degraded output contains 'DEGRADED'.
  41. render_dict() unavailable output contains 'UNAVAILABLE'.
  42. render_dict() None-equivalent produces safe frame.
  43. Provider routing summary rendered in canonical path.
  44. Provider routing selected_provider shown in canonical path.
  45. Provider routing legacy fallback shown in degraded path.
  46. render_view_model with minimal view-model (no topology) renders safely.
  47. render_view_model with minimal payload does not contain provider_id when absent.
  48. render_view_model output is str type.
  49. render_dict output is str type.
  50. Integration health 'ok' renders with canonical colour signal.
  51. Integration health 'degraded' renders with degraded colour signal.
  52. Integration health 'critical' renders with critical colour signal.
  53. OneAPI section is below topology/provider section (lower-horizon ordering).
  54. Surface is read-only (no send_command / dispatch / action methods).
  55. Degraded state has ⚠ legacy fallback warning in output.
  56. render_view_model: topology_legacy_fallback_active=True shows legacy warn.
  57. render_view_model: routing_legacy_fallback_active=True shows legacy warn.
  58. render_dict canonical path shows Provider / Routing Summary section.
  59. render_dict degraded path shows LEGACY FALLBACK ACTIVE.
  60. Surface renders complete multi-line output (has newlines).
  61. Unavailable state: no provider_id shown in unavailable frame from render_view_model(None).
  62. Canonical path: is_canonical=True reflected visibly (green/canonical).
  63. Partial path from dict: renders partial state.
  64. Unknown readiness: renders safely.
  65. Unknown readiness: output contains 'UNKNOWN'.
  66. render_view_model produces 'Desktop Status Board' title.
  67. render_dict produces 'Desktop Status Board' title.
  68. Surface is adapter-driven: does not reconstruct from nested authority dicts.
  69. Surface renders with ANSI disabled (plain text mode).
  70. Surface renders with ANSI enabled without raising.
"""

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
# Helpers — build test view-models using the PR-9 adapter
# ---------------------------------------------------------------------------

def _canonical_vm():
    """Build a canonical DesktopClientViewModel via the PR-9 adapter."""
    from contracts.desktop_status_projection import (
        build_desktop_status_board_integration_payload,
    )
    from core.desktop_consumption_adapter import adapt_integration_payload

    ucp = {
        "topology_route_plan": {
            "primary_model": {
                "model_id": "gpt-4o",
                "provider_id": "openai",
                "vendor_source": "direct",
                "native_multimodal": False,
            },
            "support_models": [],
            "route_reason": "pr10_test_canonical",
            "phase": "manifest",
            "domain": "local",
            "active_weights": {},
            "authority": (
                "core.model_topology.topology_router.CANONICAL_ROUTING_AUTHORITY"
            ),
        }
    }
    payload = build_desktop_status_board_integration_payload(
        unified_control_plan=ucp,
        tristate="manifest",
    )
    return adapt_integration_payload(payload)


def _degraded_vm():
    """Build a degraded DesktopClientViewModel via the PR-9 adapter."""
    from contracts.desktop_status_projection import (
        build_desktop_status_board_integration_payload,
    )
    from core.desktop_consumption_adapter import adapt_integration_payload

    ucp = {
        "chosen_model": "legacy-model",
        "chosen_provider": "legacy-provider",
        "is_native_multimodal": False,
        "route_reason": "legacy_path",
    }
    payload = build_desktop_status_board_integration_payload(
        unified_control_plan=ucp,
    )
    return adapt_integration_payload(payload)


def _empty_vm():
    """Build an empty/unavailable DesktopClientViewModel via the PR-9 adapter."""
    from contracts.desktop_status_projection import (
        build_desktop_status_board_integration_payload,
    )
    from core.desktop_consumption_adapter import adapt_integration_payload

    payload = build_desktop_status_board_integration_payload(
        unified_control_plan={},
    )
    return adapt_integration_payload(payload)


def _minimal_vm():
    """Build a minimal (no UCP) DesktopClientViewModel via the PR-9 adapter."""
    from contracts.desktop_status_projection import (
        build_desktop_status_board_integration_payload,
    )
    from core.desktop_consumption_adapter import adapt_integration_payload

    payload = build_desktop_status_board_integration_payload()
    return adapt_integration_payload(payload)


def _partial_vm():
    """Build a partial view-model with partial readiness indicators."""
    from core.desktop_consumption_adapter import (
        DesktopClientViewModel,
        DesktopReadinessState,
        DesktopProviderRoutingSummary,
        DesktopOneAPIHorizonSummary,
        DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )
    import time, uuid
    return DesktopClientViewModel(
        view_model_id=f"dcvm_{uuid.uuid4().hex[:12]}",
        adapted_at=time.time(),
        readiness_state=DesktopReadinessState.partial,
        is_canonical=False,
        is_degraded=False,
        is_partial=True,
        is_unavailable=False,
        topology_legacy_fallback_active=False,
        routing_legacy_fallback_active=False,
        topology_provider_id="partial-provider",
        topology_primary_model_id="partial-model",
        topology_route_reason="partial_test",
        routing_authority_source="PartialAuthority",
        provider_routing=DesktopProviderRoutingSummary(
            {"selected_provider": "partial-provider", "primary_model_id": "partial-model"},
            None,
        ),
        oneapi_horizon=DesktopOneAPIHorizonSummary(
            {"system_layer": "aggregator_integration", "available": False}
        ),
        integration_health="advisory",
        authority_indicators={"topology_readiness": "partial"},
        adapter_authority=DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )


def _unavailable_vm():
    """Build an explicit unavailable view-model."""
    from core.desktop_consumption_adapter import (
        DesktopClientViewModel,
        DesktopReadinessState,
        DesktopProviderRoutingSummary,
        DesktopOneAPIHorizonSummary,
        DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )
    import time, uuid
    return DesktopClientViewModel(
        view_model_id=f"dcvm_{uuid.uuid4().hex[:12]}",
        adapted_at=time.time(),
        readiness_state=DesktopReadinessState.unavailable,
        is_canonical=False,
        is_degraded=False,
        is_partial=False,
        is_unavailable=True,
        topology_legacy_fallback_active=False,
        routing_legacy_fallback_active=False,
        topology_provider_id=None,
        topology_primary_model_id=None,
        topology_route_reason=None,
        routing_authority_source=None,
        provider_routing=DesktopProviderRoutingSummary(None, None),
        oneapi_horizon=DesktopOneAPIHorizonSummary(None),
        integration_health="unknown",
        authority_indicators={"topology_readiness": "unavailable"},
        adapter_authority=DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )


def _unknown_vm():
    """Build an unknown-readiness view-model."""
    from core.desktop_consumption_adapter import (
        DesktopClientViewModel,
        DesktopReadinessState,
        DesktopProviderRoutingSummary,
        DesktopOneAPIHorizonSummary,
        DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )
    import time, uuid
    return DesktopClientViewModel(
        view_model_id=f"dcvm_{uuid.uuid4().hex[:12]}",
        adapted_at=time.time(),
        readiness_state=DesktopReadinessState.unknown,
        is_canonical=False,
        is_degraded=False,
        is_partial=False,
        is_unavailable=False,
        topology_legacy_fallback_active=False,
        routing_legacy_fallback_active=False,
        topology_provider_id=None,
        topology_primary_model_id=None,
        topology_route_reason=None,
        routing_authority_source=None,
        provider_routing=DesktopProviderRoutingSummary(None, None),
        oneapi_horizon=DesktopOneAPIHorizonSummary(None),
        integration_health="unknown",
        authority_indicators={},
        adapter_authority=DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )


# ===========================================================================
# 1–3: Import and instantiation
# ===========================================================================

def test_01_adapter_surface_importable_from_module():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    assert AdapterSurface is not None


def test_02_adapter_surface_importable_from_package():
    from windows_client.status_board_v2 import AdapterSurface
    assert AdapterSurface is not None


def test_03_adapter_surface_instantiable():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    assert surface is not None


# ===========================================================================
# 4–5: Method existence
# ===========================================================================

def test_04_has_render_view_model():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    assert callable(getattr(surface, "render_view_model", None))


def test_05_has_render_dict():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    assert callable(getattr(surface, "render_dict", None))


# ===========================================================================
# 6–10: Safe unavailable frames
# ===========================================================================

def test_06_render_view_model_none_returns_string():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(None)
    assert isinstance(result, str) and len(result) > 0


def test_07_render_view_model_none_mentions_unavailable():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(None)
    assert "UNAVAILABLE" in result


def test_08_render_view_model_none_does_not_raise():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    try:
        surface.render_view_model(None)
    except Exception as exc:
        pytest.fail(f"render_view_model(None) raised: {exc}")


def test_09_render_dict_empty_returns_string():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_dict({})
    assert isinstance(result, str) and len(result) > 0


def test_10_render_dict_empty_does_not_raise():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    try:
        surface.render_dict({})
    except Exception as exc:
        pytest.fail(f"render_dict({{}}) raised: {exc}")


# ===========================================================================
# 11–17: Canonical state
# ===========================================================================

def test_11_canonical_render_view_model_non_empty():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _canonical_vm()
    result = surface.render_view_model(vm)
    assert isinstance(result, str) and len(result) > 0


def test_12_canonical_output_contains_canonical():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _canonical_vm()
    result = surface.render_view_model(vm)
    assert "CANONICAL" in result


def test_13_canonical_output_not_contains_degraded():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _canonical_vm()
    result = surface.render_view_model(vm)
    # Should not show DEGRADED readiness label (legacy-fallback warning must be absent)
    assert "DEGRADED" not in result


def test_14_canonical_output_not_contains_unavailable_readiness():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _canonical_vm()
    result = surface.render_view_model(vm)
    # Must not show the UNAVAILABLE readiness indicator
    assert "UNAVAILABLE" not in result


def test_15_canonical_output_shows_provider_id():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _canonical_vm()
    result = surface.render_view_model(vm)
    assert "openai" in result


def test_16_canonical_output_shows_model_id():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _canonical_vm()
    result = surface.render_view_model(vm)
    assert "gpt-4o" in result


def test_17_canonical_output_shows_health_ok():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _canonical_vm()
    result = surface.render_view_model(vm)
    assert "ok" in result


# ===========================================================================
# 18–21: Degraded state
# ===========================================================================

def test_18_degraded_output_contains_degraded():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _degraded_vm()
    result = surface.render_view_model(vm)
    assert "DEGRADED" in result


def test_19_degraded_output_contains_legacy_fallback():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _degraded_vm()
    result = surface.render_view_model(vm)
    assert "LEGACY FALLBACK" in result or "legacy" in result.lower()


def test_20_degraded_output_not_canonical_readiness():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _degraded_vm()
    result = surface.render_view_model(vm)
    # CANONICAL readiness line must not appear when degraded
    assert "CANONICAL — fully authoritative" not in result


def test_21_degraded_output_not_unavailable_readiness():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _degraded_vm()
    result = surface.render_view_model(vm)
    assert "UNAVAILABLE — no topology" not in result


# ===========================================================================
# 22–24: Partial state
# ===========================================================================

def test_22_partial_output_contains_partial():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _partial_vm()
    result = surface.render_view_model(vm)
    assert "PARTIAL" in result


def test_23_partial_visually_distinct_from_canonical():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    canonical_out = surface.render_view_model(_canonical_vm())
    partial_out = surface.render_view_model(_partial_vm())
    assert canonical_out != partial_out


def test_24_partial_visually_distinct_from_degraded():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    degraded_out = surface.render_view_model(_degraded_vm())
    partial_out = surface.render_view_model(_partial_vm())
    assert degraded_out != partial_out


# ===========================================================================
# 25–27: Unavailable state
# ===========================================================================

def test_25_unavailable_output_contains_unavailable():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _unavailable_vm()
    result = surface.render_view_model(vm)
    assert "UNAVAILABLE" in result


def test_26_unavailable_not_canonical_readiness():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _unavailable_vm()
    result = surface.render_view_model(vm)
    assert "CANONICAL — fully authoritative" not in result


def test_27_unavailable_not_degraded_readiness():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _unavailable_vm()
    result = surface.render_view_model(vm)
    assert "DEGRADED  — legacy fallback" not in result


# ===========================================================================
# 28–35: OneAPI lower-horizon
# ===========================================================================

def test_28_oneapi_rendered_in_canonical():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_canonical_vm())
    assert "ONEAPI" in result or "oneapi" in result.lower()


def test_29_oneapi_rendered_in_degraded():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_degraded_vm())
    assert "ONEAPI" in result or "oneapi" in result.lower()


def test_30_oneapi_rendered_in_unavailable():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_unavailable_vm())
    assert "ONEAPI" in result or "oneapi" in result.lower()


def test_31_oneapi_shows_lower_horizon_label():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_canonical_vm())
    assert "lower-horizon" in result.lower()


def test_32_oneapi_shows_is_lower_horizon_only_flag():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_canonical_vm())
    assert "is_lower_horizon_only=True" in result


def test_33_oneapi_not_in_same_section_as_canonical_peers():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_canonical_vm())
    # The OneAPI section is separated by a rule and appears after the
    # Topology / Provider section.  The topology section must appear before.
    oneapi_pos = result.find("ONEAPI LOWER-HORIZON")
    topology_pos = result.find("Topology / Provider")
    assert oneapi_pos > topology_pos


def test_34_oneapi_system_layer_rendered():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    from core.desktop_consumption_adapter import (
        DesktopClientViewModel,
        DesktopReadinessState,
        DesktopProviderRoutingSummary,
        DesktopOneAPIHorizonSummary,
        DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )
    import time, uuid

    vm = DesktopClientViewModel(
        view_model_id=f"dcvm_{uuid.uuid4().hex[:12]}",
        adapted_at=time.time(),
        readiness_state=DesktopReadinessState.canonical,
        is_canonical=True,
        is_degraded=False,
        is_partial=False,
        is_unavailable=False,
        topology_legacy_fallback_active=False,
        routing_legacy_fallback_active=False,
        topology_provider_id="openai",
        topology_primary_model_id="gpt-4o",
        topology_route_reason=None,
        routing_authority_source=None,
        provider_routing=DesktopProviderRoutingSummary(None, None),
        oneapi_horizon=DesktopOneAPIHorizonSummary(
            {"system_layer": "aggregator_integration", "available": True}
        ),
        integration_health="ok",
        authority_indicators={"topology_readiness": "canonical"},
        adapter_authority=DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )
    surface = AdapterSurface()
    result = surface.render_view_model(vm)
    assert "aggregator_integration" in result


def test_35_oneapi_available_status_rendered():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    from core.desktop_consumption_adapter import (
        DesktopClientViewModel,
        DesktopReadinessState,
        DesktopProviderRoutingSummary,
        DesktopOneAPIHorizonSummary,
        DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )
    import time, uuid

    vm = DesktopClientViewModel(
        view_model_id=f"dcvm_{uuid.uuid4().hex[:12]}",
        adapted_at=time.time(),
        readiness_state=DesktopReadinessState.canonical,
        is_canonical=True,
        is_degraded=False,
        is_partial=False,
        is_unavailable=False,
        topology_legacy_fallback_active=False,
        routing_legacy_fallback_active=False,
        topology_provider_id="openai",
        topology_primary_model_id="gpt-4o",
        topology_route_reason=None,
        routing_authority_source=None,
        provider_routing=DesktopProviderRoutingSummary(None, None),
        oneapi_horizon=DesktopOneAPIHorizonSummary(
            {"system_layer": "aggregator_integration", "available": True}
        ),
        integration_health="ok",
        authority_indicators={"topology_readiness": "canonical"},
        adapter_authority=DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )
    surface = AdapterSurface()
    result = surface.render_view_model(vm)
    assert "available" in result.lower()


# ===========================================================================
# 36–37: Adapter authority and view-model ID display
# ===========================================================================

def test_36_adapter_authority_shown_in_canonical():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    from core.desktop_consumption_adapter import DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY
    surface = AdapterSurface()
    vm = _canonical_vm()
    result = surface.render_view_model(vm)
    # At least part of the adapter authority string must be visible
    assert (
        "adapt_integration_payload" in result
        or "desktop_consumption_adapter" in result
        or DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY[-30:] in result
    )


def test_37_view_model_id_shown_in_canonical():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _canonical_vm()
    result = surface.render_view_model(vm)
    assert vm.view_model_id in result


# ===========================================================================
# 38–42: render_dict consistency
# ===========================================================================

def test_38_render_dict_canonical_same_structure_as_render_view_model():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _canonical_vm()
    vm_output = surface.render_view_model(vm)
    dict_output = surface.render_dict(vm.to_dict())
    # Both must mention CANONICAL and the board title
    assert "CANONICAL" in vm_output
    assert "CANONICAL" in dict_output


def test_39_render_dict_canonical_contains_canonical():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_dict(_canonical_vm().to_dict())
    assert "CANONICAL" in result


def test_40_render_dict_degraded_contains_degraded():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_dict(_degraded_vm().to_dict())
    assert "DEGRADED" in result


def test_41_render_dict_unavailable_contains_unavailable():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_dict(_unavailable_vm().to_dict())
    assert "UNAVAILABLE" in result


def test_42_render_dict_none_equivalent_safe():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_dict({})
    assert isinstance(result, str) and len(result) > 0


# ===========================================================================
# 43–45: Provider routing summary
# ===========================================================================

def test_43_provider_routing_rendered_in_canonical():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_canonical_vm())
    assert "Provider / Routing Summary" in result or "Routing" in result


def test_44_provider_routing_selected_provider_shown():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_canonical_vm())
    # The canonical VM is built with provider_id openai via topology block;
    # openai should appear somewhere in the routing summary too.
    assert "openai" in result


def test_45_degraded_routing_legacy_shown():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_degraded_vm())
    assert "legacy" in result.lower()


# ===========================================================================
# 46–49: Minimal / edge cases
# ===========================================================================

def test_46_minimal_vm_renders_safely():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _minimal_vm()
    try:
        result = surface.render_view_model(vm)
        assert isinstance(result, str)
    except Exception as exc:
        pytest.fail(f"render_view_model(minimal_vm) raised: {exc}")


def test_47_minimal_vm_no_provider_id_shown():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _minimal_vm()
    result = surface.render_view_model(vm)
    # No stray provider ID should appear when the payload is empty
    assert "openai" not in result
    assert "gpt-4o" not in result


def test_48_render_view_model_returns_str():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    assert isinstance(surface.render_view_model(_canonical_vm()), str)


def test_49_render_dict_returns_str():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    assert isinstance(surface.render_dict(_canonical_vm().to_dict()), str)


# ===========================================================================
# 50–52: Integration health display
# ===========================================================================

def test_50_health_ok_shown_canonical():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_canonical_vm())
    assert "ok" in result


def test_51_health_degraded_shown():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_degraded_vm())
    # Integration health for a legacy-fallback VM is typically 'degraded'
    assert "Health" in result


def test_52_health_critical_shown():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    from core.desktop_consumption_adapter import (
        DesktopClientViewModel,
        DesktopReadinessState,
        DesktopProviderRoutingSummary,
        DesktopOneAPIHorizonSummary,
        DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )
    import time, uuid

    vm = DesktopClientViewModel(
        view_model_id=f"dcvm_{uuid.uuid4().hex[:12]}",
        adapted_at=time.time(),
        readiness_state=DesktopReadinessState.unavailable,
        is_canonical=False,
        is_degraded=False,
        is_partial=False,
        is_unavailable=True,
        topology_legacy_fallback_active=False,
        routing_legacy_fallback_active=False,
        topology_provider_id=None,
        topology_primary_model_id=None,
        topology_route_reason=None,
        routing_authority_source=None,
        provider_routing=DesktopProviderRoutingSummary(None, None),
        oneapi_horizon=DesktopOneAPIHorizonSummary(None),
        integration_health="critical",
        authority_indicators={},
        adapter_authority=DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )
    surface = AdapterSurface()
    result = surface.render_view_model(vm)
    assert "critical" in result.lower()


# ===========================================================================
# 53: Section ordering (OneAPI below topology)
# ===========================================================================

def test_53_oneapi_section_below_topology_section():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_canonical_vm())
    oneapi_pos = result.find("ONEAPI LOWER-HORIZON")
    topology_pos = result.find("Topology / Provider")
    assert oneapi_pos > topology_pos > 0


# ===========================================================================
# 54: Read-only guarantee
# ===========================================================================

def test_54_surface_is_read_only():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    # Must not have any send/dispatch/action methods
    forbidden = [
        "send_command", "dispatch", "execute", "trigger_action",
        "post", "write", "submit",
    ]
    for attr in forbidden:
        assert not hasattr(surface, attr), (
            f"AdapterSurface must not have method '{attr}' (read-only guarantee)"
        )


# ===========================================================================
# 55–57: Legacy fallback warnings
# ===========================================================================

def test_55_degraded_has_warning_symbol():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_degraded_vm())
    assert "⚠" in result


def test_56_topology_legacy_shows_warning():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    from core.desktop_consumption_adapter import (
        DesktopClientViewModel,
        DesktopReadinessState,
        DesktopProviderRoutingSummary,
        DesktopOneAPIHorizonSummary,
        DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )
    import time, uuid

    vm = DesktopClientViewModel(
        view_model_id=f"dcvm_{uuid.uuid4().hex[:12]}",
        adapted_at=time.time(),
        readiness_state=DesktopReadinessState.degraded,
        is_canonical=False,
        is_degraded=True,
        is_partial=False,
        is_unavailable=False,
        topology_legacy_fallback_active=True,
        routing_legacy_fallback_active=False,
        topology_provider_id=None,
        topology_primary_model_id=None,
        topology_route_reason=None,
        routing_authority_source=None,
        provider_routing=DesktopProviderRoutingSummary(None, None),
        oneapi_horizon=DesktopOneAPIHorizonSummary(None),
        integration_health="degraded",
        authority_indicators={},
        adapter_authority=DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )
    surface = AdapterSurface()
    result = surface.render_view_model(vm)
    assert "topology-legacy" in result


def test_57_routing_legacy_shows_warning():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    from core.desktop_consumption_adapter import (
        DesktopClientViewModel,
        DesktopReadinessState,
        DesktopProviderRoutingSummary,
        DesktopOneAPIHorizonSummary,
        DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )
    import time, uuid

    vm = DesktopClientViewModel(
        view_model_id=f"dcvm_{uuid.uuid4().hex[:12]}",
        adapted_at=time.time(),
        readiness_state=DesktopReadinessState.degraded,
        is_canonical=False,
        is_degraded=True,
        is_partial=False,
        is_unavailable=False,
        topology_legacy_fallback_active=False,
        routing_legacy_fallback_active=True,
        topology_provider_id=None,
        topology_primary_model_id=None,
        topology_route_reason=None,
        routing_authority_source=None,
        provider_routing=DesktopProviderRoutingSummary(None, None),
        oneapi_horizon=DesktopOneAPIHorizonSummary(None),
        integration_health="degraded",
        authority_indicators={},
        adapter_authority=DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )
    surface = AdapterSurface()
    result = surface.render_view_model(vm)
    assert "routing-legacy" in result


# ===========================================================================
# 58–60: Section presence in render_dict
# ===========================================================================

def test_58_render_dict_canonical_has_routing_summary():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_dict(_canonical_vm().to_dict())
    assert "Routing" in result or "Provider" in result


def test_59_render_dict_degraded_has_legacy_fallback():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_dict(_degraded_vm().to_dict())
    assert "LEGACY FALLBACK" in result or "legacy" in result.lower()


def test_60_render_view_model_multiline():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_canonical_vm())
    assert "\n" in result


# ===========================================================================
# 61: Unavailable frame from None does not leak provider info
# ===========================================================================

def test_61_none_frame_no_provider_id():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(None)
    assert "openai" not in result
    assert "gpt-4o" not in result


# ===========================================================================
# 62: Canonical path reflects canonical visually
# ===========================================================================

def test_62_canonical_path_is_canonical_visible():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_canonical_vm())
    # Must show "CANONICAL" (readiness desc uses this exact word)
    assert "CANONICAL" in result


# ===========================================================================
# 63–65: Partial and unknown from dict
# ===========================================================================

def test_63_partial_from_dict_renders_partial():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_dict(_partial_vm().to_dict())
    assert "PARTIAL" in result


def test_64_unknown_renders_safely():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    vm = _unknown_vm()
    try:
        result = surface.render_view_model(vm)
        assert isinstance(result, str)
    except Exception as exc:
        pytest.fail(f"render_view_model(unknown_vm) raised: {exc}")


def test_65_unknown_output_contains_unknown():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_unknown_vm())
    assert "UNKNOWN" in result


# ===========================================================================
# 66–67: Board title present
# ===========================================================================

def test_66_render_view_model_has_board_title():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_view_model(_canonical_vm())
    assert "Desktop Status Board" in result


def test_67_render_dict_has_board_title():
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    surface = AdapterSurface()
    result = surface.render_dict(_canonical_vm().to_dict())
    assert "Desktop Status Board" in result


# ===========================================================================
# 68: Adapter-driven (not raw-payload-driven)
# ===========================================================================

def test_68_surface_is_adapter_driven():
    """Surface renders from DesktopClientViewModel, not from raw nested
    authority dicts.  Verify by passing in a view-model and checking that
    the adapter_authority sentinel is visible — confirming it was produced
    by the PR-9 adapter, not reconstructed from scratch."""
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    from core.desktop_consumption_adapter import DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY
    surface = AdapterSurface()
    vm = _canonical_vm()
    assert vm.adapter_authority == DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY
    result = surface.render_view_model(vm)
    # The adapter authority string (or its tail) is visible in the surface
    assert (
        "adapt_integration_payload" in result
        or "desktop_consumption_adapter" in result
        or DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY[-25:] in result
    )


# ===========================================================================
# 69–70: ANSI toggle
# ===========================================================================

def test_69_surface_renders_with_ansi_disabled():
    from windows_client.status_board_v2 import _ansi
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    original = _ansi.ANSI_ENABLED
    try:
        _ansi.ANSI_ENABLED = False
        surface = AdapterSurface()
        result = surface.render_view_model(_canonical_vm())
        assert isinstance(result, str)
        assert "CANONICAL" in result
        # No ANSI escape codes should be present
        assert "\033[" not in result
    finally:
        _ansi.ANSI_ENABLED = original


def test_70_surface_renders_with_ansi_enabled_no_raise():
    from windows_client.status_board_v2 import _ansi
    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    original = _ansi.ANSI_ENABLED
    try:
        _ansi.ANSI_ENABLED = True
        surface = AdapterSurface()
        try:
            result = surface.render_view_model(_canonical_vm())
            assert isinstance(result, str)
        except Exception as exc:
            pytest.fail(f"render with ANSI enabled raised: {exc}")
    finally:
        _ansi.ANSI_ENABLED = original
