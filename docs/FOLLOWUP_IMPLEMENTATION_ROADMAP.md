# Follow-Up Implementation Roadmap

> **Full re-audit pass** — fresh standalone prioritized roadmap produced as part of the
> complete dual-repo architecture re-audit.
> Primary repo: `DannyFish-11/ufo-galaxy-realization-v2`.
> Cross-repo reference: `DannyFish-11/ufo-galaxy-android`.
>
> Supersedes all prior roadmap versions including `REAUDIT_FOLLOWUP_ROADMAP_V2.md`.
> Companion: `DUAL_REPO_FULL_REAUDIT.md`, `DUAL_REPO_GAP_MATRIX.md`.

---

## Roadmap principles

1. **Correctness before capability**: P0/P1 items address correctness failures visible
   to users today. They block all other protocol and multi-device work.
2. **Architectural convergence before feature expansion**: Unify scheduling and truth
   surfaces before adding new multi-device features on top of divergent foundations.
3. **Cross-repo coordination explicitly gated**: Items requiring Android client changes
   are grouped separately and require joint planning.
4. **Design decisions before implementation**: Open questions (Q1–Q7) must be answered
   as design PRs before corresponding implementation PRs are opened.

---

## Priority levels

| Level | Meaning |
|-------|---------|
| **P0** | Correctness failure affecting users today; must be addressed first |
| **P1** | High-priority architectural gap; blocks P2/P3 work or causes misuse risk |
| **P2** | Important completeness gap; unblocks downstream capabilities |
| **P3** | Planned retirement or observability improvement |
| **P4** | Low-priority cleanup; acceptable to defer indefinitely |

---

## Group A: Scheduling / truth convergence

*Goal: Ensure the canonical capability graph is actually consulted at dispatch time and
that truth surfaces converge into a single, fully-populated outward truth.*

### A1 — CommandRouter capability graph enforcement (P1)

**Gap**: SCHED-001 / GAP-512-004.
`CommandRouter.route_envelope()` calls `query_routable_executors()` advisory-only.
Results are logged but not used to gate or alter routing decisions.

**Required work**:
- Decide (Q1): Should capability verification join the admissibility chain as Gate 4,
  or remain a post-selection validation?
- If Gate 4: add `CapabilityAssimilationLayer.query_routable_executors()` as a
  mandatory gate in `cross_device_candidates.resolve_candidates()`.
- If post-selection: add a validation step in `CommandRouter` that raises
  `CapabilityMismatchError` when selected devices cannot satisfy required capabilities.
- Add test: task with `required_capabilities=["vlm"]` must not be dispatched to a
  device that has not reported VLM capability.

**Blocks**: A2, B1.

---

### A2 — DeviceRouter policy residue extraction (P1)

**Gap**: SCHED-003.
`DeviceRouter.route_task()` still calls `_analyze_command()` and `_select_devices()`.

**Required work**:
- Move `_analyze_command()` logic to `CommandRouter` pre-dispatch. `CommandRouter`
  should pass resolved `exec_mode` and `task_type` to `DeviceRouter` as part of
  the `TaskEnvelope`.
- Make `_select_devices()` accept externally resolved target list from `CommandRouter`
  rather than self-resolving. If no external targets provided, fall back gracefully.
- Add test: after extraction, `DeviceRouter.route_task()` must not perform
  `exec_mode` derivation or independent device selection.

---

### A3 — DevicePool → CapabilityAssimilation wiring audit (P2)

**Gap**: SCHED-004.
`ConstellationRuntime._run_dag_loop()` calls `pool.select_device(required_capabilities=caps)`.
Whether `DevicePool` reads from `CapabilityAssimilationLayer` is unconfirmed.

**Required work**:
- Audit `DevicePool.select_device()` implementation.
- If it maintains its own capability state: replace with `CapabilityAssimilationLayer.query_routable_executors()`.
- Add test: `DevicePool.select_device()` must return devices that are present in `CapabilityAssimilationLayer`.

---

### A4 — Projection endpoint full convergence (P2)

**Gap**: TRUTH-001 / ADMIT-002.
Not all projection endpoint code paths call `enrich_runtime_projection()`. Some
fallback paths return `outward_truth: null`.

**Required work**:
- Audit all code paths in `core/routes/projection.py` that return a projection response.
- Ensure all paths (success and fallback/error) call `enrich_runtime_projection()` and
  include a non-null `outward_truth`.
- Add test: projection endpoint must always return a non-null `outward_truth` key.

---

### A5 — MultiDeviceRuntimeProjection.merged_results full population (P2)

**Gap**: TRUTH-004 / ADMIT-002.
`MultiDeviceRuntimeProjection.merged_results` body is not confirmed as fully sourced
from canonical chain state.

**Required work**:
- Trace all assembly points for `merged_results` in `ProjectionSurfaceBridge.enrich_runtime_projection()`.
- Confirm: per-device readiness, formation data, mesh session data, and task result data
  are all sourced from canonical read contracts (`RegisteredRuntimeDevice`,
  `DeviceFormationGroup`, `MeshSession`, `TaskGraphRuntime`).
- Add test: `merged_results` includes formation data when formation was resolved.

---

### A6 — Desktop projection surface convergence (P2)

**Gap**: TRUTH-002.
Desktop status board surfaces assemble some topology/route views independently.

**Required work**:
- Audit `desktop_projection/` and `status_board_v2` topology assembly.
- For any view that independently queries route/topology: replace with
  `NetworkTopologyRuntime` read via `TruthIntegrationLayer`.
- Add test: desktop projection topology matches `NetworkTopologyRuntime` state.

---

## Group B: Multi-device runtime systemization

*Goal: Replace contract-first multi-device components with live runtime engines that
drive session lifecycle, barrier coordination, role allocation, and result merge.*

### B1 — MeshSession lifecycle engine (P1)

**Gap**: MESH-001.
`MeshSessionStatus` transitions are declared but no runtime process drives them.
`FORMING → ACTIVE → COMPLETING → DONE` are never triggered.

**Required work**:
- Design decision (Q3): confirm canonical session migration path.
- Implement `MeshSessionLifecycleEngine`:
  - Subscribes to `TaskGraphRuntime` node state transitions.
  - Drives `MeshSessionStatus` based on participant task states.
  - Publishes `mesh_session_status_changed` events.
- Wire `MeshSessionLifecycleEngine` startup into `BodyMeshRegistry.create_session()`.
- Add test: creating a mesh session and submitting tasks transitions status through
  `FORMING → ACTIVE → COMPLETING → DONE`.

**Blocks**: B2, B3.

---

### B2 — MeshSessionCoordinator live state engine (P1)

**Gap**: MESH-002.
`MeshSessionCoordinator` state is populated at construction time from a static snapshot.
`pending_device_ids`, `completed_device_ids`, `failed_device_ids` are never updated.

**Required work**:
- Implement `MeshSessionCoordinatorRuntime`:
  - Consumes `mesh_session_status_changed` events (from B1).
  - Moves device IDs between `pending → completed / failed` as task results arrive.
  - Triggers barrier release when all `pending_device_ids` have been resolved.
  - Triggers merge when `MeshBarrierState.barrier_satisfied` transitions to `True`.
- Add test: all devices completing their assigned tasks causes
  `MeshBarrierState.barrier_satisfied = True`.

---

### B3 — CrossRuntimeResultMerge engine (P2)

**Gap**: MESH-007.
`CrossRuntimeResultMerge` is a contract definition with no merge execution engine.

**Required work**:
- Implement `ResultMergeEngine`:
  - Receives per-device `ResultEnvelope` entries as they arrive.
  - Applies merge strategy (ordered, unordered, or priority-weighted).
  - Emits merged `ResultEnvelope` to `ReplayFoundation` and `OperatorSurface`.
- Wire into `MeshSessionCoordinatorRuntime` merge trigger (from B2).
- Add test: two device results merged into one canonical result.

---

### B4 — Mesh session persistence (P2)

**Gap**: MESH-003 / Durable session snapshot.
`BodyMeshRegistry` is in-memory only. Session state is lost on restart.

**Required work**:
- Implement persistent session store backend (SQLite for single-node; pluggable for distributed).
- `BodyMeshRegistry` writes session state to persistent store on every state change.
- On startup, `BodyMeshRegistry` restores sessions from persistent store.
- Add test: session survives a `BodyMeshRegistry` restart.

---

### B5 — Dynamic formation rebalance (P3)

**Gap**: MESH-008.
`formation_resolver` resolves a formation statically at dispatch time. No runtime
reshaping when device health changes or a device disconnects mid-session.

**Required work**:
- Design decision: what triggers rebalance? (device disconnect, score threshold crossed)
- Implement `FormationRebalanceEngine`:
  - Subscribes to device health/score events.
  - Re-runs `formation_resolver.resolve_formation()` with updated available devices.
  - Emits `formation_reshaping_event` to active session coordinator.
- Wire into `MeshSessionCoordinatorRuntime` (from B2).
- Add test: device disconnect mid-session triggers formation rebalance.

---

### B6 — Recovery / resume from checkpoint (P3)

**Gap**: MESH-004 / Durable runtime session snapshot.

**Required work**:
- Implement checkpoint store: after every task step, write `TaskGraphRuntime` node
  states + `MeshSessionCoordinator` state to durable store.
- Implement `SessionResumeEngine`: on session restore request, load from checkpoint
  store, resume incomplete task nodes.
- Wire with persistent session store (B4).
- Add test: session resumes from checkpoint after simulated coordinator restart.

---

## Group C: Compatibility retirement

*Goal: Remove high-misuse-risk surfaces and retire known-dead compat paths.*

### C1 — DeviceRouter policy residue retirement (P1)

See A2. Extracting policy from `DeviceRouter` is both a scheduling convergence item
and a compatibility retirement item. After extraction, `_analyze_command()` and
`_select_devices()` can be removed from `DeviceRouter`.

---

### C2 — CapabilityRegistry routing guard (P1)

**Gap**: COMPAT-002.

**Required work**:
- Add a context-aware guard: if `CapabilityRegistry` is called from a routing-context
  module (`command_router.py`, `formation_resolver.py`, `cross_device_candidates.py`,
  `device_router.py`), emit a structured warning and record a `CapabilityRegistryMisuseEvent`.
- Add lint rule or test that fails if `CapabilityRegistry` is imported in routing modules.

---

### C3 — LEGACY_DISPATCH observability (P2)

**Gap**: COMPAT-003 / observability gap.

**Required work**:
- Add Prometheus counter (or equivalent) `galaxy_legacy_dispatch_total` incremented
  on every `LEGACY_DISPATCH` event in `CrossDeviceCoordinator`.
- Add alert: if `galaxy_legacy_dispatch_total` rate exceeds expected baseline (>0),
  fire an alert to the on-call channel.
- Extend pattern to other compat surfaces: `_handle_forward_log`, AIP v2 normalisation.

---

### C4 — TaskRouter / TaskScheduler file removal (P3)

**Gap**: COMPAT-001.

**Required work**:
- Confirm `galaxy_gateway/task_router.py` is removed from disk.
- `grep -r "TaskRouter\|TaskScheduler" --include="*.py"` to verify no remaining imports.

---

### C5 — Android REST compat alias retirement (P3, requires coordination)

**Gap**: COMPAT-006.

**Required work**:
1. Add access log analysis: confirm volume on `/api/devices/register`, `/api/devices/list`.
2. Add deprecation headers to these endpoints.
3. Coordinate with Android team: update SDK to use canonical paths.
4. Set retirement date (suggest: 2 sprints after SDK update confirmed).
5. Remove endpoints after retirement date.

**Cross-repo coordination required**: `ufo-galaxy-android`.

---

### C6 — Legacy WebSocket path retirement (P3, requires coordination)

**Gap**: PROTO-007 / Android compat.

**Required work**:
1. Confirm which Android client versions still use `/ws/ufo3/`.
2. EOL old client versions or require upgrade.
3. Remove `/ws/ufo3/` handler after confirmed migration.

**Cross-repo coordination required**: `ufo-galaxy-android`.

---

## Group D: Protocol / runtime completion

*Goal: Promote HIGH-severity Android protocol gaps to full canonical handlers.*

### D1 — task_cancel canonical handler (P0)

**Gap**: PROTO-002 (re-classified HIGH / P0).
`task_cancel` hits `_handle_forward_log` and is discarded. Tasks continue executing
after the Android side believes they are cancelled. **Correctness failure.**

**Required work**:
- Implement `_handle_task_cancel()` in `galaxy_gateway/android_bridge.py` (or handler).
- Route cancellation to `CommandRouter.cancel_task(task_id)` (or equivalent lifecycle operation).
- Confirm `TaskGraphRuntime` transitions task node to `CANCELLED`.
- Emit `task_cancel_ack` back to Android.
- Add test: Android `task_cancel` message cancels the task on center side.

---

### D2 — task_status canonical handler (P1)

**Gap**: PROTO-002.
`task_status` hits `_handle_forward_log`. Android cannot get authoritative task state.

**Required work**:
- Implement `_handle_task_status_request()` in Android bridge.
- Query `TaskGraphRuntime` for current task node state.
- Respond with structured `task_status_response` AIP message.
- Add test: Android `task_status` request returns current task state.

---

### D3 — session_migrate canonical path unification (P1)

**Gap**: PROTO-001 / MESH-005.
`SESSION_MIGRATE` is AIP v2 binary. Two migration code paths may exist (`session_roaming.py`
vs. `core/routes/sessions.py`). Canonical path not confirmed.

**Required work**:
- Design decision (Q3): confirm canonical session migration path.
- Implement AIP v3 JSON `session_migrate` / `session_restore` message types in Android bridge.
- Route both paths to single canonical session migration engine.
- Confirm `core/routes/sessions.py` and `galaxy_gateway/routes/sessions.py` both delegate
  to `galaxy_gateway/session_roaming.py` (not two independent engines).
- Add test: session migration via both REST path and WebSocket path produces identical outcome.

**Cross-repo coordination required**: `ufo-galaxy-android` must ship AIP v3 session_migrate.

---

### D4 — Android capability ingress wiring (P2)

**Gap**: CROSS-004.
Android `device_capabilities` message received by V2 but not confirmed forwarded to
`CapabilityAssimilationLayer.assimilate_device()`.

**Required work**:
- Audit `_handle_device_register()` in `android_bridge.py`.
- Confirm `device.capabilities` from registration message is passed to
  `CapabilityAssimilationLayer.assimilate_device(device_id, capabilities)`.
- If missing, add the call.
- Add test: Android registration with capability list results in device appearing in
  `CapabilityAssimilationLayer.query_routable_executors()`.

---

### D5 — WebRTC-task lifecycle integration (P2)

**Gap**: WEBRTC-001, WEBRTC-002.
WebRTC is fully isolated from the canonical task lifecycle.

**Required work**:
- Design decision (Q5): is this near-term or longer-term?
- If near-term:
  - Add `task_type = "screen_capture_task"` to AIP v3 message types.
  - Add `screen_stream_start` step to `TaskEnvelope` for this task type.
  - Implement `WebRTCSessionManager.setup_session(task_id)` called from task step handler.
  - Implement teardown on `task_complete` / `task_cancel`.
  - Wire `Node_95_WebRTC_Receiver` as a task-scoped resource consumer.
- Add test: `screen_capture_task` task creation triggers WebRTC session setup.

---

### D6 — Android local truth reconciliation design (P2)

**Gap**: CROSS-002, TRUTH-005.
Android local state (session snapshot, readiness, task phase) has no reconciliation
protocol with V2 outward truth.

**Required work**:
- Design decision (Q4): V2 authoritative vs. Android authoritative vs. explicit sync?
- Implement agreed reconciliation protocol:
  - If V2 authoritative: Android emits delta sync events; V2 applies them.
  - If explicit sync: define `state_reconcile` AIP message type with conflict resolution.
- Add test: Android reconnection after disconnect causes local state to reconcile with V2.

**Cross-repo coordination required**: `ufo-galaxy-android`.

---

## Prioritized sequence summary

### Immediate (P0)
1. **D1** — task_cancel canonical handler (correctness failure)

### Short-term (P1)
2. **A1** — CommandRouter capability graph enforcement
3. **A2** — DeviceRouter policy residue extraction (C1)
4. **C2** — CapabilityRegistry routing guard
5. **B1** — MeshSession lifecycle engine
6. **B2** — MeshSessionCoordinator live state engine
7. **D2** — task_status canonical handler
8. **D3** — session_migrate canonical path unification

### Medium-term (P2)
9. **A3** — DevicePool → CapabilityAssimilation wiring
10. **A4** — Projection endpoint full convergence
11. **A5** — MultiDeviceRuntimeProjection.merged_results population
12. **A6** — Desktop projection convergence
13. **B3** — CrossRuntimeResultMerge engine
14. **B4** — Mesh session persistence
15. **C3** — LEGACY_DISPATCH observability
16. **D4** — Android capability ingress wiring
17. **D5** — WebRTC-task lifecycle integration
18. **D6** — Android local truth reconciliation

### Longer-term (P3/P4)
19. **B5** — Dynamic formation rebalance
20. **B6** — Recovery / resume from checkpoint
21. **C4** — TaskRouter file removal
22. **C5** — Android REST compat alias retirement
23. **C6** — Legacy WebSocket path retirement

---

## Design decisions required before implementation

These questions (from `DUAL_REPO_FULL_REAUDIT.md` §11) must be resolved as
explicit design decisions before their dependent PRs can be opened:

| Q# | Question | Blocks |
|----|----------|--------|
| Q1 | Capability verification as Gate 4 or post-selection validation? | A1 |
| Q2 | DevicePool → CapabilityAssimilation: yes/no and consistency model? | A3 |
| Q3 | Canonical session migration path: `session_roaming.py` or `core/routes/`? | D3, B1 |
| Q4 | Android local state: V2 authoritative, Android authoritative, or explicit sync? | D6 |
| Q5 | WebRTC-task lifecycle: near-term or longer-term? | D5 |
| Q6 | AIP v2 binary retirement date? | C5, C6 |
| Q7 | LEGACY_DISPATCH: metrics or log-only? | C3 |

---

## Answer to acceptance criterion 8

**AC8 — Prioritized follow-up implementation roadmap?**

> The roadmap above is grouped into four functional areas:
>
> **Scheduling / truth convergence (Group A)**: CommandRouter capability graph
> enforcement, DeviceRouter policy extraction, DevicePool audit, projection endpoint
> full convergence, MultiDeviceRuntimeProjection population, desktop projection convergence.
>
> **Multi-device runtime systemization (Group B)**: MeshSession lifecycle engine
> (critical P1), MeshSessionCoordinator live state, result merge engine, persistence,
> dynamic rebalance, recovery/resume.
>
> **Compatibility retirement (Group C)**: CapabilityRegistry guard, LEGACY_DISPATCH
> observability, TaskRouter file removal, Android REST/WebSocket compat retirement
> (with cross-repo coordination).
>
> **Protocol / runtime completion (Group D)**: task_cancel handler (P0 correctness),
> task_status handler, session_migrate canonical unification, capability ingress wiring,
> WebRTC-task lifecycle integration, Android local truth reconciliation.
>
> **Sequencing**: D1 first (correctness failure). Then A1/A2/C2/B1/B2/D2/D3 in parallel
> where possible (P1, high impact, mostly V2-internal). Then Group A completeness and
> Group B systemization work. Then Group D cross-repo items with coordination. Group C
> retirement items are ongoing throughout at lower priority.
