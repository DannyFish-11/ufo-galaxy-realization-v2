# Phase Transition Table — State Continuum

> Allowed transitions for `ContinuumPhase`.  
> Any transition not listed here is **forbidden** and must be rejected by the temporal engine.

---

## Allowed Transitions

| From | To | Trigger condition | Guard |
|---|---|---|---|
| `formless` | `liminal` | `presence_intensity ≥ hysteresis.liminal_enter` | — |
| `liminal` | `formless` | `presence_intensity < hysteresis.liminal_exit` AND dwell elapsed | dwell ≥ `dwell.liminal_ms` |
| `liminal` | `manifest` | `collapse_tendency ≥ hysteresis.manifest_enter` AND `action_level ≥ assist` | dwell ≥ `dwell.liminal_ms` |
| `manifest` | `receding` | task finished OR timeout OR `retreat_tendency` high OR user cancel | dwell ≥ `dwell.manifest_ms` |
| `receding` | `formless` | `presence_intensity < config.min_presence_formless` | dwell ≥ `dwell.receding_ms` |

---

## Forbidden Transitions

| From | To | Reason |
|---|---|---|
| `formless` | `manifest` | Skips liminal gate; no structure has formed |
| `formless` | `receding` | Receding requires prior presence |
| `manifest` | `liminal` | Structure cannot un-collapse without receding first |
| `receding` | `manifest` | Must return to formless before re-entering manifest |
| `receding` | `liminal` | Must return to formless before re-entering liminal |

> **Exception:** When `flags.allow_emergency_jump = True`, the transition  
> `formless → manifest` is permitted.  Use only for critical/interrupt scenarios.

---

## Transition Decision Tree

```
Current phase = FORMLESS
  │
  ├─ presence_intensity ≥ liminal_enter?
  │     YES → transition to LIMINAL
  │     NO  → remain FORMLESS

Current phase = LIMINAL
  │
  ├─ dwell elapsed?
  │     NO  → remain LIMINAL (dwell guard)
  │
  ├─ collapse_tendency ≥ manifest_enter AND action_level ≥ assist?
  │     YES → transition to MANIFEST
  │
  ├─ presence_intensity < liminal_exit?
  │     YES → transition to FORMLESS
  │
  └─ else → remain LIMINAL

Current phase = MANIFEST
  │
  ├─ dwell elapsed?
  │     NO  → remain MANIFEST (dwell guard)
  │
  ├─ task finished OR timeout OR retreat_tendency high OR user cancel?
  │     YES → transition to RECEDING
  │
  └─ else → remain MANIFEST

Current phase = RECEDING
  │
  ├─ dwell elapsed?
  │     NO  → remain RECEDING (dwell guard)
  │
  ├─ presence_intensity < min_presence_formless?
  │     YES → transition to FORMLESS
  │
  └─ else → remain RECEDING (continue decay)
```

---

## Dwell Guard Summary

| Phase | Minimum dwell before leaving | Config key |
|---|---|---|
| `formless` | None (can leave immediately) | — |
| `liminal` | 800 ms (default) | `dwell.liminal_ms` |
| `manifest` | 1200 ms (default) | `dwell.manifest_ms` |
| `receding` | 600 ms (default) | `dwell.receding_ms` |

---

## Hysteresis Thresholds Summary

| Transition | Enter threshold | Exit threshold |
|---|---|---|
| formless ↔ liminal | `hysteresis.liminal_enter` = 0.68 | `hysteresis.liminal_exit` = 0.45 |
| liminal ↔ manifest | `hysteresis.manifest_enter` = 0.78 | `hysteresis.manifest_exit` = 0.52 |

The asymmetric enter/exit thresholds prevent rapid oscillation near boundaries.  
A signal must exceed the *enter* threshold to commit and drop below the *exit* threshold to leave.

---

## Return Triggers (any phase → receding)

| Trigger | Condition |
|---|---|
| `task_finished` | Downstream executor signals completion |
| `timeout` | No new input for `timeout_receding_ms` (default 5000 ms) |
| `low_value` | `should_act_score` remains below 0.15 for sustained period |
| `high_uncertainty` | `uncertainty > 0.85` sustained |
| `user_cancel` | Explicit cancellation signal from user context |

Return actions (ordered by severity, least first):

| Action | Meaning |
|---|---|
| `hold` | Pause evaluation; maintain current phase |
| `soft_decay` | Gradually reduce `presence_intensity` |
| `step_down` | Immediate phase step down (manifest → liminal, liminal → formless) |
| `return_to_formless` | Unconditional reset to formless |

---

*See also: [OPENCLAWD_STATE_CONTINUUM.md](OPENCLAWD_STATE_CONTINUUM.md) for the full protocol overview.*
