# Gemini Rendering Integration Protocol

> Version: 1.0.0  
> Status: Normative  
> Applies to: any renderer that consumes `state_continuum` output from the Galaxy Continuum pipeline.

---

## 1. Purpose

This document defines the protocol that a Gemini-based renderer **must** implement when consuming the `state_continuum` state object produced by `ContinuumOrchestrator`.

Key guarantees:
- The renderer is **stateless with respect to decision logic**: it maps state to visual parameters and nothing else.
- All input values are bounded `[0, 1]`.
- The renderer **never** infers intent, alters state, or writes back to the bus.

---

## 2. Input: `response.state_continuum` Schema

Every response from `OpenClawd.process()` may carry an optional `state_continuum` field when `enable_continuum: true` is set in `config.json`.

### 2.1 Top-level envelope

```json
{
  "state_continuum": {
    "phase": "<string>",
    "presence_intensity": 0.0,
    "coherence": 0.0,
    "ambiguity": 0.0,
    "collapse_tendency": 0.0,
    "action_level": 0.0,
    "schema_version": 1,
    "tick_id": 0,
    "degrade_reason": null
  }
}
```

| Field                | Type            | Bounds   | Description |
|----------------------|-----------------|----------|-------------|
| `phase`              | string (enum)   | —        | Current continuum phase. One of: `emergence`, `liminal`, `resolution`, `collapse`, `idle`. |
| `presence_intensity` | float           | [0, 1]   | How strongly the system's "presence" is felt in the current moment. |
| `coherence`          | float           | [0, 1]   | Degree of internal state coherence. 1.0 = fully coherent. |
| `ambiguity`          | float           | [0, 1]   | Unresolved uncertainty in the current state. |
| `collapse_tendency`  | float           | [0, 1]   | Likelihood of transitioning to the `collapse` phase. |
| `action_level`       | float           | [0, 1]   | Readiness for outbound action. |
| `schema_version`     | integer         | ≥ 1      | Always `1` in this release. |
| `tick_id`            | integer         | ≥ 0      | Monotonically increasing tick counter. |
| `degrade_reason`     | string or null  | —        | Non-null when the orchestrator degraded gracefully (e.g. `"tick_budget_exceeded"`). |

### 2.2 Phase enumeration

| Phase          | Semantic meaning |
|----------------|------------------|
| `idle`         | No active session; system is quiescent. |
| `emergence`    | New input has arrived; context is forming. |
| `liminal`      | Transition state: the system is between two resolved states. |
| `resolution`   | Context is fully resolved; action or output is imminent. |
| `collapse`     | Uncertainty cannot be resolved; graceful fallback has been invoked. |

---

## 3. Mapping Guidance: State → Visual Parameters

The renderer translates `state_continuum` fields into visual parameters.  
**No threshold checks, branching logic, or secondary inference is permitted in the renderer.**  
All mappings are linear or monotone unless otherwise specified.

### 3.1 Required mappings

| `state_continuum` field | Suggested visual parameter | Mapping |
|-------------------------|---------------------------|---------|
| `presence_intensity`    | Glow / luminance overlay  | Linear: `luminance = presence_intensity` |
| `coherence`             | Edge sharpness / crispness | Linear: `sharpness = coherence` |
| `ambiguity`             | Blur / noise overlay      | Linear: `blur_amount = ambiguity` |
| `collapse_tendency`     | Desaturation / fade       | Linear: `saturation = 1.0 − collapse_tendency` |
| `action_level`          | Pulse rate / animation speed | Linear: `pulse_hz = action_level × max_hz` |
| `phase`                 | Palette / scene selection | One palette per phase (see §3.2) |

### 3.2 Phase → palette mapping

| Phase        | Suggested palette |
|--------------|------------------|
| `idle`       | Monochrome, low contrast |
| `emergence`  | Cool blue-green gradients, low luminance |
| `liminal`    | Shifting hue between emergence and resolution palettes |
| `resolution` | Warm amber-white, high contrast |
| `collapse`   | Desaturated grey-red, reduced animation |

### 3.3 Degraded state handling

When `degrade_reason` is non-null the renderer **must** display in the degraded visual style:
- Set `luminance = 0.3` (muted presence).
- Set `sharpness = 0.5` (partially coherent).
- Keep all other fields unchanged.
- Do **not** hide or blank the overlay — always show *something*.

---

## 4. Required Invariants

The following invariants are **normative** (enforced by renderer acceptance tests):

1. **No decision logic in renderer.**  
   The renderer must not contain `if phase == "collapse"` style branch logic that routes to different code paths.  
   Phase is an input to a lookup table only.

2. **Consume `state_continuum` only.**  
   The renderer must not read any other field of the response (e.g. `content`, `tool_calls`) to derive visual parameters.

3. **Values must be clamped to `[0, 1]`.**  
   The renderer must clamp any received float to `[0, 1]` before use, even if the schema guarantees the range, to guard against future schema extensions.

4. **Idempotent on identical input.**  
   Given the same `state_continuum` object twice the renderer must produce identical output.

5. **Schema-version forward compatibility.**  
   If `schema_version > 1` the renderer must apply all known mappings and ignore unknown fields.

6. **`tick_id` is informational only.**  
   The renderer must not use `tick_id` to compute velocity or delta between frames; that is the responsibility of the orchestrator.

---

## 5. Example Payloads

### 5.1 `idle` phase — quiescent system

```json
{
  "state_continuum": {
    "phase": "idle",
    "presence_intensity": 0.05,
    "coherence": 0.95,
    "ambiguity": 0.02,
    "collapse_tendency": 0.0,
    "action_level": 0.0,
    "schema_version": 1,
    "tick_id": 0,
    "degrade_reason": null
  }
}
```

Expected visual: near-black monochrome, very faint glow, crisp edges.

---

### 5.2 `emergence` phase — new input received

```json
{
  "state_continuum": {
    "phase": "emergence",
    "presence_intensity": 0.45,
    "coherence": 0.60,
    "ambiguity": 0.50,
    "collapse_tendency": 0.05,
    "action_level": 0.10,
    "schema_version": 1,
    "tick_id": 7,
    "degrade_reason": null
  }
}
```

Expected visual: cool blue-green palette, moderate glow, noticeable blur, slow pulse.

---

### 5.3 `liminal` phase — transition in progress

```json
{
  "state_continuum": {
    "phase": "liminal",
    "presence_intensity": 0.65,
    "coherence": 0.40,
    "ambiguity": 0.70,
    "collapse_tendency": 0.20,
    "action_level": 0.30,
    "schema_version": 1,
    "tick_id": 14,
    "degrade_reason": null
  }
}
```

Expected visual: hue shifting between cool and warm, high blur, moderate saturation, medium pulse.

---

### 5.4 `resolution` phase — output imminent

```json
{
  "state_continuum": {
    "phase": "resolution",
    "presence_intensity": 0.90,
    "coherence": 0.92,
    "ambiguity": 0.08,
    "collapse_tendency": 0.02,
    "action_level": 0.85,
    "schema_version": 1,
    "tick_id": 21,
    "degrade_reason": null
  }
}
```

Expected visual: warm amber-white palette, sharp edges, minimal blur, fast pulse.

---

### 5.5 `collapse` phase — graceful fallback

```json
{
  "state_continuum": {
    "phase": "collapse",
    "presence_intensity": 0.20,
    "coherence": 0.25,
    "ambiguity": 0.90,
    "collapse_tendency": 0.95,
    "action_level": 0.05,
    "schema_version": 1,
    "tick_id": 28,
    "degrade_reason": null
  }
}
```

Expected visual: desaturated grey-red palette, heavy blur, very slow or halted pulse.

---

### 5.6 Degraded tick — budget exceeded

```json
{
  "state_continuum": {
    "phase": "liminal",
    "presence_intensity": 0.50,
    "coherence": 0.50,
    "ambiguity": 0.50,
    "collapse_tendency": 0.10,
    "action_level": 0.10,
    "schema_version": 1,
    "tick_id": 35,
    "degrade_reason": "tick_budget_exceeded"
  }
}
```

Expected visual: degraded style — luminance clamped to 0.3, sharpness to 0.5, all other parameters as-received.

---

## 6. Renderer Acceptance Test Contract

A renderer implementation is considered compliant if it passes the following checks:

```python
def test_renderer_clamps_values(renderer, payload):
    # All float fields must be accepted when clamped to [0, 1]
    for k in ("presence_intensity", "coherence", "ambiguity",
              "collapse_tendency", "action_level"):
        payload["state_continuum"][k] = 1.5   # out of range
        result = renderer.render(payload["state_continuum"])
        assert result is not None              # must not raise or return None

def test_renderer_handles_all_phases(renderer):
    for phase in ("idle", "emergence", "liminal", "resolution", "collapse"):
        sc = {"phase": phase, "presence_intensity": 0.5,
              "coherence": 0.5, "ambiguity": 0.5,
              "collapse_tendency": 0.1, "action_level": 0.3,
              "schema_version": 1, "tick_id": 0, "degrade_reason": None}
        result = renderer.render(sc)
        assert result is not None

def test_renderer_idempotent(renderer, payload):
    r1 = renderer.render(payload["state_continuum"])
    r2 = renderer.render(payload["state_continuum"])
    assert r1 == r2

def test_renderer_degraded_state(renderer, payload):
    payload["state_continuum"]["degrade_reason"] = "tick_budget_exceeded"
    result = renderer.render(payload["state_continuum"])
    assert result["luminance"] == pytest.approx(0.3)
    assert result["sharpness"] == pytest.approx(0.5)
```

---

## 7. Changelog

| Version | Date       | Change |
|---------|------------|--------|
| 1.0.0   | 2026-03-18 | Initial normative specification. |
