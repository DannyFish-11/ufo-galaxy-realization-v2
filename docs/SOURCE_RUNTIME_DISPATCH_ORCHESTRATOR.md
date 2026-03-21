# Source Runtime Dispatch Orchestrator

> **PR-35** — Source-side execution orchestration layer for Galaxy.

## What is the Source Runtime Dispatch Orchestrator?

The **Source Runtime Dispatch Orchestrator** (`core/runtime/source_dispatch_orchestrator.py`) is the canonical source-side layer that decides:

1. **Whether to execute locally** — use `OpenClawd._run_execution()` on the source device.
2. **Whether to delegate to a target runtime** — build a `HandoffEnvelopeV2` (PR-31) and dispatch via `galaxy_gateway.agent_bridge`.
3. **Whether to coordinate a staged multi-device dispatch** — prepare a mesh session plan (PR-33) for future coordinator work (PR-37).

It is the **source-side counterpart** to the Target Runtime Local Takeover Path (PR-34):

| Layer | Module | Role |
|-------|--------|------|
| **Source** | `core/runtime/source_dispatch_orchestrator.py` | Decides *how* to dispatch; orchestrates local/remote/mesh execution |
| **Target** | `core/runtime/target_takeover.py` | Adopts an incoming handoff envelope and executes locally |

---

## How it differs from the Target Runtime Local Takeover Path (PR-34)

| Dimension | PR-35 Source Orchestrator | PR-34 Target Takeover |
|-----------|--------------------------|----------------------|
| **Side** | Source device | Target device |
| **Entry trigger** | User task / agent request | Incoming `HandoffEnvelopeV2` |
| **Decision** | Local vs remote vs mesh | Already decided (takeover received) |
| **Artefacts produced** | `SourceDispatchDecision`, `SourceDispatchPlan`, `SourceDispatchResult` | `LocalTakeoverResult` |
| **Governance/policy role** | Consumed to *make* the dispatch decision | Consumed to *validate* the takeover |
| **Mesh session role** | Used to detect staged multi-device opportunity | Used to extract session context |

---

## How local vs remote vs staged dispatch is decided

`select_dispatch_mode()` evaluates available signals in priority order:

1. **`force_local`** — caller explicitly requests local execution.
2. **`force_remote`** — caller explicitly requests remote handoff (requires `target_device_id`).
3. **Policy alignment (PR-28)** — if `blocked` flag is set → `blocked` mode.
4. **Policy alignment hints** — if `can_expand_cross_device` and a `target_device_id` is available → `remote_handoff`.
5. **Mesh session (PR-33)** — if 2+ active participants and no explicit target → `staged_mesh`.
6. **Governance snapshot (PR-27)** — if `execution_allowed` is `False` → `blocked`.
7. **Default** → `local`.

After mode selection, `orchestrate_source_runtime_dispatch()` executes:

| Mode | Execution path |
|------|---------------|
| `local` | `OpenClawd._run_execution()` via `_try_run_local_execution()` |
| `remote_handoff` | Pre-built `HandoffEnvelopeV2` → `galaxy_gateway.agent_bridge.forward_handoff()` |
| `fallback_local` | Remote handoff failed; falls back to local execution |
| `staged_mesh` | Returns plan summary; full coordinator execution deferred to PR-37 |
| `blocked` | Returns a failure result immediately |
| `unknown` | Falls back to local with a warning note |

---

## How governance snapshot / policy alignment / mesh session context are used

### Governance Snapshot (PR-27)
- Fetched automatically via `core.runtime_governance.snapshot.assemble_runtime_governance_snapshot()`.
- Checked for `execution_allowed` flag: `False` → `blocked` mode.
- Attached to `SourceDispatchDecision`, `SourceDispatchPlan`, and `SourceDispatchResult` for downstream consumers.

### Policy Alignment (PR-28)
- Fetched automatically via `core.routes.projection._assemble_policy_alignment()`.
- `blocked` flag → `blocked` mode.
- `alignment_hints.can_expand_cross_device` → `remote_handoff` when target is available.
- `alignment_hints.can_execute_locally = False` → forced remote or blocked.

### Mesh Session (PR-33)
- Fetched automatically via `core.mesh.body_mesh_registry.BodyMeshRegistry.get_mesh_session()`.
- Multiple active participants → `staged_mesh` mode when no explicit target is given.
- Session ID propagated to `SourceDispatchTarget.mesh_session_id`.

### Mesh Membership (PR-32)
- Fetched automatically to assist target selection.
- Active member device IDs used as candidate targets.

All context signals degrade gracefully: if a module is unavailable, the orchestrator continues with partial context and defaults to safe local execution.

---

## Contracts

### `SourceDispatchMode` (enum)

| Value | Description |
|-------|-------------|
| `local` | Execute locally on the source runtime |
| `remote_handoff` | Delegate to a target runtime via HandoffEnvelopeV2 |
| `staged_mesh` | Coordinate across multiple devices (plan prepared; coordinator deferred) |
| `blocked` | Cannot dispatch due to policy/governance |
| `fallback_local` | Remote failed; fell back to local |
| `unknown` | Mode could not be determined |

### `SourceDispatchDecision`
The record of the dispatch decision: which mode was chosen, why, what target was selected, and which governance/policy context was active.

### `SourceDispatchTarget`
The selected execution target for remote or mesh dispatch (device ID, runtime ID, envelope ID, mesh session ID).

### `SourceDispatchPlan`
The full dispatch plan before execution: decision fields + pre-built HandoffEnvelopeV2 (if remote) + mesh session context + readiness assessment.

### `SourceDispatchResult`
The result after dispatch: success flag, raw result, execution trace (if local), takeover result (if remote), errors, and the governance/policy context that was active.

### `SourceDispatchSummary`
A compact, read-only projection summary suitable for dashboard tiles, trace metadata, and the `/api/v1/runtime/source-dispatch-summary` endpoint.

---

## Key functions

### `select_dispatch_mode(...) → (SourceDispatchMode, reason)`
Evaluates signals and returns the selected mode and a human-readable reason string.

### `select_dispatch_target(...) → SourceDispatchTarget | None`
Selects the execution target for remote/mesh dispatch.  Returns `None` for local mode.

### `build_source_dispatch_plan(...) → SourceDispatchPlan`
Assembles a full dispatch plan from available signals.  Pre-builds a HandoffEnvelopeV2 for remote mode.  Does **not** execute.

### `orchestrate_source_runtime_dispatch(...) → SourceDispatchResult`
End-to-end entry point.  Builds the plan, executes according to the selected mode, and returns a populated `SourceDispatchResult`.

### `SourceDispatchOrchestrator.dispatch(...) → SourceDispatchResult`
Stateless handler class wrapping `orchestrate_source_runtime_dispatch`.

### `SourceDispatchOrchestrator.plan(...) → SourceDispatchPlan`
Stateless handler class wrapping `build_source_dispatch_plan`.

---

## Projection endpoint

```
GET /api/v1/runtime/source-dispatch-summary
```

Returns a read-only `SourceDispatchSummary` reflecting the current dispatch posture.  This endpoint is **read-only** and never triggers execution.

Example response:

```json
{
  "summary_id": "...",
  "dispatch_id": "...",
  "trace_id": null,
  "mode": "local",
  "success": false,
  "decision_reason": "default_local",
  "target_device_id": null,
  "error_count": 0,
  "has_execution_trace": false,
  "has_takeover_result": false,
  "has_mesh_session": false,
  "timestamp": 1700000000.0
}
```

---

## Integration with existing execution paths

### Local execution
`orchestrate_source_runtime_dispatch` calls `OpenClawd._run_execution()` via `_try_run_local_execution()`.  If OpenClawd is unavailable (e.g. in test environments), a `skipped_reason: executor_unavailable` result is returned.

### Remote handoff
For `remote_handoff` mode, a `HandoffEnvelopeV2` is pre-built and forwarded via `galaxy_gateway.agent_bridge.AgentBridge.forward_handoff()`.  If the bridge is unavailable or the handoff fails, the orchestrator automatically falls back to local execution (`fallback_local` mode).

### Staged mesh (deferred)
For `staged_mesh` mode, a plan summary is returned with:
```json
{
  "action_taken": "staged_mesh_plan_prepared",
  "note": "Staged mesh dispatch plan prepared. Full Mesh Session Coordinator execution deferred to PR-37."
}
```
Full coordinator execution is out of scope for PR-35.

---

## What this PR explicitly does NOT do

- **No full Mesh Session Coordinator engine** — deferred to PR-37.
- **No UI/dashboard redesign** — additive read-only projection endpoint only.
- **No persistence/streaming redesign** — out of scope.
- **No broad execution-core rewrite** — `openclawd.py` and `agent_bridge.py` are unchanged.
- **No full registration-flow rewrite** — out of scope.
- **No Node_71 major rewrite** — out of scope.

---

## Architectural position

```
PR-25  Execution Trace Contract
PR-27  Runtime Governance Snapshot
PR-28  Execution Policy Alignment Surface
PR-29  Unified Registered Runtime Device Contract
PR-30  Local Runtime Host Contract
PR-31  Unified Handoff Envelope v2
PR-32  Mesh Membership Contract
PR-33  Mesh Session Contract
PR-34  Target Runtime Local Takeover Path
PR-35  Source Runtime Dispatch Orchestrator  ← this PR
          │
          ├── PR-36  Cross-Runtime Result Merge Contract
          ├── PR-37  Mesh Session Coordinator
          └── PR-38  Unified Multi-Device Runtime Projection
```

The Source Runtime Dispatch Orchestrator is the **foundation** for the mesh coordinator layer that comes next.
