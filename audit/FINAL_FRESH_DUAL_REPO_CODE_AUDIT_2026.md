# Final Fresh Dual-Repository Code Audit — V2 ↔ Android Integrated System
<!-- audit_id: FINAL_FRESH_DUAL_REPO_CODE_AUDIT_2026 -->
<!-- method: code-only, no prior audit artifacts used as evidence -->
<!-- android-sha: 92041b5bc16324488f9dcd68fa35a5836a1ee1f5 -->
<!-- v2-ref: HEAD (copilot/new-final-code-integrated-audit) -->

---

## Scope and Methodology

This document is produced from **direct reading of implementation code only**.  
No prior audit files, verdict constants, reality-summary markdown, or narrative 
documents from earlier PRs are treated as evidence.  All claims below reference 
specific source files and code paths from:

- **V2**: `DannyFish-11/ufo-galaxy-realization-v2` (this repository)  
- **Android**: `DannyFish-11/ufo-galaxy-android` @ SHA `92041b5bc16324488f9dcd68fa35a5836a1ee1f5`

Findings are labeled:

- **FACT** — directly readable from source code  
- **INFERRED** — reasonable conclusion from code structure (noted where inference is made)

---

## Part 1 — System Architecture and Repository Roles

### 1.1 What V2 is

V2 is the **centralized orchestration and protocol gateway** for the system.  
Evidence: `main.py` → `SystemOrchestrator` → `unified_launcher.py` → `galaxy_gateway/` FastAPI application.

Its concrete roles (all FACT from source):

| Role | Code location |
|------|--------------|
| Protocol gateway (WebSocket ingress) | `galaxy_gateway/routes/websocket.py` |
| Task dispatch authority | `galaxy_gateway/device_router.py` |
| Device registry/presence truth | `core/unified/device_manager.py` (UDM); `core/device_registry.py` is a compat index layer |
| Pending-delivery buffer (V2-side) | `galaxy_gateway/pending_delivery_buffer.py` |
| Stale device cleanup | `galaxy_gateway/bootstrap/lifecycle.py` periodic task |
| AI reasoning / LLM routing | `core/multi_llm_router.py`, `core/openclawd.py` |
| REST API surface | `core/routes/` sub-modules, aggregated in `core/api_routes.py` |

### 1.2 What Android is

Android is the **distributed execution participant node**.  
Evidence: `GalaxyConnectionService.kt` (161 KB foreground service), `GalaxyWebSocketClient.kt`, `BootReceiver.kt`.

Its concrete roles (all FACT):

| Role | Code location |
|------|--------------|
| Single persistent uplink | `GalaxyWebSocketClient.kt` — sole write path |
| Perpetual reconnect | `GalaxyWebSocketClient.kt` exponential backoff loop |
| Offline result buffering | `OfflineTaskQueue.kt` |
| UI automation execution | `EnhancedFloatingService.kt`, `AccessibilityActionExecutor.kt` |
| Boot auto-start | `BootReceiver.kt` (`BOOT_COMPLETED` intent handler) |
| Protocol model | `AipModels.kt` → `MsgType` enum |

### 1.3 How the two repositories form one system

```
User / Operator
      │
      ▼
  main.py ──► SystemOrchestrator ──► unified_launcher.py
                                            │
                                            ▼
                                   galaxy_gateway/ (FastAPI)
                                            │
                                    ┌───────┴───────┐
                                    │  WebSocket     │
                            /ws/device/{id}          │
                            /ws/android/{id}         │
                                    │                │
                          ┌─────────┘                │
                          │  AndroidBridge           │
                          │  .handle_message()       │
                          │  dispatch table          │
                          └─────────┬────────────────┘
                                    │ (35+ handlers)
                                    ▼
                           DeviceRouter, UDM,
                           PendingDeliveryBuffer,
                           LifecycleCoordinator...
                                    ▲
                                    │ WebSocket
                           GalaxyWebSocketClient
                                    │
                              Android App
                          GalaxyConnectionService
                          (foreground service)
                                    │
                         UI automation / execution
                         EnhancedFloatingService
                         AccessibilityActionExecutor
```

**FACT**: The two repositories are complementary halves of a single system.  
V2 cannot execute UI actions on a phone (it has no display).  
Android cannot orchestrate multi-step agent tasks without the V2 reasoning layer.

---

## Part 2 — Protocol and Transport

### 2.1 Canonical WebSocket ingress path

**FACT** (`galaxy_gateway/routes/websocket.py`, lines 1–100):

The sole **canonical** device ingress is:
```
/ws/device/{device_id}
```
declared as `CANONICAL_DEVICE_INGRESS_AUTHORITY` in that file.

Additional paths and their status:

| Path | Classification | Notes |
|------|---------------|-------|
| `/ws/device/{device_id}` | **CANONICAL** | AIP v3, all production devices |
| `/ws/android/{device_id}` | COMPAT | delegates to same `_handle_android_ws()` pipeline |
| `/ws/android` | COMPAT | fallback compat, same pipeline |
| `/ws/ufo3/{device_id}` | LEGACY-DISABLED | gated by `GALAXY_ENABLE_LEGACY_PROTOCOLS=true` |
| `/ws/webrtc/{device_id}` | MEDIA | WebRTC signaling only, not device-mainline |
| `/ws/{device_id}` | DEPRECATED | catch-all, do not use |
| `/ws` | DEBUG | auto-assign debug path |

All Android-facing compat paths route through `_handle_android_ws()` which calls
`android_bridge.handle_message()` after normalising messages through 
`galaxy_gateway/protocol/compat.normalise_to_v3_dict()`.

**FACT** (`core/api_routes.py`, line 527): A second `/ws/device/{device_id}` exists in
`core/api_routes.py` but is explicitly classified as a **compatibility-only** path, non-canonical.

### 2.2 Message type coverage

**V2 side** (`galaxy_gateway/protocol/aip_v3.py`): Defines the `MessageType` enum with dozens of
string-typed entries covering device lifecycle, task lifecycle, handoff, reconciliation,
peer mesh, vision, diagnostics, and more.

**Android side** (`AipModels.kt`): Defines the corresponding `MsgType` enum that **mirrors** the
server-side `MessageType` one-to-one (explicitly noted in the file's KDoc: "mirroring server-side 
MsgType enum exactly").

**FACT**: Protocol alignment is declared explicitly in code.

### 2.3 Handler registration and dispatch

**FACT** (`galaxy_gateway/android_bridge.py`, lines 728–816): `AndroidBridge.__init__` builds
a complete `_message_handlers` dict by explicit registration of every handled type, followed by
a catch-all loop that fills any remaining `MessageType` member with `handle_unregistered`.

Explicitly registered handlers include:

| Message type | Handler |
|-------------|---------|
| `DEVICE_REGISTER` | `handle_device_register` |
| `DEVICE_HEARTBEAT` | `handle_heartbeat` |
| `TASK_RESULT` | `handle_task_result` |
| `TASK_PROGRESS` | `handle_task_progress` |
| `COMMAND_RESULT` | `handle_command_result` |
| `GOAL_EXECUTION` | `handle_goal_execution` |
| `PARALLEL_SUBTASK` | `handle_parallel_subtask` |
| `GOAL_EXECUTION_RESULT` | `handle_goal_execution_result` |
| `GOAL_RESULT` | `handle_goal_execution_result` (alias) |
| `TASK_CANCEL` | `handle_task_cancel` |
| `FILE_TRANSFER` | `handle_file_transfer` |
| `PEER_ANNOUNCE` | `handle_peer_announce` |
| `PEER_EXCHANGE` | `handle_peer_exchange` |
| `MESH_TOPOLOGY` | `handle_mesh_topology` |
| `CAPABILITY_REPORT` | `handle_capability_report` |
| `DIAGNOSTICS_PAYLOAD` | `handle_diagnostics_payload` |
| `VISION_REQUEST` | `handle_vision_request` |
| `DELEGATED_EXECUTION_SIGNAL` | `handle_delegated_execution_signal` |
| `HANDOFF_ACK` / `HANDOFF_RESULT` / `HANDOFF_FAILURE` | `handle_handoff_v2_result` |
| `HANDOFF_ENVELOPE_V2_RESULT` | `handle_handoff_v2_result` |
| `TAKEOVER_RESPONSE` | `handle_takeover_response` |
| `RECONCILIATION_SIGNAL` | `handle_reconciliation_signal` |
| `CANCEL_RESULT`, `DEVICE_*_REPORT` (5 types) | `handle_generic_forward` |
| All other valid `MessageType` members | `handle_unregistered` (catch-all) |

### 2.4 Unknown-type behavior

**FACT** (`galaxy_gateway/android_bridge.py`, `handle_message()`, lines ~870–880):

Two-tier handling:

1. If `msg_type_str` is not a valid `MessageType` enum value → `ValueError` is caught →
   returns `{"type": "error", "code": "UNKNOWN_MESSAGE_TYPE"}` to the Android device.
   Messages are **not silently dropped**.

2. If `msg_type_str` **is** a valid `MessageType` but has no explicit handler →
   `handle_unregistered` is called (catch-all loop ensures this), which logs the type
   and returns `{"type": "ack", "original_type": ..., "note": "No specific handler"}`.
   Also **not silently dropped**.

### 2.5 ACK behavior

**FACT**: Every handler returns a dict response.  ACKs are:

- **Typed ACKs**: e.g. `heartbeat_ack`, `device_register_ack`, `reconciliation_signal_ack`
  (handler-specific).
- **Generic ACKs**: `handle_generic_forward` returns `{type: "{original_type}_ack"}`.
- **Unregistered ACKs**: `handle_unregistered` returns `{type: "ack", original_type: ...}`.

Android-side heartbeat: `GalaxyWebSocketClient` sends `heartbeat` every 30 s; expects
`heartbeat_ack` from V2 (registered handler: `handle_heartbeat`).

### 2.6 ReconciliationSignal end-to-end

**FACT** (`galaxy_gateway/android/handlers/reconciliation_signal.py`):

1. Android sends `reconciliation_signal` message (uplink from `RuntimeController`)
2. V2 `RECONCILIATION_SIGNAL` handler registered in dispatch table
3. Handler calls `AndroidDelegatedRuntimeLifecycleCoordinator.on_reconciliation_signal()`
4. Returns `reconciliation_signal_ack` to Android

The wire is **fully closed**: send path exists in Android, receive+process path exists in V2,
ACK is returned.

### 2.7 HandoffEnvelopeV2 response/settlement path

**FACT** (`galaxy_gateway/android/handlers/handoff_v2_result.py`):

1. V2 dispatches a handoff via `DeviceRouter` → Android receives it
2. Android executes and sends back `handoff_result` / `handoff_ack` / `handoff_failure`
3. V2 handler `handle_handoff_v2_result` receives it
4. Calls `core.android_handoff_v2_response_ingress.ingest_android_handoff_response()`
   to correlate response to dispatch, resolve any waiting Future, invoke callback
5. For terminal messages also calls `DeviceRouter.handle_task_result()` to wake any
   `dispatch_to_websocket` awaiter (prevents 30 s timeout-only completion)

The settlement path is **fully wired**: handoff dispatch → Android execution → V2 ingestion
→ orchestration continuation.

---

## Part 3 — Lifecycle, Resilience, and Long-Run Recoverability

### 3.1 Android reconnect behavior after repeated failures

**FACT** (`GalaxyWebSocketClient.kt`, KDoc and `companion object`):

```kotlin
private val RECONNECT_BACKOFF_MS = longArrayOf(1_000, 2_000, 4_000, 8_000, 16_000, 30_000)
private const val RECONNECT_JITTER_MAX_MS = 1_000L
private const val MAX_RECONNECT_ATTEMPTS = 10
```

Behavior:
- Delays: 1 s → 2 s → 4 s → 8 s → 16 s → 30 s (capped), +≤1 s jitter
- After `MAX_RECONNECT_ATTEMPTS` (10): `Listener.onError` emitted, **counter resets to 0**
- Reconnect continues **indefinitely** at the 30 s capped interval
- `shouldReconnect = true` is the only gate; calling `disconnect()` sets it to `false`
- `onOpen` resets attempt counter to 0

**FACT**: The device **never stops reconnecting** unless explicitly stopped by `RuntimeController`.
This is documented in the KDoc as "perpetual watchdog" behavior.

### 3.2 Watchdog recovery

**FACT**: `GalaxyWebSocketClient` itself IS the watchdog — it loops indefinitely.
No separate watchdog class is needed on Android.

**FACT** (`GalaxyConnectionService.kt`, 161 KB foreground service): The service runs in the
Android foreground (persistent notification), survives screen-off and background restriction
on most Android versions.

**FACT** (`BootReceiver.kt`): Registered for `BOOT_COMPLETED` Android intent — starts
`GalaxyConnectionService` automatically on device reboot (subject to Android OS allowing it).

### 3.3 Startup behavior (V2 side)

**FACT** (`main.py`, `galaxy_gateway/bootstrap/lifecycle.py`):

V2 startup sequence:
1. `main.py` → `SystemOrchestrator.run_startup_sequence()` (phases 1–7)
2. Hand-off to `unified_launcher.py`
3. `galaxy_gateway/bootstrap/lifecycle.py` `lifespan()` context manager starts:
   - `WebSocketManager` + heartbeat
   - `TaskOrchestrator`
   - `OpenClawd` (AI layer)
   - `MultiLLMRouter`
   - NATS adapter (optional, degrades gracefully if NATS not available)
   - Stale-device cleanup background task (asyncio task, runs immediately)

### 3.4 Stale device cleanup on V2 side

**FACT** (`galaxy_gateway/bootstrap/lifecycle.py`, lines 135–165):

Background asyncio task:
- Interval: `GALAXY_STALE_CLEANUP_INTERVAL_S` (default 90 s)
- Timeout threshold: `GALAXY_STALE_CLEANUP_TIMEOUT_S` (default 120 s)
- Calls `android_bridge.cleanup_stale_devices(timeout_seconds=120)` each cycle
- Marks devices without heartbeat within 120 s as disconnected in transport cache

**FACT** (`galaxy_gateway/pending_delivery_buffer.py`, line 55): `cleanup_stale_devices` also
calls `buffer.purge_expired()` to remove stale pending-delivery entries for cleaned-up devices.

### 3.5 Long-run recoverability verdict

| Scenario | Behavior (from code) |
|----------|---------------------|
| Android brief disconnect (<60 s) | V2 `DurablePendingDeliveryBuffer` preserves in-flight tasks; Android `OfflineTaskQueue` preserves results; both sides flush on reconnect |
| Android long disconnect (>60 s, <24 h) | Android `OfflineTaskQueue` survives (SharedPreferences, TTL 24 h); V2 buffer expires (TTL 60 s) — task-to-device re-dispatch must be re-triggered by V2 orchestration layer |
| V2 restart (<60 s) | `DurablePendingDeliveryBuffer` file-backed snapshot survives; messages re-delivered on reconnect |
| Android reboot | `BootReceiver` starts `GalaxyConnectionService`; `OfflineTaskQueue` loaded from SharedPreferences |
| Perpetual Android failure loop | Reconnect continues indefinitely at 30 s intervals; V2 stale cleanup removes device from routing after 120 s of silence |

---

## Part 4 — Dispatch, Execution, and Result Continuity

### 4.1 Task routing

**FACT** (`galaxy_gateway/device_router.py`, 1947 lines): `DeviceRouter` is the task dispatch
authority. It routes tasks to connected devices via `dispatch_to_websocket()`, which uses
`android_bridge.send_to_device()` for Android targets.

### 4.2 Legality gates

**FACT** (`core/unified_dispatch_readiness_gate.py`, `core/release_blocking_gate.py`): 
Legality/readiness gates exist as Python modules.  
**INFERRED**: These gates are called at dispatch time; whether they are enforced as hard-blocking
or advisory depends on the calling code. The CI `governance_gate_enforcement.yml` workflow runs
`run_governance_verdict_ci` and exits with code 1 on `BLOCKED` verdict — this gate **is** 
enforced in CI but is only exercised at merge time, not at runtime task dispatch.

### 4.3 Pending/offline buffering — both sides

**V2 side** (FACT, `galaxy_gateway/pending_delivery_buffer.py`):
- `DurablePendingDeliveryBuffer` (file-backed) used when `send_to_device()` finds device offline
- Bufferable types: `task_assign`, `task_execute`, `task_submit`, `goal_execution`, 
  `action_execute`, `action_sequence_execute`, `system_command`
- Capacity: 32 per device (oldest evicted)
- TTL: 60 s (above 30 s command timeout, below long-disconnect threshold)
- Flushed by `reconnect_device()` on successful reconnect

**Android side** (FACT, `OfflineTaskQueue.kt`):
- Queues `task_result`, `goal_result`, `goal_execution_result` when WebSocket disconnected
- Capacity: 50 per instance (oldest evicted with WARN log)
- TTL: 24 h (loaded from SharedPreferences on restart; stale entries discarded)
- Session authority bounding: `discardForDifferentSession(currentTag)` removes stale-session entries before drain
- Flushed via `drainAll()` on successful `onOpen`

### 4.4 Durability across V2 restarts

**FACT** (`DurablePendingDeliveryBuffer`): File written atomically to
`$GALAXY_DATA_DIR/pending_delivery.json` (default `data/pending_delivery.json`).
Messages with non-expired wall-clock timestamps survive V2 process restart within TTL window.

### 4.5 Replay/flush behavior on reconnect

**FACT** (both sides):
- Android: `onOpen` callback calls `offlineQueue.discardForDifferentSession(currentTag)` then
  `offlineQueue.drainAll()` and re-sends in FIFO order
- V2: `reconnect_device()` calls `pending_delivery_buffer.flush(device_id)` and re-delivers
  buffered messages via the live WebSocket

### 4.6 Result ingestion and terminal completion

**FACT** (`handle_handoff_v2_result`): HandoffEnvelopeV2 results call
`DeviceRouter.handle_task_result()` → sets `task_events[task_id]` event →
wakes any `dispatch_to_websocket` awaiter.  
This closes the completion continuation path — V2 does not rely on timeouts alone.

---

## Part 5 — Deployment and Real-World Operability

### 5.1 What works in actual code

The following require **only** that V2 is running and Android has the correct server URL:

- WebSocket connection (OkHttp with `pingInterval(20, TimeUnit.SECONDS)`)
- Device registration (`DEVICE_REGISTER` handler wired)
- Heartbeat keepalive (both sides implemented)
- Task dispatch and result return (dispatch table complete)
- Perpetual reconnect on Android failures

### 5.2 Single-device reality

**FACT** (RUNNABLE): One Android device connecting to one V2 instance on LAN works with only
server URL configuration. `device_id` is auto-assigned or configured in Android config.

### 5.3 Multi-device reality

**FACT** (RUNNABLE WITH PROVISIONING): `DeviceRouter` and `UnifiedDeviceManager` both support
multiple devices by `device_id`. No architectural constraint prevents multi-device.  
**INFERRED limitation**: Each device needs independent network access to V2; no zero-config
auto-discovery (mDNS/Bonjour) is implemented in the reviewed code.

### 5.4 Remote/non-LAN reality

**FACT** (`TailscaleAdapter.kt` exists, 5.9 KB): An adapter class for Tailscale VPN is
present in the Android codebase.

**FACT** (`GalaxyWebSocketClient.kt`): `allowSelfSigned: Boolean = false` parameter exists for
self-signed TLS (debug/dev only, explicitly noted).

**DEPLOYMENT-CONDITIONAL**: Remote operation requires either:
- A publicly reachable V2 server endpoint, **or**
- Tailscale configured on both Android device and V2 host (requires operator setup,
  Tailscale not auto-provisioned by the app)

**Not present** in either codebase: zero-config remote tunneling or auto-NAT traversal.

### 5.5 What remains deployment-conditional vs. implementation-missing

| Capability | Status | Basis |
|-----------|--------|-------|
| LAN single-device operation | **Runnable** | WebSocket, registration, reconnect all implemented |
| LAN multi-device operation | **Runnable** | DeviceRouter supports N devices |
| Remote access | **Deployment-conditional** | Requires reachable endpoint or Tailscale |
| Android UI automation | **Deployment-conditional** | Requires user to grant Accessibility Service |
| Android boot persistence | **Deployment-conditional** | Requires Android OS not to kill BootReceiver (varies by OEM) |
| Advanced hybrid/RAG/code execution | **Partial** | `MsgType` defined; `@status minimal-compat` noted in `AipModels.kt` KDoc |

---

## Part 6 — Governance and Integrity Enforcement

### 6.1 CI enforcement reality

**FACT** (`.github/workflows/ci.yml`):

Real blocking CI jobs in V2:
- `lint`: flake8, black, isort — hard-fails on violations
- `v3-protocol-guard`: scans for `aip_protocol_v2` imports outside deprecated stub — hard-fails if found
- `s6-compat-smoke`: legacy path compat regression suite

**FACT** (`.github/workflows/governance_gate_enforcement.yml`):
- `governance-verdict` job: runs `run_governance_verdict_ci()`, exits 1 on `BLOCKED`
- `consistency-gates` job: runs `build_consistency_gate_snapshot()`, exits 1 on any `"fail"` verdict

These gates are **real CI-blocking** jobs (not advisory).

### 6.2 Cross-repo drift detection

**FACT**: `core/cross_repo_consistency_gates.py` and Android's
`protocol/CrossRepoConsistencyGate.kt` both exist. V2 CI runs the Python gates.

**LIMITATION** (FACT from code inspection): The V2 CI workflows do **not** dynamically
`git checkout` the Android repository and scan its source. The Python consistency gate
(`core/cross_repo_protocol_consistency.py`) describes cross-repo contracts but cannot
verify them against live Android source code at PR merge time.  
The Android-side gate (`CrossRepoConsistencyGate.kt`) runs only when the Android app
is built/tested, which is a separate build process.

**INFERRED conclusion**: Protocol drift between the two repos would only be caught if:
(a) the V2 CI gates are tuned to detect it, and/or (b) the Android CI is run — but
there is no evidence of a unified cross-repo CI pipeline that runs both together.

### 6.3 Truth surface enforceability

**FACT**: The governance/consistency gate code exists and blocks CI on documented failure
conditions. The system has more enforcement than purely advisory-only.

**LIMITATION**: The enforcement is bounded to what the gate code checks.
Current gate code checks protocol constants and dispatch invariants within the V2 repo.
It does not dynamically verify Android source.

---

## Part 7 — Final Integrated Verdict

### Based strictly on code evidence:

**System identity**: A center-distributed AI agent execution system.  
V2 is the orchestration/protocol center.  Android is the execution edge node.

**Core protocol**: ✅ COMPLETE  
Both sides have matching `MessageType`/`MsgType` enums. V2 dispatch table has 35+  
registered handlers with no silent-drop paths. Unknown types return typed error or ACK.

**Transport/reconnect**: ✅ COMPLETE  
Android: perpetual exponential-backoff reconnect (never stops). V2: stale cleanup task,
TCP-level ping every 20 s (OkHttp). Both sides buffer across brief disconnections.

**ReconciliationSignal**: ✅ COMPLETE (wire closed end-to-end)  
**HandoffEnvelopeV2 settlement**: ✅ COMPLETE (wire closed end-to-end)

**Offline buffering**: ✅ COMPLETE (both sides, file-backed/SharedPreferences)

**Boot persistence**: ✅ IMPLEMENTED (`BootReceiver.kt`, foreground service)

**Single-device LAN operation**: ✅ RUNNABLE — no unimplemented blockers

**Multi-device operation**: ✅ RUNNABLE — architecture supports it, requires provisioning

**Remote/non-LAN operation**: ⚠️ DEPLOYMENT-CONDITIONAL — infrastructure dependent  
(Tailscale adapter exists; zero-config tunneling does not)

**Android UI automation**: ⚠️ DEPLOYMENT-CONDITIONAL — requires OS permission grants

**CI governance enforcement**: ✅ REAL (hard-blocking CI jobs exist)  
❕ Cross-repo drift detection is **partial** — V2-side only; no unified cross-repo CI pipeline

**Advanced capability channels** (hybrid, RAG, code execution): ⚠️ MINIMAL-COMPAT  
(protocol models defined; full implementations marked TODO in `AipModels.kt`)

### Final verdict:

```
OPERATIONALLY_RUNNABLE_CONDITIONAL
```

The system is a real, functionally coherent center-distributed AI agent architecture.  
The protocol is implemented and aligned across both repos. Reconnect and buffering are  
fully implemented. The core task execution loop (dispatch → Android → result → V2 settlement)  
is completely wired.

It is **not** unconditionally complete because:
1. Remote access requires operator deployment (Tailscale or public endpoint)
2. Android automation requires user permission grants (OS-level, cannot be coded around)
3. Advanced capability channels (hybrid, RAG, code execution) have protocol stubs but
   missing runtime implementations (`@status minimal-compat` in source)
4. Cross-repo CI drift detection is partial — no unified build pipeline verifying
   both repos together against live source

These are **deployment and activation gaps**, not protocol or architectural gaps.  
The architecture and protocol are genuinely complete for the core execution path.

---

## Appendix — Key Code Evidence Index

| Claim | File | Line range |
|-------|------|-----------|
| Canonical WebSocket ingress declaration | `galaxy_gateway/routes/websocket.py` | ~1–50 |
| Android compat path delegates to same pipeline | `galaxy_gateway/routes/websocket.py` | `_handle_android_ws()` |
| Dispatch table registration | `galaxy_gateway/android_bridge.py` | ~728–820 |
| Catch-all unregistered handler | `galaxy_gateway/android_bridge.py` | ~814–817 |
| Unknown type → error response | `galaxy_gateway/android_bridge.py` | `handle_message()` ValueError block |
| ReconciliationSignal handler | `galaxy_gateway/android/handlers/reconciliation_signal.py` | entire file |
| HandoffEnvelopeV2 settlement | `galaxy_gateway/android/handlers/handoff_v2_result.py` | entire file |
| Pending delivery buffer (V2) | `galaxy_gateway/pending_delivery_buffer.py` | entire file |
| Stale device cleanup task | `galaxy_gateway/bootstrap/lifecycle.py` | ~135–165 |
| Android perpetual reconnect | `GalaxyWebSocketClient.kt` | `companion object` + reconnect loop |
| Android offline queue | `OfflineTaskQueue.kt` | entire file |
| Android boot receiver | `service/BootReceiver.kt` | entire file |
| Protocol enum alignment | `galaxy_gateway/protocol/aip_v3.py` + `protocol/AipModels.kt` | `MessageType` / `MsgType` |
| CI governance gate | `.github/workflows/governance_gate_enforcement.yml` | entire file |
| CI protocol guard | `.github/workflows/ci.yml` | `v3-protocol-guard` job |
| Tailscale remote access adapter | `network/TailscaleAdapter.kt` | entire file |
| Advanced channels minimal-compat status | `protocol/AipModels.kt` | `@status minimal-compat` annotations |
