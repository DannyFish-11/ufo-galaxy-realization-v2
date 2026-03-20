# Orchestration Authority Consolidation (PR-9)

> **V3 PR-9 — Additive orchestration authority clarification, integration helpers,
> and guardrails.**
> This document describes the authoritative request chain, delegate and runtime
> relationships, the role of `TaskGraph`, what is legacy/deprecated vs. active, and
> what this PR does *not* change.

---

## 1. Background and motivation

After PR-7 (Execution Observability Unification) and PR-8 (Execution Envelope
Consolidation), the Galaxy repository had a rich set of well-typed execution and
envelope schemas.  However, the *orchestration authority* picture — which module
owns which level of orchestration responsibility, and which paths are legacy
compatibility vs. authoritative — was documented only informally in docstrings
scattered across `core/desktop_presence_runtime.py`,
`core/constellation_runtime.py`, and `core/e2e_orchestrator.py`.

PR-9 introduces a small, **additive** package (`core/orchestration_authority/`)
that:

* Formalises the authority-role taxonomy as a stable enum.
* Provides a machine-readable catalog of the complete authority topology.
* Centralises the legacy/deprecated path registry (extending the list already
  present in `core/constellation_runtime.py`).
* Offers resolver and summary helpers that downstream projection / observability
  layers can use without inventing ad-hoc fields.
* Integrates with PR-7 and PR-8 patterns via narrow adapter helpers.

**What this PR does NOT do:**

* It does not introduce a new orchestrator.
* It does not modify any existing active execution path.
* It does not remove or break any legacy compatibility module.
* It does not change any canonical envelope model.

---

## 2. The authoritative request chain

```
User Request
    │
    ▼
DesktopPresenceRuntime.handle_request()         ← AUTHORITATIVE_ENTRYPOINT
    │  core/desktop_presence_runtime.py
    │  • Owns tri-state progression (silent → liminal → manifest → silent)
    │  • Emits runtime_session_id propagated throughout request lifecycle
    │  • Enforces that no entrypoint skips the progression
    │
    ├─► (Convenience path) process_user_input()  ← ORCHESTRATION_COORDINATOR
    │       core/e2e_orchestrator.py
    │       • Wires together control-plane and runtime-delegate layers
    │       • Forces multi-device tasks through TaskGraph
    │       • Not itself an authority; defers upward to DesktopPresenceRuntime
    │
    └─► ConstellationRuntime.run()               ← EXECUTION_RUNTIME_DELEGATE
            core/constellation_runtime.py
            • Closes planning → DAG → execution loop
            • Contains LEGACY_ORCHESTRATOR_PATHS registry and warn_legacy_path()
            │
            └─► TaskGraph.execute()              ← DAG_EXECUTION_ENGINE
                    core/task_graph.py
                    • Lower-level, reusable DAG execution engine
                    • Supports parallel nodes, retry, partial rollback
                    • NOT a replacement for DAGScheduler in orchestrator_engine.py
```

---

## 3. Role taxonomy

| Role | Value | Canonical module | Active |
|---|---|---|---|
| `AUTHORITATIVE_ENTRYPOINT` | `authoritative_entrypoint` | `core.desktop_presence_runtime` | ✅ |
| `EXECUTION_RUNTIME_DELEGATE` | `execution_runtime_delegate` | `core.constellation_runtime` | ✅ |
| `DAG_EXECUTION_ENGINE` | `dag_execution_engine` | `core.task_graph` | ✅ |
| `ORCHESTRATION_COORDINATOR` | `orchestration_coordinator` | `core.e2e_orchestrator` | ✅ |
| `LEGACY_COMPATIBILITY` | `legacy_compatibility` | Various (see §4) | ✅ (compat only) |
| `DEPRECATED` | `deprecated` | Various (see §4) | ❌ |
| `UNKNOWN` | `unknown` | — | — |

---

## 4. Legacy and deprecated paths

The following paths are registered in
`core/orchestration_authority/legacy_paths.py`.  They extend — and do not
replace — the `LEGACY_ORCHESTRATOR_PATHS` set already in
`core/constellation_runtime.py`.

| Module path | Status | Migration guidance |
|---|---|---|
| `nodes.Node_110_SmartOrchestrator.server` | LEGACY_COMPATIBILITY | Use `core.constellation_runtime.get_constellation_runtime()` |
| `nodes.Node_110_SmartOrchestrator.main` | LEGACY_COMPATIBILITY | Use `core.constellation_runtime.get_constellation_runtime()` |
| `nodes.Node_81_Orchestrator.main` | LEGACY_COMPATIBILITY | Use `core.constellation_runtime.get_constellation_runtime()` |
| `nodes.Node_50_Transformer.task_orchestrator` | **DEPRECATED** | Use `core.schemas.task_envelope.TaskEnvelope` for routing |
| `galaxy_gateway.orchestrator.task_orchestrator` | LEGACY_COMPATIBILITY | Route through `core.e2e_orchestrator.process_user_input()` |
| `fusion.unified_orchestrator` | LEGACY_COMPATIBILITY | Use `core.e2e_orchestrator.process_user_input()` |
| `core.orchestrator_engine` | LEGACY_COMPATIBILITY | Valid internally within ConstellationRuntime; do not call as a top-level entrypoint |

### Guardrail usage

```python
from core.orchestration_authority import emit_legacy_guardrail, is_legacy_path

# Proactive check before routing
if is_legacy_path(caller_module):
    emit_legacy_guardrail(caller_module, trace_id=trace_id)
```

The `emit_legacy_guardrail()` output uses the same `LEGACY PATH GUARDRAIL`
prefix as the existing `warn_legacy_path()` in `core/constellation_runtime.py`
so that log aggregation pipelines see a consistent format.

---

## 5. New package: `core/orchestration_authority/`

```
core/orchestration_authority/
├── __init__.py          — public API re-exports
├── authority_roles.py   — AuthorityRole enum + ROLE_CATALOG + helpers
├── legacy_paths.py      — LegacyPathEntry registry + emit_legacy_guardrail
├── authority_resolver.py — classify_module() + authority_catalog() + authority_chain()
└── authority_summary.py — AuthoritySummary + projection/observability helpers
```

### 5.1 `AuthorityRole` enum

```python
from core.orchestration_authority import AuthorityRole

role = AuthorityRole.AUTHORITATIVE_ENTRYPOINT
print(role.value)   # "authoritative_entrypoint"
```

### 5.2 `classify_module()`

Classifies any dotted module path into an `AuthorityRole`:

```python
from core.orchestration_authority import classify_module

classify_module("core.desktop_presence_runtime")   # AUTHORITATIVE_ENTRYPOINT
classify_module("core.constellation_runtime")      # EXECUTION_RUNTIME_DELEGATE
classify_module("core.task_graph")                 # DAG_EXECUTION_ENGINE
classify_module("core.e2e_orchestrator")           # ORCHESTRATION_COORDINATOR
classify_module("nodes.Node_110_SmartOrchestrator.server")  # LEGACY_COMPATIBILITY
classify_module("nodes.Node_50_Transformer.task_orchestrator")  # DEPRECATED
classify_module("some.random.module")              # UNKNOWN
```

### 5.3 `authority_catalog()`

Returns a machine-readable JSON-serialisable catalog:

```python
from core.orchestration_authority import authority_catalog
import json

catalog = authority_catalog()
print(json.dumps(catalog, indent=2))
# {
#   "schema_version": 1,
#   "pr": "PR-9",
#   "authority_chain": [...],
#   "role_catalog": {...},
#   "legacy_paths": [...]
# }
```

### 5.4 `summarise_authority()`

Creates a stable, serialisable authority context for a request:

```python
from core.orchestration_authority import summarise_authority, authority_summary_for_projection

summary = summarise_authority(
    "core.desktop_presence_runtime",
    trace_id="trace_abc123",
    runtime_session_id="rsess_xyz",
)
# summary.role == AuthorityRole.AUTHORITATIVE_ENTRYPOINT
# summary.active == True

proj = authority_summary_for_projection(summary)
# {"role": "authoritative_entrypoint", "label": "...", "active": True, ...}
```

### 5.5 PR-7 / PR-8 integration helpers

```python
from core.orchestration_authority import (
    attach_authority_to_event,
    attach_authority_to_envelope_summary,
)

# Annotate a PR-7 ExecutionEvent dict
annotated_event = attach_authority_to_event(
    execution_event.to_dict(),
    source_module="core.constellation_runtime",
)
# annotated_event["orchestration_authority"]["role"] == "execution_runtime_delegate"

# Annotate a PR-8 EnvelopeSummary dict
annotated_envelope = attach_authority_to_envelope_summary(
    envelope_summary.to_dict(),
    source_module="core.e2e_orchestrator",
)
# annotated_envelope["orchestration_authority"]["role"] == "orchestration_coordinator"
```

---

## 6. Role of TaskGraph

`core/task_graph.py` (`TaskGraph`) is a **lower-level, reusable DAG execution
engine**.  Key design notes:

* It is **not** a replacement for `core/orchestrator_engine.py`'s `DAGScheduler`,
  which operates on LLM-driven `SubTask` decompositions.
* It is consumed internally by `ConstellationRuntime` and `E2EOrchestrator`
  for multi-device task graphs.
* New code that needs DAG execution should call it via `ConstellationRuntime`
  or `e2e_orchestrator.compile_and_run_dag()` — not directly.
* Its authority role is `DAG_EXECUTION_ENGINE` — a subordinate layer, not a
  top-level entrypoint.

---

## 7. Observability and projection alignment

Downstream systems (Status Board v2, RuntimeProjection, Manifest stage) can
consume authority information by:

1. **Embedding `authority_summary_for_projection()`** output in their response
   dicts — a minimal 6-key dict with `role`, `label`, `active`, `trace_id`,
   `runtime_session_id`, and `canonical_module`.

2. **Annotating PR-7 ExecutionEvents** via `attach_authority_to_event()` so
   that the observability pipeline knows which authority path handled a traced
   request.

3. **Annotating PR-8 EnvelopeSummaries** via `attach_authority_to_envelope_summary()`
   so that envelope-level introspection carries authority context.

4. **Serving the full catalog** via `authority_catalog()` as a read-only API
   response or status board endpoint.

Example (in a RuntimeProjection handler):

```python
from core.orchestration_authority import summarise_authority, authority_summary_for_projection

authority = authority_summary_for_projection(
    summarise_authority(
        source_module="core.desktop_presence_runtime",
        trace_id=runtime_session.trace_id,
        runtime_session_id=runtime_session.runtime_session_id,
    )
)
projection_response["orchestration_authority"] = authority
```

---

## 8. What this PR does not change

* No existing orchestration module is modified.
* `core/constellation_runtime.py` keeps its `LEGACY_ORCHESTRATOR_PATHS` and
  `warn_legacy_path()` intact; the new registry extends rather than replaces it.
* No legacy compatibility path is removed or broken.
* No new orchestrator is added.
* All canonical envelope models (`TaskEnvelope`, `CommandEnvelope`,
  `InteractionEnvelope`, `ResultEnvelope`) are unchanged.
* All PR-7 and PR-8 public APIs are unchanged.

---

## 9. Migration guidance for future orchestration code

| Scenario | Recommended approach |
|---|---|
| New top-level request handler | Use `DesktopPresenceRuntime.handle_request()` |
| Convenience API / CLI entry | Use `e2e_orchestrator.process_user_input()` |
| Multi-device task routing | Use `e2e_orchestrator.run_multi_device_via_task_graph()` |
| DAG execution | Use `e2e_orchestrator.compile_and_run_dag()` or `ConstellationRuntime.run()` |
| Classifying an unknown module | Use `classify_module(module_path)` |
| Emitting authority context to a log/event | Use `summarise_authority()` + `authority_summary_for_projection()` |
| Checking if a caller is a legacy path | Use `is_legacy_path(module_path)` |
| Emitting a structured legacy warning | Use `emit_legacy_guardrail(caller, trace_id)` |

For any new module that participates in orchestration, add a docstring line such as:

```
Authority role: EXECUTION_RUNTIME_DELEGATE (core.orchestration_authority.AuthorityRole)
```

This allows future automated tooling to cross-reference against the catalog.

---

## 10. Tests

Tests are in `tests/test_pr9_orchestration_authority.py` and cover:

* `AuthorityRole` enum values and `ROLE_CATALOG` shape (9 tests)
* `LegacyPathRegistry` contents and serialisation (6 tests)
* Legacy guardrail helpers (8 tests)
* `classify_module()` for all known modules, prefix matching, edge cases (13 tests)
* `authority_chain()` structure and ordering (4 tests)
* `authority_catalog()` sections, JSON serialisability, inclusion flags (9 tests)
* `AuthoritySummary` factory, round-trip, defaults (7 tests)
* `authority_summary_for_projection()` minimal keys (3 tests)
* `attach_authority_to_event()` PR-7 integration (5 tests)
* `attach_authority_to_envelope_summary()` PR-8 integration (2 tests)
* `resolve_trace_authority()` (3 tests)
* Edge cases — partial match isolation, idempotency, frozen entries (5 tests)
