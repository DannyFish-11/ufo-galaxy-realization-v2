# Final Dual-Repository Integrated System Reality

> **Document class**: Final integrated understanding artifact — dual-repository aligned  
> **Repositories covered**:  
> — `DannyFish-11/ufo-galaxy-realization-v2` (center/orchestration plane, Python/FastAPI)  
> — `DannyFish-11/ufo-galaxy-android` (participant/device runtime, Kotlin/Android)  
>
> **Method**: Code-grounded traversal across both repositories.  
> Prior audit documents (`COMPLETE_DUAL_REPO_SYSTEM_AUDIT_2026.md`,  
> `DEEP_RECONCILIATION_AUDIT_2026.md`, `FINAL_ARCHITECTURE_VALIDATION_AUDIT.md`)  
> are superseded by this document as the single canonical final understanding artifact.  
>
> **Remediation baseline**: Includes impact of remediation-wave PRs (HandoffEnvelopeV2  
> uplink wiring, canonical ReconciliationSignal handler, CI governance gate enforcement).  
>
> **Status**: Final — post-remediation, dual-repository-aligned  
> **Date**: 2026-05-01

---

## Table of Contents

1. [System Identity — What This Two-Repo Stack Actually Is](#1-system-identity)
2. [V2 Center Plane — Responsibilities and Code Evidence](#2-v2-center-plane)
3. [Android Participant Runtime — Responsibilities and Code Evidence](#3-android-participant-runtime)
4. [Protocol Interaction Surface — AIP v3 Wire Alignment](#4-protocol-interaction-surface)
5. [Lifecycle and Recovery Cooperation](#5-lifecycle-and-recovery-cooperation)
6. [Dispatch, Delivery, and Result Continuity](#6-dispatch-delivery-and-result-continuity)
7. [Governance and Integrity Enforcement](#7-governance-and-integrity-enforcement)
8. [Previously Identified Blockers and Their Resolution](#8-previously-identified-blockers-and-their-resolution)
9. [Final Integrated Verdict](#9-final-integrated-verdict)

---

## 1. System Identity

### 1.1 What This Two-Repository Stack Actually Is

Galaxy is a **center-governed, center-distributed intelligent agent runtime**. It is not a
peer-to-peer mesh and not a simple chat-relay service. The governance model is:

- **V2** (`ufo-galaxy-realization-v2`) holds exclusive authority over: dispatch decisions,
  session continuity classification, task completion truth, and governance gate enforcement.
- **Android** (`ufo-galaxy-android`) is an **instrumented participant node** that accepts
  center-dispatched tasks, executes them using on-device capabilities (UI automation,
  optional local LLM), and reports structured results back to the center.

The architecture is intentionally asymmetric. Android is not a redundant copy of V2 logic.
It is the execution arm; V2 is the brain, decision authority, and truth keeper.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ufo-galaxy-realization-v2 (Center Orchestration Plane)                 │
│                                                                         │
│  main.py → SystemOrchestrator (7-phase startup)                        │
│    → unified_launcher.py (FastAPI + async services)                    │
│       → galaxy_gateway/app.py                                          │
│          /ws/device/{device_id}   ← AIP v3 canonical WS ingress        │
│          REST API (chat/devices/tasks/sessions/health/…)                │
│          30+ registered AIP v3 message handlers in android_bridge      │
│                                                                         │
│  Cognitive spine:  OpenClawd.process()                                  │
│  Dispatch spine:   CommandRouter.route_envelope()                       │
│  Protocol bridge:  android_bridge.py + android/handlers/               │
│  Session truth:    device_registry + attached_runtime_session_registry  │
│  Completion truth: canonical_completion_ingress (Future-based)          │
│  Governance CI:    governance_gate_enforcement.yml (hard-blocking)      │
└────────────────────┬────────────────────────────────────────────────────┘
                     │  AIP v3 WebSocket (wss://<center>/ws/device/<id>)
                     │  30+ bidirectional message types
                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  ufo-galaxy-android (Participant Device Runtime)                        │
│                                                                         │
│  GalaxyConnectionService (foreground service, persistent)              │
│    → GalaxyWebSocketClient (OkHttp, AIP v3, auto-reconnect)            │
│       → BootReceiver (starts service on device boot)                   │
│                                                                         │
│  Execution paths:                                                       │
│    → EdgeExecutor / AccessibilityActionExecutor (UI automation)         │
│    → AutonomousExecutionPipeline (center-delegated LLM-driven)          │
│    → AgentRuntimeBridge (delegated handoff execution)                  │
│    → DelegatedTakeoverExecutor (deep takeover execution)               │
│                                                                         │
│  Offline resilience:  OfflineTaskQueue (session-bounded, LRU, 24h TTL) │
│  Protocol model:      AipModels.kt (full AIP v3 Kotlin layer, 103 KB)  │
│  Readiness gating:    ReadinessChecker.kt (self-reports before register)│
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Key Architectural Invariants (Code-Grounded)

| Invariant | Evidence |
|---|---|
| Android never initiates task execution without center direction | `GalaxyConnectionService` only executes on receipt of `task_assign` / `goal_execution` / `handoff_envelope_v2` |
| Center owns session continuity classification | `classify_reconnect_outcome()` in `registration.py` determines `new_attachment` vs `continuity_resume` |
| Center owns task completion truth | `canonical_completion_ingress.py` Future resolution is the only path that unblocks the center awaiter |
| Android dispatch is capability-gated | `capability_routing_gate.py` is a hard gate in `routing/device_selection.py` Step 2 |
| Governance gates are CI-enforced | `governance_gate_enforcement.yml` runs both governance verdict and cross-repo consistency checks as required merge gates |

---

## 2. V2 Center Plane

### 2.1 System Startup Authority

**Files**: `main.py` → `core/system_orchestrator.py` → `unified_launcher.py`

`SystemOrchestrator.run_startup_sequence()` runs 7 sequential phases:

| Phase | Name | Behavior on exception |
|---|---|---|
| 1 | LOAD_CONFIG | → DEGRADED (never FAILED) |
| 2 | RESOLVE_MODE | → DEGRADED |
| 3 | ENV_CHECKS | → DEGRADED |
| 4 | BACKGROUND_SUBSYSTEMS | → DEGRADED |
| 5 | RUNTIME_SUBJECT | → DEGRADED |
| 6 | DESKTOP_SURFACE | → DEGRADED |
| 7 | READINESS_SUMMARY | → DEGRADED |

Phase 4 probes real background subsystems: `CommandRouter`, dispatch plan build,
mesh session recovery, and startup recovery for in-flight tasks and WebRTC bindings.

After preflight, `main.py` hands off to `unified_launcher.py` (`GalaxyUnified` class)
which brings up async services: NATS, Redis, L4 modules, OpenClawd, DesktopPresenceRuntime,
and the unified FastAPI/uvicorn API gateway.

**Startup chain verdict**: REAL and HOT-PATH. Non-fatal by design (all phases degrade
gracefully) but structurally complete. The design intent is resilient startup over
hard-fail startup.

### 2.2 Cognitive Entry Point

**File**: `core/openclawd.py`

`OpenClawd.process()` is the cognitive spine for all per-request processing. It runs 4 stages:

```
Stage 1: Ingest
  ├─ PerceptionFrame (continuous Windows-native context from MultimodalIngressBus)
  └─ multimodal_context (request-bound fusion via MultimodalBus.ingest)

Stage 2: ContinuumOrchestrator.run()
  └─ intent → state_continuum → runtime_domain (tri-state phase classification)

Stage 3: _determine_execution_path()
  ├─ "local"        → DecisionExecutor (Windows/System API)
  ├─ "cross_device" → CommandRouter.route_envelope()
  ├─ "hybrid"       → both simultaneously
  └─ "none"         → respond only

Stage 4: Execute + Manifest
```

`_determine_execution_path()` is a pure function with no I/O side-effects. Its output
drives Stage 4. **OpenClawd is the highest-risk module in the system**: it must not be
wrapped or restructured — doing so would break the only confirmed runnable cognitive path.

### 2.3 LLM Routing

**Files**: `core/openclawd.py` → `core/unified/llm_router.py` → `core/multi_llm_router.py`

The actual live LLM invocation chain:
```python
# Lazy-initialized in OpenClawd._get_router()
try:
    from core.unified.llm_router import get_unified_llm_router
    self._router = get_unified_llm_router()   # PRIMARY path
except Exception:
    from core.multi_llm_router import get_llm_router
    self._router = get_llm_router()           # FALLBACK path
```

`UnifiedLLMRouter` wraps `MultiLLMRouter` with:
- Policy-driven routing (`config/llm_routing_policy.yaml`)
- Routing telemetry (success rate, latency, fallback rate, cost)
- Cost budget / SLO threshold enforcement

`LLMRouteAuthority` (L1), `LLMSupplyAuthority` (L2), `CognitiveContextAuthority` (L3)
are structurally present but not yet called from the `process()` hot path. They are
active in the REST API route layer only.

### 2.4 Cross-Device Dispatch

**File**: `core/command_router.py`

`CommandRouter.route_envelope()` is the canonical cross-device dispatch substrate.
Pre-dispatch gate sequence:

| Gate | Type | Effect on failure |
|---|---|---|
| ACL check: `get_acl_enforcer().check()` | **HARD** | Returns structured error dict; dispatch blocked |
| Target selection (capability_graph + DevicePoolManager) | **HARD** | Error if no valid targets |
| Capability-graph enforcement | **HARD** | Rejects with `CAPABILITY_MISMATCH` for invalid explicit targets |
| HITL high-risk stamp | SOFT | Metadata stamp; no dispatch block |
| Task memory injection | SOFT | try/except; dispatch continues |
| Posture gate | SOFT | Warning-only |
| Admissibility chain | SOFT | Graceful degradation |

After gates, routes via `_route_cross_device_envelope`, `_route_worker_envelope`, or
`_route_parallel_fanout_envelope` as appropriate.

### 2.5 Android Protocol Bridge

**Files**: `galaxy_gateway/android_bridge.py` + `galaxy_gateway/android/handlers/`

`AndroidBridge.handle_message()` receives raw WebSocket frames and dispatches via a
type-keyed handler map with 30+ registered handlers. All inbound messages first pass
through the AIP compatibility normalization layer:

```python
from galaxy_gateway.protocol.compat import normalise_to_v3_dict
```

This normalizes AIP v1.0 / v2.0 messages to canonical AIP v3 before dispatch, handling
legacy type aliases (`register` → `device_register`, `task_execute` → `task_submit`, etc.)

Core handler registrations (representative):
```python
self._message_handlers[MessageType.DEVICE_REGISTER]             = handle_device_register
self._message_handlers[MessageType.TASK_RESULT]                 = handle_task_result
self._message_handlers[MessageType.GOAL_EXECUTION_RESULT]       = handle_goal_execution_result
self._message_handlers[MessageType.HANDOFF_ENVELOPE_V2_RESULT]  = handle_handoff_v2_result
self._message_handlers[MessageType.RECONCILIATION_SIGNAL]       = handle_reconciliation_signal
self._message_handlers[MessageType.DELEGATED_EXECUTION_SIGNAL]  = handle_delegated_execution_signal
self._message_handlers[MessageType.TAKEOVER_RESPONSE]           = handle_takeover_response
# … 23+ more types
```

### 2.6 Session and Device Presence

**Files**: `core/device_registry.py`, `core/attached_runtime_session_registry.py`,
`core/unified/device_manager.py` (UDM — SSOT for device state)

The center is the exclusive authority for:
- Device registration → UDM write → body mesh role derivation
- Session continuity classification on reconnect (`classify_reconnect_outcome()`)
- Session attachment/detachment lifecycle

### 2.7 Task Completion Truth Chain

**Files**: `core/task_lifecycle.py`, `core/canonical_completion_ingress.py`

The 4-step truth chain executed on every inbound `task_result`:

```
Step 1: android_participant_truth_ingress.ingest_android_participant_truth_message()
Step 2: android_execution_signal_reconciler.reconcile_inbound_message()
Step 3: canonical_task.CanonicalTaskRuntime.update_lifecycle()
Step 4: canonical_completion_ingress.CanonicalCompletionIngress.notify()  ← Future resolved
```

Each step is wrapped in `try/except`. `is_truth_chain_complete = False` is logged as
WARNING but does not block completion. The Future is resolved regardless of truth chain
outcome. This is the primary remaining structural softness in the completion path.

---

## 3. Android Participant Runtime

### 3.1 Connection Lifecycle

**Files**: `service/GalaxyConnectionService.kt`, `network/GalaxyWebSocketClient.kt`

`GalaxyConnectionService` is a persistent Android foreground service (started on device
boot via `BootReceiver.kt`). It owns the full WebSocket lifecycle:

```
UFOGalaxyApplication.onCreate()
  → GalaxyConnectionService started (foreground, persistent)
      → GalaxyWebSocketClient.connect(serverUrl)
           → OkHttp WebSocket: wss://<center>/ws/device/{device_id}
                → onOpen(): sendHandshake()  ← device_register message
                     → GalaxyWebSocketClient.Listener.onRegistered(deviceInfo)
                          → GalaxyConnectionService.onDeviceRegistered()
                → offlineQueue.drainAll()  ← replay buffered results on reconnect
```

`RuntimeController` is the **sole authority** for `connect()` / `disconnect()` —
documented explicitly in the `GalaxyWebSocketClient.kt` module docstring. `sendJson()`
is hard-blocked when `crossDeviceEnabled = false`.

Reconnect behavior: exponential backoff (1s → 30s + jitter, max 10 retries).

### 3.2 Registration and Session Continuity

Session continuity is jointly implemented across both repos:

**Android side** (sends on every connect including reconnect):
```kotlin
// device_register payload fields:
runtime_attachment_session_id  // same UUID on reconnect (RECONNECT_RECOVERY mode)
session_continuity_epoch       // increments on each transparent reconnect
durable_session_id             // persists across cold restarts (SharedPreferences)
```

**Center side** (`galaxy_gateway/android/handlers/registration.py`):
```python
_reconnect_outcome = classify_reconnect_outcome(
    device_id, runtime_attachment_session_id, ...
)
# Outcomes: "new_attachment" | "continuity_resume" | "session_mismatch"
```

For `continuity_resume`: `reconnect_session()` restores the prior session.
For `new_attachment`: a fresh session is created.

### 3.3 Task Execution

**Files**: `service/GalaxyConnectionService.kt`, `service/EdgeExecutor.kt`,
`local/AutonomousExecutionPipeline.kt`, `agent/AgentRuntimeBridge.kt`

Android can execute tasks through multiple paths:

| Path | Module | Availability |
|---|---|---|
| UI automation | `EdgeExecutor` / `AccessibilityActionExecutor.kt` | ✅ Always available (requires Accessibility permission) |
| Center-delegated goal execution | `AutonomousExecutionPipeline.kt` | ⚠️ Requires local LLM server at `127.0.0.1:8080` |
| Handoff/bridge execution | `AgentRuntimeBridge.kt` (idempotent, retried) | ✅ When `crossDeviceEnabled && execMode ∈ {REMOTE, BOTH}` |
| Deep takeover | `DelegatedTakeoverExecutor.kt` (wired to pipeline) | ✅ When accessibility active and device unoccupied |

Task cancellation is registered inside the launched coroutine:
```kotlin
taskCancelRegistry.register(taskId, coroutineContext[Job]!!)  // avoids launch/register race
```

### 3.4 Offline Result Buffering

**File**: `network/OfflineTaskQueue.kt`

```kotlin
QUEUEABLE_TYPES = setOf("task_result", "goal_result", "goal_execution_result")
// Capacity: max 50 entries, LRU eviction
// TTL: 24-hour max-age
// Session-bounded: discardForDifferentSession(currentTag) on reconnect
```

On reconnect: `OfflineTaskQueue.drainAll()` replays buffered results **only if** the
current session tag matches. Session mismatch → queue discarded (prevents stale results
from a prior session polluting a new session).

All 3 queued types have registered center-side handlers:
- `task_result` → `handle_task_result`
- `goal_result` → `handle_goal_execution_result` (compat alias)
- `goal_execution_result` → `handle_goal_execution_result`

### 3.5 Local Inference Availability

**Files**: `local/MobileVlmPlanner.kt`, `inference/LocalInferenceRuntimeManager.kt`

The Android on-device AI path (`MobileVlmPlanner` → `SeeClickGroundingEngine`) requires
an external inference server running at `127.0.0.1:8080` / `127.0.0.1:8081`. This is
**not built into the APK**. The `NoOpPlannerService` is the default implementation and
returns an error for all planning calls. Activation requires:
1. Downloading MobileVLM V2-1.7B GGUF weights to the device
2. Running a llama.cpp/MLC-LLM server on-device at the expected ports
3. Passing `ModelAssetManager.verifyAll()` checks

This is an explicitly documented non-default capability. The Accessibility-based UI
automation path (`AccessibilityActionExecutor`) requires no local model and is always
available given the necessary Android permissions.

### 3.6 Delegated Runtime Governance (Android-Side)

**Files**: `agent/DelegatedRuntimeAcceptanceEvaluator.kt` (33 KB),
`agent/DelegatedRuntimeGovernanceEvaluator.kt`,
`agent/TakeoverEligibilityAssessor.kt`

Android has its own governance stack for evaluating whether to accept a delegated
execution request. The evaluation is multi-dimensional:
- `TakeoverEligibilityAssessor`: verifies accessibility service active and device unoccupied
- `DelegatedRuntimeAcceptanceEvaluator`: multi-criteria acceptance decision
- `HandoffContractValidator`: validates `HandoffEnvelopeV2` structural integrity before
  execution begins (HARD gate: invalid contract → execution does not start)

Android never overrides a center dispatch decision — it can only accept, defer, or fail a
delegated execution. The center retains dispatch authority.

---

## 4. Protocol Interaction Surface

### 4.1 AIP v3 Wire Alignment

Both repos share the same wire-string convention. Python defines `MessageType(str, Enum)`
in `galaxy_gateway/protocol/aip_v3.py`; Kotlin defines `MsgType` in `AipModels.kt`.
The Android bridge registers 30+ handler entries in total; the table below covers the
key bidirectional types. All handler registrations confirmed from `android_bridge.py`
lines 711–785.

Bidirectional wire-type alignment (representative; confirmed from code):

| Wire String | Direction | Center Module | Android Module | Status |
|---|---|---|---|---|
| `device_register` | Android → Center | `handlers/registration.py` | `GalaxyWebSocketClient.sendHandshake()` | ✅ Aligned |
| `device_register_ack` | Center → Android | `registration.py` response | `Listener.onRegistered()` | ✅ Aligned |
| `heartbeat` | Android → Center | heartbeat handler | scheduled sender | ✅ Aligned |
| `task_assign` | Center → Android | `handlers/task_submit.py` | `Listener.onTaskAssign()` | ✅ Aligned |
| `task_result` | Android → Center | `handlers/task_lifecycle.py` | `sendTaskResult()` | ✅ Aligned |
| `task_cancel` | Center → Android | command router | `Listener.onTaskCancel()` | ✅ Aligned |
| `task_progress` | Android → Center | progress handler | step-level progress emit | ✅ Aligned |
| `goal_execution` | Center → Android | `handlers/goal_execution.py` | `Listener.onGoalExecution()` | ✅ Aligned |
| `goal_execution_result` | Android → Center | `handlers/goal_execution.py` | `sendGoalResult()` | ✅ Aligned |
| `goal_result` (compat alias) | Android → Center | compat → `goal_execution_result` | `OfflineTaskQueue` legacy type | ✅ Aligned (compat) |
| `handoff_envelope_v2` | Center → Android | `message_builder.py` | `Listener.onHandoffEnvelopeV2()` | ✅ Aligned |
| `handoff_envelope_v2_result` | Android → Center | `handlers/handoff_v2_result.py` | `sendJson(handoff_v2_result)` | ✅ Aligned (remediated) |
| `handoff_ack` | Android → Center | `handlers/handoff_v2_result.py` | `sendJson(handoff_ack)` | ✅ Aligned (remediated) |
| `handoff_result` | Android → Center | `handlers/handoff_v2_result.py` | `sendJson(handoff_result)` | ✅ Aligned (remediated) |
| `handoff_failure` | Android → Center | `handlers/handoff_v2_result.py` | `sendJson(handoff_failure)` | ✅ Aligned (remediated) |
| `reconciliation_signal` | Android → Center | `handlers/reconciliation_signal.py` | `RuntimeController` emit | ✅ Aligned (remediated) |
| `delegated_execution_signal` | Android → Center | `handlers/delegated_execution_signal.py` | `DelegatedTakeoverExecutor.signalSink` | ✅ Aligned |
| `takeover_response` | Android → Center | `handlers/takeover_response.py` | `GalaxyConnectionService` | ✅ Aligned |
| `parallel_subtask` | Center → Android | `handlers/goal_execution.py` | `Listener.onParallelSubtask()` | ✅ Aligned |
| `mesh_topology` | Android → Center | mesh topology handler | mesh state emission | ✅ Aligned |
| `command_result` | Android → Center | command result handler | command execution result | ✅ Aligned |
| `vision_request` | Center → Android | vision handler | Android vision capability | ✅ Aligned |

Additional registered types (22+ entries in the handler map) cover: task_submit,
goal_status, bridge_handoff, sensor_data, voice_input, capability_update, and
device-specific event types. The full map is in `android_bridge.py` lines 711–785.

### 4.2 Compat Normalization Layer

**File**: `galaxy_gateway/protocol/compat.py` — `normalise_to_v3_dict()`

Normalizes AIP v1.0/v2.0 inbound messages to canonical AIP v3 before any handler
dispatch. Type aliases handled:
- `"register"` → `"device_register"`
- `"task_execute"` → `"task_submit"`
- `"goal_result"` → `"goal_execution_result"` (semantic alias, v2.x compat)

The compat layer is live on the canonical `/ws/device/{device_id}` ingress.

### 4.3 Message Flow by Category

**Center → Android** (dispatch):
- `task_assign` — single-step task execution dispatch
- `goal_execution` — multi-step goal execution with local LLM
- `parallel_subtask` — parallel fan-out subtask
- `handoff_envelope_v2` — delegated runtime handoff with full V2 dispatch metadata
- `task_cancel` — cancel in-progress task

**Android → Center** (result and governance):
- `device_register` — initial registration and transparent reconnect
- `heartbeat` — keepalive, session continuity
- `task_result` — single-step task completion
- `goal_execution_result` — multi-step goal completion
- `handoff_envelope_v2_result` — handoff ACK / result / failure
- `reconciliation_signal` — explicit state reconciliation push from RuntimeController
- `delegated_execution_signal` — step-level delegated execution events
- `takeover_response` — takeover accept/complete/fail events

---

## 5. Lifecycle and Recovery Cooperation

### 5.1 Connection Lifecycle

```
Android connects:
  GalaxyWebSocketClient.connect()
    → OkHttp WebSocket to wss://<center>/ws/device/<id>
       → onOpen(): sendHandshake() [device_register]

Center receives:
  handle_device_register()
    → classify_reconnect_outcome()
       ├─ new_attachment:     create fresh AttachedRuntimeSession
       └─ continuity_resume:  reconnect_session() [restore prior session]
    → UDM.register_device()          [SSOT device state write]
    → attach_runtime_session()       [session attach]
    → register_body_mesh_roles()     [mesh role derivation]
    → send device_register_ack
```

### 5.2 Transparent Reconnect

The Android reconnect path is NOT a distinct wire type. It reuses `device_register` with
the same `runtime_attachment_session_id`. The center's `classify_reconnect_outcome()`
uses the session ID to determine `continuity_resume` vs `new_attachment`.

On reconnect with `continuity_resume`:
- Session state is restored on the center side
- Android drains the `OfflineTaskQueue` (session-tag matched)
- In-flight task results buffered during disconnect are replayed

On reconnect with `new_attachment`:
- Center creates a fresh session
- Android discards offline queue (session tag mismatch)
- Prior in-flight tasks are treated as abandoned (no automatic re-dispatch)

### 5.3 Heartbeat and Session Keepalive

Android sends scheduled heartbeats. The center uses heartbeat receipts to update device
state in UDM. Missing heartbeats eventually mark a device as offline in UDM, but the
center does NOT cancel in-flight tasks on heartbeat loss alone — tasks remain pending
until either the result arrives or the center awaiter times out.

### 5.4 Disconnect During Active Execution

Android handles active takeover disconnect:
```kotlin
// GalaxyConnectionService.kt
if (activeTakeoverId != null) {
    notifyTakeoverFailed(cause = DisconnectCause.DISCONNECT)
}
```

V2 handles Android disconnect during in-flight dispatch:
- `DeviceRouter.handle_task_result()` is the wakeup path
- If no result arrives and the DeviceRouter task event never fires, the
  `dispatch_to_websocket` coroutine awaits until its timeout (30s default)
- After timeout, the dispatch is marked as failed and the caller is unblocked

### 5.5 V2 Restart Recovery

**File**: `core/runtime_restart_recovery.py`

V2 restart recovers:
- Mesh session restoration (`get_multi_device_runtime_harness().recover_sessions()`)
- WebRTC transport rebinding
- Hybrid orchestration binding restoration

V2 restart does **not** recover:
- In-flight task `asyncio.Future` objects (in-memory only, lost on restart)
- `task_envelope_lifecycle_registry` pending futures

This is a documented intentional design choice. The system does not auto-resubmit
in-flight tasks on restart. An external task source is expected to resubmit if needed.

---

## 6. Dispatch, Delivery, and Result Continuity

### 6.1 Full Nominal Task Round-Trip (Confirmed Hot Path)

```
User/request
    ↓
main.py → SystemOrchestrator → unified_launcher.py
    ↓
OpenClawd.process()
    │  Stage 1: Ingest (PerceptionFrame + multimodal_context)
    │  Stage 2: ContinuumOrchestrator (intent → state_continuum)
    │  Stage 3: _determine_execution_path() → "cross_device"
    ↓
CommandRouter.route_envelope()
    │  Gate 1 (HARD): ACL check
    │  Gate 2 (HARD): Target selection + capability graph
    │  Gate 3 (HARD): Capability mismatch rejection
    ↓
galaxy_gateway/android_bridge.py
    ↓
WebSocket → Android: task_assign / goal_execution / handoff_envelope_v2
    ↓
GalaxyConnectionService.handleTaskAssign()
    │  → DelegatedRuntimeAcceptanceEvaluator (accept/decline decision)
    │  → EdgeExecutor / AgentRuntimeBridge / AutonomousExecutionPipeline
    ↓
GalaxyWebSocketClient.sendJson(task_result / goal_execution_result)
  [if offline: enqueue in OfflineTaskQueue, drain on reconnect]
    ↓
android_bridge.handle_task_result()
    │  → check_result_idempotency()  ← durable file-backed dedup
    │  → run_task_result_truth_chain()
    │       Step 1: ingest_android_participant_truth_message()
    │       Step 2: reconcile_inbound_message()
    │       Step 3: canonical_task.update_lifecycle()
    │       Step 4: canonical_completion_ingress.notify()  ← Future resolved
    │  → device_router.handle_task_result()  ← unblocks dispatch_to_websocket awaiter
    │  → store_task_result()  ← memory backflow
    ↓
OpenClawd receives completion → manifest / respond
```

Every link in this chain is confirmed by code traversal. This path is **operationally
closed** for nominal conditions (device registered, WS live, center and Android both up).

### 6.2 Durable Result Idempotency

**File**: `core/durable_result_idempotency.py`

File-level JSON storage with atomic write-then-rename semantics. 512-slot cap prevents
unbounded growth. Survives V2 process restart. Ensures that if Android replays a result
(offline queue drain after reconnect), the center does not double-process it.

### 6.3 HandoffEnvelopeV2 Round-Trip (Post-Remediation)

Before the remediation wave, `handoff_envelope_v2_result` messages fell into the
`handle_unregistered` catch-all and were silently discarded. V2 dispatched handoff
envelopes but never learned the outcome.

After remediation (`galaxy_gateway/android/handlers/handoff_v2_result.py`):

```python
# PR-02-V2: ingest_android_handoff_response() correlates the response to the
# originating dispatch via handoff_id / task_id / session_id.
# For terminal responses (result/failure): resolves Future + invokes callback.
# PR-1 P0 Completion Closure: calls device_router.handle_task_result() to wake
# the dispatch_to_websocket awaiter — previously it would timeout after 30s.
```

The handoff round-trip is now fully closed: dispatch → execution → result → completion
wakeup, with no timeout fallback for the terminal path.

### 6.4 Result Delivery Guarantees (Actual vs. Claimed)

| Property | Actual guarantee | Notes |
|---|---|---|
| At-least-once delivery (Android → Center) | ✅ Via OfflineTaskQueue drain on reconnect | Session-bounded; queue discarded on session mismatch |
| Deduplication (Center side) | ✅ Durable file-backed idempotency guard | 512-slot cap; file-atomic |
| At-most-once-processed | ✅ Idempotency guard prevents double-processing | |
| In-order delivery | ⚠️ FIFO drain, but AIP v3 has no message sequence numbers | Out-of-order across reconnects is theoretically possible |
| Guaranteed delivery across V2 restart | ❌ In-flight task Futures are lost on V2 restart | By documented design; resubmit required from task source |

---

## 7. Governance and Integrity Enforcement

### 7.1 CI Governance Gate (Hard-Blocking, Post-Remediation)

**File**: `.github/workflows/governance_gate_enforcement.yml`

Before the remediation wave, governance gate checks were advisory-only: they reported
results but did not block merges. After PR Block 3, two hard-blocking CI jobs now run
on every push to `main` and on every pull request:

**Job 1: governance-verdict** (blocks on `FAIL`)
```yaml
python -m core.governance_validation_gate --output governance_verdict.json
# exits 1 when any gate_worthy governance category is BLOCKED
# or when the readiness gate verdict is BLOCKED
```

**Job 2: consistency-gates** (blocks when any gate reports `verdict == "fail"`)
```yaml
python -m core.cross_repo_consistency_gates --output consistency_gates.json
# hard-blocks merges that introduce cross-repository protocol drift
```

Both jobs run in parallel. Both must pass for the workflow to succeed.
Verdict artifacts (`governance_verdict.json`, `consistency_gates.json`) are uploaded
as CI artifacts for 90-day audit retention.

### 7.2 Dual-Repo Integration CI

**File**: `.github/workflows/dual_repo_integration.yml`

5 parallel jobs that validate cross-repo correctness:
1. `transport-harness` — FastAPI TestClient end-to-end transport validation
2. `protocol-regression` — Reconnect/offline-queue/duplicate-result/handoff/session-identity regression tests
3. `android-ci-baseline` — Inbound type stability and handler coverage audit
4. `composite-gate` — Combined cross-repo gate
5. `contract-drift-guard` — Detects protocol contract drift between repos

### 7.3 Center Authority Boundary

**File**: `core/center_authority_boundary.py`

V6 in the authority closure layer. Declares V2 as exclusive owner of 4 authority domains:
1. Dispatch authority (cross-device targeting, ACL, capability gate)
2. Session truth authority (continuity classification, session attach/detach)
3. Completion truth authority (Future resolution, truth chain)
4. Governance enforcement authority (release gate, consistency gate)

`assert_center_authority_intact()` is callable at startup, health endpoint, and release
gate CI to verify none of the authority domains have been overridden or corrupted.

### 7.4 Android-Side Governance Contribution

Android contributes to governance through:
- **ReadinessChecker.kt**: self-reports capability state before registration; center's
  `capability_routing_gate.py` uses this for hard capability gating
- **DelegatedRuntimeAcceptanceEvaluator.kt**: multi-criteria local acceptance decision
  before executing a delegated task; declines when device is in inappropriate state
- **HandoffContractValidator.kt**: structural validation of `HandoffEnvelopeV2` before
  execution begins (HARD gate on Android side)
- **CrossRepoConsistencyGate.kt**, **UgcpSharedSchemaAlignment.kt**: cross-repo protocol
  consistency surface on the Android side

### 7.5 Dispatch Gate Architecture

Pre-dispatch gates in `CommandRouter.route_envelope()`:

```
1. ACL enforcement (HARD)           — center authority, not overridable by Android
2. HITL risk stamp (SOFT)           — metadata only
3. Task memory injection (SOFT)     — enrichment, not blocking
4. Target selection (HARD)          — must find a valid capable device
5. Capability-graph enforcement     — HARD rejection for explicit invalid targets
6. Posture gate (SOFT)              — warning-only
7. Admissibility chain (SOFT)       — graceful degradation
```

The `canonical_dispatch_slot_authority.py` (V3) provides a 10-dimension evaluation
framework but is not yet wired into `CommandRouter.route_envelope()`. The current 3
hard gates (ACL, target, capability) cover the essential dispatch integrity surface.
V3 wiring remains a future improvement that would extend, not replace, these gates.

---

## 8. Previously Identified Blockers and Their Resolution

The prior audit wave (`COMPLETE_DUAL_REPO_SYSTEM_AUDIT_2026.md`,
`DEEP_RECONCILIATION_AUDIT_2026.md`, `FINAL_ARCHITECTURE_VALIDATION_AUDIT.md`)
identified the following blockers. This section records each blocker's resolution status
against actual merged code.

### Blocker 1: HandoffEnvelopeV2 uplink had no center-side handler

**Pre-remediation state**: `handoff_envelope_v2_result`, `handoff_ack`, `handoff_result`,
`handoff_failure` messages fell into `handle_unregistered`. V2 dispatched handoff
envelopes but silently dropped all responses. The `dispatch_to_websocket` awaiter had
no completion signal — it would only unblock via 30-second timeout.

**Resolution**: `galaxy_gateway/android/handlers/handoff_v2_result.py` (PR-02-V2)
- Registered for `handoff_envelope_v2_result`, `handoff_ack`, `handoff_result`,
  `handoff_failure` in the AndroidBridge handler map
- Delegates to `ingest_android_handoff_response()` which correlates via `handoff_id` /
  `task_id` / `session_id`, resolves the pending registry entry, and invokes the callback
- For terminal responses: calls `device_router.handle_task_result()` to wake the
  `dispatch_to_websocket` awaiter immediately (no 30s timeout needed)
- Audit trail via `android_delegated_runtime_audit.py` (PR-10-V2)

**Status**: ✅ RESOLVED — handoff round-trip is now fully closed

### Blocker 2: ReconciliationSignal had no canonical V2 handler

**Pre-remediation state**: `reconciliation_signal` messages from Android's
`RuntimeController` were unregistered in the V2 gateway handler map. The message fell
to `handle_unregistered` and the reconciliation intent was silently discarded.

**Resolution**: `galaxy_gateway/android/handlers/reconciliation_signal.py` (PR-7-V2)
- Registered for `reconciliation_signal` in the AndroidBridge handler map
- Delegates to `AndroidDelegatedRuntimeLifecycleCoordinator.on_reconciliation_signal()`
  which calls `android_participant_truth_ingress.reconcile_android_participant_truth()`
  and `android_runtime_transition_reducer.py`
- Returns a typed `reconciliation_signal_ack` to the Android runtime
- Boundary: explicitly NOT duplicating terminal event processing from
  `delegated_execution_signal` — this is an explicit state reconciliation push, not
  a lifecycle event

**Status**: ✅ RESOLVED — reconciliation signal now has a canonical first-class handler

### Blocker 3: Governance gates were advisory-only, not CI-enforced

**Pre-remediation state**: Governance verdict checks and cross-repo consistency gate
checks existed as Python modules but had no CI job that would fail a build on violation.
A BLOCKED governance verdict or a protocol drift detection would be reported but would
not block a PR merge.

**Resolution**: `.github/workflows/governance_gate_enforcement.yml` (PR Block 3)
- `governance-verdict` job: runs `core.governance_validation_gate` and exits 1 on BLOCKED
- `consistency-gates` job: runs `core.cross_repo_consistency_gates` and exits 1 on any
  hard FAIL verdict
- Both jobs run on every push to `main` and every PR to `main`
- Verdict JSON artifacts retained for 90 days

**Status**: ✅ RESOLVED — governance gates are now hard-blocking CI checks

### Blocker 4: V3 dispatch slot authority not wired to CommandRouter (split-brain)

**Pre-remediation state**: `canonical_dispatch_slot_authority.get_canonical_dispatch_slots()`
defined a 10-dimension dispatch gate but was never called by `CommandRouter.route_envelope()`.
V3 was architecturally present but operationally decoupled — a declared authority with
no actual enforcement path.

**Resolution status**: ⚠️ PARTIALLY MITIGATED — not yet wired. The 3 existing hard
gates in `CommandRouter` (ACL, target selection, capability mismatch) cover the essential
integrity surface. V3 wiring (additive, ~20 lines in `CommandRouter`) remains a future
improvement. The governance CI gate (Blocker 3) now enforces at merge time that the
governance surface is not violated even though the per-request dispatch gate is not yet V3.

### Blocker 5: Truth chain was entirely soft-enforced

**Pre-remediation state**: All 4 steps of `run_task_result_truth_chain()` were wrapped
in `try/except`. `is_truth_chain_complete = False` was a WARNING only. A failed truth
chain did not block task completion.

**Resolution status**: ⚠️ UNCHANGED — the truth chain remains soft-enforced by design.
The system completes tasks optimistically. The Future is resolved regardless of truth
chain outcome. This is a deliberate resilience choice, not a neglected gap. The governance
CI gate catches truth-surface violations at the architectural layer; individual request
failures are observable but not blocking.

---

## 9. Final Integrated Verdict

### 9.1 System-Level Classification

```
CLASSIFICATION: OPERATIONALLY CLOSED — POST-REMEDIATION BASELINE ESTABLISHED
```

This classification replaces the prior `RUNNABLE_BUT_CONDITIONAL` verdict from
`CENTER_DISTRIBUTED_SYSTEM_FINAL_VERDICT.md`.

**What "operationally closed" means in this context**:
- The full nominal task round-trip from `OpenClawd.process()` to Android execution to
  V2 completion is confirmed by real code at every link
- The three previously unhandled message types (HandoffEnvelopeV2 uplink,
  ReconciliationSignal) now have canonical first-class handlers
- Governance gate enforcement is now machine-enforced via hard-blocking CI, not advisory
- The center governs dispatch, session continuity, and completion truth by code, not
  just by design intent
- Protocol alignment between V2 (Python) and Android (Kotlin) is confirmed for all 14+
  bidirectional wire types

### 9.2 What Each Repository Contributes to This Verdict

| Contribution | V2 evidence | Android evidence |
|---|---|---|
| **Transport infrastructure** | `/ws/device/{device_id}` canonical WS ingress, AIP v3 normalization | `GalaxyWebSocketClient` OkHttp, AIP v3 typed listener |
| **Session integrity** | `classify_reconnect_outcome()` — center decides continuity | `runtime_attachment_session_id` carried transparently on reconnect |
| **Dispatch integrity** | 3 HARD gates in `CommandRouter`, capability graph | `ReadinessChecker` self-reports before registration; `DelegatedRuntimeAcceptanceEvaluator` local accept gate |
| **Execution capability** | `DeviceRouter` routing, task dispatch | `EdgeExecutor` UI automation (always available), `AutonomousExecutionPipeline` (conditional) |
| **Result continuity** | Durable idempotency guard, truth chain, Future resolution | `OfflineTaskQueue` session-bounded buffering, drain-on-reconnect |
| **Handoff lifecycle** | `handoff_v2_result.py` full uplink handling (post-remediation) | `AgentRuntimeBridge` retried idempotent handoff, `HandoffContractValidator` |
| **Reconciliation** | `reconciliation_signal.py` canonical handler (post-remediation) | `RuntimeController` emits reconciliation signals |
| **Governance** | Hard-blocking CI gates on governance verdict + cross-repo consistency | `CrossRepoConsistencyGate.kt`, `UgcpSharedSchemaAlignment.kt` |
| **Audit trail** | `android_delegated_runtime_audit.py`, 90-day artifact retention | `DurableSessionContinuityRecord.kt` |

### 9.3 Residual Constraints

The following are real constraints on the system, documented against code reality:

| Constraint | Code evidence | Operational impact | Category |
|---|---|---|---|
| In-flight task Futures lost on V2 restart | `task_envelope_lifecycle_registry.py` in-memory | Tasks submitted before V2 restart require external resubmit | BY DESIGN — documented non-goal in `runtime_restart_recovery.py` |
| Truth chain is soft-enforced | All 4 steps in `try/except` in `task_lifecycle.py` | Truth chain failures are logged but don't block completion | RESILIENCE CHOICE |
| Android local AI non-default | `NoOpPlannerService` is default; `127.0.0.1:8080` (MobileVLM) and `127.0.0.1:8081` (SeeClick) required | LLM-driven Android tasks require external inference server setup | DEPLOYMENT PREREQUISITE |
| V3 dispatch slot gate not yet wired | No `get_canonical_dispatch_slots()` call in `CommandRouter` | 3 existing hard gates cover essentials; 10-dimension V3 gate deferred | FUTURE IMPROVEMENT |
| Android E2E CI limited to unit tests | No emulator tests in `android-ci.yml` | Android execution chain not auto-validated in CI against real WS | KNOWN GAP |

### 9.4 System Maturity Assessment

| Dimension | Maturity | Evidence |
|---|---|---|
| Transport layer | 🟢 Production-grade | Canonical WS ingress, AIP v3 normalization, compat layer live |
| Protocol alignment | 🟢 Confirmed aligned | 14+ wire types verified bidirectionally; `dual_repo_integration.yml` CI |
| Dispatch integrity | 🟢 Enforced | 3 HARD gates in CommandRouter; capability gate in device_selection |
| Handoff round-trip | 🟢 Fully closed (post-remediation) | `handoff_v2_result.py` + device_router wakeup |
| Reconciliation signal | 🟢 Canonical (post-remediation) | `reconciliation_signal.py` with lifecycle coordinator |
| Result continuity | 🟢 Durable idempotency + offline replay | File-backed idempotency; session-bounded OfflineTaskQueue |
| Governance enforcement | 🟢 Machine-enforced via CI (post-remediation) | `governance_gate_enforcement.yml` hard-blocking |
| Session continuity | 🟢 Code-enforced | `classify_reconnect_outcome()`, `session_continuity_epoch` |
| Completion truth | 🟡 Soft-enforced | Truth chain steps wrapped in `try/except`; Future resolved regardless |
| V2 restart recovery | 🟡 Partial | Mesh+WebRTC recovered; in-flight task Futures not recovered |
| Android local AI | 🔴 Non-default | Requires external inference server; `NoOpPlannerService` is default |
| Android E2E CI | 🟡 Build/test/lint only | No emulator-based E2E validation in `android-ci.yml` |

### 9.5 Final Verdict Statement

> **The V2↔Android dual-repository system is a genuine, operationally closed,
> center-governed distributed runtime. The full nominal task round-trip from center
> intent to Android execution to center completion is confirmed at every link by real
> code paths in both repositories. The previously identified protocol gaps
> (HandoffEnvelopeV2 uplink, ReconciliationSignal) are resolved as canonical
> first-class message handling, and governance gate enforcement is now a hard-blocking
> CI requirement rather than an advisory check.**
>
> **The system operates with a center (V2) that holds exclusive authority over dispatch
> decisions, session continuity classification, and task completion truth. Android is
> a capable, well-governed participant node with multi-path execution, offline
> resilience, and its own governance stack for local acceptance decisions.**
>
> **Remaining constraints (soft truth chain, non-default local AI, V3 dispatch gate
> not yet wired, in-flight task recovery by restart) are real but documented,
> understood, and either by intentional design or roadmapped for future closure.
> They do not block the system from executing tasks end-to-end in nominal conditions.**
>
> **Integrated system status: `OPERATIONALLY_CLOSED` — post-remediation baseline.**

---

## Appendix: Document Supersession Map

This document is the **single canonical final understanding artifact** for the
V2↔Android integrated system. Prior audit documents are superseded as follows:

| Document | Status |
|---|---|
| `audit/CENTER_DISTRIBUTED_SYSTEM_FINAL_VERDICT.md` | Superseded — pre-remediation verdict |
| `audit/COMPLETE_DUAL_REPO_SYSTEM_AUDIT_2026.md` | Superseded — pre-remediation complete audit |
| `audit/DEEP_RECONCILIATION_AUDIT_2026.md` | Superseded — reconciliation analysis |
| `audit/FINAL_ARCHITECTURE_VALIDATION_AUDIT.md` | Superseded — architecture validation |
| `audit/FINAL_VERDICT_CLASSIFICATION_TABLE.md` | Superseded — per-module verdict table |
| `audit/DUAL_REPO_SYSTEM_AUDIT.md` | Superseded — initial system audit (Chinese) |
| `docs/JOINT_SYSTEM_REVIEW_V2_ANDROID_2026Q2.md` | Superseded — Q2 joint review |

The per-module verdict table in `FINAL_VERDICT_CLASSIFICATION_TABLE.md` remains useful
for implementation-level detail on V1–V6/L1–L4/A1–A4 individual modules.
`FINAL_ARCHITECTURE_VALIDATION_AUDIT.md` remains useful for the architecture precision
corrections it records. Both documents retain value as reference; this document provides
the post-remediation integrated synthesis.
