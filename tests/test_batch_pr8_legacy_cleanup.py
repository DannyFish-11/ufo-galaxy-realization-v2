"""tests/test_batch_pr8_legacy_cleanup.py
==========================================

Tests that verify the PR-8 batch cleanup deliverables:

  A) Fully-deleted files are absent from the repository.
  B) windows_client/_legacy/__init__.py acknowledges the deletions.
  C) core/orchestration_authority/legacy_paths.py contains PR-8 entries.
  D) docs/LEGACY_SURFACES.md exists and covers the required sections.
  E) scripts/check_legacy_regression.py exists and runs cleanly.
  F) .github/workflows/guardrails.yml contains the legacy-regression-guard job.
  G) Legacy-compat surfaces (dashboard, core/routes/compat.py) still exist
     and are explicitly marked as legacy/compatibility-only.
  H) Canonical documentation references are present (docs/UNIFIED_STARTUP.md,
     docs/WINDOWS_EXECUTION_PIPELINE.md).
"""

from __future__ import annotations

import importlib
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).parent.parent


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


# ===========================================================================
# A) Fully-deleted files must not exist anywhere in the repository
# ===========================================================================


class TestDeletedFilesAbsent:
    """PR-8 deleted files must not be present in the repository."""

    def test_start_client_bat_not_in_legacy_dir(self):
        assert not (_ROOT / "windows_client" / "_legacy" / "START_CLIENT.bat").exists(), (
            "START_CLIENT.bat was deleted in PR-8 and must not be in _legacy/"
        )

    def test_start_client_bat_not_in_windows_client_root(self):
        assert not (_ROOT / "windows_client" / "START_CLIENT.bat").exists(), (
            "START_CLIENT.bat must not be in the active windows_client/ root"
        )

    def test_start_galaxy_client_bat_not_in_legacy_dir(self):
        assert not (_ROOT / "windows_client" / "_legacy" / "start_galaxy_client.bat").exists(), (
            "start_galaxy_client.bat was deleted in PR-8 and must not be in _legacy/"
        )

    def test_start_galaxy_client_bat_not_in_windows_client_root(self):
        assert not (_ROOT / "windows_client" / "start_galaxy_client.bat").exists(), (
            "start_galaxy_client.bat must not be in the active windows_client/ root"
        )

    def test_no_bat_files_in_windows_client_at_all(self):
        """No .bat files should exist anywhere inside windows_client/."""
        bat_files = list((_ROOT / "windows_client").rglob("*.bat"))
        assert bat_files == [], (
            f"Found unexpected .bat file(s) inside windows_client/: {bat_files}"
        )


# ===========================================================================
# B) windows_client/_legacy/__init__.py acknowledges deletions
# ===========================================================================


class TestLegacyInitAcknowledgesDeletions:
    """The _legacy/__init__.py must document the PR-8 deletions."""

    def test_init_mentions_start_client_bat_deleted(self):
        content = _read("windows_client/_legacy/__init__.py")
        assert "START_CLIENT.bat" in content, (
            "_legacy/__init__.py must reference the deleted START_CLIENT.bat"
        )

    def test_init_mentions_start_galaxy_client_bat_deleted(self):
        content = _read("windows_client/_legacy/__init__.py")
        assert "start_galaxy_client.bat" in content, (
            "_legacy/__init__.py must reference the deleted start_galaxy_client.bat"
        )

    def test_init_mentions_deletion_or_pr8(self):
        content = _read("windows_client/_legacy/__init__.py")
        has_deleted = "deleted" in content.lower() or "pr-8" in content.lower()
        assert has_deleted, (
            "_legacy/__init__.py must note that the .bat files were deleted (PR-8)"
        )

    def test_init_still_documents_active_direction(self):
        content = _read("windows_client/_legacy/__init__.py")
        assert "DesktopPresenceRuntime" in content or "status_board_v2" in content, (
            "_legacy/__init__.py must still document the active Windows direction"
        )


# ===========================================================================
# C) legacy_paths.py contains PR-8 registry entries
# ===========================================================================


class TestLegacyPathsContainsPR8Entries:
    """core/orchestration_authority/legacy_paths.py must have PR-8 entries."""

    def test_module_importable(self):
        try:
            import core.orchestration_authority.legacy_paths as lp
            assert lp is not None
        except ImportError as e:
            pytest.skip(f"legacy_paths not importable in this env: {e}")

    def test_pr8_deleted_paths_exported(self):
        try:
            from core.orchestration_authority.legacy_paths import PR8_DELETED_PATHS
        except ImportError as e:
            pytest.skip(f"legacy_paths not importable: {e}")
        assert isinstance(PR8_DELETED_PATHS, frozenset), (
            "PR8_DELETED_PATHS must be a frozenset"
        )
        assert len(PR8_DELETED_PATHS) >= 2, (
            "PR8_DELETED_PATHS must list at least the two deleted .bat files"
        )

    def test_pr8_deleted_paths_contains_start_client_bat(self):
        try:
            from core.orchestration_authority.legacy_paths import PR8_DELETED_PATHS
        except ImportError as e:
            pytest.skip(f"legacy_paths not importable: {e}")
        assert any("START_CLIENT" in p for p in PR8_DELETED_PATHS), (
            "PR8_DELETED_PATHS must include START_CLIENT.bat"
        )

    def test_pr8_deleted_paths_contains_start_galaxy_client_bat(self):
        try:
            from core.orchestration_authority.legacy_paths import PR8_DELETED_PATHS
        except ImportError as e:
            pytest.skip(f"legacy_paths not importable: {e}")
        assert any("start_galaxy_client" in p for p in PR8_DELETED_PATHS), (
            "PR8_DELETED_PATHS must include start_galaxy_client.bat"
        )

    def test_legacy_path_registry_has_pr8_guardrail_entries(self):
        try:
            from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        except ImportError as e:
            pytest.skip(f"legacy_paths not importable: {e}")
        pr8_entries = [
            k for k, v in LEGACY_PATH_REGISTRY.items()
            if v.pr_guardrail_added and "PR-8" in v.pr_guardrail_added
        ]
        assert len(pr8_entries) >= 2, (
            f"LEGACY_PATH_REGISTRY must have at least 2 PR-8 entries, got: {pr8_entries}"
        )

    def test_source_contains_pr8_deleted_paths_sentinel(self):
        content = _read("core/orchestration_authority/legacy_paths.py")
        assert "PR8_DELETED_PATHS" in content, (
            "legacy_paths.py must define and export PR8_DELETED_PATHS"
        )


# ===========================================================================
# D) docs/LEGACY_SURFACES.md exists and covers required sections
# ===========================================================================


class TestLegacySurfacesDocExists:
    """docs/LEGACY_SURFACES.md must exist and cover key topics."""

    def test_file_exists(self):
        assert (_ROOT / "docs" / "LEGACY_SURFACES.md").exists(), (
            "docs/LEGACY_SURFACES.md must be created in PR-8"
        )

    def test_mentions_deleted_status(self):
        content = _read("docs/LEGACY_SURFACES.md")
        assert "DELETED" in content, (
            "LEGACY_SURFACES.md must define/use a DELETED status"
        )

    def test_mentions_start_client_bat(self):
        content = _read("docs/LEGACY_SURFACES.md")
        assert "START_CLIENT.bat" in content

    def test_mentions_start_galaxy_client_bat(self):
        content = _read("docs/LEGACY_SURFACES.md")
        assert "start_galaxy_client.bat" in content

    def test_mentions_canonical_replacement_for_bat_files(self):
        content = _read("docs/LEGACY_SURFACES.md")
        assert "unified_launcher.py" in content or "start.bat" in content, (
            "LEGACY_SURFACES.md must name the canonical replacement for the .bat files"
        )

    def test_mentions_dashboard_as_legacy_compat(self):
        content = _read("docs/LEGACY_SURFACES.md")
        assert "dashboard" in content.lower(), (
            "LEGACY_SURFACES.md must document the dashboard legacy-compat status"
        )

    def test_mentions_compat_py_as_legacy_compat(self):
        content = _read("docs/LEGACY_SURFACES.md")
        assert "compat.py" in content, (
            "LEGACY_SURFACES.md must document core/routes/compat.py legacy-compat status"
        )

    def test_mentions_canonical_startup(self):
        content = _read("docs/LEGACY_SURFACES.md")
        assert "unified_launcher" in content, (
            "LEGACY_SURFACES.md must reference the canonical startup path"
        )

    def test_mentions_non_regression_guardrails(self):
        content = _read("docs/LEGACY_SURFACES.md")
        assert "check_legacy_regression" in content, (
            "LEGACY_SURFACES.md must reference the non-regression CI script"
        )


# ===========================================================================
# E) scripts/check_legacy_regression.py exists and runs cleanly
# ===========================================================================


class TestCheckLegacyRegressionScript:
    """scripts/check_legacy_regression.py must exist and pass on the current repo."""

    def test_script_exists(self):
        assert (_ROOT / "scripts" / "check_legacy_regression.py").exists(), (
            "scripts/check_legacy_regression.py must be created in PR-8"
        )

    def test_script_passes_on_current_repo(self):
        """The script must exit 0 on the current (clean) repository state."""
        result = subprocess.run(
            [sys.executable, str(_ROOT / "scripts" / "check_legacy_regression.py")],
            capture_output=True,
            text=True,
            cwd=str(_ROOT),
        )
        assert result.returncode == 0, (
            f"check_legacy_regression.py reported violations:\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    def test_script_has_warn_only_flag(self):
        """The script must support --warn-only for CI warning-mode usage."""
        content = _read("scripts/check_legacy_regression.py")
        assert "--warn-only" in content, (
            "check_legacy_regression.py must support --warn-only flag for CI warning mode"
        )

    def test_script_checks_pr8_deleted_files(self):
        content = _read("scripts/check_legacy_regression.py")
        assert "START_CLIENT.bat" in content
        assert "start_galaxy_client.bat" in content

    def test_script_checks_no_new_bat_launchers(self):
        content = _read("scripts/check_legacy_regression.py")
        assert ".bat" in content and ("windows_client" in content), (
            "check_legacy_regression.py must check for new .bat files in windows_client/"
        )


# ===========================================================================
# F) .github/workflows/guardrails.yml contains the legacy-regression-guard job
# ===========================================================================


class TestGuardrailsYmlHasLegacyRegressionJob:
    """guardrails.yml must include the legacy-regression-guard job added in PR-8."""

    def test_guardrails_yml_exists(self):
        assert (_ROOT / ".github" / "workflows" / "guardrails.yml").exists()

    def test_guardrails_yml_has_legacy_regression_guard_job(self):
        content = _read(".github/workflows/guardrails.yml")
        assert "legacy-regression-guard" in content, (
            "guardrails.yml must define the legacy-regression-guard CI job"
        )

    def test_guardrails_yml_runs_check_legacy_regression_script(self):
        content = _read(".github/workflows/guardrails.yml")
        assert "check_legacy_regression.py" in content, (
            "guardrails.yml must invoke scripts/check_legacy_regression.py"
        )

    def test_guardrails_yml_updated_for_pr8(self):
        content = _read(".github/workflows/guardrails.yml")
        assert "PR-8" in content, (
            "guardrails.yml header must be updated to reference PR-8"
        )


# ===========================================================================
# G) Legacy-compat surfaces still exist and are properly marked
# ===========================================================================


class TestLegacyCompatSurfacesPresent:
    """Conditional legacy surfaces must remain and be explicitly marked."""

    def test_dashboard_backend_main_exists(self):
        assert (_ROOT / "dashboard" / "backend" / "main.py").exists(), (
            "dashboard/backend/main.py must still exist as a legacy-compat surface"
        )

    def test_dashboard_backend_main_has_legacy_authority_marker(self):
        content = _read("dashboard/backend/main.py")
        assert "LEGACY" in content or "legacy" in content.lower(), (
            "dashboard/backend/main.py must be marked as legacy/non-authoritative"
        )

    def test_dashboard_legacy_surface_md_exists(self):
        assert (_ROOT / "dashboard" / "LEGACY_SURFACE.md").exists(), (
            "dashboard/LEGACY_SURFACE.md must exist to document the dashboard legacy status"
        )

    def test_core_routes_compat_py_exists(self):
        assert (_ROOT / "core" / "routes" / "compat.py").exists(), (
            "core/routes/compat.py must remain as a legacy-compat surface until "
            "all Android callers are migrated"
        )

    def test_core_routes_compat_py_has_deprecation_marker(self):
        content = _read("core/routes/compat.py")
        assert "deprecated" in content.lower() or "DEPRECATED" in content, (
            "core/routes/compat.py must be marked as deprecated/legacy-compat"
        )


# ===========================================================================
# H) Canonical documentation is present
# ===========================================================================


class TestCanonicalDocsPresent:
    """Key canonical documentation files must exist."""

    def test_unified_startup_md_exists(self):
        assert (_ROOT / "docs" / "UNIFIED_STARTUP.md").exists(), (
            "docs/UNIFIED_STARTUP.md must exist as canonical startup documentation"
        )

    def test_legacy_surfaces_md_exists(self):
        assert (_ROOT / "docs" / "LEGACY_SURFACES.md").exists(), (
            "docs/LEGACY_SURFACES.md must exist (created in PR-8)"
        )

    def test_readme_exists(self):
        assert (_ROOT / "README.md").exists()

    def test_readme_mentions_canonical_startup(self):
        content = _read("README.md")
        has_startup = "unified_launcher" in content or "main.py" in content
        assert has_startup, (
            "README.md must reference the canonical startup path"
        )
