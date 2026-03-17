# PersonaState — Persona / Spirit Engine (PR-3)

> **Module path**: `core/persona/`  
> **Schema**: `core/schemas/persona_state.py`  
> **Tests**: `tests/test_persona.py`

---

## Overview

The Persona / Spirit Engine adds a lightweight **affective state layer** to OpenClawd.  
It tracks how the agent's mood, energy, focus, and other qualitative signals evolve  
across a session based on message sentiment, interaction mode, and task outcomes.

The layer is **purely additive**: existing callers receive a new `persona_state` key in  
every `OpenClawd.process()` response, while `response.response` remains unchanged.

---

## PersonaState Schema

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `session_id` | `str` | `"__global__"` | Session this state belongs to |
| `mood` | `str` | `"calm"` | Qualitative mood label (calm / focused / concerned / tired / warm) |
| `energy` | `float [0,1]` | `0.6` | Processing / engagement energy |
| `focus` | `float [0,1]` | `0.7` | Task focus sharpness |
| `curiosity` | `float [0,1]` | `0.5` | Drive to explore / ask follow-ups |
| `urgency` | `float [0,1]` | `0.1` | Perceived time-pressure or criticality |
| `trust_level` | `float [0,1]` | `0.5` | Accumulated trust from session history |
| `expression_mode` | `str` | `"quiet_luminous"` | Surface style hint for UI / voice layers |
| `updated_at` | `datetime` | now (UTC) | Timestamp of last mutation |

All numeric fields are clipped to `[0.0, 1.0]` after every update.

```python
from core.schemas.persona_state import PersonaState

state = PersonaState.default_baseline("sess_abc")
print(state.to_dict())
# {
#   "session_id": "sess_abc",
#   "mood": "calm",
#   "energy": 0.6,
#   "focus": 0.7,
#   "curiosity": 0.5,
#   "urgency": 0.1,
#   "trust_level": 0.5,
#   "expression_mode": "quiet_luminous",
#   "updated_at": "2026-03-17T05:00:00+00:00"
# }
```

---

## Module Structure

```
core/
  persona/
    __init__.py
    persona_rules.py     # keyword lists + delta constants + mood/expression derivation
    emotion_engine.py    # EmotionEngine: compute_delta() + apply_delta()
    state_store.py       # StateStore: get_state() + update_state() + reset_state()
  schemas/
    persona_state.py     # PersonaState dataclass + _clip() helper
```

---

## EmotionEngine — Update Rules

All updates are **rule-based, no model calls**.

| Trigger | Affected Fields | Delta |
|---------|-----------------|-------|
| Gratitude keywords (谢谢 / thanks / awesome …) | `trust_level` | +0.10 |
| Frustration keywords (错误 / crash / wrong …) | `urgency`, `energy` | +0.15, −0.10 |
| Curiosity keywords (为什么 / why / how …) | `curiosity` | +0.08 |
| Urgency keywords (紧急 / urgent / asap …) | `urgency`, `energy` | +0.15, +0.10 |
| Message length ≥ 80 chars | `focus` | +0.08 |
| Message length ≤ 10 chars | `energy` | −0.03 |
| `interaction_mode == CONTROL_CONSOLE` | `focus`, `urgency` | +0.10, +0.05 |
| `interaction_mode == AMBIENT_COMPANION` | `energy` | +0.05 |
| `task_success == True` | `trust_level`, `energy` | +0.05, +0.08 |
| `task_success == False` | `urgency`, `energy` | +0.20, −0.12 |
| `task_success == False` + `CONTROL_CONSOLE` | `mood` override | `"focused"` |

After every numeric update, **mood** and **expression_mode** are automatically  
re-derived from the current numeric values using the priority rules below.

### Mood derivation priority

1. `urgency > 0.6` → `"concerned"`
2. `focus > 0.8` → `"focused"`
3. `energy < 0.35` → `"tired"`
4. `trust_level > 0.75` → `"warm"`
5. default → `"calm"`

---

## StateStore

```python
from core.persona.state_store import get_state_store

store = get_state_store()

# Read current state
state = store.get_state("sess_xyz")

# Update after processing a request
updated_state, delta = store.update_state(
    "sess_xyz",
    message="这个脚本崩溃了",
    interaction_mode="control_console",
    task_success=False,
)
print(updated_state.mood)          # "concerned"
print(updated_state.urgency)       # ≥ 0.35 (baseline 0.1 + CONTROL_CONSOLE + task_failure)

# Reset to baseline
store.reset_state("sess_xyz")
```

---

## OpenClawd Integration

`OpenClawd.process()` now includes `persona_state` in every response:

```json
{
  "success": true,
  "response": "...",
  "intent": "chat",
  "trace_id": "...",
  "interaction": { ... },
  "persona_state": {
    "session_id": "sess_abc",
    "mood": "calm",
    "energy": 0.65,
    "focus": 0.72,
    "curiosity": 0.58,
    "urgency": 0.12,
    "trust_level": 0.55,
    "expression_mode": "quiet_luminous",
    "updated_at": "2026-03-17T05:01:23+00:00"
  },
  "metadata": { ... }
}
```

The field is `null` only if the entire persona subsystem raises an unhandled  
exception (which is caught and logged at DEBUG level).  
`response.response` is **never modified** by the persona layer.

---

## EventBus

The store emits `EventType.PERSONA_STATE_UPDATED` after every successful update:

```python
{
  "event_type": "PERSONA_STATE_UPDATED",
  "source": "persona_state_store",
  "data": {
    "session_id": "sess_abc",
    "delta": { "trust_level": 0.1, "energy": 0.08 },
    "state": { ... }   # full PersonaState.to_dict()
  }
}
```

Subscribers can react to persona shifts for UI adaptation, avatar animation, or logging.

---

## Constraints

* No external dependencies (stdlib + existing codebase only).
* No LLM calls — all rules are deterministic keyword / threshold checks.
* State is in-memory only; lost on process restart.
* Minimal changes outside `core/persona/` and `core/openclawd.py`.
