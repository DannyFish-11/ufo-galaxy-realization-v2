# Dual-Repo Gap Matrix

> **Full re-audit pass** — fresh standalone review. Supersedes all prior gap matrix versions.
> Primary repo: `DannyFish-11/ufo-galaxy-realization-v2`.
> Cross-repo reference: `DannyFish-11/ufo-galaxy-android`.
>
> This is the machine-readable companion to `DUAL_REPO_FULL_REAUDIT.md`.
> Each row is a discrete gap with severity, classification, owning layer,
> and recommended follow-up.
>
> **Prior versions**: `REAUDIT_GAP_MATRIX_V2.md` (superseded), `DUAL_REPO_UNRESOLVED_AUDIT.md` (superseded).

---

## Classification legend

| Severity | Meaning |
|----------|---------|
| **CRITICAL** | Blocks correctness; causes silent data loss, authority violation, or undetected failures |
| **HIGH** | Significant architectural gap; affects canonical chain integrity or cross-repo reliability |
| **MEDIUM** | Architecture incomplete; affects reliability or observability but system still functions |
| **LOW** | Minor gap; clean-up / hardening work; system functions correctly without it |

| Status | Meaning |
|--------|---------|
| **OPEN** | Not yet addressed |
| **PARTIAL** | Partially addressed; residual gap remains |
| **RESOLVED** | Fully addressed in a prior PR |

---

## Domain 1: Unified Scheduling Convergence

| Gap ID | Severity | Status | Module | Description | Recommended PR |
|--------|----------|--------|--------|-------------|----------------|
| SCHED-001 | MEDIUM | OPEN | `core/command_router.py` | `CommandRouter` does not call `query_routable_executors()` / `query_network_path()` before selecting dispatch targets. Routing decisions bypass canonical capability/network truth. | PR-514 (per RESIDUAL_GAP_MAP) |
| SCHED-002 | LOW | OPEN | `core/capability_assimilation.py` | `assimilate_device()` registers devices in the capability graph, but `DeviceRouter` does not query the capability graph when selecting target devices. Two parallel device-selection paths exist: admissibility chain (canonical) and DeviceRouter._select_devices() (legacy). | Scheduling convergence PR |
| SCHED-003 | LOW | OPEN | `galaxy_gateway/device_router.py` | `DeviceRouter.route_task()` still performs command analysis (`_analyze_command`) to derive `exec_mode` and `task_type`. This is policy/classification logic that ideally lives in `CommandRouter` pre-dispatch. | Scheduling authority clean-up PR |

---

## Domain 2: Device Admission to Execution Qualification Chain

| Gap ID | Severity | Status | Module | Description | Recommended PR |
|--------|----------|--------|--------|-------------|----------------|
| ADMIT-001 | MEDIUM | OPEN | `core/truth_integration_layer.py` | `TruthIntegrationLayer` is defined and tested (28 tests), but it is not confirmed as the single entry point for all device truth reads across all consumers. Some status/projection surfaces may still query UDM/UCM directly. | Truth convergence PR |
| ADMIT-002 | MEDIUM | OPEN | `core/routes/projection.py` | Multi-device projection endpoint partially enriched (PR-522 resolved GAP-517-008) but `projection.merged_results` body still not fully sourced from canonical chain state. | PR-514 / projection convergence PR |
| ADMIT-003 | LOW | OPEN | `core/device_formation/formation_resolver.py` | Formation resolver uses execution policy and routing summary as inputs; it does not directly query `CapabilityAssimilationLayer` for device capability verification at formation time. Device may be included in a formation without capability verification. | Formation + capability integration PR |
| ADMIT-004 | LOW | OPEN | `contracts/registered_runtime_device.py` | `RegisteredRuntimeDevice` is the canonical single-device read contract (PR-5/PR-29), but adapters from `BodyMeshRegistry` and `DeviceRegistry` to `RegisteredRuntimeDevice` are not confirmed as exhaustive — legacy consumers may still read from internal models directly. | Canonical read contract audit PR |

---

## Domain 3: Multi-Device Runtime Maturity

| Gap ID | Severity | Status | Module | Description | Recommended PR |
|--------|----------|--------|--------|-------------|----------------|
| MESH-001 | HIGH | OPEN | `contracts/mesh_session_coordinator.py` | `MeshSessionCoordinatorState` contract exists (PR-37) but no live coordinator engine evolves its state as session executes. Barrier wait, assignment progress, and merge trigger are not runtime-driven. | Multi-device runtime systemization PR |
| MESH-002 | HIGH | OPEN | `contracts/mesh_session.py` | `MeshSessionStatus` transitions are not driven by any live engine. `subtask_assignments` statuses are not updated from `TaskGraphRuntime` events. | Multi-device runtime systemization PR |
| MESH-003 | MEDIUM | OPEN | `core/mesh/body_mesh_registry.py` | `BodyMeshRegistry` is in-process only; no persistence across restarts. Not automatically wired to device connect/disconnect events from UDM/UCM. | Multi-device runtime systemization PR |
| MESH-004 | MEDIUM | OPEN | `core/mesh/device_role_allocator.py` | `DeviceRoleAllocator.allocate()` does not consult `CapabilityAssimilationLayer` for capability-aware role allocation. | Role allocation intelligence PR |
| MESH-005 | MEDIUM | OPEN | `galaxy_gateway/session_roaming.py` + `core/routes/sessions.py` | Two separate session migration implementations exist with different semantics and different persistence paths. No single canonical session migration entry. | Session migration unification PR |
| MESH-006 | MEDIUM | OPEN | `core/device_formation/formation_resolver.py` | Formation is resolved statically at dispatch time only. No dynamic rebalancing when device health degrades or a device disconnects mid-session. | Formation rebalance PR |
| MESH-007 | LOW | OPEN | `contracts/cross_runtime_result_merge.py` | `CrossRuntimeResultMerge` contract exists; `MeshSession.merge_policy` is declared; but no runtime process drives merge from policy declaration. | Mesh result merge engine PR |
| MESH-008 | LOW | OPEN | Distributed | Staged mesh participation (dependency-ordered multi-device subtask graphs where device A completes before device B starts based on A's output) is not implemented. Parallel fanout only. | Staged mesh execution PR |

---

## Domain 4: Android Protocol Maturity

| Gap ID | Severity | Status | Module | Description | Recommended PR |
|--------|----------|--------|--------|-------------|----------------|
| PROTO-001 | HIGH | OPEN | Android + `galaxy_gateway/session_roaming.py` | `SESSION_MIGRATE` / `session_restore` remains in AIP v2 binary format. Two center-side implementations (gateway + core). No unified AIP v3 JSON path. | Session protocol unification PR (high-priority) |
| PROTO-002 | HIGH | OPEN | `galaxy_gateway/android_bridge.py` | `task_cancel` and `task_status` use `_handle_forward_log` catch-all — received, logged, not acted upon. No canonical cancel/status propagation to `CommandRouter`. | Task control protocol PR (high-priority) |
| PROTO-003 | MEDIUM | OPEN | Android + V2 | `WAKE_EVENT` / `WAKE_ROUTE_RESULT` remain in AIP v2 binary (hex 0x70/0x71). Need migration to AIP v3 JSON with typed payload and canonical session-routing wiring. | Wake protocol promotion PR |
| PROTO-004 | MEDIUM | OPEN | `galaxy_gateway/android_bridge.py` | `ui_tree_request`, `action_sequence_execute`, `app_start` handled by `_handle_forward_log` — not actively executed. | Action protocol handlers PR |
| PROTO-005 | MEDIUM | OPEN | Android | AIP v2 binary `ANDROID_SCREEN` (0x60) / `ANDROID_INPUT` (0x61) not migrated to AIP v3 `screen_stream_data` / `action_execute`. | AIP v2 binary migration PR |
| PROTO-006 | LOW | OPEN | Android + V2 | `HYBRID_EXECUTE` / `HYBRID_RESULT` defined in AIP v3 enum but Android uses degrade path (`HYBRID_DEGRADE`). True hybrid execution not wired. | Hybrid execution design PR |
| PROTO-007 | LOW | FENCED (PR-5) | V2 | `/ws/ufo3/{device_id}` legacy path still served. No client confirmed; retire after confirming no active usage. Fence: `GALAXY_ENABLE_LEGACY_PROTOCOLS` env-var gate (default: false); connection rejected with redirect to canonical path. Catalogued in `core.center_side_compat_closure`. | Compat retirement PR |

---

## Domain 5: WebRTC and Task Lifecycle

| Gap ID | Severity | Status | Module | Description | Recommended PR |
|--------|----------|--------|--------|-------------|----------------|
| WEBRTC-001 | MEDIUM | OPEN | `galaxy_gateway/webrtc_proxy.py` | WebRTC signaling exists as a standalone subsystem. No integration with `CommandRouter` / `TaskEnvelope` — WebRTC sessions are not initiated as part of a task lifecycle. | WebRTC-task lifecycle integration PR |
| WEBRTC-002 | MEDIUM | OPEN | `nodes/Node_95_WebRTC_Receiver/main.py` | `Node_95_WebRTC_Receiver` receives video streams but operates independently — no canonical capability routing for "tasks that require video input from device camera". | WebRTC capability integration PR |
| WEBRTC-003 | LOW | OPEN | V2 + Android | No task types explicitly declare that they trigger WebRTC setup. `screen_stream_start` / `screen_stream_data` exist as AIP types but are not mapped to a WebRTC session lifecycle. | WebRTC task type mapping PR |

---

## Domain 6: Truth / Projection / Outward Truth Convergence

| Gap ID | Severity | Status | Module | Description | Recommended PR |
|--------|----------|--------|--------|-------------|----------------|
| TRUTH-001 | MEDIUM | PARTIAL | `core/projection_surface_bridge.py` | `ProjectionSurfaceBridge` is wired (PR-511) but not all projection endpoints call `enrich_runtime_projection()`. Status board surfaces may still assemble their own runtime view (GAP-512-003, GAP-512-005 — PR-514 targets). | PR-514 |
| TRUTH-002 | MEDIUM | OPEN | `desktop_projection` / `status_board_v2` | Desktop projection surfaces maintain independent topology/route representations without consuming `NetworkTopologyRuntime`. Final presentation authority clarification deferred (GAP-512-008). | PR-515 target |
| TRUTH-003 | MEDIUM | OPEN | `core/continuum` + model topology | Multi-model intelligent routing supply is expressed through `ContinuumState`/`TopologyRoutePlan` only, without a canonical runtime authority equivalent to `NetworkTopologyRuntime` for the model/provider domain (GAP-512-009). | PR-515 |
| TRUTH-004 | LOW | OPEN | `contracts/multi_device_runtime_projection.py` | `MultiDeviceRuntimeProjection.merged_results` body is partially enriched from canonical chain state (PR-522) but not fully sourced. | Projection completeness PR |
| TRUTH-005 | LOW | OPEN | Android-side | Android-side authoritative host-facing projections (runtime state / session snapshot / target readiness) exist as local state. Whether they converge into or are superseded by V2 outward truth is not explicitly defined. | Android truth alignment PR |

---

## Domain 7: Compatibility and Transitional Surfaces

| Gap ID | Severity | Status | Module | Description | Recommended PR |
|--------|----------|--------|--------|-------------|----------------|
| COMPAT-001 | MEDIUM | FENCED (PR-5) | `galaxy_gateway/task_router.py` | `TaskRouter` / `TaskScheduler` RETIRED (PR-516) but residual file may remain on disk. Confirm removal and verify no callers. Fence: `NO_PARALLEL_DISPATCH_AUTHORITY_POLICY` sentinel via `legacy_system_decommission`. Catalogued in `core.center_side_compat_closure`. | Compat retirement PR |
| COMPAT-002 | MEDIUM | FENCED (PR-5) | `core/capability_registry.py` | `CapabilityRegistry` gated (PR-516); permitted for device-local bookkeeping but routing decisions must use `CapabilityAssimilationLayer`. Fence: `CANONICAL_CAPABILITY_SOURCE_POLICY` sentinel. Catalogued in `core.center_side_compat_closure`. | Compat governance PR |
| COMPAT-003 | MEDIUM | FENCED (PR-5) | `galaxy_gateway/cross_device_coordinator.py` | Substrate-only with sentinel enforcement (PR-518). External callers still possible. Emit `LEGACY_DISPATCH` warnings. Catalogued in `core.center_side_compat_closure`. | Sentinel coverage audit |
| COMPAT-004 | LOW | FENCED (PR-5) | `core/local_agent_runtime.py` | `LocalAgentRuntime` gated; server-side planning role retired. Device-side sandbox retained. Fence: `legacy_system_decommission` sentinel. Catalogued in `core.center_side_compat_closure`. | Documentation and boundary clarification |
| COMPAT-005 | LOW | FENCED (PR-5) | `desktop_projection/projection_engine.py` | `ProjectionEngine` gated; must delegate to `ProjectionSurfaceBridge` for runtime enrichment. Fence: `CANONICAL_PROJECTION_CONTRACT_POLICY` sentinel. Catalogued in `core.center_side_compat_closure`. | Projection consolidation PR |
| COMPAT-006 | LOW | FENCED (PR-5) | Android REST compat | `POST /api/devices/register`, `GET /api/devices/list` compat aliases still served. Fence: `DeprecationWarning` emitted at `create_router()` call. Catalogued in `core.center_side_compat_closure`. | Gradual retirement after traffic analysis |

---

## Domain 8: Cross-repo coupling gaps

| Gap ID | Severity | Status | Description | Recommended action |
|--------|----------|--------|-------------|-------------------|
| CROSS-001 | HIGH | OPEN | Android-side canonical execution chain: it is not confirmed that ALL Android message types walk the full canonical execution chain (`TaskEnvelope → CommandRouter analog → local execution → signal back`). The delegated execution signal path (PR-16) is well-defined for delegated tasks, but direct task_submit / task_execute Android-initiated flows may bypass canonical admission on the Android side. | Android canonical chain audit |
| CROSS-002 | MEDIUM | OPEN | Android-side truth / projection: Android maintains local runtime state (session snapshot, target readiness, current task state) that may diverge from V2 outward truth. No explicit reconciliation protocol defined. | Android-V2 truth reconciliation design PR |
| CROSS-003 | MEDIUM | OPEN | No confirmed E2E test that runs across both repos with real connected Android devices. PR-523 acceptance tests are server-side only (99 tests, no Android device required). | Real-device E2E integration test suite |
| CROSS-004 | LOW | OPEN | Capability report from Android (`device_capabilities` AIP type) is received by V2 but it is not confirmed that these capabilities are forwarded into `CapabilityAssimilationLayer.assimilate_device()` automatically at connection time. | Android capability ingress wiring PR |

---

## Gap count summary

| Domain | CRITICAL | HIGH | MEDIUM | LOW | Total |
|--------|----------|------|--------|-----|-------|
| 1. Scheduling | 0 | 0 | 1 | 2 | 3 |
| 2. Admission chain | 0 | 0 | 2 | 2 | 4 |
| 3. Multi-device runtime | 0 | 2 | 3 | 3 | 8 |
| 4. Android protocol | 0 | 2 | 3 | 2 | 7 |
| 5. WebRTC | 0 | 0 | 2 | 1 | 3 |
| 6. Truth/projection | 0 | 0 | 3 | 2 | 5 |
| 7. Compatibility | 0 | 0 | 3 (all FENCED) | 3 (all FENCED) | 6 |
| 8. Cross-repo | 0 | 1 | 2 | 1 | 4 |
| **Total** | **0** | **5** | **19** | **16** | **40** |

No CRITICAL gaps. 5 HIGH gaps (MESH-001, MESH-002, PROTO-001, PROTO-002, CROSS-001) require priority attention.
Domain 7 (Compatibility): all 6 gaps are now FENCED via `core.center_side_compat_closure` (PR-5).

---

## Prioritized follow-up PR sequence

### Immediate (HIGH gaps)
1. **Multi-device runtime systemization PR** — MESH-001, MESH-002: live coordinator engine, session status transitions
2. **Session protocol unification PR** — PROTO-001: SESSION_MIGRATE to AIP v3 JSON, unified center-side path
3. **Task control protocol PR** — PROTO-002: task_cancel / task_status canonical handlers
4. **Android canonical chain audit** — CROSS-001: verify Android-side admission chain

### Short-term (MEDIUM gaps)
5. **PR-514 targets** — SCHED-001, TRUTH-001: CommandRouter capability query, projection enrichment
6. **Formation + body mesh wiring** — MESH-003, MESH-004, MESH-006
7. **Android protocol promotion** — PROTO-003, PROTO-004, PROTO-005: wake events, action handlers, AIP v2 binary migration
8. **WebRTC-task lifecycle integration** — WEBRTC-001, WEBRTC-002
9. **Truth / projection completeness** — TRUTH-002, TRUTH-003: desktop projection, model topology

### Longer-term
10. **Staged mesh execution** — MESH-008
11. **Mesh result merge engine** — MESH-007
12. **Android-V2 truth reconciliation** — CROSS-002, TRUTH-005
13. **Compat retirement (physical deletion)** — COMPAT-001 through COMPAT-006, PROTO-007 — all FENCED in PR-5; physical deletion pending retirement conditions (see `core.center_side_compat_closure` for each gap's retirement_condition)
