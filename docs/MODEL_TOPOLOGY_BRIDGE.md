# Model Topology Bridge

> **Package**: `core/model_topology/`
> **Introduced**: V2 PR-1 (Topology Config Bridge)
> **Status**: Foundation layer – consumed by later V2 PRs

---

## Why this bridge exists

The Galaxy repository accumulated a rich set of provider/router/node concepts
during the dashboard era (see `dashboard/README.md`).  Those concepts –
*IntentRouter*, *ExecutionPlanner*, *AgentFactory*, *TwinModel*, *Multi-LLM
Router*, provider tables with speed/quality scores, multimodal flags, env-key
requirements, and node-API categories – encode important design decisions that
the V2 topology layer must *understand and preserve*, even as the old
dashboard UI is retired as the primary interaction surface.

The **Topology Config Bridge** (`core/model_topology/`) is the translation
layer that:

1. Reads dashboard-era provider/node snapshots (static dicts *or* live API
   responses from `GET /api/v1/llm/providers` and
   `GET /api/v1/config/node-apis`).
2. Normalises them into a strongly-typed `NormalizedTopologyEntry` schema.
3. Assembles a queryable `ProviderInventory` with derived role hints and
   aggregator/router semantic annotations.
4. Produces `AggregatorRouterHint` objects that name logical roles
   (`multimodal_core_aggregator`, `reasoning_aggregator`, etc.) for later V2
   PRs to wire into the runtime routing graph.

---

## Dashboard-era semantics preserved

| Dashboard concept | Bridge mapping |
|---|---|
| `provider` field | `ProviderIdentity.provider_id` |
| `model` / `models` | `ModelIdentity.model_id` + `alternatives` |
| `multimodal: bool` | `ModalityCapability.native_multimodal` (+ `supports_vision`) |
| `speed_score` / `quality_score` | `ScoringProfile.speed_score` / `.quality_score` |
| `available` / `missing_env_key` | `AvailabilityStatus.available` / `.missing_env_key` |
| `env_keys` list | `AvailabilityStatus.all_env_keys` |
| Node `category` (direct\_models / oneapi / tools / …) | `ProviderCategory` enum |
| Node-API entry (node\_id / name / category / keys) | `NormalizedTopologyEntry` via `bridge_node_api()` |
| IntentRouter / Multi-LLM Router role | `AggregatorRouterHint(kind=ROUTE_ARBITER)` |
| ExecutionPlanner / AgentFactory role | `AggregatorRouterHint(kind=EXECUTION_AGGREGATOR)` |
| TwinModel / memory role | `AggregatorRouterHint(kind=MEMORY_AGGREGATOR)` |
| Multi-modal vision node | `AggregatorRouterHint(kind=MULTIMODAL_CORE_AGGREGATOR)` |
| Cross-device coordination | `AggregatorRouterHint(kind=CROSS_DEVICE_AGGREGATOR)` |

### Observability categories preserved as semantics

The following dashboard-era status/health categories are surfaced as
`ProviderCategory` and `TopologyRole` values so that future projection layers
can query them:

| Dashboard concept | Bridge representation |
|---|---|
| Model route status | `TopologyRole.ROUTING` + `AggregatorKind.ROUTE_ARBITER` |
| Device health | `ProviderCategory.NODE_BACKED` + health fields on `ProviderInventoryEntry` |
| Capability load status | `AvailabilityStatus.available` + `ScoringProfile` |
| Mesh/body assignment | `TopologyRole.CROSS_DEVICE` (hint; wired in later PRs) |
| Projection events | Reserved via `AggregatorKind.CROSS_DEVICE_AGGREGATOR` |

---

## What is intentionally NOT preserved

| Item | Reason |
|---|---|
| Dashboard HTML/JS/TS frontend | The bridge is headless; UI is a separate concern |
| FastAPI route handlers from `dashboard/backend/main.py` | Not imported; bridge works on typed snapshots only |
| Dashboard session state / WebSocket state | Runtime state; not part of the static config schema |
| Dashboard form layouts / user-configurable fields | Form-factor; the bridge just translates data |
| Any live API call to the running dashboard server | The bridge is a pure translation layer |

The new `core/model_topology/` package has **zero imports** from
`dashboard/backend/main.py` or the TypeScript frontend.

---

## Package structure

```
core/model_topology/
├── __init__.py              Public surface / re-exports
├── topology_types.py        Enums + frozen dataclasses (ProviderIdentity, …)
├── legacy_dashboard_schema.py  Read-only mirrors of dashboard-era types
├── provider_inventory.py    ProviderInventory collection + queries
└── config_bridge.py         ConfigBridge translation logic
```

---

## How to use it

```python
from core.model_topology import (
    ConfigBridge,
    LegacyLLMProviderSnapshot,
    LegacyNodeAPIEntry,
    LegacyNodeAPIKeySpec,
    ProviderCategory,
    TopologyRole,
)

bridge = ConfigBridge()

# 1. Translate a single provider snapshot
snapshot = LegacyLLMProviderSnapshot.from_dict({
    "provider": "anthropic",
    "model": "claude-sonnet-4-6-20251022",
    "models": ["claude-opus-4-8-20250529", "claude-sonnet-4-6-20251022", "claude-haiku-4-5-20251001"],
    "speed_score": 7,
    "quality_score": 10,
    "available": True,
    "multimodal": True,
})
entry = bridge.bridge_provider(snapshot)
# entry.role_hints → [TopologyRole.MULTIMODAL_CORE, TopologyRole.REASONING, TopologyRole.GENERAL]

# 2. Build a full inventory from all provider snapshots
inventory = bridge.build_inventory(provider_snapshots=[snapshot])

# 3. Query the inventory
mm_providers = inventory.multimodal_entries()
top5 = inventory.top_by_quality(n=5)
print(inventory.to_dict())          # JSON-serialisable
```

---

## How this bridge feeds later V2 PRs

```
V2 PR-1  (this PR)
  └─ core/model_topology/  ← produces ProviderInventory
        │
        ▼
V2 PR-2  Model Supply Topology Core
  └─ consumes ProviderInventory to build the weighted supply graph
        │
        ▼
V2 PR-3  Routing Policy Layer
  └─ consumes supply graph + AggregatorRouterHints to derive routing rules
        │
        ▼
V2 PR-4  Tri-State ↔ Routing Coupling
  └─ tri_state_phase drives model-weight selection from supply graph
        │
        ▼
V2 PR-5  Desktop Spatial Projection
  └─ reads ProviderInventory + supply graph weights for topology board
```

---

## Running the tests

```bash
# Run all model_topology tests
python -m pytest tests/test_model_topology_bridge.py -v

# Or via make
make test:fast
```
