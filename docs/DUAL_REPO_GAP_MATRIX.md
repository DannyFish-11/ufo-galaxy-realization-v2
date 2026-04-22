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
| **CLOSED (PR-4V2)** | Closed by the Android participant truth reconciliation PR |

---

## Domain 1: Unified Scheduling Convergence

| Gap ID | Severity | Status | Module | Description | Recommended PR |
|--------|----------|--------|--------|-------------|----------------|
| SCHED-001 | MEDIUM | RESOLVED | `core/command_router.py` | `CommandRouter.route_envelope()` now calls `query_routable_executors()` and `query_network_path()` from `core.capability_network_runtime_policy` before dispatching cross-device envelopes. Targets not confirmed in the capability graph emit a structured warning and are filtered when confirmed alternatives exist. Closes GAP-512-004. | Resolved in baseline hardening PR |
| SCHED-002 | LOW | RESOLVED | `galaxy_gateway/routing/device_selection.py`, `core/command_router.py` | `select_devices()` (step 0) now applies a canonical admissibility pre-filter using `core.target_device_validator.validate_target_device()` for each candidate before exec_mode or capability filtering — devices that fail the readiness check are excluded.  `CommandRouter._route_cross_device_envelope()` additionally validates envelope targets via `validate_target_device()` and propagates the validated primary target as `context["device_id"]` to DeviceRouter so the canonical target is used rather than a fresh selection from the local session cache.  Both degrade gracefully when the readiness module is unavailable.  Resolves SCHED-002 (two parallel selection paths now converge on canonical readiness truth). | Resolved in routing canonical truth alignment PR |
| SCHED-003 | LOW | OPEN | `galaxy_gateway/device_router.py` | `DeviceRouter.route_task()` still performs command analysis (`_analyze_command`) to derive `exec_mode` and `task_type`. This is policy/classification logic that ideally lives in `CommandRouter` pre-dispatch. | Scheduling authority clean-up PR |

---

## Domain 2: Device Admission to Execution Qualification Chain

| Gap ID | Severity | Status | Module | Description | Recommended PR |
|--------|----------|--------|--------|-------------|----------------|
| ADMIT-001 | MEDIUM | OPEN | `core/truth_integration_layer.py` | `TruthIntegrationLayer` is defined and tested (28 tests), but it is not confirmed as the single entry point for all device truth reads across all consumers. Some status/projection surfaces may still query UDM/UCM directly. | Truth convergence PR |
| ADMIT-002 | MEDIUM | OPEN | `core/routes/projection.py` | Multi-device projection endpoint partially enriched (PR-522 resolved GAP-517-008) but `projection.merged_results` body still not fully sourced from canonical chain state. | PR-514 / projection convergence PR |
| ADMIT-003 | LOW | RESOLVED | `galaxy_gateway/device_router.py` | `DeviceRouter._dispatch_cross_device_task()` now filters the device list through `core.device_participation.get_device_participation()` before calling `resolve_formation()`, ensuring the formation group is assembled from participation-eligible devices only.  Non-eligible devices are excluded with a structured warning; graceful degradation preserves dispatch if all devices are ineligible or the participation module is unavailable.  This closes the gap where formation could include devices without participation/orchestration-eligibility verification.  Resolves ADMIT-003. | Resolved in routing canonical truth alignment PR |
| ADMIT-004 | LOW | OPEN | `contracts/registered_runtime_device.py` | `RegisteredRuntimeDevice` is the canonical single-device read contract (PR-5/PR-29), but adapters from `BodyMeshRegistry` and `DeviceRegistry` to `RegisteredRuntimeDevice` are not confirmed as exhaustive — legacy consumers may still read from internal models directly. | Canonical read contract audit PR |

---

## Domain 3: Multi-Device Runtime Maturity

| Gap ID | Severity | Status | Module | Description | Recommended PR |
|--------|----------|--------|--------|-------------|----------------|
| MESH-001 | HIGH | RESOLVED | `contracts/mesh_session_coordinator.py` | `MeshSessionCoordinatorState` contract is now backed by a live runtime engine. `LiveMeshRuntimeEngine` (batch) and `LiveMeshSessionCoordinator` (incremental event-driven) drive barrier wait, assignment progress, and merge trigger in `core/mesh/live_mesh_runtime_engine.py` and `core/mesh/live_mesh_session_coordinator.py`. 147 tests verify live progression. | Resolved in live mesh coordinator PR |
| MESH-002 | HIGH | RESOLVED | `contracts/mesh_session.py` | `MeshSessionStatus` transitions and `subtask_assignments.status` are now driven by `MeshSessionProgressionDriver` (`core/mesh/mesh_session_progression_driver.py`). The driver advances `MeshSession.status` (PENDING→ACTIVE→MERGING→COMPLETED/FAILED) and `MeshSubtaskAssignment.status` (pending→running→success/failed) in lock-step with participant lifecycle events. 60 tests verify live session progression. | Resolved in live mesh session progression PR |
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
| PROTO-002 | HIGH | RESOLVED | `galaxy_gateway/android_bridge.py` | `task_cancel` and `task_status` messages are now routed to dedicated `handle_task_cancel()` / `handle_task_status()` handlers in `galaxy_gateway/android/handlers/task_lifecycle.py`, registered via `_register_default_handlers()`. `handle_task_cancel` cancels the pending Future and clears `current_task_id`; `handle_task_status` returns a structured `task_status_response`; both return canonical ack messages to Android. No longer falls through to `_handle_forward_log`. | Resolved in baseline hardening PR |
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
| TRUTH-005 | LOW | CLOSED (PR-4V2) | `core/android_participant_truth_ingress.py` | **Closed by PR-4V2.** Android participant truth (session snapshot, readiness assessment, task phase, runtime state, cancel, status, failure, result) now has an explicit reconciliation protocol with V2 canonical orchestration state via `ingest_android_participant_truth_message()` / `reconcile_android_participant_truth()`. cancel/failure/result materially update V2 tracking records; readiness/runtime_state remain advisory. See `docs/ANDROID_TRUTH_RECONCILIATION_REVIEWER_GUIDE.md` and policy sentinels in `core/android_participant_truth_ingress.py`. | Closed — see `core/android_participant_truth_ingress.py` |

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
| CROSS-002 | MEDIUM | CLOSED (PR-4V2) | Android-side truth / projection: **Closed by PR-4V2.** `core/android_participant_truth_ingress.py` defines the explicit reconciliation protocol between Android local runtime state and V2 canonical orchestration truth. cancel/failure/result signals materially update V2 canonical tracking records; session snapshots are validated against `AttachedSessionRegistry`; readiness/runtime_state are advisory. V2 terminal state wins all conflicts; no phantom records are created on miss. See `docs/ANDROID_TRUTH_RECONCILIATION_REVIEWER_GUIDE.md`. | Closed — see `core/android_participant_truth_ingress.py` |
| CROSS-003 | MEDIUM | OPEN | No confirmed E2E test that runs across both repos with real connected Android devices. PR-523 acceptance tests are server-side only (99 tests, no Android device required). | Real-device E2E integration test suite |
| CROSS-004 | LOW | OPEN | Capability report from Android (`device_capabilities` AIP type) is received by V2 but it is not confirmed that these capabilities are forwarded into `CapabilityAssimilationLayer.assimilate_device()` automatically at connection time. | Android capability ingress wiring PR |

---

## Gap count summary

| Domain | CRITICAL | HIGH | MEDIUM | LOW | Total |
|--------|----------|------|--------|-----|-------|
| 1. Scheduling | 0 | 0 | 1 | 2 | 3 |
| 2. Admission chain | 0 | 0 | 2 | 2 | 4 |
| 3. Multi-device runtime | 0 | 0 (was 2, MESH-001/002 now RESOLVED) | 3 | 3 | 6 |
| 4. Android protocol | 0 | 1 (PROTO-001; PROTO-002 RESOLVED) | 3 | 2 | 6 |
| 5. WebRTC | 0 | 0 | 2 | 1 | 3 |
| 6. Truth/projection | 0 | 0 | 3 | 1 (TRUTH-005 CLOSED) | 4 |
| 7. Compatibility | 0 | 0 | 3 (all FENCED) | 3 (all FENCED) | 6 |
| 8. Cross-repo | 0 | 1 | 1 (CROSS-002 CLOSED) | 1 | 3 |
| **Total** | **0** | **2** | **18** | **15** | **35** |

No CRITICAL gaps. 2 HIGH gaps remain (PROTO-001, CROSS-001). MESH-001, MESH-002, PROTO-002, TRUTH-005, CROSS-002 resolved.

---

## Prioritized follow-up PR sequence

### Immediate (HIGH gaps)
1. **Session protocol unification PR** — PROTO-001: SESSION_MIGRATE to AIP v3 JSON, unified center-side path
2. **Android canonical chain audit** — CROSS-001: verify Android-side admission chain

### Short-term (MEDIUM gaps)
3. **PR-514 targets** — SCHED-001, TRUTH-001: CommandRouter capability query, projection enrichment
4. **Formation + body mesh wiring** — MESH-003, MESH-004, MESH-006
5. **Android protocol promotion** — PROTO-003, PROTO-004, PROTO-005: wake events, action handlers, AIP v2 binary migration
6. **WebRTC-task lifecycle integration** — WEBRTC-001, WEBRTC-002
7. **Truth / projection completeness** — TRUTH-002, TRUTH-003: desktop projection, model topology

### Longer-term
8. **Staged mesh execution** — MESH-008
9. **Mesh result merge engine** — MESH-007
10. ~~**Android-V2 truth reconciliation** — CROSS-002, TRUTH-005~~ **CLOSED by PR-4V2** — see `core/android_participant_truth_ingress.py` and `docs/ANDROID_TRUTH_RECONCILIATION_REVIEWER_GUIDE.md`
11. **Compat retirement (physical deletion)** — COMPAT-001 through COMPAT-006, PROTO-007 — all FENCED in PR-5; physical deletion pending retirement conditions (see `core.center_side_compat_closure` for each gap's retirement_condition)
