# WebRTC Gateway Proxy

This document describes the WebRTC signaling gateway integration added to the
Galaxy Gateway (server repo `DannyFish-11/galaxy-realization-v2`).

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
| `GATEWAY_URL` | `http://localhost:8000`  | HTTP base URL of this gateway service.          |

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
  "gateway_ws_url": "http://localhost:8000",
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
# ws://localhost:8000/ws/webrtc/phone_a
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

## Running Tests

```bash
pytest tests/test_webrtc_gateway.py -v
```

Tests use a local mock WebSocket server and do **not** require a real
`Node_95_WebRTC_Receiver` instance.

---

## Implementation Files

| File                                   | Role                                                     |
|----------------------------------------|----------------------------------------------------------|
| `galaxy_gateway/webrtc_proxy.py`       | Proxy helpers: health probe, endpoint info, WS relay     |
| `galaxy_gateway/app.py`                | REST + WS endpoint registrations                         |
| `galaxy_gateway/smart_transport_router.py` | `use_gateway` option in `TransportRequest`           |
| `tests/test_webrtc_gateway.py`         | Unit + integration tests (mock Node_95)                  |
