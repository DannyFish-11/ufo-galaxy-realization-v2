# Return Intelligence Formalization (PR-10)

> **Status:** V3 formalization/consolidation step.  
> **Builds on:** PR #264 (Orchestration Authority Consolidation), PR-6 (Manifest Stage), PR-5 (Liminal Projection Engine), PR-3 (Runtime Projection).

---

## Overview

This document describes the **return intelligence layer** added in PR-10.  The goal is to make existing return/receding intelligence coherent, additive, and easy for downstream systems to consume — without replacing or renaming any existing continuum engine contracts.

### What existed before this PR

| Existing artifact | Location | Role |
|---|---|---|
| `ReturnTrigger` enum | `core/continuum/return_engine.py` | Internal trigger labels (`finished`, `timeout`, `low_value`, `high_uncertainty`, `user_cancel`) |
| `ReturnAction` enum | `core/continuum/return_engine.py` | Internal action labels (`hold`, `soft_decay`, `step_down`, `return_to_formless`) |
| `ReturnResult` dataclass | `core/continuum/return_engine.py` | Immutable output of `ReturnEngine.evaluate()` |
| `ReturnEngine` | `core/continuum/return_engine.py` | Stateless engine; determines whether/how to retreat |
| `ContinuumPhase.RECEDING` | `core/continuum/types.py` | Internal phase; collapses to `silent` publicly |
| `collapse_tendency` / `retreat_tendency` | `core/projection/runtime_projection.py` | Scalar tendency fields on `RuntimeProjection` |

### What this PR adds

| New artifact | Location | Role |
|---|---|---|
| `ReturnMode` enum | `core/return_intelligence/return_modes.py` | Public-safe mode labels for downstream consumers |
| `ReturnSummary` dataclass | `core/return_intelligence/return_summary.py` | Stable, serialisable public summary |
| `IDLE_RETURN_SUMMARY` constant | `core/return_intelligence/return_summary.py` | Safe default for non-returning states |
| `build_return_summary()` | `core/return_intelligence/return_projection_adapter.py` | Converts `ReturnResult` → `ReturnSummary` |
| `attach_return_summary()` | `core/return_intelligence/return_projection_adapter.py` | Attaches summary to projection dict additively |
| `get_return_hints()` | `core/return_intelligence/return_projection_adapter.py` | Quick boolean hint dict for surface controllers |
| `ReturnSurface` | `windows_client/status_board_v2/return_surface.py` | Read-only Status Board V2 panel |
| `GET /api/v1/projection/return` | `core/routes/projection.py` | Read-only endpoint: RuntimeProjection + return intelligence |

---

## Core design rule: `receding` stays internal

`ContinuumPhase.RECEDING` is an **internal return mechanism**.  External consumers must never see it as a public state.

```
Internal (ContinuumPhase)       Public (TriStatePhase)
─────────────────────────       ──────────────────────
formless   ─────────────────→   silent
liminal    ─────────────────→   liminal
manifest   ─────────────────→   manifest
receding   ─────────────────→   silent   ← collapsed, never exposed
```

Return intelligence is surfaced through `ReturnSummary`, not through exposing `receding` as a state.

---

## The `ReturnMode` enum (public-safe)

`ReturnMode` belongs to the **projection/intelligence layer**, not the continuum engine.  It mirrors `ReturnAction` values but adds `NONE` to represent "no return active".

| ReturnMode | Meaning |
|---|---|
| `none` | No return is active; the system is progressing forward |
| `hold` | Engine recommends staying in current phase with no change |
| `soft_decay` | Gently reduce presence intensity; no phase transition |
| `step_down` | Step down one phase level (manifest → liminal → silent) |
| `return_to_formless` | Immediate hard reset to formless/silent base state |

### Influence on downstream surfaces

| ReturnMode | `affects_manifest` | `affects_liminal` |
|---|---|---|
| `none` | ✗ | ✗ |
| `hold` | ✗ | ✗ |
| `soft_decay` | ✗ | ✓ softened |
| `step_down` | ✓ suppressed | ✓ softened |
| `return_to_formless` | ✓ suppressed | ✓ softened |

---

## The `ReturnSummary` dataclass

```python
@dataclass(frozen=True)
class ReturnSummary:
    is_returning: bool = False
    return_mode: ReturnMode = ReturnMode.NONE
    return_action: Optional[str] = None       # raw ReturnAction string
    return_trigger: Optional[str] = None      # raw ReturnTrigger string
    decay_amount: float = 0.0
    reason: str = "no return active"
    affects_manifest: bool = False
    affects_liminal: bool = False
```

### Key invariants

- `is_returning` is `True` only when the engine's `should_return` was `True`.
- `return_mode` is `ReturnMode.NONE` when `is_returning` is `False`.
- `affects_manifest` is `True` only for `step_down` and `return_to_formless`.
- `affects_liminal` is `True` for `soft_decay`, `step_down`, and `return_to_formless`.
- `receding` never appears in any field.

### Serialisation

```python
summary.to_dict()
# {
#   "is_returning": True,
#   "return_mode": "step_down",
#   "return_action": "step_down",
#   "return_trigger": "finished",
#   "decay_amount": 0.0,
#   "reason": "finished: normal completion, stepping down manifest → receding",
#   "affects_manifest": True,
#   "affects_liminal": True
# }
```

---

## Adapters

### `build_return_summary(result)`

```python
from core.return_intelligence import build_return_summary
from core.continuum.return_engine import ReturnEngine
from core.continuum.types import ContinuumState, ContinuumPhase

engine = ReturnEngine()
state = ContinuumState(phase=ContinuumPhase.MANIFEST, presence_intensity=0.7)
result = engine.evaluate(state, finished=True)

summary = build_return_summary(result)
print(summary.return_mode)   # ReturnMode.STEP_DOWN
print(summary.is_returning)  # True
print(summary.affects_manifest)  # True
```

`None` input returns `IDLE_RETURN_SUMMARY` (safe default).

### `attach_return_summary(projection_dict, summary)`

Attaches a `ReturnSummary` to any `RuntimeProjection`-compatible dict **additively** — the original dict is not modified.

```python
from core.return_intelligence import attach_return_summary

enriched = attach_return_summary(projection.to_dict(), summary)
# enriched["return_intelligence"]["is_returning"] → bool
# enriched["tri_state_phase"] → unchanged (backward compatible)
```

### `get_return_hints(summary)`

Returns a compact hint dict for surface controllers that only need quick boolean checks.

```python
from core.return_intelligence import get_return_hints

hints = get_return_hints(summary)
# {
#   "is_returning": True,
#   "suppresses_manifest": True,
#   "softens_liminal": True,
#   "decay_amount": 0.0,
#   "return_mode": "step_down"
# }
```

---

## API endpoint: `GET /api/v1/projection/return`

Returns the current `RuntimeProjection` enriched with return intelligence.  All standard projection fields are unchanged; a `return_intelligence` key is added additively.

```json
{
  "tri_state_phase": "manifest",
  "runtime_domain": "local",
  "presence_intensity": 0.72,
  "coherence": 0.61,
  "collapse_tendency": 0.45,
  "retreat_tendency": 0.18,
  "...",
  "return_intelligence": {
    "is_returning": false,
    "return_mode": "none",
    "return_action": null,
    "return_trigger": null,
    "decay_amount": 0.0,
    "reason": "no trigger active (phase=manifest, elapsed_ms=0, uncertainty=0.280)",
    "affects_manifest": false,
    "affects_liminal": false
  }
}
```

The existing `GET /api/v1/projection/runtime` endpoint is **unchanged**.

---

## Status Board V2 integration: `ReturnSurface`

`ReturnSurface` is a new **read-only** panel added to the Status Board V2 render loop.  It reads the `return_intelligence` key from the projection payload.

```
  ┌─ Return Intelligence ───────────────────────────┐
  │  Mode     : idle   · idle
  │  Trigger  : (none)
  │  Decay    : —
  │  Manifest : ✓ normal
  │  Liminal  : ✓ normal
  │  Reason   : no trigger active (phase=silent, ...)
  └─────────────────────────────────────────────────┘
```

When a return is active:

```
  ┌─ Return Intelligence ───────────────────────────┐
  │  Mode     : step down ↓   ↩ RETURNING
  │  Trigger  : finished
  │  Decay    : —
  │  Manifest : ⚑ suppressed
  │  Liminal  : ⚑ softened
  │  Reason   : finished: normal completion, stepping down...
  └─────────────────────────────────────────────────┘
```

The surface degrades gracefully: when `return_intelligence` is absent from the payload (older server) it renders an idle state without error.

---

## Relationship to existing docs and layers

| Layer | Relationship to return intelligence |
|---|---|
| `docs/DECISION_GATE_SPEC.md` | Describes `ReturnEngine` inputs (e.g. `decision_score`). `ReturnSummary` is derived from `ReturnResult` produced by that engine. |
| `docs/MANIFEST_STAGE.md` | `retreat_tendency` already softens `stage_ready`. `return_intelligence.affects_manifest` provides a higher-level, reason-bearing complement. |
| `docs/LIMINAL_PROJECTION_ENGINE.md` | `retreat_tendency` already softens liminal ambient. `affects_liminal` provides a structured return-reason for the same softening. |
| `docs/RUNTIME_PROJECTION.md` | `RuntimeProjection` fields are unchanged. Return intelligence is additive under `return_intelligence`. |
| `docs/STATUS_BOARD_V2.md` | `ReturnSurface` is a new panel; no existing surfaces are modified. |

---

## How to consume return intelligence downstream

### Pattern 1: Surface controller (Manifest/Liminal)

```python
from core.return_intelligence import build_return_summary, get_return_hints
from core.continuum.return_engine import ReturnEngine

engine = ReturnEngine()
result = engine.evaluate(continuum_state, elapsed_ms=elapsed)
summary = build_return_summary(result)
hints = get_return_hints(summary)

if hints["suppresses_manifest"]:
    # Override stage_ready to False
    ...
if hints["softens_liminal"]:
    # Apply additional decay to ambient_intensity
    ...
```

### Pattern 2: Enriched projection endpoint

The `GET /api/v1/projection/return` endpoint provides return intelligence pre-attached.  Consume it the same as the standard projection endpoint:

```python
import httpx
resp = httpx.get("http://localhost:8000/api/v1/projection/return")
payload = resp.json()
ri = payload["return_intelligence"]
print(ri["return_mode"], ri["is_returning"])
```

### Pattern 3: Status Board V2

No changes needed in downstream status-board consumers.  `ReturnSurface` reads `projection["return_intelligence"]` automatically.

---

## What this PR does NOT do

- **Does not rename** any existing `ReturnEngine`, `ReturnTrigger`, `ReturnAction`, or `ReturnResult` symbols.
- **Does not modify** `RuntimeProjection` fields (`collapse_tendency`, `retreat_tendency` remain unchanged).
- **Does not expose** `receding` as a public phase anywhere.
- **Does not add command inputs** to any surface.
- **Does not replace** the manifest stage softening logic (that logic uses `retreat_tendency` directly; this PR adds a complement, not a replacement).
