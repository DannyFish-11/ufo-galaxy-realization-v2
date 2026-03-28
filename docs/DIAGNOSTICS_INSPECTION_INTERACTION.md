# Diagnostics and Inspection Interaction Layer (PR-13)

This document describes the diagnostics and inspection interaction layer
introduced in PR-13, which builds on the PR-9 adapter, PR-11 topology layout,
and PR-12 topology renderer to make the desktop topology / status board not
only readable, but **investigable**.

---

## Overview

PR-13 adds a **`TopologyInspector`** surface to `windows_client/status_board_v2/`
that allows operators and client code to drill into topology nodes, relations,
readiness/authority state, routing summary details, and lower-horizon OneAPI
details — safely and without breaking the semantic guarantees established by
PR-4 through PR-12.

### Key design principles

1. **Built on the adapter + layout pipeline** — the inspector always operates
   on a `TopologyConstellationLayout` (PR-11/12 model) or a
   `DesktopClientViewModel` (PR-9 adapter output). It never bypasses these
   layers to access raw nested payload dicts.

2. **Safe authority semantics** — canonical, degraded, partial, and unavailable
   states are always explicit. Degraded/fallback data is never presented as
   authoritative truth.

3. **OneAPI stays lower-horizon** — `OneAPIInspectionDetail.is_lower_horizon_only`
   is always `True`. OneAPI is never returned as a canonical routing peer.

4. **Read-only** — the inspector never sends commands or modifies system state.

5. **Graceful** — all inspection paths handle `None` / missing inputs without
   raising.

---

## Module location

```
windows_client/status_board_v2/topology_inspector.py
```

All public symbols are exported from the package `__init__.py` and available
via `windows_client.status_board_v2`.

---

## Public API

### Authority sentinel

```python
TOPOLOGY_INSPECTOR_AUTHORITY: str
# = "windows_client.status_board_v2.topology_inspector.TopologyInspector"
```

Confirms that an `InspectionReport` was produced by the canonical PR-13
inspector (not assembled ad-hoc).

---

### Data classes

#### `NodeInspectionDetail`

Detailed view of a single topology node.

| Attribute | Type | Description |
|-----------|------|-------------|
| `node_id` | `str` | Unique node identifier |
| `kind` | `str` | Node kind (`"primary_provider"` / `"routing_peer"` / `"support_node"` / `"oneapi_horizon"`) |
| `kind_meaning` | `str` | Human-readable explanation of the node kind |
| `label` | `str` | Display label |
| `readiness_label` | `str` | `"canonical"` / `"degraded"` / `"partial"` / `"unavailable"` |
| `is_authoritative` | `bool` | `True` only for canonical topology nodes |
| `is_available` | `bool` | Whether the resource is available |
| `is_lower_horizon` | `bool` | `True` for OneAPI nodes only |
| `provider_id` | `str \| None` | Provider identifier |
| `model_id` | `str \| None` | Model identifier |
| `extra` | `dict` | Additional metadata |
| `authority_note` | `str` | Explicit human-readable authority status note |
| `inspector_authority` | `str` | Always `TOPOLOGY_INSPECTOR_AUTHORITY` |

#### `RelationInspectionDetail`

Detailed view of a directed topology relation.

| Attribute | Type | Description |
|-----------|------|-------------|
| `source_id` | `str` | Source node ID |
| `target_id` | `str` | Target node ID |
| `kind` | `str` | `"canonical_route"` / `"fallback_path"` / `"support_path"` / `"lower_horizon_link"` |
| `kind_meaning` | `str` | Human-readable explanation of the relation kind |
| `label` | `str` | Display label |
| `is_authoritative` | `bool` | `True` for canonical route relations only |
| `is_fallback` | `bool` | `True` for `fallback_path` relations |
| `is_lower_horizon` | `bool` | `True` for `lower_horizon_link` relations |
| `authority_note` | `str` | Explicit authority status note |
| `inspector_authority` | `str` | Always `TOPOLOGY_INSPECTOR_AUTHORITY` |

#### `ReadinessInspectionDetail`

Authority / readiness interpretation for the whole layout.

| Attribute | Type | Description |
|-----------|------|-------------|
| `readiness_label` | `str` | `"canonical"` / `"degraded"` / `"partial"` / `"unavailable"` / `"unknown"` |
| `is_authoritative` | `bool` | `True` only when canonical |
| `is_degraded` | `bool` | `True` when legacy fallback is active |
| `is_partial` | `bool` | `True` when canonical source present but incomplete |
| `is_unavailable` | `bool` | `True` when no topology data available |
| `meaning` | `str` | Full human-readable explanation of this readiness state |
| `fallback_active` | `bool` | Any legacy fallback active |
| `topology_legacy_fallback_active` | `bool` | Topology-specific fallback flag |
| `routing_legacy_fallback_active` | `bool` | Routing-specific fallback flag |
| `degraded_reason` | `str \| None` | Why the topology is degraded/non-authoritative; `None` when canonical |
| `inspector_authority` | `str` | Always `TOPOLOGY_INSPECTOR_AUTHORITY` |

#### `RoutingInspectionDetail`

Routing and provider summary diagnostics.

| Attribute | Type | Description |
|-----------|------|-------------|
| `provider_id` | `str \| None` | Primary provider identifier |
| `model_id` | `str \| None` | Primary model identifier |
| `route_reason` | `str \| None` | Routing reason / phase string |
| `authority_source` | `str \| None` | Routing authority source |
| `integration_health` | `str` | `"ok"` / `"degraded"` / `"advisory"` / `"critical"` / `"unknown"` |
| `routing_legacy_fallback_active` | `bool` | Whether legacy routing fallback is active |
| `provider_routing_available` | `bool` | Whether provider routing info is available |
| `vendor_source` | `str \| None` | Vendor source string |
| `active_model_id` | `str \| None` | Active model ID |
| `is_authoritative` | `bool` | `True` only for canonical routing |
| `authority_note` | `str` | Explicit authority status note |
| `inspector_authority` | `str` | Always `TOPOLOGY_INSPECTOR_AUTHORITY` |

#### `OneAPIInspectionDetail`

Lower-horizon OneAPI integration diagnostic detail.

| Attribute | Type | Description |
|-----------|------|-------------|
| `is_lower_horizon_only` | `bool` | **Always `True`** — never a canonical peer |
| `oneapi_available` | `bool` | Whether OneAPI is available |
| `integration_type` | `str \| None` | Integration type string |
| `provider_id` | `str \| None` | OneAPI provider identifier |
| `raw_summary` | `dict` | Raw summary from the OneAPI horizon summary |
| `authority_note` | `str` | Explicit lower-horizon note |
| `inspector_authority` | `str` | Always `TOPOLOGY_INSPECTOR_AUTHORITY` |

#### `InspectionReport`

Complete diagnostics report. All components are accessible as attributes.

| Attribute | Type | Description |
|-----------|------|-------------|
| `report_id` | `str` | Unique report identifier |
| `readiness` | `ReadinessInspectionDetail` | Overall readiness/authority |
| `nodes` | `list[NodeInspectionDetail]` | All nodes (all layers) |
| `relations` | `list[RelationInspectionDetail]` | All relations |
| `routing` | `RoutingInspectionDetail` | Routing/provider summary |
| `oneapi` | `OneAPIInspectionDetail` | OneAPI lower-horizon detail |
| `primary_nodes` | `list[NodeInspectionDetail]` | Primary layer nodes only |
| `support_nodes` | `list[NodeInspectionDetail]` | Support layer nodes only |
| `lower_horizon_nodes` | `list[NodeInspectionDetail]` | Lower-horizon layer nodes |
| `layout_authority` | `str \| None` | PR-11 layout authority string |
| `inspector_authority` | `str` | Always `TOPOLOGY_INSPECTOR_AUTHORITY` |

Methods: `to_dict()`, `to_json(**kwargs)`

---

### `TopologyInspector`

The main inspection surface.

```python
from windows_client.status_board_v2.topology_inspector import TopologyInspector
inspector = TopologyInspector()
```

#### `inspect_layout(layout) → InspectionReport`

Build a complete inspection report from a `TopologyConstellationLayout` or
its `to_dict()` form. Returns an unavailable report for `None` input.

#### `inspect_node(node_id, layout) → NodeInspectionDetail | None`

Drill into a specific node by its ID. Returns `None` if not found.

#### `inspect_relation(source_id, target_id, layout) → RelationInspectionDetail | None`

Drill into a specific relation by source and target node IDs. Returns the
first matching relation, or `None` if not found.

#### `inspect_readiness(layout) → ReadinessInspectionDetail`

Return readiness/authority detail from a layout. Never raises.

#### `inspect_oneapi(layout) → OneAPIInspectionDetail`

Return lower-horizon OneAPI detail. `is_lower_horizon_only` is always `True`.
Never raises.

#### `inspect_routing_summary(layout) → RoutingInspectionDetail`

Return routing/provider summary diagnostic detail. Never raises.

#### `inspect_from_view_model(vm) → InspectionReport`

Build a complete report from a `DesktopClientViewModel` (PR-9 adapter output).
This is the preferred entry point when starting from the adapter layer rather
than from an already-built layout.

Builds the PR-11 layout internally, then enriches the report with view-model
fields (`topology_route_reason`, `routing_authority_source`,
`integration_health`, fallback flags, OneAPI horizon summary).

---

## Usage examples

### Starting from a layout

```python
from windows_client.status_board_v2.topology_inspector import TopologyInspector
from windows_client.status_board_v2.topology_layout import build_constellation_layout
from core.desktop_consumption_adapter import adapt_integration_payload

vm = adapt_integration_payload(payload)
layout = build_constellation_layout(vm)
inspector = TopologyInspector()

# Full report
report = inspector.inspect_layout(layout)
print(report.readiness.readiness_label)    # "canonical"
print(report.readiness.is_authoritative)   # True
print(report.readiness.degraded_reason)    # None

# Drill into primary node
if report.primary_nodes:
    node = report.primary_nodes[0]
    print(node.kind)                        # "primary_provider"
    print(node.provider_id)                 # "openai"
    print(node.is_authoritative)            # True
    print(node.authority_note)              # "... canonical topology ..."

# Drill into a specific node by ID
detail = inspector.inspect_node("primary_provider_node", layout)
if detail:
    print(detail.readiness_label)

# Inspect OneAPI (always lower-horizon)
oneapi = inspector.inspect_oneapi(layout)
print(oneapi.is_lower_horizon_only)        # always True
print(oneapi.authority_note)               # "... lower-horizon ..."
```

### Starting from the view-model (preferred)

```python
from windows_client.status_board_v2.topology_inspector import TopologyInspector
from core.desktop_consumption_adapter import adapt_integration_payload

vm = adapt_integration_payload(payload)
inspector = TopologyInspector()

# One-step inspection from the adapter output
report = inspector.inspect_from_view_model(vm)
print(report.readiness.readiness_label)
print(report.routing.route_reason)
print(report.oneapi.is_lower_horizon_only)  # always True
```

### Serialisation

```python
report = inspector.inspect_layout(layout)
d = report.to_dict()     # dict — safe for JSON serialisation
j = report.to_json()     # JSON string
```

---

## Semantic invariants

These invariants are enforced and tested:

1. `OneAPIInspectionDetail.is_lower_horizon_only` is **always `True`**.
2. OneAPI nodes always appear in `lower_horizon_nodes` only, never in
   `primary_nodes` or `support_nodes`.
3. `ReadinessInspectionDetail.degraded_reason` is `None` only for canonical
   readiness; non-`None` for degraded, partial, and unavailable.
4. Nodes in degraded layouts have `is_authoritative = False`.
5. `fallback_path` relations have `is_fallback = True` and
   `is_authoritative = False`.
6. `canonical_route` relations have `is_authoritative = True`.
7. `lower_horizon_link` relations have `is_lower_horizon = True`.
8. Every `NodeInspectionDetail` has an explicit `authority_note` that
   distinguishes canonical from non-canonical data.
9. The inspector is built on the PR-9/PR-11 adapter + layout pipeline and
   never bypasses it to reconstruct truth from raw nested dicts.

---

## Related documents

- [`docs/TOPOLOGY_RENDERING_VISUAL_SEMANTICS.md`](TOPOLOGY_RENDERING_VISUAL_SEMANTICS.md) — PR-12
- [`docs/TOPOLOGY_CONSTELLATION_LAYOUT.md`](TOPOLOGY_CONSTELLATION_LAYOUT.md) — PR-11
- [`docs/DESKTOP_STATUS_BOARD_UI.md`](DESKTOP_STATUS_BOARD_UI.md) — PR-10
- [`docs/DESKTOP_CONSUMPTION_ADAPTER.md`](DESKTOP_CONSUMPTION_ADAPTER.md) — PR-9
- [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) — overall status board V2 design
