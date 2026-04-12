# Status Board V2 — Design & Usage Guide

> ⚠️ Historical design document: for current runtime/product-readiness truth, use
> [`docs/WINDOWS_STATUS_BOARD.md`](WINDOWS_STATUS_BOARD.md),
> [`docs/CLONE_TO_USE_REALITY.md`](CLONE_TO_USE_REALITY.md), and
> [`docs/PRODUCT_READINESS_AUDIT.md`](PRODUCT_READINESS_AUDIT.md) first.
>
> **PR-0 architecture freeze:**  `windows_client/status_board_v2/` is the
> **sole canonical desktop operator-facing surface** for the Galaxy system.
> Legacy desktop surfaces are retired.  Dashboard frontend is retired.
> No new operator-facing UI work must target any other desktop surface.
>
> **PR-3 (landed):** The local unified configuration authority is now
> implemented.  `runtime/config.json` (non-secrets) and `runtime/secrets.env`
> (secrets) are the canonical persistence targets.  Core modules:
> `core/config_store.py`, `core/config_service.py`, `core/config_schema.py`.
> See [`docs/CONFIGURATION_ENTRY_UNIFICATION.md`](CONFIGURATION_ENTRY_UNIFICATION.md)
> and [`docs/CONFIG_GOVERNANCE.md`](CONFIG_GOVERNANCE.md) §10.
>
> **Future direction:**  `status_board_v2` will become the **sole desktop
> configuration entry surface** (Phase D of dashboard migration).  Config
> entry UI implementation is deferred to a later PR.  When implemented,
> configuration entered here must write to the local unified configuration
> authority (`runtime/config.json` / `runtime/secrets.env`) via
> `core/config_service.ConfigService` and have system-wide effect.
>
> **Current state — READ-ONLY.**  The Status Board V2 currently never accepts
> system configuration input, never sends commands, and never triggers any
> actions.  It is a pure display surface until the config entry phase lands.
>
> See [`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`](DASHBOARD_RETIREMENT_AND_MIGRATION.md)
> and [`docs/ADR_STATUS_BOARD_CONFIG_AUTHORITY.md`](ADR_STATUS_BOARD_CONFIG_AUTHORITY.md).

---

## Architecture freeze — sole desktop surface (PR-0)

`windows_client/status_board_v2/` is formally declared the **sole canonical
desktop operator-facing surface** for the Galaxy system as of PR-0.

| Declaration | Detail |
|-------------|--------|
| **Sole desktop surface** | This is the only canonical operator-facing desktop surface going forward |
| **Legacy surfaces retired** | `windows_client/status_board.py` (root-level legacy) and any other non-`status_board_v2` desktop operator surfaces are retired |
| **Dashboard frontend retired** | `dashboard/frontend/` is no longer part of the active target architecture |
| **Future config entry surface** | Phase D will add interactive configuration entry to this surface (deferred, not in this PR) |
| **Routing authority unchanged** | `TopologyRouter` / `TopologyRoutePlan` remain sole canonical routing authority; this surface consumes, never derives, routing truth |

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

Polls `http://127.0.0.1:8299/api/v1/projection/runtime` every second.

### 2. Specify a different server

```bash
python -m windows_client.status_board_v2 --host 10.0.0.5 --port 8299
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
- **PR-4 (inventory layer)**: The provider inventory consumed by `TopologyRouter`
  is now driven by the unified config authority (`runtime/config.json` /
  `runtime/secrets.env`).  `ProviderInventoryEntry` carries
  `config_enabled` / `config_has_key` / `is_candidate_eligible` flags.
  The routing candidate pool (`candidate_pool_entries()`) excludes:
  - disabled providers (`config_enabled == False`)
  - providers missing required secrets (`config_has_key == False`)
  - unconfigured OneAPI (treated as **absent**, not merely disabled)
  Status-board diagnostics may surface these via `disabled_entries()` and
  `unconfigured_entries()` for operator visibility without polluting the
  active candidate pool.
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

## PR-5: Server-Side Canonicalization

PR-5 completes the server-side canonicalization phase that follows PR-4 (OneAPI
lower-horizon cleanup).  It removes remaining ambiguous and non-canonical
projection/routing outputs so that the backend emits a cleaner, single source of
truth for downstream desktop topology work.

### What PR-5 adds

| Addition | Location | Purpose |
|----------|----------|---------|
| `LEGACY_UCP_ROUTING_KEYS` | `contracts.desktop_status_projection` | Frozen registry of top-level UCP keys that are legacy/compatibility-only |
| `PROJECTION_CONTRACT_AUTHORITY` | `contracts.desktop_status_projection` | Machine-checkable sentinel for the canonical projection contract |
| `LEGACY_ROUTING_FIELDS` | `core.model_topology.topology_router` | Tuple of legacy routing field names demoted by PR-5 |
| `LEGACY_PROJECTION_UCP_KEYS` | `core.projection.projection_compiler` | Tuple of legacy UCP projection keys (mirrors contract registry) |
| `PROJECTION_COMPILER_AUTHORITY` | `core.projection.projection_compiler` | Machine-checkable sentinel for the canonical projection compiler |
| `legacy_routing_fallback_active` | `ModelRoutingProjection` | `bool` field — `True` when routing was derived from legacy UCP keys |
| `GET /api/v1/projection/server-canonicalization-status` | `core/routes/projection.py` | Read-only endpoint returning PR-5 canonicalization summary |

### PR-4 guarantees preserved

PR-5 does not undo any PR-4 guarantees:

- `DesktopStatusProjection.oneapi_integration` is always present (lower-horizon only).
- `model_routing.oneapi_source` is `None` when `vendor_source != "oneapi"`.
- OneAPI is never merged into the top-layer provider list.

### Machine-checkable exports (PR-5)

```python
# Contract-layer sentinels (contracts.desktop_status_projection)
from contracts.desktop_status_projection import LEGACY_UCP_ROUTING_KEYS  # frozenset
from contracts.desktop_status_projection import PROJECTION_CONTRACT_AUTHORITY  # str

# Topology-router legacy registry (core.model_topology.topology_router)
from core.model_topology.topology_router import LEGACY_ROUTING_FIELDS  # tuple

# Compiler-layer sentinels — also accessible via core.projection package
from core.projection import LEGACY_PROJECTION_UCP_KEYS   # tuple (mirrors LEGACY_UCP_ROUTING_KEYS)
from core.projection import PROJECTION_COMPILER_AUTHORITY  # str (compiler assembly sentinel)

# Check legacy routing key registry (contract layer)
assert "chosen_model" in LEGACY_UCP_ROUTING_KEYS
assert "chosen_provider" in LEGACY_UCP_ROUTING_KEYS

# Check fallback state in projection
from contracts.desktop_status_projection import build_desktop_status_projection
proj = build_desktop_status_projection(unified_control_plan={"chosen_model": "gpt-4o"})
assert proj.model_routing.legacy_routing_fallback_active is True  # degraded path
```

See [`docs/SERVER_SIDE_CANONICALIZATION.md`](SERVER_SIDE_CANONICALIZATION.md) for the
full PR-5 policy and consumer guidance.

---

## PR-6: Desktop Topology Projection

PR-6 delivers the final desktop topology-oriented projection layer on top of the
PR-5 canonicalization foundation.  Desktop surfaces can now consume a single
server-assembled topology-ready block rather than reconstructing topology from
scattered routing data.

### What PR-6 adds

| Addition | Location | Purpose |
|----------|----------|---------|
| `TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY` | `contracts.desktop_status_projection` | Machine-checkable sentinel for the PR-6 topology-ready block |
| `TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY` | `core.projection.projection_compiler` | Mirror sentinel in compiler namespace |
| `TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY` | `core.projection` (package) | Convenience re-export for downstream consumers |
| `DesktopTopologyProjection` | `contracts.desktop_status_projection` | Renderer-agnostic structured block for desktop topology surfaces |
| `topology_ready` field | `DesktopStatusProjection` | PR-6 topology-ready block attached to the top-level projection |
| `GET /api/v1/projection/desktop-topology` | `core/routes/projection.py` | Dedicated read-only endpoint returning the topology-ready block |

### Consumer guidance (PR-6)

- Desktop topology surfaces should consume the `topology_ready` block from
  `DesktopStatusProjection` (or from `GET /api/v1/projection/desktop-topology`)
  as the single canonical topology-ready projection.
- `canonical_source_present == true` confirms the block was derived from a
  canonical `TopologyRoutePlan`.  `legacy_fallback_active == true` signals a
  degraded projection (assembled from legacy UCP keys).
- The `oneapi_integration` block inside `topology_ready` remains a lower-horizon
  integration block only — it must never be promoted to a top-layer provider peer.
- `contract_authority` is the machine-checkable sentinel
  `"contracts.desktop_status_projection.DesktopTopologyProjection"` confirming
  the block was produced by the canonical builder.

### Machine-checkable exports (PR-6)

```python
from contracts.desktop_status_projection import (
    TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY,
    DesktopTopologyProjection,
)
from core.projection import TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY

# Verify topology-ready block in a projection
from contracts.desktop_status_projection import build_desktop_status_projection
ucp = {
    "topology_route_plan": {
        "primary_model": {"model_id": "gpt-4o", "provider_id": "openai",
                          "vendor_source": "direct", "native_multimodal": False},
        "support_models": [],
        "route_reason": "test",
    }
}
proj = build_desktop_status_projection(unified_control_plan=ucp)
assert proj.topology_ready is not None
assert proj.topology_ready.canonical_source_present is True
assert proj.topology_ready.legacy_fallback_active is False
assert proj.topology_ready.contract_authority == TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY
```

See [`docs/SERVER_SIDE_CANONICALIZATION.md`](SERVER_SIDE_CANONICALIZATION.md) §8 for
the full PR-6 policy and topology-ready block structure.

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

## PR-14: Observability and History Layer

PR-14 adds the **topology observability and history layer** — making it
possible to understand not only the current state, but also recent changes,
transitions, and stability over time, while preserving all semantic guarantees
around canonical authority, fallback/degraded states, and OneAPI lower-horizon
separation.

### What PR-14 adds

| Symbol | Module | Description |
|--------|--------|-------------|
| `TopologyHistoryRecorder` | `windows_client.status_board_v2.topology_history` | PR-14 main history/observability surface |
| `TOPOLOGY_HISTORY_AUTHORITY` | `windows_client.status_board_v2.topology_history` | PR-14 history authority sentinel |
| `TopologyChangeKind` | `windows_client.status_board_v2.topology_history` | Enumeration of observable change event types |
| `ReadinessTransitionRecord` | `windows_client.status_board_v2.topology_history` | Records a readiness state transition |
| `AuthorityChangeRecord` | `windows_client.status_board_v2.topology_history` | Records an authority change |
| `RoutingChangeRecord` | `windows_client.status_board_v2.topology_history` | Records a provider/routing change |
| `OneAPIHistorySummary` | `windows_client.status_board_v2.topology_history` | OneAPI lower-horizon historical summary (always `is_lower_horizon_only=True`) |
| `TopologyHistoryEntry` | `windows_client.status_board_v2.topology_history` | Single timestamped change record |
| `TopologySnapshot` | `windows_client.status_board_v2.topology_history` | Point-in-time topology state snapshot |
| `TopologyHistoryBuffer` | `windows_client.status_board_v2.topology_history` | Bounded in-memory buffer for history entries |

### Semantic guarantees (PR-14)

- `OneAPIHistorySummary.is_lower_horizon_only` is **always `True`** —
  OneAPI is never a canonical routing peer in any historical view.
- `TopologySnapshot.oneapi_is_lower_horizon_only` is **always `True`**.
- Degraded/fallback entries always have `is_authoritative = False`.  They are
  never re-promoted to authoritative truth.
- `ReadinessTransitionRecord.transition_note` explicitly states the
  non-authoritative constraint when transitioning into a degraded/fallback state.
- The recorder builds exclusively on the PR-9/PR-11/PR-12/PR-13 pipeline and
  never bypasses it to reconstruct truth from raw nested dicts.
- `snapshot_from_*` always returns a `TopologySnapshot`; `None` input yields
  an unavailable snapshot (`is_unavailable=True`, `is_authoritative=False`).

### Consumer guidance (post-PR-14)

```python
from windows_client.status_board_v2.topology_history import (
    TopologyHistoryRecorder, TopologyHistoryBuffer,
)
from windows_client.status_board_v2.topology_inspector import TopologyInspector
from core.desktop_consumption_adapter import adapt_integration_payload

vm = adapt_integration_payload(payload)
inspector = TopologyInspector()
report = inspector.inspect_from_view_model(vm)

recorder = TopologyHistoryRecorder()
buf = TopologyHistoryBuffer(max_size=50)

# Record a history entry from the current inspection report
entry = recorder.record_from_inspection_report(report)
if entry:
    buf.add_entry(entry)

# Take a point-in-time snapshot
snap = recorder.snapshot_from_inspection_report(report)
print(snap.readiness_label)          # "canonical"
print(snap.stability_indicator)      # "stable"
print(snap.oneapi_is_lower_horizon_only)   # always True

# Compare two snapshots to detect transitions
diff = recorder.compare_snapshots(snap_before, snap_after)
if diff["readiness_changed"]:
    tr = diff["readiness_transition"]
    print(f"Readiness: {tr.from_readiness} → {tr.to_readiness}")
    print(tr.transition_note)        # explicitly notes non-authoritative transitions

# Stability summary over a buffer
summary = recorder.stability_summary(buf)
print(summary["overall_stability"])  # "stable" / "mostly_stable" / "unstable"
print(summary["stability_ratio"])    # 0.0–1.0
```

See [`docs/OBSERVABILITY_HISTORY.md`](OBSERVABILITY_HISTORY.md)
for the full PR-14 guide.

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

## PR-15: Final End-to-End Hardening and Closure

PR-15 closes the multi-PR initiative by consolidating all PR-8 through PR-14
work into a fully hardened, regression-protected, documentation-complete state.

### What PR-15 adds

| Artifact | Description |
|----------|-------------|
| `tests/test_pr15_e2e_hardening.py` | 100 end-to-end regression tests covering the full pipeline |
| `docs/DESKTOP_PIPELINE_ARCHITECTURE.md` | Authoritative post-PR-15 architecture reference |

### End-to-end regression protection

`tests/test_pr15_e2e_hardening.py` proves that the full pipeline works
coherently for all four semantic states and that the following invariants
hold end-to-end:

- Canonical / degraded / partial / unavailable semantics are **consistent
  across all layers** (adapter → layout → renderer → inspector → history).
- Degraded / fallback data is **never** silently promoted to authoritative
  truth at any layer.
- OneAPI is **lower-horizon only** across every layer (layout, renderer,
  inspector, history).
- Historical / inspection / rendering outputs remain **semantically aligned**.
- `None` / empty / unavailable paths are **safe and serialisable** at every
  layer.

### Consumer guidance (post-PR-15)

See [`docs/DESKTOP_PIPELINE_ARCHITECTURE.md`](DESKTOP_PIPELINE_ARCHITECTURE.md)
for the authoritative post-PR-15 consumption guide, including:

- The full seven-layer architecture diagram.
- Layer-by-layer symbol reference and invariants.
- The intended primary consumption path (code example).
- Semantic state reference (canonical / degraded / partial / unavailable).
- OneAPI lower-horizon enforcement table.
- Contributor guidance on how to avoid bypassing the pipeline.

---

## Related Documents

- [`docs/DESKTOP_PIPELINE_ARCHITECTURE.md`](DESKTOP_PIPELINE_ARCHITECTURE.md) — **PR-15 authoritative post-closure architecture reference**
- [`docs/OBSERVABILITY_HISTORY.md`](OBSERVABILITY_HISTORY.md) — PR-14 observability and history layer
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
