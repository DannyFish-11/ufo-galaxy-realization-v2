# Topology / Constellation Layout Foundation (PR-11)

> **Status:** PR-11 — Topology / constellation layout foundation after PR-10
> merge.

This document describes the topology/constellation layout module introduced in
PR-11 (`windows_client/status_board_v2/topology_layout.py`).  It is the next
stage after the adapter-driven desktop status board surface (PR-10) and
establishes structural layout and relationship rendering so the status board
moves beyond a flat status surface into a topology-aware presentation.

---

## Overview

PR-11 adds a **topology/constellation layout layer** on top of the PR-9/PR-10
adapter-driven surface.  Rather than rendering flat textual sections, the
layout module structures the status board into:

- **layers** — primary topology, support/routing, and OneAPI lower-horizon
- **nodes** — individual topology/provider/routing/OneAPI entries per layer
- **relations** — directed edges expressing routing paths, support paths,
  fallback paths, and lower-horizon links between nodes

The layout builder consumes a
`core.desktop_consumption_adapter.DesktopClientViewModel` (or an equivalent
plain dict) produced by the PR-9 adapter and never bypasses it to access raw
nested integration payload dicts directly.

---

## Layer model

The layout is organised into **three fixed layers** rendered top-to-bottom:

```
┌──────────────────────────────────────────────┐
│  PRIMARY LAYER                               │
│  (canonical provider / topology root node)   │
├──────────────────────────────────────────────┤
│  SUPPORT LAYER                               │
│  (routing peers / support paths)             │
├──────────────────────────────────────────────┤
│  LOWER-HORIZON LAYER                         │
│  (OneAPI integration — not a routing peer)   │
└──────────────────────────────────────────────┘
```

| Layer kind        | `TopologyLayerKind` value | `is_lower_horizon` |
|-------------------|---------------------------|--------------------|
| Primary           | `primary`                 | `False`            |
| Support           | `support`                 | `False`            |
| Lower-horizon     | `lower_horizon`           | `True`             |

The lower-horizon layer is **always present and always structurally separate**
from the primary and support layers.  It is never empty: a placeholder OneAPI
node is always placed there even when no OneAPI data is available.

---

## Node kinds

Each layer holds zero or more `TopologyLayoutNode` instances:

| `TopologyNodeKind` value | Placement layer   | Role                                      |
|--------------------------|-------------------|-------------------------------------------|
| `primary_provider`       | primary           | Canonical primary topology/provider root  |
| `routing_peer`           | support           | Canonical routing peer (non-legacy)       |
| `support_node`           | support           | Legacy / degraded routing support node    |
| `oneapi_horizon`         | lower_horizon     | OneAPI lower-horizon integration node     |

---

## Relation kinds

Directed relations between nodes:

| `TopologyRelationKind` value | `is_authoritative` | Description                                          |
|------------------------------|--------------------|------------------------------------------------------|
| `canonical_route`            | `True`             | Fully authoritative canonical routing path           |
| `support_path`               | `False`            | Auxiliary routing path (non-canonical)               |
| `fallback_path`              | `False`            | Legacy / degraded fallback path                      |
| `lower_horizon_link`         | `False`            | Link to OneAPI lower-horizon node (never canonical)  |

---

## Readiness-aware behaviour

The layout adapts to the readiness state from the view-model:

| Readiness state | Primary node `is_authoritative` | Relations include                          |
|-----------------|---------------------------------|--------------------------------------------|
| `canonical`     | `True`                          | `canonical_route`, `lower_horizon_link`    |
| `degraded`      | `False`                         | `fallback_path`, `lower_horizon_link`      |
| `partial`       | `False`                         | `support_path` / empty, `lower_horizon_link` |
| `unavailable`   | N/A (no primary node)           | No primary→support relations               |

**Key invariant:** the OneAPI node in the lower-horizon layer always has
`is_authoritative = False`, regardless of the topology readiness state.  It is
structurally and semantically separated from the primary and support layers.

---

## Usage

```python
from windows_client.status_board_v2.topology_layout import (
    build_constellation_layout,
    TopologyConstellationLayout,
    TOPOLOGY_LAYOUT_AUTHORITY,
)
from core.desktop_consumption_adapter import adapt_integration_payload

# Build the view-model from the PR-8 integration payload (PR-9 adapter)
vm = adapt_integration_payload(payload)

# Build the topology/constellation layout (PR-11)
layout = build_constellation_layout(vm)

# Readiness state
print(layout.readiness_label)     # "canonical" / "degraded" / "partial" / "unavailable"
print(layout.is_authoritative)    # True only for canonical (no legacy fallback)

# Primary topology node
for node in layout.primary_layer.nodes:
    print(node.node_id, node.kind.value, node.provider_id, node.is_authoritative)

# Support / routing-peer nodes
for node in layout.support_layer.nodes:
    print(node.node_id, node.kind.value)

# OneAPI lower-horizon node — always present, always is_authoritative=False
for node in layout.lower_horizon_layer.nodes:
    print(node.node_id, node.kind.value, node.is_authoritative)  # always False

# Directed relations
for rel in layout.relations:
    print(rel.source_id, "→", rel.target_id, rel.kind.value, rel.is_authoritative)

# Serialise the full layout
import json
print(json.dumps(layout.to_dict(), indent=2))
```

You can also import everything from the package:

```python
from windows_client.status_board_v2 import (
    build_constellation_layout,
    TopologyConstellationLayout,
    TopologyLayoutLayer,
    TopologyLayoutNode,
    TopologyLayoutRelation,
    TopologyNodeKind,
    TopologyRelationKind,
    TopologyLayerKind,
    TOPOLOGY_LAYOUT_AUTHORITY,
)
```

---

## Constraints and guarantees

- **Adapter-driven only** — the builder always consumes a
  `DesktopClientViewModel` (or equivalent plain dict) produced by the PR-9
  adapter.  It never reaches into raw nested integration payload dicts.
- **OneAPI always lower-horizon** — the OneAPI node is always in
  `TopologyLayerKind.lower_horizon`; its `is_authoritative` is always `False`.
  OneAPI is never promoted to a canonical routing peer.
- **Degraded / fallback states are not misrepresented** — a degraded or partial
  layout never sets `is_authoritative=True` on any node or relation.
- **Read-only** — the module never sends commands or modifies system state.
- **Graceful** — `build_constellation_layout(None)` produces a valid
  unavailable layout without raising.
- **PR-10 not bypassed** — this module is layered on top of PR-9/PR-10; it
  does not undo or replace the `AdapterSurface`.

---

## API reference

### `build_constellation_layout(vm)` → `TopologyConstellationLayout`

Main entry point.  Accepts a `DesktopClientViewModel` instance, a plain dict,
or `None`.  Returns a `TopologyConstellationLayout` representing the current
topology/constellation layout.

### `TopologyConstellationLayout`

Top-level layout object.  Key attributes:

| Attribute              | Type                       | Description                               |
|------------------------|----------------------------|-------------------------------------------|
| `layout_id`            | `str`                      | Unique layout instance ID                 |
| `layout_authority`     | `str`                      | Always `TOPOLOGY_LAYOUT_AUTHORITY`        |
| `readiness_label`      | `str`                      | `"canonical"` / `"degraded"` / etc.      |
| `is_authoritative`     | `bool`                     | `True` only when canonical               |
| `is_degraded`          | `bool`                     | `True` when degraded                     |
| `is_partial`           | `bool`                     | `True` when partial                      |
| `is_unavailable`       | `bool`                     | `True` when unavailable                  |
| `primary_layer`        | `TopologyLayoutLayer`      | Primary provider / topology root layer   |
| `support_layer`        | `TopologyLayoutLayer`      | Routing peer / support layer             |
| `lower_horizon_layer`  | `TopologyLayoutLayer`      | OneAPI lower-horizon layer               |
| `relations`            | `List[TopologyLayoutRelation]` | Directed topology relations           |
| `layers`               | `List[TopologyLayoutLayer]`| All three layers in display order        |
| `all_nodes`            | `List[TopologyLayoutNode]` | Every node across all layers             |

Methods: `to_dict()`, `to_json(**kwargs)`

---

## Related documents

- [`docs/DESKTOP_STATUS_BOARD_UI.md`](DESKTOP_STATUS_BOARD_UI.md) — PR-10
  first usable adapter-driven status board UI surface
- [`docs/DESKTOP_CONSUMPTION_ADAPTER.md`](DESKTOP_CONSUMPTION_ADAPTER.md) —
  PR-9 desktop client consumption adapter and `DesktopClientViewModel`
- [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) — Status Board V2 overview
- [`docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md`](RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md)
  — canonical model topology semantics for the right-side board
