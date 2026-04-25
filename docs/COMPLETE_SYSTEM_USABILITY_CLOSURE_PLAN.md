# V2 PR-9: Complete-System Usability Closure Plan

> **Document type**: Canonical V2-side complete-system usability closure plan.
>
> **Supersedes**: PR #825 (previous V2 PR-9 attempt).
>
> **Primary repository**: `DannyFish-11/ufo-galaxy-realization-v2`
> **Companion repository**: `DannyFish-11/ufo-galaxy-android`
>
> **Purpose**: Translate the code-grounded dual-repo full-system review (PR-8 and
> prior audit artifacts) into a structured, reviewer-actionable closure plan that
> can be incrementally updated as real closure happens in follow-up PRs.
>
> **Evidence classification used throughout**:
> - ✅ **Verified** — directly confirmed in repository source, tests, or prior
>   review artifacts; code references provided.
> - 🟡 **Partial** — structural code exists but path is not fully wired,
>   operationally smooth, or end-to-end tested.
> - ❌ **Missing / Blocked** — no code evidence found, path is broken, or gap
>   explicitly blocks usability.

---

## Table of Contents

1. [Purpose and Scope](#1-purpose-and-scope)
2. [System Model Reference](#2-system-model-reference)
3. [Dimension 1 — Buildability / Startup Closure](#3-dimension-1--buildability--startup-closure)
4. [Dimension 2 — Backend Orchestration Closure](#4-dimension-2--backend-orchestration-closure)
5. [Dimension 3 — Android Participant / Runtime Closure](#5-dimension-3--android-participant--runtime-closure)
6. [Dimension 4 — Cross-Repo Integration Closure](#6-dimension-4--cross-repo-integration-closure)
7. [Dimension 5 — Truth / Reconciliation Closure](#7-dimension-5--truth--reconciliation-closure)
8. [Dimension 6 — Offline / Replay / Recovery Closure](#8-dimension-6--offline--replay--recovery-closure)
9. [Dimension 7 — Operator / Observability / Reviewability Closure](#9-dimension-7--operator--observability--reviewability-closure)
10. [Dimension 8 — Readiness / Release / Governance Closure](#10-dimension-8--readiness--release--governance-closure)
11. [System Usability Matrix Summary](#11-system-usability-matrix-summary)
12. [Follow-Up Track Map](#12-follow-up-track-map)
13. [Evidence and Prior Artifact Index](#13-evidence-and-prior-artifact-index)

---

## 1. Purpose and Scope

### 1.1 What this document is

This is the canonical V2-side record of where the dual-repo Galaxy system stands
against the requirements for it to be a **complete, runnable, smooth, and usable
product**. It does not claim the system is already fully usable. It maps each
closure dimension to the real codebase, classifies current state as verified /
partial / missing, and structures the remaining work into reviewer-actionable
follow-up tracks.

### 1.2 What "complete, runnable, smooth, usable" means here

For this system, full usability requires:

1. A new operator can install, start, and verify V2 from a fresh clone without
   needing undocumented tribal knowledge.
2. An Android device can join as a runtime participant with a documented workflow.
3. Commands sent from V2 are received, executed, and result-returned on Android.
4. V2 and Android can survive disconnects, reboots, and partial failures and
   resume correct operation.
5. An operator can observe system state, diagnose issues, and understand what
   the system is doing without source-diving.
6. There is a release gate that gives a trustworthy signal before deployment.

### 1.3 Relationship to Prior Work

| Artifact | Role |
|----------|------|
| `docs/SYSTEM_READINESS_REVIEW_PR8.md` | Full-system product readiness assessment (PR-8, primary evidence source for this plan) |
| `docs/V2_ANDROID_RUNTIME_CLOSURE_AUDIT.md` | Runtime closure audit for the distributed V2+Android pair |
| `docs/SYSTEM_AUDIT_REPORT_ZH.md` | Chinese-language dual-repo systematic review |
| `docs/RESIDUAL_GAP_MAP.md` | Machine-readable residual gap catalog from PR-512 |
| `core/runtime_closure_audit.py` | Programmatic gap registry (`_KNOWN_RESIDUAL_GAPS`) |
| `core/distributed_release_gate_skeleton.py` | Release gate verdict (skeleton, no hard enforcement yet) |
| `core/v2_readiness_governance_evidence_surface.py` | Readiness evidence surface (PR-7) |

This plan is the synthesis layer: it converts the findings from all the above
into a single structured closure reference that future PRs can update.

---

## 2. System Model Reference

### 2.1 Canonical Authority Chain

```
main.py                              ← single canonical entrypoint (never bypassed)
  └─ core/system_orchestrator.py     ← 7-phase staged pre-flight
       └─ unified_launcher.py        ← subordinate async service launch
            ├─ DesktopPresenceRuntime  ← session/lifecycle owner (Windows-first)
            │    └─ OpenClawd           ← cognition + execution decision core
            │         ├─ local path     ← Windows/System API execution
            │         └─ cross-device   ← CommandRouter → SourceDispatchOrchestrator
            │                                → AndroidBridge → DeviceRouter
            └─ galaxy_gateway (FastAPI, port 9000)
                 └─ /ws/device/{device_id}  ← AIP v3 canonical WebSocket
                      └─ AndroidBridge      ← Android-specific protocol adapter
```

*Code references*: `main.py`, `core/system_orchestrator.py`, `unified_launcher.py`,
`core/openclawd.py`, `galaxy_gateway/routes/websocket.py`,
`galaxy_gateway/android_bridge.py`

### 2.2 Repository Role Split

| Repository | Role | Language |
|------------|------|----------|
| `ufo-galaxy-realization-v2` | V2 control plane — orchestration authority, API gateway, dispatch spine, truth/projection | Python (FastAPI, asyncio) |
| `ufo-galaxy-android` | Android device runtime — on-device execution, result uplink, offline queue, floating UI | Kotlin (Android SDK) |

V2 is the single center of authority. Android is a routable execution participant.
V2 runs without Android; Android cannot operate usefully without V2.

---

## 3. Dimension 1 — Buildability / Startup Closure

> **Closure question**: Can a new operator build, install, and start the full
> system from a fresh clone without needing tribal knowledge?

### 3.1 V2 Build / Install Path

| Item | Status | Code Reference |
|------|--------|----------------|
| `requirements.txt` present and pinned | ✅ Verified | `requirements.txt`, `requirements.in`, `requirements.hash.txt` |
| `python main.py` is canonical entrypoint | ✅ Verified | `main.py:104–158` |
| 7-phase staged startup with non-fatal exception path | ✅ Verified | `core/system_orchestrator.py:61–80` |
| Port defaults documented (`9000`) | ✅ Verified | `config.json:2`, `config/unified_ports.yaml` |
| `--setup` wizard for first-run configuration | ✅ Verified | `main.py:118–123`, `setup_wizard.py` |
| Docker / Compose deployment path | ✅ Verified | `Dockerfile`, `docker-compose.yml` |
| Windows-specific startup script | ✅ Verified | `start.bat`, `start.sh` |
| Development prerequisites documented | 🟡 Partial | `README.md`, `QUICKSTART.md` — exist but lack a single end-to-end runbook |
| Auth (`core/auth.py`) setup documented | ❌ Missing | Auth module must be present; no default-open dev mode or documented stub |
| NATS/Redis optional-dependency behavior documented | 🟡 Partial | Optional per config but no "minimal-mode" startup guide |

**Key blocker (D1-B1)**: A new operator who clones V2 and runs `python main.py`
without a configured `core/auth.py` will receive HTTP 401 on all guarded routes.
No documented stub, bypass, or development-mode auth path exists.

*Reference*: `core/api_routes.py:70–79`, `docs/SYSTEM_READINESS_REVIEW_PR8.md §3.2`

### 3.2 Android Build / Install Path

| Item | Status | Code Reference |
|------|--------|----------------|
| Gradle build files present | ✅ Verified | `build.gradle`, `app/build.gradle`, `settings.gradle` (android repo) |
| Build script present | ✅ Verified | `build_apk.sh` (android repo) |
| Kotlin source compilable | ✅ Verified | `app/src/main/java/com/ufo/galaxy/` |
| Pre-built APK distributed | ❌ Missing | No CI artifact, no release APK |
| CI workflow produces debug APK artifact | ❌ Missing | No automated APK publication |
| Server URL discovery (auto or QR) | ❌ Missing | URL must be manually typed; no mDNS/QR |

**Key blocker (D1-B2)**: Android participants cannot join the system without
building the APK from source. No distribution channel or CI artifact exists.

### 3.3 Combined Startup Runbook

| Item | Status |
|------|--------|
| Single document covering: V2 prerequisites → `python main.py` → Android APK build → server URL config → device registration verification → health check | ❌ Missing |

**Key blocker (D1-B3)**: No single end-to-end "clone to running system" walkthrough
exists. The closest approximation requires reading `README.md`, `QUICKSTART.md`,
`L4_QUICK_START_GUIDE.md`, and `docs/CLONE_TO_USE_REALITY.md` independently.

### 3.4 Dimension 1 Closure Summary

| Sub-area | Status | Priority |
|----------|--------|----------|
| V2 Python build / install | ✅ Verified | — |
| V2 staged startup | ✅ Verified | — |
| V2 auth setup path | ❌ Missing | P0 |
| Android APK build | 🟡 Partial (manual only) | P1 |
| Android APK distribution (CI artifact) | ❌ Missing | P1 |
| End-to-end startup runbook | ❌ Missing | P0 |
| Server URL auto-discovery | ❌ Missing | P2 |

---

## 4. Dimension 2 — Backend Orchestration Closure

> **Closure question**: Does the V2 backend orchestration spine run completely
> and correctly, including all canonical execution paths?

### 4.1 Local Execution Path

| Item | Status | Code Reference |
|------|--------|----------------|
| `main.py → SystemOrchestrator → DesktopPresenceRuntime → OpenClawd` chain | ✅ Verified | `main.py`, `core/system_orchestrator.py`, `core/openclawd.py` |
| Local Windows/System API execution | ✅ Verified | `core/openclawd.py:8–35` |
| `CommandRouter.route_envelope()` as sole legal dispatcher | ✅ Verified | `core/command_router.py` |
| `SourceDispatchOrchestrator` as canonical dispatch brain | ✅ Verified | `core/source_dispatch_orchestrator.py` |
| Task ingress front-loading `CanonicalTask` at API boundary | ✅ Verified | `core/routes/tasks.py` (PR-507) |
| `TaskExecutionRecord` written to `ReplayFoundation` on API ingress | ❌ Missing (GAP-512-001) | `core/routes/tasks.py` — audit lineage gap |
| Scheduler relay/mesh paths register tasks in `TaskGraphRuntime` before dispatch | ❌ Missing (GAP-512-002) | `core/scheduler.py` |
| `CommandRouter` calls `query_routable_executors()` before dispatch | ❌ Missing (GAP-512-004) | `core/capability_network_runtime_policy.py` |
| Task cancellation propagated correctly to `CommandRouter` | ❌ Missing | `task_cancel` only logs; does not propagate to `CommandRouter` |
| `task_status` propagated to `CommandRouter` | ❌ Missing | Same gap as `task_cancel` |

**Key blocker (D2-B1)**: `task_cancel` and `task_status` signals do not propagate
correctly to `CommandRouter`. Cancellation of in-flight tasks is unreliable.

*Reference*: `docs/SYSTEM_AUDIT_REPORT_ZH.md §6.2`,
`docs/RESIDUAL_GAP_MAP.md`, `core/runtime_closure_audit.py`

### 4.2 Cross-Device Execution Path

| Item | Status | Code Reference |
|------|--------|----------------|
| `SourceDispatchOrchestrator._try_android_bridge_dispatch()` | ✅ Verified | `core/source_dispatch_orchestrator.py` |
| `AndroidBridge.assign_task()` wired to `DeviceRouter.dispatch_task()` | ✅ Verified | `galaxy_gateway/android_bridge.py`, `core/device_router.py` |
| `DeviceRouter` strategy remnants causing ambiguous dispatch | 🟡 Partial | Legacy policy remnants in `DeviceRouter` (P1 clean-up) |
| `hybrid_execute` co-execution path | 🟡 Partial (HYBRID_DEGRADE fallback only) | `core/command_router.py`, Android `AgentMessageHandler` |
| Multi-device mesh session coordination | 🟡 Partial | `core/multi_device_coordination_authority.py` present; operational state unclear |

### 4.3 Cognition / Intent Pipeline

| Item | Status | Code Reference |
|------|--------|----------------|
| `ContinuumOrchestrator` intent recognition | ✅ Verified | `core/continuum/` |
| `OpenClawd` LLM routing | ✅ Verified | `core/openclawd.py` |
| Multi-LLM model routing governance | ✅ Verified | `core/model_routing_authority.py` (PR-7) |
| `rag_query` cross-device path operational | ❌ Missing | Protocol type exists; no runtime consumer verified |

### 4.4 Dimension 2 Closure Summary

| Sub-area | Status | Priority |
|----------|--------|----------|
| Local execution spine | ✅ Verified | — |
| Task ingress canonicalization | ✅ Verified | — |
| `task_cancel` / `task_status` propagation | ❌ Missing | P0 |
| Audit lineage on API-ingressed tasks | ❌ Missing (GAP-512-001) | P1 |
| Scheduler mesh task graph registration | ❌ Missing (GAP-512-002) | P1 |
| Capability-aware dispatch routing | ❌ Missing (GAP-512-004) | P1 |
| `hybrid_execute` real path | 🟡 Partial | P2 |
| `rag_query` cross-device path | ❌ Missing | P2 |
| `DeviceRouter` strategy clean-up | 🟡 Partial | P1 |

---

## 5. Dimension 3 — Android Participant / Runtime Closure

> **Closure question**: Can an Android device join as a fully operational runtime
> participant, receive tasks, execute them, and return results reliably?

### 5.1 Android Core Service Layer

| Item | Status | Code Reference |
|------|--------|----------------|
| `GalaxyConnectionService` foreground service lifecycle | ✅ Verified | `GalaxyConnectionService.kt`, `AndroidManifest.xml` |
| WebSocket connection + reconnect logic | ✅ Verified | `GalaxyWebSocketClient.kt` |
| AIP v3 protocol model | ✅ Verified | `AipModels.kt` |
| `OfflineTaskQueue` (FIFO, 50-cap, 24hr TTL, SharedPreferences) | ✅ Verified | `OfflineTaskQueue.kt` |
| Boot auto-start via `BootReceiver` | ✅ Verified | `BootReceiver.kt`, `AndroidManifest.xml` |
| Voice recognition service | ✅ Verified | `VoiceRecognitionService.kt` |
| Floating window / enhanced floating service | ✅ Verified | `FloatingWindowService.kt`, `EnhancedFloatingService.kt` |
| Hardware key trigger (accessibility service) | ✅ Verified | `HardwareKeyListener.kt` |
| Cleartext traffic allowed (dev/LAN) | ✅ Verified (with caveats) | `AndroidManifest.xml` — `usesCleartextTraffic="true"` |
| Network security config restricting cleartext to LAN | ❌ Missing | No `network_security_config.xml` scoped restriction |

### 5.2 Android Protocol Path

| AIP v3 Type | Status | Code Reference |
|-------------|--------|----------------|
| `device_register` (C→S) | ✅ Verified | `GalaxyConnectionService` → V2 `handle_device_register()` |
| `heartbeat` (C→S) | ✅ Verified | `GalaxyWebSocketClient` → V2 `handle_heartbeat()` |
| `task_assign` (S→C) | ✅ Verified | V2 `MessageBuilder` → `GalaxyConnectionService` |
| `task_result` (C→S) | ✅ Verified | `GalaxyConnectionService` → V2 `handle_task_result()` |
| `task_execute` (C↔S) | ✅ Verified | Bidirectional |
| `gui_click/swipe/input` (S→C) | ✅ Verified | V2 AIPMessage → Android accessibility layer |
| `action_execute` (S→C) | ✅ Verified | V2 `_handle_forward_log` → `AgentMessageHandler` |
| `hybrid_execute` (S→C) | 🟡 Partial | Receives but falls back to `HYBRID_DEGRADE` |
| `rag_query` (C↔S) | ❌ Missing | No confirmed runtime consumer on either side |
| `takeover_response` (C→S) | 🟡 Partial | Android sends; V2 `on_takeover_response()` receives |
| `reconciliation_signal` (C→S) | 🟡 Partial | Android sends; V2 `on_reconciliation_signal()` receives |
| `handoff_v2_response` (S→C) | 🟡 Partial | V2 ingress exists; Android receipt path not verified |

### 5.3 Android Runtime Host Classification

| Item | Status | Code Reference |
|------|--------|----------------|
| Android classified as `DEVICE_RUNTIME_HOST` (not V2 backend host) | ✅ Verified | `core/android_runtime_host.py:54–76` |
| Participant admission gates evaluated before dispatch | ✅ Verified | `docs/V2_ANDROID_RUNTIME_CLOSURE_AUDIT.md §4` |
| Capability negotiation on registration | ✅ Verified | `core/capability_registry.py`, `core/device_registry.py` |

### 5.4 Dimension 3 Closure Summary

| Sub-area | Status | Priority |
|----------|--------|----------|
| Core Android service lifecycle | ✅ Verified | — |
| WebSocket connection + reconnect | ✅ Verified | — |
| Canonical AIP v3 protocol types | ✅ Verified | — |
| `hybrid_execute` real path on Android | 🟡 Partial | P2 |
| `rag_query` Android path | ❌ Missing | P2 |
| `handoff_v2_response` Android receipt | 🟡 Partial | P2 |
| Network security config (cleartext scoping) | ❌ Missing | P1 (security) |
| APK distribution / CI artifact | ❌ Missing | P1 |

---

## 6. Dimension 4 — Cross-Repo Integration Closure

> **Closure question**: Are V2 and Android integrated in a way that is correct,
> maintained, and operationally testable across repository boundaries?

### 6.1 Structural Integration (Both Repos)

| Item | Status | Code Reference |
|------|--------|----------------|
| V2-side cross-repo consistency gates | ✅ Verified | `core/cross_repo_consistency_gates.py`, `core/cross_repo_contract_finalization.py`, `core/cross_repo_protocol_consistency.py` |
| Android-side cross-repo consistency gate | ✅ Verified | `CrossRepoConsistencyGate.kt`, `UgcpProtocolConsistencyRules.kt`, `UgcpSharedSchemaAlignment.kt` |
| UGCP shared protocol schema alignment | ✅ Verified | `UgcpSharedSchemaAlignment.kt` (android repo), `docs/ANDROID_PROTOCOL_MATURITY_MATRIX.md` |
| Android session layer contracts | ✅ Verified | `AndroidSessionLayerContracts.kt` |
| V2 Android lifecycle coordinator (façade) | ✅ Verified | `core/android_delegated_runtime_lifecycle_coordinator.py` |
| V2–Android continuity contract (7 scenario classes) | ✅ Verified | `core/android_v2_continuity_contract.py` |

### 6.2 Cross-Repo Testing Gap

| Item | Status | Notes |
|------|--------|-------|
| V2 integration tests mock Android (no real WS) | 🟡 Partial | V2 tests verify V2 side; Android side is mocked |
| Android unit tests mock V2 | 🟡 Partial | Android tests verify Android logic; V2 side is mocked |
| End-to-end integration test spanning both repos | ❌ Missing | No test verifies the real V2 server + real WS protocol together |
| CI workflow that exercises device_register + task_dispatch + result_return | ❌ Missing | Neither repo has such a workflow |
| Reconnect recovery integration test | ❌ Missing | Critical for production confidence |

**Key blocker (D4-B1)**: No automated test validates the actual cross-repo
integration contract. Protocol divergence could be introduced by either repo
without detection until manual testing.

### 6.3 Schema / Contract Governance

| Item | Status |
|------|--------|
| Protocol schema managed manually in `UgcpSharedSchemaAlignment.kt` | 🟡 Partial |
| No shared schema generation tooling | ❌ Missing |
| No contract-compatibility CI check between repos | ❌ Missing |

### 6.4 Dimension 4 Closure Summary

| Sub-area | Status | Priority |
|----------|--------|----------|
| Cross-repo structural consistency enforcement | ✅ Verified | — |
| V2 continuity contract | ✅ Verified | — |
| End-to-end cross-repo integration test | ❌ Missing | P0 |
| Cross-repo CI workflow | ❌ Missing | P1 |
| Shared schema generation tooling | ❌ Missing | P2 |
| Contract-compatibility CI check | ❌ Missing | P2 |

---

## 7. Dimension 5 — Truth / Reconciliation Closure

> **Closure question**: Is there a single authoritative truth source for system
> state, task state, and participant state, and are reconciliation paths closed?

### 7.1 V2-Side Truth Architecture

| Item | Status | Code Reference |
|------|--------|----------------|
| `UnifiedDeviceManager` (UDM) as canonical device write SSOT | ✅ Verified | `core/device_registry.py:1–57` |
| `DeviceRegistry` as compatibility/indexing layer (read-only pass-through) | ✅ Verified | `core/device_registry.py:80+` |
| `CanonicalTask` adaptation at all API ingress points | ✅ Verified | `core/routes/tasks.py`, `adapt_to_canonical_task()` (PR-507) |
| `TaskGraphRuntime` as task graph truth | ✅ Verified | `core/task_graph_runtime.py` (PR-508) |
| `ReplayFoundation` as replay/audit truth | ✅ Verified | `core/replay_foundation.py` |
| `OperatorSurface` as operator inspection truth | ✅ Verified | `core/operator_surface.py` (PR-510) |
| Conflict CONFLICT-001 resolved (task_status / task_identity) | ✅ Verified | PR-507, `docs/RESIDUAL_GAP_MAP.md §Resolved` |
| Conflict CONFLICT-004 resolved (operator inspection truth) | ✅ Verified | PR-510, `docs/RESIDUAL_GAP_MAP.md §Resolved` |
| Conflict CONFLICT-005 resolved (replay/audit truth) | ✅ Verified | PR-506, `docs/RESIDUAL_GAP_MAP.md §Resolved` |
| Conflict CONFLICT-002 open (network topology truth) | ❌ Open | `NetworkTopologyRuntime` vs `ContinuumState/TopologyRoutePlan` — PR-514 target |
| Conflict CONFLICT-003 open (executor readiness truth) | ❌ Open | `CapabilityAssimilationLayer` vs `CapabilityRegistry` — PR-513 target |
| `TaskExecutionRecord` written on API-ingressed tasks | ❌ Missing (GAP-512-001) | Audit lineage incomplete for API ingress path |
| Scheduler mesh tasks registered in `TaskGraphRuntime` | ❌ Missing (GAP-512-002) | Gap between PR-508 and scheduler relay/mesh paths |

### 7.2 Android ↔ V2 Reconciliation

| Item | Status | Code Reference |
|------|--------|----------------|
| `AndroidExecutionSignalReconciler` | ✅ Verified | `core/android_execution_signal_reconciler.py` |
| `AndroidParticipantTruthIngress` | ✅ Verified | `core/android_participant_truth_ingress.py` |
| `ReconcileAndroidExecutionSignal` | ✅ Verified | `galaxy_gateway/android_bridge.py` |
| `reconciliation_signal` sent by Android | 🟡 Partial | Android side sends; V2 `on_reconciliation_signal()` receives; downstream processing not fully verified |
| Parallel truth reconciliation paths resolved (CONFLICT-001, -004, -005) | ✅ Verified | `docs/RESIDUAL_GAP_MAP.md §Resolved` |
| Model/provider routing truth (`ContinuumState` vs dedicated authority) | ❌ Open (GAP-512-009) | No canonical `NetworkTopologyRuntime`-equivalent for model/provider domain — PR-515 target |

### 7.3 Dimension 5 Closure Summary

| Sub-area | Status | Priority |
|----------|--------|----------|
| Device SSOT (UDM) | ✅ Verified | — |
| Task canonical adaptation at ingress | ✅ Verified | — |
| Task graph truth (`TaskGraphRuntime`) | ✅ Verified | — |
| Replay/audit truth (`ReplayFoundation`) | ✅ Verified | — |
| Operator inspection truth (`OperatorSurface`) | ✅ Verified | — |
| Parallel truth conflicts CONFLICT-001/004/005 | ✅ Resolved | — |
| Network topology truth conflict (CONFLICT-002) | ❌ Open | P1 (PR-514) |
| Executor readiness truth conflict (CONFLICT-003) | ❌ Open | P1 (PR-513) |
| API ingress audit lineage (GAP-512-001) | ❌ Missing | P1 (PR-513) |
| Scheduler mesh task graph registration (GAP-512-002) | ❌ Missing | P1 (PR-513) |
| Model/provider routing truth (GAP-512-009) | ❌ Open | P2 (PR-515) |
| Android reconciliation signal downstream processing | 🟡 Partial | P1 |

---

## 8. Dimension 6 — Offline / Replay / Recovery Closure

> **Closure question**: Can the system survive disconnects, V2 restarts, and
> Android reboots, and resume correct operation with no data loss?

### 8.1 Android Offline Capability

| Item | Status | Code Reference |
|------|--------|----------------|
| `OfflineTaskQueue` FIFO, 50-message cap | ✅ Verified | `OfflineTaskQueue.kt` |
| 24-hour TTL with stale message eviction on load | ✅ Verified | `OfflineTaskQueue.kt` |
| SharedPreferences persistence (survives process death) | ✅ Verified | `OfflineTaskQueue.kt` |
| Session-scoped authority bounding (`discardForDifferentSession`) | ✅ Verified | `OfflineTaskQueue.kt` |
| Queue flush on reconnect | ✅ Verified | `GalaxyWebSocketClient.kt` reconnect path |
| Queue replay ordering guarantees | 🟡 Partial | FIFO ordering verified; cross-session ordering semantics not fully documented |

### 8.2 V2 Recovery Infrastructure

| Item | Status | Code Reference |
|------|--------|----------------|
| `RecoveryDurabilityClosureValidator` (cross-module recovery matrix) | ✅ Verified | `core/recovery_durability_closure_validator.py` |
| `FlowContinuityCoordinator` (continuity decision entry point) | ✅ Verified | `core/flow_continuity_coordinator.py` |
| V2–Android continuity contract (7 scenario classes) | ✅ Verified | `core/android_v2_continuity_contract.py` |
| `DurableRuntimeSessionSnapshot` (session state durability) | ✅ Verified | `core/durable_runtime_session_snapshot.py` |
| `TakeoverTracking` (session ownership handoff) | ✅ Verified | `core/takeover_tracking.py` |
| V2 restart + in-flight task + Android reconnect + result acceptance scenario | 🟡 Partial | Infrastructure is present; no automated test verifies the full scenario |
| V2 restart recovery E2E test | ❌ Missing | Critical correctness gap for production confidence |

### 8.3 Replay / Audit Infrastructure

| Item | Status | Code Reference |
|------|--------|----------------|
| `ReplayFoundation` as replay/audit truth | ✅ Verified | `core/replay_foundation.py` |
| `OperatorSurfaceReplayFoundation` | ✅ Verified | `core/operator_surface_replay_foundation.py` |
| All writes routed through `CommandRouter.route_envelope()` | ✅ Verified (CONFLICT-005 resolved) | PR-506 |
| Replay coverage of API-ingressed tasks | ❌ Missing (GAP-512-001) | `TaskExecutionRecord` not written for API-ingressed tasks |
| Distributed task merge/recovery (`DistributedTaskMergeRecovery`) | 🟡 Partial | Module exists; operational completeness unclear |

### 8.4 Dimension 6 Closure Summary

| Sub-area | Status | Priority |
|----------|--------|----------|
| Android offline queue (FIFO, TTL, persistence, session scoping) | ✅ Verified | — |
| V2 recovery infrastructure (continuity contract, durability) | ✅ Verified | — |
| Replay/audit write path | ✅ Verified | — |
| V2 restart E2E recovery test | ❌ Missing | P0 |
| API ingress replay coverage (GAP-512-001) | ❌ Missing | P1 |
| Distributed task merge/recovery operational state | 🟡 Partial | P1 |
| Cross-session queue ordering semantics | 🟡 Partial | P2 |

---

## 9. Dimension 7 — Operator / Observability / Reviewability Closure

> **Closure question**: Can an operator understand what the system is doing,
> diagnose issues, and verify correctness without diving into source code?

### 9.1 V2 Operator Surface

| Item | Status | Code Reference |
|------|--------|----------------|
| `OperatorSurface` as canonical operator inspection truth | ✅ Verified | `core/operator_surface.py` (PR-510) |
| `/api/v1/operator` route reads only from `OperatorSurface` | ✅ Verified | `core/routes/operator.py` (CONFLICT-004 resolved) |
| `V2ReadinessGovernanceEvidenceSurface` | ✅ Verified | `core/v2_readiness_governance_evidence_surface.py` |
| Status board surface (desktop) | ✅ Verified | `desktop_projection/status_board_v2.py` |
| NATS-based observability | ✅ Verified | `core/nats_*` modules |
| SLO observability surface | 🟡 Partial | `docs/SLO_OBSERVABILITY.md` documented; runtime implementation state unclear |
| Status board does not consume `OperatorSurface` snapshot | ❌ Missing (GAP-512-005) | Still assembles its own runtime view — PR-514 target |
| `ProjectionSurfaceBridge` consumed by all projection endpoints | ❌ Missing (GAP-512-003) | Bridge wired but not consumed by all endpoints — PR-514 target |
| Combined V2+Android health endpoint | ❌ Missing | No single endpoint shows connected Android devices + last heartbeat + queue state |
| `AgentKernel` emits `TASK_ADMITTED` audit event | ❌ Missing (GAP-512-007) | Audit event gap in `core/agent/kernel.py` |
| `TaskOrchestrator` emits audit event after orchestration handoff | ❌ Missing (GAP-512-006) | Audit gap in `galaxy_gateway/orchestrator/task_orchestrator.py` |

### 9.2 Android Observability from V2

| Item | Status |
|------|--------|
| Connected Android devices visible in V2 health/monitoring surface | 🟡 Partial — `/api/v1/monitoring` exists but no dedicated Android view |
| Per-device last heartbeat visible to operator | 🟡 Partial |
| Per-device offline queue depth visible to operator | ❌ Missing |
| Per-device in-flight task state visible to operator | ❌ Missing |

**Key improvement (D7-I1)**: A single `/api/v1/system/android-devices` endpoint
(or extension of the monitoring surface) would give operators a usable cross-device
state view without source-diving.

### 9.3 Reviewability / Evidence Surfaces

| Item | Status | Code Reference |
|------|--------|----------------|
| `RuntimeClosureAudit` programmatic gap registry | ✅ Verified | `core/runtime_closure_audit.py` |
| `describe_contract_closure()` operator introspection function | ✅ Verified | `core/contract_closure.py:326–353` |
| `docs/RESIDUAL_GAP_MAP.md` human-readable gap catalog | ✅ Verified | `docs/RESIDUAL_GAP_MAP.md` |
| Test coverage for gap catalog entries | ✅ Verified | `tests/test_pr512_runtime_closure_audit.py` |
| Acceptance report cross-referencing U1–U33 criteria | ✅ Verified | `docs/acceptance/u1_u33_final_acceptance.md` |

### 9.4 Dimension 7 Closure Summary

| Sub-area | Status | Priority |
|----------|--------|----------|
| `OperatorSurface` as canonical truth | ✅ Verified | — |
| Status board and observability surface | ✅ Verified (partial) | — |
| Programmatic gap registry + evidence surfaces | ✅ Verified | — |
| Status board consuming `OperatorSurface` snapshot (GAP-512-005) | ❌ Missing | P1 (PR-514) |
| `ProjectionSurfaceBridge` consumed by all endpoints (GAP-512-003) | ❌ Missing | P1 (PR-514) |
| Combined V2+Android health endpoint | ❌ Missing | P1 |
| Per-device offline queue depth visible to operator | ❌ Missing | P1 |
| Audit events from `AgentKernel` and `TaskOrchestrator` (GAP-512-006/007) | ❌ Missing | P1 |

---

## 10. Dimension 8 — Readiness / Release / Governance Closure

> **Closure question**: Is there a trustworthy, enforced gate that determines
> whether the system is ready for a given deployment stage?

### 10.1 Release Gate State

| Item | Status | Code Reference |
|------|--------|----------------|
| `DistributedReleaseGateSkeleton` produces structured `ReleaseGateVerdict` | ✅ Verified | `core/distributed_release_gate_skeleton.py` (PR-7) |
| Gate categories: `execution_chain_health`, `session_truth_integrity`, etc. | ✅ Verified (status: `deferred`) | `core/distributed_release_gate_skeleton.py` |
| Gate verdict wired into CI (build fails if `ReleaseGateVerdict == "blocked"`) | ❌ Missing | Gate produces verdict but does not block CI |
| `execution_chain_health` and `session_truth_integrity` promoted to `gate_worthy` | ❌ Missing | Both categories remain `deferred` |
| Auth configuration documented for production deployment | ❌ Missing | `core/auth.py` interface undocumented; no dev-mode stub |

**Key blocker (D8-B1)**: The release gate exists as a well-structured skeleton but
produces no enforcement. A system that looks "blocked" can still be deployed.

*Reference*: `docs/SYSTEM_READINESS_REVIEW_PR8.md §12 P3-A`

### 10.2 Deployment Infrastructure

| Item | Status | Code Reference |
|------|--------|----------------|
| Docker / docker-compose deployment | ✅ Verified | `Dockerfile`, `docker-compose.yml` |
| Systemd service unit | ✅ Verified | `systemd/` |
| `DEPLOYMENT_GUIDE.md` | ✅ Verified | `DEPLOYMENT_GUIDE.md` |
| Windows installer / `start.bat` | ✅ Verified | `installer/`, `start.bat` |
| Supply chain security policy | ✅ Verified | `docs/SUPPLY_CHAIN_SECURITY.md` |
| CHANGELOG / versioning policy | ✅ Verified | `CHANGELOG.md` |
| Release gate hard enforcement in CI | ❌ Missing | — |

### 10.3 Governance / Review Structures

| Item | Status | Code Reference |
|------|--------|----------------|
| ADR status board | ✅ Verified | `docs/ADR_STATUS_BOARD_CONFIG_AUTHORITY.md` |
| Architecture completion scorecard | ✅ Verified | `docs/ARCHITECTURE_COMPLETION_SCORECARD.md` |
| U1–U33 final acceptance report | ✅ Verified | `docs/acceptance/u1_u33_final_acceptance.md` |
| V2 readiness governance evidence surface | ✅ Verified | `core/v2_readiness_governance_evidence_surface.py` |
| Multi-device E2E acceptance matrix | ✅ Verified | `docs/MULTI_DEVICE_E2E_ACCEPTANCE_MATRIX.md` |
| Distributed release gate governance doc | ✅ Verified | `docs/DISTRIBUTED_RELEASE_GATE_SKELETON.md` |

### 10.4 Dimension 8 Closure Summary

| Sub-area | Status | Priority |
|----------|--------|----------|
| Release gate structure | ✅ Verified | — |
| Deployment infrastructure | ✅ Verified | — |
| Governance / review structures | ✅ Verified | — |
| Release gate CI enforcement | ❌ Missing | P0 |
| Auth configuration documentation | ❌ Missing | P0 |
| `execution_chain_health` / `session_truth_integrity` promoted to gate-worthy | ❌ Missing | P1 |

---

## 11. System Usability Matrix Summary

This matrix provides a single-page overview of closure status across all eight
dimensions. It is intended as the primary reviewer-facing summary.

| Dimension | Verified ✅ | Partial 🟡 | Missing ❌ | Overall |
|-----------|-------------|------------|-----------|---------|
| D1 Buildability / Startup | V2 build, staged startup, Docker | Android build (manual only) | Auth dev mode, APK CI artifact, end-to-end runbook | 🟡 Partial |
| D2 Backend Orchestration | Local execution spine, task ingress | `hybrid_execute`, `DeviceRouter` | `task_cancel/status` propagation, capability-aware dispatch, audit lineage | 🟡 Partial |
| D3 Android Runtime | Core services, canonical protocol types | `hybrid_execute` Android path, `takeover_response` | `rag_query`, `handoff_v2_response` receipt, cleartext scoping | 🟡 Partial |
| D4 Cross-Repo Integration | Structural consistency enforcement, continuity contract | V2/Android mock tests | End-to-end integration test, schema generation tooling | ❌ Critical gap |
| D5 Truth / Reconciliation | UDM, `CanonicalTask`, `TaskGraphRuntime`, 3 conflicts resolved | Android reconciliation downstream | 2 open truth conflicts, API audit lineage, scheduler registration | 🟡 Partial |
| D6 Offline / Replay / Recovery | Android offline queue, V2 recovery infrastructure | Distributed task merge/recovery | V2 restart E2E test, API ingress replay | 🟡 Partial |
| D7 Operator / Observability | `OperatorSurface`, gap registry, evidence surfaces | Monitoring surface | Status board `OperatorSurface` consumption, combined Android health view | 🟡 Partial |
| D8 Readiness / Release | Gate structure, deployment infra, governance docs | — | Gate CI enforcement, auth documentation | ❌ Critical gap |

### Overall Usability Verdict

> **Architecturally Ready. Operationally Pre-Production.**
>
> The dual-repo system is structurally sophisticated and correctly decomposed.
> The V2 backend has a well-designed canonical orchestration spine, a mature
> Android integration layer, and extensive review/governance artifacts.
> The Android app is a production-grade Kotlin application with proper lifecycle
> management and protocol discipline.
>
> However, the system **cannot yet be smoothly operated by a new operator**
> without undocumented tribal knowledge. The highest-leverage blockers are
> operational, not architectural:
>
> 1. No end-to-end startup runbook (D1-B3)
> 2. No auth dev mode / documentation (D1-B1, D8)
> 3. No cross-repo integration test (D4-B1)
> 4. `task_cancel/status` propagation broken (D2-B1)
> 5. Release gate not enforced in CI (D8-B1)
>
> These five items are the P0 closure priorities.

---

## 12. Follow-Up Track Map

This section organizes remaining closure work into reviewer-actionable follow-up
tracks. Each track maps to one or more concrete future PRs.

### Track A — Startup / Bootstrap Clarity (P0/P1)

**Goal**: A new operator can start the complete system from a fresh clone by
following a single runbook.

| Work Item | Priority | Suggested PR |
|-----------|----------|-------------|
| Create `docs/OPERATOR_STARTUP_RUNBOOK.md`: V2 prerequisites → startup → Android APK build → server URL → device verification → health check | P0 | Follow-up PR-A1 |
| Document `core/auth.py` interface; provide a development-mode stub | P0 | Follow-up PR-A1 |
| Add GitHub Actions workflow to produce debug APK as CI artifact on every Android repo commit | P1 | Follow-up PR-A2 (android repo) |
| Implement server URL discovery (mDNS or QR code from `/api/v1/system`) | P2 | Follow-up PR-A3 |

*References*: `docs/CLONE_TO_USE_REALITY.md`, `QUICKSTART.md`, `L4_QUICK_START_GUIDE.md`

### Track B — Android ↔ V2 Integration Contract Completion (P0/P1)

**Goal**: The cross-repo integration contract is tested, schema-governed, and
operationally verified.

| Work Item | Priority | Suggested PR |
|-----------|----------|-------------|
| Add end-to-end integration test: real V2 + simulated Android WS client → device_register + task_dispatch + result_return + reconnect | P0 | Follow-up PR-B1 |
| Add V2 restart + in-flight task + Android reconnect + result acceptance E2E test | P0 | Follow-up PR-B1 |
| Add `network_security_config.xml` restricting cleartext to LAN address ranges | P1 | Follow-up PR-B2 (android repo) |
| Add schema generation tooling for shared AIP v3 types | P2 | Follow-up PR-B3 |
| Add contract-compatibility CI check (V2 schema vs Android `AipModels.kt`) | P2 | Follow-up PR-B3 |

*References*: `docs/ANDROID_PROTOCOL_MATURITY_MATRIX.md`, `docs/CROSS_REPO_SIGNAL_CLOSURE_VALIDATION_MATRIX.md`

### Track C — Operational Recovery Hardening (P0/P1)

**Goal**: V2 restart, network disconnect, and Android reboot scenarios are
automatically tested and verified to recover correctly.

| Work Item | Priority | Suggested PR |
|-----------|----------|-------------|
| E2E test: V2 restart while Android has in-flight task → Android reconnects → V2 accepts queued results | P0 | Follow-up PR-C1 |
| Fix `task_cancel` and `task_status` propagation to `CommandRouter` | P0 | Follow-up PR-C1 |
| Verify `DistributedTaskMergeRecovery` operational completeness | P1 | Follow-up PR-C2 |
| Document cross-session queue ordering semantics in `OfflineTaskQueue` | P2 | Follow-up PR-C2 |

*References*: `core/android_v2_continuity_contract.py`, `core/recovery_durability_closure_validator.py`,
`docs/SYSTEM_AUDIT_REPORT_ZH.md §6.2`

### Track D — Operator Visibility Improvements (P1)

**Goal**: An operator can observe full system state — including Android participants
— from the V2 monitoring surface without source-diving.

| Work Item | Priority | Suggested PR |
|-----------|----------|-------------|
| Add `/api/v1/system/android-devices` endpoint (or extend monitoring surface): connected devices, last heartbeat, offline queue depth, in-flight tasks | P1 | Follow-up PR-D1 |
| Wire status board to consume `OperatorSurface` snapshot (close GAP-512-005) | P1 | PR-514 (existing target) |
| Wire all projection endpoints to consume `ProjectionSurfaceBridge` (close GAP-512-003) | P1 | PR-514 (existing target) |
| Add `TASK_ADMITTED` audit event from `AgentKernel` (close GAP-512-007) | P1 | PR-513 (existing target) |
| Add orchestration handoff audit event from `TaskOrchestrator` (close GAP-512-006) | P1 | PR-513 (existing target) |
| Write `TaskExecutionRecord` to `ReplayFoundation` on API ingress (close GAP-512-001) | P1 | PR-513 (existing target) |

*References*: `docs/RESIDUAL_GAP_MAP.md`, `core/runtime_closure_audit.py`,
`core/operator_surface.py`

### Track E — Release Gate / Policy Tightening (P0/P1)

**Goal**: The release gate gives a trustworthy, enforced signal before deployment.

| Work Item | Priority | Suggested PR |
|-----------|----------|-------------|
| Wire `ReleaseGateVerdict` into CI (fail build if verdict == "blocked") | P0 | Follow-up PR-E1 |
| Promote `execution_chain_health` and `session_truth_integrity` from `deferred` to `gate_worthy` | P1 | Follow-up PR-E1 |
| Resolve CONFLICT-002 (network topology truth: `NetworkTopologyRuntime` vs `ContinuumState`) | P1 | PR-514 (existing target) |
| Resolve CONFLICT-003 (executor readiness truth: `CapabilityAssimilationLayer` vs `CapabilityRegistry`) | P1 | PR-513 (existing target) |
| Establish model/provider routing canonical authority (close GAP-512-009) | P2 | PR-515 (existing target) |

*References*: `core/distributed_release_gate_skeleton.py`,
`docs/DISTRIBUTED_RELEASE_GATE_SKELETON.md`, `docs/RESIDUAL_GAP_MAP.md`

### Track F — End-to-End Runnable Scenario Validation (P1/P2)

**Goal**: A documented, reproducible scenario proves the complete system runs
end-to-end under realistic conditions.

| Work Item | Priority | Suggested PR |
|-----------|----------|-------------|
| Define a canonical "V2+Android end-to-end runnable scenario": V2 starts → Android joins → user sends command → Android executes → result returned and visible in V2 operator surface | P1 | Follow-up PR-F1 |
| Record an evidence artifact (test output, screen recording, or operator surface snapshot) proving the scenario runs | P1 | Follow-up PR-F1 |
| Extend scenario to cover: offline queue flush, reconnect, V2 restart recovery | P2 | Follow-up PR-F2 |

---

## 13. Evidence and Prior Artifact Index

This section catalogs the review artifacts that ground this closure plan in the
real repositories. Reviewers can use these references to verify claims made in
the closure plan above.

### V2 Repository Artifacts

| Artifact | Location | Contents |
|----------|----------|----------|
| PR-8 Full-System Readiness Review | `docs/SYSTEM_READINESS_REVIEW_PR8.md` | Code-grounded product usability assessment; primary evidence source for this plan |
| V2+Android Runtime Closure Audit | `docs/V2_ANDROID_RUNTIME_CLOSURE_AUDIT.md` | Distributed runtime completeness classification and reviewer checklist |
| Dual-Repo Full Re-Audit | `docs/DUAL_REPO_FULL_REAUDIT.md` | Second-pass dual-repo audit |
| Residual Gap Map | `docs/RESIDUAL_GAP_MAP.md` | Machine-readable gap catalog (PR-512) |
| System Audit Report (ZH) | `docs/SYSTEM_AUDIT_REPORT_ZH.md` | Chinese-language systematic review |
| Android Protocol Maturity Matrix | `docs/ANDROID_PROTOCOL_MATURITY_MATRIX.md` | Per-message-type protocol maturity |
| Cross-Repo Signal Closure Validation | `docs/CROSS_REPO_SIGNAL_CLOSURE_VALIDATION_MATRIX.md` | Signal-level cross-repo closure matrix |
| U1–U33 Final Acceptance Report | `docs/acceptance/u1_u33_final_acceptance.md` | Block-by-block acceptance verdict |
| Architecture Completion Scorecard | `docs/ARCHITECTURE_COMPLETION_SCORECARD.md` | Architecture readiness scorecard |
| Multi-Device E2E Acceptance Matrix | `docs/MULTI_DEVICE_E2E_ACCEPTANCE_MATRIX.md` | Multi-device scenario acceptance |
| Clone-to-Use Reality | `docs/CLONE_TO_USE_REALITY.md` | Honest operator experience assessment |

### V2 Code Modules Referenced

| Module | Role |
|--------|------|
| `main.py` | Canonical single entrypoint |
| `core/system_orchestrator.py` | 7-phase staged pre-flight |
| `unified_launcher.py` | Subordinate async launcher |
| `core/openclawd.py` | Cognition + execution decision core |
| `core/command_router.py` | Sole legal cross-device dispatcher |
| `core/source_dispatch_orchestrator.py` | Canonical dispatch brain |
| `core/device_registry.py` | UDM (device write SSOT) + DeviceRegistry (compat) |
| `core/android_bridge.py` / `galaxy_gateway/android_bridge.py` | AIP v3 protocol adapter |
| `core/android_delegated_runtime_lifecycle_coordinator.py` | Lifecycle event façade |
| `core/android_v2_continuity_contract.py` | Joint continuity contract (7 scenarios) |
| `core/flow_continuity_coordinator.py` | Continuity decision entry point |
| `core/android_execution_signal_reconciler.py` | Signal reconciliation |
| `core/recovery_durability_closure_validator.py` | Recovery matrix |
| `core/runtime_closure_audit.py` | Programmatic gap registry |
| `core/distributed_release_gate_skeleton.py` | Release gate (skeleton) |
| `core/v2_readiness_governance_evidence_surface.py` | Readiness evidence surface |
| `core/operator_surface.py` | Canonical operator inspection truth |
| `core/replay_foundation.py` | Replay/audit truth |
| `core/task_graph_runtime.py` | Task graph truth |
| `core/contract_closure.py` | `describe_contract_closure()` introspection |
| `galaxy_gateway/routes/websocket.py` | AIP v3 WebSocket routes |

### Android Repository Artifacts

| Module | Role |
|--------|------|
| `app/src/main/java/com/ufo/galaxy/service/GalaxyConnectionService.kt` | Main foreground service |
| `app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt` | WS client + reconnect |
| `app/src/main/java/com/ufo/galaxy/network/OfflineTaskQueue.kt` | Offline queue |
| `app/src/main/java/com/ufo/galaxy/protocol/AipModels.kt` | AIP v3 protocol model |
| `app/src/main/java/com/ufo/galaxy/protocol/CrossRepoConsistencyGate.kt` | Cross-repo consistency gate |
| `app/src/main/java/com/ufo/galaxy/protocol/UgcpProtocolConsistencyRules.kt` | Protocol consistency rules |
| `app/src/main/java/com/ufo/galaxy/protocol/UgcpSharedSchemaAlignment.kt` | Shared schema alignment |
| `app/src/main/AndroidManifest.xml` | Service registration + permissions |

---

*This document is V2 PR-9's canonical closure artifact. It supersedes the previous
V2 PR-9 attempt (PR #825). Future PRs should update the status fields in the
closure summaries as real closure happens, and add resolved items to the
[Evidence and Prior Artifact Index](#13-evidence-and-prior-artifact-index).*
