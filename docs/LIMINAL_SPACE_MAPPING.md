# Liminal Space Mapping — Canonical Definition

> **Version:** PR-5 (formalize-liminal-mapping)

---

## 1. What Is Liminal Space?

Liminal space is the **spatial execution field** of the Galaxy runtime.

It sits in the middle of the tri-state desktop lifecycle:

```
silent  →  liminal  →  manifest
```

This "middle" position does **not** mean it is a passive transition region.
Liminal space is an active, execution-bearing field.  It is the layer where
the runtime decides *how* an intent moves from silent (no presence) to
manifest (committed execution).

### Key principle

> Liminal space is where execution *happens*, not where system information
> is *displayed*.

It must never become a second status board.

---

## 2. What Liminal Space Is NOT

| Incorrect interpretation | Why it is wrong |
|--------------------------|-----------------|
| A second status board | Status-board information (model cards, provider panels, metrics) belongs exclusively on the right-side desktop status board. |
| A generic transition UI bucket | Generic transition visuals with weak architectural meaning are prohibited.  Every element must belong to one of the three allowed content classes. |
| A provider/model card display | Provider lists, vendor tags, and routing-authority panels are right-side board content. |
| A metrics or health panel | Presence intensity, coherence, collapse/retreat tendencies are right-side board fields. |
| A duplicate of any right-side panel | If a field already appears on the right-side status board, it must not be replicated in liminal space. |

---

## 3. Three Allowed Content Classes

Liminal space carries **exactly** these three categories:

### 3.1 Local Execution Chain

The on-device execution path.  Represents the six-step canonical chain from
`openclawd_dispatch` through to `openclawd_feedback` running entirely on the
local Windows desktop host.

**Spatial representation:** A sequential unfolding path — each step in the
chain advances the spatial field from left to right (or top to bottom in
text-mode rendering).  The field narrows at each commitment boundary and
widens as intermediate results propagate.

Sourced from: `core.local_execution_chain.LocalChainSnapshot`

### 3.2 Cross-Device Execution Chain

The distributed multi-device execution path.  Represents the seven-step
canonical chain from `openclawd_dispatch` through gateway substrate to remote
executors and back via result envelope merge.

**Spatial representation:** An expansion path — the field expands outward
from the local origin to remote nodes, then contracts back as results return.
Multiple concurrent device legs produce parallel field branches.

Sourced from: `core.cross_device_execution_chain.CrossDeviceChainSnapshot`

### 3.3 Sandbox Simulation / Speculative Execution Field

Simulated, speculative, or sandboxed execution branches.  Represents
hypothetical execution paths that have not yet been committed to either the
local or cross-device chains.

**Spatial representation:** A branching field — speculative branches diverge
from the main execution path and are visually distinguished from committed
execution (e.g., dimmed, annotated as simulation/speculative).

Sourced from: `core.liminal_space_mapping.SimulationSummary`

---

## 4. Relationship to Right-Side Status Board

The right-side desktop status board (`windows_client/status_board_v2/`) and
liminal space are **strictly separated** layers:

| Dimension | Right-side status board | Liminal space |
|-----------|------------------------|---------------|
| Content kind | Structured system information | Execution / simulation dynamics |
| Data source | `DesktopStatusProjection` | `LiminalSpaceMap` |
| Model/routing info | ✅ Yes | ❌ No |
| Provider/vendor panels | ✅ Yes | ❌ No |
| Metrics (presence, coherence) | ✅ Yes | ❌ No |
| Local execution chain | ❌ No | ✅ Yes |
| Cross-device chain | ❌ No | ✅ Yes |
| Sandbox/simulation field | ❌ No | ✅ Yes |
| Execution-field spatial dims | Summary only | Full representation |

The separation is enforced by:
- `docs/DESKTOP_DISPLAY_BOUNDARIES.md` — boundary contract
- `windows_client/status_board_v2/ACTIVE_SURFACE.md` — surface authority
- `core/liminal_space_mapping.py` — structural separation at code level

---

## 5. Relationship to Manifest State

The manifest surface (`windows_client/status_board_v2/manifest_surface.py`)
sits at the boundary between liminal and manifest phases.  It shows the
*outcome* of the liminal field transitioning into committed execution
(focus intensity, active stage, routed models, active devices).

The manifest surface is permitted to show execution *context* (where the
field landed) but must not show liminal-field spatial dimensions as primary
content.  The manifest surface is distinct from liminal space:

- **Liminal space** — the execution field in motion (chains unfolding,
  simulation branching)
- **Manifest surface** — the execution field after commitment (stage ready,
  focus committed, routing confirmed)

---

## 6. Serialisable Structures for Liminal-Space Consumption

The canonical entry point for liminal-space rendering is:

```python
from core.liminal_space_mapping import (
    build_liminal_space_map,
    LiminalSpaceMap,
    LocalChainView,
    CrossDeviceChainView,
    SimulationSummary,
)
```

`LiminalSpaceMap` is a read-only, serialisable dataclass that holds:
- `local_chain` — `LocalChainView` (derived from `LocalChainSnapshot`)
- `cross_device_chain` — `CrossDeviceChainView` (derived from `CrossDeviceChainSnapshot`)
- `simulation_summary` — `SimulationSummary` (speculative/sandbox field)

All structures implement `to_dict()` and are safe for display consumption.

---

## 7. References

- `core/liminal_space_mapping.py` — canonical liminal-facing structures
- `core/local_execution_chain.py` — local chain source
- `core/cross_device_execution_chain.py` — cross-device chain source
- `docs/SANDBOX_SIMULATION_PROJECTION.md` — sandbox/simulation field definition
- `docs/LOCAL_EXECUTION_CHAIN.md` — local chain full documentation
- `docs/CROSS_DEVICE_EXECUTION_CHAIN.md` — cross-device chain full documentation
- `docs/DESKTOP_DISPLAY_BOUNDARIES.md` — canonical boundary contract
- `windows_client/status_board_v2/liminal_surface.py` — liminal surface renderer
- `windows_client/status_board_v2/ACTIVE_SURFACE.md` — surface authority registry
