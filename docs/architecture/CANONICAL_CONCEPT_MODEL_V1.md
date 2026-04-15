# Canonical Concept Model v1 (Cross-Repo Baseline)

This artifact defines a single canonical concept model shared by:

- `dannyfish-11/ufo-galaxy-realization-v2`
- `dannyfish-11/ufo-galaxy-android`

## Canonical concepts

| Concept | Canonical meaning | Compatibility notes |
|---|---|---|
| participant | Real runtime/system execution actor. | Legacy `node_id` may still appear in compatibility contracts. |
| device | Registered endpoint identity and capability carrier. | Device identity is distinct from participant/runtime identity. |
| runtime | Executable host/process attached to a participant/device. | Runtime attachment has its own session semantics. |
| capability | Ability surface reported/derived for readiness and routing. | Capability does not define participant identity. |
| conversation session | Conversation/history continuity context. | Legacy `session_id` is often this in chat/control payloads. |
| runtime attachment session | Attach/reconnect continuity context for runtime truth. | Legacy `runtime_session_id` / `attached_session_id` map here. |
| delegation transfer session | Ownership transfer/handoff lifecycle context. | Legacy transfer/handoff session keys map here. |
| posture | Source runtime participation posture (`control_only`, `join_runtime`). | Input to dispatch/truth gating. |
| coordination role | Participant role in coordination (`controller`, `participant`, `observer`, ...). | Preserved across cross-device routing/merge surfaces. |

## Required disambiguation rules

1. `node` in graph/topology/task-model modules means graph abstraction, not runtime participant.
2. New runtime/control surfaces should prefer `participant` naming for real actors.
3. Bare `session` is non-canonical for new surfaces; pick one explicit session class.
4. Existing flows remain compatible through aliases/mappings; no runtime behavior change is required in this baseline PR.

## Canonical participant model (primary abstraction)

`core.schemas.ugcp.shared.ParticipantModel` is the canonical participant abstraction for
runtime/system actors. It is additive and compatibility-safe, and is designed to sit
above existing node/device/runtime structures while preserving current behavior.

The model explicitly captures:

- participant kind
- runtime tier
- autonomy level
- coordination role
- readiness/participation state
- support surfaces (`local_execution`, `delegation`, `attached_session`)
- linkage surfaces (`device_id`, `capability_refs`)

Low-risk adapters map existing node/device/runtime records into this model:

- `map_from_node_participant_record(...)`
- `map_from_device_participation_summary(...)`
- `map_from_runtime_participant_surface(...)`
