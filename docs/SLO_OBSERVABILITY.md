# SLO Observability — Galaxy Health Monitor (PR-G2)

Runtime SLO metrics for the Galaxy health-monitoring layer: startup duration,
heartbeat loss rate, reconnect attempts, and command latency p50/p95.

---

## 1  Metrics Overview

| Metric | Type | Description |
|--------|------|-------------|
| `galaxy_slo_startup_duration_ms` | Gauge | Milliseconds from process start until the first node/service reported "ready". Set once; remains stable. |
| `galaxy_slo_heartbeat_total` | Counter | Cumulative heartbeat checks performed since process start. |
| `galaxy_slo_heartbeat_failure_total` | Counter | Cumulative heartbeat checks that failed or timed out. |
| `galaxy_slo_heartbeat_loss_rate` | Gauge | Fraction of **recent** heartbeat checks that failed (rolling window, 0.0–1.0). |
| `galaxy_slo_reconnect_attempts_total` | Counter | Cumulative node reconnect/restart attempts triggered by the health monitor. |
| `galaxy_slo_command_latency_p50_ms` | Gauge | 50th-percentile health-check round-trip latency (ms), rolling window. `NaN` until first sample. |
| `galaxy_slo_command_latency_p95_ms` | Gauge | 95th-percentile health-check round-trip latency (ms), rolling window. `NaN` until first sample. |
| `galaxy_slo_command_latency_sample_count` | Gauge | Number of latency samples currently in the rolling window. |

---

## 2  Endpoints

### Prometheus scrape

```
GET http://<health-monitor-host>:<port>/metrics
Content-Type: text/plain; version=0.0.4; charset=utf-8
```

Example output:

```
# HELP galaxy_slo_startup_duration_ms System startup duration in milliseconds (set once at first ready state)
# TYPE galaxy_slo_startup_duration_ms gauge
galaxy_slo_startup_duration_ms 342.7
# HELP galaxy_slo_heartbeat_total Total heartbeat checks performed
# TYPE galaxy_slo_heartbeat_total counter
galaxy_slo_heartbeat_total 480
# HELP galaxy_slo_heartbeat_failure_total Total heartbeat checks that failed or timed out
# TYPE galaxy_slo_heartbeat_failure_total counter
galaxy_slo_heartbeat_failure_total 3
# HELP galaxy_slo_heartbeat_loss_rate Fraction of recent heartbeat checks that failed (rolling window, 0.0-1.0)
# TYPE galaxy_slo_heartbeat_loss_rate gauge
galaxy_slo_heartbeat_loss_rate 0.015
# HELP galaxy_slo_reconnect_attempts_total Cumulative number of node reconnect/restart attempts
# TYPE galaxy_slo_reconnect_attempts_total counter
galaxy_slo_reconnect_attempts_total 1
# HELP galaxy_slo_command_latency_p50_ms 50th-percentile command round-trip latency in milliseconds (rolling window)
# TYPE galaxy_slo_command_latency_p50_ms gauge
galaxy_slo_command_latency_p50_ms 48.3
# HELP galaxy_slo_command_latency_p95_ms 95th-percentile command round-trip latency in milliseconds (rolling window)
# TYPE galaxy_slo_command_latency_p95_ms gauge
galaxy_slo_command_latency_p95_ms 312.1
```

### JSON snapshot

```
GET http://<health-monitor-host>:<port>/api/v1/slo/metrics
Content-Type: application/json
```

Example response:

```json
{
  "startup": {
    "duration_ms": 342.7,
    "recorded_at": 1700000000.0
  },
  "heartbeat": {
    "total": 480,
    "failures": 3,
    "loss_rate": 0.015
  },
  "reconnect": {
    "attempts_total": 1
  },
  "command_latency": {
    "sample_count": 200,
    "p50_ms": 48.3,
    "p95_ms": 312.1
  }
}
```

---

## 3  Scraping with Prometheus

Add the following job to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: galaxy_health_monitor
    static_configs:
      - targets: ["localhost:9100"]   # default health-monitor port
    scrape_interval: 30s
    metrics_path: /metrics
```

The port is controlled by `core.port_config` (`health_monitor` key).  The
default is `9100`.  Override with the `HEALTH_MONITOR_PORT` environment
variable if needed.

---

## 4  Grafana Dashboard

An example Grafana dashboard is provided at
[`docs/grafana/slo_dashboard.json`](grafana/slo_dashboard.json).

### Import steps

1. Open Grafana → **+** (Create) → **Import**.
2. Upload `docs/grafana/slo_dashboard.json` or paste its contents.
3. Select your Prometheus data source when prompted.
4. Click **Import**.

The dashboard contains four rows:

| Row | Panels |
|-----|--------|
| **SLO Overview** | Startup Duration · Heartbeat Loss Rate · Reconnect Attempts · Command Latency p95 |
| **Heartbeat Health** | Loss Rate over time · Total vs Failures over time |
| **Command Latency** | p50 and p95 trend |
| **Reconnects** | Reconnect rate per 5 m |

---

## 5  SLO Targets (Recommended)

These are indicative starting points; adjust to match your deployment SLA.

| SLO | Target | Metric |
|-----|--------|--------|
| Startup duration | ≤ 15 000 ms | `galaxy_slo_startup_duration_ms` |
| Heartbeat loss rate | ≤ 5 % | `galaxy_slo_heartbeat_loss_rate` |
| Reconnect attempts (rate) | ≤ 10 / hour | `increase(galaxy_slo_reconnect_attempts_total[1h])` |
| Command latency p50 | ≤ 200 ms | `galaxy_slo_command_latency_p50_ms` |
| Command latency p95 | ≤ 1 000 ms | `galaxy_slo_command_latency_p95_ms` |

Example Prometheus alerting rule:

```yaml
groups:
  - name: galaxy_slo
    rules:
      - alert: GalaxyHighHeartbeatLossRate
        expr: galaxy_slo_heartbeat_loss_rate > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Galaxy heartbeat loss rate above 5 %"
          description: "Current loss rate: {{ $value | humanizePercentage }}"

      - alert: GalaxyHighCommandLatencyP95
        expr: galaxy_slo_command_latency_p95_ms > 1000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Galaxy command latency p95 above 1 s"
          description: "Current p95: {{ $value | humanize }}ms"
```

---

## 6  Configuration

All tuning is done via environment variables — no code change required.

| Variable | Default | Description |
|----------|---------|-------------|
| `GALAXY_SLO_LATENCY_WINDOW` | `1000` | Max latency samples kept for percentile computation (rolling). |
| `GALAXY_SLO_HEARTBEAT_WINDOW` | `200` | Max heartbeat results kept for loss-rate computation (rolling). |
| `GALAXY_TRACE_SAMPLE_RATE` | `1.0` | Trace log sampling rate (gateway, see `docs/OBSERVABILITY.md`). |

---

## 7  Implementation Details

### Module: `core/slo_metrics.py`

Single source of truth for SLO metric collection:

- `SLOMetrics` — thread-safe collector with rolling windows.
- `get_slo_metrics()` — process-level singleton (lazy-init).
- `.record_startup(ms)` — called once in `health_monitor.startup_event`.
- `.record_heartbeat(ok)` — called on every `HealthMonitor.check_node()` cycle.
- `.record_reconnect(node_id)` — called in `HealthMonitor.handle_unhealthy_node()`.
- `.record_command_latency(ms)` — called after every health-check HTTP request.
- `.prometheus_text()` — Prometheus text-format exposition.
- `.snapshot()` — JSON-serialisable dict.

### Integration points

| File | Change |
|------|--------|
| `health_monitor.py` | Imports `get_slo_metrics`; records heartbeat, latency, reconnect; exposes `/metrics` and `/api/v1/slo/metrics`; records startup in `startup_event`. |
| `system_manager.py` | `wait_for_node()` calls `get_slo_metrics().record_startup(ms)` when a node first becomes ready. |

### Backward compatibility

- All new endpoints are at **distinct paths** (`/metrics`, `/api/v1/slo/metrics`).
- No existing API response is modified.
- The `latency_ms` field is **added** to health-check node status dicts (additive).
- Production paths are unchanged beyond metric emission.
