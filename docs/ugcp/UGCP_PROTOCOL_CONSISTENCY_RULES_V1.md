# UGCP Protocol Consistency Rules v1

> **Introduced**: PR-4 (Define canonical cross-repository protocol consistency rules)
>
> **Module authority**: `core.cross_repo_protocol_consistency`
>
> Related documents:
> - `CROSS_REPO_HOMOMORPHIC_MAPPING_V1.md` — cross-repository homomorphic mapping baseline
> - `UGCP_SESSION_AXIS_V1.md` — session axis model (PR-3)
> - `UGCP_CANONICAL_VOCABULARY_V1.md` — canonical vocabulary freeze
> - `UGCP_TRUTH_EVENT_MODEL_V1.md` — truth/event backbone
> - `UGCP_CONFORMANCE_SURFACES_V1.md` — conformance surface classifications

---

## 1) Purpose

This document defines the **canonical consistency rules** for the most load-bearing
shared protocol surfaces between `DannyFish-11/ufo-galaxy-realization-v2` (center)
and `DannyFish-11/ufo-galaxy-android` (android).

The goal is not to remove all compatibility immediately, but to **stop uncontrolled
drift** on the most important shared protocol surfaces and make convergence reviewable.

Specifically, this document and its associated module (`core.cross_repo_protocol_consistency`)
provide:

1. An explicit classification of critical cross-repository protocol surfaces.
2. A clear distinction between canonical (drift-protected) and transitional (bounded
   compat) surfaces.
3. A reviewable consistency baseline for shared protocol semantics.
4. A foundation suitable for later validation or CI-based consistency checks.

---

## 2) Classification model

### Surface classes

| Symbol | Class | Meaning |
|---|---|---|
| `C` | canonical | Stable, explicitly agreed vocabulary across both repositories. Changes require a coordinated dual-repository update. |
| `T` | transitional | Bounded compatibility allowance. Android-side or center-side name/value differs but is explicitly normalised at ingress. Must carry a retirement pathway. |
| `D` | deprecated | Marked for retirement. New code must not consume or produce it. |
| `U` | unresolved | Known inconsistency not yet resolved. Explicitly catalogued to make drift visible. |

### Consistency categories

| Category | Description |
|---|---|
| `shared_vocabulary` | Shared UGCP schema/enum vocabulary (types, field names, enum values) |
| `terminal_state` | Terminal lifecycle state vocabulary across all shared protocol surfaces |
| `session_identifier` | Session and runtime identifier consistency (see also PR-3) |
| `delegated_execution` | Delegated execution lifecycle status and result semantics |
| `runtime_profile` | Runtime profile and capability descriptor fields |
| `truth_event` | Truth-event payload structure and canonical event type vocabulary |
| `compatibility_alias` | Explicit alias normalisation allowances (Android→center field renames) |

---

## 3) Core governance policies

### 3.1 Canonical surfaces are drift-protected

> **POLICY::CANONICAL_SURFACES_ARE_DRIFT_PROTECTED**
>
> Surfaces classified as 'canonical' represent the authoritative cross-repository
> contract. Their vocabulary (enum values, field names, payload structure) must not
> change without a coordinated dual-repository update and an explicit consistency-rule
> revision. Unilateral changes to canonical surfaces constitute protocol drift and
> are prohibited.

**Authority**: `CANONICAL_SURFACES_ARE_DRIFT_PROTECTED_POLICY` in
`core.cross_repo_protocol_consistency`

### 3.2 Transitional surfaces must not expand

> **POLICY::TRANSITIONAL_SURFACES_MUST_NOT_EXPAND**
>
> Surfaces classified as 'transitional' are explicitly bounded compatibility allowances.
> Their scope must not be extended and no new transitional allowances may be introduced
> without explicit PR-level justification. Each transitional allowance must carry a
> retirement pathway.

**Authority**: `TRANSITIONAL_SURFACES_MUST_NOT_EXPAND_POLICY` in
`core.cross_repo_protocol_consistency`

### 3.3 Terminal state set is closed

> **POLICY::TERMINAL_STATE_SET_IS_CLOSED**
>
> The canonical terminal state vocabulary (`completed`, `failed`, `partial`,
> `cancelled`, `timed_out`) is the closed set for all shared protocol surfaces.
> No new terminal state values may be introduced on cross-repository surfaces
> without a coordinated dual-repository update that revises this catalogue.

**Authority**: `TERMINAL_STATE_SET_IS_CLOSED_POLICY` in
`core.cross_repo_protocol_consistency`

### 3.4 Center is delegated execution authority

> **POLICY::DELEGATED_EXECUTION_STATUS_IS_CENTER_AUTHORITY**
>
> The center repository is the authoritative resolver for delegated execution
> lifecycle status. Android-side execution signals are evidence inputs that are
> normalised into canonical `DelegatedExecutionPhase` values at center ingress.
> Android must not act as an independent execution lifecycle authority.

**Authority**: `DELEGATED_EXECUTION_STATUS_IS_CENTER_AUTHORITY_POLICY` in
`core.cross_repo_protocol_consistency`

### 3.5 Truth-event type vocabulary is frozen

> **POLICY::TRUTH_EVENT_TYPE_VOCABULARY_IS_FROZEN**
>
> The `CanonicalTruthEventType` vocabulary in `core.ugcp_truth_event_model` is
> frozen. New truth-event types must not be introduced without explicit PR-level
> review and addition to the truth-event surface catalogue.

**Authority**: `TRUTH_EVENT_TYPE_VOCABULARY_IS_FROZEN_POLICY` in
`core.cross_repo_protocol_consistency`

---

## 4) Canonical terminal state vocabulary

The closed set of cross-repository terminal state values:

| Canonical value | Present in `shared_schema` | Present in `DelegatedExecutionPhase` | Present in `HandoffContractStatus` | Notes |
|---|---|---|---|---|
| `completed` | ✓ | ✓ | — | Consistent across schema and phase. HandoffContract uses `dispatched` for contract-lifecycle reasons. |
| `failed` | ✓ | ✓ | — | Consistent across schema and phase. HandoffContract uses `expired` for contract failure. |
| `partial` | ✓ | — | — | Shared schema and result-merge layer only. Delegated execution surfaces partial results through `completed` phase with `success=False`. |
| `cancelled` | — | ✓ | ✓ | **Known inconsistency**: present in execution phase and contract status but not in `shared_schema._VALID_TERMINAL_STATES`. Should be added. |
| `timed_out` | — | ✓ | — | **Known inconsistency**: present in execution phase but not in shared schema. Result-merge layer uses `timeout` (variant). Should be added to shared schema. |

### Legacy value

| Value | Status | Notes |
|---|---|---|
| `interrupted` | `D` (deprecated) | Present in `shared_schema._VALID_TERMINAL_STATES` but not in `DelegatedExecutionPhase`. Legacy value; migrate to `failed` or `cancelled`. |

---

## 5) Delegated execution lifecycle

### 5.1 Phase lifecycle model

```
pending_ack → acknowledged → in_progress → [completed | failed | timed_out | cancelled]
```

| Phase | Terminal | Android signal | Notes |
|---|---|---|---|
| `pending_ack` | — | — | Dispatched; no Android signal yet |
| `acknowledged` | — | `ack` | Android confirmed receipt |
| `in_progress` | — | `progress` / `partial_result` | Execution underway |
| `completed` | ✓ | `final_result` | Successful completion |
| `failed` | ✓ | `error` | Error or host-detected failure |
| `timed_out` | ✓ | `timeout` | No ack/progress within window |
| `cancelled` | ✓ | `cancelled` | Explicitly cancelled |

**Center authority**: `core.delegated_runtime_execution_tracker.DelegatedExecutionPhase`

### 5.2 Handoff contract lifecycle

The `HandoffContractStatus` governs the **contract** lifecycle, which is distinct
from the execution phase:

```
draft → sealed → dispatched (terminal)
                 expired (terminal)
                 cancelled (terminal)
```

**Center authority**: `core.delegated_runtime_handoff_contract.HandoffContractStatus`

---

## 6) Session identifier consistency rules

Session identifier consistency rules are fully defined in PR-3.  This document
references them for completeness.

| Center canonical field | Android variants | Class | Authority |
|---|---|---|---|
| `conversation_session_id` | `session_id` (conv context) | `C` | `core.canonical_session_axis` |
| `control_session_id` | `session_id` (Android primary) | `C` | `core.canonical_session_axis` |
| `runtime_attachment_session_id` | `runtime_session_id`, `attached_session_id` | `C` + `T` aliases | `core.canonical_session_axis` |
| `delegation_transfer_session_id` | `transfer_session_id`, `handoff_session_id` | `C` + `T` aliases | `core.canonical_session_axis` |
| `mesh_session_id` | `mesh_session_id` | `≡` | `core.canonical_session_axis` |

**See**: `UGCP_SESSION_AXIS_V1.md` for full details.

---

## 7) Runtime profile and capability descriptor fields

### Canonical capability fields

| Field | Class | Description |
|---|---|---|
| `capabilities` | `C` | List of capability name strings declared by the device |
| `capability_flags` | `C` | Optional bitmask encoding capabilities (Android-bridge convention) |
| `supported_actions` | `C` | List of discrete action verbs the device can execute |
| `source_runtime_posture` | `C` | Runtime execution posture identifier |
| `coordination_role` | `T` | Canonical center name; Android uses same conceptual vocabulary, not yet unified at enum level |

**Center authority**:
- `contracts.registered_runtime_device.RuntimeCapabilityProfile`
- `core.canonical_capability_scheduling_basis.RuntimeCapabilityProfile`

### Capability posture policy

Android-side capability reports must use the canonical field names listed above.
Undocumented extra fields are tolerated but must not replace canonical fields.

**Authority**: `CAPABILITY_DESCRIPTOR_FIELDS_ARE_CANONICAL_POLICY` in
`core.cross_repo_protocol_consistency`

---

## 8) Truth-event payload structures

### 8.1 Canonical base fields

All truth events must carry these base fields from `core.schemas.ugcp.shared.TruthEvent`:

| Field | Required | Notes |
|---|---|---|
| `event_type` | ✓ | Must be a `CanonicalTruthEventType` value |
| `trace_id` | — | Optional correlation identifier |
| `task_id` | — | Optional task correlation |
| `control_session_id` | — | Optional control-plane session anchor |
| `runtime_session_id` | — | Optional runtime attachment session anchor |
| `payload` | — | Profile-specific payload dict |

### 8.2 Canonical truth-event types

| Event type | Android-visible | Required payload fields |
|---|---|---|
| `ugcp.truth.session.recorded.v1` | — | `event_type`, `trace_id`, `task_id` |
| `ugcp.truth.session.snapshot.v1` | — | `event_type` |
| `ugcp.task.lifecycle.transition.v1` | ✓ | `event_type`, `task_id` |
| `ugcp.runtime.lifecycle.transition.v1` | ✓ | `event_type` |
| `ugcp.control_transfer.transition.v1` | ✓ | `event_type`, `profile`, `family`, `current_state` |
| `ugcp.coordination.transition.v1` | ✓ | `event_type` |

**Vocabulary is frozen**. See `TRUTH_EVENT_TYPE_VOCABULARY_IS_FROZEN_POLICY`.

---

## 9) Explicit transitional compatibility allowances

The following table lists all currently permitted compatibility allowances.
Each must carry a retirement condition.  No new allowances may be introduced
without PR-level justification.

| Allowance ID | Kind | Android value | Center canonical value | Retirement condition |
|---|---|---|---|---|
| `session_id_to_control_session_id` | field_rename | `session_id` | `control_session_id` | Android adopts explicit `control_session_id` |
| `runtime_session_id_alias` | field_rename | `runtime_session_id` | `runtime_attachment_session_id` | Android adopts explicit `runtime_attachment_session_id` |
| `attached_session_id_alias` | field_rename | `attached_session_id` | `runtime_attachment_session_id` | Android adopts explicit `runtime_attachment_session_id` |
| `transfer_session_id_alias` | field_rename | `transfer_session_id` | `delegation_transfer_session_id` | Android adopts explicit `delegation_transfer_session_id` |
| `handoff_session_id_alias` | field_rename | `handoff_session_id` | `delegation_transfer_session_id` | Android adopts explicit `delegation_transfer_session_id` |
| `device_status_message_alias` | field_rename | `device_status` | `heartbeat` | Android migrates to canonical `heartbeat` message type |
| `agent_status_message_alias` | field_rename | `agent_status` | `heartbeat` | Android migrates to canonical `heartbeat` message type |
| `timeout_to_timed_out` | enum_variant | `timeout` | `timed_out` | Unify result-merge layer to `timed_out` |
| `coordination_role_semantic_approximation` | semantic_approximation | Android participant role | `core.schemas.ugcp.shared.CoordinationRole` | Full enum-level unification |

---

## 10) Realization-v2 implementation anchor

Canonical module:
- `core/cross_repo_protocol_consistency.py`

Projection alignment sentinel:
- `core.routes.projection.CROSS_REPO_PROTOCOL_CONSISTENCY_ALIGNED_PR4`

Test suite:
- `tests/test_pr4_cross_repo_protocol_consistency.py`

---

## 11) Consistency invariants

The following invariants are verifiable from `build_protocol_consistency_snapshot()`:

1. **No unresolved surfaces**: all protocol surfaces are explicitly classified (canonical, transitional, or deprecated).
2. **Transitional surfaces have retirement pathways**: every transitional or deprecated surface carries an explicit retirement condition.
3. **Canonical surfaces are the majority**: canonical surfaces outnumber transitional + deprecated surfaces combined.
4. **Terminal state set matches**: the `TerminalStateConsistencyRecord` catalogue covers all five `CanonicalTerminalState` values.
5. **Delegated execution phases are complete**: all seven phases are catalogued with terminal status documented.
6. **Truth-event types are versioned**: all canonical truth-event types carry a `.v1` version suffix.
7. **Transitional allowances have retirement conditions**: every allowance records a retirement condition.

These invariants are asserted in `tests/test_pr4_cross_repo_protocol_consistency.py`.
