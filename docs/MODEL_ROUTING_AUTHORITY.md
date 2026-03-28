# Model Routing Authority

> **Status:** Canonical — formalised in this PR; strengthened in PR-1 (architecture freeze);
> confirmed unchanged in PR-0 (unified native-multimodal-first architecture freeze).
> **Scope:** Routing authority for projection-facing model/provider selection semantics.
>
> **PR-0 confirmation:** `TopologyRouter` remains the **sole** canonical routing
> authority.  `TopologyRoutePlan` remains the **sole** canonical routing output
> contract.  This is unchanged.  The addition of a configuration entry surface
> inside `status_board_v2` (Phase D) does **not** alter this invariant —
> configuration entry modifies routing inputs (provider inventory, preferences);
> it never bypasses or replaces `TopologyRouter` as the decision-making authority.
>
> Related: [`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](SKY_GROWN_CONSTELLATION_TOPOLOGY.md) ·
> [`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`](DASHBOARD_RETIREMENT_AND_MIGRATION.md) ·
> [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md) ·
> [`docs/ADR_STATUS_BOARD_CONFIG_AUTHORITY.md`](ADR_STATUS_BOARD_CONFIG_AUTHORITY.md)

---

## 1. Overview

This document defines **the single canonical model-routing authority** for the Galaxy
system. It clarifies which components own routing truth, how downstream surfaces consume
that truth, and which legacy structures are retained only as compatibility bridges.

---

## 2. Canonical Routing Authority Path

```
ProviderInventory  ──┐
                     ├──▶  TopologyRouter  ──▶  TopologyRoutePlan  ──▶  Projection consumers
AggregatorRouterHint ┘          │
                                └─ builds ModelSupplyGraph
                                   applies ModelWeightField per node
                                   runs routing_policy selection
```

### 2.1 Canonical authority module

```
core/model_topology/topology_router.py
```

- **`TopologyRouter`** is the **sole** canonical routing decision-maker.  No other
  component has routing-truth authority.
- **`TopologyRoutePlan`** is the **sole** canonical routing output contract.  Any
  routing summary produced outside of a `TopologyRoutePlan` is a legacy
  compatibility artefact, not an authority source.
- `TopologyRouter.route(phase, domain)` produces a deterministic, stable plan.
- All routing-related projection fields (`selected_model`, `selected_provider`,
  `is_native_multimodal`, `support_models`, `route_reason`) must be sourced from a
  `TopologyRoutePlan` whenever one is available.
- **The desktop status board topology display must consume canonical route truth
  from `TopologyRoutePlan` via the projection layer.**  The topology surface
  must never derive its own routing conclusions.
- **The dashboard is not a routing-truth authority surface.**  Dashboard endpoints
  and frontend state may display routing information, but they do not own it and
  must not be treated as the source of truth.
- **Any routing path that does not originate from `TopologyRouter` is a degraded
  compatibility path**, not a canonical alternative.  These paths are registered
  in `core/orchestration_authority/legacy_paths.py` with
  `LegacyPathStatus.LEGACY_COMPATIBILITY`.

The authority is identified by the sentinel:

```python
# core/model_topology/topology_router.py
CANONICAL_ROUTING_AUTHORITY = "core.model_topology.topology_router.TopologyRouter"
```

---

## 3. What `TopologyRoutePlan` Is Responsible For

`TopologyRoutePlan` is the **stable output contract** produced by `TopologyRouter`.  
It carries:

| Field | Description |
|---|---|
| `primary_model` | Top-ranked `ModelNode`; the canonical primary supply |
| `support_models` | Ordered list of supporting `ModelNode` objects |
| `active_weights` | `node_id → ModelWeightField` for every node considered |
| `route_reason` | Human-readable routing explanation |
| `phase` | `TriStatePhase` used for this plan |
| `domain` | `RuntimeDomain` used for this plan |
| `graph` | `ModelSupplyGraph` built for this plan |

`TopologyRoutePlan.to_dict()` is the stable serialisation format consumed by
downstream projection builders.

---

## 4. How Projection Consumers Read Routing Truth

### 4.1 `RuntimeProjection` (`core/projection/runtime_projection.py`)

`RuntimeProjection` is populated by `build_runtime_projection()` in
`core/projection/projection_compiler.py`.

When a `TopologyRoutePlan` is provided:

- `primary_model_id` ← `route_plan.primary_model.node_id`
- `support_model_ids` ← `[n.node_id for n in route_plan.support_models]`
- `active_weights` ← `{node_id: wf.combined_weight ...}`
- `route_reason` ← `route_plan.route_reason`
- `routing_authority` is set to `CANONICAL_ROUTING_AUTHORITY`

When no `TopologyRoutePlan` is provided, routing fields default to `None` /
empty collections.  `routing_authority` is set to `"none"`.

### 4.2 `DesktopStatusProjection` (`contracts/desktop_status_projection.py`)

`DesktopStatusProjection.model_routing` is a `ModelRoutingProjection` built by
`_build_model_routing_projection(ucp)`.

**Source priority (highest to lowest):**

1. **CANONICAL** — `ucp["topology_route_plan"]` block (`TopologyRoutePlan.to_dict()` output).
   When present, all routing fields are read from this block.  
   `routing_authority_source` is set to `"topology_router"`.

2. **LEGACY COMPAT** — top-level UCP keys (`chosen_model`, `chosen_provider`,
   `is_native_multimodal`, `support_model_ids`, `route_reason`) and the
   `multimodal_route` block (PR-20).  
   `routing_authority_source` is set to `"legacy_ucp_keys"`.

The `routing_authority_source` field on `ModelRoutingProjection` tells consumers
which path was taken.  Any consumer that receives `routing_authority_source != "topology_router"`
should treat the routing data as a **degraded compatibility result from a non-canonical
authority path**.  It must not be presented as authoritative topology state.

---

## 5. Legacy Compatibility Routing Semantics

The following structures are retained **for backward compatibility only**.  They are
**not** routing authority sources and must never be treated as canonical.  All are
classified as degraded compatibility paths:

| Structure | Role | Canonical replacement |
|---|---|---|
| `core.multi_llm_router.MultiLLMRouter` | Legacy multi-provider LLM selector | `TopologyRouter` |
| `dashboard.backend.main` (provider routing endpoints) | Legacy dashboard provider list — **not a routing-truth authority** | `TopologyRouter` via `ProviderInventory` |
| `ucp["chosen_model"]` / `ucp["chosen_provider"]` top-level keys | Legacy UCP compat keys | `ucp["topology_route_plan"]` |
| `ucp["multimodal_route"]` block | PR-20 multimodal route compat | `ucp["topology_route_plan"]` (preferred) |

These paths are registered in `core/orchestration_authority/legacy_paths.py` with
`LegacyPathStatus.LEGACY_COMPATIBILITY`.

### 5.1 What must no longer claim routing authority

- **`dashboard/` endpoints must not define the active model/provider selection.**
  The dashboard is not a routing-truth authority surface; it is in retirement per
  [`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`](DASHBOARD_RETIREMENT_AND_MIGRATION.md).
- `MultiLLMRouter` must not be used as the primary routing decision-maker for new code.
- Top-level scattered `chosen_model` / `chosen_provider` keys in the UCP must not be
  used directly when a `topology_route_plan` block is present.
- **Any summary of routing state that does not originate from `TopologyRoutePlan` is a
  degraded compatibility result**, not an authoritative routing view.  Such summaries
  must be labelled as `routing_authority_source: "legacy_ucp_keys"` or similar so that
  consumers can detect the degraded state.

---

## 6. Data Flow Diagram (Canonical Path)

```
ProviderInventory (inventory of providers/models)
    │
    ▼
TopologyRouter.route(phase, domain)          ← CANONICAL AUTHORITY
    │
    ▼
TopologyRoutePlan {                          ← CANONICAL OUTPUT CONTRACT
    primary_model,
    support_models,
    active_weights,
    route_reason,
    phase,
    domain,
    graph
}
    │
    ├──▶ RuntimeProjection                   ← STATUS BOARD V2 / PROJECTION ENDPOINT
    │       (via build_runtime_projection)
    │       routing_authority = "core.model_topology.topology_router.TopologyRouter"
    │
    └──▶ DesktopStatusProjection             ← SHELL-FACING STATUS CONTRACT
            (via _build_model_routing_projection reading ucp["topology_route_plan"])
            routing_authority_source = "topology_router"
```

---

## 7. Guardrails and Tests

Guardrails are implemented in `tests/test_pr53_model_routing_authority.py`:

- `TopologyRouter` output is correctly reflected in `RuntimeProjection` routing fields.
- `DesktopStatusProjection` prefers `topology_route_plan` over legacy UCP keys.
- Legacy bridge inputs do not override `topology_route_plan` when present.
- `CANONICAL_ROUTING_AUTHORITY` sentinel is importable from `topology_router`.
- `routing_authority_source` on `ModelRoutingProjection` correctly reflects the source used.

Legacy routing paths are registered in `core/orchestration_authority/legacy_paths.py`
(PR-routing-authority entries).

---

## 8. Migration Notes

For new code producing routing decisions:

1. Build a `ProviderInventory` from your provider/model list.
2. Instantiate `TopologyRouter(inventory)`.
3. Call `router.route(phase, domain)` to get a `TopologyRoutePlan`.
4. Embed `plan.to_dict()` as `ucp["topology_route_plan"]` in the `UnifiedControlPlan`.
5. Pass the `UnifiedControlPlan` to `build_desktop_status_projection()`.

For existing code still populating `chosen_model` / `chosen_provider` top-level keys:  
— Continue doing so for backward compatibility, but add `topology_route_plan` when possible.
— These keys are now explicitly classified as legacy compat fallbacks.
