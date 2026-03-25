# Ingress Normalization Contract

**Module:** `galaxy_gateway/protocol/normalized_ingress_event.py`  
**Introduced:** PR-56 (Server PRD-02 — Unified Ingress Normalization Layer)

## Purpose

`NormalizedIngressEvent` is the **canonical schema that all gateway WS/REST
ingress produces** after protocol normalization.  It is the stable internal
representation that all handlers, routers, and service layers consume.

## Design Principle: Legacy Aliases Stay at the Gateway Edge

```
┌──────────────────────────────────────────────────────────┐
│                    Gateway Edge                          │
│                                                          │
│  /ws/device/{id}  ──┐                                   │
│  /ws/android      ──┤                                   │
│  REST /register   ──┤──► compat.normalise_to_v3_dict()  │
│  AIP v1 client    ──┤    (type aliases, version, fields) │
│  AIP v2 client    ──┘                                   │
│                           │                              │
│                           ▼                              │
│              to_normalized_ingress_event()               │
│                           │                              │
└───────────────────────────┼──────────────────────────────┘
                            │
                            ▼
                 NormalizedIngressEvent
                 ┌─────────────────────┐
                 │ kind: "task_submit" │  ← always canonical
                 │ trace_id: "abc..."  │  ← always non-empty
                 │ route_mode: "cross" │  ← always non-empty
                 │ device_id: "dev_1" │
                 │ payload: {...}      │
                 └─────────────────────┘
                            │
                            ▼
              Internal handlers / services
              (never see legacy type aliases)
```

## Guarantees

After `to_normalized_ingress_event()` produces a `NormalizedIngressEvent`:

1. **`kind`** — always a canonical `IngressEventKind` string, never a legacy alias
2. **`trace_id`** — always non-empty (generated if absent in input)
3. **`route_mode`** — always non-empty (defaults to `"cross_device"`)
4. **`aip_version`** — always `"3.0"` (v1/v2 inputs are upgraded)
5. **`payload`** — always a dict (never `None`)

## Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `event_id` | `str` | auto | Unique event identifier (generated at normalization) |
| `kind` | `str` | — | Canonical event kind (see `IngressEventKind`) |
| `device_id` | `str` | `"unknown"` | Stable device identifier |
| `trace_id` | `str` | — | Distributed trace ID (always non-empty) |
| `route_mode` | `str` | `"cross_device"` | Routing mode |
| `runtime_session_id` | `Optional[str]` | `None` | Session ID |
| `idempotency_key` | `Optional[str]` | `None` | Idempotency key |
| `task_id` | `Optional[str]` | `None` | Task identifier |
| `message_id` | `Optional[str]` | `None` | Message-level ID |
| `correlation_id` | `Optional[str]` | `None` | Request-response correlation |
| `aip_version` | `str` | `"3.0"` | Detected protocol version (after upgrade) |
| `original_type` | `Optional[str]` | `None` | Raw type string before normalization (debug only) |
| `ingress_ts` | `float` | `time.time()` | Unix timestamp of normalization |
| `payload` | `Dict[str, Any]` | `{}` | Application payload (tracing fields removed) |
| `extra_fields` | `Dict[str, Any]` | `{}` | Non-schema fields (platform metadata etc.) |

## Canonical Kind Vocabulary (`IngressEventKind`)

| Constant | Wire value | AIP v3 `MessageType` |
|---|---|---|
| `DEVICE_REGISTER` | `"device_register"` | `DEVICE_REGISTER` |
| `DEVICE_HEARTBEAT` | `"heartbeat"` | `DEVICE_HEARTBEAT` |
| `DEVICE_STATUS` | `"device_status"` | `DEVICE_STATUS` |
| `DEVICE_DISCONNECT` | `"device_unregister"` | `DEVICE_UNREGISTER` |
| `TASK_SUBMIT` | `"task_submit"` | `TASK_SUBMIT` |
| `TASK_RESULT` | `"task_result"` | `TASK_RESULT` |
| `TASK_CANCEL` | `"task_cancel"` | `TASK_CANCEL` |
| `COMMAND` | `"command"` | `COMMAND` |
| `COMMAND_RESULT` | `"command_result"` | `COMMAND_RESULT` |
| `GOAL_EXECUTION` | `"goal_execution"` | `GOAL_EXECUTION` |
| `PARALLEL_SUBTASK` | `"parallel_subtask"` | `PARALLEL_SUBTASK` |
| `PARALLEL_RESULT` | `"parallel_result"` | `PARALLEL_RESULT` |
| `CAPABILITY_REPORT` | `"capability_report"` | `CAPABILITY_REPORT` |
| `WAKE_EVENT` | `"wake_event"` | `WAKE_EVENT` |

## Usage

### Primary entry point

```python
from galaxy_gateway.protocol.normalized_ingress_event import (
    NormalizedIngressEvent,
    IngressEventKind,
    to_normalized_ingress_event,
)

# From any input (string, dict, AIPMessage)
event = to_normalized_ingress_event(raw_input)

# Handlers branch only on canonical kind
if event.kind == IngressEventKind.DEVICE_REGISTER:
    # handle registration
elif event.kind == IngressEventKind.TASK_SUBMIT:
    # handle task submission
```

### From an already-parsed AIPMessage

```python
from galaxy_gateway.protocol.normalized_ingress_event import from_aip_message
from galaxy_gateway.protocol.compat import parse_message_compat

aip_msg = parse_message_compat(raw_text)
event = from_aip_message(aip_msg)
```

### From a normalized dict

```python
from galaxy_gateway.protocol.normalized_ingress_event import from_normalized_dict
from galaxy_gateway.protocol.compat import normalise_to_v3_dict

v3_dict = normalise_to_v3_dict(raw_input)
event = from_normalized_dict(v3_dict)
```

## Package exports

```python
from galaxy_gateway.protocol import (
    NormalizedIngressEvent,
    IngressEventKind,
    to_normalized_ingress_event,
    ingress_event_from_aip_message,
    ingress_event_from_dict,
)
```

## AIP v1/v2 Legacy Alias Resolution (compat.py)

The following aliases are resolved **only in `compat.py`**, before reaching
`NormalizedIngressEvent`:

| Legacy alias (v1) | Canonical wire string |
|---|---|
| `register`, `agent_register`, `registration` | `device_register` |
| `heartbeat`, `agent_heartbeat` | `heartbeat` |
| `task_execute` | `task_submit` |
| `command_result` | `task_result` (via TASK_RESULT) |
| `status_update`, `update_status` | `device_status` |
| `goal`, `goal_execute` | `goal_execution` |
| `parallel_task` | `parallel_subtask` |
| `parallel_result` | `parallel_result` |

## Related

- [`CanonicalDeviceIdentity`](./CANONICAL_DEVICE_IDENTITY_CONTRACT.md) — device identity
- [`RuntimePresenceRecord`](./RUNTIME_PRESENCE_RECORD_CONTRACT.md) — connection state
- `galaxy_gateway/protocol/compat.py` — legacy alias resolution
- `galaxy_gateway/protocol/aip_v3.py` — AIP v3 protocol schema
