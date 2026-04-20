# V2 + Android Two-Repository System Audit

> **PR Type**: Review / Audit / Hardening PR
>
> **Scope**: Complete two-repository system spanning
> `DannyFish-11/ufo-galaxy-realization-v2` (control/orchestration plane) and
> `DannyFish-11/ufo-galaxy-android` (native execution/participant plane).
>
> **Purpose**: Audit, validate, and determine whether the full end-to-end system
> is actually wired through and can fully run.  This document is the canonical
> review evidence trail for that determination.
>
> **Companion test file**: `tests/test_review_audit_e2e_hardening.py`
>
> **Supersedes**: Nothing — this is an additive review document layered on top of
> `docs/DUAL_REPO_FULL_REAUDIT.md` and `docs/DUAL_REPO_GAP_MATRIX.md`, which
> remain authoritative for gap tracking.

---

## Table of Contents

1. [System Architecture Map](#1-system-architecture-map)
2. [PR Dependency Chain](#2-pr-dependency-chain)
3. [Component-by-Component Wiring Status](#3-component-by-component-wiring-status)
4. [Staged-Mesh → Live Runtime Path](#4-staged-mesh--live-runtime-path)
5. [Participant State Machine](#5-participant-state-machine)
6. [Barrier / Merge / Complete Semantics](#6-barrier--merge--complete-semantics)
7. [Handoff / ACK / Result / Failure Loop](#7-handoff--ack--result--failure-loop)
8. [Formation / Membership / Registry Substrate](#8-formation--membership--registry-substrate)
9. [Failure Path Coverage Matrix](#9-failure-path-coverage-matrix)
10. [Evidence Checklist: "Fully Wired / Fully Runnable"](#10-evidence-checklist-fully-wired--fully-runnable)
11. [What is Proven by V2 Tests vs Depends on Android](#11-what-is-proven-by-v2-tests-vs-depends-on-android)
12. [Open Risks and Reviewer Guidance](#12-open-risks-and-reviewer-guidance)

---

## 1. System Architecture Map

### 1.1 Two-Repository Roles

```
┌───────────────────────────────────────────────────────────────┐
│  ufo-galaxy-realization-v2  (CONTROL + ORCHESTRATION PLANE)   │
│                                                               │
│  ┌─────────────────┐  ┌──────────────────────────────────┐  │
│  │  CapabilityLayer │  │  CommandRouter (sole dispatcher) │  │
│  │  (assimilation,  │  │  ── route_envelope()             │  │
│  │   capability     │  │  ── SourceDispatchOrchestrator   │  │
│  │   graph)         │  │     orchestrate_source_runtime   │  │
│  └─────────────────┘  └──────────────────────────────────┘  │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Mesh Layer                                          │    │
│  │  ── MeshSession (contract)                           │    │
│  │  ── MeshSessionCoordinatorState (contract)           │    │
│  │  ── LiveMeshRuntimeEngine (execution driver)         │    │
│  │  ── MeshAutoEnrollmentService (auto-enroll)          │    │
│  │  ── BodyMeshRegistry (participant registry)          │    │
│  │  ── MeshSessionLifecycleCoordinator (durability)     │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Formation Layer                                     │    │
│  │  ── FormationResolver (static formation at dispatch) │    │
│  │  ── FormationAutoEnrollmentManager (live enrollment) │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Handoff / ACK Contract                              │    │
│  │  ── HandoffEnvelopeV2 (outbound to Android)          │    │
│  │  ── AndroidHandoffResponseEnvelope (inbound from     │    │
│  │     Android: ack / result / failure)                 │    │
│  └──────────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────────┘
                          │  AIP v3 JSON
                          │  WebSocket / REST
                          ▼
┌───────────────────────────────────────────────────────────────┐
│  ufo-galaxy-android  (EXECUTION / PARTICIPANT PLANE)          │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐     │
│  │  Handoff Consumer                                   │     │
│  │  ── HandoffEnvelopeV2 receiver + executor           │     │
│  │  ── ACK / result / failure uplink                   │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐     │
│  │  Device Runtime                                     │     │
│  │  ── GUI automation / screen capture                 │     │
│  │  ── sensor / network execution                      │     │
│  │  ── local task execution                            │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐     │
│  │  Capability Report                                  │     │
│  │  ── device_capabilities AIP type → V2 ingestion     │     │
│  └─────────────────────────────────────────────────────┘     │
└───────────────────────────────────────────────────────────────┘
```

### 1.2 Canonical Data Flow (Happy Path)

```
Android connects via WebSocket
        │
        ▼
galaxy_gateway (V2): device registered in UDM/UCM
        │  triggers
        ▼
MeshAutoEnrollmentService.on_device_registered()
        │  capability reported →
        ▼
CapabilityAssimilationLayer.assimilate_device()
        │  formation enrollment →
        ▼
FormationAutoEnrollmentManager.enroll_device()
        │
        ▼
User task arrives → CommandRouter.route_envelope()
        │  multi-device → staged_mesh mode →
        ▼
orchestrate_source_runtime_dispatch()
        │  coordinate_mesh_session() →
        ▼
MeshSessionCoordinatorState (pending)
        │  run_live_mesh_session() →
        ▼
LiveMeshRuntimeEngine.run()
  Phase 1: Promote staged → active
  Phase 2: Track participants (pending→ready→working)
  Phase 3: Barrier evaluation (wait / release / fail)
  Phase 4: Merge participant results
  Phase 5: Finalise (completed / partial / failed)
        │
        ▼
SourceDispatchResult with live_outcome + live_merged_result
        │
        ▼
HandoffEnvelopeV2 dispatched to each Android participant
        │  (via galaxy_gateway → WebSocket → Android)
        ▼
Android executes task
        │  result / ACK / failure →
        ▼
AndroidHandoffResponseEnvelope received by V2
        │
        ▼
Result surfacing: TaskGraphRuntime / OperatorSurface / ReplayFoundation
```

---

## 2. PR Dependency Chain

### 2.1 Recommended merge order

```
PR-A  device registration / capability ingestion
  │
  ▼
PR-B  UDM/UCM canonical device truth
  │
  ▼
PR-C  registration + attach to BodyMeshRegistry
  │
  ▼
PR-D / PR-E  source dispatch / target takeover contracts
  │
  ▼
PR-F  Android single-device dispatch
  │
  ▼
PR-G  observability / production hooks
  │
  ▼
PR-H  Android native HandoffEnvelopeV2 consumption + ACK/result/failure uplink
  │
  ▼
PR-I  MeshMembership / BodyMeshRegistry auto-write + Formation auto-enrollment
  │
  ▼  ◄── THIS IS THE CRITICAL PATH NODE ──►
PR-J  Live Mesh Runtime Engine + staged_mesh true reachability
```

### 2.2 Critical dependency notes for reviewers

| Dependency | Risk if not satisfied | Evidence in V2 tests |
|------------|----------------------|----------------------|
| **PR-J strongly depends on PR-I** | If participant enrollment, formation membership, and readiness triggers are not closed, PR-J builds on unstable inputs; runtime is fragile | `tests/test_pri_auto_enrollment.py` (56 tests passing) |
| **PR-J benefits from PR-H** | Without Android native HandoffEnvelopeV2 consumption, the live mesh runtime runs on the V2 control side but cannot confirm real device execution or receive real ACK/result/failure signals | `tests/test_prh_android_handoff_v2.py` (103 tests passing) |
| **PR-I depends on PR-C** | Auto-enrollment writes to BodyMeshRegistry; if the registry substrate is not wired, enrollment is in-memory only and does not survive restarts | `tests/test_prc_registration_attach_body_mesh.py` |
| **PR-H depends on PR-31** | HandoffEnvelopeV2 must be a stable contract before Android can consume it; PR-31 provides that contract | `tests/test_pr31_handoff_envelope_v2.py` |
| **PR-J depends on PR-37** | `MeshSessionCoordinatorState` contract from PR-37 is the core data model that `LiveMeshRuntimeEngine` operates on | `tests/test_pr37_mesh_session_coordinator.py` |

### 2.3 What happens if you run PR-J without PR-I

The `LiveMeshRuntimeEngine` can still run (it is isolated from the enrollment pipeline), but:

1. `coordinator_state.participants` may be empty or stale (no auto-enrollment wrote them)
2. Barrier evaluation will fail (no participants arrived)
3. `staged_mesh` path will produce `outcome=failed` with `reason=promotion_failed`
4. The system will not be "actually wired" — it will be control-side self-consistent but not driving real participant execution

**Reviewer check**: Run `test_review_audit_e2e_hardening.py::TestSectionB_StagedMeshProductionPath::test_b4_staged_mesh_without_enrollment_degrades_cleanly` to verify this degradation path is explicit.

---

## 3. Component-by-Component Wiring Status

### 3.1 V2 Control Plane Components

| Component | Module | PR | Status | Tests |
|-----------|--------|----|--------|-------|
| CommandRouter | `core/command_router.py` | PR-521 | ✅ Stable; sole dispatcher | `test_command_unified_canonical_spine.py` |
| CapabilityAssimilationLayer | `core/capability_assimilation.py` | PR-509 | ✅ Stable | `test_pr509_capability_network_runtime_assimilation.py` |
| TruthIntegrationLayer | `core/truth_integration_layer.py` | PR-1 | ✅ Wired; coverage incomplete | `test_pr1_truth_integration_layer.py` |
| HandoffEnvelopeV2 | `contracts/handoff_envelope_v2.py` | PR-31 | ✅ Stable | `test_pr31_handoff_envelope_v2.py` |
| AndroidHandoffResponseEnvelope | `contracts/android_handoff_response.py` | PR-H | ✅ Stable | `test_prh_android_handoff_v2.py` |
| MeshAutoEnrollmentService | `core/mesh/mesh_auto_enrollment.py` | PR-I | ✅ Working | `test_pri_auto_enrollment.py` |
| BodyMeshRegistry | `core/mesh/body_mesh_registry.py` | PR-I | ✅ In-process only (see MESH-003) | `test_pri_auto_enrollment.py` |
| FormationAutoEnrollmentManager | `core/device_formation/formation_auto_enrollment.py` | PR-I | ✅ Working | `test_pri_auto_enrollment.py` |
| MeshSessionCoordinatorState | `contracts/mesh_session_coordinator.py` | PR-37 | ✅ Stable | `test_pr37_mesh_session_coordinator.py` |
| LiveMeshRuntimeEngine | `core/mesh/live_mesh_runtime_engine.py` | PR-J | ✅ Working | `test_prj_live_mesh_runtime_engine.py` |
| SourceDispatchOrchestrator (staged_mesh path) | `core/runtime/source_dispatch_orchestrator.py` | PR-J | ✅ Wired | `test_prj_live_mesh_runtime_engine.py` Group K |
| MeshSessionLifecycleCoordinator | `core/mesh/mesh_session_lifecycle.py` | PR-1 | ✅ Stable | `test_pr1_mesh_session_durable_foundation.py` |

### 3.2 Android Execution Plane Components (from V2 perspective)

| Component | V2 Interface | Status | V2 Evidence |
|-----------|-------------|--------|-------------|
| Android device connection | WebSocket at `galaxy_gateway` | ✅ Protocol defined | `test_prh_android_handoff_v2.py` |
| HandoffEnvelopeV2 dispatch to Android | `HandoffEnvelopeV2.to_aip_task_message()` | ✅ Contract stable | `test_pr31_handoff_envelope_v2.py` |
| ACK signal from Android | `AndroidHandoffResponseEnvelope` (kind=ack) | ✅ Contract stable | `test_prh_android_handoff_v2.py` |
| Result signal from Android | `AndroidHandoffResponseEnvelope` (kind=result) | ✅ Contract stable | `test_prh_android_handoff_v2.py` |
| Failure signal from Android | `AndroidHandoffResponseEnvelope` (kind=failure) | ✅ Contract stable | `test_prh_android_handoff_v2.py` |
| Capability report from Android | `device_capabilities` AIP type → `CapabilityAssimilationLayer` | ⚠️ PARTIAL (CROSS-004) | Not confirmed end-to-end |
| Real device E2E test | None in V2 | ❌ Missing (CROSS-003) | No real-device test |

### 3.3 Known Gaps (from DUAL_REPO_GAP_MATRIX.md)

The following HIGH-severity gaps from `DUAL_REPO_GAP_MATRIX.md` directly affect the "fully runnable" claim:

| Gap ID | Severity | Affects | Summary |
|--------|----------|---------|---------|
| MESH-001 | HIGH | staged_mesh live path | No live coordinator engine was the gap; now addressed by PR-J `LiveMeshRuntimeEngine` |
| MESH-002 | HIGH | staged_mesh live path | `MeshSessionStatus` transitions now driven by `LiveMeshRuntimeEngine` |
| PROTO-002 | HIGH | Android control protocol | `task_cancel` / `task_status` still catch-all (`_handle_forward_log`) |
| CROSS-001 | HIGH | Android canonical chain | Android-side admission chain not confirmed to be canonical |
| CROSS-003 | MEDIUM | E2E validation | No confirmed E2E test with real connected Android devices |

---

## 4. Staged-Mesh → Live Runtime Path

### 4.1 Entry points (production paths)

The `staged_mesh` path is entered via:

```python
# Path 1: Full orchestration entry
orchestrate_source_runtime_dispatch(
    trace_id=...,
    mesh_session=<MeshSession dict>,
    ...
)
# → SourceDispatchMode.staged_mesh
# → coordinate_mesh_session()
# → run_live_mesh_session()
# → LiveMeshRuntimeEngine.run()
```

```python
# Path 2: Direct engine entry
from core.mesh.live_mesh_runtime_engine import run_live_mesh_session
result = run_live_mesh_session(coordinator_state, participant_results={...})
```

```python
# Path 3: Via mesh_session_coordinator convenience wrapper
from core.mesh.mesh_session_coordinator import run_live_mesh_session
result = run_live_mesh_session(coordinator_state, ...)
```

```python
# Path 4: Via core.runtime re-exports
from core.runtime import run_live_mesh_session
result = run_live_mesh_session(coordinator_state, ...)
```

All 4 paths converge on `LiveMeshRuntimeEngine.run()`.

### 4.2 Staged → Active promotion requirements

For `staged_mesh` to advance to `active`, the coordinator state MUST:

1. Have `session_id` set (non-empty)
2. Have at least one participant in `participants` list
3. Coordinator `status` starts as `pending`

If promotion fails (no participants, no session_id), the engine returns `outcome=failed` with `errors=["promotion_failed"]`.

### 4.3 Reviewer check: is staged_mesh entering the REAL production path?

**Yes**, as of PR-J. Evidence:

1. `core/runtime/source_dispatch_orchestrator.py` line ~2563-2654 contains the `staged_mesh` dispatch branch
2. The branch calls `coordinate_mesh_session()` then `run_live_mesh_session()` (not a stub or plan-only path)
3. The result carries `action_taken='staged_mesh_coordinated'` (not `'plan_prepared'`)
4. PR-J sentinel `LIVE_MESH_RUNTIME_ENGINE_ORCHESTRATOR_PR_J_SENTINEL` is present in the module

Test evidence: `tests/test_prj_live_mesh_runtime_engine.py::TestGroupK_OrchestratorPRJ`

---

## 5. Participant State Machine

### 5.1 State model

```
                    ┌─────────────┐
                    │   (absent)  │
                    └──────┬──────┘
                           │ register_participant()
                           ▼
                    ┌─────────────┐
                    │   pending   │
                    └──────┬──────┘
                           │ update_participant_status("ready")
                           ▼
                    ┌─────────────┐
                    │    ready    │
                    └──────┬──────┘
                           │ update_participant_status("working")
                           ▼
                    ┌─────────────┐
                    │   working   │
                    └──────┬──────┘
               ┌───────────┴──────────────┐
               │                          │
               ▼                          ▼
        ┌─────────────┐          ┌─────────────────┐
        │  completed  │          │     waiting     │
        └─────────────┘          └────────┬────────┘
                                          │ (barrier evaluation)
                                          ▼
                                 ┌─────────────────┐
                                 │  failed/offline │
                                 └─────────────────┘
```

### 5.2 State → Runtime behavior mapping

| Participant state | Effect on barrier | Effect on merge | Effect on completion |
|-------------------|-------------------|-----------------|---------------------|
| `pending` | Not counted as "arrived" | Not included in merge | Cannot contribute to completed |
| `ready` | Not counted as "arrived" | Not included in merge | Cannot contribute to completed |
| `working` | Not counted as "arrived" | Not included in merge | Cannot contribute to completed |
| `waiting` | Counted as "waiting at barrier" | Not included in merge | Barrier not satisfied |
| `completed` | Counted as "arrived" | Included in merge | Contributes to completed set |
| `failed` | Counted as failed | Excluded from successful merge | Contributes to failed set |
| `offline` | Counted as dropped | Excluded from merge | Contributes to failed set |

### 5.3 State transitions driven by LiveMeshRuntimeEngine

In Phase 2 (`_track_participants_working`), the engine transitions all `pending` participants to `working`. In Phase 5 (`_finalise_coordinator_state`), the engine sets participants to `completed` or `failed` based on whether their result was provided and successful.

---

## 6. Barrier / Merge / Complete Semantics

### 6.1 Barrier lifecycle

```
Barrier created with status=open / unknown
        │
        ▼
Phase 3: _evaluate_barrier()
  ┌─────────────────────────────────────┐
  │ barrier_posture == "none"?          │─── YES ──→ status=not_required → released=True
  └─────────────────────────────────────┘
        │ NO
        ▼
  ┌─────────────────────────────────────┐
  │ All expected devices arrived?       │─── YES ──→ status=released → released=True
  └─────────────────────────────────────┘
        │ NO
        ▼
  ┌─────────────────────────────────────┐
  │ Partial arrival (some waiting)?     │─── YES ──→ status=waiting → released=False
  └─────────────────────────────────────┘
        │ NO (no participants at all)
        ▼
  status=failed → released=False
```

### 6.2 Barrier failure semantics

When barrier fails (`status=failed`):
- If `participant_results` is empty → `LiveMeshRunResult(outcome='failed', success=False)`
- If some results exist → Phase 4 (merge) still runs → `outcome='partial'`

### 6.3 Merge semantics

Merge is **order-independent** and **last-writer-wins** on key conflicts. The merged dict always contains:

| Key | Type | Description |
|-----|------|-------------|
| `_participants` | `list[str]` | List of device_ids that contributed |
| `_merge_timestamp` | `float` | Unix timestamp of merge |
| `<device_id>` | `any` | Per-device result (for non-dict scalar results) |
| `<key>` | `any` | Per-key result (for dict results, merged flat) |

### 6.4 Completion outcome semantics

| `outcome` | `success` | Meaning |
|-----------|-----------|---------|
| `completed` | `True` | All participants completed with `success=True` |
| `partial` | `True` | At least one participant completed; others failed/missing |
| `failed` | `False` | No participants completed; or promotion failed |

---

## 7. Handoff / ACK / Result / Failure Loop

### 7.1 Outbound path (V2 → Android)

```python
# HandoffEnvelopeV2 is the V2 → Android contract
envelope = HandoffEnvelopeV2(
    handoff_id=...,
    task_id=...,
    device_id=...,      # target Android device
    task_payload=...,
    source_runtime_posture=...,
)
aip_message = envelope.to_aip_task_message()
# → dispatched via galaxy_gateway WebSocket to Android
```

Key fields that Android MUST handle:
- `handoff_id` — correlation ID for ACK/result/failure
- `task_payload` — the task content
- `ack_expected` — whether V2 expects an explicit ACK
- `result_expected` — whether V2 expects a result signal

### 7.2 Inbound path (Android → V2)

```python
# Android sends ACK, result, or failure back as AIP messages
# V2 parses via AndroidHandoffResponseEnvelope:
from contracts.android_handoff_response import extract_handoff_response_envelope

envelope = extract_handoff_response_envelope(raw_message)
# envelope.kind: HandoffResponseKind.ack | .result | .failure
# envelope.handoff_id: correlates back to the outbound HandoffEnvelopeV2
# envelope.is_terminal(): True for result/failure
```

### 7.3 Closed-loop wiring status

| Signal | V2 side | Android side | Closed? |
|--------|---------|--------------|---------|
| Dispatch (V2 → Android) | `HandoffEnvelopeV2.to_aip_task_message()` | HandoffEnvelopeV2 consumer in Android | ⚠️ Contract defined; Android consumption confirmed at contract level by PR-H tests |
| ACK (Android → V2) | `from_android_ack_message()` | Android ACK emitter | ⚠️ V2 parse tested; Android ACK timing not tested in V2 |
| Result (Android → V2) | `from_android_result_message()` | Android result emitter | ⚠️ V2 parse tested; Android result not tested in V2 |
| Failure (Android → V2) | `from_android_failure_message()` | Android failure emitter | ⚠️ V2 parse tested; Android failure not tested in V2 |

**Conclusion**: The handoff/ACK/result/failure loop is **contractually closed** in V2. The Android side is confirmed at protocol contract level by PR-H tests. However, **no real-device E2E test exists** that runs the full loop end-to-end (CROSS-003).

---

## 8. Formation / Membership / Registry Substrate

### 8.1 Auto-enrollment chain

```
on_device_registered(device_id)
        │
        ├─ if capabilities empty → deferred
        │
        └─ else → enroll_to_registry() → BodyMeshRegistry.register()
                          │
                          ▼
                   derive_mesh_membership() → MeshMembership
                          │
                          ▼
                   formation_manager.enroll_device()
                          │
                          ├─ first device → role=primary_execution
                          └─ subsequent → role=support

on_capability_reported(device_id, capabilities)
        │ if auto_enroll_on_capability=True
        └─ triggers enrollment (if deferred) or updates roles

on_readiness_confirmed(device_id)
        └─ triggers enrollment (regardless of auto_enroll_on_capability)
```

### 8.2 Substrate limitations (from DUAL_REPO_GAP_MATRIX.md)

| Gap | Impact |
|-----|--------|
| MESH-003: BodyMeshRegistry in-process only | If V2 restarts, all enrolled participants are lost |
| MESH-004: DeviceRoleAllocator not capability-aware | Role assignment may not match device capability profile |
| MESH-006: Formation not dynamically rebalanced | If a device disconnects mid-session, formation is stale |

---

## 9. Failure Path Coverage Matrix

### 9.1 Failure scenarios and V2 behavior

| Scenario | Detected by | V2 Behavior | Test Evidence |
|----------|-------------|-------------|---------------|
| No participants enrolled | `LiveMeshRuntimeEngine._promote_to_active()` | `outcome=failed`, `errors=['promotion_failed']` | `test_prj::TestGroupD::test_d2` |
| All participants dropped before run | `_track_participants_working` + `_evaluate_barrier` | `outcome=failed` | `test_prj::TestGroupJ::test_j2` |
| Partial participant drop | `_finalise_coordinator_state` | `outcome=partial` | `test_prj::TestGroupJ::test_j1` |
| All participants report `success=False` | `_finalise_coordinator_state` | `outcome=failed` | `test_prj::TestGroupI::test_i3` |
| Some participants report `success=False` | `_finalise_coordinator_state` | `outcome=partial` | `test_prj::TestGroupI::test_i2` |
| Barrier not satisfied (partial arrival) | `_evaluate_barrier` | `barrier_released=False`, `outcome=partial/failed` | `test_prj::TestGroupG::test_g4` |
| Barrier never satisfied (no participants) | `_evaluate_barrier` | `barrier_released=False`, `outcome=failed` | `test_prj::TestGroupG::test_g5` |
| Garbage input to engine | `LiveMeshRuntimeEngine.run()` exception guard | Returns `LiveMeshRunResult(outcome='failed')` | `test_prj::TestGroupD::test_d7`, `TestGroupJ::test_j4` |
| Coordinator state is None | Engine None-check | `outcome=failed`, `errors=['coordinator_state_is_none']` | `test_prj::TestGroupD::test_d1` |
| staged_mesh with no mesh_session | `orchestrate_source_runtime_dispatch` | Does not enter staged_mesh branch | `test_prj::TestGroupK::test_k4` |
| Android ACK timeout (V2 side) | Not yet modeled in V2 | **GAP**: V2 does not track handoff correlation or timeout | CROSS-003 |
| Android device disconnect mid-session | `drop_participant()` API available | Caller must invoke; V2 not auto-triggered | MESH-006 |

### 9.2 Failure paths that need improvement (for future PRs)

1. **ACK/result timeout tracking**: V2 dispatches `HandoffEnvelopeV2` but does not correlate ACK/result timing. If Android never sends a result, V2 has no timeout-based failure path.
2. **Mid-session device disconnect**: `drop_participant()` exists but is not automatically called when a WebSocket disconnects during an active mesh session.
3. **Merge conflict**: Current merge is last-writer-wins; no explicit conflict resolution for semantic conflicts in task results.

---

## 10. Evidence Checklist: "Fully Wired / Fully Runnable"

The following checklist captures the evidence required to claim the system is
"fully wired" and "fully runnable". Each item states its current status.

### Control Plane (V2)

- [x] CommandRouter is the sole cross-device dispatcher (`test_command_unified_canonical_spine.py`)
- [x] CapabilityAssimilationLayer ingests both node and device capabilities (`test_pr509_*`)
- [x] MeshAutoEnrollmentService auto-enrolls devices into BodyMeshRegistry (`test_pri_auto_enrollment.py`)
- [x] FormationAutoEnrollmentManager assigns roles at enrollment time (`test_pri_auto_enrollment.py`)
- [x] HandoffEnvelopeV2 contract is stable and serialisable (`test_pr31_handoff_envelope_v2.py`)
- [x] AndroidHandoffResponseEnvelope parses ACK/result/failure from Android (`test_prh_android_handoff_v2.py`)
- [x] `staged_mesh` dispatch enters `LiveMeshRuntimeEngine` (not a plan-only stub) (`test_prj::TestGroupK`)
- [x] LiveMeshRuntimeEngine drives staged→active→barrier→merge→complete lifecycle (`test_prj::TestGroupL`)
- [x] Participant state transitions are tracked and affect barrier/merge decisions (`test_prj::TestGroupF`, `TestGroupG`)
- [x] Barrier semantics: released on full arrival, waiting on partial, failed on timeout (`test_prj::TestGroupG`)
- [x] Merge aggregates per-participant results with stable semantics (`test_prj::TestGroupH`)
- [x] `outcome=completed/partial/failed` is correctly determined and returned (`test_prj::TestGroupI`)
- [x] Failure paths produce explicit errors list, not silent failures (`test_prj::TestGroupJ`)
- [x] MeshSessionLifecycleCoordinator durably persists session lifecycle (`test_pr1_mesh_session_durable_foundation.py`)

### Execution Plane (Android) — V2 Contract Evidence

- [x] HandoffEnvelopeV2 can be serialised to AIP task message for dispatch (`test_pr31_handoff_envelope_v2.py`)
- [x] ACK parsing: `from_android_ack_message()` produces correct envelope (`test_prh_android_handoff_v2.py`)
- [x] Result parsing: `from_android_result_message()` produces correct envelope (`test_prh_android_handoff_v2.py`)
- [x] Failure parsing: `from_android_failure_message()` produces correct envelope (`test_prh_android_handoff_v2.py`)
- [ ] **MISSING**: Real-device E2E test running complete dispatch → Android → result loop (CROSS-003)
- [ ] **MISSING**: Confirmed automatic capability ingestion from Android into `CapabilityAssimilationLayer` (CROSS-004)
- [ ] **MISSING**: Confirmed ACK/result correlation with `handoff_id` at runtime (CROSS-003)

### Integration / Cross-Cutting

- [x] `orchestrate_source_runtime_dispatch()` enters staged_mesh branch with real coordinator + engine call
- [x] `run_live_mesh_session()` re-exported through `core.runtime`, `core.mesh.mesh_session_coordinator` (accessible from production call sites)
- [x] Participant enrollment chain: device_registered → capability_reported → enrolled → formation assigned
- [ ] **MISSING**: Dynamic formation rebalancing when device disconnects mid-session (MESH-006)
- [ ] **MISSING**: BodyMeshRegistry persistence across restarts (MESH-003)
- [ ] **MISSING**: Android-side canonical admission chain confirmed (CROSS-001)

### Summary Score

| Category | Passed | Total | Status |
|----------|--------|-------|--------|
| V2 Control Plane | 14 | 14 | ✅ FULLY WIRED |
| Android Contract (V2-side) | 4 | 7 | ⚠️ PARTIALLY WIRED |
| Integration | 3 | 6 | ⚠️ PARTIALLY WIRED |

**Overall**: The V2 control plane is **fully wired** as of PR-J. The Android execution plane is **contractually defined** but **not confirmed E2E with real devices**. The system can run in production configuration within V2 tests; the Android-side closing loop depends on the Android repo implementation matching the V2 contracts.

---

## 11. What is Proven by V2 Tests vs Depends on Android

### Proven by V2 tests alone

| Claim | Test | Confidence |
|-------|------|------------|
| `staged_mesh` enters `LiveMeshRuntimeEngine` (not a stub) | `test_prj::TestGroupK::test_k2` | HIGH |
| Participant state transitions occur correctly | `test_prj::TestGroupF` (13 tests) | HIGH |
| Barrier releases when all participants arrive | `test_prj::TestGroupG::test_g2`, `test_g3` | HIGH |
| Barrier does NOT release on partial arrival | `test_prj::TestGroupG::test_g4`, `test_g7` | HIGH |
| Merge aggregates all participant results | `test_prj::TestGroupH` (6 tests) | HIGH |
| `outcome=completed` when all participants succeed | `test_prj::TestGroupI::test_i1` | HIGH |
| `outcome=partial` when some participants fail | `test_prj::TestGroupI::test_i2` | HIGH |
| `outcome=failed` when all participants fail | `test_prj::TestGroupI::test_i3` | HIGH |
| Failure paths produce explicit errors | `test_prj::TestGroupJ` (7 tests) | HIGH |
| HandoffEnvelopeV2 serialises correctly | `test_pr31_*` | HIGH |
| ACK/result/failure parsing from Android messages | `test_prh_*` | HIGH |
| Auto-enrollment from device registration + capability | `test_pri_*` | HIGH |
| Formation auto-enrollment assigns correct roles | `test_pri_*` | HIGH |
| Full lifecycle staged→active→barrier→merge→completed | `test_prj::TestGroupL::test_l1` | HIGH |

### Requires Android repo for full confidence

| Claim | What is missing | Risk |
|-------|-----------------|------|
| Android actually receives and executes HandoffEnvelopeV2 | No V2-side test can confirm Android execution | HIGH |
| Android sends ACK/result in real protocol timing | No E2E test with real device (CROSS-003) | HIGH |
| Android capability report reaches `CapabilityAssimilationLayer` | CROSS-004 gap: auto-wiring not confirmed | MEDIUM |
| Android task admission uses canonical chain | CROSS-001: Android-side admission not audited | HIGH |
| Full session flow: dispatch → ACK → execute → result → V2 completion | No real-device E2E test | HIGH |

### Reviewer instruction

A reviewer should consider the system:
- **"V2 internally runnable"** — the V2 control plane orchestration is fully exercised by tests
- **"Fully end-to-end runnable"** — only after CROSS-001, CROSS-003, CROSS-004 are addressed with real-device tests

---

## 12. Open Risks and Reviewer Guidance

### 12.1 High-confidence production-ready claims

1. `staged_mesh` dispatch in V2 no longer stops at "plan prepared" — it calls `LiveMeshRuntimeEngine.run()` and returns a real orchestration result.
2. Participant enrollment (PR-I) + live mesh execution (PR-J) are both working and tested independently.
3. The handoff/ACK/result/failure contract is stable and both sides are contractually defined.

### 12.2 Areas requiring further hardening

| Risk | Severity | Suggested action |
|------|----------|-----------------|
| BodyMeshRegistry in-memory only | MEDIUM | Add persistence layer (MESH-003) |
| No ACK/result timeout in V2 | MEDIUM | Add handoff correlation tracker with configurable timeout |
| Formation not rebalanced on mid-session disconnect | MEDIUM | Wire WebSocket disconnect event to `drop_participant()` (MESH-006) |
| Android canonical admission chain not verified | HIGH | Android repo audit (CROSS-001) |
| No real-device E2E test | HIGH | Add to Android repo or cross-repo CI (CROSS-003) |

### 12.3 Key files for reviewer navigation

```
contracts/mesh_session_coordinator.py      # MeshSessionCoordinatorState + all status enums
contracts/handoff_envelope_v2.py           # V2 → Android dispatch contract
contracts/android_handoff_response.py      # Android → V2 result contract
core/mesh/live_mesh_runtime_engine.py      # PR-J execution driver (the runtime brain)
core/mesh/mesh_session_coordinator.py      # Convenience wrappers + re-exports
core/mesh/mesh_auto_enrollment.py          # PR-I auto-enrollment service
core/runtime/source_dispatch_orchestrator.py  # staged_mesh dispatch path (line ~2563)
tests/test_prj_live_mesh_runtime_engine.py   # 78 tests for PR-J
tests/test_prh_android_handoff_v2.py         # 103 tests for PR-H
tests/test_pri_auto_enrollment.py            # 56 tests for PR-I
tests/test_review_audit_e2e_hardening.py     # THIS PR: integration audit tests
```

### 12.4 How to quickly verify the system is wired

```bash
# Run all three PR core test suites
pytest tests/test_prj_live_mesh_runtime_engine.py tests/test_prh_android_handoff_v2.py tests/test_pri_auto_enrollment.py -v

# Run this PR's audit/hardening test suite
pytest tests/test_review_audit_e2e_hardening.py -v
```

All tests should pass. Any failure indicates a regression in the claimed wiring.

---

*Document generated as part of the review/audit/hardening PR for the complete V2 + Android system. Last updated against codebase state including PR-J (Live Mesh Runtime Engine).*
