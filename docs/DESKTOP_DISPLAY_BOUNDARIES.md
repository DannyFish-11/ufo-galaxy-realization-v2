# Desktop Display Boundaries

> **Canonical architectural contract** — this document is the authoritative
> definition of what belongs on each display layer of the Galaxy desktop
> runtime.  All surfaces, docs, and tests must conform to this contract.

---

## Overview

The Galaxy desktop shell contains two distinct display regions:

| Region | Role |
|--------|------|
| **Right-side desktop status board** (`status_board_v2/`) | Structured information display layer |
| **Liminal middle-state space** | Spatial execution field for the tri-state transition layer |

These regions have **different responsibilities** and must not be conflated.
The boundary between them is intentional and architectural, not cosmetic.

---

## 1. Right-Side Desktop Status Board

### Purpose

The right-side desktop status board is the **canonical structured-information
display layer** for the Galaxy desktop shell.  It answers the operator question:

> *"What is the system currently doing, and why?"*

### Content classes

The status board is the correct and only place for:

| Content class | Example fields |
|---------------|---------------|
| **Model / routing information** | `primary_model_id`, `support_model_ids`, `active_weights`, `route_reason` |
| **Provider / vendor and OneAPI status** | provider health, supply state, OneAPI gateway status |
| **Primary / support model topology** | weight bars, topology graph |
| **System state and execution summary** | `execution_stage`, `current_task_summary`, tri-state phase label |
| **Device / task / metrics information** | `active_device_ids`, `presence_intensity`, `coherence`, `collapse_tendency`, `retreat_tendency` |

### Projection contract

The status board **consumes** the canonical
`contracts.desktop_status_projection.DesktopStatusProjection` contract, which
is **produced** by `DesktopPresenceRuntime.build_desktop_status_projection()`.

```
DesktopPresenceRuntime (shell)
  └── build_desktop_status_projection(unified_control_plan, source_registry)
        │
        ▼
  DesktopStatusProjection   ← right-side board reads from here
    ├── PerceptionProjection      (ingress / modalities)
    ├── ModelRoutingProjection    (provider / model / route)
    ├── ExecutionProjection       (path / remote-mode / devices)
    ├── LifecycleProjection       (stage / health)
    └── ExplainabilityProjection  (fallback / diagnostics)
```

### Active surfaces

These `status_board_v2/` sub-surfaces all belong to the right-side board:

- `phase_surface.py` — tri-state phase label
- `domain_surface.py` — runtime domain
- `topology_surface.py` — model topology and weight bars
- `device_surface.py` — device IDs and execution context
- `metrics_surface.py` — presence / coherence / tendency metrics
- `return_surface.py` — return-intelligence surface

### Authority references

- `core/ui_surface_authority.py` — registers `status_board_v2/` as
  `PROJECTION_DRIVEN` / `ACTIVE_DESKTOP_STATUS`
- `core/repo_layout_registry.py` — classifies as `ACTIVE_DESKTOP_STATUS`
- `contracts/desktop_status_projection.py` — canonical projection contract
- `core/routes/` — `GET /api/v1/projection/runtime` endpoint

---

## 2. Liminal Middle-State Space

### Purpose

The liminal space is a **spatial execution field** — not a second status board.
It represents the middle transition layer of the tri-state lifecycle
(`silent → liminal → manifest`) and carries only execution-field semantics.

> **Key principle:** Liminal space is not a display area for system
> information.  It is a spatial field that reflects the *execution dynamics*
> of the current transition.

### Permitted content — exactly three categories

The liminal space must carry **only** these three categories:

| Category | Description |
|----------|-------------|
| **Local execution chain** | The on-device execution chain (local branch of the subject loop) |
| **Cross-device execution chain** | The distributed multi-device execution chain |
| **Sandbox simulation / speculative execution field** | Simulation, speculative or sandbox execution fields |

### Projection contract

The liminal surface **consumes** `core.projection.runtime_projection.RuntimeProjection`
(the same projection used by all surfaces) but derives **spatial dimensions**
from it via `desktop_projection.StateSpaceMapper` — not structured display
fields:

```
RuntimeProjection  →  StateSpaceMapper  →  LiminalSpaceState
                                               ├── depth_factor
                                               ├── topology_visibility
                                               ├── domain_path_emphasis
                                               └── ambient_intensity
```

The liminal space does **not** consume `DesktopStatusProjection` directly.

### Active surfaces

- `liminal_surface.py` — spatial field dimensions (depth, topology visibility,
  domain path emphasis, ambient intensity)
- `manifest_surface.py` — manifest-stage surface that emerges from the liminal
  field (execution context: which models are routing, which devices are active)

The manifest surface sits at the **boundary** between liminal and manifest
states.  Its content (model routing, device IDs, execution stage) is
execution-context data derived from the liminal field's transition into the
manifest phase — it is not a provider panel or metrics dashboard.

---

## 3. What "Manifest" Means Relative to Both Layers

`manifest` is the third tri-state phase (`silent → liminal → manifest`).  It
means the subject has fully committed to an execution context and is actively
producing output or controlling devices.

- **In the status board context**, `manifest` appears as a phase label in
  `phase_surface.py`.
- **In the liminal-space context**, `manifest_surface.py` renders the
  execution-context state that the liminal field has crystallised into.

The manifest surface is **not** a second status board.  It shows execution
focus (focus intensity, active stage, route reason) — fields that describe
*where the execution field landed*, not a general system information panel.

---

## 4. Prohibited Crossovers

The following content classes must **never** appear in the liminal space:

| Prohibited content class | Why it is prohibited |
|--------------------------|----------------------|
| Provider list cards | Provider information belongs to the status board's `ModelRoutingProjection` / `PerceptionProjection` |
| Dashboard-style model panels | Dashboard UI elements belong in `dashboard/` (legacy) or the status board, never in liminal space |
| Full metrics / status-board panels | Metrics belong to `metrics_surface.py` on the status board |
| Generic operator information blocks | Operator-facing structured info belongs to the status board |

Similarly, the right-side status board must **not** render execution-field
spatial dimensions (depth, ambient intensity, domain path emphasis) as primary
panels — those are liminal-space concerns.

---

## 5. Relationship to RuntimeProjection and DesktopStatusProjection

```
                          ┌─────────────────────┐
                          │  RuntimeProjection   │
                          │  (core/projection/)  │
                          └──────────┬──────────┘
                                     │ consumed by both layers
              ┌──────────────────────┴──────────────────────┐
              │                                             │
              ▼                                             ▼
  ┌───────────────────────────┐            ┌──────────────────────────────┐
  │ DesktopStatusProjection   │            │  StateSpaceMapper            │
  │ (contracts/)              │            │  (desktop_projection/)       │
  │                           │            │                              │
  │  RIGHT-SIDE STATUS BOARD  │            │  LiminalSpaceState           │
  │  ─ structured info        │            │  ─ spatial field dims        │
  │  ─ model routing          │            │  ─ depth / topology /        │
  │  ─ provider status        │            │    domain path / ambient     │
  │  ─ metrics / devices      │            │                              │
  └───────────────────────────┘            └──────────────────────────────┘
           consumed by:                              consumed by:
    phase_surface.py                         liminal_surface.py
    domain_surface.py                        manifest_surface.py
    topology_surface.py                      (spatial field only)
    device_surface.py
    metrics_surface.py
    return_surface.py
```

Key rules:
- `DesktopStatusProjection` is the **right-side board's** canonical contract.
- `StateSpaceMapper` / `LiminalSpaceState` are the **liminal space's** spatial
  contract.
- Neither layer introduces UI-state authority into projection modules.
- Projection modules (`core/projection/`, `contracts/`) are **read-only
  consumers** of runtime state — they do not write UI state or re-infer
  system structure.

---

## 6. Enforcement

These guardrails are encoded in `tests/test_display_boundary_guardrails.py`:

- Liminal surface rendering must not contain provider list / metrics board /
  dashboard-style content.
- Liminal surface rendering must contain only spatial-field labels.
- Right-side status board surfaces must not delegate execution-field spatial
  dimensions as primary content.
- `DesktopStatusProjection` sub-contracts must cover the right-side board
  content classes.
- `LiminalSpaceState` spatial dimensions must not overlap with
  `DesktopStatusProjection` information fields.

---

## 7. Summary

| Rule | Right-side status board | Liminal space |
|------|------------------------|---------------|
| Role | Structured information display | Spatial execution field |
| Canonical contract | `DesktopStatusProjection` | `LiminalSpaceState` (via `StateSpaceMapper`) |
| Content | Model routing, provider, metrics, devices | Local chain, cross-device chain, simulation |
| Prohibited | Execution-field spatial dimensions as primary panels | Provider cards, metrics boards, generic info blocks |
| Authority | `PROJECTION_DRIVEN` / `ACTIVE_DESKTOP_STATUS` | Spatial transition field only |
| Parallel authority | ❌ Must not introduce a second authority model | ❌ Must not become a second status board |
