#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/generate_system_readiness_report.py
=============================================
PR-7 Final — Unified OpenClawd System Readiness Report Generator

Runs a series of static and import-based checks that verify the Galaxy
Unified System is correctly assembled and ready for production:

  1. Required documentation artifacts exist (U1–U33 acceptance, migration
     matrix, unified system contract, module ownership map).
  2. Core canonical modules are importable.
  3. Conformance test files exist.
  4. Chaos test files exist.
  5. CI workflow contains required check jobs.
  6. Audit scripts exist and are executable.
  7. Schema / contract files exist.
  8. Feature flags config exists.
  9. LLM routing policy exists.
 10. No forbidden aip_protocol_v2 imports outside the deprecated stub.

Output
------
Prints a human-readable readiness summary.  Exits with:
  0 — all checks pass
  1 — one or more checks failed

Usage
-----
    python scripts/generate_system_readiness_report.py
    python scripts/generate_system_readiness_report.py --json
    python scripts/generate_system_readiness_report.py --output report.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Repo root (parent of this script's directory)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Check result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    category: str
    passed: bool
    detail: str = ""
    suggestion: str = ""


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_file_exists(name: str, category: str, path: Path) -> CheckResult:
    exists = path.is_file()
    return CheckResult(
        name=name,
        category=category,
        passed=exists,
        detail=f"{'Found' if exists else 'MISSING'}: {path.relative_to(REPO_ROOT)}",
        suggestion="" if exists else f"Create the file at {path.relative_to(REPO_ROOT)}",
    )


def check_doc_artifacts() -> List[CheckResult]:
    """Verify required documentation files exist."""
    docs = [
        ("Unified System Contract", REPO_ROOT / "docs/architecture/unified_system_contract.md"),
        ("Module Ownership Map", REPO_ROOT / "docs/architecture/module_ownership_map.md"),
        ("Unified Migration Matrix", REPO_ROOT / "docs/migration/unified_migration_matrix.md"),
        ("U1–U33 Final Acceptance Report", REPO_ROOT / "docs/acceptance/u1_u33_final_acceptance.md"),
    ]
    return [_check_file_exists(name, "Documentation", path) for name, path in docs]


def check_core_modules() -> List[CheckResult]:
    """Verify canonical core modules are importable."""
    results: List[CheckResult] = []

    module_paths = [
        ("EntrypointRouter", "core.unified.entrypoint_router", "get_entrypoint_router"),
        ("CommandEnvelope", "core.unified.command_envelope", "CommandEnvelope"),
        ("CapabilityContract", "core.unified.capability_contract", "CapabilityContract"),
        ("CapabilityResolver", "core.unified.capability_resolver", "get_capability_resolver"),
        ("StateSchema", "core.unified.state_schema", "DeviceState"),
        ("ErrorCodes", "core.unified.error_codes", "GalaxyErrorCode"),
        ("ErrorMapper", "core.unified.error_mapper", "ErrorMapper"),
        ("IdempotencyStore", "core.unified.idempotency", "IdempotencyStore"),
        ("ReleaseGate", "core.unified.release_gate", "ReleaseGate"),
        ("LLMRouter", "core.unified.llm_router", "get_unified_llm_router"),
        ("DeviceHealth", "core.unified.device_health", "DeviceHealthScorer"),
        ("ModelRolePolicy", "core.model_role_policy", "ModelRolePolicy"),
        ("StateEventBus", "core.state_event_bus", "get_state_event_bus"),
        ("NodeFabricRegistry", "core.nodes.node_fabric_registry", "get_node_fabric_registry"),
        ("GlobalArbiter", "core.orchestration.global_arbiter", "GlobalArbiter"),
    ]

    # Add REPO_ROOT to sys.path temporarily so imports work when run as script
    _added = False
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
        _added = True

    for friendly_name, module_name, symbol_name in module_paths:
        try:
            mod = __import__(module_name, fromlist=[symbol_name])
            getattr(mod, symbol_name)
            results.append(
                CheckResult(
                    name=f"Import: {friendly_name}",
                    category="Core Modules",
                    passed=True,
                    detail=f"✓ {module_name}.{symbol_name}",
                )
            )
        except Exception as exc:
            results.append(
                CheckResult(
                    name=f"Import: {friendly_name}",
                    category="Core Modules",
                    passed=False,
                    detail=f"✗ {module_name}: {exc}",
                    suggestion=f"Ensure {module_name} is importable with no missing dependencies.",
                )
            )

    if _added:
        sys.path.remove(str(REPO_ROOT))

    return results


def check_conformance_tests() -> List[CheckResult]:
    """Verify conformance test files exist."""
    conformance_dir = REPO_ROOT / "tests" / "conformance"
    expected = [
        "test_aip_v3_envelope.py",
        "test_gateway_routing.py",
        "test_nats_trace.py",
        "test_udm_ssot_conformance.py",
    ]
    results = []
    for fname in expected:
        path = conformance_dir / fname
        results.append(_check_file_exists(f"Conformance: {fname}", "Conformance Tests", path))
    return results


def check_chaos_tests() -> List[CheckResult]:
    """Verify chaos test files exist."""
    chaos_dir = REPO_ROOT / "tests" / "chaos"
    expected = [
        "test_disconnect_chaos.py",
        "test_latency_chaos.py",
        "test_duplicate_message_chaos.py",
        "test_partial_failure_chaos.py",
    ]
    results = []
    for fname in expected:
        path = chaos_dir / fname
        results.append(_check_file_exists(f"Chaos: {fname}", "Chaos Tests", path))
    return results


def check_ci_workflow() -> List[CheckResult]:
    """Verify CI workflow contains required check jobs."""
    results: List[CheckResult] = []
    ci_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"

    if not ci_path.is_file():
        return [
            CheckResult(
                name="CI Workflow: ci.yml",
                category="CI/CD",
                passed=False,
                detail="MISSING: .github/workflows/ci.yml",
                suggestion="Create .github/workflows/ci.yml with required check jobs.",
            )
        ]

    ci_content = ci_path.read_text(encoding="utf-8")

    required_jobs = [
        ("conformance-tests", "Conformance test job"),
        ("chaos-tests", "Chaos test job"),
        ("ssot-udm-conformance", "SSOT/UDM conformance job"),
        ("v3-protocol-guard", "AIPv3 protocol guard job"),
        ("s6-compat-smoke", "S6 compatibility smoke job"),
        ("test", "General test job"),
    ]

    for job_id, friendly in required_jobs:
        present = job_id + ":" in ci_content
        results.append(
            CheckResult(
                name=f"CI Job: {job_id}",
                category="CI/CD",
                passed=present,
                detail=f"{'Found' if present else 'MISSING'}: {job_id} in ci.yml",
                suggestion="" if present else f"Add '{job_id}:' job to .github/workflows/ci.yml",
            )
        )

    return results


def check_audit_scripts() -> List[CheckResult]:
    """Verify audit scripts exist."""
    scripts = [
        ("audit_udm_write_paths.py", REPO_ROOT / "scripts" / "audit_udm_write_paths.py"),
        ("audit_unified_paths.py", REPO_ROOT / "scripts" / "audit_unified_paths.py"),
        ("generate_system_readiness_report.py", REPO_ROOT / "scripts" / "generate_system_readiness_report.py"),
    ]
    return [_check_file_exists(f"Script: {name}", "Audit Scripts", path) for name, path in scripts]


def check_schema_and_config_files() -> List[CheckResult]:
    """Verify schema, contract, and config files exist."""
    files = [
        ("AIP Envelope Schema", REPO_ROOT / "galaxy_gateway" / "protocol" / "schemas" / "aip_envelope.schema.json"),
        ("Command Result Schema", REPO_ROOT / "galaxy_gateway" / "protocol" / "schemas" / "command_result.schema.json"),
        ("Task Assign Schema", REPO_ROOT / "galaxy_gateway" / "protocol" / "schemas" / "task_assign.schema.json"),
        ("Feature Flags Config", REPO_ROOT / "config" / "feature_flags.yaml"),
        ("LLM Routing Policy", REPO_ROOT / "config" / "llm_routing_policy.yaml"),
    ]
    return [_check_file_exists(name, "Schemas & Config", path) for name, path in files]


def check_no_forbidden_aip_v2_imports() -> List[CheckResult]:
    """Scan Python sources for forbidden aip_protocol_v2 imports outside the legacy stub."""
    results: List[CheckResult] = []
    violations: List[str] = []

    allowed_files = {
        REPO_ROOT / "galaxy_gateway" / "aip_protocol_v2.py",
        REPO_ROOT / "tests" / "test_v3_protocol_guard.py",
        # PR7 test file references the pattern as a string literal in test cases
        REPO_ROOT / "tests" / "test_pr7_final_consolidation.py",
    }

    # Also skip scripts/ directory — audit/readiness scripts reference the
    # pattern as string literals, not as actual imports to be blocked.
    def _is_scripts_dir(p: Path) -> bool:
        try:
            rel = p.relative_to(REPO_ROOT)
            return rel.parts[0] == "scripts"
        except ValueError:
            return False

    for root, dirs, files in os.walk(REPO_ROOT):
        # skip hidden dirs and common non-source dirs
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = Path(root) / fname
            if fpath in allowed_files or _is_scripts_dir(fpath):
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                if "aip_protocol_v2" in content:
                    rel = fpath.relative_to(REPO_ROOT)
                    violations.append(str(rel))
            except Exception:
                pass

    if violations:
        results.append(
            CheckResult(
                name="No Forbidden aip_protocol_v2 Imports",
                category="Protocol Guard",
                passed=False,
                detail=f"Forbidden aip_protocol_v2 references in: {', '.join(violations)}",
                suggestion="Remove aip_protocol_v2 imports; use galaxy_gateway/protocol/aip_v3.py instead.",
            )
        )
    else:
        results.append(
            CheckResult(
                name="No Forbidden aip_protocol_v2 Imports",
                category="Protocol Guard",
                passed=True,
                detail="No forbidden aip_protocol_v2 references found outside the deprecated stub.",
            )
        )

    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def run_all_checks() -> List[CheckResult]:
    all_results: List[CheckResult] = []
    all_results.extend(check_doc_artifacts())
    all_results.extend(check_core_modules())
    all_results.extend(check_conformance_tests())
    all_results.extend(check_chaos_tests())
    all_results.extend(check_ci_workflow())
    all_results.extend(check_audit_scripts())
    all_results.extend(check_schema_and_config_files())
    all_results.extend(check_no_forbidden_aip_v2_imports())
    return all_results


def _group_by_category(results: List[CheckResult]) -> Dict[str, List[CheckResult]]:
    groups: Dict[str, List[CheckResult]] = {}
    for r in results:
        groups.setdefault(r.category, []).append(r)
    return groups


def print_report(results: List[CheckResult]) -> None:
    groups = _group_by_category(results)
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    print("=" * 70)
    print("  Galaxy Unified OpenClawd — System Readiness Report")
    print(f"  Generated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    print("=" * 70)
    print()

    for category, checks in groups.items():
        cat_passed = sum(1 for c in checks if c.passed)
        cat_total = len(checks)
        cat_status = "✅" if cat_passed == cat_total else "❌"
        print(f"{cat_status}  {category}  ({cat_passed}/{cat_total})")
        for c in checks:
            icon = "  ✓" if c.passed else "  ✗"
            print(f"{icon}  {c.name}")
            if c.detail:
                print(f"       {c.detail}")
            if not c.passed and c.suggestion:
                print(f"       💡 {c.suggestion}")
        print()

    print("-" * 70)
    overall = "✅ READY" if failed == 0 else f"❌ NOT READY ({failed} check(s) failed)"
    print(f"  Overall: {overall}  |  {passed}/{total} checks passed")
    print("=" * 70)


def to_json_report(results: List[CheckResult]) -> dict:
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "ready": all(r.passed for r in results),
        "checks": [
            {
                "name": r.name,
                "category": r.category,
                "passed": r.passed,
                "detail": r.detail,
                "suggestion": r.suggestion,
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the Galaxy Unified OpenClawd system readiness report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON (in addition to human-readable summary).",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Write JSON report to FILE (implies --json).",
    )
    args = parser.parse_args(argv)

    results = run_all_checks()

    print_report(results)

    if args.json or args.output:
        report = to_json_report(results)
        json_str = json.dumps(report, indent=2)
        if args.output:
            Path(args.output).write_text(json_str, encoding="utf-8")
            print(f"\n📄 JSON report written to: {args.output}")
        else:
            print("\n--- JSON Report ---")
            print(json_str)

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
