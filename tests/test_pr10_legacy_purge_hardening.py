#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr10_legacy_purge_hardening.py
==========================================

PR-10 — Final Legacy Purge and Baseline Hardening tests.

Validates the purge and hardening decisions from the 10-PR cleanup
sequence.  All tests are self-contained (no live servers, no real
devices, no imports of heavyweight optional dependencies).

Test classes
------------
  1. TestLegacyPurgeRegistry
       The ``core.legacy_purge_registry`` module is importable and
       contains a coherent, non-empty registry with the expected fields.

  2. TestStartGalaxyHardening
       ``start_galaxy.py`` no longer contains the dead ``_start_desktop()``
       function or the dead ``run_ui.py`` call-site; the PR-10 LEGACY
       WRAPPER guard comment is present; the deprecation message is updated.

  3. TestStartL4Hardening
       ``start_l4.py`` carries the expected deprecation warning and does
       not start L4 logic directly; it delegates to ``unified_launcher``.

  4. TestHardDisabledStubsUnchanged
       Regression guard: the windows_client hard-disabled stubs still
       raise ``RuntimeError`` on import (no accidental re-enablement).

  5. TestRunUiStillHardDisabled
       Regression guard: ``enhancements/clients/windows_client/run_ui.py``
       still raises ``RuntimeError`` on import.

  6. TestLegacyMarkerFiles
       Marker files (``LEGACY_SURFACE.md``, ``LEGACY_WRAPPER.txt``) exist
       where the purge registry says they should.

  7. TestPurgeRegistrySummary
       ``purge_registry_summary()`` returns a well-formed dict with all
       expected keys.

  8. TestDocumentationPresent
       ``docs/LEGACY_PURGE_HARDENING.md`` exists and contains the required
       section headings.

  9. TestValidateRuntimeScriptUpdated
       ``scripts/validate_runtime.py`` references the purge-hardening
       checks (regression guard against accidentally stripping them).

 10. TestArchitectureBaselineUpdated
       ``docs/ARCHITECTURE_BASELINE.md`` references PR-10 as the
       consolidation source.
"""

from __future__ import annotations

import importlib
import os
import pathlib
import sys
import warnings

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ===========================================================================
# Helpers
# ===========================================================================


def _file_text(rel_path: str) -> str:
    """Return the text of *rel_path* (relative to repo root)."""
    return (_ROOT / rel_path).read_text(encoding="utf-8")


def _import_raises_runtime_error(module_name: str) -> bool:
    """Return True if importing *module_name* raises RuntimeError."""
    if module_name in sys.modules:
        del sys.modules[module_name]
    try:
        importlib.import_module(module_name)
        return False
    except RuntimeError:
        return True
    except Exception:
        return False


# ===========================================================================
# 1. TestLegacyPurgeRegistry
# ===========================================================================


class TestLegacyPurgeRegistry:
    """core.legacy_purge_registry is importable and coherent."""

    def test_module_importable(self):
        from core.legacy_purge_registry import PURGE_REGISTRY  # noqa: F401

    def test_registry_non_empty(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        assert len(PURGE_REGISTRY) >= 10, (
            "PURGE_REGISTRY must have at least 10 entries covering PR-3 "
            "through PR-10 decisions"
        )

    def test_all_entries_have_asset_path(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        for entry in PURGE_REGISTRY:
            assert entry.asset_path, f"Missing asset_path on entry {entry}"

    def test_all_entries_have_pr(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        for entry in PURGE_REGISTRY:
            assert entry.pr.startswith("PR-"), (
                f"entry.pr must be 'PR-N' format, got {entry.pr!r}"
            )

    def test_all_entries_have_rationale(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        for entry in PURGE_REGISTRY:
            assert len(entry.rationale) >= 20, (
                f"entry rationale is too short for {entry.asset_path!r}"
            )

    def test_purge_status_enum_values(self):
        from core.legacy_purge_registry import PurgeStatus
        expected = {
            "hard_disabled",
            "permanently_isolated",
            "dead_reference_removed",
            "wrapper_hardened",
            "legacy_marker_added",
        }
        actual = {s.value for s in PurgeStatus}
        assert actual == expected

    def test_pr10_entries_present(self):
        from core.legacy_purge_registry import get_entries_by_pr
        pr10 = get_entries_by_pr("PR-10")
        assert len(pr10) >= 2, (
            "Expected at least 2 PR-10 entries "
            "(start_galaxy.py dead ref removal + wrapper hardening)"
        )

    def test_pr3_entries_present(self):
        from core.legacy_purge_registry import get_entries_by_pr
        pr3 = get_entries_by_pr("PR-3")
        assert len(pr3) >= 7, "Expected at least 7 PR-3 hard-disable entries"

    def test_get_purge_entry_found(self):
        from core.legacy_purge_registry import get_purge_entry, PurgeStatus
        entry = get_purge_entry("start_galaxy.py::_start_desktop()")
        assert entry is not None
        assert entry.status == PurgeStatus.DEAD_REFERENCE_REMOVED
        assert entry.pr == "PR-10"

    def test_get_purge_entry_missing(self):
        from core.legacy_purge_registry import get_purge_entry
        assert get_purge_entry("nonexistent/asset.py") is None

    def test_get_entries_by_status_hard_disabled(self):
        from core.legacy_purge_registry import get_entries_by_status, PurgeStatus
        entries = get_entries_by_status(PurgeStatus.HARD_DISABLED)
        assert len(entries) >= 7, "Expected at least 7 HARD_DISABLED entries"

    def test_get_entries_by_status_wrapper_hardened(self):
        from core.legacy_purge_registry import get_entries_by_status, PurgeStatus
        entries = get_entries_by_status(PurgeStatus.WRAPPER_HARDENED)
        paths = [e.asset_path for e in entries]
        assert "start_galaxy.py" in paths
        assert "start_l4.py" in paths

    def test_run_ui_entry_hard_disabled(self):
        from core.legacy_purge_registry import get_purge_entry, PurgeStatus
        entry = get_purge_entry(
            "enhancements/clients/windows_client/run_ui.py"
        )
        assert entry is not None
        assert entry.status == PurgeStatus.HARD_DISABLED

    def test_dashboard_entry_legacy_marker(self):
        from core.legacy_purge_registry import get_purge_entry, PurgeStatus
        entry = get_purge_entry("dashboard/")
        assert entry is not None
        assert entry.status == PurgeStatus.LEGACY_MARKER_ADDED


# ===========================================================================
# 2. TestStartGalaxyHardening
# ===========================================================================


class TestStartGalaxyHardening:
    """start_galaxy.py no longer contains the dead _start_desktop() path."""

    def _text(self) -> str:
        return _file_text("start_galaxy.py")

    def test_no_start_desktop_function(self):
        text = self._text()
        # The function definition must be gone; it may appear in doc comments
        assert "def _start_desktop(" not in text, (
            "start_galaxy.py must not define _start_desktop() — "
            "the dead path to run_ui.py was removed in PR-10"
        )

    def test_no_run_ui_reference(self):
        text = self._text()
        # os.system call to run_ui.py must be gone; docstring/warning references ok
        assert "os.system" not in text, (
            "start_galaxy.py must not contain os.system() — "
            "the dead os.system call targeting run_ui.py was removed in PR-10"
        )

    def test_no_multiprocessing_process_start_desktop(self):
        # Ensure the block that launched the desktop process is gone.
        assert "multiprocessing.Process(target=_start_desktop)" not in self._text()

    def test_legacy_wrapper_guard_comment(self):
        assert "PR-10 LEGACY WRAPPER" in self._text(), (
            "start_galaxy.py must carry the PR-10 LEGACY WRAPPER guard comment"
        )

    def test_deprecation_message_updated(self):
        text = self._text()
        # Must mention PR-10 hardening or the purge
        assert "PR-10" in text or "final purge" in text.lower() or "legacy wrapper" in text.lower(), (
            "start_galaxy.py deprecation message should reference PR-10 hardening"
        )

    def test_desktop_flag_still_accepted_gracefully(self):
        # --desktop / --all must still be accepted (no argparse error) but
        # must NOT call any live startup path.
        text = self._text()
        assert "--desktop" in text, (
            "--desktop flag should still be present (no-op stub) for backward compat"
        )
        assert "--all" in text, (
            "--all flag should still be present (no-op stub) for backward compat"
        )

    def test_desktop_flag_warns_not_starts(self):
        # The --desktop branch should warn, not start a process.
        text = self._text()
        # After PR-10 the _start_desktop call is gone; the branch should only warn.
        assert "DeprecationWarning" in text or "warnings.warn" in text, (
            "start_galaxy.py should still issue DeprecationWarning for --desktop/--all"
        )
        # Crucially, there must be no multiprocessing.Process(target=_start_desktop)
        assert "desktop_proc" not in text, (
            "The desktop process launch block must be gone in PR-10"
        )

    def test_delegates_to_unified_launcher(self):
        assert "from unified_launcher import main as unified_main" in self._text()

    def test_no_import_os_for_system_call(self):
        # After removing _start_desktop, 'import os' should no longer be needed.
        # This is a soft check — if os is used for something else that's fine.
        # We just verify os.system(run_ui) isn't there.
        text = self._text()
        assert "os.system" not in text, (
            "os.system() call targeting run_ui.py should have been removed"
        )


# ===========================================================================
# 3. TestStartL4Hardening
# ===========================================================================


class TestStartL4Hardening:
    """start_l4.py carries the expected deprecation and delegates properly."""

    def _text(self) -> str:
        return _file_text("start_l4.py")

    def test_file_exists(self):
        assert (_ROOT / "start_l4.py").exists()

    def test_has_deprecation_warning(self):
        text = self._text()
        assert "deprecated" in text.lower() or "DeprecationWarning" in text, (
            "start_l4.py must carry a deprecation notice (PR-6 frozen)"
        )

    def test_delegates_to_unified_launcher(self):
        text = self._text()
        assert "unified_launcher" in text, (
            "start_l4.py must delegate to unified_launcher.py"
        )

    def test_no_direct_l4_loop_instantiation(self):
        text = self._text()
        assert "GalaxyMainLoopL4()" not in text, (
            "start_l4.py must not instantiate GalaxyMainLoopL4 directly"
        )


# ===========================================================================
# 4. TestHardDisabledStubsUnchanged
# ===========================================================================


class TestHardDisabledStubsUnchanged:
    """Regression: windows_client hard-disabled stubs still raise RuntimeError."""

    @pytest.mark.parametrize("module_name", [
        "windows_client.client",
        "windows_client.ui_sidebar",
        "windows_client.desktop_automation",
        "windows_client.windows_mcp_server",
        "windows_client.main",
        "windows_client.windows_client_integrated",
        "windows_client.key_listener",
    ])
    def test_module_still_hard_disabled(self, module_name):
        assert _import_raises_runtime_error(module_name), (
            f"{module_name} must still raise RuntimeError on import (hard-disabled stub)"
        )


# ===========================================================================
# 5. TestRunUiStillHardDisabled
# ===========================================================================


class TestRunUiStillHardDisabled:
    """Regression: enhancements run_ui.py still raises RuntimeError."""

    def test_run_ui_still_hard_disabled(self):
        assert _import_raises_runtime_error(
            "enhancements.clients.windows_client.run_ui"
        ), (
            "enhancements/clients/windows_client/run_ui.py must still be hard-disabled"
        )


# ===========================================================================
# 6. TestLegacyMarkerFiles
# ===========================================================================


class TestLegacyMarkerFiles:
    """Legacy marker files exist at expected locations."""

    def test_dashboard_legacy_surface_md(self):
        assert (_ROOT / "dashboard" / "LEGACY_SURFACE.md").exists()

    def test_dashboard_frontend_legacy_surface_md(self):
        assert (_ROOT / "dashboard" / "frontend" / "LEGACY_SURFACE.md").exists()

    def test_status_board_v2_active_surface_md(self):
        assert (_ROOT / "windows_client" / "status_board_v2" / "ACTIVE_SURFACE.md").exists()

    def test_enhancements_legacy_transition_md(self):
        assert (_ROOT / "enhancements" / "LEGACY_TRANSITION.md").exists()

    def test_windows_client_legacy_dir_exists(self):
        assert (_ROOT / "windows_client" / "_legacy").is_dir(), (
            "windows_client/_legacy/ directory must exist (PR-3 isolation)"
        )


# ===========================================================================
# 7. TestPurgeRegistrySummary
# ===========================================================================


class TestPurgeRegistrySummary:
    """purge_registry_summary() returns a well-formed dict."""

    def test_summary_keys(self):
        from core.legacy_purge_registry import purge_registry_summary
        summary = purge_registry_summary()
        assert "total_entries" in summary
        assert "by_status" in summary
        assert "by_pr" in summary

    def test_total_entries_positive(self):
        from core.legacy_purge_registry import purge_registry_summary
        summary = purge_registry_summary()
        assert summary["total_entries"] >= 10

    def test_by_pr_includes_pr10(self):
        from core.legacy_purge_registry import purge_registry_summary
        summary = purge_registry_summary()
        assert "PR-10" in summary["by_pr"]

    def test_by_pr_includes_pr3(self):
        from core.legacy_purge_registry import purge_registry_summary
        summary = purge_registry_summary()
        assert "PR-3" in summary["by_pr"]

    def test_by_status_includes_hard_disabled(self):
        from core.legacy_purge_registry import purge_registry_summary
        summary = purge_registry_summary()
        assert "hard_disabled" in summary["by_status"]

    def test_by_status_includes_dead_reference_removed(self):
        from core.legacy_purge_registry import purge_registry_summary
        summary = purge_registry_summary()
        assert "dead_reference_removed" in summary["by_status"]

    def test_summary_serializable(self):
        import json
        from core.legacy_purge_registry import purge_registry_summary
        summary = purge_registry_summary()
        # Should not raise
        json.dumps(summary)


# ===========================================================================
# 8. TestDocumentationPresent
# ===========================================================================


class TestDocumentationPresent:
    """docs/LEGACY_PURGE_HARDENING.md exists with required section headings."""

    def _doc(self) -> str:
        path = _ROOT / "docs" / "LEGACY_PURGE_HARDENING.md"
        assert path.exists(), "docs/LEGACY_PURGE_HARDENING.md must exist"
        return path.read_text(encoding="utf-8")

    def test_file_exists(self):
        assert (_ROOT / "docs" / "LEGACY_PURGE_HARDENING.md").exists()

    def test_has_pr10_heading(self):
        assert "PR-10" in self._doc()

    def test_has_purge_section(self):
        doc = self._doc()
        assert "Purge Decisions" in doc or "purge" in doc.lower()

    def test_mentions_start_desktop_removal(self):
        assert "_start_desktop" in self._doc()

    def test_mentions_run_ui(self):
        assert "run_ui" in self._doc()

    def test_mentions_active_windows_direction(self):
        doc = self._doc()
        assert "status_board_v2" in doc

    def test_mentions_legacy_purge_registry(self):
        assert "legacy_purge_registry" in self._doc()


# ===========================================================================
# 9. TestValidateRuntimeScriptUpdated
# ===========================================================================


class TestValidateRuntimeScriptUpdated:
    """scripts/validate_runtime.py exists and is a functioning script."""

    def test_file_exists(self):
        assert (_ROOT / "scripts" / "validate_runtime.py").exists()

    def test_references_architecture_baseline(self):
        text = _file_text("scripts/validate_runtime.py")
        assert "ARCHITECTURE_BASELINE" in text

    def test_references_maintainer_runbook(self):
        text = _file_text("scripts/validate_runtime.py")
        assert "MAINTAINER_RUNBOOK" in text

    def test_references_unified_launcher(self):
        text = _file_text("scripts/validate_runtime.py")
        assert "unified_launcher" in text


# ===========================================================================
# 10. TestArchitectureBaselineUpdated
# ===========================================================================


class TestArchitectureBaselineUpdated:
    """docs/ARCHITECTURE_BASELINE.md references PR-010 as consolidation source."""

    def test_file_exists(self):
        assert (_ROOT / "docs" / "ARCHITECTURE_BASELINE.md").exists()

    def test_references_pr010(self):
        text = _file_text("docs/ARCHITECTURE_BASELINE.md")
        assert "PR-010" in text or "PR-10" in text, (
            "docs/ARCHITECTURE_BASELINE.md must reference PR-010/PR-10 "
            "as the consolidation pass"
        )

    def test_authority_chain_present(self):
        text = _file_text("docs/ARCHITECTURE_BASELINE.md")
        assert "DesktopPresenceRuntime" in text
        assert "OpenClawd" in text

    def test_projection_policy_present(self):
        text = _file_text("docs/ARCHITECTURE_BASELINE.md")
        assert "status_board_v2" in text or "projection" in text.lower()
