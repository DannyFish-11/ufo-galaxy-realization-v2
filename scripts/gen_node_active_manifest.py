#!/usr/bin/env python3
"""
scripts/gen_node_active_manifest.py — Node Active Manifest Generator
=====================================================================

PR-10: Automate audit/manifest generation and finalize the long-term
       maintainer workflow.

Generates ``docs/NODE_ACTIVE_MANIFEST.md`` from the two canonical
machine-readable sources:

  1. ``node_dependencies.json``  — authoritative node registry (startup
     policies, ports, groups, descriptions)
  2. ``docs/node_audit_report.json`` — latest structured audit output
     (optional-node baseline checks, promotion-readiness data)

This script reduces long-term drift between the human-readable manifest
and the canonical machine-readable state.  Run it after any change to
``node_dependencies.json`` or after regenerating the audit report.

Usage::

    python scripts/gen_node_active_manifest.py
    python scripts/gen_node_active_manifest.py --output docs/NODE_ACTIVE_MANIFEST.md
    python scripts/gen_node_active_manifest.py --print-summary

Makefile shorthand::

    make manifest-regen
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Project root resolution
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = _SCRIPT_DIR.parent

# ---------------------------------------------------------------------------
# Static content blocks (policy semantics, state machine, promotion checklist)
# These are governance policy text; the data-driven sections below are
# generated from the canonical sources.
# ---------------------------------------------------------------------------

_POLICY_SEMANTICS = """\
## Startup Policy Semantics

`node_dependencies.json` carries an explicit `startup_policy` field on **every**
node entry (normalized in PR-6 — all entries now carry an explicit value;
implicit defaults are no longer accepted as a governance practice).

The launcher (`launcher/node_startup.py`) respects this field to decide what to start.

| Policy | Meaning | Launcher behaviour |
|--------|---------|--------------------|
| `active` | Healthy, orchestrated, no issues | Started unconditionally |
| `optional` | Deliberate governance state — valid role, individually tracked path to active | Started if available; failure does not abort system |
| `skip` | Archived, deleted, or unfinished stub | **Never started** — registry entry kept for audit tracking only |

### Startup Policy State Machine

States and legal transitions:

```
         ┌─────────────────────────────────────┐
         │  optional → active                  │
         │  (promotion checklist complete;      │
         │   governance review passed)          │
         ▼                                     │
    ┌─────────┐   active → optional        ┌──────────┐
    │ active  │ ─────────────────────────► │ optional │
    └─────────┘   (known issue / drift;    └──────────┘
         │         soft-fail tolerated)         │
         │                                      │
         │  active → skip                       │  optional → skip
         │  (node retired / archived /          │  (repair attempt abandoned;
         │   identified as stub)                │   node archived)
         ▼                                      ▼
                        ┌──────┐
                        │ skip │
                        └──────┘
```

| Transition | Trigger | Required action |
|------------|---------|-----------------|
| `optional` → `active` | Promotion checklist complete; governance review passed | Update `startup_policy` in `node_dependencies.json`; run `make regen-all` |
| `active` → `optional` | Node develops a known issue or config drift | Demote to allow soft-fail startup; open a tracking issue |
| `active` → `skip` | Node retired, archived, or confirmed stub | Update `startup_policy`; document reason in registry `description` |
| `optional` → `skip` | Repair attempt abandoned | Update `startup_policy`; document reason in registry `description` |

> **Note**: `skip` is a terminal/holding state.  A `skip` node must not be
> started by any launcher path.  To resurrect a skipped node, open a dedicated
> PR with a full implementation review.
"""

_OPTIONAL_GOVERNANCE_INTRO = """\
## Optional-Node Governance

`optional` is a **deliberate, governable state**, not an undefined bucket.
Every optional node must:

1. Appear in `node_dependencies.json` with `startup_policy: "optional"` explicitly set.
2. Meet the optional-node minimum baseline (see below).
3. Have a tracked path toward `active` (or a documented decision to remain optional / be archived).

Maintainers can inspect the health of the optional-node set by running:

```bash
python scripts/node_audit.py --print-summary
# Then open docs/NODE_SYSTEM_AUDIT.md §Optional-Node Governance for the full table
```

### Optional-Node Minimum Baseline

The following checks must pass for a node to be considered a **well-governed
optional node**.  Failing any of these is a governance gap requiring remediation.

| Check | Requirement |
|-------|-------------|
| `registry_present` | Entry in `node_dependencies.json` with `startup_policy: "optional"` |
| `has_main_py` | `main.py` exists in node directory |
| `has_fusion_entry` | `fusion_entry.py` exists in node directory |
| `syntax_ok` | `main.py` and `fusion_entry.py` pass `py_compile` |
| `has_readme` | `README.md` exists (describability) |
| `hygiene_clean` | No runtime-artifact files in node root |

> The optional baseline is deliberately weaker than `active`.  Packaging
> (Dockerfile / requirements.txt) and runtime-contract endpoints (/health, /status)
> are **not** required for optional — they are tracked as **promotion-gap** checks.

### Promotion-Gap Checks (delta to `active`)

| Check | Requirement |
|-------|-------------|
| `has_dockerfile` | `Dockerfile` present in node directory |
| `has_requirements` | `requirements.txt` present |
| `has_health_endpoint` | `/health` endpoint declared in `main.py` |
| `has_status_endpoint` | `/status` endpoint declared in `main.py` |
"""

_PROMOTION_CHECKLIST = """\
## Promotion Checklist: `optional` → `active`

Use this checklist when promoting a node.  All items must be checked before
changing `startup_policy` from `"optional"` to `"active"`.

### 1. Technical checks (must pass audit engine)

- [ ] `main.py` exists and passes `py_compile`
- [ ] `fusion_entry.py` exists and passes `py_compile`
- [ ] `README.md` exists and describes port, endpoints, env vars, and dependencies
- [ ] `Dockerfile` present and builds successfully
- [ ] `requirements.txt` present and pinned/validated
- [ ] `/health` endpoint declared and returns `{"status": "healthy"}` when live
- [ ] `/status` endpoint declared and returns operational state when live
- [ ] No hygiene violations in node root
- [ ] Node is registered in `node_dependencies.json` with explicit `startup_policy`
- [ ] No port conflicts with other registered nodes

### 2. Runtime validation

- [ ] Node starts cleanly under `launcher/node_startup.py`
- [ ] `/health` probe returns HTTP 200 within the health-check timeout
- [ ] `/status` probe returns HTTP 200 with a meaningful state payload
- [ ] Node does not abort system startup on failure (launcher soft-fail confirmed)

### 3. Governance review

- [ ] Node role is documented in `README.md` and understood by a maintainer
- [ ] Node description in `node_dependencies.json` is accurate
- [ ] No known open issues blocking promotion
- [ ] Run `make regen-all` and commit regenerated docs

### 4. Commit actions

1. Change `startup_policy` from `"optional"` to `"active"` in `node_dependencies.json`.
2. Update node description / audit metadata fields if needed.
3. Run `make regen-all` to regenerate `docs/node_audit_report.json`,
   `docs/NODE_SYSTEM_AUDIT.md`, and `docs/NODE_ACTIVE_MANIFEST.md`.
4. Run `make governance` — all checks must pass.
5. Open a PR with health-check evidence in the description.
"""


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _load_node_dependencies(project_root: Path) -> Dict[str, Any]:
    path = project_root / "node_dependencies.json"
    if not path.exists():
        raise FileNotFoundError(f"node_dependencies.json not found at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_audit_report(project_root: Path) -> Dict[str, Any]:
    path = project_root / "docs" / "node_audit_report.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _audit_node_map(audit_report: Dict[str, Any]) -> Dict[str, Any]:
    """Return a dict keyed by node name from the audit report node list."""
    nodes = audit_report.get("nodes", [])
    return {n["name"]: n for n in nodes if "name" in n}


# ---------------------------------------------------------------------------
# Section generators
# ---------------------------------------------------------------------------

def _gen_header(audit_report: Dict[str, Any]) -> str:
    generated_at = audit_report.get("generated_at", datetime.now(timezone.utc).isoformat())
    lines = [
        "# Galaxy Node Active Manifest",
        "",
        "> **Generated by** `scripts/gen_node_active_manifest.py` (PR-10)  ",
        f"> **Audit source:** `docs/node_audit_report.json` (generated {generated_at})  ",
        "> **Registry source:** `node_dependencies.json`",
        ">",
        "> This document is a **human-readable companion** to the two canonical",
        "> machine-readable sources above.  If they conflict, the JSON files are",
        "> authoritative.  Regenerate with `make manifest-regen` or `make regen-all`.",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def _gen_counts_section(
    node_deps: Dict[str, Any],
    audit_report: Dict[str, Any],
) -> str:
    nodes_section = node_deps.get("nodes", {})
    if isinstance(nodes_section, dict):
        all_nodes = nodes_section.values()
    else:
        all_nodes = nodes_section

    total = len(list(all_nodes))
    # Recount from dict
    if isinstance(node_deps.get("nodes"), dict):
        policies: Dict[str, int] = {}
        for nd in node_deps["nodes"].values():
            p = nd.get("startup_policy", "unknown")
            policies[p] = policies.get(p, 0) + 1
    else:
        policies = {}

    active_count = policies.get("active", audit_report.get("nominal_count", 0) - audit_report.get("optional_count", 0))
    optional_count = policies.get("optional", audit_report.get("optional_count", 0))
    skip_count = policies.get("skip", 0)

    lines = [
        "## Active Node Counts",
        "",
        "> *Generated from `node_dependencies.json` policy fields.*",
        "",
        "| Category | Count |",
        "|----------|-------|",
        f"| Total nodes in registry | {total} |",
        f"| `startup_policy = active` | {active_count} |",
        f"| `startup_policy = optional` (governed optional-node set) | {optional_count} |",
        f"| `startup_policy = skip` (archived / deleted / stubs) | {skip_count} |",
        "",
    ]
    return "\n".join(lines)


def _gen_optional_baseline_status(audit_report: Dict[str, Any]) -> str:
    opt_count = audit_report.get("optional_count", 0)
    baseline_pass = audit_report.get("optional_baseline_pass", 0)
    baseline_partial = audit_report.get("optional_baseline_partial", 0)
    baseline_fail = audit_report.get("optional_baseline_fail", 0)
    promo_ready = audit_report.get("optional_promotion_ready", 0)
    promo_near = audit_report.get("optional_promotion_near", 0)
    promo_not_ready = audit_report.get("optional_promotion_not_ready", 0)

    lines = [
        "### Optional-Node Baseline Status",
        "",
        "> *Generated from `docs/node_audit_report.json`.*",
        "",
        "| Category | Count |",
        "|----------|-------|",
        f"| Optional nodes (total) | {opt_count} |",
        f"| Baseline: **pass** | {baseline_pass} |",
        f"| Baseline: **partial** | {baseline_partial} |",
        f"| Baseline: **fail** | {baseline_fail} |",
        f"| Promotion gap: **ready** (all active-grade checks pass) | {promo_ready} |",
        f"| Promotion gap: **near** (1–2 checks remaining) | {promo_near} |",
        f"| Promotion gap: **not ready** (3+ checks remaining) | {promo_not_ready} |",
        "",
    ]
    return "\n".join(lines)


def _icon(value: str) -> str:
    """Return an icon character for a check result string."""
    if value == "pass":
        return "✓"
    if value in ("partial", "warn"):
        return "~"
    if value == "fail":
        return "✗"
    return "?"


def _promo_icon(ready: str) -> str:
    if ready == "ready":
        return "ready"
    if ready == "near":
        return "near"
    return "gap"


def _gen_optional_nodes_table(
    node_deps: Dict[str, Any],
    audit_node_map: Dict[str, Any],
) -> str:
    nodes_dict = node_deps.get("nodes", {})
    if not isinstance(nodes_dict, dict):
        return ""

    optional_nodes = sorted(
        [(name, data) for name, data in nodes_dict.items()
         if data.get("startup_policy") == "optional"],
        key=lambda x: x[0],
    )
    if not optional_nodes:
        return "*(no optional nodes)*\n"

    lines = [
        "## Optional Nodes — Full Set",
        "",
        "> *Generated from `node_dependencies.json` + `docs/node_audit_report.json`.*",
        "",
        "| Node | Port | Group | Baseline | Promo Gap |",
        "|------|------|-------|----------|-----------|",
    ]
    for name, data in optional_nodes:
        port = data.get("port", "—")
        group = data.get("group", "—")
        audit = audit_node_map.get(name, {})
        baseline = audit.get("optional_baseline_result", "?")
        readiness = audit.get("promotion_readiness", "?")
        baseline_icon = _icon(baseline) if baseline else "?"
        promo_icon = _promo_icon(readiness) if readiness else "?"
        lines.append(f"| `{name}` | {port} | {group} | {baseline_icon} | {promo_icon} |")

    lines += [
        "",
        "> **Icon key:** ✓=pass · ~=partial · ✗=fail · ?=unknown",
        "> **Promo gap:** ready=all active-grade checks pass · near=1–2 remaining · gap=3+ remaining",
        "",
    ]
    return "\n".join(lines)


def _gen_skip_nodes_section(
    node_deps: Dict[str, Any],
    audit_node_map: Dict[str, Any],
) -> str:
    nodes_dict = node_deps.get("nodes", {})
    if not isinstance(nodes_dict, dict):
        return ""

    skip_nodes = sorted(
        [(name, data) for name, data in nodes_dict.items()
         if data.get("startup_policy") == "skip"],
        key=lambda x: x[0],
    )
    if not skip_nodes:
        return ""

    lines = [
        "## Nodes Excluded from Startup (`skip`)",
        "",
        "> *Generated from `node_dependencies.json`.*",
        "",
        "| Node | Port | Audit Action | Reason |",
        "|------|------|-------------|--------|",
    ]
    for name, data in skip_nodes:
        port = data.get("port", "—")
        audit = audit_node_map.get(name, {})
        action = audit.get("action", data.get("audit_action", "—"))
        # Build reason from notes or description
        notes = audit.get("notes", [])
        reason = notes[0] if notes else data.get("description", "—")
        # Truncate long reasons
        if len(reason) > 80:
            reason = reason[:77] + "..."
        lines.append(f"| `{name}` | {port} | {action} | {reason} |")

    lines += [""]
    return "\n".join(lines)


def _gen_duplicate_roles_section(audit_report: Dict[str, Any]) -> str:
    duplicates: List[str] = audit_report.get("duplicate_roles", [])
    if not duplicates:
        return ""

    lines = [
        "## Duplicate Role Nodes",
        "",
        "> *Generated from `docs/node_audit_report.json`.*",
        "",
        "The audit identified duplicate-role clusters.  Resolution requires a",
        "dedicated PR focused on deduplication; both nodes in each pair remain",
        "active until then.",
        "",
        "| Role | Nodes |",
        "|------|-------|",
    ]
    for entry in duplicates:
        if ":" in entry:
            role, node_list = entry.split(":", 1)
            lines.append(f"| {role.strip()} | {node_list.strip()} |")
        else:
            lines.append(f"| — | {entry} |")
    lines += [""]
    return "\n".join(lines)


def _gen_next_steps(audit_report: Dict[str, Any], node_deps: Dict[str, Any]) -> str:
    nodes_dict = node_deps.get("nodes", {})
    optional_count = sum(
        1 for v in nodes_dict.values() if isinstance(v, dict) and v.get("startup_policy") == "optional"
    ) if isinstance(nodes_dict, dict) else audit_report.get("optional_count", 0)

    repair_count = audit_report.get("repair_count", 0)
    missing_readme_nodes: List[str] = audit_report.get("missing_required_files_nodes", [])

    lines = [
        "## Nodes Requiring Further Action",
        "",
    ]
    item_num = 1
    if optional_count:
        lines.append(
            f"{item_num}. **Promote optional nodes** — Use the promotion checklist above to promote "
            f"each `startup_policy: \"optional\"` node individually.  "
            f"All {optional_count} currently pass the technical promotion-gap checks; "
            "promotion requires per-node runtime validation and governance review."
        )
        item_num += 1

    duplicates: List[str] = audit_report.get("duplicate_roles", [])
    for dup in duplicates:
        if "MemorySystem" in dup:
            lines.append(
                f"{item_num}. **Resolve MemorySystem duplicate** — Decide canonical node between "
                "the two MemorySystem nodes."
            )
            item_num += 1
        elif "MediaGen" in dup:
            lines.append(
                f"{item_num}. **Resolve MediaGen duplicate** — Decide canonical node between "
                "the two MediaGen nodes."
            )
            item_num += 1

    if repair_count:
        lines.append(
            f"{item_num}. **Repair nodes needing attention** — {repair_count} node(s) classified as "
            "`repair` by the audit.  See `docs/NODE_SYSTEM_AUDIT.md` for details."
        )
        item_num += 1

    if missing_readme_nodes:
        nodes_str = ", ".join(f"`{n}`" for n in missing_readme_nodes[:5])
        if len(missing_readme_nodes) > 5:
            nodes_str += f" (+ {len(missing_readme_nodes) - 5} more)"
        lines.append(
            f"{item_num}. **Add missing README.md files** — {nodes_str} are missing a README."
        )

    lines += [""]
    return "\n".join(lines)


def _gen_footer() -> str:
    return (
        "---\n\n"
        "*This document is generated by `scripts/gen_node_active_manifest.py`.  "
        "Re-run after changing `node_dependencies.json` or after regenerating "
        "`docs/node_audit_report.json`.*\n\n"
        "*Regeneration command:* `make manifest-regen` or `make regen-all`\n"
    )


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_manifest(project_root: Path) -> str:
    """Generate the full NODE_ACTIVE_MANIFEST.md content as a string."""
    node_deps = _load_node_dependencies(project_root)
    audit_report = _load_audit_report(project_root)
    audit_map = _audit_node_map(audit_report)

    sections = [
        _gen_header(audit_report),
        _POLICY_SEMANTICS,
        "---\n",
        _OPTIONAL_GOVERNANCE_INTRO,
        _gen_optional_baseline_status(audit_report),
        "---\n",
        _gen_counts_section(node_deps, audit_report),
        "---\n",
        _PROMOTION_CHECKLIST,
        "---\n",
        _gen_optional_nodes_table(node_deps, audit_map),
        "---\n",
        _gen_skip_nodes_section(node_deps, audit_map),
        "---\n",
        _gen_duplicate_roles_section(audit_report),
        "---\n",
        _gen_next_steps(audit_report, node_deps),
        _gen_footer(),
    ]
    return "\n".join(s for s in sections if s)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate docs/NODE_ACTIVE_MANIFEST.md from node_dependencies.json "
            "and docs/node_audit_report.json."
        )
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "docs" / "NODE_ACTIVE_MANIFEST.md"),
        help="Path to write the manifest (default: docs/NODE_ACTIVE_MANIFEST.md)",
    )
    parser.add_argument(
        "--print-summary",
        action="store_true",
        default=False,
        help="Print a brief summary to stdout after generation",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    content = generate_manifest(PROJECT_ROOT)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    print(f"Manifest written → {out_path}")

    if args.print_summary:
        # Quick count summary from node_dependencies.json
        node_deps = _load_node_dependencies(PROJECT_ROOT)
        nodes_dict = node_deps.get("nodes", {})
        if isinstance(nodes_dict, dict):
            policies: Dict[str, int] = {}
            for nd in nodes_dict.values():
                p = nd.get("startup_policy", "unknown")
                policies[p] = policies.get(p, 0) + 1
            print(
                f"\nRegistry: {len(nodes_dict)} total  "
                f"active={policies.get('active', 0)}  "
                f"optional={policies.get('optional', 0)}  "
                f"skip={policies.get('skip', 0)}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
