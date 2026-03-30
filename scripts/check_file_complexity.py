#!/usr/bin/env python3
"""
check_file_complexity.py — File-size and complexity budget guardrail.

Warns (or fails in strict mode) when Python source files exceed defined
line-count thresholds.  The goal is to detect new monolithic files early
before they become entrenched.

Thresholds (lines):
  ERROR_THRESHOLD   — file is considered critically over-budget (fails CI in strict)
  WARN_THRESHOLD    — file is over-budget but not critical (always a warning)

Existing over-budget files are grandfathered with explicit per-file limits.
New files introduced above the thresholds will trigger the guardrail.

Usage:
    python scripts/check_file_complexity.py             # warning mode
    python scripts/check_file_complexity.py --strict    # strict mode (CI)
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
ERROR_THRESHOLD = 2000   # lines — new files must not exceed this
WARN_THRESHOLD = 1000    # lines — warn but don't block

# ---------------------------------------------------------------------------
# Grandfathered files (existing large files that pre-date this guardrail).
# These are allowed to remain at their current size but must NOT grow past
# the grandfathered limit.  Format: {relative_path: max_allowed_lines}
# ---------------------------------------------------------------------------
GRANDFATHERED: dict[str, int] = {
    "core/openclawd.py": 7500,
    "core/api_routes.py": 3000,
    "core/command_router.py": 3000,
    "core/routes/projection.py": 3500,
    "core/multi_llm_router.py": 2000,
    "core/agent_factory.py": 1500,
    "core/desktop_presence_runtime.py": 1500,
    "core/github_installer.py": 1500,
    "core/mainline_convergence.py": 1250,
    "core/orchestration_authority/legacy_paths.py": 1300,
    "core/policy/alignment_surface.py": 1400,
    "core/schemas/unified_control_plan.py": 1350,
    "core/degraded_operation_envelope.py": 1150,
    "core/decision_timeline.py": 1100,
    "core/task_graph.py": 1100,
    "core/vision_pipeline.py": 1100,
    "core/node_communication.py": 1100,
    "core/windows_execution_arbiter.py": 1100,
    "core/runtime_governance/snapshot.py": 1150,
    "core/runtime/source_dispatch_orchestrator.py": 1100,
    "core/multimodal/permission_safety_state.py": 1100,
    "galaxy_gateway/device_router.py": 1500,
    "galaxy_gateway/orchestrator/galaxy_orchestrator.py": 1300,
    "galaxy_gateway/enhanced_nlu_v2.py": 900,
    "galaxy_gateway/android_bridge.py": 900,
    "galaxy_gateway/agent_bridge.py": 900,
    "galaxy_gateway/multimodal_transfer.py": 900,
    "galaxy_gateway/cross_device_coordinator.py": 800,
    "galaxy_gateway/gateway_nats_adapter.py": 800,
    "galaxy_gateway/task_router.py": 800,
    "galaxy_gateway/webrtc_proxy.py": 700,
    "dashboard/backend/main.py": 4000,
    "enhancements/learning/autonomous_learning_engine.py": 1300,
}

# Directories to scan
SCAN_DIRS = ["core", "galaxy_gateway", "enhancements", "dashboard"]

# Patterns to skip
SKIP_PARTS = {"__pycache__", ".venv", "venv", "node_modules", "build", "dist", "external"}


def count_lines(path: Path) -> int:
    try:
        return sum(1 for _ in path.open("r", encoding="utf-8", errors="replace"))
    except OSError:
        return 0


def main() -> int:
    strict = "--strict" in sys.argv
    repo_root = Path(__file__).resolve().parent.parent

    errors: list[str] = []
    warnings: list[str] = []

    for scan_dir in SCAN_DIRS:
        scan_path = repo_root / scan_dir
        if not scan_path.is_dir():
            continue
        for py_file in sorted(scan_path.rglob("*.py")):
            if any(part in py_file.parts for part in SKIP_PARTS):
                continue
            rel = str(py_file.relative_to(repo_root))
            lines = count_lines(py_file)
            grandfathered_limit = GRANDFATHERED.get(rel)

            if grandfathered_limit is not None:
                # Grandfathered file: only flag if it has grown past its limit
                if lines > grandfathered_limit:
                    errors.append(
                        f"  {rel}: {lines} lines — grandfathered limit is "
                        f"{grandfathered_limit} lines (file has grown, please refactor)"
                    )
            elif lines > ERROR_THRESHOLD:
                errors.append(
                    f"  {rel}: {lines} lines — exceeds ERROR_THRESHOLD of "
                    f"{ERROR_THRESHOLD} lines"
                )
            elif lines > WARN_THRESHOLD:
                warnings.append(
                    f"  {rel}: {lines} lines — exceeds WARN_THRESHOLD of "
                    f"{WARN_THRESHOLD} lines (consider splitting)"
                )

    exit_code = 0

    if warnings:
        print("\n⚠️  File-size warnings (non-blocking):\n")
        for w in warnings:
            print(w)

    if errors:
        print("\n❌ File-size budget violations:\n")
        for e in errors:
            print(e)
        if strict:
            print("\nFailing CI (--strict mode).")
            exit_code = 1
        else:
            print("\nWarning only — pass --strict to fail CI.")

    if not warnings and not errors:
        print("✅ All files within complexity budget.")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
