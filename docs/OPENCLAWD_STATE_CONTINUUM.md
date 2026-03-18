# OpenClawd State Continuum — Protocol Overview

> **This is a state protocol, not a UI protocol.**
> All fields describe system *presence* and *intent* as a continuous signal.
> Rendering layers (visual, audio, haptic) are optional consumers.

---

## 1. Purpose

The State Continuum upgrades OpenClawd from a discrete request/response assistant into a **continuously-present state entity**.  The system is always in one of four phases; transitions are smooth, governed by hysteresis and dwell constraints, and fully reversible.

---

## 2. Phase Model

```
         ┌─────────────────────────────────────────────────────────────┐
         │                   State Continuum Lifecycle                  │
         └─────────────────────────────────────────────────────────────┘

  ┌───────────┐   intent↑ / coherence↑       ┌───────────┐
  │  FORMLESS │ ─────────────────────────────▶│  LIMINAL  │
  │  (silent) │ ◀─────────────────────────────│ (brewing) │
  └───────────┘   signal drops / timeout      └───────────┘
                                                    │
                                  collapse_tendency↑│
                                  decision ≥ assist │
                                                    ▼
  ┌───────────┐   task done / value drop       ┌───────────┐
  │  RECEDING │ ◀─────────────────────────────│  MANIFEST │
  │ (fading)  │                                │  (active) │
  └───────────┘                                └───────────┘
        │        presence < floor
        └────────────────────────────────────▶ FORMLESS
```

| Phase | Meaning | Default presence_intensity |
|---|---|---|
| `formless` | Silent sensing, minimal footprint | 0.0 – 0.2 |
| `liminal` | Intent forming, structure undecided | 0.2 – 0.7 |
| `manifest` | Structure stable, action in progress | 0.7 – 1.0 |
| `receding` | Expression dissolving | 0.7 → 0.0 |

---

## 3. Wire Format — `state_continuum`

Appended to every OpenClawd response as an **optional, additive field**.  Existing response fields are unchanged.

```json
{
  "state_continuum": {
    "version": 1,
    "trace_id": "cont_a3f8c21d4b7e",
    "phase": "liminal",
    "presence_intensity": 0.41,
    "coherence": 0.36,
    "ambiguity": 0.64,
    "collapse_tendency": 0.27,
    "retreat_tendency": 0.08,
    "stability": 0.82,
    "decision": {
      "should_act_score": 0.31,
      "action_level": "assist",
      "decision_reason": "moderate intent, low interruption cost",
      "decision_confidence": 0.67,
      "value_score": 0.48,
      "interruption_cost": 0.12,
      "risk_cost": 0.05,
      "timestamp": 1710000000.0
    },
    "expression": {
      "motion": 0.32,
      "intensity": 0.41,
      "form_signature": "diffuse_cluster",
      "spatial_presence": "peripheral",
      "texture_hint": "soft_granular",
      "phase_signature": "liminal"
    },
    "degraded": false,
    "degrade_reason": null,
    "timestamp": 1710000000.0,
    "metadata": {}
  }
}
```

### Degraded Fallback

When the continuum engine encounters an unhandled error, it returns a safe `formless` state without interrupting the main response:

```json
{
  "state_continuum": {
    "version": 1,
    "phase": "formless",
    "presence_intensity": 0.0,
    "degraded": true,
    "degrade_reason": "continuum_internal_error"
  }
}
```

---

## 4. Core Computational Pipeline

Each evaluation cycle executes the following stages in order:

```
PerceptionFrame
      │
      ▼
HumanField Engine          ← infer attention, focus, intent_probability, …
      │
      ▼
State Fusion               ← merge human + world context + history → UnifiedState
      │
      ▼
Mode Collapse              ← derive phase_candidate + candidate_confidence
      │
      ▼
Temporal Engine            ← EMA smooth → hysteresis → dwell → rate-limit
      │
      ▼
Liminal Field              ← compute coherence, ambiguity, collapse_tendency
      │
      ▼
Decision Gate              ← value − interruption_cost − risk_cost → ActionLevel
      │
      ▼
Expression Planner         ← map phase + decision → ExpressionState (non-UI)
      │
      ▼
Return Engine              ← check exit conditions → trigger receding if needed
      │
      ▼
ContinuumState             ← assemble final output
```

---

## 5. Decision Gate Formula

```
value             = intent_probability × context_utility × urgency
interruption_cost = interruption_sensitivity × focus_level × timing_penalty
risk_cost         = action_risk × uncertainty

should_act_score  = value − interruption_cost − risk_cost
```

| Score range | ActionLevel |
|---|---|
| < 0.20 | `observe` |
| 0.20 – 0.44 | `hint` |
| 0.45 – 0.69 | `assist` |
| ≥ 0.70 | `execute` |

---

## 6. Backward Compatibility

- The `state_continuum` field is **additive**.  Clients that do not consume it are unaffected.
- All existing request/response fields remain unchanged.
- When `flags.enabled = False`, the field is omitted entirely.
- On engine error, the field is present but carries `degraded: true` and a safe formless state.

---

## 7. Key Constraints

1. **Not UI semantics** — `ExpressionState` fields describe presence energy, not widget properties.
2. **No hard phase jumps** — `formless → manifest` is forbidden except in emergency mode (`allow_emergency_jump: true`).
3. **Default silent** — initial state is always `formless`.
4. **Always reversible** — any path through the graph ends at `formless`.
5. **Interrupt on value** — action only when `should_act_score` exceeds the threshold.

---

## 8. Configuration Reference

See [`core/continuum/config.py`](../core/continuum/config.py) and the
[`ContinuumConfig`](../core/continuum/config.py) Pydantic model for all
configurable parameters with defaults and descriptions.

Key defaults:

| Parameter | Default | Notes |
|---|---|---|
| `tick_ms` | 120 | Evaluation interval |
| `ema_alpha` | 0.25 | Smoothing factor |
| `max_delta_per_tick` | 0.08 | Rate limiter |
| `hysteresis.liminal_enter` | 0.68 | |
| `hysteresis.liminal_exit` | 0.45 | |
| `hysteresis.manifest_enter` | 0.78 | |
| `hysteresis.manifest_exit` | 0.52 | |
| `dwell.liminal_ms` | 800 | |
| `dwell.manifest_ms` | 1200 | |
| `dwell.receding_ms` | 600 | |
| `timeout_receding_ms` | 5000 | Idle → receding |

---

## 9. Module Map

| Module | Responsibility |
|---|---|
| `core/continuum/types.py` | Canonical enums and Pydantic models |
| `core/continuum/config.py` | Configuration structures and defaults |
| `core/continuum/human_field.py` | Human field inference engine *(PR-3)* |
| `core/continuum/state_fusion.py` | Multi-source state fusion *(PR-3)* |
| `core/continuum/temporal_engine.py` | EMA, hysteresis, dwell *(PR-2)* |
| `core/continuum/liminal_field.py` | Liminal field computation *(PR-3)* |
| `core/continuum/decision_gate.py` | Decision gate formula *(PR-4)* |
| `core/continuum/expression_engine.py` | Expression planner *(PR-5)* |
| `core/continuum/return_engine.py` | Return-to-formless logic *(PR-4)* |
| `core/continuum/orchestrator.py` | Single entry-point `run_cycle()` *(PR-5)* |

---

*Protocol version 1 — subject to additive change only.*
