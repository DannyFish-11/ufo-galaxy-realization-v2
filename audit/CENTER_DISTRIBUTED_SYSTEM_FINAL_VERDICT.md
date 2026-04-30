# Code-Grounded Dual-Repo System Audit: Can the Full Center-Distributed System Truly Run End-to-End?

> **Scope**: `DannyFish-11/ufo-galaxy-realization-v2` (center repo) × `DannyFish-11/ufo-galaxy-android` (Android runtime repo)  
> **Method**: Code-first traversal. No prior PRs, docs, reviews, or design documents were treated as evidence unless verified by real importable code paths.  
> **Date**: 2026-04-30  
> **Status**: Final — all chains traced from source to sink.

---

## Executive Summary (read this first)

The full center-distributed system **can run nominally end-to-end today through one confirmed path**. That path is:

```
main.py → SystemOrchestrator → unified_launcher.py
  → DesktopPresenceRuntime → OpenClawd.process()
    → ContinuumOrchestrator → UnifiedLLMRouter → MultiLLMRouter → provider API
    → _determine_execution_path() → CommandRouter.route_envelope()
      → galaxy_gateway (android_bridge) → WS → Android GalaxyConnectionService
        → EdgeExecutor or AgentRuntimeBridge → task execution
          → GalaxyWebSocketClient.sendJson(goal_execution_result)
            → android_bridge.handle_task_result()
              → run_task_result_truth_chain() [best-effort]
                → CanonicalCompletionIngress.notify() → Future resolved
```

However:

1. **The 14 merged authority-closure PRs (V1–V6, L1–L4, A1–A4) added a second layer of authority infrastructure that is NOT yet wired into the above nominal path.** These modules exist, are importable, and are architecturally correct — but the live execution chain bypasses them.

2. **The truth chain (V1) is soft-enforced** — all four steps are `try/except` and `is_truth_chain_complete = False` is only a warning.

3. **The LLM cognitive authority chain (L1–L4) is not on the hot path** — `OpenClawd` uses `UnifiedLLMRouter` → `MultiLLMRouter` directly, bypassing `LLMRouteAuthority`, `LLMSupplyAuthority`, `CognitiveContextAuthority`, and `CognitiveExecutionAuthority`.

4. **The dispatch slot / orchestration spine (V3, V4) is not on the hot path** — `CommandRouter` does not call `evaluate_orchestration_request()` or `get_canonical_dispatch_slots()` before dispatch.

**Final verdict**: The system is **architecturally converged but not yet operationally closed**. The nominal path runs. The authority infrastructure is present but structurally decoupled from the hot path. The system can execute tasks end-to-end in nominal conditions; it cannot enforce the authority boundaries it declares.

---

## 1. Center-Repo Main Execution Chain (traced from real code)

### 1.1 System Startup Chain

**File**: `main.py` → `core/system_orchestrator.py` → `unified_launcher.py`

```python
# main.py (159 lines)
def main():
    ready = _run_orchestrator_preflight()   # <- SystemOrchestrator.run_startup_sequence()
    if not ready:
        return 1
    return subprocess.call([sys.executable, "unified_launcher.py"] + sys.argv[1:])
```

`SystemOrchestrator.run_startup_sequence()` executes 7 phases:
- Phase 1: LOAD_CONFIG
- Phase 2: RESOLVE_MODE
- Phase 3: ENV_CHECKS
- Phase 4: BACKGROUND_SUBSYSTEMS
- Phase 5: RUNTIME_SUBJECT
- Phase 6: DESKTOP_SURFACE
- Phase 7: READINESS_SUMMARY

**Verdict**: Startup chain is complete and linear. `unified_launcher.py` performs the async bring-up (FastAPI/gateway services). This path **is runnable**.

Non-fatal: if `SystemOrchestrator` raises an exception it is caught and the startup continues in degraded mode (`continue_on_failure=False` means hard phases must succeed).

---

### 1.2 Runtime Subject Chain

**Files**: `core/desktop_presence_runtime.py` → `core/openclawd.py`

```
DesktopPresenceRuntime (shell — outer lifecycle, tri-state: silent/liminal/manifest)
  └── invokes OpenClawd.process() during LIMINAL phase
        Stage 1: Ingest (PerceptionFrame + multimodal_context)
        Stage 2: ContinuumOrchestrator → intent → state_continuum
        Stage 3: _determine_execution_path()
          → local | cross_device | hybrid | none
        Stage 4: DecisionExecutor (local) | CommandRouter (cross-device)
```

This chain **is confirmed by code** (`openclawd.py` docstring + imports).

---

### 1.3 LLM/Cognitive Invocation (actual live path)

**Real path in `openclawd.py`**:
```python
# Primary (lazy-initialized):
from core.unified.llm_router import get_unified_llm_router
self._router = get_unified_llm_router()

# Fallback if unified router unavailable:
from core.multi_llm_router import get_llm_router
self._router = get_llm_router()
```

`UnifiedLLMRouter` (`core/unified/llm_router.py`) wraps `MultiLLMRouter` with:
- policy-driven routing (`config/llm_routing_policy.yaml`)
- routing telemetry
- cost budget / SLO thresholds
- `chat_with_tools()` / `chat_raw()` / `chat()` methods

**Verdict**: LLM invocation path is real and runnable. The `UnifiedLLMRouter` → `MultiLLMRouter` → provider chain is the actual execution path. **This path bypasses L1–L4** (see §4 below).

---

### 1.4 Cross-Device Dispatch Chain

**File**: `core/command_router.py`

```
CommandRouter.route_envelope(envelope)
  → ACL enforcement
  → lifecycle management
  → NATS/WebSocket dispatch
  → galaxy_gateway.android_bridge.send_message() / send_task()
    → android/handlers/task_submit.handle_task_execute()
      → WS message [task_assign] → Android
```

All routes merge into `CommandRouter.route_envelope()` as single substrate root (PR-7 confirmed by module docstring + both `command_only` and `agent_runtime` paths).

**Verdict**: Cross-device dispatch chain **is real and runnable** in nominal conditions (device registered, gateway up, WebSocket live).

---

### 1.5 Result Ingress Chain

**File**: `galaxy_gateway/android/handlers/task_lifecycle.py`

```
Android → WS → android_bridge.handle_message()
  → task_lifecycle.handle_task_result()
    → check_result_idempotency(task_id)           ← durable_result_idempotency
    → record_result_idempotency(task_id)
    → run_task_result_truth_chain(message)         ← 4-step chain
        step1: ingest_android_participant_truth_message()   [try/except]
        step2: reconcile_inbound_message()                  [try/except]
        step3: canonical_task.update_lifecycle()            [try/except]
        step4: canonical_completion_ingress.notify()        [try/except]
    → bridge._pending_responses[task_id].set_result()      ← Future resolved
    → device_router.handle_task_result(task_id, result)    ← unblocks await
    → store_task_result()                                   ← memory backflow
```

**Verdict**: Result ingress path **is runnable**. All four truth chain steps are `try/except` — if any sub-system is unavailable the chain continues and `is_truth_chain_complete = False` is logged as WARNING but does not block completion. The Future is resolved regardless of truth chain outcome.

---

### 1.6 Completion Closure

**File**: `core/canonical_completion_ingress.py`

`CanonicalCompletionIngress` manages asyncio Futures keyed by `handoff_id` / `task_id`. `notify(envelope)` resolves them. `OpenClawd` awaits these Futures with a timeout.

**Verdict**: Completion closure **is real** (Future-based). However, the Future is resolved even when truth chain steps failed (`is_truth_chain_complete = False`). There is no `verdict = accepted/rejected` gate — completion is optimistic.

---

## 2. Android Runtime Participation Chain (traced from real code)

### 2.1 Lifecycle and Connection

**File**: `app/.../network/GalaxyWebSocketClient.kt`

```
RuntimeController (lifecycle authority for connect/disconnect/enable-disable)
  → GalaxyWebSocketClient.connect()
    → OkHttp WebSocket → wss://{gateway}/ws/device/{device_id}
      [onOpen]
        → sendHandshake()   device_register {
              device_id, platform, capabilities(bitmask), model, os_version,
              app_version, runtime_attachment_session_id,
              durable_session_id, session_continuity_epoch,
              source_runtime_posture [if join_runtime]
            }
        → offlineQueue.drainAll()   ← FIFO replay of buffered results
      [onMessage]
        → Listener.onMessage() → GalaxyConnectionService routing
      [onFailure]
        → scheduleReconnect() [exponential backoff: 1s→30s + jitter, max 10 retries]
```

**Key facts verified in code**:
- `RuntimeController` is the **sole authority** for `connect()` / `disconnect()` — comment in `GalaxyWebSocketClient.kt` explicitly states this.
- `sendJson()` is **hard-blocked** when `crossDeviceEnabled = false`.
- `runtime_attachment_session_id` is fresh UUID on first connect; **same value** on transparent reconnect (`RECONNECT_RECOVERY`).
- `session_continuity_epoch` increments on each transparent reconnect — center uses this for continuity classification.
- `durable_session_id` persists across cold restarts (SharedPreferences).

**Verdict**: Android lifecycle chain **is real and complete**. Session continuity semantics are properly implemented.

---

### 2.2 Task Execution Chain

**File**: `app/.../service/GalaxyConnectionService.kt`

```
handleTaskAssign(taskId, payloadJson, traceId)
  → AgentRuntimeBridge.isEligible(payload)?
    [yes] → AgentRuntimeBridge.handoff(payload)    ← LLM-driven execution
    [no]  → executeLocally(payload)
              → EdgeExecutor.execute(actions)       ← command-interpreter execution
                 ├── GUI touch/click/scroll/input (Accessibility API)
                 ├── screenshot / OCR (grounding/)
                 └── shell commands (limited)
  → sendTaskResult(taskId, status, result, traceId)
    → GalaxyWebSocketClient.sendJson(task_result_envelope)  ← or enqueue if offline
```

`AutonomousExecutionPipeline.handleGoalExecution()` handles `goal_execution` messages.

**Capability report fact**: `local_model_inference = true` only when both AgentRuntime AND inference components are available. This is **conditional**, not always-on.

**Verdict**: Android execution path **is runnable**. `EdgeExecutor` can execute UI actions unconditionally (given Accessibility permission). `AgentRuntimeBridge` / `AutonomousExecutionPipeline` require local inference components to be up — conditionally available.

---

### 2.3 Result Emission

**File**: `GalaxyWebSocketClient.kt` (docstring section)

```
Single write path: sendJson(message)
  → hard-blocked if crossDeviceEnabled = false
  → if disconnected AND message type in QUEUEABLE_TYPES:
      offlineQueue.enqueue("goal_execution_result" / "task_result" / "goal_result")
  → if connected: WebSocket.send(json)

Canonical result type: "goal_execution_result"
Offline-queue compat types: "task_result", "goal_result" (legacy backward compat)
```

`OfflineTaskQueue.QUEUEABLE_TYPES` retains `"task_result"` and `"goal_result"` for backward compatibility with older Android clients. These are **live bypass paths** — they bypass `goal_execution_result` canonicalization.

**Verdict**: Canonical result emission path **is confirmed**. Legacy `task_result`/`goal_result` types are still live in the offline queue path, providing compat backward paths that the center's `unified_result_ingress.py` must handle (and does — it lists them as source channels 2–4).

---

### 2.4 Offline / Reconnect / Recovery

**File**: `OfflineTaskQueue.kt`

```
enqueue(type, json, sessionTag=durableSessionId) → FIFO, max 50 items, SharedPreferences
discardForDifferentSession(currentDurableSessionId) ← purge stale-session messages
drainAll() → sendJson() in FIFO order
```

**Center-side**: `registration.handle_device_reconnect()` → `classify_reconnect_outcome()`:
- `"continuity_resume"`: same `runtime_attachment_session_id` → reconnect without new session
- `"new_attachment"`: different `runtime_attachment_session_id` → fresh session

**Verdict**: Offline/reconnect chain **is the most complete sub-system** in both repos. Session authority bounding on Android side (discards messages from different session era) prevents stale replay. Center continuity classification is correctly implemented.

---

### 2.5 Handoff V2 / Takeover

**Files**: `agent/HandoffEnvelopeV2.kt`, `agent/DelegatedTakeoverExecutor.kt`, `agent/TakeoverEligibilityAssessor.kt`, `agent/DelegatedHandoffContract.kt`

```
Center → Android: handoff_envelope_v2 {takeover_id, goal, context, contract}
  → TakeoverEligibilityAssessor.assess() → eligible/not-eligible
    [eligible] → DelegatedTakeoverExecutor.execute()
                  → (goal execution with contract validation)
                  → sendGoalResult(takeover_id, "success", ...)
    [not eligible] → capability_limitation signal → degrade reply

Android → Center: handoff_v2_result / takeover_response
  → android_delegated_runtime_lifecycle_coordinator
```

**Verdict**: Protocol contract is aligned (`HandoffEnvelopeV2.kt` mirrors `contracts/handoff_envelope_v2.py`). Execution depth (whether `DelegatedTakeoverExecutor` can truly complete a complex multi-step goal) depends on Android device state, permissions, and AgentRuntime availability.

---

## 3. Cross-Repository Protocol Truth

### 3.1 Wire Types — Confirmed Alive

| Wire type | Direction | Center handler | Android sender/receiver | Status |
|-----------|-----------|---------------|------------------------|--------|
| `device_register` | Android→Center | `registration.handle_device_register()` | `GalaxyWebSocketClient.sendHandshake()` | ✅ live |
| `capability_report` | Android→Center | `capability_report.handle_capability_report()` | `sendHandshake()` (second msg) | ✅ live |
| `heartbeat` | Android→Center | `heartbeat.handle_heartbeat()` | Timer 30s | ✅ live |
| `task_assign` | Center→Android | `task_submit.handle_task_execute()` | `GalaxyConnectionService.handleTaskAssign()` | ✅ live |
| `goal_execution` | Center→Android | `goal_execution.handle_goal_execution_sent()` | `GalaxyConnectionService.handleGoalExecution()` | ✅ live |
| `goal_execution_result` | Android→Center | `goal_execution.handle_goal_execution_result()` | `sendJson()` (canonical) | ✅ live, canonical |
| `task_result` | Android→Center | `task_lifecycle.handle_task_result()` | `sendJson()` (compat) | ⚠️ compat still alive |
| `goal_result` | Android→Center | `goal_execution.handle_goal_execution_result()` | `sendJson()` (legacy compat) | ⚠️ compat still alive |
| `reconnect_ack` | Center→Android | (registration path) | `onHandshakeAck()` | ✅ live |
| `handoff_envelope_v2` | Center→Android | — | `onHandoffEnvelopeV2()` | ✅ live |
| `handoff_v2_result` | Android→Center | `handoff_v2_result.handle_handoff_v2_result()` | `DelegatedTakeoverExecutor` | ✅ live |
| `takeover_request` | Center→Android | — | `handleTakeoverRequest()` | ✅ live |
| `takeover_response` | Android→Center | `takeover_response.handle_takeover_response()` | `TakeoverEligibilityAssessor` | ✅ live |

### 3.2 Protocol Compatibility Paths Still Alive

**Center side** (`unified_result_ingress.py` `ResultSourceChannel` enum):
```python
class ResultSourceChannel(str, Enum):
    CANONICAL_WS = "canonical_ws"           # goal_execution_result (canonical)
    COMPAT_WS_TASK_RESULT = "compat_ws"     # task_result (compat)
    COMPAT_WS_GOAL_RESULT = "compat_ws_goal"# goal_result (compat)
    REST_RESULT_POST = "rest"               # POST /api/v1/tasks/{id}/result
    ANDROID_OFFLINE_REPLAY = "offline_replay"
    DELEGATED_HANDOFF = "delegated"
```

All five legacy/compat paths are **alive and handled**. The center knows about them, normalizes them through `NormalizedResultEvent`, and routes through the same 7-step processing chain. This is intentional, documented backward compat — not uncontrolled bypasses.

**Android side** (`OfflineTaskQueue`): queues both `goal_execution_result` (canonical) and `task_result`/`goal_result` (legacy compat). Older Android clients that only emit `task_result` remain supported.

**Verdict**: The protocol surface is **genuinely dual-path** — canonical path and compat path are both real, both handled, both intentional. This is not a fake closure; it is explicit backward compatibility with known tradeoffs.

### 3.3 Dead or Nominal Protocol Paths

| Path | Location | Status |
|------|----------|--------|
| `/ws/{device_id}` (generic fallback) | `galaxy_gateway/routes/websocket.py` | Lives but routes to `WebSocketManager`, NOT `android_bridge` — does **not** trigger UDM registration or truth chain |
| `/ws` (debug with auto-id) | `galaxy_gateway/routes/websocket.py` | Same issue — not AIP v3 pipeline |
| `/ws/ufo3/{device_id}` (legacy) | `galaxy_gateway/routes/websocket.py` | Disabled by default; `GALAXY_ENABLE_LEGACY_PROTOCOLS=true` required |
| `/ws/android/{device_id}` (compat) | `galaxy_gateway/routes/websocket.py` | Routes to `android_bridge` — AIP v3 pipeline, acceptable compat |
| `/ws/device/{device_id}` @ `core/api_routes.py` | `core/api_routes.py` | Compat path for old clients connecting to core-direct (not gateway) — separate from gateway path |

**Real gap**: A device connecting to `/ws/{device_id}` or `/ws` (not the canonical `/ws/device/{device_id}` at gateway) does NOT enter the AIP v3 pipeline and will not be registered in UDM or the truth chain. These paths appear to be debug/legacy infrastructure.

---

## 4. Authority Closure Reality vs. Appearance

This is the core finding. The 14 PRs added real, importable, architecturally correct authority modules. The question is: are they on the hot path?

### 4.1 V1 — Completion Truth (canonical_completion_ingress + truth chain)

**Module**: `core/canonical_completion_ingress.py`, `core/task_result_canonical_truth_chain.py`

**Is it on the hot path?** YES — `handle_task_result()` calls `run_task_result_truth_chain()`.

**Is it enforced?** PARTIALLY — all 4 steps are `try/except`. `is_truth_chain_complete = False` logs WARNING but does NOT block completion or reject the result. The Future is resolved regardless.

**Verdict**: V1 authority module is **on the path but soft-enforced**. Not a fake closure, but not a hard gate either.

---

### 4.2 V2 — Continuity Legality (unified_continuity_legality_authority)

**Module**: `core/unified_continuity_legality_authority.py`

**Is it on the hot path?**

Check: Does `command_router.py` call `evaluate_continuity_legality()`?
```python
# grep result: command_router.py has NO reference to:
# unified_continuity_legality_authority, evaluate_continuity_legality
```

Check: Does `canonical_dispatch_slot_authority.py` call it (dimension 4)?
```python
# Yes — canonical_dispatch_slot_authority delegates dimension 4 to
# unified_continuity_legality_authority
```

But `canonical_dispatch_slot_authority` is NOT imported by `command_router.py`.

**Verdict**: V2 module exists and is wired correctly **inside the authority stack** (V3 calls V2). However, the authority stack (`canonical_dispatch_slot_authority` → `unified_continuity_legality_authority`) is **not imported by the live dispatch path** (`command_router.py`). Authority exists in isolation; dispatch bypasses it.

---

### 4.3 V3 — Dispatch Readiness / Canonical Dispatch Slot Authority

**Module**: `core/canonical_dispatch_slot_authority.py`

**Expected callers per policy sentinel**: `ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY` declares every execution mode MUST call `evaluate_orchestration_request()`, which in turn calls `get_canonical_dispatch_slots()`.

**Real callers (grep result)**:
- `core/unified_orchestration_spine.py` — imports and calls `get_canonical_dispatch_slots`
- `core/center_authority_boundary.py` — declares the policy as a sentinel
- `core/unified_dispatch_readiness_gate.py` — referenced in comments

**Does `command_router.py` call `get_canonical_dispatch_slots()`?** NO.
**Does `command_router.py` call `evaluate_canonical_dispatch_slot()`?** NO.

**Verdict**: V3 authority exists and is internally consistent, but **the live dispatch path (`CommandRouter`) does not pass through it**. The 10-dimension slot evaluation (transport, registration, attachment, continuity legality, capability, execution-mode eligibility, occupancy, policy, cross-device reachability, handoff acceptability) is not enforced before real dispatches.

---

### 4.4 V4 — Unified Orchestration Spine

**Module**: `core/unified_orchestration_spine.py`

**Policy**: `ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY`, `PARALLEL_FANOUT_MUST_USE_SPINE_POLICY`, `WAKE_HANDOFF_DELEGATED_MUST_USE_SPINE_POLICY`

**Real callers (grep result)**:
- `core/center_authority_boundary.py` — policy declaration only
- No import in `command_router.py`, `openclawd.py`, `cross_device_execution_chain.py`, or `execution_spine.py`

**Verdict**: V4 spine is **not on the hot path**. Its `evaluate_orchestration_request()` function is callable but never called from real execution paths traced above. The spine module itself correctly composes V3 → V2 — the chain is internally correct but externally disconnected from the live dispatcher.

---

### 4.5 V5 — Group Completion Closure

**Module**: `core/canonical_group_completion_closure.py`

**Scope**: Advanced execution modes — parallel fan-out, delegated, handoff/takeover, wake-routed, cross-device, hybrid.

**Is it on the hot path?** For basic `task_assign` → `task_result`, no — single-device completions go through `canonical_completion_ingress` directly. For parallel subtask fan-out and handoff/takeover, V5 would be needed.

**Verdict**: V5 is **relevant only for advanced multi-device scenarios**. It is correctly architected. Whether it's wired into `parallel_subtask` handling in `command_router.py` requires deeper tracing. Based on the grep showing no V5 import in `command_router.py`, it is likely **not wired into the live parallel fan-out path**.

---

### 4.6 V6 — Center Authority Boundary

**Module**: `core/center_authority_boundary.py`

This module is a **policy declaration module** — it imports and re-asserts the authority sentinels from V3 and V4. It does not execute logic on the hot path; it is a boundary manifest.

**Verdict**: V6 is **an architectural declaration, not a runtime enforcement**. It correctly summarizes which modules own authority. Its presence makes the authority model auditable, not enforced.

---

### 4.7 L1 — LLM Route Authority

**Module**: `core/llm/route_authority.py`  
**Class**: `LLMRouteAuthority`  
**Sentinel**: `LLM_ROUTE_AUTHORITY = "core.llm.route_authority.LLMRouteAuthority"`

**Real callers (grep in all `*.py`)**:
- `core/llm/__init__.py` — re-exports
- `core/orchestration_authority/legacy_paths.py` — references sentinel
- `core/routes/ai.py`, `core/routes/chat.py` — API route surface

**Does `openclawd.py` use `LLMRouteAuthority`?** NO.
```python
# openclawd.py actual LLM init:
from core.unified.llm_router import get_unified_llm_router
self._router = get_unified_llm_router()
# fallback:
from core.multi_llm_router import get_llm_router
self._router = get_llm_router()
```

`LLMRouteAuthority` is **not in the `UnifiedLLMRouter` chain**. `UnifiedLLMRouter` is a separate pre-L1 unified facade.

**Verdict**: L1 authority module is **architecturally defined and importable** but is NOT on OpenClawd's LLM execution path. The live LLM routing goes through `UnifiedLLMRouter` → `MultiLLMRouter`. `LLMRouteAuthority` is a parallel routing authority that is accessible from API routes but not from the cognitive execution chain inside `OpenClawd`.

---

### 4.8 L2 — LLM Supply Authority

**Module**: `core/llm/supply_authority.py`  
**Class**: `LLMSupplyAuthority`

**Is it on the live path?** Only if L1 (`LLMRouteAuthority`) is called first. Since L1 is not called from `OpenClawd`, L2 is also not on the OpenClawd hot path.

**`UnifiedLLMRouter` / `MultiLLMRouter` have their own provider ordering and fallback logic** (configured via `config/llm_routing_policy.yaml` and `MultiLLMRouter` internal state). This is a **parallel supply system** that predates L2.

**Verdict**: L2 supply authority is **architecturally present but bypassed** by the live LLM path. `MultiLLMRouter` has its own supply + fallback logic.

---

### 4.9 L3 — Cognitive Context Assembly Authority

**Module**: `core/llm/context_authority.py`  
**Class**: `CognitiveContextAuthority`

**Is it on the live path?** No — `OpenClawd.process()` assembles context internally and passes it to `UnifiedLLMRouter.chat_with_tools()`. There is no call to `CognitiveContextAuthority.assemble()`.

**Verdict**: L3 context assembly is **architecturally defined and internally consistent** (6-step canonical assembly) but **is not invoked** by the live `OpenClawd` cognitive path.

---

### 4.10 L4 — Cognitive Execution Authority

**Module**: `core/llm/execution_authority.py`  
**Class**: `CognitiveExecutionAuthority`  
**Sentinel**: `LLM_EXECUTION_AUTHORITY = "core.llm.execution_authority.CognitiveExecutionAuthority"`

**Is it on the live path?** No. `OpenClawd` calls `UnifiedLLMRouter.chat_with_tools()` / `chat_raw()`, which calls `MultiLLMRouter` directly. `CognitiveExecutionAuthority.execute()` is never invoked.

**The 5-step gate** (verify L3 context sentinel → verify L2 supply sentinel → check is_satisfied → delegate raw execution → normalize output → embed L4 sentinel in result) **is never executed on the live path.**

**Verdict**: L4 is the final cognitive authority closure. It is architecturally complete and correctly chains L3→L2→L4. However, it is **not wired into `OpenClawd`'s execution path**. The live path invokes `UnifiedLLMRouter` which does not carry L3/L2 sentinels and does not pass through `CognitiveExecutionAuthority`.

---

### 4.11 A1 — Android Result Emission Canonicalization

**Verified in**: `GalaxyWebSocketClient.kt` docstring section on result paths.

```
* All production result paths (task_assign, goal_execution, parallel_subtask,
  error/parse-failure) emit `goal_execution_result` as the canonical result type.
* sendJson() is the single write path for all outbound results.
```

**Verdict**: A1 is **genuinely closed**. `goal_execution_result` is the canonical type. `sendJson()` is the single emission path. Legacy `task_result`/`goal_result` in offline queue are explicit compat paths, not unintended bypasses.

---

### 4.12 A2 — Continuity Authority in All Execution Gates

**Verified in**: `GalaxyWebSocketClient.kt` session fields.

```kotlin
// session_continuity_epoch: increments on each transparent reconnect
// runtime_attachment_session_id: stable across transparent reconnects
// durable_session_id: stable across cold restarts
// All three fields included in both device_register and capability_report handshake
```

**Center side**: `unified_continuity_legality_authority.py` evaluates these fields. `attached_runtime_session_registry.py` tracks session identity. `classify_reconnect_outcome()` uses `runtime_attachment_session_id` for `continuity_resume` vs `new_attachment` classification.

**Verdict**: A2 is **genuinely closed on the Android side** — all continuity signals are present and correctly structured. Center-side evaluation is real. Caveat: center-side evaluation is only enforced when V2/V3 modules are called, which (as shown above) is not the case on the live dispatch path.

---

### 4.13 A3 — Delegated/Takeover Signal Contract

**Verified in**: `agent/DelegatedTakeoverExecutor.kt`, `agent/HandoffEnvelopeV2.kt`, `agent/DelegatedHandoffContract.kt`, `agent/TakeoverEligibilityAssessor.kt`

Protocol alignment confirmed: `handoff_envelope_v2` / `handoff_v2_result` / `takeover_request` / `takeover_response` are all defined in both repos with matching field names.

**Verdict**: A3 protocol contract is **genuinely aligned**. The execution depth of `DelegatedTakeoverExecutor` is device-capability-dependent.

---

### 4.14 A4 — Android Reduced to Participant-Truth Role

**Verified in**: `core/android_runtime_host.py`

```python
class AndroidRuntimeHostRole(Enum):
    FULL_RUNTIME_HOST = "full_runtime_host"    # source_runtime_posture="join_runtime"
    PARTIAL_RUNTIME_HOST = "partial_runtime_host"
    CONNECTED_DEVICE = "connected_device"       # default — no runtime posture
    UNCLASSIFIED = "unclassified"
```

Classification based on `source_runtime_posture`, `is_runtime_host`, and `autonomy.runtime_enabled` fields in the device registration payload.

**Verdict**: A4 role classification is **architecturally present**. Android devices that don't explicitly set `source_runtime_posture = "join_runtime"` are classified as `CONNECTED_DEVICE` and do not participate as runtime hosts. This correctly demotes most Android devices to participant-truth role. However, whether the classification result actually gates dispatch decisions depends on whether `classify_android_runtime_host()` is called in dispatch flows — not confirmed for live dispatch path.

---

## 5. Summary: Real Runnable Paths vs. Assumed Paths

### 5.1 Genuinely Closed (confirmed runnable)

| Chain | Evidence |
|-------|----------|
| System startup (main.py → SystemOrchestrator → unified_launcher) | `main.py:88-97`, `system_orchestrator.py` |
| DesktopPresenceRuntime → OpenClawd.process() → ContinuumOrchestrator | `openclawd.py` docstring + stage structure |
| OpenClawd → UnifiedLLMRouter → MultiLLMRouter → provider API | `openclawd.py` import chain, `unified/llm_router.py` |
| CommandRouter.route_envelope() → gateway → Android task_assign WS | `command_router.py` PR-7 single-substrate root |
| Android EdgeExecutor local action execution | `EdgeExecutor.kt` actions dispatch |
| Android GalaxyWebSocketClient WS transport (connect/disconnect/reconnect) | `GalaxyWebSocketClient.kt` full lifecycle |
| Android → Center result emission (`goal_execution_result` via `sendJson()`) | `GalaxyWebSocketClient.kt` single write path |
| Center task_lifecycle.handle_task_result() → truth chain → Future resolve | `task_lifecycle.py` handler, `canonical_completion_ingress.py` |
| Offline queue + session-bound reconnect replay | `OfflineTaskQueue.kt`, `registration.py` classify_reconnect |
| AIP v3 protocol alignment (20+ message types) | `aip_v3.py`, `AipModels.kt` |

### 5.2 Architecturally Present but Not on Hot Path (false closure)

| Chain | Authority Exists | On Hot Path? | Gap |
|-------|-----------------|-------------|-----|
| L1 LLM Route Authority | ✅ `core/llm/route_authority.py` | ❌ NOT used by OpenClawd | OpenClawd uses `UnifiedLLMRouter` directly |
| L2 LLM Supply Authority | ✅ `core/llm/supply_authority.py` | ❌ NOT on OpenClawd path | `MultiLLMRouter` has own supply logic |
| L3 Cognitive Context Assembly | ✅ `core/llm/context_authority.py` | ❌ NOT called by OpenClawd | Context assembled ad-hoc inside `process()` |
| L4 Cognitive Execution Semantics | ✅ `core/llm/execution_authority.py` | ❌ NOT called by OpenClawd | `UnifiedLLMRouter.chat_with_tools()` bypasses L4 |
| V3 Canonical Dispatch Slot (10 dimensions) | ✅ `canonical_dispatch_slot_authority.py` | ❌ NOT called by CommandRouter | CommandRouter dispatches without slot evaluation |
| V4 Unified Orchestration Spine | ✅ `unified_orchestration_spine.py` | ❌ NOT called by any live execution path | Spine is a standalone evaluator, never invoked |
| V5 Group Completion Closure | ✅ `canonical_group_completion_closure.py` | ❌ Not confirmed wired into parallel fan-out | No import in CommandRouter |
| V6 Center Authority Boundary | ✅ `center_authority_boundary.py` | N/A — policy declaration only | Not an executable gate |

### 5.3 Soft-Enforced (nominally on path, not hard-gated)

| Chain | Status |
|-------|--------|
| V1 Truth Chain (4-step) | On path, all 4 steps try/except — soft enforcement only |
| V2 Continuity Legality | Evaluated inside V3, but V3 not on hot path |
| Device registration post-steps (mesh/session/registry) | 7 try/except blocks — all soft |
| goal_result truth chain | Weaker than task_result — `goal_execution` handler lacks full 4-step chain |

---

## 6. Cross-Cutting Gaps Identified

### Gap 1 [HIGH]: L1–L4 Cognitive Authority Stack Is Not on the Live Execution Path

The four cognitive authority modules (`route_authority.py`, `supply_authority.py`, `context_authority.py`, `execution_authority.py`) represent a complete, well-designed cognitive authority model. None of them are invoked by `OpenClawd.process()`. The live path uses `UnifiedLLMRouter` → `MultiLLMRouter`, which was the pre-L1 unified routing facade. L1–L4 are accessible from API routes (`core/routes/ai.py`, `core/routes/chat.py`) but not from the primary cognitive execution path inside `OpenClawd`.

**Consequence**: The center does not enforce cognitive authority semantics (routing intent verification, supply legality, canonical context assembly, execution semantics ownership) on its primary LLM invocations.

### Gap 2 [HIGH]: V3/V4 Dispatch Authority Stack Is Not on the Live Dispatch Path

`canonical_dispatch_slot_authority` (10-dimension slot evaluation) and `unified_orchestration_spine` (canonical pre-dispatch gate) are not imported by `command_router.py`. Every dispatch via `CommandRouter.route_envelope()` bypasses all 10 legality dimensions (transport, registration, attachment, continuity legality, capability, execution-mode eligibility, occupancy, policy allowance, cross-device reachability, handoff acceptability).

**Consequence**: Devices can receive tasks even when continuity is illegal, occupancy is active, or policy blocks dispatch — because the canonical gate is never consulted.

### Gap 3 [HIGH]: V1 Truth Chain Is Best-Effort

Already documented in `DUAL_REPO_SYSTEM_AUDIT.md`. Repeated here because it's the primary result-processing gap: `run_task_result_truth_chain()` wraps all 4 steps in `try/except`, `is_truth_chain_complete = False` is only a WARNING, and the Future is resolved regardless.

**Consequence**: The center cannot distinguish "truth fully closed" from "truth chain partially failed" at the completion level. A task can be marked complete with degraded or missing truth.

### Gap 4 [MEDIUM]: goal_result Has Weaker Truth Chain than task_result

`handle_goal_execution_result()` does not call `run_task_result_truth_chain()`. It has partial ingress (status update, memory backflow) but not the full 4-step chain. `goal_execution` represents the higher-level autonomous execution path — arguably it needs stronger, not weaker, truth closure.

### Gap 5 [MEDIUM]: No Dual-Repo Automated E2E Test

The test suite has extensive unit tests (`tests/test_android_bridge_udm_flow.py`, `tests/test_v2_android_runtime_closure_audit.py`, `tests/test_l4_e2e.py`, etc.) but no live E2E test that:
- Starts the FastAPI gateway in test mode
- Runs a real WebSocket client simulating Android
- Sends `device_register` → receives `task_assign` → sends `task_result`
- Verifies `is_truth_chain_complete = True`

### Gap 6 [MEDIUM]: UDM Registration Post-Steps Are All try/except

7 post-UDM registration actions in `registration.handle_device_register()` are all wrapped in try/except. Any of them can fail silently. This means a device can appear registered (receives `device_register_ack`) while missing from `attached_runtime_session_registry`, `body_mesh_registry`, or mesh session state.

**Consequence**: Downstream dispatch decisions that depend on these registries (particularly V3 dispatch slot dimension 3: attachment validity) may make incorrect decisions because the registry data is incomplete.

---

## 7. Final Verdict

### 7.1 Can the full center-distributed system actually run end-to-end today?

**Yes, through the nominal path, under favorable conditions.**

The following complete path is real:
```
User request → OpenClawd.process() → UnifiedLLMRouter (LLM call) → 
cross_device branch → CommandRouter.route_envelope() → gateway WS → 
Android task execution (EdgeExecutor) → goal_execution_result →
android_bridge.handle_task_result() → truth chain (best-effort) → Future resolved
```

This path **can and does execute** when:
- The center service is running (FastAPI + gateway)
- An Android device is connected via the canonical WebSocket path
- Provider API keys are configured
- Android has Accessibility Service permission for EdgeExecutor
- The device is registered and reachable

### 7.2 Through which real paths?

**Confirmed runnable real paths:**
1. **Local execution path**: `OpenClawd → DecisionExecutor → WindowsExecutionArbiter` (no Android involved)
2. **Cross-device path**: `OpenClawd → CommandRouter → gateway → Android EdgeExecutor → task_result`
3. **Goal execution path**: `CommandRouter → Android AutonomousExecutionPipeline → goal_result` (LLM-dependent on Android side)
4. **Handoff/Takeover path**: `CommandRouter → handoff_envelope_v2 → DelegatedTakeoverExecutor → handoff_v2_result`

### 7.3 What exact gaps prevent full run-through?

The system runs. The gaps are **enforcement gaps**, not **execution gaps**:

1. **No cognitive authority enforcement**: L1–L4 exist but are not on the hot path. LLM calls go through `UnifiedLLMRouter`, not `CognitiveExecutionAuthority`. The center cannot verify that routing, supply, context, and execution followed the canonical authority chain.

2. **No dispatch slot enforcement**: V3/V4 exist but are not called before dispatch. `CommandRouter` can dispatch to any device that is in `bridge._devices` without evaluating continuity legality, occupancy, or policy allowance.

3. **No hard completion truth**: V1 truth chain is on the path but soft. A task can complete with partial or failed truth chain steps.

4. **No automated E2E verification**: No CI test exercises the full round-trip. The system could be broken at any integration point without automatic detection.

### 7.4 Which chains are genuinely closed, and which are only architecturally implied?

| Chain | Status |
|-------|--------|
| Transport / connection layer | **GENUINELY CLOSED** |
| AIP v3 protocol contract | **GENUINELY CLOSED** |
| Android session continuity (connect/reconnect/offline) | **GENUINELY CLOSED** |
| Result emission canonical path (goal_execution_result) | **GENUINELY CLOSED** |
| System startup sequence | **GENUINELY CLOSED** |
| LLM invocation (UnifiedLLMRouter path) | **GENUINELY CLOSED** (bypasses L1–L4) |
| Basic task_assign → task_result round-trip | **GENUINELY CLOSED** (truth soft) |
| L1–L4 cognitive authority chain | **ARCHITECTURALLY IMPLIED** — present but not invoked from hot path |
| V3 canonical dispatch slot (10 dimensions) | **ARCHITECTURALLY IMPLIED** — not called from CommandRouter |
| V4 unified orchestration spine | **ARCHITECTURALLY IMPLIED** — not called from any live path |
| V1 truth chain (hard enforcement) | **ARCHITECTURALLY IMPLIED** — on path but best-effort only |
| V5 group completion closure | **ARCHITECTURALLY IMPLIED** — not confirmed wired into fan-out |
| Final acceptance verdict | **ARCHITECTURALLY IMPLIED** — optimistic completion only |

### 7.5 Is the system only architecturally converged, or actually operationally closed?

The system is **architecturally converged but not yet operationally closed**.

- **Transport, protocol, and execution are operationally closed**: the nominal round-trip works.
- **Authority enforcement is architecturally converged but operationally disconnected**: the authority modules exist, are internally consistent, and correctly declare policy — but the live execution paths do not call them.

The 14 merged PRs (V1–V6, L1–L4, A1–A4) created a complete, well-designed authority layer. This layer sits **adjacent to** rather than **inside** the live execution chain. To complete operational closure, each authority module needs to be inserted into the dispatch path it is meant to govern:

- `LLMRouteAuthority.resolve()` must be called from `UnifiedLLMRouter` or `OpenClawd._run_continuum()`
- `evaluate_orchestration_request()` must be called from `CommandRouter.route_envelope()`
- `run_task_result_truth_chain()` steps must be promoted from `try/except` to at minimum `retry-or-fail` semantics
- `evaluate_canonical_dispatch_slot()` must gate `DeviceRouter.dispatch_to_websocket()`

---

## 8. Evidence Summary

All findings above are grounded in the following real code locations:

| Claim | Code location |
|-------|--------------|
| L1 not on hot path | `core/openclawd.py`: imports `unified.llm_router`, not `llm.route_authority` |
| L2 not on hot path | Same — no import of `llm.supply_authority` in `openclawd.py` or `unified/llm_router.py` |
| L3 not on hot path | grep: `context_authority` → only in `core/llm/`, `core/routes/ai.py`, `core/routes/chat.py` |
| L4 not on hot path | grep: `execution_authority` → only in `core/llm/`, `core/schemas/`, `core/routes/` |
| V3 not called by CommandRouter | grep `canonical_dispatch_slot` in `command_router.py` → no matches |
| V4 not called by any live path | grep `unified_orchestration_spine` → only `core/center_authority_boundary.py` and self-references |
| V1 soft-enforced | `task_lifecycle.py` truth chain loop: all steps `try/except`; `is_truth_chain_complete=False` only a warning |
| Transport chain real | `GalaxyWebSocketClient.kt` 68KB single-file WS client; full lifecycle in code |
| Protocol alignment real | `aip_v3.py` + `AipModels.kt` field-level match; `handle_*` handlers exist for all 20+ message types |
| Session continuity real | `OfflineTaskQueue.kt` session authority bounding; `classify_reconnect_outcome()` in `registration.py` |
| Offline queue compat paths alive | `OfflineTaskQueue.QUEUEABLE_TYPES` includes `"task_result"`, `"goal_result"` |

---

*This document was produced by real code traversal across both repositories as of 2026-04-30. Every claim is backed by a named file, import, or grep result. No prior PRs, documentation, or design statements were used as evidence.*
