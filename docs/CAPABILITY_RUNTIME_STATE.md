# CAPABILITY_RUNTIME_STATE.md

## PR-20 (V4) — Capability Runtime State

> **Status:** Additive — does not replace existing capability registries.

---

## Overview

The capability runtime state layer introduces a stable, serialisable model for
expressing the **live operational truth** of each named capability in the
Galaxy system.

Before this layer, capability availability was stored as ad-hoc `available`
booleans, scattered metadata dicts, or inferred from device state at call
time.  This works for simple dispatch but breaks down as routing and planning
need to make decisions based on:

- Is this capability currently reachable?
- Is it degraded (slow, intermittent, partially available)?
- Should routing prefer a specific device or executor?
- Does this capability require human-in-the-loop confirmation?
- Is it restricted to local execution only?

`core/capability_runtime/` provides a clean additive answer to these
questions.

---

## How Runtime State Differs from the Static Registry

| Dimension | `CapabilityRegistry` (existing) | `CapabilityRuntimeRegistry` (new) |
|---|---|---|
| **Purpose** | Schema / discovery (what capabilities exist) | Live state (what is available right now) |
| **Data model** | `CapabilityItem` / `CapabilityContract` | `CapabilityRuntimeState` |
| **Availability** | `available: bool` (static at registration) | `CapabilityAvailability` enum (updated at runtime) |
| **Device binding** | Via `CapabilitySource.DEVICE` + source_id | `device_bindings` + `preferred_device_ids` |
| **Constraint flags** | Not modelled | `CapabilityConstraintFlags` |
| **Health signals** | Not modelled | `reliability_flags` dict |
| **Read surface** | `CapabilityResolver` + `list_tools()` | `GET /api/v1/capabilities/runtime` |
| **Writes** | Static (registration time) | Dynamic (runtime updates) |
| **Replaces existing?** | — | **No.** Additive only. |

---

## Package Structure

```
core/capability_runtime/
├── __init__.py                    # Public API exports
├── capability_state.py            # CapabilityAvailability enum + CapabilityRuntimeState
├── capability_constraint.py       # CapabilityConstraintFlags (frozen dataclass)
├── capability_preference.py       # CapabilityPreference (routing hints)
├── capability_registry_runtime.py # CapabilityRuntimeRegistry singleton
└── capability_summary.py          # CapabilityRuntimeSummary + snapshot helpers
```

---

## Core Concepts

### `CapabilityAvailability`

Four stable posture values:

| Value | Meaning |
|---|---|
| `available` | Fully operational; safe to dispatch. |
| `degraded` | Partially operational; prefer alternatives. |
| `unavailable` | Explicitly offline or blocked; skip dispatch. |
| `unknown` | Not yet reported; treat as degraded for safety. |

### `CapabilityRuntimeState`

The internal store record for a capability.  Fields:

| Field | Type | Purpose |
|---|---|---|
| `name` | `str` | Unique capability identifier. |
| `availability` | `CapabilityAvailability` | Current posture. |
| `device_bindings` | `list[str]` | Devices currently providing this capability. |
| `preferred_device_ids` | `list[str]` | Routing hint: prefer these first. |
| `constraint_flags` | `dict` | Serialised `CapabilityConstraintFlags`. |
| `reliability_flags` | `dict` | Health/reliability signals (`health_score`, `error_rate`, …). |
| `last_updated` | `float` | Unix timestamp of last write. |
| `state_id` | `str` | Auto-generated unique record id. |
| `metadata` | `dict` | Extension metadata. |

### `CapabilityConstraintFlags`

Immutable frozen flags expressing **usage constraints**:

| Flag | Effect |
|---|---|
| `requires_confirmation` | Dispatch must wait for HITL confirmation. |
| `cross_device_restricted` | Must not be dispatched cross-device (local only). |
| `latency_sensitive` | Route via low-latency path only. |
| `device_exclusive` | Only one device may hold this capability active at a time. |
| `requires_elevated_privilege` | Invocation requires elevated permissions. |

### `CapabilityPreference`

Frozen routing-preference model:

| Field | Purpose |
|---|---|
| `preferred_device_ids` | Ordered list of device ids to try first. |
| `preferred_executor` | Preferred executor name/id. |
| `weight` | Routing weight in `[0.0, 1.0]`. |
| `sticky` | Prefer reusing the same device across a session. |

### `CapabilityRuntimeSummary`

Public-safe, read-only summary combining all runtime dimensions.
This is what endpoints and routing helpers consume.

---

## How to Update Runtime State

### Register a new capability state

```python
from core.capability_runtime import (
    CapabilityRuntimeRegistry,
    CapabilityRuntimeState,
    CapabilityAvailability,
    CapabilityConstraintFlags,
)

registry = CapabilityRuntimeRegistry.get_instance()
registry.register(
    CapabilityRuntimeState(
        name="take_screenshot",
        availability=CapabilityAvailability.AVAILABLE,
        device_bindings=["android_01"],
        preferred_device_ids=["android_01"],
        constraint_flags=CapabilityConstraintFlags(latency_sensitive=True).to_dict(),
        reliability_flags={"health_score": 0.95},
    )
)
```

### Partially update an existing state

```python
registry.update("take_screenshot", availability=CapabilityAvailability.DEGRADED.value)
```

### Degrade on device disconnect

```python
registry.update(
    "take_screenshot",
    availability=CapabilityAvailability.UNAVAILABLE.value,
    reliability_flags={"reason": "device_offline"},
)
```

### Feed from device health

```python
from core.unified.device_health import DeviceHealthScorer
from core.capability_runtime import CapabilityRuntimeRegistry, CapabilityAvailability

scorer = DeviceHealthScorer.get_instance()
registry = CapabilityRuntimeRegistry.get_instance()

score = scorer.get_health(device_id)
if score is not None:
    availability = (
        CapabilityAvailability.AVAILABLE if score >= 0.7
        else CapabilityAvailability.DEGRADED if score >= 0.3
        else CapabilityAvailability.UNAVAILABLE
    )
    registry.update(
        capability_name,
        availability=availability.value,
        reliability_flags={"health_score": score},
    )
```

---

## How Routing Should Consume Runtime State

Routing helpers should query the registry **before** selecting a device:

```python
from core.capability_runtime import CapabilityRuntimeRegistry, CapabilityAvailability

registry = CapabilityRuntimeRegistry.get_instance()
state = registry.get_state("take_screenshot")

if state is None or not state.is_routable():
    # fall back or error
    ...

# Use preferred devices if available
if state.preferred_device_ids:
    target_device = state.preferred_device_ids[0]

# Respect constraints
from core.capability_runtime import CapabilityConstraintFlags
cf = CapabilityConstraintFlags.from_dict(state.constraint_flags)
if cf.cross_device_restricted and is_cross_device_request:
    raise RoutingError("capability is local-only")
if cf.requires_confirmation and not has_hitl_approval:
    raise RoutingError("capability requires confirmation")
```

### Projection enrichment

```python
from core.capability_runtime import attach_runtime_summary_to_projection

projection = {"task_id": "t_abc", "result": "..."}
enriched = attach_runtime_summary_to_projection(projection, "take_screenshot")
# enriched now has a "capability_runtime" key
```

---

## Read-Only API Endpoints

### `GET /api/v1/capabilities/runtime`

Returns all registered capability runtime summaries.

```json
{
  "capabilities": {
    "take_screenshot": {
      "capability_name": "take_screenshot",
      "availability": "available",
      "preferred_device_ids": ["android_01"],
      "constraint_flags": ["latency_sensitive"],
      "reliability_notes": "health_score=0.95",
      "device_bindings": ["android_01"],
      "last_updated": 1711000000.0,
      "metadata": {},
      "schema_version": 1
    }
  },
  "total_capabilities": 1,
  "schema_version": 1
}
```

### `GET /api/v1/capabilities/runtime/{capability_name}`

Returns the summary for a single capability.  Returns `404` with a degraded
sentinel when the capability has no recorded runtime state.

---

## What This PR Does NOT Yet Solve

1. **Automated capability scoring from health** — health scores from
   `DeviceHealthScorer` are not yet automatically fed into capability
   availability posture.  A future PR can wire up a background task to
   periodically sync device health → capability runtime state.

2. **Cross-node capability state synchronisation** — the registry is
   process-local.  Multi-node deployments would need a state-sync mechanism
   (e.g., via NATS pub/sub) to keep capability runtime state consistent
   across nodes.

3. **Capability lease / lock model** — the `device_exclusive` flag is
   recorded but not enforced.  A lock/lease enforcement layer is out of
   scope for this PR.

4. **Persistence** — the runtime registry is in-memory only.  State is lost
   on process restart.  A future PR could add persistence via a lightweight
   store.

5. **Automated capability degradation on error threshold** — reliability
   flags record error rates but do not automatically trigger degradation.
   That logic belongs in a future health-to-capability sync worker.

---

## Testing

```bash
pytest tests/test_pr20_capability_runtime.py -v
```

Tests cover:

- `CapabilityAvailability` enum stability and JSON serialisation
- `CapabilityRuntimeState` construction, serialisation, round-trip
- `CapabilityConstraintFlags` flags, sentinels, active_constraints()
- `CapabilityPreference` construction, round-trip
- `CapabilityRuntimeRegistry` register/get/update/deregister, stats
- `CapabilityRuntimeSummary` construction, round-trip, from_dict degradation
- `make_capability_summary` factory with valid and partial/unknown inputs
- `get_capability_runtime_snapshot` shape
- `attach_runtime_summary_to_projection` additive, non-mutating
- Read-only endpoint output shape (`GET /api/v1/capabilities/runtime`)

---

## Architecture Notes

This layer is intentionally **narrow and additive**.  It mirrors the same
pattern established by:

- `core/reliability_contract/` (PR-19) — reliability semantics
- `core/contract_map/` (PR-16) — cross-plane contract map

All three packages:
- Do not modify existing registries or transport
- Expose read-only endpoints for introspection
- Are fully serialisable
- Degrade gracefully on missing data
