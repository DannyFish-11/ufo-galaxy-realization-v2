# Cross-Device Execution Chain — Canonical Definition

> **Status**: Canonical  
> **Introduced**: PR-7 (Canonicalize OpenClawd Cross-Device Execution Chain)  
> **Aligned / docs strengthened**: PR-4 (Formalize Local & Cross-Device Execution Chains)  
> **Module**: `core/cross_device_execution_chain.py`  
> **Parallel chain**: [`LOCAL_EXECUTION_CHAIN.md`](LOCAL_EXECUTION_CHAIN.md)

---

## 1. What It Is

The **cross-device execution chain** is one of two first-class canonical
runtime chains owned by the unified subject.  It covers all execution that
**delegates from the local desktop to a remote device, phone, or cloud worker**
via the Galaxy gateway substrate.

The chain is strictly bounded: only `CommandRouter` may initiate cross-device
dispatch.  All other modules that attempt independent cross-device dispatch
are classified as legacy compatibility paths.

Together with the local chain, it forms the complete execution surface of
the unified subject runtime:

```
DesktopPresenceRuntime (outer shell / Windows clothing)
    └─ unified subject runtime
          ├─ LOCAL EXECUTION CHAIN
          └─ CROSS-DEVICE EXECUTION CHAIN  ← this document
```

---

## 2. What Triggers It

The cross-device chain is triggered when `OpenClawd` selects an execution
path that **delegates** to a remote device or gateway.  Concretely, the
control-plan field `execution_path` resolves to one of:

| `ExecutionPathKind` value | Description |
|---|---|
| `cross_device` | Single remote device execution via gateway |
| `hybrid` | Local + remote multi-device orchestration |

The decision is made by `OpenClawd._select_multimodal_route()` together
with `UnifiedExecutionDecision` (see `core/schemas/unified_control_plan.py`).

---

## 3. Canonical Step Ordering

```
Step 1 — openclawd_dispatch
    OpenClawd receives the request, selects multimodal route, and determines
    that execution will be delegated cross-device.
    Authority: OpenClawd (subject_decision_authority).

Step 2 — command_router
    CommandRouter.route_envelope() is called with REMOTE_COMMAND or
    REMOTE_AGENT mode.  This is the SOLE router for cross-device tasks.
    Authority: CommandRouter (execution_substrate).

Step 3 — task_envelope
    A TaskEnvelope / CommandEnvelope is constructed — the serialisable task
    contract that carries the intent to the gateway.
    Authority: task envelope builder (serialisation layer only).

Step 4 — gateway_substrate
    The Galaxy gateway substrate receives the task envelope and forwards it
    to the target device / worker node.  The gateway is execution plumbing
    only; it does not make planning or routing decisions.
    Authority: galaxy_gateway (execution_plumbing_only).

Step 5 — worker_executor
    The remote device / worker node executes the task and produces a raw
    result.  Workers are executors only; they do not plan.
    Authority: device/worker node (executor_only).

Step 6 — result_envelope
    The raw result is normalised into a ResultEnvelope (see
    core/cross_device_execution_chain.ResultEnvelope) before being returned
    to OpenClawd.  All cross-device results MUST pass through this step.
    Authority: core.cross_device_execution_chain (result_normaliser).

Step 7 — openclawd_feedback
    OpenClawd receives the ResultEnvelope, applies memory backflow, emits
    projection/audit updates, and produces the final response.
    Authority: OpenClawd (subject_decision_authority).
```

Canonical step order constant: `CANONICAL_CHAIN_ORDER` in
`core/cross_device_execution_chain.py`.

---

## 4. Authority at Each Stage

| Step | Authority owner | Authority label |
|---|---|---|
| `openclawd_dispatch` | `core.openclawd` | `subject_decision_authority` |
| `command_router` | `core.command_router` | `execution_substrate` |
| `task_envelope` | serialisation layer | `serialisation_only` |
| `gateway_substrate` | `galaxy_gateway` | `execution_plumbing_only` |
| `worker_executor` | device / worker node | `executor_only` |
| `result_envelope` | `core.cross_device_execution_chain` | `result_normaliser` |
| `openclawd_feedback` | `core.openclawd` | `subject_decision_authority` |

Key invariants:
- **OpenClawd** is the sole routing decision authority — it decides whether
  a request goes cross-device.
- **CommandRouter** is the *sole router* for cross-device tasks.  Other
  modules (e.g. `galaxy_gateway.orchestrator.*`) that attempt independent
  dispatch are legacy compatibility paths.
- **Gateway substrate** is execution plumbing only.  It must not make
  planning or routing decisions.
- **Workers / Devices / Nodes** are executors only.
- **All results** must be normalised into `ResultEnvelope` before being
  merged back into OpenClawd.

---

## 5. Feedback / Backflow Semantics

Once `worker_executor` produces a raw result:

1. The result is normalised into a `ResultEnvelope` at the
   `result_envelope` step by `build_result_envelope()`.
2. `record_chain_execution()` is called in the `openclawd_feedback` step,
   which:
   - Marks `result_envelope.openclawd_merged = True`.
   - Appends a `ChainExecutionRecord` to the `CrossDeviceChainSingleton`
     (bounded audit log; max 200 records by default).
3. OpenClawd processes the `ResultEnvelope` and:
   - Calls `core.openclawd_memory_backflow.store_result_envelope()` to
     persist the result in the memory/backflow subsystem.
   - Emits projection updates (`DesktopStatusProjection`).
   - Advances tri-state lifecycle from `MANIFEST → SILENT`.

**Backflow normalisation invariant**: all cross-device backflow results must
arrive at OpenClawd as `ResultEnvelope` objects.  Raw gateway dicts must
never be passed directly to OpenClawd or the projection layer.

---

## 6. Projection / Status Surface

The cross-device execution chain surfaces into projections through:

| Surface | Field |
|---|---|
| `contracts.desktop_status_projection.ExecutionProjection` | `execution_path = ExecutionPathKind.cross_device` or `hybrid` |
| `contracts.desktop_status_projection.ExecutionProjection` | `remote_execution_mode` (`"command_only"` or `"agent_runtime"`) |
| `contracts.desktop_status_projection.ExecutionProjection` | `target_device_ids` (IDs of targeted remote devices) |
| `contracts.desktop_status_projection.ExecutionProjection` | `orchestration_active` (multi-device orchestration flag) |
| `core.cross_device_execution_chain.CrossDeviceChainSnapshot` | Serialisable snapshot of recent cross-device executions |

Projection consumers should check `execution_path in ("cross_device", "hybrid")`
to identify cross-device chain activity.  The `CrossDeviceChainSnapshot` is
suitable for embedding in debug/audit endpoints and for later liminal-space
mapping work.

---

## 7. Relationship to Local Chain

The cross-device and local chains are **parallel, symmetric** concepts:

| Dimension | Cross-device chain | Local chain |
|---|---|---|
| Execution scope | Remote device / gateway | Local device only |
| Result container | `ResultEnvelope` | `LocalExecutionResult` |
| Record type | `ChainExecutionRecord` | `LocalExecutionRecord` |
| Singleton | `CrossDeviceChainSingleton` | `LocalExecutionChainSingleton` |
| Snapshot | `CrossDeviceChainSnapshot` | `LocalChainSnapshot` |
| Authority at routing | OpenClawd | OpenClawd |
| Authority at routing layer | CommandRouter (REMOTE_COMMAND / REMOTE_AGENT) | CommandRouter (LOCAL_MANIFESTATION) |
| Feedback path | `ResultEnvelope` → OpenClawd feedback step | Synchronous return |

Both chains belong to the same unified subject runtime.  Neither is more
"real" than the other.

---

## 8. Legacy / Non-Canonical Paths

The following patterns are **non-canonical** for cross-device execution and
are formally tracked as legacy compatibility paths:

| Path | Legacy reason |
|---|---|
| `galaxy_gateway.orchestrator.GalaxyOrchestrator` | Makes routing decisions that belong to CommandRouter/OpenClawd |
| `galaxy_gateway.orchestrator.TaskOrchestrator` | Independent task dispatch outside canonical chain |
| `galaxy_gateway.device_router.DeviceRouter.route_task` | Independent routing outside CommandRouter |
| `galaxy_gateway.cross_device_coordinator.CrossDeviceCoordinator` | Independent cross-device coordination |

Non-canonical paths are tracked in
`core.orchestration_authority.legacy_paths.LEGACY_PATH_REGISTRY`.

---

## 9. Module Reference

```
core/cross_device_execution_chain.py
    CanonicalChainStep       — enum of canonical cross-device chain steps (7 steps)
    CHAIN_STEP_AUTHORITIES   — step → authority-owner mapping
    CANONICAL_CHAIN_ORDER    — ordered list of canonical steps
    ResultEnvelope           — normalised cross-device result container
    ChainExecutionRecord     — per-execution record (is_canonical, steps, result)
    CrossDeviceChainSnapshot — serialisable snapshot (recent records + metadata)
    CrossDeviceChainSingleton — bounded in-memory audit log
    build_result_envelope()           — construct a ResultEnvelope
    build_chain_execution_record()    — construct a ChainExecutionRecord
    record_chain_execution()          — append to singleton + return record
    build_cross_device_chain_snapshot() — build CrossDeviceChainSnapshot from singleton
    get_cross_device_chain()          — return global singleton
    reset_cross_device_chain()        — reset singleton (testing only)
```
