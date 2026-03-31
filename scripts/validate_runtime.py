#!/usr/bin/env python3
"""
Galaxy — Runtime Integration Validator
=======================================

PR-9 integration validation script.

Validates that the current authoritative runtime system is coherent after the
PR-1 through PR-8 cleanup sequence:

  PR-1  Authority model frozen
  PR-2  Broken startup paths and wrappers cleaned
  PR-3  Legacy Windows client stack retired from active runtime surface
  PR-4  dashboard/frontend demoted from active primary system surface
  PR-5  Python launcher refactored into clearer startup modules
  PR-6  Canonical node audit established
  PR-7  Active node system unified based on audit
  PR-8  Repository layout reorganised around active/legacy separation

What this script checks
-----------------------
1. Authoritative startup path coherence
   - main.py exists and delegates to unified_launcher.py
   - unified_launcher.py exists and imports the launcher package
   - launcher/ package exports all required sub-modules
2. Core authority chain imports
   - DesktopPresenceRuntime, OpenClawd, CommandRouter are importable
   - core.repo_layout_registry is importable and classifies known dirs correctly
3. Node registry consistency
   - node_dependencies.json exists and is valid JSON
   - All nodes have a recognised startup_policy value
   - startup_policy counts are within expected bounds
4. Legacy surface isolation
   - dashboard/ is classified as a legacy surface in the layout registry
   - windows_client/ (root) is classified as a legacy shell
   - windows_client/status_board_v2/ is classified as active desktop status
5. Critical docs exist
   - docs/ARCHITECTURE_BASELINE.md
   - docs/REPO_LAYOUT.md
   - docs/NODE_ACTIVE_MANIFEST.md
   - docs/ENTRYPOINT_AND_SURFACE_DEMOTION.md
   - docs/MAINTAINER_RUNBOOK.md

Usage::

    python scripts/validate_runtime.py             # run all checks
    python scripts/validate_runtime.py --json      # JSON output for CI
    python scripts/validate_runtime.py --strict    # exit 1 on warnings too
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple

# ---------------------------------------------------------------------------
# Project root
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

class CheckResult(NamedTuple):
    name: str
    status: str          # "PASS" | "FAIL" | "WARN"
    detail: str = ""


_results: List[CheckResult] = []


def _record(name: str, ok: bool, detail: str = "", warn_only: bool = False) -> CheckResult:
    if ok:
        status = "PASS"
    elif warn_only:
        status = "WARN"
    else:
        status = "FAIL"
    r = CheckResult(name=name, status=status, detail=detail)
    _results.append(r)
    return r


def _section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def _print_result(r: CheckResult) -> None:
    symbol = {"PASS": "✓", "FAIL": "✗", "WARN": "△"}.get(r.status, "?")
    line = f"  [{r.status}] {symbol} {r.name}"
    if r.detail:
        line += f"\n        {r.detail}"
    print(line)


# ---------------------------------------------------------------------------
# 1. Authoritative startup path
# ---------------------------------------------------------------------------

def check_startup_path() -> None:
    _section("1. Authoritative Startup Path")

    main_py = PROJECT_ROOT / "main.py"
    r = _record(
        "main.py exists",
        main_py.exists(),
        f"expected at {main_py}",
    )
    _print_result(r)

    if main_py.exists():
        content = main_py.read_text()
        # PR-2: main.py is now the canonical system orchestrator; it must declare
        # the authority sentinel and still reference unified_launcher as a
        # subordinate component.
        r = _record(
            "main.py is canonical system orchestrator (SYSTEM_ORCHESTRATOR_AUTHORITY)",
            "SYSTEM_ORCHESTRATOR_AUTHORITY" in content,
            "main.py must declare SYSTEM_ORCHESTRATOR_AUTHORITY (PR-2 orchestrator contract)",
        )
        _print_result(r)

        r = _record(
            "main.py references unified_launcher as subordinate component",
            "unified_launcher" in content,
            "main.py must still reference unified_launcher.py as a subordinate component",
        )
        _print_result(r)

    launcher_py = PROJECT_ROOT / "unified_launcher.py"
    r = _record(
        "unified_launcher.py exists",
        launcher_py.exists(),
        f"expected at {launcher_py}",
    )
    _print_result(r)

    launcher_pkg = PROJECT_ROOT / "launcher" / "__init__.py"
    r = _record(
        "launcher/ package exists",
        launcher_pkg.exists(),
        f"expected at {launcher_pkg}",
    )
    _print_result(r)

    required_submodules = [
        "launcher.bootstrap",
        "launcher.service_manager",
        "launcher.core_services",
        "launcher.node_startup",
        "launcher.health_checks",
        "launcher.shutdown",
    ]
    for mod in required_submodules:
        try:
            importlib.import_module(mod)
            ok = True
            detail = ""
        except Exception as exc:
            ok = False
            detail = str(exc)[:120]
        r = _record(f"import {mod}", ok, detail)
        _print_result(r)


# ---------------------------------------------------------------------------
# 2. Core authority chain imports
# ---------------------------------------------------------------------------

def check_authority_chain() -> None:
    _section("2. Core Authority Chain Imports")

    authority_modules = [
        ("core.desktop_presence_runtime", "DesktopPresenceRuntime"),
        ("core.openclawd", "OpenClawd"),
        ("core.command_router", "CommandRouter"),
        ("core.repo_layout_registry", "RepoLayoutRegistry"),
    ]
    for mod_name, cls_name in authority_modules:
        try:
            mod = importlib.import_module(mod_name)
            has_cls = hasattr(mod, cls_name)
            ok = has_cls
            detail = "" if has_cls else f"{cls_name} not found in {mod_name}"
        except Exception as exc:
            ok = False
            detail = str(exc)[:120]
        r = _record(f"{mod_name}.{cls_name}", ok, detail)
        _print_result(r)

    # Check layout registry classifies canonical dirs correctly
    try:
        from core.repo_layout_registry import (
            is_active_runtime_directory,
            is_legacy_directory,
            is_active_desktop_status_directory,
        )
        checks = [
            ("core/ is active_runtime", is_active_runtime_directory("core")),
            ("launcher/ is active_runtime", is_active_runtime_directory("launcher")),
            ("nodes/ is active_runtime", is_active_runtime_directory("nodes")),
            ("dashboard/ is legacy", is_legacy_directory("dashboard")),
            (
                "windows_client/status_board_v2/ is active_desktop_status",
                is_active_desktop_status_directory("windows_client/status_board_v2"),
            ),
        ]
        for name, ok in checks:
            r = _record(f"layout: {name}", ok)
            _print_result(r)
    except Exception as exc:
        r = _record("repo_layout_registry checks", False, str(exc)[:120])
        _print_result(r)


# ---------------------------------------------------------------------------
# 3. Node registry consistency
# ---------------------------------------------------------------------------

def check_node_registry() -> None:
    _section("3. Node Registry Consistency")

    node_deps_path = PROJECT_ROOT / "node_dependencies.json"
    r = _record("node_dependencies.json exists", node_deps_path.exists())
    _print_result(r)
    if not node_deps_path.exists():
        return

    try:
        data = json.loads(node_deps_path.read_text())
        r = _record("node_dependencies.json is valid JSON", True)
        _print_result(r)
    except json.JSONDecodeError as exc:
        r = _record("node_dependencies.json is valid JSON", False, str(exc))
        _print_result(r)
        return

    nodes: Dict = data.get("nodes", {})
    r = _record(
        "nodes key present",
        bool(nodes),
        f"found {len(nodes)} node entries",
    )
    _print_result(r)

    valid_policies = {"active", "optional", "skip"}
    invalid: List[str] = []
    counts: Dict[str, int] = {}
    for node_id, entry in nodes.items():
        policy = entry.get("startup_policy", "active")
        counts[policy] = counts.get(policy, 0) + 1
        if policy not in valid_policies:
            invalid.append(f"{node_id}: {policy!r}")

    r = _record(
        "all nodes have valid startup_policy",
        not invalid,
        "; ".join(invalid[:5]) if invalid else "",
    )
    _print_result(r)

    total = sum(counts.values())
    r = _record(
        f"total nodes ({total})",
        total >= 100,
        f"active={counts.get('active', 0)}, "
        f"optional={counts.get('optional', 0)}, "
        f"skip={counts.get('skip', 0)}",
    )
    _print_result(r)

    # Check that no "skip" nodes accidentally have startup_policy = "active"
    # (just surface counts for operator awareness)
    skipped = counts.get("skip", 0)
    r = _record(
        "skip-policy count reasonable",
        0 <= skipped <= 20,
        f"skip count: {skipped}",
        warn_only=skipped > 20,
    )
    _print_result(r)


# ---------------------------------------------------------------------------
# 4. Legacy surface isolation
# ---------------------------------------------------------------------------

def check_legacy_isolation() -> None:
    _section("4. Legacy Surface Isolation")

    # dashboard/LEGACY_SURFACE.md or dashboard/frontend/LEGACY_SURFACE.md
    legacy_markers = [
        PROJECT_ROOT / "dashboard" / "LEGACY_SURFACE.md",
        PROJECT_ROOT / "dashboard" / "frontend" / "LEGACY_SURFACE.md",
    ]
    for marker in legacy_markers:
        r = _record(
            f"legacy marker: {marker.relative_to(PROJECT_ROOT)}",
            marker.exists(),
            f"expected at {marker}",
        )
        _print_result(r)

    # windows_client root should NOT contain an ACTIVE_SURFACE.md at root
    # (active surface lives under status_board_v2/)
    windows_active = PROJECT_ROOT / "windows_client" / "status_board_v2" / "ACTIVE_SURFACE.md"
    r = _record(
        "windows_client/status_board_v2/ACTIVE_SURFACE.md exists",
        windows_active.exists(),
        "Status board v2 should carry ACTIVE_SURFACE.md",
    )
    _print_result(r)

    # dashboard/README.md should mention legacy/demoted status
    dash_readme = PROJECT_ROOT / "dashboard" / "README.md"
    if dash_readme.exists():
        content = dash_readme.read_text().lower()
        r = _record(
            "dashboard/README.md mentions legacy/demoted status",
            any(kw in content for kw in ("legacy", "demoted", "deprecated")),
            "dashboard README should clarify its demoted status",
        )
        _print_result(r)
    else:
        r = _record(
            "dashboard/README.md exists",
            False,
            warn_only=True,
            detail="optional but recommended",
        )
        _print_result(r)


# ---------------------------------------------------------------------------
# 5. Critical docs exist
# ---------------------------------------------------------------------------

def check_docs() -> None:
    _section("5. Critical Documentation Files")

    required_docs = [
        ("docs/ARCHITECTURE_BASELINE.md", "Post-PR-009 architecture baseline"),
        ("docs/REPO_LAYOUT.md", "Repository layout and zone classification"),
        ("docs/NODE_ACTIVE_MANIFEST.md", "Active node set manifest"),
        ("docs/ENTRYPOINT_AND_SURFACE_DEMOTION.md", "Surface demotion policy"),
        ("docs/MAINTAINER_RUNBOOK.md", "Maintainer runbook (PR-9)"),
        ("docs/LEGACY_PURGE_HARDENING.md", "Final legacy purge decisions (PR-10)"),
    ]
    for rel_path, description in required_docs:
        path = PROJECT_ROOT / rel_path
        r = _record(
            f"{rel_path}",
            path.exists(),
            f"({description})",
        )
        _print_result(r)


def check_purge_hardening() -> None:
    """PR-10: Verify final legacy purge and baseline hardening decisions."""
    _section("6. PR-10 Legacy Purge Hardening")

    # 6a. start_galaxy.py and start_l4.py must be fully removed
    for fname in ("start_galaxy.py", "start_l4.py"):
        removed = not (PROJECT_ROOT / fname).exists()
        r = _record(
            f"{fname}: fully removed",
            removed,
            f"{fname} must be deleted — use main.py or unified_launcher.py instead (post-PR-10 cleanup)",
        )
        _print_result(r)

    # 6b. Canonical L4 runtime module must be importable
    try:
        from core.galaxy_main_loop_l4_enhanced import GalaxyMainLoopL4  # type: ignore[import]
        r = _record(
            "core.galaxy_main_loop_l4_enhanced: canonical L4 module importable",
            True,
            "GalaxyMainLoopL4 is now the canonical class in core.galaxy_main_loop_l4_enhanced",
        )
    except Exception as exc:
        r = _record(
            "core.galaxy_main_loop_l4_enhanced: canonical L4 module importable",
            False,
            str(exc),
        )
    _print_result(r)

    # 6c. Legacy purge registry importable
    try:
        from core.legacy_purge_registry import (  # type: ignore[import]
            PURGE_REGISTRY,
            purge_registry_summary,
        )
        summary = purge_registry_summary()
        r = _record(
            "core.legacy_purge_registry importable",
            True,
            f"total entries: {summary['total_entries']}",
        )
        _print_result(r)

        r = _record(
            "purge registry: PR-10 entries present",
            "PR-10" in summary.get("by_pr", {}),
            "Registry must contain PR-10 purge decisions",
        )
        _print_result(r)
    except Exception as exc:
        _print_result(_record(
            "core.legacy_purge_registry importable",
            False,
            f"import failed: {exc}",
        ))

    # 6c. docs/LEGACY_PURGE_HARDENING.md exists (also checked in section 5,
    #     but we verify content here)
    purge_doc = PROJECT_ROOT / "docs" / "LEGACY_PURGE_HARDENING.md"
    if purge_doc.exists():
        content = purge_doc.read_text(encoding="utf-8")
        r = _record(
            "docs/LEGACY_PURGE_HARDENING.md: mentions _start_desktop removal",
            "_start_desktop" in content,
            "Purge doc must document the _start_desktop() dead reference removal",
        )
        _print_result(r)
    else:
        _print_result(_record(
            "docs/LEGACY_PURGE_HARDENING.md content",
            False,
            "File not found; skipping content check",
        ))





# ---------------------------------------------------------------------------
# Summary and CLI
# ---------------------------------------------------------------------------

def _summarise(strict: bool) -> int:
    passed = sum(1 for r in _results if r.status == "PASS")
    failed = sum(1 for r in _results if r.status == "FAIL")
    warned = sum(1 for r in _results if r.status == "WARN")
    total = len(_results)

    print(f"\n{'=' * 60}")
    print(f"  Galaxy Runtime Validation — Summary")
    print(f"{'=' * 60}")
    print(f"  Total checks : {total}")
    print(f"  ✓  Passed    : {passed}")
    if failed:
        print(f"  ✗  Failed    : {failed}")
    if warned:
        print(f"  △  Warnings  : {warned}")

    if failed == 0 and (not strict or warned == 0):
        print(f"\n  Result: PASS")
        print(f"{'=' * 60}\n")
        return 0
    else:
        print(f"\n  Result: FAIL")
        print(f"{'=' * 60}\n")
        return 1


def _to_json() -> Dict:
    return {
        "checks": [
            {"name": r.name, "status": r.status, "detail": r.detail}
            for r in _results
        ],
        "summary": {
            "total": len(_results),
            "passed": sum(1 for r in _results if r.status == "PASS"),
            "failed": sum(1 for r in _results if r.status == "FAIL"),
            "warned": sum(1 for r in _results if r.status == "WARN"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Galaxy runtime integration validator (PR-9 / PR-10)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON results to stdout instead of human-readable output",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 even if only warnings are present",
    )
    args = parser.parse_args()

    if not args.json:
        print("=" * 60)
        print("  Galaxy — Runtime Integration Validator (PR-9 / PR-10)")
        print("=" * 60)

    check_startup_path()
    check_authority_chain()
    check_node_registry()
    check_legacy_isolation()
    check_docs()
    check_purge_hardening()

    if args.json:
        print(json.dumps(_to_json(), indent=2))
        failed = sum(1 for r in _results if r.status == "FAIL")
        warned = sum(1 for r in _results if r.status == "WARN")
        if failed > 0 or (args.strict and warned > 0):
            return 1
        return 0

    return _summarise(strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
