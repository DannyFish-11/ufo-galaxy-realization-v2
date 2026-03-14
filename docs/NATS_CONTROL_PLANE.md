# Galaxy — Unified NATS-Centric Control Plane

## Overview

Galaxy uses **NATS JetStream** as its single control bus connecting all system
components: MasterBrain, Gateway, Python Nodes, Go Workers, and Device/WebSocket
adapters.

```
                       ┌────────────────────────────┐
                       │        MasterBrain          │
                       │  (Cloud Control Plane)      │
                       └────────────┬───────────────┘
                                    │  NATS JetStream
             ┌──────────────────────┼──────────────────────┐
             │                      │                      │
   ┌─────────▼──────────┐  ┌────────▼────────┐  ┌────────▼────────┐
   │  Go Worker Nodes   │  │ Gateway (Python) │  │  Python Nodes   │
   │  (code execution)  │  │ NATS↔WebSocket  │  │  Node_00, 04…   │
   └────────────────────┘  └────────┬────────┘  └─────────────────┘
                                    │ WebSocket / HTTP
                              ┌─────▼──────┐
                              │  Devices   │
                              │ (Android,  │
                              │  IoT, etc) │
                              └────────────┘
```

## Configuration

| Environment Variable | Description | Required |
|---|---|---|
| `GALAXY_NATS_URL` | NATS server URL (e.g. `nats://localhost:4222`) | Optional (no-op mode if absent) |
| `GALAXY_MASTER_BRAIN_ENABLED` | Set to `true` to enable MasterBrain orchestrator | Optional |
| `GALAXY_GW_ADAPTER_TIMEOUT` | Gateway task WebSocket timeout in seconds (default: 30) | Optional |
| `GALAXY_GW_ADAPTER_RETRIES` | Gateway task max retries before DLQ (default: 2) | Optional |
| `GALAXY_GW_ADAPTER_DLQ_SUBJECT` | Dead-letter subject (default: `galaxy.tasks.deadletter`) | Optional |
| `GALAXY_HEARTBEAT_INTERVAL` | Node heartbeat interval in seconds (default: 10) | Optional |
| `GALAXY_NATS_EXECUTOR_FALLBACK` | `true`/`false`: use local executor when NATS unavailable (default: `true`) | Optional |
| `GALAXY_NATS_EXECUTOR_TIMEOUT` | NATS executor task timeout in seconds (default: 30) | Optional |

> **No breaking changes**: All NATS features are opt-in via environment variables.
> The system falls back to existing WebSocket/HTTP paths when NATS is unavailable.

## NATS Subject Layout

| Subject | Direction | Description |
|---|---|---|
| `galaxy.tasks.dispatch.{worker_id}` | Brain → Worker | Task dispatch to a specific worker |
| `galaxy.tasks.dispatch.gateway` | Brain → Gateway | Task dispatch to the WebSocket gateway adapter |
| `galaxy.tasks.result.{task_id}` | Worker/Gateway → Brain | Task execution result |
| `galaxy.tasks.deadletter` | Gateway → DLQ | Tasks that exhausted all retries |
| `galaxy.workers.register` | Node → Brain | Worker/Node registration on startup |
| `galaxy.workers.heartbeat` | Node → Brain | Periodic heartbeat (every 10s) |
| `galaxy.events.{type}` | Any → Bus | System-wide observability events |
| `galaxy.mcp.calls` | Any → MCP | MCP tool call requests |
| `galaxy.mcp.results` | MCP → Any | MCP tool call results |

## Quick Start

### 1. Start a NATS server

```bash
# Docker (simplest)
docker run -d --name nats -p 4222:4222 nats:latest -js

# Or use the official NATS installer
# https://docs.nats.io/running-a-nats-service/introduction/installation
```

### 2. Configure Galaxy

```bash
export GALAXY_NATS_URL=nats://localhost:4222
export GALAXY_MASTER_BRAIN_ENABLED=true
```

### 3. Start Galaxy

```bash
python main.py
# or
python unified_launcher.py
```

On startup, Galaxy will:
- Connect to NATS (Phase A)
- Start MasterBrain subscriptions (Phase A)
- Initialize the Gateway NATS↔WebSocket adapter (Phase B)
- Register all active Python nodes via `galaxy.workers.register` (Phase C)
- Begin periodic heartbeats every 10 seconds (Phase C)
- Set up the NATS executor in CommandRouter for device command dispatch (Phase D)

## Architecture Phases

### Phase A — Startup & Config Hardening

`unified_launcher.py` now connects the NATS bus and starts MasterBrain
subscriptions during the startup sequence.  If `GALAXY_NATS_URL` is not set,
the system runs in **no-op mode** (all NATS calls are silent no-ops) so that
existing deployments without NATS continue to work unchanged.

### Phase B — Gateway Worker Adapter

`galaxy_gateway/gateway_nats_adapter.py` bridges NATS task dispatches to the
WebSocket device layer:

1. Subscribes to `galaxy.tasks.dispatch.gateway` (durable consumer "gateway")
2. For each `TaskDispatch`, finds the target device in `DeviceRouter` or
   `WebSocketManager` and forwards the task payload
3. Awaits the device result and publishes it to `galaxy.tasks.result.{task_id}`
4. On timeout/failure: retries up to `GALAXY_GW_ADAPTER_RETRIES` times, then
   publishes to the dead-letter subject

### Phase C — Node/Device Heartbeats

`core/nats_heartbeat.py` provides a `NodeHeartbeatSender` and
`start_node_heartbeat()` helper used by Python nodes to:

- Send a `WorkerRegistration` message on startup via `galaxy.workers.register`
- Emit `WorkerHeartbeat` every `GALAXY_HEARTBEAT_INTERVAL` seconds

Nodes that currently send heartbeats: `Node_00_StateMachine`, `Node_04_Router`.

### Phase D — CommandRouter NATS Executor

`core/command_router.py` now includes a `NATSExecutor` class that:

1. Wraps commands as `TaskDispatch` (type: `device_cmd`) and publishes via
   `NATSBus.publish_task_dispatch`
2. Subscribes to `galaxy.tasks.result.*` to resolve pending futures
3. Falls back to the existing local executor when NATS is unavailable
   (configurable via `GALAXY_NATS_EXECUTOR_FALLBACK`)

### Phase E — Observability & UI Surfacing

New endpoints available in both the Galaxy core API and the gateway service:

| Endpoint | Description |
|---|---|
| `GET /health/nats` | NATS bus connection status, stats, and MasterBrain state |
| `GET /api/v1/observability/nats` | Full NATS topology: bus stats, worker topology, executor stats |
| `GET /api/v1/observability/bus-events` | Recent NATS bus events from the EventBus |

## Observability

### Health Check

```bash
# Gateway NATS health
curl http://localhost:8765/health/nats

# Core API NATS health
curl http://localhost:8000/health/nats
```

Example response:
```json
{
  "status": "connected",
  "noop_mode": false,
  "bus": {
    "connected": true,
    "published": 42,
    "received": 17,
    "errors": 0,
    "reconnects": 0,
    "subscriptions": 3
  },
  "master_brain": {
    "started": true,
    "worker_count": 2,
    "task_log_size": 5
  }
}
```

### Full Topology

```bash
curl http://localhost:8000/api/v1/observability/nats
```

## Testing

Run the NATS control plane smoke tests:

```bash
python -m pytest tests/test_nats_control_plane.py -v
```

These tests mock the NATS client and verify:
- Gateway adapter dispatch/result roundtrip
- Node heartbeat registration messages
- NATSExecutor task dispatch and result resolution
- Health endpoint response structure
