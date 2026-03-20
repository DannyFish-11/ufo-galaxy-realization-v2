# Liminal Projection Engine

> **PR-5** — Builds on PR #259 (Status Board v2) and PR #258 (RuntimeProjection).

## Overview

The Liminal Projection Engine translates a
[`RuntimeProjection`](../core/projection/runtime_projection.py) into a
**spatial transition descriptor** that drives the desktop's "silent → liminal
→ manifest" expansion sequence.

It is **not** a graphics engine.  There are no GPU calls, no shader pipelines,
and no heavyweight UI frameworks.  Instead, it defines:

1. A mapping from `RuntimeProjection` fields to four normalised spatial
   dimensions (the `LiminalSpaceState`).
2. Smooth easing / interpolation between states (the `TransitionAnimator`).
3. A stateful coordinator that holds the current state and produces transition
   frames on each update (the `LiminalSpaceEngine`).
4. A read-only surface adapter for Status Board V2 (`LiminalSurface`).

---

## What Is Liminal Projection?

The OpenClawd continuum moves through three public states:

| Phase      | What is happening |
|------------|-------------------|
| `silent`   | Native multimodal ingress; minimal footprint; system is always alive but quiet |
| `liminal`  | Intent forming; the transition zone between local and cross-device; topology beginning to surface |
| `manifest` | Structure formed; execution underway; full spatial depth |

**Liminal projection** is the moment when the desktop surface begins to
_spatially_ respond to the system's internal state.  The four spatial
dimensions encode that response:

| Dimension | Meaning | Source |
|-----------|---------|--------|
| `depth_factor` | How "deep" the spatial projection is (0 = surface, 1 = full depth) | `tri_state_phase` + `collapse_tendency` |
| `topology_visibility` | How visible the model-topology layer is | max magnitude of `active_weights` |
| `domain_path_emphasis` | How prominently the runtime-domain path is shown | `runtime_domain` |
| `ambient_intensity` | Ambient field strength (geometric mean of `presence_intensity` × `coherence`) | `presence_intensity`, `coherence` |

---

## How RuntimeProjection Drives It

```
RuntimeProjection
│
├── tri_state_phase ──────────────┐
├── collapse_tendency ────────────┼──→ depth_factor
│
├── active_weights (max mag) ─────────→ topology_visibility
│
├── runtime_domain ───────────────────→ domain_path_emphasis
│
├── presence_intensity ───────────┐
└── coherence ────────────────────┴──→ ambient_intensity  (√(p × c))
```

The mapping is performed by
[`StateSpaceMapper.map()`](../desktop_projection/state_space_mapper.py) and
produces a [`LiminalSpaceState`](../desktop_projection/state_space_mapper.py).

### Depth factor detail

```
depth = phase_base + 0.25 × collapse_tendency
```

| Phase      | `phase_base` |
|------------|--------------|
| `silent`   | 0.05 |
| `liminal`  | 0.50 |
| `manifest` | 0.95 |

The `collapse_tendency` field nudges depth toward manifest even before the
phase formally crosses the threshold.  This produces a natural acceleration
into the manifest stage.

---

## Transition Timing

The [`TransitionAnimator`](../desktop_projection/transition_animator.py)
provides three easing curves:

| Curve | Formula | Best for |
|-------|---------|----------|
| `linear` | `t` | Debugging |
| `ease_in_out` | `3t² − 2t³` (smooth step / cubic Hermite) | `silent → liminal`, `liminal → manifest` |
| `ease_out` | `1 − (1 − t)²` | `manifest → liminal`, `liminal → silent` (retreat) |

When the caller does not specify a curve, the animator selects the recommended
one based on the detected `TransitionPhase` direction.

### Interpolation contract

`TransitionAnimator.interpolate(source, target, steps=N)` yields exactly `N`
frames.  The last frame is exactly the target state — there is no overshoot.
The first frame is the first step _away_ from the source.

This guarantees:

- No hard jumps at the start or end of any transition.
- A caller that renders all frames arrives at the correct final state.

---

## Module Structure

```
desktop_projection/
├── __init__.py                  # Public surface
├── state_space_mapper.py        # RuntimeProjection → LiminalSpaceState
├── liminal_space_engine.py      # Stateful coordinator
└── transition_animator.py       # Easing curves + interpolation frames

windows_client/status_board_v2/
└── liminal_surface.py           # Read-only text adapter for Status Board V2
```

---

## Integration: Status Board V2

`LiminalSurface` in
[`windows_client/status_board_v2/liminal_surface.py`](../windows_client/status_board_v2/liminal_surface.py)
is a read-only surface that renders the four liminal dimensions as ASCII bars.

It calls `StateSpaceMapper` internally on every render cycle, so it always
reflects the current projection without maintaining its own state cache.

Example output (in the Status Board V2 render loop):

```
  ┌─ Liminal Projection ─────────────────────────────┐
  │  Phase        : liminal  Domain: local
  │  Depth        : [█████████░░░░░░░░░░]  0.513
  │  Topology     : [████████████░░░░░░░]  0.650
  │  Domain Path  : [░░░░░░░░░░░░░░░░░░░]  0.000
  │  Ambient      : [████████░░░░░░░░░░░]  0.424
  └─────────────────────────────────────────────────┘
```

---

## How It Will Feed Manifest Stage (PR-6)

The manifest stage (PR-6) will consume `LiminalSpaceState.depth_factor` and
`topology_visibility` as its entry thresholds:

- When `depth_factor ≥ 0.85`, the manifest stage controller arms itself.
- When `topology_visibility ≥ 0.70`, the execution pipeline is allowed to
  surface in the manifest stage.

The `TransitionAnimator` frames produced by PR-5 will drive the collapse
animation as `depth_factor → 1.0` and `topology_visibility` convergences.

PR-6 will import directly from `desktop_projection`:

```python
from desktop_projection import LiminalSpaceEngine, LiminalSpaceState
```

and subscribe to engine updates rather than polling the RuntimeProjection
endpoint directly.

---

## Tests

Tests are in
[`tests/test_pr5_liminal_projection_engine.py`](../tests/test_pr5_liminal_projection_engine.py).

Coverage:

- `StateSpaceMapper` output for all `tri_state_phase` × `runtime_domain`
  combinations.
- Boundary conditions (silent/manifest extremes, None fields).
- `TransitionAnimator` interpolation stability and last-frame exactness.
- Easing curve monotonicity.
- `LiminalSpaceEngine` first-call behaviour and multi-update transitions.
- `LiminalSurface` render output.
