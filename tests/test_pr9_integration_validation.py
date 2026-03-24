"""
tests/test_pr9_integration_validation.py
========================================

PR-9 — Integration Validation Tests

Validates that the authoritative Galaxy runtime system is coherent after the
PR-1 through PR-8 structural cleanup sequence.  All tests are:

- Pure in-process (no subprocesses, no live ports, no network).
- Fast: each completes in < 1 s.
- Focused on the structural/startup invariants established by PR-1–PR-8.

Test groups
-----------
1. Authoritative startup path — main.py, unified_launcher.py, launcher/ package
2. Core authority chain — DesktopPresenceRuntime, OpenClawd, CommandRouter
3. Repository layout registry — active vs legacy directory classification
4. Node registry — node_dependencies.json consistency
5. Legacy surface isolation — dashboard/ and windows_client/ markers
6. Critical documentation — required docs present
7. Validation script — scripts/validate_runtime.py present and runnable
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# 1. Authoritative Startup Path
# ===========================================================================

class TestStartupPath:
    """The canonical startup path main.py → unified_launcher.py → launcher/ is intact."""

    def test_main_py_exists(self):
        assert (PROJECT_ROOT / "main.py").exists()

    def test_main_py_delegates_to_unified_launcher(self):
        content = (PROJECT_ROOT / "main.py").read_text()
        assert "unified_launcher" in content, (
            "main.py must reference unified_launcher.py"
        )

    def test_unified_launcher_exists(self):
        assert (PROJECT_ROOT / "unified_launcher.py").exists()

    def test_launcher_package_init_exists(self):
        assert (PROJECT_ROOT / "launcher" / "__init__.py").exists()

    @pytest.mark.parametrize("submodule", [
        "launcher.bootstrap",
        "launcher.service_manager",
        "launcher.core_services",
        "launcher.node_startup",
        "launcher.health_checks",
        "launcher.shutdown",
    ])
    def test_launcher_submodule_importable(self, submodule):
        importlib.import_module(submodule)

    def test_launcher_bootstrap_exports_system_config(self):
        from launcher.bootstrap import SystemConfig
        assert SystemConfig is not None

    def test_launcher_bootstrap_exports_system_state(self):
        from launcher.bootstrap import SystemState
        assert SystemState is not None

    def test_launcher_bootstrap_exports_print_status(self):
        from launcher.bootstrap import print_status
        assert callable(print_status)

    def test_launcher_service_manager_exports_service_manager(self):
        from launcher.service_manager import ServiceManager
        assert ServiceManager is not None

    def test_launcher_node_startup_exports_node_system_launcher(self):
        from launcher.node_startup import NodeSystemLauncher
        assert NodeSystemLauncher is not None

    def test_launcher_shutdown_exports_async_shutdown(self):
        from launcher.shutdown import async_shutdown
        assert callable(async_shutdown)

    def test_unified_launcher_imports_launcher_package(self):
        """unified_launcher.py must reference the launcher sub-package."""
        content = (PROJECT_ROOT / "unified_launcher.py").read_text()
        assert "from launcher" in content or "import launcher" in content, (
            "unified_launcher.py must import from the launcher/ sub-package"
        )


# ===========================================================================
# 2. Core Authority Chain
# ===========================================================================

class TestAuthorityChain:
    """The core authority chain modules are importable with correct class names."""

    def test_desktop_presence_runtime_importable(self):
        mod = importlib.import_module("core.desktop_presence_runtime")
        assert hasattr(mod, "DesktopPresenceRuntime")

    def test_openclawd_importable(self):
        mod = importlib.import_module("core.openclawd")
        assert hasattr(mod, "OpenClawd")

    def test_command_router_importable(self):
        mod = importlib.import_module("core.command_router")
        assert hasattr(mod, "CommandRouter")

    def test_repo_layout_registry_importable(self):
        mod = importlib.import_module("core.repo_layout_registry")
        assert hasattr(mod, "RepoLayoutRegistry")

    def test_architecture_baseline_doc_references_authority_chain(self):
        doc = PROJECT_ROOT / "docs" / "ARCHITECTURE_BASELINE.md"
        if not doc.exists():
            pytest.skip("ARCHITECTURE_BASELINE.md not present")
        content = doc.read_text()
        assert "DesktopPresenceRuntime" in content
        assert "OpenClawd" in content
        assert "CommandRouter" in content


# ===========================================================================
# 3. Repository Layout Registry
# ===========================================================================

class TestRepoLayoutRegistry:
    """core.repo_layout_registry correctly classifies directories."""

    @pytest.fixture(scope="class")
    def registry_helpers(self):
        from core.repo_layout_registry import (
            is_active_runtime_directory,
            is_active_desktop_status_directory,
            is_legacy_directory,
        )
        return is_active_runtime_directory, is_active_desktop_status_directory, is_legacy_directory

    @pytest.mark.parametrize("directory", ["core", "launcher", "nodes"])
    def test_active_runtime_directories(self, registry_helpers, directory):
        is_active_runtime, _, _ = registry_helpers
        assert is_active_runtime(directory), f"{directory!r} should be ACTIVE_RUNTIME"

    def test_status_board_v2_is_active_desktop_status(self, registry_helpers):
        _, is_active_status, _ = registry_helpers
        assert is_active_status("windows_client/status_board_v2"), (
            "'windows_client/status_board_v2' should be ACTIVE_DESKTOP_STATUS"
        )

    def test_dashboard_is_legacy(self, registry_helpers):
        _, _, is_legacy = registry_helpers
        assert is_legacy("dashboard"), "'dashboard' should be legacy"

    def test_get_repo_layout_registry_returns_singleton(self):
        from core.repo_layout_registry import get_repo_layout_registry
        r1 = get_repo_layout_registry()
        r2 = get_repo_layout_registry()
        assert r1 is r2

    def test_registry_has_entries(self):
        from core.repo_layout_registry import get_repo_layout_registry
        registry = get_repo_layout_registry()
        assert len(registry.active_entries()) > 0

    def test_core_entry_is_present(self):
        from core.repo_layout_registry import get_repo_layout_entry
        entry = get_repo_layout_entry("core")
        assert entry is not None
        assert "active" in entry.role.value.lower()

    def test_dashboard_entry_is_present(self):
        from core.repo_layout_registry import get_repo_layout_entry
        entry = get_repo_layout_entry("dashboard")
        assert entry is not None
        assert "legacy" in entry.role.value.lower()


# ===========================================================================
# 4. Node Registry Consistency
# ===========================================================================

class TestNodeRegistry:
    """node_dependencies.json is present, valid, and internally consistent."""

    @pytest.fixture(scope="class")
    def node_data(self):
        path = PROJECT_ROOT / "node_dependencies.json"
        assert path.exists(), "node_dependencies.json must exist"
        return json.loads(path.read_text())

    @pytest.fixture(scope="class")
    def nodes(self, node_data):
        nodes = node_data.get("nodes", {})
        assert nodes, "node_dependencies.json must contain a 'nodes' key"
        return nodes

    def test_node_dependencies_json_exists(self):
        assert (PROJECT_ROOT / "node_dependencies.json").exists()

    def test_node_dependencies_json_valid_json(self):
        path = PROJECT_ROOT / "node_dependencies.json"
        json.loads(path.read_text())

    def test_nodes_key_present(self, node_data):
        assert "nodes" in node_data

    def test_minimum_node_count(self, nodes):
        assert len(nodes) >= 100, f"Expected ≥100 nodes, got {len(nodes)}"

    def test_all_nodes_have_recognised_startup_policy(self, nodes):
        valid_policies = {"active", "optional", "skip"}
        invalid = [
            (node_id, entry.get("startup_policy", "active"))
            for node_id, entry in nodes.items()
            if entry.get("startup_policy", "active") not in valid_policies
        ]
        assert not invalid, (
            f"Nodes with unrecognised startup_policy: {invalid[:5]}"
        )

    def test_active_nodes_majority(self, nodes):
        active = sum(
            1 for e in nodes.values()
            if e.get("startup_policy", "active") == "active"
        )
        assert active >= 50, f"Expected ≥50 active nodes, got {active}"

    def test_skip_nodes_count_reasonable(self, nodes):
        skipped = sum(
            1 for e in nodes.values()
            if e.get("startup_policy") == "skip"
        )
        assert skipped <= 20, (
            f"Unexpectedly many skip-policy nodes: {skipped}"
        )

    def test_node_ids_have_expected_pattern(self, nodes):
        """Node IDs should follow the Node_NN_Name pattern."""
        malformed = [
            k for k in nodes if not (k.startswith("Node_") or k.startswith("node_"))
        ]
        # Allow up to 5 exceptions (may have infrastructure entries)
        assert len(malformed) <= 5, (
            f"Unexpected node ID format: {malformed[:5]}"
        )

    def test_pr7_metadata_present(self, node_data):
        """node_dependencies.json should carry PR-7 unification metadata."""
        assert "_pr7_node_unification" in node_data, (
            "node_dependencies.json should contain _pr7_node_unification key from PR-7"
        )


# ===========================================================================
# 5. Legacy Surface Isolation
# ===========================================================================

class TestLegacySurfaceIsolation:
    """Legacy surfaces carry their isolation markers and don't claim active authority."""

    def test_dashboard_legacy_surface_marker_exists(self):
        assert (PROJECT_ROOT / "dashboard" / "LEGACY_SURFACE.md").exists()

    def test_dashboard_frontend_legacy_surface_marker_exists(self):
        assert (PROJECT_ROOT / "dashboard" / "frontend" / "LEGACY_SURFACE.md").exists()

    def test_status_board_v2_active_surface_marker_exists(self):
        assert (
            PROJECT_ROOT / "windows_client" / "status_board_v2" / "ACTIVE_SURFACE.md"
        ).exists()

    def test_dashboard_readme_mentions_legacy_status(self):
        readme = PROJECT_ROOT / "dashboard" / "README.md"
        if not readme.exists():
            pytest.skip("dashboard/README.md not present")
        content = readme.read_text().lower()
        assert any(kw in content for kw in ("legacy", "demoted", "deprecated")), (
            "dashboard/README.md should describe its legacy/demoted status"
        )

    def test_dashboard_legacy_surface_md_content(self):
        marker = PROJECT_ROOT / "dashboard" / "LEGACY_SURFACE.md"
        content = marker.read_text().lower()
        assert any(kw in content for kw in ("legacy", "demoted", "deprecated", "dashboard"))

    def test_status_board_v2_active_surface_md_content(self):
        marker = PROJECT_ROOT / "windows_client" / "status_board_v2" / "ACTIVE_SURFACE.md"
        content = marker.read_text().lower()
        assert any(kw in content for kw in ("active", "canonical", "status_board", "status board"))


# ===========================================================================
# 6. Critical Documentation
# ===========================================================================

class TestCriticalDocs:
    """All required architecture and runbook docs are present."""

    @pytest.mark.parametrize("rel_path", [
        "docs/ARCHITECTURE_BASELINE.md",
        "docs/REPO_LAYOUT.md",
        "docs/NODE_ACTIVE_MANIFEST.md",
        "docs/ENTRYPOINT_AND_SURFACE_DEMOTION.md",
        "docs/UNIFIED_STARTUP.md",
        "docs/MAINTAINER_RUNBOOK.md",
    ])
    def test_required_doc_exists(self, rel_path):
        assert (PROJECT_ROOT / rel_path).exists(), (
            f"Required doc not found: {rel_path}"
        )

    def test_maintainer_runbook_contains_startup_section(self):
        doc = PROJECT_ROOT / "docs" / "MAINTAINER_RUNBOOK.md"
        content = doc.read_text()
        assert "main.py" in content
        assert "unified_launcher" in content

    def test_maintainer_runbook_contains_legacy_section(self):
        doc = PROJECT_ROOT / "docs" / "MAINTAINER_RUNBOOK.md"
        content = doc.read_text().lower()
        assert "legacy" in content
        assert "dashboard" in content

    def test_maintainer_runbook_contains_validation_section(self):
        doc = PROJECT_ROOT / "docs" / "MAINTAINER_RUNBOOK.md"
        content = doc.read_text()
        assert "validate_runtime.py" in content

    def test_architecture_baseline_contains_authority_policy(self):
        doc = PROJECT_ROOT / "docs" / "ARCHITECTURE_BASELINE.md"
        content = doc.read_text()
        assert "OpenClawd" in content
        assert "DesktopPresenceRuntime" in content

    def test_repo_layout_doc_contains_active_legacy_split(self):
        doc = PROJECT_ROOT / "docs" / "REPO_LAYOUT.md"
        content = doc.read_text()
        assert "ACTIVE_RUNTIME" in content or "active_runtime" in content.lower()
        assert "LEGACY" in content or "legacy" in content.lower()


# ===========================================================================
# 7. Validation Script
# ===========================================================================

class TestValidationScript:
    """scripts/validate_runtime.py exists and is runnable as a module."""

    @pytest.fixture(scope="class")
    def script_path(self):
        return PROJECT_ROOT / "scripts" / "validate_runtime.py"

    def test_validate_runtime_script_exists(self, script_path):
        assert script_path.exists()

    def test_validate_runtime_script_has_main(self, script_path):
        content = script_path.read_text()
        assert "def main(" in content

    def test_validate_runtime_script_has_json_flag(self, script_path):
        content = script_path.read_text()
        assert "--json" in content

    def test_validate_runtime_script_has_strict_flag(self, script_path):
        content = script_path.read_text()
        assert "--strict" in content

    def test_validate_runtime_module_importable(self):
        """The validation script can be imported without side effects."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "validate_runtime",
            PROJECT_ROOT / "scripts" / "validate_runtime.py",
        )
        mod = importlib.util.module_from_spec(spec)
        # Load but do not call main — just confirm it imports cleanly
        spec.loader.exec_module(mod)
        assert hasattr(mod, "main")
        assert hasattr(mod, "check_startup_path")
        assert hasattr(mod, "check_authority_chain")
        assert hasattr(mod, "check_node_registry")
        assert hasattr(mod, "check_legacy_isolation")
        assert hasattr(mod, "check_docs")
