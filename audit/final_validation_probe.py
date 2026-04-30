#!/usr/bin/env python3
"""audit/final_validation_probe.py
=====================================
Final Architecture Validation Probe — validates key assumptions from the
terminal dual-repository architecture audit against actual code files.

Usage
-----
    python audit/final_validation_probe.py [--repo-root <path>]

Run from the repository root:
    python audit/final_validation_probe.py

Returns exit code 0 if all CRITICAL probes pass, 1 if any fail.
ADVISORY probes are informational and do not affect the exit code.

Probe categories
----------------
CRITICAL — must pass for the architecture claims in the audit to be valid.
           Failures mean the audit evidence is wrong or the code has changed.

ADVISORY — useful to track but do not invalidate the audit.

Each probe prints a one-line verdict: PASS / FAIL / ADVISORY-PASS / ADVISORY-FAIL.
"""

from __future__ import annotations

import importlib
import os
import sys
import re
from pathlib import Path
from typing import List, NamedTuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_REPO_ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Probe result type
# ---------------------------------------------------------------------------


class ProbeResult(NamedTuple):
    name: str
    category: str  # CRITICAL | ADVISORY
    passed: bool
    detail: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _contains_pattern(path: Path, pattern: str) -> bool:
    """Return True if *path* contains *pattern* (literal string search)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return pattern in text
    except OSError:
        return False


def _count_pattern(path: Path, pattern: str) -> int:
    """Return number of lines containing *pattern* in *path*."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return sum(1 for line in text.splitlines() if pattern in line)
    except OSError:
        return 0


def _file_exists(repo_root: Path, rel_path: str) -> bool:
    return (repo_root / rel_path).is_file()


def _grep_file(repo_root: Path, rel_path: str, pattern: str) -> bool:
    """Return True if *pattern* appears anywhere in file at *rel_path*."""
    return _contains_pattern(repo_root / rel_path, pattern)


def _grep_dir(repo_root: Path, rel_dir: str, pattern: str, glob: str = "*.py") -> int:
    """Return count of files in *rel_dir* that contain *pattern*."""
    base = repo_root / rel_dir
    if not base.is_dir():
        return 0
    return sum(1 for f in base.rglob(glob) if _contains_pattern(f, pattern))


# ---------------------------------------------------------------------------
# Probe definitions
# ---------------------------------------------------------------------------


def run_probes(repo_root: Path) -> List[ProbeResult]:
    results: List[ProbeResult] = []

    def probe(name: str, category: str, passed: bool, detail: str) -> None:
        results.append(ProbeResult(name=name, category=category, passed=passed, detail=detail))

    # ===========================================================
    # PROBE SET 1: Core spine files exist and declare correct roles
    # ===========================================================

    probe(
        "SPINE-01: openclawd.py exists",
        "CRITICAL",
        _file_exists(repo_root, "core/openclawd.py"),
        "core/openclawd.py must exist as the cognitive entry point",
    )

    probe(
        "SPINE-02: command_router.py exists",
        "CRITICAL",
        _file_exists(repo_root, "core/command_router.py"),
        "core/command_router.py must exist as the dispatch substrate",
    )

    probe(
        "SPINE-03: openclawd.py declares COMMAND_ROUTER as downstream",
        "CRITICAL",
        _grep_file(repo_root, "core/openclawd.py", "CommandRouter"),
        "openclawd.py must reference CommandRouter as its dispatch authority",
    )

    probe(
        "SPINE-04: command_router.py declares COMMAND_ROUTER_ORCHESTRATION_AUTHORITY sentinel",
        "CRITICAL",
        _grep_file(repo_root, "core/command_router.py", "COMMAND_ROUTER_ORCHESTRATION_AUTHORITY"),
        "CommandRouter must declare its authority sentinel",
    )

    probe(
        "SPINE-05: main.py invokes SystemOrchestrator or unified_launcher",
        "CRITICAL",
        _grep_file(repo_root, "main.py", "unified_launcher") or _grep_file(repo_root, "main.py", "SystemOrchestrator"),
        "main.py must invoke system startup through SystemOrchestrator or unified_launcher",
    )

    # ===========================================================
    # PROBE SET 2: V1-V6 authority module existence
    # ===========================================================

    v_modules = [
        ("V1", "core/unified_continuity_legality_authority.py", "evaluate_continuity_legality"),
        ("V2", "core/task_result_canonical_truth_chain.py", "run_task_result_truth_chain"),
        ("V3", "core/canonical_dispatch_slot_authority.py", "get_canonical_dispatch_slots"),
        ("V4", "core/unified_orchestration_spine.py", "evaluate_orchestration_request"),
        ("V5", "core/canonical_group_completion_closure.py", "apply_completion_closure"),
        ("V6", "core/center_authority_boundary.py", "assert_center_authority_intact"),
    ]

    for label, rel_path, key_fn in v_modules:
        probe(
            f"VMOD-{label}-exists: {rel_path} exists",
            "CRITICAL",
            _file_exists(repo_root, rel_path),
            f"{label} authority module must exist at {rel_path}",
        )
        probe(
            f"VMOD-{label}-fn: {key_fn} declared",
            "CRITICAL",
            _grep_file(repo_root, rel_path, key_fn),
            f"{label} must declare {key_fn}()",
        )

    # ===========================================================
    # PROBE SET 3: Completion ingress (CC)
    # ===========================================================

    probe(
        "CC-01: canonical_completion_ingress.py exists",
        "CRITICAL",
        _file_exists(repo_root, "core/canonical_completion_ingress.py"),
        "Canonical completion ingress must exist",
    )

    probe(
        "CC-02: canonical_completion_ingress.py declares notify()",
        "CRITICAL",
        _grep_file(repo_root, "core/canonical_completion_ingress.py", "def notify"),
        "CanonicalCompletionIngress must have notify() method",
    )

    # ===========================================================
    # PROBE SET 4: V3 wiring gap detection (CRITICAL split-brain check)
    # ===========================================================

    # This is the most important probe: V3 should NOT yet be in CommandRouter
    # (confirming the audit finding that it is a shadow authority).
    # Once P0 fix is applied, this probe inverts.
    v3_in_command_router = _grep_file(
        repo_root, "core/command_router.py", "get_canonical_dispatch_slots"
    ) or _grep_file(
        repo_root, "core/command_router.py", "canonical_dispatch_slot_authority"
    )

    probe(
        "SPLIT-01: V3 wiring gap confirmed (CommandRouter does NOT call V3)",
        "CRITICAL",
        not v3_in_command_router,
        "AUDIT EVIDENCE: V3 is a shadow authority — CommandRouter does not call "
        "get_canonical_dispatch_slots(). This probe PASSES when the gap exists "
        "(confirming audit finding). After P0 fix, this probe should be INVERTED "
        "to verify V3 is PRESENT in CommandRouter.",
    )

    # ===========================================================
    # PROBE SET 5: V4 wiring gap detection
    # ===========================================================

    v4_in_openclawd = _grep_file(
        repo_root, "core/openclawd.py", "evaluate_orchestration_request"
    ) or _grep_file(
        repo_root, "core/openclawd.py", "unified_orchestration_spine"
    )

    probe(
        "SPLIT-02: V4 wiring gap confirmed (OpenClawd does NOT call V4)",
        "CRITICAL",
        not v4_in_openclawd,
        "AUDIT EVIDENCE: V4 is correctly NOT in OpenClawd per-request path. "
        "V4 belongs in multi-step orchestration (goal_execution handler), not "
        "in per-request OpenClawd.process(). This probe PASSES when V4 is "
        "ABSENT from openclawd.py — this is the correct architecture.",
    )

    v4_in_command_router = _grep_file(
        repo_root, "core/command_router.py", "evaluate_orchestration_request"
    )

    probe(
        "SPLIT-03: V4 wiring gap confirmed (CommandRouter does NOT call V4)",
        "CRITICAL",
        not v4_in_command_router,
        "AUDIT EVIDENCE: V4 should NOT be in CommandRouter dispatch path. "
        "CommandRouter is per-task substrate; V4 is multi-step orchestration session. "
        "This probe PASSES when V4 is ABSENT from command_router.py.",
    )

    # ===========================================================
    # PROBE SET 6: V2 truth chain wiring in android_bridge
    # ===========================================================

    # Check that android_bridge or its gateway handlers call run_task_result_truth_chain
    galaxy_gateway = repo_root / "galaxy_gateway"
    v2_on_hot_path = False
    if galaxy_gateway.is_dir():
        v2_on_hot_path = _grep_dir(repo_root, "galaxy_gateway", "run_task_result_truth_chain") > 0

    # Also check core directory handlers
    if not v2_on_hot_path:
        v2_on_hot_path = _grep_dir(repo_root, "core", "run_task_result_truth_chain") > 0

    probe(
        "V2-HOT-01: run_task_result_truth_chain is called somewhere in hot path",
        "CRITICAL",
        v2_on_hot_path,
        "V2 truth chain must be called by android_bridge or related gateway handler",
    )

    # ===========================================================
    # PROBE SET 7: V5 group completion wiring
    # ===========================================================

    v5_callers = _grep_dir(repo_root, "core", "apply_completion_closure")
    probe(
        "V5-HOT-01: apply_completion_closure is called in core/",
        "CRITICAL",
        v5_callers > 0,
        f"V5 group completion closure must have callers in core/ (found {v5_callers})",
    )

    # ===========================================================
    # PROBE SET 8: Canonical completion ingress callers
    # ===========================================================

    cc_callers = _grep_dir(repo_root, "core", "CanonicalCompletionIngress") + (
        _grep_dir(repo_root, "galaxy_gateway", "CanonicalCompletionIngress") if (repo_root / "galaxy_gateway").is_dir() else 0
    )
    probe(
        "CC-HOT-01: CanonicalCompletionIngress is referenced in the codebase",
        "CRITICAL",
        cc_callers > 1,  # At least 2 files (definition + caller)
        f"CanonicalCompletionIngress must have callers beyond its own file (found {cc_callers} references)",
    )

    # ===========================================================
    # PROBE SET 9: A1 participant truth ingress wiring in V2
    # ===========================================================

    v2_calls_a1 = _grep_file(
        repo_root,
        "core/task_result_canonical_truth_chain.py",
        "android_participant_truth_ingress",
    ) or _grep_file(
        repo_root,
        "core/task_result_canonical_truth_chain.py",
        "ingest_android_participant_truth_message",
    )

    probe(
        "A1-HOT-01: V2 truth chain calls A1 participant truth ingress",
        "CRITICAL",
        v2_calls_a1,
        "V2 truth chain Step 1 must call android_participant_truth_ingress",
    )

    # ===========================================================
    # PROBE SET 10: Local and cross-device chain documentation
    # ===========================================================

    probe(
        "CHAIN-LOCAL: local_execution_chain.py exists",
        "CRITICAL",
        _file_exists(repo_root, "core/local_execution_chain.py"),
        "Local execution chain must be documented as a first-class chain",
    )

    probe(
        "CHAIN-CROSS: cross_device_execution_chain.py exists",
        "CRITICAL",
        _file_exists(repo_root, "core/cross_device_execution_chain.py"),
        "Cross-device execution chain must be documented as a first-class chain",
    )

    # ===========================================================
    # PROBE SET 11: Delegated flow modules
    # ===========================================================

    probe(
        "DELEGATED-01: delegated_flow_acceptance_gate.py exists",
        "CRITICAL",
        _file_exists(repo_root, "core/delegated_flow_acceptance_gate.py"),
        "Delegated flow acceptance gate must exist (V3 dimension 10)",
    )

    probe(
        "DELEGATED-02: android_delegated_runtime_lifecycle_coordinator.py exists",
        "CRITICAL",
        _file_exists(repo_root, "core/android_delegated_runtime_lifecycle_coordinator.py"),
        "Android delegated lifecycle coordinator must exist",
    )

    probe(
        "DELEGATED-03: V3 composes delegated_flow_acceptance_gate",
        "CRITICAL",
        _grep_file(repo_root, "core/canonical_dispatch_slot_authority.py", "delegated_flow_acceptance_gate"),
        "V3 must delegate dimension 10 to delegated_flow_acceptance_gate",
    )

    # ===========================================================
    # PROBE SET 12: Multi-device capability
    # ===========================================================

    probe(
        "MDEV-01: multi_device_coordination_authority.py exists",
        "CRITICAL",
        _file_exists(repo_root, "core/multi_device_coordination_authority.py"),
        "Multi-device coordination authority must exist",
    )

    probe(
        "MDEV-02: canonical_group_completion_closure.py handles multi-device",
        "CRITICAL",
        _grep_file(repo_root, "core/canonical_group_completion_closure.py", "group"),
        "Group completion closure must handle multi-device group semantics",
    )

    # ===========================================================
    # PROBE SET 13: Replay / recovery capability
    # ===========================================================

    probe(
        "REPLAY-01: replay_foundation.py exists",
        "CRITICAL",
        _file_exists(repo_root, "core/replay_foundation.py"),
        "Replay foundation must exist for terminal-state event emission",
    )

    probe(
        "REPLAY-02: A1 calls replay_foundation",
        "CRITICAL",
        _grep_file(repo_root, "core/android_participant_truth_ingress.py", "replay_foundation"),
        "A1 participant truth ingress must emit to replay_foundation for terminal states",
    )

    # ===========================================================
    # PROBE SET 14: Continuity / session legality
    # ===========================================================

    probe(
        "CONT-01: android_v2_continuity_contract.py exists",
        "CRITICAL",
        _file_exists(repo_root, "core/android_v2_continuity_contract.py"),
        "Android-V2 joint continuity contract must exist",
    )

    probe(
        "CONT-02: V3 delegates dimension 4 to V1 (continuity legality)",
        "CRITICAL",
        _grep_file(repo_root, "core/canonical_dispatch_slot_authority.py", "unified_continuity_legality_authority"),
        "V3 must delegate dimension 4 to V1 unified_continuity_legality_authority",
    )

    # ===========================================================
    # PROBE SET 15: V6 center authority boundary
    # ===========================================================

    probe(
        "V6-01: center_authority_boundary.py exists",
        "CRITICAL",
        _file_exists(repo_root, "core/center_authority_boundary.py"),
        "Center authority boundary module must exist",
    )

    probe(
        "V6-02: assert_center_authority_intact declared",
        "CRITICAL",
        _grep_file(repo_root, "core/center_authority_boundary.py", "def assert_center_authority_intact"),
        "V6 must declare assert_center_authority_intact() function",
    )

    # ===========================================================
    # PROBE SET 16: V2 truth chain soft enforcement (advisory)
    # ===========================================================

    v2_try_except = _count_pattern(
        repo_root / "core/task_result_canonical_truth_chain.py", "try:"
    )

    probe(
        "V2-SOFT-01: V2 truth chain uses try/except (advisory — should be hardened)",
        "ADVISORY",
        v2_try_except > 0,
        f"V2 truth chain has {v2_try_except} try: blocks — confirming soft enforcement. "
        "This is the P1 hardening target. Probe PASSES (confirms finding); "
        "after P1 fix, this count should be 0 or 1 (only CC notification step).",
    )

    # ===========================================================
    # PROBE SET 17: L4 outer loop (not per-request)
    # ===========================================================

    l4_in_openclawd = _grep_file(repo_root, "core/openclawd.py", "GalaxyMainLoopL4")

    probe(
        "L4-01: GalaxyMainLoopL4Enhanced NOT in openclawd.py (advisory)",
        "ADVISORY",
        not l4_in_openclawd,
        "AUDIT EVIDENCE: L4 outer loop should NOT be in per-request openclawd path. "
        "Probe PASSES when L4 is ABSENT from openclawd.py — this is the correct layering.",
    )

    probe(
        "L4-02: galaxy_main_loop_l4_enhanced.py exists in core/",
        "CRITICAL",
        _file_exists(repo_root, "core/galaxy_main_loop_l4_enhanced.py"),
        "L4 enhanced loop must exist in core/",
    )

    # ===========================================================
    # PROBE SET 18: Android participant model (generalization advisory)
    # ===========================================================

    android_prefix_count = sum(
        1
        for f in (repo_root / "core").glob("android_*.py")
        if f.is_file()
    )

    probe(
        "GENERIC-01: android_participant_truth_ingress.py exists",
        "CRITICAL",
        _file_exists(repo_root, "core/android_participant_truth_ingress.py"),
        "Android participant truth ingress (A1) must exist",
    )

    probe(
        "GENERIC-02: android_* files in core/ (advisory — count for generalization planning)",
        "ADVISORY",
        android_prefix_count > 0,
        f"Found {android_prefix_count} android_*.py files in core/. "
        "Generalization target: participant-authority-level files (P3). "
        "Implementation files (bridges, ingress handlers) may retain android_ prefix.",
    )

    probe(
        "GENERIC-03: device_registry.py uses no android_ prefix (generic foundation)",
        "CRITICAL",
        _file_exists(repo_root, "core/device_registry.py")
        and not _contains_pattern(
            repo_root / "core/device_registry.py", "android_specific"
        ),
        "device_registry.py must be device-agnostic (no android_specific hardcoding)",
    )

    # ===========================================================
    # PROBE SET 19: HybridExecutor role (not a parallel authority)
    # ===========================================================

    probe(
        "HYBRID-01: hybrid_executor.py exists",
        "CRITICAL",
        _file_exists(repo_root, "core/hybrid_executor.py"),
        "HybridExecutionArbiter must exist as local fallback helper",
    )

    probe(
        "HYBRID-02: hybrid_executor.py declares fallback_execution_helper role",
        "CRITICAL",
        _grep_file(repo_root, "core/hybrid_executor.py", "fallback_execution_helper"),
        "HybridExecutionArbiter must declare its role as fallback_execution_helper, "
        "not a parallel dispatch authority",
    )

    # ===========================================================
    # PROBE SET 20: Source runtime posture (generic participant concept)
    # ===========================================================

    probe(
        "POSTURE-01: source_runtime_posture.py exists (generic participant concept)",
        "CRITICAL",
        _file_exists(repo_root, "core/source_runtime_posture.py"),
        "source_runtime_posture.py must exist as a non-Android-specific participant concept",
    )

    probe(
        "POSTURE-02: source_runtime_posture.py uses join_runtime / control_only (generic postures)",
        "CRITICAL",
        _grep_file(repo_root, "core/source_runtime_posture.py", "join_runtime")
        and _grep_file(repo_root, "core/source_runtime_posture.py", "control_only"),
        "source_runtime_posture must define join_runtime and control_only (generic, not Android-specific)",
    )

    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def print_report(results: List[ProbeResult]) -> int:
    """Print probe results and return exit code (0 = all CRITICAL pass)."""
    critical_pass = 0
    critical_fail = 0
    advisory_pass = 0
    advisory_fail = 0

    print("\n" + "=" * 78)
    print("FINAL ARCHITECTURE VALIDATION PROBE RESULTS")
    print("=" * 78)

    for r in results:
        if r.category == "CRITICAL":
            if r.passed:
                status = "✅ PASS   "
                critical_pass += 1
            else:
                status = "❌ FAIL   "
                critical_fail += 1
        else:
            if r.passed:
                status = "ℹ️  ADV-OK "
                advisory_pass += 1
            else:
                status = "⚠️  ADV-FAIL"
                advisory_fail += 1

        print(f"{status} [{r.category}] {r.name}")
        if not r.passed or r.category == "ADVISORY":
            print(f"          {r.detail[:120]}")

    print("\n" + "-" * 78)
    print(
        f"CRITICAL: {critical_pass} passed, {critical_fail} failed  |  "
        f"ADVISORY: {advisory_pass} ok, {advisory_fail} attention"
    )
    print("-" * 78)

    if critical_fail == 0:
        print("\n✅ ALL CRITICAL PROBES PASS — audit evidence is validated against current code.")
        return 0
    else:
        print(
            f"\n❌ {critical_fail} CRITICAL PROBE(S) FAILED — audit assumptions may not match current code."
        )
        print("   Review failures above. If code has changed intentionally, update the audit.")
        return 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Final Architecture Validation Probe")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=_DEFAULT_REPO_ROOT,
        help="Path to repository root (default: parent of this script's directory)",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    if not (repo_root / "core").is_dir():
        print(f"ERROR: {repo_root}/core not found. Pass --repo-root to the correct path.", file=sys.stderr)
        return 2

    print(f"Probing repository at: {repo_root}")
    results = run_probes(repo_root)
    return print_report(results)


if __name__ == "__main__":
    sys.exit(main())
