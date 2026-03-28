# Desktop Consumption Adapter — Post-PR-9 Guide

> **READ-ONLY REFERENCE.**  This document describes the PR-9 desktop
> consumption adapter layer.  The adapter converts the PR-8 integrated payload
> into a stable client-consumable view-model so desktop status board consumers
> no longer reconstruct truth from multiple sources.

---

## Overview

After PR-8, the Galaxy server exposes one stable integrated payload through
`GET /api/v1/projection/desktop-status-board`.  Before PR-9, desktop consumers
still needed to know how to navigate nested sub-structures within that payload
or, worse, reconstruct state from multiple lower-level endpoints.

PR-9 introduces the **desktop consumption adapter** (`core/desktop_consumption_adapter.py`),
a thin layer that:

1. Accepts the PR-8 `DesktopStatusBoardIntegrationPayload`.
2. Returns a flat, easy-to-use `DesktopClientViewModel`.
3. Eliminates the need for ad-hoc field inspection or multi-endpoint assembly.

---

## Quickstart

```python
from core.projection import (
    build_desktop_status_board_integration_from_runtime,
    adapt_integration_payload,
)
from core.continuum.types import ContinuumState, ContinuumPhase

# 1. Build the PR-8 integrated payload (server side)
state = ContinuumState(phase=ContinuumPhase.MANIFEST)
payload = build_desktop_status_board_integration_from_runtime(
    continuum_state=state
)

# 2. Adapt it into the PR-9 view-model (client/consumer side)
vm = adapt_integration_payload(payload)

# 3. Consume top-level properties — no nested dict traversal needed
if vm.is_canonical:
    print("Routing is fully canonical —", vm.topology_provider_id)
elif vm.is_degraded:
    print("WARNING: legacy fallback active")
elif vm.is_partial:
    print("INFO: partial data —", vm.integration_health)
else:
    print("Topology unavailable")

# Readiness label for display
print(vm.readiness_label())  # e.g. "Canonical" / "Degraded (legacy fallback)"
```

---

## Public Surface

All PR-9 symbols are exported from `core.projection` and `core.desktop_consumption_adapter`.

### `adapt_integration_payload(payload)` → `DesktopClientViewModel`

The main adapter function.  Pass any
`DesktopStatusBoardIntegrationPayload`; receive a `DesktopClientViewModel`.
Never raises — returns a safe minimal view-model on any error.

### `DesktopClientViewModel`

The stable client-consumable view-model.

| Attribute | Type | Description |
|-----------|------|-------------|
| `view_model_id` | `str` | Unique identifier for this view-model instance |
| `adapted_at` | `float` | Unix epoch when this view-model was assembled |
| `readiness_state` | `DesktopReadinessState` | Enum: `canonical` / `degraded` / `partial` / `unavailable` / `unknown` |
| `is_canonical` | `bool` | `True` when topology is fully authoritative |
| `is_degraded` | `bool` | `True` when legacy routing fallback is active |
| `is_partial` | `bool` | `True` when canonical source present but components missing |
| `is_unavailable` | `bool` | `True` when no topology data is available |
| `topology_legacy_fallback_active` | `bool` | Explicit topology legacy fallback flag |
| `routing_legacy_fallback_active` | `bool` | Explicit routing legacy fallback flag |
| `topology_provider_id` | `str \| None` | Provider identifier from the topology block |
| `topology_primary_model_id` | `str \| None` | Primary model identifier from the topology block |
| `topology_route_reason` | `str \| None` | Routing reason from the topology block |
| `routing_authority_source` | `str \| None` | Authority source for the routing decision |
| `provider_routing` | `DesktopProviderRoutingSummary` | Flattened provider/routing summary |
| `oneapi_horizon` | `DesktopOneAPIHorizonSummary` | Flattened OneAPI lower-horizon summary |
| `oneapi_is_lower_horizon_only` | `bool` | Always `True` — OneAPI is never a top-level routing peer |
| `integration_health` | `str` | Rolled-up health: `"ok"` / `"degraded"` / `"advisory"` / `"critical"` / `"unknown"` |
| `authority_indicators` | `dict` | Full authority indicators dict for advanced inspection |
| `adapter_authority` | `str` | Equals `DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY` |

#### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `readiness_label()` | `str` | Human-readable readiness string for display |
| `to_dict()` | `dict` | JSON-serialisable dict |
| `to_json(**kwargs)` | `str` | JSON string |

### `DesktopReadinessState` (enum)

```python
class DesktopReadinessState(str, Enum):
    canonical   = "canonical"    # Fully canonical and authoritative
    degraded    = "degraded"     # Legacy fallback active — surface warning
    partial     = "partial"      # Canonical source but components missing
    unavailable = "unavailable"  # No topology data
    unknown     = "unknown"      # Readiness cannot be determined
```

### `DesktopProviderRoutingSummary`

Flat provider and routing summary.  Key attributes:

| Attribute | Description |
|-----------|-------------|
| `selected_provider` | Currently selected provider identifier |
| `primary_model_id` | Primary model node identifier |
| `vendor_source` | Vendor/source string |
| `routing_authority_source` | Authority source for the routing decision |
| `legacy_routing_fallback_active` | `True` when legacy keys used |
| `route_reason` | Human-readable routing reason |
| `provider_available` | Whether selected provider is available |
| `to_dict()` | JSON-serialisable dict |

### `DesktopOneAPIHorizonSummary`

Flat OneAPI lower-horizon summary.  Key attributes:

| Attribute | Description |
|-----------|-------------|
| `system_layer` | OneAPI system layer identifier |
| `is_lower_horizon_only` | Always `True` |
| `provider_id` | OneAPI provider identifier |
| `available` | Whether the OneAPI block is active/available |
| `to_dict()` | JSON-serialisable dict |

### `DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY`

```python
DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY = (
    "core.desktop_consumption_adapter.adapt_integration_payload"
)
```

Sentinel confirming the view-model was produced by the PR-9 canonical adapter.

---

## Readiness Semantics (preserved from PR-7/8)

The adapter preserves the full PR-7 `TopologyProjectionReadiness` / PR-8
`authority_indicators` semantics and maps them to the flat `DesktopReadinessState`:

| PR-7/8 value | `DesktopReadinessState` | Meaning |
|---|---|---|
| `"canonical"` + `topology_authoritative=True` | `canonical` | Fully authoritative — safe to render |
| `"degraded"` / legacy fallback active | `degraded` | Surface **warning** to operator |
| `"partial"` | `partial` | Surface **partial data** indicator |
| `"unavailable"` | `unavailable` | Show empty/error state |
| Not determinable | `unknown` | Show unknown/loading state |

---

## OneAPI Lower-Horizon Contract (preserved from PR-4)

OneAPI remains a **lower-horizon integration block** only.  The adapter:

- Exposes OneAPI in `vm.oneapi_horizon` as a **distinct sub-summary**.
- Sets `vm.oneapi_is_lower_horizon_only = True` always.
- Never promotes OneAPI to a top-level routing peer.

```python
# Correct OneAPI consumption
if vm.oneapi_horizon.available:
    print("OneAPI layer:", vm.oneapi_horizon.system_layer)

# vm.oneapi_is_lower_horizon_only is always True — never promote to top-level
```

---

## Legacy Fallback Contract (preserved from PR-5)

Legacy routing fallback is always explicitly surfaced:

- `vm.topology_legacy_fallback_active` — topology block is using legacy keys.
- `vm.routing_legacy_fallback_active` — routing layer is using legacy keys.
- `vm.is_degraded` — combined degraded flag for quick display logic.

Consumers **must not** treat data as authoritative when `vm.is_degraded` is
`True`.  Surface a clear warning or degraded badge to the operator.

---

## Machine-Checkable Exports (PR-9)

| Symbol | Module | Type | Description |
|--------|--------|------|-------------|
| `DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY` | `core.desktop_consumption_adapter` | `str` | PR-9 adapter sentinel |
| `DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY` | `core.projection` (package `__all__`) | `str` | Re-exported from package |
| `DesktopClientViewModel` | `core.desktop_consumption_adapter` | class | PR-9 view-model |
| `DesktopReadinessState` | `core.desktop_consumption_adapter` | str Enum | Readiness state enum |
| `DesktopProviderRoutingSummary` | `core.desktop_consumption_adapter` | class | Flat routing summary |
| `DesktopOneAPIHorizonSummary` | `core.desktop_consumption_adapter` | class | Flat OneAPI summary |
| `adapt_integration_payload` | `core.desktop_consumption_adapter` | function | Main adapter function |
| `adapt_integration_payload` | `core.projection` (package `__all__`) | function | Re-exported from package |

---

## Post-PR-9 Consumption Guidance

### Preferred path (PR-9)

```
GET /api/v1/projection/desktop-status-board
    → DesktopStatusBoardIntegrationPayload   (PR-8)
    → adapt_integration_payload(payload)     (PR-9)
    → DesktopClientViewModel                 (consume directly)
```

1. Fetch `GET /api/v1/projection/desktop-status-board`.
2. Build the payload (or receive it directly from the server).
3. Call `adapt_integration_payload(payload)` to obtain the view-model.
4. Consume `vm.is_canonical`, `vm.is_degraded`, `vm.topology_provider_id`,
   `vm.integration_health`, `vm.oneapi_horizon`, etc. directly.
5. **Do not** reconstruct state from scattered lower-level endpoints.
6. **Do not** promote `oneapi_horizon` to a top-level routing peer.
7. **Do** surface `vm.is_degraded` / `vm.topology_legacy_fallback_active`
   clearly to the operator when `True`.

### Legacy / diagnostic paths (still available)

The lower-level endpoints remain available for diagnostic use:

| Endpoint | When to use |
|----------|-------------|
| `GET /api/v1/projection/runtime` | Raw RuntimeProjection (diagnostic) |
| `GET /api/v1/projection/canonical-routing` | Canonical routing detail (diagnostic) |
| `GET /api/v1/projection/server-canonicalization-status` | Legacy demotion status (diagnostic) |
| `GET /api/v1/projection/desktop-topology` | Topology-ready block only (diagnostic) |

---

## What PR-9 Does NOT Do

- Does **not** implement the final polished desktop UI (that is PR-10+).
- Does **not** add new server-side endpoints.
- Does **not** undo or modify PR-4 through PR-8 contracts.
- Does **not** change OneAPI's lower-horizon-only status.
- Does **not** change legacy fallback demotion semantics.

---

## Related Documentation

- [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) — Status Board V2 overview and PR-8 integration contract
- [`docs/SERVER_SIDE_CANONICALIZATION.md`](SERVER_SIDE_CANONICALIZATION.md) — Legacy routing demotion (PR-5)
- [`docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md`](RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md) — Topology projection (PR-6/7)
- [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md) — OneAPI lower-horizon position (PR-4)
