# DECISION_GATE_SPEC.md

## Decision Gate — Specification

The **Decision Gate** (`core/continuum/decision_gate.py`) determines whether
and at what level the system should act during a continuum evaluation cycle.
It is a stateless engine: every call produces a fresh
[`DecisionState`](../core/continuum/types.py) based solely on the inputs
provided.

---

## Decision Formula

```
should_act_score = value - interruption_cost - risk_cost
```

All intermediate terms are bounded in `[0, 1]`.  The final score is clamped
to `[0, 1]` before classification.

### Value

```
value = intent_probability × context_utility × clamp(urgency + 0.05)
```

| Field | Source | Description |
|---|---|---|
| `intent_probability` | `UnifiedState.human.intent_probability` | Probability that an actionable intent is forming |
| `context_utility` | `UnifiedState.context_utility` | Utility estimate of acting given the current world context |
| `urgency` | `UnifiedState.urgency` | Time-sensitivity of potential action |

A floor of `0.05` is added to urgency so that dormant states still produce a
minimal positive signal.

### Interruption Cost

```
interruption_cost = interruption_sensitivity × focus_level × timing_penalty
```

| Field | Source | Description |
|---|---|---|
| `interruption_sensitivity` | `UnifiedState.human.interruption_sensitivity` | How disruptive an interruption would be right now |
| `focus_level` | `UnifiedState.human.focus_level` | Depth of cognitive focus on the current task |
| `timing_penalty` | Constructor / per-call override | Base context timing penalty `[0, 1]`, default `0.5` |

### Risk Cost

```
risk_cost = action_risk × uncertainty
```

| Field | Source | Description |
|---|---|---|
| `action_risk` | `UnifiedState.action_risk` | Estimated risk of taking action |
| `uncertainty` | `UnifiedState.uncertainty` | Model uncertainty about the current context |

---

## Action Levels

The net `should_act_score` is mapped to a graduated
[`ActionLevel`](../core/continuum/types.py):

| Score range | `ActionLevel` | Description |
|---|---|---|
| `< 0.15` | `observe` | Monitor only — no external signal emitted |
| `0.15 – 0.40` | `hint` | Subtle ambient signal — low interruption cost |
| `0.40 – 0.65` | `assist` | Proactive partial engagement — moderate cost |
| `≥ 0.65` | `execute` | Full action — passed all gate thresholds |

Thresholds are defined as module-level constants and can be inspected at
import time:

```python
from core.continuum.decision_gate import (
    _THRESHOLD_HINT,    # 0.15
    _THRESHOLD_ASSIST,  # 0.40
    _THRESHOLD_EXECUTE, # 0.65
)
```

---

## Decision Confidence

`decision_confidence` measures how far the `should_act_score` is from the
nearest threshold boundary.  A score that sits comfortably in the middle of
an action-level band yields high confidence; a score near a boundary yields
low confidence.

```
confidence = clamp(min_distance_to_any_threshold / 0.125)
```

A distance of `0.125` (half the narrowest band) maps to `confidence = 1.0`.

---

## Output: `DecisionState`

```json
{
  "should_act_score": 0.47,
  "action_level": "assist",
  "decision_reason": "action_level=assist (score=0.470, value=0.612, interruption_cost=0.090, risk_cost=0.050); proactive partial engagement warranted",
  "decision_confidence": 0.72,
  "value_score": 0.612,
  "interruption_cost": 0.090,
  "risk_cost": 0.050,
  "timestamp": 1742302107.351
}
```

---

## Usage

```python
from core.continuum.decision_gate import DecisionGate
from core.continuum.types import UnifiedState, HumanFieldState

gate = DecisionGate()

state = UnifiedState(
    human=HumanFieldState(
        intent_probability=0.8,
        focus_level=0.4,
        interruption_sensitivity=0.3,
    ),
    context_utility=0.7,
    urgency=0.6,
    action_risk=0.2,
    uncertainty=0.25,
)
decision = gate.evaluate(state)
print(decision.action_level)        # assist
print(decision.should_act_score)    # ~0.47
print(decision.decision_confidence) # ~0.72
```

Per-call `timing_penalty` override:

```python
# Rush context — low timing penalty (less cost to interrupt)
decision = gate.evaluate(state, timing_penalty=0.1)
```

---

## Constraints

- No UI semantics.  `DecisionState` carries no widget, page, or view fields.
- All numeric outputs are bounded in `[0, 1]`.
- The engine is **stateless**: history, trends, and smoothing are the
  responsibility of upstream engines (e.g. `TemporalEngine`).
- Uses `core/continuum/config.py` (`ContinuumConfig`) for runtime
  configuration.

---

# Return-to-Formless Engine — Specification

The **Return Engine** (`core/continuum/return_engine.py`) determines whether
the continuum should retreat from its current phase back toward silence.  Like
the Decision Gate, it is stateless: each call produces a fresh
[`ReturnResult`](../core/continuum/return_engine.py).

---

## Return Triggers

Triggers are evaluated in **priority order** (highest first).  The first
trigger that fires wins; lower-priority triggers are not evaluated.

| Priority | Trigger | Fires when | Default action |
|---|---|---|---|
| 1 | `user_cancel` | `user_cancel=True` | `return_to_formless` |
| 2 | `high_uncertainty` | `effective_uncertainty >= threshold` (default `0.85`) | `return_to_formless` |
| 3 | `finished` | `finished=True` | `step_down` |
| 4 | `timeout` | `elapsed_ms >= config.timeout_receding_ms` | `step_down` |
| 5 | `low_value` | `decision_score < threshold` (default `0.10`) | `soft_decay` |

`effective_uncertainty` is derived from `ContinuumState.stability`:

```
effective_uncertainty = clamp(1.0 - stability)
```

Low stability → high effective uncertainty.

---

## Return Actions

| Action | Phase change | Description |
|---|---|---|
| `hold` | none | Remain in current phase; monitor |
| `soft_decay` | none | Reduce `presence_intensity` by `decay_amount`; no phase change |
| `step_down` | current → next lower | `manifest → receding → formless` |
| `return_to_formless` | any → `formless` | Immediate hard return, bypasses intermediate steps |

### Phase step-down table

| Current phase | Next phase |
|---|---|
| `manifest` | `receding` |
| `receding` | `formless` |
| `liminal` | `formless` |
| `formless` | `formless` (no-op) |

---

## Output: `ReturnResult`

```json
{
  "should_return": true,
  "trigger": "low_value",
  "return_action": "soft_decay",
  "reason": "low_value: decision_score=0.042 < threshold=0.100",
  "next_phase": null,
  "decay_amount": 0.05
}
```

When `should_return=False`:

```json
{
  "should_return": false,
  "trigger": null,
  "return_action": "hold",
  "reason": "no trigger active (phase=manifest, elapsed_ms=1200, uncertainty=0.050)",
  "next_phase": null,
  "decay_amount": 0.0
}
```

---

## Usage

```python
from core.continuum.return_engine import ReturnEngine
from core.continuum.types import ContinuumPhase, ContinuumState

engine = ReturnEngine()
state = ContinuumState(phase=ContinuumPhase.MANIFEST, presence_intensity=0.7)

# Normal evaluation
result = engine.evaluate(state, elapsed_ms=6000)
if result.should_return:
    print(result.return_action, result.trigger)

# Force return (error path / shutdown)
result = engine.force_return(state)
assert result.return_action == "return_to_formless"
```

Integrate with the Decision Gate:

```python
from core.continuum.decision_gate import DecisionGate
from core.continuum.return_engine import ReturnEngine

gate = DecisionGate()
engine = ReturnEngine()

decision = gate.evaluate(unified_state)
result = engine.evaluate(
    continuum_state,
    elapsed_ms=elapsed,
    decision_score=decision.should_act_score,
)
```

---

## Configuration

Both engines read from `core/continuum/config.py`
([`ContinuumConfig`](../core/continuum/config.py)).

| Config field | Used by | Default | Effect |
|---|---|---|---|
| `timeout_receding_ms` | `ReturnEngine` | `5000` | Milliseconds before timeout trigger fires |
| `min_presence_formless` | `ReturnEngine` (context) | `0.05` | Presence floor for receding → formless snapping |

`ReturnEngine` additional constructor parameters:

| Parameter | Default | Description |
|---|---|---|
| `low_value_threshold` | `0.10` | Decision score below which `low_value` fires |
| `high_uncertainty_threshold` | `0.85` | Effective uncertainty above which `high_uncertainty` fires |
| `soft_decay_amount` | `0.05` | Presence reduction per `soft_decay` tick |

`DecisionGate` additional constructor parameters:

| Parameter | Default | Description |
|---|---|---|
| `timing_penalty` | `0.50` | Base timing penalty for interruption cost |

---

## Constraints

- No UI semantics.
- All numeric values bounded in `[0, 1]`.
- Backward compatible: new engines add no breaking changes to existing modules.
- Both engines are stateless; history and smoothing remain upstream.
- Config is read from `core/continuum/config.py` (`ContinuumConfig`).
