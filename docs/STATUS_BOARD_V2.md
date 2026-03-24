# Status Board V2 — Design & Usage Guide

> **READ-ONLY.**  The Status Board V2 never accepts chat input, never sends
> commands, and never triggers any actions.  It is a pure display surface.

---

## Overview

Status Board V2 is a lightweight, dependency-free CLI status board that
visualises the current `RuntimeProjection` assembled by the Galaxy server.

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
ONEAPI AGGREGATOR  (lower-layer / not a direct provider)
  <base_url>  [configured]  <N models>
```

### Key rules

- Primary model is always in the MAIN ROUTE layer, marked `★`.
- `[MM]` badge appears when `is_native_multimodal` is `True` in the projection.
- OneAPI appears **only** in the lower AGGREGATOR row, never mixed into the
  main-route or support layer.
- When `oneapi_source` is absent from the projection, the OneAPI row is omitted.

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

- [`docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md`](RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md) — canonical model topology semantics for the right-side board
- [`docs/DESKTOP_DISPLAY_BOUNDARIES.md`](DESKTOP_DISPLAY_BOUNDARIES.md) — canonical display boundary contract
- [`docs/RUNTIME_PROJECTION.md`](RUNTIME_PROJECTION.md) — full design rationale for `RuntimeProjection`
- [`windows_client/status_board.py`](../windows_client/status_board.py) — original minimal status board (still functional)
- [`core/projection/`](../core/projection/) — `RuntimeProjection` model and `build_runtime_projection` compiler
