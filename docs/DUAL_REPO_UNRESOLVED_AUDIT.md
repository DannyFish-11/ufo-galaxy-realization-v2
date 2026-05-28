> ## ⚠️ SUPERSEDED — NOT AUTHORITATIVE
>
> **This document has been superseded by [`DUAL_REPO_GAP_MATRIX.md`](DUAL_REPO_GAP_MATRIX.md).**
> The content below is preserved for historical reference only.
> For the current structured gap matrix, see [`DUAL_REPO_GAP_MATRIX.md`](DUAL_REPO_GAP_MATRIX.md).

---

# Dual-Repo Unresolved Architecture Audit

> **Complete dual-repo linked total audit / clarification PR**
>
> Primary repo: `DannyFish-11/ufo-galaxy-realization-v2` (V2 — center-side control plane)
> Cross-repo reference: `DannyFish-11/ufo-galaxy-android` (Android device runtime)
>
> **Purpose**: Turn remaining architecture unknowns into a concrete, structured
> gap map that supports complete planning of subsequent implementation PRs.
>
> **Companion documents**:
> - `docs/DUAL_REPO_GAP_MATRIX.md` — machine-readable gap matrix with all 40 gaps
> - `docs/MULTI_DEVICE_RUNTIME_MATURITY.md` — per-component maturity classification
> - `docs/ANDROID_PROTOCOL_MATURITY_MATRIX.md` — Android long-tail protocol assessment
> - `docs/UNIFIED_SCHEDULING_AUTHORITY_MAP.md` — scheduling/routing authority map

---

## System shape overview

The Galaxy system is a distributed intelligent agent system with three tiers:

1. **V2 (center-side control plane)** — `ufo-galaxy-realization-v2`: governs capability routing, device admission, task orchestration, truth/projection, and canonical dispatch authority.
2. **Android runtime executor** — `ufo-galaxy-android`: connected device runtime that receives task assignments, executes on-device actions, reports results, and optionally participates in multi-device mesh sessions.
3. **Node network** — specialized capability nodes (Node_95 WebRTC, Node_90 VLM, etc.) that extend V2's execution reach with domain-specific capabilities.

The prior work (PR-506 through PR-532) established the core canonical spine:
- `CommandRouter.route_envelope()` as sole cross-device dispatch authority
- `CapabilityAssimilationLayer` as unified capability registration for all participant types
- `TruthIntegrationLayer` as canonical device truth convergence point
- `MultiDeviceRuntimeProjection` as canonical top-level multi-device read projection
- `RegisteredRuntimeDevice` as canonical single-device read contract
- Formation resolution (`DeviceFormationGroup`) at every cross-device dispatch
- Control semantic separation (source vs. target device IDs)
- Cross-device result surfacing into `TaskGraphRuntime`, `ReplayFoundation`, `OperatorSurface`

**What remains unresolved** is documented in this audit.

---

## Investigation 1: Unified Scheduling Convergence

### Finding

Node capabilities and device capabilities are **architecturally unified** in
`CapabilityAssimilationLayer` — both nodes and devices are assimilated as
`AssimilationRecord` entries with appropriate `NodeParticipantKind`. The
capability graph covers both.

However, convergence is **operationally partial** at the routing layer:
`CommandRouter` routing decisions do not yet invoke
`query_routable_executors()` / `query_network_path()` from
`core/capability_network_runtime_policy.py` before selecting dispatch targets
(GAP-512-004, MEDIUM, PR-514 target per `RESIDUAL_GAP_MAP.md`).

This means the unified capability graph is built and maintained, but the
hot-path dispatch in `CommandRouter` still selects devices without consulting
it. The routing decision is valid (devices are reachable via UCM/UDM) but it
bypasses the capability+network co-selection authority.

### CommandRouter — is it truly performing unified node-vs-device target selection?

`CommandRouter.route_envelope()` is the sole canonical dispatcher, but:

1. It branches into local path (capability bus / orchestrator) or cross-device path.
2. The cross-device path uses the admissibility chain
   (`cross_device_candidates.resolve_candidates()`) for device eligibility, not
   a capability-graph query.
3. `CapabilityAssimilationLayer.query_routable_executors()` exists precisely for
   this purpose but is not yet called by `CommandRouter`.

**Conclusion**: `CommandRouter` is the unified **orchestration** authority, but
it does not yet perform unified **capability-graph** based target selection.

### DeviceRouter — substrate or policy?

`DeviceRouter.route_task()` is sentinel-enforced as substrate-only
(`DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY`). However, it legitimately
performs formation resolution and command analysis. The classification is:

> **Canonical dispatch substrate with formation-aware routing** — more than
> pure transport, but not a policy authority. The boundary is well-governed.

See `docs/UNIFIED_SCHEDULING_AUTHORITY_MAP.md` for the complete authority map.

---

## Investigation 2: Device Admission to Execution Qualification Chain

### Confirmed chain

The full device admission chain is:

```
Device connects (WebSocket to /ws/android/{device_id} or /ws/device/{device_id})
    │
    ▼ UCM (UnifiedConnectionManager)
    ├── Records active WebSocket connection
    ├── Marks device as connected/routable
    │
    ▼ AndroidBridge._handle_device_register()
    ├── Creates/updates UDM (UnifiedDeviceManager) record
    ├── Records capabilities from device_register payload
    ├── CapabilityAssimilationLayer.assimilate_device() [CROSS-004: not confirmed as automatic]
    │
    ▼ TruthIntegrationLayer.resolve_device_truth(device_id)
    ├── UCM → is_connected, is_routable
    ├── UDM → is_registered, is_online, capabilities
    ├── Compat cache (last resort)
    └── Returns CanonicalDeviceTruth
    │
    ▼ RegisteredRuntimeDevice (canonical single-device read projection)
    ├── Adapters from UDM, DeviceRouter, AndroidBridge, DeviceRegistry
    │
    ▼ Admissibility chain (for cross-device routing eligibility):
    ├── Layer 1: device_readiness — transport presence / routability
    ├── Layer 2: device_participation — orchestration eligibility + roles
    ├── Layer 3: target_device_validator — per-device pre-dispatch validation
    │
    ▼ cross_device_candidates.resolve_candidates()
    ├── Gate 1: readiness check
    ├── Gate 2: orchestration eligibility (if required)
    └── Returns CrossDeviceCandidateResolution
    │
    ▼ formation_resolver.resolve_formation()
    ├── DeviceFormationGroup (source/primary/support/relay/observer)
    ├── FormationPolicy (barrier posture, merge confirmation)
    │
    ▼ DeviceRouter.route_task() → device execution
```

### Android vs. other device paths

**Android path**:
- Primary: `POST /ws/android/{device_id}` WebSocket connection
- Registration: `device_register` AIP v3 message → `AndroidBridge._handle_device_register()`
- Capability report: `device_capabilities` or `capability_report` AIP type
- Heartbeat: `heartbeat` message
- Task assignment: `task_assign` S→C message

**Compat paths** (still active):
- `/ws/device/{device_id}` — alias
- `/ws/ufo3/{device_id}` — legacy UFO3 path (retire candidate)
- `POST /api/devices/register` — REST compat alias

### Unresolved gaps

- **CROSS-004** (LOW): It is not confirmed that Android capability reports
  (`device_capabilities` message) are automatically forwarded into
  `CapabilityAssimilationLayer.assimilate_device()`. If this is not wired,
  devices appear in UDM/UCM but not in the canonical capability graph.
- **ADMIT-001** (MEDIUM): `TruthIntegrationLayer` is the canonical truth
  convergence point but not confirmed as the single entry for all consumers.
- **ADMIT-002** (MEDIUM): Multi-device projection's `merged_results` body is
  partially enriched from canonical chain (PR-522) but not fully.

---

## Investigation 3: Multi-Device Runtime Maturity

### Summary classification

| Component | Maturity | Key gap |
|-----------|----------|---------|
| `formation_resolver` | ✅ Runtime-complete (static) | No dynamic rebalance |
| `CommandRouter` cross-device dispatch | ✅ Runtime-complete | — |
| `DeviceRouter` substrate | ✅ Runtime-complete | — |
| Parallel fanout | ✅ Runtime-complete | — |
| `body_mesh_registry` | ⚠️ Partial | No persistence, no auto-wiring |
| `session_roaming` | ⚠️ Partial | Dual implementations |
| `MeshSession` | ⚠️ Contract-first/partial | No lifecycle engine |
| `MeshSessionCoordinator` | ⚠️ Contract-first | No live coordinator engine |
| `device_role_allocator` | ⚠️ Contract-first | No capability-aware allocation |
| Formation dynamic rebalance | ❌ Not implemented | — |
| Staged mesh participation | ❌ Not implemented | — |
| Persistent mesh session store | ❌ Not implemented | — |
| Recovery / resume from checkpoint | ❌ Not implemented | — |

See `docs/MULTI_DEVICE_RUNTIME_MATURITY.md` for full per-component analysis.

---

## Investigation 4: Android Long-Tail Protocol Maturity

### High-severity items

1. **SESSION_MIGRATE / session_restore** (PROTO-001, HIGH): Still in AIP v2
   binary format. Two competing center-side implementations exist
   (`galaxy_gateway/session_roaming.py` and `core/routes/sessions.py`). Must
   be unified and promoted to AIP v3 JSON.

2. **task_cancel / task_status** (PROTO-002, HIGH): Both handled by
   `_handle_forward_log` catch-all — received, logged, not acted upon. No
   canonical cancellation or status propagation to `CommandRouter`. This means
   Android devices cannot reliably cancel or query task status.

3. **Android canonical chain audit** (CROSS-001, HIGH): It is not confirmed
   that Android-initiated task_submit / task_execute flows walk the full
   admission chain on the Android side. The delegated execution signal ingress
   (PR-16+) is well-defined for delegated tasks, but the Android-origin
   execution path needs explicit verification.

### Disposition summary

| Category | Disposition | Count |
|----------|-------------|-------|
| PROMOTE (high-priority) | `SESSION_MIGRATE`, `task_cancel/status`, `WAKE_EVENT`, action handlers | 5 types |
| PROMOTE (medium-priority) | AIP v2 binary `ANDROID_SCREEN`/`ANDROID_INPUT`, `RECOVERY_*` | 3 types |
| DEFER | `HYBRID_EXECUTE`, `RAG_QUERY`, `CODE_EXECUTE`, `PEER_ANNOUNCE`, `LOCK/UNLOCK` | 5 types |
| RETIRE | `/ws/ufo3/`, legacy REST compat aliases, `_handle_forward_log` pattern | 3 surfaces |
| Already canonical | `delegated_execution_signal`, core task/register/heartbeat types | 10+ types |

See `docs/ANDROID_PROTOCOL_MATURITY_MATRIX.md` for full type-by-type analysis.

---

## Investigation 5: WebRTC and Canonical Task Lifecycle Relationship

### Finding

WebRTC is an **adjacent subsystem**, not part of the canonical task lifecycle.

**What exists**:
- `galaxy_gateway/webrtc_proxy.py` — gateway-level signaling proxy (Android ↔ Node_95)
- `nodes/Node_95_WebRTC_Receiver/main.py` — receives and processes video streams from Android
- REST endpoint: `GET /api/v1/webrtc/endpoint` — discovery
- WebSocket: `WS /ws/webrtc/{device_id}` — signaling proxy

**What is missing**:
- No task type in AIP v3 that explicitly triggers WebRTC session setup as part of a task lifecycle
- No `CommandRouter` integration — WebRTC sessions start via direct WebSocket connection, not via `TaskEnvelope`
- No signaling lifecycle tied to `TaskGraphRuntime` — WebRTC session open/close does not create task graph events
- `Node_95_WebRTC_Receiver` receives video frames but operates independently — no canonical capability routing for "tasks that require device camera input"

**What would integration look like**:
```
Task (task_type="vision_analysis", exec_mode="android_camera")
    → CommandRouter (routes to device with camera capability)
    → TaskEnvelope carries webrtc_session_id
    → DeviceRouter triggers WebRTC setup on target device
    → Node_95 receives video stream
    → VLM node (Node_90) processes frames
    → Result surfaced via CrossDeviceChainSingleton
```

This flow does not exist today. WebRTC and the AIP/task chain are currently
only loosely coexisting.

**Gaps**: WEBRTC-001, WEBRTC-002, WEBRTC-003 (see `DUAL_REPO_GAP_MATRIX.md`).

---

## Investigation 6: Truth / Projection / Outward Truth Convergence

### V2-side truth hierarchy (established)

```
UCM (connection/presence authority)
UDM (registration/state/capabilities authority)
    │
    ▼
TruthIntegrationLayer.resolve_device_truth()
    │
    ▼
RegisteredRuntimeDevice (canonical single-device read projection)
    │
    ▼
MultiDeviceRuntimeProjection (canonical top-level multi-device read projection)
    │  aggregates: registered devices, session/handoff/dispatch/coordination/result state
    ▼
ProjectionSurfaceBridge.enrich_runtime_projection()
    │
    ▼
Operator tooling, observability, status boards
```

### How far has convergence progressed?

**Converged (stable)**:
- UCM + UDM as dual truth authorities — fully defined with conflict-resolution policy
- `TruthIntegrationLayer` as canonical fusion point — 28 tests, all passing
- `RegisteredRuntimeDevice` as sole canonical single-device read contract (PR-5/PR-29)
- `MultiDeviceRuntimeProjection` as sole canonical top-level multi-device projection (PR-38/PR-8)
- Cross-device results surfaced into `CrossDeviceChainSingleton`, `TaskGraphRuntime`, `ReplayFoundation`, `OperatorSurface` (PR-517 through PR-522, all 8 gaps resolved)

**Partially converged (gaps remain)**:
- `ProjectionSurfaceBridge` is wired (PR-511) but not all projection endpoints use it (GAP-512-003, GAP-512-005 — TRUTH-001)
- `MultiDeviceRuntimeProjection.merged_results` body partially enriched (PR-522) but not fully sourced from canonical chain (TRUTH-004)
- Desktop projection maintains independent topology view (GAP-512-008 — TRUTH-002)

**Not yet converged**:
- Model/provider topology — still expressed only through `ContinuumState`/`TopologyRoutePlan`, no canonical authority equivalent to `NetworkTopologyRuntime` (GAP-512-009 — TRUTH-003)
- Android-side truth — Android maintains local runtime state (session snapshot, target readiness) with no explicit reconciliation protocol against V2 outward truth (TRUTH-005, CROSS-002)

### Is `MultiDeviceRuntimeProjection` stable or transitional?

`MultiDeviceRuntimeProjection` is **stable and canonical** as the top-level read projection (sentinel: PR-8 canonical closure). It is not transitional. However, the content of its fields (particularly `merged_results` and device entries) is not yet fully populated from canonical chain state — the shell is stable but the content completeness is PARTIAL.

---

## Investigation 7: Compatibility and Transitional Surface Impact Map

### Retired surfaces (post PR-516)

| Surface | Status | Risk |
|---------|--------|------|
| `GatewayCapabilityRegistry` | RETIRED | Low — replacement is clear |
| `TaskDecomposer` / `IntelligentTaskPlanner` | RETIRED | Low — canonical replacement is `TaskGraph` |
| `TaskRouter` / `TaskScheduler` | RETIRED | Low — canonical replacement is `CommandRouter` |
| `legacy_projection_contract` | RETIRED | Low — replacement is `ProjectionSurfaceBridge` |

### Gated surfaces (active, governed)

| Surface | Status | Risk |
|---------|--------|------|
| `CapabilityRegistry` | GATED | **Medium** — boundary between local bookkeeping and routing decisions must not blur |
| `LocalAgentRuntime` | GATED | Low — device-side sandbox role is legitimate |
| `ProjectionEngine` | GATED | Low — must delegate to `ProjectionSurfaceBridge` |

### Active compatibility surfaces (still on meaningful paths)

| Surface | Status | Risk |
|---------|--------|------|
| `CrossDeviceCoordinator` | Substrate-only (sentinel-enforced) | Medium — external bypass still theoretically possible |
| `AgentBridge` | Transitional handoff layer | Medium — preferred over coordinator but not fully canonical |
| Legacy REST compat routes | Still served | Low — no retirement timeline |
| `/ws/ufo3/`, `/ws/android` broadcast | Still served | Low — legacy client path |
| AIP v2 binary protocol | Used for WAKE_EVENT, SESSION_MIGRATE, etc. | Medium — blocking Android protocol promotions |

### Surfaces with high misuse risk

| Surface | Risk | Action |
|---------|------|--------|
| `CapabilityRegistry` (routing decisions) | **High** — developers may route through it instead of `CapabilityAssimilationLayer` | Add runtime assertion / guardrail |
| `CrossDeviceCoordinator` direct calls | Medium | Sentinel warning exists; consider hard-fail option |
| `_handle_forward_log` catch-all | Medium — hides missing implementations | Promote individual handlers or make gap explicit |

---

## Acceptance criteria answers

**AC1** — Is node and device capability scheduling truly unified in practice?
> **Architecturally yes, operationally partial.** Both converge in `CapabilityAssimilationLayer`. `CommandRouter` is not yet consulting it at dispatch time (GAP-512-004).

**AC2** — Is `DeviceRouter` cleanly reduced to substrate responsibility?
> **Substantially yes.** Sentinel-enforced substrate-only boundary. Residual formation-resolution logic is architecture-correct. No high-risk policy leakage.

**AC3** — Which multi-device runtime pieces are runtime-complete vs partial vs contract-only?
> See `MULTI_DEVICE_RUNTIME_MATURITY.md`. Short: formation_resolver + CommandRouter dispatch + DeviceRouter substrate are runtime-complete. MeshSession + MeshSessionCoordinator are contract-first. Dynamic rebalance / staged mesh / persistent session are not implemented.

**AC4** — Which Android long-tail message types should be promoted / retired / deferred?
> See `ANDROID_PROTOCOL_MATURITY_MATRIX.md`. High-priority promotes: SESSION_MIGRATE (AIP v3), task_cancel/status handlers. High-priority defers: HYBRID_EXECUTE, RAG_QUERY, PEER_ANNOUNCE.

**AC5** — Is WebRTC actually integrated with the canonical task lifecycle?
> **No.** WebRTC is an adjacent subsystem. No task type triggers WebRTC setup. No `CommandRouter`/`TaskEnvelope` integration. Three gaps (WEBRTC-001, WEBRTC-002, WEBRTC-003) must be closed for integration.

**AC6** — How far has truth/projection convergence progressed for multi-device state?
> **Core truth hierarchy is stable.** UCM+UDM → TruthIntegrationLayer → RegisteredRuntimeDevice → MultiDeviceRuntimeProjection is established. Cross-device result surfacing is resolved (PR-519/522). Remaining gaps: projection endpoint completeness, desktop projection independence, model topology authority, Android-side truth alignment.

**AC7** — Which remaining compatibility surfaces still materially affect the architecture?
> `CapabilityRegistry` (routing risk), `CrossDeviceCoordinator` (bypass risk), AIP v2 binary protocol (blocks promotions), `AgentBridge` (transitional), `_handle_forward_log` catch-all (hides gaps). See Investigation 7 above.

**AC8** — What is the prioritized next implementation PR sequence?
> See Prioritized Follow-Up Roadmap below.

---

## Prioritized Follow-Up Roadmap

### Group 1: Scheduling / Truth Convergence Work

| Priority | PR title | Gaps closed | Value |
|----------|----------|-------------|-------|
| P1 | CommandRouter capability-graph integration | SCHED-001 (GAP-512-004) | `CommandRouter` routing decisions consume canonical capability+network truth |
| P2 | Projection endpoint completeness | TRUTH-001, TRUTH-004 (GAP-512-003, GAP-512-005, GAP-517-008) | All projection surfaces consume `ProjectionSurfaceBridge`; `merged_results` fully canonical |
| P3 | Desktop projection authority clarification | TRUTH-002 (GAP-512-008) | Remove independent topology view from desktop surfaces |
| P4 | Model topology canonical authority | TRUTH-003 (GAP-512-009) | Dedicated model-topology runtime authority |
| P5 | Android capability ingress wiring | CROSS-004 | `device_capabilities` messages auto-assimilate into `CapabilityAssimilationLayer` |

### Group 2: Multi-Device Runtime Systemization Work

| Priority | PR title | Gaps closed | Value |
|----------|----------|-------------|-------|
| P1 | MeshSession lifecycle engine | MESH-001, MESH-002 | Live coordinator driving `MeshSessionStatus` transitions from `TaskGraphRuntime` events |
| P2 | Session migration unification | MESH-005, PROTO-001 | Single canonical session migrate path; AIP v3 JSON SESSION_MIGRATE |
| P3 | BodyMeshRegistry persistence + auto-wiring | MESH-003 | Durable mesh registry; auto-register on device connect |
| P4 | Capability-aware role allocation | MESH-004 | `DeviceRoleAllocator` consumes `CapabilityAssimilationLayer` |
| P5 | Formation dynamic rebalance | MESH-006 | Reshaping engine for device disconnect / health degradation mid-session |
| P6 | Staged mesh execution | MESH-008 | Dependency-ordered subtask graph execution across devices |

### Group 3: Compatibility Retirement Work

| Priority | PR title | Gaps closed | Value |
|----------|----------|-------------|-------|
| P1 | task_cancel / task_status canonical handlers | PROTO-002 | Android can reliably cancel and query task status |
| P2 | WAKE_EVENT / WAKE_ROUTE_RESULT AIP v3 promotion | PROTO-003 | Wake event in canonical protocol |
| P3 | AIP v2 binary migration | PROTO-005 | `ANDROID_SCREEN`, `ANDROID_INPUT` → AIP v3 JSON |
| P4 | Action protocol handlers | PROTO-004 | `ui_tree_request`, `action_sequence_execute`, `app_start` promoted from catch-all |
| P5 | Legacy compat path retirement | COMPAT-001, PROTO-007 | `/ws/ufo3/` retired; legacy REST aliases removed after traffic analysis |
| P6 | CapabilityRegistry routing guardrail | COMPAT-002 | Runtime assertion prevents routing decisions via CapabilityRegistry |

### Group 4: High-Value Protocol / Runtime Feature Completion Work

| Priority | PR title | Gaps closed | Value |
|----------|----------|-------------|-------|
| P1 | Android canonical chain audit | CROSS-001 | Verify Android-initiated flows walk full admission chain |
| P2 | WebRTC-task lifecycle integration | WEBRTC-001, WEBRTC-002, WEBRTC-003 | Camera tasks trigger WebRTC sessions via `CommandRouter` |
| P3 | Android-V2 truth reconciliation | CROSS-002, TRUTH-005 | Android local state reconciled against V2 outward truth |
| P4 | Real-device E2E integration test suite | CROSS-003 | E2E tests requiring actual Android device connection |
| P5 | Hybrid execution design | PROTO-006 | `HYBRID_EXECUTE` with real Android co-execution |
