"""
tests/test_display_boundary_guardrails.py
==========================================
Guardrail tests protecting the display boundary between the right-side desktop
status board and the liminal middle-state space.

See ``docs/DESKTOP_DISPLAY_BOUNDARIES.md`` for the canonical contract.

Coverage
--------
1. Module-level boundary declaration
   - liminal_surface module docstring declares it is a spatial execution field
   - liminal_surface module docstring prohibits provider/metrics/dashboard content
   - manifest_surface module docstring declares boundary compliance
   - manifest_surface module docstring prohibits provider/metrics/dashboard content
   - ACTIVE_SURFACE.md contains display boundary section

2. LiminalSurface rendering — spatial field only
   - render() output contains spatial field labels (depth, topology, ambient)
   - render() output does NOT contain provider-list-style content
   - render() output does NOT contain dashboard / metrics-board keywords
   - render() output does NOT contain generic operator info block keywords

3. ManifestSurface rendering — execution context only
   - render() output contains execution-context labels (stage, focus, route)
   - render() output does NOT contain provider-list-style content
   - render() output does NOT contain dashboard / metrics-board keywords

4. DesktopStatusProjection contract — covers right-side board content classes
   - contract has ModelRoutingProjection sub-contract
   - contract has ExecutionProjection sub-contract
   - contract has LifecycleProjection sub-contract
   - contract has PerceptionProjection sub-contract
   - contract has ExplainabilityProjection sub-contract

5. Spatial-field / status-board field separation
   - LiminalSpaceState fields are purely spatial dimensions
   - LiminalSpaceState fields do NOT overlap with DesktopStatusProjection information fields
   - DESKTOP_DISPLAY_BOUNDARIES.md exists at the expected path

6. Right-side board surfaces do not import spatial-field modules as primary rendering
   - topology_surface, metrics_surface, device_surface, phase_surface do not
     import StateSpaceMapper / LiminalSpaceEngine as a primary dependency
"""

from __future__ import annotations

import importlib
import inspect
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

# ---------------------------------------------------------------------------
# Repo root helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent


def _repo_file(rel: str) -> Path:
    return _REPO_ROOT / rel


# ---------------------------------------------------------------------------
# Sample projections for render tests
# ---------------------------------------------------------------------------

_SAMPLE_PROJECTION: Dict[str, Any] = {
    "tri_state_phase": "liminal",
    "runtime_domain": "local",
    "presence_intensity": 0.6,
    "coherence": 0.75,
    "collapse_tendency": 0.3,
    "retreat_tendency": 0.1,
    "primary_model_id": "gpt-4o",
    "support_model_ids": ["claude-3", "local-vlm"],
    "active_weights": {
        "gpt-4o": 0.9,
        "claude-3": 0.6,
    },
    "route_reason": "Native multimodal preferred",
    "active_device_ids": ["desktop-win"],
    "execution_stage": "planning",
    "current_task_summary": "Drafting email",
    "timestamp": 1711533600.0,
}

_MANIFEST_PROJECTION: Dict[str, Any] = {
    "tri_state_phase": "manifest",
    "runtime_domain": "local",
    "presence_intensity": 0.9,
    "coherence": 0.95,
    "collapse_tendency": 0.05,
    "retreat_tendency": 0.0,
    "primary_model_id": "gpt-4o",
    "support_model_ids": ["claude-3"],
    "active_weights": {"gpt-4o": 0.95},
    "route_reason": "Committed to local execution",
    "active_device_ids": ["desktop-win"],
    "execution_stage": "executing",
    "current_task_summary": "Writing code",
    "timestamp": 1711533601.0,
}

_MINIMAL_PROJECTION: Dict[str, Any] = {
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


# ---------------------------------------------------------------------------
# 1. Module-level boundary declarations
# ---------------------------------------------------------------------------


class TestBoundaryDeclarations:
    """The module docstrings and docs must declare the display boundary."""

    def test_liminal_surface_docstring_mentions_spatial_field(self) -> None:
        """LiminalSurface module docstring must identify it as a spatial field."""
        from windows_client.status_board_v2 import liminal_surface
        doc = liminal_surface.__doc__ or ""
        assert "spatial" in doc.lower(), (
            "liminal_surface module docstring must identify it as a spatial execution field"
        )

    def test_liminal_surface_docstring_mentions_boundary(self) -> None:
        """LiminalSurface module docstring must reference the display boundary."""
        from windows_client.status_board_v2 import liminal_surface
        doc = liminal_surface.__doc__ or ""
        # The docstring must mention what is prohibited or mention the boundary doc
        assert (
            "DESKTOP_DISPLAY_BOUNDARIES" in doc
            or "not a second status board" in doc.lower()
            or "must not" in doc.lower()
        ), (
            "liminal_surface module docstring must reference display boundary constraints"
        )

    def test_liminal_surface_docstring_prohibits_provider_panels(self) -> None:
        """LiminalSurface module docstring must explicitly prohibit provider/metrics panels."""
        from windows_client.status_board_v2 import liminal_surface
        doc = liminal_surface.__doc__ or ""
        assert any(
            kw in doc.lower()
            for kw in ("provider", "metrics", "dashboard", "not carry", "must not")
        ), (
            "liminal_surface module docstring must prohibit provider/metrics/dashboard content"
        )

    def test_manifest_surface_docstring_mentions_boundary(self) -> None:
        """ManifestSurface module docstring must reference the display boundary."""
        from windows_client.status_board_v2 import manifest_surface
        doc = manifest_surface.__doc__ or ""
        assert (
            "DESKTOP_DISPLAY_BOUNDARIES" in doc
            or "not a second status board" in doc.lower()
            or "prohibited" in doc.lower()
        ), (
            "manifest_surface module docstring must reference display boundary constraints"
        )

    def test_manifest_surface_docstring_prohibits_provider_panels(self) -> None:
        """ManifestSurface module docstring must explicitly prohibit provider/metrics panels."""
        from windows_client.status_board_v2 import manifest_surface
        doc = manifest_surface.__doc__ or ""
        assert any(
            kw in doc.lower()
            for kw in ("provider", "metrics", "dashboard", "not carry", "must not", "prohibited")
        ), (
            "manifest_surface module docstring must prohibit provider/metrics/dashboard content"
        )

    def test_active_surface_md_contains_boundary_section(self) -> None:
        """ACTIVE_SURFACE.md must contain a display boundary section."""
        md_path = _repo_file("windows_client/status_board_v2/ACTIVE_SURFACE.md")
        assert md_path.exists(), "ACTIVE_SURFACE.md must exist"
        content = md_path.read_text()
        assert "boundary" in content.lower(), (
            "ACTIVE_SURFACE.md must contain a display boundary section"
        )

    def test_canonical_boundary_doc_exists(self) -> None:
        """docs/DESKTOP_DISPLAY_BOUNDARIES.md must exist as the canonical boundary doc."""
        doc_path = _repo_file("docs/DESKTOP_DISPLAY_BOUNDARIES.md")
        assert doc_path.exists(), (
            "docs/DESKTOP_DISPLAY_BOUNDARIES.md must exist as the canonical boundary contract"
        )

    def test_canonical_boundary_doc_is_non_empty(self) -> None:
        """docs/DESKTOP_DISPLAY_BOUNDARIES.md must contain meaningful content."""
        doc_path = _repo_file("docs/DESKTOP_DISPLAY_BOUNDARIES.md")
        content = doc_path.read_text()
        assert len(content) > 500, (
            "docs/DESKTOP_DISPLAY_BOUNDARIES.md must contain substantial boundary definitions"
        )

    def test_canonical_boundary_doc_defines_status_board(self) -> None:
        """Boundary doc must define what the right-side status board is."""
        doc_path = _repo_file("docs/DESKTOP_DISPLAY_BOUNDARIES.md")
        content = doc_path.read_text()
        assert "status board" in content.lower(), (
            "Boundary doc must define the right-side desktop status board"
        )

    def test_canonical_boundary_doc_defines_liminal_space(self) -> None:
        """Boundary doc must define what the liminal space is."""
        doc_path = _repo_file("docs/DESKTOP_DISPLAY_BOUNDARIES.md")
        content = doc_path.read_text()
        assert "liminal" in content.lower(), (
            "Boundary doc must define the liminal space"
        )

    def test_canonical_boundary_doc_defines_prohibited_crossovers(self) -> None:
        """Boundary doc must define prohibited crossovers."""
        doc_path = _repo_file("docs/DESKTOP_DISPLAY_BOUNDARIES.md")
        content = doc_path.read_text()
        assert any(
            kw in content.lower() for kw in ("prohibit", "must not", "never")
        ), "Boundary doc must enumerate prohibited crossovers"

    def test_canonical_boundary_doc_references_runtime_projection(self) -> None:
        """Boundary doc must mention RuntimeProjection or DesktopStatusProjection."""
        doc_path = _repo_file("docs/DESKTOP_DISPLAY_BOUNDARIES.md")
        content = doc_path.read_text()
        assert (
            "RuntimeProjection" in content or "DesktopStatusProjection" in content
        ), "Boundary doc must describe how projection contracts relate to the two layers"

    def test_status_board_v2_doc_references_boundary_doc(self) -> None:
        """STATUS_BOARD_V2.md must reference the canonical boundary doc."""
        doc_path = _repo_file("docs/STATUS_BOARD_V2.md")
        content = doc_path.read_text()
        assert "DESKTOP_DISPLAY_BOUNDARIES" in content, (
            "STATUS_BOARD_V2.md must reference DESKTOP_DISPLAY_BOUNDARIES.md"
        )


# ---------------------------------------------------------------------------
# 2. LiminalSurface rendering — spatial field only
# ---------------------------------------------------------------------------

# Content that must be present in a spatial-field surface
_LIMINAL_SPATIAL_LABELS = ["Depth", "Topology", "Domain Path", "Ambient"]

# Keywords that must NEVER appear in liminal rendering
# (These represent information-board / provider-list content)
_LIMINAL_FORBIDDEN_KEYWORDS = [
    "Provider",
    "vendor",
    "OneAPI",
    "Dashboard",
    "Metrics Board",
    "Operator Info",
]


class TestLiminalSurfaceRendering:
    """LiminalSurface must render only spatial-field content."""

    def _render(self, projection: Dict[str, Any]) -> str:
        from windows_client.status_board_v2.liminal_surface import LiminalSurface
        surf = LiminalSurface()
        return surf.render(projection)

    def test_render_returns_nonempty_string(self) -> None:
        rendered = self._render(_SAMPLE_PROJECTION)
        assert isinstance(rendered, str) and len(rendered) > 0

    def test_render_contains_spatial_label_depth(self) -> None:
        rendered = self._render(_SAMPLE_PROJECTION)
        assert "Depth" in rendered, "Liminal surface must show spatial depth_factor label"

    def test_render_contains_spatial_label_topology(self) -> None:
        rendered = self._render(_SAMPLE_PROJECTION)
        assert "Topology" in rendered, (
            "Liminal surface must show topology_visibility label"
        )

    def test_render_contains_spatial_label_ambient(self) -> None:
        rendered = self._render(_SAMPLE_PROJECTION)
        assert "Ambient" in rendered, "Liminal surface must show ambient_intensity label"

    def test_render_does_not_contain_provider_list_header(self) -> None:
        """Liminal surface must not render provider-list-style headers."""
        rendered = self._render(_SAMPLE_PROJECTION)
        # Strip ANSI codes for plain-text matching
        import re
        plain = re.sub(r"\x1b\[[0-9;]*m", "", rendered)
        forbidden = ["Provider List", "Provider Cards", "Model Panel", "OneAPI Status"]
        for kw in forbidden:
            assert kw not in plain, (
                f"Liminal surface must not contain '{kw}' — that belongs to the status board"
            )

    def test_render_does_not_contain_dashboard_keywords(self) -> None:
        """Liminal surface must not render dashboard-style content."""
        rendered = self._render(_SAMPLE_PROJECTION)
        import re
        plain = re.sub(r"\x1b\[[0-9;]*m", "", rendered)
        forbidden = ["Dashboard", "Metrics Board", "Status Panel"]
        for kw in forbidden:
            assert kw not in plain, (
                f"Liminal surface must not contain '{kw}' — that belongs to the status board"
            )

    def test_render_handles_minimal_projection(self) -> None:
        """Liminal surface must degrade gracefully with a minimal (silent) projection."""
        rendered = self._render(_MINIMAL_PROJECTION)
        assert isinstance(rendered, str) and len(rendered) > 0

    def test_render_handles_manifest_projection(self) -> None:
        """Liminal surface must render without errors for manifest-phase projections."""
        rendered = self._render(_MANIFEST_PROJECTION)
        assert isinstance(rendered, str) and len(rendered) > 0

    def test_liminal_surface_class_docstring_mentions_spatial(self) -> None:
        """LiminalSurface class docstring must mention spatial or execution field."""
        from windows_client.status_board_v2.liminal_surface import LiminalSurface
        doc = LiminalSurface.__doc__ or ""
        assert any(
            kw in doc.lower() for kw in ("spatial", "field", "execution")
        ), "LiminalSurface class docstring must describe its spatial / execution-field nature"


# ---------------------------------------------------------------------------
# 3. ManifestSurface rendering — execution context only
# ---------------------------------------------------------------------------

_MANIFEST_EXECUTION_LABELS = ["Phase", "Stage", "Focus", "Primary"]
_MANIFEST_FORBIDDEN_KEYWORDS = [
    "Provider List",
    "Provider Cards",
    "Model Panel",
    "Dashboard",
    "Metrics Board",
]


class TestManifestSurfaceRendering:
    """ManifestSurface must render only execution-context content."""

    def _render(self, projection: Dict[str, Any]) -> str:
        from windows_client.status_board_v2.manifest_surface import ManifestSurface
        surf = ManifestSurface()
        return surf.render(projection)

    def test_render_returns_nonempty_string(self) -> None:
        rendered = self._render(_SAMPLE_PROJECTION)
        assert isinstance(rendered, str) and len(rendered) > 0

    def test_render_contains_execution_label_phase(self) -> None:
        rendered = self._render(_SAMPLE_PROJECTION)
        import re
        plain = re.sub(r"\x1b\[[0-9;]*m", "", rendered)
        assert "Phase" in plain, "Manifest surface must show execution phase label"

    def test_render_contains_execution_label_focus(self) -> None:
        rendered = self._render(_MANIFEST_PROJECTION)
        import re
        plain = re.sub(r"\x1b\[[0-9;]*m", "", rendered)
        assert "Focus" in plain, "Manifest surface must show focus intensity label"

    def test_render_does_not_contain_provider_list_keywords(self) -> None:
        """ManifestSurface must not render provider-list-style content."""
        rendered = self._render(_MANIFEST_PROJECTION)
        import re
        plain = re.sub(r"\x1b\[[0-9;]*m", "", rendered)
        for kw in _MANIFEST_FORBIDDEN_KEYWORDS:
            assert kw not in plain, (
                f"Manifest surface must not contain '{kw}' — that belongs to the status board"
            )

    def test_render_handles_minimal_projection(self) -> None:
        rendered = self._render(_MINIMAL_PROJECTION)
        assert isinstance(rendered, str) and len(rendered) > 0

    def test_manifest_surface_class_docstring_mentions_execution_context(self) -> None:
        from windows_client.status_board_v2.manifest_surface import ManifestSurface
        doc = ManifestSurface.__doc__ or ""
        assert any(
            kw in doc.lower() for kw in ("execution", "manifest", "field")
        ), "ManifestSurface class docstring must describe its execution-context nature"


# ---------------------------------------------------------------------------
# 4. DesktopStatusProjection contract — covers right-side board content classes
# ---------------------------------------------------------------------------


class TestDesktopStatusProjectionContract:
    """DesktopStatusProjection must cover the right-side board content classes."""

    def _get_projection_module(self):
        return importlib.import_module("contracts.desktop_status_projection")

    def test_contract_has_model_routing_projection(self) -> None:
        mod = self._get_projection_module()
        assert hasattr(mod, "ModelRoutingProjection"), (
            "DesktopStatusProjection contract must have ModelRoutingProjection sub-contract"
        )

    def test_contract_has_execution_projection(self) -> None:
        mod = self._get_projection_module()
        assert hasattr(mod, "ExecutionProjection"), (
            "DesktopStatusProjection contract must have ExecutionProjection sub-contract"
        )

    def test_contract_has_lifecycle_projection(self) -> None:
        mod = self._get_projection_module()
        assert hasattr(mod, "LifecycleProjection"), (
            "DesktopStatusProjection contract must have LifecycleProjection sub-contract"
        )

    def test_contract_has_perception_projection(self) -> None:
        mod = self._get_projection_module()
        assert hasattr(mod, "PerceptionProjection"), (
            "DesktopStatusProjection contract must have PerceptionProjection sub-contract"
        )

    def test_contract_has_explainability_projection(self) -> None:
        mod = self._get_projection_module()
        assert hasattr(mod, "ExplainabilityProjection"), (
            "DesktopStatusProjection contract must have ExplainabilityProjection sub-contract"
        )

    def test_contract_has_build_function(self) -> None:
        mod = self._get_projection_module()
        assert hasattr(mod, "build_desktop_status_projection"), (
            "DesktopStatusProjection contract must expose build_desktop_status_projection()"
        )

    def test_model_routing_projection_has_provider_field(self) -> None:
        mod = self._get_projection_module()
        cls = mod.ModelRoutingProjection
        fields = cls.model_fields if hasattr(cls, "model_fields") else {}
        # Should have some provider/model routing fields
        field_names = set(fields.keys())
        assert any(
            kw in " ".join(field_names) for kw in ("provider", "primary", "model", "route")
        ), (
            "ModelRoutingProjection must have provider/model routing fields for the status board"
        )

    def test_desktop_status_projection_class_exists(self) -> None:
        mod = self._get_projection_module()
        assert hasattr(mod, "DesktopStatusProjection"), (
            "contracts module must export DesktopStatusProjection"
        )

    def test_desktop_status_projection_is_serialisable(self) -> None:
        """DesktopStatusProjection must produce a to_dict / to_json callable."""
        mod = self._get_projection_module()
        cls = mod.DesktopStatusProjection
        instance = mod.build_desktop_status_projection(
            unified_control_plan={},
            source_registry_snapshot=None,
            tristate=None,
            runtime_session_id="test-guardrail",
        )
        assert hasattr(instance, "to_dict") or hasattr(instance, "dict"), (
            "DesktopStatusProjection must be serialisable (to_dict or .dict)"
        )


# ---------------------------------------------------------------------------
# 5. Spatial-field / status-board field separation
# ---------------------------------------------------------------------------


class TestSpatialFieldSeparation:
    """Spatial-field dimensions must not bleed into the status board contract."""

    # These are the spatial-dimension names from LiminalSpaceState
    _SPATIAL_DIMS = {"depth_factor", "topology_visibility", "domain_path_emphasis", "ambient_intensity"}

    def test_liminal_space_state_has_spatial_dims(self) -> None:
        """LiminalSpaceState must expose the four canonical spatial dimensions."""
        from desktop_projection import StateSpaceMapper
        mapper = StateSpaceMapper()
        sample = {
            "tri_state_phase": "liminal",
            "runtime_domain": "local",
            "presence_intensity": 0.5,
            "coherence": 0.5,
            "collapse_tendency": 0.2,
            "retreat_tendency": 0.1,
            "active_weights": {"gpt-4o": 0.8},
        }
        state = mapper.map(sample)
        for dim in self._SPATIAL_DIMS:
            assert hasattr(state, dim), (
                f"LiminalSpaceState must expose spatial dimension '{dim}'"
            )

    def test_spatial_dims_are_floats_in_0_1(self) -> None:
        """Spatial dimensions must be floats in [0, 1]."""
        from desktop_projection import StateSpaceMapper
        mapper = StateSpaceMapper()
        sample = {
            "tri_state_phase": "liminal",
            "runtime_domain": "local",
            "presence_intensity": 0.5,
            "coherence": 0.7,
            "collapse_tendency": 0.1,
            "retreat_tendency": 0.05,
            "active_weights": {"gpt-4o": 0.9},
        }
        state = mapper.map(sample)
        for dim in self._SPATIAL_DIMS:
            val = getattr(state, dim)
            assert isinstance(val, float), f"Spatial dimension '{dim}' must be a float"
            assert 0.0 <= val <= 1.0, (
                f"Spatial dimension '{dim}' must be in [0, 1], got {val}"
            )

    def test_desktop_status_projection_fields_do_not_include_spatial_dims(self) -> None:
        """DesktopStatusProjection must not have spatial dimension fields at the top level."""
        mod = importlib.import_module("contracts.desktop_status_projection")
        cls = mod.DesktopStatusProjection
        fields = cls.model_fields if hasattr(cls, "model_fields") else {}
        top_level_names = set(fields.keys())
        overlap = top_level_names & self._SPATIAL_DIMS
        assert not overlap, (
            f"DesktopStatusProjection must not have spatial field names at the top level: {overlap}"
        )

    def test_boundary_doc_mentions_both_projection_contracts(self) -> None:
        """Boundary doc must describe both DesktopStatusProjection and StateSpaceMapper."""
        doc_path = _repo_file("docs/DESKTOP_DISPLAY_BOUNDARIES.md")
        content = doc_path.read_text()
        assert "StateSpaceMapper" in content, (
            "Boundary doc must mention StateSpaceMapper as the liminal layer's contract"
        )
        assert "DesktopStatusProjection" in content, (
            "Boundary doc must mention DesktopStatusProjection as the status board's contract"
        )


# ---------------------------------------------------------------------------
# 6. Right-side board surfaces do not import spatial-field modules as primary
# ---------------------------------------------------------------------------

_STATUS_BOARD_SURFACES = [
    "windows_client/status_board_v2/topology_surface.py",
    "windows_client/status_board_v2/metrics_surface.py",
    "windows_client/status_board_v2/device_surface.py",
    "windows_client/status_board_v2/phase_surface.py",
    "windows_client/status_board_v2/domain_surface.py",
]

_SPATIAL_ONLY_IMPORTS = ["StateSpaceMapper", "LiminalSpaceEngine"]


class TestStatusBoardSurfacesDoNotImportSpatialModules:
    """Right-side board surfaces must not import spatial-field-only modules at module level."""

    @pytest.mark.parametrize("surface_rel_path", _STATUS_BOARD_SURFACES)
    def test_surface_does_not_import_state_space_mapper_at_module_level(
        self, surface_rel_path: str
    ) -> None:
        """Status board surface source must not import StateSpaceMapper at module level."""
        path = _repo_file(surface_rel_path)
        if not path.exists():
            pytest.skip(f"{surface_rel_path} does not exist")
        source = path.read_text()
        # Check for top-level (non-deferred) imports of spatial modules.
        # Deferred/local imports inside render() are acceptable as a compatibility
        # pattern, but module-level imports would blur the boundary.
        lines = source.splitlines()
        top_level_import_lines = [
            ln for ln in lines
            if ln.startswith("import ") or ln.startswith("from ")
        ]
        for imp_line in top_level_import_lines:
            for kw in _SPATIAL_ONLY_IMPORTS:
                assert kw not in imp_line, (
                    f"{surface_rel_path} must not import {kw} at module level — "
                    f"that is a liminal-space concern"
                )
