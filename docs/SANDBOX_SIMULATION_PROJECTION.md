# Sandbox Simulation / Speculative Execution Field

> **Version:** PR-5 (formalize-liminal-mapping)

---

## 1. Overview

The **sandbox simulation / speculative execution field** is the third allowed
content class in liminal space.  It represents execution paths that are
*hypothetical*, *simulative*, or *sandboxed* — they have not yet been committed
to either the local execution chain or the cross-device execution chain.

This field exists so that the liminal layer can show the runtime *exploring*
potential execution paths before committing to one.

---

## 2. Definitions

### 2.1 Speculative Execution

A speculative execution branch is a path that the runtime has *started*
evaluating but has not yet committed.  The routing authority (OpenClawd) may
be simultaneously considering multiple paths:

- Execute locally?
- Dispatch cross-device?
- Defer (remain silent)?

The speculative field shows which candidates are live before the commitment
decision is made.

### 2.2 Sandbox Simulation

A sandbox simulation is a *safe* execution of a plan against a sandboxed or
synthetic environment, without side-effects to the live system.  It may be
used to:
- Pre-validate a multi-step task plan before committing it.
- Simulate device interactions on a virtual device model.
- Run speculative reasoning scenarios for operator review.

### 2.3 Simulation Summary

`SimulationSummary` is the canonical serialisable structure that captures the
current sandbox/speculative execution state for liminal-space consumption.

Fields:

| Field | Type | Description |
|-------|------|-------------|
| `summary_id` | `str` | Auto-generated UUID |
| `is_active` | `bool` | Whether a simulation is currently running |
| `simulation_kind` | `str` | `"speculative"`, `"sandbox"`, or `"none"` |
| `candidate_paths` | `list[str]` | Candidate execution path labels under evaluation |
| `committed_path` | `str \| None` | The path committed to (or `None` if still speculative) |
| `scenario_label` | `str \| None` | Human-readable label for the scenario |
| `step_count` | `int` | Number of simulation steps completed |
| `is_committed` | `bool` | Whether this simulation has resolved to a committed path |
| `timestamp` | `float` | UNIX timestamp |

---

## 3. Relationship to Execution Chains

The three liminal-space content classes form a progression:

```
SimulationSummary          ←  speculative / uncommitted field
    │
    │  commit decision (OpenClawd routing authority)
    ▼
LocalChainView             ←  committed local execution
CrossDeviceChainView       ←  committed cross-device execution
```

A simulation can resolve into either the local chain or the cross-device
chain.  Before it resolves, it lives entirely in the speculative field.

---

## 4. Spatial Representation in Liminal Space

In the liminal surface rendering:

- **Active simulation** is shown with a `[SIM]` or `[SPECULATIVE]` label.
- **Candidate paths** are listed as branching options.
- **Committed path** (when present) shows which branch was selected.
- **Sandbox** simulation is distinguished from speculative by a `[SANDBOX]`
  label.

Example (text/CLI rendering):

```
  ┌─ Sandbox / Speculative ──────────────────────────┐
  │  Kind     : speculative
  │  Active   : Yes
  │  Paths    : local | cross_device
  │  Committed: (pending)
  │  Steps    : 0
  └──────────────────────────────────────────────────┘
```

When no simulation is active:

```
  ┌─ Sandbox / Speculative ──────────────────────────┐
  │  (no active simulation)
  └──────────────────────────────────────────────────┘
```

---

## 5. Scope and Constraints

- `SimulationSummary` is **read-only** — it describes a state; it does not
  trigger execution.
- It must not include model-routing details (those belong on the right-side
  status board).
- It must not duplicate fields from `LocalChainView` or `CrossDeviceChainView`.
- It is suitable for embedding in debug/audit endpoints and liminal-surface
  renderers.

---

## 6. Structural Location

```python
from core.liminal_space_mapping import SimulationSummary, build_simulation_summary
```

Full documentation for `LiminalSpaceMap` (which wraps all three content
classes) is in `docs/LIMINAL_SPACE_MAPPING.md`.

---

## 7. References

- `core/liminal_space_mapping.py` — canonical structures
- `docs/LIMINAL_SPACE_MAPPING.md` — full liminal space definition
- `docs/LOCAL_EXECUTION_CHAIN.md` — local chain
- `docs/CROSS_DEVICE_EXECUTION_CHAIN.md` — cross-device chain
- `windows_client/status_board_v2/liminal_surface.py` — surface renderer
