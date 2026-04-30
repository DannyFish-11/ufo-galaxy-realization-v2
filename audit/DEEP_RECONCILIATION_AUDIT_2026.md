# Deep Dual-Repository Architecture-Reconciliation Audit

> **Repositories Audited**:  
> — `DannyFish-11/ufo-galaxy-realization-v2` (center repo, Python/FastAPI)  
> — `DannyFish-11/ufo-galaxy-android` (Android runtime repo, Kotlin)
>
> **Method**: Bottom-up, code-only traversal across both repositories.  
> No prior PRs, audit documents, or design documents used as evidence.  
> Every finding is backed by a named file, import chain, or grep result.  
>
> **Date**: 2026-04-30  
> **Supersedes**: Prior audits in `COMPLETE_DUAL_REPO_SYSTEM_AUDIT_2026.md`,  
> `CENTER_DISTRIBUTED_SYSTEM_FINAL_VERDICT.md`, `DUAL_REPO_SYSTEM_AUDIT.md`  
> **Purpose**: Reconciliation — determine whether newer authority structures are  
> genuinely integrated, redundant, parallel, conflicting, or partially correct.

---

## Bottom-Line Verdict First

> The dual-repo system has a **genuine, runnable center-distributed runtime**
> whose primary hot paths are operationally closed. The newer authority
> structures (V1–V6, and their center-side Android companions A1–A4) are
> **architecturally real but operationally split-brain**: they declare
> exclusive authority over execution paths they do **not** actually intercept
> at runtime. The central tension is a **control conflict** — the V4
> orchestration spine and V3 dispatch-slot authority each declare they are the
> mandatory gate for ALL execution modes, but the primary hot path
> (`OpenClawd.process() → CommandRouter.route_envelope()`) does **not** call
> either of them. This is not a case where the new layers are simply
> "unfinished" — they are fully built — but a case where the authority
> declarations and the actual runtime execution paths have diverged and run
> in parallel without being wired together.

---

## Part 1: What the Dual-Repo System Actually Is

### 1.1 Center Repo Runtime Identity

From code traversal, `ufo-galaxy-realization-v2` is a **center-governed,
Windows-first distributed runtime**. Its true identity is:

| Role | Code evidence |
|---|---|
| **System startup authority** | `main.py` → `SystemOrchestrator.run_startup_sequence()` 7-phase |
| **Cognitive entry point** | `core/openclawd.py` `OpenClawd.process()` |
| **LLM dispatch** | `core/unified/llm_router.py` → `core/multi_llm_router.py` → providers |
| **Cross-device dispatch substrate** | `core/command_router.py` `CommandRouter.route_envelope()` |
| **Android protocol bridge** | `galaxy_gateway/android_bridge.py` + `android/handlers/` |
| **Task lifecycle truth** | `core/task_lifecycle.py` + Future-based completion |
| **Device presence** | `core/device_registry.py`, `core/attached_runtime_session_registry.py` |
| **Completion ingress** | `core/canonical_completion_ingress.py` |

The center is the **governance authority** for session continuity, dispatch
targeting, and task completion. Android devices are participants that receive
and execute center-dispatched tasks.

### 1.2 Android Repo Runtime Identity

`ufo-galaxy-android` is a **participant runtime** inside the center-governed
system. Its true identity is:

| Role | Code evidence |
|---|---|
| **WS connection lifecycle** | `GalaxyConnectionService.kt` (161 KB) |
| **AIP v3 protocol client** | `GalaxyWebSocketClient.kt` (69 KB) |
| **Offline buffering** | `OfflineTaskQueue.kt` |
| **UI automation executor** | `EdgeExecutor.kt` (MobileVLM + SeeClick + AccessibilityService) |
| **On-device autonomous execution** | `AutonomousExecutionPipeline.kt` |
| **Handoff/takeover** | `AgentRuntimeBridge.kt`, `DelegatedTakeoverExecutor.kt` |
| **Readiness self-report** | `ReadinessChecker.kt` |
| **Multi-device coordination surface** | `MultiDeviceCoordinator.kt`, `FormationCoordinationSurface.kt` |
| **Protocol schema** | `AipModels.kt` (103 KB, AIP v3 full model layer) |

The Android side is **not** an independent agent. It only executes tasks
center-dispatched via AIP v3 `task_assign` / `goal_execution` /
`handoff_envelope_v2` messages.

### 1.3 System Identity: How They Divide Responsibilities

```
CENTER (ufo-galaxy-realization-v2)
  ├─ owns: session truth, completion truth, dispatch authority
  ├─ owns: cognitive routing (LLM path)
  ├─ owns: cross-device targeting policy
  └─ bridges via: AIP v3 WebSocket (galaxy_gateway/android_bridge.py)
            │
            │  AIP v3 bidirectional protocol
            │
ANDROID (ufo-galaxy-android)
  ├─ owns: on-device execution (EdgeExecutor, AutonomousExecutionPipeline)
  ├─ owns: WS connection lifecycle (GalaxyConnectionService)
  ├─ owns: offline buffering (OfflineTaskQueue)
  └─ reports: readiness + results → center
```

This is **one system**, not two. Center = policy and cognition. Android =
execution participant.

---

## Part 2: The Real Hot Path (What Actually Runs)

### 2.1 Cognitive Hot Path

Confirmed by grep showing no authority-layer interception:

```
main.py
  └─ unified_launcher.py
        └─ OpenClawd.process()
              └─ _determine_execution_path()
                    ├─ "local"       → DecisionExecutor (Windows API)
                    ├─ "cross_device"→ CommandRouter.route_envelope()
                    ├─ "hybrid"      → DecisionExecutor + CommandRouter concurrently
                    └─ "none"        → respond only
```

**LLM routing sub-path** (inside `OpenClawd.process()`):
```
UnifiedLLMRouter → MultiLLMRouter → provider APIs
```

**Authority layers that OpenClawd DOES NOT call**:
- `evaluate_orchestration_request()` (V4 spine): grep confirms **zero calls** in `openclawd.py`
- `get_canonical_dispatch_slots()` (V3): grep confirms **zero calls** in `openclawd.py`
- `unified_continuity_legality_authority` (V1): not called on the cognitive entry path

### 2.2 Cross-Device Dispatch Hot Path

`CommandRouter.route_envelope()` has confirmed **hard enforcement gates**:

| Gate | Code | Type |
|---|---|---|
| ACL check | `get_acl_enforcer().check()` | HARD block |
| Capability-mismatch | `CAPABILITY_MISMATCH` error return | HARD block |
| No-target | envelope validation | HARD block |
| HITL for high-risk commands | `_is_high_risk_command()` approval window | CONDITIONAL block |

**Authority layers that CommandRouter DOES NOT call**:
- `evaluate_orchestration_request()` (V4 spine): grep confirms **zero calls** in `command_router.py`
- `get_canonical_dispatch_slots()` (V3): grep confirms **zero calls** in `command_router.py`

### 2.3 The One Exception: `goal_execution.py`

The **only** production code call to `evaluate_orchestration_request()` outside tests is:

```python
# galaxy_gateway/android/handlers/goal_execution.py
from core.unified_orchestration_spine import evaluate_orchestration_request
_orch_decision = evaluate_orchestration_request(_orch_request)
```

This is a **single inbound handler** for Android-originated `goal_execution`
messages. It does not represent coverage of the main cross-device dispatch
path originating from `OpenClawd.process()`.

### 2.4 Android-Side Execution Hot Path

```
GalaxyConnectionService.kt
  └─ GalaxyWebSocketClient.kt (AIP v3 message dispatch)
        ├─ task_assign → EdgeExecutor.kt (UI automation)
        ├─ goal_execution → AutonomousExecutionPipeline.kt
        ├─ handoff_envelope_v2 → AgentRuntimeBridge.kt → DelegatedTakeoverExecutor.kt
        └─ ping/heartbeat → connection keepalive
```

Android **does** call its own readiness gate:
```kotlin
// ReadinessChecker.kt called before device_register
```

Android result/completion flows back to center via AIP v3 `task_result` /
`goal_result` → `android_bridge.handle_task_result()` →
`run_task_result_truth_chain()` → `CanonicalCompletionIngress.notify()`.

---

## Part 3: Classifying Each Authority Layer

### 3.1 Classification Taxonomy

For each authority module, the audit assigns one of six categories:

| Category | Meaning |
|---|---|
| **HOT-PATH-ENFORCED** | Actually called during execution; blocks or modifies dispatch |
| **USEFUL CANONICALIZATION** | Correct semantic work, but called only in some paths |
| **PARTIAL OVERLAP** | Partially duplicates existing hot-path logic |
| **SHADOW AUTHORITY** | Declares authority over a path it does not intercept |
| **DEAD ABSTRACTION** | Protocol slot declared, never executed |
| **POLICY DECLARATION BOUNDARY** | Correct domain separation, but not runtime-enforced |

---

### 3.2 V-Series Authority Modules

#### V1 — `core/unified_continuity_legality_authority.py`
**Classification: PARTIAL OVERLAP / SHADOW AUTHORITY**

- Provides a single gate for 8 inbound-action continuity legality paths
- Is called from: `core/flow_continuity_coordinator.py` (soft advisory), route-layer
- **Not called from**: `OpenClawd.process()`, `CommandRouter.route_envelope()`
- The hot path applies its own posture checks (`source_runtime_posture` via
  `check_source_execution_eligibility()` in CommandRouter Gate A)
- **Verdict**: Genuinely useful canonicalization of a fragmented legacy problem,
  but currently operating in **parallel** with the CommandRouter's posture gate —
  neither references the other. Not a conflict because they live in different
  enforcement points, but there is **semantic overlap** around continuity/posture
  that should be resolved by having CommandRouter consume V1 rather than maintain
  its own posture check.

#### V2 — Completion truth modules
**Classification: HOT-PATH-ENFORCED (partially)**

Includes: `core/unified_result_ingress.py`, `core/canonical_completion_ingress.py`,
`core/task_result_canonical_truth_chain.py`, `core/canonical_group_completion_closure.py`

- `canonical_completion_ingress.py` is **genuinely hot-path**: called from
  `android_bridge.handle_task_result()` → resolves asyncio Futures
- `unified_result_ingress.py` and `task_result_canonical_truth_chain.py` are
  consumed by the bridge handler chain
- `canonical_group_completion_closure.py` covers group/delegated terminal
  semantics: hot in delegated paths
- **Verdict**: V2 completion truth is the **best-integrated** of the V-series.
  These modules are genuinely in the hot path for the completion ingress. No
  reconciliation needed here — this is working as intended.

#### V3 — `core/canonical_dispatch_slot_authority.py`
**Classification: SHADOW AUTHORITY**

- Declares a 10-dimension dispatch gate that "ALL execution modes MUST consume"
- Is consumed by: V4 orchestration spine only
- `CommandRouter.route_envelope()` does **not** call V3
- `OpenClawd.process()` does **not** call V3
- Is called from: tests + V4 spine + `center_authority_boundary.py` (assertion only)
- V3 internally delegates to `unified_dispatch_readiness_gate` (dimensions 1–3, 5, 9)
  and `unified_continuity_legality_authority` (dimension 4) and
  `delegated_flow_acceptance_gate` (dimension 10)
- **Verdict**: V3 is a **correct canonicalization** of dispatch readiness into
  10 dimensions. It would add genuine semantic value if wired into the hot path.
  Currently it is a shadow authority: it declares ownership over dispatch
  decisions that CommandRouter makes independently using its own checks. This
  is **control overlap without integration** — not a runtime conflict, but a
  structural split.

#### V4 — `core/unified_orchestration_spine.py`
**Classification: SHADOW AUTHORITY (most critical finding)**

- Declares: "ALL execution modes MUST pass through `evaluate_orchestration_request()`"
- Consumed by: `galaxy_gateway/android/handlers/goal_execution.py` (1 call), tests
- **NOT consumed by**: `OpenClawd.process()`, `CommandRouter.route_envelope()`
- The V4 spine calls V3 (`get_canonical_dispatch_slots`) internally
- **The fundamental problem**: V4 claims mandatory authority over the very dispatch
  paths that form the center hot path, but those paths were built before V4 and
  continue to run without it. This is the most significant **control conflict**
  in the system.
- **Verdict**: V4 is a **genuine structural improvement** — it would unify all
  execution modes under one gate and provide lifecycle/audit records. But it is
  currently a **shadow authority**: architecturally complete, policy-declaring,
  but not intercepting the dispatch path it claims to own.

#### V5 — `core/canonical_group_completion_closure.py`
**Classification: HOT-PATH-ENFORCED (delegated/group paths)**

- Terminal semantics for group and delegated flows
- Called from delegated flow handlers and group result aggregation
- **Verdict**: Correctly placed. No reconciliation needed.

#### V6 — `core/center_authority_boundary.py`
**Classification: POLICY DECLARATION BOUNDARY**

- Provides `assert_center_authority_intact()` — a callable that checks the
  structural soundness of V2's authority boundary
- Is **not** called during execution; it is an assertion/audit module
- Called from: health checks, acceptance gates, tests
- **Verdict**: V6 is correctly classified as a policy declaration + assertion
  module. It should stay where it is — not be forced into the hot path. Its
  value is in gating releases and health checks, not intercepting execution.
  No reconciliation needed for its current role, but the assertions it makes
  about V3/V4 being "the dispatch authority" are currently false as runtime
  statements (they are structurally present but not called).

---

### 3.3 L-Series (L4 Runtime)

#### `GalaxyMainLoopL4Enhanced` — `core/galaxy_main_loop_l4_enhanced.py`
**Classification: USEFUL CANONICALIZATION / OUTER LOOP**

- The L4 runtime is the **outer autonomous execution loop** that calls
  `OpenClawd.process()` on a cycle
- It is the autonomous "agentic loop" mode of the center runtime
- Entry: `main.py` → `unified_launcher.py` manages the L4 loop
- The L-series is **not** an authority gate over individual requests —
  it is the outer scheduling/loop mechanism
- **Verdict**: Correctly scoped. L4 is the "outer shell" that calls the
  inner cognitive hot path. No conflict with V-series authority modules.
  The "L4 authority" refers to system-level operational mode governance,
  not per-request dispatch gating.

---

### 3.4 Android-Side Authority Companions (A-series)

#### `core/android_participant_truth_ingress.py` (A1-equivalent)
**Classification: USEFUL CANONICALIZATION / partially hot-path**

- Reconciles Android participant/session/runtime truth into V2 canonical state
- Is called via: bridge handler chain for `session_snapshot`, `readiness_assessment`,
  `task_phase`, `runtime_state`, `cancel`, `failure`, `result` signals
- Correct and necessary: closes TRUTH-005 gap
- **Verdict**: Well-placed. Should remain as the canonical truth ingress for
  Android-originated signals. No reconciliation needed.

#### `core/android_delegated_runtime_audit.py` (A-series audit module)
**Classification: POLICY DECLARATION BOUNDARY**

- Audit/observability surface for delegated runtime lifecycle
- Not in hot path; called from audit/monitoring only
- **Verdict**: Keep as-is.

#### Android governance uplinks (CRITICAL GAP)
**Classification: DEAD ABSTRACTION (center side)**

The Android side emits three governance uplink message types:
- `device_governance_report`
- `device_acceptance_report`
- `device_strategy_report`

These are **declared in the Android protocol** but the center bridge
(`galaxy_gateway/android_bridge.py`) has **no registered handler** for them.
They are sent by Android, received by the center's WS stack, and silently
dropped.

This is not a **runtime conflict** (no two systems fight over them) but a
**protocol gap**: Android is emitting signals that the center never consumes.
The center-side authority modules that would logically consume these signals
(e.g., `android_delegated_runtime_lifecycle_coordinator.py`) may exist
structurally but are not wired to the bridge handler map.

#### `hybrid_execute` protocol slot
**Classification: DEAD ABSTRACTION**

- Declared in both Python `MessageType` and Kotlin `MsgType`
- Android receives the message type but executes `sendHybridDegrade()` instead
  of actually performing hybrid execution
- Center side has no actual hybrid execution driver that uses this path
- **Verdict**: Confirmed dead path. Should be removed from the protocol or
  formally retired with a clear compat shim.

---

## Part 4: Structural Conflicts Identified

### 4.1 Control Conflict: V4 Spine vs. CommandRouter

**Type**: Control conflict (two places claiming dispatch authority)

The V4 `unified_orchestration_spine` declares:
```python
ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY = (
    "No execution mode may bypass evaluate_orchestration_request()."
)
```

But `CommandRouter.route_envelope()` — the actual dispatch path called by
`OpenClawd` — does not call `evaluate_orchestration_request()`. This means:

- V4 says it owns all dispatch decisions.
- `CommandRouter` makes dispatch decisions independently (ACL, capability check,
  constraint chain, posture filter, target admissibility).
- Neither module knows about or defers to the other on dispatch.

**This is the primary architectural split-brain.** Two dispatch authorities
coexist without connection.

**Impact assessment**: No **runtime collision** (there is no bug where both
fire and disagree — only one fires). But the split means:
- The 10-dimension V3 gate (occupancy, delegated acceptability, mode eligibility)
  is never enforced on the main OpenClawd → CommandRouter path
- The lifecycle stage tracking and audit records V4 produces are not generated
  for most dispatches
- V4's completion contract is not used by the primary path

### 4.2 Semantic Overlap: V1 Continuity Gate vs. CommandRouter Posture Gate

**Type**: Partial overlap / semantic duplication

`unified_continuity_legality_authority` (V1) provides a single gate for
continuity legality across 8 inbound-action paths.

`CommandRouter.route_envelope()` independently implements Gate A
(`check_source_execution_eligibility()` via `source_runtime_posture`) which
overlaps with V1's continuity/posture checks.

**Impact**: Soft. Neither blocks the other. But the system has two different
definitions of "continuity legality" that may diverge.

### 4.3 Protocol Gap: Android Governance Uplinks Without Center Consumers

**Type**: Protocol mismatch

Android emits `device_governance_report` / `device_acceptance_report` /
`device_strategy_report`. The center has no bridge handler for them. These
signals are sent, not consumed.

**Impact**: Governance signals that Android intends to communicate to the
center (e.g., that a device is in a particular governance state) are silently
lost. If any center logic was intended to respond to these signals, it does
not.

### 4.4 Dead Path: `hybrid_execute`

**Type**: Dead abstraction

Protocol declares hybrid execution. Android degrades to `sendHybridDegrade()`.
Center has no hybrid execution driver.

**Impact**: Any task dispatched with `HYBRID_EXECUTE` intent will silently
not execute the hybrid logic. Not a conflict — just a dead declared path.

### 4.5 Startup Chain Softness (Not a Conflict, But a Gap)

The startup preflight (`_run_orchestrator_preflight()`) catches all exceptions
and returns `True` (proceed). Every 7-phase failure degrades to `DEGRADED`
rather than blocking startup. This means:

- Pre-flight is **advisory**, not mandatory
- A system where all 7 phases fail still starts
- Authority boundaries are never confirmed before the server accepts traffic

**Impact**: Not a runtime conflict, but a gap in the authority enforcement
chain. V6 `assert_center_authority_intact()` could be called during startup
to provide a hard gate, but it currently isn't.

---

## Part 5: Are the Newer Authority Structures Integral or Parallel?

### Direct Answer

The V-series (V1–V6) and their Android companions are **neither fully integral
nor purely parallel**. They occupy a third state:

> **Architecturally complete policy layers that were built as mandatory gates
> but were never wired into the execution paths they were intended to govern.**

More precisely:

| Module | Status |
|---|---|
| V2 (completion truth) | **INTEGRAL** — genuinely in the completion hot path |
| V5 (group completion) | **INTEGRAL** — in the delegated/group completion path |
| A1 (participant truth ingress) | **INTEGRAL** — in the Android bridge handler chain |
| V1 (continuity legality) | **PARTIAL** — exists, some paths use it, hot path does not |
| V3 (dispatch slot authority) | **PARALLEL** — correct semantics, not wired to dispatch hot path |
| V4 (orchestration spine) | **PARALLEL** — correct architecture, not called from OpenClawd or CommandRouter |
| V6 (authority boundary) | **POLICY DECLARATION** — assertion module, not execution layer |
| Android governance uplinks | **PARALLEL (broken)** — emitted by Android, not consumed by center |
| `hybrid_execute` | **DEAD** — declared, never executed |

---

## Part 6: What the Ideal Integrated Architecture Should Look Like

### 6.1 The Real Primary Spine

The real primary spine today is:

```
main.py → unified_launcher.py → OpenClawd.process()
  → UnifiedLLMRouter (cognition)
  → CommandRouter.route_envelope() (cross-device dispatch)
     ├─ ACL gate [HARD]
     ├─ Capability-mismatch gate [HARD]
     ├─ Constraint chain (posture, admissibility, topology) [SOFT → should be HARD]
     └─ DeviceRouter → AIP v3 bridge → Android
```

Android completion loop:
```
Android AIP v3 result → android_bridge → task_result_truth_chain
  → CanonicalCompletionIngress.notify() → Future resolution → OpenClawd
```

### 6.2 What Should Be Fused Into the Primary Spine

**V3 dispatch-slot authority should be consumed by CommandRouter**:

The 10-dimension slot gate adds genuine semantics that CommandRouter currently
does not enforce:
- Dimension 6 (execution-mode eligibility) — not in CommandRouter
- Dimension 7 (occupancy/reservation) — not in CommandRouter
- Dimension 8 (policy allowance) — partially in CommandRouter's ACL, not unified
- Dimension 10 (delegated/handoff acceptability) — not in CommandRouter

**Recommended integration**:
```python
# In CommandRouter.route_envelope() before dispatch branching:
from core.canonical_dispatch_slot_authority import get_canonical_dispatch_slots
slots_result = get_canonical_dispatch_slots(target_device_ids, execution_mode)
# Use slots_result.approved_slots to filter dispatch targets
```

**V4 orchestration spine should be recognized as the correct wrapper**:

Rather than force V4 into OpenClawd, the cleaner architecture is:
- OpenClawd calls CommandRouter (unchanged)
- CommandRouter calls V3 (as above)
- V4 orchestration spine remains as the higher-level orchestration API for
  multi-step, multi-mode orchestration requests (e.g., from `goal_execution.py`)
  — this is its correct role and it already serves it in that one handler

**V1 continuity legality should be unified with CommandRouter's Gate A**:

CommandRouter's posture gate should delegate to `unified_continuity_legality_authority`
rather than maintaining its own parallel check. This eliminates the semantic
overlap.

### 6.3 What Should Remain as Boundary/Policy Layers

**V6 `center_authority_boundary`**: Keep as assertion module for health checks,
release gates, and acceptance tests. Do not force into hot path.

**V5 `canonical_group_completion_closure`**: Already correctly placed in the
delegated/group completion path. No change needed.

**V2 completion truth modules**: Already in hot path. No change needed.

**A1 `android_participant_truth_ingress`**: Already in bridge handler chain. No change.

### 6.4 What Should Be Fixed or Removed

**Android governance uplinks**: Either:
- Add center bridge handlers for `device_governance_report`,
  `device_acceptance_report`, `device_strategy_report` in `android_bridge.py`
- OR formally retire these message types by removing them from the Android
  protocol and documentation

**`hybrid_execute`**: Retire formally. Either remove from `MessageType`/`MsgType`
enums with a compat tombstone, or implement the center-side hybrid executor.
Do not leave a dead path in the protocol.

**Startup pre-flight softness**: Call `assert_center_authority_intact()` from
`SystemOrchestrator` Phase 7 (READINESS_SUMMARY) so that authority boundary
gaps become observable at startup, not only at test time.

---

## Part 7: Reconciliation Strategy and Recommended Actions

### Priority 1 (HIGH) — Wire V3 into CommandRouter

**Action**: Integrate `get_canonical_dispatch_slots()` into
`CommandRouter.route_envelope()` as a pre-dispatch gate.

**Location**: `core/command_router.py`, inside `route_envelope()`, after
the existing ACL check and before execution branching.

**What this closes**: Occupancy gating (dim 7), execution-mode eligibility
(dim 6), policy allowance unification (dim 8), delegated/handoff acceptability
(dim 10).

**Risk**: Low. The V3 gate degrades gracefully when sub-modules are
unavailable. The existing ACL and capability gates remain in place;
V3 adds dimensions they don't cover.

```python
# Recommended addition in route_envelope() after ACL gate:
try:
    from core.canonical_dispatch_slot_authority import get_canonical_dispatch_slots
    slot_result = get_canonical_dispatch_slots(
        device_ids=target_ids,
        execution_mode=execution_mode_str,
        task_id=envelope.task_id,
    )
    blocked = [s for s in slot_result.slots if s.status.value != "SLOT_APPROVED"]
    if blocked and not slot_result.approved_slots:
        return _make_slot_blocked_result(envelope, blocked)
    target_ids = [s.device_id for s in slot_result.approved_slots]
except Exception:
    pass  # graceful degradation
```

### Priority 2 (HIGH) — Fix Android Governance Uplink Gap

**Action**: Add bridge handlers for `device_governance_report`,
`device_acceptance_report`, `device_strategy_report` in
`galaxy_gateway/android_bridge.py`.

**Minimum viable handler**: Log + forward to
`android_delegated_runtime_lifecycle_coordinator` or equivalent.

**Alternative**: If these signals are not actually intended to trigger
center logic, remove them from the Android protocol to close the dead path.

### Priority 3 (MEDIUM) — Retire `hybrid_execute`

**Action**: Remove `HYBRID_EXECUTE` / `hybrid_execute` from `MessageType`
(Python) and `MsgType` (Kotlin). Add compat tombstone that logs a warning
and returns a structured "not implemented" response.

**What this closes**: Removes a silent dead path from both sides of the protocol.

### Priority 4 (MEDIUM) — Unify Continuity Gating

**Action**: Replace CommandRouter's inline posture gate (Gate A,
`check_source_execution_eligibility`) with a call to
`unified_continuity_legality_authority`.

**What this closes**: Eliminates semantic overlap between V1 and CommandRouter's
posture check. Single source of truth for continuity legality.

### Priority 5 (LOW) — Add Startup Authority Check

**Action**: In `SystemOrchestrator.run_startup_sequence()` Phase 7
(READINESS_SUMMARY), call `assert_center_authority_intact()` from
`core/center_authority_boundary.py` and log the result.

**What this closes**: Makes authority boundary gaps visible at startup
rather than only at test time. Does not need to be a hard block — logging
a WARNING when authority domains are degraded is sufficient.

### Priority 6 (LOW) — Add Integration Tests for the Wired Path

Add tests in `tests/` that verify:
1. `CommandRouter.route_envelope()` consults V3 slot authority (after Priority 1)
2. Android governance uplink messages have registered handlers (after Priority 2)
3. `hybrid_execute` returns a structured "not-implemented" response (after Priority 3)

---

## Part 8: Summary Classification Table

| Module / Path | Classification | Action |
|---|---|---|
| `OpenClawd.process()` → `UnifiedLLMRouter` | **HOT-PATH-ENFORCED** | No change |
| `CommandRouter.route_envelope()` ACL + capability gates | **HOT-PATH-ENFORCED** | No change |
| `canonical_completion_ingress.py` (V2) | **HOT-PATH-ENFORCED** | No change |
| `task_result_canonical_truth_chain.py` (V2) | **HOT-PATH-ENFORCED** | No change |
| `canonical_group_completion_closure.py` (V5) | **HOT-PATH-ENFORCED (delegated)** | No change |
| `android_participant_truth_ingress.py` (A1) | **HOT-PATH-ENFORCED (bridge)** | No change |
| `AIP v3 protocol bridge` | **HOT-PATH-ENFORCED** | No change |
| `OfflineTaskQueue` + session replay | **HOT-PATH-ENFORCED (Android)** | No change |
| `unified_continuity_legality_authority.py` (V1) | **PARTIAL OVERLAP** | Wire into CommandRouter Gate A |
| `canonical_dispatch_slot_authority.py` (V3) | **SHADOW AUTHORITY** | Wire into `CommandRouter.route_envelope()` |
| `unified_orchestration_spine.py` (V4) | **SHADOW AUTHORITY** | Keep for multi-step orchestration; wire V3 into CommandRouter as the fix |
| `center_authority_boundary.py` (V6) | **POLICY DECLARATION BOUNDARY** | Add to startup READINESS_SUMMARY phase |
| `GalaxyMainLoopL4Enhanced` (L4 loop) | **USEFUL CANONICALIZATION** | No change; correctly scoped as outer loop |
| Android governance uplinks | **DEAD ABSTRACTION (center side)** | Add bridge handlers or retire message types |
| `hybrid_execute` protocol slot | **DEAD ABSTRACTION** | Retire from both sides of protocol |
| `unified_dispatch_readiness_gate.py` | **HOT-PATH-ENFORCED (via V3)** | No change; already consumed by V3 |
| Startup pre-flight phases 1–7 | **SOFT-PATH (degraded-always)** | Add V6 assertion to Phase 7 |

---

## Part 9: How Local and Cross-Device Chains Form One System

### 9.1 Local Chain (Windows-centric)

```
OpenClawd.process() → "local" branch
  └─ DecisionExecutor → WindowsExecutionArbiter → Windows APIs
```

The local chain is the Windows desktop subject's autonomous execution loop.
It is the "inner loop" of the system — fast, local, no network.

### 9.2 Cross-Device Chain (distributed)

```
OpenClawd.process() → "cross_device" branch
  └─ CommandRouter.route_envelope()
        └─ DeviceRouter → AIP v3 WS → Android device
              ├─ EdgeExecutor (UI automation)
              └─ AutonomousExecutionPipeline (LLM-driven goals)
```

### 9.3 Why They Are One System

Both chains share:
- Same cognitive entry point (`OpenClawd.process()`)
- Same session/task lifecycle state (`task_lifecycle.py`)
- Same completion resolution mechanism (`CanonicalCompletionIngress`)
- Same LLM routing layer (decisions made before the branch)
- Same ACL policy (`get_acl_enforcer()`)

The branching is a **liminal domain decision** — same subject, different
execution substrate. Cross-device execution is the subject's liminal domain
expanding beyond the local Windows host. It is not a separate system; it is
the same system extended.

---

## Part 10: Final Reconciliation Model

### The System Is Real and Runnable

The dual-repo system is a genuine center-governed distributed runtime with a
working hot path that spans both repositories. It is not a conceptual system.
It can execute tasks, dispatch to Android, receive results, and close
completion Futures.

### The Authority Architecture Is Architecturally Complete But Operationally Split

The authority architecture (V3 dispatch-slot gate, V4 orchestration spine,
V6 boundary) represents correct, well-designed policy work. The problem is
that it was built without being wired into the hot path that already existed
and continued to run without it.

This produced an **architecture split-brain**:
- The policy layers say "all dispatch must go through me"
- The execution path continues to run without them

### The Path to Reconciliation Is Concrete and Low-Risk

The split can be closed by:
1. Wiring V3 into `CommandRouter.route_envelope()` (Priority 1)
2. Adding center handlers for Android governance uplinks (Priority 2)
3. Retiring `hybrid_execute` (Priority 3)
4. Unifying continuity gating V1 → CommandRouter (Priority 4)
5. Adding V6 to startup Phase 7 (Priority 5)

None of these require restructuring the hot path. They are additive changes
that bring the authority layers into the path they were designed for, without
replacing the working dispatch infrastructure that is already there.

### What Should Not Change

- `OpenClawd.process()` should remain the cognitive entry point
- `CommandRouter.route_envelope()` should remain the dispatch substrate
- V4 spine should remain the orchestration API for multi-step goal-execution
  handlers — it is correctly used in `goal_execution.py` and should stay
- V2/V5 completion truth modules are in the hot path and working — no change
- The AIP v3 protocol layer is operationally closed — no change
- The Android runtime participation chain is real and working — no change

### The One Honest Uncertainty

There is no dual-repo live E2E automated test that validates the full path
from `OpenClawd.process()` through `CommandRouter` through `android_bridge`
to Android and back. The audit can confirm that each segment is real and
connected, but the end-to-end round-trip has not been validated by a test
that would catch breakage at the integration seam. Adding such a test is
the clearest signal that the reconciled architecture is actually working as
an integrated system rather than a structurally complete set of individually
correct pieces.
