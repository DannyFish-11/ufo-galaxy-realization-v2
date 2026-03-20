# Model Supply Topology — Design Document

> **Package:** `core/model_topology/`  
> **PR:** V2 PR-2 (Model Supply Topology Core)  
> **Depends on:** PR-1 (Topology Config Bridge — `ProviderInventory`, `AggregatorRouterHint`)

---

## Overview

The Model Supply Topology Core turns the bridge outputs from PR-1 into a true
**graph-based model supply topology** with weighted routing.  It answers the
question: *given the current system phase and execution scope, which model(s)
should be activated, and in what priority order?*

Key design principles:

1. **Native multimodal models have the highest base priority.**  They always
   anchor the primary slot in `silent` and `liminal` phases.
2. **Deterministic ordering.**  Identical inputs always produce the same route
   plan.  Ties in combined weight are broken by `node_id` lexicographic order.
3. **Additive.**  Nothing in this PR modifies existing routing, LLM-manager, or
   dashboard code.  All new symbols are in `core/model_topology/`.
4. **No UI semantics.**  The topology core produces data structures; it has no
   knowledge of the status board or any frontend.

---

## Architecture

```
ProviderInventory ──────────────────────────────────────┐
  (from PR-1 ConfigBridge)                              │
                                                        ▼
AggregatorRouterHint[] ─────────────────▶  TopologyRouter
  (from PR-1 ConfigBridge)                      │
                                                │ builds
                                                ▼
                                       ModelSupplyGraph
                                        ├── ModelNode[]
                                        └── GraphEdge[]
                                                │
                                    applies ModelWeightField
                                    per (TriStatePhase × RuntimeDomain)
                                                │
                                    runs routing_policy selection
                                                │
                                                ▼
                                       TopologyRoutePlan
                                         ├── primary_model
                                         ├── support_models[]
                                         ├── active_weights{}
                                         └── route_reason
```

---

## Module Reference

### `model_node.py` — ModelNode + EdgeKind + LocalityHint

**`ModelNode`** is the atomic unit of the graph.  It wraps the PR-1
`NormalizedTopologyEntry` fields plus:

| Field | Description |
|---|---|
| `node_id` | Unique identifier (`provider_id` by convention) |
| `topology_role` | Primary role used by routing policy |
| `role_hints` | Full list including secondary roles |
| `locality_hints` | `LOCAL`, `REMOTE`, `CROSS_DEVICE`, or `ANY` |
| `base_weight` | Static weight: `(composite_score / 10 + role_addend) × multimodal_multiplier` |
| `dynamic_weight` | Runtime weight updated by `ModelWeightField` |

**Base weight formula:**

```
composite  = (speed_score + quality_score) / 20   # 0.0 – 1.0
role_add   = per-role addend (MULTIMODAL_CORE = 2.0, highest)
base       = composite + role_add
if native_multimodal:
    base  *= 1.5   # native multimodal multiplier
```

This ensures **native multimodal nodes always receive the highest base weight**
when quality/speed are equal.

**`EdgeKind`** values: `SUPPORT`, `SUBSTITUTE`, `AGGREGATE`.

**`LocalityHint`** values: `LOCAL`, `REMOTE`, `CROSS_DEVICE`, `ANY`.

---

### `model_supply_graph.py` — ModelSupplyGraph

Holds a **node registry** (dict) and **typed edges** (list of `GraphEdge`).

Key queries (all return deterministically sorted lists):

| Method | Description |
|---|---|
| `primary_multimodal_cores()` | Native MM nodes, sorted by `base_weight` desc |
| `available_nodes()` | Nodes with `availability.available == True` |
| `nodes_by_role(role)` | Nodes whose `topology_role` or `role_hints` include `role` |
| `nodes_by_category(cat)` | Nodes of a given `ProviderCategory` |
| `cross_device_capable_nodes()` | Nodes with `CROSS_DEVICE` role or locality hint |

**Construction from inventory:**

```python
graph = ModelSupplyGraph.from_inventory(inventory)
```

Edges are inferred from `inventory.aggregator_hints`:
- The first candidate in each hint becomes the aggregator **anchor**.
- Subsequent candidates receive `AGGREGATE` edges from the anchor.
- Other nodes with a matching role receive `SUPPORT` edges toward the anchor.

---

### `model_weight_field.py` — ModelWeightField

Implements the **tri-state + runtime-domain weight modifiers**.

```
combined_weight = base_weight × state_modifier × domain_modifier
```

**State modifiers** (`TriStatePhase × TopologyRole`):

| Phase | MULTIMODAL_CORE | REASONING | EXECUTION | ROUTING | CROSS_DEVICE |
|---|---|---|---|---|---|
| `silent` | **1.4** | 0.7 | **0.3** | 0.5 | **0.2** |
| `liminal` | **1.3** | **1.3** | 0.6 | **1.3** | 1.0 |
| `manifest` | 1.2 | 1.0 | **1.4** | 1.0 | **1.2** |

**Domain modifiers** (`RuntimeDomain × TopologyRole`):

| Domain | MULTIMODAL_CORE | CROSS_DEVICE | ROUTING |
|---|---|---|---|
| `local` | 1.1 | **0.4** | 1.0 |
| `cross_device` | 1.1 | **1.5** | 1.1 |
| `transition` | 1.1 | 1.1 | **1.2** |

Tie-breaking: `combined_weight` descending → `node_id` ascending.

---

### `routing_policy.py` — PolicyConfig + selection helpers

`PolicyConfig` controls:
- `max_support_models` (default 3)
- `require_multimodal_primary` (default `True`)
- `allow_unavailable_fallback` (default `False`)

Selection logic:
1. **SILENT / LIMINAL:** primary *must* be native multimodal when any MM node
   is available (enforced by `require_multimodal_primary`).
2. **MANIFEST + CROSS_DEVICE:** cross-device capable nodes are promoted to the
   front of the support list.

---

### `topology_router.py` — TopologyRouter + TopologyRoutePlan

**`TopologyRouter`** is the main entry point:

```python
from core.model_topology import TopologyRouter
from core.continuum.types import TriStatePhase, RuntimeDomain

router = TopologyRouter(inventory)
plan = router.route(TriStatePhase.SILENT, RuntimeDomain.LOCAL)
```

**`TopologyRoutePlan`** fields:

| Field | Type | Description |
|---|---|---|
| `primary_model` | `ModelNode \| None` | Highest-ranked model for this phase/domain |
| `support_models` | `List[ModelNode]` | Supporting models in priority order |
| `active_weights` | `Dict[str, ModelWeightField]` | Weight records for all selected nodes |
| `route_reason` | `str` | Human-readable routing decision explanation |
| `phase` | `TriStatePhase` | Phase used for this plan |
| `domain` | `RuntimeDomain` | Domain used for this plan |
| `graph` | `ModelSupplyGraph` | The graph constructed for this plan |

---

## Routing Behaviour per Phase × Domain

| Phase | Domain | Primary | Support emphasis | Cross-device? |
|---|---|---|---|---|
| `silent` | `local` | Native MM (highest bw) | MM + perception | No |
| `silent` | `cross_device` | Native MM | MM + perception | No |
| `liminal` | `local` | Native MM (anchor) | Reasoning + Routing | No |
| `liminal` | `transition` | Native MM (anchor) | Reasoning + Routing | Partial |
| `manifest` | `local` | Native MM or top-ranked | Execution roles | No |
| `manifest` | `cross_device` | Native MM or top-ranked | Execution + **CD specialists** | **Yes** |

### Policy rules (enforced)

1. **Native multimodal = highest base priority** — the `_NATIVE_MULTIMODAL_BASE_MULTIPLIER`
   (×1.5) and `MULTIMODAL_CORE` role addend (+2.0) ensure native MM nodes always
   outrank same-quality non-MM nodes.

2. **`silent`** — state modifiers emphasize `MULTIMODAL_CORE` (×1.4) and
   penalize `EXECUTION` (×0.3) and `CROSS_DEVICE` (×0.2).

3. **`liminal`** — reasoning and routing roles receive equal amplification
   (×1.3) while `MULTIMODAL_CORE` remains the anchor (×1.3, primary slot
   still requires MM).

4. **`manifest`** — execution roles are amplified (×1.4); when domain is
   `CROSS_DEVICE`, the `CROSS_DEVICE` domain modifier (×1.5) promotes
   cross-device specialists into the support list.

---

## How It Consumes PR-1 Bridge Outputs

```
PR-1 outputs               PR-2 consumers
──────────────             ─────────────────────────────
NormalizedTopologyEntry ──▶ node_from_entry()
                           └── ModelNode (base_weight computed)

ProviderInventory       ──▶ ModelSupplyGraph.from_inventory()
                           └── node registry + edge inference

AggregatorRouterHint[]  ──▶ _infer_edges_from_hints()
                           └── AGGREGATE + SUPPORT edges
```

The topology core never calls `ConfigBridge` directly; it only consumes the
stable `ProviderInventory` / `NormalizedTopologyEntry` / `AggregatorRouterHint`
contracts defined in PR-1.

---

## Why It Is Not Tied to UI

- All public types (`ModelNode`, `ModelSupplyGraph`, `TopologyRoutePlan`, etc.)
  are plain Python dataclasses / classes with no web-framework, template, or
  rendering dependencies.
- `TopologyRoutePlan.to_dict()` produces a serialisable plain dict suitable for
  JSON transport — the status board or any projection layer consumes this dict;
  the topology core never consumes the projection layer.
- No imports from `dashboard/`, no FastAPI route definitions, no frontend
  asset generation.

---

## Quick Start

```python
from core.model_topology import (
    ConfigBridge,
    LegacyLLMProviderSnapshot,
    TopologyRouter,
)
from core.continuum.types import TriStatePhase, RuntimeDomain

bridge = ConfigBridge()
snapshots = [LegacyLLMProviderSnapshot.from_dict(d) for d in raw_provider_list]
inventory = bridge.build_inventory(snapshots)

router = TopologyRouter(inventory)

# Route for the current system phase
plan = router.route(TriStatePhase.LIMINAL, RuntimeDomain.LOCAL)
print(plan)
# <TopologyRoutePlan phase=liminal domain=local primary=openai support=[...]>

print(plan.to_dict())
```

---

## Tests

All tests live in `tests/test_model_supply_topology.py`:

| Section | Coverage |
|---|---|
| `TestModelNodeConstruction` | Node construction, base weight, locality hints, role hints |
| `TestModelSupplyGraph` | Graph construction, queries, edges, serialisation |
| `TestModelWeightField` | Weight computation across all phase/domain combinations, tie-breaking |
| `TestTopologyRouter` | Route plan selection, MM anchor enforcement, CD inclusion, determinism |
| `TestEmptyInventory` | Edge cases with empty inventory |
| `TestModuleExports` | All new symbols importable from `core.model_topology` |

Run:

```bash
python -m pytest tests/test_model_supply_topology.py -v
```
