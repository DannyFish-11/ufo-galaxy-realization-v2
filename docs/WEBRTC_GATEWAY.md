# WebRTC Gateway Proxy

This document describes the WebRTC signaling gateway integration added to the
Galaxy Gateway (server repo `DannyFish-11/galaxy-realization-v2`).

## Protocol Requirements (AIP v3 — Round 2 enforcement)

> **All WebSocket and HTTP connections to this gateway require AIP v3.0+.**
>
> * Every message **must** include `"version": "3.0"` (or higher).  Connections
>   or messages carrying an older version (or omitting the field) are rejected
>   immediately: WebSocket connections receive a close frame with code `4000`;
>   HTTP requests receive a `400 Bad Request`.
> * Every message **must** include `trace_id` (a UUID string) and `route_mode`
>   (`"cross_device"` or `"local"`).  When either field is absent, the gateway
>   injects a generated default and records a structured log entry
>   (`event: aip_metadata_injected`).  Clients should send both fields
>   explicitly for end-to-end traceability.
>
> These requirements apply to all WebSocket paths (`/ws/android/*`,
> `/ws/device/*`, `/ws/webrtc/*`) and to all HTTP ingress endpoints.

## Overview

Android clients need a stable, single gateway address to perform WebRTC
signaling. Previously they had to connect directly to `Node_95_WebRTC_Receiver`
(port 8095). The gateway proxy adds an adapter layer so that:

* Clients connect to the **main gateway** (`/ws/webrtc/{device_id}`).
* The gateway transparently relays signaling messages to Node_95 and forwards
  responses back.
* Clients can discover the relevant URLs from a single REST endpoint
  (`/api/v1/webrtc/endpoint`).

```
Android Client
    │
    │  ws://GATEWAY_HOST/ws/webrtc/{device_id}
    ▼
Galaxy Gateway  ──────────────────────────►  Node_95_WebRTC_Receiver
(galaxy_gateway/app.py)                           ws://NODE_95_HOST/signaling/{device_id}
```

## Environment Variables

| Variable      | Default                  | Description                                     |
|---------------|--------------------------|-------------------------------------------------|
| `NODE_95_URL` | `http://localhost:8095`  | HTTP base URL of `Node_95_WebRTC_Receiver`.     |
| `GATEWAY_URL` | `http://localhost:8765`  | HTTP base URL of this gateway service (unified port — WS + REST + WebRTC on same port). |

Both variables are read at call-time, so they can be changed without
restarting the process (useful for testing).

## Endpoints

### `GET /api/v1/webrtc/endpoint`

Returns endpoint metadata that Android clients can use to configure their
WebRTC signaling connection.

**Response — 200 OK**

```json
{
  "node95_url": "http://localhost:8095",
  "ws_signaling_path": "/signaling/{device_id}",
  "gateway_ws_url": "http://localhost:8765",
  "gateway_ws_path": "/ws/webrtc/{device_id}"
}
```

Replace `{device_id}` with the actual device identifier.

**Response — 503 Service Unavailable**

Returned when `Node_95_WebRTC_Receiver` is not reachable (health probe
failed).

```json
{
  "detail": "Node_95 WebRTC Receiver is not reachable"
}
```

---

### `WS /ws/webrtc/{device_id}`

WebSocket passthrough endpoint. The gateway accepts the connection from the
Android client and opens a connection to
`ws://NODE_95_HOST/signaling/{device_id}`, then relays messages in both
directions until either side disconnects.

**Path parameters**

| Parameter   | Description               |
|-------------|---------------------------|
| `device_id` | Unique ID for the device. |

**Close codes**

| Code | Meaning                                               |
|------|-------------------------------------------------------|
| 1000 | Normal closure (either side initiated clean shutdown) |
| 1011 | Node_95 unreachable (503-equivalent)                  |

**Signaling message format** (passed through unchanged)

```json
{
  "type": "offer | answer | ice_candidate",
  "sdp": "...",
  "candidate": "..."
}
```

---

## SmartTransportRouter integration

`SmartTransportRouter` (in `galaxy_gateway/smart_transport_router.py`)
supports an optional `use_gateway` flag in `TransportRequest`.

When `use_gateway=True` **and** the selected transport method is `webrtc`,
the router returns the gateway WebSocket signaling URL
(`ws://GATEWAY_HOST/ws/webrtc/{device_id}`) instead of connecting the client
directly to Node_95.

```python
from galaxy_gateway.smart_transport_router import SmartTransportRouter, TransportRequest

router = SmartTransportRouter()

resp = await router.route(TransportRequest(
    device_id="phone_a",
    task_type="dynamic",
    realtime=True,
    preferred_method="webrtc",
    use_gateway=True,   # ← return gateway WS URL
))

print(resp.endpoint)
# ws://localhost:8765/ws/webrtc/phone_a
```

---

## Message Flow

```
Android Client
    │
    │  1. GET /api/v1/webrtc/endpoint
    │     ← { gateway_ws_path, node95_url, … }
    │
    │  2. WS connect to ws://GATEWAY/ws/webrtc/{device_id}
    ▼
Galaxy Gateway
    │
    │  3. Gateway opens WS to ws://NODE_95/signaling/{device_id}
    ▼
Node_95_WebRTC_Receiver
    │
    │  4. Signaling exchange (Offer/Answer/ICE) relayed transparently
    │
    │  5. WebRTC P2P stream established between client and Node_95
    ▼
Android Client  ◄───── WebRTC Media Stream ──────  Node_95
```

---

## Client Configuration Discovery

### `GET /api/v1/config`

Returns a unified configuration payload that Android (and other) clients
should fetch **at startup** to bootstrap connection settings.  Using this
endpoint avoids hard-coded addresses in the client.

This endpoint is **always public** (no authentication required) so that
clients can obtain configuration before they have a token.

**Response — 200 OK**

```json
{
  "ws_base": "ws://192.168.1.10:8765",
  "rest_base": "http://192.168.1.10:8765",
  "ws_paths": [
    "/ws/android/{id}",
    "/ws/device/{id}",
    "/ws/android"
  ],
  "webrtc_gateway_ws_path": "/ws/webrtc/{id}",
  "stun_servers": [
    "stun:stun.l.google.com:19302"
  ],
  "turn_servers": [],
  "transport_priority": ["tailscale", "intranet", "internet"],
  "feature_flags": {
    "tailscale_enabled": false,
    "use_gateway_for_webrtc": true
  }
}
```

#### Field descriptions

| Field | Type | Description |
|-------|------|-------------|
| `ws_base` | string | WebSocket base URL (`ws://` or `wss://`).  Prepend this to any `ws_paths` entry to build the full WS URL. |
| `rest_base` | string | HTTP/REST base URL.  Use for REST API calls. |
| `ws_paths` | array of strings | Ordered WebSocket paths to attempt, most preferred first.  Replace `{id}` with the device identifier. |
| `webrtc_gateway_ws_path` | string | WS path for WebRTC signaling through the gateway.  Replace `{id}` with the device identifier. |
| `stun_servers` | array of strings | STUN server URLs for `RTCPeerConnection.iceServers`.  Never empty; falls back to `stun:stun.l.google.com:19302`. |
| `turn_servers` | array of objects | TURN server objects (`{"urls": "...", "username": "...", "credential": "..."}`).  **May be empty** — clients must not crash when the list is empty. |
| `transport_priority` | array of strings | Ordered transport preference: probe each in order and use the first reachable one. |
| `feature_flags` | object | Boolean feature toggles.  `tailscale_enabled` signals whether Tailscale networking is active on the server; `use_gateway_for_webrtc` indicates whether clients should route WebRTC signaling through the gateway path instead of contacting `Node_95` directly. |

#### Placeholder substitution

Paths that contain `{id}` (e.g. `/ws/android/{id}`) use the literal token
`{id}` as a placeholder.  Replace it with the actual device identifier
before connecting:

```kotlin
// Android (Kotlin) example
val wsUrl = "${config.wsBase}${config.wsPaths[0].replace("{id}", deviceId)}"
```

#### How Android clients should consume this response

1. **Fetch** `GET /api/v1/config` on startup (before any WebSocket connection).
2. **Override** local `ServerConfig` fields with the returned values.
3. **Probe transports** in the order given by `transport_priority`
   (Tailscale → intranet → internet) and connect via the fastest reachable
   `ws_base`.
4. **Try `ws_paths` in order** until a connection succeeds.
5. **Populate `RTCPeerConnection.iceServers`** with `stun_servers` (always)
   and `turn_servers` (when non-empty).
6. If `feature_flags.use_gateway_for_webrtc` is `true`, use
   `webrtc_gateway_ws_path` for signaling; otherwise connect to `Node_95`
   directly using the URL from `/api/v1/webrtc/endpoint`.

#### Environment variables (config endpoint)

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_URL` | `http://localhost:8765` | HTTP base URL — used to derive `rest_base` and `ws_base`. |
| `GALAXY_STUN_URLS` | `stun:stun.l.google.com:19302` | Comma-separated STUN URLs. |
| `GALAXY_TURN_URLS` | _(not set)_ | Comma-separated TURN URLs.  Omit to return an empty `turn_servers`. |
| `GALAXY_TURN_USERNAME` | _(not set)_ | TURN credential username. |
| `GALAXY_TURN_CREDENTIAL` | _(not set)_ | TURN credential password. |
| `GALAXY_TAILSCALE_ENABLED` | `false` | Set to `1`, `true`, or `yes` to set `feature_flags.tailscale_enabled = true`. |
| `GALAXY_USE_GATEWAY_FOR_WEBRTC` | `true` | Set to `0`, `false`, or `no` to disable gateway WebRTC routing. |
| `GALAXY_TRANSPORT_PRIORITY` | `tailscale,intranet,internet` | Comma-separated transport priority list. |

---

## Capability Schema and exec_mode (Round 3)

### Overview

Since Round 3 every Android (or other) client can advertise a richer, per-action
capability schema via the **`capability_report`** WebSocket message.  The server
stores these schemas in the in-memory `GatewayCapabilityRegistry`
(`galaxy_gateway/capability_registry.py`) and uses the `exec_mode` field to
select the best target device when dispatching a task.

### `capability_report` message format

```json
{
  "type": "capability_report",
  "version": "3.0",
  "device_id": "<device_id>",
  "platform": "android",
  "supported_actions": ["tap", "swipe", "screenshot"],
  "capability_schemas": [
    {
      "action": "tap",
      "params": {
        "x": { "type": "integer" },
        "y": { "type": "integer" }
      },
      "returns": { "success": { "type": "boolean" } },
      "version": "1.2",
      "exec_mode": "local",
      "tags": ["ui", "touch"]
    },
    {
      "action": "screenshot",
      "params": {},
      "returns": { "image_base64": { "type": "string" } },
      "version": "1.0",
      "exec_mode": "both"
    }
  ]
}
```

`capability_schemas` is **optional**.  Older clients that only send
`supported_actions` are handled with backward-compatible defaults
(`exec_mode = "both"`).

### Schema fields

| Field        | Type                    | Required | Description |
|--------------|-------------------------|----------|-------------|
| `action`     | string                  | ✓        | Action identifier (e.g. `"tap"`, `"screenshot"`). |
| `params`     | object (JSON Schema)    | ✗        | Input parameter schema.  Omit if no parameters. |
| `returns`    | object (JSON Schema)    | ✗        | Return value schema. |
| `version`    | string                  | ✗        | Schema version string (e.g. `"1.2"`).  Defaults to `"1.0"`. |
| `exec_mode`  | `"local"` \| `"remote"` \| `"both"` | ✗ | Execution preference (see below).  Defaults to `"both"` if absent. |
| `tags`       | array of strings        | ✗        | Free-form labels used for additional filtering (e.g. `["ui", "capture"]`). |

### exec_mode semantics

| Value    | Meaning |
|----------|---------|
| `local`  | The action **should** run on the device itself.  The server router will not assign this capability to a remote (server-side) executor.  Typical for low-latency UI automation actions. |
| `remote` | The action **should** run server-side / remotely.  The router will not assign it to the originating device. |
| `both`   | Either local or remote execution is acceptable.  The router may use any available executor. |
| _(absent)_ | Treated as `"both"` for backward compatibility. |

### Routing decision

`DeviceRouter._select_devices()` queries the `GatewayCapabilityRegistry` to
find devices that match both the requested **action** and the caller's
**exec_mode** preference:

1. Devices that have the capability registered **and** whose `exec_mode` is
   compatible with the requested mode are preferred.
2. If no devices have matching schemas, devices with **no capability_report at
   all** (legacy clients) are used as a fallback.
3. If neither group has online devices, the router returns an empty list and
   the caller receives a "no available device" error.

### Cleanup on disconnect

When a device disconnects, `DeviceRouter.unregister_device()` calls
`GatewayCapabilityRegistry.purge(device_id)` to remove all stale schemas.

### Registry API (`galaxy_gateway/capability_registry.py`)

```python
from galaxy_gateway.capability_registry import (
    GatewayCapabilityRegistry,
    ExecMode,
    get_gateway_capability_registry,
)

reg = get_gateway_capability_registry()   # global singleton

# Upsert a capability (e.g. from capability_report)
reg.upsert("device-abc", "tap", {
    "exec_mode": "local",
    "version": "1.2",
    "params": {"x": {"type": "integer"}, "y": {"type": "integer"}},
    "tags": ["ui"],
})

# Query: find devices that support "tap" in local mode
schemas = reg.query(action="tap", exec_mode=ExecMode.LOCAL)

# Purge on disconnect
reg.purge("device-abc")

# Observability
print(reg.stats())
# {'registrations': 1, 'hits': 1, 'misses': 0, 'devices': 0, 'total_capabilities': 0}
```

### Metrics / Logging

The registry emits structured log entries and maintains in-memory counters:

| Metric                | Description |
|-----------------------|-------------|
| `registrations`       | Total number of `upsert()` calls (cumulative). |
| `hits`                | Number of `query()` calls that returned ≥ 1 result. |
| `misses`              | Number of `query()` calls that returned 0 results. |
| `devices`             | Current number of devices with registered capabilities. |
| `total_capabilities`  | Current total number of capability entries across all devices. |

Log events:
- `capability_registry: upsert device=<id> action=<action> exec_mode=<mode>` (DEBUG)
- `capability_registry: purged N capabilities for device <id>` (INFO)
- `capability_report: upserted N capabilities for device <id> to GatewayCapabilityRegistry` (INFO)
- `unregister_device: purged N capabilities for device <id>` (DEBUG)

### Running the new tests

```bash
pytest tests/test_capability_registry.py tests/test_routing_with_exec_mode.py -v
```

---

## Running Tests

```bash
pytest tests/test_webrtc_gateway.py tests/test_config_endpoint.py -v
```

Tests use a local mock WebSocket server and do **not** require a real
`Node_95_WebRTC_Receiver` instance.

---

## Implementation Files

| File                                   | Role                                                     |
|----------------------------------------|----------------------------------------------------------|
| `galaxy_gateway/webrtc_proxy.py`       | Proxy helpers: health probe, endpoint info, WS relay     |
| `galaxy_gateway/api/config.py`         | `GET /api/v1/config` route and config builder helpers    |
| `galaxy_gateway/app.py`                | REST + WS endpoint registrations                         |
| `galaxy_gateway/smart_transport_router.py` | `use_gateway` option in `TransportRequest`           |
| `tests/test_webrtc_gateway.py`         | Unit + integration tests (mock Node_95)                  |
| `tests/test_config_endpoint.py`        | Unit tests for `GET /api/v1/config`                      |
