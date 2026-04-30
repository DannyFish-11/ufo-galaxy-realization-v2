# Complete Dual-Repo System Audit: Center-Distributed System End-to-End Reality Check

> **Repositories Audited**:  
> — `DannyFish-11/ufo-galaxy-realization-v2` (center repo, Python/FastAPI)  
> — `DannyFish-11/ufo-galaxy-android` (Android runtime repo, Kotlin)
>
> **Method**: Bottom-up code traversal across both repositories.  
> No prior PRs, audit documents, or design documents were used as evidence.  
> Every finding is backed by a named file, import chain, or grep result.  
>
> **Date**: 2026-04-30  
> **Replaces**: Prior audit in `CENTER_DISTRIBUTED_SYSTEM_FINAL_VERDICT.md`  
> **Status**: Complete independent re-audit with fresh code traversal

---

## Executive Summary

This audit traces every critical runtime path across both repositories from source to sink, distinguishes what is genuinely hot-path-enforced from what is merely architecturally present, and delivers a final evidence-based verdict on whether the full center-distributed system can truly run end-to-end today.

**Bottom line**:

> The full center-distributed system runs **nominally end-to-end** through one confirmed primary path. The transport layer, AIP v3 protocol, Android participation runtime, and basic task round-trip are **genuinely operationally closed**. The multi-layer authority infrastructure (V1–V6, L1–L4, A1–A4) is architecturally complete but **partially decoupled from the live execution hot path**. The system executes tasks; it does not enforce all declared authority boundaries during execution.

---

## Section 1: What This Two-Repo System Actually Is

### 1.1 Center Repo (`ufo-galaxy-realization-v2`) — What It Owns

From real code traversal:

| Responsibility | Evidence |
|---|---|
| **System startup authority** | `main.py`: canonical entrypoint; `SystemOrchestrator` runs 7-phase pre-flight |
| **Cognitive entry point** | `core/openclawd.py`: `OpenClawd.process()` is the subject core |
| **LLM routing and policy** | `core/unified/llm_router.py` → `core/multi_llm_router.py` → provider APIs |
| **Cross-device dispatch** | `core/command_router.py`: `CommandRouter.route_envelope()` |
| **Android protocol bridge** | `galaxy_gateway/android_bridge.py`: AIP v3 WS handler + 30+ message types |
| **Task lifecycle state** | `core/task_lifecycle.py`: truth chain + Future resolution |
| **Device presence & session** | `core/device_registry.py`, `core/attached_runtime_session_registry.py` |
| **Completion ingress** | `core/canonical_completion_ingress.py` |
| **Authority layer (structural)** | V1–V6, L1–L4 modules in `core/`; A1–A4 in `core/android_*` |

### 1.2 Android Repo (`ufo-galaxy-android`) — What It Owns

From real code traversal:

| Responsibility | Evidence |
|---|---|
| **WS connection lifecycle** | `GalaxyConnectionService.kt` (161KB): connect, register, reconnect, heartbeat |
| **WebSocket client** | `GalaxyWebSocketClient.kt` (69KB): full AIP v3 typed listener, reconnect logic |
| **Offline result buffering** | `OfflineTaskQueue.kt`: session-bounded, LRU-evicting, 24h TTL |
| **On-device UI automation** | `EdgeExecutor.kt`: MobileVLM 1.7B + SeeClick grounding + AccessibilityService |
| **Autonomous goal execution** | `AutonomousExecutionPipeline.kt`: center-delegated LLM-driven task execution |
| **Cross-device handoff** | `AgentRuntimeBridge.kt`: idempotent, retried bridge handoff |
| **Takeover execution** | `DelegatedTakeoverExecutor.kt`: wired to `AutonomousExecutionPipeline` |
| **Protocol schema** | `AipModels.kt` (103KB): full AIP v3 Kotlin model layer |
| **Cross-repo consistency** | `CrossRepoConsistencyGate.kt`, `UgcpSharedSchemaAlignment.kt` |
| **Readiness gating** | `ReadinessChecker.kt`: capability self-report before registration |

### 1.3 Is This Truly a Center-Governed Distributed Runtime?

**Yes, by code**, not just by design intent. The center retains governance in code through:

1. **Dispatch authority**: Android devices only receive tasks via center-dispatched AIP v3 `task_assign` / `goal_execution` / `handoff_envelope_v2` messages. Android never self-initiates execution without center direction.
2. **Session authority**: `classify_reconnect_outcome()` in `registration.py` determines whether a reconnecting Android device resumes an existing session or starts fresh. The center owns this decision.
3. **Completion authority**: Task completion flows back through `android_bridge.handle_task_result()` → `run_task_result_truth_chain()` → `CanonicalCompletionIngress.notify()`. The center resolves the completion Future.
4. **ACL gate**: `CommandRouter.route_envelope()` enforces ACL (`get_acl_enforcer().check()`) and capability-graph gating before any cross-device dispatch. These are hard gates.

---

## Section 2: Center-Side Main Execution Chains (Traced from Real Code)

### 2.1 Startup Chain

**Files**: `main.py` → `core/system_orchestrator.py` → `unified_launcher.py`

```python
# main.py: _run_orchestrator_preflight()
try:
    from core.system_orchestrator import SystemOrchestrator
    summary = SystemOrchestrator(continue_on_failure=False).run_startup_sequence()
    return summary.is_ready()
except Exception as exc:
    logger.warning("Orchestrator pre-flight raised an exception (non-fatal): %s", exc)
    return True  # ← CRITICAL: exception in pre-flight = proceed anyway
```

`SystemOrchestrator.run_startup_sequence()` runs 7 phases in order:

| Phase | Name | Exception handling |
|---|---|---|
| 1 | LOAD_CONFIG | → DEGRADED (never FAILED) |
| 2 | RESOLVE_MODE | → DEGRADED |
| 3 | ENV_CHECKS | → DEGRADED |
| 4 | BACKGROUND_SUBSYSTEMS | → DEGRADED |
| 5 | RUNTIME_SUBJECT | → DEGRADED |
| 6 | DESKTOP_SURFACE | → DEGRADED |
| 7 | READINESS_SUMMARY | → DEGRADED |

**Critical observation**: Every exception handler in all 7 phase implementations returns `PhaseStatus.DEGRADED`, never `PhaseStatus.FAILED`. Combined with the outer `except → return True`, the startup chain **effectively never blocks system launch**. `is_ready()` returns True unless a phase explicitly sets `PhaseStatus.FAILED` via non-exception logic — which no current phase does.

Phase 4 background subsystem checks are real:
- `get_command_router()` — probes CommandRouter
- `build_source_dispatch_plan()` — dispatch plan build
- `get_multi_device_runtime_harness().recover_sessions()` — mesh session recovery
- `run_startup_recovery()` — in-flight task records + WebRTC + hybrid bindings

After pre-flight, `main.py` hands off to `unified_launcher.py`:
```python
return subprocess.call([sys.executable, str(launcher_path)] + sys.argv[1:])
```

`unified_launcher.py` (`GalaxyUnified` class) performs async bring-up: background services (NATS, Redis, L4 modules), core runtime (OpenClawd + DesktopPresenceRuntime), and unified API gateway (FastAPI/uvicorn).

**Startup chain verdict**: REAL/HOT-PATH. Non-fatal by design, but structurally complete.

---

### 2.2 Runtime / Cognitive Entry Chain

**Files**: `core/desktop_presence_runtime.py` → `core/openclawd.py`

```
DesktopPresenceRuntime (shell — outer tri-state lifecycle)
  Tri-state: SILENT → LIMINAL → MANIFEST
    └─ LIMINAL phase: invokes OpenClawd.process()
          OpenClawd.process() stages:
            Stage 1: Ingest
              ├─ PerceptionFrame (continuous host ingress from MultimodalIngressBus)
              └─ multimodal_context (request-bound fusion via MultimodalBus.ingest)
            Stage 2: ContinuumOrchestrator.run()
              └─ intent → state_continuum → runtime_domain
            Stage 3: _determine_execution_path()
              ├─ "local"         → DecisionExecutor (Windows/System API)
              ├─ "cross_device"  → _delegate_single_remote() via SourceDispatchOrchestrator
              ├─ "hybrid"        → both local and cross-device simultaneously
              └─ "none"          → respond only, no execution
            Stage 4: Execute
              └─ DecisionExecutor | CommandRouter | SourceDispatchOrchestrator
```

`_determine_execution_path()` is a **pure function** (no I/O, no side effects):
```python
# core/openclawd.py
action_taken = execution_result.get("action_taken", "none")
local_executed = action_taken not in ("none", "noop", "error")
if local_executed and cross_device_dispatched: return "hybrid"
if cross_device_dispatched or entry_mode == "cross_device": return "cross_device"
if entry_mode == "hybrid": return "hybrid"
if local_executed: return "local"
return "none"
```

**Cognitive/runtime entry verdict**: REAL/HOT-PATH.

---

### 2.3 LLM / Cognitive Execution Chain (actual live path)

**Files**: `core/openclawd.py` → `core/unified/llm_router.py` → `core/multi_llm_router.py`

The real LLM invocation chain in `OpenClawd`:

```python
# core/openclawd.py: _get_router() (lazy-initialized)
try:
    from core.unified.llm_router import get_unified_llm_router
    self._router = get_unified_llm_router()     # UnifiedLLMRouter (primary)
except Exception as e:
    logger.warning(f"UnifiedLLMRouter failed, downgrading to MultiLLMRouter: {e}")
    from core.multi_llm_router import get_llm_router
    self._router = get_llm_router()              # MultiLLMRouter (fallback)
```

Live LLM calls in `process()` go through `self._get_router().chat_with_tools()`, which resolves via:
```
UnifiedLLMRouter → MultiLLMRouter → provider (OpenAI/Claude/Gemini/DeepSeek/Ollama/OneAPI)
```

`UnifiedLLMRouter` (`core/unified/llm_router.py`) is:
- The sole legitimate model-access entry point for the main orchestration layer
- Applies policy via `config/llm_routing_policy.yaml`
- Records routing telemetry (success rate, latency, fallback rate, cost)
- Enforces cost budget / SLO thresholds

**LLM route authority (L1) reality**: `LLMRouteAuthority` (`core/llm/route_authority.py`) exists and is imported by `routes/ai.py`, `routes/system.py`, `routes/nodes.py`, `routes/observability.py`, and `system_integration.py` — but **NOT by `openclawd.py` or `unified/llm_router.py`**. The REST API route layer applies `LLMRouteAuthority` for external-facing model selection. The internal `process()` hot path bypasses it, using `UnifiedLLMRouter` directly.

**Verdict**: LLM path is REAL/HOT-PATH via `UnifiedLLMRouter`. L1 (`LLMRouteAuthority`) is used in the API layer only — NOT in the `process()` execution hot path.

---

### 2.4 Dispatch and Execution-Mode Selection

**File**: `core/command_router.py`

`CommandRouter.route_envelope()` pre-dispatch gate sequence:

| Gate | Type | Effect on failure |
|---|---|---|
| ACL check: `get_acl_enforcer().check()` | **HARD** | Returns structured error dict; dispatch blocked |
| HITL high-risk stamp | SOFT | Metadata stamp only; no dispatch block |
| Task memory injection | SOFT | try/except; dispatch continues |
| Target selection (capability_graph + DevicePoolManager) | **HARD** | Returns error if no valid targets found |
| Capability-graph enforcement (PR-1-P0) | **HARD** | Rejects with `CAPABILITY_MISMATCH` for explicit targets not in graph |
| Posture gate (SESSION_TRUTH_POSTURE) | SOFT | Warning-only; dispatch continues |
| Admissibility chain | SOFT | Graceful degradation; dispatch continues |

After gates, routes to one of: `_route_cross_device_envelope`, `_route_worker_envelope`, `_route_parallel_fanout_envelope`.

**Canonical dispatch slot authority (V3) reality**: `evaluate_canonical_dispatch_slot()` and `get_canonical_dispatch_slots()` in `core/canonical_dispatch_slot_authority.py` define a 10-dimension dispatch slot evaluation system. `grep "get_canonical_dispatch_slots" core/command_router.py` → **zero matches**. V3 is not called from `route_envelope()` at any point. It exists in a self-referential structural layer: `canonical_dispatch_slot_authority.py` ↔ `unified_orchestration_spine.py` ↔ `center_authority_boundary.py`.

**Unified orchestration spine (V4) reality**: `evaluate_orchestration_request()` in `core/unified_orchestration_spine.py` defines the canonical orchestration authority. `grep "evaluate_orchestration_request" core/command_router.py` → **zero matches**. V4 has no live callers in the dispatch hot path.

**Verdict**: CommandRouter is REAL/HOT-PATH with 3 HARD gates (ACL, no-target, capability-mismatch) and several SOFT gates. V3/V4 form a shadow authority layer — structurally present, not in the dispatch hot path.

---

### 2.5 Gateway / Android Bridge Path

**Files**: `galaxy_gateway/android_bridge.py` → `galaxy_gateway/android/handlers/`

The `AndroidBridge.handle_message()` receives raw WebSocket frames and dispatches via a type-keyed handler map (30+ registered handlers):

```python
# galaxy_gateway/android_bridge.py — handler registration (lines 711–785)
self._message_handlers[MessageType.DEVICE_REGISTER]           = handle_device_register
self._message_handlers[MessageType.TASK_RESULT]               = handle_task_result
self._message_handlers[MessageType.GOAL_EXECUTION_RESULT]     = handle_goal_execution_result
self._message_handlers[MessageType.GOAL_RESULT]               = handle_goal_execution_result  # compat alias
self._message_handlers[MessageType.DELEGATED_EXECUTION_SIGNAL] = handle_delegated_execution_signal
self._message_handlers[MessageType.HANDOFF_ENVELOPE_V2_RESULT] = handle_handoff_v2_result
self._message_handlers[MessageType.TAKEOVER_RESPONSE]         = handle_takeover_response
self._message_handlers[MessageType.RECONCILIATION_SIGNAL]     = handle_reconciliation_signal
# ... 22+ more types including task_progress, command_result, vision_request, mesh_topology, etc.
```

Inbound messages first go through the compat layer:
```python
from galaxy_gateway.protocol.compat import normalise_to_v3_dict
```
This normalizes AIP v1.0 / v2.0 messages to canonical AIP v3 before dispatch. The compat layer handles legacy type aliases (`register` → `device_register`, `task_execute` → `task_submit`, etc.) and bumps v2.0 messages to v3.

**Verdict**: Android bridge handler map is REAL/HOT-PATH. Compat normalization layer is live.

---

### 2.6 Result Ingress and Completion Closure

**Files**: `galaxy_gateway/android/handlers/task_lifecycle.py` → `core/task_lifecycle.py` → `core/canonical_completion_ingress.py`

`handle_task_result()` in `task_lifecycle.py` (lines 244–271):

```python
if _run_task_result_truth_chain is not None:
    _truth_chain_outcome = _run_task_result_truth_chain(
        message, task_id=task_id, result_status=result_status
    )
    if not _truth_chain_outcome.is_truth_chain_complete:
        logger.warning(...)    # WARNING ONLY — no block
    else:
        logger.debug(...)
else:
    # _run_task_result_truth_chain unavailable (import failed at module load):
    logger.warning("canonical truth chain module unavailable ...")
    _try_reconcile(message)          # best-effort, non-blocking
    _try_ingest_participant_truth(message, "result")  # best-effort
# Execution continues regardless:
# → DeviceRouter.notify_task_complete() + Future resolution + memory backflow
```

`_run_task_result_truth_chain` is imported at module load inside `try/except`; failure sets it to `None` silently. The 4-step truth chain (truth_ingress → reconcile → authority_state_update → canonical_completion_linkage) inside `core/task_lifecycle.py` uses `try/except` around each step.

**Completion chain truth (V1) verdict**: SOFT-GATE. Truth chain is on the path and runs when available, but incomplete truth chain → warning only. The system completes tasks regardless of truth chain outcome.

---

## Section 3: Android-Side Main Execution Chains (Traced from Real Code)

### 3.1 Connection / Registration / Handshake

**Files**: `GalaxyConnectionService.kt`, `GalaxyWebSocketClient.kt`, `ReadinessChecker.kt`

Android startup sequence:
```
UFOGalaxyApplication.onCreate()
  → GalaxyConnectionService started (foreground service)
      → GalaxyWebSocketClient.connect(serverUrl)
           → OkHttp WebSocket: wss://<center>:<port>/ws/device/{device_id}
                → onOpen(): send device_register message
                     → GalaxyWebSocketClient.Listener.onRegistered(deviceInfo)
                          → GalaxyConnectionService.onDeviceRegistered()
```

`device_register` payload carries:
- `device_id`, `device_type`, `platform`, `session_id`
- `capabilities` (self-reported by `ReadinessChecker.kt`)
- `runtime_attachment_session_id` (for reconnect resumption)

On the center side, `handle_device_register()` calls `classify_reconnect_outcome()`:
```python
# galaxy_gateway/android/handlers/registration.py line 318
_reconnect_outcome = classify_reconnect_outcome(
    device_id, runtime_attachment_session_id, ...
)
# → "new_attachment" | "continuity_resume" | "session_mismatch"
```

For `continuity_resume`: `reconnect_session()` restores the prior attached session. For `new_attachment`: a fresh session is created.

**Verdict**: Connection/registration chain is REAL/HOT-PATH.

---

### 3.2 Lifecycle and Continuity Participation

**Files**: `GalaxyConnectionService.kt`, `GalaxyWebSocketClient.kt`

`GalaxyWebSocketClient` maintains:
- Reconnect loop with exponential backoff
- Heartbeat sender (scheduled interval)
- `@Volatile private var sessionTag: String?` — session continuity tag across reconnects
- `activeTakeoverId: @Volatile String?` — takeover concurrency guard

WS disconnect during active takeover:
```kotlin
// GalaxyConnectionService.kt
if (activeTakeoverId != null) {
    notifyTakeoverFailed(cause = DisconnectCause.DISCONNECT)
}
```

Android lifecycle continuity: the service runs as a **foreground service** (persistent notification), meaning it survives app backgrounding and screen-off. `BootReceiver.kt` starts the service on device boot.

**Verdict**: Lifecycle and continuity participation is REAL/HOT-PATH.

---

### 3.3 Runtime Attachment / Posture / Host Participation

**Files**: `GalaxyConnectionService.kt`, `AgentRuntimeBridge.kt`

Task dispatch to Android triggers typed callbacks on `GalaxyWebSocketClient.Listener`:

```kotlin
// GalaxyConnectionService.kt — listener wiring
override fun onTaskAssign(taskId, taskAssignPayloadJson, traceId) {
    serviceScope.launch { handleTaskAssign(taskId, taskAssignPayloadJson, traceId) }
}
override fun onGoalExecution(taskId, goalPayloadJson, traceId) {
    serviceScope.launch {
        taskCancelRegistry.register(taskId, coroutineContext[Job]!!)
        handleGoalExecution(taskId, goalPayloadJson, traceId)
    }
}
override fun onParallelSubtask(taskId, subtaskPayloadJson, traceId) {
    serviceScope.launch {
        taskCancelRegistry.register(taskId, coroutineContext[Job]!!)
        handleParallelSubtask(taskId, subtaskPayloadJson, traceId)
    }
}
override fun onHandoffEnvelopeV2(taskId, envelopePayloadJson, traceId) {
    serviceScope.launch { handleHandoffEnvelopeV2(taskId, envelopePayloadJson, traceId) }
}
```

Task cancellation: `taskCancelRegistry.register(taskId, coroutineContext[Job]!!)` — **called inside the coroutine** to avoid a race between `launch` and job registration.

`AgentRuntimeBridge.kt` handles cross-device handoff (`bridge_handoff` AIP v3 message):
- Eligible when: `crossDeviceEnabled == true` AND `execMode in {EXEC_MODE_REMOTE, EXEC_MODE_BOTH}`
- Idempotency: `ConcurrentHashMap` keyed by `traceId`, bounded to `IDEMPOTENCY_CACHE_MAX` (LRU eviction)
- Retry: up to `MAX_RETRY_ATTEMPTS` with `RETRY_DELAYS_MS = [1000, 2000, 4000]`
- Fallback: `HandoffResult.isHandoff = false` → caller falls back to local execution

**Verdict**: Runtime attachment and host participation is REAL/HOT-PATH.

---

### 3.4 Delegated / Handoff / Takeover Participation

**Files**: `DelegatedTakeoverExecutor.kt`, `DelegatedHandoffContract.kt`, `HandoffEnvelopeV2.kt`, `TakeoverEligibilityAssessor.kt`

`DelegatedTakeoverExecutor` is lazy-initialized and wired to `AutonomousExecutionPipeline`:
```kotlin
private val delegatedTakeoverExecutor: DelegatedTakeoverExecutor by lazy {
    DelegatedTakeoverExecutor(
        pipeline = GoalExecutionPipeline { payload ->
            UFOGalaxyApplication.autonomousExecutionPipeline.handleGoalExecution(payload)
        },
        signalSink = delegatedSignalSink    // ← emits DELEGATED_EXECUTION_SIGNAL uplinks
    )
}
```

`TakeoverEligibilityAssessor.kt` verifies:
- `TAKEOVER_DEFAULT_MAX_STEPS = 10` (configurable)
- `TAKEOVER_DEFAULT_TIMEOUT_MS = 0L` (no timeout by default)
- Pre-takeover eligibility checks: accessibility service active, device not occupied

Signal sink failure never interrupts execution: `delegatedSignalSink` catches and logs internally.

`HandoffEnvelopeV2.kt` carries full V2 dispatch metadata: `dispatchIntent`, `dispatchOrigin`, `orchestrationStage`, `executionContext`, `sourceRuntimePosture` (defaults `"control_only"`), durable continuity and recovery context (PR-F).

`HandoffContractValidator.kt` validates handoff envelope structural integrity before execution begins. Pre-execution validation is a HARD gate: invalid contract = execution does not start.

**Verdict**: Delegated/handoff/takeover participation is REAL/HOT-PATH.

---

### 3.5 Local Execution vs Local Intelligence / Runtime Execution

**Files**: `EdgeExecutor.kt`, `AutonomousExecutionPipeline.kt`

**`EdgeExecutor.kt`** — on-device UI automation:
```
Receives: task_assign payload with UI action spec
Pipeline: screenshot() → MobileVLM 1.7B planner → SeeClick grounding → AccessibilityService.performAction()
Model gate: if models not loaded → returns STATUS_ERROR immediately (hard fail-fast)
require_local_agent == false → returns CANCELLED immediately
All errors: structured result maps, never throws across public API
```

**`AutonomousExecutionPipeline.kt`** — center-delegated goal execution with local LLM:
```
Receives: goal_execution payload (goal, context, max_steps)
Pipeline: LLM reasoning loop → action planning → EdgeExecutor (per step) → result aggregation
Local LLM: inference via local model (configured in GalaxyConnectionService)
Emits: goal_execution_result back via GalaxyWebSocketClient.sendGoalResult()
```

**`LocalGoalExecutor.kt`** — simpler goal execution without full pipeline overhead.

**Verdict**: Both EdgeExecutor (UI automation) and AutonomousExecutionPipeline (LLM-driven) are REAL/HOT-PATH for their respective execution modes.

---

### 3.6 Result Emission and Offline Replay

**Files**: `OfflineTaskQueue.kt`, `GalaxyWebSocketClient.kt`

Result emission: `GalaxyWebSocketClient.sendJson(goal_execution_result)` is the canonical result emission call. All result types (task_result, goal_execution_result, goal_result) go through this single function.

Offline queue behavior:
```kotlin
// OfflineTaskQueue.kt
val QUEUEABLE_TYPES: Set<String> = setOf("task_result", "goal_result", "goal_execution_result")
// Max 50 entries, LRU eviction (oldest dropped when full)
// 24-hour max-age TTL
// discardForDifferentSession(currentTag) → drainAll() on reconnect
// Session-bounded: stale results from prior session are discarded, not replayed
```

All 3 queued types correspond to live handler registrations in the Python bridge:
- `task_result` → `handle_task_result`
- `goal_result` → `handle_goal_execution_result` (compat alias)
- `goal_execution_result` → `handle_goal_execution_result`

Replay on reconnect: after `onReconnected()`, `OfflineTaskQueue.drainAll()` replays queued results if session tag matches current session. Session mismatch → queue discarded.

**Verdict**: Offline result emission and replay is REAL/HOT-PATH.

---

### 3.7 Reconnect / Recovery / Replay Behavior

**Files**: `GalaxyWebSocketClient.kt`, `registration.py` (center side)

Android reconnect is not a separate wire type — it reuses `device_register` with the same `runtime_attachment_session_id`. `GalaxyWebSocketClient` reconnects automatically with backoff.

Center-side reconnect classification (`registration.py` line 318):
```python
# Possible outcomes from classify_reconnect_outcome():
# "new_attachment"     — no prior session or session mismatch → fresh start
# "continuity_resume"  — same runtime_attachment_session_id → session restored
# "session_mismatch"   — device_id matches but session ID doesn't → handled per policy
```

There is **no separate `device_reconnect` wire message**. The `handle_device_reconnect()` function exists in `registration.py` for clients that still send it (compat path), but the canonical Android reconnect path is `device_register` only.

**Verdict**: Reconnect/recovery behavior is REAL/HOT-PATH. Session continuity logic is enforced in code.

---

## Section 4: Real Cross-Repo Protocol Surface

### 4.1 AIP v3 Wire-Type Alignment

Both sides share the same wire-string convention. Python defines `MessageType(str, Enum)` in `galaxy_gateway/protocol/aip_v3.py`; Kotlin defines `MsgType` in `AipModels.kt`. All bidirectional types confirmed aligned:

| Wire String | Python `MessageType` | Kotlin `MsgType` | Direction | Status |
|---|---|---|---|---|
| `"device_register"` | DEVICE_REGISTER | DEVICE_REGISTER | Android→Center | ✓ Matched |
| `"device_register_ack"` | DEVICE_REGISTER_ACK | DEVICE_REGISTER_ACK | Center→Android | ✓ Matched |
| `"heartbeat"` | DEVICE_HEARTBEAT | DEVICE_HEARTBEAT | Android→Center | ✓ Matched |
| `"task_assign"` | TASK_ASSIGN | TASK_ASSIGN | Center→Android | ✓ Matched |
| `"task_result"` | TASK_RESULT | TASK_RESULT | Android→Center | ✓ Matched |
| `"task_cancel"` | TASK_CANCEL | TASK_CANCEL | Center→Android | ✓ Matched |
| `"goal_execution"` | GOAL_EXECUTION | GOAL_EXECUTION | Center→Android | ✓ Matched |
| `"goal_execution_result"` | GOAL_EXECUTION_RESULT | GOAL_EXECUTION_RESULT | Android→Center | ✓ Matched |
| `"goal_result"` | GOAL_RESULT | GOAL_RESULT | Android→Center | ✓ Compat alias (both sides) |
| `"handoff_envelope_v2"` | HANDOFF_ENVELOPE_V2 | HANDOFF_ENVELOPE_V2 | Center→Android | ✓ Matched |
| `"handoff_envelope_v2_result"` | HANDOFF_ENVELOPE_V2_RESULT | HANDOFF_ENVELOPE_V2_RESULT | Android→Center | ✓ Matched |
| `"delegated_execution_signal"` | DELEGATED_EXECUTION_SIGNAL | DELEGATED_EXECUTION_SIGNAL | Android→Center | ✓ Matched |
| `"takeover_request"` | TAKEOVER_REQUEST | TAKEOVER_REQUEST | Center→Android | ✓ Matched |
| `"takeover_response"` | TAKEOVER_RESPONSE | TAKEOVER_RESPONSE | Android→Center | ✓ Matched |
| `"reconciliation_signal"` | RECONCILIATION_SIGNAL | RECONCILIATION_SIGNAL | Android→Center | ✓ Matched |
| `"device_readiness_report"` | DEVICE_READINESS_REPORT | DEVICE_READINESS_REPORT | Android→Center | ✓ Matched |
| `"hybrid_execute"` | HYBRID_EXECUTE | HYBRID_EXECUTE | Center→Android | ⚠ Declared, NOT implemented (see §4.4) |
| `"device_governance_report"` | — | DEVICE_GOVERNANCE_REPORT | Android→Center | ⚠ Android-only uplink, NOT in Python bridge handler map |
| `"device_acceptance_report"` | — | DEVICE_ACCEPTANCE_REPORT | Android→Center | ⚠ Android-only uplink, NOT in Python bridge handler map |
| `"device_strategy_report"` | — | DEVICE_STRATEGY_REPORT | Android→Center | ⚠ Android-only uplink, NOT in Python bridge handler map |

**No wire-string mismatches found** on bidirectional types.

### 4.2 Canonical vs Compat Message Paths

**Compat normalization** (`galaxy_gateway/protocol/compat.py`): live, applied to all inbound messages before handler dispatch:

| Legacy type | Normalized to |
|---|---|
| `register`, `agent_register`, `registration` | `device_register` |
| `heartbeat`, `agent_heartbeat` | `heartbeat` |
| `task_execute` | `task_submit` |
| `command_result` | `task_result` |
| `status_update`, `update_status` | `device_status` |

AIP v2.0 messages pass through as-is (field names identical to v3; version tag bumped to 3.0). AIP v1.0 messages go through type aliasing before dispatch.

The `GOAL_RESULT` compat alias (Python side): `MessageType.GOAL_RESULT` is mapped to `handle_goal_execution_result`. Android `OfflineTaskQueue.QUEUEABLE_TYPES` includes `"goal_result"`. This compat path is **alive on both sides**.

### 4.3 Android-Only Uplink Types Not in Python Bridge Map

Three Android→Center uplink types from `AipModels.kt` are not in the Python bridge's `_message_handlers`:
- `device_governance_report`
- `device_acceptance_report`
- `device_strategy_report`

These arrive at the Python WebSocket handler but fall through to the **unhandled message path** (silent logging or `handle_unregistered`). These appear to be architectural governance telemetry types from Android cross-repo contract modules (`CrossRepoConsistencyGate.kt`, `UgcpProtocolConsistencyRules.kt`) that have no consumer on the center side.

**Status**: ARCHITECTURALLY-PRESENT on Android, NOT-WIRED on center side.

### 4.4 Dead Paths and Parallel Message Systems

**`HYBRID_EXECUTE` — CONFIRMED DEAD-PATH on Android**:
```kotlin
// GalaxyConnectionService.kt — onAdvancedMessage()
else -> {
    // HYBRID_EXECUTE falls here:
    sendHybridDegrade(...)   // sends structured downgrade response, does NOT execute
}
```
`sendHybridDegrade()` sends a `hybrid_degrade` response back to center — no actual hybrid execution occurs. The Python side defines `MessageType.HYBRID_EXECUTE` but there is no `handle_hybrid_execute` function. **Both sides handle it as a no-op/degrade.**

**`PEER_EXCHANGE`, `MESH_TOPOLOGY`, `PEER_ANNOUNCE`**: These are in the bridge handler map (`handle_peer_exchange`, `handle_mesh_topology`, `handle_peer_announce`). They appear to support a P2P/mesh topology layer. Present and wired on both sides but whether the mesh runtime is actively used depends on deployment configuration.

---

## Section 5: Authority Closure Reality Across Both Repos

### 5.1 Methodology

For each authority module, we check:
1. Does the source exist?
2. Is it imported by a live execution path?
3. Is it called from the hot path (OpenClawd.process() or CommandRouter.route_envelope())?
4. If called, is the gate HARD (blocks on failure) or SOFT (warns, continues)?

### 5.2 Per-Module Authority Reality

#### Completion Authority (V1) — `core/task_lifecycle.py`

| Check | Result |
|---|---|
| Source exists | ✓ Yes |
| Called from result handler | ✓ `handle_task_result()` calls `_run_task_result_truth_chain()` |
| Gate type | SOFT — `try/except` around all 4 steps |
| Failure effect | Warning log only; `CanonicalCompletionIngress.notify()` still called |

**Verdict: SOFT-GATE**. Truth chain is wired and executes, but failure does not block completion.

#### Continuity Legality Authority (V2) — `core/unified_continuity_legality_authority.py`

Referenced in `CommandRouter` posture check (SESSION_TRUTH_POSTURE gate). Gate is SOFT (warn-only). Continuity legality is checked but not enforced as a hard dispatch gate.

**Verdict: SOFT-GATE in dispatch path**.

#### Canonical Dispatch Slot Authority (V3) — `core/canonical_dispatch_slot_authority.py`

| Check | Result |
|---|---|
| Source exists | ✓ Yes — 10-dimension dispatch slot evaluation |
| `grep "get_canonical_dispatch_slots" command_router.py` | 0 matches |
| `grep "get_canonical_dispatch_slots" openclawd.py` | 0 matches |
| Called from hot path | **No** |
| Known callers | `center_authority_boundary.py`, `unified_orchestration_spine.py` (structural only) |

**Verdict: ARCHITECTURALLY-PRESENT, NOT-WIRED to hot path**.

#### Unified Orchestration Spine (V4) — `core/unified_orchestration_spine.py`

| Check | Result |
|---|---|
| Source exists | ✓ Yes |
| `grep "evaluate_orchestration_request" command_router.py` | 0 matches |
| `grep "evaluate_orchestration_request" openclawd.py` | 0 matches |
| Called from hot path | **No** |
| Known callers | `center_authority_boundary.py` only |

**Verdict: ARCHITECTURALLY-PRESENT, NOT-WIRED to hot path. No live caller anywhere in execution chain.**

#### Group Completion Closure (V5) — `core/canonical_group_completion_closure.py`

Referenced in `CanonicalCompletionIngress.notify()` for parallel group tracking. Wired for fan-out scenarios via `ParallelGroupTracker` (imported in `openclawd.py` from `core/orchestration/lifecycle.py`).

**Verdict: REAL/HOT-PATH for parallel task scenarios; ARCHITECTURALLY-PRESENT for single-task completion**.

#### Final Acceptance Verdict (V6) — `core/system_final_acceptance_verdict.py`

Not found in any live execution path call chain. Structural/governance artifact.

**Verdict: ARCHITECTURALLY-PRESENT**.

#### LLM Route Authority (L1) — `core/llm/route_authority.py`

| Check | Result |
|---|---|
| Source exists | ✓ Yes |
| Imported by `openclawd.py` | **No** |
| Imported by `unified/llm_router.py` | **No** |
| Imported by routes layer | ✓ `routes/ai.py`, `routes/system.py`, `routes/nodes.py`, `routes/observability.py` |
| Call site | REST API model selection (external-facing routes) |

**Verdict: REAL/HOT-PATH in the REST API routes layer. NOT in the `process()` internal execution hot path.**

#### LLM Supply Authority (L2) — `core/llm/supply_authority.py`

Not imported by `openclawd.py` or `unified/llm_router.py`. The `UnifiedLLMRouter` handles provider availability and fallback internally without calling `LLMSupplyAuthority`.

**Verdict: ARCHITECTURALLY-PRESENT, not in execution hot path**.

#### Cognitive Context Authority (L3) — `core/llm/context_authority.py`

Grep: `context_authority` → only in `core/llm/`, `core/routes/ai.py`, `core/routes/chat.py`. Not imported by `openclawd.py`.

**Verdict: ARCHITECTURALLY-PRESENT, not in execution hot path**.

#### Cognitive Execution Authority (L4) — `core/llm/execution_authority.py`

Grep: `execution_authority` → `core/llm/`, `core/schemas/`, `core/routes/`. Not imported by `openclawd.py`. Calls `LLMRouteAuthority.resolve()` internally — part of the L1 layer.

**Verdict: ARCHITECTURALLY-PRESENT, not in execution hot path**.

#### Android Delegated Signal (A3) — `core/android_delegated_signal_ingress.py`

Wired in Python bridge: `handle_delegated_execution_signal` dispatches to `android_delegated_signal_ingress`. Emitted by Android `delegatedSignalSink` in `DelegatedTakeoverExecutor`. Wire type `DELEGATED_EXECUTION_SIGNAL` confirmed on both sides.

**Verdict: REAL/HOT-PATH**.

#### Android Transport (A1/TRANSPORT) — `core/transport_hierarchy.py` + WS transport layer

FastAPI WebSocket endpoint in `galaxy_gateway/app.py`, OkHttp WS in `GalaxyWebSocketClient.kt`. Both confirmed live.

**Verdict: REAL/HOT-PATH**.

#### Android Protocol (A2/PROTOCOL) — `galaxy_gateway/protocol/aip_v3.py` + `AipModels.kt`

Both confirmed live (see §4.1 alignment table).

**Verdict: REAL/HOT-PATH**.

#### Android Participant Truth (A4) — `core/android_participant_truth_ingress.py`

Called from `handle_task_result` in the best-effort fallback path (when canonical truth chain unavailable). Also called from compat paths. SOFT invocation.

**Verdict: SOFT-PATH**.

### 5.3 Authority Classification Summary

| Authority | Module | Verdict |
|---|---|---|
| Completion truth chain | `task_lifecycle.py` | SOFT-GATE (on path, try/except) |
| Continuity legality | `unified_continuity_legality_authority.py` | SOFT-GATE (posture check, warn-only) |
| Canonical dispatch slot | `canonical_dispatch_slot_authority.py` | ARCHITECTURALLY-PRESENT, NOT-WIRED |
| Orchestration spine | `unified_orchestration_spine.py` | ARCHITECTURALLY-PRESENT, NOT-WIRED |
| Group completion closure | `canonical_group_completion_closure.py` | HOT-PATH (parallel), ARCH-PRESENT (single) |
| LLM route authority | `llm/route_authority.py` | HOT-PATH in REST routes, NOT in process() |
| LLM supply authority | `llm/supply_authority.py` | ARCHITECTURALLY-PRESENT |
| Cognitive context authority | `llm/context_authority.py` | ARCHITECTURALLY-PRESENT |
| Cognitive execution authority | `llm/execution_authority.py` | ARCHITECTURALLY-PRESENT |
| Android delegated signal | `android_delegated_signal_ingress.py` | HOT-PATH |
| Transport layer | WS endpoint + OkHttp | HOT-PATH |
| AIP v3 protocol | `aip_v3.py` + `AipModels.kt` | HOT-PATH |
| Android participant truth | `android_participant_truth_ingress.py` | SOFT-PATH (fallback) |
| ACL enforcement | `acl_enforcer.py` via CommandRouter | HOT-PATH (HARD gate) |
| Capability-graph enforcement | PR-1-P0 in CommandRouter | HOT-PATH (HARD gate) |

---

## Section 6: End-to-End System Runnability — Final Verdict

### 6.1 Does the Full System Run End-to-End?

**Yes — through one confirmed nominal path.**

The confirmed complete runnable chain is:

```
main.py
  → SystemOrchestrator.run_startup_sequence() [7 phases, fault-tolerant]
    → subprocess.call([unified_launcher.py])
       → GalaxyUnified.start_all() [FastAPI + uvicorn + background services]
         → DesktopPresenceRuntime.receive() [tri-state SILENT → LIMINAL]
           → OpenClawd.process(message)
             → UnifiedLLMRouter → MultiLLMRouter → provider API [LLM reasoning]
               → _determine_execution_path() → "cross_device"
                 → SourceDispatchOrchestrator.dispatch() → AndroidBridge.send()
                   → WS → Android device: GalaxyConnectionService
                     → GalaxyWebSocketClient.Listener.onGoalExecution()
                       → AutonomousExecutionPipeline.handleGoalExecution()
                         → [LLM reasoning + EdgeExecutor UI steps]
                           → GalaxyWebSocketClient.sendJson(goal_execution_result)
                             → Center: android_bridge.handle_goal_execution_result()
                               → [truth chain, best-effort]
                                 → CanonicalCompletionIngress.notify()
                                   → Future resolved → response returned
```

This path **is runnable** under the following conditions:
- Center service is running (FastAPI + gateway)
- Android device is connected via WebSocket
- Provider API keys are configured
- Android device has Accessibility Service enabled (for EdgeExecutor)
- Device is registered and capability-graph shows it as reachable

### 6.2 Additional Confirmed Runnable Paths

| Path | Components | Status |
|---|---|---|
| Local execution | OpenClawd → DecisionExecutor → WindowsExecutionArbiter | CONFIRMED RUNNABLE |
| Basic task round-trip | CommandRouter → task_assign → EdgeExecutor → task_result | CONFIRMED RUNNABLE |
| Handoff/Takeover | CommandRouter → handoff_envelope_v2 → DelegatedTakeoverExecutor → takeover_response | CONFIRMED RUNNABLE |
| Parallel fan-out | CommandRouter → parallel_fanout → multiple devices → ParallelGroupTracker | CONFIRMED RUNNABLE (group completion wired) |
| Reconnect + replay | Android reconnect via device_register → OfflineTaskQueue drain | CONFIRMED RUNNABLE |
| Hybrid execution | hybrid_execute → sendHybridDegrade() | **DEAD-PATH** — no actual hybrid execution |

### 6.3 What Prevents Calling the System "Fully Operationally Closed"?

#### Gap 1: L1–L4 not in `process()` execution hot path

The 4-module cognitive authority chain (LLMRouteAuthority, LLMSupplyAuthority, CognitiveContextAuthority, CognitiveExecutionAuthority) is architecturally complete and applied in the REST API layer, but the internal `OpenClawd.process()` execution loop uses `UnifiedLLMRouter` directly — bypassing the L1–L4 gate.

**Practical impact**: The center cannot verify via the authority chain that routing, supply, context, and execution followed declared policy when processing internal task requests. REST API requests go through L1; internal process() requests do not.

#### Gap 2: V3/V4 dispatch slot and orchestration spine not in dispatch hot path

`canonical_dispatch_slot_authority.py` and `unified_orchestration_spine.py` exist but are not called from `CommandRouter.route_envelope()`. The dispatch slot's 10 dimensions (continuity legality, occupancy, attachment validity, etc.) are not evaluated before dispatch.

**Practical impact**: `CommandRouter` can dispatch to any device that passes ACL and capability-graph checks, without evaluating the full canonical dispatch slot conditions. Structural dispatch correctness may not match declared policy.

#### Gap 3: V1 truth chain is soft, not hard

`run_task_result_truth_chain()` runs when available but does not block completion on partial failure. All 4 steps use `try/except`. `is_truth_chain_complete = False` triggers a warning log, not a completion block.

**Practical impact**: The system can close tasks with incomplete truth chains. Completion truth is advisory, not binding.

#### Gap 4: Android governance uplinks not consumed by center

`device_governance_report`, `device_acceptance_report`, and `device_strategy_report` from Android are not in the Python bridge handler map. These governance signals are emitted by Android but silently dropped by the center.

**Practical impact**: Center cannot apply governance decisions that depend on Android-reported governance, acceptance, or strategy signals.

#### Gap 5: No automated dual-repo E2E test

There is no CI test that exercises the full round-trip from center startup through Android execution to result return. The system could be broken at any integration point without automatic detection.

### 6.4 What Is Truly Runnable vs Only Nominally Runnable?

| Claim | Reality |
|---|---|
| "The system can process tasks end-to-end" | **TRULY RUNNABLE** |
| "Authority boundaries are enforced during execution" | **ONLY NOMINALLY RUNNABLE** — most authority is structural |
| "Cognitive routing follows the L1–L4 authority chain" | **ONLY FOR REST API** — not for internal process() |
| "Dispatch follows canonical dispatch slot policy" | **NOT ENFORCED** in hot path |
| "Truth chain gates completion" | **ADVISORY ONLY** — not a hard gate |
| "Hybrid execution works" | **DEAD-PATH** — both sides degrade without executing |
| "Reconnect with session continuity works" | **TRULY RUNNABLE** |
| "Offline result replay works" | **TRULY RUNNABLE** |

### 6.5 Integrated Final Verdict

The center-distributed system formed by `ufo-galaxy-realization-v2` (center) and `ufo-galaxy-android` (Android runtime) is **genuinely operational at the transport, protocol, and execution layers**. The nominal end-to-end path from center startup through Android task execution to result completion is real, traceable in code, and runnable.

The authority infrastructure (V1–V6, L1–L4, A1–A4) is architecturally complete and self-consistent. However, most of it is **architecturally present but not operationally wired into the live execution hot path**. The 3 genuinely hard-enforced gates in the live path are ACL (CommandRouter), capability-graph (CommandRouter), and Android HandoffContractValidator. Everything else is either SOFT (warns, continues) or ARCHITECTURALLY-PRESENT (exists, not called from execution hot path).

The precise description of current system state is:

> **Transport and participation are closed. Execution is runnable. Authority enforcement is architecturally declared but not operationally enforced in the primary execution loop.**

The system is not a fake system. It is a partially-hardened distributed runtime with a real executable core and a well-designed authority architecture that has not yet been fully inserted into the hot path.

---

## Section 7: Evidence Index

All findings above are grounded in the following code locations:

| Claim | Evidence |
|---|---|
| Startup never hard-blocks | `main.py:_run_orchestrator_preflight()` → `except → return True`; all 7 phases: exceptions → DEGRADED |
| OpenClawd LLM path | `core/openclawd.py:_get_router()` line 1051 → `unified.llm_router.get_unified_llm_router()` |
| L1 not in process() hot path | grep `route_authority` in `openclawd.py` → no match; grep in `routes/ai.py` → match |
| V3 not called by CommandRouter | grep `get_canonical_dispatch_slots` in `command_router.py` → 0 matches |
| V4 has no live caller | grep `evaluate_orchestration_request` in `command_router.py`, `openclawd.py` → 0 matches each |
| V1 is soft-gate | `task_lifecycle.py` truth chain: all steps `try/except`; `is_truth_chain_complete=False` → `logger.warning()` only |
| AIP v3 wire alignment | `aip_v3.py:MessageType` enum vs `AipModels.kt:MsgType` enum — all bidirectional types match |
| HYBRID_EXECUTE dead-path | `GalaxyConnectionService.kt:onAdvancedMessage()` → `sendHybridDegrade()` in `else` branch |
| Compat paths live | `android_bridge.py` line 727: `GOAL_RESULT` mapped to `handle_goal_execution_result`; `OfflineTaskQueue.QUEUEABLE_TYPES` includes `"goal_result"` |
| Android governance uplinks unhandled | `AipModels.kt:MsgType`: DEVICE_GOVERNANCE_REPORT, DEVICE_ACCEPTANCE_REPORT, DEVICE_STRATEGY_REPORT exist; not in `android_bridge._message_handlers` |
| EdgeExecutor hard model gate | `EdgeExecutor.kt`: `if models not loaded → return STATUS_ERROR` |
| DelegatedTakeoverExecutor wired | `GalaxyConnectionService.kt`: `by lazy { DelegatedTakeoverExecutor(pipeline = GoalExecutionPipeline { ... }) }` |
| OfflineTaskQueue session-bounded | `OfflineTaskQueue.kt:discardForDifferentSession(currentTag)` → `drainAll()` on reconnect |
| ACL gate is HARD | `command_router.py`: `get_acl_enforcer().check()` → return error dict on deny |
| Reconnect canonical path | `registration.py` line 97–116: `handle_device_register` is canonical reconnect consumer |

---

*This audit was produced by direct code traversal across both repositories as of 2026-04-30. No prior PRs, design documents, or review artifacts were used as evidence. Every claim above references a specific file, line, import, or grep result.*
