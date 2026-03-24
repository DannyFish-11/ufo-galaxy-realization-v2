#!/usr/bin/env python3
"""
scripts/node_audit.py — Canonical Node-System Audit Tool
=========================================================

PR-6: Node-system audit and canonical inventory establishment.
PR-2 (upgrade): Promoted to the repository-wide canonical governance engine.

Produces a machine-readable JSON audit report and a human-readable Markdown
summary that together answer:

  1. How many nodes exist nominally (directories under nodes/)?
  2. How many are complete / runnable (have main.py + meaningful implementation)?
  3. How many are clearly orchestrated (present in node_dependencies.json)?
  4. Which nodes should be kept / repaired / archived / deleted?

Governance check categories (PR-2):
  - source_completeness   : main.py / fusion_entry.py / README.md presence
  - syntax_safety         : py_compile check for Python entry files
  - packaging             : Dockerfile / requirements.txt presence
  - registry_governance   : node_dependencies.json presence + policy validity
  - runtime_contract      : /health and /status endpoint declarations (static)
  - hygiene               : absence of runtime-generated artifacts (pid/log/tmp…)

Cross-checks:
  - node_dependencies.json  ← authoritative startup config
  - nodes/ directory        ← filesystem reality
  - launcher/node_startup.py ← runtime discovery logic (get_all_nodes)

Usage:
    python scripts/node_audit.py [--output PATH] [--markdown PATH]
                                  [--print-summary]
"""

from __future__ import annotations

import argparse
import json
import os
import py_compile
import re
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# PR-5: packaging audit integration
PACKAGING_POLICY_ACTIVE       = "active"
PACKAGING_POLICY_OPTIONAL     = "optional"
PACKAGING_POLICY_SKIP         = "skip"
PACKAGING_POLICY_UNREGISTERED = "unregistered"

# ---------------------------------------------------------------------------
# Project root resolution
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = _SCRIPT_DIR.parent


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RUNNABLE_MIN_LINES = 100   # nodes with fewer lines are classified as stubs
_RICH_MIN_LINES     = 300   # nodes with ≥300 lines are considered well-implemented

# Valid startup_policy values in node_dependencies.json
_VALID_STARTUP_POLICIES = frozenset({"active", "optional", "skip"})

# Patterns that indicate a /health endpoint declaration in source
_HEALTH_PATTERNS = re.compile(
    r'["\'/]health["\']|def health_check|def health\b',
    re.IGNORECASE,
)
# Patterns that indicate a /status endpoint declaration in source
_STATUS_PATTERNS = re.compile(
    r'["\'/]status["\']|def status_check|def status\b',
    re.IGNORECASE,
)

# File suffixes / names that are runtime-generated artifacts (hygiene check)
_HYGIENE_SUFFIXES = frozenset({".pid", ".log", ".tmp", ".lock", ".cache"})
_HYGIENE_NAMES   = frozenset({"__pycache__"})

# Check category keys (used in NodeAuditEntry.checks dict)
CHECK_SOURCE_COMPLETENESS  = "source_completeness"
CHECK_SYNTAX_SAFETY        = "syntax_safety"
CHECK_PACKAGING            = "packaging"
CHECK_REGISTRY_GOVERNANCE  = "registry_governance"
CHECK_RUNTIME_CONTRACT     = "runtime_contract"
CHECK_HYGIENE              = "hygiene"

# Check result values
CHECK_PASS    = "pass"
CHECK_WARN    = "warn"
CHECK_FAIL    = "fail"
CHECK_UNKNOWN = "unknown"


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
class NodePackagingStatus:
    """Structured packaging completeness record for a single node.

    PR-5: Unified packaging coverage in the canonical node audit.

    Attributes
    ----------
    has_dockerfile : bool
        ``True`` when a ``Dockerfile`` exists in the node directory.
    has_requirements : bool
        ``True`` when ``requirements.txt`` exists in the node directory.
    missing : List[str]
        Names of the packaging files that are absent (empty list = fully covered).
    policy_class : str
        Governance class of the node: ``active`` | ``optional`` | ``skip`` |
        ``unregistered``.  Derived from ``startup_policy`` in
        ``node_dependencies.json`` (``None`` / absent policy → ``active``).
    status : str
        Canonical packaging check result: ``pass`` | ``warn`` | ``fail``.
    severity : str
        Human-readable severity label aligned to the packaging outcome.
        ``"fail"`` for active nodes with missing Dockerfile; ``"warn"`` for
        optional / skip / unregistered nodes or active nodes missing only
        ``requirements.txt``; ``"pass"`` when fully covered.
    """

    has_dockerfile:  bool = False
    has_requirements: bool = False
    missing:         List[str] = field(default_factory=list)
    policy_class:    str = PACKAGING_POLICY_UNREGISTERED
    status:          str = CHECK_UNKNOWN
    severity:        str = CHECK_UNKNOWN

    def to_dict(self) -> Dict:
        return asdict(self)


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
    in_node_dependencies:  bool = False
    config_port:           Optional[int] = None
    config_group:          Optional[str] = None
    config_priority:       Optional[int] = None
    config_deps:           List[str] = field(default_factory=list)
    config_startup_policy: Optional[str] = None   # PR-2: explicit startup_policy value
    policy_valid:          Optional[bool] = None  # PR-2: True/False/None (not in config)

    # Docker / orchestration signals
    in_docker_compose:    bool = False

    # PR-2: Syntax safety
    syntax_ok:         Optional[bool] = None   # None = not applicable (no main.py)
    fusion_syntax_ok:  Optional[bool] = None   # None = not applicable (no fusion_entry.py)
    syntax_error:      Optional[str]  = None   # first error message if syntax fails

    # PR-2: Runtime contract (static inspection only)
    has_health_endpoint: bool = False
    has_status_endpoint: bool = False

    # PR-2: Hygiene violations (runtime-generated artifacts found in node dir)
    hygiene_violations: List[str] = field(default_factory=list)

    # PR-2: Per-category check results (pass/fail/warn/unknown)
    checks: Dict[str, str] = field(default_factory=dict)

    # PR-5: Structured packaging status (canonical per-node packaging record)
    packaging: NodePackagingStatus = field(default_factory=NodePackagingStatus)

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

    # PR-2: Failure category aggregates
    port_conflicts:           List[str] = field(default_factory=list)
    syntax_error_nodes:       List[str] = field(default_factory=list)
    missing_packaging_nodes:  List[str] = field(default_factory=list)
    hygiene_violation_nodes:  List[str] = field(default_factory=list)
    policy_violation_nodes:   List[str] = field(default_factory=list)
    missing_required_files_nodes: List[str] = field(default_factory=list)

    # PR-5: Packaging-specific aggregate lists (separate from the combined list above)
    missing_dockerfile_nodes:   List[str] = field(default_factory=list)
    missing_requirements_nodes: List[str] = field(default_factory=list)

    nodes: List[NodeAuditEntry] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["nodes"] = [n.to_dict() for n in self.nodes]
        return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _check_syntax(py_path: Path) -> Tuple[bool, Optional[str]]:
    """
    Compile-check a Python file.  Returns (ok, error_message).
    Uses py_compile with a throwaway destination to avoid side-effects.
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".pyc", delete=True) as tmp:
            py_compile.compile(str(py_path), cfile=tmp.name, doraise=True)
        return True, None
    except py_compile.PyCompileError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, str(exc)


def _check_runtime_contract(main_py: Path) -> Tuple[bool, bool]:
    """
    Static inspection of main.py for /health and /status endpoint declarations.
    Returns (has_health, has_status).
    """
    try:
        content = main_py.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False, False
    return bool(_HEALTH_PATTERNS.search(content)), bool(_STATUS_PATTERNS.search(content))


def _check_hygiene(node_dir: Path) -> List[str]:
    """
    Return a list of runtime-generated artifact paths found directly inside
    the node directory (non-recursive scan).
    """
    violations: List[str] = []
    try:
        for child in node_dir.iterdir():
            if child.name in _HYGIENE_NAMES:
                violations.append(child.name)
            elif child.suffix in _HYGIENE_SUFFIXES:
                violations.append(child.name)
    except Exception:
        pass
    return sorted(violations)


def _detect_port_conflicts(node_deps: Dict) -> List[str]:
    """
    Detect duplicate port assignments across all nodes in node_dependencies.json.
    Returns human-readable conflict descriptions.
    """
    port_owners: Dict[int, List[str]] = {}
    for name, cfg in node_deps.items():
        port = cfg.get("port")
        if port is not None:
            port_owners.setdefault(int(port), []).append(name)
    conflicts = []
    for port, owners in sorted(port_owners.items()):
        if len(owners) > 1:
            conflicts.append(f"port {port}: {', '.join(sorted(owners))}")
    return conflicts


def _packaging_policy_class(entry: NodeAuditEntry) -> str:
    """Determine the packaging policy class from the node's startup_policy.

    PR-5: Used to calibrate packaging severity per node governance class.
    """
    if not entry.in_node_dependencies:
        return PACKAGING_POLICY_UNREGISTERED
    policy = entry.config_startup_policy
    if policy is None:
        # Implicit "active" when in config but no explicit policy key
        return PACKAGING_POLICY_ACTIVE
    if policy == "optional":
        return PACKAGING_POLICY_OPTIONAL
    if policy == "skip":
        return PACKAGING_POLICY_SKIP
    # Any other value (including "active") maps to active
    return PACKAGING_POLICY_ACTIVE


def _build_packaging_status(entry: NodeAuditEntry) -> NodePackagingStatus:
    """Build a structured packaging status record for a node entry.

    PR-5: Canonical packaging assessment path.

    Severity rules
    --------------
    - ``active`` nodes missing Dockerfile  → **fail**  (containerised deployment blocked)
    - ``active`` nodes missing requirements.txt only → **warn**  (may still be deployable)
    - ``optional`` / ``skip`` nodes missing any packaging file → **warn**
    - ``unregistered`` nodes missing any packaging file → **warn**
    - All files present → **pass**
    """
    policy_class = _packaging_policy_class(entry)
    missing: List[str] = []
    if not entry.has_dockerfile:
        missing.append("Dockerfile")
    if not entry.has_requirements:
        missing.append("requirements.txt")

    if not missing:
        status = CHECK_PASS
        severity = CHECK_PASS
    elif policy_class == PACKAGING_POLICY_ACTIVE:
        # Active nodes: missing Dockerfile is a hard failure; missing only
        # requirements.txt is a warning.
        if not entry.has_dockerfile:
            status = CHECK_FAIL
            severity = CHECK_FAIL
        else:
            # has Dockerfile, missing requirements.txt only
            status = CHECK_WARN
            severity = CHECK_WARN
    else:
        # optional / skip / unregistered — packaging gaps are warnings
        status = CHECK_WARN
        severity = CHECK_WARN

    return NodePackagingStatus(
        has_dockerfile=entry.has_dockerfile,
        has_requirements=entry.has_requirements,
        missing=missing,
        policy_class=policy_class,
        status=status,
        severity=severity,
    )


def _build_checks(entry: NodeAuditEntry) -> Dict[str, str]:
    """Derive per-category check results for a node entry."""
    checks: Dict[str, str] = {}

    # --- source_completeness ---
    if not entry.has_main_py:
        checks[CHECK_SOURCE_COMPLETENESS] = CHECK_FAIL
    elif entry.has_fusion_entry and entry.has_readme:
        checks[CHECK_SOURCE_COMPLETENESS] = CHECK_PASS
    else:
        checks[CHECK_SOURCE_COMPLETENESS] = CHECK_WARN

    # --- syntax_safety ---
    if entry.syntax_ok is None and entry.fusion_syntax_ok is None:
        checks[CHECK_SYNTAX_SAFETY] = CHECK_UNKNOWN
    elif entry.syntax_ok is False or entry.fusion_syntax_ok is False:
        checks[CHECK_SYNTAX_SAFETY] = CHECK_FAIL
    else:
        checks[CHECK_SYNTAX_SAFETY] = CHECK_PASS

    # --- packaging (PR-5: derive from the structured packaging status) ---
    checks[CHECK_PACKAGING] = entry.packaging.status

    # --- registry_governance ---
    if not entry.in_node_dependencies:
        checks[CHECK_REGISTRY_GOVERNANCE] = CHECK_FAIL
    elif entry.policy_valid is False:
        checks[CHECK_REGISTRY_GOVERNANCE] = CHECK_FAIL
    elif entry.config_startup_policy is None:
        # In config, no explicit policy → treated as "active" (valid but implicit)
        checks[CHECK_REGISTRY_GOVERNANCE] = CHECK_PASS
    else:
        checks[CHECK_REGISTRY_GOVERNANCE] = CHECK_PASS

    # --- runtime_contract ---
    if not entry.has_main_py:
        checks[CHECK_RUNTIME_CONTRACT] = CHECK_UNKNOWN
    elif entry.has_health_endpoint and entry.has_status_endpoint:
        checks[CHECK_RUNTIME_CONTRACT] = CHECK_PASS
    elif entry.has_health_endpoint or entry.has_status_endpoint:
        checks[CHECK_RUNTIME_CONTRACT] = CHECK_WARN
    else:
        checks[CHECK_RUNTIME_CONTRACT] = CHECK_WARN

    # --- hygiene ---
    if entry.hygiene_violations:
        checks[CHECK_HYGIENE] = CHECK_FAIL
    else:
        checks[CHECK_HYGIENE] = CHECK_PASS

    return checks


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

    # PR-2: Port conflict detection across registry entries
    report.port_conflicts = _detect_port_conflicts(node_deps)

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
        fusion_py = node_dir / "fusion_entry.py"
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

        # PR-2: Startup policy
        raw_policy = cfg.get("startup_policy") if cfg else None
        policy_valid: Optional[bool] = None
        if cfg:  # node is in config
            if raw_policy is None:
                # Implicit "active" — treated as valid
                policy_valid = True
            else:
                policy_valid = raw_policy in _VALID_STARTUP_POLICIES

        # PR-2: Syntax checks
        syntax_ok: Optional[bool] = None
        fusion_syntax_ok: Optional[bool] = None
        syntax_error: Optional[str] = None
        if main_py.exists():
            syntax_ok, err = _check_syntax(main_py)
            if not syntax_ok and syntax_error is None:
                syntax_error = err
        if fusion_py.exists():
            fusion_syntax_ok, err = _check_syntax(fusion_py)
            if not fusion_syntax_ok and syntax_error is None:
                syntax_error = err

        # PR-2: Runtime contract (static)
        has_health = False
        has_status = False
        if main_py.exists():
            has_health, has_status = _check_runtime_contract(main_py)

        # PR-2: Hygiene
        hygiene_violations = _check_hygiene(node_dir)

        entry = NodeAuditEntry(
            name=name,
            path=str(node_dir.relative_to(project_root)),
            has_main_py=main_py.exists(),
            has_dockerfile=(node_dir / "Dockerfile").exists(),
            has_readme=(node_dir / "README.md").exists(),
            has_fusion_entry=fusion_py.exists(),
            has_requirements=(node_dir / "requirements.txt").exists(),
            extra_py_files=sorted(extra_py),
            main_py_lines=lines,
            in_node_dependencies=name in nodes_in_config,
            config_port=cfg.get("port") if cfg else None,
            config_group=cfg.get("group") if cfg else None,
            config_priority=cfg.get("priority") if cfg else None,
            config_deps=list(cfg.get("dependencies", [])) if cfg else [],
            config_startup_policy=raw_policy,
            policy_valid=policy_valid,
            in_docker_compose=name in docker_nodes,
            syntax_ok=syntax_ok,
            fusion_syntax_ok=fusion_syntax_ok,
            syntax_error=syntax_error,
            has_health_endpoint=has_health,
            has_status_endpoint=has_status,
            hygiene_violations=hygiene_violations,
        )

        _classify(entry)
        # PR-5: build packaging status first so _build_checks can use it
        entry.packaging = _build_packaging_status(entry)
        entry.checks = _build_checks(entry)
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

    # PR-2: Failure category aggregates
    report.syntax_error_nodes = sorted(
        e.name for e in entries
        if e.syntax_ok is False or e.fusion_syntax_ok is False
    )
    # PR-5: missing_packaging_nodes now covers nodes missing EITHER file
    # (previously only nodes missing BOTH were included)
    report.missing_packaging_nodes = sorted(
        e.name for e in entries
        if not e.has_dockerfile or not e.has_requirements
    )
    # PR-5: fine-grained per-file packaging aggregates
    report.missing_dockerfile_nodes = sorted(
        e.name for e in entries if not e.has_dockerfile
    )
    report.missing_requirements_nodes = sorted(
        e.name for e in entries if not e.has_requirements
    )
    report.hygiene_violation_nodes = sorted(
        e.name for e in entries if e.hygiene_violations
    )
    report.policy_violation_nodes = sorted(
        e.name for e in entries if e.policy_valid is False
    )
    report.missing_required_files_nodes = sorted(
        e.name for e in entries
        if not e.has_main_py or not e.has_fusion_entry or not e.has_readme
    )

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
    a("> Authority: `scripts/node_audit.py` — canonical repository governance engine (PR-2)")
    a("")

    # ── Summary Counts ──────────────────────────────────────────────────────
    a("## Summary Counts")
    a("")
    a("| Metric | Count |")
    a("|--------|-------|")
    a(f"| Total nodes audited | **{report.nominal_count}** |")
    a(f"| Runnable nodes (has main.py + ≥{_RUNNABLE_MIN_LINES} lines) | {report.runnable_count} |")
    a(f"| Orchestrated nodes (in node_dependencies.json) | {report.orchestrated_count} |")
    a(f"| Stub nodes (main.py < {_RUNNABLE_MIN_LINES} lines) | {report.stub_count} |")
    a("")

    # ── Recommended Actions ─────────────────────────────────────────────────
    a("## Recommended Actions")
    a("")
    a("| Action | Count | Meaning |")
    a("|--------|-------|---------|")
    a(f"| **keep** | {report.keep_count} | Healthy, orchestrated, no issues |")
    a(f"| **repair** | {report.repair_count} | Valuable role; fix config/impl before use |")
    a(f"| **archive** | {report.archive_count} | Non-trivial but not orchestrated; preserve |")
    a(f"| **delete** | {report.delete_count} | Placeholder/stub/duplicate with no unique value |")
    a("")

    # ── Failure Summary by Category (PR-2) ──────────────────────────────────
    a("## Failure Summary by Category")
    a("")

    def _category_counts(category: str) -> Tuple[int, int]:
        fail_n = sum(1 for e in report.nodes if e.checks.get(category) == CHECK_FAIL)
        warn_n = sum(1 for e in report.nodes if e.checks.get(category) == CHECK_WARN)
        return fail_n, warn_n

    categories = [
        (CHECK_SOURCE_COMPLETENESS, "Source completeness (main.py / fusion_entry.py / README.md)"),
        (CHECK_SYNTAX_SAFETY,       "Syntax safety (py_compile check)"),
        (CHECK_PACKAGING,           "Packaging (Dockerfile / requirements.txt)"),
        (CHECK_REGISTRY_GOVERNANCE, "Registry governance (node_dependencies.json + policy)"),
        (CHECK_RUNTIME_CONTRACT,    "Runtime contract (health / status endpoint)"),
        (CHECK_HYGIENE,             "Hygiene (no runtime artifacts)"),
    ]
    a("| Category | Failing | Warning |")
    a("|----------|---------|---------|")
    for cat_key, cat_label in categories:
        fail_n, warn_n = _category_counts(cat_key)
        a(f"| {cat_label} | {fail_n} | {warn_n} |")
    a("")

    # ── Config Drift ─────────────────────────────────────────────────────────
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

    # ── Port Conflicts (PR-2) ────────────────────────────────────────────────
    a("## Port Conflicts")
    if report.port_conflicts:
        for pc in report.port_conflicts:
            a(f"- {pc}")
    else:
        a("_No port conflicts detected across registry entries._")
    a("")

    # ── Hygiene Violations (PR-2) ────────────────────────────────────────────
    a("## Nodes with Hygiene Violations")
    if report.hygiene_violation_nodes:
        for n in report.hygiene_violation_nodes:
            entry = next(e for e in report.nodes if e.name == n)
            a(f"- `{n}`: {', '.join(entry.hygiene_violations)}")
    else:
        a("_No hygiene violations detected._")
    a("")

    # ── Missing Required Artifacts (PR-2) ────────────────────────────────────
    a("## Nodes with Missing Required Artifacts")
    a("")
    a("Nodes missing one or more of: `main.py`, `fusion_entry.py`, `README.md`")
    a("")
    if report.missing_required_files_nodes:
        a("| Node | main.py | fusion_entry.py | README.md |")
        a("|------|---------|-----------------|-----------|")
        for n in report.missing_required_files_nodes:
            e = next(x for x in report.nodes if x.name == n)
            a(
                f"| `{n}` "
                f"| {'✓' if e.has_main_py else '✗'} "
                f"| {'✓' if e.has_fusion_entry else '✗'} "
                f"| {'✓' if e.has_readme else '✗'} |"
            )
    else:
        a("_All nodes have the required source artifacts._")
    a("")

    # ── Syntax Errors (PR-2) ─────────────────────────────────────────────────
    a("## Nodes with Syntax Errors")
    if report.syntax_error_nodes:
        for n in report.syntax_error_nodes:
            entry = next(e for e in report.nodes if e.name == n)
            a(f"- `{n}`: {entry.syntax_error or 'syntax error'}")
    else:
        a("_No syntax errors detected._")
    a("")

    # ── Packaging Coverage (PR-5) ────────────────────────────────────────────
    a("## Packaging Coverage")
    a("")
    a("> **Canonical source of truth:** `scripts/node_audit.py` — `tools/check_node_packaging.sh` is a "
      "thin companion that defers to this report.")
    a("")

    # --- Nodes missing Dockerfile ---
    a("### Nodes Missing `Dockerfile`")
    a("")
    if report.missing_dockerfile_nodes:
        a("| Node | Policy Class | Severity |")
        a("|------|-------------|----------|")
        for n in report.missing_dockerfile_nodes:
            e = next(x for x in report.nodes if x.name == n)
            a(f"| `{n}` | {e.packaging.policy_class} | **{e.packaging.severity}** |")
    else:
        a("_All nodes have a `Dockerfile`._")
    a("")

    # --- Nodes missing requirements.txt ---
    a("### Nodes Missing `requirements.txt`")
    a("")
    if report.missing_requirements_nodes:
        a("| Node | Policy Class | Severity |")
        a("|------|-------------|----------|")
        for n in report.missing_requirements_nodes:
            e = next(x for x in report.nodes if x.name == n)
            a(f"| `{n}` | {e.packaging.policy_class} | **{e.packaging.severity}** |")
    else:
        a("_All nodes have a `requirements.txt`._")
    a("")

    # --- Packaging summary by policy class ---
    a("### Packaging Summary by Policy Class")
    a("")
    policy_classes = [
        PACKAGING_POLICY_ACTIVE,
        PACKAGING_POLICY_OPTIONAL,
        PACKAGING_POLICY_SKIP,
        PACKAGING_POLICY_UNREGISTERED,
    ]
    a("| Policy Class | Total | Full Coverage | Missing Dockerfile | Missing requirements.txt |")
    a("|-------------|-------|--------------|-------------------|--------------------------|")
    for pc in policy_classes:
        pc_nodes = [e for e in report.nodes if e.packaging.policy_class == pc]
        total_pc = len(pc_nodes)
        if total_pc == 0:
            continue
        full = sum(1 for e in pc_nodes if e.packaging.status == CHECK_PASS)
        no_df = sum(1 for e in pc_nodes if not e.has_dockerfile)
        no_req = sum(1 for e in pc_nodes if not e.has_requirements)
        a(f"| `{pc}` | {total_pc} | {full} | {no_df} | {no_req} |")
    a("")


    a("## Node Inventory")
    a("")
    a("| Node | Lines | Group | Port | Policy | Tier | Action | src | syn | pkg | reg | rt | hyg |")
    a("|------|-------|-------|------|--------|------|--------|-----|-----|-----|-----|----|-----|")
    _icon = {CHECK_PASS: "✓", CHECK_WARN: "~", CHECK_FAIL: "✗", CHECK_UNKNOWN: "?"}
    for e in report.nodes:
        c = e.checks
        policy_display = e.config_startup_policy or ("—" if not e.in_node_dependencies else "active")
        a(
            f"| `{e.name}` "
            f"| {e.main_py_lines if e.has_main_py else '—'} "
            f"| {e.config_group or '—'} "
            f"| {e.config_port or '—'} "
            f"| {policy_display} "
            f"| {e.tier} "
            f"| **{e.action}** "
            f"| {_icon.get(c.get(CHECK_SOURCE_COMPLETENESS, CHECK_UNKNOWN), '?')} "
            f"| {_icon.get(c.get(CHECK_SYNTAX_SAFETY, CHECK_UNKNOWN), '?')} "
            f"| {_icon.get(c.get(CHECK_PACKAGING, CHECK_UNKNOWN), '?')} "
            f"| {_icon.get(c.get(CHECK_REGISTRY_GOVERNANCE, CHECK_UNKNOWN), '?')} "
            f"| {_icon.get(c.get(CHECK_RUNTIME_CONTRACT, CHECK_UNKNOWN), '?')} "
            f"| {_icon.get(c.get(CHECK_HYGIENE, CHECK_UNKNOWN), '?')} |"
        )

    a("")
    a("**Column key:** src=source_completeness · syn=syntax_safety · pkg=packaging · "
      "reg=registry_governance · rt=runtime_contract · hyg=hygiene")
    a("**Icon key:** ✓=pass · ~=warn · ✗=fail · ?=unknown")
    a("")
    a("---")
    a("*This report is generated by `scripts/node_audit.py` (canonical governance engine). "
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
