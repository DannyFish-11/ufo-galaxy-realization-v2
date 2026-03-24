# Desktop Semantic Closure

> **Status: Canonical — PR-7 semantic-closure.**
>
> This document is the authoritative definition of the
> **manifest / active / liminal tri-state** for the Galaxy desktop runtime.
> All surfaces, tests, comments, and documentation must use these definitions
> consistently.

---

## 1. The Tri-State: manifest / active / liminal

The Galaxy desktop runtime operates on a three-value lifecycle for every
execution subject:

```
silent  →  liminal  →  manifest
```

| State | One-line meaning | Architectural role |
|---|---|---|
| **silent** | No active presence; minimal footprint. | Subject is dormant.  No execution chains running, no field active.  The runtime waits. |
| **liminal** | Execution is unfolding; intent is forming. | The **execution/simulation field**.  Local and cross-device chains are active.  Speculative and sandbox branches are evaluated here. |
| **manifest** | Execution context committed; producing output. | The **structured surfaced state**.  The system has fully committed to a routing context.  Results, models, devices, and task summaries are exposed here. |

### 1.1 `active` — the immediate foreground operating state

**`active`** is not a separate lifecycle value — it is the adjective describing
the **current foreground operating state** of the runtime:

- An execution subject is *active* when it is in the `manifest` state and
  producing output.
- A surface is *active* when it is rendering data derived from live runtime
  state (not legacy compatibility data).
- The `ACTIVE_DESKTOP_STATUS` role (see `core/ui_surface_authority.py`) marks
  `windows_client/status_board_v2/` as the **active** canonical desktop
  status surface.

> **Rule**: Use `active` to describe foreground operating state or surface
> authority.  Do **not** use `active` as a substitute for `manifest` or
> `liminal` in lifecycle descriptions.

### 1.2 `manifest` — structured status / declared surfaced state

**`manifest`** means the subject has committed to an execution context and
is actively producing output or controlling devices.

- In the **status board context**, `manifest` appears as the phase label in
  `phase_surface.py`.
- In the **liminal-space context**, `manifest_surface.py` renders the
  execution-context state that crystallised from the liminal field.
- `ManifestStageState` (see `desktop_projection/manifest_stage_state.py`)
  encodes this committed execution context: focus intensity, active models,
  devices, route reason, and task summary.
- The `DesktopStatusProjection` contract (see
  `contracts/desktop_status_projection.py`) is the **canonical structured
  information contract** for the manifest surface.

> **Rule**: `manifest` = structure formed, action committed.  Do **not** use
> it to mean "a dashboard overview" or "a general information panel".

### 1.3 `liminal` — execution/simulation field

**`liminal`** is the active execution layer between silent and manifest.

- It is a **spatial execution field**, not a transition holding area.
- It carries **exactly** three categories of content (see §3):
  1. Local execution chain
  2. Cross-device execution chain
  3. Sandbox simulation / speculative execution field
- `LiminalSurface` (see `windows_client/status_board_v2/liminal_surface.py`)
  renders the three-part execution field view.
- `LiminalSpaceMap` (see `core/liminal_space_mapping.py`) is the canonical
  data structure for liminal content.

> **Rule**: `liminal` = execution/simulation field; intent forming.
> Do **not** use it to mean "a generic transition bucket" or "any intermediate
> state".

---

## 2. Authoritative Surfaces

### 2.1 Right-side desktop status board (`status_board_v2/`)

**Authority role**: `PROJECTION_DRIVEN` / `ACTIVE_DESKTOP_STATUS`

This is the **canonical structured-information display layer**.  It answers:

> *"What is the system currently doing, and why?"*

**Canonical contract**: `contracts.desktop_status_projection.DesktopStatusProjection`

**Authoritative for**:
- Model routing information (`primary_model_id`, `support_model_ids`, `active_weights`, `route_reason`)
- Provider/vendor and OneAPI status
- Primary/support model topology (weight bars, topology graph)
- System state and execution summary (`execution_stage`, `current_task_summary`, tri-state phase)
- Device/task/metrics information

**Sub-surfaces** (all projection-driven, read-only):

| Surface | Domain |
|---|---|
| `phase_surface.py` | Tri-state phase label (`silent` / `liminal` / `manifest`) |
| `domain_surface.py` | Runtime domain (`local` / `cross_device` / `transition`) |
| `topology_surface.py` | Model topology: native-multimodal-first layered structure |
| `device_surface.py` | Device IDs and execution context |
| `metrics_surface.py` | Presence / coherence / tendency metrics |
| `return_surface.py` | Return-intelligence surface |

**See also**: `docs/DESKTOP_DISPLAY_BOUNDARIES.md`, `docs/STATUS_BOARD_V2.md`

### 2.2 Liminal space (execution/simulation field)

**Authority role**: Spatial execution field only

This is the **canonical execution-field surface**.  It carries only
execution-path unfolding, not system information.

**Canonical contract**: `core.liminal_space_mapping.LiminalSpaceMap`

**Authoritative for**:
- Local execution chain (`LocalChainView`)
- Cross-device execution chain (`CrossDeviceChainView`)
- Sandbox/speculative execution field (`SimulationSummary`)

**Sub-surfaces**:

| Surface | Domain |
|---|---|
| `liminal_surface.py` | Three-part execution field (local chain / cross-device chain / sandbox) |
| `manifest_surface.py` | Execution-context state crystallised from the liminal field |

**See also**: `docs/LIMINAL_SPACE_MAPPING.md`, `docs/DESKTOP_DISPLAY_BOUNDARIES.md`

### 2.3 Model routing authority

**Authority role**: Canonical routing decision source

`core/model_topology/topology_router.py` (sentinel `CANONICAL_ROUTING_AUTHORITY`)
is the **sole canonical routing authority**.  The `routing_authority` field in
`RuntimeProjection` exposes this.

**See also**: `docs/MODEL_ROUTING_AUTHORITY.md`

### 2.4 OneAPI as aggregator integration layer

**Authority role**: External aggregator — **not** a direct/native-multimodal provider

OneAPI occupies the **lower aggregator row** in the model supply topology.
It is a system-level source integration, not a dashboard-local config surface.

Configuration entries (`ONEAPI_BASE_URL`, `ONEAPI_API_KEY`) are **system-wide**
and feed the provider pool, routing logic, and projection-facing status.

**See also**: `docs/ONEAPI_SYSTEM_POSITION.md`

---

## 3. Content Ownership — Canonical Table

| Content class | Canonical surface | Prohibited in |
|---|---|---|
| Model routing info (primary, support, weights) | Right-side status board (`topology_surface.py`) | Liminal space |
| Provider/vendor status, OneAPI row | Right-side status board (`topology_surface.py`) | Liminal space |
| Tri-state phase label | Right-side status board (`phase_surface.py`) | — |
| Presence/coherence/tendency metrics | Right-side status board (`metrics_surface.py`) | Liminal space |
| Device IDs, execution stage, task summary | Right-side status board (`device_surface.py`) | Liminal space as primary panels |
| Local execution chain | Liminal space (`liminal_surface.py`) | Right-side board as primary |
| Cross-device execution chain | Liminal space (`liminal_surface.py`) | Right-side board as primary |
| Sandbox/speculative execution field | Liminal space (`liminal_surface.py`) | Right-side board as primary |
| Execution-context committed state | Manifest surface (`manifest_surface.py`) | Right-side board as primary |
| Structured summary/statistics | Right-side status board (`DesktopStatusProjection`) | Liminal space |
| Execution-path unfolding | Liminal space (`LiminalSpaceMap`) | Right-side board |
| Configuration-entry semantics | System-level (`CONFIG_GOVERNANCE.md`, env vars) | Dashboard-local panes (legacy) |

---

## 4. Summary / Statistics Semantics

Summary and statistics fields belong on the **right-side status board** via the
`DesktopStatusProjection` contract:

- `ExecutionProjection` — execution path, remote mode, active device IDs
- `LifecycleProjection` — execution stage, health
- `ExplainabilityProjection` — fallback chain, diagnostics

**Rules**:
1. Structured summaries (model routing, device state, metrics) belong to the
   right-side board / `manifest`-facing information model.
2. Execution-path unfolding belongs to the liminal field (`LiminalSpaceMap`).
3. Summary/statistics helpers must **not** re-introduce dashboard-centric
   semantics (flat provider panel, per-screen stats blocks, etc.).
4. The `build_desktop_status_projection()` builder in `DesktopPresenceRuntime`
   is the canonical assembly point for all structured summaries.

---

## 5. Configuration-Entry Semantics

Configuration entries are **system-level inputs** — not per-surface or
per-dashboard settings.

### 5.1 Canonical entry points

| Config entry | System role |
|---|---|
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc. | Direct provider keys — feed `MultiLLMRouter` / `ProviderInventory` |
| `ONEAPI_BASE_URL`, `ONEAPI_API_KEY` | OneAPI aggregator entry — system-wide, feeds provider pool and routing |
| `GALAXY_API_TOKEN` | API bearer token — authentication for REST + WS |
| `GALAXY_MODE` | Runtime mode (`production` / `development` / `testing`) |
| `GALAXY_CROSS_DEVICE_ENABLED` | Cross-device routing toggle — system-wide |

### 5.2 Invariants

- Configuration entries entered by the operator flow into the **system-level
  provider pool and routing logic**, then surface through
  `DesktopStatusProjection` on the right-side board.
- There is **no concept** of a configuration entry that applies to only one
  dashboard page or one surface.
- Configuring OneAPI from any UI surface must propagate globally (update env
  / runtime config, re-register provider, refresh projection).
- Dashboard-local configuration panes are **legacy/compatibility-only**.

**See also**: `docs/CONFIG_GOVERNANCE.md`, `docs/ONEAPI_SYSTEM_POSITION.md`

---

## 6. Deprecated / Compatibility-Only Semantics

The following terms and patterns are **deprecated** and must not be introduced
as canonical semantics:

| Deprecated pattern | Canonical replacement |
|---|---|
| "Dashboard" as a primary execution surface | `windows_client/status_board_v2/` — the active canonical status board |
| Flat provider-panel list as primary topology view | Native-multimodal-first layered topology (`topology_surface.py`) |
| `dashboard/` backend as projection source | `core/routes/projection.py` — the canonical `GET /api/v1/projection/runtime` endpoint |
| `liminal` as a generic transition bucket | `liminal` = execution/simulation field with three allowed content classes |
| `manifest` as a dashboard overview | `manifest` = structured surfaced state after execution commitment |
| Per-screen OneAPI config pane | System-wide OneAPI config via `ONEAPI_BASE_URL` / `ONEAPI_API_KEY` |
| Provider-list-first semantics | Provider info belongs to the right-side board topology row, not liminal space |

### 6.1 Compatibility marking convention

Where legacy code or wording is retained for backward compatibility, it must
be explicitly marked with one of:

```python
# [COMPAT-ONLY] — legacy; do not extend.
```

```markdown
> **Compatibility-only** — retained for legacy consumers.  Do not extend.
```

See `dashboard/LEGACY_SURFACE.md` and `core/orchestration_authority/legacy_paths.py`
for examples of correctly marked compatibility surfaces.

---

## 7. Guardrails and Tests

The following test files encode the semantic boundaries defined above:

| Test file | What it guards |
|---|---|
| `tests/test_display_boundary_guardrails.py` | Display boundary between right-side board and liminal space |
| `tests/test_pr55_liminal_space_mapping.py` | Liminal space canonical mapping structure (`LiminalSpaceMap`) |
| `tests/test_pr7_semantic_closure.py` | Tri-state terminology, surface ownership, summary/statistics placement, config-entry unification, legacy demotion |

### 7.1 Key invariants tested in `test_pr7_semantic_closure.py`

1. `DESKTOP_SEMANTIC_CLOSURE.md` exists at the expected path.
2. The doc defines all three tri-state terms: `silent`, `liminal`, `manifest`.
3. The doc defines `active` separately from the three lifecycle states.
4. The doc enumerates the four authoritative surfaces (status board, liminal,
   routing authority, OneAPI aggregator).
5. Summary/statistics fields belong to the right-side board contract.
6. Configuration entries are documented as system-level (not per-screen).
7. Legacy/deprecated patterns are explicitly listed and marked.
8. `DesktopStatusProjection` contract covers all required right-side content.
9. `LiminalSpaceMap` covers exactly the three allowed liminal content classes.
10. Tri-state phase labels are consistent across `phase_surface.py`,
    `liminal_surface.py`, `manifest_surface.py`.

---

## 8. Summary

| Question | Answer |
|---|---|
| What does `silent` mean? | No active presence; minimal footprint. |
| What does `liminal` mean? | Execution/simulation field; intent forming. |
| What does `manifest` mean? | Structured surfaced state; execution committed. |
| What does `active` mean? | Foreground operating state or surface authority (not a lifecycle value). |
| Where do summaries/statistics go? | Right-side status board via `DesktopStatusProjection`. |
| Where does execution-path unfolding go? | Liminal space via `LiminalSpaceMap`. |
| Where do configuration entries go? | System-level (env vars / config files); never per-screen only. |
| What is OneAPI's system position? | Aggregator integration layer (lower row); system-wide, not dashboard-local. |
| What routing authority is canonical? | `topology_router.py` / `CANONICAL_ROUTING_AUTHORITY`. |
| What is the legacy status board? | `dashboard/` and `windows_client/status_board.py` — compatibility-only. |

---

## Related Documents

- [`docs/DESKTOP_DISPLAY_BOUNDARIES.md`](DESKTOP_DISPLAY_BOUNDARIES.md) — canonical display boundary contract
- [`docs/LIMINAL_SPACE_MAPPING.md`](LIMINAL_SPACE_MAPPING.md) — canonical liminal space mapping
- [`docs/MANIFEST_STAGE.md`](MANIFEST_STAGE.md) — manifest stage architecture
- [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) — status board V2 design guide
- [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md) — OneAPI aggregator position
- [`docs/MODEL_ROUTING_AUTHORITY.md`](MODEL_ROUTING_AUTHORITY.md) — routing authority contract
- [`docs/CONFIG_GOVERNANCE.md`](CONFIG_GOVERNANCE.md) — configuration governance
- [`windows_client/status_board_v2/ACTIVE_SURFACE.md`](../windows_client/status_board_v2/ACTIVE_SURFACE.md) — active surface authority
- [`contracts/desktop_status_projection.py`](../contracts/desktop_status_projection.py) — canonical projection contract
- [`core/liminal_space_mapping.py`](../core/liminal_space_mapping.py) — canonical liminal structures
