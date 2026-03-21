# Runtime Governance Snapshot

**PR-27: Runtime Governance Snapshot**

---

## Overview

The Runtime Governance Snapshot (`core/runtime_governance/snapshot.py`) is the canonical runtime-side counterpart to the PR-26 Projection Assembly Governance layer. It assembles the current runtime posture into one unified, stable, serialisable object.

In one snapshot object, it answers:

- What tri-state phase is the system currently in?
- What runtime domain is active or intended?
- What is the current governance posture across intent / readiness / fallback / execution?
- What execution lifecycle summary is currently available?
- What projection-governance summary is currently available?
- Can downstream runtime, projection, status surfaces, and future mesh/session work consume one narrow snapshot instead of hand-rolling multiple summaries?

---

## Relationship to Earlier PRs

| PR | Layer | Role |
|----|-------|------|
| PR-22 | Execution Intent Profile | Intent construction |
| PR-23 | Execution Readiness Gate | Policy/readiness evaluation |
| PR-24 | Fallback Decision Trace | Fallback path selection |
| PR-25 | Execution Trace Contract | Lifecycle tracing (canonical schema) |
| PR-26 | Projection Assembly Governance | Projection-safe governance assembly |
| **PR-27** | **Runtime Governance Snapshot** | **Unified runtime-side posture snapshot** |

PR-25 standardised the execution lifecycle trace.  
PR-26 standardised projection-safe governance assembly.  
**PR-27 standardises the runtime-side governance posture as one unified snapshot.**

---

## What It Is vs What It Is Not

### What the Runtime Governance Snapshot IS

- A single canonical, serialisable object that assembles the complete runtime governance posture.
- The stable bridge between execution/projection contract work and future runtime-device-mesh unification.
- A read-only, additive surface. It does not modify any existing module.
- Suitable for both internal runtime consumption and outward read-only status surfaces.
- Gracefully degrading: when inputs are missing, the snapshot returns safe defaults and never raises.

### How It Differs From Execution Trace Contract (PR-25)

| Dimension | Execution Trace Contract (PR-25) | Runtime Governance Snapshot (PR-27) |
|-----------|----------------------------------|-------------------------------------|
| Scope | Lifecycle events for one execution run | Unified posture across all governance layers |
| Object | `ExecutionTraceEnvelope` + `ExecutionTraceEvent` | `RuntimeGovernanceSnapshot` |
| Focus | "What happened step by step in this execution?" | "What is the current runtime posture right now?" |
| Consumers | Execution tracing, debugging | Runtime, projection, status surfaces, mesh work |

### How It Differs From Projection Assembly Governance (PR-26)

| Dimension | Projection Assembly Governance (PR-26) | Runtime Governance Snapshot (PR-27) |
|-----------|----------------------------------------|-------------------------------------|
| Scope | Projection-safe governance summaries | Unified runtime-side posture |
| Object | `ProjectionGovernanceSummary` | `RuntimeGovernanceSnapshot` |
| Orientation | Outward / projection-facing | Runtime-internal + outward |
| Top-level field | `governance_available` | `posture` (execute / observe / blocked / degraded / unknown) |
| Phase/Domain | Part of the summary | First-class top-level fields |

The Runtime Governance Snapshot may consume a `ProjectionGovernanceSummary` as one of its inputs.

---

## Snapshot Contracts

### `RuntimeGovernanceSnapshot` (top-level)

The main unified snapshot. See `core/runtime_governance/snapshot.py` for full field reference.

Key fields:

| Field | Type | Description |
|-------|------|-------------|
| `snapshot_id` | `str` | UUID4, unique per snapshot instance |
| `trace_id` | `Optional[str]` | Shared trace ID from active execution lifecycle |
| `runtime_session_id` | `Optional[str]` | Active runtime/OpenClawd session ID |
| `tri_state_phase` | `Optional[str]` | `"silent"` / `"liminal"` / `"manifest"` |
| `runtime_domain` | `Optional[str]` | `"local"` / `"cross_device"` / `"transition"` |
| `governance_available` | `bool` | True when at least one governance input was present |
| `intent_summary` | `RuntimeGovernanceExecutionSummary` | Compact intent summary (PR-22) |
| `readiness_summary` | `RuntimeGovernancePolicySummary` | Compact readiness/policy summary (PR-23) |
| `fallback_summary` | `RuntimeGovernanceTraceSummary` | Compact fallback trace summary (PR-24/25) |
| `execution_trace_summary` | `RuntimeGovernanceTraceSummary` | Compact execution lifecycle trace summary (PR-25) |
| `projection_governance_summary` | `RuntimeGovernanceProjectionSummary` | Compact projection governance summary (PR-26) |
| `posture` | `str` | Top-level posture: `execute` / `observe` / `blocked` / `degraded` / `unknown` |
| `blocked` | `bool` | Convenience flag — True when posture is `blocked` |
| `degraded` | `bool` | Convenience flag — True when posture is `degraded` |
| `timestamp` | `float` | Unix epoch seconds when snapshot was assembled |

### `RuntimeGovernanceExecutionSummary`

Compact runtime-side summary of execution intent (PR-22). Mirrors `ProjectionExecutionSummary` but is positioned as the canonical runtime-side view.

### `RuntimeGovernancePolicySummary`

Compact runtime-side readiness and policy posture summary (PR-23). Mirrors `ProjectionPolicySummary` from the projection layer.

### `RuntimeGovernanceTraceSummary`

Compact runtime-side execution trace summary (PR-25) or fallback-decision summary (PR-24). Used for both the execution trace and the fallback summary sub-fields.

### `RuntimeGovernanceProjectionSummary`

Compact runtime-side summary of the projection governance layer (PR-26). Extracts the narrow set of fields that are meaningful to the runtime governance layer.

---

## Assembly Helpers

### `assemble_runtime_governance_snapshot(...)` — the single entry point

```python
from core.runtime_governance.snapshot import assemble_runtime_governance_snapshot

snapshot = assemble_runtime_governance_snapshot(
    intent_profile=profile,           # PR-22 (optional)
    readiness_result=readiness,       # PR-23 (optional)
    fallback_trace=trace,             # PR-24 (optional)
    execution_trace_envelope=envelope, # PR-25 (optional)
    projection_governance=gov_summary, # PR-26 (optional)
    tri_state_phase="manifest",       # explicit override (optional)
    runtime_domain="local",           # explicit override (optional)
    trace_id="trace-abc",             # explicit override (optional)
    runtime_session_id="sess-xyz",    # explicit override (optional)
)
payload = snapshot.to_dict()
```

All parameters are optional. When all are `None`, the snapshot returns a safe minimal default with `governance_available=False` and `posture="unknown"`.

### Individual adapters

- `summarize_runtime_intent(intent_profile)` → `RuntimeGovernanceExecutionSummary`
- `summarize_runtime_readiness(readiness_result)` → `RuntimeGovernancePolicySummary`
- `summarize_runtime_fallback(fallback_trace)` → `RuntimeGovernanceTraceSummary`
- `summarize_runtime_execution_trace(execution_trace_envelope)` → `RuntimeGovernanceTraceSummary`
- `summarize_projection_governance_for_runtime(projection_governance)` → `RuntimeGovernanceProjectionSummary`

All adapters:
- Accept `None` gracefully (return an `available=False` default)
- Accept Pydantic objects and plain dicts
- Use `compact_summary()` when available, fall back to attribute access
- Never raise to callers

---

## Posture Derivation

The top-level `posture` field is derived from the combined governance signals in this priority order:

1. **`blocked`** — when readiness is blocked, or execution trace final_status is `blocked`/`failed`
2. **`degraded`** — when readiness is degraded (e.g., `observe_only` status)
3. **`execute`** — when readiness explicitly permits execution (`ready=True`)
4. **`observe`** — when intent action_level is `observe` or `hint`
5. **`unknown`** — when insufficient signals are available

---

## Graceful Degradation

The snapshot is designed to degrade gracefully at every level:

- `assemble_runtime_governance_snapshot()` with all-`None` inputs → returns a minimal safe snapshot with `governance_available=False`, `posture="unknown"`, all sub-summaries `available=False`
- Individual adapters with `None` input → return a minimal `available=False` sub-summary
- Internal assembly failures → caught, logged, and a safe default is returned
- No governance inputs → snapshot is still valid and serialisable
- Partial governance inputs → only available sub-summaries carry `available=True`

**The snapshot never raises to callers, under any input.**

---

## Example Payloads

### All-`None` / No Governance Inputs

```json
{
  "snapshot_id": "550e8400-e29b-41d4-a716-446655440000",
  "trace_id": null,
  "runtime_session_id": null,
  "tri_state_phase": null,
  "runtime_domain": null,
  "governance_available": false,
  "intent_summary": {
    "intent_id": null,
    "source": "unknown",
    "action_level": "observe",
    "intent_mode": "advisory",
    "target_type": null,
    "target_ref": null,
    "device_scope": null,
    "runtime_domain": null,
    "confidence": null,
    "degrade_reason": null,
    "available": false
  },
  "readiness_summary": {
    "ready": false,
    "status": "blocked",
    "reason": "",
    "requires_confirmation": false,
    "action_level": "observe",
    "policy_band": null,
    "blocked_by": "none",
    "runtime_domain": null,
    "blocked": true,
    "degraded": false,
    "available": false
  },
  "fallback_summary": {
    "trace_id": null,
    "intent_id": null,
    "runtime_session_id": null,
    "final_status": "pending",
    "stage_count": 0,
    "stages": [],
    "fallback_outcome": null,
    "available": false
  },
  "execution_trace_summary": {
    "trace_id": null,
    "intent_id": null,
    "runtime_session_id": null,
    "final_status": "pending",
    "stage_count": 0,
    "stages": [],
    "fallback_outcome": null,
    "available": false
  },
  "projection_governance_summary": {
    "governance_available": false,
    "action_level": "observe",
    "intent_mode": "advisory",
    "policy_status": "blocked",
    "ready": false,
    "blocked": true,
    "degraded": false,
    "fallback_outcome": "noop",
    "trace_final_status": "pending",
    "tri_state_phase": null,
    "runtime_domain": null,
    "assembled_at": null,
    "available": false
  },
  "posture": "unknown",
  "blocked": false,
  "degraded": false,
  "timestamp": 1711000000.0
}
```

### Full Governance Inputs (manifest phase, local domain, execute posture)

```json
{
  "snapshot_id": "660f9500-f30c-52e5-b827-557766551111",
  "trace_id": "trace-abc-123",
  "runtime_session_id": "sess-xyz-456",
  "tri_state_phase": "manifest",
  "runtime_domain": "local",
  "governance_available": true,
  "intent_summary": {
    "intent_id": "intent-001",
    "source": "openclawd",
    "action_level": "execute",
    "intent_mode": "direct",
    "target_type": "app",
    "target_ref": "notepad",
    "device_scope": "local",
    "runtime_domain": "local",
    "confidence": 0.95,
    "degrade_reason": null,
    "available": true
  },
  "readiness_summary": {
    "ready": true,
    "status": "ready",
    "reason": "full_execute band",
    "requires_confirmation": false,
    "action_level": "execute",
    "policy_band": "full_execute",
    "blocked_by": "none",
    "runtime_domain": "local",
    "blocked": false,
    "degraded": false,
    "available": true
  },
  "fallback_summary": {
    "trace_id": "trace-abc-123",
    "intent_id": "intent-001",
    "runtime_session_id": null,
    "final_status": "pending",
    "stage_count": 0,
    "stages": [],
    "fallback_outcome": "noop",
    "available": true
  },
  "execution_trace_summary": {
    "trace_id": "trace-abc-123",
    "intent_id": "intent-001",
    "runtime_session_id": "sess-xyz-456",
    "final_status": "success",
    "stage_count": 3,
    "stages": ["intent_created", "readiness_evaluated", "execution_finished"],
    "fallback_outcome": null,
    "available": true
  },
  "projection_governance_summary": {
    "governance_available": true,
    "action_level": "execute",
    "intent_mode": "direct",
    "policy_status": "ready",
    "ready": true,
    "blocked": false,
    "degraded": false,
    "fallback_outcome": "noop",
    "trace_final_status": "success",
    "tri_state_phase": "manifest",
    "runtime_domain": "local",
    "assembled_at": 1711000001.0,
    "available": true
  },
  "posture": "execute",
  "blocked": false,
  "degraded": false,
  "timestamp": 1711000002.0
}
```

---

## Integration Points

### 1. `core/runtime_governance/snapshot.py`

The main module. Contains all contracts and assembly helpers.

```python
from core.runtime_governance import assemble_runtime_governance_snapshot

snapshot = assemble_runtime_governance_snapshot(
    intent_profile=...,
    readiness_result=...,
    # ...
)
```

### 2. `core/projection/runtime_projection.py`

`RuntimeProjection` now carries an optional `runtime_governance_snapshot` field (a `Dict[str, Any]` or `None`) for downstream consumers that want both the projection and the governance snapshot in one object.

```python
from core.projection.runtime_projection import RuntimeProjection

# The field is additive — existing consumers are unaffected
proj = RuntimeProjection(
    tri_state_phase=TriStatePhase.MANIFEST,
    runtime_governance_snapshot=snapshot.to_dict(),
)
d = proj.to_dict()
# d["runtime_governance_snapshot"] is now populated
```

### 3. `GET /api/v1/projection/runtime-governance`

A new read-only endpoint that returns the unified `RuntimeGovernanceSnapshot` as JSON:

```
GET /api/v1/projection/runtime-governance
```

Response: `RuntimeGovernanceSnapshot.to_dict()` — always returns a valid JSON payload, never a 500 error.

---

## What This PR Does NOT Do

The following are explicit non-goals for PR-27:

- No Registered Runtime Device contract
- No Local Runtime Host contract
- No Handoff Envelope v2 redesign
- No Mesh Membership contract
- No Mesh Session contract
- No target runtime local takeover flow
- No multi-device execution rewrite
- No dashboard/UI redesign
- No persistence or streaming requirement

---

## Preparing Later Work

This PR is the stable foundation for later work on:

- **Registered Runtime Device** — will consume the snapshot's `tri_state_phase`, `runtime_domain`, and governance posture
- **Local Runtime Host** — will use the snapshot as the authoritative posture source for local takeover decisions
- **Handoff Envelope v2** — will embed or reference the snapshot for governance context at handoff time
- **Mesh Membership** — will use the snapshot to determine eligibility and posture for mesh participation
- **Mesh Session** — will use the snapshot as the canonical runtime posture reference per session
- **Local takeover / cross-device runtime handoff** — will use the snapshot's `posture`, `blocked`, `degraded` fields for handoff gate decisions

In all these future cases, downstream code should call `assemble_runtime_governance_snapshot(...)` and consume the resulting object rather than hand-rolling their own governance dicts.
