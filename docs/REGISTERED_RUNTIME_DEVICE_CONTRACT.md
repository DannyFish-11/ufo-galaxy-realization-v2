# Registered Runtime Device Contract

**PR-29** (introduced) · **PR-5** (standardized as sole canonical contract)

**Introduced** in `contracts/registered_runtime_device.py` (PR-29).
**Standardized as the sole canonical external single-device read contract** in PR-5.

> **PR-5 Canonical Authority:** `RegisteredRuntimeDevice` is the **sole
> canonical external single-device read contract** for the Galaxy / OpenClawd
> system.  No parallel single-device external schema may be created.  All major
> device sources — UDM, DeviceRouter, AndroidBridge, DeviceRegistry,
> DeviceAgentManager — provide a stable adapter into this contract.  It is the
> only authoritative stable read projection for a single device.  It sits
> below `MultiDeviceRuntimeProjection` (the top-level multi-device aggregation)
> and above the internal models of `UnifiedDeviceManager`, `DeviceRouter`,
> `DeviceRegistry`, and `AndroidBridge`.  See
> `docs/architecture/unified_device_registration_runtime_participation_v1.md`
> for the normative V1 architecture spec.

---

## What is a Registered Runtime Device?

A **Registered Runtime Device** is the canonical, serialisable identity and
state carrier for any physical (or virtual) device that participates in the
Galaxy / OpenClawd system as a runtime-capable endpoint.

It is the single authoritative answer to:

> *"What is a runtime-capable device in this system?"*

Before this contract, the answer was fragmented across multiple overlapping
models:

| Source module | Model | Notes |
|---|---|---|
| `core/schemas/device.py` | `DeviceModel` | Pydantic V2, primary SSOT in device registry |
| `core/unified/models.py` | `UnifiedDevice` | UDM SSOT, simpler field set |
| `galaxy_gateway/device_router.py` | `Device` | Gateway runtime wrapper, WebSocket-focused |
| `galaxy_gateway/android_bridge.py` | `AndroidDevice` | AIP v3, bitmask capabilities |
| `core/device_agent_manager.py` | `DeviceInfo` | Dataclass, agent-lifecycle focus |
| `core/mesh/body_mesh_registry.py` | `BodyEntry` | Mesh role assignment, no connection info |

The `RegisteredRuntimeDevice` contract sits *above* all of these as a
normalisation layer.  It does not replace any of them; it provides a stable
view that can be consumed by runtime, projection, and governance layers without
coupling to any single internal model.

---

## Contract structure

```
RegisteredRuntimeDevice
├── device_id              str  (required)
├── device_name            str
├── owner_id               Optional[str]
├── platform               RuntimeDevicePlatform  (android/ios/windows/…)
├── form_factor            RuntimeDeviceFormFactor (phone/desktop/…)
├── device_type            str  (fine-grained, e.g. "android_phone")
├── status                 RuntimeDeviceStatus  (online/offline/busy/…)
├── online                 bool  (convenience: True when ONLINE or BUSY)
├── last_seen              Optional[float]  (Unix timestamp)
│
├── connection             RuntimeConnectionSummary
│   ├── state              RuntimeConnectionState
│   ├── transport          str  ("websocket", "http", …)
│   ├── endpoint           str
│   ├── ip_address         str
│   ├── port               int
│   ├── connected_at       Optional[float]
│   └── reconnect_count    int
│
├── capabilities           RuntimeCapabilityProfile
│   ├── capabilities       List[str]  (name strings)
│   ├── capability_flags   int  (Android bitmask; 0 if not applicable)
│   └── supported_actions  List[str]  ("click", "swipe", …)
│
├── autonomy               RuntimeAutonomySummary
│   ├── runtime_enabled         bool
│   ├── supports_local_autonomy bool
│   ├── supports_remote_handoff bool
│   ├── runtime_id              Optional[str]
│   └── runtime_version         Optional[str]
│
├── session_presence       RuntimeSessionPresence
│   ├── active_session_ids  List[str]
│   ├── current_task_id     Optional[str]
│   └── pending_task_ids    List[str]
│
├── participation_hints    RuntimeParticipationHints
│   ├── body_mesh_roles    List[str]  ("perception", "action", "presence")
│   ├── is_primary_body    bool
│   ├── groups             List[str]
│   └── tags               List[str]
│
└── metadata               Dict[str, Any]
```

All fields are optional except `device_id`.

---

## How it differs from existing device paths

| Aspect | Raw registration paths | `RegisteredRuntimeDevice` |
|---|---|---|
| Source | Per-system model (UDM, router, bridge, …) | Normalised canonical view |
| Serialisation | Ad hoc dicts or Pydantic models | Stable `to_dict()` / `to_json()` |
| Capability representation | Varies (list of strings, enum, bitmask) | Unified `RuntimeCapabilityProfile` |
| Connection state | Varies (websocket object, bool, string) | `RuntimeConnectionSummary` |
| Autonomy hints | Not captured uniformly | `RuntimeAutonomySummary` |
| Session references | Not captured uniformly | `RuntimeSessionPresence` |
| Mesh hints | Only in `BodyMeshRegistry` | `RuntimeParticipationHints` |

---

## Adapter / builder functions

Five typed adapters normalise all major existing device shapes, and a generic
builder covers ad-hoc construction.  All adapters catch exceptions internally
and degrade to a minimal valid contract so that partial or missing data never
causes a hard failure.

### `from_udm_device(device)`
Builds from a `core.unified.models.UnifiedDevice` (UDM SSOT).

```python
from contracts.registered_runtime_device import from_udm_device

udm = get_unified_device_manager()
device = udm.get_device("phone_001")
contract = from_udm_device(device)
```

### `from_router_device(device)`
Builds from a `galaxy_gateway.device_router.Device` gateway wrapper.

```python
from contracts.registered_runtime_device import from_router_device

router_dev = device_router.devices.get("phone_001")
contract = from_router_device(router_dev)
```

### `from_android_registration(data)`
Builds from a raw Android registration message dict (AIP v3 format).

```python
from contracts.registered_runtime_device import from_android_registration

contract = from_android_registration({
    "device_id": "phone_001",
    "name": "My Phone",
    "model": "Pixel 9",
    "os_version": "15",
    "capabilities": 0b11011,   # bitmask
    "app_version": "3.2.0",
})
```

### `from_device_registry_record(device)`
Builds from a `core.schemas.device.DeviceModel` registry record.

```python
from contracts.registered_runtime_device import from_device_registry_record

reg_dev = device_registry.get("phone_001")
contract = from_device_registry_record(reg_dev)
```

### `from_device_agent_manager_record(device)`
Builds from a `core.device_agent_manager.DeviceInfo` dataclass.  Covers the
agent-backed device source — devices registered through `DeviceAgentManager`.

```python
from contracts.registered_runtime_device import from_device_agent_manager_record

device_info = device_agent_manager.get_device_info("phone_001")
contract = from_device_agent_manager_record(device_info)
```

The adapter maps:
- `DeviceInfo.device_id` → `device_id`
- `DeviceInfo.device_name` → `device_name`
- `DeviceInfo.device_type` (enum or string) → `platform` / `device_type`
- `DeviceInfo.status` (enum or string) → `status` / `online`
- `DeviceInfo.capabilities` (list of `DeviceCapability` enums) → `capabilities`
- `DeviceInfo.last_heartbeat` (datetime) → `last_seen` (Unix timestamp)
- `DeviceInfo.metadata` → `metadata`
- `DeviceInfo.registered_at` (datetime) → `metadata["registered_at"]` (ISO string)

### `build_registered_runtime_device(**kwargs)`
Generic builder — use when you have individual field values rather than an
existing model object.

```python
from contracts.registered_runtime_device import build_registered_runtime_device

contract = build_registered_runtime_device(
    device_id="desktop_001",
    device_name="Dev Workstation",
    platform="windows",
    form_factor="desktop",
    capabilities=["screen", "keyboard", "mouse"],
    runtime_enabled=True,
    supports_local_autonomy=True,
    status="online",
)
```

---

## How local autonomy and remote-handoff support are represented

The `autonomy` sub-contract (`RuntimeAutonomySummary`) captures *intent and
support declarations* rather than live activation state:

| Field | Meaning |
|---|---|
| `runtime_enabled` | The Galaxy runtime is currently active on this device |
| `supports_local_autonomy` | The device can execute tasks without constant server involvement |
| `supports_remote_handoff` | The device can participate in cross-device handoff |
| `runtime_id` | Identifier of the local runtime instance (when active) |
| `runtime_version` | Version of the device-side runtime client |

The actual **Local Runtime Host contract** (PR-30) will carry live activation
state, lock/lease semantics, and adoption paths.

---

## Read-only API endpoint

PR-29 adds one additive read-only endpoint:

```
GET /api/v1/devices/{device_id}/runtime-contract
```

Returns the canonical `RegisteredRuntimeDevice` JSON for the given device,
normalising from the UDM SSOT, falling back to the device registry and the
legacy cache.  All existing endpoints remain unchanged.

Example response:

```json
{
  "device_id": "phone_001",
  "device_name": "My Phone",
  "owner_id": null,
  "platform": "android",
  "form_factor": "unknown",
  "device_type": "android",
  "status": "online",
  "online": true,
  "last_seen": 1742553404.0,
  "connection": {
    "state": "disconnected",
    "transport": "",
    "endpoint": "",
    "ip_address": "",
    "port": 0,
    "connected_at": null,
    "reconnect_count": 0
  },
  "capabilities": {
    "capabilities": ["screen", "camera"],
    "capability_flags": 0,
    "supported_actions": []
  },
  "autonomy": {
    "runtime_enabled": true,
    "supports_local_autonomy": false,
    "supports_remote_handoff": false,
    "runtime_id": null,
    "runtime_version": null
  },
  "session_presence": {
    "active_session_ids": [],
    "current_task_id": null,
    "pending_task_ids": []
  },
  "participation_hints": {
    "body_mesh_roles": [],
    "is_primary_body": false,
    "groups": [],
    "tags": []
  },
  "metadata": {}
}
```

---

## What this PR explicitly does NOT do

- No **Local Runtime Host contract** (PR-30) — live runtime lock/lease semantics.
- No **Handoff Envelope v2 redesign** (PR-31).
- No **Mesh Membership contract** (PR-32) — binding role assignments.
- No **Mesh Session contract** (PR-33).
- No device registration flow rewrite — existing paths unchanged.
- No full `Node_71` rewrite.
- No runtime code refactors — this contract is purely additive.
- No command/write semantics added or changed.

---

## Architectural position

```
UnifiedDeviceManager (write SSOT)
  └── all registration paths converge here
──────────────────────────────────────────
PR-29  RegisteredRuntimeDevice             ← canonical single-device read contract
──────────────────────────────────────────
PR-38  MultiDeviceRuntimeProjection        ← canonical top-level multi-device
         (aggregates RegisteredRuntimeDevice     read projection; sits above
          entries across all devices)            RegisteredRuntimeDevice
```

`RegisteredRuntimeDevice` is the per-device unit of the canonical read model.
`MultiDeviceRuntimeProjection` is the aggregated view across all devices.
Any consumer that needs the full multi-device view should read
`MultiDeviceRuntimeProjection`; any consumer that needs the state of a single
device should read `RegisteredRuntimeDevice`.

This contract is UI-agnostic.  Any future observability surface, operator
tooling, governance layer, or routing / scheduling component should consume
`RegisteredRuntimeDevice` or `MultiDeviceRuntimeProjection` directly.  No UI
or dashboard component is required for this contract to be useful.

PR-29 introduces the contract; PR-5 standardizes it as the sole canonical
external single-device read contract, completes all source projections, and
prohibits parallel single-device external schemas.

---

## Import paths

```python
# Direct from contracts package
from contracts.registered_runtime_device import (
    RegisteredRuntimeDevice,
    RuntimeConnectionSummary,
    RuntimeCapabilityProfile,
    RuntimeAutonomySummary,
    RuntimeSessionPresence,
    RuntimeParticipationHints,
    RuntimeDevicePlatform,
    RuntimeDeviceFormFactor,
    RuntimeDeviceStatus,
    RuntimeConnectionState,
    build_registered_runtime_device,
    from_udm_device,
    from_router_device,
    from_android_registration,
    from_device_registry_record,
    from_device_agent_manager_record,
)

# Via contracts package root
from contracts import (
    RegisteredRuntimeDevice,
    build_registered_runtime_device,
    from_udm_device,
    from_device_agent_manager_record,
    # …
)

# Via core.unified (re-exported for convenience)
from core.unified import (
    RegisteredRuntimeDevice,
    build_registered_runtime_device,
    from_udm_device,
    from_device_agent_manager_record,
    # …
)
```
