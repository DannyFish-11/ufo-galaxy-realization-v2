# Manifest Stage (显现台)

> **PR-6** — builds on the Liminal Projection Engine (PR-5) and RuntimeProjection (PR-3).

---

## Overview

The **Manifest Stage** (显现台, *xiǎn xiàn tái*) is the final projection surface in the
`silent → liminal → manifest` desktop expansion sequence.  It renders the execution
flow and model/device routing information as a read-only display surface, driven
exclusively by:

1. **`RuntimeProjection`** — the unified projection contract produced by the server.
2. **`LiminalSpaceState`** — the spatial descriptor produced by PR-5's
   `StateSpaceMapper` from the same `RuntimeProjection`.

The manifest surface is a *natural continuation* of the liminal state.  It never
appears abruptly — it waits until the liminal field (`ambient_intensity`) crosses a
readiness threshold before marking itself as active.

---

## Architecture

```
RuntimeProjection
       │
       ├──► StateSpaceMapper ──► LiminalSpaceState
       │                               │
       └───────────────────────────────┤
                                       ▼
                          ManifestStageController
                                       │
                                       ▼
                          ManifestStageState (显现台)
                                       │
                                       ▼
                          ManifestSurface (Status Board V2)
```

### Module Structure

```
desktop_projection/
├── __init__.py                      # Public surface (updated)
├── state_space_mapper.py            # RuntimeProjection → LiminalSpaceState  (PR-5)
├── liminal_space_engine.py          # Stateful liminal coordinator             (PR-5)
├── transition_animator.py           # Easing curves + interpolation frames     (PR-5)
├── manifest_stage_state.py          # ManifestStageState dataclass             (PR-6)
└── manifest_stage_controller.py     # ManifestStageController                  (PR-6)

windows_client/status_board_v2/
├── manifest_surface.py              # Read-only manifest panel                 (PR-6)
└── app.py                           # Updated: includes ManifestSurface        (PR-6)

docs/
└── MANIFEST_STAGE.md                # This document                            (PR-6)

tests/
└── test_pr6_manifest_stage.py       # Tests                                    (PR-6)
```

---

## How Manifest Stage is Derived

### Step 1 — RuntimeProjection fields

The `ManifestStageController` reads the following fields from a `RuntimeProjection`
dict (or object):

| Field | Purpose |
|-------|---------|
| `tri_state_phase` | Source phase label (`silent` / `liminal` / `manifest`) |
| `coherence` | Degree of intent coherence [0, 1] |
| `collapse_tendency` | Probability mass pushing toward manifest [0, 1] |
| `retreat_tendency` | Probability mass pushing toward retreat [0, 1] |
| `primary_model_id` | Top-ranked routed model |
| `support_model_ids` | Supporting model list |
| `active_device_ids` | Devices in execution |
| `active_weights` | Model weight map |
| `route_reason` | Routing rationale string |
| `current_task_summary` | Task description |
| `execution_stage` | Lifecycle stage label |

### Step 2 — LiminalSpaceState fields

The `LiminalSpaceState` (output of PR-5's `StateSpaceMapper`) contributes:

| Field | Purpose in manifest stage |
|-------|--------------------------|
| `ambient_intensity` | Drives `focus_intensity` and `stage_ready` threshold |

### Step 3 — focus_intensity

```
focus = sqrt(max(ambient, 0) * max(coherence, 0))  +  0.15 * collapse_tendency
focus = clamp(focus, 0.0, 1.0)
```

This ensures that focus is only high when *both* the liminal ambient field is active
*and* the system has coherent intent.  The small nudge from `collapse_tendency`
reflects the drive toward manifestation.

### Step 4 — stage_ready

```python
stage_ready = (ambient_intensity >= STAGE_READY_THRESHOLD) and (retreat_tendency < RETREAT_SOFTENING_THRESHOLD)
```

Default thresholds:

| Constant | Value | Meaning |
|----------|-------|---------|
| `STAGE_READY_THRESHOLD` | `0.35` | Minimum ambient for stage activation |
| `RETREAT_SOFTENING_THRESHOLD` | `0.50` | Retreat level that suppresses stage_ready |

---

## Connection to Liminal Projection

The manifest stage is *downstream* of the liminal projection — it can only activate
when the liminal field is sufficiently warm (`ambient_intensity >= 0.35`).

### Smooth transition policy

The `ManifestStageController` holds the previous `ManifestStageState`.  When
`retreat_tendency` is high (≥ 0.5), the controller blends `focus_intensity`
toward the previous value instead of jumping:

```python
focus = prev_focus * retreat_blend + raw_focus * (1 - retreat_blend)
# Default retreat_blend = 0.7
```

This prevents the manifest surface from flickering when the system momentarily
retreats.

---

## What is Rendered in the Manifest Surface

`ManifestSurface` (read-only, no command inputs) displays:

| Row | Content |
|-----|---------|
| **Phase / Status** | Current tri-state phase + `● READY` or `○ HOLD` indicator |
| **Focus** | ASCII bar + numeric value of `focus_intensity` |
| **Stage** | `execution_stage` label |
| **Task** | `task_summary` (truncated to fit) |
| **Primary** | `primary_model_id` (green if set) |
| **Support** | `support_model_ids` (cyan) |
| **Weights** | Top-N `active_weights` as ASCII bar chart (primary starred ★) |
| **Devices** | `active_device_ids` |
| **Reason** | `route_reason` rationale (grey, truncated) |

Example output (ANSI colours not shown):

```
  ┌─ Manifest Stage (显现台) ────────────────────────┐
  │  Phase    : manifest   Status: ● READY
  │  Focus    : [████████████░░░░]  0.762
  │  Stage    : executing
  │  Task     : Summarise the Q3 earnings report
  │  Primary  : gpt-4o
  │  Support  : claude-3
  │  Weights :
  │   ★ [███████████████░]  gpt-4o
  │     [████████████░░░░]  claude-3
  │  Devices  : desktop-win
  │  Reason   : native preferred
  └─────────────────────────────────────────────────┘
```

---

## Read-Only Guarantee

`ManifestSurface` and `ManifestStageController` never:
- Accept chat input
- Send commands to any subsystem
- Modify any state outside the controller's own `previous_state` cache

All execution remains in `windows_aip_client.py → WindowsExecutionArbiter.route_command()`.

---

## Related Documents

- [`docs/LIMINAL_PROJECTION_ENGINE.md`](LIMINAL_PROJECTION_ENGINE.md) — PR-5 liminal layer
- [`desktop_projection/manifest_stage_state.py`](../desktop_projection/manifest_stage_state.py)
- [`desktop_projection/manifest_stage_controller.py`](../desktop_projection/manifest_stage_controller.py)
- [`windows_client/status_board_v2/manifest_surface.py`](../windows_client/status_board_v2/manifest_surface.py)
- [`tests/test_pr6_manifest_stage.py`](../tests/test_pr6_manifest_stage.py)
