# Status Board V2 — Design & Usage Guide

> **READ-ONLY.**  The Status Board V2 never accepts chat input, never sends
> commands, and never triggers any actions.  It is a pure display surface.
>
> **Canonical desktop operator-visible surface** for model topology, routing state,
> and provider status in the Galaxy system.  The dashboard is in retirement; this
> board is the target surface for all operator-facing model topology work.
> See [`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`](DASHBOARD_RETIREMENT_AND_MIGRATION.md).

---

## Overview

Status Board V2 is a lightweight, dependency-free CLI status board that
visualises the current `RuntimeProjection` assembled by the Galaxy server.

`windows_client/status_board_v2/` is the **canonical desktop structured
operator-visible surface** for model topology.  The target visual grammar for
the model topology display is the **Native-Multimodal-First Sky-Grown
Constellation Topology** defined in
[`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](SKY_GROWN_CONSTELLATION_TOPOLOGY.md).

It supersedes the minimal `windows_client/status_board.py` board (which only
displayed `tri_state_phase` and `runtime_domain`) by adding:

| Surface | Fields displayed |
|---------|-----------------|
| **PhaseSurface** | `tri_state_phase` (silent / liminal / manifest) |
| **DomainSurface** | `runtime_domain` (local / cross_device / transition) |
| **TopologySurface** | `primary_model_id` [with `[MM]` badge when native-multimodal], `vendor_source`, `topology_role`, `support_model_ids`, `active_weights` (top-5 bar chart), `route_reason`, `routing_authority`, `oneapi_source` (lower aggregator row) |
| **DeviceSurface** | `active_device_ids`, `execution_stage`, `current_task_summary` |
| **MetricsSurface** | `presence_intensity`, `coherence`, `collapse_tendency`, `retreat_tendency` |

---

## Package Structure

```
windows_client/status_board_v2/
├── __init__.py          # Public surface (StatusBoardV2App, ProjectionReader, main, run)
├── __main__.py          # python -m windows_client.status_board_v2 entry point
├── app.py               # Main application class and CLI entry point
├── projection_reader.py # Reads RuntimeProjection from HTTP / file / stdin
├── phase_surface.py     # Renders tri_state_phase
├── domain_surface.py    # Renders runtime_domain
├── topology_surface.py  # Renders model topology (weights, primary, support)
├── device_surface.py    # Renders device IDs and execution context
├── metrics_surface.py   # Renders presence/coherence/tendency metrics
└── _ansi.py             # Internal ANSI colour helpers
```

---

## Running the Status Board

### 1. Poll the local Galaxy server (default)

```bash
python -m windows_client.status_board_v2
```

Polls `http://127.0.0.1:8000/api/v1/projection/runtime` every second.

### 2. Specify a different server

```bash
python -m windows_client.status_board_v2 --host 10.0.0.5 --port 8000
```

### 3. Adjust the poll interval

```bash
python -m windows_client.status_board_v2 --interval 2.0
```

### 4. Read from a JSON file (offline / testing)

```bash
python -m windows_client.status_board_v2 --file /tmp/projection.json
```

### 5. Read a single projection from stdin

```bash
cat projection.json | python -m windows_client.status_board_v2 --stdin
```

### 6. Disable ANSI colour

```bash
python -m windows_client.status_board_v2 --no-color
```

---

## Projection Endpoint

### `GET /api/v1/projection/runtime`

Added in `core/routes/projection.py` (wired into `core/api_routes.py`).

#### Purpose
Returns the current `RuntimeProjection` assembled from:
1. Live `ContinuumState` from the cognitive/presence layer.
2. Optional `TopologyRoutePlan` from the model topology router.
3. Optional `ExecutionSummary` from the device manager.

#### Response schema

```json
{
  "tri_state_phase": "silent" | "liminal" | "manifest",
  "runtime_domain": "local" | "cross_device" | "transition" | null,
  "presence_intensity": 0.0,
  "coherence": 0.0,
  "collapse_tendency": 0.0,
  "retreat_tendency": 0.0,
  "primary_model_id": "gpt-4o" | null,
  "support_model_ids": ["model-a", "model-b"],
  "active_weights": {
    "gpt-4o": 0.85,
    "claude-3": 0.42
  },
  "route_reason": "Native multimodal core preferred in liminal phase",
  "active_device_ids": ["device-001"],
  "execution_stage": "planning" | "executing" | "completing" | null,
  "current_task_summary": "Summarise the document on screen",
  "timestamp": 1711533600.0
}
```

#### Design constraints
- **Read-only** — the endpoint never writes state or triggers actions.
- **Graceful degradation** — if any sub-component is unavailable, the endpoint
  returns a minimal valid projection (all optional fields as `null` / empty)
  rather than an error.  The status board always has something to display.
- **Not dashboard** — this route lives in `core/routes/`, not in
  `dashboard/backend/`.  The dashboard backend must not be modified to serve
  projection data.

---

## Input Source Priority

`ProjectionReader` tries sources in the following order:

1. **HTTP endpoint** — `GET <base_url>/api/v1/projection/runtime`
2. **File** — reads a JSON file on disk (`--file PATH`)
3. **stdin** — reads a single JSON blob from standard input (`--stdin`)

The first source that succeeds is used.  If all sources fail, the board
displays an `OFFLINE` frame.

---

## Dependencies

Status Board V2 uses **only Python stdlib**:

- `argparse`, `datetime`, `json`, `os`, `sys`, `time`, `urllib.request`

No new packages are required.

---

## Tests

Tests are in `tests/test_pr4_status_board_v2.py` and cover:

1. `ProjectionReader` parsing with sample projection JSON.
2. Surface rendering logic (snapshot text formatting for each surface).
3. `GET /api/v1/projection/runtime` endpoint returns a valid `RuntimeProjection`
   structure.

Run with:

```bash
pytest tests/test_pr4_status_board_v2.py -v
```

---

## Model Topology Semantics

`TopologySurface` renders the model routing topology as a **native-multimodal-
first layered structure**, not a flat provider list.  This is documented in full
in [`docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md`](RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md).

The target visual identity for this surface is the **Native-Multimodal-First
Sky-Grown Constellation Topology** (星空一体化生长式星座拓扑树), defined in
[`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](SKY_GROWN_CONSTELLATION_TOPOLOGY.md).
This is a depth-illusion / 2.5-D semantic structure — not true 3-D, not a flat
dashboard card grid, but a projection-driven constellation-style layout where
position, brightness, and separator depth express routing relationships.

### Layer structure

```
MAIN ROUTE (direct / native-multimodal first)
  ★ <primary_model>  [MM]  [vendor]  weight ████████░░

SUPPORT
  · <support_model_1>  [vendor]  weight █████░░░░░
  · <support_model_2>  [vendor]  weight ███░░░░░░░

Reason  : <route_reason>
Authority: <routing_authority>

─────────────────────────────────────────────────────
ONEAPI AGGREGATOR HORIZON  (lower-layer / not a direct provider)
  <base_url>  [configured]  <N models>
```

### Key rules

- Primary model is always in the MAIN ROUTE layer, marked `★`.
- `[MM]` badge appears when `is_native_multimodal` is `True` in the projection.
- OneAPI appears **only** in the lower AGGREGATOR HORIZON row, never mixed into
  the main-route or support layer.  **Any rendering that places OneAPI at the
  same visual level as direct providers is architecturally incorrect.**
- **PR-4**: the `oneapi_integration` top-level block in `DesktopStatusProjection`
  is **always present** in the projection.  The OneAPI row must therefore always
  be rendered — when not configured it shows `not configured`.  Omitting the
  row entirely is not permitted.
- The `oneapi_source` field in `ModelRoutingProjection` is `None` unless the
  active route actually goes *through* OneAPI.  Do not use it as the data
  source for the horizon row; use `DesktopStatusProjection.oneapi_integration`
  instead.
- When `routing_authority` is not `topology_router`, the surface must highlight
  the degraded authority state rather than silently accepting it.
- **PR-6**: the `topology_ready` block in `DesktopStatusProjection` is the
  **single canonical topology-ready projection** for desktop topology surfaces.
  Desktop consumers should use `topology_ready` rather than reconstructing
  routing truth from legacy keys or assembling dashboard-era summaries.
  `canonical_source_present == true` confirms canonical sourcing;
  `legacy_fallback_active == true` signals a degraded projection.
- **PR-7**: `topology_ready` now carries a structured `projection_quality` block
  (`TopologyProjectionQualityBlock`) with explicit readiness/quality semantics.
  Desktop/constellation consumers **must** inspect `projection_quality.readiness`
  and `projection_quality.authoritative` before treating topology data as ground
  truth.  `readiness == "canonical"` and `authoritative == true` are required for
  fully authoritative routing truth.  `readiness == "degraded"` signals legacy
  fallback; `readiness == "partial"` signals missing/unavailable components;
  `readiness == "unavailable"` means no topology data is available.

---

## PR-8: Final Desktop Status Board Integration Contract

PR-8 delivers the final integration-oriented contract for the desktop status
board / topology consumer boundary, building on PR-4 through PR-7.  After
PR-8, desktop clients can consume **one stable server-provided payload** without
re-deriving state from multiple endpoints or legacy/dashboard-era assembly
logic.

### What PR-8 adds

| Addition | Location | Purpose |
|----------|----------|---------|
| `DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY` | `contracts.desktop_status_projection` | Machine-checkable PR-8 integration sentinel |
| `DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY` | `core.projection.projection_compiler` | Mirror sentinel in compiler namespace |
| `DesktopStatusBoardIntegrationPayload` | `contracts.desktop_status_projection` | Final integration-oriented composed payload |
| `build_desktop_status_board_integration_payload()` | `contracts.desktop_status_projection` | Builder for the integration payload |
| `build_desktop_status_board_integration_from_runtime()` | `core.projection.projection_compiler` | Bridge: RuntimeProjection → integration payload |
| `GET /api/v1/projection/desktop-status-board` | `core.routes.projection` | Single stable endpoint for desktop status board consumption |

### Integration payload fields

| Field | Type | Description |
|-------|------|-------------|
| `topology_projection` | `DesktopTopologyProjection` | PR-6/7 topology block with quality/readiness semantics |
| `model_routing_summary` | `dict` | Compact routing summary (provider, model, authority source, legacy flag) |
| `provider_health_summary` | `dict \| null` | Provider health/availability when relevant |
| `oneapi_integration` | `dict \| null` | PR-4 lower-horizon OneAPI block (never a top-layer peer) |
| `authority_indicators` | `dict` | All canonical-vs-legacy authority signals in one place |
| `integration_authority` | `str` | PR-8 sentinel confirming canonical builder provenance |
| `integration_health` | `str` | Rolled-up integration health |

### Convenience properties on `DesktopStatusBoardIntegrationPayload`

Two convenience properties are available so desktop clients do not need to
drill into sub-blocks for the most common checks:

| Property | Type | Description |
|----------|------|-------------|
| `.readiness` | `str` | Shorthand for `authority_indicators["topology_readiness"]` — `"canonical"` / `"degraded"` / `"partial"` / `"unavailable"` |
| `.is_canonical` | `bool` | Shorthand for `authority_indicators["topology_authoritative"]` — `True` when topology is fully authoritative routing truth |

### Canonical authority layering (preserved)

- `TopologyRoutePlan` / canonical projection structures remain authoritative.
- Legacy compatibility fields remain secondary/fallback-only.
- OneAPI remains a lower-horizon integration block only.
- `authority_indicators.topology_authoritative == true` confirms topology data
  is fully authoritative routing truth.

### Consumer guidance (post-PR-8)

1. **Consume `GET /api/v1/projection/desktop-status-board`** to obtain the
   final integrated payload.  Do **not** assemble state by combining
   `/runtime`, `/desktop-topology`, and other legacy endpoint outputs.

2. **Check `.readiness` or `.is_canonical`** for the most common single-flag
   checks without drilling into sub-blocks.

3. **Inspect `authority_indicators`** for a complete machine-checkable view of
   all canonical-vs-legacy authority signals.

4. **`topology_projection.projection_quality`** remains the primary readiness
   discriminator (PR-7 semantics preserved):
   - `"canonical"` → fully authoritative
   - `"degraded"` → legacy fallback active; surface warning to operator
   - `"partial"` → components missing; surface partial state
   - `"unavailable"` → no data; do not render topology

5. **`oneapi_integration`** is always a lower-horizon block; never promote it
   to a top-layer provider peer.

6. **`integration_authority`** equals
   `"contracts.desktop_status_projection.DesktopStatusBoardIntegrationPayload"` —
   verify this sentinel to confirm canonical builder provenance.

### Machine-Checkable Exports (PR-8)

| Symbol | Module | Type | Description |
|--------|--------|------|-------------|
| `DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY` | `contracts.desktop_status_projection` | `str` | PR-8 integration sentinel |
| `DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY` | `core.projection.projection_compiler` | `str` | Mirror sentinel |
| `DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY` | `core.projection` (package `__all__`) | `str` | Re-exported from package |
| `DesktopStatusBoardIntegrationPayload` | `contracts.desktop_status_projection` | Pydantic model | Final integration payload |
| `build_desktop_status_board_integration_from_runtime` | `core.projection.projection_compiler` | function | Bridge to build payload from runtime state |
| `build_desktop_status_board_integration_from_runtime` | `core.projection` (package `__all__`) | function | Re-exported from package |

### API Endpoints (post-PR-8)

| Endpoint | PR | Description |
|----------|-----|-------------|
| `GET /api/v1/projection/runtime` | PR-3 | Live `RuntimeProjection` |
| `GET /api/v1/projection/canonical-routing` | PR-3 | Canonical routing + provider status |
| `GET /api/v1/projection/server-canonicalization-status` | PR-5 | Server-side canonicalization summary |
| `GET /api/v1/projection/desktop-topology` | PR-6/7 | Topology-ready block with readiness/quality semantics |
| `GET /api/v1/projection/desktop-status-board` | **PR-8** | **Final integrated desktop status board payload** |

> **Desktop clients should prefer `/api/v1/projection/desktop-status-board`
> after PR-8.**  The lower-level endpoints remain available for diagnostic
> and integration-layer use, but the integration payload provides everything
> a status board client needs in one stable contract.


## PR-9: Desktop Client Consumption Adapter

PR-9 adds the **desktop client consumption adapter** (`core/desktop_consumption_adapter.py`)
so desktop status board consumers can work with one flat, easy-to-use view-model
rather than navigating nested sub-structures in the PR-8 payload.

### What PR-9 adds

| Addition | Location | Purpose |
|----------|----------|---------|
| `DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY` | `core.desktop_consumption_adapter` | PR-9 adapter sentinel |
| `DesktopReadinessState` | `core.desktop_consumption_adapter` | Client-facing readiness enum (`canonical` / `degraded` / `partial` / `unavailable` / `unknown`) |
| `DesktopClientViewModel` | `core.desktop_consumption_adapter` | Flat, stable client view-model |
| `DesktopProviderRoutingSummary` | `core.desktop_consumption_adapter` | Flattened provider/routing summary |
| `DesktopOneAPIHorizonSummary` | `core.desktop_consumption_adapter` | Flattened OneAPI lower-horizon summary |
| `adapt_integration_payload()` | `core.desktop_consumption_adapter` | Adapter function: `DesktopStatusBoardIntegrationPayload` → `DesktopClientViewModel` |
| All of the above | `core.projection` (package `__all__`) | Re-exported from the projection package |

### Consumer guidance (post-PR-9)

```python
from core.projection import adapt_integration_payload, build_desktop_status_board_integration_from_runtime

payload = build_desktop_status_board_integration_from_runtime(continuum_state=state)
vm = adapt_integration_payload(payload)

# Top-level readiness — no nested dict inspection needed
if vm.is_canonical:
    render_canonical_state(vm.topology_provider_id)
elif vm.is_degraded:
    render_degraded_warning()
elif vm.is_partial:
    render_partial_indicator()
else:
    render_unavailable_state()
```

See [`docs/DESKTOP_CONSUMPTION_ADAPTER.md`](DESKTOP_CONSUMPTION_ADAPTER.md) for the full post-PR-9 guide.

---

## PR-10: First Usable Desktop Status Board UI

PR-10 adds the **first usable adapter-driven desktop status board UI surface**
(`windows_client/status_board_v2/adapter_surface.py`).

### What PR-10 adds

| Symbol | Module | Description |
|--------|--------|-------------|
| `AdapterSurface` | `windows_client.status_board_v2.adapter_surface` | First usable adapter-driven status board UI surface |

### Consumer guidance (post-PR-10)

`AdapterSurface` consumes a `DesktopClientViewModel` from the PR-9 adapter
and renders a clear, operator-visible status board covering:

- Readiness / quality state (canonical / degraded / partial / unavailable / unknown)
- Canonical-vs-fallback authority state with ⚠ banner when legacy fallback active
- Primary topology / provider identity when available
- Provider and routing summary
- OneAPI lower-horizon block (always visually distinct, always labelled as lower-horizon)

```python
from windows_client.status_board_v2.adapter_surface import AdapterSurface
from core.desktop_consumption_adapter import adapt_integration_payload

surface = AdapterSurface()
vm = adapt_integration_payload(payload)   # PR-9 adapter
print(surface.render_view_model(vm))      # PR-10 UI surface
```

See [`docs/DESKTOP_STATUS_BOARD_UI.md`](DESKTOP_STATUS_BOARD_UI.md) for the full PR-10 guide.

---

## PR-11: Topology / Constellation Layout Foundation

PR-11 adds the **topology/constellation layout foundation** layered on top of
the PR-9/PR-10 adapter-driven surface.  The status board moves beyond flat
textual sections into a topology-aware layout of **layers**, **nodes**, and
**relations**.

### What PR-11 adds

| Symbol | Module | Role |
|--------|--------|------|
| `build_constellation_layout` | `windows_client.status_board_v2.topology_layout` | Main builder — produces a `TopologyConstellationLayout` from a `DesktopClientViewModel` |
| `TopologyConstellationLayout` | `windows_client.status_board_v2.topology_layout` | Top-level layout structure |
| `TopologyLayoutLayer` | `windows_client.status_board_v2.topology_layout` | Layer (primary / support / lower-horizon) |
| `TopologyLayoutNode` | `windows_client.status_board_v2.topology_layout` | Individual topology/provider/routing/OneAPI node |
| `TopologyLayoutRelation` | `windows_client.status_board_v2.topology_layout` | Directed relation between nodes |
| `TopologyNodeKind` | `windows_client.status_board_v2.topology_layout` | Node kind enum |
| `TopologyRelationKind` | `windows_client.status_board_v2.topology_layout` | Relation kind enum |
| `TopologyLayerKind` | `windows_client.status_board_v2.topology_layout` | Layer kind enum |
| `TOPOLOGY_LAYOUT_AUTHORITY` | `windows_client.status_board_v2.topology_layout` | PR-11 builder authority sentinel |

### Consumer guidance (post-PR-11)

`build_constellation_layout` consumes a `DesktopClientViewModel` from the PR-9
adapter and produces a `TopologyConstellationLayout` with three fixed layers:
**primary** (canonical provider), **support** (routing peers), and
**lower-horizon** (OneAPI — always structurally separate, never authoritative).

```python
from windows_client.status_board_v2.topology_layout import build_constellation_layout
from core.desktop_consumption_adapter import adapt_integration_payload

vm = adapt_integration_payload(payload)         # PR-9 adapter
layout = build_constellation_layout(vm)         # PR-11 topology layout

print(layout.readiness_label)                   # "canonical" / "degraded" / ...
print(layout.is_authoritative)                  # True only for canonical
for node in layout.primary_layer.nodes:
    print(node.provider_id, node.is_authoritative)
for node in layout.lower_horizon_layer.nodes:
    print(node.kind.value, node.is_authoritative)  # always False
```

See [`docs/TOPOLOGY_CONSTELLATION_LAYOUT.md`](TOPOLOGY_CONSTELLATION_LAYOUT.md)
for the full PR-11 guide.

---

## PR-12: Topology Rendering and Visual Semantics Polish

PR-12 adds the **topology constellation renderer** layered on top of the PR-11
layout model.  It transforms a `TopologyConstellationLayout` into a polished,
operator-visible terminal surface with clear visual semantics.

### What PR-12 adds

| Symbol | Module | Role |
|--------|--------|------|
| `TopologyRenderer` | `windows_client.status_board_v2.topology_renderer` | Main renderer — produces a polished string from a `TopologyConstellationLayout` |
| `TOPOLOGY_RENDERER_AUTHORITY` | `windows_client.status_board_v2.topology_renderer` | PR-12 renderer authority sentinel |

### Visual semantic guarantees (PR-12)

- **Canonical** (`●`, green) — fully authoritative topology; `[auth]` tag on
  primary node; `━━▶` edge on canonical route relation.
- **Degraded** (`◑`, yellow) — legacy fallback active; `⚠ DEGRADED` banner;
  `[NOT-auth]` tag on all nodes; `╌╌▷` fallback edge; never appears canonical.
- **Partial** (`◔`, cyan) — canonical source present but incomplete; `⚠ PARTIAL`
  banner; `[not-auth]` tag; never appears fully authoritative.
- **Unavailable** (`○`, red) — no topology data; `✗ UNAVAILABLE` line; no node
  symbols for absent layers.
- **OneAPI** (`⬡`, magenta) — always in `LOWER-HORIZON · OneAPI · not a routing
  peer` section; always `[lower-horizon]` tag; never `[auth]`; never `━━▶` edge.

### Consumer guidance (post-PR-12)

```python
from windows_client.status_board_v2 import TopologyRenderer
from windows_client.status_board_v2 import build_constellation_layout
from core.desktop_consumption_adapter import adapt_integration_payload

vm = adapt_integration_payload(payload)         # PR-9 adapter
layout = build_constellation_layout(vm)         # PR-11 topology layout
renderer = TopologyRenderer()                   # PR-12 renderer
print(renderer.render_layout(layout))           # polished output
```

See [`docs/TOPOLOGY_RENDERING_VISUAL_SEMANTICS.md`](TOPOLOGY_RENDERING_VISUAL_SEMANTICS.md)
for the full PR-12 guide.

---

## PR-13: Diagnostics and Inspection Interaction Layer

PR-13 adds the **topology diagnostics/inspection layer** — an investigable
surface that lets operators and client code drill into topology nodes,
relations, readiness/authority state, routing summary details, and lower-
horizon OneAPI details without breaking the semantic guarantees established by
PR-4 through PR-12.

### What PR-13 adds

| Symbol | Module | Description |
|--------|--------|-------------|
| `TopologyInspector` | `windows_client.status_board_v2.topology_inspector` | PR-13 main inspection surface |
| `TOPOLOGY_INSPECTOR_AUTHORITY` | `windows_client.status_board_v2.topology_inspector` | PR-13 inspector authority sentinel |
| `NodeInspectionDetail` | `windows_client.status_board_v2.topology_inspector` | Single-node diagnostic view |
| `RelationInspectionDetail` | `windows_client.status_board_v2.topology_inspector` | Single-relation diagnostic view |
| `ReadinessInspectionDetail` | `windows_client.status_board_v2.topology_inspector` | Readiness/authority interpretation |
| `RoutingInspectionDetail` | `windows_client.status_board_v2.topology_inspector` | Routing/provider summary diagnostics |
| `OneAPIInspectionDetail` | `windows_client.status_board_v2.topology_inspector` | OneAPI lower-horizon diagnostic (always `is_lower_horizon_only=True`) |
| `InspectionReport` | `windows_client.status_board_v2.topology_inspector` | Complete diagnostics report |

### Semantic guarantees (PR-13)

- `OneAPIInspectionDetail.is_lower_horizon_only` is **always `True`** —
  OneAPI is never a canonical routing peer during inspection.
- Nodes in degraded layouts have `is_authoritative = False`.
- `fallback_path` relations are always `is_fallback = True` and
  `is_authoritative = False`.
- `canonical_route` relations are always `is_authoritative = True`.
- Every `NodeInspectionDetail` has an explicit `authority_note` that
  distinguishes canonical from non-canonical/fallback data.
- The inspector builds exclusively on the PR-9/PR-11 adapter + layout pipeline
  and never bypasses it to reconstruct truth from raw nested dicts.

### Consumer guidance (post-PR-13)

```python
from windows_client.status_board_v2.topology_inspector import TopologyInspector
from core.desktop_consumption_adapter import adapt_integration_payload

vm = adapt_integration_payload(payload)
inspector = TopologyInspector()

# One-step inspection from adapter output
report = inspector.inspect_from_view_model(vm)
print(report.readiness.readiness_label)       # "canonical"
print(report.readiness.is_authoritative)      # True / False
print(report.readiness.degraded_reason)       # None or explanation

# Inspect OneAPI — always lower-horizon only
oneapi = inspector.inspect_oneapi(layout)
print(oneapi.is_lower_horizon_only)           # always True

# Serialise for logging / persistence
d = report.to_dict()
j = report.to_json()
```

See [`docs/DIAGNOSTICS_INSPECTION_INTERACTION.md`](DIAGNOSTICS_INSPECTION_INTERACTION.md)
for the full PR-13 guide.

---

## Display Boundary

> **Status Board V2 is the right-side structured information display layer.**
> It must not cross into the liminal space's responsibilities.

The canonical boundary between this board and the liminal middle-state space
is defined in [`docs/DESKTOP_DISPLAY_BOUNDARIES.md`](DESKTOP_DISPLAY_BOUNDARIES.md).
Key rules enforced there:

- The **status board** is the correct and only place for model/routing
  information, provider/vendor status, metrics, and device/task panels.
- The **liminal space** (`liminal_surface.py`, `manifest_surface.py`) carries
  only: local execution chain, cross-device execution chain, and
  sandbox/speculative execution field content.
- Provider list cards, dashboard-style model panels, full metrics/status-board
  panels, and generic operator information blocks must **not** appear in
  liminal space.

---

## Related Documents

- [`docs/DIAGNOSTICS_INSPECTION_INTERACTION.md`](DIAGNOSTICS_INSPECTION_INTERACTION.md) — PR-13 diagnostics and inspection interaction layer
- [`docs/TOPOLOGY_RENDERING_VISUAL_SEMANTICS.md`](TOPOLOGY_RENDERING_VISUAL_SEMANTICS.md) — PR-12 topology rendering and visual semantics polish
- [`docs/TOPOLOGY_CONSTELLATION_LAYOUT.md`](TOPOLOGY_CONSTELLATION_LAYOUT.md) — PR-11 topology / constellation layout foundation
- [`docs/DESKTOP_STATUS_BOARD_UI.md`](DESKTOP_STATUS_BOARD_UI.md) — PR-10 first usable adapter-driven status board UI surface
- [`docs/DESKTOP_SEMANTIC_CLOSURE.md`](DESKTOP_SEMANTIC_CLOSURE.md) — **canonical tri-state semantic closure contract** (manifest / active / liminal)
- [`docs/STATUS_AND_STATISTICS_OWNERSHIP.md`](STATUS_AND_STATISTICS_OWNERSHIP.md) — statistics / summary ownership across surfaces
- [`docs/CONFIGURATION_ENTRY_UNIFICATION.md`](CONFIGURATION_ENTRY_UNIFICATION.md) — unified configuration entry semantics
- [`docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md`](RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md) — canonical model topology semantics for the right-side board
- [`docs/DESKTOP_DISPLAY_BOUNDARIES.md`](DESKTOP_DISPLAY_BOUNDARIES.md) — canonical display boundary contract
- [`docs/LIMINAL_SPACE_MAPPING.md`](LIMINAL_SPACE_MAPPING.md) — canonical liminal space mapping definition (three allowed content classes)
- [`docs/SANDBOX_SIMULATION_PROJECTION.md`](SANDBOX_SIMULATION_PROJECTION.md) — sandbox/speculative execution field semantics
- [`docs/RUNTIME_PROJECTION.md`](RUNTIME_PROJECTION.md) — full design rationale for `RuntimeProjection`
- [`windows_client/status_board.py`](../windows_client/status_board.py) — original minimal status board (still functional)
- [`core/projection/`](../core/projection/) — `RuntimeProjection` model and `build_runtime_projection` compiler
