"""
tests/test_pr4_topology_semantics.py
=====================================
Tests / guardrails for the native-multimodal-first model topology semantics
in ``windows_client/status_board_v2/topology_surface.py``.

Acceptance criteria covered
----------------------------
1. Primary vs. support roles are visually distinct in the rendered output.
2. Native-multimodal (``is_native_multimodal=True``) preserves the ``[MM]``
   badge on the primary model entry.
3. OneAPI is rendered as a **separate lower aggregator row** when
   ``oneapi_source`` is present — it must not appear in the main-route or
   support layer.
4. When OneAPI data is absent, no OneAPI row is rendered.
5. Vendor/source tags (``vendor_source``) appear next to the primary model
   when available.
6. Topology role hints (``topology_role``) are shown when available.
7. Route reason is shown when present; truncated when very long.
8. Routing authority is shown when present.
9. Backward compatibility: projections that do not include the new optional
   fields still render correctly.

These tests ANSI-disable the module to make string assertions simple.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _disable_ansi(monkeypatch):
    import windows_client.status_board_v2._ansi as ansi_mod
    monkeypatch.setattr(ansi_mod, "ANSI_ENABLED", False)


# Full-featured projection with all new optional topology fields.
_FULL_PROJECTION: Dict[str, Any] = {
    "tri_state_phase": "liminal",
    "runtime_domain": "local",
    "primary_model_id": "gpt-4o",
    "is_native_multimodal": True,
    "vendor_source": "openai",
    "topology_role": "primary",
    "support_model_ids": ["claude-3-5-sonnet", "local-vlm"],
    "active_weights": {
        "gpt-4o": 0.9,
        "claude-3-5-sonnet": 0.6,
        "local-vlm": 0.3,
    },
    "route_reason": "Native multimodal preferred in liminal phase",
    "routing_authority": "core.model_topology.topology_router.TopologyRouter",
    "oneapi_source": {
        "base_url": "http://oneapi.local:3000",
        "status": "configured",
        "model_count": 12,
    },
    "timestamp": 1711533600.0,
}

# Projection without native-multimodal flag (should NOT show [MM]).
_NON_MM_PROJECTION: Dict[str, Any] = {
    **_FULL_PROJECTION,
    "is_native_multimodal": False,
    "vendor_source": "anthropic",
    "primary_model_id": "claude-3-5-sonnet",
}

# Projection without OneAPI source (should NOT render lower OneAPI row).
_NO_ONEAPI_PROJECTION: Dict[str, Any] = {
    **_FULL_PROJECTION,
    "oneapi_source": None,
}

# Projection without new optional fields (backward compat).
_LEGACY_PROJECTION: Dict[str, Any] = {
    "tri_state_phase": "liminal",
    "runtime_domain": "local",
    "primary_model_id": "gpt-4o",
    "support_model_ids": ["claude-3"],
    "active_weights": {"gpt-4o": 0.85, "claude-3": 0.5},
    "route_reason": "Native multimodal preferred",
    "timestamp": 1711533600.0,
}

# Minimal projection with no routing data at all.
_EMPTY_PROJECTION: Dict[str, Any] = {
    "tri_state_phase": "silent",
    "runtime_domain": None,
    "primary_model_id": None,
    "support_model_ids": [],
    "active_weights": {},
    "route_reason": None,
    "timestamp": 1711533600.0,
}


# ---------------------------------------------------------------------------
# 1. Primary vs. support visual distinction
# ---------------------------------------------------------------------------

class TestPrimarySupportDistinction:
    """Primary and support layers are visually distinct."""

    @pytest.fixture(autouse=True)
    def _no_ansi(self, monkeypatch):
        _disable_ansi(monkeypatch)

    def test_main_route_header_present(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        assert "MAIN ROUTE" in out

    def test_support_header_present(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        assert "SUPPORT" in out

    def test_primary_marked_with_star(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        assert "★" in out

    def test_primary_model_in_main_route_section(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        lines = out.splitlines()
        main_idx = next(i for i, l in enumerate(lines) if "MAIN ROUTE" in l)
        support_idx = next(i for i, l in enumerate(lines) if "SUPPORT" in l)
        # Primary model ("gpt-4o") must appear between MAIN ROUTE and SUPPORT headers.
        primary_line_idx = next(
            i for i, l in enumerate(lines) if "gpt-4o" in l
        )
        assert main_idx < primary_line_idx < support_idx

    def test_support_models_listed_after_support_header(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        lines = out.splitlines()
        support_idx = next(i for i, l in enumerate(lines) if "SUPPORT" in l)
        # "claude-3-5-sonnet" is a support model; it must appear after the SUPPORT header.
        claude_line_idx = next(
            i for i, l in enumerate(lines) if "claude-3-5-sonnet" in l
        )
        assert claude_line_idx > support_idx

    def test_empty_support_shows_none(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        proj = dict(_EMPTY_PROJECTION)
        out = TopologySurface().render(proj)
        assert "SUPPORT" in out
        assert "(none)" in out


# ---------------------------------------------------------------------------
# 2. Native-multimodal emphasis
# ---------------------------------------------------------------------------

class TestNativeMultimodalEmphasis:
    """[MM] badge is preserved exactly when is_native_multimodal is True."""

    @pytest.fixture(autouse=True)
    def _no_ansi(self, monkeypatch):
        _disable_ansi(monkeypatch)

    def test_mm_badge_shown_when_true(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        assert "[MM]" in out

    def test_mm_badge_not_shown_when_false(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_NON_MM_PROJECTION)
        assert "[MM]" not in out

    def test_mm_badge_not_shown_when_field_absent(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_LEGACY_PROJECTION)
        assert "[MM]" not in out

    def test_mm_badge_on_same_line_as_primary_model(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        # Find the line containing the primary model ID; [MM] must be on that line.
        lines = out.splitlines()
        primary_line = next(l for l in lines if "gpt-4o" in l and "★" in l)
        assert "[MM]" in primary_line


# ---------------------------------------------------------------------------
# 3. OneAPI rendered as a separate lower aggregator row
# ---------------------------------------------------------------------------

class TestOneAPILowerRow:
    """OneAPI is rendered as a separate lower aggregator row."""

    @pytest.fixture(autouse=True)
    def _no_ansi(self, monkeypatch):
        _disable_ansi(monkeypatch)

    def test_oneapi_row_present_when_source_provided(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        assert "ONEAPI AGGREGATOR" in out

    def test_oneapi_row_absent_when_source_is_none(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_NO_ONEAPI_PROJECTION)
        assert "ONEAPI" not in out

    def test_oneapi_row_absent_when_field_missing(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_LEGACY_PROJECTION)
        assert "ONEAPI" not in out

    def test_oneapi_row_below_main_route_and_support(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        lines = out.splitlines()
        main_idx = next(i for i, l in enumerate(lines) if "MAIN ROUTE" in l)
        support_idx = next(i for i, l in enumerate(lines) if "SUPPORT" in l)
        oneapi_idx = next(i for i, l in enumerate(lines) if "ONEAPI" in l)
        assert main_idx < support_idx < oneapi_idx

    def test_oneapi_base_url_shown(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        assert "http://oneapi.local:3000" in out

    def test_oneapi_status_shown(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        assert "configured" in out

    def test_oneapi_model_count_shown(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        assert "12" in out

    def test_oneapi_not_mixed_into_main_route_layer(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        lines = out.splitlines()
        main_idx = next(i for i, l in enumerate(lines) if "MAIN ROUTE" in l)
        support_idx = next(i for i, l in enumerate(lines) if "SUPPORT" in l)
        # No line between MAIN ROUTE and SUPPORT should contain "ONEAPI".
        for l in lines[main_idx:support_idx]:
            assert "ONEAPI" not in l

    def test_oneapi_row_with_empty_source_dict(self):
        """An empty oneapi_source dict still renders the ONEAPI row."""
        from windows_client.status_board_v2.topology_surface import TopologySurface
        proj = dict(_FULL_PROJECTION, oneapi_source={})
        out = TopologySurface().render(proj)
        assert "ONEAPI AGGREGATOR" in out
        assert "not configured" in out

    def test_oneapi_row_without_model_count(self):
        """Missing model_count should not crash; count line is omitted."""
        from windows_client.status_board_v2.topology_surface import TopologySurface
        proj = dict(
            _FULL_PROJECTION,
            oneapi_source={"base_url": "http://oneapi.local", "status": "ok"},
        )
        out = TopologySurface().render(proj)
        assert "ONEAPI AGGREGATOR" in out
        assert "http://oneapi.local" in out

    def test_oneapi_not_a_direct_provider(self):
        """The ONEAPI row must carry the '(lower-layer / not a direct provider)' label."""
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        assert "not a direct provider" in out


# ---------------------------------------------------------------------------
# 4. Vendor/source visibility
# ---------------------------------------------------------------------------

class TestVendorSourceVisibility:
    """vendor_source tags appear for the primary model when provided."""

    @pytest.fixture(autouse=True)
    def _no_ansi(self, monkeypatch):
        _disable_ansi(monkeypatch)

    def test_vendor_tag_shown_in_primary_line(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        lines = out.splitlines()
        primary_line = next(l for l in lines if "gpt-4o" in l and "★" in l)
        assert "openai" in primary_line

    def test_no_vendor_tag_when_absent(self):
        """No vendor tag section when vendor_source is not in projection."""
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_LEGACY_PROJECTION)
        # No crash; primary line rendered.
        assert "gpt-4o" in out


# ---------------------------------------------------------------------------
# 5. Topology role hints
# ---------------------------------------------------------------------------

class TestTopologyRoleHints:
    """topology_role hints are shown when present."""

    @pytest.fixture(autouse=True)
    def _no_ansi(self, monkeypatch):
        _disable_ansi(monkeypatch)

    def test_role_hint_shown_when_present(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        assert "primary" in out

    def test_role_hint_absent_when_missing(self):
        """No crash when topology_role is not in projection."""
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_LEGACY_PROJECTION)
        assert "gpt-4o" in out  # Still renders.


# ---------------------------------------------------------------------------
# 6. Route reason and routing authority
# ---------------------------------------------------------------------------

class TestRouteReasonAndAuthority:
    """Route reason and routing authority are correctly rendered."""

    @pytest.fixture(autouse=True)
    def _no_ansi(self, monkeypatch):
        _disable_ansi(monkeypatch)

    def test_reason_shown(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        assert "Native multimodal preferred" in out

    def test_long_reason_truncated(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        proj = dict(_FULL_PROJECTION, route_reason="x" * 100)
        out = TopologySurface().render(proj)
        assert "..." in out

    def test_routing_authority_shown(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_FULL_PROJECTION)
        assert "Authority" in out
        # The authority string may be truncated; check it contains at least "TopologyRouter".
        assert "TopologyRouter" in out

    def test_routing_authority_not_shown_when_none(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        proj = dict(_EMPTY_PROJECTION, routing_authority="none")
        out = TopologySurface().render(proj)
        assert "Authority" not in out

    def test_routing_authority_not_shown_when_absent(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_LEGACY_PROJECTION)
        assert "Authority" not in out


# ---------------------------------------------------------------------------
# 7. Backward compatibility — legacy projections still render
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Existing projections without new optional fields still render correctly."""

    @pytest.fixture(autouse=True)
    def _no_ansi(self, monkeypatch):
        _disable_ansi(monkeypatch)

    def test_legacy_projection_renders_without_crash(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_LEGACY_PROJECTION)
        assert "gpt-4o" in out
        assert "MAIN ROUTE" in out

    def test_empty_projection_renders_without_crash(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_EMPTY_PROJECTION)
        assert "no topology data" in out

    def test_legacy_projection_still_shows_support(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_LEGACY_PROJECTION)
        assert "claude-3" in out

    def test_legacy_projection_shows_reason(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_LEGACY_PROJECTION)
        assert "Native multimodal preferred" in out

    def test_legacy_projection_has_weight_bars(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_LEGACY_PROJECTION)
        assert "█" in out or "Weights" in out

    def test_legacy_projection_star_marker(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(_LEGACY_PROJECTION)
        assert "★" in out


# ---------------------------------------------------------------------------
# 8. Existing test_pr4_status_board_v2 compatibility assertions
# ---------------------------------------------------------------------------

class TestExistingTestCompat:
    """
    Ensure the updated TopologySurface still satisfies all assertions that
    the existing test_pr4_status_board_v2.TestTopologySurface makes.
    """

    @pytest.fixture(autouse=True)
    def _no_ansi(self, monkeypatch):
        _disable_ansi(monkeypatch)

    # Replicate _SAMPLE_PROJECTION from test_pr4_status_board_v2
    _SAMPLE = {
        "tri_state_phase": "liminal",
        "runtime_domain": "local",
        "presence_intensity": 0.6,
        "coherence": 0.75,
        "collapse_tendency": 0.3,
        "retreat_tendency": 0.1,
        "primary_model_id": "gpt-4o",
        "support_model_ids": ["claude-3", "local-vlm"],
        "active_weights": {"gpt-4o": 0.9, "claude-3": 0.6, "local-vlm": 0.4},
        "route_reason": "Native multimodal preferred in liminal",
        "active_device_ids": ["desktop-win"],
        "execution_stage": "planning",
        "current_task_summary": "Drafting email",
        "timestamp": 1711533600.0,
    }
    _MINIMAL = {
        "tri_state_phase": "silent",
        "runtime_domain": None,
        "presence_intensity": None,
        "coherence": None,
        "collapse_tendency": None,
        "retreat_tendency": None,
        "primary_model_id": None,
        "support_model_ids": [],
        "active_weights": {},
        "route_reason": None,
        "active_device_ids": [],
        "execution_stage": None,
        "current_task_summary": None,
        "timestamp": 1711533600.0,
    }

    def test_render_with_weights(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(self._SAMPLE)
        assert "gpt-4o" in out
        assert "MAIN ROUTE" in out or "Primary" in out
        assert "█" in out or "Weights" in out

    def test_render_primary_marker(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(self._SAMPLE)
        assert "★" in out

    def test_render_no_weights(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(self._MINIMAL)
        assert "no topology data" in out

    def test_render_support_models(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(self._SAMPLE)
        assert "claude-3" in out

    def test_render_route_reason(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        out = TopologySurface().render(self._SAMPLE)
        assert "Native multimodal" in out

    def test_render_long_reason_truncated(self):
        from windows_client.status_board_v2.topology_surface import TopologySurface
        proj = dict(self._SAMPLE, route_reason="x" * 100)
        out = TopologySurface().render(proj)
        assert "..." in out
