#!/usr/bin/env python3
"""scripts/check_legacy_regression.py
======================================

Non-regression guard for PR-8: Remove retired legacy surfaces.

Checks that:

1. Fully-deleted files (PR-8) have not been reintroduced anywhere in the
   repository.
2. No new ``.bat`` launcher files have appeared inside ``windows_client/``
   outside the approved archive zone (``windows_client/_legacy/``).
3. ``windows_client/_legacy/`` does NOT contain any new non-``__init__.py``
   Python source files (only archive/documentation items are allowed there).

Exit codes
----------
0  — all checks pass
1  — one or more violations found (printed to stdout)

Usage
-----
    python scripts/check_legacy_regression.py [--warn-only]

With ``--warn-only`` the script always exits 0 but still prints violations.
This matches the ``warning mode`` convention used by other guardrail scripts.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
from typing import List

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Files that were physically deleted in PR-8 and must never reappear.
# Paths are relative to the repository root.
_PR8_DELETED_FILES: tuple[str, ...] = (
    "windows_client/_legacy/START_CLIENT.bat",
    "windows_client/_legacy/start_galaxy_client.bat",
)

# Active root of the Windows client package.
_WINDOWS_CLIENT_ROOT = _REPO_ROOT / "windows_client"

# The only approved zone inside windows_client/ where legacy .bat files are
# allowed to sit during an intermediate archival phase.  In PR-8 that zone
# was cleared entirely; new .bat launchers must not appear here either.
_LEGACY_ARCHIVE_DIR = _WINDOWS_CLIENT_ROOT / "_legacy"


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------


def _check_deleted_files_absent() -> List[str]:
    """Return violation messages for any PR-8-deleted file that has reappeared."""
    violations: List[str] = []
    for rel in _PR8_DELETED_FILES:
        path = _REPO_ROOT / rel
        if path.exists():
            violations.append(
                f"[PR-8 REGRESSION] Deleted file reintroduced: {rel}\n"
                f"  This file was fully removed in PR-8 and must not be "
                f"reintroduced.\n"
                f"  See docs/LEGACY_SURFACES.md for the canonical replacement."
            )
    return violations


def _check_no_new_bat_launchers_in_windows_client() -> List[str]:
    """Return violation messages for new .bat files found in windows_client/.

    .bat files in the _legacy/ archive directory are also rejected because
    PR-8 completed the deletion of all legacy launchers from that zone.
    """
    violations: List[str] = []
    for bat in _WINDOWS_CLIENT_ROOT.rglob("*.bat"):
        rel = bat.relative_to(_REPO_ROOT)
        violations.append(
            f"[PR-8 REGRESSION] New .bat launcher detected: {rel}\n"
            f"  windows_client/ must not contain .bat launcher files.  "
            f"The last remaining legacy launchers were deleted in PR-8.\n"
            f"  Use python main.py instead "
            f"(or start.bat on Windows / python unified_launcher.py for direct subordinate invocation)."
        )
    return violations


def _check_no_new_py_sources_in_legacy_archive() -> List[str]:
    """Return violations for new Python source files added inside _legacy/.

    The _legacy/ archive package must only contain __init__.py and static
    archive artefacts under the ``ui/`` subdirectory (legacy chat UI code).
    Adding new .py source modules anywhere else in the archive zone indicates
    a shim is being buried there, which is not allowed.
    """
    violations: List[str] = []
    allowed_py = {"__init__.py"}
    for py in _LEGACY_ARCHIVE_DIR.rglob("*.py"):
        # Allow __init__.py at any level, and all files under the ui/ subtree
        # which holds the archived legacy chat UI.
        if py.name in allowed_py:
            continue
        try:
            py.relative_to(_LEGACY_ARCHIVE_DIR / "ui")
            continue  # inside the permitted ui/ archive subtree
        except ValueError:
            pass
        rel = py.relative_to(_REPO_ROOT)
        violations.append(
            f"[LEGACY ZONE VIOLATION] New Python source in _legacy/ archive: "
            f"{rel}\n"
            f"  windows_client/_legacy/ is a static archive zone.  "
            f"Do not add new Python source files here (outside ui/); use the "
            f"canonical module hierarchy instead."
        )
    return violations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Non-regression guard for PR-8 legacy cleanup."
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Print violations but always exit 0 (CI warning mode).",
    )
    args = parser.parse_args(argv)

    violations: List[str] = []
    violations.extend(_check_deleted_files_absent())
    violations.extend(_check_no_new_bat_launchers_in_windows_client())
    violations.extend(_check_no_new_py_sources_in_legacy_archive())

    if violations:
        print("=" * 70)
        print("check_legacy_regression: VIOLATIONS FOUND")
        print("=" * 70)
        for v in violations:
            print()
            print(v)
        print()
        print(f"Total violations: {len(violations)}")
        if args.warn_only:
            print("(warn-only mode — exiting 0)")
            return 0
        return 1

    print("check_legacy_regression: OK — no legacy regressions detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
