# Unified Center-Distributed Runtime — Final Architecture Freeze

> **Status**: FROZEN — Architectural root for the full unification program  
> **Version**: V1.0  
> **Date**: 2026-04-30  
> **Repositories**:  
> - `DannyFish-11/ufo-galaxy-realization-v2` (center runtime)  
> - `DannyFish-11/ufo-galaxy-android` (first concrete participant runtime)  
> **Supersedes**: All prior design-only or proposal-only architectural statements  
> **Grounded in**: `audit/FINAL_ARCHITECTURE_VALIDATION_AUDIT.md`, `audit/FINAL_VERDICT_CLASSIFICATION_TABLE.md`, `audit/CENTER_DISTRIBUTED_SYSTEM_FINAL_VERDICT.md`  
> **Companion documents**:  
> - `ARCHITECTURE_FREEZE_IMPLEMENTATION_GUARDRAILS.md` (per-PR enforcement rules)  
> - `audit/ARCHITECTURE_FREEZE_SUMMARY.md` (compact reference)

---

## Purpose and Binding Authority

This document is the **binding architectural root** for all implementation work that follows. It freezes the final integrated architecture of the unified center-distributed runtime based on the completed terminal dual-repository code audits. All subsequent implementation PRs must conform to this document. They may not:

- contradict the layer assignments in Section 4,
- violate the preservation guarantees in Section 7,
- ignore the role assignments in Section 5,
- or introduce any of the anti-patterns explicitly listed in Section 8.

This document does not describe a speculative redesign. Every module named here is confirmed by code-level audit to exist and be importable. The architectural statements reflect the reality of the running system, corrected where the audits identified split-brain, and extended where the audits confirmed architecturally valid infrastructure not yet connected to the hot path.

---

## 1. System Identity

The system is one **Unified Center-Distributed Runtime**. It is not a standalone local agent, not a pure remote dispatcher, and not a center-and-one-endpoint architecture. It is:

> **One governing center, one unified authority model, one unified completion truth, multiple coexisting execution domains, and a participant model that is architecturally generalized above its first concrete implementation.**

### 1.1 The system consists of exactly one center subject and three execution domains

```
Unified Center-Distributed Runtime
│
├── Center Governance and Cognition Domain
│     Modules: main.py → SystemOrchestrator → DesktopPresenceRuntime → OpenClawd
│     Authorities: ContinuumOrchestrator, UnifiedLLMRouter, CommandRouter
│     Truth keepers: CanonicalCompletionIngress, TaskLifecycle, ReplayFoundation
│
├── Local Execution Domain
│     Modules: HybridExecutionArbiter, DecisionExecutor, desktop_projection
│     Role: center-local execution; not optional, not deprecated
│
└── Distributed Participant Execution Domain
      First realized implementation: Android participant runtime
        (GalaxyConnectionService, EdgeExecutor, AgentRuntimeBridge,
         AutonomousExecutionPipeline, MultiDeviceCoordinator)
      Architecture: participant-generic; Android is one realization, not the definition
      Capabilities: single-target, delegated, handoff/takeover, grouped, replay
```

These three domains are parts of **one system**, not three separate systems in loose federation.

### 1.2 The system remains center-distributed

The center governs:
- task and session truth,
- orchestration authority,
- dispatch authority and legality,
- participant admission and readiness,
- result acceptance and completion closure.

Participant devices contribute execution, readiness signals, and result reporting. They do not hold dispatch authority, session truth, or completion authority.

### 1.3 Local and cross-device execution are both first-class

The system preserves two fully realized execution domains under the same cognitive spine. The choice of execution domain is made at the execution-decision layer (Section 4, Layer 2) — it is never hardcoded or defaulted. Both domains are equal in architectural standing.

### 1.4 Multi-device execution is native, not an add-on

The architecture natively supports:
- single-target remote execution,
- delegated execution,
- handoff and takeover,
- grouped multi-device participation,
- grouped completion via canonical group completion closure (V5),
- replay and recovery across device session continuity.

This capability is not optional decoration and must not be narrowed or removed by any subsequent implementation work.

### 1.5 Participant devices are not Android-only by architectural principle

Android is the first concrete participant runtime. The participant model must remain architecturally generalized. Authority interfaces, completion truth models, and participant runtime classification must be defined at a participant-generic level, with Android as a concrete implementation below that level.

---

## 2. Confirmed Execution Chains

The following chains are confirmed runnable by code-level audit. They are the **canonical chains** of the unified system.

### 2.1 Local execution chain

```
OpenClawd.process()
  └─ _determine_execution_path() → "local"
        └─ DecisionExecutor
              └─ HybridExecutionArbiter
                    └─ LocalExecutionResult
                          └─ OpenClawd feedback → memory backflow → projection
```

Source: `core/local_execution_chain.py`, `core/hybrid_executor.py`

### 2.2 Cross-device execution chain

```
OpenClawd.process()
  └─ _determine_execution_path() → "cross_device"
        └─ CommandRouter.route_envelope()
              └─ TaskEnvelope (RemoteExecutionMode stamped)
                    └─ galaxy_gateway/android_bridge
                          └─ WebSocket → participant device
                                └─ participant execution
                                      └─ result → android_bridge.handle_task_result()
                                            └─ run_task_result_truth_chain()
                                                  └─ CanonicalCompletionIngress.notify()
```

Source: `core/cross_device_execution_chain.py`, `core/command_router.py`, `galaxy_gateway/android_bridge.py`

### 2.3 Delegated / handoff / takeover chain

```
center dispatches handoff_envelope_v2
  └─ android_bridge.handle_handoff_envelope_v2()
        └─ AndroidDelegatedRuntimeLifecycleCoordinator.on_handoff_dispatched()
              └─ android_participant_session_state (session record)
              └─ DelegatedRuntimeExecutionTracker (V2 tracking)

participant sends takeover_response
  └─ android_bridge.handle_takeover_response()
        └─ AndroidDelegatedRuntimeLifecycleCoordinator.on_takeover_response()

participant sends reconciliation_signal
  └─ android_bridge.handle_reconciliation_signal()
        └─ AndroidDelegatedRuntimeLifecycleCoordinator.on_reconciliation_signal()
              └─ android_participant_truth_ingress.reconcile_android_participant_truth()
              └─ android_runtime_transition_reducer
```

Source: `core/android_delegated_runtime_lifecycle_coordinator.py`

### 2.4 Grouped / multi-device completion chain

```
[multi-device targets execute]
  └─ per-target result → run_task_result_truth_chain() (per device)
        └─ canonical_group_completion_closure.py (V5) — group terminal state
              └─ CanonicalCompletionIngress.notify() — Future resolved
```

Source: `core/canonical_group_completion_closure.py`, `core/multi_device_coordination_authority.py`

### 2.5 Replay / recovery chain

```
replay_foundation.py — terminal-state events, replay ordering
replay_audit_persistence.py — audit trail
offline_replay_ordering_contract.py — ordering guarantees
runtime_restart_recovery.py — in-flight task recovery on restart
android_v2_continuity_contract.py — joint continuity verification
```

Source: `core/replay_foundation.py`, `core/runtime_restart_recovery.py`

---

## 3. System Startup Chain

The confirmed startup authority chain is:

```
main.py
  └─ SystemOrchestrator.run_startup_sequence()  [7 phases]
        Phase 1: LOAD_CONFIG
        Phase 2: RESOLVE_MODE
        Phase 3: ENV_CHECKS
        Phase 4: BACKGROUND_SUBSYSTEMS
        Phase 5: RUNTIME_SUBJECT
        Phase 6: DESKTOP_SURFACE
        Phase 7: READINESS_SUMMARY ← V6 assert_center_authority_intact() to be added here
  └─ unified_launcher.py [FastAPI / gateway bring-up]
        └─ DesktopPresenceRuntime [tri-state: silent / liminal / manifest]
              └─ OpenClawd.process() [per-request cognitive entry]
```

---

## 4. Final Layer Model

The unified system is defined by exactly seven architectural layers. Each layer has a single governing module or set of modules and a specific scope. Layers do not overlap in authority.

---

### Layer 1 — Unified Cognitive Subject Layer

**Governing module**: `OpenClawd.process()` (`core/openclawd.py`)

**Scope**: Sole cognitive entry point. Every request enters through this module. It performs four stages:
1. Ingest — `PerceptionFrame` + multimodal context assembly
2. Cognition — `ContinuumOrchestrator` → intent → `state_continuum`
3. Branch — `_determine_execution_path()` (local / cross-device / hybrid)
4. Manifest — feedback, memory backflow, projection

**Cognitive authority fusing (P2 work)**:
- `UnifiedLLMRouter` receives `LLMRouteAuthority` (L1), `LLMSupplyAuthority` (L2), and `CognitiveContextAuthority` (L3) as fused pre-selection gates
- This fusion happens **inside `UnifiedLLMRouter`**, not by restructuring `OpenClawd.process()`

**What must never happen**:
- `OpenClawd.process()` must not be replaced, wrapped, or bypassed
- V4 must not be inserted as a mandatory synchronous gate on `OpenClawd.process()`
- L4 must not be inserted into Stage 2 or Stage 3 of the cognitive sequence
- No parallel cognitive runtime may claim to be the real cognitive entry point

**Frozen structure**:
```
OpenClawd.process()
  → ContinuumOrchestrator → intent determination
  → UnifiedLLMRouter [with L1/L2/L3 fused] → model execution
  → _determine_execution_path() → Layer 2 (execution decision)
```

---

### Layer 2 — Unified Execution Decision Layer

**Governing module**: `OpenClawd._determine_execution_path()` + multi-step orchestration governed by `V4 unified_orchestration_spine`

**Scope**: Determines which execution domain is used for a given request.

**Decision tree**:
- "local" → local execution domain (Layer 4a)
- "cross_device" / "hybrid" → dispatch authority layer (Layer 3)
- Multi-step orchestration session → `V4 unified_orchestration_spine` as the session orchestrator

**V4 scope clarification (non-negotiable)**:
`V4 unified_orchestration_spine` governs **multi-step orchestration sessions** — parallel fan-out, delegated wake-routed tasks, and complex multi-device goals. It is **not** a universal synchronous gate on every per-request `OpenClawd.process()` call. Forcing V4 into the per-request hot path would introduce unnecessary latency and split-brain authority.

**What must never happen**:
- V4 must not replace `_determine_execution_path()`
- V4 must not be forced as a synchronous per-request pre-check on `OpenClawd`
- There must be no second parallel execution-decision layer claiming authority over the same decision

---

### Layer 3 — Unified Dispatch Authority Layer

**Governing module**: `V3 canonical_dispatch_slot_authority` (`core/canonical_dispatch_slot_authority.py`) fused into `CommandRouter.route_envelope()` as a pre-dispatch step

**Scope**: Determines whether a cross-device execution action is legal and dispatchable.

**V3 is the canonical dispatch legality authority.** Its 10-dimension slot evaluation consolidates:
1. `unified_dispatch_readiness_gate` — transport / registration / attachment / capability
2. `canonical_device_identity_contract` — device identity legality
3. Circuit-breaker state
4. `unified_continuity_legality_authority` (V1) — 12-dimension continuity legality
5. `multi_device_control_integrity` — multi-device coordination legality
6. HITL / risk gate
7. ACL enforcement
8. Policy allowance
9. Capability matching
10. `delegated_flow_acceptance_gate` — delegated/handoff acceptability

**Required wiring (P0 work)**:
V3's `get_canonical_dispatch_slots()` must be called in `CommandRouter.route_envelope()` as a pre-dispatch step, before the existing ACL gate. The existing ACL gate logic in `CommandRouter` is retained as a secondary fallback, not removed. This is an additive ~20-line change.

**What must never happen**:
- `CommandRouter.route_envelope()` must not be replaced
- No second dispatch legality layer may be created outside V3 + `CommandRouter`
- Dimensions already declared by V3 must not be re-implemented inline in `CommandRouter`

**Frozen structure**:
```
CommandRouter.route_envelope()
  [pre-dispatch]: V3.get_canonical_dispatch_slots() ← P0 addition
  [existing]:     ACL enforcement (retained as fallback)
  [existing]:     circuit-breaker
  [existing]:     target resolution
  [existing]:     transport dispatch (galaxy_gateway substrate)
```

---

### Layer 4 — Execution Domain Layer

**Two coexisting first-class sub-domains:**

#### 4a — Local Execution Domain

**Governing modules**: `DecisionExecutor`, `HybridExecutionArbiter` (`core/hybrid_executor.py`)

`HybridExecutionArbiter` is a fallback execution helper (A2A → GUI → VLM). It is not a parallel authority. It does not hold dispatch authority. It is local execution substrate.

#### 4b — Distributed Participant Execution Domain

**Governing modules (center side)**: `galaxy_gateway/android_bridge.py` + message handlers  
**Governing modules (participant side)**: `GalaxyConnectionService`, `EdgeExecutor`, `AgentRuntimeBridge`, `AutonomousExecutionPipeline`, `MultiDeviceCoordinator`

Android is the first concrete participant runtime implementation. The participant model is architecturally generic above this level.

**Multi-device coordination**:
- Center: `core/multi_device_coordination_authority.py`, `core/multi_device_canonical_governance.py`, `core/multi_device_control_integrity.py`, `core/multi_device_truth_convergence.py`
- Participant: `coordination/MultiDeviceCoordinator.kt`, `coordination/FormationCoordinationSurface.kt`

---

### Layer 5 — Participant Truth / Result / Completion Layer

**Governing modules**:
- `V2 task_result_canonical_truth_chain` — 4-step canonical truth chain for every `task_result`
- `A1 android_participant_truth_ingress` — participant truth reconciliation (Step 1 of V2)
- `A2 android_execution_signal_reconciler` — signal reconciliation (Step 2 of V2)
- `canonical_completion_ingress.py` — Future-based completion awaiter (Step 4 of V2)
- `V5 canonical_group_completion_closure` — group/delegated completion terminal semantics

**Canonical completion sequence**:
```
android_bridge.handle_task_result(message)
  → run_task_result_truth_chain(message)          [V2 — must be hardened to non-soft]
      Step 1: participant_truth_ingress.ingest()  [A1 — on hot path]
      Step 2: execution_signal_reconciler()       [A2 — on hot path]
      Step 3: CanonicalTaskRuntime.update_lifecycle()
      Step 4: CanonicalCompletionIngress.notify() [CC — idempotent best-effort]
  → [group context]: V5.close_group()
```

**V1 continuity legality pre-check (P1 addition)**:
`evaluate_continuity_legality(RESULT_INGRESS)` must be added as a pre-check in `android_bridge.handle_task_result()`, ensuring continuity legality is validated before entering the V2 truth chain for inbound results.

**V2 hardening (P1 work)**:
The `try/except` soft wrapping on Steps 1–3 of `run_task_result_truth_chain()` must be replaced with hard enforcement. Step 4 (CC notification) remains idempotent best-effort.

**What must never happen**:
- Result return alone must not be treated as completion truth
- `CanonicalCompletionIngress.notify()` must remain the single completion resolution point
- The V2 truth chain must not be weakened (it must be hardened)
- V5 group completion semantics must not be merged into Step 4 of V2

---

### Layer 6 — Boundary / Audit / Startup Integrity Layer

**Governing module**: `V6 center_authority_boundary` (`core/center_authority_boundary.py`)

**Scope**: Structural soundness assertions at startup, health, and release gates. Not a per-request hot-path gate.

`V6.assert_center_authority_intact()` must be called at:
- `SystemOrchestrator` Phase 7 (READINESS_SUMMARY)
- Health endpoint (`/health` or equivalent)
- CI release gate

**What must never happen**:
- V6 must not be wired into the per-request execution hot path
- V6 must not claim runtime authority over paths it does not actually intercept
- V6's import references must be updated to reference generic `participant_truth_ingress` rather than `android_participant_truth_ingress`

---

### Layer 7 — Protocol Truth Layer

**Scope**: Every declared protocol path must equal runtime truth.

**Rule**: A protocol message type may not remain in a state where:
- one side emits it,
- the other side ignores it,
- and the architecture treats it as valid.

All declared protocol paths must be:
- consumed and validated, or
- formally retired in the protocol schema.

Dead declared protocol paths are not part of the final architecture.

---

## 5. Role Assignments for Key Modules

The following role assignments are frozen. No subsequent PR may reassign these modules to different roles, replace them with parallel implementations claiming the same authority, or remove them.

### 5.1 Cognitive spine

| Module | Frozen Role |
|---|---|
| `OpenClawd.process()` | Sole cognitive entry point; 4-stage: Ingest → Cognition → Branch → Manifest |
| `ContinuumOrchestrator` | Intent determination and state continuum under OpenClawd |
| `UnifiedLLMRouter` | LLM route selection and execution, receiving L1/L2/L3 as fused authority gates |
| `MultiLLMRouter` | Multi-provider LLM execution substrate under `UnifiedLLMRouter` |

### 5.2 Execution decision

| Module | Frozen Role |
|---|---|
| `OpenClawd._determine_execution_path()` | Per-request execution domain selection (local / cross-device) |
| `V4 unified_orchestration_spine` | Multi-step orchestration session governor; NOT per-request gate |

### 5.3 Dispatch authority and substrate

| Module | Frozen Role |
|---|---|
| `V3 canonical_dispatch_slot_authority` | Canonical dispatch legality authority — 10-dimension pre-dispatch gate |
| `CommandRouter.route_envelope()` | Dispatch substrate — sole carrier of all cross-device dispatch; receives V3 |
| `V1 unified_continuity_legality_authority` | 12-dimension continuity legality; activated via V3 (dispatch) and direct (result ingress) |
| `unified_dispatch_readiness_gate` | V3 dimension 1–3, 5, 9 delegate |
| `delegated_flow_acceptance_gate` | V3 dimension 10 delegate |

### 5.4 Cognitive authority chain

| Module | Frozen Role |
|---|---|
| `L1 LLMRouteAuthority` | Route selection authority gate; fused into `UnifiedLLMRouter` |
| `L2 LLMSupplyAuthority` | Supply availability gate; fused into `UnifiedLLMRouter` |
| `L3 CognitiveContextAuthority` | Context enrichment; fused into `UnifiedLLMRouter` |
| `L4 GalaxyMainLoopL4Enhanced` | Outer autonomous loop driver; NOT a per-request cognitive gate |

### 5.5 Completion truth backbone

| Module | Frozen Role |
|---|---|
| `V2 task_result_canonical_truth_chain` | 4-step mandatory truth chain for every `task_result`; to be hardened |
| `V5 canonical_group_completion_closure` | Group/delegated completion terminal semantics |
| `CanonicalCompletionIngress` | Future-based completion awaiter and resolution; sole completion point |
| `A1 android_participant_truth_ingress` | Participant truth reconciliation (V2 Step 1); interface to be generalized |
| `A2 android_execution_signal_reconciler` | Execution signal reconciliation (V2 Step 2) |

### 5.6 Android participant truth and lifecycle

| Module | Frozen Role |
|---|---|
| `A3 android_delegated_runtime_lifecycle_coordinator` | Single facade for all Android delegated lifecycle events |
| `A4 android_v2_continuity_contract` | Joint continuity verification policy (7 scenarios); boundary/test layer |
| `android_participant_session_state` | Per-device session state record |
| `android_runtime_transition_reducer` | Runtime state transition reducer |

### 5.7 Multi-device coordination

| Module | Frozen Role |
|---|---|
| `core/multi_device_coordination_authority.py` | Multi-device governance center |
| `core/multi_device_canonical_governance.py` | Canonical multi-device governance model |
| `core/multi_device_control_integrity.py` | Multi-device V3 dimension 5 delegate |
| `core/multi_device_truth_convergence.py` | Multi-device result convergence |

### 5.8 Replay / recovery

| Module | Frozen Role |
|---|---|
| `replay_foundation.py` | Terminal-state event emission and replay ordering |
| `replay_audit_persistence.py` | Audit trail for replay |
| `offline_replay_ordering_contract.py` | Ordering guarantees |
| `runtime_restart_recovery.py` | In-flight task recovery on restart |
| `android_v2_continuity_contract.py` | Joint Android-V2 continuity verification |

### 5.9 Boundary and startup

| Module | Frozen Role |
|---|---|
| `V6 center_authority_boundary` | Startup / health / release integrity assertions only |
| `main.py → SystemOrchestrator` | 7-phase startup authority |
| `DesktopPresenceRuntime` | Outer runtime shell; tri-state lifecycle (silent/liminal/manifest) |

---

## 6. Fusion Targets for Follow-Up PRs

Based on the terminal audit, the following items require implementation work to close the known split-brain gaps. They are listed in priority order.

### P0 — Critical split-brain closures

1. **Wire V3 into `CommandRouter.route_envelope()`** (dispatch legality fusion)  
   `get_canonical_dispatch_slots()` as a pre-dispatch additive step.  
   ~20 lines. Additive only. Existing ACL gate retained as fallback.

2. **Confirm V4 is NOT forced into per-request `OpenClawd.process()`**  
   V4 must be scoped to multi-step orchestration sessions only.  
   Add assertion documentation. Verify no existing PR has silently inserted V4 into `OpenClawd`.

### P1 — Truth chain hardening

3. **Harden V2 truth chain**  
   Replace `try/except` soft wrapping on Steps 1–3 with hard enforcement.

4. **Add V1 result-ingress pre-check**  
   Add `evaluate_continuity_legality(RESULT_INGRESS)` in `android_bridge.handle_task_result()` before entering V2 chain.

### P2 — Cognitive authority fusion

5. **Fuse L1/L2/L3 into `UnifiedLLMRouter`**  
   Wire `LLMRouteAuthority`, `LLMSupplyAuthority`, `CognitiveContextAuthority` as pre-selection gates inside `UnifiedLLMRouter.select_route()`.

### P3 — Participant model generalization

6. **Define `ParticipantTruthIngressProtocol`** abstract interface  
   `core/participant_truth_ingress.py` — Android impl remains, interface generalized.

7. **Define `ParticipantTruthKind` base enum**  
   Android-specific `AndroidParticipantTruthKind` extends it.

8. **Update V6 import** to reference generic `participant_truth_ingress`.

9. **Update `CanonicalCompletionIngress` docstring** from "Android handoff result" to "participant result".

10. **Update V6 startup call** — add `assert_center_authority_intact()` to `SystemOrchestrator` Phase 7.

---

## 7. Preservation Guarantees

The following capabilities are frozen as first-class parts of the architecture. No subsequent implementation work may remove, replace, or narrow them.

### 7.1 Local execution capability

The local execution domain (`_determine_execution_path() → "local"` → `HybridExecutionArbiter`) must be preserved as a first-class execution path. It may not be removed, deprecated, or converted to a stub.

### 7.2 Cross-device execution capability

`CommandRouter.route_envelope()` and the `galaxy_gateway` transport substrate must be preserved as the cross-device dispatch spine. This chain may not be replaced.

### 7.3 Multi-device, delegated, handoff, replay, and continuity capabilities

All multi-device coordination, delegated execution, handoff/takeover, replay/recovery, and session continuity flows are first-class capabilities. They may not be narrowed, removed, or converted to stubs. V5, V3 dimension 10, and the replay foundation modules are part of the production architecture.

### 7.4 Participant model generalizability

The participant model must not be hardcoded to Android at the authority/interface level. Android is a concrete implementation. Any effort to generalize participant interfaces must not break the existing Android implementation.

### 7.5 Cognitive spine integrity

`OpenClawd.process()` must not be replaced, wrapped, or bypassed. It is the single cognitive entry point and the highest-risk module for accidental breakage.

### 7.6 Completion truth integrity

The V2 truth chain, `CanonicalCompletionIngress`, and V5 group completion closure must not be weakened. They may only be strengthened (hardened).

---

## 8. Prohibited Patterns

These patterns are explicitly prohibited in any subsequent implementation PR:

| Anti-pattern | Why prohibited |
|---|---|
| Wrapping `OpenClawd.process()` with a new outer authority | Would duplicate the cognitive entry point, creating split-brain |
| Forcing V4 as a synchronous per-request gate on `OpenClawd` | V4 governs orchestration sessions, not per-task dispatch |
| Forcing V6 into the request hot path | V6 is a boundary/startup/health layer; hot-path insertion is a category error |
| Replacing `CommandRouter.route_envelope()` with a new dispatch substrate | This is the confirmed dispatch spine; replace = split-brain |
| Creating a new meta-authority coordinator above V3 + `CommandRouter` | Creates a third dispatch authority, compounding split-brain |
| Narrowing participant truth ingress to Android-only at the interface level | Prevents non-Android participant runtimes |
| Removing the local execution domain | Destroys the local-first runtime capability |
| Removing multi-device, delegated, replay, or continuity flows | Destroys confirmed production capabilities |
| Keeping dead protocol paths active after authority fusion | Creates runtime/protocol mismatch |
| Inserting L4 into `OpenClawd.process()` Stage 2 or 3 | L4 is the outer autonomous loop, not a per-request cognitive gate |

---

## 9. Final Integration Completeness Criteria

The system shall be considered fully integrated when all of the following are simultaneously true:

1. V3 `get_canonical_dispatch_slots()` is wired into `CommandRouter.route_envelope()` as a pre-dispatch step.
2. V4 is confirmed not on the per-request `OpenClawd.process()` hot path.
3. V2 truth chain steps 1–3 are hard-enforced (not soft `try/except`).
4. V1 continuity legality is called both via V3 (dispatch) and directly in `handle_task_result()` (result ingress).
5. L1, L2, L3 are fused into `UnifiedLLMRouter` as pre-selection gates.
6. `ParticipantTruthIngressProtocol` abstract interface is defined; A1 Android implementation delegates through it.
7. V6 is called at startup Phase 7, health endpoint, and CI release gate — and nowhere in the request hot path.
8. Local and cross-device execution domains are both confirmed runnable.
9. Multi-device, delegated, handoff, replay, and continuity flows are confirmed runnable.
10. No dead declared protocol paths remain.

---

## 10. Final Principle

> **The system must end as one center-distributed runtime with one integrated authority model and multiple preserved execution domains — not as a compromise between old runnable paths and new authority declarations, but as their complete fusion into a single operational truth.**

This principle is not aspirational. It reflects the architecture that already exists in the system's runnable spine and correctly designed authority infrastructure. The remaining implementation work is fusion, hardening, and generalization — not redesign.

---

*This document is frozen as of the terminal dual-repository audit dated 2026-04-30. Modifications require a new architecture freeze document superseding this one.*
