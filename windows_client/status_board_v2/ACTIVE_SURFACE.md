# windows_client/status_board_v2/ — ACTIVE DESKTOP STATUS SURFACE

> **Status: ACTIVE / CANONICAL** (established PR-8)
>
> Role: `ACTIVE_DESKTOP_STATUS`

`windows_client/status_board_v2/` is the **canonical read-only desktop status
board** for the Galaxy system.

## What this surface does

Consumes the canonical runtime projection endpoint and renders the current
tri-state phase (silent / liminal / manifest) along with system health metrics:

```
Source:   GET /api/v1/projection/runtime
Contract: contracts.desktop_status_projection.DesktopStatusProjection
```

This surface is **projection-driven and read-only** — it does not maintain its
own system state, does not write to the authority model, and does not define
system structure.

## Active sub-surfaces

| Module | Purpose |
|--------|---------|
| `app.py` | Top-level status board application |
| `projection_reader.py` | Projection API consumer |
| `phase_surface.py` | Tri-state phase display (silent / liminal / manifest) |
| `device_surface.py` | Connected device status |
| `metrics_surface.py` | Runtime metrics surface |
| `topology_surface.py` | Model topology view (native-multimodal-first; see below) |
| `domain_surface.py` | Domain / capability surface |
| `manifest_surface.py` | Manifest-stage surface |
| `return_surface.py` | Return-intelligence surface |
| `liminal_surface.py` | Liminal-space surface (local chain / cross-device chain / sandbox simulation) |

## Model topology semantics (`topology_surface.py`)

`topology_surface.py` renders the model routing topology as a **native-
multimodal-first layered structure**, per
[`docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md`](../../docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md):

1. **MAIN ROUTE** — primary model with optional `[MM]` native-multimodal badge
   and vendor/source tag.
2. **SUPPORT** — auxiliary/support models with weights and vendor tags.
3. **Route reason / routing authority** — human-readable rationale and
   canonical authority source.
4. **ONEAPI AGGREGATOR** (lower row, separated by a rule) — rendered only
   when `oneapi_source` data is present; never mixed into the main
   direct-provider layer.

This is a **topology**, not a flat provider list.  See
[`docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md`](../../docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md)
for full semantics, invariants, and display-field reference.

## Relationship to legacy status board

`windows_client/status_board.py` (root level) is a **legacy status board**
(PR-8 demoted) that polls `/api/v1/continuum/state` — an ad-hoc non-projection
endpoint.  It has been superseded by this module.

Do NOT extend `status_board.py`.  Extend `status_board_v2/` instead.

## Display boundary

This surface is **exclusively** a structured information display layer.  It
must not carry liminal-space content.

Per [`docs/DESKTOP_DISPLAY_BOUNDARIES.md`](../../docs/DESKTOP_DISPLAY_BOUNDARIES.md):

- **Right-side status board (this surface)**: model/routing information,
  provider/vendor status, primary/support model topology, system state and
  execution summary, device/task/metrics panels.
- **Liminal space** (`liminal_surface.py`, `manifest_surface.py`): local
  execution chain, cross-device execution chain, sandbox/speculative execution
  field only.

**Prohibited in this surface**: execution-field spatial dimensions as primary
panels (depth_factor, ambient_intensity, domain_path_emphasis — those belong
to the liminal space).

**Prohibited in liminal space**: provider list cards, dashboard-style model
panels, full metrics/status-board panels, generic operator information blocks.

## Authority references

- `core/ui_surface_authority.py` — registers this surface as `PROJECTION_DRIVEN`
- `core/repo_layout_registry.py` — classifies as `ACTIVE_DESKTOP_STATUS`
- `contracts/desktop_status_projection.py` — canonical projection contract
- `core/routes/` — `GET /api/v1/projection/runtime` endpoint
- `core/liminal_space_mapping.py` — canonical liminal-facing structures
- `docs/LIMINAL_SPACE_MAPPING.md` — canonical liminal space mapping definition
- `docs/SANDBOX_SIMULATION_PROJECTION.md` — sandbox/simulation field semantics

## Migration guidance

Consumers of `windows_client/status_board.py` should migrate to this module:

```python
# Legacy (deprecated):
from windows_client.status_board import StatusBoard

# Active:
from windows_client.status_board_v2.app import StatusBoardV2App
# or use the projection API directly:
# GET /api/v1/projection/runtime
```
