# OpenClawd State Continuum — Protocol Overview

> **This is a state protocol, not a UI protocol.**
> All fields describe system *presence* and *intent* as a continuous signal.
> Rendering layers (visual, audio, haptic) are optional consumers.

---

## 1. Purpose

The State Continuum upgrades OpenClawd from a discrete request/response assistant into a **continuously-present state entity**.  The system moves through a tri-state public model; transitions are smooth, governed by hysteresis and dwell constraints, and fully reversible.

---

## 2. Public Tri-State Model

External consumers (APIs, desktop status boards, documentation) interact with
**three** public-facing states:

| Public State | Meaning | `presence_intensity` range |
|---|---|---|
| `silent` | Native multimodal ingress, minimal footprint | 0.0 – 0.2 |
| `liminal` | Intent forming; single-device ↔ cross-device bridge | 0.2 – 0.7 |
| `manifest` | Structure formed, action in progress | 0.7 – 1.0 |

> **Note:** `receding` is an **internal return/rollback mechanism** and is NOT
> a public primary state.  It is never surfaced to external consumers.  Use
> `ContinuumState.tri_state_phase` (a `TriStatePhase` enum) for all outward
> projections.

### Why three states?

`silent` is the native multimodal *intake* state — the system is always alive
and receiving inputs (audio, visual, touch, text) even when outwardly quiet.
`liminal` is the *bridging* state where single-device local execution can
smoothly expand into cross-device coordination.  `manifest` is the *execution*
state where all action paths (local UIA, system-API, cross-device) operate.

---

## 3. Internal Phase Lifecycle

The continuum engine uses four internal phases for precise transition control:

```
         ┌─────────────────────────────────────────────────────────────┐
         │               Internal State Continuum Lifecycle             │
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
  │  RECEDING │◀──────────────────────────────│  MANIFEST │
  │ (internal)│                                │  (active) │
  └───────────┘                                └───────────┘
        │        presence < floor
        └────────────────────────────────────▶ FORMLESS
```

| Internal Phase | Public Projection | Meaning |
|---|---|---|
| `formless` | `silent` | Silent sensing, minimal footprint |
| `liminal` | `liminal` | Intent forming, structure undecided |
| `manifest` | `manifest` | Structure stable, action in progress |
| `receding` | `silent` *(collapsed)* | **Internal only** — expression dissolving, returning to silence |

**`receding` is never exposed externally.**  It collapses to `silent` when
projected via `ContinuumState.tri_state_phase`.

---

## 4. Wire Format — `state_continuum`

Appended to every OpenClawd response as an **optional, additive field**.  Existing response fields are unchanged.

The `phase` field carries the **internal** `ContinuumPhase` value; external
consumers SHOULD prefer `tri_state_phase` for display and routing decisions.

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

### Public projection

Use `ContinuumState.tri_state_phase` to get a `TriStatePhase` value (`silent`,
`liminal`, or `manifest`) suitable for status boards and external APIs:

```python
from core.continuum import TriStatePhase, continuum_to_tri_state

pub = state.tri_state_phase   # TriStatePhase.SILENT | LIMINAL | MANIFEST
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

## 5. Core Computational Pipeline

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
      │                                              (internal only)
      ▼
ContinuumState             ← assemble final output
                             (.tri_state_phase = public projection)
```

---

## 6. Decision Gate Formula

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

## 7. Backward Compatibility

- The `state_continuum` field is **additive**.  Clients that do not consume it are unaffected.
- All existing request/response fields remain unchanged.
- When `flags.enabled = False`, the field is omitted entirely.
- On engine error, the field is present but carries `degraded: true` and a safe formless state.

---

## 8. Key Constraints

1. **Not UI semantics** — `ExpressionState` fields describe presence energy, not widget properties.
2. **No hard phase jumps** — `formless → manifest` is forbidden except in emergency mode (`allow_emergency_jump: true`).
3. **Default silent** — initial state is always `formless` (projects to `silent`).
4. **Always reversible** — any path through the graph ends at `formless`.
5. **Interrupt on value** — action only when `should_act_score` exceeds the threshold.
6. **Three public states** — external code MUST use `TriStatePhase` / `tri_state_phase`; never depend on `receding` being visible externally.

---

## 9. Configuration Reference

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
| `dwell.receding_ms` | 600 | Internal only |
| `timeout_receding_ms` | 5000 | Idle → receding (internal) |

---

## 10. Module Map

| Module | Responsibility |
|---|---|
| `core/continuum/types.py` | Canonical enums (`TriStatePhase`, `ContinuumPhase`) and Pydantic models |
| `core/continuum/config.py` | Configuration structures and defaults |
| `core/continuum/human_field.py` | Human field inference engine *(PR-3)* |
| `core/continuum/state_fusion.py` | Multi-source state fusion *(PR-3)* |
| `core/continuum/temporal_engine.py` | EMA, hysteresis, dwell *(PR-2)* |
| `core/continuum/liminal_field.py` | Liminal field computation *(PR-3)* |
| `core/continuum/decision_gate.py` | Decision gate formula *(PR-4)* |
| `core/continuum/expression_engine.py` | Expression planner *(PR-5)* |
| `core/continuum/return_engine.py` | Return-to-formless logic *(PR-4)* — internal |
| `core/continuum/orchestrator.py` | Single entry-point `run_cycle()` *(PR-5)* |

---

*Protocol version 1 — subject to additive change only.*

---
