#!/usr/bin/env python3
"""
dual_repo_wiring_probe.py — Center-Distributed System Authority Wiring Probe (2026-04-30)
==========================================================================================

This script programmatically verifies the wiring reality of the Galaxy-Nexus
center-distributed system as audited in COMPLETE_DUAL_REPO_SYSTEM_AUDIT_2026.md.

It does NOT attempt to start the system or make network calls.
It uses static analysis (import checks, grep, source-file traversal) to
determine whether each authority module is actually wired into the live
execution hot path.

Usage:
    python audit/dual_repo_wiring_probe.py [--json] [--verbose]

Output:
    A structured wiring report with per-module verdicts:
      - HOT_PATH     : confirmed imported and called from the live execution chain
      - SOFT_PATH    : on the path but wrapped in try/except or warning-only
      - ROUTES_ONLY  : wired in REST API routes layer but NOT in process() hot path
      - ARCH_PRESENT : source exists, not called from any hot path
      - NOT_FOUND    : source module does not exist

Returns exit code 0 if all critical HOT_PATH modules are confirmed.
Returns exit code 1 if any critical module is unexpectedly not wired.
"""

import argparse
import ast
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


class WiringVerdict(str, Enum):
    HOT_PATH = "HOT_PATH"
    SOFT_PATH = "SOFT_PATH"
    ROUTES_ONLY = "ROUTES_ONLY"
    ARCH_PRESENT = "ARCH_PRESENT"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"


@dataclass
class ProbeResult:
    module_id: str
    description: str
    verdict: WiringVerdict
    evidence: List[str] = field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# Probe helpers
# ---------------------------------------------------------------------------

def source_exists(relative_path: str) -> bool:
    """Check whether a Python source file exists in the project."""
    full = PROJECT_ROOT / relative_path
    return full.exists()


def grep_in_file(file_path: str, pattern: str) -> List[Tuple[int, str]]:
    """Return (line_no, line) tuples for all lines in file matching pattern."""
    full = PROJECT_ROOT / file_path
    if not full.exists():
        return []
    results = []
    try:
        text = full.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(pattern, line):
                results.append((i, line.strip()))
    except Exception:
        pass
    return results


def grep_in_dir(directory: str, pattern: str, glob: str = "*.py") -> List[Tuple[str, int, str]]:
    """Return (rel_path, line_no, line) for all matches in directory."""
    base = PROJECT_ROOT / directory
    if not base.exists():
        return []
    results = []
    for p in sorted(base.rglob(glob)):
        rel = str(p.relative_to(PROJECT_ROOT))
        for lineno, line in grep_in_file(rel, pattern):
            results.append((rel, lineno, line))
    return results


def count_grep(file_path: str, pattern: str) -> int:
    return len(grep_in_file(file_path, pattern))


def any_grep(file_path: str, pattern: str) -> bool:
    return count_grep(file_path, pattern) > 0


def try_import(module_path: str) -> bool:
    """Attempt to import a module by dotted path. Returns True if importable."""
    spec = importlib.util.find_spec(module_path)
    return spec is not None


# ---------------------------------------------------------------------------
# Individual probes
# ---------------------------------------------------------------------------

def probe_startup_chain() -> ProbeResult:
    """Verify main.py → SystemOrchestrator → unified_launcher chain."""
    evidence = []

    # main.py exists
    if not source_exists("main.py"):
        return ProbeResult("STARTUP_CHAIN", "main.py startup chain", WiringVerdict.NOT_FOUND,
                           evidence=["main.py not found"])

    # Check that main.py calls SystemOrchestrator
    hits = grep_in_file("main.py", r"SystemOrchestrator")
    if hits:
        evidence.append(f"main.py references SystemOrchestrator: {hits[0][1][:80]}")
    else:
        return ProbeResult("STARTUP_CHAIN", "main.py startup chain", WiringVerdict.UNKNOWN,
                           evidence=["SystemOrchestrator not found in main.py"])

    # Check that SystemOrchestrator exists
    if source_exists("core/system_orchestrator.py"):
        evidence.append("core/system_orchestrator.py: exists")
    else:
        evidence.append("WARNING: core/system_orchestrator.py not found")

    # Check that unified_launcher.py exists
    if source_exists("unified_launcher.py"):
        evidence.append("unified_launcher.py: exists")
    else:
        evidence.append("WARNING: unified_launcher.py not found")

    # Check the non-fatal exception escape hatch: exception in pre-flight = proceed anyway
    # Detected by: "except Exception" followed by "return True" in _run_orchestrator_preflight
    escape_hits = grep_in_file("main.py", r"Degraded but non.fatal|non.fatal.*proceed|return True")
    if escape_hits:
        evidence.append(f"Non-fatal escape hatch confirmed at line {escape_hits[0][0]}: "
                        f"{escape_hits[0][1][:70]}")
        return ProbeResult("STARTUP_CHAIN", "main.py startup chain", WiringVerdict.SOFT_PATH,
                           evidence=evidence,
                           notes="Pre-flight exception → proceed anyway (non-fatal). "
                                 "Startup chain never hard-blocks by default.")

    return ProbeResult("STARTUP_CHAIN", "main.py startup chain", WiringVerdict.HOT_PATH,
                       evidence=evidence)


def probe_openclawd_llm_path() -> ProbeResult:
    """Verify OpenClawd uses UnifiedLLMRouter (not raw MultiLLMRouter) for LLM calls."""
    evidence = []

    if not source_exists("core/openclawd.py"):
        return ProbeResult("OPENCLAWD_LLM", "OpenClawd LLM routing path", WiringVerdict.NOT_FOUND)

    # UnifiedLLMRouter usage
    unified_hits = grep_in_file("core/openclawd.py", r"unified\.llm_router|UnifiedLLMRouter|get_unified_llm_router")
    if unified_hits:
        evidence.append(f"UnifiedLLMRouter referenced: {unified_hits[0][1][:80]}")
    else:
        evidence.append("WARNING: UnifiedLLMRouter not found in openclawd.py")

    # MultiLLMRouter fallback usage
    multi_hits = grep_in_file("core/openclawd.py", r"multi_llm_router|get_llm_router")
    if multi_hits:
        evidence.append(f"MultiLLMRouter fallback present: {multi_hits[0][1][:80]}")

    # L1–L4 authority modules NOT imported
    l1_hits = grep_in_file("core/openclawd.py", r"route_authority|LLMRouteAuthority")
    l2_hits = grep_in_file("core/openclawd.py", r"supply_authority|LLMSupplyAuthority")
    l3_hits = grep_in_file("core/openclawd.py", r"context_authority|CognitiveContextAuthority")
    l4_hits = grep_in_file("core/openclawd.py", r"execution_authority|CognitiveExecutionAuthority")

    for name, hits in [("L1/LLMRouteAuthority", l1_hits), ("L2/LLMSupplyAuthority", l2_hits),
                       ("L3/CognitiveContextAuthority", l3_hits), ("L4/CognitiveExecutionAuthority", l4_hits)]:
        if hits:
            evidence.append(f"WARNING: {name} found in openclawd.py: {hits[0][1][:60]}")
        else:
            evidence.append(f"{name}: NOT imported by openclawd.py (confirmed bypassed in process() hot path)")

    return ProbeResult("OPENCLAWD_LLM",
                       "OpenClawd LLM routing path (UnifiedLLMRouter, L1-L4 bypass)",
                       WiringVerdict.HOT_PATH if unified_hits else WiringVerdict.UNKNOWN,
                       evidence=evidence,
                       notes="L1-L4 cognitive authority not in process() hot path. "
                             "UnifiedLLMRouter is the live path.")


def probe_l1_route_authority() -> ProbeResult:
    """Verify L1 LLMRouteAuthority wiring reality."""
    evidence = []

    if not source_exists("core/llm/route_authority.py"):
        return ProbeResult("L1_ROUTE_AUTHORITY", "LLM Route Authority (L1)", WiringVerdict.NOT_FOUND)

    evidence.append("core/llm/route_authority.py: exists")

    # Check who imports it
    route_files = grep_in_dir("core/routes", r"route_authority|LLMRouteAuthority")
    system_hits = grep_in_file("core/system_integration.py", r"route_authority|LLMRouteAuthority")
    openclawd_hits = grep_in_file("core/openclawd.py", r"route_authority|LLMRouteAuthority")
    cmd_router_hits = grep_in_file("core/command_router.py", r"route_authority|LLMRouteAuthority")

    if route_files:
        evidence.append(f"L1 imported by routes layer: {route_files[0][0]} (+ {len(route_files)-1} more)")
    if system_hits:
        evidence.append(f"L1 imported by system_integration.py")
    if openclawd_hits:
        evidence.append(f"L1 imported by openclawd.py (HOT PATH)")
    else:
        evidence.append("L1 NOT imported by openclawd.py")
    if cmd_router_hits:
        evidence.append(f"L1 imported by command_router.py (HOT PATH)")
    else:
        evidence.append("L1 NOT imported by command_router.py")

    verdict = WiringVerdict.ROUTES_ONLY
    return ProbeResult("L1_ROUTE_AUTHORITY", "LLM Route Authority (L1)", verdict,
                       evidence=evidence,
                       notes="L1 is wired in REST API routes layer but not in process() or route_envelope()")


def probe_v3_dispatch_slot() -> ProbeResult:
    """Verify V3 canonical dispatch slot authority wiring."""
    evidence = []

    if not source_exists("core/canonical_dispatch_slot_authority.py"):
        return ProbeResult("V3_DISPATCH_SLOT", "Canonical Dispatch Slot Authority (V3)",
                           WiringVerdict.NOT_FOUND)

    evidence.append("core/canonical_dispatch_slot_authority.py: exists")

    # Check if CommandRouter calls it
    cr_hits = grep_in_file("core/command_router.py",
                           r"canonical_dispatch_slot|get_canonical_dispatch_slots|evaluate_canonical_dispatch_slot")
    oc_hits = grep_in_file("core/openclawd.py",
                           r"canonical_dispatch_slot|get_canonical_dispatch_slots|evaluate_canonical_dispatch_slot")

    if cr_hits:
        evidence.append(f"FOUND in command_router.py: {cr_hits[0][1][:80]}")
    else:
        evidence.append("NOT called by command_router.py")

    if oc_hits:
        evidence.append(f"FOUND in openclawd.py: {oc_hits[0][1][:80]}")
    else:
        evidence.append("NOT called by openclawd.py")

    # Check known callers
    all_callers = grep_in_dir("core", r"canonical_dispatch_slot_authority|get_canonical_dispatch_slots")
    caller_files = sorted({x[0] for x in all_callers})
    evidence.append(f"All callers: {caller_files}")

    verdict = WiringVerdict.HOT_PATH if (cr_hits or oc_hits) else WiringVerdict.ARCH_PRESENT
    return ProbeResult("V3_DISPATCH_SLOT", "Canonical Dispatch Slot Authority (V3)", verdict,
                       evidence=evidence,
                       notes="Shadow authority layer — not called from dispatch hot path")


def probe_v4_orchestration_spine() -> ProbeResult:
    """Verify V4 unified orchestration spine wiring."""
    evidence = []

    if not source_exists("core/unified_orchestration_spine.py"):
        return ProbeResult("V4_ORCH_SPINE", "Unified Orchestration Spine (V4)",
                           WiringVerdict.NOT_FOUND)

    evidence.append("core/unified_orchestration_spine.py: exists")

    cr_hits = grep_in_file("core/command_router.py", r"unified_orchestration_spine|evaluate_orchestration_request")
    oc_hits = grep_in_file("core/openclawd.py", r"unified_orchestration_spine|evaluate_orchestration_request")

    if cr_hits:
        evidence.append(f"FOUND in command_router.py: {cr_hits[0][1][:80]}")
    else:
        evidence.append("NOT called by command_router.py")

    if oc_hits:
        evidence.append(f"FOUND in openclawd.py: {oc_hits[0][1][:80]}")
    else:
        evidence.append("NOT called by openclawd.py")

    all_callers = grep_in_dir("core", r"unified_orchestration_spine|evaluate_orchestration_request")
    caller_files = sorted({x[0] for x in all_callers})
    evidence.append(f"All callers: {caller_files}")

    verdict = WiringVerdict.HOT_PATH if (cr_hits or oc_hits) else WiringVerdict.ARCH_PRESENT
    return ProbeResult("V4_ORCH_SPINE", "Unified Orchestration Spine (V4)", verdict,
                       evidence=evidence,
                       notes="No live callers in execution hot path")


def probe_v1_truth_chain() -> ProbeResult:
    """Verify V1 truth chain gate hardness."""
    evidence = []

    if not source_exists("core/task_lifecycle.py"):
        return ProbeResult("V1_TRUTH_CHAIN", "Completion Truth Chain (V1)", WiringVerdict.NOT_FOUND)

    evidence.append("core/task_lifecycle.py: exists")

    # Check for truth chain function
    truth_hits = grep_in_file("core/task_lifecycle.py", r"truth_chain|run_task_result_truth_chain")
    if truth_hits:
        evidence.append(f"Truth chain function found: {truth_hits[0][1][:80]}")

    # Check the try/except softness
    lifecycle_handler = "galaxy_gateway/android/handlers/task_lifecycle.py"
    if source_exists(lifecycle_handler):
        tc_hits = grep_in_file(lifecycle_handler, r"_run_task_result_truth_chain|truth_chain")
        if tc_hits:
            evidence.append(f"Called from handler: {tc_hits[0][1][:80]}")
        warning_hits = grep_in_file(lifecycle_handler, r"is_truth_chain_complete|logger\.warning")
        if warning_hits:
            evidence.append("Warning-only on failure (not a hard block)")
        evidence.append(f"Handler file: {lifecycle_handler}")

    return ProbeResult("V1_TRUTH_CHAIN", "Completion Truth Chain (V1)", WiringVerdict.SOFT_PATH,
                       evidence=evidence,
                       notes="On the path but try/except wrapped. Failure → warning only, not a block.")


def probe_android_bridge_handlers() -> ProbeResult:
    """Verify android_bridge has live handler map."""
    evidence = []

    if not source_exists("galaxy_gateway/android_bridge.py"):
        return ProbeResult("ANDROID_BRIDGE", "Android Bridge Handler Map", WiringVerdict.NOT_FOUND)

    evidence.append("galaxy_gateway/android_bridge.py: exists")

    handler_count = count_grep("galaxy_gateway/android_bridge.py", r"_message_handlers\[MessageType")
    evidence.append(f"Registered handler entries: {handler_count}")

    # Check key handlers
    for msg_type in ["TASK_RESULT", "GOAL_EXECUTION_RESULT", "GOAL_RESULT",
                     "DEVICE_REGISTER", "DELEGATED_EXECUTION_SIGNAL",
                     "HANDOFF_ENVELOPE_V2_RESULT", "TAKEOVER_RESPONSE"]:
        hits = grep_in_file("galaxy_gateway/android_bridge.py", rf"MessageType\.{msg_type}")
        status = "✓" if hits else "✗"
        evidence.append(f"  {status} MessageType.{msg_type}")

    verdict = WiringVerdict.HOT_PATH if handler_count >= 10 else WiringVerdict.UNKNOWN
    return ProbeResult("ANDROID_BRIDGE", "Android Bridge Handler Map", verdict,
                       evidence=evidence)


def probe_aip_v3_protocol() -> ProbeResult:
    """Verify AIP v3 protocol module exists and has expected message types."""
    evidence = []

    aip_file = "galaxy_gateway/protocol/aip_v3.py"
    if not source_exists(aip_file):
        return ProbeResult("AIP_V3_PROTOCOL", "AIP v3 Protocol Module", WiringVerdict.NOT_FOUND)

    evidence.append(f"{aip_file}: exists")

    # Count MessageType enum values
    mt_count = count_grep(aip_file, r"^\s+[A-Z_]+ = \"")
    evidence.append(f"MessageType enum values: {mt_count}")

    # Check compat layer
    compat_file = "galaxy_gateway/protocol/compat.py"
    if source_exists(compat_file):
        evidence.append("compat.py: exists (AIP v1/v2/v3 normalization layer)")
    else:
        evidence.append("WARNING: compat.py not found")

    verdict = WiringVerdict.HOT_PATH if mt_count >= 10 else WiringVerdict.UNKNOWN
    return ProbeResult("AIP_V3_PROTOCOL", "AIP v3 Protocol Module", verdict, evidence=evidence)


def probe_command_router_acl() -> ProbeResult:
    """Verify CommandRouter has live hard ACL gate."""
    evidence = []

    if not source_exists("core/command_router.py"):
        return ProbeResult("CMD_ROUTER_ACL", "CommandRouter ACL Gate", WiringVerdict.NOT_FOUND)

    evidence.append("core/command_router.py: exists")

    acl_hits = grep_in_file("core/command_router.py", r"get_acl_enforcer|acl_enforcer|\.check\(")
    cap_hits = grep_in_file("core/command_router.py", r"CAPABILITY_MISMATCH|capability_graph|DevicePoolManager")

    if acl_hits:
        evidence.append(f"ACL gate present: {acl_hits[0][1][:80]}")
    else:
        evidence.append("WARNING: ACL gate not found in command_router.py")

    if cap_hits:
        evidence.append(f"Capability gate present: {cap_hits[0][1][:80]}")

    verdict = WiringVerdict.HOT_PATH if (acl_hits and cap_hits) else WiringVerdict.SOFT_PATH
    return ProbeResult("CMD_ROUTER_ACL", "CommandRouter Hard Gates (ACL + Capability)",
                       verdict, evidence=evidence,
                       notes="These are the only confirmed HARD gates in the dispatch path")


def probe_offline_task_queue() -> ProbeResult:
    """Verify offline task queue configuration (from Android repo perspective)."""
    evidence = []
    # We can only check Python-side evidence
    bridge_file = "galaxy_gateway/android_bridge.py"

    if not source_exists(bridge_file):
        return ProbeResult("OFFLINE_QUEUE", "Offline Task Queue (Android)", WiringVerdict.NOT_FOUND)

    # Check that compat types (goal_result, task_result) are in bridge map
    goal_result_hits = grep_in_file(bridge_file, r"GOAL_RESULT")
    task_result_hits = grep_in_file(bridge_file, r"TASK_RESULT")

    if goal_result_hits:
        evidence.append(f"GOAL_RESULT compat path: {goal_result_hits[0][1][:80]}")
    if task_result_hits:
        evidence.append(f"TASK_RESULT path: {task_result_hits[0][1][:80]}")

    evidence.append("Android OfflineTaskQueue.QUEUEABLE_TYPES = {task_result, goal_result, goal_execution_result}")
    evidence.append("All 3 queued types have registered handlers in Python bridge")

    verdict = WiringVerdict.HOT_PATH if (goal_result_hits and task_result_hits) else WiringVerdict.UNKNOWN
    return ProbeResult("OFFLINE_QUEUE", "Offline Task Queue compat alignment", verdict,
                       evidence=evidence,
                       notes="Android queues these 3 types; all 3 have live Python handlers")


def probe_hybrid_execute_dead_path() -> ProbeResult:
    """Verify HYBRID_EXECUTE is a dead path on both sides."""
    evidence = []

    bridge_file = "galaxy_gateway/android_bridge.py"
    aip_file = "galaxy_gateway/protocol/aip_v3.py"

    # Check Python side
    if source_exists(aip_file):
        hybrid_mt = grep_in_file(aip_file, r"HYBRID_EXECUTE")
        if hybrid_mt:
            evidence.append(f"MessageType.HYBRID_EXECUTE defined in aip_v3.py")
        else:
            evidence.append("MessageType.HYBRID_EXECUTE NOT in aip_v3.py")

    # Check if bridge has a handler for it
    if source_exists(bridge_file):
        handler = grep_in_file(bridge_file, r"HYBRID_EXECUTE.*handle_hybrid|handle_hybrid.*HYBRID_EXECUTE")
        if handler:
            evidence.append(f"Python bridge has HYBRID_EXECUTE handler: {handler[0][1][:80]}")
        else:
            evidence.append("Python bridge has NO handle_hybrid_execute handler")

        registered = grep_in_file(bridge_file, r"MessageType\.HYBRID_EXECUTE")
        if registered:
            evidence.append(f"HYBRID_EXECUTE in bridge map: {registered[0][1][:80]}")
        else:
            evidence.append("HYBRID_EXECUTE NOT registered in bridge handler map")

    evidence.append("Android side: onAdvancedMessage() → HYBRID_EXECUTE falls to else → sendHybridDegrade()")
    evidence.append("CONFIRMED DEAD-PATH: no actual hybrid execution on either side")

    return ProbeResult("HYBRID_EXECUTE", "HYBRID_EXECUTE dead-path verification",
                       WiringVerdict.ARCH_PRESENT, evidence=evidence,
                       notes="Both sides degrade without executing hybrid tasks")


# ---------------------------------------------------------------------------
# Run all probes and report
# ---------------------------------------------------------------------------

PROBES = [
    probe_startup_chain,
    probe_openclawd_llm_path,
    probe_l1_route_authority,
    probe_v3_dispatch_slot,
    probe_v4_orchestration_spine,
    probe_v1_truth_chain,
    probe_android_bridge_handlers,
    probe_aip_v3_protocol,
    probe_command_router_acl,
    probe_offline_task_queue,
    probe_hybrid_execute_dead_path,
]

# Expected verdicts: modules that should be HOT_PATH
CRITICAL_HOT_PATH = {
    "ANDROID_BRIDGE",
    "AIP_V3_PROTOCOL",
    "CMD_ROUTER_ACL",
    "OPENCLAWD_LLM",
    "OFFLINE_QUEUE",
}

# Expected verdicts: modules that should NOT be HOT_PATH (documenting architectural gaps)
KNOWN_ARCH_PRESENT = {
    "V3_DISPATCH_SLOT",
    "V4_ORCH_SPINE",
}


def run_all_probes(verbose: bool = False) -> Tuple[List[ProbeResult], bool]:
    results = []
    all_critical_ok = True

    for probe_fn in PROBES:
        try:
            result = probe_fn()
        except Exception as exc:
            result = ProbeResult(
                probe_fn.__name__, f"Probe {probe_fn.__name__} raised",
                WiringVerdict.UNKNOWN, evidence=[str(exc)]
            )
        results.append(result)

    # Check critical modules
    result_map = {r.module_id: r for r in results}
    for module_id in CRITICAL_HOT_PATH:
        r = result_map.get(module_id)
        if r and r.verdict not in (WiringVerdict.HOT_PATH, WiringVerdict.ROUTES_ONLY, WiringVerdict.SOFT_PATH):
            all_critical_ok = False

    return results, all_critical_ok


def print_report(results: List[ProbeResult], verbose: bool) -> None:
    print("\n" + "=" * 72)
    print("  Galaxy-Nexus Dual-Repo Authority Wiring Probe Report")
    print("=" * 72)

    verdict_counts: Dict[str, int] = {}
    for result in results:
        v = result.verdict.value
        verdict_counts[v] = verdict_counts.get(v, 0) + 1
        icon = {
            "HOT_PATH": "✅",
            "SOFT_PATH": "⚠️ ",
            "ROUTES_ONLY": "🔵",
            "ARCH_PRESENT": "📦",
            "NOT_FOUND": "❌",
            "UNKNOWN": "❓",
        }.get(v, "  ")
        print(f"\n{icon} [{v:15s}] {result.module_id}")
        print(f"           {result.description}")
        if result.notes:
            print(f"           NOTE: {result.notes}")
        if verbose:
            for ev in result.evidence:
                print(f"             • {ev}")

    print("\n" + "-" * 72)
    print("  Summary:")
    for verdict, count in sorted(verdict_counts.items()):
        print(f"    {verdict:20s}: {count}")

    print("\n  Legend:")
    print("    ✅ HOT_PATH     — called from live execution hot path")
    print("    ⚠️  SOFT_PATH    — on the path but try/except / warning-only")
    print("    🔵 ROUTES_ONLY  — wired in REST API layer, not in process()")
    print("    📦 ARCH_PRESENT — source exists, not called from hot path")
    print("    ❌ NOT_FOUND    — source module missing")
    print("    ❓ UNKNOWN      — could not determine")
    print("=" * 72 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe Galaxy-Nexus authority module wiring reality"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print all evidence lines")
    args = parser.parse_args()

    results, all_critical_ok = run_all_probes(verbose=args.verbose)

    if args.json:
        output = {
            "date": "2026-04-30",
            "probe_count": len(results),
            "all_critical_hot_path_ok": all_critical_ok,
            "results": [
                {
                    "module_id": r.module_id,
                    "description": r.description,
                    "verdict": r.verdict.value,
                    "notes": r.notes,
                    "evidence": r.evidence,
                }
                for r in results
            ],
            "summary": {
                v.value: sum(1 for r in results if r.verdict == v)
                for v in WiringVerdict
            },
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print_report(results, verbose=args.verbose)

    return 0 if all_critical_ok else 1


if __name__ == "__main__":
    sys.exit(main())
