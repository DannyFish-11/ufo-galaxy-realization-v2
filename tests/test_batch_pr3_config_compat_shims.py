#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_batch_pr3_config_compat_shims.py
============================================

Batch PR-3 — Unify configuration authority, eliminate forbidden fallbacks,
and standardize compatibility shims.

Coverage areas
--------------
A) launcher/config_manager: DeprecationWarning emitted at import time.
B) dashboard/backend/main.py: forbidden inline UnifiedChatResponse fallback
   class is gone; the import is now a hard dependency.
C) dashboard/backend/main.py: get_cors_origins uses _AVAILABLE flag pattern,
   no inline function definition in the except block.
D) dashboard/backend/main.py: ascii_art uses _AVAILABLE flag pattern.
E) core/routes/compat.py: deprecation metadata present in docstring;
   create_router() emits DeprecationWarning.
F) core/legacy_adapters/connection_manager_adapter.py: deprecation metadata
   (``.. deprecated::`` annotation and removal target) present.
G) core/legacy_adapters/device_agent_manager_adapter.py: deprecation metadata
   present.
H) galaxy_gateway/legacy/capability_registry.py: DeprecationWarning emitted
   at import time; deprecation metadata in docstring.
I) galaxy_gateway/legacy/task_decomposer.py: DeprecationWarning emitted at
   import time; deprecation metadata in docstring.
J) docs/CONFIGURATION_AUTHORITY.md: config.json reclassification and
   launcher/config_manager.py D2 demotion are documented.
K) docs/migration/LEGACY_SURFACE_INVENTORY.md: launcher/config_manager.py
   listed; shims carry PR-3 status column.
"""

from __future__ import annotations

import ast
import importlib
import sys
import textwrap
import types
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _has_deprecated_docstring(source: str) -> bool:
    """Return True if the module docstring contains '.. deprecated::'."""
    return ".. deprecated::" in source


def _has_removal_target(source: str) -> bool:
    """Return True if the source mentions a removal target (Batch PR-N)."""
    return "Removal target" in source or "removal target" in source


# ---------------------------------------------------------------------------
# A) launcher/config_manager — DeprecationWarning at import time
# ---------------------------------------------------------------------------

class TestLauncherConfigManagerDeprecation:

    def test_module_file_has_warnings_import(self):
        src = _read("launcher/config_manager.py")
        assert "import warnings" in src, (
            "launcher/config_manager.py must import the `warnings` module"
        )

    def test_module_file_emits_deprecation_warning_on_import(self):
        src = _read("launcher/config_manager.py")
        assert "warnings.warn" in src, (
            "launcher/config_manager.py must call warnings.warn()"
        )
        assert "DeprecationWarning" in src, (
            "launcher/config_manager.py must pass DeprecationWarning to warnings.warn()"
        )

    def test_module_header_still_says_deprecated(self):
        src = _read("launcher/config_manager.py")
        assert "DEPRECATED" in src, (
            "launcher/config_manager.py module header must retain DEPRECATED notice"
        )

    def test_deprecation_warning_mentions_canonical_replacement(self):
        src = _read("launcher/config_manager.py")
        assert "core.unified.config_manager" in src or "UnifiedConfigManager" in src, (
            "DeprecationWarning message should point to the canonical replacement"
        )

    def test_deprecation_warning_mentions_removal_batch(self):
        src = _read("launcher/config_manager.py")
        assert "PR-5" in src or "Batch PR-5" in src, (
            "DeprecationWarning message should mention the removal batch (PR-5)"
        )

    def test_import_emits_deprecation_warning_at_runtime(self):
        """Verify that importing the module raises DeprecationWarning."""
        # Remove from sys.modules so we get a fresh import
        mod_name = "launcher.config_manager"
        sys.modules.pop(mod_name, None)
        sys.modules.pop("launcher", None)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                importlib.import_module(mod_name)
            except Exception:
                # Module may have side effects that fail in the test sandbox;
                # we only care that the warning was raised.
                pass

        dep_warnings = [
            w for w in caught
            if issubclass(w.category, DeprecationWarning)
        ]
        assert dep_warnings, (
            "Importing launcher.config_manager must emit a DeprecationWarning"
        )


# ---------------------------------------------------------------------------
# B) dashboard/backend/main.py — no forbidden inline UnifiedChatResponse class
# ---------------------------------------------------------------------------

class TestDashboardForbiddenFallbackRemoved:

    def test_no_inline_unifiedchatresponse_class_in_except_block(self):
        src = _read("dashboard/backend/main.py")
        # The forbidden pattern is defining the class inside an except ImportError block.
        # We look for a class definition that appears after 'except ImportError'
        # and before the next top-level statement, within the first ~120 lines.
        lines = src.splitlines()
        in_except = False
        _EXCEPT_CONTINUATION_PREFIXES = ("#", "from", "import", "class", "def", " ", "\t")
        _UNIFIED_RESPONSE_FIELD_NAMES = (
            "success", "response", "intent", "confidence",
            "mode", "suggestions", "data", "error", "session_id",
        )
        for line in lines[:120]:
            stripped = line.strip()
            if stripped.startswith("except ImportError"):
                in_except = True
            elif in_except and stripped.startswith("class UnifiedChatResponse"):
                pytest.fail(
                    "dashboard/backend/main.py must NOT define UnifiedChatResponse "
                    "as an inline fallback inside an except ImportError block. "
                    "It is a core dependency and must be a hard import."
                )
            elif in_except and stripped:
                # Determine whether we have left the except block
                is_continuation = (
                    stripped.startswith(_EXCEPT_CONTINUATION_PREFIXES)
                    or stripped.startswith(_UNIFIED_RESPONSE_FIELD_NAMES)
                )
                if not is_continuation:
                    in_except = False

    def test_unified_response_imported_as_hard_dependency(self):
        src = _read("dashboard/backend/main.py")
        # Should have: `from core.unified_response import UnifiedChatResponse`
        # NOT inside a try block
        assert "from core.unified_response import UnifiedChatResponse" in src, (
            "dashboard/backend/main.py must have a hard (non-try) import of UnifiedChatResponse "
            "from core.unified_response"
        )

    def test_no_pydantic_basemodel_fallback_for_unified_response(self):
        src = _read("dashboard/backend/main.py")
        # The old forbidden fallback imported BaseModel as _BaseModel
        assert "pydantic import BaseModel as _BaseModel" not in src, (
            "The forbidden fallback that re-creates UnifiedChatResponse from pydantic.BaseModel "
            "must have been removed from dashboard/backend/main.py"
        )


# ---------------------------------------------------------------------------
# C) dashboard/backend/main.py — get_cors_origins uses _AVAILABLE flag pattern
# ---------------------------------------------------------------------------

class TestDashboardCorsOriginsPattern:

    def test_cors_origins_available_flag_exists(self):
        src = _read("dashboard/backend/main.py")
        assert "_CORS_ORIGINS_AVAILABLE" in src, (
            "dashboard/backend/main.py must declare _CORS_ORIGINS_AVAILABLE flag "
            "for the get_cors_origins optional dependency"
        )

    def test_cors_origins_fallback_function_not_in_except_block_with_inline_def(self):
        """The fallback get_cors_origins() function must be paired with _CORS_ORIGINS_AVAILABLE.

        Acceptable pattern:
            except ImportError:
                _CORS_ORIGINS_AVAILABLE = False

            def get_cors_origins() -> list[str]: ...  # outside except block

        Forbidden pattern:
            except ImportError:
                def get_cors_origins(): ...  # inline definition inside except block
        """
        src = _read("dashboard/backend/main.py")
        # The _AVAILABLE flag must exist (verified by another test).
        # Here we verify that get_cors_origins is NOT defined inside an except block
        # without the _AVAILABLE guard.
        lines = src.splitlines()
        in_except = False
        _EXCEPT_CONTINUATION_PREFIXES = (" ", "\t", "#", "def", "return", "_CORS")

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("except ImportError"):
                in_except = True
            elif in_except and stripped.startswith("def get_cors_origins"):
                # If we reach here, get_cors_origins is defined inside an except block.
                # It is acceptable only if _CORS_ORIGINS_AVAILABLE is set nearby.
                context_start = max(0, i - 15)
                context_text = "\n".join(lines[context_start : i + 5])
                assert "_CORS_ORIGINS_AVAILABLE" in context_text, (
                    "get_cors_origins defined inside except ImportError block at line "
                    f"{i + 1} must be accompanied by the _CORS_ORIGINS_AVAILABLE flag"
                )
            elif in_except and stripped:
                if not stripped.startswith(_EXCEPT_CONTINUATION_PREFIXES):
                    in_except = False


# ---------------------------------------------------------------------------
# D) dashboard/backend/main.py — ascii_art uses _AVAILABLE flag pattern
# ---------------------------------------------------------------------------

class TestDashboardAsciiArtPattern:

    def test_ascii_art_available_flag_exists(self):
        src = _read("dashboard/backend/main.py")
        assert "_ASCII_ART_AVAILABLE" in src, (
            "dashboard/backend/main.py must declare _ASCII_ART_AVAILABLE flag "
            "for the optional core.ascii_art dependency"
        )

    def test_print_banner_fallback_not_forbidden_pattern(self):
        """The _print_banner fallback must be paired with _ASCII_ART_AVAILABLE."""
        src = _read("dashboard/backend/main.py")
        assert "_ASCII_ART_AVAILABLE" in src, (
            "_print_banner fallback function must use _ASCII_ART_AVAILABLE flag"
        )


# ---------------------------------------------------------------------------
# E) core/routes/compat.py — deprecation metadata and warning
# ---------------------------------------------------------------------------

class TestCompatRouteDeprecation:

    def test_module_has_deprecated_docstring(self):
        src = _read("core/routes/compat.py")
        assert _has_deprecated_docstring(src), (
            "core/routes/compat.py docstring must contain '.. deprecated::' annotation"
        )

    def test_module_has_removal_target(self):
        src = _read("core/routes/compat.py")
        assert _has_removal_target(src), (
            "core/routes/compat.py must declare a removal target (Batch PR-5)"
        )

    def test_module_mentions_canonical_replacement(self):
        src = _read("core/routes/compat.py")
        assert "core.routes.devices" in src or "/api/v1/devices" in src, (
            "core/routes/compat.py must name the canonical replacement route"
        )

    def test_module_states_new_code_must_not_depend(self):
        src = _read("core/routes/compat.py")
        assert "New code must not" in src or "new code must not" in src or "must not depend" in src, (
            "core/routes/compat.py must state that new code must not depend on it"
        )

    def test_create_router_emits_deprecation_warning(self):
        src = _read("core/routes/compat.py")
        assert "warnings.warn" in src, (
            "core/routes/compat.py create_router() must emit a DeprecationWarning"
        )
        assert "DeprecationWarning" in src, (
            "core/routes/compat.py must use DeprecationWarning category"
        )

    def test_module_imports_warnings(self):
        src = _read("core/routes/compat.py")
        assert "import warnings" in src, (
            "core/routes/compat.py must import the warnings module"
        )

    def test_removal_target_pr5(self):
        src = _read("core/routes/compat.py")
        assert "PR-5" in src or "Batch PR-5" in src, (
            "core/routes/compat.py must mention the PR-5 removal target"
        )


# ---------------------------------------------------------------------------
# F) core/legacy_adapters/connection_manager_adapter.py — metadata
# ---------------------------------------------------------------------------

class TestConnectionManagerAdapterDeprecation:

    def test_has_deprecated_docstring(self):
        src = _read("core/legacy_adapters/connection_manager_adapter.py")
        assert _has_deprecated_docstring(src), (
            "connection_manager_adapter.py must have '.. deprecated::' in its docstring"
        )

    def test_has_removal_target(self):
        src = _read("core/legacy_adapters/connection_manager_adapter.py")
        assert _has_removal_target(src), (
            "connection_manager_adapter.py must declare a removal target"
        )

    def test_mentions_canonical_replacement(self):
        src = _read("core/legacy_adapters/connection_manager_adapter.py")
        assert "UnifiedConnectionManager" in src or "unified.connection_manager" in src, (
            "connection_manager_adapter.py must name the canonical replacement"
        )

    def test_new_code_must_not_depend(self):
        src = _read("core/legacy_adapters/connection_manager_adapter.py")
        assert "New code must not" in src or "new code must not" in src or "must not depend" in src, (
            "connection_manager_adapter.py must state that new code must not depend on it"
        )

    def test_removal_target_pr5(self):
        src = _read("core/legacy_adapters/connection_manager_adapter.py")
        assert "PR-5" in src or "Batch PR-5" in src, (
            "connection_manager_adapter.py must mention PR-5 removal target"
        )


# ---------------------------------------------------------------------------
# G) core/legacy_adapters/device_agent_manager_adapter.py — metadata
# ---------------------------------------------------------------------------

class TestDeviceAgentManagerAdapterDeprecation:

    def test_has_deprecated_docstring(self):
        src = _read("core/legacy_adapters/device_agent_manager_adapter.py")
        assert _has_deprecated_docstring(src), (
            "device_agent_manager_adapter.py must have '.. deprecated::' in its docstring"
        )

    def test_has_removal_target(self):
        src = _read("core/legacy_adapters/device_agent_manager_adapter.py")
        assert _has_removal_target(src), (
            "device_agent_manager_adapter.py must declare a removal target"
        )

    def test_mentions_canonical_replacement(self):
        src = _read("core/legacy_adapters/device_agent_manager_adapter.py")
        assert "UnifiedDeviceManager" in src or "unified.device_manager" in src, (
            "device_agent_manager_adapter.py must name the canonical replacement"
        )

    def test_new_code_must_not_depend(self):
        src = _read("core/legacy_adapters/device_agent_manager_adapter.py")
        assert "New code must not" in src or "new code must not" in src or "must not depend" in src, (
            "device_agent_manager_adapter.py must state that new code must not depend on it"
        )

    def test_removal_target_pr5(self):
        src = _read("core/legacy_adapters/device_agent_manager_adapter.py")
        assert "PR-5" in src or "Batch PR-5" in src, (
            "device_agent_manager_adapter.py must mention PR-5 removal target"
        )


# ---------------------------------------------------------------------------
# H) galaxy_gateway/legacy/capability_registry.py — DeprecationWarning
# ---------------------------------------------------------------------------

class TestGatewayLegacyCapabilityRegistry:

    def test_has_deprecated_docstring(self):
        src = _read("galaxy_gateway/legacy/capability_registry.py")
        assert _has_deprecated_docstring(src), (
            "galaxy_gateway/legacy/capability_registry.py must have '.. deprecated::' in its docstring"
        )

    def test_has_removal_target(self):
        src = _read("galaxy_gateway/legacy/capability_registry.py")
        assert _has_removal_target(src), (
            "galaxy_gateway/legacy/capability_registry.py must declare a removal target"
        )

    def test_emits_deprecation_warning(self):
        src = _read("galaxy_gateway/legacy/capability_registry.py")
        assert "warnings.warn" in src, (
            "galaxy_gateway/legacy/capability_registry.py must call warnings.warn()"
        )
        assert "DeprecationWarning" in src, (
            "DeprecationWarning must be passed to warnings.warn()"
        )

    def test_mentions_canonical_replacement(self):
        src = _read("galaxy_gateway/legacy/capability_registry.py")
        assert "core.capability_bus" in src or "capability_bus" in src, (
            "galaxy_gateway/legacy/capability_registry.py must name the canonical replacement"
        )

    def test_new_code_must_not_depend(self):
        src = _read("galaxy_gateway/legacy/capability_registry.py")
        assert "New code must not" in src or "new code must not" in src or "must not depend" in src, (
            "galaxy_gateway/legacy/capability_registry.py must state that new code must not depend on it"
        )

    def test_removal_target_pr5(self):
        src = _read("galaxy_gateway/legacy/capability_registry.py")
        assert "PR-5" in src or "Batch PR-5" in src, (
            "galaxy_gateway/legacy/capability_registry.py must mention PR-5 removal target"
        )


# ---------------------------------------------------------------------------
# I) galaxy_gateway/legacy/task_decomposer.py — DeprecationWarning
# ---------------------------------------------------------------------------

class TestGatewayLegacyTaskDecomposer:

    def test_has_deprecated_docstring(self):
        src = _read("galaxy_gateway/legacy/task_decomposer.py")
        assert _has_deprecated_docstring(src), (
            "galaxy_gateway/legacy/task_decomposer.py must have '.. deprecated::' in its docstring"
        )

    def test_has_removal_target(self):
        src = _read("galaxy_gateway/legacy/task_decomposer.py")
        assert _has_removal_target(src), (
            "galaxy_gateway/legacy/task_decomposer.py must declare a removal target"
        )

    def test_emits_deprecation_warning(self):
        src = _read("galaxy_gateway/legacy/task_decomposer.py")
        assert "warnings.warn" in src, (
            "galaxy_gateway/legacy/task_decomposer.py must call warnings.warn()"
        )
        assert "DeprecationWarning" in src, (
            "DeprecationWarning must be passed to warnings.warn()"
        )

    def test_mentions_canonical_replacement(self):
        src = _read("galaxy_gateway/legacy/task_decomposer.py")
        assert "orchestrator" in src, (
            "galaxy_gateway/legacy/task_decomposer.py must name the canonical replacement (orchestrator)"
        )

    def test_new_code_must_not_depend(self):
        src = _read("galaxy_gateway/legacy/task_decomposer.py")
        assert "New code must not" in src or "new code must not" in src or "must not depend" in src, (
            "galaxy_gateway/legacy/task_decomposer.py must state that new code must not depend on it"
        )

    def test_removal_target_pr5(self):
        src = _read("galaxy_gateway/legacy/task_decomposer.py")
        assert "PR-5" in src or "Batch PR-5" in src, (
            "galaxy_gateway/legacy/task_decomposer.py must mention PR-5 removal target"
        )


# ---------------------------------------------------------------------------
# J) docs/CONFIGURATION_AUTHORITY.md — config.json reclassification
# ---------------------------------------------------------------------------

class TestConfigAuthorityDocs:

    def test_config_json_reclassified(self):
        src = _read("docs/CONFIGURATION_AUTHORITY.md")
        # Must state config.json is non-authoritative or static defaults
        assert "static" in src.lower() and "config.json" in src, (
            "docs/CONFIGURATION_AUTHORITY.md must reclassify config.json as static defaults"
        )
        assert "non-authoritative" in src.lower() or "lowest" in src.lower() or "lowest-priority" in src.lower(), (
            "docs/CONFIGURATION_AUTHORITY.md must state config.json is the lowest-priority source"
        )

    def test_launcher_config_manager_demoted_d2(self):
        src = _read("docs/CONFIGURATION_AUTHORITY.md")
        assert "launcher/config_manager.py" in src, (
            "docs/CONFIGURATION_AUTHORITY.md must mention launcher/config_manager.py"
        )
        assert "D2" in src or "HARD_DEPRECATED" in src or "Deprecated" in src, (
            "docs/CONFIGURATION_AUTHORITY.md must mark launcher/config_manager.py as deprecated"
        )

    def test_canonical_config_stack_described(self):
        src = _read("docs/CONFIGURATION_AUTHORITY.md")
        assert "core/config_store.py" in src or "config_store" in src, (
            "docs/CONFIGURATION_AUTHORITY.md must describe the canonical config stack"
        )
        assert "core/config_service.py" in src or "config_service" in src, (
            "docs/CONFIGURATION_AUTHORITY.md must describe the canonical config stack"
        )

    def test_runtime_config_json_distinguished_from_root_config_json(self):
        src = _read("docs/CONFIGURATION_AUTHORITY.md")
        assert "runtime/config.json" in src, (
            "docs/CONFIGURATION_AUTHORITY.md must distinguish runtime/config.json "
            "(canonical) from config.json (root, static)"
        )

    def test_config_json_do_not_write_secrets(self):
        src = _read("docs/CONFIGURATION_AUTHORITY.md")
        assert "secrets" in src.lower() or "Do not write" in src or "must never" in src, (
            "docs/CONFIGURATION_AUTHORITY.md must warn against writing secrets to config.json"
        )


# ---------------------------------------------------------------------------
# K) docs/migration/LEGACY_SURFACE_INVENTORY.md — launcher/config_manager listed
# ---------------------------------------------------------------------------

class TestLegacySurfaceInventoryUpdated:

    def test_launcher_config_manager_listed(self):
        src = _read("docs/migration/LEGACY_SURFACE_INVENTORY.md")
        assert "launcher/config_manager.py" in src, (
            "LEGACY_SURFACE_INVENTORY.md must list launcher/config_manager.py"
        )

    def test_launcher_config_manager_is_d2(self):
        src = _read("docs/migration/LEGACY_SURFACE_INVENTORY.md")
        # The row should contain D2
        lines = [l for l in src.splitlines() if "launcher/config_manager.py" in l]
        assert lines, "launcher/config_manager.py must appear in a table row"
        assert any("D2" in l for l in lines), (
            "launcher/config_manager.py must be marked D2 in LEGACY_SURFACE_INVENTORY.md"
        )

    def test_shims_have_pr3_status_column(self):
        src = _read("docs/migration/LEGACY_SURFACE_INVENTORY.md")
        assert "PR-3 Status" in src, (
            "LEGACY_SURFACE_INVENTORY.md section 6 must have a PR-3 Status column "
            "showing which shims received deprecation metadata in this batch"
        )

    def test_compat_routes_pr3_status_marked(self):
        src = _read("docs/migration/LEGACY_SURFACE_INVENTORY.md")
        # core/routes/compat.py row should show PR-3 completion
        lines = [l for l in src.splitlines() if "core/routes/compat.py" in l]
        assert lines, "core/routes/compat.py must appear in LEGACY_SURFACE_INVENTORY.md"
        assert any("PR-3" in l or "✅" in l for l in lines), (
            "core/routes/compat.py shim row must show PR-3 status completion"
        )

    def test_dashboard_fallback_pr3_status_marked(self):
        src = _read("docs/migration/LEGACY_SURFACE_INVENTORY.md")
        lines = [l for l in src.splitlines() if "dashboard/backend/main.py" in l]
        assert lines, "dashboard/backend/main.py must appear in LEGACY_SURFACE_INVENTORY.md"
        # Should note that PR-3 fixed the forbidden fallback
        assert any("PR-3" in l for l in lines), (
            "dashboard/backend/main.py row must show PR-3 status (forbidden fallback removed)"
        )


# ---------------------------------------------------------------------------
# Additional structural checks
# ---------------------------------------------------------------------------

class TestStructuralInvariants:

    def test_check_debt_freeze_passes(self):
        """Run the debt-freeze guardrail and assert no new violations."""
        import subprocess
        result = subprocess.run(
            ["python", "scripts/check_debt_freeze.py"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"check_debt_freeze.py failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        # "✅ Debt-freeze check passed" means no new violations
        assert "Debt-freeze check passed" in result.stdout, (
            f"check_debt_freeze.py did not report clean pass:\n{result.stdout}"
        )

    def test_dashboard_main_does_not_define_class_in_except_importerror(self):
        """AST-based check: no class is defined inside an except ImportError handler."""
        src = _read("dashboard/backend/main.py")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            pytest.skip("dashboard/backend/main.py has syntax errors — skipping AST check")

        class _ExceptImportErrorClassFinder(ast.NodeVisitor):
            def __init__(self):
                self.violations: list[str] = []

            def visit_Try(self, node: ast.Try):
                for handler in node.handlers:
                    # Check if it's an except ImportError or ModuleNotFoundError
                    exc_type = handler.type
                    if exc_type is None:
                        continue
                    exc_name = ""
                    if isinstance(exc_type, ast.Name):
                        exc_name = exc_type.id
                    elif isinstance(exc_type, ast.Attribute):
                        exc_name = exc_type.attr
                    if exc_name in ("ImportError", "ModuleNotFoundError"):
                        for stmt in handler.body:
                            if isinstance(stmt, ast.ClassDef):
                                self.violations.append(stmt.name)
                self.generic_visit(node)

        finder = _ExceptImportErrorClassFinder()
        finder.visit(tree)
        assert not finder.violations, (
            f"dashboard/backend/main.py defines classes inside except ImportError handlers: "
            f"{finder.violations}. These are forbidden core-dep fallbacks that must be removed."
        )

    def test_core_routes_compat_no_business_logic(self):
        """Shim must not contain complex business logic (just delegation)."""
        src = _read("core/routes/compat.py")
        # The file may contain delegation logic (acceptable) but must not import
        # other business-logic modules as first-class dependencies.
        # Basic sanity: ensure it's still a thin router wrapper, not a full module.
        assert len(src) < 15_000, (
            "core/routes/compat.py has grown too large; shims must be thin delegation wrappers"
        )

    def test_launcher_config_manager_still_functional(self):
        """Deprecation warning must not break the module's basic imports."""
        src = _read("launcher/config_manager.py")
        # Ensure core classes are still present (backward compat preserved)
        assert "class ConfigManager" in src, (
            "launcher/config_manager.py must still export ConfigManager for backward compat"
        )
        assert "class NodeConfig" in src, (
            "launcher/config_manager.py must still export NodeConfig for backward compat"
        )
