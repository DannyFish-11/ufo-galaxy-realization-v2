# Re-Audit: Unresolved Dual-Repo Architecture Gaps — Fresh Pass 2

> **Scope**: `DannyFish-11/ufo-galaxy-realization-v2` (V2 — center-side control plane) and
> `DannyFish-11/ufo-galaxy-android` (Android device runtime).
>
> **Intent**: This is a fresh, independent re-audit pass. It supersedes and replaces the
> previous review effort. It does not assume prior conclusions are final; each domain
> is re-examined from first principles against current code reality.
>
> **Companion documents** (produced as part of this re-audit):
> - `docs/REAUDIT_GAP_MATRIX_V2.md` — structured gap matrix v2
> - `docs/REAUDIT_MULTI_DEVICE_MATURITY_V2.md` — multi-device runtime maturity matrix v2
> - `docs/REAUDIT_ANDROID_PROTOCOL_V2.md` — Android long-tail protocol maturity v2
> - `docs/REAUDIT_SCHEDULING_AUTHORITY_V2.md` — scheduling / authority map v2
> - `docs/REAUDIT_FOLLOWUP_ROADMAP_V2.md` — prioritized follow-up roadmap v2

---

## 1. Purpose and scope

The Galaxy system is a **distributed intelligent agent system** where:

- V2 is the **center-side control plane** — canonical routing, capability assimilation,
  task orchestration, truth / projection surfaces.
- Android runtime is the **connected device executor** — receives task assignments,
  executes on-device GUI/sensor/network actions, reports results, participates in
  multi-device mesh sessions.
- Nodes (Node_95 WebRTC, Node_90 VLM, etc.) extend the execution reach with
  domain-specific capabilities.

For the system to work as a **distributed intelligent agent** it must satisfy three
foundational conditions **simultaneously**:

1. **Device admission** — devices (Android, desktop, sensor nodes) must enter a
   routable execution chain: transport presence → orchestration eligibility →
   capability verification → formation membership.
2. **Node-device scheduling unity** — routing decisions for local nodes and remote
   devices must derive from the same capability graph so that the "best executor"
   selection is truly unified.
3. **Multi-device runtime** — once two or more devices are admitted, a runtime
   engine must coordinate their execution: barrier synchronization, role handoff,
   parallel fanout, result merge, session roaming / migration.

Prior work (PR-506 through PR-532) established the canonical spine for conditions 1
and 2. Condition 3 remains **contract-first** in most components. This re-audit
produces a precise state-of-the-world map.

---

## 2. What was established in prior PRs (reference baseline)

| Capability | Primary module | Status |
|------------|---------------|--------|
| Sole canonical cross-device dispatcher | `CommandRouter.route_envelope()` | ✅ Stable |
| Unified capability registration | `CapabilityAssimilationLayer.assimilate_device()` | ✅ Stable |
| Canonical device truth convergence | `TruthIntegrationLayer` | ✅ Wired; coverage incomplete |
| Canonical single-device read contract | `RegisteredRuntimeDevice` | ✅ Stable |
| Cross-device top-level read model | `MultiDeviceRuntimeProjection` | ✅ Contract; partially populated |
| Formation resolution at dispatch | `formation_resolver.resolve_formation()` | ✅ Runtime-complete (static) |
| Source vs target device semantic separation | `CommandRouter` PR-521 | ✅ Stable |
| Substrate-only sentinel on legacy paths | `CrossDeviceCoordinator`, `DeviceRouter` | ✅ Enforced |
| AIP v3.0 canonical protocol | `galaxy_gateway/protocol/aip_v3.py` | ✅ Stable |

---

## 3. Domain findings

### 3.1 Unified Scheduling Convergence

**Question**: Are node capabilities and device capabilities routed through one unified
capability-graph authority at dispatch time, or does convergence stop at registration?

**Finding (re-audit)**:

Convergence is real at the **registration** tier: `CapabilityAssimilationLayer`
ingests both node and device capability reports into a unified graph. The graph
supports `query_routable_executors()` and `query_network_path()`.

Convergence is **absent** at the **hot-path dispatch** tier: `CommandRouter`'s
cross-device path uses `cross_device_candidates.resolve_candidates()` (admissibility
chain) for device selection, not the capability graph. The three admissibility gates
(transport presence, orchestration eligibility, per-device validation) do not
consult `CapabilityAssimilationLayer`.

Additionally, `DeviceRouter._select_devices()` contains an independent device
selection path that bypasses both the admissibility chain and the capability graph.
Two parallel selection paths exist.

**New observation (not in prior audit)**: `ConstellationRuntime._run_dag_loop()`
calls `pool.select_device(required_capabilities=caps)` where `pool` is a
`DevicePool` object. It is not confirmed whether `DevicePool` reads from
`CapabilityAssimilationLayer` or from its own internal state. If the latter, this
is a **third** parallel device selection path.

**Gap delta**: Gap SCHED-001 (CommandRouter → capability graph) and SCHED-002
(DeviceRouter dual path) confirmed open. New gap SCHED-004 (ConstellationRuntime
DevicePool → CapabilityAssimilation wiring) added.

See `REAUDIT_SCHEDULING_AUTHORITY_V2.md` for the full authority map.

---

### 3.2 Device Admission to Routable Execution Participant Chain

**Question**: Is there a complete, gated chain that transforms a raw device connection
into a verified execution participant?

**Finding (re-audit)**:

The admissibility chain (`cross_device_candidates.resolve_candidates()`) has three
confirmed gates:

- Gate 1 (`device_readiness`): transport/presence (UDM / UCM)
- Gate 2 (`device_participation`): orchestration eligibility
- Gate 3 (`target_device_validator`): per-device validation

**What is confirmed**:
- All three gates are invoked from `CommandRouter` on the cross-device path.
- `RegisteredRuntimeDevice` is the canonical output contract.

**What remains unresolved**:
- Gate 2 (`device_participation`) does not consult `CapabilityAssimilationLayer`.
  A device may be "eligible" for orchestration without its capabilities being
  verified against the task's required capabilities at admission time. Capability
  verification happens separately via the capability graph, but these two checks
  are not joined.
- `formation_resolver` is called after the admissibility chain but does not
  re-query `CapabilityAssimilationLayer` for capability verification at formation
  time (ADMIT-003).
- `BodyMeshRegistry` → `RegisteredRuntimeDevice` adapter coverage is not confirmed
  as exhaustive; direct internal model access by some consumers is possible (ADMIT-004).
- **New observation**: When an Android device connects via WebSocket and sends
  `device_register`, it is not confirmed that the registration path calls
  `CapabilityAssimilationLayer.assimilate_device()` with the device's reported
  capabilities. Gap CROSS-004 (capability ingress wiring) is likely HIGH, not LOW.

---

### 3.3 Multi-Device Runtime Maturity

**Question**: Which pieces of the multi-device runtime stack are runtime-complete,
which are contract-first only, and what is blocking full multi-device session execution?

**Finding (re-audit)**:

See `REAUDIT_MULTI_DEVICE_MATURITY_V2.md` for the full per-component classification.

Summary:

| Category | Components |
|----------|-----------|
| Runtime-complete | `formation_resolver`, `CommandRouter` cross-device dispatch, parallel fanout API, `DeviceRouter` substrate dispatch |
| Partial | `BodyMeshRegistry` (in-process, no persist), `session_roaming` (basic migrate only) |
| Contract-first | `MeshSession`, `MeshSessionCoordinator`, `DeviceRoleAllocator`, `CrossRuntimeResultMerge` |
| Not implemented | Dynamic formation rebalance, staged mesh execution, persistent mesh session store, recovery / resume from checkpoint |

**Critical gap confirmed**: `MeshSession` and `MeshSessionCoordinator` are
contract-first — their lifecycle state machines have no live runtime engine.
`MeshSessionStatus` transitions (`FORMING → ACTIVE → COMPLETING → DONE`) are never
driven by any executor or event consumer. The barrier coordination, assignment
progress, and merge trigger are all declared but inert.

**New observation (session_roaming duplication)**: `galaxy_gateway/session_roaming.py`
and `core/routes/sessions.py` implement two separate session migration paths. Neither
is confirmed as the canonical entry; calling through either can result in divergent
session state. This is MESH-005 — elevated from MEDIUM to HIGH in this re-audit
because it creates a split-brain risk for migrating sessions.

---

### 3.4 Android Long-Tail Protocol Maturity

**Question**: Which Android AIP message types are canonical, which are placeholders,
and what is the correct classify-and-action for each long-tail type?

**Finding (re-audit)**:

See `REAUDIT_ANDROID_PROTOCOL_V2.md` for the full per-type classification with
promote / retire / defer recommendations.

Summary:

| Disposition | Count | Types |
|-------------|-------|-------|
| CANONICAL (no action needed) | 7 | `device_register`, `heartbeat`, `task_submit/execute`, `task_result`, `task_assign`, `action_execute`, GUI controls |
| PROMOTE (priority) | 2 | `task_cancel`, `task_status` (PROTO-002) |
| PROMOTE + UNIFY (high) | 1 | `session_migrate` / `session_restore` (PROTO-001) |
| PROMOTE | 3 | `wake_event`/`wake_route_result` (PROTO-003), `ui_tree_request`/`action_sequence_execute`/`app_start` (PROTO-004), AIP v2 binary screen/input types (PROTO-005) |
| DEFER | 3 | `peer_announce`, `mesh_topology`, `peer_exchange` |
| DEFER | 1 | `hybrid_execute` / `hybrid_result` (PROTO-006) |
| RETIRE (after traffic analysis) | 1 | `/ws/ufo3/{device_id}` legacy path (PROTO-007) |

**New observation**: `task_cancel` not being acted upon is HIGH severity (not MEDIUM)
because it creates a correctness gap: Android users can initiate a task cancel but
the center-side takes no action. Tasks continue executing after the Android side
believes they have been cancelled. This gap is re-classified HIGH.

---

### 3.5 WebRTC and Canonical Task Lifecycle

**Question**: Is WebRTC an isolated subsystem, or is it integrated with the canonical
task lifecycle? What is the correct relationship?

**Finding (re-audit)**:

WebRTC operates as an **isolated adjacency subsystem**:
- `webrtc_proxy.py` handles signaling as a standalone gateway path.
- `Node_95_WebRTC_Receiver` operates independently of `CommandRouter` / `TaskEnvelope`.
- No task type in AIP v3 explicitly triggers WebRTC session setup as part of a
  task lifecycle.
- `screen_stream_start` / `screen_stream_data` AIP types exist but are not mapped
  to a WebRTC session lifecycle.

**Architecture clarification**: The correct long-term relationship is:

1. A task that requires live device camera/screen input should emit a
   `screen_stream_start` task step via `TaskEnvelope`.
2. The step should trigger WebRTC session setup via `webrtc_proxy.py`.
3. The resulting video stream should be consumed by `Node_95` and made available
   as a task-scoped resource.
4. `Task completion` / `task_cancel` should tear down the WebRTC session.

Currently none of steps 2–4 are implemented. WebRTC sessions are started by
direct WebSocket connection outside the task lifecycle.

**Severity re-classification**: WEBRTC-001 and WEBRTC-002 are elevated from MEDIUM
to HIGH for any task that requires real-time visual input from Android devices —
without this integration, such tasks silently fail to provide the required input.

---

### 3.6 Multi-Device Truth / Projection / Outward Truth Convergence

**Question**: Is there a single canonical truth surface for multi-device state, or
are there multiple divergent projections?

**Finding (re-audit)**:

Three truth surfaces co-exist:

| Surface | Module | Authority | Status |
|---------|--------|-----------|--------|
| `TruthIntegrationLayer` | `core/truth_integration_layer.py` | Canonical device truth convergence point | Wired; not all consumers use it |
| `MultiDeviceRuntimeProjection` | `contracts/multi_device_runtime_projection.py` | Top-level read model | Contract-stable; `merged_results` body partially populated |
| Desktop projection | `desktop_projection/` + `status_board_v2` | Display-side representation | Independent; does not consume `NetworkTopologyRuntime` |

`ProjectionSurfaceBridge` (`core/projection_surface_bridge.py`) is the intended
convergence adapter (wired in PR-511), but not all projection endpoints call
`enrich_runtime_projection()`. The status board surfaces may still assemble
independent runtime views.

**New observation**: Android-side local state (session snapshot, target readiness,
current task state) has no reconciliation protocol with V2 outward truth. This is
a **silent divergence risk**: V2 may show a device as "active in task" while the
Android side has already completed or failed. Gap CROSS-002 / TRUTH-005 confirmed
open. Design decision needed: does V2 outward truth supersede Android local state,
or are they independent with explicit sync?

**Model topology gap** (TRUTH-003): Multi-model intelligent routing (ContinuumState
/ TopologyRoutePlan) has no canonical runtime authority equivalent to
`NetworkTopologyRuntime`. This means model routing decisions are not reflected in
the unified truth surface.

---

### 3.7 Compatibility / Transitional Surface Impact

**Question**: Which legacy surfaces remain on active paths and what is the risk
if they are used instead of canonical replacements?

**Finding (re-audit)**:

| Surface | Status | Risk |
|---------|--------|------|
| `TaskRouter` / `TaskScheduler` | RETIRED (PR-516); file may still exist on disk | LOW — confirm file removed |
| `CapabilityRegistry` | GATED; permitted for device-local bookkeeping only | MEDIUM — routing decisions must use `CapabilityAssimilationLayer`; developers may still route through it |
| `CrossDeviceCoordinator` | Substrate-only with sentinel; external callers possible | MEDIUM — sentinel bypass risk |
| `LocalAgentRuntime` | Gated; server-side planning retired | LOW — boundary confusion risk |
| `ProjectionEngine` | Gated; must delegate to `ProjectionSurfaceBridge` | LOW — runtime enforcement not confirmed |
| Android REST compat aliases | `/api/devices/register`, `/api/devices/list` | LOW — no active retirement timeline |

**New observation (transition surface cohesion)**: The sentinel enforcement on
`CrossDeviceCoordinator` emits `LEGACY_DISPATCH` warnings when called incorrectly.
However, there is no monitoring/alerting on these warnings in production. They
disappear into logs silently. A `LEGACY_DISPATCH` counter in the observability
surface would make accidental legacy path usage visible.

---

## 4. Cross-domain synthesis

### 4.1 The "admission → scheduling → runtime" gap chain

The three foundational conditions for distributed agent operation are sequentially
dependent:

```
Device connection
    │
    ▼ [PARTIAL] Gate 1-3 admissibility checks
    │
    ▼ [GAP] Capability verification NOT joined to admission gates
    │
    ▼ [GAP] CommandRouter does NOT query capability graph for routing
    │
    ▼ [PARTIAL] Formation resolved statically at dispatch time
    │
    ▼ [GAP] No live runtime engine for MeshSession / MeshSessionCoordinator
    │
    ▼ [GAP] No dynamic rebalancing or staged subtask execution
    │
    ▼ [GAP] No cross-device result merge engine
```

The chain breaks at the capability verification join and again at the live runtime
engine. Until these are fixed, the system can **route tasks to multiple devices**
but cannot **coordinate a true multi-device session with barrier sync, role
handoff, or result merge**.

### 4.2 The "protocol → admission → execution" gap in Android

Android devices must transit a protocol-level admission before they can participate
in canonical execution:

```
Android connect
    │
    ▼ WebSocket established
    │
    ▼ [CONFIRMED] device_register → UDM/UCM registration
    │
    ▼ [GAP] device_capabilities NOT auto-forwarded to CapabilityAssimilationLayer
    │
    ▼ [GAP] task_cancel / task_status NOT propagated to CommandRouter
    │
    ▼ [GAP] session_migrate still AIP v2 binary; no unified canonical path
    │
    ▼ [GAP] WebRTC not tied to task lifecycle
```

---

## 5. Key questions for follow-up design

The following open design questions require explicit decisions before implementation
PRs can proceed:

| Q# | Question | Required decision |
|----|----------|------------------|
| Q1 | Should capability verification be joined into the admissibility chain as Gate 4, or remain separate post-admission? | Architecture decision; impacts CommandRouter and formation_resolver |
| Q2 | Should `DevicePool` in `ConstellationRuntime` read from `CapabilityAssimilationLayer`? If yes, what is the consistency model? | Scheduling convergence decision |
| Q3 | What is the canonical session migration path — `galaxy_gateway/session_roaming.py` or `core/routes/sessions.py`? | One must be retired or delegated; splits MESH-005 into a definitive answer |
| Q4 | Does Android local state (session snapshot, target readiness) converge into V2 outward truth, or are they always independent with explicit sync events? | Truth authority decision; impacts CROSS-002 / TRUTH-005 |
| Q5 | Is WebRTC-task lifecycle integration a near-term requirement (triggers a PROMOTE action on WEBRTC-001/002) or a longer-term capability (DEFER)? | Roadmap priority decision |
| Q6 | What is the target retirement date for AIP v2 binary types (`ANDROID_SCREEN` 0x60 / `ANDROID_INPUT` 0x61)? | Compat timeline decision |

---

## 6. Document index

| Document | Purpose |
|----------|---------|
| This document | Overview, findings, synthesis, open questions |
| `REAUDIT_GAP_MATRIX_V2.md` | Machine-readable gap matrix; 44 gaps across 8 domains |
| `REAUDIT_MULTI_DEVICE_MATURITY_V2.md` | Per-component runtime maturity classification |
| `REAUDIT_ANDROID_PROTOCOL_V2.md` | Per-type Android protocol classification with actions |
| `REAUDIT_SCHEDULING_AUTHORITY_V2.md` | Full scheduling / authority chain map |
| `REAUDIT_FOLLOWUP_ROADMAP_V2.md` | Sequenced follow-up PR roadmap with rationale |
