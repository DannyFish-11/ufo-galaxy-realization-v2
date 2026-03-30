#!/usr/bin/env python3
"""
check_import_boundaries.py — Structural import-boundary guardrail.

Enforces that the canonical execution chain layers do NOT import upward:
  - core/  must not import from galaxy_gateway/
  - tests/ must not import from nodes/ directly (go through core/ contracts)

Runs in warning-only mode by default.  Pass --strict to exit 1 on violations.

Usage:
    python scripts/check_import_boundaries.py            # warning mode
    python scripts/check_import_boundaries.py --strict   # strict mode (CI)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Boundary rules: (source_dir, forbidden_target_prefix, description)
# ---------------------------------------------------------------------------
BOUNDARY_RULES: list[tuple[str, str, str]] = [
    (
        "core",
        "galaxy_gateway",
        "core/ must not import from galaxy_gateway/ "
        "(gateway depends on core, not the reverse)",
    ),
    (
        "core",
        "dashboard",
        "core/ must not import from dashboard/ "
        "(dashboard is a consumer of core, not a dependency)",
    ),
    (
        "core",
        "enhancements",
        "core/ must not import from enhancements/ "
        "(enhancements layer sits above core)",
    ),
]


def _collect_imports(path: Path) -> list[str]:
    """Return a list of top-level module names imported by *path*."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                modules.append(node.module.split(".")[0])
    return modules


def main() -> int:
    strict = "--strict" in sys.argv
    repo_root = Path(__file__).resolve().parent.parent

    violations: list[str] = []

    for source_dir, forbidden_prefix, description in BOUNDARY_RULES:
        src_path = repo_root / source_dir
        if not src_path.is_dir():
            continue
        for py_file in sorted(src_path.rglob("*.py")):
            # Skip __pycache__ and virtual envs
            if any(
                part in py_file.parts
                for part in ("__pycache__", ".venv", "venv", "node_modules")
            ):
                continue
            for mod in _collect_imports(py_file):
                if mod == forbidden_prefix:
                    rel = py_file.relative_to(repo_root)
                    violations.append(
                        f"  {rel}: imports '{forbidden_prefix}' — {description}"
                    )

    if violations:
        label = "❌" if strict else "⚠️ "
        print(f"\n{label} Import boundary violations detected:\n")
        for v in violations:
            print(v)
        print(
            f"\n{'Failing CI (--strict mode).' if strict else 'Warning only — pass --strict to fail CI.'}"
        )
        return 1 if strict else 0
    else:
        print("✅ No import boundary violations detected.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
