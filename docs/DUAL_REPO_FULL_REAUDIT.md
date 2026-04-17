# Full Re-Audit: Dual-Repo Galaxy Architecture

> **Scope**: `DannyFish-11/ufo-galaxy-realization-v2` (V2 — center-side control plane)
> and `DannyFish-11/ufo-galaxy-android` (Android device runtime).
>
> **Intent**: This is a **fresh, standalone, full architecture re-audit**. It is not
> a continuation of prior review notes. Every domain is re-examined from first
> principles against current code reality, incorporating all prior PRs up to and
> including PR-533.
>
> **Companion documents** (produced as part of this re-audit pass):
> - `docs/DUAL_REPO_GAP_MATRIX.md` — machine-readable gap matrix (supersedes all prior versions)
> - `docs/MULTI_DEVICE_RUNTIME_MATURITY.md` — per-component runtime maturity classification
> - `docs/ANDROID_PROTOCOL_MATURITY_MATRIX.md` — Android long-tail protocol maturity matrix
> - `docs/UNIFIED_SCHEDULING_AUTHORITY_MAP.md` — scheduling / routing authority chain map
> - `docs/TRUTH_PROJECTION_CONVERGENCE_MAP.md` — truth / projection convergence audit
> - `docs/COMPATIBILITY_RETIREMENT_IMPACT_MAP.md` — compatibility surface retirement impact map
> - `docs/FOLLOWUP_IMPLEMENTATION_ROADMAP.md` — prioritized follow-up implementation roadmap

---

## Table of contents

1. [System shape and prior-PR baseline](#1-system-shape-and-prior-pr-baseline)
2. [Domain 1 — Unified scheduling convergence](#2-domain-1--unified-scheduling-convergence)
3. [Domain 2 — Device admission to routable execution participant chain](#3-domain-2--device-admission-to-routable-execution-participant-chain)
4. [Domain 3 — Multi-device runtime maturity](#4-domain-3--multi-device-runtime-maturity)
5. [Domain 4 — Android long-tail protocol maturity](#5-domain-4--android-long-tail-protocol-maturity)
6. [Domain 5 — WebRTC relation to canonical task lifecycle](#6-domain-5--webrtc-relation-to-canonical-task-lifecycle)
7. [Domain 6 — Truth / projection / outward truth convergence](#7-domain-6--truth--projection--outward-truth-convergence)
8. [Domain 7 — Compatibility / transitional surface impact map](#8-domain-7--compatibility--transitional-surface-impact-map)
9. [Acceptance criteria answers](#9-acceptance-criteria-answers)
10. [Cross-domain synthesis](#10-cross-domain-synthesis)
11. [Open design questions requiring decisions](#11-open-design-questions-requiring-decisions)

---

## 1. System shape and prior-PR baseline

### 1.1 Three-tier architecture

The Galaxy system is a **distributed intelligent agent system** with three tiers:

| Tier | Repo | Role |
|------|------|------|
| **V2 control plane** | `ufo-galaxy-realization-v2` | Canonical routing, capability assimilation, task orchestration, truth/projection, governance |
| **Android device runtime** | `ufo-galaxy-android` | On-device GUI/sensor/network execution, result uplink, mesh session participation |
| **Node network** | Inside V2 repo | Domain-specific capability extension (130+ nodes: VLM, WebRTC, RAG, code, etc.) |

### 1.2 Canonical spine established by prior PRs

| Capability | Primary module | Status |
|-----------|---------------|--------|
| Sole cross-device dispatcher | `core/command_router.py` — `CommandRouter.route_envelope()` | ✅ Stable |
| Unified capability registration | `core/capability_assimilation.py` — `CapabilityAssimilationLayer` | ✅ Stable |
| Canonical device truth convergence | `core/truth_integration_layer.py` — `TruthIntegrationLayer` | ✅ Wired; consumer coverage incomplete |
| Single-device read contract | `contracts/registered_runtime_device.py` — `RegisteredRuntimeDevice` | ✅ Stable |
| Cross-device read model | `contracts/multi_device_runtime_projection.py` — `MultiDeviceRuntimeProjection` | ✅ Contract-stable; partially populated |
| Formation resolution at dispatch | `core/device_formation/formation_resolver.py` | ✅ Runtime-complete (static formation only) |
| Source vs. target semantic separation | `CommandRouter` PR-521 | ✅ Stable |
| Substrate-only sentinels on legacy paths | `galaxy_gateway/cross_device_coordinator.py`, `galaxy_gateway/device_router.py` | ✅ Enforced at code boundary |
| AIP v3.0 canonical protocol | `galaxy_gateway/protocol/aip_v3.py` | ✅ Stable |
| Compat normalisation at ingress | `galaxy_gateway/protocol/compat.py` | ✅ Stable |
| Result surfacing | `TaskGraphRuntime`, `ReplayFoundation`, `OperatorSurface` | ✅ Wired from cross-device path |

### 1.3 What this re-audit addresses

Prior audits established the canonical spine. This re-audit provides a
**definitive state-of-the-world** answer to seven unresolved questions:

1. Are node and device capabilities truly unified in scheduling?
2. Is DeviceRouter now pure substrate?
3. What is the multi-device runtime maturity, component by component?
4. What should happen to each Android long-tail protocol message?
5. What is the real relationship between WebRTC and the task lifecycle?
6. How far has truth/projection convergence progressed?
7. Which compatibility surfaces still materially affect the architecture?

---

## 2. Domain 1 — Unified scheduling convergence

### 2.1 Re-audit finding

**Definitive answer: Architecturally unified at registration; operationally partial at dispatch.**

#### Registration tier — unified

`CapabilityAssimilationLayer` (`core/capability_assimilation.py`) ingests both
node and device capability reports into a single capability graph via
`assimilate_node()` and `assimilate_device()`. Participants are stored as
`AssimilationRecord` entries keyed by `NodeParticipantKind`. The graph supports
`query_routable_executors()` and `query_network_path()` for unified executor
lookup across all participant types.

#### Dispatch tier — partially converged

`CommandRouter.route_envelope()` now invokes `query_routable_executors()` and
`query_network_path()` (wired in PR-513 / GAP-512-004). **However, this call is
advisory only**: results are logged and used to annotate the envelope's metadata.
They are **not used to gate or alter the routing decision itself**. The actual
target selection still uses the three-gate admissibility chain
(`cross_device_candidates.resolve_candidates()`), which does not consult
`CapabilityAssimilationLayer`.

Gap SCHED-001 therefore remains **open** at the enforcement level despite the
advisory wiring.

#### DeviceRouter — policy residue confirmed

`DeviceRouter.route_task()` calls `self._analyze_command()` (delegated to
`galaxy_gateway/routing/policy.py`) to derive `exec_mode` and `task_type`, and
calls `self._select_devices()` (delegated to
`galaxy_gateway/routing/device_selection.py`) for a second independent device
selection pass. Both calls contain classification and policy logic that belongs
in `CommandRouter`. Gap SCHED-003 is confirmed open.

#### ConstellationRuntime DevicePool — third selection path

`ConstellationRuntime._run_dag_loop()` calls `pool.select_device(required_capabilities=caps)`.
`DevicePool` maintains its own internal capability state. Whether it reads from
`CapabilityAssimilationLayer` is not confirmed. If it does not, this constitutes a
**third parallel selection path** (SCHED-004).

### 2.2 Authority chain trace

```
User request / agent invocation
    │
    ▼
OpenClawd._dispatch_device()
    │  (intent resolution; picks up required_capabilities)
    ▼
CommandRouter.route_envelope()          ← SOLE CANONICAL CROSS-DEVICE DISPATCHER
    │  [advisory] query_routable_executors() → logs, annotates envelope metadata
    │  [advisory] query_network_path()       → logs reachability info
    │  [enforced] cross_device_candidates.resolve_candidates()
    │       Gate 1: device_readiness   (UDM / UCM transport presence)
    │       Gate 2: device_participation (orchestration eligibility)
    │       Gate 3: target_device_validator (per-device validation)
    │  [GAP: Gate 4 — capability verification NOT joined to admissibility chain]
    │
    ▼
formation_resolver.resolve_formation()  ← static formation only
    │  [GAP: does not query CapabilityAssimilationLayer at formation time]
    │
    ▼
DeviceRouter.route_task()               ← TRANSPORT SUBSTRATE
    │  [POLICY RESIDUE: _analyze_command(), _select_devices() still present]
    │
    ▼
Transport (WebSocket / NATS) → Android / node execution
```

### 2.3 Summary table

| Question | Answer |
|----------|--------|
| Are node and device capabilities architecturally unified? | **Yes** — both flow through `CapabilityAssimilationLayer` |
| Is the capability graph consulted at dispatch time? | **Advisory only** — not a routing gate |
| Is `CommandRouter` the sole canonical dispatcher? | **Yes** |
| Is `DeviceRouter` pure substrate? | **No** — `_analyze_command` / `_select_devices` residue present |
| Are there multiple device selection paths? | **Yes** — three paths confirmed (admissibility chain, DeviceRouter, ConstellationRuntime DevicePool) |

---

## 3. Domain 2 — Device admission to routable execution participant chain

### 3.1 Re-audit finding

**The admission chain is structurally present with three confirmed gates. Capability
verification is not joined to the chain, and the Android→CapabilityAssimilation wiring
is unconfirmed.**

#### Confirmed admission chain

```
Android WebSocket connect
    │
    ▼ [CONFIRMED] device_register → UDM.register_device() + UCM.mark_connected()
    │
    ▼ [CONFIRMED] Gate 1: device_readiness — transport presence via UDM/UCM
    │
    ▼ [CONFIRMED] Gate 2: device_participation — orchestration eligibility check
    │       [GAP: does not verify reported capabilities against task requirements]
    │
    ▼ [CONFIRMED] Gate 3: target_device_validator — per-device validation
    │
    ▼ [CONFIRMED] TruthIntegrationLayer fuses state into canonical truth record
    │       [GAP: not all truth consumers read through TruthIntegrationLayer]
    │
    ▼ [CONFIRMED] Projection: RegisteredRuntimeDevice (canonical single-device read)
    │       [GAP: BodyMeshRegistry → RegisteredRuntimeDevice adapter coverage unconfirmed]
    │
    ▼ [CONFIRMED] MultiDeviceRuntimeProjection (top-level read model)
    │       [GAP: merged_results body not fully sourced from canonical chain state]
    │
    ▼ [CONFIRMED] formation_resolver — device included in formation
    │       [GAP: capability re-verification not performed at formation time]
    │
    ▼ DeviceRouter.route_task() → transport execution
```

#### Component roles

| Component | Role | Status |
|-----------|------|--------|
| `UnifiedDeviceManager` (UDM) | Canonical identity and mutable state SSOT | ✅ Stable |
| `UnifiedConnectionManager` (UCM) | Transport presence and connection lifecycle | ✅ Stable |
| `TruthIntegrationLayer` | Canonical convergence point for device truth reads | ✅ Wired; consumer coverage incomplete |
| `RegisteredRuntimeDevice` | Canonical single-device read contract | ✅ Stable |
| `MultiDeviceRuntimeProjection` | Top-level multi-device read model | ✅ Contract-stable; partially populated |
| `CapabilityAssimilationLayer` | Unified capability registration | ✅ Stable; Android→assimilation wiring unconfirmed |
| `formation_resolver` | Resolves formation group at dispatch time | ✅ Static runtime-complete |
| `BodyMeshRegistry` | In-memory mesh session registry | ✅ Partial; no persistence |

#### Android vs. bridge paths

- **Android native path**: WebSocket connect → `android_bridge.py` → `_handle_device_register()` → UDM/UCM
- **Bridge/relay path**: agent_bridge → CommandRouter (bypasses android_bridge register path)
- **Desktop path**: `system_integration.py` → UDM direct write

All paths must write to UDM. The Android path's capability forwarding to `CapabilityAssimilationLayer`
is not confirmed.

### 3.2 Critical gap: capability verification join

Gate 2 (`device_participation`) confirms orchestration eligibility but does not
verify whether the device's reported capabilities satisfy the task's
`required_capabilities`. The two checks (eligibility and capability match) are
structurally separate and never joined. A device can pass all three gates and
be included in a formation for a task whose capabilities it cannot satisfy.

---

## 4. Domain 3 — Multi-device runtime maturity

### 4.1 Re-audit finding

**Summary: Formation resolution and parallel fanout are runtime-complete. Mesh
session lifecycle, barrier coordination, role allocation, and result merge are
all contract-first. Recovery and staged execution are not implemented.**

#### Classification by component

| Component | Classification | Blocking gap |
|-----------|---------------|-------------|
| `formation_resolver.resolve_formation()` | **Runtime-complete** (static) | No dynamic rebalance |
| `CommandRouter` cross-device fanout | **Runtime-complete** | None |
| `DeviceRouter` transport dispatch | **Runtime-complete** | Policy residue (SCHED-003) |
| `BodyMeshRegistry` | **Partial** | In-memory only; no persistence |
| `session_roaming.migrate_session()` | **Partial** | Basic migrate only; no restore-from-checkpoint |
| `MeshSession` | **Contract-first** | No live runtime engine drives lifecycle transitions |
| `MeshSessionCoordinator` | **Contract-first** | State is populated at construction but never updated dynamically |
| `DeviceRoleAllocator` | **Contract-first** | Role contract exists; no runtime intelligence |
| `CrossRuntimeResultMerge` | **Contract-first** | Merge contract exists; no runtime engine |
| `session_roaming` (migration path) | **Transitional** | Two migration paths: `galaxy_gateway/session_roaming.py` (roaming) vs. `galaxy_gateway/routes/sessions.py` (REST endpoint) — caller parity unconfirmed |
| Dynamic formation rebalance | **Not implemented** | No health-driven reshaping |
| Staged mesh execution | **Not implemented** | No staged-subtask participation engine |
| Persistent mesh session store | **Not implemented** | `MeshSessionCoordinator` is stateless across restarts |
| Recovery / resume from checkpoint | **Not implemented** | No checkpoint store; no resume protocol |

#### Most critical gap: MeshSession lifecycle state machine has no driver

`MeshSessionStatus` transitions (`FORMING → ACTIVE → COMPLETING → DONE`) are
declared in `contracts/mesh_session.py` but no runtime process drives them. The
barrier coordination, assignment progress tracking, and merge trigger are all
contract declarations. Without a live coordinator engine, multi-device sessions
exist only as dispatch events — not as coordinated runtime entities.

#### Session migration split-brain risk

`galaxy_gateway/session_roaming.py` implements the roaming/migration engine.
`galaxy_gateway/routes/sessions.py` exposes REST endpoints that delegate to it.
These are correctly related (REST → roaming engine). However, `core/routes/sessions.py`
also references session migration paths. Whether both route modules converge to the
same `session_roaming` engine needs explicit confirmation; if they diverge,
migrating sessions via the core route vs. the gateway route may produce split-brain state.

For full details and maturity scores per component, see
`docs/MULTI_DEVICE_RUNTIME_MATURITY.md`.

---

## 5. Domain 4 — Android long-tail protocol maturity

### 5.1 Re-audit finding

**7 canonical types confirmed complete. 3 priority promotions needed. 3 deferred
pending design. 1 legacy path retireable after traffic analysis.**

#### Summary disposition table

| Disposition | Types |
|-------------|-------|
| **CANONICAL** — no action needed | `device_register`, `heartbeat`, `task_submit/execute`, `task_result`, `task_assign`, `action_execute`, GUI controls |
| **PROMOTE (HIGH)** — task lifecycle correctness | `task_cancel` / `task_cancel_ack`, `task_status` / `task_status_response` |
| **PROMOTE + UNIFY (HIGH)** — session migration canonical path | `session_migrate` / `session_restore` |
| **PROMOTE (MEDIUM)** — capability and wake routing | `wake_event` / `wake_route_result`, `device_capabilities` ingress wiring |
| **PROMOTE (MEDIUM)** — UI automation protocol | `ui_tree_request`, `action_sequence_execute`, `app_start` |
| **PROMOTE (MEDIUM)** — AIP v2 binary types | `ANDROID_SCREEN` (0x60), `ANDROID_INPUT` (0x61) migration to v3 |
| **DEFER** — P2P mesh topology | `peer_announce`, `mesh_topology`, `peer_exchange` |
| **DEFER** — hybrid execution design pending | `hybrid_execute` / `hybrid_result` |
| **RETIRE (after traffic analysis)** | `/ws/ufo3/{device_id}` legacy WebSocket path |

#### Most important re-classification

`task_cancel` is re-classified **HIGH** (was MEDIUM in prior audits). A user on
Android can initiate task cancellation; the center-side currently takes no action
(no `CommandRouter` consumer for `task_cancel`). Tasks continue executing after
the Android side believes they are cancelled — a correctness failure.

For full per-type documentation, see `docs/ANDROID_PROTOCOL_MATURITY_MATRIX.md`.

---

## 6. Domain 5 — WebRTC relation to canonical task lifecycle

### 6.1 Re-audit finding

**Definitive answer: WebRTC is an isolated adjacency subsystem. It is not part of
the canonical task lifecycle. No task type currently triggers WebRTC setup.**

#### Current architecture

```
TaskEnvelope (canonical task lifecycle)
    │
    ▼ CommandRouter → DeviceRouter → transport → Android execution
    │
    │                   [NO BRIDGE]
    │
WebRTC subsystem (isolated)
    │
    ▼ webrtc_proxy.py — standalone WebSocket signaling gateway
    ▼ Node_95_WebRTC_Receiver — independent node; not wired to CommandRouter
```

#### What exists

- `galaxy_gateway/webrtc_proxy.py` — signaling proxy; handles `screen_stream_start` /
  `screen_stream_data` AIP message types as a standalone gateway path
- `Node_95_WebRTC_Receiver` — WebRTC capability node; operates independently
- AIP v3 message types `screen_stream_start` / `screen_stream_data` exist but
  are not mapped to a WebRTC session lifecycle managed within `TaskEnvelope`

#### What does not exist

- A task type that explicitly triggers WebRTC session setup as a task step
- Any mechanism for `task_cancel` / `task_complete` to tear down a WebRTC session
- Lifecycle coordination between `webrtc_proxy.py` and `TaskEnvelope` / `TaskGraphRuntime`
- Video stream consumption by Node_95 scoped to a specific `task_id`

#### Correct target architecture

For tasks requiring live device camera/screen input:

```
TaskEnvelope with task_type = "screen_capture_task"
    │
    ▼ CommandRouter routes to Android device
    │
    ▼ TaskEnvelope step: screen_stream_start → triggers webrtc_proxy.setup_session(task_id)
    │
    ▼ WebRTC session established; stream scoped to task_id
    │
    ▼ Node_95 consumes stream as task-scoped resource
    │
    ▼ task_cancel / task_complete → webrtc_proxy.teardown_session(task_id)
```

None of this integration exists today. WebRTC sessions are started by direct
WebSocket connection outside the task lifecycle.

### 6.2 Impact classification

**WebRTC is ADJACENT** to the canonical task lifecycle. For any task that requires
real-time visual input from Android devices, the current architecture silently
fails to provide the required input. Severity: HIGH for use cases requiring live
screen/camera input; LOW for use cases that do not.

---

## 7. Domain 6 — Truth / projection / outward truth convergence

### 7.1 Re-audit finding

**Three truth surfaces still co-exist. Projection endpoint convergence is partial.
Android local state has no reconciliation protocol with V2 outward truth.**

#### Three co-existing truth surfaces

| Surface | Module | Authority | Status |
|---------|--------|-----------|--------|
| `TruthIntegrationLayer` | `core/truth_integration_layer.py` | Canonical device truth convergence point | Wired from canonical paths; not all consumers use it |
| `MultiDeviceRuntimeProjection` | `contracts/multi_device_runtime_projection.py` | Top-level multi-device read model | Contract-stable; `merged_results` partially populated |
| Desktop projection / status board | `desktop_projection/` + `status_board_v2` | Display representation | Partially independent; does not always consume `NetworkTopologyRuntime` |

#### Projection endpoint convergence

`ProjectionSurfaceBridge.enrich_runtime_projection()` and `compile_outward_truth()`
are called from `core/routes/projection.py` at the main projection endpoints.
This is the correct convergence pattern. However:

- Not all projection endpoint code paths call `enrich_runtime_projection()` — some
  fallback paths return `outward_truth: null`
- `MultiDeviceRuntimeProjection.merged_results` body is not confirmed as fully
  sourced from canonical chain state (ADMIT-002)
- Desktop status board surfaces assemble some views independently, not always
  consuming the same `NetworkTopologyRuntime` state

#### Android local state divergence

Android-side state (session snapshot, target readiness, current task phase) has no
reconciliation protocol with V2 outward truth. V2 may project a device as "active
in task" while the Android side has already completed, cancelled, or failed. This
is a **silent divergence risk** (TRUTH-005). No design decision has been made on
whether V2 outward truth supersedes Android local state or whether they are
independent with explicit sync events.

#### Multi-model topology gap

`ContinuumState` / `TopologyRoutePlan` for multi-model intelligent routing has no
canonical runtime authority equivalent to `NetworkTopologyRuntime`. Model routing
decisions are not reflected in the unified truth surface (TRUTH-003).

#### Is `MultiDeviceRuntimeProjection` canonical or transitional?

`MultiDeviceRuntimeProjection` is **canonical and stable** as a contract. It is the
designated top-level read model for multi-device state. Its transitional aspect is
that `merged_results` population is partial — it is not yet fully assembled from
all canonical chain inputs.

For full convergence map, see `docs/TRUTH_PROJECTION_CONVERGENCE_MAP.md`.

---

## 8. Domain 7 — Compatibility / transitional surface impact map

### 8.1 Re-audit finding

**Most legacy surfaces have been retired or gated. Remaining active risks are:
DeviceRouter policy residue, CapabilityRegistry misuse risk, CrossDeviceCoordinator
sentinel bypass, and Android REST compat aliases with no retirement timeline.**

#### Impact classification

| Surface | Classification | Action required |
|---------|---------------|----------------|
| `task_router.py` / `TaskScheduler` | **Harmless residue** — retired in PR-516 | Confirm file removed from disk |
| `cross_device_coordinator.py` | **Still meaningful path** — substrate-only sentinel enforced; `LEGACY_DISPATCH` on incorrect use | Add monitoring counter on `LEGACY_DISPATCH` |
| `agent_bridge.py` | **Still meaningful path** — delegation surface; may bypass full admissibility chain | Audit delegation path against canonical gates |
| `CapabilityRegistry` | **High misuse risk** — gated for device-local bookkeeping; routing must use `CapabilityAssimilationLayer` | Enforce routing guard; add lint/test |
| `DeviceRouter._analyze_command()` + `_select_devices()` | **High misuse risk** — policy residue that can produce divergent routing decisions | Extract to `CommandRouter`; retire from DeviceRouter |
| Android REST compat aliases | **Immediately retireable (after traffic analysis)** — `/api/devices/register`, `/api/devices/list` | Traffic analysis; deprecation header; then retire |
| `/ws/ufo3/{device_id}` legacy WebSocket | **Immediately retireable (after traffic analysis)** | Traffic analysis; then retire |
| `LocalAgentRuntime` | **Harmless residue** — gated; server-side planning retired | Low-priority cleanup |
| `ProjectionEngine` | **Transitional** — gated; must delegate to `ProjectionSurfaceBridge` | Confirm delegation enforced; then retire |
| Long-tail compat registries | **Harmless residue** — normalised at ingress by `protocol/compat.py` | Keep compat layer; retire source types on schedule |

For full impact map with per-surface analysis, see `docs/COMPATIBILITY_RETIREMENT_IMPACT_MAP.md`.

---

## 9. Acceptance criteria answers

| # | Criterion | Answer |
|---|-----------|--------|
| 1 | Are node and device capabilities truly unified in canonical scheduling? | **Partially.** Unified at registration (`CapabilityAssimilationLayer`). Advisory-only at dispatch; not a routing gate. Three parallel selection paths exist. |
| 2 | Is `DeviceRouter` now substrate-only? | **No.** `_analyze_command` (policy) and `_select_devices` (selection) are still present. They are delegated to `galaxy_gateway/routing/` modules but remain in the dispatch path. |
| 3 | Which multi-device runtime surfaces are complete vs partial vs contract-first vs placeholder? | Formation resolution: **runtime-complete**. BodyMeshRegistry, session_roaming: **partial**. MeshSession, MeshSessionCoordinator, DeviceRoleAllocator, CrossRuntimeResultMerge: **contract-first**. Dynamic rebalance, staged execution, persistence, recovery: **not implemented**. |
| 4 | Which Android long-tail messages should be promote / retire / defer / replace? | `task_cancel` / `task_status`: **PROMOTE (HIGH)**. `session_migrate`: **PROMOTE + UNIFY (HIGH)**. `wake_event`, UI automation types, AIP v2 binary: **PROMOTE (MEDIUM)**. `peer_announce` / mesh types: **DEFER**. `hybrid_execute`: **DEFER**. Legacy WebSocket path: **RETIRE**. |
| 5 | Is WebRTC canonical, adjacent, or only partially connected? | **Adjacent / isolated.** No task type triggers WebRTC setup. No lifecycle coordination with `TaskEnvelope`. |
| 6 | How far has truth/projection convergence progressed? | **Partial.** `TruthIntegrationLayer` is wired from canonical paths. `compile_outward_truth()` is called from main projection endpoints. But: fallback paths return null truth; desktop status board is partially independent; Android local state has no sync protocol; `MultiDeviceRuntimeProjection.merged_results` is partially populated. |
| 7 | Which compatibility surfaces still materially affect the architecture? | `DeviceRouter` policy residue (SCHED-003), `CapabilityRegistry` misuse risk, `CrossDeviceCoordinator` sentinel bypass, Android REST/WS compat aliases. |
| 8 | Prioritized follow-up implementation roadmap? | See `docs/FOLLOWUP_IMPLEMENTATION_ROADMAP.md`. |

---

## 10. Cross-domain synthesis

### 10.1 The broken admission → scheduling → runtime chain

The three foundational conditions for distributed agent operation are sequentially
dependent. The chain breaks in two places:

```
Device connect
    │
    ▼ [PARTIAL] Gates 1–3 admissibility checks (transport, eligibility, validation)
    │
    ▼ [GAP] Capability verification NOT joined to admission gates → devices admitted
    │        without capability match against task requirements
    │
    ▼ [GAP] CommandRouter capability graph query is advisory only → routing bypasses
    │        unified capability authority
    │
    ▼ [PARTIAL] Formation resolved statically at dispatch time (no dynamic rebalance)
    │
    ▼ [GAP] No live runtime engine for MeshSession / MeshSessionCoordinator
    │        → lifecycle transitions are declared but inert
    │
    ▼ [GAP] No dynamic rebalancing or staged subtask execution
    │
    ▼ [GAP] No cross-device result merge engine (CrossRuntimeResultMerge is contract-first)
```

Until Gap 1 (capability join) and Gap 3 (live MeshSession engine) are resolved, the
system can **route tasks to multiple devices in parallel** but cannot **coordinate a
true multi-device session with barrier synchronization, role handoff, or result merge**.

### 10.2 The Android protocol → admission gap

```
Android connect
    │
    ▼ [CONFIRMED] device_register → UDM/UCM
    │
    ▼ [UNCONFIRMED] device_capabilities auto-forwarded to CapabilityAssimilationLayer
    │
    ▼ [GAP] task_cancel / task_status NOT propagated to CommandRouter
    │        → correctness failure for cancellation
    │
    ▼ [GAP] session_migrate still needs canonical path unification
    │
    ▼ [GAP] WebRTC not tied to task lifecycle
    │        → tasks requiring live visual input silently receive no stream
```

### 10.3 Maturity summary

| Domain | Maturity | Key gap |
|--------|---------|---------|
| Center control plane (CommandRouter, DeviceRouter) | **Medium-high** | DeviceRouter policy residue; advisory-only capability query |
| Device admission chain (Gates 1–3, UDM, UCM, TIL) | **Medium** | Capability verification not joined; Android→assimilation unconfirmed |
| Multi-device runtime (formation, MeshSession, role, merge) | **Low-medium** | MeshSession has no live runtime engine |
| Android protocol (AIP v3, compat, long-tail) | **Medium** | task_cancel HIGH gap; session_migrate needs unification |
| WebRTC integration | **Low** | Fully isolated from task lifecycle |
| Truth/projection convergence | **Medium** | Fallback paths; Android state not reconciled |
| Compatibility surfaces | **Medium** | DeviceRouter residue; CapabilityRegistry misuse risk |

---

## 11. Open design questions requiring decisions

The following questions require explicit architectural decisions before implementation
PRs can proceed:

| Q# | Question | Required decision |
|----|----------|------------------|
| Q1 | Should capability verification be joined into the admissibility chain as Gate 4, or remain a separate post-admission check? | Determines implementation path for SCHED-001 / ADMIT-001 |
| Q2 | Should `DevicePool` in `ConstellationRuntime` delegate to `CapabilityAssimilationLayer`? | If yes, clarifies SCHED-004 |
| Q3 | What is the canonical migration path for session_migrate — `galaxy_gateway/session_roaming.py` or `core/routes/sessions.py`? | Blocks MESH-005 resolution |
| Q4 | Does Android local state (snapshot, readiness, task phase) converge into V2 outward truth, or are they independent with explicit sync events? | Determines TRUTH-005 resolution approach |
| Q5 | Is WebRTC-task lifecycle integration near-term (triggers PROMOTE) or longer-term (DEFER)? | Changes WEBRTC-001/002 priority |
| Q6 | What is the target retirement date for AIP v2 binary types (`ANDROID_SCREEN` 0x60 / `ANDROID_INPUT` 0x61)? | Unblocks compat retirement timeline |
| Q7 | Should `LEGACY_DISPATCH` sentinels emit observable metrics, or log-only? | Determines observability gap resolution approach |

---

*This document is part of the full dual-repo architecture re-audit. See companion
documents listed at the top for detailed per-domain matrices and maps.*
