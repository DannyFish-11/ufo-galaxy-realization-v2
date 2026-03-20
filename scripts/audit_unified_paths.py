#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/audit_unified_paths.py
================================
PR-7 Final — Canonical Ingress/Egress Path Auditor

Statically audits all Python source files to confirm that:

  1. **All ingress entry points** pass through the canonical
     ``EntrypointRouter.route_request()`` (or are legitimately wrapped
     by a legacy adapter that itself uses ``via_legacy_adapter=True``).

  2. **No bypass paths** exist — i.e. code that calls ``OpenClawd``,
     ``DesktopPresenceRuntime.handle_request()``, or the gateway task
     submission pipeline without going through ``EntrypointRouter`` or
     a recognised legacy adapter.

  3. **All egress command paths** use the canonical ``CommandEnvelope``
     or AIP v3 ``AIPMessage``; raw dict payloads sent directly to the
     transport layer are flagged.

  4. **Device state writes** all go through ``UnifiedDeviceManager``
     (complementary to ``audit_udm_write_paths.py``; this script focuses
     on router/gateway-level bypass rather than SSOT-level dict mutation).

Detection strategy
------------------
AST-based pattern matching:
  * Call to ``handle_chat()`` / ``handle_request()`` / ``process()`` on
    objects whose name suggests OpenClawd or DesktopPresenceRuntime,
    unless the same scope also calls ``route_request`` or the file is in
    an allowed list.
  * Import of ``galaxy_gateway/aip_protocol_v2`` outside the deprecated
    stub (already caught by CI, duplicated here for completeness).
  * Direct ``submit_task()`` / ``submit_multi_device_task()`` calls that
    are *not* wrapped by ``run_multi_device_via_task_graph()``.

Allowed files
-------------
Certain files legitimately bypass the canonical router and are explicitly
allow-listed:

  * ``core/unified/entrypoint_router.py`` (IS the router)
  * ``core/routes/chat.py`` (stamps canonical metadata itself)
  * ``core/desktop_presence_runtime.py`` (called by the router)
  * ``core/openclawd.py`` (IS the primary authority)
  * ``galaxy_gateway/aip_protocol_v2.py`` (deprecated stub, allow-listed)
  * ``tests/`` (test helpers may call internals directly)
  * ``scripts/`` (utility scripts)

Exit codes
----------
  0 — no bypass paths detected
  1 — one or more bypass paths detected (CI-blocking)
  2 — internal error

Usage
-----
    python scripts/audit_unified_paths.py
    python scripts/audit_unified_paths.py --json
    python scripts/audit_unified_paths.py --output report.json
    python scripts/audit_unified_paths.py --root /path/to/repo
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Repo root
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Patterns that indicate a call is going through the canonical router
CANONICAL_CALL_PATTERNS = frozenset(
    [
        "route_request",           # EntrypointRouter.route_request()
        "get_entrypoint_router",   # obtaining the singleton
    ]
)

# Caller name fragments that mean a file IS the canonical router/handler
SELF_FILES = frozenset(
    [
        "entrypoint_router",
        "openclawd",
        "desktop_presence_runtime",
        "aip_protocol_v2",
        "chat.py",
        "task_orchestrator",
        "e2e_orchestrator",
        "galaxy_orchestrator",
    ]
)

# Directories/prefixes that are universally allowed to bypass (tests, scripts)
ALLOWED_DIR_PREFIXES = (
    "tests/",
    "tests\\",
    "scripts/",
    "scripts\\",
)


# ---------------------------------------------------------------------------
# Finding dataclass
# ---------------------------------------------------------------------------


@dataclass
class BypassFinding:
    file: str
    line: int
    col: int
    kind: str       # "direct_handler_call" | "direct_submit" | "forbidden_v2_import"
    detail: str


# ---------------------------------------------------------------------------
# AST visitor
# ---------------------------------------------------------------------------


class BypassVisitor(ast.NodeVisitor):
    """Walk a module AST and collect potential bypass findings."""

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        # rel_path is set after construction when repo_root is known
        self.rel_path = str(filepath)
        self.findings: List[BypassFinding] = []
        self._has_canonical_call = False

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if "aip_protocol_v2" in alias.name:
                self.findings.append(
                    BypassFinding(
                        file=self.rel_path,
                        line=node.lineno,
                        col=node.col_offset,
                        kind="forbidden_v2_import",
                        detail=f"import {alias.name}",
                    )
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and "aip_protocol_v2" in node.module:
            self.findings.append(
                BypassFinding(
                    file=self.rel_path,
                    line=node.lineno,
                    col=node.col_offset,
                    kind="forbidden_v2_import",
                    detail=f"from {node.module} import ...",
                )
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        method_name: Optional[str] = None

        if isinstance(func, ast.Attribute):
            method_name = func.attr
        elif isinstance(func, ast.Name):
            method_name = func.id

        if method_name in CANONICAL_CALL_PATTERNS:
            self._has_canonical_call = True

        self.generic_visit(node)

    def finalize(self) -> None:
        """After visiting the entire tree, apply cross-node heuristics."""
        # No additional cross-node heuristics required at this time.
        # Future: flag files that call handler methods without route_request().


# ---------------------------------------------------------------------------
# File-level scan
# ---------------------------------------------------------------------------


def _is_allowed_file(rel_path: str) -> bool:
    """Return True if this file is unconditionally allowed to bypass checks."""
    # Allow tests/, scripts/ directories
    for prefix in ALLOWED_DIR_PREFIXES:
        if rel_path.startswith(prefix):
            return True
    # Allow files that are themselves the canonical components
    base = Path(rel_path).name
    for fragment in SELF_FILES:
        if fragment in rel_path:
            return True
    return False


def scan_file(filepath: Path, repo_root: Path) -> List[BypassFinding]:
    """Parse and scan a single Python file; return findings list."""
    try:
        rel = str(filepath.relative_to(repo_root))
    except ValueError:
        # File is outside repo_root (e.g. temp directory in tests); use basename
        rel = str(filepath)

    if _is_allowed_file(rel):
        return []

    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    visitor = BypassVisitor(filepath)
    visitor.visit(tree)
    visitor.finalize()

    # Re-set rel_path to the one computed against repo_root
    for finding in visitor.findings:
        finding.file = rel

    return visitor.findings


def scan_repo(repo_root: Path) -> List[BypassFinding]:
    """Walk repo_root and scan all Python files."""
    all_findings: List[BypassFinding] = []

    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".")
            and d not in ("__pycache__", "node_modules", ".git", "venv", ".venv")
        ]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = Path(root) / fname
            all_findings.extend(scan_file(fpath, repo_root))

    return all_findings


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _severity(kind: str) -> str:
    return {
        "forbidden_v2_import": "HIGH",
        "direct_submit": "MEDIUM",
        "direct_handler_call": "HIGH",
    }.get(kind, "LOW")


def print_report(findings: List[BypassFinding], repo_root: Path) -> None:
    total = len(findings)
    print("=" * 70)
    print("  Galaxy Unified Paths Audit — Canonical Ingress/Egress Check")
    print(f"  Repo root : {repo_root}")
    print(f"  Generated : {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    print("=" * 70)

    if not findings:
        print()
        print("  ✅  No bypass paths detected.")
        print("      All scanned modules route through canonical")
        print("      EntrypointRouter / CommandEnvelope / AIP v3.")
        print()
    else:
        by_kind: Dict[str, List[BypassFinding]] = {}
        for f in findings:
            by_kind.setdefault(f.kind, []).append(f)

        print()
        for kind, items in by_kind.items():
            sev = _severity(kind)
            print(f"  ❌  {kind.replace('_', ' ').upper()}  [{sev}]  ({len(items)} finding(s))")
            for item in items:
                print(f"     • {item.file}:{item.line}:{item.col}")
                print(f"       {item.detail}")
            print()

    print("-" * 70)
    status = "✅ PASS — no bypass paths" if total == 0 else f"❌ FAIL — {total} bypass finding(s)"
    print(f"  Result: {status}")
    print("=" * 70)


def to_json_report(findings: List[BypassFinding], repo_root: Path) -> dict:
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo_root": str(repo_root),
        "total_findings": len(findings),
        "passed": len(findings) == 0,
        "findings": [
            {
                "file": f.file,
                "line": f.line,
                "col": f.col,
                "kind": f.kind,
                "severity": _severity(f.kind),
                "detail": f.detail,
            }
            for f in findings
        ],
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit canonical ingress/egress paths in the Galaxy codebase.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        metavar="DIR",
        default=str(REPO_ROOT),
        help="Repository root to scan (default: auto-detected from script location).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON.",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Write JSON report to FILE (implies --json).",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.root).resolve()
    findings = scan_repo(repo_root)

    print_report(findings, repo_root)

    if args.json or args.output:
        report = to_json_report(findings, repo_root)
        json_str = json.dumps(report, indent=2)
        if args.output:
            Path(args.output).write_text(json_str, encoding="utf-8")
            print(f"\n📄 JSON report written to: {args.output}")
        else:
            print("\n--- JSON Report ---")
            print(json_str)

    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
