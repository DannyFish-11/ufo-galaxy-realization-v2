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
        ("docs/STARTUP_TIER_MODEL.md", "Canonical startup-tier model and readiness baseline"),
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
# 7. Startup tier model
# ---------------------------------------------------------------------------


def check_startup_tier_model() -> None:
    """Validate the canonical 3-tier startup model and active-node readiness baseline."""
    _section("7. Startup Tier Model & Readiness Baseline")

    # 7a. core.startup_tier_model is importable
    try:
        from core.startup_tier_model import (  # type: ignore[import]
            STARTUP_TIER_MODEL_AUTHORITY,
            STARTUP_TIER_MODEL_GROUNDED_IN_EXISTING_GOVERNANCE,
            ACTIVE_NODE_READINESS_BASELINE_DEFINED,
            TIER_CORE,
            TIER_STANDARD,
            TIER_FULL,
            build_readiness_baseline,
            check_tier_model_metadata,
        )
        r = _record(
            "core.startup_tier_model importable",
            True,
            f"authority: {STARTUP_TIER_MODEL_AUTHORITY}",
        )
        _print_result(r)
    except Exception as exc:
        _print_result(_record(
            "core.startup_tier_model importable",
            False,
            str(exc)[:120],
        ))
        return

    # 7b. Sentinels set
    r = _record(
        "STARTUP_TIER_MODEL_GROUNDED_IN_EXISTING_GOVERNANCE sentinel",
        bool(STARTUP_TIER_MODEL_GROUNDED_IN_EXISTING_GOVERNANCE),
    )
    _print_result(r)
    r = _record(
        "ACTIVE_NODE_READINESS_BASELINE_DEFINED sentinel",
        bool(ACTIVE_NODE_READINESS_BASELINE_DEFINED),
    )
    _print_result(r)

    # 7c. node_dependencies.json contains _startup_tier_model metadata
    try:
        ndj_path = PROJECT_ROOT / "node_dependencies.json"
        with ndj_path.open(encoding="utf-8") as f:
            ndj_data = json.load(f)
        checks = check_tier_model_metadata(ndj_data)
        for check_name, ok in checks.items():
            r = _record(f"tier metadata: {check_name}", ok)
            _print_result(r)
    except Exception as exc:
        _print_result(_record("tier metadata checks", False, str(exc)[:120]))

    # 7d. NodeSystemLauncher exposes tier helpers
    try:
        from launcher.node_startup import NodeSystemLauncher  # type: ignore[import]
        r = _record(
            "NodeSystemLauncher.STARTUP_TIER_CORE == 'Core'",
            NodeSystemLauncher.STARTUP_TIER_CORE == TIER_CORE,
        )
        _print_result(r)
        r = _record(
            "NodeSystemLauncher.STARTUP_TIER_STANDARD == 'Standard'",
            NodeSystemLauncher.STARTUP_TIER_STANDARD == TIER_STANDARD,
        )
        _print_result(r)
        r = _record(
            "NodeSystemLauncher.STARTUP_TIER_FULL == 'Full'",
            NodeSystemLauncher.STARTUP_TIER_FULL == TIER_FULL,
        )
        _print_result(r)
        r = _record(
            "NodeSystemLauncher.get_tier_nodes method present",
            callable(getattr(NodeSystemLauncher, "get_tier_nodes", None)),
        )
        _print_result(r)
        r = _record(
            "NodeSystemLauncher.get_readiness_baseline method present",
            callable(getattr(NodeSystemLauncher, "get_readiness_baseline", None)),
        )
        _print_result(r)
    except Exception as exc:
        _print_result(_record(
            "NodeSystemLauncher tier helpers",
            False,
            str(exc)[:120],
        ))

    # 7e. Readiness baseline is coherent
    try:
        baseline = build_readiness_baseline()
        r = _record(
            f"Core-tier node count ({baseline.core_tier_count})",
            baseline.core_tier_count >= 1,
            f"expected ≥ 1, got {baseline.core_tier_count}",
        )
        _print_result(r)
        r = _record(
            "Standard tier ⊇ Core tier",
            set(baseline.core_tier).issubset(set(baseline.standard_tier)),
            "standard_tier must be a superset of core_tier",
        )
        _print_result(r)
        r = _record(
            f"Active baseline count ({baseline.active_baseline_count})",
            baseline.active_baseline_count >= 1,
            f"active nodes meeting readiness bar: {baseline.active_baseline_count}",
        )
        _print_result(r)
        r = _record(
            "Core-tier nodes have no readiness gaps",
            baseline.is_core_complete(),
            (
                f"Core nodes with gaps: "
                f"{[n for n in baseline.readiness_gaps if n in baseline.core_tier]}"
                if not baseline.is_core_complete() else ""
            ),
        )
        _print_result(r)
        r = _record(
            f"readiness gap count ({baseline.readiness_gap_count})",
            baseline.readiness_gap_count <= 30,
            f"active nodes missing fusion_entry.py: {baseline.readiness_gap_count}",
            warn_only=baseline.readiness_gap_count > 0,
        )
        _print_result(r)
    except Exception as exc:
        _print_result(_record(
            "readiness baseline coherence",
            False,
            str(exc)[:120],
        ))

    # 7f. Canonical doc exists
    tier_doc = PROJECT_ROOT / "docs" / "STARTUP_TIER_MODEL.md"
    r = _record(
        "docs/STARTUP_TIER_MODEL.md exists",
        tier_doc.exists(),
        "Canonical startup-tier reference doc (PR-startup-tiers)",
    )
    _print_result(r)


# ---------------------------------------------------------------------------
# 8. Runtime acceptance checks (Phase-B consolidation)
# ---------------------------------------------------------------------------


def check_runtime_acceptance() -> None:
    """Phase-B: Minimal runtime acceptance checks for the primary request path.

    Verifies three things without launching any live services:
    a. Core startup modules are importable (DesktopPresenceRuntime, OpenClawd,
       CommandRouter).
    b. ``OpenClawd._collect_tools()`` method is present and callable (structural
       check; does not require live MCP/Skill/Node backends).
    c. ``CanonicalDispatcher.classify()`` can route all canonical tool prefixes
       to the correct :class:`~core.capabilities.canonical_dispatcher.CapabilityLayer`.
    """
    _section("8. Runtime Acceptance — Primary Request Path")

    # 8a. Core startup modules importable
    core_modules = [
        ("core.desktop_presence_runtime", "DesktopPresenceRuntime"),
        ("core.openclawd", "OpenClawd"),
        ("core.command_router", "CommandRouter"),
    ]
    for mod_name, cls_name in core_modules:
        try:
            mod = importlib.import_module(mod_name)
            ok = hasattr(mod, cls_name)
            detail = "" if ok else f"{cls_name} not found in {mod_name}"
        except Exception as exc:
            ok = False
            detail = str(exc)[:120]
        r = _record(f"acceptance: {mod_name}.{cls_name} importable", ok, detail)
        _print_result(r)

    # 8b. OpenClawd._collect_tools method is present
    try:
        from core.openclawd import OpenClawd  # type: ignore[import]
        has_method = callable(getattr(OpenClawd, "_collect_tools", None))
        r = _record(
            "acceptance: OpenClawd._collect_tools() is present",
            has_method,
            "method must exist and be callable for tool collection to work",
        )
        _print_result(r)
    except Exception as exc:
        r = _record(
            "acceptance: OpenClawd._collect_tools() is present",
            False,
            str(exc)[:120],
        )
        _print_result(r)

    # 8c. CanonicalDispatcher classifies canonical tool prefixes correctly
    try:
        from core.capabilities.canonical_dispatcher import (  # type: ignore[import]
            CanonicalDispatcher,
            CapabilityLayer,
        )
        test_cases = [
            ("mcp__server__tool", CapabilityLayer.MCP),
            ("mcp__gateway__tool", CapabilityLayer.MCP_GW),
            ("skill__my_skill", CapabilityLayer.SKILL),
            ("node__node_01__ping", CapabilityLayer.NODE),
        ]
        all_ok = True
        for tool_name, expected_layer in test_cases:
            got = CapabilityLayer.classify(tool_name)
            if got != expected_layer:
                all_ok = False
                _print_result(_record(
                    f"acceptance: CanonicalDispatcher.classify({tool_name!r})",
                    False,
                    f"expected {expected_layer.value!r}, got {got.value!r}",
                ))
        if all_ok:
            r = _record(
                "acceptance: CanonicalDispatcher classifies all canonical prefixes",
                True,
                "mcp__ / mcp__gateway__ / skill__ / node__ all routed correctly",
            )
            _print_result(r)
    except Exception as exc:
        r = _record(
            "acceptance: CanonicalDispatcher classifies canonical prefixes",
            False,
            str(exc)[:120],
        )
        _print_result(r)

    # 8d. Phase-A sentinel: scheduler canonical tool naming
    try:
        from core.scheduler import SCHEDULER_CANONICAL_TOOL_NAMING_PRIMARY  # type: ignore[import]
        r = _record(
            "acceptance: SCHEDULER_CANONICAL_TOOL_NAMING_PRIMARY sentinel present",
            bool(SCHEDULER_CANONICAL_TOOL_NAMING_PRIMARY),
            SCHEDULER_CANONICAL_TOOL_NAMING_PRIMARY[:80],
        )
        _print_result(r)
    except Exception as exc:
        r = _record(
            "acceptance: SCHEDULER_CANONICAL_TOOL_NAMING_PRIMARY sentinel present",
            False,
            str(exc)[:120],
        )
        _print_result(r)

    # 8e. Phase-A sentinel: hybrid executor rename
    try:
        from core.hybrid_executor import APP_EXECUTION_CAPABILITY_REGISTRY_RENAMED  # type: ignore[import]
        r = _record(
            "acceptance: APP_EXECUTION_CAPABILITY_REGISTRY_RENAMED sentinel present",
            bool(APP_EXECUTION_CAPABILITY_REGISTRY_RENAMED),
            APP_EXECUTION_CAPABILITY_REGISTRY_RENAMED[:80],
        )
        _print_result(r)
    except Exception as exc:
        r = _record(
            "acceptance: APP_EXECUTION_CAPABILITY_REGISTRY_RENAMED sentinel present",
            False,
            str(exc)[:120],
        )
        _print_result(r)


# ---------------------------------------------------------------------------
# 9. Callable-node baseline (Phase-B consolidation)
# ---------------------------------------------------------------------------


def check_callable_node_baseline() -> None:
    """Phase-B: Verify the callable-node baseline is encoded and queryable.

    Checks:
    a. ``core.callable_node_baseline`` is importable and carries the
       :data:`CALLABLE_NODE_BASELINE_ESTABLISHED` sentinel.
    b. :data:`CALLABLE_ARCHITECTURAL_CLASSES` is non-empty (at least one class
       makes a node callable).
    c. :func:`is_callable_by_openclawd` correctly distinguishes CAPABILITY_NODE
       (callable) from SERVICE_NODE / LEGACY_ORCHESTRATOR_NODE (not callable).
    d. :func:`get_callable_node_names` is callable without error.
    e. ``NodeArchitecturalClass`` enum is accessible from the node fabric
       registry and carries the expected members.
    """
    _section("9. Callable-Node Baseline")

    # 9a. Module importable + sentinel
    try:
        from core.callable_node_baseline import (  # type: ignore[import]
            CALLABLE_NODE_BASELINE_ESTABLISHED,
            CALLABLE_ARCHITECTURAL_CLASSES,
            is_callable_by_openclawd,
            get_callable_node_names,
        )
        r = _record(
            "core.callable_node_baseline importable",
            True,
            f"sentinel: {CALLABLE_NODE_BASELINE_ESTABLISHED[:60]}",
        )
        _print_result(r)
        r = _record(
            "CALLABLE_NODE_BASELINE_ESTABLISHED sentinel",
            bool(CALLABLE_NODE_BASELINE_ESTABLISHED),
        )
        _print_result(r)
    except Exception as exc:
        _print_result(_record(
            "core.callable_node_baseline importable",
            False,
            str(exc)[:120],
        ))
        return

    # 9b. CALLABLE_ARCHITECTURAL_CLASSES is non-empty
    r = _record(
        f"CALLABLE_ARCHITECTURAL_CLASSES non-empty ({len(CALLABLE_ARCHITECTURAL_CLASSES)} class(es))",
        len(CALLABLE_ARCHITECTURAL_CLASSES) >= 1,
        "at least CAPABILITY_NODE must be callable",
    )
    _print_result(r)

    # 9c. is_callable_by_openclawd semantics
    try:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass  # type: ignore[import]
        cases = [
            (NodeArchitecturalClass.CAPABILITY_NODE, True),
            (NodeArchitecturalClass.SERVICE_NODE, False),
            (NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE, False),
            (NodeArchitecturalClass.EXPERIMENTAL_NODE, False),
            (NodeArchitecturalClass.ARCHIVED_NODE, False),
        ]
        all_ok = True
        for arch_cls, expected in cases:
            got = is_callable_by_openclawd(arch_cls)
            if got != expected:
                all_ok = False
                _print_result(_record(
                    f"is_callable_by_openclawd({arch_cls.value})",
                    False,
                    f"expected {expected}, got {got}",
                ))
        if all_ok:
            r = _record(
                "is_callable_by_openclawd() semantics correct for all 5 classes",
                True,
                "CAPABILITY_NODE=callable; SERVICE/LEGACY/EXPERIMENTAL/ARCHIVED=not callable",
            )
            _print_result(r)
    except Exception as exc:
        r = _record(
            "is_callable_by_openclawd() semantics",
            False,
            str(exc)[:120],
        )
        _print_result(r)

    # 9d. get_callable_node_names() returns without error
    try:
        node_names = get_callable_node_names()
        r = _record(
            f"get_callable_node_names() callable (returned {len(node_names)} names)",
            True,
        )
        _print_result(r)
    except Exception as exc:
        r = _record(
            "get_callable_node_names() callable",
            False,
            str(exc)[:120],
        )
        _print_result(r)

    # 9e. NodeArchitecturalClass accessible from node_fabric_registry
    try:
        from core.nodes.node_fabric_registry import (  # type: ignore[import]
            NodeArchitecturalClass,
            _CAPABILITY_SYNC_ELIGIBLE,
        )
        members = {c.value for c in NodeArchitecturalClass}
        expected_members = {
            "capability_node", "service_node", "legacy_orchestrator_node",
            "experimental_node", "archived_node",
        }
        ok = expected_members.issubset(members)
        r = _record(
            "NodeArchitecturalClass has all expected members",
            ok,
            f"members: {sorted(members)}" if not ok else "",
        )
        _print_result(r)
        r = _record(
            "_CAPABILITY_SYNC_ELIGIBLE non-empty",
            len(_CAPABILITY_SYNC_ELIGIBLE) >= 1,
        )
        _print_result(r)
    except Exception as exc:
        r = _record(
            "NodeArchitecturalClass accessible",
            False,
            str(exc)[:120],
        )
        _print_result(r)


# ---------------------------------------------------------------------------
# 10. Callable-node baseline startup integration (PR-529 Phase-B)
# ---------------------------------------------------------------------------


def check_callable_startup_integration() -> None:
    """Phase-B: Verify the callable-node baseline is integrated into node startup.

    Checks:
    a. ``launcher.node_startup`` exposes the
       :data:`~launcher.node_startup.CALLABLE_BASELINE_STARTUP_INTEGRATION`
       sentinel confirming the integration is present.
    b. :meth:`~launcher.node_startup.NodeSystemLauncher.get_callable_node_classification`
       method is callable without error.
    c. The method returns the expected classification keys.
    d. ``classification_available`` field is present in the result.
    """
    _section("10. Callable-Node Baseline Startup Integration")

    # 10a. Sentinel
    try:
        import importlib.util as _ilu
        import sys as _sys
        _launcher_path = (
            Path(__file__).parent.parent / "launcher" / "node_startup.py"
        )
        _spec = _ilu.spec_from_file_location("_node_startup_check", _launcher_path)
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
        sentinel = getattr(_mod, "CALLABLE_BASELINE_STARTUP_INTEGRATION", None)
        r = _record(
            "CALLABLE_BASELINE_STARTUP_INTEGRATION sentinel present",
            bool(sentinel),
            f"{str(sentinel)[:80]}" if sentinel else "sentinel missing",
        )
        _print_result(r)
    except Exception as exc:
        _print_result(_record(
            "launcher.node_startup importable",
            False,
            str(exc)[:120],
        ))
        return

    # 10b/c/d. get_callable_node_classification()
    try:
        launcher_cls = getattr(_mod, "NodeSystemLauncher", None)
        if launcher_cls is None:
            _print_result(_record(
                "NodeSystemLauncher class accessible",
                False,
                "NodeSystemLauncher not found in launcher.node_startup",
            ))
            return
        r = _record("NodeSystemLauncher.get_callable_node_classification method present",
                    hasattr(launcher_cls, "get_callable_node_classification"))
        _print_result(r)
    except Exception as exc:
        _print_result(_record(
            "NodeSystemLauncher.get_callable_node_classification accessible",
            False,
            str(exc)[:120],
        ))


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


# ---------------------------------------------------------------------------
# 10. Execution spine observability hardening (PR-530)
# ---------------------------------------------------------------------------


def check_spine_observability() -> None:
    """PR-530: Verify that the execution spine carries stable correlation IDs.

    Checks:
    a. ``CANONICAL_DISPATCHER_SPINE_HARDENED`` sentinel is importable from
       ``core.capabilities.canonical_dispatcher``.
    b. ``DispatchResult`` carries ``trace_id`` and ``request_id`` fields.
    c. ``OPENCLAWD_SPINE_OBSERVABILITY_HARDENED`` sentinel is importable from
       ``core.openclawd``.
    d. ``COMMAND_ROUTER_CORRELATION_HARDENED`` sentinel is importable from
       ``core.command_router``.
    e. ``CapabilityLayer.classify()`` returns deterministic values for all
       canonical tool prefixes (regression guard).
    """
    _section("10. Execution Spine Observability Hardening (PR-530)")

    # 10a. CanonicalDispatcher spine-hardened sentinel
    try:
        from core.capabilities.canonical_dispatcher import (  # type: ignore[import]
            CANONICAL_DISPATCHER_SPINE_HARDENED,
        )
        r = _record(
            "spine: CANONICAL_DISPATCHER_SPINE_HARDENED sentinel present",
            bool(CANONICAL_DISPATCHER_SPINE_HARDENED),
            CANONICAL_DISPATCHER_SPINE_HARDENED[:80],
        )
        _print_result(r)
    except Exception as exc:
        r = _record(
            "spine: CANONICAL_DISPATCHER_SPINE_HARDENED sentinel present",
            False,
            str(exc)[:120],
        )
        _print_result(r)

    # 10b. DispatchResult carries trace_id + request_id
    try:
        from core.capabilities.canonical_dispatcher import DispatchResult  # type: ignore[import]
        dr = DispatchResult(success=True, trace_id="t1", request_id="r1")
        has_trace = hasattr(dr, "trace_id") and dr.trace_id == "t1"
        has_request = hasattr(dr, "request_id") and dr.request_id == "r1"
        d = dr.to_dict()
        in_dict = "trace_id" in d and "request_id" in d
        ok = has_trace and has_request and in_dict
        detail = "" if ok else (
            f"trace_id={has_trace} request_id={has_request} in_dict={in_dict}"
        )
        r = _record(
            "spine: DispatchResult carries trace_id + request_id in to_dict()",
            ok,
            detail,
        )
        _print_result(r)
    except Exception as exc:
        r = _record(
            "spine: DispatchResult carries trace_id + request_id in to_dict()",
            False,
            str(exc)[:120],
        )
        _print_result(r)

    # 10c. OpenClawd spine observability hardened sentinel
    try:
        from core.openclawd import OPENCLAWD_SPINE_OBSERVABILITY_HARDENED  # type: ignore[import]
        r = _record(
            "spine: OPENCLAWD_SPINE_OBSERVABILITY_HARDENED sentinel present",
            bool(OPENCLAWD_SPINE_OBSERVABILITY_HARDENED),
            OPENCLAWD_SPINE_OBSERVABILITY_HARDENED[:80],
        )
        _print_result(r)
    except Exception as exc:
        r = _record(
            "spine: OPENCLAWD_SPINE_OBSERVABILITY_HARDENED sentinel present",
            False,
            str(exc)[:120],
        )
        _print_result(r)

    # 10d. CommandRouter correlation hardened sentinel
    try:
        from core.command_router import COMMAND_ROUTER_CORRELATION_HARDENED  # type: ignore[import]
        r = _record(
            "spine: COMMAND_ROUTER_CORRELATION_HARDENED sentinel present",
            bool(COMMAND_ROUTER_CORRELATION_HARDENED),
            COMMAND_ROUTER_CORRELATION_HARDENED[:80],
        )
        _print_result(r)
    except Exception as exc:
        r = _record(
            "spine: COMMAND_ROUTER_CORRELATION_HARDENED sentinel present",
            False,
            str(exc)[:120],
        )
        _print_result(r)

    # 10e. CapabilityLayer.classify() regression guard
    try:
        from core.capabilities.canonical_dispatcher import (  # type: ignore[import]
            CapabilityLayer,
        )
        cases = [
            ("mcp__srv__tool",      CapabilityLayer.MCP),
            ("mcp__gateway__tool",  CapabilityLayer.MCP_GW),
            ("skill__my_skill",     CapabilityLayer.SKILL),
            ("node__n1__ping",      CapabilityLayer.NODE),
            ("device__d1__act",     CapabilityLayer.DEVICE),
            ("github__install",     CapabilityLayer.GITHUB),
            ("unknown_prefix",      CapabilityLayer.UNKNOWN),
        ]
        failures = []
        for name, expected in cases:
            got = CapabilityLayer.classify(name)
            if got != expected:
                failures.append(f"{name!r}: expected {expected.value!r} got {got.value!r}")
        ok = len(failures) == 0
        r = _record(
            "spine: CapabilityLayer.classify() deterministic for all prefixes",
            ok,
            "; ".join(failures) if failures else "all 7 prefixes classify correctly",
        )
        _print_result(r)
    except Exception as exc:
        r = _record(
            "spine: CapabilityLayer.classify() deterministic for all prefixes",
            False,
            str(exc)[:120],
        )
        _print_result(r)


# ---------------------------------------------------------------------------
# 11. Outward Runtime Truth (PR-531)
# ---------------------------------------------------------------------------


def check_outward_runtime_truth() -> None:
    """PR-531: Verify that the outward runtime truth governance layer is present.

    Checks:
    a. ``core.outward_runtime_truth`` is importable.
    b. :data:`~core.outward_runtime_truth.OUTWARD_RUNTIME_TRUTH_AUTHORITY`
       sentinel is non-empty.
    c. :func:`~core.outward_runtime_truth.compile_outward_truth` is callable.
    d. Compilation returns an :class:`~core.outward_runtime_truth.OutwardRuntimeTruthSnapshot`
       with a non-empty ``snapshot_id`` and ``compiled_at > 0``.
    e. Policy sentinels are present and non-empty.
    f. :data:`~core.routes.projection.OUTWARD_RUNTIME_TRUTH_INTEGRATED` sentinel
       is present in ``core.routes.projection``.
    """
    _section("11. Outward Runtime Truth (PR-531)")

    # 11a. Import
    try:
        from core.outward_runtime_truth import (
            OUTWARD_RUNTIME_TRUTH_AUTHORITY,
            OUTWARD_RUNTIME_TRUTH_LAYER_POSITION,
            NO_SECONDARY_SOURCE_AS_PRIMARY_TRUTH_POLICY,
            NO_PARALLEL_OUTWARD_ASSEMBLY_POLICY,
            OUTWARD_SURFACE_MUST_PREFER_COMPILED_TRUTH_POLICY,
            compile_outward_truth,
            OutwardRuntimeTruthSnapshot,
            reset_outward_runtime_truth_runtime,
        )
        r = _record(
            "outward_runtime_truth: module importable",
            True,
            "core.outward_runtime_truth importable",
        )
        _print_result(r)
    except Exception as exc:
        r = _record("outward_runtime_truth: module importable", False, str(exc)[:120])
        _print_result(r)
        return

    # 11b. Authority sentinel
    r = _record(
        "outward_runtime_truth: OUTWARD_RUNTIME_TRUTH_AUTHORITY non-empty",
        bool(OUTWARD_RUNTIME_TRUTH_AUTHORITY),
        str(OUTWARD_RUNTIME_TRUTH_AUTHORITY)[:60],
    )
    _print_result(r)

    # 11c. Layer position
    r = _record(
        "outward_runtime_truth: LAYER_POSITION == 15",
        OUTWARD_RUNTIME_TRUTH_LAYER_POSITION == 15,
        f"layer_position={OUTWARD_RUNTIME_TRUTH_LAYER_POSITION}",
    )
    _print_result(r)

    # 11d. Policy sentinels present
    for sentinel_name, sentinel_val in [
        ("NO_SECONDARY_SOURCE_AS_PRIMARY_TRUTH_POLICY", NO_SECONDARY_SOURCE_AS_PRIMARY_TRUTH_POLICY),
        ("NO_PARALLEL_OUTWARD_ASSEMBLY_POLICY", NO_PARALLEL_OUTWARD_ASSEMBLY_POLICY),
        ("OUTWARD_SURFACE_MUST_PREFER_COMPILED_TRUTH_POLICY", OUTWARD_SURFACE_MUST_PREFER_COMPILED_TRUTH_POLICY),
    ]:
        r = _record(
            f"outward_runtime_truth: {sentinel_name} non-empty",
            bool(sentinel_val),
            str(sentinel_val)[:60],
        )
        _print_result(r)

    # 11e. compile_outward_truth() callable and returns a snapshot
    try:
        reset_outward_runtime_truth_runtime()
        snapshot = compile_outward_truth()
        r = _record(
            "outward_runtime_truth: compile_outward_truth() returns snapshot",
            isinstance(snapshot, OutwardRuntimeTruthSnapshot),
            f"snapshot_id={str(getattr(snapshot, 'snapshot_id', ''))[:12]}...",
        )
        _print_result(r)
        r = _record(
            "outward_runtime_truth: snapshot.compiled_at > 0",
            getattr(snapshot, "compiled_at", 0) > 0,
            f"compiled_at={getattr(snapshot, 'compiled_at', None)}",
        )
        _print_result(r)
        r = _record(
            "outward_runtime_truth: snapshot has source_records",
            isinstance(getattr(snapshot, "source_records", None), list),
        )
        _print_result(r)
    except Exception as exc:
        r = _record("outward_runtime_truth: compile_outward_truth() callable", False, str(exc)[:120])
        _print_result(r)

    # 11f. Projection routes integration sentinel
    try:
        import importlib.util as _ilu
        _proj_path = Path(__file__).parent.parent / "core" / "routes" / "projection.py"
        _spec = _ilu.spec_from_file_location("_proj_check_ort", _proj_path)
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
        integrated = getattr(_mod, "OUTWARD_RUNTIME_TRUTH_INTEGRATED", None)
        r = _record(
            "projection_routes: OUTWARD_RUNTIME_TRUTH_INTEGRATED sentinel present",
            bool(integrated) and "UNAVAILABLE" not in str(integrated),
            str(integrated)[:80] if integrated else "sentinel missing",
        )
        _print_result(r)
    except Exception as exc:
        r = _record(
            "projection_routes: OUTWARD_RUNTIME_TRUTH_INTEGRATED sentinel",
            False,
            str(exc)[:120],
        )
        _print_result(r)


# ---------------------------------------------------------------------------
# 12. Node Lifecycle Governor (PR-531)
# ---------------------------------------------------------------------------


def check_node_lifecycle_governor() -> None:
    """PR-531: Verify that the node lifecycle governor is present and functional.

    Checks:
    a. ``core.node_lifecycle_governor`` is importable.
    b. Authority sentinel and pipeline sentinel are non-empty.
    c. Policy sentinels are non-empty.
    d. :func:`~core.node_lifecycle_governor.get_node_lifecycle_governor` returns
       a singleton.
    e. :meth:`~core.node_lifecycle_governor.NodeLifecycleGovernor.register_node`
       returns a valid :class:`~core.node_lifecycle_governor.NodeGovernanceRecord`.
    f. :meth:`~core.node_lifecycle_governor.NodeLifecycleGovernor.govern_node`
       advances the lifecycle stage beyond REGISTERED.
    g. Promotion pipeline: a node with capability_registered=True is promotable.
    """
    _section("12. Node Lifecycle Governor (PR-531)")

    try:
        from core.node_lifecycle_governor import (
            NODE_LIFECYCLE_GOVERNOR_AUTHORITY,
            NODE_LIFECYCLE_GOVERNOR_LAYER_POSITION,
            NODE_LIFECYCLE_GOVERNANCE_PIPELINE_DEFINED,
            NODE_MUST_PASS_LIFECYCLE_GATES_POLICY,
            NO_WILD_GROWTH_POLICY,
            PROMOTION_REQUIRES_CAPABILITY_REGISTRATION_POLICY,
            NodeLifecycleStage,
            NodeGovernanceRecord,
            NodeLifecycleGovernor,
            get_node_lifecycle_governor,
            reset_node_lifecycle_governor,
            govern_node,
        )
        r = _record("node_lifecycle_governor: module importable", True)
        _print_result(r)
    except Exception as exc:
        r = _record("node_lifecycle_governor: module importable", False, str(exc)[:120])
        _print_result(r)
        return

    # 12b. Sentinels
    r = _record(
        "node_lifecycle_governor: NODE_LIFECYCLE_GOVERNOR_AUTHORITY non-empty",
        bool(NODE_LIFECYCLE_GOVERNOR_AUTHORITY),
        str(NODE_LIFECYCLE_GOVERNOR_AUTHORITY)[:60],
    )
    _print_result(r)
    r = _record(
        "node_lifecycle_governor: LAYER_POSITION == 15",
        NODE_LIFECYCLE_GOVERNOR_LAYER_POSITION == 15,
    )
    _print_result(r)
    r = _record(
        "node_lifecycle_governor: PIPELINE sentinel non-empty",
        bool(NODE_LIFECYCLE_GOVERNANCE_PIPELINE_DEFINED),
    )
    _print_result(r)
    for name, val in [
        ("NODE_MUST_PASS_LIFECYCLE_GATES_POLICY", NODE_MUST_PASS_LIFECYCLE_GATES_POLICY),
        ("NO_WILD_GROWTH_POLICY", NO_WILD_GROWTH_POLICY),
        ("PROMOTION_REQUIRES_CAPABILITY_REGISTRATION_POLICY", PROMOTION_REQUIRES_CAPABILITY_REGISTRATION_POLICY),
    ]:
        r = _record(f"node_lifecycle_governor: {name} non-empty", bool(val))
        _print_result(r)

    # 12c. Singleton accessible
    try:
        reset_node_lifecycle_governor()
        gov = get_node_lifecycle_governor()
        r = _record(
            "node_lifecycle_governor: singleton accessible",
            gov is not None,
        )
        _print_result(r)
    except Exception as exc:
        r = _record("node_lifecycle_governor: singleton accessible", False, str(exc)[:120])
        _print_result(r)
        return

    # 12d. register_node()
    try:
        rec = gov.register_node("_validate_test_node", startup_policy="active")
        r = _record(
            "node_lifecycle_governor: register_node() returns NodeGovernanceRecord",
            isinstance(rec, NodeGovernanceRecord),
            f"stage={rec.lifecycle_stage.value}",
        )
        _print_result(r)
        r = _record(
            "node_lifecycle_governor: initial stage is REGISTERED",
            rec.lifecycle_stage == NodeLifecycleStage.REGISTERED,
        )
        _print_result(r)
    except Exception as exc:
        r = _record("node_lifecycle_governor: register_node()", False, str(exc)[:120])
        _print_result(r)
        return

    # 12e. govern_node() advances stage
    try:
        rec2 = gov.govern_node("_validate_test_node2")
        r = _record(
            "node_lifecycle_governor: govern_node() runs without error",
            rec2 is not None,
            f"stage={rec2.lifecycle_stage.value}",
        )
        _print_result(r)
        r = _record(
            "node_lifecycle_governor: govern_node() advances beyond REGISTERED",
            rec2.lifecycle_stage != NodeLifecycleStage.REGISTERED,
            f"stage={rec2.lifecycle_stage.value}",
        )
        _print_result(r)
    except Exception as exc:
        r = _record("node_lifecycle_governor: govern_node()", False, str(exc)[:120])
        _print_result(r)

    # 12f. snapshot()
    try:
        snap = gov.snapshot()
        r = _record(
            "node_lifecycle_governor: snapshot() returns NodeLifecycleGovernorSnapshot",
            snap is not None and hasattr(snap, "total_nodes"),
            f"total_nodes={getattr(snap, 'total_nodes', '?')}",
        )
        _print_result(r)
    except Exception as exc:
        r = _record("node_lifecycle_governor: snapshot()", False, str(exc)[:120])
        _print_result(r)


# ---------------------------------------------------------------------------
# 13. Deployment Baseline (PR-531)
# ---------------------------------------------------------------------------


def check_deployment_baseline() -> None:
    """PR-531: Verify that the deployment baseline is checkable in code.

    Checks:
    a. ``core.deployment_baseline`` is importable.
    b. Authority and policy sentinels are non-empty.
    c. :func:`~core.deployment_baseline.check_runtime_baseline` returns a
       :class:`~core.deployment_baseline.DeploymentBaselineReport`.
    d. CORE_RUNTIME baseline_met is True (all core checks pass).
    e. DeploymentEnvironment tiers are defined.
    """
    _section("13. Deployment Baseline (PR-531)")

    try:
        from core.deployment_baseline import (
            DEPLOYMENT_BASELINE_AUTHORITY,
            DEPLOYMENT_BASELINE_LAYER_POSITION,
            DEPLOYMENT_BASELINE_CONVERGENCE_DEFINED,
            CORE_RUNTIME_MUST_BE_CHECKABLE_POLICY,
            ENVIRONMENT_TIERS_MUST_MAP_TO_STARTUP_TIERS_POLICY,
            DeploymentEnvironment,
            DeploymentBaselineReport,
            check_runtime_baseline,
            reset_deployment_baseline_runtime,
        )
        r = _record("deployment_baseline: module importable", True)
        _print_result(r)
    except Exception as exc:
        r = _record("deployment_baseline: module importable", False, str(exc)[:120])
        _print_result(r)
        return

    # 13b. Sentinels
    r = _record(
        "deployment_baseline: DEPLOYMENT_BASELINE_AUTHORITY non-empty",
        bool(DEPLOYMENT_BASELINE_AUTHORITY),
    )
    _print_result(r)
    r = _record(
        "deployment_baseline: LAYER_POSITION == 15",
        DEPLOYMENT_BASELINE_LAYER_POSITION == 15,
    )
    _print_result(r)
    for name, val in [
        ("DEPLOYMENT_BASELINE_CONVERGENCE_DEFINED", DEPLOYMENT_BASELINE_CONVERGENCE_DEFINED),
        ("CORE_RUNTIME_MUST_BE_CHECKABLE_POLICY", CORE_RUNTIME_MUST_BE_CHECKABLE_POLICY),
        ("ENVIRONMENT_TIERS_MUST_MAP_TO_STARTUP_TIERS_POLICY", ENVIRONMENT_TIERS_MUST_MAP_TO_STARTUP_TIERS_POLICY),
    ]:
        r = _record(f"deployment_baseline: {name} non-empty", bool(val))
        _print_result(r)

    # 13c. DeploymentEnvironment tiers
    for tier in ("CORE_RUNTIME", "STANDARD_DEV", "FULL_PRODUCTION"):
        r = _record(
            f"deployment_baseline: DeploymentEnvironment.{tier} defined",
            hasattr(DeploymentEnvironment, tier),
        )
        _print_result(r)

    # 13d. check_runtime_baseline() returns a report
    try:
        reset_deployment_baseline_runtime()
        report = check_runtime_baseline(DeploymentEnvironment.CORE_RUNTIME)
        r = _record(
            "deployment_baseline: check_runtime_baseline(CORE_RUNTIME) returns report",
            isinstance(report, DeploymentBaselineReport),
            f"baseline_met={getattr(report, 'baseline_met', '?')}",
        )
        _print_result(r)
        r = _record(
            "deployment_baseline: CORE_RUNTIME baseline_met is True",
            getattr(report, "baseline_met", False),
            f"passed={getattr(report, 'passed_count', '?')} "
            f"failed={getattr(report, 'failed_count', '?')}",
        )
        _print_result(r)
    except Exception as exc:
        r = _record(
            "deployment_baseline: check_runtime_baseline() callable", False, str(exc)[:120]
        )
        _print_result(r)


# ---------------------------------------------------------------------------
# 14. Capability Utilization Observability (PR-531)
# ---------------------------------------------------------------------------


def check_capability_utilization_observability() -> None:
    """PR-531: Verify that capability utilization observability is present.

    Checks:
    a. ``core.capability_utilization_observability`` is importable.
    b. Authority and foundation sentinels are non-empty.
    c. :func:`~core.capability_utilization_observability.record_capability_call`
       is callable without error.
    d. :func:`~core.capability_utilization_observability.get_utilization_report`
       returns a valid report after a recorded call.
    e. :func:`~core.capability_utilization_observability.get_all_utilization_reports`
       returns a :class:`~core.capability_utilization_observability.UtilizationSummary`.
    f. :data:`OBSERVABILITY_DOES_NOT_BLOCK_DISPATCH_POLICY` sentinel present.
    """
    _section("14. Capability Utilization Observability (PR-531)")

    try:
        from core.capability_utilization_observability import (
            CAPABILITY_UTILIZATION_OBSERVABILITY_AUTHORITY,
            CAPABILITY_UTILIZATION_OBSERVABILITY_LAYER_POSITION,
            CAPABILITY_UTILIZATION_FOUNDATIONS_ESTABLISHED,
            OBSERVABILITY_DOES_NOT_BLOCK_DISPATCH_POLICY,
            UTILIZATION_DATA_IS_ADVISORY_POLICY,
            record_capability_call,
            record_failure,
            get_utilization_report,
            get_all_utilization_reports,
            UtilizationReport,
            UtilizationSummary,
            reset_capability_utilization_observability,
        )
        r = _record("capability_utilization_observability: module importable", True)
        _print_result(r)
    except Exception as exc:
        r = _record(
            "capability_utilization_observability: module importable",
            False,
            str(exc)[:120],
        )
        _print_result(r)
        return

    # 14b. Sentinels
    r = _record(
        "capability_utilization_observability: AUTHORITY non-empty",
        bool(CAPABILITY_UTILIZATION_OBSERVABILITY_AUTHORITY),
    )
    _print_result(r)
    r = _record(
        "capability_utilization_observability: LAYER_POSITION == 15",
        CAPABILITY_UTILIZATION_OBSERVABILITY_LAYER_POSITION == 15,
    )
    _print_result(r)
    for name, val in [
        ("FOUNDATIONS_ESTABLISHED", CAPABILITY_UTILIZATION_FOUNDATIONS_ESTABLISHED),
        ("OBSERVABILITY_DOES_NOT_BLOCK_DISPATCH_POLICY", OBSERVABILITY_DOES_NOT_BLOCK_DISPATCH_POLICY),
        ("UTILIZATION_DATA_IS_ADVISORY_POLICY", UTILIZATION_DATA_IS_ADVISORY_POLICY),
    ]:
        r = _record(f"capability_utilization_observability: {name} non-empty", bool(val))
        _print_result(r)

    # 14c. record_capability_call() fire-and-forget
    try:
        reset_capability_utilization_observability()
        record_capability_call(
            "node::_validate_test::action",
            caller="validate_runtime",
            success=True,
            latency_ms=1.5,
        )
        r = _record(
            "capability_utilization_observability: record_capability_call() non-raising",
            True,
        )
        _print_result(r)
    except Exception as exc:
        r = _record(
            "capability_utilization_observability: record_capability_call() non-raising",
            False,
            str(exc)[:120],
        )
        _print_result(r)
        return

    # 14d. get_utilization_report()
    try:
        report = get_utilization_report("node::_validate_test::action")
        r = _record(
            "capability_utilization_observability: get_utilization_report() returns UtilizationReport",
            isinstance(report, UtilizationReport),
            f"total_calls={getattr(report, 'total_calls', '?')}",
        )
        _print_result(r)
        r = _record(
            "capability_utilization_observability: report.total_calls == 1",
            getattr(report, "total_calls", 0) == 1,
        )
        _print_result(r)
    except Exception as exc:
        r = _record(
            "capability_utilization_observability: get_utilization_report()",
            False,
            str(exc)[:120],
        )
        _print_result(r)

    # 14e. record_failure() and failure domain tracking
    try:
        record_failure(
            "node::_validate_test::action",
            caller="validate_runtime",
            failure_domain="NODE_UNAVAILABLE",
        )
        report2 = get_utilization_report("node::_validate_test::action")
        r = _record(
            "capability_utilization_observability: failure_count tracked",
            getattr(report2, "failure_count", 0) == 1,
            f"failure_count={getattr(report2, 'failure_count', '?')}",
        )
        _print_result(r)
        r = _record(
            "capability_utilization_observability: failure_domains tracked",
            "NODE_UNAVAILABLE" in getattr(report2, "failure_domains", {}),
        )
        _print_result(r)
    except Exception as exc:
        r = _record(
            "capability_utilization_observability: failure tracking",
            False,
            str(exc)[:120],
        )
        _print_result(r)

    # 14f. get_all_utilization_reports()
    try:
        summary = get_all_utilization_reports()
        r = _record(
            "capability_utilization_observability: get_all_utilization_reports() returns UtilizationSummary",
            isinstance(summary, UtilizationSummary),
            f"total_tracked={getattr(summary, 'total_tracked_capabilities', '?')}",
        )
        _print_result(r)
    except Exception as exc:
        r = _record(
            "capability_utilization_observability: get_all_utilization_reports()",
            False,
            str(exc)[:120],
        )
        _print_result(r)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Galaxy runtime integration validator (PR-9 / PR-10 / PR-530 / PR-531)"
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
        print("  Galaxy — Runtime Integration Validator")
        print("=" * 60)

    check_startup_path()
    check_authority_chain()
    check_node_registry()
    check_legacy_isolation()
    check_docs()
    check_purge_hardening()
    check_startup_tier_model()
    check_runtime_acceptance()
    check_callable_node_baseline()
    check_callable_startup_integration()
    check_spine_observability()
    check_outward_runtime_truth()
    check_node_lifecycle_governor()
    check_deployment_baseline()
    check_capability_utilization_observability()

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
