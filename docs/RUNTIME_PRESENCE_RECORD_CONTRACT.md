# Runtime Presence Record Contract

**Module:** `contracts/runtime_presence_record.py`  
**Introduced:** PR-56 (Server PRD-01 — Canonical Runtime Contracts)

## Purpose

`RuntimePresenceRecord` is the **canonical runtime presence and connection-state
contract** for a Galaxy device.  It answers *"is this device reachable right now,
and how?"* without carrying any long-term identity or capability truth.

## Design Principle: Presence ≠ Identity

| Contract | Answers | Does NOT carry |
|---|---|---|
| `RuntimePresenceRecord` | Is the device connected? Via what transport? What tasks does it have? | Capabilities, platform, owner, groups, tags |
| `CanonicalDeviceIdentity` | What is this device? What can it do? | Transport refs, session IDs, task pointers |
| `RegisteredRuntimeDevice` | Complete read view of a single device | (retained as sole canonical external read contract) |

## Relationship to `RegisteredRuntimeDevice`

`RegisteredRuntimeDevice` (PR-5 / PR-29) remains the **sole canonical external
single-device read contract**.  `RuntimePresenceRecord` is a *narrower,
identity-free projection* suitable for:

- Online/offline routing decisions
- Heartbeat and reconnect logic
- Task assignment gating (is the device currently reachable?)
- Presence-authority services (future PRD-04: `RuntimePresenceService`)

## Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `device_id` | `str` | — | Stable device identifier |
| `connection_id` | `Optional[str]` | `None` | Ephemeral connection ID; changes on reconnect |
| `session_id` | `Optional[str]` | `None` | Runtime session ID; may persist across short disconnects |
| `transport` | `str` | `"unknown"` | Active transport: `websocket`, `http`, `webrtc`, `local`, `bridge` |
| `connection_state` | `str` | `"disconnected"` | Low-level state: `connected`, `connecting`, `reconnecting`, `disconnecting`, `disconnected` |
| `online` | `bool` | `False` | True when device has a healthy active connection |
| `last_seen` | `float` | `0.0` | Unix timestamp of most recent heartbeat/message |
| `routable` | `bool` | `False` | True when device can receive dispatched tasks |
| `degraded` | `bool` | `False` | True when online but operating in reduced capacity |
| `current_task_id` | `Optional[str]` | `None` | ID of task currently executing |
| `pending_task_ids` | `List[str]` | `[]` | IDs of queued tasks |

## What this contract must NOT carry

- `capabilities` / `supported_actions`
- `platform` / `device_type` / `form_factor`
- `owner_id` / `groups` / `tags`
- Long-term metadata about the device

## Helper methods

| Method | Returns | Description |
|---|---|---|
| `is_connected()` | `bool` | `connection_state == "connected"` |
| `is_available_for_dispatch()` | `bool` | `online and routable and not degraded` |
| `seconds_since_seen()` | `float` | Elapsed seconds since `last_seen` (inf if 0) |

## Transport normalisation

`RuntimeTransport.normalise(raw)` maps common aliases:

| Input | Canonical |
|---|---|
| `"ws"`, `"wss"` | `"websocket"` |
| `"rest"` | `"http"` |
| `"rtc"`, `"peer"` | `"webrtc"` |
| `None` | `"unknown"` |

## Adapters

```python
from contracts.runtime_presence_record import (
    RuntimePresenceRecord,
    RuntimeTransport,
    build_runtime_presence_record,
    from_registered_runtime_device,
)

# From an existing RegisteredRuntimeDevice (PR-29)
record = from_registered_runtime_device(rrd)

# Generic builder
record = build_runtime_presence_record(
    device_id="phone_001",
    online=True,
    transport="websocket",
    connection_state="connected",
    routable=True,
    last_seen=time.time(),
)
```

## Package root re-exports

```python
from contracts import RuntimePresenceRecord, RuntimeTransport
from contracts import build_runtime_presence_record, presence_record_from_rrd
```

## Related

- [`CanonicalDeviceIdentity`](./CANONICAL_DEVICE_IDENTITY_CONTRACT.md) — pure identity
- [`RegisteredRuntimeDevice`](./REGISTERED_RUNTIME_DEVICE_CONTRACT.md) — full external read contract
- [`NormalizedIngressEvent`](./INGRESS_NORMALIZATION_CONTRACT.md) — gateway ingress schema
