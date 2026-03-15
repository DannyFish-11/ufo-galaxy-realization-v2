# Runtime Bridge — Agent Handoff Contract (Round 5)

This document describes the **Agent Bridge** introduced in Round 5.  The bridge
mediates between the Galaxy Gateway / `DeviceRouter` and a downstream Agent
Runtime (e.g. OpenClawd) for cross-device task flows.

---

## Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Client / WebSocket / REST                                               │
└──────────────────────────────────────┬───────────────────────────────────┘
                                       │
                    ┌──────────────────▼───────────────────┐
                    │  galaxy_gateway/device_router.py      │
                    │  DeviceRouter.route_task()            │
                    └──────────────────┬───────────────────┘
                                       │
                    ┌──────────────────▼───────────────────┐
                    │  galaxy_gateway/cross_device_switch   │
                    │  is_cross_device_enabled() guard      │
                    └──────────────────┬───────────────────┘
                          OFF ◄────────┘────────► ON
                           │                      │
               structured disabled          ┌─────▼──────────────────────┐
               response returned            │  galaxy_gateway/agent_bridge│
               (no runtime call)            │  AgentBridge.handoff()      │
                                            └─────┬──────────────────────┘
                                        ┌─────────┤
                                        │         │
                              runtime ──┘   fallback (timeout / unreachable)
                              response       │
                                        local coordinator / executor
```

When the **cross-device switch** is **ON** and a task requires cross-device
coordination, `DeviceRouter.route_task()` delegates to `AgentBridge.handoff()`
before falling back to the local cross-device coordinator.

When the switch is **OFF**, the standard Round 4 disabled response is returned
immediately — the bridge is never invoked.

---

## Handoff Contract

Every bridge handoff carries a `HandoffContract` with the following fields:

| Field              | Type   | Description                                                   |
|--------------------|--------|---------------------------------------------------------------|
| `trace_id`         | `str`  | Unique per request; used for deduplication, logs, and metrics |
| `task`             | `dict` | Original task payload (command + analysis + context)          |
| `capability`       | `str`  | Primary capability required (from `task_type` analysis)       |
| `exec_mode`        | `str`  | `"local"` \| `"remote"` \| `"both"` (AIP v3 field)           |
| `route_mode`       | `str`  | AIP v3 route mode (`"direct"`, `"broadcast"`, …)             |
| `session`          | `dict` | Session / context dict forwarded as-is to the runtime         |
| `callback_channel` | `str`  | Preferred response channel: `"ws"` \| `"webrtc"` \| `"nats"` |

The contract is serialised to JSON and `POST`-ed to the runtime's `/handoff`
endpoint.

---

## Fallback Behavior

The bridge follows a layered fallback policy:

| Condition                              | Action                                           |
|----------------------------------------|--------------------------------------------------|
| Cross-device switch OFF                | Return `cross_device_disabled` error immediately |
| Bridge disabled (`GALAXY_RUNTIME_ENABLED=0`) | Run `local_fallback` coroutine              |
| Runtime timeout                        | Run `local_fallback` coroutine                   |
| Runtime unreachable (`OSError`)        | Run `local_fallback` coroutine                   |
| Runtime returns HTTP ≥ 400             | Run `local_fallback` coroutine                   |
| No `local_fallback` supplied           | Return generic `agent_runtime_unavailable` error |

All fallback paths emit a structured `INFO` log entry including `trace_id` and
the failure reason, and increment the `fallback_count` metric.

---

## Idempotency (Deduplication)

`AgentBridge` maintains an in-process LRU cache of recent `trace_id` →
result mappings (max 1024 entries).

A second `handoff()` call with the same `trace_id` returns the cached result
**immediately** without a second runtime call.  The `dedup_hit_count` metric
is incremented on each cache hit.

This makes the bridge safe to call from retry loops or at-least-once delivery
systems.

---

## Configuration

All settings are read from **environment variables at call-time** — no restart
required to toggle them.

| Variable                    | Default                    | Description                                             |
|-----------------------------|----------------------------|---------------------------------------------------------|
| `GALAXY_RUNTIME_URL`        | `http://localhost:9000`    | HTTP(S) base URL of the agent runtime                   |
| `GALAXY_RUNTIME_TIMEOUT`    | `10`                       | Seconds before timeout triggers fallback                |
| `GALAXY_RUNTIME_ENABLED`    | `1` (enabled)              | Set to `0`, `false`, or `no` to disable the bridge      |
| `GALAXY_CROSS_DEVICE_ENABLED` | `1` (enabled)            | Round 4 switch; when `0` the bridge is never invoked    |

---

## Metrics / Logging

`AgentBridge.get_metrics()` returns a snapshot dict:

```json
{
  "handoff_attempts": 42,
  "handoff_success":  40,
  "handoff_failure":   2,
  "fallback_count":    2,
  "dedup_hit_count":   5,
  "avg_latency_ms": 37.4
}
```

Every bridge event emits a structured log line at the appropriate level:

| Event                       | Level   | Fields                                   |
|-----------------------------|---------|------------------------------------------|
| `agent_bridge_handoff_ok`   | `INFO`  | `trace_id`, `latency_ms`                 |
| `agent_bridge_handoff_failed` | `WARNING` | `trace_id`, `error`, `latency_ms`    |
| `agent_bridge_fallback`     | `INFO`  | `trace_id`, `reason`                     |
| `agent_bridge_dedup_hit`    | `INFO`  | `trace_id`                               |
| `agent_bridge_disabled`     | `DEBUG` | `trace_id`                               |

---

## Implementation Files

| File                                  | Role                                                               |
|---------------------------------------|--------------------------------------------------------------------|
| `galaxy_gateway/agent_bridge.py`      | **Round 5** — `AgentBridge`, `HandoffContract`, `AgentBridgeMetrics`, `AgentBridgeConfig` |
| `galaxy_gateway/device_router.py`     | Extended — bridge hook in `route_task()` cross-device path         |
| `galaxy_gateway/cross_device_switch.py` | Round 4 — feature-flag guard; imported by bridge                 |
| `tests/test_agent_bridge.py`          | Unit + integration tests (34 cases)                                |

---

## Running the Round 5 Tests

```bash
pytest tests/test_agent_bridge.py -v
```

To run the full cross-device test suite (Rounds 4 + 5):

```bash
pytest tests/test_cross_device_switch.py tests/test_agent_bridge.py -v
```

---

## Backward Compatibility

* **Cross-device switch OFF**: behaviour is identical to Round 4 — the bridge
  returns the same `cross_device_disabled` dict and emits the same `WARNING`
  log.  No new error codes are introduced.
* **Bridge disabled** (`GALAXY_RUNTIME_ENABLED=0`): tasks stay local; the
  bridge does not appear in any log or metric path.
* **No runtime configured / unreachable**: the bridge falls back to the
  existing `CrossDeviceCoordinator` (same behaviour as pre-Round 5).
* All prior AIP v3 metadata, capability registry, and `exec_mode` routing
  semantics from Rounds 1–4 are preserved.
