# Task Semantics & Step Classes (PR-15)

## Overview

PR-15 introduces a stable, additive **task-semantics layer** (`core/task_semantics/`) that formalises semantic step meaning on top of the existing `TaskGraph`, `TaskEnvelope`, orchestration, and policy structures established by earlier V4 PRs.

This layer answers, for any given task step:

- **What kind of step is this?** (`perceive`, `analyze`, `decide`, `execute`, `confirm`, `notify`, `rollback`, `observe_remote`, `unknown`)
- **Is the step side-effectful?**
- **Can it run cross-device?**
- **Is failure skippable, or must the task halt?**
- **Should it be visible / prominent in manifest/projection surfaces?**
- **Should an observability highlight be emitted?**
- **What recovery posture is recommended when this step fails?**

> **This PR is additive.** It does not replace `TaskGraph`, `TaskEnvelope`, any orchestrator, or any existing runtime. All existing paths continue to work unchanged.

---

## Package Layout

```
core/task_semantics/
├── __init__.py               # Public API re-exports
├── step_kind.py              # StepKind enum + helpers
├── step_policy.py            # StepSemanticPolicy dataclass + factory
├── task_semantic_summary.py  # ClassifiedStep, TaskSemanticSummary, adapters
└── step_resolver.py          # Resolver helpers (infer kind from metadata)
```

---

## Step Kind Definitions

| Kind | Value | Side-effectful | Description |
|------|-------|---------------|-------------|
| `StepKind.PERCEIVE` | `"perceive"` | No | Gather environmental data (screenshot, sensor read, API poll). Read-only. |
| `StepKind.ANALYZE` | `"analyze"` | No | Process or reason over gathered data. No I/O side effects. |
| `StepKind.DECIDE` | `"decide"` | No | Choose among alternatives or select an execution plan. No direct system effects. |
| `StepKind.EXECUTE` | `"execute"` | **Yes** | Perform a concrete system action (click, type, file-write, API call). |
| `StepKind.CONFIRM` | `"confirm"` | No | Await or record explicit user/system confirmation. Gate step. |
| `StepKind.NOTIFY` | `"notify"` | **Yes** | Deliver a notification (push, log alert, webhook). |
| `StepKind.ROLLBACK` | `"rollback"` | **Yes** | Undo or compensate for a previously executed step. |
| `StepKind.OBSERVE_REMOTE` | `"observe_remote"` | No | Observe state of a remote device without performing any action. Cross-device read-only. |
| `StepKind.UNKNOWN` | `"unknown"` | **Yes** (conservative) | Step kind could not be inferred. Treated conservatively. |

All values are stable lowercase strings that round-trip cleanly through JSON and log streams.

---

## Semantic Trait Definitions (`StepSemanticPolicy`)

Each step has an associated `StepSemanticPolicy` that describes its semantic traits:

| Trait | Type | Description |
|-------|------|-------------|
| `step_kind` | `StepKind` | The semantic kind of the step. |
| `side_effectful` | `bool` | Whether the step modifies external state. |
| `requires_confirmation` | `bool` | Whether explicit user/system confirmation is required before proceeding. |
| `cross_device_allowed` | `bool` | Whether the step may be dispatched to a non-local device. |
| `failure_skippable` | `bool` | Whether the task can continue when this step fails. `False` = halt. |
| `should_surface_in_manifest` | `bool` | Whether the step should be visible in manifest/projection surfaces. |
| `should_emit_observability_highlight` | `bool` | Whether an observability highlight event should be emitted. |
| `preferred_recovery_posture` | `str \| None` | Hint for the preferred `RecoveryPosture` when this step fails. |
| `policy_reason` | `str` | Human-readable note explaining why these traits were assigned. |

### Default policies by kind

| Kind | `side_effectful` | `cross_device_allowed` | `failure_skippable` | `requires_confirmation` | `surfaces_in_manifest` | `preferred_recovery_posture` |
|------|-----------------|----------------------|--------------------|-----------------------|----------------------|-----------------------------|
| `perceive` | No | No | Yes | No | No | — |
| `analyze` | No | No | Yes | No | No | — |
| `decide` | No | No | No | No | Yes | — |
| `execute` | **Yes** | No | No | No | Yes | `retry_same_device` |
| `confirm` | No | No | No | **Yes** | Yes | `require_confirmation` |
| `notify` | **Yes** | **Yes** | Yes | No | No | `skip_optional_branch` |
| `rollback` | **Yes** | No | No | No | Yes | `abort_task` |
| `observe_remote` | No | **Yes** | Yes | No | No | — |
| `unknown` | **Yes** | No | No | No | Yes | `retry_same_device` |

---

## Resolver Behavior

The `step_resolver` module infers step kinds using the following priority order (first match wins):

1. **Explicit `"step_kind"` key** in node/envelope metadata dict.
2. **`tool_name` keyword mapping** — e.g. `"screenshot"` → `perceive`, `"click"` → `execute`.
3. **Description keyword scan** — e.g. description contains `"rollback"` → `rollback`.
4. **Cross-device routing context** — if `RoutingPolicy.posture == "mirrored_observation"` → `observe_remote`.
5. **Execution policy band** — if `ExecutionPolicy.policy_band == "observe_only"` → `perceive`.
6. **Fallback** → `StepKind.UNKNOWN`.

The resolver degrades gracefully when inputs are absent or of unexpected types. Unknown step kinds are assigned conservative (side-effectful, non-skippable) defaults.

### Tool name mappings (selection)

| Tool name prefix/substring | Mapped kind |
|----------------------------|-------------|
| `screenshot`, `read_screen`, `observe`, `poll`, `fetch` | `perceive` |
| `observe_remote`, `remote_screenshot`, `remote_poll` | `observe_remote` |
| `analyze`, `ocr`, `parse`, `detect`, `classify`, `extract`, `summarize` | `analyze` |
| `decide`, `plan`, `select`, `choose`, `route` | `decide` |
| `click`, `type`, `execute`, `run`, `write_file`, `api_call`, `shell` | `execute` |
| `confirm`, `approve`, `gate` | `confirm` |
| `notify`, `alert`, `push`, `webhook`, `broadcast` | `notify` |
| `rollback`, `undo`, `revert`, `compensate`, `restore` | `rollback` |

---

## Relation to Upstream Packages

| Package | Relation |
|---------|----------|
| `core/execution_policy/` (PR-11) | Task-level execution bands (`observe_only`, `assistive`, etc.) influence step-kind resolution and `requires_confirmation` / `cross_device_allowed` overrides in the resolver. |
| `core/cross_device_policy/` (PR-13) | `RoutingPolicy.posture` and `is_cross_device` influence `observe_remote` inference and `cross_device_allowed` in step policy. |
| `core/distributed_execution/` (PR-14) | `RecoveryPosture` string values are reused as `preferred_recovery_posture` hints. |
| `core/execution_observability/` (PR-7) | `should_emit_observability_highlight` trait guides when highlight events should be emitted (future enforcement). |
| `core/task_graph.py` | `build_semantic_summary_from_graph()` reads `TaskGraph._nodes` to classify each node. The graph is **not modified**. |
| `core/schemas/task_envelope.py` | `classify_task_envelope()` reads `tool_name` and `metadata` from `TaskEnvelope`. The envelope is **not modified**. |

---

## Read-only API Endpoint

PR-15 adds a single new read-only projection endpoint:

```
GET /api/v1/projection/task_semantics
```

**Response** (additive over `GET /api/v1/execution/merge-summary`):

```json
{
  "tri_state_phase": "...",
  "...": "...",
  "task_semantics": {
    "task_id": "",
    "trace_id": "",
    "classified_steps": [],
    "total_steps": 0,
    "has_side_effectful_steps": false,
    "has_cross_device_steps": false,
    "has_confirmation_required_steps": false,
    "has_rollback_steps": false,
    "primary_visible_steps": [],
    "observability_highlight_steps": [],
    "unresolved_count": 0,
    "is_fully_resolved": true,
    "summarised_at": 1234567890.0
  },
  "semantic_hints": {
    "total_steps": 0,
    "unresolved_count": 0,
    "is_fully_resolved": true,
    "has_side_effectful_steps": false,
    "has_cross_device_steps": false,
    "has_confirmation_required_steps": false,
    "has_rollback_steps": false,
    "primary_visible_step_count": 0,
    "observability_highlight_count": 0,
    "task_id": "",
    "trace_id": ""
  }
}
```

The endpoint currently returns the idle `EMPTY_SEMANTIC_SUMMARY`. Future code that maintains a live task context registry should replace this with the appropriate active summary.

---

## Usage Examples

### Classify a TaskGraph

```python
from core.task_semantics import build_semantic_summary_from_graph

summary = build_semantic_summary_from_graph(my_task_graph)
print(summary.has_side_effectful_steps)   # True if any node is side-effectful
print(summary.primary_visible_steps)      # IDs of manifest-visible steps
```

### Classify a list of TaskEnvelopes

```python
from core.task_semantics import build_semantic_summary_from_envelopes

summary = build_semantic_summary_from_envelopes(envelopes)
for step in summary.classified_steps:
    print(step.step_id, step.step_kind.value, step.policy.failure_skippable)
```

### Classify plain step dicts

```python
from core.task_semantics import build_semantic_summary_from_dicts

steps = [
    {"node_id": "n1", "tool_name": "screenshot"},
    {"node_id": "n2", "tool_name": "click", "description": "click submit button"},
    {"node_id": "n3", "metadata": {"step_kind": "rollback"}},
]
summary = build_semantic_summary_from_dicts(steps)
```

### Attach to a projection dict

```python
from core.task_semantics import attach_semantic_summary_to_projection, get_semantic_hints

enriched = attach_semantic_summary_to_projection(projection_dict, summary)
hints = get_semantic_hints(summary)
```

### Build a policy for a known kind

```python
from core.task_semantics import build_policy_for_kind, StepKind

policy = build_policy_for_kind(
    StepKind.EXECUTE,
    cross_device_allowed=True,
    failure_skippable=False,
)
print(policy.to_dict())
```

---

## What This PR Does NOT Yet Enforce

- Step-level policy is **descriptive only** — no execution path is blocked or modified by `StepSemanticPolicy` in this PR.
- The `should_emit_observability_highlight` trait does not yet automatically trigger observability events — it is a hint for future integration.
- The `preferred_recovery_posture` hint does not yet feed directly into `RecoveryRecommendation` generation.
- The endpoint returns an idle/empty summary; a live task context registry would be needed to serve per-task summaries.

---

## How Future Orchestration Code Should Classify / Publish Steps

1. **At task-plan time**, call `build_semantic_summary_from_graph()` or `build_semantic_summary_from_dicts()` to classify the planned steps.
2. **Store** the resulting `TaskSemanticSummary` in a task context registry (keyed by `task_id`).
3. **During execution**, consult `step.policy.failure_skippable` before deciding whether to continue on failure.
4. **During rollback planning**, filter `summary.classified_steps` for `step_kind == StepKind.EXECUTE` to identify what needs rollback.
5. **For manifest surfaces**, surface only steps whose `policy.should_surface_in_manifest is True`.
6. **For observability**, emit highlight events for steps in `summary.observability_highlight_steps`.
7. **For recovery**, use `step.policy.preferred_recovery_posture` as the input to `recommend_recovery()` from `core.distributed_execution`.
