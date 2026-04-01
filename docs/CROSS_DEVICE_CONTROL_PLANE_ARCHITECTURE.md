# Cross-Device Control-Plane Architecture

> **Status**: Canonical  
> **Introduced**: PR-13 (Integration and stabilization of canonical cross-device control plane)  
> **Scope**: Authoritative reference for the canonical cross-device control-plane layer model

---

## 1. Overview

The Galaxy cross-device control plane is a layered set of read-only, additive
modules that together answer the question:

> **Which devices are eligible, ready, and capable of participating in cross-device execution right now?**

The control plane is **not** the transport layer and **not** the orchestration
engine.  It is the *gating / eligibility / candidate-selection* layer that
sits between raw device state and actual task dispatch.

```
┌──────────────────────────────────────────────────────────────┐
│                    Orchestration Layer                        │
│  (ConstellationRuntime, TaskGraph, SmartOrchestrator, etc.)  │
└───────────────────────────┬──────────────────────────────────┘
                            │ reads eligibility from ▼
┌──────────────────────────────────────────────────────────────┐
│              Cross-Device Control Plane                       │
│                                                              │
│  Layer 1 — Readiness          core/device_readiness.py       │
│  Layer 2 — Participation      core/device_participation.py   │
│  Layer 3 — Formation/Mesh     core/mesh_participation_summary│
│  Layer 4 — Capability         core/capability_registry.py    │
│  Layer 5 — Target Validation  core/target_device_validator   │
│  Layer 6 — Candidate Res.     core/cross_device_candidates   │
│  Layer 7 — Constellation Gate core/constellation_runtime     │
│  Layer 8 — Cross-Device Policy core/cross_device_policy/     │
│  Layer 9 — Failure Domains    core/failure_domains.py        │
│                                                              │
└───────────────────────────┬──────────────────────────────────┘
                            │ reads raw state from ▼
┌──────────────────────────────────────────────────────────────┐
│              Device State / Transport Layer                   │
│  (galaxy_gateway transport, UnifiedDeviceManager,            │
│   CapabilityBus, MeshRegistry, SessionCoordinator, etc.)     │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. Layer Responsibilities

### Layer 1 — Readiness (`core/device_readiness.py`)

**Authority sentinel**: `DEVICE_READINESS_AUTHORITY`

**Question answered**: Is this device connected, online, and routable at the
transport level right now?

**Source of truth**: Aggregates across:
- `UnifiedDeviceManager` (device registry + online status)
- `UnifiedConnectionManager` (WebSocket connection state)
- `DeviceRouter` (gateway routing table)

**Key types**:
- `ConnectionSummary` — WebSocket / UCM / router-table connection state
- `RoutabilitySummary` — direct WS, UCM send, relay, mesh path availability
- `DeviceReadinessSummary` — combined readiness verdict

**Key helpers**:
- `get_device_readiness(device_id)` — full summary for a single device
- `is_device_cross_device_ready(device_id)` — boolean gate
- `get_cross_device_ready_devices()` — all currently ready devices

**Design constraints**:
- Read-only. Never modifies device state.
- Graceful degradation: missing subsystems record reasons, not exceptions.
- Not a proxy for orchestration eligibility (that is Layer 2).

---

### Layer 2 — Participation / Orchestration Eligibility (`core/device_participation.py`)

**Authority sentinel**: `DEVICE_PARTICIPATION_AUTHORITY`

**Question answered**: Is this device registered, runtime-present, and
eligible to participate in multi-device orchestration?

**Source of truth**: Aggregates across:
- Canonical device selector (`core.device_selection.canonical_device_selector`)
- Mesh membership registry
- Mesh session coordinator

**Key types**:
- `ParticipationSummary` — full participation assessment for a device

**Key helpers**:
- `get_device_participation(device_id)` — full participation summary
- `is_device_orchestration_ready(device_id)` — boolean gate
- `get_orchestration_ready_devices()` — all orchestration-eligible devices

**Design constraints**:
- Distinct from readiness. A device may be transport-ready but not
  orchestration-eligible (e.g., missing runtime presence record).
- Roles (`is_primary`, `is_source`, `is_relay`) describe participation intent,
  not routing decisions.

---

### Layer 3 — Formation / Mesh / Session Summary (`core/mesh_participation_summary.py`)

**Authority sentinel**: `MESH_PARTICIPATION_SUMMARY_AUTHORITY`

**Question answered**: What is the current mesh / formation / session
participation state, as a unified serialisable summary?

**Source of truth**: Aggregates across:
- `FormationSummary` (device formation manager)
- `MeshMembership` (mesh registry)
- `MeshSession` (mesh session coordinator)
- `BodyMeshRegistry`

**Key types**:
- `MeshParticipationSummary` — unified mesh/session/formation view

**Key helpers**:
- `get_current_mesh_participation_summary()` — aggregate summary
- `get_device_mesh_summary(device_id)` — device-scoped view

**Design constraints**:
- Read-only. Does not modify formation, mesh, or session state.
- Used by orchestration layer for multi-device session context.

---

### Layer 4 — Capability Resolution (`core/capability_registry.py`)

**Authority sentinel**: `CAPABILITY_REGISTRY_AUTHORITY`

**Question answered**: What capabilities does this device have, and does it
satisfy a given set of capability requirements?

**Source of truth**: Union of:
1. `DeviceRegistry` (declared capabilities at registration)
2. `CapabilityBus` (runtime-advertised capabilities)
3. `GatewayCapabilityRegistry` (legacy gateway surface)

**Key types**:
- `DeviceCapabilitySummary` — capability summary for a device
- `CapabilityMatchResult` — match result for a requirement check

**Key helpers**:
- `get_device_capability_summary(device_id)` — full capability summary
- `device_matches_capabilities(device_id, required_capabilities)` — boolean gate
- `get_devices_matching_capabilities(required_capabilities)` — all capable devices

**Design constraints**:
- Union-based capability resolution (any source declaring a capability counts).
- Missing sources degrade gracefully; reasons are recorded.
- `resolved_capabilities` is the recommended field for policy decisions;
  `declared_capabilities` is registration-time only.

---

### Layer 5 — Target-Device Validation (`core/target_device_validator.py`)

**Authority sentinel**: `TARGET_DEVICE_VALIDATOR_AUTHORITY`

**Question answered**: Given an explicit `target_device_id`, is that device
valid, ready, capability-matched, and (optionally) orchestration-eligible?

**Source of truth**: Delegates to Layer 1 (readiness), Layer 4 (capability),
and Layer 2 (participation), then combines into a single validation result.

**Key types**:
- `TargetDeviceValidationResult` — combined validation verdict

**Key helpers**:
- `validate_target_device(device_id, required_capabilities, require_orchestration_eligible)`

**Design constraints**:
- Returns a structured result, not a plain boolean, so callers can inspect
  which specific check failed.
- Used for explicit `target_device` requests (not for open candidate selection).
- Orchestration eligibility check is opt-in (`require_orchestration_eligible=False`
  by default).

---

### Layer 6 — Cross-Device Candidate Resolution (`core/cross_device_candidates.py`)

**Authority sentinel**: `CROSS_DEVICE_CANDIDATES_AUTHORITY`

**Question answered**: For an open cross-device execution request (no explicit
target or multiple targets needed), which devices are selected?

**Source of truth**: Combines Layers 1 + 2 + 4 in order:
1. Readiness gate (Layer 1)
2. Orchestration eligibility gate (Layer 2, optional)
3. Capability gate (Layer 4)

**Key types**:
- `CrossDeviceCandidate` — per-device eligibility record
- `CrossDeviceCandidateResolution` — full resolution result with selected/eligible sets

**Key helpers**:
- `resolve_cross_device_candidates(required_capabilities, requested_target_device, require_orchestration_eligible)`
- `get_selected_cross_device_candidates(...)` — convenience wrapper

**Design constraints**:
- When `requested_target_device` is provided, only that device is evaluated
  (effectively a single-candidate pass of Layer 5 logic).
- When no target is specified, all known devices are evaluated.
- Every exclusion decision is logged with a structured reason string.

---

### Layer 7 — Constellation Scheduling Gate (`core/constellation_runtime.py`)

**Authority sentinel**: (module-level documentation)

**Question answered**: Before scheduling a multi-device task plan, are there
enough orchestration-ready devices to proceed?

**Source of truth**: Delegates to Layer 2 (`get_orchestration_ready_devices`,
`is_device_orchestration_ready`) as the canonical participation gate.

**Key methods**:
- `_get_orchestration_candidate_set()` — returns current orchestration-ready devices
- `_check_scheduling_gate(min_devices, required_capabilities, require_orchestration_eligible)` — fail-fast gate before DAG construction
- `_is_orchestration_ready(device_id)` — per-device participation check

**Design constraints**:
- Fail-fast: raises or returns early before expensive DAG construction
  when the candidate set is insufficient.
- Does not implement its own readiness/participation logic; always delegates
  to the canonical control-plane helpers.

---

### Layer 8 — Cross-Device Policy (`core/cross_device_policy/`)

**Authority sentinel**: (package-level)

**Question answered**: Given the current system signals (runtime domain,
execution policy, authority role, device assignments), what routing posture
and role assignments should apply?

**Key types**:
- `DeviceRole` — enum: source, primary_execution, support, observer, relay, fallback, unassigned
- `DeviceRoleAssignment` — per-device role record
- `RoutingPosture` — enum: local_preferred, local_then_expand, remote_required, split_execution, mirrored_observation, undecided
- `RoutingPolicy` — full routing policy for a request
- `CrossDeviceAssignmentSummary` — serialisable summary for downstream consumers

**Key helpers**:
- `resolve_routing(domain, execution_policy, authority_role, ...)` — derive `RoutingPolicy`
- `build_assignment_summary(policy)` — convert to summary
- `attach_cross_device_to_projection(projection_dict, summary)` — add to projection
- `get_assignment_hints(summary)` — compact boolean hints

**Design constraints**:
- Policy resolution reads signals; it does not perform readiness checks itself.
  That is delegated to Layers 1–6.
- `DEFAULT_LOCAL_ROUTING_POLICY` and `IDLE_ASSIGNMENT_SUMMARY` are the
  safe-fallback constants for callers that cannot determine the policy.

---

### Layer 9 — Failure Domains (`core/failure_domains.py`, `core/schemas/execution_failure.py`)

**Authority sentinel**: (module-level)

**Question answered**: When a cross-device execution attempt fails, what kind
of failure occurred and what retry/fallback policy applies?

**Key types**:
- `FailureDomain` — canonical failure domain enum (9 domains)
- `FailureClassification` — structured failure classification
- `RetryPolicy` — structured retry eligibility and limits
- `FallbackPolicy` — structured fallback execution policy
- `FailureRecord` — combined classification + policies for a single failure

**Key helpers**:
- `classify_from_error_code(error_code)` — classify from gateway error codes
- `classify_from_exception(exc)` — classify from Python exceptions
- `build_failure_record(error_code)` — full record with derived policies
- `failure_record_summary(record)` — compact JSON-safe dict

**Design constraints**:
- `core.failure_domains` is import-safe (no heavy dependencies).
- Failure policy objects are descriptors only; actual retry/fallback logic
  lives in the transport and dispatch layers.

---

## 3. Gateway Transport Boundary

The gateway transport layer (`galaxy_gateway/`) is explicitly **not** a
control-plane component.  It is responsible for:

- WebSocket connection management (`websocket_handler.py`)
- Device routing table (`device_router.py`)
- Cross-device message coordination (`cross_device_coordinator.py`)
- Session/state-of-truth storage (`ssot.py`)

**What the gateway is NOT**:
- It is not the source of truth for device readiness. Gateway connection state
  is one *input* to Layer 1, not the verdict.
- It does not make orchestration eligibility decisions.
- It does not perform capability matching.

See `galaxy_gateway/GATEWAY_TRANSPORT_BOUNDARY.md` for the transport boundary
sentinels and contracts.

---

## 4. Source-of-Truth Expectations

| Concept | Source of Truth | Module |
|---|---|---|
| Device registered | UnifiedDeviceManager / DeviceRegistry | Layer 1 aggregates |
| Transport connected | UnifiedConnectionManager, DeviceRouter | Layer 1 |
| Orchestration eligible | Canonical device selector + mesh membership | Layer 2 |
| Formation / session | FormationManager, MeshRegistry, SessionCoordinator | Layer 3 |
| Capabilities | DeviceRegistry + CapabilityBus + GatewayCapabilityRegistry | Layer 4 |
| Target device valid | Layers 1 + 2 + 4 combined | Layer 5 |
| Open candidate set | Layers 1 + 2 + 4 combined | Layer 6 |
| Scheduling gate | Layer 2 (orchestration eligibility) | Layer 7 |
| Routing posture | Runtime domain + execution policy + authority role | Layer 8 |
| Failure domain | Error code / exception classification | Layer 9 |

---

## 5. Naming and Field Conventions

Across all control-plane modules, the following field naming conventions apply:

### Boolean gates
| Field | Meaning |
|---|---|
| `ready` | Device passes the canonical readiness gate (Layers 1) |
| `orchestration_eligible` | Device passes the orchestration participation gate (Layer 2) |
| `capability_match` | Device satisfies the required capability set (Layer 4) |
| `valid` | Device passes all requested validation checks (Layer 5) |
| `selected` | Device is included in the candidate resolution result (Layer 6) |

### Diagnostic fields
| Field | Meaning |
|---|---|
| `reasons` | List of human-readable strings explaining exclusions or degradations |
| `sources` | Dict mapping source-name → raw data from that source |

### Logging event names (structured `extra=` fields)
| Event name | Layer | Meaning |
|---|---|---|
| `readiness_check_failed` | 1 | Readiness subsystem raised an error |
| `readiness_cross_device_list_failed` | 1 | Could not enumerate ready devices |
| `target_validation_readiness_error` | 5 | Readiness check error during target validation |
| `target_validation_failed` | 5 | Target validation returned invalid verdict |
| `target_validation_passed` | 5 | Target device passed all checks |

---

## 6. Intended Layering Invariants

1. **Higher layers call lower layers, never the reverse.**  
   Candidate resolution (Layer 6) calls readiness (Layer 1), participation
   (Layer 2), and capability (Layer 4). Layer 1 never calls Layer 6.

2. **The gateway transport layer (galaxy_gateway) does not call control-plane
   layers.**  
   Control-plane modules are called by orchestration code *above* the gateway.
   The gateway provides raw connection state as input to Layer 1.

3. **All control-plane modules are read-only and additive.**  
   No control-plane module modifies device state, registry entries, or session
   records. They only read and aggregate.

4. **Every module degrades gracefully.**  
   Missing subsystems record reasons rather than raising exceptions.
   Partial results are always returned.

5. **All imports of optional subsystems are lazy (inside functions).**  
   This prevents circular imports and allows the modules to be imported
   safely before all subsystems are initialized.

---

## 7. Related Documents

- [`CROSS_DEVICE_EXECUTION_CHAIN.md`](CROSS_DEVICE_EXECUTION_CHAIN.md) — the execution chain from OpenClawd to device
- [`CROSS_DEVICE_ROLE_ROUTING_POLICY.md`](CROSS_DEVICE_ROLE_ROUTING_POLICY.md) — role and routing policy details
- [`GATEWAY_TRANSPORT_BOUNDARY.md`](../galaxy_gateway/GATEWAY_TRANSPORT_BOUNDARY.md) — gateway transport boundary contracts
- [`CANONICAL_DEVICE_IDENTITY_CONTRACT.md`](CANONICAL_DEVICE_IDENTITY_CONTRACT.md) — device identity contracts
- [`CAPABILITY_RUNTIME_STATE.md`](CAPABILITY_RUNTIME_STATE.md) — capability runtime state details
- [`MESH_SESSION_CONTRACT.md`](MESH_SESSION_CONTRACT.md) — mesh session contracts

---

## 8. Contributor Notes

When adding a new cross-device control-plane concern:

1. **Identify which layer it belongs to** (or whether it is a new layer).
2. **Do not duplicate** readiness/participation/capability logic — call the
   canonical helpers instead.
3. **Use the standard field names** (`ready`, `orchestration_eligible`,
   `capability_match`, `valid`, `selected`, `reasons`, `sources`).
4. **Degrade gracefully** — wrap subsystem imports in `try/except` and record
   reasons on failure.
5. **Do not call the gateway** from control-plane code. The gateway is a
   transport sink; it provides raw state upward, not decisions downward.
6. **Log exclusion decisions** at `INFO` level with structured `device_id` and
   `reason` fields so operators can trace why a device was skipped.
7. **Add an authority sentinel** to new control-plane modules so the module
   can be identified and traced across the codebase.
