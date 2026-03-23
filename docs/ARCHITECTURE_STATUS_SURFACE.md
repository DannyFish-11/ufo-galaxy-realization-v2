# Architecture Status Surface

> **PR-011** — Add live architecture status surface for runtime readiness.

## Overview

`core/architecture_live_status.py` is the **canonical runtime-facing architecture
status surface** for the Galaxy system.  It converts the post-consolidation
architecture baseline (PR-001 through PR-010) into a single, structured,
JSON-serialisable payload that operators and contributors can query to understand
the operational posture of the system at a glance.

This document describes:
- what the status surface reports
- how runtime readiness is classified
- how this differs from the Architecture Completion Scorecard
- how contributors should update it when architecture changes

---

## What the Status Surface Reports

The surface produces an `ArchitectureLiveStatus` payload with the following
top-level fields:

| Field | Type | Description |
|-------|------|-------------|
| `baseline_version` | `str` | Which PR baseline this report reflects (e.g. `"PR-011"`) |
| `runtime_readiness` | `str` | `"ready"` \| `"partial"` \| `"blocked"` |
| `canonical_paths` | `list[dict]` | Modules/paths confirmed as canonical entry points |
| `legacy_zones` | `list[dict]` | Modules/paths operating in legacy or compatibility mode |
| `scorecard_summary` | `dict` | Compact summary from the Architecture Completion Scorecard |
| `active_blockers` | `list[dict]` | Actionable issues preventing readiness advancement |
| `projection_status` | `dict` | Outward-truth / projection-only alignment status |
| `capability_catalog_status` | `dict` | MCP/Skill/capability ecosystem health |
| `addon_ecosystem_status` | `dict` | Installability and addon contract readiness |
| `cross_device_status` | `dict` | Cross-device execution chain consistency |
| `authority_chain_status` | `dict` | Authority chain validity and ordering |
| `recommended_next_steps` | `list[str]` | Ordered actionable next steps |

### `canonical_paths` entries

Each entry represents a confirmed canonical module/path:

```json
{
  "path": "core.constellation_runtime",
  "role": "canonical dispatcher — primary entry point for all agent requests",
  "pr_introduced": "PR-1"
}
```

### `legacy_zones` entries

Each entry represents a module in legacy or compatibility mode:

```json
{
  "path": "dashboard.backend.main",
  "status": "legacy_ui",
  "superseded_by": "windows_client.status_board_v2",
  "notes": "WebUI management panel — legacy; no longer defines system structure."
}
```

### `active_blockers` entries

Each entry represents an actionable issue:

```json
{
  "dimension": "capability_integration_completeness",
  "severity": "warning",
  "description": "Dimension 'capability_integration_completeness' still has legacy ambiguity — parallel authority paths remain.",
  "recommended_action": "Resolve legacy ambiguity by guardrailing or removing legacy paths."
}
```

---

## Runtime Readiness Classification

The surface classifies the system into one of three readiness postures:

### `ready`

All of the following must hold:
- No architecture dimension is at `LEGACY_AMBIGUITY` or `IN_PROGRESS` maturity (blocking count = 0).
- No active blocker has `"blocking"` severity.
- Projection is confirmed as the sole outward truth (`projection_is_only_outward_truth = true`).
- No legacy ambiguity remains in any dimension.
- No active blocker has `"warning"` severity.

### `partial`

The system is in `partial` posture when `blocked` conditions do not apply, but any of:
- Scorecard has legacy ambiguity in one or more dimensions.
- Projection is not confirmed as the sole outward truth (`false` or `null`).
- Capability catalog or addon ecosystem status is `"partial"` or `"unknown"`.
- At least one active blocker has `"warning"` severity.

### `blocked`

The system is in `blocked` posture when any of:
- One or more architecture dimensions are at `LEGACY_AMBIGUITY` or `IN_PROGRESS` maturity.
- Authority chain status is explicitly `"invalid"`.
- At least one active blocker has `"blocking"` severity.

Rules are evaluated in order: `blocked` → `partial` → `ready`.  The first
matching condition determines the final classification.

---

## Signal Sources

The status surface aggregates signals from the following modules:

| Signal | Source Module | PR |
|--------|--------------|-----|
| Canonical path list | Static registry in `build_architecture_live_status()` | PR-011 |
| Legacy zone registry | `core.ui_surface_authority` + `core.orchestration_authority.legacy_paths` | PR-8/PR-9 |
| Scorecard summary | `core.architecture_completion` | PR-9 |
| Projection status | `core.ui_surface_authority` | PR-8 |
| Cross-device chain | `core.cross_device_execution_chain` | PR-7 |
| Authority chain | `core.orchestration_authority.authority_resolver` | PR-9 |
| Capability catalog | `core.capability_runtime.capability_registry_runtime` | — |
| Addon ecosystem | `core.architecture_completion` (INSTALLABILITY dimension) | PR-9 |

All signal collectors are **fault-tolerant** — if a source module is unavailable,
the collector logs a debug message and returns a graceful fallback dict.

---

## Usage

### Python API

```python
from core.architecture_live_status import (
    get_architecture_live_status,
    build_architecture_live_status,
    RuntimeReadiness,
    BASELINE_VERSION,
)

# Cached singleton (built once per process lifetime)
status = get_architecture_live_status()
print(status.runtime_readiness)           # "partial"
print(status.scorecard_summary["canonical_count"])  # 8

# Force a fresh build (useful in tests)
status = get_architecture_live_status(force_rebuild=True)

# Serialise to JSON
import json
print(json.dumps(status.to_dict(), indent=2))
print(status.to_json(indent=2))

# Clear the cache (use in test teardown)
from core.architecture_live_status import reset_architecture_live_status
reset_architecture_live_status()
```

### Querying readiness programmatically

```python
from core.architecture_live_status import get_architecture_live_status, RuntimeReadiness

status = get_architecture_live_status()

if status.runtime_readiness == RuntimeReadiness.READY.value:
    print("System is production-ready.")
elif status.runtime_readiness == RuntimeReadiness.PARTIAL.value:
    print("System is partially ready. Active blockers:")
    for b in status.active_blockers:
        print(f"  [{b.severity}] {b.dimension}: {b.description}")
else:
    print("System is blocked. Immediate action required.")
    for b in status.active_blockers:
        if b.severity == "blocking":
            print(f"  BLOCKING: {b.recommended_action}")
```

---

## Relationship to the Architecture Completion Scorecard

These two surfaces are **complementary, not duplicates**:

| Aspect | Architecture Completion Scorecard (`core.architecture_completion`) | Architecture Status Surface (`core.architecture_live_status`) |
|--------|-------------------------------------------------------------------|---------------------------------------------------------------|
| **Purpose** | Measures *design maturity* across 10 architecture dimensions | Measures *runtime/operational readiness* as a current posture |
| **Audience** | Contributors reviewing architecture quality | Operators and CI pipelines checking deployment readiness |
| **Granularity** | Per-dimension maturity levels (5-tier scale) | Aggregate readiness verdict + dimension summary |
| **Inputs** | Static dimension evidence from PRs | Dynamic signals from live modules |
| **Output** | `ArchitectureCompletionScorecard` with 10 `DimensionScorecard` entries | `ArchitectureLiveStatus` with a `runtime_readiness` classification |
| **Update cadence** | Updated by the contributor introducing a dimension-changing PR | Rebuilt on each call (with caching) from live module state |

The status surface *consumes* the completion scorecard as one of its inputs
(via `scorecard_summary`), but also aggregates additional live signals to
produce a holistic operational view.

---

## How to Update the Status Surface

### When architecture changes (new canonical path established)

1. Add a `CanonicalPathEntry` to the `_collect_canonical_paths()` function in
   `core/architecture_live_status.py`.
2. Update `BASELINE_VERSION` to reflect the PR that made the change.
3. Update any affected dimension in `core/architecture_completion.py`.
4. Re-run `tests/test_pr50_architecture_live_status.py` to verify.

### When a module is demoted to legacy

1. Add the module to the appropriate source registry:
   - UI surfaces: `core/ui_surface_authority.py`
   - Orchestration paths: `core/orchestration_authority/legacy_paths.py`
2. The status surface picks up these changes automatically via
   `_collect_legacy_zones()`.
3. Update the relevant dimension in `core/architecture_completion.py`.

### When a blocker is resolved

Active blockers are derived automatically from the scorecard. When a blocking
dimension advances to `CANONICALIZED` or `COMPLETE` maturity, the blocker
disappears from the next status build.

### When the readiness classification rules change

Update `_classify_readiness()` in `core/architecture_live_status.py` and add
corresponding tests in `tests/test_pr50_architecture_live_status.py`.

---

## Current Posture (PR-011 Baseline)

As of PR-011, the default posture is **`partial`** because:

- 2 scorecard dimensions retain legacy ambiguity:
  - `capability_integration_completeness` — PARTIAL maturity; capability integration through canonical catalog not fully enforced
  - `installability_ecosystem_readiness` — PARTIAL maturity; GitHub-installable MCP/Skill addon contracts not fully CI-tested
- Projection alignment is **confirmed** (`projection_is_only_outward_truth: true`)
- Authority chain is **valid**
- 0 blocking dimensions (no LEGACY_AMBIGUITY or IN_PROGRESS)

Advancing to `ready` requires resolving the 2 legacy-ambiguity dimensions.

---

## Tests

Tests are in `tests/test_pr50_architecture_live_status.py` (90 tests).

Coverage includes:
1. `RuntimeReadiness` enum values
2. `CanonicalPathEntry`, `LegacyZoneEntry`, `ActiveBlocker` dataclass fields and serialisation
3. `ArchitectureLiveStatus` field presence and serialisation
4. `build_architecture_live_status()` payload structure and content
5. Singleton helpers (`get_architecture_live_status`, `reset_architecture_live_status`)
6. Readiness classification rules (`_classify_readiness`)
7. Active blocker generation from scorecard data
8. Scorecard summary consistency with `core.architecture_completion`
9. JSON round-trip serialisation
10. `BASELINE_VERSION` constant constraints
