# CONTINUUM_OBSERVABILITY.md

> **Scope**: PR-6 — Continuum Observability, Feature Flags, and Performance Guardrails

---

## Overview

This document covers the observability and operational control surface added to the
State Continuum pipeline in PR-6.  All additions are opt-in via configuration flags
and have safe defaults that preserve backward compatibility.

---

## 1. Structured Logging

The continuum pipeline emits structured log entries at two levels:

| Logger name                          | When emitted                             |
|--------------------------------------|------------------------------------------|
| `Galaxy.Continuum.Orchestrator`      | Tick summary, stage events, warnings     |

### Enabling verbose logs

Set `debug_continuum = true` in `config.json` (or pass `extra_flags={"debug_continuum": True}` to `ContinuumOrchestrator`).

When `debug_continuum` is `true` the orchestrator emits one log entry per pipeline stage and a final tick summary:

```
DEBUG Galaxy.Continuum.Orchestrator Continuum stage perception | trace=<id> skipped=False elapsed_ms=0.12
DEBUG Galaxy.Continuum.Orchestrator Continuum stage human_field | trace=<id> skipped=False attention=0.500 intent=0.000 elapsed_ms=0.04
DEBUG Galaxy.Continuum.Orchestrator Continuum stage state_fusion | trace=<id> phase_candidate=formless confidence=0.000 elapsed_ms=0.01
DEBUG Galaxy.Continuum.Orchestrator Continuum stage liminal_field | trace=<id> skipped=False elapsed_ms=0.02
DEBUG Galaxy.Continuum.Orchestrator Continuum stage temporal_engine | trace=<id> phase=formless intensity=0.039 elapsed_ms=0.01
DEBUG Galaxy.Continuum.Orchestrator Continuum stage decision_gate | trace=<id> skipped=False action=observe score=0.000 elapsed_ms=0.01
DEBUG Galaxy.Continuum.Orchestrator Continuum stage expression_engine | trace=<id> form=none spatial=absent elapsed_ms=0.01
DEBUG Galaxy.Continuum.Orchestrator Continuum tick | trace=<id> phase=formless intensity=0.039 coherence=0.000 action=observe degraded=False elapsed_ms=0.42
```

#### Sampling skipped tick (debug log)

```
DEBUG Galaxy.Continuum.Orchestrator Continuum tick SKIPPED (sampling) | trace=<id> sampling_rate=0.100
```

#### Time budget exceeded (warning log, always emitted regardless of debug flag)

```
WARNING Galaxy.Continuum.Orchestrator Continuum tick budget exceeded | trace=<id> elapsed_ms=52.1 max_ms=20.0 — degrading to formless
```

### Log fields reference

| Field              | Type    | Description                                          |
|--------------------|---------|------------------------------------------------------|
| `trace`            | string  | Caller-supplied trace/correlation ID                 |
| `phase`            | string  | Current phase: `formless / liminal / manifest / receding` |
| `intensity`        | float   | EMA-smoothed presence intensity (0–1)                |
| `coherence`        | float   | Degree of intent coherence (0–1)                     |
| `action`           | string  | Decision-gate action level                           |
| `degraded`         | bool    | Whether tick returned a degraded state               |
| `elapsed_ms`       | float   | Wall-clock time for the full tick or stage (ms)      |
| `skipped`          | bool    | Whether this stage/tick was bypassed                 |

---

## 2. Feature Flags

All flags live under `FeatureFlags` in `core/continuum/config.py` and can be set via `config.json` top-level keys.  All flags default to their **backward-compatible** values.

### Master flags (existing)

| `config.json` key   | `FeatureFlags` field | Default | Effect when `false`                            |
|---------------------|----------------------|---------|------------------------------------------------|
| `enable_continuum`  | `enabled`            | `true`  | Return static formless state, skip all work    |
| `debug_continuum`   | `debug`              | `false` | Suppress verbose per-stage log entries         |

### Per-component flags (new in PR-6)

| `config.json` key        | `FeatureFlags` field     | Default | Disabled behaviour                                          |
|--------------------------|--------------------------|---------|-------------------------------------------------------------|
| `enable_perception`      | `enable_perception`      | `true`  | Minimal default frame used regardless of caller input       |
| `enable_human_field`     | `enable_human_field`     | `true`  | `HumanFieldState()` default substituted                     |
| `enable_liminal_field`   | `enable_liminal_field`   | `true`  | Liminal metrics zeroed; unified state not enriched          |
| `enable_decision_gate`   | `enable_decision_gate`   | `true`  | `DecisionState(action_level=OBSERVE)` substituted           |

**Example** — disable only the decision gate:

```json
{
  "enable_continuum": true,
  "debug_continuum": false,
  "enable_decision_gate": false
}
```

**All flags are optional** and already present with their defaults in `config.json`.

### Programmatic override via `extra_flags`

Any of the above keys can be passed as `extra_flags` to `ContinuumOrchestrator`:

```python
from core.continuum.orchestrator import ContinuumOrchestrator

orch = ContinuumOrchestrator(extra_flags={
    "enable_human_field": False,
    "enable_decision_gate": False,
    "continuum_max_tick_ms": 50,
    "continuum_sampling_rate": 0.5,
})
```

---

## 3. Sampling Rate

Control what fraction of ticks are actually evaluated.

| `config.json` key           | `FeatureFlags` field | Default | Range    |
|-----------------------------|----------------------|---------|----------|
| `continuum_sampling_rate`   | `sampling_rate`      | `1.0`   | 0.0–1.0  |

- `1.0` (default) — every tick is evaluated (no change from previous behaviour).
- `0.5` — ~50 % of ticks are evaluated; the rest return the last cached state.
- `0.0` — all ticks are skipped; the last cached state (or a formless default on the first call) is always returned.

**Skipped ticks** increment `ticks_skipped` in [metrics](#4-in-process-metrics) and (when `debug_continuum=true`) emit a `DEBUG` log line.

**Use case**: Reduce compute cost in high-frequency polling scenarios while keeping the last known state available.

---

## 4. Per-Tick Time Budget

Enforce a wall-clock deadline on each full pipeline evaluation.

| `config.json` key        | `FeatureFlags` field | Default | Unit |
|--------------------------|----------------------|---------|------|
| `continuum_max_tick_ms`  | `max_tick_ms`        | `0`     | ms   |

- `0` (default) — no time limit (existing behaviour preserved).
- Any positive value — if the pipeline takes longer than `max_tick_ms` milliseconds the result is discarded and a degraded formless state is returned:

  ```python
  ContinuumState(
      phase=ContinuumPhase.FORMLESS,
      degraded=True,
      degrade_reason="tick_budget_exceeded",
      trace_id=<caller_trace_id>,
  )
  ```

A `WARNING` log entry is always emitted (regardless of `debug_continuum`) when the budget is exceeded.

**Important**: the time measurement covers the full pipeline from the start of `_run_pipeline` to the end; it does not include sampling overhead.

---

## 5. In-Process Metrics

`core/continuum/metrics.py` provides a lightweight, thread-safe metrics singleton with no external dependencies.

### Accessing the singleton

```python
from core.continuum.metrics import get_continuum_metrics

m = get_continuum_metrics()
snap = m.snapshot()
```

### Snapshot schema

```json
{
  "ticks_total": 1042,
  "ticks_degraded": 3,
  "ticks_skipped": 87,
  "ticks_budget_exceeded": 1,
  "phases": {
    "formless": 800,
    "liminal": 180,
    "manifest": 50,
    "receding": 12
  },
  "tick_latency": {
    "count": 955,
    "sum_ms": 4320.5,
    "avg_ms": 4.524,
    "min_ms": 0.21,
    "max_ms": 48.3,
    "buckets": {
      "le_5ms": 720,
      "le_10ms": 200,
      "le_25ms": 30,
      "le_50ms": 5,
      "le_inf": 0
    }
  },
  "stage_latency": {
    "perception": { "count": 955, "sum_ms": 120.3, "avg_ms": 0.126, ... },
    "human_field": { ... },
    "state_fusion": { ... },
    "liminal_field": { ... },
    "temporal_engine": { ... },
    "decision_gate": { ... },
    "expression_engine": { ... },
    "return_engine": { ... }
  }
}
```

### Resetting metrics

```python
get_continuum_metrics().reset()
```

Useful between isolated test cases or when a session boundary is reached.

---

## 6. Configuration Reference (`config.json`)

Below is the complete set of continuum-related keys with their defaults:

```json
{
  "enable_continuum": true,
  "debug_continuum": false,
  "enable_perception": true,
  "enable_human_field": true,
  "enable_liminal_field": true,
  "enable_decision_gate": true,
  "continuum_max_tick_ms": 0,
  "continuum_sampling_rate": 1.0
}
```

All keys are **optional** — the system operates identically to pre-PR-6 behaviour when none are set.

---

## 7. Tests

| Test file                                 | Coverage area                                    |
|-------------------------------------------|--------------------------------------------------|
| `tests/test_continuum_observability.py`   | ContinuumMetrics API, structured logging, per-component flags, extra-flags passthrough |
| `tests/test_continuum_guardrails.py`      | Time-budget guardrail, sampling-rate guardrail, FeatureFlags validation, integration |

Run:

```bash
python -m pytest tests/test_continuum_observability.py tests/test_continuum_guardrails.py -v
```

---

## 8. Architecture Notes

- All new code lives in `core/continuum/` — no UI, no rendering, no HTTP-specific logic.
- `ContinuumMetrics` is a process-level singleton; it accumulates across all orchestrator instances.
- Per-component flags **substitute safe defaults** — they never raise or propagate errors.
- The time-budget check happens *after* the pipeline finishes; it does not interrupt mid-flight stages.
- Sampling is applied at the very beginning of `run()`, before any stage work begins.
- Backward compatibility is guaranteed: all new flags default to the behaviour that existed before PR-6.
