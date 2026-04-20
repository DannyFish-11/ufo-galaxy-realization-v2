# V2 + Android Distributed Runtime Closure Audit

> **Document type**: Canonical runtime audit — reviewability, completeness classification,
> and reviewer checklist.
>
> **Scope**: `DannyFish-11/ufo-galaxy-realization-v2` (V2 control plane, primary)
> and `DannyFish-11/ufo-galaxy-android` (Android device runtime, companion).
>
> **Purpose**: This document answers the question: *"Can the full V2 + Android
> distributed runtime honestly be described as end-to-end runnable, and if not,
> exactly what remains missing?"*

---

## Table of contents

1. [Two-repository system model](#1-two-repository-system-model)
2. [Canonical authority chain](#2-canonical-authority-chain)
3. [Local path vs cross-device path](#3-local-path-vs-cross-device-path)
4. [Distributed participant admission rules](#4-distributed-participant-admission-rules)
5. [Completeness classification](#5-completeness-classification)
6. [Android terminal signal closure (this PR)](#6-android-terminal-signal-closure-this-pr)
7. [Reviewer checklist](#7-reviewer-checklist)

---

## 1. Two-repository system model

The Galaxy distributed system is split across exactly two repositories:

| Repository | Role |
|---|---|
| `ufo-galaxy-realization-v2` | **V2 control plane** — canonical entry, orchestration authority, dispatch spine, participant admission, truth/projection |
| `ufo-galaxy-android` | **Android device runtime** — on-device execution, result uplink, mesh session participation |

### Relationship between the two repos

- V2 is the **single center of authority**. It owns all orchestration decisions.
- Android is a **routable execution participant** — it receives task envelopes dispatched
  by V2, executes them, and returns result/status/cancel signals via WebSocket/AIP v3.
- V2 is not dependent on Android being online; the local execution chain is always available.
- Android becomes a distributed participant only when all admission gates pass
  (see [Section 4](#4-distributed-participant-admission-rules)).

### V2-side dependencies on Android

V2 requires Android only for:
1. **Cross-device task dispatch** via `AndroidBridge.assign_task()`.
2. **Inbound signal reconciliation** via `reconcile_android_execution_signal()`.

Everything else (local execution, staging, mesh coordination, truth/projection) runs
without Android.

### Android-side dependencies on V2

Android requires V2 for:
1. **Task assignment** — tasks arrive as AIP v3 `TASK_ASSIGN` envelopes from V2.
2. **Protocol definitions** — canonical AIP v3 message shapes are defined in V2.

---

## 2. Canonical authority chain

```
main.py                          ← canonical system entry point (never bypassed)
  └─ unified_launcher.py         ← from-source launcher component
       └─ SystemOrchestrator     ← phased pre-check + startup coordination
            └─ DesktopPresenceRuntime   ← session owner, tri-state lifecycle owner
                 └─ OpenClawd           ← cognition + execution decision core
                      ├─ local execution path
                      └─ cross-device path
                           └─ CommandRouter.route_envelope()   ← sole legal cross-device dispatcher
                                └─ SourceDispatchOrchestrator  ← canonical dispatch brain
                                     ├─ _try_android_bridge_dispatch()
                                     │    └─ AndroidBridge.assign_task()
                                     │         └─ DeviceRouter.dispatch_task()
                                     └─ staged_mesh path
                                          ├─ coordinate_mesh_session()
                                          └─ run_live_mesh_session()
```

### Key authority properties

1. **`main.py` is the single canonical entry point** — never bypassed.
2. **`DesktopPresenceRuntime` is the session/lifecycle owner** — Windows/Desktop is
   the center of the network.
3. **`OpenClawd` is the execution decision core** — local/cross-device branching happens here.
4. **`CommandRouter.route_envelope()` is the sole legal cross-device dispatcher** — no
   other component dispatches cross-device tasks.
5. **`SourceDispatchOrchestrator` is the canonical dispatch brain** — it is the
   authoritative module for: mode selection, target selection, dispatch planning, and
   result propagation.

---

## 3. Local path vs cross-device path

### Local execution path

```
OpenClawd.process() [entry_mode = "local"]
  └─ DecisionExecutor.run()
       └─ WindowsExecutionArbiter / CapabilityOrchestrator
            └─ LocalExecutionResult
```

**Properties**:
- Always present; always available
- Does not depend on cross-device toggle or Android/other devices being online
- Is the first-class execution path, not a fallback patch

### Cross-device execution path

```
OpenClawd.process() [entry_mode = "cross_device" or cross_device_dispatched=True]
  └─ CommandRouter.route_envelope()
       └─ cross_device_candidates.resolve_candidates()
            └─ formation_resolver.resolve_formation()
                 └─ DeviceRouter.route_task()
                      └─ WebSocket/NATS → Android / other devices
```

**Properties**:
- Not the default path — requires `GALAXY_CROSS_DEVICE_ENABLED=true`
- Is a **controlled extension** of the local subject, not a parallel system
- Requires passing all four admission gates (see Section 4)

### Key distinction

The system is **not** a peer-to-peer mesh where all devices are equal.
It is a **center-controlled distributed system**: Windows/Desktop is the sole authority,
and Android/other devices are **routable execution surfaces** that are brought in when needed.

---

## 4. Distributed participant admission rules

A device becomes a distributed execution participant only when all four gates pass:

```
Gate 1: GALAXY_CROSS_DEVICE_ENABLED=true      ← gateway-level toggle
Gate 2: SystemMode == DESKTOP_CROSS_DEVICE    ← system-level mode
Gate 3: device.registered                     ← has canonical identity
         AND device.routable                  ← can be reached
         AND device.orchestration_eligible    ← has execution capability
Gate 4: source_runtime_posture == "join_runtime"  ← device has opted in
```

### Gate semantics

| Gate | What it governs | Failure behavior |
|---|---|---|
| **Gateway gate** | Whether cross-device is enabled at all | All cross-device dispatch blocked |
| **System mode gate** | Whether the system is in cross-device orchestration mode | Dispatch falls back to local |
| **Admissibility gates** | Whether the device has identity, reachability, and capability | Device excluded from candidate pool |
| **Posture gate** | Whether the device has explicitly opted into the distributed runtime | Device selected as `control_only`, not as dispatch target |

### Key implication

**"Device online" ≠ "Device is a distributed participant."**

A device may be registered and reachable but still fail the posture gate.
Only when all gates pass does the device enter the canonical distributed execution network.

This is documented in `ANDROID_CONTROL_ONLY_POSTURE_IS_NOT_DISPATCH_TARGET_POLICY`
and `POSTURE_GATE_PRESERVES_BACKWARD_COMPAT_POLICY` in
`core/runtime/source_dispatch_orchestrator.py`.

---

## 5. Completeness classification

### ✅ Fully wired (proven to be live-path correct)

| Capability | Primary module | Evidence |
|---|---|---|
| Canonical system entry | `main.py` → `DesktopPresenceRuntime` → `OpenClawd` | Authority chain is stable and tested |
| Local execution chain | `DecisionExecutor` → `LocalExecutionResult` | Always available; not gated |
| Cross-device dispatcher spine | `CommandRouter.route_envelope()` | Sole dispatch authority; no bypass |
| Dispatch orchestration | `SourceDispatchOrchestrator.orchestrate_source_runtime_dispatch()` | Full end-to-end dispatch decisions |
| Android outbound dispatch | `AndroidBridge.assign_task()` → `DeviceRouter` | Canonical Android dispatch chain |
| Posture gating | `_score_candidate()` rejects `control_only` posture | Tests: `test_android_posture_dispatch_gating.py` |
| Android signal reconciliation | `reconcile_android_execution_signal()` / `reconcile_inbound_message()` | Tests: `test_pr13_post533_android_execution_signal_reconciler.py` |
| Tracking record → terminal phase | `DelegatedExecutionTrackingRuntime` | Tests: PR-13 suite (BA–BD lifecycle tests) |
| staged_mesh → live runtime | `coordinate_mesh_session()` → `run_live_mesh_session()` | Tests: `test_pr32_post533_staged_mesh_executable_closure.py`, `test_prj_live_mesh_runtime_engine.py` |
| Barrier coordination | `LiveMeshRuntimeEngine` barrier phases | Tests: Group B/C/D in `test_prj_live_mesh_runtime_engine.py` |
| Merge / aggregation | `merge_runtime_results()` / `build_merged_runtime_result()` | Tests: `test_pr36_cross_runtime_result_merge.py` |
| **Android terminal signal → ReplayFoundation** | `consume_android_behavioral_result()` + `emit_runtime_event()` | **NEW (this PR)**: `test_v2_android_runtime_closure_audit.py` Group F |

### ⚠️ Partially wired (core path wired; full coverage incomplete)

| Capability | Current state | What remains |
|---|---|---|
| Formation as live runtime substrate | `formation_resolver.resolve_formation()` — static formation only; dispatch-time only | Dynamic rebalance under participant drop is not wired |
| MeshSession coordinator → live session progression | `MeshSessionCoordinatorState` transitions are implemented | Long-running session lifecycle under real workload not exercised |
| Mesh membership evaluation | `mesh_memberships` gate exists; some paths stub | Full membership constraint enforcement under real multi-device scenario |

### 🔲 Contract-first (contract defined; wiring deferred)

| Capability | Contract | What's missing |
|---|---|---|
| Android result → dispatch awaiter correlation | `consume_android_behavioral_result()` docstring: "stable contract (PR-5A) — full behavioral result integration deferred" | Mechanism for dispatch awaiter (e.g. `OpenClawd.process()`) to observe Android task completion |
| Dynamic formation rebalance | `DeviceFormation` contract exists | No runtime engine drives formation updates on participant drop/rejoin |
| Multi-device barrier under real latency | Barrier timeout is "advisory" per `live_mesh_runtime_engine.py` comment | Hard timeout enforcement not yet wired |
| WebRTC → task lifecycle correlation | WebRTC gateway exists | No direct WebRTC signal → canonical task phase mapping |

---

## 6. Android terminal signal closure (this PR)

### The gap

Before this PR, `consume_android_behavioral_result()` in `SourceDispatchOrchestrator`:

1. Extracted signal identity fields from the reconcile outcome.
2. Emitted an event to the **observability sink** (`emit_dispatch_decision_event`).
3. Returned a structured summary dict.

**The gap**: Terminal Android signals (cancelled / error / final_result / timeout)
were **only logged via the observability sink** — they were **not recorded** in the
canonical **ReplayFoundation** truth store. This meant the canonical orchestration
event stream was incomplete: a reviewer or debugging session could not find Android
cancel/failure/completion events in the authoritative event log.

### The fix

This PR adds:

1. **`ANDROID_TERMINAL_SIGNAL_RECORDED_TO_CANONICAL_TRUTH_SENTINEL`** — a policy sentinel
   confirming the gap is closed.
2. **`ANDROID_TERMINAL_SIGNAL_RECORDS_TO_REPLAY_FOUNDATION_POLICY`** — a policy string
   documenting the rule: terminal Android signals MUST be emitted to `ReplayFoundation`.
3. **`_ANDROID_TERMINAL_SIGNAL_KINDS`** — a frozenset defining the four terminal kinds:
   `{"cancelled", "error", "final_result", "timeout"}`.
4. **In `consume_android_behavioral_result()`**: when `was_updated=True` and the signal
   kind is terminal, calls `emit_runtime_event(kind="android_terminal_signal", ...)` so
   the canonical event stream reflects the Android terminal outcome.
5. **`terminal_signal_recorded` key** in the return dict — allows callers to verify
   whether a terminal event was emitted.

### What this fixes and what remains

**Fixed**: Android cancel/failure/result terminal signals now appear in the canonical
ReplayFoundation event stream. Any component that queries `ReplayFoundation.get_events_for_task()`
will find Android terminal events.

**Still contract-first**: The dispatch awaiter (whoever is waiting for the Android task
to complete, e.g. `OpenClawd.process()`) does not yet have a mechanism to observe the
ReplayFoundation event and correlate it back to the original dispatch. That would require
an active poll or callback pattern on the ReplayFoundation. This is documented in the
`consume_android_behavioral_result()` docstring as "deferred to a later PR."

---

## 7. Reviewer checklist

Use this checklist to evaluate whether the full V2 + Android runtime is end-to-end runnable.

### AC1: Does `staged_mesh` truly enter the intended live runtime path?

- [x] `orchestrate_source_runtime_dispatch()` with 2+ active participants returns a
  `SourceDispatchResult` with `mode=staged_mesh`.
- [x] The staged_mesh result carries `action_taken='staged_mesh_coordinated'`.
- [x] The staged_mesh result carries `live_outcome` (PR-J).
- [x] The staged_mesh result carries `live_merged_result` (PR-J).
- [x] `coordinate_mesh_session()` is reachable from the orchestration path.
- [x] `run_live_mesh_session()` is called after `coordinate_mesh_session()`.

**Evidence**: `tests/test_pr32_post533_staged_mesh_executable_closure.py` (Groups J, K),
`tests/test_prj_live_mesh_runtime_engine.py` (Group K),
`tests/test_v2_android_runtime_closure_audit.py` (Group B).

### AC2: Does participant posture/admissibility affect runtime behavior?

- [x] `control_only` posture rejects a candidate from dispatch target selection.
- [x] `join_runtime` posture (or absent) makes a candidate eligible.
- [x] Posture gate is applied during `_score_candidate()`, after readiness and
  participation gates.
- [x] `ANDROID_CONTROL_ONLY_POSTURE_IS_NOT_DISPATCH_TARGET_POLICY` is present.
- [x] Admissibility gates (registered, routable, orchestration_eligible) are tested.

**Evidence**: `tests/test_android_posture_dispatch_gating.py`,
`tests/test_v2_android_runtime_closure_audit.py` (Group C).

### AC3: Are barrier / merge / completion semantics truly exercised?

- [x] Two-participant success → `outcome='completed'`, `success=True`.
- [x] `barrier_released=True` on success.
- [x] Merged result aggregates per-participant outputs.
- [x] `outcome='failed'` when coordinator state is None.
- [x] `success=False` on failed outcome.
- [x] `errors` list is non-empty on failure.
- [x] Graceful degradation: `run_live_mesh_session(None)` returns `outcome='failed'`.

**Evidence**: `tests/test_prj_live_mesh_runtime_engine.py` (Groups B, C, D, E, F, G, H),
`tests/test_pr36_cross_runtime_result_merge.py`,
`tests/test_v2_android_runtime_closure_audit.py` (Groups D, E).

### AC4: Do cancel/failure/result signals correctly affect canonical orchestration?

- [x] Android cancel message → `DelegatedExecutionTrackingRecord` reaches terminal phase.
- [x] Android error message → tracking record updated, terminal.
- [x] Android final_result message → tracking record updated to `completed`.
- [x] **NEW**: `consume_android_behavioral_result()` with terminal signal →
  `ReplayFoundation` event emitted (`kind='android_terminal_signal'`).
- [x] `terminal_signal_recorded=True` in return dict for terminal signals.
- [x] `terminal_signal_recorded=False` for non-terminal (progress) signals.
- [x] `terminal_signal_recorded=False` when `was_updated=False`.
- [ ] **DEFERRED**: Android terminal signal → dispatch awaiter correlation
  (full behavioral result integration). See `consume_android_behavioral_result()`
  docstring.

**Evidence**: `tests/test_pr13_post533_android_execution_signal_reconciler.py` (Groups Z–BD),
`tests/test_v2_android_runtime_closure_audit.py` (Group F).

### AC5: What is fully wired today vs partial vs contract-first?

See [Section 5: Completeness classification](#5-completeness-classification) above.

- [x] Fully wired capabilities are listed with their primary modules.
- [x] Partially wired capabilities are listed with what remains.
- [x] Contract-first capabilities are listed with what's missing.

### AC6: Can the V2 + Android system be described as end-to-end runnable?

**Answer**: **Partially yes, with clear caveats.**

**What is honestly end-to-end runnable today**:
- The V2 local execution chain is fully runnable without Android.
- The staged_mesh coordination path is runnable (V2-local, no real Android needed).
- The Android outbound dispatch chain is wired (V2 → AndroidBridge → DeviceRouter).
- The Android inbound signal chain is wired (Android signal → reconciler → tracking record → ReplayFoundation).

**What is not yet fully closed**:
- **Dispatch awaiter correlation**: when Android completes/fails/cancels a task, the
  original dispatch awaiter does not yet have a mechanism to observe the result and
  close the local execution loop. This is the most important remaining gap.
- **Dynamic formation rebalance**: participant drop/rejoin during live mesh sessions
  is not dynamically rebalanced.
- **Hard barrier timeout**: barrier timeout is advisory, not enforced.

**Honest assessment**:
> The V2 + Android system has a **fully wired control plane and a partially wired
> runtime plane**. The outbound dispatch path (V2 → Android) and the inbound signal
> path (Android → V2 tracking/truth) are both wired. The gap is in the **result
> awaiting loop**: V2 knows Android completed/failed (via ReplayFoundation), but the
> original dispatch caller does not yet automatically observe this and return a final
> result to the user.

---

*This document is produced as part of the "Audit and harden full V2 + Android
distributed runtime closure" PR.  It should be updated whenever the
completeness classification changes.*
