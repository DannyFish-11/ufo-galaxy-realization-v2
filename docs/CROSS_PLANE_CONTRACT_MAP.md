# Cross-Plane Contract Map & Messaging Taxonomy

> **PR-16** — Additive contract-map package for the Galaxy runtime.
>
> This document captures the current message planes and contract boundaries
> that already exist in the main-branch architecture.  It is grounded in real
> code paths; it does not invent new abstractions or replace existing ones.

---

## Table of Contents

1. [Purpose and scope](#purpose-and-scope)
2. [What this PR does NOT do](#what-this-pr-does-not-do)
3. [Current message planes](#current-message-planes)
4. [Representative contracts per plane](#representative-contracts-per-plane)
5. [Contract families: canonical vs compat-wrapped](#contract-families-canonical-vs-compat-wrapped)
6. [Package structure](#package-structure)
7. [Read-only introspection endpoints](#read-only-introspection-endpoints)
8. [How to register new contracts](#how-to-register-new-contracts)
9. [Design decisions](#design-decisions)

---

## Purpose and scope

The Galaxy runtime now contains multiple real message and contract planes that
already work, but their **ownership and boundaries** are not fully explicit in
one place.  Without a clear contract map, future work on device formation,
agent responsibility, reliability semantics, planning, and recovery risks
becoming fragmented or contradictory.

This PR creates a **real, code-adjacent contract map** — a descriptor layer over
the existing planes and message kinds.  It makes the current architecture
inspectable at runtime through a read-only API and serves as the stable
foundation for later device-formation, agent-governance, and reliability work.

---

## What this PR does NOT do

- Does **not** replace or modify `TaskEnvelope` (`core/schemas/task_envelope.py`).
- Does **not** replace or modify `HandoffContract` (`galaxy_gateway/agent_bridge.py`).
- Does **not** replace or modify `SwarmAgentManifest` (`core/control_plane/swarm_manifest.py`).
- Does **not** replace or modify NATS payload models (`core/nats_bus.py`).
- Does **not** introduce a new transport layer, orchestrator, or router.
- Does **not** perform sweeping router rewrites.
- Does **not** replace AIP/device protocols.
- Does **not** re-implement any message schemas; it provides a *descriptor* layer
  over them.

---

## Current message planes

The following planes are formalised in `core/contract_map/plane_kind.py`:

| Plane | Value | Primary code locus |
|---|---|---|
| Device plane | `device_plane` | `core/routes/devices.py`, `galaxy_gateway/device_router.py`, `core/unified/command_envelope.py` |
| Orchestration plane | `orchestration_plane` | `core/schemas/task_envelope.py`, `galaxy_gateway/orchestrator/task_orchestrator.py` |
| Control plane | `control_plane` | `core/nats_bus.py`, `core/control_plane/` |
| Runtime handoff plane | `runtime_handoff_plane` | `galaxy_gateway/agent_bridge.py`, `core/control_plane/swarm_manifest.py` |
| Projection plane | `projection_plane` | `core/routes/projection.py`, `core/projection/runtime_projection.py` |
| Observability plane | `observability_plane` | `core/routes/audit.py`, `core/routes/observability.py`, NATS `galaxy.audit.*` |

### Device plane

Covers all AIP/WebSocket flows between physical devices (Android app, desktop
client) and the Galaxy gateway.  Devices register, send heartbeats, report
capabilities, and deliver task results over this plane.

Key identity fields: `device_id`, `trace_id`.

### Orchestration plane

Covers the internal task-envelope lifecycle.  All work entering the executor
graph is wrapped in a `TaskEnvelope`; the orchestration plane governs how that
envelope is created, transitioned, and resolved.

State machine: `created → running → done | failed` (terminal).

Key identity fields: `task_id`, `trace_id`, `session_id`.

### Control plane

Covers NATS JetStream subjects that carry task dispatch, worker heartbeats, MCP
tool calls, capability registration events, and audit logs.  The control plane
is the internal nervous system between the gateway and worker processes.

NATS streams:
- `GALAXY_TASKS` — task dispatch and results (100K msgs, 1 GB)
- `GALAXY_MCP` — MCP calls (50K msgs, 512 MB)
- `GALAXY_EVENTS` — events and worker heartbeats (200K msgs, 512 MB)

Key identity fields: `task_id`, `trace_id`, `target`.

### Runtime handoff plane

Covers the contracts that transfer execution context from the gateway to a
downstream agent runtime or remote swarm member.

- **`HandoffContract`** — dataclass posted to `POST /handoff` at
  `GALAXY_RUNTIME_URL` (default `localhost:9000`).  Includes LRU dedup cache
  (1024 entries) and automatic fallback to local executor.
- **`SwarmAgentManifest`** — state-only, JSON-serialisable manifest for remote
  swarm dispatch.  `to_agent_execute_payload()` produces a PR155-compatible
  payload.

Key identity fields: `trace_id`, `task_id`, `manifest_id`, `agent_id`.

### Projection plane

Covers read-only derived/summarised state surfaces exposed to dashboards and
clients.  The projection plane *reads* from the runtime; it never writes.

Endpoints:
- `GET /api/v1/projection/runtime` — `RuntimeProjection` snapshot
- `GET /api/v1/projection/return` — with return-intelligence enrichment (PR-10)
- `GET /api/v1/projection/execution_policy` — with policy-band view (PR-11)
- `GET /api/v1/execution/merge-summary` — cross-device merge status (PR-14)

Key identity fields: `timestamp`.

### Observability plane

Cross-cutting audit traces, error telemetry, and diagnostic events that flow
orthogonally to all other planes.  All published audit events are also mirrored
to NATS `galaxy.audit.*` subjects.

Key identity fields: `trace_id`, `code`.

---

## Representative contracts per plane

### Device plane contracts

| Kind | Canonical type | Source module |
|---|---|---|
| `device_register` | _(informal)_ | `core.routes.devices` |
| `device_heartbeat` | _(informal)_ | `core.routes.devices` |
| `device_capability_report` | `CapabilityContract` | `core.unified.capability_contract` |
| `device_task_result` | `ResultEnvelope` | `core.unified.command_envelope` |
| `command_envelope` | `CommandEnvelope` | `core.unified.command_envelope` |

### Orchestration plane contracts

| Kind | Canonical type | Source module |
|---|---|---|
| `task_envelope` | `TaskEnvelope` | `core.schemas.task_envelope` |
| `task_envelope_cancel` | `CommandEnvelope` (verb=CANCEL) | `core.unified.command_envelope` |
| `task_envelope_interrupt` | `CommandEnvelope` (verb=INTERRUPT) | `core.unified.command_envelope` |

### Control plane contracts

| Kind | Canonical type | Source module |
|---|---|---|
| `nats_task_dispatch` | `TaskDispatchModel` | `core.nats_bus` |
| `nats_task_result` | `TaskResultModel` | `core.nats_bus` |
| `nats_worker_heartbeat` | `WorkerHeartbeatModel` | `core.nats_bus` |
| `nats_capability_event` | `AgentEventModel` | `core.nats_bus` |
| `nats_audit_event` | _(JSON, snake_case)_ | `core.nats_bus` |
| `nats_mcp_call` | `MCPCallRequestModel` | `core.nats_bus` |

### Runtime handoff plane contracts

| Kind | Canonical type | Source module |
|---|---|---|
| `handoff_contract` | `HandoffContract` | `galaxy_gateway.agent_bridge` |
| `swarm_agent_manifest` | `SwarmAgentManifest` | `core.control_plane.swarm_manifest` |

### Projection plane contracts

| Kind | Canonical type | Source module |
|---|---|---|
| `runtime_projection` | `RuntimeProjection` | `core.projection.runtime_projection` |
| `return_projection` | `RuntimeProjection` + enrichment | `core.routes.projection` |
| `execution_policy_projection` | `RuntimeProjection` + enrichment | `core.routes.projection` |
| `merge_summary` | _(dict)_ | `core.routes.projection` |

### Observability plane contracts

| Kind | Canonical type | Source module |
|---|---|---|
| `audit_trace` | _(structured dict)_ | `core.routes.audit` |
| `error_payload` | `ErrorPayload` | `core.unified.error_codes` |

---

## Contract families: canonical vs compat-wrapped

### Canonical contract families

The following are **canonical** — they are the authoritative representation in
their plane.  Future code should produce and consume these directly.

- **`TaskEnvelope`** — the single authoritative orchestration contract.  All
  incoming work must be wrapped here.  Use `envelope_from_command_request()`,
  `envelope_from_relay_request()`, or `envelope_from_mcp_call()` for legacy
  intake paths.
- **`CommandEnvelope`** (version `"3.0"`) — the AIP v3 wire-level contract.
  Use `from_task_envelope()` to bridge from orchestration → device plane.
- **`HandoffContract`** — the authoritative gateway-to-runtime transfer.
  Do not bypass `agent_bridge.py` for cross-runtime dispatch.
- **`SwarmAgentManifest`** — the authoritative remote swarm member payload.
  Always use `to_agent_execute_payload()` for backward compatibility.
- **`RuntimeProjection`** — the authoritative read surface.  Dashboards must
  consume this rather than reading internal state directly.

### Compat-wrapped / legacy paths

- `envelope_from_command_request()` — wraps a legacy `CommandDispatchRequest`
  in a `TaskEnvelope`.  **Still valid**, but new code should produce
  `TaskEnvelope` directly.
- `from_aip_message()` (on `CommandEnvelope`) — bridges AIP v2-style messages.
  Valid for backward compat with older clients.
- `compat.py` routes (`/api/devices`, `/api/v1` legacy prefixes) — maintained
  for backward compat with Android clients that have not yet upgraded.

---

## Package structure

```
core/contract_map/
├── __init__.py               # Public API exports
├── plane_kind.py             # PlaneKind enum
├── message_kind.py           # MessageKind enum
├── contract_descriptor.py    # ContractDescriptor frozen dataclass
├── contract_registry.py      # ContractRegistry singleton + seed data
└── contract_introspection.py # Read-only snapshot helpers
```

```
core/routes/contracts.py      # GET /api/v1/contracts/planes
                              # GET /api/v1/contracts/messages
```

```
tests/test_pr16_contract_map.py  # Tests for the contract map package
```

### `PlaneKind` (plane_kind.py)

`str` enum; values are stable identifiers for the six planes described above.

### `MessageKind` (message_kind.py)

`str` enum; values are stable identifiers for all known contract/message kinds
grounded in actual code paths.  Docstrings note the source module for each kind.

### `ContractDescriptor` (contract_descriptor.py)

Frozen dataclass.  Fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| `plane` | `PlaneKind` | ✓ | The plane this contract belongs to |
| `kind` | `MessageKind` | ✓ | Identifies this contract family |
| `canonical_type` | `str \| None` | — | Dotted import path for the schema class |
| `source_module` | `str \| None` | — | Module that owns the definition |
| `identity_fields` | `List[str]` | — | Fields that uniquely identify a message |
| `producer_modules` | `List[str]` | — | Modules that emit this kind |
| `consumer_modules` | `List[str]` | — | Modules that consume this kind |
| `notes` | `str \| None` | — | Compatibility / fallback notes |

### `ContractRegistry` (contract_registry.py)

Thread-safe singleton.  Seeded at import time with all known current-architecture
descriptors.  Additional descriptors can be registered at runtime via
`registry.register(descriptor)`.

### `contract_introspection.py`

Five read-only helper functions:

- `get_planes_snapshot()` — payload for `GET /api/v1/contracts/planes`
- `get_messages_snapshot()` — payload for `GET /api/v1/contracts/messages`
- `get_descriptor_for_kind(kind)` — descriptor dict for a specific kind
- `get_required_fields_summary()` — identity-fields summary for all contracts
- `get_contracts_for_plane(plane)` — all descriptor dicts for a plane

---

## Read-only introspection endpoints

### `GET /api/v1/contracts/planes`

Returns all planes and their message kinds.

```json
{
  "planes": {
    "device_plane": {
      "description": "AIP/WebSocket device-facing flows ...",
      "message_kinds": ["command_envelope", "device_heartbeat", ...]
    },
    "orchestration_plane": { ... },
    ...
  },
  "total_planes": 6,
  "total_contracts": 18
}
```

### `GET /api/v1/contracts/messages`

Returns full descriptor metadata for every registered contract.

```json
{
  "contracts": {
    "task_envelope": {
      "plane": "orchestration_plane",
      "kind": "task_envelope",
      "canonical_type": "core.schemas.task_envelope.TaskEnvelope",
      "source_module": "core.schemas.task_envelope",
      "identity_fields": ["task_id", "trace_id", "session_id"],
      "producer_modules": [...],
      "consumer_modules": [...],
      "notes": "..."
    },
    ...
  },
  "total_contracts": 18
}
```

Both endpoints:
- Are **read-only** — they never write state or trigger side-effects.
- Require **no authentication** — contract metadata is non-sensitive.
- Return HTTP 503 with an error payload if the contract-map package fails to
  load (graceful degradation).

---

## How to register new contracts

When adding a new message kind to the Galaxy runtime:

1. **Add a value to `MessageKind`** in `core/contract_map/message_kind.py`.
   Follow the `<noun>_<verb_or_role>` naming convention and include a docstring
   that references the source module.

2. **Register a descriptor** in `_seed_registry()` in
   `core/contract_map/contract_registry.py`.  At minimum provide `plane`,
   `kind`, `source_module`, and `identity_fields`.

3. **Update this document** — add a row to the appropriate plane's contract
   table above.

4. **Add a test** — add an entry to the `EXPECTED_CONTRACTS` set in
   `tests/test_pr16_contract_map.py` and verify the descriptor fields.

For experimental or plugin-provided contracts that should not be in the seed
layer, call `get_contract_registry().register(descriptor)` at startup.

---

## Design decisions

**Why descriptors instead of live type references?**
Using dotted string paths for `canonical_type` avoids import-time coupling.
The registry can be loaded and introspected even when optional modules (NATS,
swarm coordinator, etc.) are absent.  This is consistent with how the rest of
the codebase handles optional modules (try/except import pattern).

**Why a frozen dataclass for `ContractDescriptor`?**
Descriptors are immutable after creation.  The registry is the mutable
surface.  This prevents accidental mutation of shared descriptor objects and
makes the registry thread-safe for reads without locking.

**Why not extend the existing `core/schemas/contracts.py`?**
`core/schemas/contracts.py` contains *data schemas* (Pydantic models for wire
formats).  The contract map contains *metadata descriptors* — annotations
about those schemas.  Keeping them separate prevents circular imports and
maintains the principle of separation of concerns.

**Why no auth on the contract endpoints?**
Contract metadata describes the architecture, not user data or credentials.
It is non-sensitive and useful to diagnostics tooling and developer clients
alike.  This is consistent with `/api/v1/projection/runtime` and other
read-only diagnostic endpoints.
