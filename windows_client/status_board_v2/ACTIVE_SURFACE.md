# windows_client/status_board_v2/ — ACTIVE DESKTOP STATUS SURFACE

> **Status: ACTIVE / CANONICAL / SOLE DESKTOP SURFACE** (established PR-8;
> confirmed PR-1 architecture freeze; formally declared sole operator surface
> in PR-0)
>
> Role: `ACTIVE_DESKTOP_STATUS` · `SOLE_DESKTOP_OPERATOR_SURFACE`

`windows_client/status_board_v2/` is the **sole canonical operator-facing
desktop surface** and the **canonical read-only status board** for the Galaxy
system.

## PR-0 architecture freeze — key declarations

| Declaration | Detail |
|-------------|--------|
| **Sole desktop surface** | This is the only canonical operator-facing desktop surface.  All legacy desktop/operator surfaces are retired. |
| **Dashboard frontend retired** | `dashboard/frontend/` is no longer part of the active target architecture.  No new operator-facing UI work must target the dashboard. |
| **Future config entry surface** | This surface will become the sole desktop configuration entry point (Phase D of dashboard migration).  Config entry UI is **not implemented yet**. |
| **Config authority constraint** | When config entry is implemented, written configuration must target `runtime/config.json` (non-secret) and `runtime/secrets.env` (secrets) and must have system-wide effect.  It must not be stored as per-surface local state. |
| **Routing authority unchanged** | `TopologyRouter` remains sole canonical routing authority.  `TopologyRoutePlan` remains sole canonical routing output contract.  This surface never derives routing truth independently. |
| **Native-multimodal-first unchanged** | The Sky-Grown Constellation Topology remains the governing visual and semantic model.  Native multimodal paths anchor the primary layer. |

The dashboard (`dashboard/`) is in retirement and is no longer the target
primary UI surface.  See
[`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`](../../docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md)
for the retirement and migration plan.  See
[`docs/ADR_STATUS_BOARD_CONFIG_AUTHORITY.md`](../../docs/ADR_STATUS_BOARD_CONFIG_AUTHORITY.md)
for the architecture decision record freezing this surface as the future
configuration entry point.

The target visual grammar for the model topology display is the
**Native-Multimodal-First Sky-Grown Constellation Topology**
(星空一体化生长式星座拓扑树), defined in
[`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](../../docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md).

## Tri-state alignment

This surface renders and tracks all three canonical desktop states:

| State | Displayed as | Surface behaviour |
|-------|-------------|-------------------|
| `silent` | Phase label (grey) | Minimal display; all fields at defaults |
| `liminal` | Phase label (amber) | Routing and execution-context fields active |
| `manifest` | Phase label (green) | Full execution context; device IDs; task summary |

The tri-state lifecycle is owned exclusively by `DesktopPresenceRuntime`
(`core/desktop_presence_runtime.py`).  This surface **consumes** the lifecycle
value from the canonical projection endpoint — it never sets or drives the
tri-state value.

See [`docs/DESKTOP_SEMANTIC_CLOSURE.md`](../../docs/DESKTOP_SEMANTIC_CLOSURE.md)
for the authoritative definition of all three states and their invariants.

## What this surface does (current state)

Consumes the canonical runtime projection endpoint and renders the current
tri-state phase (silent / liminal / manifest) along with system health metrics:

```
Source:   GET /api/v1/projection/runtime
Contract: contracts.desktop_status_projection.DesktopStatusProjection
```

This surface is currently **projection-driven and read-only** — it does not
maintain its own system state, does not write to the authority model, and does
not define system structure.

## What this surface will do (future Phase D)

A future PR (Phase D of the dashboard migration) will add an interactive
configuration entry mode to this surface.  At that point:

- Operators will be able to enter provider API keys, provider enable/disable
  settings, and model preferences directly through this surface.
- Written configuration will be persisted to the local unified configuration
  authority: `runtime/config.json` (non-secret) and `runtime/secrets.env`
  (secrets).
- Configuration changes must have system-wide effect — affecting provider
  inventory, routing candidate pool, projection, and topology.
- `TopologyRouter` will remain the sole canonical routing decision-maker.
  Config entry modifies the inputs (provider inventory, preferences) that
  `TopologyRouter` consumes; it does not bypass the routing authority.

**This interactive mode is not implemented in this PR.**  The current surface
remains read-only.

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
[`docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md`](../../docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md).

The target visual identity is the **Native-Multimodal-First Sky-Grown
Constellation Topology** — a depth-illusion / 2.5-D semantic structure, not a
flat provider card grid, not true 3-D.  See
[`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](../../docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md)
for the full specification.

1. **MAIN ROUTE** — primary model with optional `[MM]` native-multimodal badge
   and vendor/source tag.
2. **SUPPORT** — auxiliary/support models with weights and vendor tags.
3. **Route reason / routing authority** — human-readable rationale and
   canonical authority source.  Degraded authority must be highlighted.
4. **ONEAPI AGGREGATOR HORIZON** (lower row, separated by a mandatory rule) —
   always rendered; never mixed into the main direct-provider layer.
   Rendering OneAPI at the same level as direct providers is
   **architecturally incorrect**.

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
- `docs/ADR_STATUS_BOARD_CONFIG_AUTHORITY.md` — ADR freezing this surface as sole desktop config entry surface
- `docs/LIMINAL_SPACE_MAPPING.md` — canonical liminal space mapping definition
- `docs/SANDBOX_SIMULATION_PROJECTION.md` — sandbox/simulation field semantics
- `docs/DESKTOP_SEMANTIC_CLOSURE.md` — canonical tri-state semantic closure
- `docs/STATUS_AND_STATISTICS_OWNERSHIP.md` — statistics / summary ownership
- `docs/CONFIGURATION_ENTRY_UNIFICATION.md` — configuration entry semantics

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
