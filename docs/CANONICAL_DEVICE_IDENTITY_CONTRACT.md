# Canonical Device Identity Contract

**Module:** `contracts/canonical_device_identity.py`  
**Introduced:** PR-56 (Server PRD-01 — Canonical Runtime Contracts)

## Purpose

`CanonicalDeviceIdentity` is the **pure identity contract** for a Galaxy runtime
device.  It answers *"what is this device and what can it do?"* without carrying
any ephemeral presence or connection state.

## Design Principle: Identity ≠ Presence

| Contract | Answers | Does NOT carry |
|---|---|---|
| `CanonicalDeviceIdentity` | What is this device? What can it do? | Transport refs, WebSocket objects, connection state, session IDs, task pointers |
| `RuntimePresenceRecord` | Is the device reachable right now? How? | Capability truth, platform classification, owner metadata |
| `RegisteredRuntimeDevice` | Complete read view of a single device | (retained as sole canonical external read contract) |

## Relationship to `RegisteredRuntimeDevice`

`RegisteredRuntimeDevice` (PR-5 / PR-29) remains the **sole canonical external
single-device read contract**.  `CanonicalDeviceIdentity` is a *narrower,
presence-free projection* suitable for:

- Device-eligibility evaluation (can this device run task X?)
- Capability-driven routing and scheduling
- Cross-device formation and group membership decisions
- Identity-authority services that must remain free of ephemeral state

## Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `device_id` | `str` | — | Globally stable device identifier |
| `device_name` | `str` | `""` | Human-readable name |
| `owner_id` | `str` | `""` | Owner account/principal identifier |
| `platform` | `str` | `"unknown"` | OS/platform family: `android`, `ios`, `windows`, `linux`, `macos`, `cloud`, `embedded` |
| `device_type` | `str` | `""` | Fine-grained type, e.g. `"android_phone"` |
| `form_factor` | `str` | `""` | Physical form: `phone`, `tablet`, `desktop`, etc. |
| `capabilities` | `List[str]` | `[]` | Named capabilities |
| `supported_actions` | `List[str]` | `[]` | Canonical action names |
| `capability_schemas` | `Dict[str, Any]` | `{}` | Per-capability JSON schema fragments |
| `supports_local_autonomy` | `bool` | `False` | Can execute tasks using local inference |
| `supports_remote_handoff` | `bool` | `False` | Can receive cross-device handoff |
| `groups` | `List[str]` | `[]` | Formation/group labels |
| `tags` | `List[str]` | `[]` | Searchable tags |
| `metadata` | `Dict[str, Any]` | `{}` | Extension fields (no transport objects) |

## What this contract must NOT carry

- `transport` / WebSocket references / socket objects
- `connection_id` / `connection_state`
- `session_id` / `active_session_ids`
- `online` / `last_seen` / `routable` / `degraded`
- `current_task_id` / `pending_task_ids`

## Adapters

```python
from contracts.canonical_device_identity import (
    CanonicalDeviceIdentity,
    build_canonical_device_identity,
    from_registered_runtime_device,
    from_android_registration,
)

# From an existing RegisteredRuntimeDevice (PR-29)
identity = from_registered_runtime_device(rrd)

# From a raw Android registration payload
identity = from_android_registration({"device_id": "p1", "platform": "android"})

# Generic builder
identity = build_canonical_device_identity(
    device_id="phone_001",
    platform="android",
    capabilities=["screen", "camera"],
    supports_local_autonomy=True,
)
```

## Package root re-exports

```python
from contracts import CanonicalDeviceIdentity, build_canonical_device_identity
from contracts import canonical_identity_from_rrd, canonical_identity_from_android
```

## Related

- [`RuntimePresenceRecord`](./RUNTIME_PRESENCE_RECORD_CONTRACT.md) — connection state
- [`RegisteredRuntimeDevice`](./REGISTERED_RUNTIME_DEVICE_CONTRACT.md) — full external read contract
- [`NormalizedIngressEvent`](./INGRESS_NORMALIZATION_CONTRACT.md) — gateway ingress schema
