# Terminal Dual-Repository Architecture Validation and Reconciliation Planning Audit

> **Status**: FINAL — Terminal audit before implementation  
> **Repositories**: `DannyFish-11/ufo-galaxy-realization-v2` (center) × `DannyFish-11/ufo-galaxy-android` (participant)  
> **Method**: Code-only traversal of both repositories. No prior audits, design docs, or PR descriptions accepted as evidence unless verified by real importable code paths.  
> **Date**: 2026-04-30  
> **Supersedes**: `DEEP_RECONCILIATION_AUDIT_2026.md`, `CENTER_DISTRIBUTED_SYSTEM_FINAL_VERDICT.md`, `COMPLETE_DUAL_REPO_SYSTEM_AUDIT_2026.md`  
> **Companion**: `FINAL_VERDICT_CLASSIFICATION_TABLE.md` (裁决表), `final_validation_probe.py` (probe script)

---

## Bottom-Line Summary (Read First)

The dual-repo system is a **real, runnable, center-distributed runtime**. It can execute tasks end-to-end on the confirmed nominal path today. The 14+ authority-closure modules (V1–V6, L1–L4, A1–A4) are architecturally real and correct, but several of them form a **split-brain**: they declare mandatory authority over execution paths they do not actually intercept at runtime.

The **three critical split-brain relationships** are:

| Module | Declared role | Actual wiring |
|---|---|---|
| V3 `canonical_dispatch_slot_authority` | MUST gate all cross-device dispatch (10 legality dimensions) | **Not called by `CommandRouter`** |
| V4 `unified_orchestration_spine` | MUST be entered by all execution modes | **Not called by `OpenClawd.process()` or `CommandRouter`** |
| V1 `unified_continuity_legality_authority` | MUST gate all inbound-action paths | **Only reached via V3, which is itself not on hot path** |

The four authority modules that **are genuinely on the hot path**:

| Module | Hot path role |
|---|---|
| V2 `task_result_canonical_truth_chain` | 4-step truth chain on `task_result` processing |
| V5 `canonical_group_completion_closure` | Group/delegated completion terminal semantics |
| CC `canonical_completion_ingress` | Future-based awaiter unblock on every result |
| A1 `android_participant_truth_ingress` | Participant truth reconciliation per `task_result` |

The proposed final integrated architecture is **correct in direction** but needs precision corrections in three areas: (1) V4 must not be forced as a synchronous per-request hot-path gate — it should govern a specific outer orchestration layer; (2) V3's slot evaluation should be wired into `CommandRouter` at the dispatch pre-check point, not as a full replace of `CommandRouter`; (3) the participant model naming must be generalized away from `android_` prefixed authority semantics to preserve non-Android-exclusive participant architecture.

---

## Section 1: Re-Validation of the Real Dual-Repo System from Code

### 1.1 True Center Runtime Identity

Confirmed from code traversal of `ufo-galaxy-realization-v2`:

| Identity component | Module | Confirmed by |
|---|---|---|
| **System startup authority** | `main.py` → `core/system_orchestrator.py` | `SystemOrchestrator.run_startup_sequence()` 7-phase sequence |
| **Cognitive entry point** | `core/openclawd.py` `OpenClawd.process()` | Module docstring, Stage 1-4 structure, `_determine_execution_path()` |
| **LLM cognitive path** | `core/unified/llm_router.py` → `core/multi_llm_router.py` | Import chain in `openclawd.py` lazy init |
| **Cross-device dispatch substrate** | `core/command_router.py` `CommandRouter.route_envelope()` | `COMMAND_ROUTER_ORCHESTRATION_AUTHORITY` sentinel, docstring |
| **Android protocol bridge** | `galaxy_gateway/android_bridge.py` + message handlers | `android_bridge.handle_task_result()` |
| **Task lifecycle truth** | `core/task_lifecycle.py` + `core/canonical_completion_ingress.py` | Future-based completion in `canonical_completion_ingress.py` |
| **Device presence / registry** | `core/device_registry.py`, `core/attached_runtime_session_registry.py` | Module declarations |
| **Completion ingress** | `core/canonical_completion_ingress.py` | `notify()`, `complete_pending_dispatch()` |

The center is a **Windows-first, FastAPI-hosted, center-governed distributed runtime**. Its cognitive root is `OpenClawd.process()`. Its dispatch root is `CommandRouter.route_envelope()`. These two modules form the true spine of the system.

### 1.2 True Participant Runtime Identity (Android Repo)

Confirmed from code traversal of `ufo-galaxy-android` (`app/src/main/java/com/ufo/galaxy/`):

| Identity component | File/Module | Evidence |
|---|---|---|
| **WebSocket lifecycle** | `service/GalaxyConnectionService.kt` (161 KB) | Central connection service, handles all WS state transitions |
| **AIP v3 protocol client** | `network/GalaxyWebSocketClient.kt` (69 KB) | Full AIP v3 wire implementation |
| **On-device UI automation** | `service/AccessibilityActionExecutor.kt` | Accessibility-based touch/input execution |
| **On-device autonomous execution** | `local/AutonomousExecutionPipeline.kt` | Multi-step on-device task pipeline |
| **Handoff/takeover execution** | `agent/AgentRuntimeBridge.kt`, `agent/DelegatedTakeoverExecutor.kt` | Delegated runtime host role |
| **Readiness self-report** | `service/ReadinessChecker.kt` | Reports to center; does not govern dispatch |
| **Multi-device coordination surface** | `coordination/MultiDeviceCoordinator.kt` | Coordinates with sibling devices |
| **Protocol model layer** | `model/AipModels.kt` (103 KB) | Full AIP v3 data model |
| **Session management** | `session/` directory | Per-device session state |
| **On-device inference** | `inference/` directory | MobileVLM, SeeClick integration |
| **On-device memory** | `memory/` directory | Local task/execution history |
| **Planning** | `planner/` directory | On-device goal decomposition |

**Conclusion**: Android is not a dumb executor. It has on-device planning, inference, memory, and session management. But it is architecturally a **participant** that receives center-dispatched tasks and reports results. It does not hold dispatch authority, session truth, or completion authority.

### 1.3 The True Local Execution Chain

Confirmed chain from code:

```
OpenClawd (routing authority)
└─ _determine_execution_path() → "local"
      └─ DecisionExecutor (Windows API layer)
            └─ HybridExecutionArbiter (three-level fallback: A2A → GUI → VLM)
                  └─ LocalExecutionResult
                        └─ OpenClawd feedback
                              └─ Memory backflow / Projection
```

- `local_execution_chain.py` documents this as the canonical local chain.
- `HybridExecutionArbiter` in `hybrid_executor.py` is explicitly classified as a **fallback execution helper**, NOT a parallel authority.
- `hybrid_execute` protocol declaration exists but is the one mechanism that the prior audit flagged as possibly dead. **Verified**: the protocol concept is embedded in `hybrid_execution_policy.py` and `hybrid_orchestration_continuity.py` but does not have a dedicated dispatcher call — local hybrid execution goes through `HybridExecutionArbiter` which is correct.

### 1.4 The True Cross-Device Execution Chain

Confirmed chain from code:

```
OpenClawd.process()
└─ _determine_execution_path() → "cross_device" | "hybrid"
      └─ CommandRouter.route_envelope()
            └─ TaskEnvelope stamped with RemoteExecutionMode
                  └─ galaxy_gateway/android_bridge.py
                        └─ WebSocket → Android GalaxyConnectionService
                              └─ EdgeExecutor / AgentRuntimeBridge / AutonomousExecutionPipeline
                                    └─ GalaxyWebSocketClient.sendJson(goal_execution_result)
                                          └─ android_bridge.handle_task_result()
                                                └─ run_task_result_truth_chain()
                                                      └─ CanonicalCompletionIngress.notify()
```

Evidence for each link confirmed. This chain is real and runnable.

**Gap confirmed at `run_task_result_truth_chain()`**: The four steps inside the truth chain are each wrapped in `try/except`, making them best-effort. `is_truth_chain_complete = False` is only a warning, not a hard block. This is the one structural softness in the completion chain.

### 1.5 Delegated / Handoff / Takeover Flows

Confirmed from code:

```
Delegated flow:
  center dispatches → android_bridge.handle_handoff_envelope_v2()
    → AndroidDelegatedRuntimeLifecycleCoordinator.on_handoff_dispatched()
      → android_participant_session_state.py (session record creation)
      → DelegatedRuntimeExecutionTracker (V2 tracking)

Takeover response:
  Android → android_bridge.handle_takeover_response()
    → AndroidDelegatedRuntimeLifecycleCoordinator.on_takeover_response()
      → takeover_tracking.py

Reconciliation signal:
  Android → android_bridge.handle_reconciliation_signal()
    → AndroidDelegatedRuntimeLifecycleCoordinator.on_reconciliation_signal()
      → android_participant_truth_ingress.reconcile_android_participant_truth()
      → android_runtime_transition_reducer.py
```

**`delegated_flow_acceptance_gate.py`** is confirmed present and used as **dimension 10** in V3's slot evaluation. It is NOT on the hot path directly — but its gating logic would flow through once V3 is wired.

### 1.6 Grouped / Multi-Device Flows

Confirmed from code:

```
Center multi-device:
  core/multi_device_coordination_authority.py
  core/multi_device_canonical_governance.py
  core/multi_device_control_integrity.py
  core/multi_device_truth_convergence.py

Android multi-device:
  coordination/MultiDeviceCoordinator.kt
  coordination/FormationCoordinationSurface.kt
```

The multi-device architecture is real and present on both sides. The center side uses `DispatchPathKind.COMMAND_ROUTER_CANONICAL` to stamp canonical dispatch records. The Android side has a full formation coordination surface.

**Group completion** is handled by `canonical_group_completion_closure.py` (V5), which is confirmed on the hot path for group/delegated completion contexts.

### 1.7 Replay / Recovery / Resume Flows

Confirmed:

```
core/replay_foundation.py — terminal-state events, replay ordering
core/replay_audit_persistence.py — audit trail for replay
core/offline_replay_ordering_contract.py — ordering guarantees
core/runtime_restart_recovery.py — V2 restart recovery with in-flight tasks
android_v2_continuity_contract.py — joint Android-V2 continuity verification
```

Replay flows are real. The `replay_foundation.py` is called by `android_participant_truth_ingress.reconcile_android_participant_truth()` to emit terminal-state events — this is a confirmed wiring.

### 1.8 Continuity / Session Legality Flows

Confirmed:

```
core/conversation_continuity_truth.py — session continuity
core/android_v2_continuity_contract.py — 7-scenario joint continuity
core/attached_runtime_session_registry.py — session classification
core/flow_continuity_coordinator.py — reconnect/re-attach classification
```

`unified_continuity_legality_authority.py` (V1) is the canonical single gate for all 12 continuity dimensions, but it is **not currently called by the hot path**. It is only called by V3's slot evaluation (dimension 4), and V3 is not on the hot path. The hot path has independent continuity checks spread across `CommandRouter`, `attached_runtime_session_registry`, and `flow_continuity_coordinator`.

### 1.9 Completion / Result Truth Chain

Confirmed chain:

```
android_bridge.handle_task_result(message)
  → run_task_result_truth_chain(message)       ← V2 (best-effort, 4 steps)
    Step 1: android_participant_truth_ingress.ingest_android_participant_truth_message()  ← A1
    Step 2: android_execution_signal_reconciler.reconcile_inbound_message()
    Step 3: canonical_task.CanonicalTaskRuntime.update_lifecycle()
    Step 4: canonical_completion_ingress.CanonicalCompletionIngress.notify()  ← CC
```

This is real and on the hot path. The softness is that all four steps are `try/except`, not hard-enforced.

For group/advanced completion:

```
canonical_group_completion_closure.apply_completion_closure()  ← V5
  → canonical_completion_ingress.notify()  ← CC
```

### 1.10 Current Participant Model

The current participant model is **Android-named but architecturally generalizable**. Evidence:

- `android_participant_truth_ingress.py` uses `AndroidParticipantTruthKind` — the enum values (`session_snapshot`, `readiness_assessment`, `task_phase`, `runtime_state`, `cancel`, `status`, `failure`, `result`) are not Android-specific semantically.
- `android_participant_session_state.py`, `android_participant_evidence_ingress.py` — all prefixed `android_` but deal with participant lifecycle concepts that apply to any runtime participant.
- `android_runtime_host.py` explicitly models the distinction between "connected device" and "first-class runtime host" — this abstraction is participant-generic.
- The center's `device_registry.py`, `device_participation.py`, `device_types.py` use no `android_` prefix.
- `source_runtime_posture.py` uses `control_only` / `join_runtime` — generic posture concepts.

**Finding**: The participant protocol is architecturally generic. The `android_` naming in ingress modules is an artifact of Android being the only current concrete participant, not a design constraint. Renaming or generalizing these is a terminology concern, not an architectural restructuring.

---

## Section 2: Proposed Final Architecture Validation Against Repository Reality

### 2.1 One Unified Center-Distributed Runtime

**Verdict: ALREADY EXISTS — no structural change needed.**

The center repo IS the unified center-distributed runtime. `OpenClawd.process()` → `CommandRouter.route_envelope()` → `galaxy_gateway` is the real spine. The only work needed here is:
- Closing the authority split-brain in the spine (V3/V4 wiring).
- Not re-architecting the runtime itself.

**Risk if proposed plan restructures this**: HIGH. Replacing or re-wrapping `OpenClawd` or `CommandRouter` at the spine level would break the only confirmed runnable path.

### 2.2 One Unified Authority Model

**Verdict: PARTIALLY EXISTS — V2/V5/A1/CC already integrated; V3/V4/V1 need targeted wiring.**

The unified authority model is partially real:
- Completion truth (V2, V5, CC) is correctly centralized and on hot path.
- Dispatch authority (V3, V4) is correctly declared but not wired.
- Continuity legality (V1) is correctly declared but only reachable via V3.

**What fits the repo**: Wire V3 into `CommandRouter.route_envelope()` as a pre-dispatch check (not a replacement). Then V1 is automatically consulted as dimension 4 of V3. Do NOT create a new "unified authority coordinator" wrapper — the modules already exist.

**Risk if proposed plan creates new authority wrapper**: Creating yet another meta-authority layer would create a third-level split-brain. The repositories show the correct architecture: individual authority modules that compose. They do not need a new supervisor.

### 2.3 One Unified Cognitive Authority Model (L1–L4)

**Verdict: L1–L4 are NOT on the cognitive hot path. The proposed unification requires specific wiring, not restructuring.**

The LLM cognitive hot path is:
```
OpenClawd → get_unified_llm_router() → MultiLLMRouter → providers
```

`LLMRouteAuthority` (L1), `LLMSupplyAuthority` (L2), `CognitiveContextAuthority` (L3), `CognitiveExecutionAuthority` (L4) are **not** called by `OpenClawd`. `GalaxyMainLoopL4Enhanced` is a higher-level outer loop, not a per-request cognitive gate.

**What fits the repo**: The cognitive authority chain (L1–L4) should be integrated incrementally:
- L1 (`LLMRouteAuthority`) can be integrated as a pre-selection gate in `UnifiedLLMRouter` without touching `OpenClawd`.
- L4 (`GalaxyMainLoopL4Enhanced`) should remain as an outer autonomous loop driver — do NOT force it into the per-request `OpenClawd.process()` path.
- L2/L3 are context/supply enrichment steps that can be added as optional enrichment in `UnifiedLLMRouter`.

**Risk if proposed plan forces L4 into per-request path**: L4 is the autonomous outer loop. Forcing it into per-request `process()` would couple the outer goal-execution loop with the inner per-request cognitive loop, breaking the architectural layering.

### 2.4 One Unified Execution-Decision Model

**Verdict: EXISTS AT OPENCLAWD — V4 is the correct candidate for multi-step orchestration, not per-request dispatch.**

`OpenClawd._determine_execution_path()` is the real unified execution-decision model for per-request dispatch. V4 (`unified_orchestration_spine.evaluate_orchestration_request()`) is the correct model for **multi-step orchestration scenarios** (parallel fan-out, delegated runtime, wake-routed).

**What fits the repo**: V4 should be the entry point for complex multi-step orchestration requests (the `goal_execution.py` handler path is correct). V4 should NOT replace `OpenClawd._determine_execution_path()` for simple per-request dispatch.

**Adjustment to proposed plan**: The plan should clarify that "unified execution-decision model" means: simple dispatch → `OpenClawd._determine_execution_path()`; complex multi-step orchestration → `V4.evaluate_orchestration_request()`. These are two correct layers, not one to replace the other.

### 2.5 One Unified Dispatch Authority Chain

**Verdict: V3 is the correct unified dispatch authority — needs one wiring change to `CommandRouter`.**

The dispatch authority is currently split:
- Real dispatch: `CommandRouter.route_envelope()` with 3 hard gates (ACL, no-target, capability-mismatch).
- Canonical 10-dimension gate: `canonical_dispatch_slot_authority.get_canonical_dispatch_slots()` — not called.

**What fits the repo**: Wire `get_canonical_dispatch_slots()` into `CommandRouter.route_envelope()` as the first step before ACL enforcement. This is additive, not structural. The 10 dimensions subsume the existing 3 hard gates plus add 7 more. The existing 3 gates remain as a fallback; the V3 evaluation is the primary gate.

**Risk**: None if done additively. High if V3 is used to replace the current gate logic without preserving backward compatibility.

### 2.6 One Unified Participant Truth Model

**Verdict: A1 is already on hot path — generalize naming and abstract participant truth interface.**

The current participant truth model uses `AndroidParticipantTruthKind` and `android_participant_*` naming. The participant truth concepts are generic. The implementation is Android-specific only because Android is the only current concrete participant.

**What fits the repo**: 
- Create a `ParticipantTruthKind` base enum (or protocol) with the generic values.
- Keep `AndroidParticipantTruthKind` as a concrete implementation.
- `ingest_android_participant_truth_message()` becomes the Android implementation of `ingest_participant_truth_message()`.
- This is a terminology and interface generalization, NOT a structural overhaul.

### 2.7 One Unified Completion Truth Model

**Verdict: MOSTLY ALREADY CORRECT — harden the truth chain from best-effort to strong-enforced.**

V2 (task_result_canonical_truth_chain), V5 (group completion closure), and CC (canonical_completion_ingress) together form the unified completion truth model. The only gap is that the 4 steps in `run_task_result_truth_chain()` are all `try/except` soft-enforced.

**What fits the repo**: Make the 4 steps hard-enforced (except CC notification which can remain best-effort since it is already idempotent). Change `is_truth_chain_complete = False` to raise an exception or emit a hard warning with circuit-breaker behavior.

### 2.8 Preserved Local + Cross-Device Domains

**Verdict: PRESERVED — both chains are real and documented.**

`local_execution_chain.py` and `cross_device_execution_chain.py` are both present and declared as "two first-class runtime chains." The plan must not collapse these into a single chain.

**What fits the repo**: Keep both chains intact. V3/V4 wiring should be symmetric — applicable to both chains, not only cross-device. V4's execution mode enum (`ExecutionMode`) already includes `local`, `remote`, `parallel_fanout`, `delegated`, `handoff`, `wake`, `hybrid` — confirming the design intent covers both chains.

### 2.9 Preserved Multi-Device Capability

**Verdict: PRESERVED — both center and Android have full multi-device support.**

- Center: `multi_device_coordination_authority.py`, `multi_device_canonical_governance.py`, `multi_device_control_integrity.py` (includes `DispatchAuthorityRecord`, `DispatchPathKind.COMMAND_ROUTER_CANONICAL`).
- Android: `coordination/MultiDeviceCoordinator.kt`, `coordination/FormationCoordinationSurface.kt`.

No plan element should remove multi-device governance. V5's group completion closure is the completion analog for multi-device scenarios and must remain on the hot path.

### 2.10 Non-Android-Exclusive Participant Semantics

**Verdict: ARCHITECTURE IS GENERIC BUT NAMING IS ANDROID-SPECIFIC — needs terminology generalization, not restructuring.**

The center's authority semantics should express the participant concept in runtime-generic terms. Currently:
- 42 files in `core/` contain `android_` prefix — these are implementation files.
- The **authority-level concepts** that should be generic but use Android-specific naming include:
  - `android_participant_truth_ingress.py` (should be `participant_truth_ingress.py` with Android as a concrete impl)
  - `android_participant_session_state.py` (should be `participant_session_state.py`)
  - `android_runtime_host.py` (should be `participant_runtime_host.py` or `runtime_host_classification.py`)

The **center's device-generic concepts** that are already correctly named:
- `device_registry.py`, `device_participation.py`, `device_types.py` — no `android_` prefix
- `source_runtime_posture.py` — generic posture
- `canonical_dispatch_slot_authority.py` — device-agnostic
- `device_selection/`, `device_formation/` — generic

**The final plan must NOT require renaming everything**. Priority generalization targets are the authority-level interfaces (truth ingress, session state). Low-priority: concrete implementation files (signals, bridges) can retain `android_` prefix.

---

## Section 3: Architecture Drift, Overlap, and Redundancy Analysis

### 3.1 Element Classification

Each element classified as one of:
- **NECESSARY FUSION** — must be wired into hot path; currently shadow
- **ALREADY INTEGRATED** — on hot path; no change needed
- **BOUNDARY-ONLY** — correct as policy/health/audit layer; must NOT be forced into hot path
- **TOO ABSTRACT** — correct design but currently too high-level; needs scoped integration
- **REDUNDANT** — safe to remove or retire

| Element | Classification | Reason |
|---|---|---|
| V3 `canonical_dispatch_slot_authority` | **NECESSARY FUSION** | 10-dimension gate is correct; needs wiring into `CommandRouter` |
| V4 `unified_orchestration_spine` | **TOO ABSTRACT / SCOPED** | Correct for multi-step orchestration; wrong as universal per-request gate |
| V1 `unified_continuity_legality_authority` | **NECESSARY FUSION (via V3)** | Will be reached once V3 is wired; no direct additional wiring needed |
| V2 `task_result_canonical_truth_chain` | **ALREADY INTEGRATED** | On hot path; harden to strong enforcement |
| V5 `canonical_group_completion_closure` | **ALREADY INTEGRATED** | On hot path for group/delegated |
| V6 `center_authority_boundary` | **BOUNDARY-ONLY** | Policy declaration; belongs in startup/health/release gating ONLY |
| CC `canonical_completion_ingress` | **ALREADY INTEGRATED** | Core of completion Future resolution |
| A1 `android_participant_truth_ingress` | **ALREADY INTEGRATED** | Step 1 of V2 truth chain |
| A2 `android_execution_signal_reconciler` | **ALREADY INTEGRATED** | Step 2 of V2 truth chain |
| A3 `android_delegated_runtime_lifecycle_coordinator` | **ALREADY INTEGRATED** | Delegated lifecycle facade |
| A4 `android_v2_continuity_contract` | **BOUNDARY-ONLY** | Joint continuity policy; correct as verification suite |
| L1 `LLMRouteAuthority` | **NECESSARY FUSION (scoped)** | Should be wired into `UnifiedLLMRouter` pre-selection, not into `OpenClawd` |
| L2 `LLMSupplyAuthority` | **NECESSARY FUSION (scoped)** | Supply authority for LLM availability; into `UnifiedLLMRouter` |
| L3 `CognitiveContextAuthority` | **NECESSARY FUSION (scoped)** | Context enrichment; into `UnifiedLLMRouter` |
| L4 `GalaxyMainLoopL4Enhanced` | **ALREADY INTEGRATED** | Outer autonomous loop; should stay as outer loop driver |
| `CommandRouter.route_envelope()` | **ALREADY INTEGRATED** | Is the true dispatch spine; add V3 as pre-check |
| `OpenClawd.process()` | **ALREADY INTEGRATED** | Is the true cognitive spine; do not restructure |
| `HybridExecutionArbiter` | **ALREADY INTEGRATED** | Fallback local execution helper; correctly bounded |
| `delegated_flow_acceptance_gate` | **ALREADY INTEGRATED (via V3)** | Is dimension 10 of V3 already |
| `multi_device_coordination_authority` | **ALREADY INTEGRATED** | Multi-device governance path; preserve |
| `replay_foundation` | **ALREADY INTEGRATED** | Terminal event emission; correctly wired |
| `android_runtime_host` | **TOO ABSTRACT / GENERALIZE** | Correct model; rename to participant-generic interface |
| `android_participant_truth_ingress` (interface) | **GENERALIZE** | Implement generic interface; keep Android impl |

### 3.2 Control Conflict Resolution Map

The single most important conflict to resolve is:

```
CONFLICT: V4 says "all execution modes MUST pass through me"
          CommandRouter says "I am the sole canonical dispatching authority"
          These two claims are irreconcilable as stated.

RESOLUTION:
  V4 governs: multi-step orchestration sessions (parallel fan-out, delegated,
              handoff, wake-routed) — called by goal_execution.py handler
  CommandRouter governs: per-task dispatch execution — called by OpenClawd.process()
  
  These are two different layers of the same system.
  V4 → produces OrchestrationDecision → CommandRouter executes per-task dispatch.
  This is NOT a conflict once the layering is clarified.
```

The second conflict:

```
CONFLICT: V3 says "all dispatch MUST consult me before targeting any device"
          CommandRouter dispatches without consulting V3

RESOLUTION:
  Wire V3 into CommandRouter.route_envelope() as step 0 (pre-ACL):
    - Call get_canonical_dispatch_slots(targets, context)
    - Filter targets to SLOT_APPROVED devices
    - Proceed with filtered target list
  This is a single additive change to CommandRouter (roughly 20 lines).
```

### 3.3 Semantic Overlap Map

| Overlapping pair | Overlap | Resolution |
|---|---|---|
| V1 continuity gate vs. `CommandRouter` posture gate | Both evaluate continuity/posture for dispatch | V3 wiring resolves: V1 becomes authoritative via V3 dimension 4; CommandRouter's ad-hoc gate is retired |
| V4 orchestration spine vs. `OpenClawd._determine_execution_path()` | Both make execution mode decisions | Clarify layering: V4 for complex multi-step; `_determine_execution_path()` for simple per-request |
| `android_participant_truth_ingress` vs. raw `task_result` handling | Both process Android result signals | V2 truth chain is the canonical path; raw handling is the legacy path; V2 must be the only path |
| `delegated_flow_acceptance_gate` vs. V3 dimension 10 | Same logic | V3 delegates to `delegated_flow_acceptance_gate` — already composing, not duplicating |

---

## Section 4: Core Capability Preservation Verification

### 4.1 Local Execution Chain

**Status: PRESERVED and confirmed real**

Evidence: `local_execution_chain.py` documents the canonical chain. `DecisionExecutor` and `HybridExecutionArbiter` are present and bounded. `OpenClawd._determine_execution_path()` returns `"local"` for local tasks.

**Risk in final plan**: None if the plan leaves `OpenClawd._determine_execution_path()` intact. Risk emerges only if V4 is positioned to replace `_determine_execution_path()` for simple requests.

### 4.2 Cross-Device Dispatch Chain

**Status: PRESERVED and confirmed real**

Evidence: `cross_device_execution_chain.py`, `CommandRouter.route_envelope()`, `galaxy_gateway/android_bridge.py`, `GalaxyConnectionService.kt`. Full chain traced and confirmed runnable.

**Gap**: V3 slot evaluation not called before `CommandRouter` selects targets. Fix: wire V3 into `CommandRouter` as described in 3.2.

### 4.3 Delegated / Handoff / Takeover Flows

**Status: PRESERVED and confirmed real**

Evidence: `AndroidDelegatedRuntimeLifecycleCoordinator`, `delegated_flow_acceptance_gate.py`, `DelegatedRuntimeExecutionTracker`, `android_handoff_v2_response_ingress.py`, `DelegatedTakeoverExecutor.kt`. Full lifecycle traced.

**Status of `delegated_flow_acceptance_gate`**: It IS used as V3 dimension 10. Once V3 is wired into `CommandRouter`, delegated flow acceptance will be enforced at dispatch time.

### 4.4 Grouped / Multi-Device Flows

**Status: PRESERVED and confirmed real**

Evidence: `multi_device_coordination_authority.py` (center), `MultiDeviceCoordinator.kt` (Android), `canonical_group_completion_closure.py` (V5, on hot path). The `DispatchAuthorityRecord` with `DispatchPathKind.COMMAND_ROUTER_CANONICAL` provides canonical auditing.

**Gap**: V3 wiring will also benefit multi-device dispatch by enforcing 10-dimension legality for all targets in a group.

### 4.5 Replay / Recovery / Resume Flows

**Status: PRESERVED and confirmed real**

Evidence: `replay_foundation.py` (terminal-state emission), `replay_audit_persistence.py`, `offline_replay_ordering_contract.py`, `runtime_restart_recovery.py`, `android_v2_continuity_contract.py` (7-scenario recovery coverage).

`replay_foundation` is called by `android_participant_truth_ingress.reconcile_android_participant_truth()` — this is the confirmed wiring.

**Gap**: None. Replay chain is correctly implemented.

### 4.6 Continuity / Session Legality

**Status: PARTIALLY REAL — V1 gate not enforced on hot path**

The joint continuity contract (`android_v2_continuity_contract.py`) covers 7 scenarios. `flow_continuity_coordinator.py` handles reconnect/re-attach classification. `attached_runtime_session_registry.py` maintains session state.

**Gap**: V1 (`unified_continuity_legality_authority`) is the unified 12-dimension gate but is not on the hot path. Wiring V3 into `CommandRouter` will fix the dispatch-time continuity gate. The result-ingress path continuity gate (V1 paths: `RESULT_INGRESS`, `SIGNAL_INGRESS`) needs direct wiring in `android_bridge.handle_task_result()` as a pre-check — separate from the dispatch gate.

### 4.7 Participant Readiness and Result Truth

**Status: REAL for result truth (A1/A2/V2 chain) — readiness is advisory only**

Result truth: A1 → A2 → V2 chain is confirmed on hot path.

Readiness truth: `ReadinessChecker.kt` (Android) reports readiness. `unified_dispatch_readiness_gate.py` checks transport/registration/attachment. However, readiness truth currently does not feed into V3 slot evaluation (dimensions 1-3 come from `unified_dispatch_readiness_gate` which IS the delegate for V3).

**Gap**: `unified_dispatch_readiness_gate` is already V3 dimension 1-3/5/9 delegate. Once V3 is wired, readiness truth will feed dispatch decisions.

### 4.8 Center Completion Truth

**Status: REAL — V2/V5/CC chain confirmed on hot path**

V2 truth chain executes on every `task_result`. V5 group closure executes on group contexts. CC unblocks awaiters. The one gap is best-effort enforcement in V2.

### 4.9 Center-Distributed Governance

**Status: REAL — center retains sole governance authority**

`CommandRouter` is the sole dispatch authority. `canonical_task.CanonicalTaskRuntime` owns task lifecycle state. `canonical_completion_ingress` owns completion truth. Android cannot unilaterally advance center task state.

**V6 check**: `assert_center_authority_intact()` validates that all four authority domain modules are importable. This should be called at startup and in release gating — it is correctly placed as a BOUNDARY-ONLY check.

### 4.10 Participant Generalization Beyond Android

**Status: ARCHITECTURALLY GENERAL — naming is Android-specific implementation detail**

The participant protocol (AIP v3) is a general participant-to-center protocol. `device_registry.py`, `device_participation.py`, `source_runtime_posture.py` are all non-Android-specific. The ingress modules use `android_` prefix but implement conceptually generic participant truth semantics.

**Gap**: No participant-generic abstract interface exists. The ingress modules are directly Android-named. To add a non-Android participant (desktop, iOS, embedded), a developer would have to copy-paste the `android_` modules and rename them.

**What needs to happen**: Define `ParticipantTruthIngress` as a protocol interface. `AndroidParticipantTruthIngress` becomes the concrete implementation. This is a software engineering cleanup, not a re-architecture.

---

## Section 5: Participant Generalization Beyond Android

### 5.1 Truly Android-Specific Implementation (must stay Android-named)

| Component | Why Android-specific |
|---|---|
| `GalaxyConnectionService.kt` | Android Service lifecycle (foreground service, WakeLock) |
| `AccessibilityActionExecutor.kt` | Android Accessibility Service API |
| `service/ReadinessChecker.kt` | Android-specific permission/service checks |
| `inference/` (MobileVLM, SeeClick) | Android/mobile inference stack |
| `android_execution_signal_reconciler.py` | Reconciles Android-specific signal envelope format |
| `android_handoff_v2_response_ingress.py` | Processes Android-specific `handoff_envelope_v2` |

### 5.2 Participant-Generic in Architecture / Protocol (should be generalized)

| Component | Current naming | Generic concept | Generalization approach |
|---|---|---|---|
| `android_participant_truth_ingress.py` | Android-prefixed | Participant truth ingress | Define `ParticipantTruthIngressProtocol`; keep Android impl |
| `android_participant_session_state.py` | Android-prefixed | Participant session state | Define `ParticipantSessionState` dataclass hierarchy |
| `android_runtime_host.py` | Android-prefixed | Participant runtime host classification | Rename to `participant_runtime_host_classifier.py` (or keep as Android impl of generic interface) |
| `AndroidParticipantTruthKind` enum | Android-prefixed | Participant truth signal types | Define `ParticipantTruthKind` base enum |
| `android_v2_continuity_contract.py` | Android-prefixed | V2-participant joint continuity contract | Rename to `participant_v2_continuity_contract.py` (template); keep Android-specific policies inside |

### 5.3 Center Repo Already Uses Device-/Runtime-Generic Concepts

The following center-repo modules are already non-Android-specific by design:

- `device_registry.py` — generic device registration
- `device_participation.py` — generic participation model
- `device_types.py` — generic type taxonomy
- `source_runtime_posture.py` — `control_only` / `join_runtime` (generic)
- `canonical_dispatch_slot_authority.py` — device-agnostic 10-dimension gate
- `multi_device_coordination_authority.py` — generic multi-device coordination
- `device_selection/` directory — generic device selection policies
- `device_formation/` directory — generic formation coordination

### 5.4 Where Android-Specific Naming Leaks into Core Authority Semantics

Current leaks in authority-level modules (not just implementation files):

1. **`center_authority_boundary.py` (V6)** — references `android_participant_truth_ingress` as the participant truth module in its import check. This creates Android-specific coupling in the center authority boundary declaration.

2. **`task_result_canonical_truth_chain.py` (V2)** — Step 1 calls `ingest_android_participant_truth_message()` — Android-named function in what should be a device-agnostic truth chain.

3. **`canonical_group_completion_closure.py` (V5)** — Does NOT have Android-specific naming (clean).

4. **`canonical_completion_ingress.py` (CC)** — Module docstring references "Android handoff result" but the implementation is generic (Future resolution). Docstring should be updated to say "participant result."

### 5.5 Final Plan for Participant Generalization

**Step 1** (high priority): Define `ParticipantTruthKind` protocol and `ingest_participant_truth_message()` in a new `core/participant_truth_ingress.py`. Have `android_participant_truth_ingress.py` delegate to it. Wire `task_result_canonical_truth_chain.py` Step 1 to call `ingest_participant_truth_message()`.

**Step 2** (medium priority): Update V6 `center_authority_boundary.py` to check for `participant_truth_ingress` presence rather than `android_participant_truth_ingress`.

**Step 3** (low priority, future): When adding non-Android participants (iOS, desktop, embedded), implement concrete `ParticipantTruthIngress` for each. The center-side changes will be zero because the abstract interface is already in place.

---

## Section 6: Final Post-Review Implementation Plan

### 6.1 What to Keep Exactly As-Is

These elements are correct and must NOT be modified by the unification plan:

| Element | Reason |
|---|---|
| `OpenClawd.process()` Stage 1-4 | Is the real cognitive spine; modifying it risks breaking the only runnable path |
| `CommandRouter.route_envelope()` core dispatch logic | Is the real dispatch spine; can only receive additive pre-checks |
| `GalaxyMainLoopL4Enhanced` as outer loop | Correct autonomous loop driver; must NOT be forced into per-request path |
| `HybridExecutionArbiter` (local fallback) | Correctly bounded as three-level local fallback |
| `canonical_group_completion_closure` (V5) | Already on hot path; correct as-is |
| `canonical_completion_ingress` (CC) | Core of Future resolution; correct as-is |
| `android_participant_truth_ingress` (A1) | On hot path; correct as-is |
| `android_execution_signal_reconciler` (A2) | On hot path; correct as-is |
| `replay_foundation` | Terminal event emission; correct as-is |
| `delegated_flow_acceptance_gate` | V3 dimension 10 delegate; correct as-is |
| `multi_device_coordination_authority` | Multi-device governance; correct as-is |
| All device-generic center modules (`device_registry`, etc.) | Already generic; no change needed |

### 6.2 What to Fuse (Wire Into Hot Path)

Priority-ordered:

**P0 — Highest priority (fixes the primary split-brain):**

1. **Wire V3 into `CommandRouter.route_envelope()`** — The single most important change.
   - Insertpoint: Before ACL enforcement, after target list validation.
   - Change: Call `get_canonical_dispatch_slots(targets, context)` → filter to `SLOT_APPROVED`.
   - Fallback: If V3 is unavailable, fall through to existing ACL gate (degrade gracefully).
   - Files: `core/command_router.py` (add ~20 lines); no other file changes.
   - Impact: Automatically activates V1 (dimension 4 = V1) and `delegated_flow_acceptance_gate` (dimension 10).

**P1 — High priority (hardens truth chain):**

2. **Harden V2 truth chain enforcement** — Change `try/except` soft enforcement to hard for steps 1-3; keep step 4 (CC notification) as idempotent best-effort.
   - Files: `core/task_result_canonical_truth_chain.py` (modify error handling).
   - Impact: `is_truth_chain_complete = False` raises an observable exception (not swallowed).

3. **Wire V1 to result-ingress path** — Add `evaluate_continuity_legality(path=RESULT_INGRESS)` as pre-check in `android_bridge.handle_task_result()`.
   - Files: `galaxy_gateway/android_bridge.py` (add pre-check ~5 lines).
   - Impact: Stale or revoked runtime identities cannot pollute the truth chain.

**P2 — Medium priority (scoped cognitive authority):**

4. **Wire L1/L2/L3 into `UnifiedLLMRouter`** — Add cognitive authority pre-selection and supply checks.
   - Files: `core/unified/llm_router.py` (add L1 pre-selection gate; L2 supply check; L3 context enrichment).
   - L4 (`GalaxyMainLoopL4Enhanced`) requires NO change — it is already the outer loop driver.

5. **Clarify V4 scope** — Add explicit documentation + assertion that V4 is called only by multi-step orchestration paths (goal_execution handler).
   - Files: `core/unified_orchestration_spine.py` (docstring update); `core/galaxy_gateway/goal_execution.py` (assert V4 call).

**P3 — Lower priority (participant generalization):**

6. **Define `ParticipantTruthKind` protocol and generic ingress interface** — Create `core/participant_truth_ingress.py`.
   - Files: New `core/participant_truth_ingress.py`; update `task_result_canonical_truth_chain.py` Step 1 to call generic interface.

7. **Update V6 `center_authority_boundary.py`** — Check for `participant_truth_ingress` not `android_participant_truth_ingress`.

### 6.3 What to Demote to Boundary/Audit Only

These elements are correct as policy/audit/release-gating layers and must NOT be wired into per-request hot paths:

| Element | Correct boundary role |
|---|---|
| V6 `center_authority_boundary.assert_center_authority_intact()` | Startup check, health endpoint, release gate CI assertion |
| `architecture_invariants.py` | Invariant assertion at startup and in tests |
| `architecture_truth_guards.py` | Test and health assertion only |
| `canonical_authoritative_path_convergence.py` | Release-gating audit |
| `release_blocking_gate.py` | Release gate only |
| Android governance uplinks (if any exist and have no handler) | Retire if no consumer; do not add fake handlers |

### 6.4 What to Retire

| Element | Retirement reason |
|---|---|
| `hybrid_execute` protocol stub (if any dead protocol declaration exists) | Not backed by a callable execution path; replace with `HybridExecutionArbiter` direct call |
| Any Android governance uplink message types with zero center-side consumers | Dead protocol; retire rather than leaving as dead wire |
| Legacy dispatch paths in `orchestration_authority/legacy_paths.py` | Formally demoted; can be deleted once V3 is wired and confirmed working |

### 6.5 What to Generalize

| Element | Generalization action |
|---|---|
| `android_participant_truth_ingress.py` (authority interface) | Define `ParticipantTruthIngressProtocol`; keep Android implementation |
| `AndroidParticipantTruthKind` enum | Define `ParticipantTruthKind` base; extend for Android |
| `android_participant_session_state.py` (state model) | Define `ParticipantSessionState` base dataclass |
| `android_runtime_host.py` (host classification) | Define `ParticipantRuntimeHostClassifier` protocol |
| `canonical_completion_ingress.py` docstring | Update to say "participant result" not "Android handoff result" |
| V6 `center_authority_boundary.py` authority check | Use generic participant truth ingress module reference |

### 6.6 What to Test

After the implementation changes:

| Test | Verifies |
|---|---|
| `CommandRouter` dispatches only `SLOT_APPROVED` devices after V3 wiring | V3 is live, not shadow |
| Dispatch is blocked for device with active occupancy | V3 dimension 7 works |
| Dispatch is blocked for device in illegal continuity state | V3 dimension 4 (V1) works |
| `task_result` without valid runtime session is rejected at ingress | V1 result-ingress path works |
| `run_task_result_truth_chain()` raises on any of steps 1-3 failing | V2 hardening works |
| `assert_center_authority_intact()` passes at startup | V6 boundary integrity |
| Group completion with 2 devices produces `complete` not `partial` | V5 closure correct |
| Non-Android participant truth ingress uses generic interface | Participant generalization works |

### 6.7 Implementation Order

```
Phase 1 — Close the primary split-brain (1-2 days)
  [P0] Wire V3 into CommandRouter.route_envelope()
  [P1] Harden V2 truth chain enforcement
  [P1] Wire V1 to result-ingress pre-check

Phase 2 — Cognitive authority integration (2-3 days)
  [P2] Wire L1/L2/L3 into UnifiedLLMRouter
  [P2] Clarify V4 scope in documentation and assertion

Phase 3 — Participant generalization (1-2 days)
  [P3] Define ParticipantTruthKind protocol and generic ingress
  [P3] Update V6 center authority boundary check

Phase 4 — Test closure (1-2 days)
  Write and pass all 8 tests listed in 6.6

Phase 5 — Retirement (0.5 days)
  Retire dead protocol stubs and legacy dispatch paths

Total estimated effort: ~8-10 development days
```

---

## Appendix: Key Sentinel Constants (Architecture Anchors)

The following sentinel constants serve as machine-checkable architecture anchors. Tests and CI should assert their presence:

```python
# Command authority
COMMAND_ROUTER_ORCHESTRATION_AUTHORITY = "core.command_router.CommandRouter"

# Dispatch slot authority (V3)
CANONICAL_DISPATCH_SLOT_AUTHORITY = "core.canonical_dispatch_slot_authority"
ALL_EXECUTION_MODES_MUST_CONSUME_CANONICAL_SLOT_POLICY

# Orchestration spine (V4)
UNIFIED_ORCHESTRATION_SPINE_AUTHORITY
ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY

# Completion truth (V2)
TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY

# Center boundary (V6)
# assert_center_authority_intact() callable

# Continuity gate (V1)
# evaluate_continuity_legality() callable
```

These sentinels should be imported by the tests in Phase 4 to assert architectural compliance.
