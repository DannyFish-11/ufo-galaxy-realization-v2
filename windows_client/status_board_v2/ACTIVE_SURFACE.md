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
| `topology_surface.py` | System topology view |
| `domain_surface.py` | Domain / capability surface |
| `manifest_surface.py` | Manifest-stage surface |
| `return_surface.py` | Return-intelligence surface |
| `liminal_surface.py` | Liminal-space surface |

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
