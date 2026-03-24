#!/usr/bin/env python3
"""
scripts/node_audit.py — Canonical Node-System Audit Tool
=========================================================

PR-6: Node-system audit and canonical inventory establishment.

Produces a machine-readable JSON audit report and a human-readable Markdown
summary that together answer:

  1. How many nodes exist nominally (directories under nodes/)?
  2. How many are complete / runnable (have main.py + meaningful implementation)?
  3. How many are clearly orchestrated (present in node_dependencies.json)?
  4. Which nodes should be kept / repaired / archived / deleted?

Cross-checks:
  - node_dependencies.json  ← authoritative startup config
  - nodes/ directory        ← filesystem reality
  - launcher/node_startup.py ← runtime discovery logic (get_all_nodes)

Usage:
    python scripts/node_audit.py [--output PATH]

    --output PATH   Write JSON report to PATH instead of the default
                    docs/node_audit_report.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Project root resolution
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = _SCRIPT_DIR.parent


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class NodeTier:
    """Node quality tiers used in the audit."""
    NOMINAL      = "nominal"           # directory exists
    RUNNABLE     = "runnable"          # has main.py + non-trivial implementation
    ORCHESTRATED = "orchestrated"      # listed in node_dependencies.json
    STUB         = "stub"              # main.py < 100 lines or clearly placeholder


class RecommendedAction:
    """Recommended disposition for each node."""
    KEEP    = "keep"     # healthy, orchestrated, no issues
    REPAIR  = "repair"   # has issues but useful role; should be fixed
    ARCHIVE = "archive"  # not orchestrated but non-trivial; preserve for reference
    DELETE  = "delete"   # placeholder / stub / duplicate with no unique value


@dataclass
class NodeAuditEntry:
    name: str
    path: str

    # Structural signals
    has_main_py:      bool = False
    has_dockerfile:   bool = False
    has_readme:       bool = False
    has_fusion_entry: bool = False
    has_requirements: bool = False
    extra_py_files:   List[str] = field(default_factory=list)

    # Implementation depth
    main_py_lines:    int = 0

    # Config signals
    in_node_dependencies: bool = False
    config_port:          Optional[int] = None
    config_group:         Optional[str] = None
    config_priority:      Optional[int] = None
    config_deps:          List[str] = field(default_factory=list)

    # Docker / orchestration signals
    in_docker_compose:    bool = False

    # Classification
    tier:   str = NodeTier.NOMINAL
    action: str = RecommendedAction.ARCHIVE

    # Notes
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = asdict(self)
        return d


@dataclass
class NodeAuditReport:
    generated_at: str
    project_root: str

    # Counts
    nominal_count:      int = 0
    runnable_count:     int = 0
    orchestrated_count: int = 0
    stub_count:         int = 0

    # Recommendation counts
    keep_count:    int = 0
    repair_count:  int = 0
    archive_count: int = 0
    delete_count:  int = 0

    # Config drift
    in_config_not_on_disk: List[str] = field(default_factory=list)
    on_disk_not_in_config: List[str] = field(default_factory=list)
    reserved_nodes:        List[str] = field(default_factory=list)
    duplicate_roles:       List[str] = field(default_factory=list)
    numbering_gaps:        List[int] = field(default_factory=list)
    missing_main_py:       List[str] = field(default_factory=list)

    nodes: List[NodeAuditEntry] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["nodes"] = [n.to_dict() for n in self.nodes]
        return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RUNNABLE_MIN_LINES = 100   # nodes with fewer lines are classified as stubs
_RICH_MIN_LINES     = 300   # nodes with ≥300 lines are considered well-implemented


def _load_node_dependencies(project_root: Path) -> Dict:
    """Load and return the 'nodes' dict from node_dependencies.json."""
    cfg_path = project_root / "node_dependencies.json"
    if not cfg_path.exists():
        return {}
    try:
        with open(cfg_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("nodes", {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_docker_compose_nodes(project_root: Path) -> set:
    """Return set of node names mentioned in docker-compose.full.yml."""
    compose_path = project_root / "docker-compose.full.yml"
    if not compose_path.exists():
        return set()
    try:
        content = compose_path.read_text(encoding="utf-8", errors="replace")
        return set(re.findall(r"Node_\d+_[A-Za-z]+", content))
    except Exception:
        return set()


def _classify(entry: NodeAuditEntry) -> None:
    """Set entry.tier and entry.action based on its fields."""
    notes = entry.notes

    # --- Tier assignment ---
    if not entry.has_main_py:
        entry.tier = NodeTier.NOMINAL
        notes.append("No main.py found — not runnable")
    elif entry.main_py_lines < _RUNNABLE_MIN_LINES:
        entry.tier = NodeTier.STUB
        notes.append(f"main.py only {entry.main_py_lines} lines — classified as stub")
    elif entry.in_node_dependencies:
        entry.tier = NodeTier.ORCHESTRATED
    else:
        entry.tier = NodeTier.RUNNABLE

    # --- Action assignment ---
    is_reserved = "Reserved" in entry.name

    if is_reserved:
        notes.append("Node name contains 'Reserved' — placeholder slot")
        if entry.main_py_lines < 200:
            entry.action = RecommendedAction.DELETE
        else:
            # Reserved node with actual implementation → archive until claimed
            entry.action = RecommendedAction.ARCHIVE
        return

    if not entry.has_main_py:
        entry.action = RecommendedAction.DELETE
        return

    if entry.tier == NodeTier.STUB:
        entry.action = RecommendedAction.REPAIR
        notes.append("Stub implementation — needs meaningful code before use")
        return

    if entry.tier == NodeTier.ORCHESTRATED:
        if not entry.has_dockerfile:
            notes.append("Missing Dockerfile — containerised deployment blocked")
            entry.action = RecommendedAction.REPAIR
        else:
            entry.action = RecommendedAction.KEEP
        return

    # Runnable but not in config
    if entry.main_py_lines >= _RICH_MIN_LINES:
        notes.append("Not in node_dependencies.json — config drift")
        entry.action = RecommendedAction.REPAIR
    else:
        notes.append("Not in node_dependencies.json and thin implementation")
        entry.action = RecommendedAction.ARCHIVE


# ---------------------------------------------------------------------------
# Audit engine
# ---------------------------------------------------------------------------

def run_audit(project_root: Path) -> NodeAuditReport:
    nodes_dir = project_root / "nodes"
    if not nodes_dir.exists():
        raise FileNotFoundError(f"nodes/ directory not found at {nodes_dir}")

    node_deps = _load_node_dependencies(project_root)
    docker_nodes = _load_docker_compose_nodes(project_root)

    report = NodeAuditReport(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        project_root=str(project_root),
    )

    # --- Enumerate nominal nodes ---
    node_dirs = sorted(
        d for d in nodes_dir.iterdir()
        if d.is_dir() and d.name.startswith("Node_")
    )
    nodes_on_disk = {d.name for d in node_dirs}
    nodes_in_config = set(node_deps.keys())

    # Config drift
    report.in_config_not_on_disk = sorted(nodes_in_config - nodes_on_disk)
    report.on_disk_not_in_config = sorted(nodes_on_disk - nodes_in_config)
    report.reserved_nodes = sorted(n for n in nodes_on_disk if "Reserved" in n)
    report.missing_main_py = sorted(
        d.name for d in node_dirs if not (d / "main.py").exists()
    )

    # Duplicate role detection (same suffix → same role)
    role_map: Dict[str, List[str]] = {}
    for name in nodes_on_disk:
        m = re.match(r"Node_\d+_(.+)", name)
        if m:
            role = m.group(1)
            role_map.setdefault(role, []).append(name)
    report.duplicate_roles = sorted(
        f"{role}: {', '.join(sorted(holders))}"
        for role, holders in role_map.items()
        if len(holders) > 1
    )

    # Numbering gaps
    nums = set()
    for name in nodes_on_disk:
        m = re.match(r"Node_(\d+)_", name)
        if m:
            nums.add(int(m.group(1)))
    if nums:
        report.numbering_gaps = sorted(set(range(0, max(nums) + 1)) - nums)

    # --- Per-node entries ---
    entries: List[NodeAuditEntry] = []
    for node_dir in node_dirs:
        name = node_dir.name
        main_py = node_dir / "main.py"
        cfg = node_deps.get(name, {})

        lines = 0
        if main_py.exists():
            try:
                lines = sum(1 for _ in main_py.open(encoding="utf-8", errors="replace"))
            except Exception:
                lines = 0

        extra_py = [
            f.name for f in node_dir.iterdir()
            if f.suffix == ".py" and f.name not in ("main.py", "__init__.py", "fusion_entry.py")
        ]

        entry = NodeAuditEntry(
            name=name,
            path=str(node_dir.relative_to(project_root)),
            has_main_py=main_py.exists(),
            has_dockerfile=(node_dir / "Dockerfile").exists(),
            has_readme=(node_dir / "README.md").exists(),
            has_fusion_entry=(node_dir / "fusion_entry.py").exists(),
            has_requirements=(node_dir / "requirements.txt").exists(),
            extra_py_files=sorted(extra_py),
            main_py_lines=lines,
            in_node_dependencies=name in nodes_in_config,
            config_port=cfg.get("port") if cfg else None,
            config_group=cfg.get("group") if cfg else None,
            config_priority=cfg.get("priority") if cfg else None,
            config_deps=list(cfg.get("dependencies", [])) if cfg else [],
            in_docker_compose=name in docker_nodes,
        )

        _classify(entry)
        entries.append(entry)

    report.nodes = entries

    # --- Aggregate counts ---
    report.nominal_count      = len(entries)
    report.runnable_count     = sum(1 for e in entries if e.tier in (NodeTier.RUNNABLE, NodeTier.ORCHESTRATED))
    report.orchestrated_count = sum(1 for e in entries if e.tier == NodeTier.ORCHESTRATED)
    report.stub_count         = sum(1 for e in entries if e.tier == NodeTier.STUB)
    report.keep_count         = sum(1 for e in entries if e.action == RecommendedAction.KEEP)
    report.repair_count       = sum(1 for e in entries if e.action == RecommendedAction.REPAIR)
    report.archive_count      = sum(1 for e in entries if e.action == RecommendedAction.ARCHIVE)
    report.delete_count       = sum(1 for e in entries if e.action == RecommendedAction.DELETE)

    return report


# ---------------------------------------------------------------------------
# Markdown report generator
# ---------------------------------------------------------------------------

def _render_markdown(report: NodeAuditReport) -> str:
    lines: List[str] = []
    a = lines.append

    a("# Galaxy Node-System Audit Report")
    a("")
    a(f"> Generated: {report.generated_at}")
    a("")
    a("## Summary Counts")
    a("")
    a("| Metric | Count |")
    a("|--------|-------|")
    a(f"| Nominal node directories | {report.nominal_count} |")
    a(f"| Runnable nodes (has main.py + ≥{_RUNNABLE_MIN_LINES} lines) | {report.runnable_count} |")
    a(f"| Orchestrated nodes (in node_dependencies.json) | {report.orchestrated_count} |")
    a(f"| Stub nodes (main.py < {_RUNNABLE_MIN_LINES} lines) | {report.stub_count} |")
    a("")
    a("## Recommended Actions")
    a("")
    a("| Action | Count | Meaning |")
    a("|--------|-------|---------|")
    a(f"| **keep** | {report.keep_count} | Healthy, orchestrated, no issues |")
    a(f"| **repair** | {report.repair_count} | Valuable role; fix config/impl before use |")
    a(f"| **archive** | {report.archive_count} | Non-trivial but not orchestrated; preserve |")
    a(f"| **delete** | {report.delete_count} | Placeholder/stub/duplicate with no unique value |")
    a("")

    # Config drift
    a("## Config Drift")
    a("")
    a("### Nodes in `node_dependencies.json` but NOT on disk")
    if report.in_config_not_on_disk:
        for n in report.in_config_not_on_disk:
            a(f"- `{n}`")
    else:
        a("_None — config and disk are in sync for this direction._")
    a("")

    a("### Nodes on disk but NOT in `node_dependencies.json`")
    if report.on_disk_not_in_config:
        for n in report.on_disk_not_in_config:
            a(f"- `{n}`")
    else:
        a("_None._")
    a("")

    a("### Nodes missing `main.py`")
    if report.missing_main_py:
        for n in report.missing_main_py:
            a(f"- `{n}`")
    else:
        a("_None — all nominal nodes have a main.py._")
    a("")

    a("### Reserved (placeholder) nodes")
    if report.reserved_nodes:
        for n in report.reserved_nodes:
            a(f"- `{n}`")
    else:
        a("_None._")
    a("")

    a("### Duplicate role nodes")
    if report.duplicate_roles:
        for r in report.duplicate_roles:
            a(f"- {r}")
    else:
        a("_None._")
    a("")

    a("### Numbering gaps")
    if report.numbering_gaps:
        a(f"Missing node numbers: {report.numbering_gaps}")
    else:
        a("_No gaps in node numbering._")
    a("")

    # Per-node table
    a("## Node Inventory")
    a("")
    a("| Node | Lines | Group | Port | In Config | Tier | Action | Notes |")
    a("|------|-------|-------|------|-----------|------|--------|-------|")
    for e in report.nodes:
        notes_str = "; ".join(e.notes) if e.notes else ""
        a(
            f"| `{e.name}` "
            f"| {e.main_py_lines if e.has_main_py else '—'} "
            f"| {e.config_group or '—'} "
            f"| {e.config_port or '—'} "
            f"| {'✓' if e.in_node_dependencies else '✗'} "
            f"| {e.tier} "
            f"| **{e.action}** "
            f"| {notes_str} |"
        )

    a("")
    a("---")
    a("*This report is generated by `scripts/node_audit.py`. "
      "Re-run after node changes to refresh.*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Galaxy node-system audit and emit a canonical report."
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "docs" / "node_audit_report.json"),
        help="Path to write the JSON report (default: docs/node_audit_report.json)",
    )
    parser.add_argument(
        "--markdown",
        default=str(PROJECT_ROOT / "docs" / "NODE_SYSTEM_AUDIT.md"),
        help="Path to write the Markdown report (default: docs/NODE_SYSTEM_AUDIT.md)",
    )
    parser.add_argument(
        "--print-summary",
        action="store_true",
        default=False,
        help="Print a brief summary to stdout",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    report = run_audit(PROJECT_ROOT)

    # Write JSON
    json_path = Path(args.output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"JSON report written → {json_path}")

    # Write Markdown
    md_path = Path(args.markdown)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    print(f"Markdown report written → {md_path}")

    if args.print_summary:
        print(
            f"\nNominal: {report.nominal_count}  "
            f"Runnable: {report.runnable_count}  "
            f"Orchestrated: {report.orchestrated_count}  "
            f"Stub: {report.stub_count}\n"
            f"keep={report.keep_count}  repair={report.repair_count}  "
            f"archive={report.archive_count}  delete={report.delete_count}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
