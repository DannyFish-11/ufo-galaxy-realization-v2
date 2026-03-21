# Delivery Semantics & Reliability Contract

> PR-19 (V4) — Reliability Contract & Delivery Semantics

## Overview

This document describes the **reliability-contract layer** introduced in PR-19.
The layer is a focused additive package (`core/reliability_contract/`) that
formalises delivery semantics — delivery mode, ack posture, deduplication,
timeout ownership, and fallback ownership — across the Galaxy runtime's existing
cross-device/runtime/message paths.

The layer is **read-only** with respect to transport.  It does not replace or
modify any existing transport, bus, or orchestration implementation.  It
provides stable, serialisable, inspectable annotations over what already exists.

---

## Concepts

### Delivery Mode

Defined in `core/reliability_contract/delivery_mode.py`.

| Mode | Meaning |
|------|---------|
| `best_effort` | No ack, no persistence, no retry. Message may be silently dropped. |
| `at_most_once` | At most one delivery attempt. Errors surfaced but not retried. |
| `at_least_once` | One or more delivery attempts. Consumers must be idempotent. |
| `dedup_required` | At-least-once with explicit dedup key. Consumer discards duplicates. |
| `exactly_once` | Full end-to-end exactly-once. Transactional or enforced idempotency. |
| `unknown` | Not yet classified. Treat as `best_effort` for safety. |

### Ack Stage

Defined in `core/reliability_contract/ack_policy.py`.

| Stage | Meaning |
|-------|---------|
| `no_ack` | No acknowledgement expected. Fire-and-forget. |
| `accepted_ack` | Ack on receipt/validation — before operation completes. |
| `completed_ack` | Ack on full operation completion — result or terminal state. |
| `unknown` | Not yet classified. Treat as `no_ack` for safety. |

**AckPolicy** combines the ack stage with an advisory timeout hint and a
flag indicating whether a missing ack triggers a retry.

### Timeout Owner

Defined in `core/reliability_contract/timeout_owner.py`.

| Owner | Meaning |
|-------|---------|
| `transport` | Transport layer (WebSocket, NATS, HTTP) enforces timeout. |
| `router` | Routing layer (CommandRouter, device_router) holds dispatch timeout. |
| `runtime` | Runtime bridge (AgentBridge) enforces handoff/execution timeout. |
| `coordinator` | Orchestration coordinator (TaskOrchestrator, GlobalArbiter) holds end-to-end timeout. |
| `caller` | Caller/client enforces its own timeout. |
| `unspecified` | Timeout ownership not yet declared. |

Timeout ownership is **advisory** — it documents who *should* enforce the
timeout.  Actual enforcement lives in the transport and runtime layers.

### Fallback Owner

Defined in `core/reliability_contract/fallback_owner.py`.

| Owner | Meaning |
|-------|---------|
| `local_fallback` | Local agent/runtime executes fallback (AgentBridge `local_fallback`). |
| `transport_fallback` | Transport layer retries or switches to alternative channel. |
| `reroute_owner` | Routing layer reroutes to different device/executor. |
| `coordinator` | Orchestration coordinator decides: reschedule, split, or abort. |
| `abort_owner` | Failure propagates upward; task cancelled. |
| `caller` | Caller/client decides fallback (e.g. HITL). |
| `unspecified` | Fallback ownership not yet declared. |

### Deduplication Key

Defined in `core/reliability_contract/idempotency.py`.

A `DeduplicationKey` names the envelope/message fields that together uniquely
identify a message instance for dedup purposes.  It records:

- `fields` — list of field names forming the key
- `composition` — how fields combine (e.g. `<task_id>:<idempotency_key>`)
- `source_component` — component responsible for constructing/enforcing the key
- `enforced` — whether dedup is actively enforced at runtime

Note: This module describes the dedup contract.  Actual enforcement at the
orchestration level is handled by
`core.unified.idempotency.IdempotencyStore` (Block-5).

### Retry Policy

Defined in `core/reliability_contract/retry_policy.py`.

`RetryPolicy` describes the retry contract: maximum attempts, backoff, which
component owns retries, and which conditions trigger them.  This is
**advisory** — actual retry execution lives in the transport/runtime layers.

### Reliability Summary

Defined in `core/reliability_contract/reliability_summary.py`.

`ReliabilitySummary` is the top-level serialisable type that combines all
reliability dimensions for a single runtime path:

```python
@dataclasses.dataclass(frozen=True)
class ReliabilitySummary:
    path_key: str
    description: str
    delivery_mode: DeliveryMode
    ack_policy: AckPolicy
    dedup_key: DeduplicationKey
    retry_policy: RetryPolicy
    timeout_owner: TimeoutOwner
    fallback_owner: FallbackOwner
    source_module: Optional[str]
    notes: Optional[str]
    schema_version: int
```

---

## Runtime Path Mappings

The following five representative paths are seeded in
`RELIABILITY_PATH_REGISTRY`:

### 1. `task_envelope` — TaskEnvelope Orchestration Dispatch

| Dimension | Value |
|-----------|-------|
| Delivery mode | `dedup_required` |
| Ack stage | `accepted_ack` |
| Dedup fields | `task_id`, `idempotency_key` |
| Dedup enforced | ✅ Yes (IdempotencyStore) |
| Timeout owner | `coordinator` |
| Fallback owner | `coordinator` |
| Source module | `core.unified.command_envelope` |

**Notes:** `CommandEnvelope.idempotency_key` is validated by
`IdempotencyStore` (Block-5). Duplicate commands raise `DuplicateCommandError`.
Retry and fallback are coordinator-owned via `e2e_orchestrator` / `GlobalArbiter`.

---

### 2. `nats_task` — NATS Task Dispatch/Result Path

| Dimension | Value |
|-----------|-------|
| Delivery mode | `at_least_once` |
| Ack stage | `accepted_ack` |
| Dedup fields | `task_id`, `trace_id` (advisory) |
| Dedup enforced | ❌ No (application responsibility) |
| Timeout owner | `transport` |
| Fallback owner | `coordinator` |
| Source module | `core.nats_bus` |

**Notes:** NATS JetStream consumer groups provide at-least-once delivery at the
broker level. Consumer-side dedup is the application layer's responsibility.
Fallback to coordinator when NATS is unavailable.

---

### 3. `agent_bridge_handoff` — HandoffContract / AgentBridge Runtime Handoff

| Dimension | Value |
|-----------|-------|
| Delivery mode | `at_least_once` |
| Ack stage | `completed_ack` |
| Dedup fields | `trace_id`, `task_id` |
| Dedup enforced | ❌ No (advisory correlation) |
| Timeout owner | `runtime` |
| Fallback owner | `local_fallback` |
| Source module | `galaxy_gateway.agent_bridge` |

**Notes:** `AgentBridge.handoff()` returns a result dict; on timeout or error,
`local_fallback()` is invoked (RECOVERY agent role takes ownership per PR-18).
`HandoffPolicy.handoff_timeout_hint_ms` is the advisory timeout source.

---

### 4. `command_router_remote` — CommandRouter Remote Agent Dispatch

| Dimension | Value |
|-----------|-------|
| Delivery mode | `at_least_once` |
| Ack stage | `accepted_ack` |
| Dedup fields | `task_id` (advisory) |
| Dedup enforced | ❌ No (callers responsible) |
| Timeout owner | `router` |
| Fallback owner | `reroute_owner` |
| Source module | `core.command_router` |

**Notes:** `CommandRouter.dispatch_agent_remote()` issues `agent_deploy` +
`agent_execute` via `DeviceCommunication`. On failure, `reroute_owner`
(CommandRouter) may attempt an alternative device.

---

### 5. `device_websocket` — Device WebSocket Execution Path

| Dimension | Value |
|-----------|-------|
| Delivery mode | `best_effort` |
| Ack stage | `no_ack` |
| Dedup fields | `message_id` (advisory) |
| Dedup enforced | ❌ No |
| Timeout owner | `transport` |
| Fallback owner | `local_fallback` |
| Source module | `galaxy_gateway.transport.websocket_server` |

**Notes:** WebSocket commands are fire-and-forget at the transport level.
Device heartbeat/ack responses are application-layer signals; they do not
constitute a transport-layer ack. Local fallback via AgentBridge when device
is unreachable.

---

## Introspection API

### `GET /api/v1/contracts/reliability`

Returns the full reliability registry as a JSON payload.

```json
{
  "paths": {
    "task_envelope": {
      "path_key": "task_envelope",
      "description": "...",
      "delivery_mode": "dedup_required",
      "ack_policy": { "stage": "accepted_ack", "ack_timeout_hint_ms": 5000, ... },
      "dedup_key": { "fields": ["task_id", "idempotency_key"], ... },
      "retry_policy": { "max_attempts": 3, ... },
      "timeout_owner": "coordinator",
      "fallback_owner": "coordinator",
      "source_module": "core.unified.command_envelope",
      "notes": "...",
      "schema_version": 1
    },
    ...
  },
  "total_paths": 5,
  "schema_version": 1
}
```

This endpoint is **read-only** and always available.

---

## Python API

```python
from core.reliability_contract import (
    DeliveryMode,
    AckStage,
    AckPolicy,
    TimeoutOwner,
    FallbackOwner,
    DeduplicationKey,
    RetryPolicy,
    ReliabilitySummary,
    get_summary_for_path,
    list_known_paths,
    get_reliability_registry_snapshot,
    attach_reliability_to_projection,
    make_reliability_summary,
    RELIABILITY_PATH_REGISTRY,
    UNKNOWN_RELIABILITY_SUMMARY,
)

# Look up a known path
summary = get_summary_for_path("task_envelope")
print(summary.delivery_mode)        # DeliveryMode.DEDUP_REQUIRED
print(summary.timeout_owner)        # TimeoutOwner.COORDINATOR
print(summary.fallback_owner)       # FallbackOwner.COORDINATOR

# Build a custom summary
custom = make_reliability_summary(
    path_key="my_path",
    description="My custom path",
    delivery_mode="at_least_once",
    ack_stage="accepted_ack",
    timeout_owner="runtime",
    fallback_owner="local_fallback",
    dedup_fields=["task_id"],
)

# Attach to a projection dict
enriched = attach_reliability_to_projection(projection_dict, path_key="nats_task")

# Get full registry snapshot
snapshot = get_reliability_registry_snapshot()
```

---

## What This PR Does Not Yet Enforce

The reliability-contract layer is intentionally **read-only** with respect to
runtime behaviour.  The following are explicitly out of scope for PR-19:

1. **No new retry engine** — `RetryPolicy` describes semantics; actual retry
   execution lives in transport/runtime layers.
2. **No new timeout enforcement** — `TimeoutOwner` is advisory; enforcement
   lives in `AgentBridge`, `CommandRouter`, and `TaskOrchestrator`.
3. **No transport modification** — WebSocket, NATS, and HTTP implementations
   are unchanged.
4. **No new orchestrator** — `TaskOrchestrator` and `GlobalArbiter` are
   unchanged.
5. **No automatic dedup injection** — `DeduplicationKey` describes existing
   dedup contracts; `IdempotencyStore` (Block-5) continues to own enforcement
   for the `task_envelope` path.

---

## How Future Code Should Classify New Delivery Paths

When adding a new cross-device or runtime message path:

1. Choose the appropriate `DeliveryMode` based on transport guarantees.
2. Determine the ack stage: is a response required on acceptance, completion,
   or neither?
3. Identify the dedup key fields if the path will carry duplicates.
4. Declare the timeout owner: which component holds the deadline?
5. Declare the fallback owner: which component decides what happens on failure?
6. Register a `ReliabilitySummary` in `RELIABILITY_PATH_REGISTRY`.
7. If the path needs an architecture-level contract, also register it in
   `core/contract_map/` (PR-16) and link the two entries via `source_module`.

Use `make_reliability_summary()` for quick classification of new paths and
`ReliabilitySummary.to_dict()` for stable JSON output.

---

## Relationship to Other Packages

| Package | Relationship |
|---------|-------------|
| `core/contract_map/` (PR-16) | Sibling: describes *what* messages exist on each plane. Reliability contract describes *how reliably* they are delivered. |
| `core/device_formation/` (PR-17) | Sibling: formation groups may inform which fallback device is used; reliability contract describes the semantics of the path between them. |
| `core/agent_governance/` (PR-18) | Sibling: `HandoffPolicy` (PR-18) provides handoff timeout hints that map to `agent_bridge_handoff` timeout/fallback semantics. |
| `core/unified/idempotency.py` (Block-5) | Upstream: `IdempotencyStore` enforces the dedup contract described by `TASK_ENVELOPE_DEDUP_KEY`. |
| `core/unified/command_envelope.py` (PR-2) | Upstream: `CommandEnvelope.idempotency_key` is the dedup key field for the `task_envelope` path. |
| `core/nats_bus.py` (PR-2) | Upstream: NATS delivery semantics described by `nats_task` summary. |
| `galaxy_gateway/agent_bridge.py` | Upstream: handoff delivery semantics described by `agent_bridge_handoff` summary. |
| `core/command_router.py` | Upstream: remote dispatch semantics described by `command_router_remote` summary. |
