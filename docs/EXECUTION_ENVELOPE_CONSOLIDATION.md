# Execution Envelope Consolidation (PR-8)

> **V3 PR-8 — Additive consolidation of envelope roles, boundaries, and
> interoperability.**
> This document covers the role of each envelope type, what changed in this
> PR, what did not change, and migration guidance for future code.

---

## 1. Background

After PR-7 established a unified execution observability layer
(`core/execution_observability/`), the repository had four well-established
envelope types used across different layers of the Galaxy runtime.  However,
the boundaries between them were implicit — every developer had to read each
envelope's source file to understand *when* to use it.

PR-8 formalises those boundaries without modifying any existing canonical
model.

---

## 2. The four canonical envelope types

### 2.1 `InteractionEnvelope`

| Attribute | Value |
|---|---|
| Module | `core/schemas/interaction_envelope.py` |
| Role | Interaction / rendering / perception-output context |
| Layer | Interaction, persona, UI rendering |
| Trace field | `trace_id` |

**Purpose:** Built once per user request by `InteractionBuilder` after the
multimodal bus, scene interpreter, and persona engine have all run.  Carries
the selected interaction mode, persona state snapshot, multimodal context, and
per-channel rendering flags (`OutputPlan`).

**When to use:** Any code that decides *how* to present a response to the user
(text, voice, avatar, overlay, UI surface).

**Do NOT use for:** Routing decisions, task scheduling, executor dispatch, or
result correlation.

---

### 2.2 `TaskEnvelope`

| Attribute | Value |
|---|---|
| Module | `core/schemas/task_envelope.py` |
| Role | Internal task routing / orchestration contract |
| Layer | Orchestration, routing, scheduling |
| Trace field | `trace_id` |

**Purpose:** The single authoritative internal message format used across all
routing paths: gateway command dispatch, device-to-device relay, node
execution, MCP tool calls, and skill invocations.  Carries lifecycle state
(`created → running → done | failed`), required capabilities, priority, and
arbitrary metadata.

**When to use:** Anywhere a task needs to be routed, scheduled, queued, or
tracked through the system.  All `CommandRouter`, `TaskOrchestrator`,
`TaskGraph`, `MultiDeviceOrchestrator`, and NATS publication paths use
`TaskEnvelope` as their internal format.

**Do NOT use for:** Executor-level dispatch details, idempotency keys, or
result encoding.

---

### 2.3 `CommandEnvelope`

| Attribute | Value |
|---|---|
| Module | `core/unified/command_envelope.py` |
| Role | Executor-facing command contract |
| Layer | Executor / dispatch |
| Trace field | `trace_id` |

**Purpose:** Wraps a concrete execution request destined for a single executor
(Windows arbiter, remote device, MCP adapter).  Adds idempotency key, command
verb (`EXECUTE` / `CANCEL` / `INTERRUPT` / `QUERY`), and cancel metadata.
Constructed from a `TaskEnvelope` via `CommandEnvelope.from_task_envelope()`.

**When to use:** When handing off a task to a concrete executor.  Always
constructed from a `TaskEnvelope` so that `trace_id` and `task_id` are
preserved.

**Do NOT use for:** High-level routing, persona/rendering decisions, or result
storage.

---

### 2.4 `ResultEnvelope`

| Attribute | Value |
|---|---|
| Module | `core/unified/command_envelope.py` |
| Role | Executor return contract |
| Layer | Result / observability |
| Trace field | `trace_id` |

**Purpose:** Carries the outcome of a single executor attempt: success flag,
output data, elapsed time, error code, and fallback metadata.  Correlated back
to the originating `CommandEnvelope` via `task_id` + `trace_id`.

**When to use:** When an executor returns a result.  Also consumed by
`RuntimeProjection`, Status Board v2, Manifest stage, and the PR-7 execution
observability layer.

---

## 3. Trace propagation contract

`trace_id` must be propagated **unchanged** across all four envelope types
for a single user request:

```
InteractionEnvelope.trace_id
    == TaskEnvelope.trace_id
    == CommandEnvelope.trace_id
    == ResultEnvelope.trace_id
```

### Correct propagation pattern

```python
from core.envelope_consolidation import propagate_trace, interaction_trace_fields
from core.schemas.task_envelope import TaskEnvelope
from core.unified.command_envelope import CommandEnvelope

# 1. Extract trace from interaction context
ix_fields = interaction_trace_fields(interaction_envelope)

# 2. Build TaskEnvelope with inherited trace
task = TaskEnvelope(
    trace_id=ix_fields["trace_id"],
    session_id=ix_fields["session_id"],
    source="api",
    targets=["win_pc_01"],
    tool_name="screenshot",
    args={"format": "png"},
)

# 3. Build CommandEnvelope from TaskEnvelope (trace preserved automatically)
cmd = CommandEnvelope.from_task_envelope(task)

# 4. The result will carry the same trace_id
result = await executor.run(cmd)
assert result.trace_id == task.trace_id == ix_fields["trace_id"]
```

---

## 4. New in PR-8: `core/envelope_consolidation/`

This PR adds a small, additive package at `core/envelope_consolidation/`:

```
core/envelope_consolidation/
├── __init__.py            # re-exports the public API
├── envelope_roles.py      # EnvelopeRole enum + ROLE_DESCRIPTIONS registry
├── envelope_adapters.py   # trace extraction, propagation, and bridge adapters
└── envelope_summary.py    # EnvelopeSummary dataclass + catalog helper
```

### 4.1 `envelope_roles.py`

Defines `EnvelopeRole` — a `str` enum with four members:

| Member | Value |
|---|---|
| `EnvelopeRole.INTERACTION` | `"interaction"` |
| `EnvelopeRole.TASK` | `"task"` |
| `EnvelopeRole.COMMAND` | `"command"` |
| `EnvelopeRole.RESULT` | `"result"` |

Also provides `ROLE_DESCRIPTIONS` — a dict mapping each role to its label,
canonical class path, layer, key fields, and summary text.

Convenience helpers:
- `role_for_class(class_name)` — look up a role by class name
- `layer_for_role(role)` — get the architectural layer for a role

### 4.2 `envelope_adapters.py`

Pure functions for trace propagation and cross-envelope adaptation:

| Function | Purpose |
|---|---|
| `extract_trace_fields(envelope)` | Extract `trace_id`, `task_id`, `runtime_session_id`, `session_id`, `interaction_id` from any envelope |
| `propagate_trace(source, target)` | Copy trace fields from one envelope to a builder dict |
| `task_to_command_summary(task_envelope)` | Lightweight command-oriented summary dict from a `TaskEnvelope` |
| `result_to_observation(result_envelope)` | Convert `ResultEnvelope` to PR-7-compatible observation dict |
| `interaction_trace_fields(interaction_envelope)` | Extract trace subset from an `InteractionEnvelope` |

### 4.3 `envelope_summary.py`

Stable, serialisable summary types for downstream consumers:

| Symbol | Purpose |
|---|---|
| `EnvelopeSummary` | Compact dataclass with `to_dict()` / `from_dict()` / `projection_summary()` |
| `summarise_envelope(envelope, role=None)` | Build a summary from any envelope, auto-inferring role |
| `envelope_role_catalog()` | List all roles with metadata — suitable for read-only API response |
| `summarise_result_for_projection(result_envelope)` | Projection-friendly dict for Status Board / Manifest |

---

## 5. What did NOT change

- `InteractionEnvelope` in `core/schemas/interaction_envelope.py` — unchanged
- `TaskEnvelope` in `core/schemas/task_envelope.py` — unchanged
- `CommandEnvelope` / `ResultEnvelope` in `core/unified/command_envelope.py`
  — unchanged
- `core/execution_observability/` (PR-7) — unchanged
- All existing adapter helpers (`envelope_from_command_request`, etc.) —
  unchanged
- All existing tests — unchanged

---

## 6. Relationship to PR-7 (Execution Observability Unification)

PR-7 introduced `core/execution_observability/` with unified schemas for
execution events (`ExecutionEvent`, `TraceCorrelation`, `FallbackContext`,
`ExecutorLevel`).

PR-8 is complementary:

| PR-7 | PR-8 |
|---|---|
| Unifies **execution event** signals (what happened during execution) | Unifies **envelope role** boundaries (which container to use at which layer) |
| `TraceCorrelation` — normalises trace fields from multiple sources | `extract_trace_fields` — extracts trace fields from any envelope |
| `ExecutionEvent.from_dict()` — builds from raw dict | `result_to_observation()` — produces dict compatible with `ExecutionEvent.from_dict()` |

### Using PR-7 and PR-8 together

```python
from core.envelope_consolidation import result_to_observation
from core.execution_observability import ExecutionEvent, ExecutorLevel

# After an executor returns a ResultEnvelope:
obs_dict = result_to_observation(result_envelope)
obs_dict["executor_level"] = ExecutorLevel.UIA.value  # set explicitly if known

event = ExecutionEvent.from_dict(obs_dict)
projection = event.projection_summary()
```

---

## 7. Migration guidance for new code

### Which envelope do I use?

```
User request received
        │
        ▼
InteractionEnvelope  ← build here (interaction/rendering context)
        │
        │  propagate trace_id
        ▼
  TaskEnvelope       ← route, schedule, queue (orchestration)
        │
        │  CommandEnvelope.from_task_envelope()
        ▼
 CommandEnvelope     ← hand to executor (dispatch)
        │
        │  executor returns
        ▼
  ResultEnvelope     ← carry result, feed observability
```

### Do I need to change existing code?

No.  All existing patterns (`envelope_from_command_request`,
`CommandEnvelope.from_task_envelope`, etc.) remain valid.  The consolidation
package is additive — use it when you need to:

1. **Introspect** which role an envelope has (`summarise_envelope`)
2. **Extract** trace fields from an unknown envelope type (`extract_trace_fields`)
3. **Propagate** trace context into a new envelope builder (`propagate_trace`)
4. **Feed** a result into a downstream observability consumer
   (`result_to_observation`, `summarise_result_for_projection`)
5. **Document** or expose the role catalog to tooling (`envelope_role_catalog`)

### Adding a new envelope type in the future

1. Add a new `EnvelopeRole` member to `envelope_roles.py`
2. Add the corresponding entry to `ROLE_DESCRIPTIONS`
3. Update `_infer_role()` in `envelope_summary.py` with the new discriminating
   attribute(s)
4. Add a test case in `tests/test_pr8_envelope_consolidation.py`

---

## 8. Tests

Tests are in `tests/test_pr8_envelope_consolidation.py` and cover:

- Role enum values and `role_for_class` / `layer_for_role`
- `extract_trace_fields` from all four envelope types and from plain dicts
- `propagate_trace` non-overwrite semantics
- `task_to_command_summary` field extraction and defaults
- `result_to_observation` PR-7 compatibility
- `interaction_trace_fields` extraction
- `EnvelopeSummary` serialisation round-trip (`to_dict` / `from_dict`)
- `summarise_envelope` role inference for all four types
- `envelope_role_catalog` structure
- Edge cases: missing fields, `None` trace, partial envelopes
