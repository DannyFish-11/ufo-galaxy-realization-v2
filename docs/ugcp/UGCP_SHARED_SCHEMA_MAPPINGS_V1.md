# UGCP Shared Schema Mappings v1 (realization-v2)

This note documents the incremental compatibility shims from current key contracts into
`core.schemas.ugcp` shared canonical objects.

It is an architecture-grounding layer, not a claim of full migration.

## Canonical namespace

- `core.schemas.ugcp` (exports)
- `core.schemas.ugcp.shared` (definitions + mapping shims)

## Mapping table

| Existing construct | Mapping shim | Canonical UGCP object |
|---|---|---|
| `core.schemas.task_envelope.TaskEnvelope` | `map_from_task_envelope(...)` | `core.schemas.ugcp.TaskEnvelope` |
| `core.delegated_runtime_dispatch_intent.DelegatedRuntimeDispatchRecord` | `map_from_delegated_dispatch_record(...)` | `core.schemas.ugcp.DispatchDecision` |
| `core.delegated_runtime_handoff_contract.DelegatedHandoffContractRecord` | `map_from_delegated_handoff_contract(...)` | `core.schemas.ugcp.HandoffRequest` |
| `contracts.runtime_session_snapshot.RuntimeSessionSnapshot` | `map_from_runtime_session_snapshot(...)` | `core.schemas.ugcp.RuntimeTruth` |
| `core.message_interop` normalized payload shapes | `map_from_message_interop_payload(...)` | `core.schemas.ugcp.TaskEnvelope` |

## Shared families covered

- Identity: `TaskId`, `TraceId`, `ControlSessionId`, `RuntimeSessionId`, `MeshSessionId`, `NodeId`, `ExecutionInstanceId`
- Control: `TaskEnvelope`, `DispatchDecision`, `Assignment`, `ExecutionLease`, `HandoffRequest`, `TakeoverDecision`
- Runtime: `RuntimeTarget`, `CapabilityProfile`, `ReadinessProfile`, `RuntimePosture`, `DiagnosticsReport`
- Coordination: `MeshSession`, `MeshParticipant`, `CoordinationRole`, `BarrierState`, `AggregationPlan`
- Truth: `SessionTruth`, `TaskTruth`, `RuntimeTruth`, `TruthEvent`, `TerminalState`, `TerminalReason`

## Stability note

This shared schema layer is additive and coexistence-oriented. Existing contracts remain authoritative
for their current runtime paths until later convergence PRs complete profile-by-profile migration.
