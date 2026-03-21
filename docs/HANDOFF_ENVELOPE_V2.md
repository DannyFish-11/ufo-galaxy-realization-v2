# Handoff Envelope v2 — PR-31

This document describes the **Handoff Envelope v2** contract introduced in
PR-31.  It is the canonical cross-device runtime-handoff package that one
runtime host sends to another, and the stable foundation that future mesh and
local-takeover PRs will build on.

---

## Overview

The Galaxy system moves toward a model where each device hosts its own local
runtime.  Cross-device execution is not "remote API calls" but rather:

> **Agent / task dispatch → target device local runtime → local takeover**

PR-31 defines the structured package that travels between runtime hosts.

Before PR-31, the bridge sent a narrow `HandoffContract`:

```
trace_id, task, capability, exec_mode, route_mode, session, callback_channel
```

PR-31 adds a richer `HandoffEnvelopeV2` that additionally encodes:
- source and target device / runtime identity
- agent participation metadata
- structured task / session context bundles
- local takeover policy hints
- structured return expectations

Both representations are kept in parallel.  No existing code needs to change.

---

## How It Differs From the Current Bridge `HandoffContract`

| Concern | `HandoffContract` (legacy) | `HandoffEnvelopeV2` (PR-31) |
|---------|---------------------------|------------------------------|
| Source device identity | ✗ | ✓ (`source_device_id`, `source`) |
| Target device identity | ✗ | ✓ (`target_device_id`, `target`) |
| Runtime instance identity | ✗ | ✓ (`source_runtime_id`, `target_runtime_id`) |
| Agent specification | ✗ | ✓ (`agent_spec`) |
| Structured task bundle | flat `task` dict | ✓ (`task_spec` with `tool_name`, `args`, `targets`) |
| Structured session bundle | flat `session` dict | ✓ (`session_context` with `session_id`, `turn_id`, etc.) |
| Takeover policy hints | ✗ | ✓ (`takeover_policy`) |
| Return expectations | `callback_channel` only | ✓ (`return_contract`) |
| Governance policy | ✗ | ✓ (`handoff_policy`) |
| Schema versioning | ✗ | ✓ (`schema_version = "v2"`) |
| Legacy field preservation | n/a | ✓ (`capability`, `exec_mode`, `route_mode`, `callback_channel`) |

The legacy fields (`capability`, `exec_mode`, `route_mode`, `callback_channel`,
`trace_id`) are kept verbatim in the v2 envelope for backward compatibility.

---

## Contract Structure

### Top-level: `HandoffEnvelopeV2`

```python
HandoffEnvelopeV2(
    # Primary identity
    handoff_id="hev2_...",           # auto-generated
    trace_id="...",                  # required for dedup / tracing
    task_id=None,                    # from TaskEnvelope when available
    session_id=None,                 # for multi-step sessions

    # Device / runtime identity
    source_device_id="phone_001",
    target_device_id="tablet_002",
    source_runtime_id=None,
    target_runtime_id=None,

    # Structured sub-contracts
    source=HandoffSourceSummary(...),
    target=HandoffTargetSummary(...),
    agent_spec=HandoffAgentSpec(...),
    task_spec=HandoffTaskSpec(...),
    session_context=HandoffSessionContext(...),

    # Legacy bridge fields (preserved)
    capability="screen",
    exec_mode="both",
    route_mode="direct",
    callback_channel="ws",

    # Policy / return
    handoff_policy={...},            # from HandoffPolicy.to_dict()
    takeover_policy=LocalTakeoverPolicy(...),
    return_contract=HandoffReturnContract(...),

    # Metadata
    metadata={},
    schema_version="v2",
    created_at=1700000000.0,
)
```

### `HandoffSourceSummary` / `HandoffTargetSummary`

Carry device and runtime identity for each side of the handoff:

```python
HandoffSourceSummary(
    device_id="phone_001",
    runtime_id="rt_abc",
    platform="android",
    runtime_version="1.2.3",
    capability_summary=["screen", "camera", "microphone"],
    metadata={},
)
```

### `HandoffAgentSpec`

Describes the agent being dispatched:

```python
HandoffAgentSpec(
    agent_id="agent_executor_01",
    agent_type="executor",
    agent_role="primary",
    required_capabilities=["screen", "touch"],
    participation_hints={"prefer_local_inference": True},
)
```

### `HandoffTaskSpec`

Structured task to execute on the target:

```python
HandoffTaskSpec(
    task_id="task_xyz",
    tool_name="open_app",
    args={"app": "Chrome"},
    targets=["tablet_002"],
    source="phone_001",
    raw_task={...},          # original task dict for backward compat
)
```

### `HandoffSessionContext`

Session and context metadata:

```python
HandoffSessionContext(
    session_id="sess_abc",
    turn_id="turn_03",
    user_id="user_001",
    trace_context={"trace_id": "...", "span_id": "..."},
    raw_session={...},       # original session dict for backward compat
    metadata={},
)
```

### `LocalTakeoverPolicy`

Advisory hints for local takeover:

```python
LocalTakeoverPolicy(
    allow_local_takeover=True,
    require_ack_before_takeover=False,
    max_takeover_duration_s=30.0,
    release_on_completion=True,
    fallback_on_timeout=True,
)
```

### `HandoffReturnContract`

Structured return expectations:

```python
HandoffReturnContract(
    callback_channel="ws",
    callback_url=None,
    expect_ack=False,
    expect_result=True,
    result_schema_hint="screenshot_result_v1",
)
```

---

## Adapters and Builders

### `from_legacy_handoff_contract(contract)`

Converts a legacy `HandoffContract` → `HandoffEnvelopeV2`.  All legacy
fields are projected; unknown fields are left at defaults.

```python
from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
from galaxy_gateway.agent_bridge import HandoffContract

legacy = HandoffContract(trace_id="t1", task={"tool_name": "screenshot"})
envelope = from_legacy_handoff_contract(legacy)
```

### `from_bridge_inputs(...)`

Builds a `HandoffEnvelopeV2` directly from bridge call-site parameters
(trace_id, task dict, capability, etc.) while allowing richer fields like
`source_device_id` and `target_device_id` to be passed alongside.

```python
from contracts.handoff_envelope_v2 import from_bridge_inputs

envelope = from_bridge_inputs(
    trace_id="t2",
    task={"tool_name": "open_app"},
    capability="screen",
    source_device_id="phone_001",
    target_device_id="tablet_002",
)
```

### `to_legacy_bridge_payload(envelope)`

Converts a `HandoffEnvelopeV2` back to the legacy `POST /handoff` dict
compatible with the current runtime endpoint.

```python
from contracts.handoff_envelope_v2 import to_legacy_bridge_payload

payload = to_legacy_bridge_payload(envelope)
# → {"trace_id": ..., "task": ..., "capability": ..., ...}
```

### `build_handoff_envelope_v2(**kwargs)`

Convenience factory covering the most common construction patterns.

```python
from contracts.handoff_envelope_v2 import build_handoff_envelope_v2

envelope = build_handoff_envelope_v2(
    trace_id="t3",
    task={"tool_name": "take_screenshot"},
    source_device_id="phone_001",
    target_device_id="tablet_002",
    capability="screen",
    allow_local_takeover=True,
)
```

---

## Bridge Integration

`AgentBridge` has been updated in two additive ways:

### 1. Compact summary in bridge results

After a successful (or fallback) handoff, a compact projection-safe summary
of the v2 envelope is attached to the result dict under the key
`"handoff_envelope_v2"`.  This is additive — existing keys are not affected.

```python
result = await bridge.handoff(contract)
summary = result.get("handoff_envelope_v2")
# → {"handoff_id": "hev2_...", "trace_id": "...", "source_device_id": None, ...}
```

### 2. `AgentBridge.build_envelope_v2(contract, ...)`

A helper method that builds a full `HandoffEnvelopeV2` from a
`HandoffContract`, with optional richer fields like `source_device_id`,
`target_device_id`, and `handoff_policy`.

```python
bridge = AgentBridge()
envelope = bridge.build_envelope_v2(
    contract,
    source_device_id="phone_001",
    target_device_id="tablet_002",
)
if envelope:
    print(envelope.to_compact_summary())
```

The bridge still POSTs a legacy-compatible payload to the runtime endpoint —
no endpoint redesign is needed.

---

## Serialisation

All contracts support stable round-trip serialisation:

```python
# to dict
d = envelope.to_dict()

# to JSON string
j = envelope.to_json()

# from dict
envelope2 = HandoffEnvelopeV2.from_dict(d)

# compact summary (projection-safe)
summary = envelope.to_compact_summary()
```

---

## Package Exports

The new types are exported from both the `contracts` package and `core.unified`:

```python
# From contracts package
from contracts import (
    HandoffEnvelopeV2,
    HandoffSourceSummary,
    HandoffTargetSummary,
    HandoffAgentSpec,
    HandoffTaskSpec,
    HandoffSessionContext,
    LocalTakeoverPolicy,
    HandoffReturnContract,
    from_legacy_handoff_contract,
    from_bridge_inputs,
    to_legacy_bridge_payload,
    build_handoff_envelope_v2,
)

# From core.unified
from core.unified import HandoffEnvelopeV2, build_handoff_envelope_v2
```

---

## Compatibility

- **Legacy `HandoffContract`**: unchanged; all current bridge callers continue
  to work without modification.
- **`POST /handoff` runtime endpoint**: unchanged; the bridge still POSTs the
  same legacy payload.
- **`DeviceRouter.route_task()`**: unchanged.
- **Cross-device switch guard**: unchanged.
- **Deduplication cache**: unchanged.

---

## What This PR Does Not Do

- **No Mesh Membership contract** — that is PR-32.
- **No Mesh Session contract** — that is PR-33.
- **No target runtime local takeover execution path** — that is PR-34.
- **No full bridge/runtime endpoint redesign** — the `/handoff` endpoint and
  its POST payload are unchanged.
- **No registration-flow rewrite**.
- **No UI/dashboard redesign**.
- **No persistence/streaming redesign**.

---

## File Index

| File | Role |
|------|------|
| `contracts/handoff_envelope_v2.py` | Canonical Handoff Envelope v2 contract and adapters |
| `contracts/__init__.py` | Re-exports all PR-31 types |
| `core/unified/__init__.py` | Re-exports all PR-31 types |
| `galaxy_gateway/agent_bridge.py` | Additive bridge integration (compact summary + `build_envelope_v2`) |
| `docs/HANDOFF_ENVELOPE_V2.md` | This document |
| `tests/test_pr31_handoff_envelope_v2.py` | PR-31 tests |

---

## Sequence Context

This PR is step 3 of 5 in the cross-device contract chain:

1. **PR-29** — Unified Registered Runtime Device Contract (what a device *is*)
2. **PR-30** — Local Runtime Host Contract (what a device *exposes* as a host)
3. **PR-31** — Handoff Envelope v2 (what one host *sends* to another) ← **this PR**
4. **PR-32** — Mesh Membership Contract
5. **PR-33** — Mesh Session Contract
6. **PR-34** — Target Runtime Local Takeover Path

---

## Running the Tests

```bash
pytest tests/test_pr31_handoff_envelope_v2.py -v
```
