# Galaxy – Resilience & Performance Protection (PR-G5)

> **Scope:** Adaptive concurrency / queue-depth controls, circuit breakers /
> degradation paths for `CommandRouter`, monitoring metrics consistent with
> G2, K8s HPA & Docker Compose examples, and a Locust load test.

---

## Table of contents

1. [Architecture overview](#architecture-overview)
2. [Components](#components)
3. [Configuration (env vars)](#configuration-env-vars)
4. [API endpoints](#api-endpoints)
5. [K8s HPA](#k8s-hpa)
6. [Docker Compose rate limiting](#docker-compose-rate-limiting)
7. [Load testing with Locust](#load-testing-with-locust)
8. [Metrics format](#metrics-format)
9. [Backward compatibility](#backward-compatibility)

---

## Architecture overview

```
Client request
     │
     ▼
CommandRouter.dispatch()
     │
     ├── Admission control ──────────────────── queue_depth >= max_queue_depth?
     │        YES → return FAILED (throttled=True) → 429-compatible response
     │        NO  → continue
     │
     ├── Cache hit? (existing) → return cached result
     │
     └── Execute targets
              │
              ├── AdaptiveSemaphore  — limits simultaneous calls (AIMD algorithm)
              │
              └── per-target CircuitBreaker
                       CLOSED    → call executor normally
                       HALF_OPEN → probe call; success → CLOSED; fail → OPEN
                       OPEN      → invoke fallback (if set) or return error immediately
```

**All three controls are independently toggleable via env vars** with safe
backward-compatible defaults (see [Configuration](#configuration-env-vars)).

---

## Components

### `core/resilience/circuit_breaker.py` — CircuitBreaker

Per-target three-state machine (CLOSED → OPEN → HALF_OPEN → CLOSED).

| Parameter | Default | Description |
|-----------|---------|-------------|
| `failure_threshold` | 5 | Failures in rolling window to trip circuit |
| `recovery_timeout` | 30 s | Time in OPEN before probe attempt |
| `half_open_probes` | 1 | Concurrent trial calls in HALF_OPEN |
| `window_size` | 10 | Rolling failure-count window |
| `fallback` | None | Async callable used when circuit is OPEN |

```python
from core.resilience.circuit_breaker import CircuitBreaker

cb = CircuitBreaker(
    target="my_device",
    failure_threshold=5,
    fallback=my_fallback_fn,   # optional
)
result = await cb.call(my_executor_fn, target, command, params)
```

### `core/resilience/adaptive_semaphore.py` — AdaptiveSemaphore

AIMD-based concurrency limiter:

* **Additive increase**: every `probe_interval` seconds, if p99 < target and
  error rate < threshold, increment limit by 1 (up to `max_limit`).
* **Multiplicative decrease**: if error rate ≥ threshold, halve the limit
  (floor at `min_limit`).

```python
from core.resilience.adaptive_semaphore import AdaptiveSemaphore

sem = AdaptiveSemaphore(initial_limit=10, max_limit=50)
async with sem:
    result = await call_device()
await sem.record(latency_ms, error=False)
```

### `core/resilience/metrics.py` — ResilienceMetrics

Singleton counter store for:
- `queue_depth` / `queue_depth_max`
- `total_accepted` / `total_rejected`
- `rejection_rate_per_min` (rolling 60-second window)
- `total_fallbacks`
- `total_circuit_opens`

```python
from core.resilience.metrics import get_resilience_metrics

m = get_resilience_metrics()
m.record_rejected()        # admission control reject
m.record_fallback()        # CB fallback used
snap = m.snapshot()        # JSON-serialisable dict
text = m.prometheus_text() # Prometheus exposition
```

### `core/command_router.py` — CommandRouter (updated)

New constructor parameters (all optional, backward-compatible):

| Parameter | Env var | Default | Description |
|-----------|---------|---------|-------------|
| `max_queue_depth` | `GALAXY_ROUTER_MAX_QUEUE_DEPTH` | 200 | Max in-flight requests before rejection |
| `cb_enabled` | `GALAXY_ROUTER_CB_ENABLED` | `true` | Enable per-target circuit breakers |
| `adaptive_concurrency` | `GALAXY_ROUTER_ADAPTIVE_CONCURRENCY` | `true` | Enable AIMD adaptive semaphore |

New public methods:
- `get_resilience_snapshot()` — combined metrics + CB states + adaptive semaphore snapshot
- `get_stats()` — now includes `total_rejected`, `total_fallbacks`, `circuit_breaker_states`

---

## Configuration (env vars)

All variables are optional. Existing deployments work unchanged.

| Variable | Default | Description |
|----------|---------|-------------|
| `GALAXY_ROUTER_MAX_QUEUE_DEPTH` | `200` | Admission queue limit |
| `GALAXY_ROUTER_CB_ENABLED` | `true` | Toggle circuit breakers |
| `GALAXY_ROUTER_ADAPTIVE_CONCURRENCY` | `true` | Toggle AIMD semaphore |
| `GALAXY_CB_FAILURE_THRESHOLD` | `5` | Failures before CB opens |
| `GALAXY_CB_RECOVERY_TIMEOUT_S` | `30` | OPEN→HALF_OPEN delay (s) |
| `GALAXY_CB_HALF_OPEN_PROBES` | `1` | Trial calls in HALF_OPEN |
| `GALAXY_CB_WINDOW_SIZE` | `10` | Failure-rate rolling window |
| `GALAXY_AS_INIT_LIMIT` | `10` | Adaptive semaphore initial limit |
| `GALAXY_AS_MIN_LIMIT` | `2` | Adaptive semaphore floor |
| `GALAXY_AS_MAX_LIMIT` | `50` | Adaptive semaphore ceiling |
| `GALAXY_AS_TARGET_LATENCY_MS` | `500` | Target p99 latency for AIMD |
| `GALAXY_AS_ERROR_THRESHOLD` | `0.2` | Error rate for MD trigger |
| `GALAXY_AS_PROBE_INTERVAL_S` | `10` | AIMD evaluation interval |

---

## API endpoints

### `GET /api/v1/resilience/metrics`

JSON snapshot of all resilience counters.

```json
{
  "resilience_metrics": {
    "queue_depth": 3,
    "queue_depth_max": 12,
    "total_accepted": 1024,
    "total_rejected": 5,
    "rejection_rate_per_min": 1.0,
    "rejection_fraction": 0.0049,
    "total_fallbacks": 2,
    "total_circuit_opens": 1,
    "uptime_seconds": 3600.0
  },
  "router": {
    "circuit_breakers": {
      "device_001": { "state": "closed", "recent_error_rate": 0.0, ... }
    },
    "adaptive_semaphore": {
      "current_limit": 12, "p99_latency_ms": 87.3, ...
    },
    "queue_depth": 3,
    "max_queue_depth": 200
  }
}
```

### `GET /api/v1/resilience/metrics/prom`

Prometheus text exposition (compatible with G2 `/metrics` scraping).

```
# HELP galaxy_resilience_queue_depth Current dispatch queue depth
# TYPE galaxy_resilience_queue_depth gauge
galaxy_resilience_queue_depth 3
...
galaxy_cb_open{target="device_001"} 0
```

### `GET /api/v1/resilience/circuit-breakers`

List all registered circuit breakers and their state.

### `POST /api/v1/resilience/circuit-breakers/{target}/reset`

Manually force a circuit breaker back to CLOSED (e.g. after fixing a device).

---

## K8s HPA

`deployment/k8s/hpa.yaml` provides:

1. A `Deployment` with resilience env vars pre-configured.
2. A CPU+memory-based `HorizontalPodAutoscaler` (scale 2→10 replicas).
3. A commented-out queue-depth HPA using a custom Prometheus metric.
4. A `PodDisruptionBudget` (minAvailable=1).

Apply:
```bash
kubectl apply -f deployment/k8s/hpa.yaml
kubectl get hpa -n galaxy
```

---

## Docker Compose rate limiting

`deployment/docker-compose.rate-limiting.yml` extends the main compose file
with an Nginx rate-limiting reverse proxy and resilience env var overrides.

```bash
docker compose \
  -f docker-compose.yml \
  -f deployment/docker-compose.rate-limiting.yml \
  up -d
```

The Nginx config (`deployment/nginx/ratelimit.conf`) configures:
- 100 req/s general API rate limit
- 10 req/s on `/api/v1/resilience/*`
- 20 simultaneous connections per IP

---

## Load testing with Locust

```bash
pip install locust

# Interactive (browser UI at http://localhost:8089)
locust -f scripts/load_test_locust.py --host=http://localhost:9000

# Headless CI smoke (30 s, 20 users)
locust -f scripts/load_test_locust.py \
       --host=http://localhost:9000 \
       --headless \
       --users 20 \
       --spawn-rate 5 \
       --run-time 30s \
       --exit-code-on-error 1
```

The test validates:
- Command dispatch (sync, async, parallel) degrades gracefully under load.
- `429` / throttled responses conform to the API schema.
- `/api/v1/resilience/metrics` remains available throughout.
- Overall error rate does not exceed `GALAXY_LT_FAILURE_RATE` (default 10%).

---

## Metrics format

All resilience metrics follow the same conventions as G2 SLO metrics:

| Format | Endpoint | Usage |
|--------|----------|-------|
| JSON | `/api/v1/resilience/metrics` | Dashboard, alerting |
| Prometheus | `/api/v1/resilience/metrics/prom` | Prometheus scrape, Grafana |

Key metric names:

| Metric | Type | Description |
|--------|------|-------------|
| `galaxy_resilience_queue_depth` | gauge | Current in-flight requests |
| `galaxy_resilience_total_rejected_total` | counter | Admission-control rejects |
| `galaxy_resilience_rejection_rate_per_min` | gauge | Rejects in last 60 s |
| `galaxy_resilience_total_fallbacks_total` | counter | CB fallback activations |
| `galaxy_resilience_total_circuit_opens_total` | counter | CB open events |
| `galaxy_adaptive_sem_limit` | gauge | Current adaptive concurrency limit |
| `galaxy_adaptive_sem_p99_latency_ms` | gauge | p99 call latency |
| `galaxy_cb_open{target="…"}` | gauge | 1 if circuit is open |

---

## Backward compatibility

- All new `CommandRouter` parameters are optional with safe defaults.
- `max_queue_depth=200` is generous enough that existing low-traffic deployments
  will never hit the limit.
- `cb_enabled=true` / `adaptive_concurrency=true` can both be disabled via env
  vars without code changes.
- `get_stats()` adds new keys but does not remove existing ones.
- API contract of existing endpoints is unchanged.
