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
