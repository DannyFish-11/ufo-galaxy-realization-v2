# Agent Responsibility & Dispatch Governance

**PR-18 (V4) — Agent Responsibility Graph & Dispatch Governance**

This document describes the additive `core/agent_governance/` package that
formalises agent roles, ownership rules, and handoff governance for the
already-existing agent dispatch and runtime handoff paths in the Galaxy
system.

---

## Why this layer exists

As the system scales across multiple devices and agent runtimes, agent
dispatch must be governed by **explicit ownership rules** so it is always
clear:

- which agent is responsible for the final outcome of a task
- how ownership transfers across handoffs
- which agent roles can hand off to which other roles
- how fallback and recovery affect agent ownership

Without a formal responsibility graph, agent dispatch is ambiguous, and
recovery / accountability are unclear.

This package introduces a stable, additive agent-governance layer with
explicit roles, ownership rules, and handoff governance, **integrated with
existing dispatch/runtime paths in a read-only or metadata-enrichment way**.

---

## Agent roles

Defined in `core/agent_governance/agent_role.py` as the `AgentRole` enum.
String values are stable identifiers safe for serialisation, logging, and
API responses.

| Role               | Value               | Description                                                                                      |
|--------------------|---------------------|--------------------------------------------------------------------------------------------------|
| `PLANNER`          | `planner`           | Decomposes goals into sub-tasks and dispatches child agents. Holds initial dispatch ownership.  |
| `EXECUTOR`         | `executor`          | Executes a specific task or sub-task. Owns the final outcome of its assigned slot.              |
| `BRIDGE`           | `bridge`            | Mediates runtime handoff between agents or across device boundaries (maps to `AgentBridge`).    |
| `RECOVERY`         | `recovery`          | Takes over when the primary executor fails or a handoff times out. Owns fallback outcome.       |
| `OBSERVER`         | `observer`          | Monitors progress. No execution responsibility.                                                 |
| `LOCAL_ASSISTANT`  | `local_assistant`   | Local-device assistant. May escalate via handoff to `REMOTE_SPECIALIST`.                        |
| `REMOTE_SPECIALIST`| `remote_specialist` | Specialist on a remote device/runtime. Accepts handoffs from bridge.                            |
| `UNASSIGNED`       | `unassigned`        | Role not yet determined. Provisional state.                                                     |

### Role precedence

When multiple candidate roles apply to a single dispatch event and one must
be chosen, the precedence order (most to least authoritative) is:

1. `PLANNER`
2. `RECOVERY`
3. `EXECUTOR`
4. `BRIDGE`
5. `LOCAL_ASSISTANT`
6. `REMOTE_SPECIALIST`
7. `OBSERVER`
8. `UNASSIGNED`

---

## Ownership rules

Ownership semantics are defined in
`core/agent_governance/responsibility_graph.py` and
`core/agent_governance/ownership_summary.py`.

A task dispatch event moves through three ownership phases:

1. **`dispatch_owner`** — the role that initiated the dispatch (`PLANNER` or
   `LOCAL_ASSISTANT` in most cases). Set at dispatch start; does not change.

2. **`current_owner`** — the role currently holding execution responsibility.
   This transitions via valid handoffs (see the handoff graph below).

3. **`final_outcome_owner`** — the role that produced the final result: the
   successful `EXECUTOR` or `REMOTE_SPECIALIST` on success, or the `RECOVERY`
   agent on fallback.

### OwnershipRecord

`OwnershipRecord` is a mutable dataclass that tracks the ownership lifecycle.
Key fields:

| Field                 | Type              | Description                                                          |
|-----------------------|-------------------|----------------------------------------------------------------------|
| `dispatch_owner`      | `AgentRole`       | Role that initiated dispatch. Immutable after creation.              |
| `current_owner`       | `AgentRole`       | Role currently holding execution responsibility.                     |
| `final_outcome_owner` | `AgentRole \| None` | Role that produced the final outcome. `None` until lifecycle ends. |
| `handoff_count`       | `int`             | Number of ownership transfers applied.                               |
| `is_recovery_active`  | `bool`            | `True` when RECOVERY holds ownership.                                |
| `is_complete`         | `bool`            | `True` when the lifecycle is closed.                                 |
| `trace_id` / `task_id`| `str \| None`     | Optional identity fields for correlation.                            |

`apply_ownership_transfer(record, target_role, reason)` attempts to transfer
ownership and returns an `OwnershipTransferResult` without raising. Invalid
transfers (wrong edge, lifecycle complete) return `success=False`.

---

## Handoff governance

### Responsibility graph

The handoff graph defines which `(source_role → target_role)` transitions are
**valid**. Transitions outside this set are flagged as invalid but never raise
exceptions.

```
PLANNER          → EXECUTOR, BRIDGE, LOCAL_ASSISTANT, REMOTE_SPECIALIST
EXECUTOR         → BRIDGE, REMOTE_SPECIALIST, RECOVERY
LOCAL_ASSISTANT  → BRIDGE, REMOTE_SPECIALIST, RECOVERY
BRIDGE           → EXECUTOR, REMOTE_SPECIALIST, RECOVERY
RECOVERY         → EXECUTOR   (re-try after recovery)
REMOTE_SPECIALIST→ RECOVERY
OBSERVER         → (none — observer never initiates handoffs)
UNASSIGNED       → (none — unresolved role)
```

Any edge targeting `RECOVERY` is a **recovery transition**: ownership
transfers to the recovery agent, which may then re-try via `EXECUTOR` or
report terminal failure.

The `AgentBridge` `local_fallback` path corresponds to `BRIDGE → RECOVERY`
ownership transfer when the remote runtime is unreachable.

### HandoffPolicy

`HandoffPolicy` (in `core/agent_governance/handoff_policy.py`) is an
**advisory** policy contract governing handoff behaviour. Enforcement is the
responsibility of the dispatch layer (`AgentBridge`, `CommandRouter`).

| Field                    | Default | Description                                                         |
|--------------------------|---------|---------------------------------------------------------------------|
| `ack_required`           | `True`  | Receiving agent must acknowledge before sender releases ownership.  |
| `recovery_permitted`     | `True`  | RECOVERY may inherit ownership on failure.                          |
| `max_handoff_depth`      | `5`     | Maximum sequential ownership transfers before chain is stale.      |
| `handoff_timeout_hint_ms`| `10000` | Advisory timeout for the handoff window.                            |
| `allow_recovery_retry`   | `True`  | RECOVERY may attempt one retry via EXECUTOR.                        |

Pre-built policies:

- `DEFAULT_HANDOFF_POLICY` — conservative default (ack required, depth ≤ 5, recovery permitted)
- `RECOVERY_HANDOFF_POLICY` — recovery-focused (best-effort ack, depth ≤ 2)
- `OBSERVER_HANDOFF_POLICY` — observer role (no handoffs, depth = 0)

---

## Dispatch summary adapters

`core/agent_governance/dispatch_summary.py` provides helpers that enrich
existing dispatch results with governance metadata **without breaking existing
signatures**.

### `attach_dispatch_summary_to_handoff_result`

Enriches the dict returned by `AgentBridge.handoff()` or
`AgentBridge.handoff_from_envelope()` with an `"agent_governance"` key:

```python
from core.agent_governance import attach_dispatch_summary_to_handoff_result

result = await agent_bridge.handoff(contract)
enriched = attach_dispatch_summary_to_handoff_result(
    result,
    dispatch_role_str="local_assistant",
    target_role_str="remote_specialist",
)
# enriched["agent_governance"] contains dispatch/ownership summary
```

### `attach_dispatch_summary_to_result`

Enriches any dispatch result dict (e.g. from `CommandRouter.dispatch_agent_remote`):

```python
from core.agent_governance import (
    resolve_dispatch_summary,
    attach_dispatch_summary_to_result,
)

summary = resolve_dispatch_summary(
    dispatch_role_str="planner",
    target_role_str="executor",
    dispatch_success=result.get("success", False),
    trace_id=result.get("trace_id"),
    task_id=result.get("task_id"),
)
enriched = attach_dispatch_summary_to_result(result, summary)
```

### `attach_dispatch_summary_to_projection`

Attaches a `DispatchSummary` to any `RuntimeProjection` dict additively:

```python
from core.agent_governance import (
    IDLE_DISPATCH_SUMMARY,
    attach_dispatch_summary_to_projection,
)

projection = attach_dispatch_summary_to_projection(projection, IDLE_DISPATCH_SUMMARY)
# projection["agent_dispatch"] is now populated
```

---

## Projection endpoint

**`GET /api/v1/projection/agent-dispatch`**

Returns the current `RuntimeProjection` enriched with the PR-18 agent
governance summary. Added to `core/routes/projection.py` as a read-only
endpoint following the PR-13/PR-14/PR-17 pattern.

The response contains all standard projection keys plus:

- `"agent_dispatch"` — full `DispatchSummary` dict (dispatch/target roles,
  ownership lifecycle, handoff validity, bridge source, policy reason)
- `"ownership_hints"` — compact scalar hints for quick downstream checks

Example response additions:

```json
{
  "agent_dispatch": {
    "schema_version": 1,
    "dispatch_role": "local_assistant",
    "target_role": "executor",
    "handoff_valid": true,
    "ownership": {
      "dispatch_owner": "local_assistant",
      "current_owner": "unassigned",
      "final_outcome_owner": null,
      "handoff_count": 0,
      "is_recovery_active": false,
      "is_complete": false,
      "max_handoff_depth": 5,
      "depth_exceeded": false,
      "recovery_permitted": true,
      "last_handoff_reason": "idle",
      "policy_reason": "default conservative policy"
    },
    "dispatch_success": false,
    "bridge_source": null,
    "policy_reason": "default conservative policy"
  },
  "ownership_hints": {
    "dispatch_owner": "local_assistant",
    "current_owner": "unassigned",
    "is_recovery_active": false,
    "is_complete": false,
    "depth_exceeded": false,
    "handoff_count": 0,
    "has_final_owner": false,
    "recovery_permitted": true
  }
}
```

---

## Relationship to device formation and cross-device routing

This package is the agent-level complement to
[PR-17 Device Formation & Multi-Device Group Model](DEVICE_FORMATION_AND_MULTI_DEVICE_GROUPS.md).

| Layer           | Package                    | Governs                                              |
|-----------------|----------------------------|------------------------------------------------------|
| Device level    | `core/device_formation/`   | Which devices participate and in what formation role |
| Agent level     | `core/agent_governance/`   | Which agent roles own what responsibility            |

The two packages are additive and complementary:

- Device formation answers: *which physical devices are in the group and what
  is each device's formation role?*
- Agent governance answers: *which agent role owns the task outcome on each
  device, and how does ownership transfer across handoffs?*

For cross-device routing:
- `PLANNER` on the source device dispatches via `BRIDGE` (`AgentBridge`
  handoff)
- `BRIDGE` transfers ownership to `REMOTE_SPECIALIST` on success, or to
  `RECOVERY` on failure (which maps to the `local_fallback` path in
  `AgentBridge`)
- `RECOVERY` may re-attempt via `EXECUTOR` or report terminal failure

---

## What this PR does NOT yet enforce

This PR introduces the governance **schema and vocabulary** layer. The
following are advisory or deferred to future work:

- **Full agent orchestration** — `HandoffPolicy` fields are advisory; actual
  timeout/retry enforcement remains in `AgentBridge`.
- **Live registry** — there is no live ownership registry that intercepts
  every dispatch in real time; summaries are derived from available context.
- **Dynamic role rebalancing** — automatic role reassignment based on health
  signals is not yet implemented.
- **Cross-lifecycle correlation** — correlating ownership chains across
  multiple sequential task lifecycles requires additional plumbing.

These are natural extensions for future reliability and recovery governance
work that can build on the stable schema defined here.

---

## Package structure

```
core/agent_governance/
├── __init__.py               Public API
├── agent_role.py             AgentRole enum, precedence, handoff sets
├── responsibility_graph.py   HANDOFF_GRAPH, OwnershipRecord, transfer logic
├── handoff_policy.py         HandoffPolicy dataclass, pre-built policies
├── ownership_summary.py      OwnershipSummary, builder, projection attachment
└── dispatch_summary.py       DispatchSummary, adapters for existing paths
```

---

## Tests

`tests/test_pr18_agent_governance.py` covers:

1. `AgentRole` enum — values, serialisation stability
2. Role capability helpers — `can_role_initiate_handoff`, `can_role_receive_handoff`
3. `HANDOFF_GRAPH` — structure, valid/invalid edges
4. `is_valid_handoff` — all expected valid edges, invalid edges
5. `describe_handoff_edge` — output format
6. `OwnershipRecord` — construction, `to_dict`, `from_dict`, round-trip
7. `apply_ownership_transfer` — valid transfer, invalid edge, lifecycle-complete guard
8. `HandoffPolicy` — construction, `to_dict`, `from_dict`, `is_depth_exceeded`
9. Pre-built policies — field values
10. `get_policy_for_role` — all roles
11. `OwnershipSummary` — construction, `to_dict`
12. `build_ownership_summary` — from record + policy
13. `make_ownership_summary` — from scalars, unknown role strings
14. `attach_ownership_to_projection` — additive, non-mutating
15. `get_ownership_hints` — all keys present
16. `DispatchSummary` — construction, `to_dict`
17. `build_dispatch_summary` — success path, failure path, recovery path
18. `resolve_dispatch_summary` — valid strings, unknown strings, graceful degradation
19. `attach_dispatch_summary_to_result` — additive, non-mutating
20. `attach_dispatch_summary_to_handoff_result` — success/failure extraction
21. `attach_dispatch_summary_to_projection` — additive, non-mutating
22. `IDLE_DISPATCH_SUMMARY` / `IDLE_OWNERSHIP_SUMMARY` sentinels
23. Projection route — `GET /api/v1/projection/agent-dispatch`
24. Graceful degradation when package unavailable

---

## Related documents

- [Cross-Plane Contract Map](CROSS_PLANE_CONTRACT_MAP.md)
- [Runtime Bridge](RUNTIME_BRIDGE.md)
- [Device Formation & Multi-Device Groups](DEVICE_FORMATION_AND_MULTI_DEVICE_GROUPS.md)
- [Distributed Task Merge & Recovery](DISTRIBUTED_TASK_MERGE_RECOVERY.md)
- [Execution Policy Enforcement](EXECUTION_POLICY_ENFORCEMENT.md)
