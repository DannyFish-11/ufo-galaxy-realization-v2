#!/usr/bin/env python3
"""
audit/reconciliation_probe.py
==============================
Deep Dual-Repository Architecture-Reconciliation Probe

Purpose
-------
This probe validates the concrete findings from DEEP_RECONCILIATION_AUDIT_2026.md
by examining real code in both repositories:

1. Confirms V4 spine (evaluate_orchestration_request) is NOT called from the
   primary hot path (openclawd.py, command_router.py).
2. Confirms V3 dispatch-slot authority (get_canonical_dispatch_slots) is NOT
   called from CommandRouter.
3. Identifies where evaluate_orchestration_request IS called (expected: only
   goal_execution.py handler + tests).
4. Confirms Android governance uplinks have no center bridge handlers.
5. Confirms hybrid_execute is declared but Android degrades it.
6. Confirms V2/V5 completion truth IS in the hot path.
7. Confirms CommandRouter's hard gate list (ACL, capability-mismatch, HITL).
8. Summarizes the integration gaps with concrete remediation paths.

Usage
-----
    python audit/reconciliation_probe.py

Run from the repository root. Reports findings to stdout and returns exit
code 0 if the audit baseline is consistent with expectations, or 1 if an
unexpected structural change is detected (e.g., a gap was silently closed
without this probe being updated).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _grep(path: Path, pattern: str, *, binary: bool = False) -> List[Tuple[int, str]]:
    """Return (lineno, line) pairs matching *pattern* in *path*."""
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rx = re.compile(pattern)
    matches: List[Tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        if rx.search(line):
            matches.append((i, line.rstrip()))
    return matches


def _grep_dir(
    directory: Path,
    pattern: str,
    *,
    extension: str = ".py",
    exclude_tests: bool = False,
    exclude_self: bool = True,
) -> Dict[str, List[Tuple[int, str]]]:
    """Grep *pattern* across all files with *extension* under *directory*."""
    results: Dict[str, List[Tuple[int, str]]] = {}
    for fpath in sorted(directory.rglob(f"*{extension}")):
        if exclude_tests and ("/tests/" in str(fpath) or "/test_" in fpath.name):
            continue
        if exclude_self and fpath.name == "reconciliation_probe.py":
            continue
        hits = _grep(fpath, pattern)
        if hits:
            rel = str(fpath.relative_to(REPO_ROOT))
            results[rel] = hits
    return results


def _print_section(title: str) -> None:
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def _print_ok(msg: str) -> None:
    print(f"  [OK]  {msg}")


def _print_gap(msg: str) -> None:
    print(f"  [GAP] {msg}")


def _print_info(msg: str) -> None:
    print(f"  [--]  {msg}")


def _print_finding(msg: str) -> None:
    print(f"  [!!]  {msg}")


# ---------------------------------------------------------------------------
# Probe 1: V4 spine NOT in primary hot path
# ---------------------------------------------------------------------------

def probe_v4_spine_hot_path() -> bool:
    """Return True if V4 spine is wired into the hot path (gap closed); False if gap is open.

    The desired end-state is that evaluate_orchestration_request() is called
    from command_router.py or openclawd.py. Currently it is not — this is the
    open gap. The probe returns False (gap open) until that wiring is added.
    """
    _print_section("PROBE 1: V4 Spine — hot-path wiring check")

    wired = False

    for fname in ("core/openclawd.py", "core/command_router.py"):
        fpath = REPO_ROOT / fname
        hits = _grep(fpath, r"evaluate_orchestration_request|unified_orchestration_spine")
        if hits:
            _print_ok(f"{fname}: CALLS V4 spine (gap closed for this file):")
            for lineno, line in hits[:5]:
                print(f"      line {lineno}: {line.strip()}")
            wired = True
        else:
            _print_gap(f"{fname}: does NOT call evaluate_orchestration_request (gap is OPEN)")

    # Where IS it called (excluding tests)?
    callers = _grep_dir(REPO_ROOT, r"evaluate_orchestration_request", exclude_tests=True)
    callers.pop("core/unified_orchestration_spine.py", None)
    callers.pop("core/center_authority_boundary.py", None)
    callers.pop("audit/reconciliation_probe.py", None)
    # Exclude other audit/probe files
    for k in list(callers.keys()):
        if k.startswith("audit/"):
            del callers[k]

    if callers:
        _print_info("V4 spine IS called from these non-test, non-audit files:")
        for fname, hits in callers.items():
            for lineno, line in hits[:2]:
                print(f"      {fname}:{lineno}: {line.strip()}")
    else:
        _print_gap("V4 spine called from NO hot-path code (only goal_execution.py handler + tests)")

    return wired


# ---------------------------------------------------------------------------
# Probe 2: V3 slot authority NOT in CommandRouter
# ---------------------------------------------------------------------------

def probe_v3_slot_authority_hot_path() -> bool:
    """Return True if V3 slot authority is wired into CommandRouter (gap closed); False if open.

    The desired end-state is that CommandRouter.route_envelope() calls
    get_canonical_dispatch_slots(). Currently it does not — gap is open.
    """
    _print_section("PROBE 2: V3 Dispatch-Slot Authority — CommandRouter wiring check")

    fpath = REPO_ROOT / "core/command_router.py"
    hits = _grep(fpath, r"get_canonical_dispatch_slots|canonical_dispatch_slot_authority")
    if hits:
        _print_ok("command_router.py CALLS V3 slot authority (gap closed):")
        for lineno, line in hits[:5]:
            print(f"      line {lineno}: {line.strip()}")
        wired = True
    else:
        _print_gap("command_router.py does NOT call get_canonical_dispatch_slots (gap is OPEN)")
        wired = False

    # Where IS V3 consumed (excluding tests)?
    callers = _grep_dir(
        REPO_ROOT, r"get_canonical_dispatch_slots|from core\.canonical_dispatch_slot_authority",
        exclude_tests=True,
    )
    callers.pop("core/canonical_dispatch_slot_authority.py", None)
    callers.pop("core/unified_orchestration_spine.py", None)
    callers.pop("core/center_authority_boundary.py", None)
    for k in list(callers.keys()):
        if k.startswith("audit/"):
            del callers[k]

    if callers:
        _print_info("V3 slot authority IS consumed from (beyond V4 spine):")
        for fname, hits in callers.items():
            for lineno, line in hits[:2]:
                print(f"      {fname}:{lineno}: {line.strip()}")
    else:
        _print_gap("V3 slot authority consumed only by V4 spine and tests — not by dispatch hot path")

    return wired


# ---------------------------------------------------------------------------
# Probe 3: Android governance uplinks — center handler check
# ---------------------------------------------------------------------------

def probe_android_governance_uplinks() -> bool:
    """Check whether center bridge has handlers for Android governance uplinks."""
    _print_section("PROBE 3: Android Governance Uplinks — center handler check")

    uplink_types = [
        "device_governance_report",
        "device_acceptance_report",
        "device_strategy_report",
    ]

    # Look for handler registrations in the bridge
    bridge_files = list((REPO_ROOT / "galaxy_gateway").rglob("*.py"))
    handler_presence: Dict[str, bool] = {ut: False for ut in uplink_types}

    for fpath in bridge_files:
        for ut in uplink_types:
            hits = _grep(fpath, re.escape(ut))
            if hits:
                handler_presence[ut] = True

    ok = True
    for ut, found in handler_presence.items():
        if found:
            _print_ok(f"{ut}: handler found in galaxy_gateway")
        else:
            _print_gap(f"{ut}: NO handler in galaxy_gateway (governance uplink is dead on center side)")
            ok = False

    return ok


# ---------------------------------------------------------------------------
# Probe 4: hybrid_execute dead path
# ---------------------------------------------------------------------------

def probe_hybrid_execute() -> bool:
    """Return True if hybrid_execute is retired (no protocol declaration + degrade only).
    Return False if the dead path is still present in both sides of the protocol.
    """
    _print_section("PROBE 4: hybrid_execute — dead path confirmation")

    # Check whether it's still declared in the AIP v3 protocol
    aip_decl = _grep(REPO_ROOT / "galaxy_gateway/protocol/aip_v3.py", r"HYBRID_EXECUTE|hybrid_execute")
    android_bridge_degrade = _grep_dir(
        REPO_ROOT / "galaxy_gateway", r"hybrid.*degrade|degrade.*hybrid|HybridDegrade",
    )

    if aip_decl:
        _print_gap(f"hybrid_execute still declared in AIP v3 protocol (dead path not retired):")
        for lineno, line in aip_decl[:3]:
            print(f"      line {lineno}: {line.strip()}")
        return False

    if android_bridge_degrade:
        _print_gap("hybrid_execute degrade handler still present (path not retired):")
        for fname, hits in list(android_bridge_degrade.items())[:2]:
            for lineno, line in hits[:1]:
                print(f"      {fname}:{lineno}: {line.strip()}")
        return False

    _print_ok("hybrid_execute not found in AIP v3 protocol declaration (dead path retired)")
    return True


# ---------------------------------------------------------------------------
# Probe 5: V2 completion truth IS in hot path
# ---------------------------------------------------------------------------

def probe_v2_completion_hot_path() -> bool:
    """Return True if V2 completion truth modules are called from bridge handlers."""
    _print_section("PROBE 5: V2 Completion Truth — hot-path wiring check")

    ok = True
    expected_callers = [
        ("canonical_completion_ingress", "galaxy_gateway"),
        ("task_result_canonical_truth_chain", "galaxy_gateway"),
    ]

    for module, search_dir in expected_callers:
        search_path = REPO_ROOT / search_dir
        hits = _grep_dir(search_path, module, exclude_tests=True)
        hits = {k: v for k, v in hits.items() if module not in k}
        if hits:
            _print_ok(f"{module} IS referenced from {search_dir}:")
            for fname in list(hits.keys())[:2]:
                print(f"      {fname}")
        else:
            _print_gap(f"{module} NOT found in {search_dir} (may indicate broken wiring)")
            ok = False

    return ok


# ---------------------------------------------------------------------------
# Probe 6: CommandRouter hard gates
# ---------------------------------------------------------------------------

def probe_command_router_hard_gates() -> bool:
    """Confirm CommandRouter has its three hard gates."""
    _print_section("PROBE 6: CommandRouter Hard Gates — ACL, capability-mismatch, HITL")

    fpath = REPO_ROOT / "core/command_router.py"
    gates = {
        "ACL gate": r"get_acl_enforcer|acl_enforcer|acl\.check",
        "Capability-mismatch gate": r"CAPABILITY_MISMATCH",
        "HITL gate": r"_is_high_risk_command|HITL|hitl",
    }

    ok = True
    for gate_name, pattern in gates.items():
        hits = _grep(fpath, pattern)
        if hits:
            _print_ok(f"{gate_name}: present (first match at line {hits[0][0]})")
        else:
            _print_gap(f"{gate_name}: NOT found in command_router.py")
            ok = False

    return ok


# ---------------------------------------------------------------------------
# Probe 7: Startup pre-flight softness
# ---------------------------------------------------------------------------

def probe_startup_preflight() -> bool:
    """Confirm startup pre-flight exception handling returns True (soft)."""
    _print_section("PROBE 7: Startup Pre-Flight Softness")

    fpath = REPO_ROOT / "main.py"
    ok = True
    # Look for the soft-proceed pattern: a bare 'return True' in the preflight function
    soft_hits = _grep(fpath, r"return True")
    if soft_hits:
        for lineno, line in soft_hits[:3]:
            _print_info(f"main.py line {lineno}: {line.strip()}")
        _print_gap("Startup pre-flight exception handler returns True (soft proceed) — confirmed")
    else:
        _print_ok("main.py: no unconditional 'return True' found (pre-flight may have been hardened)")

    # Check if center_authority_boundary is called from startup
    startup_files = ["main.py", "core/system_orchestrator.py"]
    for sfile in startup_files:
        ab_hits = _grep(REPO_ROOT / sfile, r"center_authority_boundary|assert_center_authority_intact")
        if ab_hits:
            _print_ok(f"{sfile}: calls center_authority_boundary (V6 assertion present at startup)")
        else:
            _print_gap(f"{sfile}: does NOT call center_authority_boundary (V6 not in startup chain)")

    return ok


# ---------------------------------------------------------------------------
# Probe 8: V1 continuity gate — separate from CommandRouter Gate A
# ---------------------------------------------------------------------------

def probe_v1_continuity_overlap() -> bool:
    """Return True if CommandRouter uses V1 unified continuity gate (gap closed); False if separate."""
    _print_section("PROBE 8: V1 Continuity Gate vs CommandRouter Gate A")

    fpath = REPO_ROOT / "core/command_router.py"
    v1_hits = _grep(fpath, r"unified_continuity_legality|continuity_legality_authority")
    gate_a_hits = _grep(fpath, r"check_source_execution_eligibility|source_runtime_posture")

    if v1_hits:
        _print_ok("CommandRouter imports/uses unified_continuity_legality_authority (V1 unified — gap closed)")
        return True
    else:
        _print_gap("CommandRouter does NOT use V1 unified_continuity_legality_authority (gap OPEN)")
        _print_info("CommandRouter has its own independent posture check (Gate A):")
        for lineno, line in gate_a_hits[:3]:
            print(f"      line {lineno}: {line.strip()}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║   Deep Dual-Repo Architecture-Reconciliation Probe                  ║")
    print("║   DannyFish-11/ufo-galaxy-realization-v2 — 2026-04-30               ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")

    results: Dict[str, bool] = {}

    # Run all probes
    results["v4_spine_hot_path"] = probe_v4_spine_hot_path()
    results["v3_slot_hot_path"] = probe_v3_slot_authority_hot_path()
    results["governance_uplinks"] = probe_android_governance_uplinks()
    results["hybrid_execute"] = probe_hybrid_execute()
    results["v2_completion_hot_path"] = probe_v2_completion_hot_path()
    results["command_router_gates"] = probe_command_router_hard_gates()
    results["startup_preflight"] = probe_startup_preflight()
    results["v1_continuity_overlap"] = probe_v1_continuity_overlap()

    # Summary
    _print_section("RECONCILIATION SUMMARY")

    # Probes that return True = GAP IS CLOSED (working correctly)
    # Probes that return False = GAP IS OPEN (action required)
    integration_status = {
        "V3 slot authority wired into CommandRouter.route_envelope()": results["v3_slot_hot_path"],
        "V4 spine wired into OpenClawd/CommandRouter hot path": results["v4_spine_hot_path"],
        "Android governance uplinks have center bridge handlers": results["governance_uplinks"],
        "hybrid_execute dead path retired": results["hybrid_execute"],
        "V1 continuity gate unified with CommandRouter Gate A": results["v1_continuity_overlap"],
    }

    working_correctly = {
        "CommandRouter hard gates present (ACL, capability-mismatch, HITL)": results["command_router_gates"],
        "V2 completion truth in bridge hot path": results["v2_completion_hot_path"],
    }

    print()
    print("  Already working / no reconciliation action needed:")
    for desc, ok in working_correctly.items():
        status = "✓" if ok else "✗ (UNEXPECTED REGRESSION)"
        print(f"    [{status}] {desc}")

    print()
    print("  Integration gap status (action required if OPEN):")
    open_gaps = []
    for desc, closed in integration_status.items():
        status = "CLOSED" if closed else "OPEN"
        mark = "✓" if closed else "!!"
        print(f"    [{mark}] {desc} — {status}")
        if not closed:
            open_gaps.append(desc)

    print()
    if open_gaps:
        print(f"  Result: {len(open_gaps)} integration gap(s) remain open.")
        print("  See DEEP_RECONCILIATION_AUDIT_2026.md Part 7 for remediation actions.")
        return 1
    else:
        print("  Result: All probed integration gaps have been closed.")
        print("  Architecture is reconciled per DEEP_RECONCILIATION_AUDIT_2026.md.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
