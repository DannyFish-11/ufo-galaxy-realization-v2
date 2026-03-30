# Projection Output Authority

> **Status:** Canonical — established in the projection/status contracts
> canonicalization PR.
> **Scope:** Runtime-facing projection/output authority model.
>
> Related: [`docs/SERVER_SIDE_CANONICALIZATION.md`](SERVER_SIDE_CANONICALIZATION.md) ·
> [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) ·
> [`docs/DESKTOP_CONSUMPTION_ADAPTER.md`](DESKTOP_CONSUMPTION_ADAPTER.md) ·
> [`docs/RUNTIME_PROJECTION.md`](RUNTIME_PROJECTION.md)

---

## 1. Overview

This document is the authoritative reference for understanding **who owns
runtime-facing output state** in the Galaxy codebase.

The core principle:

> **Runtime truth is compiled once, by one authority, and all consumers read
> from that single output.**

Prior to this canonicalization, multiple route modules (``system.py``,
``observability.py``, legacy dashboard routes) independently assembled runtime
status by importing directly from subsystem modules — producing multiple
competing truths for the same system state.

This document defines the canonical output authority model that eliminates
that parallel assembly.

---

## 2. Canonical Output Authority Stack

```
┌─────────────────────────────────────────────────────────────────────────┐
│  CANONICAL OUTPUT AUTHORITY (single compilation point)                  │
│  ─────────────────────────────────────────────────────                  │
│  core.projection.runtime_truth_compiler.compile_runtime_truth()         │
│  sentinel: RUNTIME_TRUTH_COMPILER_AUTHORITY                             │
│                                                                          │
│  Sources (gathered once per call):                                       │
│    1. ContinuumState     ← core.continuum / CognitiveFieldEngine         │
│    2. TopologyRoutePlan  ← core.model_topology.TopologyRouter            │
│    3. OneAPIStatus       ← core.oneapi_system_position (lower-horizon)  │
│    4. SystemResource     ← core.system_resource.SystemResourceRegistry  │
│    5. DevicePresence     ← core.routes._shared (registered/online)      │
└─────────────────────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┴──────────────────────────┐
        │  CANONICAL READ-ONLY ENDPOINTS              │
        │                                             │
        │  GET /api/v1/projection/runtime-truth       │  ← RuntimeTruthSnapshot
        │  GET /api/v1/projection/desktop-status-board│  ← DesktopStatusBoardIntegrationPayload (PR-8)
        │  GET /api/v1/projection/runtime             │  ← RuntimeProjection
        └─────────────────────────────────────────────┘
                          │
        ┌─────────────────┴──────────────────────────┐
        │  DESKTOP CONSUMER ADAPTER                   │
        │                                             │
        │  core.desktop_consumption_adapter           │
        │  adapt_integration_payload(payload)         │
        │  → DesktopClientViewModel (flat, PR-9)      │
        └─────────────────────────────────────────────┘
```

---

## 3. Canonical Projection Module Chain

The full canonical chain, from source to consumer:

| Step | Module | Authority Sentinel |
|------|--------|--------------------|
| 1 | `core.projection.runtime_truth_compiler` | `RUNTIME_TRUTH_COMPILER_AUTHORITY` |
| 2 | `core.projection.projection_compiler` | `PROJECTION_COMPILER_AUTHORITY` |
| 3 | `contracts.desktop_status_projection` | `PROJECTION_CONTRACT_AUTHORITY` |
| 4 | `contracts.desktop_status_projection.DesktopTopologyProjection` | `TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY` |
| 5 | `contracts.desktop_status_projection.TopologyProjectionQualityBlock` | `TOPOLOGY_READINESS_CONTRACT_AUTHORITY` |
| 6 | `contracts.desktop_status_projection.DesktopStatusBoardIntegrationPayload` | `DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY` |
| 7 | `core.desktop_consumption_adapter.adapt_integration_payload` | `DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY` |

All sentinels are machine-checkable strings.  Consumers can verify provenance::

```python
from core.projection import RUNTIME_TRUTH_COMPILER_AUTHORITY
snapshot = compile_runtime_truth()
assert snapshot.compiler_authority == RUNTIME_TRUTH_COMPILER_AUTHORITY
```

---

## 4. Canonical Endpoint Directory

### 4.1 Canonical endpoints

These endpoints assemble output exclusively through the canonical projection
path.  Desktop consumers and status board UI should prefer these.

| Endpoint | What it returns | Module |
|----------|-----------------|--------|
| `GET /api/v1/projection/runtime-truth` | `RuntimeTruthSnapshot` — compiled from all canonical sources once per request | `core.routes.projection` |
| `GET /api/v1/projection/desktop-status-board` | `DesktopStatusBoardIntegrationPayload` — PR-8 integrated payload with topology + routing + OneAPI + authority indicators | `core.routes.projection` |
| `GET /api/v1/projection/runtime` | `RuntimeProjection` — continuum + topology projection | `core.routes.projection` |
| `GET /api/v1/projection/desktop-topology` | `DesktopTopologyProjection` — PR-6 topology-ready block | `core.routes.projection` |
| `GET /api/v1/projection/server-canonicalization-status` | PR-5 server-side canonicalization status | `core.routes.projection` |
| `GET /api/v1/contracts/planes` | Cross-plane contract map — planes | `core.routes.contracts` |
| `GET /api/v1/contracts/messages` | Cross-plane contract descriptors | `core.routes.contracts` |

### 4.2 Compatibility / management endpoints

These endpoints serve operational, management, or legacy diagnostic purposes.
They do **not** claim canonical projection authority.  Where they surface
routing or status state, that state is sourced from legacy/subsystem paths
(``MultiLLMRouter``, node registry, service manager) rather than the
canonical projection compiler.

| Endpoint | Purpose | Canonical alternative |
|----------|---------|-----------------------|
| `GET /api/v1/system/status` | Service lifecycle / node / task counts | `GET /api/v1/projection/runtime-truth` |
| `GET /api/v1/observability/model-route` | Live MultiLLMRouter routing diagnostics | `GET /api/v1/projection/runtime-truth` → `topology` block |
| `GET /api/v1/observability/gateway` | Gateway & device presence diagnostics | `GET /api/v1/projection/runtime-truth` → `device_presence` |
| `GET /api/v1/system/health` | Process health check | n/a (operational) |
| `GET /api/v1/system/config` | Sanitised config snapshot | n/a (management) |

---

## 5. Key Design Rules

### 5.1 Do not assemble runtime truth in route handlers

Route handlers must **not** import directly from subsystem modules to
assemble status payloads.  Instead, call
`core.projection.runtime_truth_compiler.compile_runtime_truth()`:

```python
# ✅ Correct
from core.projection.runtime_truth_compiler import compile_runtime_truth
snapshot = compile_runtime_truth()
return JSONResponse(snapshot.to_dict())

# ❌ Wrong — parallel truth assembly
from core.multi_llm_router import get_llm_router
from core.system_resource import get_system_resource_registry
# ... building status payload manually
```

### 5.2 OneAPI is always lower-horizon

OneAPI is **never** a top-layer provider peer.  The `oneapi` field in every
projection output always carries `system_layer == "aggregator_integration"`.
The `RuntimeTruthSnapshot.oneapi_is_lower_horizon_only` property is always
`True`.  See `core/oneapi_system_position.py`.

### 5.3 Legacy fields are demotion-annotated

Top-level UCP routing keys (`chosen_model`, `chosen_provider`, etc.) are
legacy/compatibility bridges.  When a `TopologyRoutePlan` is available,
consumers must source routing truth from it, not from these keys.

```python
from contracts.desktop_status_projection import LEGACY_UCP_ROUTING_KEYS
# These keys are compatibility-only when topology_route_plan is present
print(LEGACY_UCP_ROUTING_KEYS)
```

### 5.4 Compatibility endpoints adapt from canonical outputs

Where a legacy/compatibility endpoint must expose routing or status data, it
should obtain that data from the canonical projection output rather than
re-deriving independently.  This is the "adapter/facade over canonical
projection" pattern.

---

## 6. UI Surface Authority

The `core.ui_surface_authority` module is the authoritative registry for
which UI surfaces hold which roles:

| Surface | Role |
|---------|------|
| `windows_client.status_board_v2` | `PROJECTION_DRIVEN` (canonical) |
| `dashboard.backend.main` | `LEGACY_UI` (management panel) |
| `windows_client._legacy` | `LEGACY_SHELL` (compatibility only) |

Only `PROJECTION_DRIVEN` surfaces are canonical outward status truth.
See `core/ui_surface_authority.py`.

---

## 7. Adding New Projection Outputs

When adding a new runtime-facing output endpoint:

1. **Add the data source to `compile_runtime_truth()`** in
   `core/projection/runtime_truth_compiler.py`.  Source compilers are
   per-subsystem functions prefixed with `_compile_`.
2. **Expose the field in `RuntimeTruthSnapshot`** (add a new `__slots__`
   entry and serialise it in `to_dict()`).
3. **Add the endpoint to `core/routes/projection.py`** using the
   `_assemble_runtime_truth_payload()` helper or a dedicated assembler that
   calls `compile_runtime_truth()`.
4. **Do not** add a new truth-assembly path in `system.py`, `observability.py`,
   or any other route module.

---

## 8. PR Chain Summary

| PR | Contribution to canonical output model |
|----|----------------------------------------|
| PR-2 | `TopologyRoutePlan` as sole canonical routing output |
| PR-3 | `vendor_source`/`oneapi_source` in `ModelRoutingProjection`; `/canonical-routing` endpoint |
| PR-4 | OneAPI lower-horizon cleanup; `oneapi_integration` block in `DesktopStatusProjection` |
| PR-5 | Legacy UCP key demotion; `legacy_routing_fallback_active`; `/server-canonicalization-status` endpoint |
| PR-6 | `DesktopTopologyProjection`; `/desktop-topology` endpoint |
| PR-7 | `TopologyProjectionQualityBlock`; readiness/quality semantics |
| PR-8 | `DesktopStatusBoardIntegrationPayload`; `/desktop-status-board` integrated endpoint |
| PR-9 | `DesktopClientViewModel` via `adapt_integration_payload()`; flat consumer view-model |
| **This PR** | **`RuntimeTruthSnapshot` via `compile_runtime_truth()`; `/runtime-truth` canonical endpoint; route compatibility annotations; this document** |
