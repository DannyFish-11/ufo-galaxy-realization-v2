# Galaxy — Startup Tier Model & Active-Node Readiness Baseline

> **Authority**: `core/startup_tier_model.py` (`STARTUP_TIER_MODEL_AUTHORITY`)  
> **Canonical config**: `node_dependencies.json` (`_startup_tier_model` key)  
> **Launcher helpers**: `launcher/node_startup.py` (`NodeSystemLauncher`)  
> **Validation**: `scripts/validate_runtime.py` § 7  
>
> This document is the concise, canonical reference for startup tiers and the
> active-node readiness baseline.  It does **not** replace `startup_policy`
> governance — tiers are a read-only view over existing metadata.

---

## 1. Startup Tier Model

Galaxy defines three canonical startup tiers.  Each tier is a strict superset
of the previous: **Core ⊂ Standard ⊂ Full**.

| Tier | Selection rule | Node count | Purpose |
|------|----------------|-----------|---------|
| **Core** | `startup_policy="active"` AND `group="core"` | ~13 | Minimum canonical runtime boot |
| **Standard** | `startup_policy="active"` AND `group` ∈ `{core, development}` | ~30 | Normal development/functional boot |
| **Full** | `startup_policy` ∈ `{active, optional}` | ~124 | All active + governed optional nodes; broad runtime boot |

### What each tier means

**Core** — The essential system foundation.  Includes the State Machine, OneAPI
gateway, Tasker, Auth, Router, Filesystem, Git, Fetch, Sandbox, and core
orchestration/management nodes.  A system cannot be considered runnable if any
Core-tier node fails to start.

**Standard** — Adds active development-tooling nodes (Slack, GitHub, databases,
OCR, translation, search, etc.).  Core-tier failures remain blocking; failures
of Standard-only nodes degrade capability but do not halt the system.

**Full** — The complete production node surface: all active nodes plus governed
optional nodes.  Optional node failures are tolerated (soft-fail).  Nodes with
`startup_policy="skip"` are **never started** in any tier.

### Invariants

1. Core ⊂ Standard ⊂ Full (each tier is a strict superset of the previous).
2. `startup_policy` is the canonical governance field — tiers are a derived
   read-only view; they do not introduce a second config authority.
3. `"skip"` policy excludes nodes from all tiers unconditionally.
4. Tier membership is computed at runtime from `node_dependencies.json` — there
   is no separate tier registry to keep in sync.

---

## 2. Using Tiers from the Launcher

The `NodeSystemLauncher` in `launcher/node_startup.py` exposes tier-aware
helpers.  Use these instead of manual policy/group filtering.

```python
from launcher import NodeSystemLauncher

launcher = NodeSystemLauncher(service_manager, config)

# Get nodes for each tier
core_nodes     = launcher.get_tier_nodes(launcher.STARTUP_TIER_CORE)
standard_nodes = launcher.get_tier_nodes(launcher.STARTUP_TIER_STANDARD)
full_nodes     = launcher.get_tier_nodes(launcher.STARTUP_TIER_FULL)

# Compact readiness baseline snapshot
baseline = launcher.get_readiness_baseline()
print(baseline["summary"])
# → {core_tier_count: 13, standard_tier_count: 30,
#    active_baseline_count: N, optional_governed_count: M,
#    readiness_gap_count: K}
```

### Tier constant mapping

| Constant | Value |
|----------|-------|
| `NodeSystemLauncher.STARTUP_TIER_CORE` | `"Core"` |
| `NodeSystemLauncher.STARTUP_TIER_STANDARD` | `"Standard"` |
| `NodeSystemLauncher.STARTUP_TIER_FULL` | `"Full"` |

### Relationship to existing `start_all()` / `get_core_nodes()`

| Existing method | Equivalent tier helper |
|-----------------|----------------------|
| `get_core_nodes()` | `get_tier_nodes("Core")` |
| `get_active_nodes()` | `get_tier_nodes("Full")` |
| `start_all(minimal=True)` | Start first 10 nodes from `get_tier_nodes("Core")` |

The tier helpers are additive — they do **not** replace the existing methods.

---

## 3. Active-Node Readiness Baseline

The readiness baseline provides a compact, checkable view that distinguishes:

| Category | Definition |
|----------|-----------|
| **active_baseline** | `startup_policy="active"` + `main.py` + `fusion_entry.py` present |
| **core_tier** | Subset of active_baseline where `group="core"` |
| **standard_tier** | Subset of active_baseline where `group` ∈ `{core, development}` |
| **optional_governed** | `startup_policy="optional"` + `main.py` + `fusion_entry.py` present |
| **readiness_gaps** | `startup_policy="active"` + `main.py` present + `fusion_entry.py` **missing** |

### Acceptance bar

- **Core-tier nodes** must have **zero readiness gaps**.  A Core node with a
  missing `fusion_entry.py` is a blocking governance issue.
- **Standard-tier nodes** should have zero readiness gaps.
- **Active baseline** node count should equal or exceed the `active` policy
  count (gaps are tracked governance defects, not design intent).
- **Optional governed** count reflects the health of the optional pool.
- **Readiness gap** count should trend toward zero over time.

### Building the baseline

```python
from core.startup_tier_model import build_readiness_baseline

baseline = build_readiness_baseline()
print(baseline.summary())
# → {core_tier_count, standard_tier_count, active_baseline_count,
#    optional_governed_count, readiness_gap_count}

# Check whether Core tier is gap-free
assert baseline.is_core_complete(), f"Core gaps: {baseline.readiness_gaps}"
```

---

## 4. Validation

Run the validation script to verify the tier model in a repeatable way:

```bash
# Human-readable output
python scripts/validate_runtime.py

# JSON output (for CI)
python scripts/validate_runtime.py --json

# Fail on warnings too
python scripts/validate_runtime.py --strict
```

Section 7 of the validator checks:

- `core.startup_tier_model` is importable and sentinels are set.
- `node_dependencies.json` contains `_startup_tier_model` metadata with all
  three tier definitions.
- `NodeSystemLauncher` exposes tier constants and helper methods.
- Readiness baseline is coherent (Core ⊂ Standard, Core gap-free, counts
  within expected bounds).
- `docs/STARTUP_TIER_MODEL.md` exists.

---

## 5. Startup Tier Acceptance Criteria

| Tier | Acceptance |
|------|-----------|
| **Core** | All Core-tier nodes start successfully.  System is not runnable if any Core node fails. |
| **Standard** | All Standard-tier nodes start successfully (for full dev session).  Core failures remain blocking. |
| **Full** | All active nodes start; optional failures tolerated (soft-fail); `skip` nodes never started. |

---

## 6. Relationship to Existing Governance

This tier model is **additive** to the existing `startup_policy` governance:

```
node_dependencies.json
  └── startup_policy (canonical governance field — unchanged)
  └── group (existing metadata — unchanged)
  └── _startup_tier_model (metadata section — new, read-only tier definitions)

launcher/node_startup.py
  └── get_tier_nodes(tier)   ← NEW: tier-aware query
  └── get_readiness_baseline() ← NEW: compact baseline snapshot
  └── get_core_nodes()       ← existing (equivalent to Core tier)
  └── get_active_nodes()     ← existing (equivalent to Full tier)
  └── start_all()            ← existing (unchanged)

core/startup_tier_model.py   ← NEW: authority sentinel + standalone helpers
scripts/validate_runtime.py  ← EXTENDED: section 7 tier checks
docs/STARTUP_TIER_MODEL.md   ← NEW: this document
```

No existing launcher path, config format, or governance authority is replaced.
