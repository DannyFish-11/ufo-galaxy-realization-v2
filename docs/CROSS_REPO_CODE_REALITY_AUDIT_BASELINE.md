# Cross-Repo Code-Reality Audit Baseline & Unified Target-State Model

> **Scope**: `DannyFish-11/ufo-galaxy-realization-v2` (V2 — center-side) and
> `DannyFish-11/ufo-galaxy-android` (Android — edge runtime).
>
> **Authority**: This document is the single unified source for understanding the
> system as it **actually exists today in merged code**, the relationship between
> both repositories, the minimum viable runtime, component maturity, and the gap
> between current reality and the intended target state.
>
> **Principle**: Only code that is already merged and in the default branch is
> treated as "reality". Unmerged PR descriptions, design notes, and doc-level
> aspirations are treated as **target state** unless proven by merged implementation.
>
> **Companion documents** (detail layers — consult these for per-domain depth):
> - `docs/DUAL_REPO_FULL_REAUDIT.md` — full domain-by-domain re-audit
> - `docs/DUAL_REPO_GAP_MATRIX.md` — machine-readable gap matrix
> - `docs/MULTI_DEVICE_RUNTIME_MATURITY.md` — per-component maturity table
> - `docs/ANDROID_PROTOCOL_MATURITY_MATRIX.md` — Android long-tail protocol assessment
> - `docs/FOLLOWUP_IMPLEMENTATION_ROADMAP.md` — prioritized follow-up roadmap
> - `docs/CLONE_TO_USE_REALITY.md` — minimal quick-start truth

---

## Table of Contents

1. [System Identity — What This System Actually Is](#1-system-identity--what-this-system-actually-is)
2. [Dual-Repo Architecture Map](#2-dual-repo-architecture-map)
3. [Execution Chain Analysis](#3-execution-chain-analysis)
4. [Minimum Viable Runtime](#4-minimum-viable-runtime)
5. [Component Maturity Classification](#5-component-maturity-classification)
6. [Target State Gap Matrix](#6-target-state-gap-matrix)
7. [Critical Reality Issues](#7-critical-reality-issues)

---

## 1. System Identity — What This System Actually Is

### 1.1 One-sentence definition

**Galaxy (repo prefix: `ufo-galaxy`; runtime brand: Galaxy-Nexus / 星枢) is a
center-orchestrated cross-device intelligent agent system in which a Windows PC
acts as the cognitive center ("主脑"), Android devices act as edge execution
bodies ("边缘执行体"), and a Node network of 130+ domain services extends the
center's capability reach — all coordinated through a unified WebSocket gateway
over AIP v3.**

> **Naming note**: The repository is prefixed `ufo-galaxy-*` for historical
> reasons. Inside the codebase the system is branded **Galaxy-Nexus** (`main.py`
> header) or simply **Galaxy** (`unified_launcher.py`, API labels). Both names
> refer to the same system; "ufo-galaxy" is the repository-naming convention only.

### 1.2 What it is NOT

| Misconception | Reality |
|---------------|---------|
| A chat application | Chat is one API surface (`POST /api/v1/chat`); the system is a full runtime orchestration platform with task lifecycle, device management, and execution routing |
| A pure Android remote-control tool | Android is one execution body; the center governs routing, capability assimilation, and task dispatch across any connected device or node |
| A parallel multi-agent mesh | The center is the single cognitive authority; Android and nodes are execution participants, not peer cognitive authorities |
| Completed and production-ready | The canonical spine is established; multi-device mesh, WebRTC transport, and media lifecycle require additional runtime engines |

### 1.3 Three-layer role definition

#### Layer 1 — V2: Center Cognitive and Orchestration Authority (`ufo-galaxy-realization-v2`)

The V2 repo is the system's brain. It:

- Owns **all** routing, scheduling, capability registration, and dispatch decisions
- Hosts the **cognitive subject** (`DesktopPresenceRuntime` shell + `OpenClawd` core)
- Defines the canonical authority chain for every operation
- Contains the gateway that all external participants (Android, nodes, clients) connect to
- Manages device lifecycle, task lifecycle, truth/projection, and observability

V2 is written in Python (FastAPI/uvicorn backend) and is the only repo that must
be running for any cross-device flow to work.

#### Layer 2 — Android: Edge Execution Body (`ufo-galaxy-android`)

The Android repo is an execution body. It:

- Connects to V2's gateway over WebSocket using AIP v3.0 protocol
- Receives task assignments (`task_assign`) from V2 and executes them on-device
  (UI automation, screen capture, touch/gesture, accessibility tree traversal)
- Reports results back to V2 via `task_result` messages
- Does NOT make routing, scheduling, or capability assimilation decisions

**Why Android is "a kind of node but not a `nodes/Node_xxx` node":**
Android is a **runtime participant** that executes tasks delegated by the center,
similar in role-concept to a node. However:
- `nodes/Node_xxx` directories are Python microservices running locally or in
  Docker, registered via `NodeFabricRegistry`, and callable by `OpenClawd` as
  tool-capability endpoints over HTTP.
- Android is a remote, mobile device connected over WebSocket. It registers
  as a **device** in UDM (UnifiedDeviceManager), not as a node. It participates
  in the `CommandRouter` cross-device path, not the node capability path.
- Architecturally, Android is a `RegisteredRuntimeDevice` participant, not a
  `NodeFabricRegistry` entry. Both types are unified under
  `CapabilityAssimilationLayer`, but their routing paths differ.

#### Layer 3 — Node Network: Capability Extension Services (inside V2 repo)

The `nodes/Node_xxx` directories are domain-specific capability services:
VLM analysis (Node_113), WebRTC reception (Node_95), code engines, RAG, audio,
video processing, and 120+ others. They:

- Are Python/Docker microservices registered via `NodeFabricRegistry`
- Are discovered and started by `launcher/node_startup.py`
- Are called by `OpenClawd` via `CapabilityAssimilationLayer` tool catalog
- Have a `startup_policy` in `node_dependencies.json`: `active`, `optional`,
  or `skip`

---

## 2. Dual-Repo Architecture Map

### 2.1 V2 — Center-Side Structure

```
main.py                                  ← canonical system orchestrator (PR-2)
  │  Phases 1–7 pre-flight
  └─► unified_launcher.py               ← subordinate async bring-up
          │
          ├─► launcher/bootstrap.py      — SystemConfig, entrypoint writer
          ├─► launcher/service_manager.py — ServiceInfo lifecycle
          ├─► launcher/core_services.py  — CoreServiceLauncher (device agent, status API, UFO)
          ├─► launcher/node_startup.py   — NodeSystemLauncher (node discovery/health)
          ├─► launcher/health_checks.py  — post-startup health probe
          └─► launcher/shutdown.py       — graceful NATS + subsystem teardown
          │
          └─► galaxy_gateway/app.py      ← unified gateway (FastAPI + uvicorn, port 8765 default)
                  │
                  ├─ /ws/device/{device_id}      Android / device WebSocket ingress (AIP v3)
                  ├─ /ws/webrtc/{device_id}      WebRTC signaling proxy → Node_95
                  ├─ /api/v1/*                   REST API surface (core/api_routes.py)
                  └─ /ws/status                  status push WebSocket

Subject (cognitive + execution core):
  core/desktop_presence_runtime.py      ← runtime shell (Windows clothing, tri-state lifecycle)
      └─ LIMINAL: core/openclawd.py     ← subject cognitive core
              ├─ Stage 1: Ingest (PerceptionFrame + multimodal_context)
              ├─ Stage 2: ContinuumOrchestrator (intent → state_continuum)
              ├─ Stage 3: Branch (_determine_execution_path → local/cross_device/hybrid/none)
              └─ Stage 4: Manifest
                      ├─ DecisionExecutor         → local Windows execution
                      └─ CommandRouter            → cross-device gateway path

Canonical authority chain:
  DesktopPresenceRuntime (runtime_shell_authority)
    └─ OpenClawd (subject_decision_authority)
          └─ AgentKernel (cognition_planning_layer — LLM planning only)
                └─ CommandRouter (execution_substrate — cross-device canonical router)

Device management:
  core/unified/                          ← UnifiedDeviceManager (UDM), UnifiedConnectionManager (UCM)
  core/device_registry.py               ← compatibility indexing layer (forwards to UDM)
  contracts/registered_runtime_device.py ← canonical single-device read contract

Capability:
  core/capability_assimilation.py        ← CapabilityAssimilationLayer (unified for devices + nodes)
  core/capability_registry.py            ← runtime capability index

Truth / projection:
  core/truth_integration_layer.py        ← TruthIntegrationLayer (canonical device truth)
  contracts/multi_device_runtime_projection.py ← top-level multi-device read model

Node fabric:
  nodes/Node_xxx/                        ← 130+ domain capability services
  core/nodes/node_fabric_registry.py     ← NodeFabricRegistry (node registration)
  launcher/node_startup.py              ← node discovery / health polling

LLM backend:
  core/unified/llm_router.py             ← UnifiedLLMRouter (process-level singleton)
  core/llm_manager.py                    ← legacy compatibility shim → forwards to UnifiedLLMRouter
```

### 2.2 Android — Edge-Side Structure

```
DannyFish-11/ufo-galaxy-android
  app/
    UFOGalaxyApplication.kt              ← Application entry, dependency init
    runtime/
      RuntimeController.kt              ← runtime lifecycle controller
      LoopController.kt                 ← execution loop (task polling + action dispatch)
    connection/
      GalaxyConnectionService.kt        ← WebSocket connection to V2 gateway
                                           connects to: ws://<V2_HOST>:8765/ws/device/{device_id}
                                           protocol: AIP v3.0
    agent/
      AgentMessageHandler.kt            ← inbound message handler (task_assign, agent_config_update, etc.)
    automation/
      UIAutomationService.kt            ← Accessibility-based UI automation
      AccessibilityExecutor.kt          ← action execution (click, swipe, type, etc.)
    vlm/
      VLMClient.kt                      ← calls Node_113_AndroidVLM on V2 side for screen analysis
    media/
      WebRTCModule.kt                   ← WebRTC signaling client
                                           connects to: ws://<V2_HOST>:8765/ws/webrtc/{device_id}
```

### 2.3 Cross-Repo Boundary and Calling Relations

```
V2 (server) ←──────────── WebSocket AIP v3 ───────────── Android (client)
    │                  /ws/device/{device_id}                    │
    │                                                             │
    │  task_assign (server→client)                               │
    │  ──────────────────────────────────────────────────────►   │
    │                                                             │
    │  task_result (client→server)                               │
    │  ◄──────────────────────────────────────────────────────   │
    │                                                             │
    │  device_register / heartbeat / device_status               │
    │  ◄──────────────────────────────────────────────────────   │
    │                                                             │
    │  screen_capture / ui_tree (client→server for VLM)         │
    │  ◄──────────────────────────────────────────────────────   │

V2 (Node_113 AndroidVLM) ←── HTTP ──── Android VLMClient.kt
    │  POST /api/analyze
    │  POST /api/analyze_action

V2 (Node_95 WebRTC Receiver) ←── WebRTC signaling ──── Android WebRTCModule.kt
    │  /signaling/{device_id}  (via gateway proxy /ws/webrtc/{device_id})
```

---

## 3. Execution Chain Analysis

### 3.1 Local Execution Chain (center local path)

**Status: ✅ CLOSED MAIN CHAIN (Windows-dependent)**

```
User/API request
  → POST /api/v1/chat  (galaxy_gateway/app.py → core/api_routes.py)
  → DesktopPresenceRuntime.handle_request()      [silent → liminal]
  → OpenClawd.process()
      Stage 1: Ingest (PerceptionFrame from MultimodalIngressBus, request multimodal_context)
      Stage 2: ContinuumOrchestrator → state_continuum (intent resolved)
      Stage 3: _determine_execution_path() → "local"
      Stage 4: DecisionExecutor / WindowsExecutionArbiter
          → Windows System API / pywinauto / keyboard / mouse actions
  → result returned → [manifest → silent]
```

**Reality check**:
- Locally closed loop from chat API → LLM cognition → Windows execution → result
- Requires Windows OS (pywinauto, win32api dependencies)
- Requires a working LLM backend (OneAPI or direct provider configured in `.env`)
- `DecisionExecutor` → `WindowsExecutionArbiter` is the Windows-only local execution path
- Non-Windows environments: local execution path degrades or is bypassed

### 3.2 Cross-Device Delegation Chain (cross-device path)

**Status: ⚠️ PARTIAL CLOSED CHAIN (end-to-end wired; mesh/barrier/cancel not runtime-driven)**

```
OpenClawd._determine_execution_path() → "cross_device" | "hybrid"
  → CommandRouter.route_envelope(TaskEnvelope)            [sole dispatch authority]
      → cross_device_candidates.resolve_candidates()      [formation resolution]
      → TaskEnvelope stamped with RemoteExecutionMode
      → galaxy_gateway / DeviceRouter.route_task()
          → AndroidBridge.send_task()                     [AIP v3 task_assign]
              → WebSocket → Android GalaxyConnectionService
                  → AgentMessageHandler.kt / LoopController.kt
                  → UIAutomationService / AccessibilityExecutor
                  → task_result via WebSocket back to V2
      → TaskGraphRuntime.record_result()
      → ReplayFoundation / OperatorSurface (result surfacing)
```

**Reality check**:
- End-to-end chain is wired: `CommandRouter → gateway → Android → result → TaskGraphRuntime`
- AIP v3.0 protocol is stable and enforced at ingress
- Formation resolution at dispatch is implemented (static formations only)
- `TruthIntegrationLayer` is defined but not confirmed as sole consumer entrypoint
- Multi-device mesh session lifecycle (barrier wait, merge trigger, subtask status update) is **contract-first only** — no live coordinator engine drives state transitions at runtime
- Task cancel / recovery / memory backflow are partially wired but not fully closed

### 3.3 Node Capability Chain (node path)

**Status: ⚠️ PARTIAL — node startup and registration work; capability graph not consulted at dispatch**

```
OpenClawd (Stage 3 Branch → tool call)
  → CapabilityAssimilationLayer.query_routable_executors()  [advisory only in hot path]
  → NodeFabricRegistry (callable nodes in tool catalog)
  → node HTTP call (e.g. Node_113: POST /api/analyze)
  → result returned to OpenClawd
```

Node startup flow:
```
launcher/node_startup.py — NodeSystemLauncher
  → reads node_dependencies.json (startup_policy: active/optional/skip)
  → starts "active" nodes unconditionally; "optional" if available
  → polls health endpoints
  → registers healthy nodes in NodeFabricRegistry
  → cross-references callable_node_baseline.is_callable_by_openclawd()
```

**Reality check**:
- 130+ node directories exist; most are Python microservices or stubs
- `startup_policy` in `node_dependencies.json` is the canonical gate
- `NodeFabricRegistry` and `CapabilityAssimilationLayer` are wired for unified registration
- **Key gap**: `CommandRouter.route_envelope()` does not invoke `query_routable_executors()` to gate routing decisions; the capability graph is built but advisory-only in the dispatch hot path (SCHED-001)
- Many nodes are experimental, optional, or stub-level — only the "active" subset is
  expected to start successfully in a standard environment

### 3.4 Media / WebRTC / Streaming Chain (media path)

**Status: 🔴 SIGNALING ONLY — not integrated into canonical task/runtime main chain**

```
Android WebRTCModule.kt
  → ws://V2:8765/ws/webrtc/{device_id}    (gateway WebRTC proxy)
  → galaxy_gateway/webrtc_proxy.py         relays ↔ Node_95_WebRTC_Receiver
  → Node_95/main.py (aiortc)               WebRTC peer connection + frame capture
  → HTTP API → Node_113_AndroidVLM         VLM analysis of captured frames
```

WebRTC task lifecycle integration (`core/webrtc_task_lifecycle.py`):
```
WebRTCTaskBinding.bind(task_id, device_id, webrtc_session_id)
  → transport state changes → classify_transport_lifecycle_action()
  → terminal task → teardown_binding_on_task_terminal()
```

**Reality check**:
- WebRTC signaling proxy is wired (gateway → Node_95)
- `WebRTCTaskBinding` and `WebRTCTaskLifecycle` contracts exist with task-scoped binding
- **Critical gap**: WebRTC session creation is NOT triggered from the canonical task dispatch chain; no `CommandRouter` path or `TaskEnvelope` type causes a WebRTC session to be established as part of task execution
- `WebRTCTaskBinding` is an additive module — it can bind an **already-existing** WebRTC session to a task; it does not initiate WebRTC from a task
- `Node_95` starts as an optional/standalone service; its runtime lifecycle is NOT synchronized with `CanonicalTaskRuntime` events from `CommandRouter`
- Media lifecycle (session continuity, transport degradation, reconnect) is defined in contracts but has no live orchestration engine

---

## 4. Minimum Viable Runtime

### 4.1 What can actually be started from a fresh clone

**Environment requirement**: Linux or Windows with Python 3.9+, network access for LLM provider

```bash
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git
cd ufo-galaxy-realization-v2
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in LLM API key(s)
python main.py --host 127.0.0.1 --port 8299
```

**What starts**: FastAPI gateway server, API routes, device management, basic node discovery

### 4.2 Capabilities available after startup

| Capability | Available | Notes |
|------------|-----------|-------|
| REST chat API (`POST /api/v1/chat`) | ✅ | Requires valid LLM backend config in `.env` |
| Runtime projection (`GET /api/v1/projection/runtime`) | ✅ | Returns current device/task state snapshot |
| Device registration (`POST /api/v1/devices/register`) | ✅ | Registers Android or other devices |
| Node status queries | ✅ | Shows which nodes are running |
| WebSocket device channel | ✅ | `/ws/device/{device_id}` accepts Android connections |
| Status board | ✅ | `python -m windows_client.status_board_v2` (read-only, projection display) |
| Local Windows execution | ✅ (Windows only) | pywinauto/win32 required; silently degrades on Linux |
| Android device bridging | ✅ (if device connected) | Requires Android app running and network reachability |
| WebRTC signaling proxy | ✅ (if Node_95 active) | Proxies signaling only; video frames need aiortc dependencies |
| Full multi-device mesh | ❌ | Contract-first; no live coordinator engine |
| WebRTC → task lifecycle binding | ❌ | Module exists but no task initiation triggers it |
| Node capability graph enforcement at dispatch | ❌ | Advisory-only in hot path |
| Memory backflow / cancel / recovery | ❌ | Partially wired; not fully closed |

### 4.3 Minimum viable form

The system's minimum viable form **right now** is:

> A single-host center server answering chat via LLM, accepting Android device
> connections and forwarding task assignments to connected devices over AIP v3
> WebSocket, with task result surfacing into `TaskGraphRuntime` and observable
> via the REST projection APIs.

This works without Docker, without NATS, and without any node services (nodes
start as optional and degrade gracefully). It requires only: Python runtime,
network access to LLM provider, and optionally an Android device running the app.

---

## 5. Component Maturity Classification

| Component | Classification | Evidence |
|-----------|---------------|---------|
| **V2 startup chain** (`main.py` → `unified_launcher.py`) | ✅ Runtime-complete | Canonical PR-2 authority, phases 1–7, tests in `test_batch_pr2_startup_orchestrator.py` |
| **Gateway** (`galaxy_gateway/app.py`, AIP v3) | ✅ Runtime-complete | Stable protocol, enforcement at ingress, compat normalisation layer |
| **Subject core** (`DesktopPresenceRuntime` + `OpenClawd`) | ✅ Runtime-complete (Windows) | Tri-state lifecycle, 4-stage processing, authority chain stable |
| **CommandRouter** (sole cross-device dispatch) | ✅ Runtime-complete | Canonical substrate, `route_envelope()` sole dispatch path, PR-7/PR-8 |
| **Device management** (UDM + UCM + DeviceRegistry) | ✅ Runtime-complete | UDM is canonical write SSOT; DeviceRegistry is compatibility index layer |
| **AIP v3 protocol** | ✅ Stable | `galaxy_gateway/protocol/aip_v3.py`, enforced at WebSocket ingress |
| **Android integration** (connection + task execute) | ⚠️ Partial | Connection + task dispatch + result uplink closed; VLM/takeover/complex gestures require careful env |
| **Node network startup** | ⚠️ Partial | NodeSystemLauncher starts active/optional nodes; health polling works; capability graph advisory-only at dispatch |
| **CapabilityAssimilationLayer** | ⚠️ Partial | Unified registration for devices + nodes works; not consulted in dispatch hot path (SCHED-001) |
| **TruthIntegrationLayer** | ⚠️ Partial | Defined, tested (28 tests); not confirmed as sole consumer entrypoint for all truth reads |
| **MultiDeviceRuntimeProjection** | ⚠️ Partial / Contract-first | Contract stable; `merged_results` body not fully sourced from canonical chain state |
| **Mesh session** (`MeshSession`, `MeshSessionCoordinator`) | 🔴 Contract-first | Full contract hierarchy exists; NO live engine drives state transitions at runtime |
| **WebRTC task lifecycle** (`webrtc_task_lifecycle.py`) | 🔴 Contract-first / Additive | Binding contract and teardown logic exist; NOT triggered from canonical dispatch chain |
| **Media / streaming pipeline** | 🔴 Signaling-only | Node_95 receives WebRTC frames; no media lifecycle bound to canonical task/runtime events |
| **NATS message bus** | ⚠️ Optional | `core/nats_bus.py` exists; system degrades gracefully if NATS is not present |
| **Windows local execution** | ✅ Runtime-complete (Windows-only) | pywinauto/win32 path is full execution substrate on Windows; silently absent on Linux |
| **LLM backend** (`UnifiedLLMRouter`) | ✅ Runtime-complete | Process-level singleton, legacy `llm_manager.py` delegating shim, requires API key config |

---

## 6. Target State Gap Matrix

The following table maps each target-state goal against current reality, the
critical gap, and the highest-priority next step.

### 6.1 Center Distributed Network Topology

| | |
|---|---|
| **Target** | V2 center connects to multiple independent node/device clusters; topology is discoverable and dynamic; no single-process limitation |
| **Current reality** | V2 is a single Python process; node services run as local or Docker services; device connections are WebSocket sessions to the single gateway |
| **Gap** | No inter-instance federation; no node cluster topology outside of local process; `galaxy_federation.py` contract exists but not wired into startup or routing |
| **Blocking point** | No federation runtime (NATS pub/sub scope is single-instance); multi-process node orchestration not implemented |
| **Priority next step** | Define a minimal federation topology contract and wire at least NATS-based center-to-center event relay |

### 6.2 Node Governance Closure

| | |
|---|---|
| **Target** | Nodes are discovered, health-checked, classified (callable/service/legacy/experimental), registered in a live fabric, and consulted at every dispatch |
| **Current reality** | `NodeSystemLauncher` starts nodes; `NodeFabricRegistry` holds registrations; classification is implemented; BUT `CommandRouter` dispatch does not gate on capability graph query |
| **Gap** | SCHED-001: `query_routable_executors()` is advisory-only; routing proceeds without capability verification |
| **Blocking point** | No canonical gate in `cross_device_candidates.resolve_candidates()` or `CommandRouter` pre-dispatch for capability-capability verification |
| **Priority next step** | Add capability gate (Gate 4) to `cross_device_candidates.resolve_candidates()` or a mandatory validation step in `CommandRouter.route_envelope()` |

### 6.3 ATS / Readiness / Participation / Dispatch / Mesh Convergence

| | |
|---|---|
| **Target** | Device admission, readiness gate, task participation, dispatch selection, and mesh session lifecycle are all governed by a single authority chain with live runtime state |
| **Current reality** | Admission chain, readiness gate, and dispatch selection are wired in `CommandRouter` / `cross_device_candidates`; mesh session is contract-first only |
| **Gap** | MESH-001/002: `MeshSessionCoordinator` and `MeshSession` have no live coordinator engine; `subtask_assignments` statuses are not updated from `TaskGraphRuntime` events |
| **Blocking point** | No `MeshCoordinatorRuntime` class that runs alongside `TaskGraphRuntime` and updates barrier/assignment/merge state as execution progresses |
| **Priority next step** | Implement `MeshCoordinatorRuntime` that subscribes to `TaskGraphRuntime` events and drives `MeshSession` state transitions |

### 6.4 Android as True Edge Runtime Participant

| | |
|---|---|
| **Target** | Android participates in mesh sessions, reports readiness, receives capability-matched task assignments, handles degradation/reconnect, and contributes to multi-device merge results |
| **Current reality** | Android connects via AIP v3, receives task assignments, executes UI actions, reports results; registered as `RegisteredRuntimeDevice` in UDM; capability-aware registration exists |
| **Gap** | Android is a well-integrated execution body for point task delegation; it is NOT a full mesh participant (no barrier participation, no merge result contribution, no reconnect recovery that drives mesh session recovery) |
| **Blocking point** | Mesh session runtime engine missing (see 6.3); Android-side session bridge (`session_bridge` in Android app) not confirmed as wired to V2 mesh session state |
| **Priority next step** | After MeshCoordinatorRuntime exists, wire Android reconnect/result events into mesh session state transitions |

### 6.5 Native Multimodal Agent

| | |
|---|---|
| **Target** | OpenClawd ingests audio, video, screen context, and external sensors continuously; routes based on multimodal context; VLM analysis is a first-class input to cognition |
| **Current reality** | `MultimodalIngressBus` → `PerceptionFrame` → `OpenClawd` ingress path is wired; `request_bound multimodal_context` for per-request image/audio is supported; `Node_113_AndroidVLM` accepts screen analysis requests |
| **Gap** | Continuous perception is architecturally wired; its actual sensor availability depends on Windows-native inputs (Windows media APIs). On non-Windows, continuous perception falls back to stub. VLM analysis is available via Node_113 HTTP but is not woven into every cognition cycle by default |
| **Blocking point** | Windows-only continuous native perception; VLM analysis is triggered only when `OpenClawd` explicitly calls Node_113, not as an ambient background cognition feed |
| **Priority next step** | Define a platform-agnostic perception source interface so non-Windows can contribute perception events; wire Node_113 VLM analysis as an ambient background task during LIMINAL phase |

### 6.6 WebRTC / Streaming / Transport Continuity

| | |
|---|---|
| **Target** | WebRTC session establishment is triggered by task dispatch; transport state changes (degraded/reconnect/fail) drive task lifecycle; media lifecycle is unified with task and runtime lifecycle |
| **Current reality** | WebRTC signaling proxy works (gateway → Node_95); `WebRTCTaskBinding` contract and teardown logic exist; `WebRTCTaskLifecycle` states are defined |
| **Gap** | No task type or task dispatch path causes a WebRTC session to be established; `WebRTCTaskBinding.bind()` requires a caller to have already created a WebRTC session externally; transport → task lifecycle signal is not driven from the canonical dispatch chain |
| **Blocking point** | Missing: a task action handler that, when a task requiring WebRTC is dispatched, automatically creates a WebRTC session and calls `WebRTCTaskBinding.bind()` |
| **Priority next step** | Add a `WebRTCMediaTask` task type that, when dispatched via `CommandRouter`, triggers `Node_95` session setup and binds via `WebRTCTaskBinding` |

### 6.7 Unified Task / Runtime / Media Lifecycle

| | |
|---|---|
| **Target** | A single canonical lifecycle graph covers task creation → execution → result → memory backflow; runtime session lifecycle (attach/detach/reconnect/degradation) is synchronized; media session lifecycle (WebRTC create/degraded/teardown) is unified |
| **Current reality** | `CanonicalTaskRuntime` and `TaskLifecycleManager` handle task lifecycle; `AttachedRuntimeSession` covers runtime session attach/detach; `WebRTCTaskBinding` covers media-task binding; each module is independently functional |
| **Gap** | The three lifecycle types are not wired into a unified event bus. Task terminal events do not propagate to trigger runtime session cleanup or WebRTC teardown automatically; memory backflow (`core/openclawd_memory_backflow.py`) is wired in some paths but not confirmed as exhaustive |
| **Blocking point** | No unified lifecycle event broker that routes terminal task events to runtime-session cleanup and media-session teardown |
| **Priority next step** | Create a `LifecycleEventBroker` that subscribes to `TaskLifecycleManager` terminal events and triggers cascade cleanup to `AttachedRuntimeSession` and `WebRTCTaskBinding` |

---

## 7. Critical Reality Issues

The following issues represent the highest-value real blockers for making the
system converge toward production-grade end-to-end operation. They are ranked by
architectural impact.

### Issue 1 — Hard LLM Backend Dependency (CRITICAL)

**Description**: `OpenClawd` requires a functioning LLM backend (`UnifiedLLMRouter`
→ configured provider) to perform any cognition. Without a valid API key and
provider configuration in `.env`, the entire cognitive chain is dead. There is no
fallback rule-based cognition mode or graceful degradation for missing LLM.

**Impact**: System cannot process any chat request or task without external LLM access.
**Blocking point**: No offline or fallback cognition path.
**Recommended action**: Add a `DEGRADED_COGNITION` startup phase that warns loudly
when LLM is not configured; optionally add a minimal rule-based fallback for local
device health queries.

---

### Issue 2 — Windows-Only Local Execution Path (HIGH)

**Description**: The local execution chain (`DecisionExecutor` → `WindowsExecutionArbiter`
→ pywinauto/win32) is Windows-specific. On Linux/macOS or inside Docker, the local
execution path is silently unavailable or raises import errors.

**Impact**: In non-Windows environments, `execution_path = "local"` silently produces
no execution, and the system only works as a cross-device delegation engine.
**Recommended action**: Add a clear `EXECUTION_PATH_LOCAL_UNAVAILABLE` flag that is
surfaced in the runtime projection when local execution is not possible; ensure
`OpenClawd._determine_execution_path()` correctly falls back to `"none"` or
`"cross_device"` on non-Windows.

---

### Issue 3 — Android VLM / Accessibility / Takeover Risk (HIGH)

**Description**: Android-side automation (`UIAutomationService`, `AccessibilityExecutor`)
requires Android Accessibility Service permission, overlay permission, and active
app foreground presence. Complex gestures, multi-app navigation, and "takeover" mode
(replacing the current foreground app) carry a high risk of system-level permission
denial, silent failure, or device freeze.

**Impact**: Complex Android task execution can silently fail or hang indefinitely
without timeout enforcement on the Android side.
**Recommended action**: Enforce action-level timeout in `LoopController.kt`; add
structured error reporting for permission-denied and overlay-unavailable cases; map
these to `task_result.error_code` for the server to handle gracefully.

---

### Issue 4 — Missing Session Bridge for Reconnect Recovery (HIGH)

**Description**: When an Android device disconnects and reconnects, there is no
confirmed mechanism to resume an in-progress task or mesh session. The V2 side
has `AttachedRuntimeSession` and `AttachedRuntimeRecoveryReadiness` contracts, but
the Android-side `session_bridge` is not confirmed as wired to trigger these recovery
paths via AIP v3 messages.

**Impact**: Device disconnects during long tasks result in orphaned tasks in
`TaskGraphRuntime` with no recovery path.
**Recommended action**: Confirm that Android reconnect sends a `session_resume`
message that is handled by `AttachedRuntimeSessionRegistry` to resume or cancel
the orphaned task.

---

### Issue 5 — Node Discovery / Startup / Orchestration Closure Incomplete (MEDIUM)

**Description**: `NodeSystemLauncher` starts nodes and polls health, but:
- There is no guaranteed restart on node crash
- The capability graph (`CapabilityAssimilationLayer`) is populated at startup but
  not refreshed dynamically if a node restarts with different capabilities
- `CommandRouter` dispatch does not gate on capability graph (SCHED-001)

**Impact**: A crashed node is not automatically restarted; stale capability entries
may cause dispatch to route to an unavailable node.
**Recommended action**: Implement node-level restart policy in `NodeSystemLauncher`;
add capability re-registration on node health recovery; enforce capability gate in
`CommandRouter` dispatch.

---

### Issue 6 — WebRTC Not Integrated into Canonical Task Dispatch (HIGH)

**Description**: WebRTC operates as a standalone side path. No task type in the
canonical dispatch chain creates a WebRTC session. `WebRTCTaskBinding` is additive
but requires external initiation. The media chain is isolated from task/runtime
lifecycle.

**Impact**: Any use-case requiring real-time video from Android as part of a task
(e.g., VLM-guided action on live screen) cannot be expressed as a canonical task —
it requires manual out-of-band WebRTC session management.
**Recommended action**: Add `WebRTCMediaTask` or extend `TaskEnvelope` with a
media transport requirement field; add a pre-dispatch handler that creates the
WebRTC session and binds it before execution starts.

---

### Issue 7 — Memory Backflow / Cancel / Status / Recovery Not Fully Closed (MEDIUM)

**Description**: `core/openclawd_memory_backflow.py` and `core/task_memory.py` handle
result recording. However:
- Task cancel propagation from V2 → Android is defined in protocol but recovery
  on partial execution is not confirmed
- `TaskLifecycleManager.mark_failed()` triggers memory write but does not cascade
  to `AttachedRuntimeSession` cleanup or WebRTC teardown
- `ReplayFoundation` and `OperatorSurface` are wired from cross-device results but
  are not confirmed as exhaustive consumers

**Impact**: Failed or cancelled tasks may leave orphaned state in session registry,
WebRTC connections open, or memory writes incomplete.
**Recommended action**: Implement unified `LifecycleEventBroker` (see §6.7) that
subscribes to `TaskLifecycleManager` terminal events and triggers cascade cleanup.

---

### Issue 8 — Mesh Session Has No Live Coordinator Engine (HIGH)

**Description**: `MeshSessionCoordinatorState`, `MeshSession`, `MeshBarrierState`, and
`MeshSubtaskAssignment` are fully-defined contracts but no class continuously
updates them at runtime. `subtask_assignments` statuses are populated at creation
time and never updated as subtasks execute.

**Impact**: Any multi-device mesh session shows static state; barrier coordination,
merge triggers, and completion tracking are non-functional at runtime.
**Recommended action**: Implement `MeshCoordinatorRuntime` that subscribes to
`TaskGraphRuntime` subtask completion events and drives `MeshSession` state
transitions (FORMING → ACTIVE → COMPLETING → DONE).

---

## Summary

| Dimension | Current Reality | Distance to Target |
|-----------|-----------------|-------------------|
| Center cognitive spine | ✅ Fully established | Already at target |
| Android edge task execution | ⚠️ Point-task delegation works | Medium — session bridge, reconnect recovery, complex action reliability |
| Node capability dispatch | ⚠️ Nodes start; capability graph advisory | Medium — capability gate enforcement at dispatch (SCHED-001) |
| Multi-device mesh | 🔴 Contract-first, no live engine | Far — needs MeshCoordinatorRuntime |
| WebRTC / media lifecycle | 🔴 Signaling proxy works, not in task chain | Far — needs WebRTCMediaTask type + initiation chain |
| Unified lifecycle | 🔴 Three independent lifecycle modules | Far — needs LifecycleEventBroker |
| LLM independence | 🔴 Hard external dependency | Far — needs offline fallback or clear degradation contract |
| Cross-platform local execution | 🔴 Windows-only | Far — platform-agnostic execution abstraction needed |

**The most valuable next integration directions, in order:**
1. Capability gate enforcement at dispatch (SCHED-001) — unlocks correct node/device routing
2. MeshCoordinatorRuntime — makes multi-device actually functional at runtime
3. LifecycleEventBroker — closes task/session/media cascade cleanup
4. WebRTCMediaTask + initiation chain — integrates media into canonical execution
5. Session bridge reconnect recovery — closes the Android disconnect → resume gap