# PR-A: Canonical Task & Execution Spine

## Overview

PR-A establishes the **CanonicalTask** as the unified task ontology object
for the Galaxy runtime, and locks down
`CanonicalTask → TaskEnvelope → CommandRouter.route_envelope()` as the
**sole system-level execution spine**.

---

## Layer Hierarchy

```
CanonicalTask                 ← task ontology (core/canonical_task.py)
    │
    │  .project_to_task_envelope()
    ▼
TaskEnvelope                  ← execution projection / transport contract
    │
    │  CommandRouter.route_envelope()  ← SOLE DISPATCH SPINE
    ▼
transport / executor          ← gateway substrate
    │
    │  ResultEnvelope
    ▼
CanonicalTask.apply_result_envelope()   ← runtime/result update
```

### Roles

| Layer | Module | Role |
|-------|--------|------|
| **CanonicalTask** | `core/canonical_task.py` | Task ontology entity |
| **TaskEnvelope** | `core/schemas/task_envelope.py` | Execution projection / transport contract |
| **ResultEnvelope** | `core/schemas/task_envelope.py` | Execution result contract |
| **CommandRouter** | `core/command_router.py` | **Sole** system-level dispatch spine |
| **TaskAdapterLayer** | `core/task_adapter.py` | Input normalization → CanonicalTask |
| **LegacyDispatchRegistry** | `core/legacy_dispatch_registry.py` | Registry of demoted dispatch paths |

---

## CanonicalTask

The `CanonicalTask` is the **task entity** — it carries the full semantic
definition of a task from origin through planning, routing, execution, and
result. It is NOT a transport envelope.

### Field Groups

```
CanonicalTask
├── identity:   TaskIdentity
│   ├── task_id / trace_id / session_id
│   ├── root_task_id / parent_task_id
│
├── intent:     TaskIntent
│   ├── goal / origin / reason
│   └── requested_action
│
├── planning:   TaskPlanning
│   ├── priority / constraints
│   ├── required_capabilities / fallback_policy
│   └── remote_execution_mode
│
├── routing:    TaskRouting
│   ├── selected_targets / route_preference
│   ├── transport_preference / effective_path
│
├── execution:  TaskExecution
│   ├── tool / skill / command / args
│   ├── timeout_seconds / retry_policy
│   └── permission_level
│
├── graph:      TaskGraphRelations
│   ├── dependencies / children
│   ├── retry_of / fallback_of
│
├── result:     TaskResultSummary
│   ├── success / error_code
│   ├── failure_domain / result_summary
│
└── lifecycle:  TaskLifecycle
    created → admitted → planned → routed →
    dispatched → running → completed / failed / cancelled / degraded
```

### Usage

```python
from core.canonical_task import build_canonical_task, TaskOrigin, TaskLifecycle

# Build a task
task = build_canonical_task(
    goal="take screenshot",
    origin=TaskOrigin.API_REQUEST,
    requested_action="screenshot",
    selected_targets=["android_01"],
)

# Advance lifecycle
task.advance_lifecycle(TaskLifecycle.ADMITTED)
task.advance_lifecycle(TaskLifecycle.PLANNED)
task.advance_lifecycle(TaskLifecycle.ROUTED)

# Project to execution envelope
envelope = task.project_to_task_envelope()

# Dispatch (sole spine)
task.advance_lifecycle(TaskLifecycle.DISPATCHED)
result = await router.route_envelope(envelope)

# Update task from result
task = task.apply_result_envelope(result)
# task.lifecycle == TaskLifecycle.COMPLETED
```

---

## TaskAdapterLayer

`core/task_adapter.py` normalizes all task inputs into `CanonicalTask`.

### Supported Origins

| Origin | `TaskOrigin` value |
|--------|-------------------|
| HTTP/REST API call | `api_request` |
| AI agent intent | `ai_intent` |
| Workflow step | `workflow_step` |
| Orchestrator task | `orchestrator_task` |
| Device command | `device_command` |
| MCP tool call | `mcp_tool_call` |
| Skill invocation | `skill_invocation` |
| Scheduler | `scheduler` |

### Usage

```python
from core.task_adapter import adapt_to_canonical_task
from core.canonical_task import TaskOrigin

# From an API payload dict
task = adapt_to_canonical_task(
    {"tool_name": "screenshot", "targets": ["android_01"]},
    origin=TaskOrigin.API_REQUEST,
)

# From an existing TaskEnvelope (fast path — passthrough to CanonicalTask)
task = adapt_to_canonical_task(envelope, origin=TaskOrigin.API_REQUEST)

# From a CanonicalTask (no-op passthrough)
same_task = adapt_to_canonical_task(task)
```

---

## CommandRouter — Sole Dispatch Spine

`CommandRouter.route_envelope()` is the **only** system-level dispatch
authority. All paths MUST converge on this method.

The `CANONICAL_TASK_SPINE_INTEGRATED` sentinel in `core/command_router.py`
declares this invariant:

```python
from core.command_router import CANONICAL_TASK_SPINE_INTEGRATED
# "COMMAND_ROUTER::CANONICAL_TASK_SPINE_V1: ..."
```

---

## Legacy Dispatch Registry

`core/legacy_dispatch_registry.py` formally registers all dispatch paths
that bypass the canonical spine. Each entry has an explicit classification:

| Classification | Meaning |
|----------------|---------|
| `compat-only` | Kept for backward compatibility; must not be extended |
| `deprecated` | Will be removed; migrate to canonical spine |
| `facade-only` | Demoted to facade/planner helper; no dispatch authority |

### Pre-registered entries (bootstrapped)

| Module | Classification | PR |
|--------|---------------|-----|
| `fusion.unified_orchestrator` | `facade-only` | PR-3 |
| `galaxy_gateway.orchestrator.galaxy_orchestrator` | `facade-only` | PR-3 |
| `core.e2e_orchestrator` | `facade-only` | PR-3 |
| `core.device_orchestrator` | `facade-only` | PR-3 |
| `galaxy_gateway.task_router` | `deprecated` | PR-3 |
| `core.local_execution_chain` | `compat-only` | PR-3 |
| `core.cross_device_execution_chain` | `compat-only` | PR-3 |
| `core.hybrid_executor` | `compat-only` | PR-3 |
| `core.remote_execution_mode_resolver` | `compat-only` | PR-3 |
| `galaxy_gateway.agent_bridge` | `compat-only` | PR-3 |
| `galaxy_gateway.cross_device_coordinator` | `compat-only` | PR-3 |
| `core.execution_spine` | `compat-only` | PR-A |
| `core.repo_coordinator` | `facade-only` | PR-A |

### Usage

```python
from core.legacy_dispatch_registry import (
    get_legacy_dispatch_registry,
    register_legacy_dispatch,
    snapshot_registry,
    LegacyDispatchClassification,
)

# Check if a module is registered as legacy
reg = get_legacy_dispatch_registry()
entry = reg.get("fusion.unified_orchestrator")
print(entry.classification)   # "facade-only"

# Register a new legacy path
register_legacy_dispatch(
    "my.legacy.module",
    LegacyDispatchClassification.DEPRECATED,
    reason="Will be removed in next PR.",
    pr_origin="PR-X",
)

# Get snapshot for observability
snap = snapshot_registry()
print(f"Total legacy entries: {snap.total_entries}")
```

---

## Orchestrator Demotion

Legacy orchestrators are demoted to **facade / planner helpers / graph contributors**.
They MUST NOT perform system-level dispatch independently.

### fusion.unified_orchestrator

```python
from fusion.unified_orchestrator import UNIFIED_ORCHESTRATOR_CANONICAL_TASK_FACADE
# "UNIFIED_ORCHESTRATOR::CANONICAL_TASK_FACADE_V1: ..."
```

### galaxy_gateway.orchestrator.galaxy_orchestrator

```python
from galaxy_gateway.orchestrator.galaxy_orchestrator import GALAXY_ORCHESTRATOR_CANONICAL_TASK_FACADE
# "GALAXY_ORCHESTRATOR::CANONICAL_TASK_FACADE_V1: ..."
```

---

## Architecture Invariants

1. Every task entering the Galaxy runtime SHOULD be represented as a
   `CanonicalTask` before dispatch.

2. `TaskEnvelope` is derived FROM a `CanonicalTask` via
   `CanonicalTask.project_to_task_envelope()`.

3. `ResultEnvelope` flows back and updates the `CanonicalTask` via
   `CanonicalTask.apply_result_envelope()`.

4. `CommandRouter.route_envelope()` is the **sole** system-level dispatch
   spine. `CanonicalTask` does NOT dispatch; it only produces envelopes.

5. Legacy orchestrators remain as facade/planner helpers; they may
   **contribute** to a `CanonicalTask` but MUST NOT dispatch outside the spine.

6. All legacy dispatch shortcuts MUST be registered in
   `LegacyDispatchRegistry` with explicit classification.

---

## Tests

| File | Coverage |
|------|----------|
| `tests/test_canonical_task_model.py` | CanonicalTask entity, enums, lifecycle, projection, result update |
| `tests/test_execution_spine_uniqueness.py` | Spine sentinels, round-trip, orchestrator facade demotion |
| `tests/test_legacy_dispatch_registry.py` | Registry CRUD, bootstrap entries, classification |
| `tests/test_task_adapter_normalization.py` | All 8 origins, passthrough, log, key extraction |

---

## Relationship to Previous PRs

| PR | Module | Role under PR-A |
|----|--------|-----------------|
| PR-1 | `core/truth_integration_layer.py` | Device truth for CanonicalTask routing |
| PR-2 | `core/message_interop.py` | Interop adapter used by task_adapter |
| PR-3 | `core/execution_spine.py` | Legacy ingress normalizer (compat-only) |
| PR-4 | `core/agent_bus_fabric.py` | Transport strategy for TaskEnvelope dispatch |
| PR-5 | `core/admissibility_policy_convergence.py` | Policy for TaskPlanning gate |
| PR-6 | `core/task_graph_runtime.py` | CanonicalTask → graph node projection |
| PR-7 | `core/capability_assimilation.py` | Capability gate for required_capabilities |
| PR-8 | `core/network_topology_runtime.py` | Network topology for routing.effective_path |
