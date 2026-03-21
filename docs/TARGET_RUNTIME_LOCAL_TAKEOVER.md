# Target Runtime Local Takeover — PR-34

This document describes the **Target Runtime Local Takeover Path** introduced
in PR-34.  It is the first real target-side execution step of the
runtime-device-mesh phase.

---

## Overview

PR-34 implements the minimal, canonical path that allows a **target device's
local runtime** to:

1. Accept and normalise an incoming handoff envelope (PR-31 or legacy
   `HandoffContract`).
2. Resolve or create a local session context.
3. Execute locally using existing execution facilities.
4. Return a structured, traceable result — the `LocalTakeoverResult`.

This answers the architectural question:

> "How does a target device's local runtime actually *take over* a handoff
> and execute locally, in a canonical and traceable way?"

---

## Architecture

```
Source runtime
     │
     │  HandoffEnvelopeV2 (PR-31)
     │  POST /api/v1/runtime/takeover
     ▼
TargetTakeoverHandler.handle()
     │
     ├── normalize_handoff_envelope()
     │       HandoffEnvelopeV2 / legacy dict / HandoffContract → HandoffEnvelopeV2
     │
     ├── check takeover policy (LocalTakeoverPolicy.allow_local_takeover)
     │
     ├── adopt_handoff_session()
     │       → LocalTakeoverSessionContext (adopted / created)
     │
     ├── build_local_takeover_context()
     │       → state_continuum dict for OpenClawd._run_execution()
     │
     ├── _run_local_execution()
     │       → OpenClawd._run_execution() or skipped result
     │
     ├── _try_governance_snapshot()  (optional, PR-27)
     │
     └── from_execution_output()
             → LocalTakeoverResult
```

---

## Contract: LocalTakeoverResult

`contracts/local_takeover_result.py` defines the canonical response contract:

| Field | Type | Description |
|---|---|---|
| `result_id` | `str` | UUID4 identifier for this takeover result |
| `trace_id` | `str?` | Distributed trace ID from the handoff envelope |
| `task_id` | `str?` | Task ID from the handoff envelope |
| `session_id` | `str?` | Local session ID (adopted or created) |
| `runtime_session_id` | `str?` | Runtime's internal session ID |
| `success` | `bool` | Whether execution completed without fatal error |
| `status` | `LocalTakeoverStatus` | Lifecycle status (pending/adopted/executing/succeeded/failed/blocked/rejected) |
| `result` | `dict?` | Raw local execution output dict |
| `execution_trace` | `dict?` | Serialised ExecutionTraceEnvelope (PR-25) |
| `governance_snapshot` | `dict?` | Serialised RuntimeGovernanceSnapshot (PR-27) |
| `policy_alignment` | `dict?` | Serialised ExecutionPolicyAlignmentSurface (PR-28) |
| `session_context` | `LocalTakeoverSessionContext?` | Resolved session context |
| `errors` | `list[str]` | Error/warning strings (empty on success) |
| `reason` | `str?` | Human-readable failure reason (None on success) |
| `timestamp` | `float` | Unix timestamp when result was produced |
| `metadata` | `dict` | Arbitrary extension metadata |

### LocalTakeoverStatus values

| Value | Meaning |
|---|---|
| `pending` | Received but not yet started |
| `adopted` | Session adopted; execution not yet run |
| `executing` | Local execution in progress |
| `succeeded` | Execution completed successfully |
| `failed` | Execution completed with error |
| `blocked` | Execution blocked before start (policy / readiness gate) |
| `rejected` | Takeover rejected (policy disallows / invalid envelope) |

---

## Session Adoption

### `adopt_handoff_session(envelope, *, existing_runtime_session_id=None)`

Maps the incoming envelope into a `LocalTakeoverSessionContext`:

- Extracts `trace_id`, `task_id`, `session_id` from the envelope.
- When `existing_runtime_session_id` is provided: marks the session as
  *adopted* (`adopted=True`).
- When no existing session ID: generates a new UUID4 (`adopted=False`).
- Optionally attaches a `mesh_session_id` from the PR-33 `BodyMeshRegistry`.

### `resolve_or_create_runtime_session(envelope, *, existing_runtime_session_id=None)`

Simpler helper: returns the existing session ID, the envelope's `session_id`,
or a fresh UUID4.

### `build_local_takeover_context(envelope, *, session_context, extra_metadata)`

Assembles the `state_continuum` dict compatible with
`OpenClawd._run_execution()`.  Extracts the task spec, session context, and
trace metadata from the envelope and merges them into the standard format.

---

## Envelope Normalisation

### `normalize_handoff_envelope(payload)`

Accepts any of:
- `HandoffEnvelopeV2` (returned unchanged)
- Legacy `HandoffContract` duck-type (converted via `from_legacy_handoff_contract`)
- Raw `dict` (wrapped via `build_handoff_envelope_v2`)
- `None` (returns minimal empty envelope with generated `trace_id`)

Always returns a `HandoffEnvelopeV2`.  Never raises.

---

## Entry Point

### `execute_local_takeover(payload, ...)` — module-level convenience function

```python
from core.runtime.target_takeover import execute_local_takeover
from contracts.handoff_envelope_v2 import build_handoff_envelope_v2

envelope = build_handoff_envelope_v2(
    trace_id="trace_abc",
    task={"tool_name": "screenshot", "args": {}},
    session_id="sess_001",
    target_device_id="tablet_002",
)
result = execute_local_takeover(envelope)
print(result.to_dict())
```

### `TargetTakeoverHandler.handle(payload, ...)` — stateless handler class

```python
from core.runtime.target_takeover import TargetTakeoverHandler

handler = TargetTakeoverHandler()
result = handler.handle(raw_envelope_dict)
```

---

## REST Endpoint

### `POST /api/v1/runtime/takeover`

Accepts a JSON body that is a handoff envelope or any compatible dict.

**Request body** (example — HandoffEnvelopeV2):

```json
{
  "trace_id": "trace_abc",
  "task_id": "task_001",
  "session_id": "sess_xyz",
  "task_spec": {
    "tool_name": "screenshot",
    "args": {}
  }
}
```

**Response** (LocalTakeoverResult):

```json
{
  "result_id": "...",
  "trace_id": "trace_abc",
  "task_id": "task_001",
  "session_id": "sess_xyz",
  "runtime_session_id": "...",
  "success": true,
  "status": "succeeded",
  "result": { "action_taken": "...", "success": true, ... },
  "execution_trace": { ... },
  "governance_snapshot": { ... },
  "policy_alignment": null,
  "session_context": {
    "session_id": "sess_xyz",
    "runtime_session_id": "...",
    "task_id": "task_001",
    "trace_id": "trace_abc",
    "adopted": false,
    "mesh_session_id": null
  },
  "errors": [],
  "reason": null,
  "timestamp": 1234567890.123,
  "metadata": { "entry_mode": "local", ... }
}
```

---

## Execution Trace and Governance Integration

When execution completes successfully, the result includes:

- **`execution_trace`** — the `ExecutionTraceEnvelope` dict from PR-25, as
  returned by `OpenClawd._run_execution()`.  Contains per-stage lifecycle
  events.
- **`governance_snapshot`** — the `RuntimeGovernanceSnapshot` dict from PR-27
  (captured via `_try_governance_snapshot()`).  Includes tri-state phase,
  runtime domain, policy posture, and readiness/fallback/execution summaries.

Both fields are `null` when the respective module is unavailable.

---

## Legacy Payload Compatibility

If the target runtime receives a **legacy `HandoffContract`** payload:

```python
from galaxy_gateway.agent_bridge import HandoffContract
# ...
result = execute_local_takeover(legacy_contract)
```

`normalize_handoff_envelope` calls `from_legacy_handoff_contract(legacy_contract)`,
which wraps it in a `HandoffEnvelopeV2` without modifying the existing bridge
integration.

---

## What This PR Does NOT Do

The following are explicitly **out of scope** for PR-34:

- No Mesh Session Coordinator engine (PR-37)
- No Source Runtime Dispatch Orchestrator (PR-35)
- No full device registration rewrite
- No new UI/dashboard work
- No result persistence or streaming
- No sweeping refactors of the execution core (`openclawd.py`, `agent_bridge.py`)
- No automatic acknowledgement-before-takeover flow
  (`require_ack_before_takeover` is honoured for *rejection only* in future PRs)

---

## Contract Chain

| PR | Contract | Role |
|---|---|---|
| PR-25 | `ExecutionTraceEnvelope` | Execution lifecycle trace |
| PR-27 | `RuntimeGovernanceSnapshot` | Runtime governance posture |
| PR-28 | `ExecutionPolicyAlignmentSurface` | Policy alignment surface |
| PR-29 | `RegisteredRuntimeDevice` | What a runtime device is |
| PR-30 | `LocalRuntimeHost` | What a local runtime host exposes |
| PR-31 | `HandoffEnvelopeV2` | The inbound handoff envelope |
| PR-32 | `MeshMembership` | Device mesh participation |
| PR-33 | `MeshSession` | Multi-device cooperative session |
| **PR-34** | **`LocalTakeoverResult`** | **Target-side takeover result** |

---

## File Locations

| File | Purpose |
|---|---|
| `contracts/local_takeover_result.py` | `LocalTakeoverResult` contract + adapters |
| `core/runtime/__init__.py` | Runtime sub-package |
| `core/runtime/target_takeover.py` | Takeover handler + session helpers |
| `core/routes/projection.py` | `POST /api/v1/runtime/takeover` endpoint |
| `tests/test_pr34_target_runtime_local_takeover.py` | Focused test suite |
| `docs/TARGET_RUNTIME_LOCAL_TAKEOVER.md` | This document |
