# Legacy Decommission Audit — PR-516

**PR-516: Legacy / Parallel System Decommission Sweep**

This document is the authoritative map of what was decommissioned vs. intentionally
retained legacy surface area after the PR-516 sweep.  Future cleanup work should
start here rather than rediscovering the state from scratch.

---

## Summary

PR-516 formally retires or gates the most problematic remaining legacy and parallel
system paths that could still confuse authority, reintroduce drift, or silently bypass
the canonical mainline architecture established in PRs #506–#515.

| Decommission status | Count | Meaning |
|---------------------|-------|---------|
| **RETIRED**         | 5     | Formally retired; no new invocations permitted |
| **GATED**           | 3     | Still invocable but gated — invocations recorded |
| **RESIDUAL**        | 0     | Acknowledged active; documented for future cleanup |

**Conflicts closed:**
- `CONFLICT-003` — Executor readiness: CapabilityAssimilationLayer vs legacy CapabilityRegistry
- `CONFLICT-009` — Task decomposition: canonical TaskGraph vs legacy TaskDecomposer/IntelligentTaskPlanner
- `CONFLICT-010` — Projection contract: canonical ProjectionSurfaceBridge vs legacy dashboard-era direct contracts

---

## Decommissioned Paths

### 1. `galaxy_gateway.capability_registry.GatewayCapabilityRegistry` — **RETIRED**

| Field | Value |
|-------|-------|
| **Kind** | Capability Registry |
| **Status** | RETIRED |
| **Canonical replacement** | `core.capability_assimilation.CapabilityAssimilationLayer` |
| **Conflict closed** | CONFLICT-003 |
| **PR origin** | pre-PR-7 |

**Why decommissioned:**
GatewayCapabilityRegistry was an in-gateway per-device action-schema store introduced
before `core.capability_bus` existed.  It became a parallel capability authority that
competed with `CapabilityAssimilationLayer` (Layer 7) for executor-readiness truth.
PR-509 and PR-513 established `CapabilityAssimilationLayer` and `query_routable_executors()`
as the canonical path.  PR-516 formally retires GatewayCapabilityRegistry.

**Migration path:**
Use `core.capability_assimilation.get_capability_assimilation_layer().query_routable_executors()`
for all executor-readiness queries.

---

### 2. `core.capability_registry.CapabilityRegistry` — **GATED**

| Field | Value |
|-------|-------|
| **Kind** | Capability Registry |
| **Status** | GATED |
| **Canonical replacement** | `core.capability_assimilation.CapabilityAssimilationLayer` |
| **Conflict closed** | CONFLICT-003 |
| **PR origin** | pre-PR-7 |

**Why retained (not fully retired):**
`core.capability_registry.CapabilityRegistry` is used for device-local capability
bookkeeping by device-side components.  This is a legitimately distinct role from
executor-readiness in routing decisions.  It is gated rather than retired to
distinguish the two use cases.

**Boundary:**
- Device-local capability bookkeeping → `CapabilityRegistry` (gated, permitted)
- Routing executor-readiness decisions → `CapabilityAssimilationLayer` (canonical, required)

---

### 3. `galaxy_gateway.task_decomposer.TaskDecomposer` — **RETIRED**

| Field | Value |
|-------|-------|
| **Kind** | Task Decomposer |
| **Status** | RETIRED |
| **Canonical replacement** | `core.task_graph.TaskGraph` |
| **Conflict closed** | CONFLICT-009 |
| **PR origin** | pre-PR-S6 |

**Why decommissioned:**
TaskDecomposer is a rule-based complex-task splitter that created sub-tasks
independently of the canonical `TaskGraph`, producing sub-task graphs not tracked
by `TaskGraphRuntime`.  It was a parallel task-graph authority that could silently
bypass the canonical pipeline.

**Migration path:**
Use `core.task_graph.TaskGraph` for all task decomposition.

---

### 4. `galaxy_gateway.task_decomposer.IntelligentTaskPlanner` — **RETIRED**

| Field | Value |
|-------|-------|
| **Kind** | Task Decomposer |
| **Status** | RETIRED |
| **Canonical replacement** | `core.task_graph.TaskGraph` |
| **Conflict closed** | CONFLICT-009 |
| **PR origin** | pre-PR-S6 |

**Why decommissioned:**
IntelligentTaskPlanner was an LLM-based task planner that invoked TaskDecomposer
independently of the canonical `OpenClawd → CommandRouter → TaskGraph` pipeline.
It was a parallel planning authority.

**Migration path:**
New planning must route through `core.e2e_orchestrator.process_user_input()` or
the canonical OpenClawd pipeline.

---

### 5. `galaxy_gateway.task_router.TaskRouter` — **RETIRED**

| Field | Value |
|-------|-------|
| **Kind** | Dispatch Authority |
| **Status** | RETIRED |
| **Canonical replacement** | `core.command_router.CommandRouter` |
| **Conflict closed** | — |
| **PR origin** | pre-PR-S6 |
| **Previously demoted in** | PR-S6 |

**Why decommissioned:**
TaskRouter was a standalone task-dispatch loop that routed tasks to devices via raw
websocket/device calls, bypassing the canonical `CommandRouter → TaskEnvelope →
DeviceRouter` chain.  It was formally demoted in PR-S6 and is retired as a dispatch
authority in PR-516.

---

### 6. `galaxy_gateway.task_router.TaskScheduler` — **RETIRED**

| Field | Value |
|-------|-------|
| **Kind** | Dispatch Authority |
| **Status** | RETIRED |
| **Canonical replacement** | `core.task_graph.TaskGraph` |
| **Conflict closed** | — |
| **PR origin** | pre-PR-S6 |
| **Previously demoted in** | PR-S6 |

**Why decommissioned:**
TaskScheduler was a standalone topological scheduler that built `ExecutionPlan`
objects independently of the canonical `TaskGraph`.  Retired as a top-level
scheduling authority in PR-516.

---

### 7. `core.local_agent_runtime.LocalAgentRuntime` — **GATED**

| Field | Value |
|-------|-------|
| **Kind** | Agent Planner |
| **Status** | GATED |
| **Canonical replacement** | `core.command_router.CommandRouter` |
| **Conflict closed** | — |
| **PR origin** | PR-S5 |

**Why retained (not fully retired):**
LocalAgentRuntime is a legitimate device-side execution sandbox that receives
already-dispatched manifests.  The server-side planning role is retired, but the
device-side sandbox role is retained as an acknowledged residual.

**Boundary:**
- Device-side execution sandbox (receives dispatched manifests) → `LocalAgentRuntime` (gated, permitted)
- Server-side primary execution planner → `CommandRouter` (canonical, required)

---

### 8. `desktop_projection.projection_engine.ProjectionEngine` — **GATED**

| Field | Value |
|-------|-------|
| **Kind** | Projection Contract |
| **Status** | GATED |
| **Canonical replacement** | `core.projection_surface_bridge.ProjectionSurfaceBridge` |
| **Conflict closed** | CONFLICT-010 |
| **PR origin** | pre-PR-511 |

**Why retained (not fully retired):**
ProjectionEngine still functions as a thin adapter.  However, its independent
runtime snapshot assembly is gated.  It must delegate to `ProjectionSurfaceBridge`
for runtime enrichment rather than assembling snapshots independently.

---

### 9. `dashboard.backend.legacy_projection_contract` — **RETIRED**

| Field | Value |
|-------|-------|
| **Kind** | Projection Contract |
| **Status** | RETIRED |
| **Canonical replacement** | `core.projection_surface_bridge.ProjectionSurfaceBridge` |
| **Conflict closed** | CONFLICT-010 |
| **PR origin** | pre-PR-511 |

**Why decommissioned:**
Dashboard-era direct projection contracts built runtime views by reading raw
subsystems independently, creating parallel projection authorities that diverged
from the bridge-enriched projection.  These are retired; the dashboard should
consume `/api/v1/operator/snapshot` and `/api/v1/projection` endpoints instead.

---

### 10. `galaxy_gateway.handlers.message_handler.MessageHandler` — **GATED**

| Field | Value |
|-------|-------|
| **Kind** | Envelope Ingress |
| **Status** | GATED |
| **Canonical replacement** | `galaxy_gateway.websocket_handler` |
| **Conflict closed** | — |
| **PR origin** | PR-S6 |

**Why retained (not fully retired):**
MessageHandler (chain B: `handlers/message_handler → TaskOrchestrator`) is retained
so existing integrations wired to chain B do not immediately break.  The canonical
ingress is chain A: `websocket_handler → DeviceRouter`.  MessageHandler is gated;
new message routing must use chain A.

---

## Intentionally Retained Legacy Surface Area

The following legacy paths are **explicitly retained** for legitimate reasons and
are NOT scheduled for decommission at this time.

| Path | Reason retained |
|------|-----------------|
| `fusion.unified_orchestrator` | FACADE_ONLY — graph contributor (PR-6); retained for orchestration planning compat |
| `galaxy_gateway.orchestrator.galaxy_orchestrator` | FACADE_ONLY — graph contributor (PR-6); retained for cross-device orchestration compat |
| `core.device_orchestrator` | FACADE_ONLY — routes through CommandRouter; retained as thin compat wrapper |
| `core.scheduler` | COMPAT_ONLY — routes through CommandRouter; retained for existing call sites |
| `core.capability_orchestrator` | FACADE_ONLY — retained as CapabilityBus surface |
| `core.agent.kernel` | FACADE_ONLY — front-loads CanonicalTask (PR-507); retained as execution compat |
| `galaxy_gateway.orchestrator.task_orchestrator` | COMPAT_ONLY — front-loads CanonicalTask (PR-507); retained for gateway compat |
| `core.local_agent_runtime.LocalAgentRuntime` | Device-side execution sandbox (see GATED above) |
| `core.multi_llm_router` | Routing helper — CriticalPathHarness (PR-515) adds canonical runtime authority; MultiLLMRouter retained as routing algorithm |
| `desktop_projection.projection_engine.ProjectionEngine` | Thin adapter (see GATED above) |
| `windows_client.status_board_v2.topology_renderer` | COMPAT_ONLY — retained for UI rendering compat |
| `galaxy_gateway.android_bridge` | COMPAT_ONLY — execution spine applied (PR-3); retained for Android bridge compat |
| `nodes.Node_110_SmartOrchestrator.main` | FACADE_ONLY — node orchestrator facade; retained for node compat |

---

## Policy Sentinels

The following policy sentinels in `core/legacy_system_decommission.py` prevent
retired paths from silently regaining control:

| Sentinel | Purpose |
|----------|---------|
| `CANONICAL_CAPABILITY_SOURCE_POLICY` | All executor-readiness queries → CapabilityAssimilationLayer |
| `CANONICAL_DECOMPOSITION_PATH_POLICY` | All task decomposition → core.task_graph.TaskGraph |
| `CANONICAL_PROJECTION_CONTRACT_POLICY` | All projection enrichment → ProjectionSurfaceBridge |
| `NO_PARALLEL_DISPATCH_AUTHORITY_POLICY` | All dispatch → CommandRouter.route_envelope() |
| `DECOMMISSION_NON_REGRESSION_POLICY` | Tests must assert retired paths are in catalog |

---

## Non-Regression Test Coverage

`tests/test_pr516_legacy_system_decommission.py` contains tests that:
- Assert all retired paths are present in the decommission catalog with status RETIRED
- Assert CONFLICT-003, CONFLICT-009, CONFLICT-010 are resolved in the closure audit
- Assert PR-516 layer specs are present in `verify_all_layers()`
- Assert `LegacySystemDecommissionRuntime` ring buffer and activation recording work
- Assert `assert_path_not_active()` logs non-regression violations for RETIRED paths
- Assert the legacy orchestration authority registry includes all PR-516 entries
- Assert `snapshot_decommission()` returns operator-safe dict

---

## Related Files

- `core/legacy_system_decommission.py` — formal decommission authority module (Layer 16)
- `core/runtime_closure_audit.py` — updated with CONFLICT-009, CONFLICT-010, resolved CONFLICT-003, PR-516 layer specs
- `core/orchestration_authority/legacy_paths.py` — updated with PR-516 legacy path entries
- `core/legacy_dispatch_registry.py` — existing legacy dispatch registry (PR-A)
- `tests/test_pr516_legacy_system_decommission.py` — non-regression test suite
