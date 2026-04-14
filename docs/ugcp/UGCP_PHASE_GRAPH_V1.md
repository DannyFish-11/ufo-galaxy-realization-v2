# UGCP Canonical Phase Graph v1

## 1) Canonical phases (frozen)

`ingress → planning → assignment → execution → transfer → completion → recovery`

Notes:
- `transfer` covers remote handoff, takeover adoption, delegated signal relay, and mesh barrier/merge-transfer points.
- `recovery` is entered for timeout/failure/partial/interrupted paths and reconciliation cycles.

## 2) Existing lifecycle-family mapping (realization-v2)

| Existing family | Existing states (examples) | Canonical phase mapping |
|---|---|---|
| Task envelope lifecycle | `created`, `running`, `done/failed` | `created→ingress`, `running→execution`, `done/failed→completion` (or `recovery` on failure workflows) |
| Execution lifecycle | `created/planned/queued/selected/dispatching/waiting_remote/running/...` | `created→ingress`, `planned→planning`, `queued/selected→assignment`, `dispatching/waiting_remote→transfer`, `running→execution`, terminal states→`completion` or `recovery` |
| Source dispatch mode flow | `local/remote_handoff/staged_mesh/blocked/fallback_local` | decision point spans `assignment`; remote/staged transitions pass through `transfer`; `fallback_local/blocked` generally map to `recovery` branches |
| Delegated pre-handoff intent | `not_started/preparing/ready/dispatched/cancelled/failed` | `not_started→ingress`, `preparing→planning`, `ready→assignment`, `dispatched→transfer`, `cancelled/failed→recovery` |
| Delegated handoff contract | `draft/sealed/dispatched/expired/cancelled` | `draft→planning`, `sealed→assignment`, `dispatched→transfer`, `expired/cancelled→recovery` |
| Delegated signal lifecycle | `ack/progress/result/timeout/cancelled` | `ack→transfer`, `progress→execution`, `result→completion`, `timeout/cancelled→recovery` |
| Mesh session/coordinator | `pending/active/awaiting_barrier/merging/completed/failed/partial...` | `pending→assignment`, `active→execution`, `awaiting_barrier/merging→transfer`, `completed→completion`, `failed/partial→recovery` |
| Runtime session snapshot | `active/completed/failed/partial/interrupted/recovering` | `active→execution`, `completed→completion`, `failed/partial/interrupted/recovering→recovery` |

## 3) Phase graph usage rule

Lifecycle families may keep domain-specific states, but every state transition should be projectable to the canonical phase graph above for cross-repo control-plane consistency.
