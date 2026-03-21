# EXECUTION_INTENT_PROFILE.md

## Execution Intent Profile — PR-22

### Why this profile exists

The Galaxy system already has:

- **Decision Gate** action levels (`observe` / `hint` / `assist` / `execute`)
- Decision-to-system-execution plumbing (`DecisionExecutor`)
- `RuntimeProjection` as a unified runtime snapshot
- Governance and execution-policy surfaces
- Read-only status-board surfaces consuming the runtime projection

However, before PR-22, **there was no single canonical object representing *what the system intends to execute*.**  Execution intent was scattered across:

- `state_continuum.metadata` (e.g. `execution_target`, `force_local_execution`)
- `DecisionGate` / `action_level` output
- `OpenClawd._run_execution()` inline logic
- Windows-side execution selection heuristics

This creates **drift risk** — different downstream modules infer intent independently and may disagree on target, scope, confidence, or safety constraints.

**PR-22 solves this** by introducing a focused, additive `ExecutionIntentProfile` contract layer that is built *once* from the available runtime signals and passed forward to execution, projection, and governance surfaces.

---

### Canonical fields

| Field | Type | Description |
|-------|------|-------------|
| `intent_id` | `str` | Unique UUID4 identifier for this intent instance |
| `runtime_session_id` | `str \| None` | Active runtime / OpenClawd session ID |
| `source` | `str` | Origin tag: `chat` / `openclawd` / `e2e` / `runtime` / custom |
| `action_level` | `str` | Graduated decision gate level: `observe` / `hint` / `assist` / `execute` |
| `intent_mode` | `str` | Normalised mode: `advisory` / `assistive` / `direct` / `autonomous` |
| `target_type` | `str \| None` | Target category: `app` / `window` / `url` / `device` / `command` |
| `target_ref` | `str \| None` | Specific target reference (app name, window title, device ID, …) |
| `target_payload` | `dict` | Auxiliary parameters for the target execution |
| `device_scope` | `str \| None` | Device scope: `local` / `remote` / `multi-device` |
| `runtime_domain` | `str \| None` | Runtime domain: `local` / `cross_device` / `transition` |
| `confidence` | `float` | Decision confidence score [0.0, 1.0] |
| `safety_constraints` | `list[str]` | Active safety constraint tags |
| `origin_state` | `str \| None` | Originating continuum phase (e.g. `manifest`, `liminal`) |
| `notes` | `str \| None` | Optional human-readable debug notes |
| `degrade_reason` | `str \| None` | Non-None when the intent was downgraded |

#### `intent_mode` mapping

| `action_level` | `intent_mode` |
|----------------|---------------|
| `observe` | `advisory` |
| `hint` | `advisory` |
| `assist` | `assistive` |
| `execute` | `direct` |

---

### How it is built from current runtime / decision signals

The primary entry-point is `build_execution_intent_profile()`:

```python
from core.execution.intent_profile import build_execution_intent_profile

profile = build_execution_intent_profile(
    state_continuum=continuum_dict,   # serialised ContinuumState dict
    runtime_session_id="sess-abc",
    source="openclawd",
    entry_mode="local",               # from ingress layer
)
```

Alternatively, use the class method:

```python
profile = ExecutionIntentProfile.from_state_continuum(
    state_continuum,
    runtime_session_id="sess-abc",
    source="chat",
)
```

The builder extracts the following from `state_continuum`:

| Profile field | Extracted from |
|--------------|----------------|
| `action_level` | `state_continuum["decision"]["action_level"]` |
| `confidence` | `state_continuum["decision"]["decision_confidence"]` |
| `target_ref` | `state_continuum["metadata"]["execution_target"]` or `assist_target` |
| `target_type` | `state_continuum["metadata"]["target_type"]` (or inferred) |
| `target_payload` | `state_continuum["metadata"]["target_payload"]` |
| `runtime_domain` | `state_continuum["runtime_domain"]` |
| `origin_state` | `state_continuum["phase"]` or `tri_state_phase` |
| `safety_constraints` | `state_continuum["metadata"]["safety_constraints"]` |

`device_scope` is derived from `entry_mode` when provided, otherwise inferred from `runtime_domain`.

**Graceful defaults** — all fields fall back to safe values when the input is `None` or partially missing.  The builder never raises.

---

### How downstream modules should consume it

#### Execution layer (`DecisionExecutor` / `_run_execution`)

`OpenClawd._run_execution()` builds the profile before dispatching to `DecisionExecutor`:

```python
# result dict now includes an additive "execution_intent" key
result = self._run_execution(state_continuum, entry_mode=entry_mode)
intent_summary = result.get("execution_intent")  # compact summary dict
```

Downstream code can inspect `execution_intent` for logging, audit, or policy purposes **without touching execution behaviour**.

#### Projection / governance surfaces

`build_runtime_projection()` accepts an optional `intent_profile` argument:

```python
from core.projection import build_runtime_projection
from core.execution.intent_profile import build_execution_intent_profile

profile = build_execution_intent_profile(state_continuum)
projection = build_runtime_projection(
    continuum_state,
    intent_profile=profile,
)
# projection.execution_intent_summary is now populated
payload = projection.to_dict()
# payload["execution_intent_summary"] contains the compact summary
```

Governance and debug consumers can read `execution_intent_summary` from `RuntimeProjection.to_dict()` without any additional plumbing.

#### Direct serialisation

```python
# Full profile dict
profile.to_dict()

# Compact governance/projection summary (10 key fields)
profile.compact_summary()

# JSON string
profile.to_json()
```

---

### What this PR does NOT do

This PR is intentionally narrow and additive:

- ❌ Does **not** replace readiness gating (PR-23)
- ❌ Does **not** implement fallback decision trace (PR-24)
- ❌ Does **not** create a full execution trace contract (PR-25)
- ❌ Does **not** overhaul projection assembly governance (PR-26)
- ❌ Does **not** implement a runtime governance snapshot (PR-27)
- ❌ Does **not** add a policy alignment surface (PR-28)
- ❌ Does **not** rewrite or refactor `DecisionExecutor`
- ❌ Does **not** change any existing execution behaviour
- ❌ Does **not** add new API endpoints (the profile is surfaced read-only via `RuntimeProjection.to_dict()`)

Those capabilities will be built on top of this profile in later PRs.

---

### Module locations

| File | Role |
|------|------|
| `core/execution/intent_profile.py` | `ExecutionIntentProfile` model, `IntentMode` constants, `build_execution_intent_profile()` builder |
| `core/execution/__init__.py` | Re-exports `ExecutionIntentProfile`, `IntentMode`, `build_execution_intent_profile` |
| `core/openclawd.py` | `_run_execution()` builds and attaches profile; `_build_intent_profile()` helper |
| `core/projection/runtime_projection.py` | Additive `execution_intent_summary` field |
| `core/projection/projection_compiler.py` | `build_runtime_projection()` accepts optional `intent_profile` |
| `docs/EXECUTION_INTENT_PROFILE.md` | This document |
| `tests/test_pr22_execution_intent_profile.py` | Focused tests |
