# Runtime Projection Object — Design Document

> **PR-3** — builds on PR-2 (Model Supply Topology Core).

---

## Why This Object Exists

The OpenClawd runtime now maintains several rich, independent state objects:

| Object | Source | What it captures |
|--------|--------|-----------------|
| `ContinuumState` | `core/continuum/types.py` | Tri-state phase, runtime domain, presence/coherence/tendency metrics |
| `TopologyRoutePlan` | `core/model_topology/topology_router.py` | Primary model, support models, weight topology, route reason |
| Device/execution context | caller-supplied | Active device IDs, execution stage, current task summary |

Each object answers a different question about the system's current posture.
However, consumers like the **desktop status board v2** and future **spatial
projection layers** need a single, coherent snapshot rather than three
separate structures to query and reconcile.

`RuntimeProjection` is that snapshot.  It is:

- **Unified** — one object per projection cycle, sourcing from all three layers.
- **Additive** — it does not replace or modify any existing API or state object.
- **Wire-safe** — fully serialisable to dict/JSON with stable, predictable types.
- **Optional-safe** — callers can omit the route plan or execution summary; the
  resulting projection is still valid (unused fields default to `None`/empty).

---

## Fields and Sources

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `tri_state_phase` | `TriStatePhase` | `ContinuumState.tri_state_phase` | Public three-state view of the system. Always set. |
| `runtime_domain` | `RuntimeDomain \| None` | `ContinuumState.runtime_domain` | Execution domain. `None` when undetermined. |
| `presence_intensity` | `float \| None` | `ContinuumState.presence_intensity` | EMA-smoothed overall presence strength [0, 1]. |
| `coherence` | `float \| None` | `ContinuumState.coherence` | How coherent the current intent signal is [0, 1]. |
| `collapse_tendency` | `float \| None` | `ContinuumState.collapse_tendency` | Push toward liminal→manifest collapse [0, 1]. |
| `retreat_tendency` | `float \| None` | `ContinuumState.retreat_tendency` | Push toward retreat/receding [0, 1]. |
| `primary_model_id` | `str \| None` | `TopologyRoutePlan.primary_model.node_id` | Top-ranked model node ID. `None` if no plan. |
| `support_model_ids` | `list[str]` | `TopologyRoutePlan.support_models` | Ordered support model node IDs. |
| `active_weights` | `dict[str, float]` | `TopologyRoutePlan.active_weights` | `model_id → combined_weight` for all routed nodes. |
| `route_reason` | `str \| None` | `TopologyRoutePlan.route_reason` | Human-readable routing decision explanation. |
| `active_device_ids` | `list[str]` | `ExecutionSummary.active_device_ids` | Currently active device IDs. |
| `execution_stage` | `str \| None` | `ExecutionSummary.execution_stage` | Current execution stage tag. |
| `current_task_summary` | `str \| None` | `ExecutionSummary.current_task_summary` | Short description of the active task. |
| `timestamp` | `float` | `time.time()` at build time | Unix epoch seconds when the projection was assembled. |

### Notes on field semantics

- **`tri_state_phase`** — always sourced from `ContinuumState.tri_state_phase`
  (the public property), which collapses the internal `receding` phase to
  `silent`.  The projection never exposes internal `ContinuumPhase` values.
- **`active_weights`** — the `ModelWeightField.combined_weight` float is
  extracted from the `TopologyRoutePlan.active_weights` dict so that downstream
  consumers receive a plain `dict[str, float]` rather than needing to import
  `ModelWeightField`.
- **`presence_intensity`** — even though `ContinuumState` guarantees a float
  (defaulting to `0.0`), the projection field is typed `float | None` to allow
  callers who construct `RuntimeProjection` directly to distinguish "not yet
  measured" from `0.0`.

---

## Module Layout

```
core/projection/
├── __init__.py              — public surface (RuntimeProjection, build_runtime_projection, ExecutionSummary)
├── runtime_projection.py    — RuntimeProjection Pydantic model + to_dict/to_json
└── projection_compiler.py   — build_runtime_projection() + ExecutionSummary placeholder
```

---

## How to Build a Projection

### Minimal (continuum state only)

```python
from core.projection import build_runtime_projection
from core.continuum.types import ContinuumState, ContinuumPhase

state = ContinuumState(phase=ContinuumPhase.LIMINAL, coherence=0.6)
projection = build_runtime_projection(state)

print(projection.tri_state_phase)   # TriStatePhase.LIMINAL
print(projection.to_dict())
```

### With a topology route plan (PR-2)

```python
from core.projection import build_runtime_projection
from core.model_topology import TopologyRouter, ProviderInventory
from core.continuum.types import ContinuumState, ContinuumPhase, RuntimeDomain

state = ContinuumState(
    phase=ContinuumPhase.MANIFEST,
    runtime_domain=RuntimeDomain.LOCAL,
    coherence=0.85,
)
router = TopologyRouter(inventory)  # ProviderInventory from your config
plan = router.route(state.tri_state_phase, state.runtime_domain)

projection = build_runtime_projection(state, route_plan=plan)
print(projection.primary_model_id)   # e.g. "node-openai-gpt5"
print(projection.active_weights)     # {"node-openai-gpt5": 1.4, ...}
```

### With full context (route plan + execution summary)

```python
from core.projection import build_runtime_projection, ExecutionSummary

summary = ExecutionSummary(
    active_device_ids=["win-desktop", "android-phone"],
    execution_stage="executing",
    current_task_summary="Draft weekly report",
)

projection = build_runtime_projection(state, route_plan=plan, execution_summary=summary)
payload = projection.to_dict()   # ready for JSON transport
```

---

## Serialisation

`RuntimeProjection.to_dict()` returns a plain Python dict with:

- Enum values serialised to their string `value` (e.g. `"liminal"`, `"local"`).
- `None` fields preserved as `None` (not omitted).
- `active_weights` as `dict[str, float]`.

`RuntimeProjection.to_json(**kwargs)` delegates to `json.dumps(self.to_dict(), **kwargs)`.

### Example output

```json
{
  "tri_state_phase": "manifest",
  "runtime_domain": "local",
  "presence_intensity": 0.9,
  "coherence": 0.8,
  "collapse_tendency": 0.7,
  "retreat_tendency": 0.05,
  "primary_model_id": "node-openai-gpt5-4",
  "support_model_ids": ["node-anthropic-claude-opus-4-6", "node-local-llama3"],
  "active_weights": {
    "node-openai-gpt5-4": 1.89,
    "node-anthropic-claude-opus-4-6": 1.62,
    "node-local-llama3": 0.27
  },
  "route_reason": "MANIFEST/LOCAL: native-multimodal primary; 2 support node(s)",
  "active_device_ids": ["win-desktop"],
  "execution_stage": "executing",
  "current_task_summary": "Draft weekly report",
  "timestamp": 1700000001.0
}
```

---

## How It Feeds Downstream Consumers

### Desktop Status Board v2

The status board can subscribe to `RuntimeProjection` snapshots (e.g. via the
state event bus or a polling endpoint) and render:

- **Tri-state phase indicator** ← `tri_state_phase`
- **Execution domain badge** ← `runtime_domain`
- **Presence / coherence bars** ← `presence_intensity`, `coherence`
- **Collapse / retreat tendency** ← `collapse_tendency`, `retreat_tendency`
- **Model topology panel** ← `primary_model_id`, `support_model_ids`, `active_weights`
- **Route reason tooltip** ← `route_reason`
- **Active devices list** ← `active_device_ids`
- **Execution stage tag** ← `execution_stage`
- **Task summary line** ← `current_task_summary`

### Spatial Projection Layers

Future spatial rendering layers (transparent desktop overlays, three-state
space transitions) can use `tri_state_phase` + `runtime_domain` + continuum
metrics to drive their animation/geometry:

- `presence_intensity` → opacity / scale of the projection surface
- `coherence` → sharpness / focus of the rendered form
- `collapse_tendency` → push toward manifest-stage materialisation
- `retreat_tendency` → push toward dissolve / receding animation
- `active_weights` → per-model-node visual weight in the topology display

---

## Design Constraints

1. **No UI semantics in this package** — `core/projection/` must not import
   from any dashboard, widget, or frontend module.
2. **No modification of existing APIs** — `ContinuumState`, `TopologyRoutePlan`,
   and all PR-1/PR-2 types are consumed read-only.
3. **Additive only** — existing callers are unaffected; new callers opt-in by
   calling `build_runtime_projection`.
4. **Internal `receding` phase is never exposed** — `tri_state_phase` always
   reflects the public `TriStatePhase` (via `ContinuumState.tri_state_phase`).

---

## Related Documents

- [`docs/OPENCLAWD_STATE_CONTINUUM.md`](OPENCLAWD_STATE_CONTINUUM.md) — state
  continuum protocol and `ContinuumState` schema.
- [`docs/MODEL_SUPPLY_TOPOLOGY.md`](MODEL_SUPPLY_TOPOLOGY.md) — model supply
  topology core (PR-2), `TopologyRoutePlan`, `ModelWeightField`.
- [`docs/MODEL_TOPOLOGY_BRIDGE.md`](MODEL_TOPOLOGY_BRIDGE.md) — legacy-to-V2
  bridge for provider snapshots.
- [`docs/WINDOWS_STATUS_BOARD.md`](WINDOWS_STATUS_BOARD.md) — desktop status
  board (v1); v2 will consume `RuntimeProjection`.
