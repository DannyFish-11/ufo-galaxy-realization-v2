# Re-Audit: Prioritized Follow-Up Roadmap V2

> **Fresh re-audit pass** — `DannyFish-11/ufo-galaxy-realization-v2` and
> `DannyFish-11/ufo-galaxy-android`.
>
> Supersedes the "Prioritized follow-up PR sequence" section in `DUAL_REPO_GAP_MATRIX.md`.
> Companion: `docs/REAUDIT_FRESH_PASS_2.md`, `docs/REAUDIT_GAP_MATRIX_V2.md`

---

## Roadmap principles

1. **Correctness before capability**: P0 items fix silent correctness failures that
   affect users today. They block all other protocol and multi-device work.
2. **Foundation before features**: Capability-graph wiring and admissibility chain
   improvements must land before multi-device session features can be reliable.
3. **Unify before extend**: Duplicate paths (session migration, device selection)
   must be unified before extending them with new capabilities.
4. **Contract-first → runtime**: MeshSession / MeshSessionCoordinator contracts are
   stable; the next step is building a live runtime engine on top of them, not
   redesigning contracts.
5. **Design decisions unlock work**: Six open design questions (Q1–Q6 in
   REAUDIT_FRESH_PASS_2.md) block specific PRs. These must be answered first.

---

## Phase 0 — Correctness fixes (address before anything else)

These items cause silent failures in the current system. No new features should
be added until these are resolved.

### PR-A: Android task_cancel / task_status canonical handlers

**Gap**: PROTO-002 (HIGH)
**Problem**: Android users cancel tasks; center side ignores cancels; tasks continue
executing. Android UI shows "cancelled" while execution continues.

**Deliverables**:
- `_handle_task_cancel(msg)` in `android_bridge.py` → calls `CommandRouter.cancel_envelope(task_id)` → sends `task_cancel_ack` to Android
- `_handle_task_status(msg)` in `android_bridge.py` → reads from `TaskGraphRuntime` → returns `task_status_response`
- Unit tests: cancel propagation, status query response

**Dependency**: None. Can be started immediately.

---

### PR-B: Android capability ingress wiring

**Gap**: ADMIT-005 / CROSS-004 (HIGH, elevated from LOW)
**Problem**: When Android sends `device_register` with `device_capabilities`, it
is not confirmed that `CapabilityAssimilationLayer.assimilate_device()` is called.
Android device may be in UDM/UCM but invisible to any capability-based routing.

**Deliverables**:
- Confirm (or add) call to `CapabilityAssimilationLayer.assimilate_device()` in
  Android device registration handler in `android_bridge.py`
- Confirm capability payload is forwarded from `device_capabilities` AIP message
- Add test: Android device registration → capability graph contains device entry

**Dependency**: None. Can be started immediately (or in parallel with PR-A).

---

## Phase 1 — Foundation (capability graph + admission chain)

### PR-C: CommandRouter → capability graph wiring

**Gap**: SCHED-001 (MEDIUM)
**Problem**: `CommandRouter` selects cross-device dispatch targets without consulting
the unified capability graph. Routing is valid (devices are reachable) but not
capability-verified.

**Design decision required**: Q1 — Should capability verification be a new Gate 4
in the admissibility chain, or a pre-admissibility capability pre-filter in
CommandRouter directly?

**Deliverables**:
- Call `CapabilityAssimilationLayer.query_routable_executors(required_capabilities)` in `CommandRouter` cross-device path
- Pass result as a candidate filter into `cross_device_candidates.resolve_candidates()`
- Add test: task with `required_capabilities=["camera"]` is not dispatched to a device without that capability

**Dependency**: PR-B must land first (Android devices need to be in the capability graph).

---

### PR-D: ConstellationRuntime DevicePool → CapabilityAssimilationLayer confirmation

**Gap**: SCHED-004 (MEDIUM, NEW)
**Problem**: `ConstellationRuntime._run_dag_loop()` calls `pool.select_device()` —
not confirmed whether this reads from CapabilityAssimilationLayer.

**Deliverables**:
- Code audit: trace `DevicePool` construction and `select_device()` implementation
- If `DevicePool` is independent: wire to `CapabilityAssimilationLayer` or replace with admissibility chain
- If already wired: add documentation confirming the source
- Confirm ConstellationRuntime dispatches through `CommandRouter.route_envelope()`

**Dependency**: Can be audited independently; implementation depends on audit finding.

---

### PR-E: Session migration canonical path unification

**Gap**: MESH-005 (HIGH, elevated from MEDIUM)
**Problem**: Two session migration implementations exist. Split-brain risk for
migrating sessions.

**Design decision required**: Q3 — Which path is canonical: `galaxy_gateway/session_roaming.py`
or `core/routes/sessions.py`?

**Deliverables**:
- Define canonical session migration entry point
- Retire or fully delegate non-canonical path
- Update any callers to use canonical entry
- Add integration test: session migrates correctly and state is consistent after migration

**Dependency**: Design decision Q3 must be answered.

---

## Phase 2 — Multi-device session runtime engine

### PR-F: MeshSessionCoordinator live runtime engine

**Gap**: MESH-001 (HIGH)
**Problem**: `MeshSessionCoordinatorState` is contract-only; no live engine drives
it. Barrier coordination, assignment progress, and merge trigger are inert.

**Deliverables**:
- `MeshSessionCoordinatorRuntime` class in `core/mesh/`
- Subscribes to `TaskGraphRuntime` events (subtask start, subtask complete, subtask failed)
- Drives `pending_device_ids`, `completed_device_ids`, `failed_device_ids` transitions
- Drives `MeshSessionStatus` transitions: `FORMING → ACTIVE → COMPLETING → DONE`
- Implements barrier wait: when all `pending_device_ids` complete → trigger merge
- Writes updated coordinator state back to `BodyMeshRegistry`

**Dependency**: MESH-003 (BodyMeshRegistry persistence) should land concurrently or
slightly before to avoid state loss on restarts.

---

### PR-G: BodyMeshRegistry persistence + event wiring

**Gap**: MESH-003 (MEDIUM)
**Problem**: BodyMeshRegistry is in-process only; state lost on restart; not wired
to device connect/disconnect events.

**Deliverables**:
- Persistent storage for mesh state (recommend: Redis or SQLite)
- Subscribe to UDM/UCM device `connected`/`disconnected` events
- On device disconnect: update mesh memberships; flag affected sessions as `DEVICE_LOST`
- On process restart: reload mesh state from persistent store

**Dependency**: Can be started in parallel with PR-F.

---

### PR-H: DeviceRoleAllocator capability-aware allocation

**Gap**: MESH-004 (MEDIUM)
**Problem**: Role allocation is not capability-aware; `PRIMARY` role may be assigned
to a device with weaker capabilities.

**Deliverables**:
- `DeviceRoleAllocator.allocate()` accepts capability snapshot from `CapabilityAssimilationLayer`
- Role allocation prefers devices with `PRIMARY`-appropriate capabilities
- Test: device with `vision` capability is preferred for `PRIMARY` role in a vision task

**Dependency**: PR-C or PR-B (capability graph must be populated).

---

### PR-I: Formation capability verification

**Gap**: ADMIT-003 (MEDIUM)
**Problem**: `formation_resolver` does not verify device capabilities at formation
time. Device may join a formation for a task it cannot perform.

**Deliverables**:
- Add `CapabilityAssimilationLayer` call in `formation_resolver.resolve_formation()`
- Check that each `FormationMember` has the required capabilities declared in the task
- Exclude capability-incompatible devices from formation with logged reason

**Dependency**: PR-B (device capabilities must be in the graph).

---

## Phase 3 — Android protocol promotion

### PR-J: Session migrate / restore AIP v3 promotion

**Gap**: PROTO-001 (HIGH)
**Problem**: `session_migrate` / `session_restore` still in AIP v2 binary format
with two divergent center-side handlers.

**Deliverables**:
- AIP v3 JSON typed payload for `session_migrate`: `{session_id, source_device_id, target_device_id, context}`
- Single center-side handler in `android_bridge.py` delegating to canonical migration path
- Android update: emit `session_migrate` in AIP v3 JSON
- Retire AIP v2 binary path after confirmed migration

**Dependency**: PR-E must land first.

---

### PR-K: Wake event AIP v3 promotion

**Gap**: PROTO-003 (MEDIUM)
**Problem**: `wake_event` / `wake_route_result` still in AIP v2 binary format.

**Deliverables**:
- AIP v3 typed payload for `wake_event`: `{device_id, wake_trigger, context}`
- Wire into `process_wake_event()` in `core/e2e_orchestrator.py`
- Android update: emit `wake_event` in AIP v3 JSON

---

### PR-L: AIP v2 binary screen/input type migration

**Gap**: PROTO-005 (MEDIUM)
**Problem**: `ANDROID_SCREEN` (0x60) / `ANDROID_INPUT` (0x61) binary types not
migrated to AIP v3.

**Deliverables**:
- Android update: emit `screen_stream_data` / `action_execute` in AIP v3 JSON
- Confirm Node_95 consumes `screen_stream_data` correctly
- Set explicit retirement date for binary types (recommend: 60 days after AIP v3 migration)

---

## Phase 4 — Truth convergence and projection completeness

### PR-M: ProjectionSurfaceBridge universal rollout

**Gap**: TRUTH-001 (MEDIUM)
**Problem**: Not all projection endpoints call `enrich_runtime_projection()`.
Status board surfaces may assemble independent runtime views.

**Deliverables**:
- Audit all projection endpoints in `core/routes/projection.py`
- Ensure every endpoint that returns runtime state calls `enrich_runtime_projection()`
- Remove direct UDM/UCM queries from projection endpoint bodies where found

---

### PR-N: Android-V2 truth reconciliation protocol design

**Gap**: TRUTH-005 / CROSS-002 (MEDIUM, NEW)
**Problem**: Android local state may diverge from V2 outward truth. No reconciliation
protocol defined.

**Design decision required**: Q4 — Does V2 outward truth supersede Android local
state, or are they independent with explicit sync?

**Deliverables** (design PR):
- ADR (Architecture Decision Record) answering Q4
- Protocol specification for truth reconciliation events (if sync approach chosen)
- Or specification for V2 supersession rule (if V2-authoritative approach chosen)

---

## Phase 5 — WebRTC task lifecycle integration

### PR-O: WebRTC-task lifecycle integration

**Gaps**: WEBRTC-001, WEBRTC-002 (HIGH, elevated)
**Problem**: WebRTC operates as an isolated subsystem. Tasks requiring live visual
input from Android devices cannot trigger WebRTC setup through the task lifecycle.

**Design decision required**: Q5 — Is WebRTC-task lifecycle integration a near-term
requirement or long-term capability?

**Deliverables** (if P1 decision):
- Map `screen_stream_start` AIP type to WebRTC session setup in `webrtc_proxy.py`
- Register `Node_95_WebRTC_Receiver` as `VideoStream` capability provider in `CapabilityAssimilationLayer`
- Wire `task_complete` / `task_cancel` to WebRTC session teardown
- TaskEnvelope step type for "acquire video stream from device"

---

## Phase 6 — Compatibility retirement

### PR-P: Legacy dispatch monitoring

**Gap**: COMPAT-007 (LOW, NEW)
**Problem**: `LEGACY_DISPATCH` warnings from sentinel-gated paths are not monitored.
Accidental legacy path usage is invisible in production.

**Deliverables**:
- Add `legacy_dispatch_count` gauge metric to observability surface
- Add `LEGACY_DISPATCH` warning counter per sentinel-gated path
- Alert rule: alert if `legacy_dispatch_count > 0` in production

---

### PR-Q: Legacy compat surface retirement

**Gaps**: COMPAT-001–COMPAT-006, PROTO-007

**Deliverables**:
- Confirm `TaskRouter` / `TaskScheduler` files removed from disk (COMPAT-001)
- Add static analysis guard preventing routing through `CapabilityRegistry` (COMPAT-002)
- Baseline traffic on `/ws/ufo3/` path; retire after 30-day zero-traffic confirmation (PROTO-007)
- Baseline traffic on Android REST compat aliases; set retirement timeline (COMPAT-006)

---

## Complete sequenced roadmap

```
Phase 0 (now)
├── PR-A  Android task_cancel/task_status canonical handlers       [HIGH, P0]
└── PR-B  Android capability ingress wiring                        [HIGH, P0]

Phase 1 (after Phase 0)
├── PR-C  CommandRouter → capability graph wiring                  [MEDIUM, P1]
│         requires: Q1 design decision, PR-B
├── PR-D  ConstellationRuntime DevicePool audit                    [MEDIUM, P2]
└── PR-E  Session migration canonical path unification             [HIGH, P1]
          requires: Q3 design decision

Phase 2 (after Phase 1)
├── PR-F  MeshSessionCoordinator live runtime engine               [HIGH, P1]
│         concurrent with PR-G
├── PR-G  BodyMeshRegistry persistence + event wiring              [MEDIUM, P2]
│         concurrent with PR-F
├── PR-H  DeviceRoleAllocator capability-aware allocation          [MEDIUM, P2]
│         requires: PR-C or PR-B
└── PR-I  Formation capability verification                        [MEDIUM, P2]
          requires: PR-B

Phase 3 (after Phase 2 or in parallel)
├── PR-J  session_migrate/restore AIP v3 promotion                 [HIGH, P1]
│         requires: PR-E
├── PR-K  wake_event AIP v3 promotion                              [MEDIUM, P2]
└── PR-L  AIP v2 binary screen/input migration                     [MEDIUM, P2]

Phase 4 (parallel with Phase 2-3)
├── PR-M  ProjectionSurfaceBridge universal rollout                [MEDIUM, P2]
└── PR-N  Android-V2 truth reconciliation design                   [MEDIUM]
          requires: Q4 design decision

Phase 5 (after Q5 decision)
└── PR-O  WebRTC-task lifecycle integration                        [HIGH if P1]
          requires: Q5 design decision, PR-L

Phase 6 (ongoing)
├── PR-P  Legacy dispatch monitoring                               [LOW, P3]
└── PR-Q  Legacy compat surface retirement                         [LOW, P3]
```

---

## Design decisions that gate roadmap progress

| Decision | Question | Gates |
|----------|----------|-------|
| Q1 | Capability verification: Gate 4 in admissibility chain or pre-filter in CommandRouter? | PR-C |
| Q2 | Does ConstellationRuntime dispatch through CommandRouter? | PR-D (implementation path) |
| Q3 | Canonical session migration path: session_roaming.py or core/routes/sessions.py? | PR-E, PR-J |
| Q4 | Android-V2 truth authority: V2 supersedes Android, or explicit sync events? | PR-N |
| Q5 | WebRTC-task lifecycle integration: near-term (P1) or long-term (DEFER)? | PR-O priority |
| Q6 | AIP v2 binary type sunset date | PR-L retirement schedule |

**Recommendation**: Q1, Q3, and Q4 should be resolved in a single architecture
decision session before Phase 1 begins. These decisions are independent and can
be made in parallel.
