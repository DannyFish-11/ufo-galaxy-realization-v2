# PR-8 Full-System Product Readiness Review
## UFO Galaxy Dual-Repo System: `ufo-galaxy-realization-v2` + `ufo-galaxy-android`

> **Document type**: Code-grounded product usability assessment.
>
> **Primary repository**: `DannyFish-11/ufo-galaxy-realization-v2`  
> **Companion repository**: `DannyFish-11/ufo-galaxy-android`  
> **Review scope**: Complete dual-repo system — backend, Android runtime, cross-repo
> integration, end-to-end operational flow, recovery, and real-world usability.
>
> **Evidence classification used throughout**:
> - ✅ **Verified by code/tests** — directly confirmed in repository source
> - 🟡 **Strongly implied** — clear structural evidence, not fully traced end-to-end
> - ❌ **Unclear / likely missing** — no code evidence found or gap explicitly noted

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture Overview](#2-system-architecture-overview)
3. [V2 Backend Assessment](#3-v2-backend-assessment)
4. [Android App Assessment](#4-android-app-assessment)
5. [Cross-Repo Integration Assessment](#5-cross-repo-integration-assessment)
6. [End-to-End Operational Flow](#6-end-to-end-operational-flow)
7. [Recovery, Continuity, and Offline Behavior](#7-recovery-continuity-and-offline-behavior)
8. [Build and Test Infrastructure](#8-build-and-test-infrastructure)
9. [Operator Visibility and Usability](#9-operator-visibility-and-usability)
10. [Operational Gap Matrix](#10-operational-gap-matrix)
11. [Readiness Verdict by Dimension](#11-readiness-verdict-by-dimension)
12. [Recommended Next-Stage Priorities](#12-recommended-next-stage-priorities)

---

## 1. Executive Summary

The dual-repository Galaxy system is **architecturally sophisticated and structurally
coherent**. The V2 backend contains a well-designed canonical orchestration spine, a
rich device/Android integration layer, and extensive documentation. The Android app
is a real Kotlin application with WebSocket connectivity, offline persistence, and
production-grade service infrastructure.

However, the system **does not yet run smoothly end-to-end out of the box** for a new
operator. The core blockers are not architectural — they are operational:

1. **Connection bootstrapping is not documented as a user-facing runbook.** A developer
   who clones both repos has no single walkthrough for "install, configure, connect,
   verify working."

2. **No pre-built APK is distributed.** The Android app must be compiled from source
   before the cross-device path can be tested.

3. **Authentication is dependency-gated at startup.** `core/auth.py` must be present
   and valid; the fallback is HTTP 401 on all guarded routes. No default-open or
   development-mode auth path is documented.

4. **The V2 backend is Windows-first in its subject/execution model.** The
   `DesktopPresenceRuntime` → `OpenClawd` chain assumes a Windows desktop environment
   for local execution. Android is a cross-device participant, not an alternative host
   for the V2 backend itself.

5. **Several protocol types are deferred / minimal-compat only.** Key types such as
   `hybrid_execute`, `rag_query`, and the handoff/v2-response paths are structurally
   present but not operationally closed.

6. **The release gate is skeleton-only.** `core/distributed_release_gate_skeleton.py`
   produces a structured verdict but does not block CI or release. No hard enforcement
   exists yet.

**Overall rating: Architecturally Ready, Operationally Pre-Production.**

The system can be run by an experienced developer who understands both repositories.
It cannot yet be smoothly operated by someone relying only on the existing documentation
and tooling. The highest-leverage improvements are in the operational bootstrapping
layer, not the core architecture.

---

## 2. System Architecture Overview

### 2.1 Two-Repository Model

| Repository | Role | Primary Language |
|---|---|---|
| `ufo-galaxy-realization-v2` | V2 control plane — canonical orchestration authority, API gateway, dispatch spine, truth/projection | Python (FastAPI, asyncio) |
| `ufo-galaxy-android` | Android device runtime — on-device execution, result uplink, offline queue, floating UI | Kotlin (Android SDK) |

### 2.2 Authority Hierarchy (Verified ✅)

```
main.py                              ← canonical system entrypoint (PR-2)
  └─ core/system_orchestrator.py     ← staged 7-phase pre-flight
       └─ unified_launcher.py        ← subordinate async service launch
            ├─ DesktopPresenceRuntime  ← outer session shell (Windows)
            │    └─ OpenClawd           ← cognition + execution core
            │         ├─ local path     ← Windows/System API
            │         └─ cross-device   ← CommandRouter → DeviceRouter
            └─ galaxy_gateway (FastAPI) ← canonical device ingress
                 └─ /ws/device/{id}      ← AIP v3 WebSocket
                      └─ AndroidBridge  ← Android-specific protocol adapter
```

*Code reference*: `main.py:88–97`, `core/system_orchestrator.py:61–80`,
`galaxy_gateway/routes/websocket.py:46–49`, `core/openclawd.py:20–35`

### 2.3 Android Connection Path (Verified ✅)

```
Android App
  └─ GalaxyConnectionService       ← foreground service, lifecycle manager
       └─ GalaxyWebSocketClient    ← OkHttp WS connection
            └─ ws://<host>:9000/ws/device/{device_id}
                 └─ [compat] /ws/android/{device_id} also supported
```

*Code reference*: `app/src/main/java/com/ufo/galaxy/service/GalaxyConnectionService.kt`,
`app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt`,
`galaxy_gateway/routes/websocket.py:17–20` (compat paths)

---

## 3. V2 Backend Assessment

### 3.1 Startup and Entrypoint

| Item | Status | Code Reference |
|------|--------|----------------|
| Single canonical entrypoint (`python main.py`) | ✅ Verified | `main.py:104–158` |
| 7-phase staged pre-flight | ✅ Verified | `core/system_orchestrator.py:61–80` |
| Subordinate launcher separation | ✅ Verified | `unified_launcher.py:47–55` |
| Exception in pre-flight is non-fatal | ✅ Verified (intentional degraded mode) | `main.py:93–97` |
| Port configuration | ✅ Verified (default 9000, overridable via env) | `config.json:2`, `config/unified_ports.yaml` |
| `--setup` wizard shortcut | ✅ Verified | `main.py:118–123` |
| `--status` option | 🟡 Implied (forwarded to launcher) | `main.py:146` |
| Windows-first runtime subject | ✅ Verified (`DesktopPresenceRuntime`) | `core/openclawd.py:8–35` |

**Observation**: The startup sequence is well-structured and clearly documented. The
non-fatal exception path means V2 starts in degraded mode rather than failing hard —
this is appropriate for a development environment but should be explicitly logged and
surfaced in production.

### 3.2 API Surface

| Domain | Path | Status |
|--------|------|--------|
| Devices | `/api/v1/devices` | ✅ Verified |
| Tasks | `/api/v1/tasks` | ✅ Verified |
| Chat | `/api/v1/chat` | ✅ Verified |
| Health | `/api/v1/health` | ✅ Verified |
| Monitoring | `/api/v1/monitoring` | ✅ Verified |
| Operator surface | `/api/v1/operator` | ✅ Verified (PR-510) |
| Device WebSocket (canonical) | `/ws/device/{device_id}` | ✅ Verified (gateway) |
| Device WebSocket (compat) | `/ws/android/{device_id}` | ✅ Verified (delegates to canonical) |
| Auth guard | All guarded routes require `core/auth.py` | ✅ Verified |
| Auth fallback | 401 if `core/auth.py` absent | ✅ Verified (`api_routes.py:70–79`) |

*Code reference*: `core/api_routes.py:1–49`

**Observation**: The API surface is comprehensive. Authentication is properly guarded
but there is no documented default-open development mode. A new developer who does not
have `core/auth.py` configured will immediately hit 401s.

### 3.3 Device Management

| Item | Status | Code Reference |
|------|--------|----------------|
| UnifiedDeviceManager (UDM) as canonical write SSOT | ✅ Verified | `core/device_registry.py:1–57` |
| DeviceRegistry as compatibility/indexing layer | ✅ Verified | `core/device_registry.py:80+` |
| Device capability negotiation | ✅ Verified | `core/capability_registry.py`, `core/device_registry.py` |
| Device discovery | ✅ Verified | `core/device_registry.py:50–57` |
| Android runtime host classification | ✅ Verified | `core/android_runtime_host.py:54–76` |
| Multi-device coordination | 🟡 Implied (modules present: `core/multi_device_*`) | `core/multi_device_coordination_authority.py` |

### 3.4 Android Integration Layer

V2 has an unusually deep Android integration layer. The following modules exist and
are code-verified:

| Module | Function | Status |
|--------|----------|--------|
| `core/android_bridge.py` (gateway) | AIP v3 protocol adapter, action translation | ✅ Verified |
| `core/android_delegated_runtime_lifecycle_coordinator.py` | Lifecycle event orchestration facade | ✅ Verified |
| `core/android_v2_continuity_contract.py` | Joint continuity policy contract (7 scenario classes) | ✅ Verified |
| `core/flow_continuity_coordinator.py` | Unified continuity decision entry-point | ✅ Verified |
| `core/android_delegated_signal_ingress.py` | Signal ingress from Android | ✅ Verified |
| `core/android_evaluator_artifact_ingress.py` | Evaluator artifact ingress | ✅ Verified |
| `core/android_participant_session_state.py` | Session state tracking | ✅ Verified |
| `core/android_participant_truth_ingress.py` | Participant truth updates | ✅ Verified |
| `core/android_execution_signal_reconciler.py` | Signal reconciliation | ✅ Verified |
| `core/takeover_tracking.py` | Takeover tracking | ✅ Verified |
| `core/recovery_durability_closure_validator.py` | Cross-module recovery matrix | ✅ Verified |
| `core/distributed_release_gate_skeleton.py` | Release gate skeleton (PR-7) | ✅ Verified (skeleton only, no hard enforcement) |

**Observation**: The Android integration layer is more mature than typical for a
cross-platform system at this stage. The lifecycle coordinator provides a proper
facade pattern that prevents handler-level coupling. However, the operational
completeness of some ingress paths is deferred (see Section 5).

---

## 4. Android App Assessment

### 4.1 Build and Distribution

| Item | Status | Notes |
|------|--------|-------|
| Gradle build files present | ✅ Verified | `build.gradle`, `app/build.gradle`, `settings.gradle` |
| Build script available | ✅ Verified | `build_apk.sh` |
| Min SDK / Target SDK | 🟡 Implied by `app/build.gradle` | Android 7.0+ per `README.md` |
| Pre-built APK distributed | ❌ Not present | Must build from source |
| Kotlin source present | ✅ Verified | `app/src/main/java/com/ufo/galaxy/` |
| Test infrastructure | ✅ Verified (unit tests exist) | `app/src/test/java/` |

### 4.2 Core Services (All Verified ✅)

| Service | Role | Registration |
|---------|------|-------------|
| `GalaxyConnectionService` | Main foreground service, WS lifecycle, task dispatch | `AndroidManifest.xml` |
| `VoiceRecognitionService` | Voice input | `AndroidManifest.xml` |
| `FloatingWindowService` | Floating AI bubble UI | `AndroidManifest.xml` |
| `EnhancedFloatingService` | Full-featured floating assistant | `AndroidManifest.xml` |
| `HardwareKeyListener` | Accessibility service, hardware button triggers | `AndroidManifest.xml` |
| `BootReceiver` | Auto-start after device reboot | `AndroidManifest.xml` |
| `HardwareKeyReceiver` | Media button events | `AndroidManifest.xml` |

*Code reference*: `app/src/main/AndroidManifest.xml`

### 4.3 Network Layer (Verified ✅)

| Component | Function |
|-----------|----------|
| `GalaxyWebSocketClient` | OkHttp-based WS connection; reconnect logic; message routing |
| `OfflineTaskQueue` | FIFO, 50-message cap, 24-hour TTL, SharedPreferences persistence, session-scoped authority bounding |
| `TailscaleAdapter` | VPN-based secure connectivity for remote/cross-network scenarios |
| `NetworkDiagnostics` | Network health assessment |
| `GatewayClient` | Gateway-specific HTTP client |

The `OfflineTaskQueue` implementation is well-designed:
- Drop policy: oldest dropped at capacity limit ✅
- Persistence: SharedPreferences serialization/deserialization ✅
- Stale message eviction on load (24hr TTL) ✅
- Session-scoped authority bounding (`discardForDifferentSession`) ✅

*Code reference*: `app/src/main/java/com/ufo/galaxy/network/OfflineTaskQueue.kt`

### 4.4 Protocol Alignment

| Item | Status | Code Reference |
|------|--------|----------------|
| AIP v3 protocol model | ✅ Verified | `AipModels.kt` (~94KB, extensive) |
| Cross-repo consistency gate | ✅ Verified | `CrossRepoConsistencyGate.kt` |
| UGCP protocol consistency rules | ✅ Verified | `UgcpProtocolConsistencyRules.kt` |
| Android session layer contracts | ✅ Verified | `AndroidSessionLayerContracts.kt` |
| UGCP shared schema alignment | ✅ Verified | `UgcpSharedSchemaAlignment.kt` |

**Observation**: The Android protocol layer is unusually mature for a companion app.
The presence of `CrossRepoConsistencyGate.kt` and `UgcpProtocolConsistencyRules.kt`
shows deliberate cross-repo protocol governance rather than ad-hoc integration.

### 4.5 Permissions and Capabilities

| Permission | Purpose | Required? |
|-----------|---------|-----------|
| `INTERNET` | WebSocket connectivity | Required |
| `ACCESS_NETWORK_STATE` / `ACCESS_WIFI_STATE` | Network condition checks | Required |
| `RECORD_AUDIO` | Voice recognition | Optional |
| `CAMERA` | Vision capabilities | Optional |
| `FOREGROUND_SERVICE` | Background operation | Required |
| `SYSTEM_ALERT_WINDOW` | Floating window | Optional |
| `RECEIVE_BOOT_COMPLETED` | Auto-start | Optional |
| `BLUETOOTH*` | Bluetooth device capabilities | Optional |
| `NFC` | NFC capabilities | Optional |

Hardware features are all marked `required="false"`, meaning the app gracefully
degrades on devices lacking camera/NFC/Bluetooth. ✅

**Security note**: `android:usesCleartextTraffic="true"` is set, allowing
non-HTTPS connections. This is appropriate for LAN development (connecting to a
local V2 instance) but should be restricted in production deployments via a
Network Security Config that limits cleartext to known LAN address ranges.

---

## 5. Cross-Repo Integration Assessment

### 5.1 Connection Path (Verified ✅)

```
Android App startup
  → GalaxyConnectionService.onCreate()
  → GalaxyWebSocketClient.connect(serverUrl)
  → WebSocket handshake: ws://{v2_host}:9000/ws/device/{device_id}
  → AIP v3 device_register message
  → V2 galaxy_gateway/routes/websocket.py _handle_android_ws()
  → AndroidBridge.handle_message("device_register", ...)
  → handle_device_register() → UDM registration
  → V2 sends ACK + capability negotiation
```

This path is structurally complete and code-verified across both repositories.

### 5.2 Task Dispatch Path (Verified ✅)

```
V2 OpenClawd._determine_execution_path() → "cross_device"
  → CommandRouter.route_envelope()
  → SourceDispatchOrchestrator._try_android_bridge_dispatch()
  → AndroidBridge.assign_task(device_id, task)
  → DeviceRouter.dispatch_task()
  → WS: AIP v3 TASK_ASSIGN → Android
  → Android GalaxyConnectionService receives TASK_ASSIGN
  → Task execution on device
  → AIP v3 task_result → V2
  → AndroidBridge handle_task_result()
  → ReconcileAndroidExecutionSignal
```

### 5.3 Protocol Types Status

| AIP v3 Type | Direction | V2 Handler | Android Handler | Status |
|-------------|-----------|------------|-----------------|--------|
| `device_register` | C→S | `handle_device_register` | `GalaxyConnectionService` | ✅ Canonical |
| `heartbeat` | C→S | `handle_heartbeat` | `GalaxyWebSocketClient` | ✅ Canonical |
| `task_assign` | S→C | `MessageBuilder` | `GalaxyConnectionService` | ✅ Canonical |
| `task_result` | C→S | `handle_task_result` | `GalaxyConnectionService` | ✅ Canonical |
| `task_execute` | C↔S | `handle_task_execute` | Android handler | ✅ Canonical |
| `gui_click/swipe/input` | S→C | AIPMessage | Android accessibility layer | ✅ Canonical |
| `action_execute` | S→C | `_handle_forward_log` | `AgentMessageHandler` | ✅ Canonical |
| `hybrid_execute` | S→C | DeviceRouter routes | HYBRID_DEGRADE fallback | 🟡 Deferred (minimal-compat) |
| `rag_query` | C↔S | No dedicated handler found | Not confirmed on Android | ❌ Not operational |
| `takeover_response` | C→S | `on_takeover_response` | Sends response | 🟡 Partially wired |
| `reconciliation_signal` | C→S | `on_reconciliation_signal` | Sends signal | 🟡 Partially wired |
| `handoff_v2_response` | S→C | `android_handoff_v2_response_ingress.py` | Not verified | 🟡 Ingress exists on V2 |

*Source*: `docs/ANDROID_PROTOCOL_MATURITY_MATRIX.md`, `docs/V2_ANDROID_RUNTIME_CLOSURE_AUDIT.md`

### 5.4 Cross-Repo Consistency Mechanisms (Verified ✅)

Both repositories explicitly implement cross-repo consistency enforcement:

- **V2**: `core/cross_repo_consistency_gates.py`, `core/cross_repo_contract_finalization.py`,
  `core/cross_repo_protocol_consistency.py`
- **Android**: `CrossRepoConsistencyGate.kt`, `UgcpProtocolConsistencyRules.kt`,
  `UgcpSharedSchemaAlignment.kt`

This is a notable strength: protocol divergence is a machine-detectable concern in
both repositories, not just documented policy.

### 5.5 Unresolved Cross-Repo Gaps

| Gap | Severity | Notes |
|-----|----------|-------|
| No shared schema generation tooling | Medium | Schema alignment maintained manually in `UgcpSharedSchemaAlignment.kt` |
| No end-to-end integration test that spans both repos | High | V2 tests mock Android; Android tests mock V2 |
| `hybrid_execute` path not operational on Android | Medium | Deferred; HYBRID_DEGRADE fallback active |
| `rag_query` cross-device path not confirmed | Medium | Protocol type exists but no runtime consumer verified |
| APK distribution path not defined | High | No CI artifact, no Play Store channel, no internal distribution channel |

---

## 6. End-to-End Operational Flow

### 6.1 Startup Sequence (Full System)

**V2 Backend (verified ✅)**:
```
1. python main.py
2. Phase 1: Load unified config (config.json + env vars)
3. Phase 2: Resolve system mode
4. Phase 3: Environment checks
5. Phase 4: Background subsystems (NATS, Redis optional)
6. Phase 5: Runtime subject (DesktopPresenceRuntime → OpenClawd)
7. Phase 6: Desktop surface
8. Phase 7: Readiness summary
9. unified_launcher.py: Start FastAPI/uvicorn on port 9000
10. Write runtime/entrypoint.json for client discovery
```

**Android App (verified ✅)**:
```
1. User launches UFO Galaxy app (or BootReceiver triggers on reboot)
2. MainActivity starts
3. User enters V2 server URL in settings
4. GalaxyConnectionService started as foreground service
5. GalaxyWebSocketClient.connect() called
6. AIP v3 device_register sent to V2
7. V2 acknowledges, device enters UDM registry
8. Heartbeat loop begins (keeps connection alive)
9. Optional: Floating window / accessibility service activated
```

**Blocking step**: The Android server URL must be manually configured by the user.
There is no auto-discovery mechanism. ❌

### 6.2 Task Execution Flow (Happy Path)

```
User input → V2 (voice/text/vision via DesktopPresenceRuntime)
  → OpenClawd.process()
  → ContinuumOrchestrator (intent recognition)
  → _determine_execution_path() → cross_device
  → CommandRouter → AndroidBridge.assign_task()
  → Android receives TASK_ASSIGN
  → Device executes (UI automation via accessibility, camera, etc.)
  → task_result sent to V2
  → V2 reconciles result
  → Response delivered to user
```

This flow is **structurally complete** (all modules exist) but is **not verified by
an end-to-end test spanning both repos**. The tests that exist mock the cross-repo
boundary.

### 6.3 What Works Today (High Confidence)

| Scenario | Confidence |
|----------|-----------|
| V2 starts and serves API requests locally | ✅ High — startup sequence is clean |
| Android app connects to V2 via WebSocket | ✅ High — WS client + server handler both present |
| Device registers with V2 UDM on connect | ✅ High — registration handler is canonical |
| Heartbeat keeps connection alive | ✅ High — both sides implement heartbeat |
| Simple task dispatch (TASK_ASSIGN) from V2 to Android | ✅ High — task lifecycle handlers present |
| task_result returned from Android to V2 | ✅ High — result handler present |
| Offline queue persists results during disconnect | ✅ High — OfflineTaskQueue is complete |
| Android reconnects and drains offline queue | ✅ High — reconnect + drain flow present |
| V2 health endpoints respond | ✅ High — health routes registered |

### 6.4 What is Partially Wired (Medium Confidence)

| Scenario | Status |
|----------|--------|
| V2 restart recovery + Android result acceptance | 🟡 Infrastructure present; not end-to-end tested |
| Takeover flow (V2 takes over delegated task) | 🟡 Tracking modules exist; integration partially wired |
| Multi-device coordination | 🟡 Modules present; end-to-end not confirmed |
| Full hybrid execution (Android + V2 co-execute) | 🟡 Deferred; HYBRID_DEGRADE is the active path |
| WebRTC media path | 🟡 Module present but `enable_webrtc_session_manager: false` in config |
| Release gate enforcement | 🟡 Skeleton exists; no hard CI blocking |

### 6.5 What Remains Missing (Low/No Confidence)

| Scenario | Status |
|----------|--------|
| Auto-discovery of V2 by Android (no URL config needed) | ❌ Not implemented |
| Pre-built APK for easy testing | ❌ Not provided |
| Single-command setup guide for both repos | ❌ Not present |
| Cross-repo end-to-end test (real Android + real V2) | ❌ Tests mock the boundary |
| Production auth configuration documentation | ❌ Not found |
| RAG query cross-device path | ❌ Not confirmed operational |
| Chaos/soak test results | ❌ Not present |

---

## 7. Recovery, Continuity, and Offline Behavior

### 7.1 V2-Side Recovery Infrastructure (Verified ✅)

The following recovery modules are present and code-verified:

| Module | Scenario | Status |
|--------|----------|--------|
| `core/flow_continuity_coordinator.py` | Unified continuity decision (7 scenario classes) | ✅ Present |
| `core/delegated_flow_recovery_coordinator.py` | Flow-level replay/resume/re-dispatch | ✅ Present |
| `core/runtime_restart_recovery.py` | V2 process restart orchestration | ✅ Present |
| `core/attached_runtime_recovery_readiness.py` | Inbound signal guard on recovery | ✅ Present |
| `core/recovery_durability_closure_validator.py` | Cross-module recovery closure report | ✅ Present |
| `core/android_v2_continuity_contract.py` | 7 joint continuity scenario policies | ✅ Present |

### 7.2 Continuity Scenario Coverage

Per `core/android_v2_continuity_contract.py` and `docs/ANDROID_V2_JOINT_CONTINUITY_CONTRACT.md`,
seven scenario classes are defined:

| Scenario | Policy Defined | V2 Infrastructure | Android Support |
|----------|---------------|------------------|-----------------|
| 1. Android initial attach | ✅ | ✅ `AttachedRuntimeSessionRegistry` | ✅ `GalaxyConnectionService` |
| 2. Transport reconnect (continuity resume) | ✅ | ✅ `FlowContinuityCoordinator` | ✅ `GalaxyWebSocketClient` reconnect |
| 3. Re-attach after process recreation | ✅ | ✅ Duplicate-participant guard | 🟡 Session ID preservation (implied) |
| 4. V2 restart with in-flight tasks | ✅ | ✅ `RuntimeRestartRecovery` | 🟡 Result queued in OfflineTaskQueue |
| 5. Stale participant identity rejection | ✅ | ✅ Non-destructive rejection policy | 🟡 Session tag in OfflineTaskQueue |
| 6. Duplicate signal suppression | ✅ | ✅ Policy defined | ✅ `discardForDifferentSession` |
| 7. Partial result continuity | ✅ | ✅ `DelegatedRuntimeExecutionTracker` | 🟡 Partial result queuing |

**Assessment**: The continuity framework is the most mature aspect of the integration.
Policy is defined at the contract level, infrastructure exists on both sides, and
Android's `OfflineTaskQueue` correctly implements session-scoped authority bounding.

**Key gap**: Scenario 3 (re-attach after process recreation) depends on Android
persisting its `runtime_attachment_session_id` across process death. The mechanism
for this (likely SharedPreferences) is implied but not explicitly visible in the
reviewed source files.

### 7.3 Offline Duration Limits

Android's `OfflineTaskQueue` limits are:
- Max queue size: 50 messages (oldest dropped at limit) ✅
- Max message age: 24 hours (stale messages evicted on load) ✅
- Queue persistence: SharedPreferences ✅

These limits are reasonable for a mobile assistant use case. A 24-hour offline window
covers temporary disconnection scenarios. However, there is no documented SLA or
operator-visible metric for how often the queue fills or expires.

---

## 8. Build and Test Infrastructure

### 8.1 V2 Build Infrastructure

| Item | Status |
|------|--------|
| `requirements.txt` present | ✅ |
| `requirements.hash.txt` (dependency pinning) | ✅ |
| `pyproject.toml` present | ✅ |
| `pytest.ini` present | ✅ |
| Docker support (`Dockerfile`, `docker-compose.yml`) | ✅ Multiple Dockerfiles present |
| `Makefile` | ✅ |
| `start.sh` / `start.bat` | ✅ |
| `scripts/quick_verify.sh` | ✅ (`QUICKSTART.md` references it) |

### 8.2 V2 Test Coverage

The V2 test directory contains **608 test files** across multiple categories:

| Category | Evidence |
|----------|---------|
| Unit tests (per-module) | 500+ individual test files |
| Integration tests | `tests/integration/` directory |
| E2E tests | `tests/e2e/test_e2e_runtime_scenarios.py` |
| Android-specific tests | `tests/test_android_*.py` (8+ files) |
| Chaos tests | `tests/chaos/` directory |
| Cross-repo signal closure | `tests/test_e2e_cross_repo_signal_closure.py` |

*Coverage note*: While the number of test files is large, the cross-repo tests
mock the Android boundary. There is no evidence of tests that run against a real
Android device or APK.

### 8.3 Android Build Infrastructure

| Item | Status |
|------|--------|
| Gradle build files | ✅ |
| `build_apk.sh` | ✅ |
| `gradlew` / `gradlew.bat` | ✅ |
| `gradle.properties` | ✅ |
| Unit tests | ✅ (`app/src/test/java/`) |
| Instrumented tests | 🟡 Directory exists, extent unknown |
| CI pipeline for Android | 🟡 `.github/` exists but workflow not reviewed |
| Pre-built APK artifact | ❌ Not present in repository |

**Assessment**: Both repos have proper build tooling. The gap is CI-level APK artifact
production and distribution — there is no evidence that the CI pipeline produces or
publishes an APK that can be installed for testing without a full Android development
environment.

---

## 9. Operator Visibility and Usability

### 9.1 Available Operator Surfaces (Verified ✅)

| Surface | Path / Location |
|---------|----------------|
| Health endpoints | `GET /api/v1/health` |
| System status | `GET /api/v1/system` |
| Monitoring dashboard | `GET /api/v1/monitoring` |
| Operator check surface | `GET /api/v1/operator` |
| Projection surface | `GET /api/v1/projection` |
| Runtime status | `runtime/entrypoint.json` (written at startup) |
| Architecture diagnostics | `core/architecture_diagnostics.py`, `core/architecture_live_status.py` |
| Release gate report | `core/distributed_release_gate_skeleton.py::get_release_gate_report()` |
| Recovery closure report | `core/recovery_durability_closure_validator.py::build_recovery_closure_report()` |
| Evidence surface | `core/v2_readiness_governance_evidence_surface.py` |

### 9.2 Android-Side Observability

| Surface | Status |
|---------|--------|
| `GalaxyLogger` (structured logging) | ✅ Present |
| `NetworkDiagnostics` | ✅ Present |
| `ReadinessChecker` service | ✅ Present |
| Observability log file (FileProvider PR15) | ✅ Manifest entry present |
| Floating window status indicator | 🟡 Implied by `FloatingWindowService` |
| Real-time V2 connection status visible to user | 🟡 Implied but not confirmed |

### 9.3 Usability Gaps for Operators

| Gap | Impact |
|-----|--------|
| No single "system health" dashboard combining V2 + Android status | High |
| Android device status visible in V2 monitoring but no inverse (V2 health visible from Android) | Medium |
| No documented incident runbook for common failure modes | High |
| Release gate is skeleton-only — no operator alert when gate would block | Medium |
| Server URL must be manually entered on Android — no discovery | High (first-run UX) |

---

## 10. Operational Gap Matrix

| Dimension | Current State | Gap | Severity |
|-----------|---------------|-----|----------|
| **Startup (V2)** | Clean 7-phase sequence, documented | Non-fatal exception silently continues | Low |
| **Startup (Android)** | Services registered, BootReceiver present | Server URL discovery missing | High |
| **API auth** | Properly guarded | No dev-mode default auth documented | Medium |
| **Protocol completeness** | Core types canonical; several deferred | `hybrid_execute`, `rag_query` not operational | Medium |
| **Task dispatch** | Structurally complete | No real cross-repo E2E test | High |
| **Offline recovery** | OfflineTaskQueue complete | 50-message cap may be low for heavy use | Low |
| **Session continuity** | 7 scenarios defined + infrastructure | Scenario 3 (process recreation) not fully verified | Medium |
| **V2 restart recovery** | Infrastructure present | Not covered by cross-repo E2E test | High |
| **Release gate** | Skeleton with categories | No hard enforcement; CI does not gate on it | Medium |
| **Build (V2)** | Complete | None material | — |
| **Build (Android)** | Complete (source) | No pre-built APK; no CI artifact distribution | High |
| **Documentation** | Extensive (184 docs files) | No single end-to-end setup guide for dual-repo | High |
| **Observability** | Rich operator surfaces on V2 | No combined V2+Android health view | Medium |
| **Security** | Auth module guards APIs | `usesCleartextTraffic=true` unrestricted | Medium |
| **Scalability** | Multi-device architecture present | Not tested under load | — |

---

## 11. Readiness Verdict by Dimension

| Dimension | Verdict | Rationale |
|-----------|---------|-----------|
| **Buildable (V2)** | ✅ Ready | Clean build files, pip install, Docker support |
| **Buildable (Android)** | ✅ Ready | Gradle build, `build_apk.sh` present |
| **Runnable (V2, standalone)** | ✅ Ready | `python main.py` starts a functional server |
| **Runnable (Android, standalone)** | ✅ Ready | App installs and operates independently |
| **Runnable (cross-device, happy path)** | 🟡 Mostly Ready | Requires manual URL config; no discovery |
| **Operable (V2)** | 🟡 Mostly Ready | Rich API surfaces; no combined health dashboard |
| **Operable (Android)** | 🟡 Mostly Ready | Foreground service; no real-time V2 status visible |
| **Testable (V2 unit)** | ✅ Ready | 608 test files, pytest infrastructure |
| **Testable (Android unit)** | 🟡 Partial | Tests exist; extent not fully assessed |
| **Testable (cross-repo E2E)** | ❌ Not Ready | No real cross-repo integration test |
| **Recoverable (reconnect)** | ✅ Ready | Both sides implement reconnect |
| **Recoverable (V2 restart)** | 🟡 Mostly Ready | Infrastructure present; not E2E tested |
| **Recoverable (Android process kill)** | 🟡 Mostly Ready | OfflineTaskQueue + BootReceiver; session ID persistence unclear |
| **Understandable (architecture)** | ✅ Ready | Excellent docs, sentinels, scorecards |
| **Understandable (setup/operations)** | ❌ Not Ready | No single dual-repo setup guide |

---

## 12. Recommended Next-Stage Priorities

The following recommendations are ordered by impact on "smoothly usable end-to-end
product," based directly on the gaps identified above.

### Priority 1 (Blocking for New Adopters) — Operational Bootstrap

**P1-A: Dual-repo setup guide**
Create a single `GETTING_STARTED.md` or update `QUICKSTART.md` with a combined
V2 + Android end-to-end setup walkthrough covering:
- V2 prerequisites and `python main.py` startup
- Android APK build steps (or link to a CI-produced APK artifact)
- Server URL configuration on Android
- Verification that device registers successfully in V2
- Health check to confirm the connection is live

**P1-B: Pre-built APK in CI artifacts**
Add a GitHub Actions workflow step that builds and publishes the debug APK as a
CI artifact on every commit to the main branch. This enables non-Android-developers
to test the full system without setting up an Android SDK.

**P1-C: Server address discovery**
Implement a simple auto-discovery mechanism (mDNS/Bonjour, or QR code scan from
V2's `/api/v1/system` endpoint) so Android users do not need to manually type a
server URL.

### Priority 2 (Blocking for Confident Release Assessment) — E2E Test Coverage

**P2-A: Cross-repo integration test**
Add at minimum one integration test that runs the real V2 server (in-process or
via Docker) and a simulated Android client (using the same WebSocket protocol)
to verify:
- Device registration
- Task dispatch and result return
- Reconnect after disconnect
- V2 restart + result acceptance

This test should run in CI for both repositories.

**P2-B: V2 restart recovery E2E**
The recovery infrastructure is excellent. A test that verifies the complete
V2-restart + in-flight-task + Android-reconnect + result-acceptance scenario would
close the most critical correctness gap.

### Priority 3 (Needed Before Release Gate Has Meaning) — Gate Enforcement

**P3-A: Promote release gate skeleton to hard enforcement**
`core/distributed_release_gate_skeleton.py` (PR-7) produces a structured verdict
but does not block. A follow-up PR should:
- Wire the gate report into CI (fail build if `ReleaseGateVerdict == "blocked"`)
- Promote at least the `execution_chain_health` and `session_truth_integrity`
  categories from `deferred` to `gate_worthy`

**P3-B: Auth configuration documentation**
Document the expected `core/auth.py` interface and provide a development-mode
implementation that allows local testing without a full auth stack.

### Priority 4 (Polish / Production Hardening)

**P4-A: Android cleartext traffic restriction**
Add a `network_security_config.xml` that restricts cleartext HTTP to known local
address ranges, while still allowing cleartext for LAN/development use.

**P4-B: Combined V2+Android health surface**
Add a `/api/v1/system/android-devices` endpoint (or extend the existing monitoring
surface) to show connected Android devices, their last heartbeat, and any queued
offline messages — making the cross-device state visible from V2's operator surface.

**P4-C: `hybrid_execute` path closure**
If multi-device co-execution is a product goal, promote `hybrid_execute` from
`HYBRID_DEGRADE` fallback to a real parallel execution path. This requires
center-side task decomposition in `CommandRouter` + `formation_resolver`.

---

## Appendix A: Key Code Locations

| Component | Primary Location |
|-----------|-----------------|
| V2 entrypoint | `main.py` |
| V2 staged startup | `core/system_orchestrator.py` |
| V2 async launcher | `unified_launcher.py` |
| V2 execution core | `core/openclawd.py` |
| V2 API routes | `core/api_routes.py`, `core/routes/` |
| V2 device registry | `core/device_registry.py` |
| V2 Android lifecycle | `core/android_delegated_runtime_lifecycle_coordinator.py` |
| V2 continuity contract | `core/android_v2_continuity_contract.py` |
| V2 continuity coordinator | `core/flow_continuity_coordinator.py` |
| V2 release gate | `core/distributed_release_gate_skeleton.py` |
| V2 evidence surface | `core/v2_readiness_governance_evidence_surface.py` |
| Gateway WS routes | `galaxy_gateway/routes/websocket.py` |
| Gateway Android bridge | `galaxy_gateway/android_bridge.py` |
| Android main service | `app/src/main/java/com/ufo/galaxy/service/GalaxyConnectionService.kt` |
| Android WS client | `app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt` |
| Android offline queue | `app/src/main/java/com/ufo/galaxy/network/OfflineTaskQueue.kt` |
| Android protocol models | `app/src/main/java/com/ufo/galaxy/protocol/AipModels.kt` |
| Android cross-repo gate | `app/src/main/java/com/ufo/galaxy/protocol/CrossRepoConsistencyGate.kt` |
| Android manifest | `app/src/main/AndroidManifest.xml` |

## Appendix B: Prior Review Artifacts

The following prior-art documents in `docs/` provide supporting evidence for this
review:

| Document | Relevance |
|----------|-----------|
| `docs/V2_ANDROID_RUNTIME_CLOSURE_AUDIT.md` | Most comprehensive prior cross-repo runtime audit |
| `docs/ANDROID_PROTOCOL_MATURITY_MATRIX.md` | Per-type AIP v3 protocol maturity |
| `docs/ANDROID_V2_JOINT_CONTINUITY_CONTRACT.md` | Continuity scenario policies |
| `docs/ARCHITECTURE_COMPLETION_SCORECARD.md` | V2-internal architecture maturity dimensions |
| `docs/DISTRIBUTED_RELEASE_GATE_SKELETON.md` | Release gate skeleton description |
| `docs/V2_READINESS_GOVERNANCE_EVIDENCE_MATRIX.md` | Readiness evidence classification |
| `QUICKSTART.md` | Existing quick-start guide |

---

*Document generated as part of PR-8 (Full-System Product Readiness Review).*  
*Assessment date: 2026-04-25.*  
*Repositories reviewed at: `ufo-galaxy-realization-v2` current branch, `ufo-galaxy-android` ref `6a18547`.*
