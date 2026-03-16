# AIP v3.0 JSON Schemas

This directory contains [JSON Schema (Draft 2020-12)](https://json-schema.org/draft/2020-12/schema) files that formally define the AIP v3.0 wire format for every message type exchanged between Galaxy server and connected devices.

## Files

| File | Message type | Direction |
|------|-------------|-----------|
| `aip_envelope.schema.json` | Base envelope shared by all messages | — |
| `device_register.schema.json` | `device_register` | Client → Server |
| `heartbeat.schema.json` | `heartbeat` | Client → Server |
| `capability_report.schema.json` | `capability_report` | Client → Server |
| `task_assign.schema.json` | `task_assign` | Server → Client |
| `command_result.schema.json` | `command_result` | Client → Server |

## v3 Requirements

All AIP v3 messages **must** include:

* `"version"` – string matching `^3\.` (e.g. `"3.0"`)
* `"type"` – canonical message-type string (see `MessageType` in `aip_v3.py`)
* `"device_id"` – non-empty device identifier

`capability_report` additionally **requires**:

* `"platform"` – device platform family (e.g. `"android"`, `"windows"`)
* `"supported_actions"` – non-empty array of action name strings

## Legacy / Compat Path

Legacy clients that send AIP/1.x or AIP/2.x messages are **automatically upgraded** to v3 by `galaxy_gateway/protocol/compat.py` *before* any handler sees the message.  The schemas defined here describe the **post-conversion** v3 format; they are not applied to raw incoming data.

```
Client (any version)
    │  raw JSON
    ▼
parse_message_compat()          ← compat.py: upgrade to v3, inject trace_id / route_mode
    │  AIPMessage (v3)
    ▼
handler / router                ← only v3 AIPMessage objects reach here
    │
    ▼
schemas/*.schema.json           ← describe the v3 objects handlers receive/send
```

## Validation

The test suite (`tests/test_v3_schemas.py`) validates that each schema file:

1. Is valid JSON and loads without error.
2. Accepts the sample v3 payloads embedded in the schema `"examples"` array.
3. Rejects clearly invalid payloads (missing required fields, wrong type).

Run with:

```bash
python -m pytest tests/test_v3_schemas.py -v
```
