#!/usr/bin/env python3
"""Repository hygiene checker.

Scans the repository (with stricter rules under ``nodes/``) for forbidden
runtime/generated/temp artifacts that must never be committed.

Usage::

    python scripts/check_repo_hygiene.py            # scan whole repo
    python scripts/check_repo_hygiene.py nodes/     # scan a subtree only

Exit codes:
    0 — no violations found
    1 — one or more violations found
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Violation categories and forbidden-pattern definitions
# ---------------------------------------------------------------------------

CATEGORY_PID = "pid_file"
CATEGORY_LOG = "log_file"
CATEGORY_CACHE = "cache_dir"
CATEGORY_RUNTIME_DB = "runtime_db"
CATEGORY_TEMP = "temp_file"
CATEGORY_COMPILED = "compiled_artifact"
CATEGORY_BUILD = "build_artifact"


@dataclass(frozen=True)
class ForbiddenPattern:
    """A single forbidden-artifact rule."""

    pattern: str
    category: str
    reason: str
    match_type: str = "name"  # "name" | "path_part"
    nodes_only: bool = False  # True → only enforced under nodes/


# Patterns enforced everywhere in the repository
_GLOBAL_PATTERNS: List[ForbiddenPattern] = [
    # PID files
    ForbiddenPattern("*.pid", CATEGORY_PID, "PID files are runtime artifacts that must not be committed"),
    # Compiled Python
    ForbiddenPattern("*.pyc", CATEGORY_COMPILED, "Compiled Python bytecode must not be committed"),
    ForbiddenPattern("*.pyo", CATEGORY_COMPILED, "Compiled Python bytecode must not be committed"),
    ForbiddenPattern("*.pyd", CATEGORY_COMPILED, "Compiled Python extension must not be committed"),
    # Temp / scratch files
    ForbiddenPattern("*.tmp", CATEGORY_TEMP, "Temporary files must not be committed"),
    ForbiddenPattern("*.temp", CATEGORY_TEMP, "Temporary files must not be committed"),
    ForbiddenPattern("*.bak", CATEGORY_TEMP, "Backup files must not be committed"),
    ForbiddenPattern("*.swp", CATEGORY_TEMP, "Vim swap files must not be committed"),
    ForbiddenPattern("*.swo", CATEGORY_TEMP, "Vim swap files must not be committed"),
    # Cache directories (match_type="path_part" checks any directory segment)
    ForbiddenPattern("__pycache__", CATEGORY_CACHE, "Python cache directories must not be committed", match_type="path_part"),
    ForbiddenPattern(".pytest_cache", CATEGORY_CACHE, "pytest cache directories must not be committed", match_type="path_part"),
    ForbiddenPattern(".mypy_cache", CATEGORY_CACHE, "mypy cache directories must not be committed", match_type="path_part"),
    ForbiddenPattern(".ruff_cache", CATEGORY_CACHE, "ruff cache directories must not be committed", match_type="path_part"),
    ForbiddenPattern("node_modules", CATEGORY_BUILD, "npm node_modules must not be committed", match_type="path_part"),
    ForbiddenPattern(".cache", CATEGORY_CACHE, "Generic cache directories must not be committed", match_type="path_part"),
]

# Stricter patterns enforced only inside nodes/
_NODES_ONLY_PATTERNS: List[ForbiddenPattern] = [
    # Log files — only forbidden inside nodes/; root-level logs/ already in .gitignore
    ForbiddenPattern("*.log", CATEGORY_LOG, "Log files are runtime artifacts that must not be committed inside node directories", nodes_only=True),
    # Databases — SQLite/runtime state files
    ForbiddenPattern("*.db", CATEGORY_RUNTIME_DB, "Runtime database files must not be committed inside node directories", nodes_only=True),
    ForbiddenPattern("*.sqlite", CATEGORY_RUNTIME_DB, "Runtime database files must not be committed inside node directories", nodes_only=True),
    ForbiddenPattern("*.sqlite3", CATEGORY_RUNTIME_DB, "Runtime database files must not be committed inside node directories", nodes_only=True),
]

ALL_PATTERNS: List[ForbiddenPattern] = _GLOBAL_PATTERNS + _NODES_ONLY_PATTERNS

# ---------------------------------------------------------------------------
# Allowlist: paths (relative to repo root) explicitly permitted to exist even
# when they match a forbidden pattern.  Add entries here rather than
# weakening the global rules.
# ---------------------------------------------------------------------------

ALLOWLIST: List[str] = [
    # Example: "nodes/Node_XX_Foo/fixtures/example.db"
]

# ---------------------------------------------------------------------------
# Directories to skip entirely during scanning
# ---------------------------------------------------------------------------

SKIP_DIRS: List[str] = [
    ".git",
    ".venv",
    "venv",
    "ENV",
    "env",
]


# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------


@dataclass
class Violation:
    rel_path: str
    category: str
    reason: str


@dataclass
class HygieneReport:
    violations: List[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.violations) == 0

    def add(self, rel_path: str, category: str, reason: str) -> None:
        self.violations.append(Violation(rel_path=rel_path, category=category, reason=reason))

    def print_summary(self) -> None:
        if self.ok:
            print("✅  Repository hygiene check passed — no violations found.")
            return
        print(f"❌  Repository hygiene check FAILED — {len(self.violations)} violation(s) found:\n")
        by_category: dict[str, List[Violation]] = {}
        for v in self.violations:
            by_category.setdefault(v.category, []).append(v)
        for cat, items in sorted(by_category.items()):
            print(f"  [{cat}]")
            for item in items:
                print(f"    {item.rel_path}")
                print(f"      reason: {item.reason}")
        print()


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def _is_allowlisted(rel_path: str) -> bool:
    for allowed in ALLOWLIST:
        if rel_path == allowed or rel_path.startswith(allowed.rstrip("/") + "/"):
            return True
    return False


def _path_parts(rel_path: str) -> List[str]:
    """Return all path segments for a relative path string."""
    return Path(rel_path).parts


def _is_inside_nodes(rel_path: str) -> bool:
    parts = _path_parts(rel_path)
    return len(parts) > 0 and parts[0] == "nodes"


def scan_repository(root: str, subtree: Optional[str] = None) -> HygieneReport:
    """Walk *root* (optionally restricted to *subtree*) and collect violations.

    Parameters
    ----------
    root:
        Absolute path to the repository root.
    subtree:
        If given, only paths rooted under this directory (relative to *root*)
        are scanned.
    """
    report = HygieneReport()
    root_path = Path(root).resolve()
    start_path = (root_path / subtree).resolve() if subtree else root_path

    for dirpath, dirnames, filenames in os.walk(start_path):
        # Prune skipped directories in-place so os.walk does not recurse into them
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        current_dir = Path(dirpath)
        rel_dir = current_dir.relative_to(root_path)

        # --- Check directory names themselves ---
        for dirname in list(dirnames):
            rel_item = str(rel_dir / dirname) if str(rel_dir) != "." else dirname
            if _is_allowlisted(rel_item):
                continue
            inside_nodes = _is_inside_nodes(rel_item)
            for pat in ALL_PATTERNS:
                if pat.nodes_only and not inside_nodes:
                    continue
                if pat.match_type == "path_part" and fnmatch.fnmatch(dirname, pat.pattern):
                    report.add(rel_item, pat.category, pat.reason)
                    # Don't recurse into forbidden cache/build dirs
                    if dirname in dirnames:
                        dirnames.remove(dirname)
                    break

        # --- Check files ---
        for filename in filenames:
            rel_item = str(rel_dir / filename) if str(rel_dir) != "." else filename
            if _is_allowlisted(rel_item):
                continue
            inside_nodes = _is_inside_nodes(rel_item)
            for pat in ALL_PATTERNS:
                if pat.nodes_only and not inside_nodes:
                    continue
                if pat.match_type == "name" and fnmatch.fnmatch(filename, pat.pattern):
                    report.add(rel_item, pat.category, pat.reason)
                    break  # one violation per file is enough

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check the repository for forbidden runtime/generated artifacts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "subtree",
        nargs="?",
        default=None,
        help="Optional subtree to restrict the scan to (relative to repo root).",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root directory (defaults to the directory containing this script's parent).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output violations as JSON instead of human-readable text.",
    )
    return parser


def _find_repo_root(script_path: str) -> str:
    """Heuristically find the repo root from the script location."""
    # This script lives at <repo_root>/scripts/check_repo_hygiene.py
    return str(Path(script_path).resolve().parent.parent)


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    repo_root = args.root or _find_repo_root(__file__)
    report = scan_repository(repo_root, subtree=args.subtree)

    if args.json:
        import json
        data = {
            "ok": report.ok,
            "violation_count": len(report.violations),
            "violations": [
                {"path": v.rel_path, "category": v.category, "reason": v.reason}
                for v in report.violations
            ],
        }
        print(json.dumps(data, indent=2))
    else:
        report.print_summary()

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
