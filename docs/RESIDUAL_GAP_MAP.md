# Residual Gap Map — PR-512 System Closure Audit

> Machine-readable residual gap catalog produced by PR-512.
> Each entry is annotated with severity, owning layer, and follow-up PR.
> The canonical in-code catalog lives in `core/runtime_closure_audit.py`
> (`_KNOWN_RESIDUAL_GAPS`).  This document is the human-readable companion.

## Summary

PR-512 performed a focused system-wide closure sweep across the runtime
unification path established in PRs #506–#511.  The highest-value parallel
truth paths (CONFLICT-001, CONFLICT-004, CONFLICT-005) have been resolved.
The following gaps remain for follow-up PRs.

---

## Resolved Conflicts (PR-512)

| Conflict ID | Runtime Fact | Resolution |
|-------------|-------------|------------|
| CONFLICT-001 | task_status / task_identity | PR-507 front-loads `adapt_to_canonical_task()` at all ingress points; `task_queue` is compat-only. |
| CONFLICT-004 | operator inspection truth | PR-510 `routes/operator.py` reads only `OperatorSurface`; raw subsystem reads are prohibited. |
| CONFLICT-005 | replay/audit truth | PR-506 routes both writes through `CommandRouter.route_envelope()`. |

---

## Open Conflicts (deferred)

| Conflict ID | Runtime Fact | Owning Layer | Follow-up |
|-------------|-------------|-------------|-----------|
| CONFLICT-002 | network topology / device reachability | `NetworkTopologyRuntime` vs `ContinuumState/TopologyRoutePlan` | PR-514 |
| CONFLICT-003 | executor readiness / capability set | `CapabilityAssimilationLayer` vs legacy `CapabilityRegistry` | PR-513 |

---

## Residual Gaps

### PR-513 Targets

| Gap ID | Severity | Layer | Description |
|--------|----------|-------|-------------|
| GAP-512-001 | HIGH | `core/routes/tasks.py` | API task ingress front-loads `CanonicalTask` but does not write a `TaskExecutionRecord` to `ReplayFoundation`. Audit lineage is incomplete for API-ingressed tasks. |
| GAP-512-002 | HIGH | `core/scheduler.py` | Scheduler relay/mesh paths front-load `CanonicalTask` but do not register in `TaskGraphRuntime` before dispatch. Gap between PR-508 and scheduler mesh/relay paths. |
| GAP-512-004 | MEDIUM | `core/capability_network_runtime_policy.py` | `CommandRouter` does not call `query_routable_executors()` / `query_network_path()` before selecting dispatch targets. Routing decisions may bypass canonical capability/network truth. |
| GAP-512-006 | LOW | `galaxy_gateway/orchestrator/task_orchestrator.py` | `TaskOrchestrator` front-loads `CanonicalTask` but does not emit audit event after successful orchestration handoff. |
| GAP-512-007 | LOW | `core/agent/kernel.py` | `AgentKernel` front-loads `CanonicalTask` but does not emit `TASK_ADMITTED` audit event. |

### PR-514 Targets

| Gap ID | Severity | Layer | Description |
|--------|----------|-------|-------------|
| GAP-512-003 | MEDIUM | `core/projection_surface_bridge.py` | Status board surfaces do not call `enrich_runtime_projection()` in their assembly paths. Bridge is wired but not yet consumed by all projection endpoints. |
| GAP-512-005 | MEDIUM | `core/operator_surface.py` / `core/routes/operator.py` | Status board does not consume the operator snapshot. Still assembles its own runtime view without reading from canonical operator surface. |
| GAP-512-008 | RESIDUAL | `desktop_projection / status_board_v2` | Desktop projection surfaces maintain their own topology/route representations independently of `NetworkTopologyRuntime`. Final presentation authority clarification deferred. |

### PR-515 Targets

| Gap ID | Severity | Layer | Description |
|--------|----------|-------|-------------|
| GAP-512-009 | RESIDUAL | `core/continuum / desktop_projection` | Multi-model intelligent routing supply remains expressed through `ContinuumState`/`TopologyRoutePlan` only, without a canonical runtime authority equivalent to `NetworkTopologyRuntime` for the model/provider domain. Dedicated model-topology PR required. |

---

## Architecture Layers Reference

```
Layer  6 — TaskGraphRuntime            (PR-508 / PR-3 predecessor)
Layer  7 — CapabilityAssimilationLayer (PR-7 predecessor / PR-509)
Layer  8 — NetworkTopologyRuntime      (PR-8 predecessor / PR-509)
Layer  9 — CapabilityNetworkRuntimePolicy (PR-509)
Layer 10 — OperatorSurface / ReplayFoundation / AuditEventSemantics (PR-E)
Layer 11 — ProjectionSurfaceBridge     (PR-511)
Layer 12 — RuntimeClosureAudit         (PR-512, this module)
```

---

## How to Use the Residual Gap Map

1. **Machine-readable**: import `get_residual_gap_map()` from
   `core.runtime_closure_audit` to get `List[ClosureGapEntry]` at runtime.

2. **Human-readable**: this document.

3. **Test coverage**: `tests/test_pr512_runtime_closure_audit.py` contains
   tests that verify each gap and conflict entry is present and correctly
   annotated.

4. **Follow-up**: when closing a gap in a follow-up PR, update
   `_KNOWN_RESIDUAL_GAPS` in `core/runtime_closure_audit.py` to mark
   `is_residual=False` and add a `resolution_note`.
