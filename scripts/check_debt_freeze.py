#!/usr/bin/env python3
"""
check_debt_freeze.py — Architecture debt-freeze guardrail (Batch PR-1).

Detects patterns that represent new technical debt being added to the
codebase.  Runs as a CI check on every pull request.

Checks performed:
  1. New root-level placeholder Markdown report files (< ROOT_MD_SIZE_LIMIT bytes)
  2. New compatibility shims outside approved legacy zones
  3. New forbidden ``except ImportError: <fallback definition>`` patterns in
     non-approved files
  4. (Informational) YAML files larger than YAML_SIZE_LIMIT bytes

All checks run in WARNING mode by default.  Pass --strict to exit 1 when
any violation is found.

Usage:
    python scripts/check_debt_freeze.py             # warning mode (CI reports)
    python scripts/check_debt_freeze.py --strict    # strict mode (CI fail)
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Root-level Markdown size threshold — files at repo root smaller than this
# are considered placeholder stubs.
ROOT_MD_SIZE_LIMIT = 300  # bytes

# Already-known root placeholder files (grandfathered; not flagged as NEW)
KNOWN_ROOT_PLACEHOLDERS = {
    "SQL_FIXES.md",
    "UI_ASSETS.md",
    "EVAL_FIXES.md",
    "SECURITY_FIXES.md",
    "FULL_SYSTEM_AUDIT.md",
    "ARCHITECTURE_REVIEW.md",
    "IMPLEMENTATION_SUMMARY.md",
    "L4_SYSTEM_STATUS_REPORT.md",
    "SYSTEM_INTEGRITY_REPORT.md",
    "README_UI_L4_INTEGRATION.md",
    "UI_L4_INTEGRATION_REPORT.md",
    "R4_IMPLEMENTATION_SUMMARY.md",
    "SYSTEM_DESIGN_INTEGRATION_SUMMARY.md",
}

# Approved zones where compatibility shims are allowed
APPROVED_SHIM_ZONES = {
    "core/legacy",
    "core/legacy_adapters",
    "galaxy_gateway/legacy",
    "windows_client/_legacy",
}

# Known shim files outside approved zones (grandfathered; not flagged as NEW)
KNOWN_SHIM_FILES = {
    "galaxy_main_loop_l4.py",                             # root tombstone
    "galaxy_gateway/aip_protocol_v2.py",                  # hard-raise guard
    "core/routes/compat.py",                              # route compat layer
    "core/orchestration_authority/legacy_paths.py",       # legacy orchestration registry
    "core/capability_orchestrator.py",                    # deprecation wrapper
    "core/production_baseline.py",                        # baseline compat
    "core/command_router.py",                             # has compat shim section
    "galaxy_gateway/routes/devices.py",                   # device compat shim note
    "galaxy_gateway/protocol/compat.py",                  # AIP v2→v3 compat
    # Additional known pre-existing shims/facades (grandfathered — Batch PR-5)
    "core/legacy_purge_registry.py",                      # read-only purge catalogue
    "core/architecture_status_report.py",                 # arch shim → tools/architecture/
    "core/architecture_completion.py",                    # arch shim → tools/architecture/
    "core/architecture_invariants.py",                    # arch shim → tools/architecture/
    "core/architecture_live_status.py",                   # arch shim → tools/architecture/
    "core/architecture_diagnostics.py",                   # arch shim → tools/architecture/
    "core/architecture_truth_guards.py",                  # arch shim → tools/architecture/
    "core/scenario_harness.py",                           # arch shim → tools/architecture/
    "core/unified/config_manager.py",                     # compatibility facade
    "galaxy_gateway/task_decomposer.py",                  # legacy; copy in galaxy_gateway/legacy/
    "galaxy_gateway/capability_registry.py",              # legacy; copy in galaxy_gateway/legacy/
    "galaxy_gateway/task_router.py",                      # legacy; → galaxy_gateway/routing/
    "galaxy_gateway/handlers/message_handler.py",         # legacy chain-B dispatcher
    # PR-3 convergence — shims identified during session/continuity/authority unification
    "core/runtime_closure_audit.py",                      # PR-3 runtime closure audit shim
    "core/legacy_system_decommission.py",                 # PR-3 legacy system decommission shim
    "core/llm/execution_authority.py",                    # PR-3 LLM execution authority compat
    "core/schemas/ugcp/shared.py",                        # PR-3 UGCP shared schema compat
    "galaxy_gateway/session_roaming.py",                  # PR-3 session roaming compat
    "galaxy_gateway/enhanced_nlu_v2.py",                  # PR-3 enhanced NLU v2 compat
    "galaxy_gateway/smart_transport_router.py",           # PR-3 smart transport router compat
}

# Approved files that may contain `except ImportError` fallback definitions
# (files where the body of the except block defines classes or functions)
APPROVED_IMPORT_FALLBACK_FILES = {
    "unified_launcher.py",
    "core/openclawd.py",
    "core/scheduler.py",
    "core/openclawd_heartbeat.py",
    "core/nodes/node_fabric_registry.py",
    "core/academic_retrieval.py",
    "core/mcp_gateway.py",
    "core/routes/protocols.py",
    "core/routes/ai.py",
    "core/routes/devices.py",
    "core/routes/vision.py",
    "core/routes/command.py",
    "core/openclawd_memory_backflow.py",
    "core/monitoring.py",
    "dashboard/backend/main.py",
    "integration/event_bus.py",
    # Existing files with ImportError fallbacks (grandfathered — Batch PR-5)
    "core/self_improvement.py",
    "core/api_routes.py",
    "core/task_lifecycle.py",
    "core/temporal_workflows.py",
    "galaxy_gateway/agent_bridge.py",
    "galaxy_gateway/routes/sessions.py",
    "galaxy_gateway/routes/tasks.py",
    "galaxy_gateway/routes/llm.py",
    "galaxy_gateway/routes/chat.py",
    # PR-3 convergence — unified_governance_semantics has a guarded optional dependency
    "core/unified_governance_semantics.py",               # PR-3: guarded optional dependency
}

# YAML size limit (bytes) — informational warning only
YAML_SIZE_LIMIT = 50_000  # 50 KB

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.resolve()


def _rel(path: Path) -> str:
    """Return path relative to REPO_ROOT."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _is_in_approved_shim_zone(rel_path: str) -> bool:
    return any(rel_path.startswith(zone + "/") or rel_path.startswith(zone + "\\")
               for zone in APPROVED_SHIM_ZONES)


def _has_shim_indicators(content: str) -> bool:
    """
    Return True if the file is clearly a compatibility shim / tombstone.

    We require explicit tombstone/shim language, NOT just a ``.. deprecated::``
    docstring (which is present in many active modules that contain deprecated
    *sections* but are not themselves shims).
    """
    # Patterns that strongly indicate the *entire file* is a shim/tombstone
    strong_indicators = [
        r"compat(?:ibility)? shim",
        r"re-export tombstone",
        r"retired root module",
        r"legacy compat(?:ibility)? (?:adapter|wrapper|module)",
        r"this (?:file|module) is a (?:compat|compatibility|tombstone|shim)",
        r"backward.compat(?:ibility)? wrapper",
    ]
    lower = content.lower()
    for pat in strong_indicators:
        if re.search(pat, lower):
            return True
    return False


def _has_inline_fallback_definition(source: str) -> bool:
    """
    Return True if the source contains an ``except ImportError`` block that
    defines a class or function inside the except body — the anti-pattern
    we want to prevent.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Try,)):
            continue
        # Look at each handler
        handlers = getattr(node, "handlers", [])
        for handler in handlers:
            exc_type = handler.type
            if exc_type is None:
                continue
            # Check if the handler type is ImportError or ModuleNotFoundError
            name = None
            if isinstance(exc_type, ast.Name):
                name = exc_type.id
            elif isinstance(exc_type, ast.Attribute):
                name = exc_type.attr
            if name not in ("ImportError", "ModuleNotFoundError"):
                continue
            # Check if the handler body contains class/function definitions
            for stmt in handler.body:
                if isinstance(stmt, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    return True
    return False


# ---------------------------------------------------------------------------
# Check 1 — New root-level placeholder Markdown files
# ---------------------------------------------------------------------------

def check_root_md_placeholders() -> list[str]:
    violations: list[str] = []
    for md_file in REPO_ROOT.glob("*.md"):
        size = md_file.stat().st_size
        if size < ROOT_MD_SIZE_LIMIT and md_file.name not in KNOWN_ROOT_PLACEHOLDERS:
            violations.append(
                f"  NEW root placeholder MD: {md_file.name} ({size} bytes) — "
                f"move content to docs/reports/ instead"
            )
    return violations


# ---------------------------------------------------------------------------
# Check 2 — New compat shims outside approved zones
# ---------------------------------------------------------------------------

def check_compat_shims_outside_approved_zones() -> list[str]:
    violations: list[str] = []
    scan_dirs = ["core", "galaxy_gateway", "enhancements", "windows_client"]
    for scan_dir in scan_dirs:
        base = REPO_ROOT / scan_dir
        if not base.exists():
            continue
        for py_file in base.rglob("*.py"):
            rel = _rel(py_file)
            if _is_in_approved_shim_zone(rel):
                continue
            if rel in KNOWN_SHIM_FILES:
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _has_shim_indicators(content):
                violations.append(
                    f"  NEW compat shim outside approved zone: {rel} — "
                    f"move to core/legacy/, core/legacy_adapters/, "
                    f"galaxy_gateway/legacy/, or windows_client/_legacy/"
                )
    return violations


# ---------------------------------------------------------------------------
# Check 3 — New forbidden except ImportError fallback definitions
# ---------------------------------------------------------------------------

def check_import_error_fallbacks() -> list[str]:
    violations: list[str] = []
    scan_dirs = ["core", "galaxy_gateway", "launcher", "integration", "dashboard"]
    for scan_dir in scan_dirs:
        base = REPO_ROOT / scan_dir
        if not base.exists():
            continue
        for py_file in base.rglob("*.py"):
            rel = _rel(py_file)
            if rel in APPROVED_IMPORT_FALLBACK_FILES:
                continue
            try:
                source = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "except ImportError" not in source and "except ModuleNotFoundError" not in source:
                continue
            if _has_inline_fallback_definition(source):
                violations.append(
                    f"  NEW inline ImportError fallback definition: {rel} — "
                    f"use explicit optional-dependency flags instead "
                    f"(see docs/migration/DEPRECATION_POLICY.md §4)"
                )
    return violations


# ---------------------------------------------------------------------------
# Check 4 — Oversized YAML files (informational)
# ---------------------------------------------------------------------------

def check_yaml_size() -> list[str]:
    warnings: list[str] = []
    for yaml_file in REPO_ROOT.rglob("*.yml"):
        if ".git" in yaml_file.parts:
            continue
        size = yaml_file.stat().st_size
        if size > YAML_SIZE_LIMIT:
            warnings.append(
                f"  LARGE YAML file: {_rel(yaml_file)} ({size // 1024} KB) — "
                f"consider decomposing (threshold: {YAML_SIZE_LIMIT // 1024} KB)"
            )
    for yaml_file in REPO_ROOT.rglob("*.yaml"):
        if ".git" in yaml_file.parts:
            continue
        size = yaml_file.stat().st_size
        if size > YAML_SIZE_LIMIT:
            warnings.append(
                f"  LARGE YAML file: {_rel(yaml_file)} ({size // 1024} KB) — "
                f"consider decomposing (threshold: {YAML_SIZE_LIMIT // 1024} KB)"
            )
    return warnings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    strict = "--strict" in sys.argv

    all_violations: list[str] = []
    all_warnings: list[str] = []

    # --- Check 1
    v1 = check_root_md_placeholders()
    if v1:
        all_violations.extend(["[CHECK-1] New root-level placeholder Markdown files:"] + v1)

    # --- Check 2
    v2 = check_compat_shims_outside_approved_zones()
    if v2:
        all_violations.extend(["[CHECK-2] Compatibility shims outside approved zones:"] + v2)

    # --- Check 3
    v3 = check_import_error_fallbacks()
    if v3:
        all_violations.extend(["[CHECK-3] Inline ImportError fallback definitions:"] + v3)

    # --- Check 4 (informational only — never fails)
    w4 = check_yaml_size()
    if w4:
        all_warnings.extend(["[CHECK-4] Oversized YAML files (informational):"] + w4)

    # --- Report
    if all_warnings:
        print("⚠️  Debt-freeze warnings (informational):")
        for line in all_warnings:
            print(line)
        print()

    if all_violations:
        label = "❌" if strict else "⚠️"
        print(f"{label} Debt-freeze violations detected:")
        for line in all_violations:
            print(line)
        print()
        if strict:
            print("Run in strict mode — failing CI.")
            return 1
        else:
            print("Run in warning mode — not failing CI.")
            print("These violations should be resolved before switching to --strict.")
            return 0

    print("✅ Debt-freeze check passed — no new violations found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
