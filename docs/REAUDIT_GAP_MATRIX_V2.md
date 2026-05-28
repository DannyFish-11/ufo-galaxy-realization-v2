> ## ⚠️ SUPERSEDED — NOT AUTHORITATIVE
>
> **This document has been superseded by [`DUAL_REPO_GAP_MATRIX.md`](DUAL_REPO_GAP_MATRIX.md).**
> The content below is preserved for historical reference only.
> For the current gap matrix, see [`DUAL_REPO_GAP_MATRIX.md`](DUAL_REPO_GAP_MATRIX.md).

---

# Re-Audit Gap Matrix V2

> **Fresh re-audit pass** — `DannyFish-11/ufo-galaxy-realization-v2` and
> `DannyFish-11/ufo-galaxy-android`.
>
> This document supersedes `DUAL_REPO_GAP_MATRIX.md`.
> All prior gaps are re-evaluated. New gaps discovered in this re-audit are added.
>
> Companion: `docs/REAUDIT_FRESH_PASS_2.md`

---

## Classification legend

| Severity | Meaning |
|----------|---------|
| **CRITICAL** | Blocks correctness; causes silent data loss, authority violation, or undetected failures |
| **HIGH** | Significant architectural gap; affects canonical chain integrity or cross-repo reliability |
| **MEDIUM** | Architecture incomplete; affects reliability or observability but system still functions |
| **LOW** | Minor gap; clean-up / hardening; system functions correctly without it |

| Status | Meaning |
|--------|---------|
| **OPEN** | Not yet addressed |
| **PARTIAL** | Partially addressed; residual gap remains |
| **RESOLVED** | Fully addressed |
| **ELEVATED** | Severity raised from prior audit based on re-examination |
| **NEW** | Gap not identified in prior audit |

---

## Domain 1: Unified Scheduling Convergence

| Gap ID | Severity | Status | Module | Description | Recommended action |
|--------|----------|--------|--------|-------------|-------------------|
| SCHED-001 | MEDIUM | OPEN | `core/command_router.py` | `CommandRouter` does not call `query_routable_executors()` before selecting dispatch targets. Capability graph is built but not consulted at routing time. | Wire `CapabilityAssimilationLayer.query_routable_executors()` into CommandRouter cross-device path as co-selection authority. |
| SCHED-002 | MEDIUM | OPEN | `galaxy_gateway/device_router.py` + `core/capability_assimilation.py` | Two parallel device-selection paths: admissibility chain (canonical) and `DeviceRouter._select_devices()` (legacy). Neither queries the capability graph. | Retire `_select_devices()` or delegate to admissibility chain. Confirm DeviceRouter uses capability graph for target selection. |
| SCHED-003 | LOW | OPEN | `galaxy_gateway/device_router.py` | `DeviceRouter.route_task()` still performs command analysis (`_analyze_command`) to derive `exec_mode` / `task_type`. Policy logic ideally lives in `CommandRouter` pre-dispatch. | Move command analysis to CommandRouter; simplify DeviceRouter to pure substrate. |
| SCHED-004 | MEDIUM | NEW | `core/constellation_runtime.py` | `ConstellationRuntime._run_dag_loop()` calls `pool.select_device()` where `pool` is a `DevicePool`. Not confirmed whether `DevicePool` reads from `CapabilityAssimilationLayer` — may be a third independent device selection path. | Confirm DevicePool source; if independent, wire to CapabilityAssimilationLayer or delegate to CommandRouter. |

---

## Domain 2: Device Admission to Execution Qualification Chain

| Gap ID | Severity | Status | Module | Description | Recommended action |
|--------|----------|--------|--------|-------------|-------------------|
| ADMIT-001 | MEDIUM | OPEN | `core/truth_integration_layer.py` | `TruthIntegrationLayer` is defined and tested (28 tests) but not confirmed as single entry for all device truth reads. Some status / projection surfaces may still query UDM/UCM directly. | Audit all device-truth consumers; enforce routing through TruthIntegrationLayer. |
| ADMIT-002 | MEDIUM | OPEN | `core/routes/projection.py` | `MultiDeviceRuntimeProjection.merged_results` body partially enriched (PR-522) but not fully sourced from canonical chain state. | Complete projection enrichment from canonical chain. |
| ADMIT-003 | MEDIUM | OPEN | `core/device_formation/formation_resolver.py` | Formation resolver does not query `CapabilityAssimilationLayer` for capability verification at formation time. Device may be admitted to a formation without capability confirmation. | Add capability verification call in formation_resolver before finalizing formation membership. |
| ADMIT-004 | LOW | OPEN | `contracts/registered_runtime_device.py` | `BodyMeshRegistry` → `RegisteredRuntimeDevice` adapter not confirmed exhaustive. Legacy consumers may read from internal models directly. | Audit all consumers; enforce canonical read contract. |
| ADMIT-005 | HIGH | ELEVATED | Android + `galaxy_gateway/android_bridge.py` | When Android sends `device_register`, not confirmed that `CapabilityAssimilationLayer.assimilate_device()` is called with the reported capabilities. Android device may be in UDM/UCM but absent from the capability graph — making it invisible to any capability-based routing. | Confirm and, if missing, wire `device_capabilities` ingress from `android_bridge.py` into `CapabilityAssimilationLayer.assimilate_device()`. Previously CROSS-004 (LOW), re-classified ADMIT-005 HIGH. |

---

## Domain 3: Multi-Device Runtime Maturity

| Gap ID | Severity | Status | Module | Description | Recommended action |
|--------|----------|--------|--------|-------------|-------------------|
| MESH-001 | HIGH | OPEN | `contracts/mesh_session_coordinator.py` | `MeshSessionCoordinatorState` contract exists (PR-37) but no live coordinator engine evolves its state. Barrier wait, assignment progress, and merge trigger are not runtime-driven. | Implement live coordinator engine; subscribe to TaskGraphRuntime events; drive status transitions. |
| MESH-002 | HIGH | OPEN | `contracts/mesh_session.py` | `MeshSessionStatus` transitions (`FORMING → ACTIVE → COMPLETING → DONE`) never driven by a live engine. `subtask_assignments` statuses not updated from TaskGraphRuntime events. | Drive status transitions from execution events. |
| MESH-003 | MEDIUM | OPEN | `core/mesh/body_mesh_registry.py` | `BodyMeshRegistry` is in-process only; no persistence across restarts. Not wired to device connect/disconnect events from UDM/UCM. | Add event subscriptions; add durable persistence (Redis or DB) for mesh state. |
| MESH-004 | MEDIUM | OPEN | `core/mesh/device_role_allocator.py` | `DeviceRoleAllocator.allocate()` does not consult `CapabilityAssimilationLayer`. Role allocation is not capability-aware. | Pass capability snapshot from CapabilityAssimilationLayer into role allocator. |
| MESH-005 | HIGH | ELEVATED | `galaxy_gateway/session_roaming.py` + `core/routes/sessions.py` | Two separate session migration implementations with different semantics and different persistence paths. No canonical entry. Risk: split-brain for migrating sessions. Previously MEDIUM, elevated to HIGH. | Define and enforce one canonical migration path; retire or fully delegate the other. |
| MESH-006 | MEDIUM | OPEN | `core/device_formation/formation_resolver.py` | Formation is resolved statically at dispatch time only. No dynamic rebalancing when device health degrades or a device disconnects mid-session. | Add formation rebalance hook triggered by device health events. |
| MESH-007 | LOW | OPEN | `contracts/cross_runtime_result_merge.py` | `CrossRuntimeResultMerge` contract exists; `MeshSession.merge_policy` is declared; no runtime process drives merge from policy. | Implement merge engine that reads merge_policy and triggers cross-device result aggregation. |
| MESH-008 | LOW | OPEN | Distributed | Staged mesh execution (dependency-ordered multi-device subtask graph where device A must complete before device B starts) is not implemented. Parallel fanout only. | Design and implement staged subtask execution graph. |

---

## Domain 4: Android Protocol Maturity

| Gap ID | Severity | Status | Module | Description | Recommended action |
|--------|----------|--------|--------|-------------|-------------------|
| PROTO-001 | HIGH | OPEN | Android + `galaxy_gateway/session_roaming.py` | `SESSION_MIGRATE` / `session_restore` remains in AIP v2 binary format. Two center-side implementations. No unified AIP v3 JSON path. | Promote to AIP v3 JSON; unify to single center-side handler. Priority. |
| PROTO-002 | HIGH | ELEVATED | `galaxy_gateway/android_bridge.py` | `task_cancel` and `task_status` use `_handle_forward_log` catch-all — not acted upon. Android users can initiate cancel but center-side takes no action; task continues executing. Elevated from MEDIUM to HIGH (silent correctness failure). | Implement canonical cancel/status propagation to CommandRouter. |
| PROTO-003 | MEDIUM | OPEN | Android + V2 | `WAKE_EVENT` / `WAKE_ROUTE_RESULT` remain in AIP v2 binary (0x70/0x71). Need AIP v3 JSON migration with canonical session-routing wiring. | Promote to AIP v3 JSON. |
| PROTO-004 | MEDIUM | OPEN | `galaxy_gateway/android_bridge.py` | `ui_tree_request`, `action_sequence_execute`, `app_start` handled by `_handle_forward_log` — received and logged, not actively executed. | Implement active handlers; wire into task execution chain. |
| PROTO-005 | MEDIUM | OPEN | Android | AIP v2 binary `ANDROID_SCREEN` (0x60) / `ANDROID_INPUT` (0x61) not migrated to AIP v3 `screen_stream_data` / `action_execute`. | Migrate to AIP v3 types; set explicit retirement date for binary types. |
| PROTO-006 | LOW | OPEN | Android + V2 | `HYBRID_EXECUTE` / `HYBRID_RESULT` defined in AIP v3 enum but Android uses degrade path. True hybrid execution not wired. | DEFER until hybrid execution design is complete. |
| PROTO-007 | LOW | OPEN | V2 | `/ws/ufo3/{device_id}` legacy path still served. No confirmed active client. | Analyze traffic; retire if no clients. |

---

## Domain 5: WebRTC and Task Lifecycle

| Gap ID | Severity | Status | Module | Description | Recommended action |
|--------|----------|--------|--------|-------------|-------------------|
| WEBRTC-001 | HIGH | ELEVATED | `galaxy_gateway/webrtc_proxy.py` | WebRTC is an isolated subsystem — not integrated with `CommandRouter` / `TaskEnvelope`. For any task requiring live visual input from Android, WebRTC setup is not triggered by the task lifecycle. Elevated from MEDIUM to HIGH (blocks real-time visual tasks). | Define WebRTC-task lifecycle integration; map `screen_stream_start` to WebRTC session setup. |
| WEBRTC-002 | HIGH | ELEVATED | `nodes/Node_95_WebRTC_Receiver/main.py` | `Node_95` receives video streams independently — no canonical capability routing for tasks requiring device camera input. Elevated from MEDIUM to HIGH. | Register Node_95 as a capability provider in CapabilityAssimilationLayer; wire VideoStream capability to tasks that need it. |
| WEBRTC-003 | LOW | OPEN | V2 + Android | No task types explicitly declare that they trigger WebRTC setup. `screen_stream_start` / `screen_stream_data` exist as AIP types but are not mapped to a WebRTC session lifecycle. | Map AIP screen_stream_start to webrtc_proxy session open; map session end to task completion. |

---

## Domain 6: Truth / Projection / Outward Truth Convergence

| Gap ID | Severity | Status | Module | Description | Recommended action |
|--------|----------|--------|--------|-------------|-------------------|
| TRUTH-001 | MEDIUM | PARTIAL | `core/projection_surface_bridge.py` | `ProjectionSurfaceBridge` wired (PR-511) but not all projection endpoints call `enrich_runtime_projection()`. Status board surfaces may still assemble independent runtime views. | Complete endpoint migration to ProjectionSurfaceBridge. |
| TRUTH-002 | MEDIUM | OPEN | `desktop_projection` / `status_board_v2` | Desktop projection maintains independent topology/route representations without consuming `NetworkTopologyRuntime`. | Integrate NetworkTopologyRuntime as topology authority for desktop projection. |
| TRUTH-003 | MEDIUM | OPEN | `core/continuum` + model topology | Multi-model routing supply expressed through `ContinuumState`/`TopologyRoutePlan` only; no canonical runtime authority equivalent to NetworkTopologyRuntime. | Design canonical model topology runtime authority. |
| TRUTH-004 | LOW | OPEN | `contracts/multi_device_runtime_projection.py` | `MultiDeviceRuntimeProjection.merged_results` partially enriched (PR-522) but not fully sourced from canonical chain. | Complete merged_results population from canonical chain. |
| TRUTH-005 | MEDIUM | NEW | Android-side | Android local state (session snapshot, target readiness, current task state) has no reconciliation protocol with V2 outward truth. Silent divergence risk: V2 may show "active" while Android has completed or failed. | Define truth authority decision (Q4 in REAUDIT_FRESH_PASS_2.md); implement explicit sync protocol or supersession rule. |

---

## Domain 7: Compatibility and Transitional Surfaces

| Gap ID | Severity | Status | Module | Description | Recommended action |
|--------|----------|--------|--------|-------------|-------------------|
| COMPAT-001 | MEDIUM | PARTIAL | `galaxy_gateway/task_router.py` | `TaskRouter`/`TaskScheduler` RETIRED (PR-516) but residual file may remain on disk. | Confirm file removal; verify no import paths. |
| COMPAT-002 | MEDIUM | GATED | `core/capability_registry.py` | `CapabilityRegistry` gated; permitted for device-local bookkeeping only. Risk: developers may still use it for routing decisions. | Add static analysis guard or runtime assertion preventing routing through CapabilityRegistry. |
| COMPAT-003 | MEDIUM | PARTIAL | `galaxy_gateway/cross_device_coordinator.py` | Substrate-only sentinel enforced (PR-518). External callers still possible. `LEGACY_DISPATCH` warnings emitted but not monitored. | Add `LEGACY_DISPATCH` counter to observability surface; alert on unexpected spikes. |
| COMPAT-004 | LOW | GATED | `core/local_agent_runtime.py` | `LocalAgentRuntime` gated; server-side planning role retired. Boundary confusion risk. | Add clear docstring boundary marker; confirm no server-side planning calls remain. |
| COMPAT-005 | LOW | GATED | `desktop_projection/projection_engine.py` | `ProjectionEngine` gated; must delegate to `ProjectionSurfaceBridge`. Gating not confirmed at runtime. | Add runtime assertion verifying delegation. |
| COMPAT-006 | LOW | OPEN | Android REST compat | `POST /api/devices/register`, `GET /api/devices/list` compat aliases still served. No retirement timeline. | Set traffic baseline; schedule gradual retirement. |
| COMPAT-007 | LOW | NEW | All legacy paths | `LEGACY_DISPATCH` warnings emitted by sentinel-gated paths have no monitoring / alerting. Silent legacy usage is invisible in production. | Add `legacy_dispatch_count` metric to observability; alert on unexpected values. |

---

## Domain 8: Cross-Repo Coupling Gaps

| Gap ID | Severity | Status | Description | Recommended action |
|--------|----------|--------|-------------|-------------------|
| CROSS-001 | HIGH | OPEN | Android-side canonical execution chain: not confirmed that ALL Android message types walk full canonical chain (`TaskEnvelope → CommandRouter analog → local execution → signal back`). Direct `task_submit` / `task_execute` flows may bypass canonical admission on Android side. | Android canonical chain audit; trace all Android-initiated execution entry points. |
| CROSS-002 | MEDIUM | OPEN | Android-side truth / projection: Android maintains local runtime state that may diverge from V2 outward truth. No explicit reconciliation protocol defined. | See TRUTH-005; design authority decision and reconciliation protocol. |
| CROSS-003 | MEDIUM | OPEN | No confirmed E2E test that runs across both repos with real connected Android devices. PR-523 acceptance tests are server-side only. | Design real-device E2E integration test suite. |
| CROSS-004 | HIGH | ELEVATED | `device_capabilities` AIP message from Android not confirmed auto-forwarded to `CapabilityAssimilationLayer.assimilate_device()` at connection time. Android device may be absent from capability graph. Previously LOW, elevated to HIGH (see ADMIT-005). | Wire capability ingress in android_bridge; confirm assimilation on device_register. |

---

## Gap count summary

| Domain | CRITICAL | HIGH | MEDIUM | LOW | Total |
|--------|----------|------|--------|-----|-------|
| 1. Scheduling | 0 | 0 | 3 | 1 | 4 |
| 2. Admission chain | 0 | 1 | 3 | 1 | 5 |
| 3. Multi-device runtime | 0 | 3 | 3 | 2 | 8 |
| 4. Android protocol | 0 | 2 | 3 | 2 | 7 |
| 5. WebRTC | 0 | 2 | 0 | 1 | 3 |
| 6. Truth/projection | 0 | 0 | 4 | 1 | 5 |
| 7. Compatibility | 0 | 0 | 3 | 4 | 7 |
| 8. Cross-repo | 0 | 2 | 2 | 0 | 4 |
| **Total** | **0** | **10** | **21** | **12** | **43** |

**Changes from prior audit**:
- 5 gaps elevated in severity: ADMIT-005/CROSS-004 (LOW→HIGH), PROTO-002 (MEDIUM→HIGH), MESH-005 (MEDIUM→HIGH), WEBRTC-001 (MEDIUM→HIGH), WEBRTC-002 (MEDIUM→HIGH)
- 3 new gaps added (SCHED-004, TRUTH-005/formerly CROSS-002 as standalone, COMPAT-007)
- HIGH gap count: 5 → 10 (reflects more accurate risk assessment)
- No new CRITICAL gaps
