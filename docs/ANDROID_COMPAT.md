# Android Compatibility Layer

This document describes the backward-compatible endpoints and protocol
detection logic added to keep legacy Android clients connected while the
server evolves.

---

## Supported WebSocket Paths

All paths below are handled by the **same** connection handler
(`WebSocketManager.handle_connection`) used for the primary gateway.

| Path | Introduced | Notes |
|------|-----------|-------|
| `/ws/android/{device_id}` | v3.0+ | **Primary path** — preferred for all Android clients |
| `/ws/{device_id}` | v3.0 | Generic device path |
| `/ws` | v3.0 | Auto-assigns `device_id` if not provided via query param |
| `/ws/device/{device_id}` | compat | Compat alias for `/ws/android/{device_id}` |
| `/ws/ufo3/{device_id}` | compat | Legacy UFO3 client path |
| `/ws/android` | compat | Broadcast Android path; `device_id` optional (query param) |

> **Note**: WS, REST (`/api/v1/…`), and WebRTC proxy (`/ws/webrtc/{id}`,
> `/api/v1/webrtc/endpoint`) all run in the **same process on port 8765**.
> No separate port is required.

### Connection example

```
ws://<host>:8765/ws/android/<device_id>
ws://<host>:8765/ws/device/<device_id>
ws://<host>:8765/ws/ufo3/<device_id>
ws://<host>:8765/ws/android?device_id=<device_id>
```

---

## REST Compatibility Endpoints

These endpoints are provided in addition to the canonical `/api/v1/devices/*`
routes.  They accept the same request bodies as the v1 routes and return
responses in a format compatible with legacy Android clients.

### POST `/api/devices/register`

Registers a new device.  Maps to `/api/v1/devices/register`.

**Request body**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `device_id` | string | ✔ | — | Unique device identifier |
| `device_type` | string | | `"android"` | Platform type |
| `device_name` | string | | `""` | Human-readable name |
| `capabilities` | list | | `[]` | Device capabilities |
| `os_version` | string | | `""` | OS version string |
| `app_version` | string | | `""` | Client app version |

**Response** (core API server)

```json
{
  "success": true,
  "device_id": "<device_id>",
  "message": "设备注册成功",
  "server_version": "2.0.0",
  "available_nodes": []
}
```

> **Note**: The gateway server (`galaxy_gateway/app.py`) returns `"server_version": "3.0.0"` from its own `/api/devices/register` shim.  The core API server returns `"2.0.0"` to stay consistent with `/api/v1/devices/register`.

---

### GET `/api/devices/list`

Returns all registered devices.  Maps to `GET /api/v1/devices`.

**Response**

```json
{
  "devices": [
    {
      "device_id": "...",
      "device_type": "android",
      "online": true
    }
  ],
  "total": 1
}
```

---

### POST `/api/devices/heartbeat`

Updates a device's last-seen timestamp and optional status detail.
Maps to `/api/v1/devices/status`.

**Request body**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `device_id` | string | ✔ | — | Target device |
| `status` | object | | `{}` | Arbitrary status payload |

**Response**

```json
{
  "success": true,
  "device_id": "<device_id>"
}
```

---

### POST `/api/devices/unregister`

Marks the device as offline.  Safe no-op if the device is unknown.

**Request body**

| Field | Type | Required |
|-------|------|----------|
| `device_id` | string | ✔ |

**Response**

```json
{
  "success": true,
  "device_id": "<device_id>"
}
```

---

## Protocol Version Detection

The server supports **AIP/1.0**, **AIP/2.0** and **AIP/3.0** messages.
Detection happens in `galaxy_gateway/protocol/compat.py` and is applied
automatically to every incoming WebSocket message.

### Detection rules

| Condition | Detected version |
|-----------|-----------------|
| No `version` field, or `version` starts with `"1"` | AIP/1.0 |
| `version` starts with `"2"` | AIP/2.0 |
| `version` starts with `"3"` | AIP/3.0 |

### AIP/1.0 type aliases

Legacy `type` strings are normalised to their canonical AIP v3 equivalents
before the message is dispatched:

| Legacy `type` value | Normalised to |
|---------------------|--------------|
| `register` | `device_register` |
| `agent_register` | `device_register` |
| `device_register` | `device_register` |
| `registration` | `device_register` |
| `heartbeat` | `heartbeat` |
| `agent_heartbeat` | `heartbeat` |
| `device_heartbeat` | `heartbeat` |
| `command_result` | `task_result` |

### AIP/2.0

AIP v2 messages use the same field names as v3.  Only the `version` field is
bumped to `"3.0"` before validation.

### Logging

Each message's detected protocol version is logged at **INFO** level (v1/v2)
or **DEBUG** level (v3):

```
INFO  galaxy_gateway.protocol.compat - Protocol version detected: AIP/1.0 — normalising type='register' to v3
INFO  galaxy_gateway.protocol.compat - Protocol version detected: AIP/2.0 — normalising to v3
DEBUG galaxy_gateway.protocol.compat - Protocol version detected: AIP/3.0
```

---

## Implementation files

| File | Purpose |
|------|---------|
| `galaxy_gateway/app.py` | Legacy WebSocket paths + HTTP shim endpoints |
| `galaxy_gateway/protocol/compat.py` | Protocol version detection & normalisation |
| `galaxy_gateway/transport/websocket_server.py` | Uses `parse_message_compat` instead of `parse_message` |
| `core/routes/compat.py` | HTTP shim router for the core API server |
| `core/api_routes.py` | Includes `compat` router |
| `tests/test_android_compat.py` | Tests for all of the above |
