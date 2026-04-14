# UGCP Coordination Profile v1 (PR-6, realization-v2 side)

## 1) Scope and intent

This profile freezes center-side canonical coordination semantics for:
- mesh session lifecycle state,
- participant roles and authority scopes,
- barrier/aggregation/quorum-style coordination posture where already present,
- participant and overall coordination terminal outcomes,
- mapping of coordination state into truth events and durable snapshots.

This is an **incremental alignment profile**. It does not claim all mesh patterns are fully unified yet.

## 2) Frozen coordination vocabulary

Canonical lifecycle states:
- non-terminal: `pending`, `active`, `awaiting_barrier`, `merging`
- terminal: `completed`, `partial`, `failed`, `cancelled`, `timed_out`
- fallback: `unknown`

Canonical participant roles:
- `primary`, `source`, `support`, `merge_owner`, `fallback`, `relay`, `observer`, `participant`, `unknown`

Canonical authority scopes:
- `mesh_authority`, `execution_authority`, `merge_authority`, `barrier_authority`, `observation_only`, `shared`, `unknown`

Canonical barrier semantics:
- `not_required`, `open`, `waiting`, `released`, `failed`, `unknown`

Canonical aggregation semantics:
- `no_merge`, `sequential`, `parallel`, `barrier`, `owner_decides`, `unknown`

Canonical terminal outcomes:
- `completed`, `partial`, `failed`, `cancelled`, `timed_out`
- coordination-specific: `barrier_failed`, `merge_failed`, `quorum_not_met`, `participant_unavailable`

## 3) Canonical coordination lifecycle graph

High-level progression:

`pending → active → awaiting_barrier/merging → terminal`

Terminal set:

`completed | partial | failed | cancelled | timed_out`

Terminals are absorbing (no outbound transitions).

## 4) Existing-surface alignment under one profile

| Existing surface | Existing status semantics | Canonical coordination lifecycle |
|---|---|---|
| `contracts.mesh_session.MeshSession.status` | `pending/active/merging/completed/cancelled/failed/unknown` | same-name mapping |
| `contracts.mesh_session_coordinator.MeshCoordinatorStatus` | `pending/active/awaiting_barrier/merging/completed/failed/partial/unknown` | same-name mapping |
| Mesh barrier state (`MeshBarrierStatus`) | `not_required/open/waiting/released/failed/unknown` | canonical barrier semantics |
| Mesh merge policy (`MeshMergePolicy`) | `no_merge/sequential/parallel/barrier/owner_decides/unknown` | canonical aggregation semantics |

## 5) Truth + durable-state bridge

Coordination transitions can be represented as canonical truth-chain inputs via:

- `core.ugcp_coordination_profile.build_coordination_truth_event(...)`

Coordination lifecycle/authority snapshots can be persisted as durable read-model payloads via:

- `core.ugcp_coordination_profile.build_coordination_durable_snapshot(...)`

## 6) Realization-v2 implementation anchor

Canonical module:
- `core/ugcp_coordination_profile.py`

Key profile APIs:
- lifecycle/role/authority/barrier/aggregation/outcome enums
- canonical transition table + `can_transition(...)`
- mesh/coordinator mapping helpers
- coordination truth-event builder
- coordination durable snapshot builder
