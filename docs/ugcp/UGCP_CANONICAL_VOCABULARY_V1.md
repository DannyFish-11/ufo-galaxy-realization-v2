# UGCP Canonical Vocabulary v1

## 1) Identity and session taxonomy freeze

| Canonical term | Definition | Status in realization-v2 | Current grounding / mapping |
|---|---|---|---|
| `task_id` | Stable task work-unit identity | active | `core/schemas/task_envelope.py` |
| `trace_id` | End-to-end causal trace identity | active | `TaskEnvelope`, delegated ingress, runtime/session contracts |
| `control_session_id` | Control-plane continuity session identity | mapped | Canonical name frozen; currently mapped to existing `session_id` at control ingress/envelopes |
| `runtime_session_id` | Stable runtime-session identity across reconnect/reattach | active | `core/attached_runtime_session_registry.py` |
| `mesh_session_id` | Mesh coordination session identity | active | `contracts/mesh_session.py`, `runtime_session_snapshot.py`, merge contracts |
| `source_node_id` | Source node identity for graph/edge/control relations | active | topology/task graph runtimes |
| `target_node_id` | Target node identity for graph/edge/control relations | active | topology/task graph runtimes |
| `execution_instance_id` | Identity of one concrete execution attempt instance | mapped | Canonical name frozen; currently represented by `dispatch_id` / `dispatch_record_id` in dispatch/delegated paths |

### Session hierarchy (canonical)

`trace_id` → `task_id` → `control_session_id` → `runtime_session_id` → `mesh_session_id` (optional)

Interpretation:
- `trace_id`: request/thread lineage.
- `task_id`: concrete work unit.
- `control_session_id`: control continuity context.
- `runtime_session_id`: attached runtime identity authority.
- `mesh_session_id`: multi-participant execution session when present.

## 2) Canonical control/state vocabulary freeze

| Canonical term | Definition | Status in realization-v2 | Current grounding / mapping |
|---|---|---|---|
| `source_runtime_posture` | Source participation posture (`control_only` / `join_runtime`) | active | `contracts/source_posture_contract.py`, handoff/session/merge contracts |
| `coordination_role` | Source role in cross-device coordination | active | handoff/session/merge contracts |
| `dispatch_mode` | Intended dispatch mode | active | `contracts/source_dispatch.py` (`SourceDispatchMode`) |
| `effective_mode` | Actual mode after fallback/degradation | mapped | runtime orchestrator uses `effective_mode` variable and writes resulting `mode` |
| `delegated_signal_kind` | Canonical delegated signal kind | active | `core/android_delegated_signal_ingress.py` (`DelegatedSignalKind`) |
| `terminal_state` | Canonical terminal status label for a lifecycle family | mapped | execution lifecycle terminal set; delegated/handoff/mesh/session statuses |
| `terminal_reason` | Why terminal state was reached | mapped | existing `reason`/error fields in dispatch/handoff/delegated/mesh/recovery paths |
| `readiness_verdict` | Canonical readiness decision for participation/dispatch | mapped | `core/device_readiness.py` summary + `is_ready_for_cross_device(...)` |
| `coordination_outcome` | Canonical final coordination outcome label | mapped | mesh coordinator/session status + merged runtime result/recovery surfaces |

## 3) Truth and authority terminology freeze

- **canonical truth**: truth emitted from canonical authority modules.
- **authority chain**: ordered source precedence from ingress/control decisions to truth compilation and outward projection.
- **projection truth**: read-only compiled view; must not redefine authority decisions.
- **compat truth**: legacy/adapter-only supplemental data; non-authoritative.

Current grounded authority direction:
- `core/canonical_session_truth.py`
- `core/projection/runtime_truth_compiler.py`
- `core/outward_runtime_truth.py`
