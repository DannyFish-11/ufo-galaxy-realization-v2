# Local Execution Chain — Canonical Definition

> **Status**: Canonical  
> **Introduced**: PR-4 (Formalize Local & Cross-Device Execution Chains)  
> **Module**: `core/local_execution_chain.py`  
> **Parallel chain**: [`CROSS_DEVICE_EXECUTION_CHAIN.md`](CROSS_DEVICE_EXECUTION_CHAIN.md)

---

## 1. What It Is

The **local execution chain** is one of two first-class canonical runtime
chains owned by the unified subject.  It covers all execution that stays
on the **local Windows desktop device** — requests that do not delegate to
a remote node, phone, or cloud worker.

The chain is not just an implicit default.  It is a formal, ordered
sequence of steps with documented authority ownership at each stage, defined
feedback/backflow semantics, and projection-facing summary support.

Together with the cross-device chain, it forms the complete execution
surface of the unified subject runtime:

```
DesktopPresenceRuntime (outer shell / Windows clothing)
    └─ unified subject runtime
          ├─ LOCAL EXECUTION CHAIN      ← this document
          └─ CROSS-DEVICE EXECUTION CHAIN
```

---

## 2. What Triggers It

The local chain is triggered when `OpenClawd` selects an execution path
that does **not** delegate to a remote device or gateway.  Concretely, the
control-plan field `execution_path` resolves to one of:

| `ExecutionPathKind` value | Description |
|---|---|
| `local` | Fully local — Windows / System API execution only |
| `none` | No-op / blocked — subject at rest; no manifest action |

The decision is made by `OpenClawd._select_multimodal_route()` together
with `UnifiedExecutionDecision` (see `core/schemas/unified_control_plan.py`).

---

## 3. Canonical Step Ordering

```
Step 1 — openclawd_dispatch
    OpenClawd receives the request, selects multimodal route, and determines
    that execution will stay local.  Authority: OpenClawd (subject_decision_authority).

Step 2 — agent_kernel_plan
    AgentKernel.run() produces a plan / intent over the LLM continuum loop.
    Authority: AgentKernel (cognition_planning_layer).  NOTE: AgentKernel is a
    planning layer only — it does not hold final execution authority.

Step 3 — command_router_local
    CommandRouter.route_envelope() is called with LOCAL_MANIFESTATION mode.
    Authority: CommandRouter (execution_substrate).  The router resolves the
    local execution target (Windows API, system command, capability module).

Step 4 — local_executor
    The resolved executor (Windows API adapter, skill, MCP tool, capability
    module) performs the action on the local device.
    Authority: capability/skill module (executor only; no planning authority).

Step 5 — result_capture
    The raw result from the local executor is captured and normalised into a
    LocalExecutionResult (see core/local_execution_chain.py).
    Authority: local_execution_chain module.

Step 6 — openclawd_feedback
    OpenClawd receives the normalised result, applies memory backflow,
    produces the final response, and emits projection updates.
    Authority: OpenClawd (subject_decision_authority).
```

Canonical step order constant: `LOCAL_CHAIN_ORDER` in `core/local_execution_chain.py`.

---

## 4. Authority at Each Stage

| Step | Authority owner | Authority label |
|---|---|---|
| `openclawd_dispatch` | `core.openclawd` | `subject_decision_authority` |
| `agent_kernel_plan` | `core.agent.kernel` | `cognition_planning_layer` |
| `command_router_local` | `core.command_router` | `execution_substrate` |
| `local_executor` | capability/skill/MCP module | `executor_only` |
| `result_capture` | `core.local_execution_chain` | `result_normaliser` |
| `openclawd_feedback` | `core.openclawd` | `subject_decision_authority` |

Key invariants:
- **OpenClawd** is the sole routing decision authority.  No adapter surface
  or skill module may reroute execution.
- **AgentKernel** is a *planning layer* — it does not hold final authority.
- **CommandRouter** is the canonical local execution router; other modules
  must not call local executors directly.

---

## 5. Feedback / Backflow Semantics

Once `local_executor` completes:

1. The raw result is normalised into a `LocalExecutionResult` dataclass by
   `build_local_execution_result()`.
2. The record is appended to the `LocalExecutionChainSingleton` (bounded,
   in-memory audit log; max 200 records by default).
3. OpenClawd receives the `LocalExecutionResult` and:
   - Applies memory backflow (if `core.openclawd_memory_backflow` is active).
   - Emits projection updates (`DesktopStatusProjection`).
   - Advances the tri-state lifecycle from `MANIFEST → SILENT`.

There is **no** async back-channel for local execution results — they flow
synchronously back to OpenClawd through the return path of
`CommandRouter.route_envelope()`.

---

## 6. Projection / Status Surface

The local execution chain surfaces into projections through:

| Surface | Field |
|---|---|
| `contracts.desktop_status_projection.ExecutionProjection` | `execution_path = ExecutionPathKind.local` |
| `contracts.desktop_status_projection.ExecutionProjection` | `execution_reason` (human-readable rationale) |
| `core.local_execution_chain.LocalChainSnapshot` | Serialisable snapshot of recent local executions |

Projection consumers should check `execution_path == "local"` to identify
local chain activity.  The `LocalChainSnapshot` is suitable for embedding
in debug/audit endpoints and for later liminal-space mapping work.

---

## 7. Relationship to Cross-Device Chain

The local and cross-device chains are **parallel, symmetric** concepts:

| Dimension | Local chain | Cross-device chain |
|---|---|---|
| Execution scope | Local device only | Remote device / gateway |
| Result container | `LocalExecutionResult` | `ResultEnvelope` |
| Record type | `LocalExecutionRecord` | `ChainExecutionRecord` |
| Singleton | `LocalExecutionChainSingleton` | `CrossDeviceChainSingleton` |
| Snapshot | `LocalChainSnapshot` | `CrossDeviceChainSnapshot` |
| Authority at routing | OpenClawd | OpenClawd |
| Authority at routing layer | CommandRouter (LOCAL_MANIFESTATION) | CommandRouter (REMOTE_COMMAND / REMOTE_AGENT) |
| Feedback path | Synchronous return | `ResultEnvelope` → OpenClawd feedback step |

Both chains belong to the same unified subject runtime.  Neither is more
"real" than the other.

---

## 8. Legacy / Non-Canonical Paths

The following patterns are **non-canonical** for local execution and should
be avoided:

- Calling a Windows/System API adapter directly from an adapter surface
  (chat route, gateway) without going through `CommandRouter`.
- Skipping `OpenClawd` and invoking `AgentKernel` directly.
- Maintaining parallel result state in adapter surfaces instead of
  consuming the `LocalChainSnapshot`.

Non-canonical paths are tracked in
`core.orchestration_authority.legacy_paths.LEGACY_PATH_REGISTRY`.

---

## 9. Module Reference

```
core/local_execution_chain.py
    LocalChainStep           — enum of canonical local chain steps
    LOCAL_CHAIN_STEP_AUTHORITIES  — step → authority-owner mapping
    LOCAL_CHAIN_ORDER        — ordered list of canonical steps
    LocalExecutionResult     — normalised local result container
    LocalExecutionRecord     — per-execution record (is_canonical, steps, result)
    LocalChainSnapshot       — serialisable snapshot (recent records + metadata)
    LocalExecutionChainSingleton  — bounded in-memory audit log
    build_local_execution_result()   — construct a LocalExecutionResult
    build_local_execution_record()   — construct a LocalExecutionRecord
    record_local_execution()         — append to singleton + return record
    build_local_chain_snapshot()     — build LocalChainSnapshot from singleton
    get_local_execution_chain()      — return global singleton
    reset_local_execution_chain()    — reset singleton (testing only)
```
