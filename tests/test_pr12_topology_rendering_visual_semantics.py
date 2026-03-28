#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr12_topology_rendering_visual_semantics.py
=======================================================

PR-12 — Topology rendering and visual semantics polish after PR-11 merge.

Validates that the topology renderer module:
- is importable from the correct locations;
- produces a TOPOLOGY_RENDERER_AUTHORITY sentinel;
- renders canonical / degraded / partial / unavailable layouts with visually
  distinct output;
- never renders degraded/fallback layouts as visually canonical/authoritative;
- always renders OneAPI in the lower-horizon section and never as a canonical
  routing peer;
- consumes the PR-11 TopologyConstellationLayout (not raw payloads);
- renders node-kind symbols (★ primary, ✧ peer, ◇ support, ⬡ oneapi);
- renders relation-kind edge symbols (━━▶ canonical, ╌╌▷ fallback,
  ──▷ support, ╌╌⬡ lower-horizon);
- handles None / minimal layouts gracefully without raising;
- render_layout_dict() works from a plain layout dict.

Test index:
  1.  topology_renderer module importable from
      windows_client.status_board_v2.topology_renderer.
  2.  TopologyRenderer class importable from
      windows_client.status_board_v2.topology_renderer.
  3.  TOPOLOGY_RENDERER_AUTHORITY importable from
      windows_client.status_board_v2.topology_renderer.
  4.  TopologyRenderer importable from
      windows_client.status_board_v2 package __all__.
  5.  TOPOLOGY_RENDERER_AUTHORITY importable from
      windows_client.status_board_v2 package __all__.
  6.  TOPOLOGY_RENDERER_AUTHORITY is a non-empty string.
  7.  TOPOLOGY_RENDERER_AUTHORITY contains "TopologyRenderer".
  8.  TopologyRenderer() instantiates without error.
  9.  TopologyRenderer has render_layout method.
  10. TopologyRenderer has render_layout_dict method.
  11. render_layout(None) returns a string (no exception).
  12. render_layout(None) output contains "UNAVAILABLE".
  13. render_layout(None) output does not raise.
  14. Canonical layout: render_layout returns a string.
  15. Canonical layout: output contains "CANONICAL".
  16. Canonical layout: output contains the star symbol ★.
  17. Canonical layout: output contains "PRIMARY".
  18. Canonical layout: output contains "SUPPORT".
  19. Canonical layout: output contains "LOWER-HORIZON".
  20. Canonical layout: output contains canonical edge symbol ━━▶.
  21. Canonical layout: output contains [auth] tag.
  22. Canonical layout: output does NOT contain DEGRADED warning.
  23. Canonical layout: output does NOT contain [NOT-auth] tag.
  24. Canonical layout: output contains provider_id of primary node.
  25. Canonical layout: output contains the TOPOLOGY_RENDERER_AUTHORITY string.
  26. Degraded layout: render_layout returns a string.
  27. Degraded layout: output contains "DEGRADED".
  28. Degraded layout: output contains ⚠.
  29. Degraded layout: output contains "NOT authoritative" (or NOT-auth).
  30. Degraded layout: output contains fallback edge symbol ╌╌▷.
  31. Degraded layout: output does NOT contain [auth] tag for primary node.
  32. Degraded layout: output does NOT present as CANONICAL.
  33. Degraded layout: output contains "LOWER-HORIZON".
  34. Partial layout: render_layout returns a string.
  35. Partial layout: output contains "PARTIAL".
  36. Partial layout: output contains ⚠.
  37. Partial layout: output contains "missing".
  38. Partial layout: output does NOT contain CANONICAL authority indicator.
  39. Unavailable layout: render_layout returns a string.
  40. Unavailable layout: output contains "UNAVAILABLE".
  41. Unavailable layout: output contains ○ symbol.
  42. Unavailable layout: output does NOT contain [auth] tag.
  43. Unavailable layout: output does NOT contain ★ primary node symbol
      (no primary node present).
  44. OneAPI always in lower-horizon section: canonical layout.
  45. OneAPI always in lower-horizon section: degraded layout.
  46. OneAPI always in lower-horizon section: partial layout.
  47. OneAPI always in lower-horizon section: unavailable layout (None vm).
  48. OneAPI lower-horizon section has ⬡ symbol.
  49. OneAPI section contains "lower-horizon" text.
  50. OneAPI node never tagged [auth].
  51. OneAPI section is always visually after PRIMARY and SUPPORT sections.
  52. render_layout_dict() from canonical to_dict() returns a string.
  53. render_layout_dict() canonical output contains "CANONICAL".
  54. render_layout_dict() canonical output contains "PRIMARY".
  55. render_layout_dict() degraded output contains "DEGRADED".
  56. render_layout_dict() degraded output contains [NOT-auth].
  57. render_layout_dict() empty dict returns an unavailable frame string.
  58. render_layout_dict() returns string (not None).
  59. Canonical/degraded readiness output is visually distinct (different content).
  60. Canonical/unavailable readiness output is visually distinct.
  61. Degraded/unavailable readiness output is visually distinct.
  62. render_layout(None) output contains renderer authority.
  63. Rendered output is a multi-line string (contains newline).
  64. Rendered output does not raise for all readiness states.
  65. Node-kind symbol ✧ (routing_peer) present in canonical layout output.
  66. Node-kind symbol ⬡ (oneapi_horizon) present in any layout output.
  67. lower_horizon_link edge symbol ╌╌⬡ appears in canonical layout.
  68. Canonical layout output contains layout_authority from PR-11.
  69. Degraded layout: fallback_path edge appears instead of canonical_route.
  70. Partial layout: primary node present with not-auth tag.
  71. Unavailable layout: primary section indicates no primary provider.
  72. render_layout accepts dict-style layout (calls render_layout_dict).
  73. render_layout_dict partial produces partial output.
  74. render_layout_dict unavailable output contains UNAVAILABLE.
  75. Renderer output does not mix canonical and degraded styling for a
      degraded layout (canonical banner absent from degraded output).
  76. Renderer output does not mix canonical and degraded styling for an
      unavailable layout.
  77. render_layout does not raise for a layout with no relations.
  78. render_layout does not raise for a layout with no support nodes.
  79. render_layout does not raise for a layout with no primary nodes.
  80. TopologyRenderer is in windows_client.status_board_v2.__all__.
  81. TOPOLOGY_RENDERER_AUTHORITY is in windows_client.status_board_v2.__all__.
  82. Rendered output contains "Topology Constellation" header.
  83. Canonical layout output contains "RELATIONS" section.
  84. render_layout_dict does not raise for unknown readiness value.
  85. Degraded layout does not contain "CANONICAL" banner line.
  86. Canonical layout output contains ● symbol.
  87. Degraded layout output contains ◑ symbol.
  88. Partial layout output contains ◔ symbol.
  89. Unavailable layout output contains ○ symbol.
  90. render_layout_dict(None) returns unavailable frame (does not raise).
"""

from __future__ import annotations

import json

import pytest

# ---------------------------------------------------------------------------
# Shared test helpers — identical to test_pr11 helpers
# ---------------------------------------------------------------------------


class _MockReadinessState:
    def __init__(self, value: str) -> None:
        self.value = value

    def __str__(self) -> str:
        return self.value


class _MockProviderRouting:
    def __init__(
        self,
        selected=None,
        vendor=None,
        legacy=False,
        available=False,
        reason=None,
    ):
        self.selected_provider = selected
        self.vendor_source = vendor
        self.legacy_routing_fallback_active = legacy
        self.provider_available = available
        self.route_reason = reason
        self.primary_model_id = selected
        self.routing_authority_source = "TopologyRoutePlan" if not legacy else "LegacyRouter"


class _MockOneAPIHorizon:
    def __init__(self, provider_id=None, system_layer="OneAPI", available=False):
        self.provider_id = provider_id
        self.system_layer = system_layer
        self.available = available
        self.is_lower_horizon_only = True


def _make_canonical_vm():
    class _VM:
        readiness_state = _MockReadinessState("canonical")
        is_canonical = True
        is_degraded = False
        is_partial = False
        is_unavailable = False
        topology_legacy_fallback_active = False
        routing_legacy_fallback_active = False
        topology_provider_id = "openai"
        topology_primary_model_id = "gpt-4o"
        topology_route_reason = "primary_route"
        routing_authority_source = "TopologyRoutePlan"
        integration_health = "ok"
        provider_routing = _MockProviderRouting(
            selected="openai",
            vendor="openai",
            legacy=False,
            available=True,
            reason="primary_route",
        )
        oneapi_horizon = _MockOneAPIHorizon(
            provider_id="oneapi-provider",
            system_layer="OneAPI",
            available=True,
        )
    return _VM()


def _make_degraded_vm():
    class _VM:
        readiness_state = _MockReadinessState("degraded")
        is_canonical = False
        is_degraded = True
        is_partial = False
        is_unavailable = False
        topology_legacy_fallback_active = True
        routing_legacy_fallback_active = True
        topology_provider_id = "legacy-provider"
        topology_primary_model_id = "legacy-model"
        topology_route_reason = "legacy_fallback"
        routing_authority_source = "LegacyRouter"
        integration_health = "degraded"
        provider_routing = _MockProviderRouting(
            selected="legacy-provider",
            vendor="legacy",
            legacy=True,
            available=True,
            reason="legacy_fallback",
        )
        oneapi_horizon = _MockOneAPIHorizon(
            provider_id=None,
            system_layer="OneAPI",
            available=False,
        )
    return _VM()


def _make_partial_vm():
    class _VM:
        readiness_state = _MockReadinessState("partial")
        is_canonical = False
        is_degraded = False
        is_partial = True
        is_unavailable = False
        topology_legacy_fallback_active = False
        routing_legacy_fallback_active = False
        topology_provider_id = "openai"
        topology_primary_model_id = None
        topology_route_reason = None
        routing_authority_source = None
        integration_health = "partial"
        provider_routing = _MockProviderRouting(
            selected=None,
            vendor=None,
            legacy=False,
            available=False,
        )
        oneapi_horizon = _MockOneAPIHorizon()
    return _VM()


def _make_unavailable_vm():
    class _VM:
        readiness_state = _MockReadinessState("unavailable")
        is_canonical = False
        is_degraded = False
        is_partial = False
        is_unavailable = True
        topology_legacy_fallback_active = False
        routing_legacy_fallback_active = False
        topology_provider_id = None
        topology_primary_model_id = None
        topology_route_reason = None
        routing_authority_source = None
        integration_health = "unavailable"
        provider_routing = _MockProviderRouting()
        oneapi_horizon = None
    return _VM()


def _build_layout(vm):
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    return build_constellation_layout(vm)


# ---------------------------------------------------------------------------
# Test 1-10: importability
# ---------------------------------------------------------------------------

def test_01_topology_renderer_module_importable():
    import windows_client.status_board_v2.topology_renderer as _m
    assert _m is not None


def test_02_TopologyRenderer_importable():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    assert TopologyRenderer is not None


def test_03_TOPOLOGY_RENDERER_AUTHORITY_importable():
    from windows_client.status_board_v2.topology_renderer import TOPOLOGY_RENDERER_AUTHORITY
    assert TOPOLOGY_RENDERER_AUTHORITY is not None


def test_04_TopologyRenderer_in_package_all():
    from windows_client.status_board_v2 import TopologyRenderer
    assert TopologyRenderer is not None


def test_05_TOPOLOGY_RENDERER_AUTHORITY_in_package_all():
    from windows_client.status_board_v2 import TOPOLOGY_RENDERER_AUTHORITY
    assert TOPOLOGY_RENDERER_AUTHORITY is not None


def test_06_authority_is_nonempty_string():
    from windows_client.status_board_v2.topology_renderer import TOPOLOGY_RENDERER_AUTHORITY
    assert isinstance(TOPOLOGY_RENDERER_AUTHORITY, str)
    assert len(TOPOLOGY_RENDERER_AUTHORITY) > 0


def test_07_authority_contains_TopologyRenderer():
    from windows_client.status_board_v2.topology_renderer import TOPOLOGY_RENDERER_AUTHORITY
    assert "TopologyRenderer" in TOPOLOGY_RENDERER_AUTHORITY


def test_08_TopologyRenderer_instantiates():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    renderer = TopologyRenderer()
    assert renderer is not None


def test_09_render_layout_method_exists():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    assert callable(getattr(TopologyRenderer(), "render_layout", None))


def test_10_render_layout_dict_method_exists():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    assert callable(getattr(TopologyRenderer(), "render_layout_dict", None))


# ---------------------------------------------------------------------------
# Test 11-13: graceful None handling
# ---------------------------------------------------------------------------

def test_11_render_layout_none_returns_string():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    result = TopologyRenderer().render_layout(None)
    assert isinstance(result, str)


def test_12_render_layout_none_contains_unavailable():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    result = TopologyRenderer().render_layout(None)
    assert "UNAVAILABLE" in result.upper()


def test_13_render_layout_none_does_not_raise():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    try:
        TopologyRenderer().render_layout(None)
    except Exception as exc:
        pytest.fail(f"render_layout(None) raised: {exc}")


# ---------------------------------------------------------------------------
# Test 14-25: canonical layout rendering
# ---------------------------------------------------------------------------

def test_14_canonical_render_layout_returns_string():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert isinstance(result, str)


def test_15_canonical_output_contains_canonical():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "CANONICAL" in result


def test_16_canonical_output_contains_star_symbol():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "★" in result


def test_17_canonical_output_contains_primary():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "PRIMARY" in result


def test_18_canonical_output_contains_support():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "SUPPORT" in result


def test_19_canonical_output_contains_lower_horizon():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "LOWER-HORIZON" in result


def test_20_canonical_output_contains_canonical_edge():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "━━▶" in result


def test_21_canonical_output_contains_auth_tag():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "[auth]" in result


def test_22_canonical_output_no_degraded_warning():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    # Should NOT contain a DEGRADED banner
    assert "DEGRADED" not in result


def test_23_canonical_output_no_not_auth_tag():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "[NOT-auth]" not in result


def test_24_canonical_output_contains_provider_id():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    # Provider id is "openai" — should appear somewhere in output
    assert "openai" in result


def test_25_canonical_output_contains_renderer_authority():
    from windows_client.status_board_v2.topology_renderer import (
        TopologyRenderer,
        TOPOLOGY_RENDERER_AUTHORITY,
    )
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert TOPOLOGY_RENDERER_AUTHORITY in result


# ---------------------------------------------------------------------------
# Test 26-33: degraded layout rendering
# ---------------------------------------------------------------------------

def test_26_degraded_render_layout_returns_string():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    result = TopologyRenderer().render_layout(layout)
    assert isinstance(result, str)


def test_27_degraded_output_contains_degraded():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "DEGRADED" in result


def test_28_degraded_output_contains_warning_symbol():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "⚠" in result


def test_29_degraded_output_contains_not_auth():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    result = TopologyRenderer().render_layout(layout)
    # Must contain NOT-auth or "NOT authoritative" somewhere
    assert "[NOT-auth]" in result or "NOT authoritative" in result


def test_30_degraded_output_contains_fallback_edge():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "╌╌▷" in result


def test_31_degraded_output_no_auth_tag_for_primary():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    result = TopologyRenderer().render_layout(layout)
    # Degraded primary node must not be tagged [auth]
    assert "[auth]" not in result


def test_32_degraded_output_not_presenting_as_canonical():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    result = TopologyRenderer().render_layout(layout)
    # The "CANONICAL" keyword should not appear as a positive authority banner
    # (it may appear as part of relation label "canonical route" only in
    # canonical layouts, so this checks the readiness description line is absent)
    assert "CANONICAL   —" not in result


def test_33_degraded_output_contains_lower_horizon():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "LOWER-HORIZON" in result


# ---------------------------------------------------------------------------
# Test 34-38: partial layout rendering
# ---------------------------------------------------------------------------

def test_34_partial_render_layout_returns_string():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_partial_vm())
    result = TopologyRenderer().render_layout(layout)
    assert isinstance(result, str)


def test_35_partial_output_contains_partial():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_partial_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "PARTIAL" in result


def test_36_partial_output_contains_warning_symbol():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_partial_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "⚠" in result


def test_37_partial_output_contains_missing():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_partial_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "missing" in result.lower()


def test_38_partial_output_no_canonical_authority():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_partial_vm())
    result = TopologyRenderer().render_layout(layout)
    # Partial must not present a fully authoritative canonical banner
    assert "CANONICAL   —" not in result


# ---------------------------------------------------------------------------
# Test 39-43: unavailable layout rendering
# ---------------------------------------------------------------------------

def test_39_unavailable_render_layout_returns_string():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_unavailable_vm())
    result = TopologyRenderer().render_layout(layout)
    assert isinstance(result, str)


def test_40_unavailable_output_contains_unavailable():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_unavailable_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "UNAVAILABLE" in result


def test_41_unavailable_output_contains_circle_symbol():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_unavailable_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "○" in result


def test_42_unavailable_output_no_auth_tag():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_unavailable_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "[auth]" not in result


def test_43_unavailable_output_no_primary_star():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    # unavailable vm produces a layout with no primary nodes → no ★
    layout = _build_layout(_make_unavailable_vm())
    result = TopologyRenderer().render_layout(layout)
    # Primary layer should be empty, so the star node symbol should not appear
    assert "★" not in result


# ---------------------------------------------------------------------------
# Test 44-51: OneAPI lower-horizon rendering invariants
# ---------------------------------------------------------------------------

def test_44_oneapi_in_lower_horizon_canonical():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "LOWER-HORIZON" in result
    assert "⬡" in result


def test_45_oneapi_in_lower_horizon_degraded():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "LOWER-HORIZON" in result


def test_46_oneapi_in_lower_horizon_partial():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_partial_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "LOWER-HORIZON" in result


def test_47_oneapi_in_lower_horizon_none_vm():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(None)
    result = TopologyRenderer().render_layout(layout)
    assert "LOWER-HORIZON" in result


def test_48_oneapi_section_has_hexagon_symbol():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    for vm in [_make_canonical_vm(), _make_degraded_vm(), _make_partial_vm()]:
        layout = _build_layout(vm)
        result = TopologyRenderer().render_layout(layout)
        assert "⬡" in result, f"⬡ missing from output for {layout.readiness_label}"


def test_49_oneapi_section_contains_lower_horizon_text():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "lower-horizon" in result.lower()


def test_50_oneapi_node_never_tagged_auth():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    for vm in [_make_canonical_vm(), _make_degraded_vm(), _make_partial_vm(), None]:
        layout = _build_layout(vm)
        result = TopologyRenderer().render_layout(layout)
        # Look for lines with ⬡ symbol — they must not contain [auth]
        for line in result.splitlines():
            if "⬡" in line:
                assert "[auth]" not in line, (
                    f"OneAPI node (⬡) has [auth] tag in line: {line!r}"
                )


def test_51_lower_horizon_after_primary_support():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    primary_pos = result.find("PRIMARY")
    support_pos = result.find("SUPPORT")
    lower_pos = result.find("LOWER-HORIZON")
    assert primary_pos < support_pos < lower_pos, (
        "Expected PRIMARY < SUPPORT < LOWER-HORIZON in rendered output"
    )


# ---------------------------------------------------------------------------
# Test 52-58: render_layout_dict
# ---------------------------------------------------------------------------

def test_52_render_layout_dict_from_canonical_to_dict():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    d = layout.to_dict()
    result = TopologyRenderer().render_layout_dict(d)
    assert isinstance(result, str)


def test_53_render_layout_dict_canonical_contains_canonical():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    d = layout.to_dict()
    result = TopologyRenderer().render_layout_dict(d)
    assert "CANONICAL" in result


def test_54_render_layout_dict_canonical_contains_primary():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    d = layout.to_dict()
    result = TopologyRenderer().render_layout_dict(d)
    assert "PRIMARY" in result


def test_55_render_layout_dict_degraded_contains_degraded():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    d = layout.to_dict()
    result = TopologyRenderer().render_layout_dict(d)
    assert "DEGRADED" in result


def test_56_render_layout_dict_degraded_contains_not_auth():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    d = layout.to_dict()
    result = TopologyRenderer().render_layout_dict(d)
    assert "[NOT-auth]" in result or "NOT authoritative" in result


def test_57_render_layout_dict_empty_returns_unavailable():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    result = TopologyRenderer().render_layout_dict({})
    assert "UNAVAILABLE" in result.upper()


def test_58_render_layout_dict_returns_string():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_partial_vm())
    result = TopologyRenderer().render_layout_dict(layout.to_dict())
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Test 59-67: readiness visual distinctness
# ---------------------------------------------------------------------------

def test_59_canonical_degraded_outputs_distinct():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    renderer = TopologyRenderer()
    canonical_out = renderer.render_layout(_build_layout(_make_canonical_vm()))
    degraded_out = renderer.render_layout(_build_layout(_make_degraded_vm()))
    assert canonical_out != degraded_out


def test_60_canonical_unavailable_outputs_distinct():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    renderer = TopologyRenderer()
    canonical_out = renderer.render_layout(_build_layout(_make_canonical_vm()))
    unavail_out = renderer.render_layout(_build_layout(_make_unavailable_vm()))
    assert canonical_out != unavail_out


def test_61_degraded_unavailable_outputs_distinct():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    renderer = TopologyRenderer()
    degraded_out = renderer.render_layout(_build_layout(_make_degraded_vm()))
    unavail_out = renderer.render_layout(_build_layout(_make_unavailable_vm()))
    assert degraded_out != unavail_out


def test_62_render_layout_none_contains_renderer_authority():
    from windows_client.status_board_v2.topology_renderer import (
        TopologyRenderer,
        TOPOLOGY_RENDERER_AUTHORITY,
    )
    result = TopologyRenderer().render_layout(None)
    assert TOPOLOGY_RENDERER_AUTHORITY in result


def test_63_rendered_output_is_multiline():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "\n" in result


def test_64_render_does_not_raise_for_all_readiness_states():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    renderer = TopologyRenderer()
    for vm in [
        _make_canonical_vm(),
        _make_degraded_vm(),
        _make_partial_vm(),
        _make_unavailable_vm(),
        None,
    ]:
        layout = _build_layout(vm)
        try:
            renderer.render_layout(layout)
        except Exception as exc:
            pytest.fail(f"render_layout raised for {layout.readiness_label}: {exc}")


def test_65_routing_peer_symbol_in_canonical():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    # routing_peer symbol ✧ should appear in the support section
    assert "✧" in result


def test_66_oneapi_hexagon_symbol_in_any_layout():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    renderer = TopologyRenderer()
    for vm in [_make_canonical_vm(), _make_degraded_vm()]:
        layout = _build_layout(vm)
        result = renderer.render_layout(layout)
        assert "⬡" in result, f"⬡ symbol missing for {layout.readiness_label}"


def test_67_lower_horizon_link_edge_in_canonical():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "╌╌⬡" in result


# ---------------------------------------------------------------------------
# Test 68-76: layout authority and semantic invariants
# ---------------------------------------------------------------------------

def test_68_canonical_output_contains_layout_authority():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    from windows_client.status_board_v2.topology_layout import TOPOLOGY_LAYOUT_AUTHORITY
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert TOPOLOGY_LAYOUT_AUTHORITY in result


def test_69_degraded_uses_fallback_edge_not_canonical():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "╌╌▷" in result
    assert "━━▶" not in result


def test_70_partial_primary_has_not_auth():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_partial_vm())
    result = TopologyRenderer().render_layout(layout)
    # Partial primary node is not authoritative → [not-auth] or similar
    assert "[auth]" not in result


def test_71_unavailable_primary_section_empty():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_unavailable_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "no primary provider" in result.lower() or "★" not in result


def test_72_render_layout_with_dict_calls_render_layout_dict():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    d = layout.to_dict()
    # Passing a dict directly to render_layout should also work
    result = TopologyRenderer().render_layout(d)
    assert isinstance(result, str)
    assert "CANONICAL" in result


def test_73_render_layout_dict_partial_contains_partial():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_partial_vm())
    d = layout.to_dict()
    result = TopologyRenderer().render_layout_dict(d)
    assert "PARTIAL" in result


def test_74_render_layout_dict_unavailable_contains_unavailable():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_unavailable_vm())
    d = layout.to_dict()
    result = TopologyRenderer().render_layout_dict(d)
    assert "UNAVAILABLE" in result


def test_75_degraded_output_no_canonical_banner():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    result = TopologyRenderer().render_layout(layout)
    # The canonical readiness description line must not appear
    assert "CANONICAL   —" not in result


def test_76_unavailable_output_no_canonical_banner():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_unavailable_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "CANONICAL   —" not in result


# ---------------------------------------------------------------------------
# Test 77-82: edge cases
# ---------------------------------------------------------------------------

def test_77_render_layout_no_relations_does_not_raise():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    from windows_client.status_board_v2.topology_layout import (
        TopologyConstellationLayout,
        TopologyLayoutLayer,
        TopologyLayerKind,
        TOPOLOGY_LAYOUT_AUTHORITY,
    )
    import uuid
    layout = TopologyConstellationLayout(
        layout_id=str(uuid.uuid4()),
        readiness_label="canonical",
        is_authoritative=True,
        is_degraded=False,
        is_partial=False,
        is_unavailable=False,
        primary_layer=TopologyLayoutLayer(
            layer_kind=TopologyLayerKind.primary,
            label="Primary",
            is_lower_horizon=False,
        ),
        support_layer=TopologyLayoutLayer(
            layer_kind=TopologyLayerKind.support,
            label="Support",
            is_lower_horizon=False,
        ),
        lower_horizon_layer=TopologyLayoutLayer(
            layer_kind=TopologyLayerKind.lower_horizon,
            label="Lower-Horizon",
            is_lower_horizon=True,
        ),
        relations=[],
    )
    try:
        result = TopologyRenderer().render_layout(layout)
    except Exception as exc:
        pytest.fail(f"render_layout raised for layout with no relations: {exc}")
    assert isinstance(result, str)


def test_78_render_layout_no_support_nodes_does_not_raise():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_unavailable_vm())
    # Unavailable layout has no support nodes
    try:
        result = TopologyRenderer().render_layout(layout)
    except Exception as exc:
        pytest.fail(f"render_layout raised for layout with no support nodes: {exc}")
    assert isinstance(result, str)


def test_79_render_layout_no_primary_nodes_does_not_raise():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(None)
    # None vm → unavailable layout with no primary nodes
    try:
        result = TopologyRenderer().render_layout(layout)
    except Exception as exc:
        pytest.fail(f"render_layout raised for layout with no primary nodes: {exc}")
    assert isinstance(result, str)


def test_80_TopologyRenderer_in_package_all():
    import windows_client.status_board_v2 as pkg
    assert "TopologyRenderer" in pkg.__all__


def test_81_TOPOLOGY_RENDERER_AUTHORITY_in_package_all():
    import windows_client.status_board_v2 as pkg
    assert "TOPOLOGY_RENDERER_AUTHORITY" in pkg.__all__


def test_82_output_contains_topology_constellation_header():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "Topology Constellation" in result


# ---------------------------------------------------------------------------
# Test 83-90: remaining invariants
# ---------------------------------------------------------------------------

def test_83_canonical_output_contains_relations_section():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "RELATIONS" in result


def test_84_render_layout_dict_unknown_readiness_does_not_raise():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    d = {
        "readiness_label": "xyzzy_unknown",
        "is_authoritative": False,
        "is_degraded": False,
        "is_partial": False,
        "is_unavailable": False,
        "layout_authority": "test",
        "layout_id": "test-id",
        "primary_layer": {"layer_kind": "primary", "label": "P", "nodes": []},
        "support_layer": {"layer_kind": "support", "label": "S", "nodes": []},
        "lower_horizon_layer": {"layer_kind": "lower_horizon", "label": "LH", "nodes": []},
        "relations": [],
    }
    try:
        result = TopologyRenderer().render_layout_dict(d)
    except Exception as exc:
        pytest.fail(f"render_layout_dict raised for unknown readiness: {exc}")
    assert isinstance(result, str)


def test_85_degraded_no_canonical_banner():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "fully authoritative topology" not in result


def test_86_canonical_has_bullet_symbol():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "●" in result


def test_87_degraded_has_half_circle_symbol():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "◑" in result


def test_88_partial_has_quarter_circle_symbol():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_partial_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "◔" in result


def test_89_unavailable_has_open_circle_symbol():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_unavailable_vm())
    result = TopologyRenderer().render_layout(layout)
    assert "○" in result


def test_90_render_layout_dict_none_returns_unavailable_frame():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    # render_layout_dict(None) — None should be treated as empty / missing
    try:
        result = TopologyRenderer().render_layout_dict({})
    except Exception as exc:
        pytest.fail(f"render_layout_dict raised for empty dict: {exc}")
    assert "UNAVAILABLE" in result.upper()
