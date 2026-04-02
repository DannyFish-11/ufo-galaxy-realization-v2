# PR-B: Contract / Truth / Policy Closure

> Architecture closure document for the Galaxy runtime.
> Covers internal contract boundaries, device truth write/read boundaries,
> readiness/participation/validator/policy boundaries, policy output fields,
> and failure domain vocabulary.

---

## 1. Internal Contract Boundary

### Canonical Contracts

| Role | Canonical Class | Module |
|------|----------------|--------|
| **Internal dispatch contract** | `TaskEnvelope` | `core.schemas.task_envelope` |
| **Internal result contract** | `ResultEnvelope` | `core.unified.command_envelope` |
| Interaction/rendering contract | `InteractionEnvelope` | `core.schemas.interaction_envelope` |
| Executor dispatch contract | `CommandEnvelope` | `core.unified.command_envelope` |

### Boundary Model

```
┌─────────────────────────────────────────────────────────────────────────┐
│  PUBLIC API BOUNDARY                                                     │
│  Raw JSON / legacy request models / proto messages / mobile payloads     │
│  TaskDispatchModel, TaskResultModel, AIPMessage, CommandDispatchRequest  │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ normalised by edge adapters
┌────────────────────────────▼────────────────────────────────────────────┐
│  EDGE ADAPTER BOUNDARY                                                   │
│  AntiCorruptionLayer / normalize_to_task_envelope /                      │
│  normalize_ingress_to_envelope / TaskAdapterLayer /                      │
│  envelope_from_command_request / envelope_from_mcp_call                  │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ canonical contracts only
┌────────────────────────────▼────────────────────────────────────────────┐
│  INTERNAL CANONICAL BOUNDARY                                             │
│  TaskEnvelope → CommandRouter → transport substrate                      │
│  ResultEnvelope ← executor ← task graph runtime                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Invariants

- `TaskEnvelope` is the **only** valid internal dispatch contract.
- `ResultEnvelope` is the **only** valid internal result contract.
- Legacy models (`TaskDispatchModel`, `TaskResultModel`) must be normalised at the **EDGE ADAPTER boundary** before entering the internal routing path.
- No legacy model may cross the `INTERNAL_CANONICAL_BOUNDARY` without prior normalisation.

---

## 2. Truth Source Lock

### Device Write SSOT

Only **`UnifiedDeviceManager` (UDM)** writes device truth.
Canonical writes: `registered`, `online`, `capabilities`, `device_id`, `platform`.

### Canonical Read Contracts

| Scope | Canonical Model / Function | Module |
|-------|---------------------------|--------|
| Single-device read | `RegisteredRuntimeDevice` | `contracts.registered_runtime_device` |
| Multi-device read | `resolve_all_device_truth()` | `core.truth_integration_layer` |
| Layer-1 readiness read | `DeviceReadinessSummary` | `core.device_readiness` |

### Model Role Classification

| Model | Role | Notes |
|-------|------|-------|
| `UnifiedDeviceManager` | **write** | SSOT — sole authoritative writer |
| `UnifiedConnectionManager` | read | UCM — connection/presence truth |
| `RegisteredRuntimeDevice` | read | External single-device read contract |
| `CanonicalDeviceTruth` | read | Multi-device projection (TIL) |
| `DeviceReadinessSummary` | read | Layer-1 readiness projection |
| `ParticipationSummary` | enrich | Enrich-only — must not override L1 truth |
| `TaskDispatchModel` | adapter | Edge adapter input only |
| `TaskResultModel` | adapter | Edge adapter input only |
| `registered_devices` | compat | Read-only compat cache (not truth source) |
| `UnifiedDevice` | write | Internal UDM record |

### Invariants

- Only `UnifiedDeviceManager` writes `registered`, `online`, `capabilities`.
- External callers read device state **only** via `RegisteredRuntimeDevice`.
- Multi-device queries use **only** `resolve_all_device_truth()`.
- `registered_devices` compat cache is **read-only** and is not a truth source.
- `ParticipationSummary` must **not** override `registered`, `online`, or `routable`.

---

## 3. Readiness / Participation / Validator / Policy Boundary

### Layer Chain

```
Layer 1 — Readiness   (core.device_readiness)
    ↓
Layer 2 — Participation (core.device_participation)   [enrich-only]
    ↓
Layer 3 — Target Validation (core.target_device_validator)   [canonical inputs only]
    ↓
Layer 4 — Policy Convergence (core.admissibility_policy_convergence)
```

### Readiness Sub-types (Layer 1)

| Field | Meaning |
|-------|---------|
| `transport_present` | Any transport mechanism is physically connected |
| `transport_usable` | Transport can actively deliver messages |
| `device_routable` | Valid end-to-end canonical route exists |
| `effective_path` | Name of the canonical path: `direct_ws`, `ucm`, `relay`, or `none` |
| `registered` | Device is known to the canonical registry (UDM) |
| `online` | Device is online / heartbeat active |

### Participation Governance (Layer 2)

- `PARTICIPATION_ENRICH_ONLY = True` — participation is **enrich-only**.
- Participation **may** contribute: role, session_id, mesh membership, formation context.
- Participation **must not** override: `registered`, `online`, `routable` from Layer 1.
- `PARTICIPATION_CANNOT_OVERRIDE_CANONICAL_TRUTH` sentinel is present and non-empty.

### Validator Governance (Layer 3)

- `VALIDATOR_CANONICAL_INPUTS_ONLY = True` — validator only consumes canonical resolved truth.
- Legacy inputs must be normalised via `CanonicalValidationInput` before reaching Layer 3.

---

## 4. Standardised Policy Output

All device evaluations produce a `PolicyConvergenceOutput` with these canonical fields:

| Field | Type | Meaning |
|-------|------|---------|
| `eligibility` | bool | Overall policy verdict (device can be selected) |
| `capability_fit` | bool | Device satisfies all required capabilities |
| `route_preference` | str | Canonical name of preferred delivery path |
| `policy_score` | float [0,1] | Normalised ranking score (higher = better) |
| `transport_present` | bool | Transport mechanism physically present |
| `transport_usable` | bool | Transport can deliver messages |
| `device_routable` | bool | Valid canonical end-to-end route exists |
| `effective_path` | str | Active delivery path name |
| `degradation_reason` | str? | Why this device was degraded/fell back |
| `selected_target_reason` | str? | Why this device was/was not selected |
| `failure_domain` | str? | Canonical failure domain when `eligibility=False` |
| `reasons` | list[str] | Human-readable failure/degradation strings |
| `contract_version` | str | Schema version sentinel |

---

## 5. Failure Domain Vocabulary

### PR-13 Original Domains (preserved for backward compatibility)

| Domain | Meaning |
|--------|---------|
| `local_runtime_failure` | Local execution raised an error |
| `remote_capability_mismatch` | Target device does not support required mode/capability |
| `remote_device_unavailable` | Target device offline or unreachable |
| `gateway_transport_failure` | Transport layer (gateway/NATS/WebSocket) failure |
| `substrate_dispatch_failure` | CommandRouter unable to dispatch envelope |
| `orchestration_partial_failure` | Multi-device plan partially succeeded |
| `contract_validation_failure` | Schema/ACL/HITL rejection |
| `timeout_failure` | Operation did not complete in time |
| `unknown_failure` | Unclassifiable failure |

### PR-B Canonical Architectural Vocabulary

| Domain | Meaning |
|--------|---------|
| `semantic_failure` | Intent/capability/meaning mismatch at semantic routing level |
| `validation_failure` | Canonical validation failure (contract schema, ACL, capability, HITL) |
| `policy_failure` | Admissibility or selection policy rejected the attempt |
| `routing_failure` | Routing layer could not determine a valid dispatch path |
| `fabric_failure` | Execution fabric (NATS bus/agent bus) connectivity failure |
| `transport_failure` | Transport mechanism (WebSocket/relay/gateway) delivery failure |
| `executor_failure` | Executor (worker/node/MCP/skill/local runtime) error |

### Mapping between PR-13 and PR-B domains

| PR-13 Domain | PR-B Equivalent |
|--------------|-----------------|
| `local_runtime_failure` | `executor_failure` |
| `remote_capability_mismatch` | `semantic_failure` |
| `remote_device_unavailable` | `routing_failure` |
| `gateway_transport_failure` | `transport_failure` |
| `substrate_dispatch_failure` | `routing_failure` |
| `orchestration_partial_failure` | `executor_failure` |
| `contract_validation_failure` | `validation_failure` |
| `timeout_failure` | `transport_failure` |

Use `core.failure_domains.map_to_pr_b_domain(domain)` to convert.

---

## 6. Observability Signals

The following events are emitted by the policy convergence layer for operator observability:

| Event | Description |
|-------|-------------|
| `policy_convergence_eligible` | Device was evaluated as eligible |
| `policy_convergence_ineligible` | Device was evaluated as ineligible |
| `policy_convergence_readiness_error` | Layer-1 readiness query failed |
| `policy_convergence_participation_error` | Layer-2 participation query failed |
| `policy_convergence_validation_error` | Layer-3 validation query failed |

Each event includes `device_id`, `policy_score` (when eligible), and `failure_domain` (when ineligible).

---

## 7. Authority Module Index

| Module | Authority Sentinel | Purpose |
|--------|-------------------|---------|
| `core.contract_closure` | `INTERNAL_CONTRACT_CLOSURE_AUTHORITY` | Contract boundary declarations |
| `core.truth_source_lock` | `TRUTH_SOURCE_LOCK_AUTHORITY` | Device truth write/read governance |
| `core.admissibility_policy_convergence` | `ADMISSIBILITY_POLICY_CONVERGENCE_AUTHORITY` | Policy chain convergence point |
| `core.device_readiness` | `DEVICE_READINESS_AUTHORITY` | Layer-1 canonical readiness |
| `core.device_participation` | `DEVICE_PARTICIPATION_AUTHORITY` | Layer-2 enrich-only participation |
| `core.target_device_validator` | `TARGET_DEVICE_VALIDATOR_AUTHORITY` | Layer-3 canonical validation |
| `core.failure_domains` | `FAILURE_DOMAIN_CLOSURE_AUTHORITY` | Canonical failure domain taxonomy |
| `core.truth_integration_layer` | `TRUTH_INTEGRATION_LAYER_AUTHORITY` | UCM+UDM fusion / conflict resolution |
| `core.message_interop` | `MESSAGE_INTEROP_AUTHORITY` | Canonical message normalisation |
| `core.execution_spine` | `EXECUTION_SPINE_AUTHORITY` | Canonical execution ingress |
