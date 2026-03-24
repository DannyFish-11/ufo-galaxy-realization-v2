# Desktop Semantic Closure

> **Canonical architectural contract** — this document formally closes the
> tri-state desktop semantic model for the Galaxy runtime.  All surfaces,
> docs, tests, and future PRs must conform to these definitions.

---

## 1. The Tri-State Desktop Model

The Galaxy desktop runtime is governed by **three and only three** canonical
semantic states.  They describe the subject's existential lifecycle, not a UI
mode or internal state protocol.

| State | Meaning |
|-------|---------|
| `silent` | Subject at rest.  Native multimodal host ingress continues in the background; no active cognition request is in flight. |
| `liminal` | Subject in transition.  OpenClawd cognition and execution branching are in progress; the system is deciding whether to route locally or across devices. |
| `manifest` | Subject actively expressing: producing output, controlling devices, or running inside a cross-device execution loop.  Transitions back to `silent` on completion. |

### Authority

| Concern | Authority |
|---------|-----------|
| Tri-state lifecycle value | `core/desktop_presence_runtime.py` — `DesktopPresenceRuntime` |
| Continuum posture (internal) | `core/openclawd.py` — `ContinuumOrchestrator` |
| Projection / outward state | `contracts/desktop_status_projection.py` — `DesktopStatusProjection` |

`DesktopPresenceRuntime` is the **sole driver** of the tri-state subject
lifecycle.  No adapter surface (chat route, gateway, launcher script) has
subject-core authority.

---

## 2. Surface Semantics

### 2.1 Status Board (`windows_client/status_board_v2/`)

Role: `ACTIVE_DESKTOP_STATUS` — canonical structured-information display layer.

**Owned content classes:**

- Phase label (`tri_state_phase`)
- Model routing topology (`primary_model_id`, `support_model_ids`, weights)
- Provider / vendor and OneAPI supply status
- Device IDs and execution summary (`execution_stage`, `current_task_summary`)
- Runtime metrics (`presence_intensity`, `coherence`, `collapse_tendency`, `retreat_tendency`)

**Must not carry:**

- Spatial execution-field dimensions as primary panels
- Dashboard-style flat provider lists
- Operator information blocks unrelated to system state

### 2.2 Liminal Space (`liminal_surface.py`)

Role: spatial execution field — the bridge between `silent` and `manifest`.

**Canonical content classes (three and only three):**

1. **Local execution chain** — from `core/local_execution_chain.py`
2. **Cross-device execution chain** — from `core/cross_device_execution_chain.py`
3. **Sandbox / speculative execution field** — from `core/liminal_space_mapping.py`

**Must not carry:**

- Provider list cards
- Dashboard-style model panels
- Full metrics / status-board panels
- Generic operator information blocks

### 2.3 Manifest Surface (`manifest_surface.py`)

Role: renders the execution context that crystallises from the liminal field
when the system transitions into `manifest` state.

**Permitted content:**

- `source_phase` — tri-state phase of the underlying projection
- `stage_ready` — whether the manifest surface is active
- `focus_intensity` — execution-field commitment strength
- `primary_model_id` / `support_model_ids` / `active_weights` — routing context
- `active_device_ids` / `execution_stage` / `task_summary` / `route_reason`

**Must not carry:**

- Provider list cards, dashboard-style model panels, full metrics panels
- Content duplicating the status board's structured-information function

---

## 3. Legacy Residue Policy

The following legacy terms and architectural concepts are **downgraded**:

| Legacy concept | Canonical replacement |
|----------------|-----------------------|
| `dashboard/` provider panels | `windows_client/status_board_v2/` projection-driven surfaces |
| Flat provider/status lists | `DesktopStatusProjection` sub-contracts |
| `status_board.py` (root) | `status_board_v2/` |
| `dashboard/backend/main.py` as status authority | `core/api_routes.py` |

Dispositions:

- **`dashboard/` provider panels** — retained only for transition-period
  compatibility; must not define system structure.
- **Flat provider/status lists** — legacy wording must be updated in new code;
  use `DesktopStatusProjection` sub-contracts instead.
- **`status_board.py` (root)** — deprecated (PR-8); do not extend.
- **`dashboard/backend/main.py` as status authority** — legacy management
  panel only; `core/api_routes.py` is the authoritative REST API layer.

Legacy surfaces are registered in `core/orchestration_authority/legacy_paths.py`
and `core/ui_surface_authority.py`.  Consult those registries before adding
new references to legacy surface paths.

---

## 4. Invariants

The following invariants must hold at all times:

1. **Tri-state completeness** — every observable system state maps to exactly
   one of `silent` / `liminal` / `manifest`.  There is no fourth state.
2. **Single authority** — `DesktopPresenceRuntime` is the sole driver of the
   tri-state lifecycle.  Adapters must call `handle_request()` to enter it.
3. **Projection-driven status** — all status display surfaces must consume
   `DesktopStatusProjection` from `GET /api/v1/projection/runtime`.  No
   surface reconstructs truth independently.
4. **Boundary integrity** — content classes must not leak between the status
   board and the liminal space (see §2).
5. **Legacy isolation** — legacy surfaces carry their `LEGACY_SURFACE.md`
   markers and must not claim active architectural authority.

---

## 5. Cross-References

- [`docs/DESKTOP_DISPLAY_BOUNDARIES.md`](DESKTOP_DISPLAY_BOUNDARIES.md) — canonical display boundary contract
- [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) — status board design and usage guide
- [`docs/LIMINAL_SPACE_MAPPING.md`](LIMINAL_SPACE_MAPPING.md) — liminal space mapping definition
- [`docs/STATUS_AND_STATISTICS_OWNERSHIP.md`](STATUS_AND_STATISTICS_OWNERSHIP.md) — statistics / summary ownership
- [`docs/CONFIGURATION_ENTRY_UNIFICATION.md`](CONFIGURATION_ENTRY_UNIFICATION.md) — configuration entry semantics
- [`contracts/desktop_status_projection.py`](../contracts/desktop_status_projection.py) — canonical projection contract
- [`core/desktop_presence_runtime.py`](../core/desktop_presence_runtime.py) — tri-state lifecycle authority
- [`core/ui_surface_authority.py`](../core/ui_surface_authority.py) — surface role registry
- [`core/orchestration_authority/legacy_paths.py`](../core/orchestration_authority/legacy_paths.py) — legacy path registry
- [`windows_client/status_board_v2/ACTIVE_SURFACE.md`](../windows_client/status_board_v2/ACTIVE_SURFACE.md) — active surface declaration
- [`dashboard/LEGACY_SURFACE.md`](../dashboard/LEGACY_SURFACE.md) — legacy surface declaration
