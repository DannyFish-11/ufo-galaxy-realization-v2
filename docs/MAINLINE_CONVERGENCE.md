# MAINLINE_CONVERGENCE.md

## PR-8: System Convergence and Final Mainline Integration

**Status**: Implemented  
**Module**: `core/mainline_convergence.py`  
**Tests**: `tests/test_pr8_mainline_convergence.py`

---

## Purpose

After PRs 1–7, Galaxy's subsystems are individually solid:

| Subsystem | PR | Role |
|---|---|---|
| OpenClawd | PR-1 | Subject-core orchestration authority |
| Knowledge Core (RAGMemory) | PR-2 | Unified knowledge entry point |
| Capability Bus | PR-3 | Canonical capability directory |
| GitHub Integration | PR-4 | First-class repository resource |
| Academic Retrieval | PR-5 | First-class academic resource |
| Self-Healing Engineering Loop | PR-6 | Mediated engineering authority |
| System Resource Layer | PR-7 | Governed external resource registry |

The remaining architectural risk is that these subsystems use slightly different metadata shapes, trace semantics, and authority declarations, creating the possibility of:

- Legacy entrypoints acting as hidden parallel authorities  
- Compatibility adapters silently becoming the primary path  
- Metadata inconsistencies making cross-subsystem tracing difficult  
- No single place to verify the mainline is actually being used  

PR-8 resolves this by providing the **cross-cutting convergence layer** documented here.

---

## Mainline Execution Chain

The canonical end-to-end path for every request is:

```
Request
  │  ← stage: REQUEST_INGRESS          [authority: OPENCLAWD]
  ▼
OpenClawd.process()
  │  ← stage: OPENCLAWD_AUTHORITY      [authority: OPENCLAWD]
  │
  ├─ capability dispatch ──────────────────────────────────────────────────
  │    ├─ stage: CAPABILITY_DISPATCH   [authority: CAPABILITY_BUS]
  │    ├─ stage: RESOURCE_RESOLUTION   [authority: SYSTEM_RESOURCE_REGISTRY]
  │    └─ stage: EXECUTION             [authority: CANONICAL_DISPATCHER]
  │
  ├─ knowledge flows ──────────────────────────────────────────────────────
  │    ├─ stage: KNOWLEDGE_RECALL      [authority: RAG_MEMORY]
  │    └─ stage: KNOWLEDGE_WRITEBACK   [authority: RAG_MEMORY]
  │
  └─ engineering ──────────────────────────────────────────────────────────
       └─ stage: ENGINEERING_LOOP      [authority: SELF_HEALING_LOOP]

Response
  │  ← stage: RESPONSE_EMISSION        [authority: OPENCLAWD]
```

Every stage is named in `MainlineChainStage` and has a canonical authority in `STAGE_AUTHORITY`.

---

## Key Concepts

### MainlineChainStage

An enum that names every significant hop in the mainline path.  
All logging and tracing should use these labels so cross-subsystem comparisons are unambiguous.

```python
from core.mainline_convergence import MainlineChainStage

stage = MainlineChainStage.OPENCLAWD_AUTHORITY
print(stage.value)  # "openclawd_authority"
```

### MainlinePathClass

Every execution path is classified as one of:

| Class | Meaning |
|---|---|
| `MAINLINE` | Follows the canonical chain end-to-end |
| `COMPAT` | Uses a compatibility adapter but eventually joins mainline (secondary, intentional) |
| `LEGACY` | Bypasses one or more mainline stages (must be monitored) |

Compatibility layers must remain `COMPAT`; they must **never** be promoted to `MAINLINE` unless the underlying subsystem is updated to use the canonical path.

### MainlineMetadataFrame

The normalized metadata struct for cross-subsystem traceability.

Canonical fields:
- `authority_role` — which authority stamped this metadata
- `execution_path` — `local` / `cross_device` / `hybrid` / `none`
- `trace_id` — stable end-to-end correlation key
- `task_id` — discrete task identifier
- `session_id` — caller-assigned session context
- `source` — human-readable source label
- `resource_type` — governed resource type (from `SystemResourceType`)
- `capability_source` — capability bus role used
- `knowledge_source` — which knowledge backend was used
- `mainline_stage` — which stage emitted this metadata
- `path_class` — `mainline` / `compat` / `legacy`

### normalize_cross_subsystem_metadata()

Coerces any raw metadata dict from any subsystem into a canonical `MainlineMetadataFrame`.

```python
from core.mainline_convergence import normalize_cross_subsystem_metadata

# Works with OpenClawd kernel response metadata
frame = normalize_cross_subsystem_metadata({
    "trace_id": "abc",
    "authority_role": "subject_decision_authority",
    "execution_path": "local",
})
assert frame.is_mainline  # True
assert frame.coverage_ratio > 0.0
```

### MainlineConvergenceRegistry

Singleton that accumulates `MainlineExecutionTrace` objects, classifies them by `path_class`, and exposes aggregate statistics.

```python
from core.mainline_convergence import get_mainline_convergence_registry

reg = get_mainline_convergence_registry()

# Record a trace from an OpenClawd response
trace = reg.record_from_response(response)

# Check that mainline dominates
assert reg.assert_mainline_dominant(min_ratio=0.5)

# Snapshot for dashboards/diagnostics
snap = reg.snapshot()
print(snap.mainline_count, snap.compat_count, snap.legacy_count)
```

---

## OpenClawd Integration

`OpenClawd._build_mainline_convergence_stamp()` is called by both response paths (kernel path and direct path) in `process()`.  It:

1. Builds a `MainlineExecutionTrace` stamped with `OPENCLAWD_AUTHORITY` stage
2. Closes and records the trace in the module-level registry
3. Returns a compact dict embedded in `response.metadata["mainline_convergence"]`

This makes every OpenClawd response carry a traceable mainline convergence stamp, so the architectural mainline is visible in production responses and testable in integration tests.

---

## Fallback / Compatibility Rules

1. **Compatibility adapters** (`path_class = COMPAT`) are intentional and acceptable — they route to the mainline eventually.
2. **Legacy paths** (`path_class = LEGACY`) bypass one or more mainline stages — they must be explicitly declared and monitored.
3. `MainlineConvergenceRegistry.assert_mainline_dominant()` provides a programmatic check that the mainline path is actually dominant in recorded traces.
4. Non-mainline traces are logged as `WARNING` by the registry so they are never invisible.

---

## Testing

The test suite `tests/test_pr8_mainline_convergence.py` covers:

- All enum values and mappings
- `MainlineMetadataFrame` dataclass (construction, round-trip, coverage ratio)
- `MainlineExecutionTrace` dataclass (stages, close, elapsed_ms, properties)
- `normalize_cross_subsystem_metadata()` (all fields, fallback chain, inference)
- `build_mainline_trace()` and `record_mainline_execution()`
- `MainlineConvergenceRegistry` (record, lookup, snapshot, dominance check, reset, max_traces, thread safety)
- Integration with `OpenClawd._build_mainline_convergence_stamp()`
- **4 acceptance criteria** aligned with PR-8 requirements:
  - AC-a: Mainline chain is coherent and stable end-to-end
  - AC-b: Subsystems have canonical stage representations (no hidden bypasses needed)
  - AC-c: Metadata normalization covers all required fields from any subsystem
  - AC-d: Compatibility/legacy paths are detectable and remain secondary

---

## Architectural Invariants

1. **Single authority chain**: Every execution path must eventually attribute authority to `OPENCLAWD_AUTHORITY_ROLE = "subject_decision_authority"`.
2. **No silent bypasses**: Any path that skips the `OPENCLAWD_AUTHORITY` stage must be classified as `COMPAT` or `LEGACY` and recorded.
3. **Canonical metadata**: All responses carrying `authority_role = "subject_decision_authority"` must also carry `trace_id`, `session_id`, and `execution_path`.
4. **Mainline dominance**: In steady-state operation, `mainline_count / total_traces >= 0.5` is expected.
