# Cross-Device Role & Routing Policy

> **Unified-Subject Architecture**: Cross-device routing is **not** a parallel
> system alongside the subject.  It is the subject's **liminal execution expanding
> beyond the local Windows host** — the cross-device arm of OpenClawd's execution
> branching.
>
> When `OpenClawd._determine_execution_path()` resolves to `"cross_device"` or
> `"hybrid"`, the `CommandRouter` (cross-device expansion arm) uses this policy
> layer to determine how to route to remote devices.  The `galaxy_gateway` is the
> internal transport substrate, not a primary entrypoint.
>
> See [`docs/UNIFIED_SUBJECT_ARCHITECTURE.md`](UNIFIED_SUBJECT_ARCHITECTURE.md) §5.

**PR-13 (V4) — Cross-Device Role & Routing Policy**

This document describes the formal cross-device role and routing policy layer
introduced in PR-13.  It is an additive layer built on top of the existing
execution policy (PR-11/PR-12), orchestration authority (PR-9), and return
intelligence (PR-10) foundations.

---

## Overview

Before PR-13, `runtime_domain = cross_device` was a valid label in the
`RuntimeDomain` enum, but it carried no explicit role or routing semantics.
Any participating device was simply a "target device" without a stable,
serialisable description of its function.

PR-13 introduces a focused additive package — `core/cross_device_policy/` —
that formalises:

1. **Device roles**: what function each participating device plays
2. **Routing posture**: what routing strategy governs how the task is dispatched
3. **Routing policy**: the full set of fields needed to express a routing contract
4. **Assignment summary**: a stable, JSON-serialisable summary suitable for APIs
   and projection surfaces
5. **Routing resolver**: a function that derives routing policy from available signals

---

## Package Structure

```
core/cross_device_policy/
  __init__.py           — public API
  device_role.py        — DeviceRole enum + DeviceRoleAssignment dataclass
  routing_policy.py     — RoutingPosture enum + RoutingPolicy dataclass
  assignment_summary.py — CrossDeviceAssignmentSummary + projection helpers
  routing_resolver.py   — resolve_routing() + resolve_routing_summary()
```

---

## Device Role Definitions

`DeviceRole` is a stable `str` enum.  Each participating device in a
`cross_device` task is assigned exactly one role.

| Role                     | Value                      | Meaning                                                                         |
|--------------------------|----------------------------|---------------------------------------------------------------------------------|
| `SOURCE`                 | `source_device`            | Device that originated the request.  May not be the executor.                  |
| `PRIMARY_EXECUTION`      | `primary_execution_device` | Device primarily responsible for executing the task.  Exactly one per task.    |
| `SUPPORT`                | `support_device`           | Assists the primary executor (e.g. with camera, compute, sensor).               |
| `OBSERVER`               | `observer_device`          | Receives read-only view of progress and results.  Does not execute.             |
| `RELAY`                  | `relay_device`             | Forwards commands/data; does not execute tasks itself.                          |
| `FALLBACK`               | `fallback_device`          | Eligible to take over PRIMARY_EXECUTION if the primary becomes unavailable.     |
| `UNASSIGNED`             | `unassigned`               | In the roster but not yet assigned a role (provisional).                        |

Role assignments are recorded in `DeviceRoleAssignment` — an immutable,
serialisable record with fields: `device_id`, `role`, `reason`,
`capabilities`, `is_local`.

---

## Routing Posture Definitions

`RoutingPosture` is a stable `str` enum that expresses the intended routing
strategy for a task.

| Posture                | Value                   | Meaning                                                                         |
|------------------------|-------------------------|---------------------------------------------------------------------------------|
| `LOCAL_PREFERRED`      | `local_preferred`       | Attempt local execution first; do not expand unless local cannot satisfy.       |
| `LOCAL_THEN_EXPAND`    | `local_then_expand`     | Begin locally; expand to cross-device if policy and capacity permit.            |
| `REMOTE_REQUIRED`      | `remote_required`       | Must be dispatched to a remote device; local is not acceptable.                 |
| `SPLIT_EXECUTION`      | `split_execution`       | Task split across multiple devices (parallel branches merged later).            |
| `MIRRORED_OBSERVATION` | `mirrored_observation`  | Primary executes locally; remote device(s) receive a mirrored read-only view.  |
| `UNDECIDED`            | `undecided`             | Posture has not yet been determined (provisional).                              |

---

## Routing Policy

`RoutingPolicy` is a frozen, serialisable dataclass that packages the full
routing intent:

| Field                                  | Type                            | Description                                                       |
|----------------------------------------|---------------------------------|-------------------------------------------------------------------|
| `posture`                              | `RoutingPosture`                | The routing posture (see above).                                  |
| `source_device_id`                     | `str \| None`                   | Device that originated the request.                              |
| `assigned_devices`                     | `list[DeviceRoleAssignment]`    | All participating devices and their roles.                        |
| `runtime_domain_intent`                | `str \| None`                   | Intended `RuntimeDomain` value (plain string).                   |
| `policy_reason`                        | `str`                           | Human-readable explanation of the routing choice.                |
| `expansion_allowed_by_execution_policy`| `bool`                          | Whether `ExecutionPolicy.cross_device_allowed` is True.          |
| `confirmation_required_before_expansion`| `bool`                         | Whether confirmation is required before cross-device expansion.  |
| `task_id`                              | `str \| None`                   | Optional task identifier.                                        |
| `trace_id`                             | `str \| None`                   | Optional distributed-trace identifier.                           |

Derived properties: `is_cross_device`, `primary_execution_device_id`,
`source_assignment`, `devices_with_role(role)`.

---

## Resolver Logic

`resolve_routing(**kwargs) → RoutingPolicy`

All inputs are optional.  The resolver degrades gracefully when signals are
absent.

**Signal sources** (read-only):

| Parameter             | Type                     | Used for                                           |
|-----------------------|--------------------------|----------------------------------------------------|
| `runtime_domain`      | `str \| RuntimeDomain`   | Primary gate: is cross-device routing relevant?    |
| `execution_policy`    | `ExecutionPolicy \| dict`| Gates expansion; provides confirmation requirement |
| `source_device_id`    | `str`                    | SOURCE role assignment                             |
| `target_device_ids`   | `list[str]`              | PRIMARY_EXECUTION + SUPPORT/OBSERVER role building |
| `authority_role`      | `str \| AuthorityRole`   | Legacy roles downgrade cross-device permission     |
| `task_envelope_meta`  | `dict`                   | Posture hints (split_execution, remote_required…)  |
| `task_id`             | `str`                    | Traceability                                       |
| `trace_id`            | `str`                    | Traceability                                       |

**Resolution steps**:

1. If `runtime_domain` is not `cross_device` → `LOCAL_PREFERRED` (local routing).
2. If `execution_policy.cross_device_allowed` is `False` → `LOCAL_PREFERRED`
   (expansion blocked by policy).
3. If authority role is `legacy_compatibility` or `deprecated` → downgrade to
   `LOCAL_PREFERRED` (legacy path cannot own cross-device routing).
4. Check `task_envelope_meta` for explicit posture hints:
   - `split_execution: True` → `SPLIT_EXECUTION`
   - `remote_required: True` → `REMOTE_REQUIRED`
   - `mirrored_observation: True` → `MIRRORED_OBSERVATION`
5. If explicit `target_device_ids` provided → `LOCAL_THEN_EXPAND`
6. Default → `LOCAL_THEN_EXPAND` (safest cross-device posture)

**Device assignment building**:

- `source_device_id` → `SOURCE` role (marked `is_local=True`)
- First `target_device_ids` entry → `PRIMARY_EXECUTION`
- For `MIRRORED_OBSERVATION`: subsequent entries → `OBSERVER`
- For `SPLIT_EXECUTION` and `LOCAL_THEN_EXPAND`: subsequent entries → `SUPPORT`

---

## Assignment Summary

`CrossDeviceAssignmentSummary` is a flattened, JSON-serialisable view of a
`RoutingPolicy`, designed for API responses and projection surfaces.  Key fields:

- `posture` (str)
- `source_device_id` (str | None)
- `primary_execution_device_id` (str | None)
- `support_device_ids` (list[str])
- `observer_device_ids` (list[str])
- `relay_device_ids` (list[str])
- `fallback_device_ids` (list[str])
- `all_assignments` (list[dict])
- `expansion_allowed_by_execution_policy` (bool)
- `confirmation_required_before_expansion` (bool)
- `is_cross_device` (bool)
- `policy_reason` (str)

Helpers:

- `build_assignment_summary(policy)` — convert `RoutingPolicy` to summary
- `attach_cross_device_to_projection(projection_dict, summary)` — additive dict enrichment
- `get_assignment_hints(summary)` — compact boolean/scalar hints

---

## Relationship to Other Layers

### Execution Policy (PR-11/PR-12)

`ExecutionPolicy.cross_device_allowed` is the primary gate that determines
whether cross-device routing is eligible.  The routing resolver reads this
field but does **not** modify the execution policy.

The execution policy governs *whether* cross-device is permitted.  The routing
policy governs *how* the routing is structured and *who* participates.

### Orchestration Authority (PR-9)

`AuthorityRole` is used to downgrade routing decisions.  `LEGACY_COMPATIBILITY`
and `DEPRECATED` paths are not allowed to own cross-device routing; the resolver
forces `LOCAL_PREFERRED` in those cases.

### Runtime Domain (PR-3)

`RuntimeDomain.CROSS_DEVICE` is the trigger for cross-device routing resolution.
The routing policy package does not modify the `RuntimeDomain` or `ContinuumState`
— it reads the domain as a signal.

### Return Intelligence (PR-10)

Return intelligence is not directly consumed by the routing resolver in PR-13,
but high return pressure (via `ExecutionPolicy.cross_device_allowed=False`)
transitively gates cross-device routing.

### TaskGraph / TaskEnvelope

The `task_envelope_meta` parameter allows TaskGraph-level hints (such as
`split_execution`, `remote_required`) to influence the routing posture.
The routing policy package does not modify the task graph — it enriches the
decision context.

---

## New API Endpoint

PR-13 adds one new read-only endpoint to the projection router:

```
GET /api/v1/projection/cross_device_routing
```

**Response** includes all standard `RuntimeProjection` fields plus nested
`execution_policy` (PR-11) and `cross_device_routing` blocks.

The `cross_device_routing` block contains the full `CrossDeviceAssignmentSummary`
derived from live runtime signals.

---

## What This PR Does NOT Solve

The following topics are explicitly **deferred** to later PRs:

- **Distributed merge/recovery** (PR-14): How to merge results from multiple
  devices, handle partial failures across device boundaries, and implement
  recovery/retry policies for remote executors.

- **Dynamic device health gating**: While `DeviceRole.FALLBACK` is defined,
  automatic promotion based on live health scores is not yet implemented.
  The resolver currently assigns fallback roles only from explicitly provided
  device lists.

- **Capability-based device selection**: The routing resolver accepts
  `target_device_ids` but does not yet query the device registry or capability
  system to auto-select suitable devices.

- **Task Semantics (PR-15)**: Step-level role assignment (e.g. which device
  handles a `perceive` step vs. an `execute` step) is not yet modelled.

---

## How Future Code Should Express Cross-Device Assignments

When writing new code that involves cross-device coordination:

```python
from core.cross_device_policy import resolve_routing_summary, attach_cross_device_to_projection

# Derive routing summary from available signals
summary = resolve_routing_summary(
    runtime_domain=state.runtime_domain,          # "cross_device"
    execution_policy=current_execution_policy,    # ExecutionPolicy from PR-11
    source_device_id=local_device_id,
    target_device_ids=selected_device_ids,
    authority_role=authority_role,                # AuthorityRole from PR-9
    task_id=envelope.task_id,
    trace_id=envelope.trace_id,
)

# Attach to projection or emit in observability event
enriched_projection = attach_cross_device_to_projection(projection.to_dict(), summary)

# Quick hints for decision gates
hints = get_assignment_hints(summary)
if hints["is_cross_device"] and hints["expansion_allowed_by_execution_policy"]:
    # proceed with cross-device dispatch
    ...
```

Do **not** bypass this layer to directly assign `target_device_ids` without
a routing policy — the policy layer is what makes `runtime_domain = cross_device`
a real routing contract rather than just a label.

---

## Tests

See `tests/test_pr13_cross_device_policy.py` for full coverage including:

- Enum/schema serialisation (sections A–E)
- Routing resolution from representative inputs (sections I–L)
- Partial/missing input handling (section M)
- Assignment summary generation (sections F–H, N)
- Projection endpoint integration (section O)
- Public API completeness (section P)
