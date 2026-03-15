# Observability — Galaxy Gateway (Round 7)

End-to-end trace/span coverage, structured JSON logging, Prometheus-compatible
metrics, and configurable sampling for the cross-device pipeline.

```
Android Client
    │ trace_id / span_id in every WS message
    ▼
Galaxy Gateway (webrtc_proxy / device_router)
    │ emits: signaling_start, dispatcher_selection, bridge_handoff_start
    ▼
Agent Bridge (agent_bridge)
    │ emits: bridge_handoff_ok / bridge_handoff_failed / bridge_fallback
    ▼
Agent Runtime (POST /handoff)
    │ response carries trace_id back
    ▼
Android Client (response with trace_id / span_id)
```

---

## 1  Trace Fields

Every JSON log entry and every response message from the gateway includes the
following fields when a trace context is available:

| Field        | Type   | Description                                                        |
|--------------|--------|--------------------------------------------------------------------|
| `trace_id`   | string | UUID4. Stable across the **entire** request lifetime (ingress → egress). Generated at the gateway if the client does not send one. |
| `span_id`    | string | UUID4. Generated **fresh at every hop** (gateway, bridge, runtime). Changes at each processing stage. |
| `route_mode` | string | AIP v3 route mode — `"cross_device"` or `"local"`.               |
| `exec_mode`  | string | AIP v3 exec mode — `"local"`, `"remote"`, or `"both"`.           |
| `capability` | string | Primary device capability / task type (e.g. `"ui_automation"`).  |
| `device_id`  | string | Target device identifier, when available.                         |
| `session`    | object | Session / user context forwarded as-is, when available.           |

### Trace-ID Injection

When a client message arrives **without** a `trace_id`, the gateway:
1. Generates a fresh UUID4 and uses it for the session/request.
2. Emits a structured log entry with `event: trace_id_injected`.
3. Injects the `trace_id` (and `span_id`) into all downstream messages.

Clients **should** send `trace_id` explicitly for end-to-end traceability.

---

## 2  Structured Log Schema

All logs are written as single-line JSON to the `Galaxy.Gateway` logger.
Every entry has the following mandatory fields:

```json
{
  "event":    "<event_name>",
  "ts":       1700000000.123,
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "span_id":  "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
}
```

Additional contextual fields are merged in from the call-site.

### Key Events

| Event                      | Level   | Emitted by          | Key Fields                                              |
|----------------------------|---------|---------------------|---------------------------------------------------------|
| `signaling_start`          | info    | webrtc_proxy        | `device_id`, `node95_url`, `timeout_s`, `route_mode`   |
| `signaling_tunnel_open`    | info    | webrtc_proxy        | `device_id`, `route_mode`                               |
| `signaling_session_end`    | info    | webrtc_proxy        | `device_id`, `latency_ms`, `route_mode`                 |
| `signaling_timeout`        | warning | webrtc_proxy        | `device_id`, `timeout_s`, `latency_ms`, `cause`, `route_mode` |
| `signaling_error`          | warning | webrtc_proxy        | `device_id`, `cause`, `latency_ms`, `route_mode`        |
| `turn_fallback`            | info    | webrtc_proxy        | `device_id`, `ice_server_count`, `route_mode`           |
| `cross_device_blocked`     | warning | webrtc_proxy / router | `device_id`, `reason`, `route_mode`                   |
| `trace_id_injected`        | info    | device_router       | `reason`, `route_mode`                                  |
| `dispatcher_selection`     | info    | device_router       | `command` (truncated), `route_mode`, `exec_mode`, `capability`, `device_id`, `requires_cross_device` |
| `bridge_handoff_start`     | info    | device_router       | `device_id`, `route_mode`, `exec_mode`, `capability`    |
| `bridge_handoff_ok`        | info    | agent_bridge        | `latency_ms`, `capability`, `exec_mode`, `route_mode`   |
| `bridge_handoff_failed`    | warning | agent_bridge        | `cause`, `latency_ms`, `capability`, `exec_mode`, `route_mode` |
| `bridge_fallback`          | warning | agent_bridge        | `reason`                                                |
| `routing_failed`           | warning/error | device_router | `reason` or `cause`, `route_mode`, `exec_mode`, `capability` |

### Error log format

Error entries include `cause` (the exception string) and `trace_id`:

```json
{
  "event":    "signaling_error",
  "ts":       1700000000.123,
  "trace_id": "550e8400-...",
  "span_id":  "6ba7b810-...",
  "device_id": "phone_01",
  "cause":    "ConnectionRefusedError: [Errno 111] Connection refused",
  "latency_ms": 12.4,
  "route_mode": "cross_device"
}
```

---

## 3  Metrics

### Endpoint

| Path                              | Format        | Description                               |
|-----------------------------------|---------------|-------------------------------------------|
| `GET /api/v1/gateway/metrics`     | Prometheus text | Gateway pipeline metrics (Prometheus).  |
| `GET /gateway/metrics`            | Prometheus text | Alias.                                  |
| `GET /api/v1/gateway/metrics/json`| JSON          | Same data as a JSON snapshot.             |

### Counter Metrics

| Metric Name                               | Description                                              |
|-------------------------------------------|----------------------------------------------------------|
| `galaxy_gateway_signaling_total`          | Total WebRTC signaling sessions started.                 |
| `galaxy_gateway_signaling_success_total`  | Sessions completed successfully.                         |
| `galaxy_gateway_signaling_failure_total`  | Sessions that ended with error or timeout.               |
| `galaxy_gateway_signaling_timeout_total`  | Sessions that timed out (subset of failure).             |
| `galaxy_gateway_turn_fallback_total`      | Times TURN relay was used as ICE fallback.               |
| `galaxy_gateway_candidate_retry_total`    | ICE candidate retry events.                              |
| `galaxy_gateway_bridge_handoff_total`     | Agent bridge handoff attempts.                           |
| `galaxy_gateway_bridge_handoff_success_total` | Successful handoffs to the runtime.               |
| `galaxy_gateway_bridge_handoff_failure_total` | Failed handoffs (unreachable / timeout).          |
| `galaxy_gateway_bridge_fallback_total`    | Times the bridge fell back to local execution.           |
| `galaxy_gateway_routing_total`            | Total task routing attempts (device_router).             |
| `galaxy_gateway_routing_success_total`    | Successful task routings.                                |
| `galaxy_gateway_routing_failure_total`    | Failed task routings.                                    |

### Histogram Metrics

| Metric Name                              | Unit | Description                                      |
|------------------------------------------|------|--------------------------------------------------|
| `galaxy_gateway_signaling_latency_ms`    | ms   | WebRTC signaling session latency.                |
| `galaxy_gateway_bridge_latency_ms`       | ms   | Agent bridge handoff latency.                    |
| `galaxy_gateway_routing_latency_ms`      | ms   | Full `route_task()` latency.                     |

All histograms use buckets: `10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 30000` ms + `+Inf`.

### Example Prometheus output

```
# HELP galaxy_gateway_signaling_total Total WebRTC signaling sessions started
# TYPE galaxy_gateway_signaling_total counter
galaxy_gateway_signaling_total 42
# HELP galaxy_gateway_signaling_success_total WebRTC signaling sessions completed successfully
# TYPE galaxy_gateway_signaling_success_total counter
galaxy_gateway_signaling_success_total 38
# HELP galaxy_gateway_signaling_latency_ms WebRTC signaling session latency in milliseconds
# TYPE galaxy_gateway_signaling_latency_ms histogram
galaxy_gateway_signaling_latency_ms_bucket{le="10"} 0
galaxy_gateway_signaling_latency_ms_bucket{le="100"} 5
galaxy_gateway_signaling_latency_ms_bucket{le="+Inf"} 42
galaxy_gateway_signaling_latency_ms_sum 52310.250
galaxy_gateway_signaling_latency_ms_count 42
```

---

## 4  Sampling Knobs

Verbose `info`/`debug` trace log entries can be sub-sampled to avoid noise in
high-throughput deployments.

### Environment variable

| Variable                  | Default | Description                                              |
|---------------------------|---------|----------------------------------------------------------|
| `GALAXY_TRACE_SAMPLE_RATE`| `1.0`   | Float 0.0–1.0. Fraction of eligible log entries written. |

**Behaviour:**

- `1.0` (default) — all log entries are written.  Safe for development/staging.
- `0.1` — ~10 % of `info`/`debug` entries are written.  Suitable for production.
- `0.0` — all `info`/`debug` entries are suppressed.
- **Error / warning events always bypass sampling** (e.g. `signaling_error`,
  `bridge_handoff_failed`, `routing_failed`, `turn_fallback`).

### Hot-reload

`GALAXY_TRACE_SAMPLE_RATE` is read at call-time on every `emit_gateway_log()`
invocation, so you can change it **without restarting the process** by
updating the environment variable (e.g. via a sidecar config reload).

---

## 5  Implementation Details

### Module: `galaxy_gateway/observability.py`

The single source of truth for Round 7 observability primitives:

- `TraceContext` — frozen dataclass with `trace_id` / `span_id`.
- `emit_gateway_log()` — writes JSON to `Galaxy.Gateway` logger.
- `GatewayMetrics` — in-process counters + `_LatencyHistogram`s.
- `get_gateway_metrics()` — process-level singleton.
- `prometheus_text()` on `GatewayMetrics` — Prometheus text exposition.

### Integration points

| File                                | Change                                                       |
|-------------------------------------|--------------------------------------------------------------|
| `galaxy_gateway/webrtc_proxy.py`    | Import `TraceContext`, `emit_gateway_log`, `get_gateway_metrics`; emit structured logs and update counters on every path. |
| `galaxy_gateway/device_router.py`   | Import same; generate/propagate `TraceContext`; emit `dispatcher_selection`, `bridge_handoff_start`; update routing counters. |
| `galaxy_gateway/agent_bridge.py`    | Import same; emit `bridge_handoff_ok/failed/fallback`; update bridge counters/histograms. |
| `galaxy_gateway/app.py`             | Expose `/api/v1/gateway/metrics` (Prometheus) and `/api/v1/gateway/metrics/json`. |

### Backward compatibility

- All new log fields are **additive**; existing consumers of `Galaxy.Gateway`
  logs are not broken.
- The new metrics endpoint is at a distinct path (`/api/v1/gateway/metrics`)
  and does not interfere with existing `/metrics` or `/health/metrics` paths.
- The `trace_id` variable in `webrtc_proxy.py` is preserved for backward-compat
  with existing log lines that reference it by name.
