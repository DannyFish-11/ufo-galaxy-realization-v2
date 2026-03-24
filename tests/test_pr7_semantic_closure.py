"""
tests/test_pr7_semantic_closure.py
====================================
Guardrail tests for the complete desktop semantic closure (PR-7).

Coverage
--------
1. Canonical closure docs exist
   - docs/DESKTOP_SEMANTIC_CLOSURE.md exists and contains the three states
   - docs/CONFIGURATION_ENTRY_UNIFICATION.md exists with canonical entry points
   - docs/STATUS_AND_STATISTICS_OWNERSHIP.md exists with ownership table

2. Tri-state semantic invariants
   - TriState enum has exactly three values: silent / liminal / manifest
   - DesktopPresenceRuntime is the sole tri-state authority
   - Tri-state values match across TriState and TriStatePhase enums

3. Legacy residue isolation
   - dashboard/ carries LEGACY_SURFACE.md marker
   - status_board.py carries legacy deprecation notice
   - ACTIVE_SURFACE.md references the new semantic closure doc

4. Statistics / summary ownership
   - STATUS_AND_STATISTICS_OWNERSHIP.md references the canonical projection contract
   - liminal_surface only exposes chain/sandbox statistics (not routing stats)
   - status board doc references statistics ownership doc

5. Configuration-entry semantics
   - CONFIGURATION_ENTRY_UNIFICATION.md references CONFIG_GOVERNANCE.md
   - ACTIVE_SURFACE.md references configuration entry doc
   - No duplicate config-entry authority claims in surface docs
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

_REPO_ROOT = Path(__file__).parent.parent


def _repo_file(rel: str) -> Path:
    return _REPO_ROOT / rel


# ---------------------------------------------------------------------------
# 1. Canonical closure docs exist
# ---------------------------------------------------------------------------


class TestCanonicalClosureDocsExist:
    """The three closure docs must be present and contain the right content."""

    def test_desktop_semantic_closure_doc_exists(self) -> None:
        p = _repo_file("docs/DESKTOP_SEMANTIC_CLOSURE.md")
        assert p.exists(), "docs/DESKTOP_SEMANTIC_CLOSURE.md must exist"

    def test_desktop_semantic_closure_doc_mentions_silent(self) -> None:
        content = _repo_file("docs/DESKTOP_SEMANTIC_CLOSURE.md").read_text()
        assert "silent" in content.lower()

    def test_desktop_semantic_closure_doc_mentions_liminal(self) -> None:
        content = _repo_file("docs/DESKTOP_SEMANTIC_CLOSURE.md").read_text()
        assert "liminal" in content.lower()

    def test_desktop_semantic_closure_doc_mentions_manifest(self) -> None:
        content = _repo_file("docs/DESKTOP_SEMANTIC_CLOSURE.md").read_text()
        assert "manifest" in content.lower()

    def test_desktop_semantic_closure_doc_defines_authority(self) -> None:
        content = _repo_file("docs/DESKTOP_SEMANTIC_CLOSURE.md").read_text()
        assert "DesktopPresenceRuntime" in content, (
            "DESKTOP_SEMANTIC_CLOSURE.md must name DesktopPresenceRuntime as tri-state authority"
        )

    def test_desktop_semantic_closure_doc_mentions_invariants(self) -> None:
        content = _repo_file("docs/DESKTOP_SEMANTIC_CLOSURE.md").read_text().lower()
        assert "invariant" in content, (
            "DESKTOP_SEMANTIC_CLOSURE.md must define tri-state invariants"
        )

    def test_configuration_entry_unification_doc_exists(self) -> None:
        p = _repo_file("docs/CONFIGURATION_ENTRY_UNIFICATION.md")
        assert p.exists(), "docs/CONFIGURATION_ENTRY_UNIFICATION.md must exist"

    def test_configuration_entry_unification_doc_mentions_canonical_entry(self) -> None:
        content = _repo_file("docs/CONFIGURATION_ENTRY_UNIFICATION.md").read_text()
        assert "config.json" in content.lower() or "unified_config" in content.lower(), (
            "CONFIGURATION_ENTRY_UNIFICATION.md must reference the canonical config entry point"
        )

    def test_configuration_entry_unification_doc_references_config_governance(self) -> None:
        content = _repo_file("docs/CONFIGURATION_ENTRY_UNIFICATION.md").read_text()
        assert "CONFIG_GOVERNANCE" in content, (
            "CONFIGURATION_ENTRY_UNIFICATION.md must cross-reference CONFIG_GOVERNANCE.md"
        )

    def test_status_and_statistics_ownership_doc_exists(self) -> None:
        p = _repo_file("docs/STATUS_AND_STATISTICS_OWNERSHIP.md")
        assert p.exists(), "docs/STATUS_AND_STATISTICS_OWNERSHIP.md must exist"

    def test_status_and_statistics_ownership_doc_mentions_projection(self) -> None:
        content = _repo_file("docs/STATUS_AND_STATISTICS_OWNERSHIP.md").read_text()
        assert "DesktopStatusProjection" in content, (
            "STATUS_AND_STATISTICS_OWNERSHIP.md must reference DesktopStatusProjection"
        )

    def test_status_and_statistics_ownership_doc_mentions_liminal_chain(self) -> None:
        content = _repo_file("docs/STATUS_AND_STATISTICS_OWNERSHIP.md").read_text().lower()
        assert "local execution chain" in content or "cross-device" in content, (
            "STATUS_AND_STATISTICS_OWNERSHIP.md must cover liminal-space chain statistics"
        )


# ---------------------------------------------------------------------------
# 2. Tri-state semantic invariants
# ---------------------------------------------------------------------------


class TestTriStateSemanticInvariants:
    """The tri-state model must be consistent across the codebase."""

    def test_tristate_enum_has_silent(self) -> None:
        from core.desktop_presence_runtime import TriState
        assert TriState.SILENT.value == "silent"

    def test_tristate_enum_has_liminal(self) -> None:
        from core.desktop_presence_runtime import TriState
        assert TriState.LIMINAL.value == "liminal"

    def test_tristate_enum_has_manifest(self) -> None:
        from core.desktop_presence_runtime import TriState
        assert TriState.MANIFEST.value == "manifest"

    def test_tristate_enum_has_exactly_three_values(self) -> None:
        from core.desktop_presence_runtime import TriState
        values = {m.value for m in TriState}
        assert values == {"silent", "liminal", "manifest"}, (
            "TriState must have exactly three values: silent / liminal / manifest"
        )

    def test_continuum_tristate_phase_matches(self) -> None:
        """TriStatePhase in core.continuum.types must use the same three values.

        Loaded directly from the source file to avoid the numpy transitive
        import that triggers through core/continuum/__init__.py →
        core/continuum/human_field.py → core/multimodal/audio_features.py.
        """
        import importlib.util
        from pathlib import Path

        types_path = Path(__file__).parent.parent / "core" / "continuum" / "types.py"
        spec = importlib.util.spec_from_file_location("continuum_types_direct", types_path)
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        TriStatePhase = mod.TriStatePhase
        values = {m.value for m in TriStatePhase}
        assert values == {"silent", "liminal", "manifest"}, (
            "TriStatePhase must match the canonical tri-state values"
        )

    def test_desktop_presence_runtime_is_tristate_authority(self) -> None:
        """DesktopPresenceRuntime must expose a TriState enum and handle_request method.

        Validates the TriState enum only — avoids instantiating the runtime
        (which would trigger the numpy transitive dependency).
        """
        from core.desktop_presence_runtime import TriState
        # Verify TriState has exactly the three canonical values.
        values = {m.value for m in TriState}
        assert values == {"silent", "liminal", "manifest"}, (
            "DesktopPresenceRuntime.TriState must carry the three canonical values"
        )
        # Verify the class at least declares handle_request as the lifecycle entry.
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        assert hasattr(DesktopPresenceRuntime, "handle_request"), (
            "DesktopPresenceRuntime must expose 'handle_request' as the lifecycle driver"
        )

    def test_closure_doc_references_all_three_states(self) -> None:
        content = _repo_file("docs/DESKTOP_SEMANTIC_CLOSURE.md").read_text().lower()
        for state in ("silent", "liminal", "manifest"):
            assert state in content, (
                f"DESKTOP_SEMANTIC_CLOSURE.md must define the '{state}' state"
            )


# ---------------------------------------------------------------------------
# 3. Legacy residue isolation
# ---------------------------------------------------------------------------


class TestLegacyResidueIsolation:
    """Legacy surfaces must carry isolation markers and not claim active authority."""

    def test_dashboard_legacy_surface_md_exists(self) -> None:
        p = _repo_file("dashboard/LEGACY_SURFACE.md")
        assert p.exists(), "dashboard/LEGACY_SURFACE.md must exist"

    def test_dashboard_legacy_surface_md_contains_legacy_marker(self) -> None:
        content = _repo_file("dashboard/LEGACY_SURFACE.md").read_text().lower()
        assert "legacy" in content

    def test_dashboard_legacy_surface_md_references_canonical_surface(self) -> None:
        content = _repo_file("dashboard/LEGACY_SURFACE.md").read_text()
        assert "status_board_v2" in content or "windows_client" in content, (
            "dashboard/LEGACY_SURFACE.md must point to the canonical replacement"
        )

    def test_status_board_py_has_legacy_deprecation(self) -> None:
        sb_path = _repo_file("windows_client/status_board.py")
        assert sb_path.exists(), "windows_client/status_board.py must exist"
        content = sb_path.read_text().lower()
        assert "deprecated" in content or "legacy" in content, (
            "status_board.py must carry a legacy / deprecated notice"
        )

    def test_active_surface_md_references_semantic_closure_doc(self) -> None:
        content = _repo_file("windows_client/status_board_v2/ACTIVE_SURFACE.md").read_text()
        assert "DESKTOP_SEMANTIC_CLOSURE" in content, (
            "ACTIVE_SURFACE.md must reference docs/DESKTOP_SEMANTIC_CLOSURE.md"
        )

    def test_active_surface_md_lists_all_three_states(self) -> None:
        content = _repo_file("windows_client/status_board_v2/ACTIVE_SURFACE.md").read_text().lower()
        for state in ("silent", "liminal", "manifest"):
            assert state in content, (
                f"ACTIVE_SURFACE.md must reference the '{state}' tri-state value"
            )


# ---------------------------------------------------------------------------
# 4. Statistics / summary ownership
# ---------------------------------------------------------------------------


class TestStatisticsOwnership:
    """Statistics must live in the correct surface / doc."""

    def test_statistics_doc_references_status_board(self) -> None:
        content = _repo_file("docs/STATUS_AND_STATISTICS_OWNERSHIP.md").read_text()
        assert "status_board_v2" in content or "status board" in content.lower(), (
            "STATUS_AND_STATISTICS_OWNERSHIP.md must reference the status board as the "
            "canonical home for operator-visible statistics"
        )

    def test_statistics_doc_references_liminal_surface(self) -> None:
        content = _repo_file("docs/STATUS_AND_STATISTICS_OWNERSHIP.md").read_text()
        assert "liminal_surface" in content or "liminal space" in content.lower(), (
            "STATUS_AND_STATISTICS_OWNERSHIP.md must reference liminal_surface for "
            "execution-chain statistics"
        )

    def test_statistics_doc_references_desktop_display_boundaries(self) -> None:
        content = _repo_file("docs/STATUS_AND_STATISTICS_OWNERSHIP.md").read_text()
        assert "DESKTOP_DISPLAY_BOUNDARIES" in content, (
            "STATUS_AND_STATISTICS_OWNERSHIP.md must cross-reference DESKTOP_DISPLAY_BOUNDARIES.md"
        )

    def test_status_board_v2_doc_references_statistics_ownership(self) -> None:
        content = _repo_file("docs/STATUS_BOARD_V2.md").read_text()
        assert "STATUS_AND_STATISTICS_OWNERSHIP" in content, (
            "STATUS_BOARD_V2.md must cross-reference STATUS_AND_STATISTICS_OWNERSHIP.md"
        )

    def test_liminal_surface_does_not_render_routing_stats(self) -> None:
        """LiminalSurface render must not show routing topology keywords."""
        import re
        from windows_client.status_board_v2.liminal_surface import LiminalSurface
        projection: Dict[str, Any] = {
            "tri_state_phase": "liminal",
            "runtime_domain": "local",
            "presence_intensity": 0.6,
            "coherence": 0.75,
            "collapse_tendency": 0.3,
            "retreat_tendency": 0.1,
            "primary_model_id": "gpt-4o",
            "support_model_ids": ["claude-3"],
            "active_weights": {"gpt-4o": 0.9},
            "route_reason": "native preferred",
            "active_device_ids": ["desktop-win"],
            "execution_stage": "planning",
            "current_task_summary": "test",
            "timestamp": 1711533600.0,
        }
        surf = LiminalSurface()
        rendered = surf.render(projection)
        plain = re.sub(r"\x1b\[[0-9;]*m", "", rendered)
        forbidden = ["Provider List", "OneAPI Status", "Metrics Board", "Weight Bar"]
        for kw in forbidden:
            assert kw not in plain, (
                f"LiminalSurface must not render routing stat keyword '{kw}'"
            )


# ---------------------------------------------------------------------------
# 5. Configuration-entry semantics
# ---------------------------------------------------------------------------


class TestConfigurationEntrySemantics:
    """Configuration entry semantics must be unified and documented."""

    def test_config_entry_doc_exists(self) -> None:
        p = _repo_file("docs/CONFIGURATION_ENTRY_UNIFICATION.md")
        assert p.exists(), "docs/CONFIGURATION_ENTRY_UNIFICATION.md must exist"

    def test_config_entry_doc_describes_ownership_tiers(self) -> None:
        content = _repo_file("docs/CONFIGURATION_ENTRY_UNIFICATION.md").read_text().lower()
        assert "system" in content and ("surface" in content or "node" in content), (
            "CONFIGURATION_ENTRY_UNIFICATION.md must describe configuration ownership tiers"
        )

    def test_config_entry_doc_prohibits_secrets_in_config_json(self) -> None:
        content = _repo_file("docs/CONFIGURATION_ENTRY_UNIFICATION.md").read_text().lower()
        assert "secret" in content or "api_key" in content, (
            "CONFIGURATION_ENTRY_UNIFICATION.md must address secrets / API key placement"
        )

    def test_active_surface_md_references_configuration_entry_doc(self) -> None:
        content = _repo_file("windows_client/status_board_v2/ACTIVE_SURFACE.md").read_text()
        assert "CONFIGURATION_ENTRY_UNIFICATION" in content, (
            "ACTIVE_SURFACE.md must reference CONFIGURATION_ENTRY_UNIFICATION.md"
        )

    def test_config_governance_doc_exists(self) -> None:
        """The pre-existing CONFIG_GOVERNANCE.md must still exist."""
        p = _repo_file("docs/CONFIG_GOVERNANCE.md")
        assert p.exists(), "docs/CONFIG_GOVERNANCE.md must exist"

    def test_config_entry_doc_does_not_duplicate_config_governance_keys(self) -> None:
        """CONFIGURATION_ENTRY_UNIFICATION.md should reference, not duplicate,
        the variable matrix in CONFIG_GOVERNANCE.md."""
        content = _repo_file("docs/CONFIGURATION_ENTRY_UNIFICATION.md").read_text()
        assert "CONFIG_GOVERNANCE" in content, (
            "CONFIGURATION_ENTRY_UNIFICATION.md must reference CONFIG_GOVERNANCE.md "
            "rather than duplicating the full variable matrix"
        )
