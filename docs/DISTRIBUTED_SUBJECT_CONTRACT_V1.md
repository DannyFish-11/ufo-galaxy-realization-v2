# Distributed Subject Contract v1

> **Applies to:** `DannyFish-11/ufo-galaxy-realization-v2` (V2) and
> `DannyFish-11/ufo-galaxy-android` (Android)
>
> **Nature:** Contract baseline freeze.  Not a theoretical protocol layer.
> Based on real existing handlers, wire types, and lifecycle paths.  Provides
> a stable cross-repo contract foundation for future Android subject evolution,
> multi-subject coordination, and operator/control closure.
>
> **Primary module:** `contracts/distributed_subject_contract_v1.py`
>
> **Participant lifecycle module:** `contracts/participant_lifecycle_schema.py`
>
> **Regression tests:** `tests/test_task3_distributed_subject_contract_v1.py`

---

## 1. Architectural Position

This contract is built on the following established system definition (see
`docs/SYSTEM_FORMAL_DEFINITION_V1.md`):

> V2 is the canonical governance / truth convergence / dispatch arbitration /
> closure authority center.  Android is a **bounded relative subject runtime**:
> it has local lifecycle, local AI consumption, local execution judgment, and
> local visible surfaces, but it does not hold global truth finalization or
> global dispatch authority.

The distributed subject contract v1 **does not** change this relationship.
It formalises the wire-level and semantic-level contract that governs the
interaction between V2 and Android (and any future bounded subjects).

---

## 2. Lifecycle Labels

Every field in the contract carries one of the following lifecycle labels:

| Label | Meaning |
|---|---|
| `canonical` | Stable, authoritative, enforced by V2 governance.  Consumers MUST respect it. |
| `compat` | Backward-compatible.  Maintained but NOT the primary path for new consumers. |
| `transitional` | In active migration.  Prefer canonical alternative where available. |
| `experimental` | New; not yet proven; may change without deprecation. |
| `deprecated` | Superseded; callers must migrate before next contract version. |
| `evidence_only` | Valid local subject evidence.  Must NOT be treated as canonical truth. |

> **Policy**: A field's presence does NOT imply the capability is mature.
> Always check the label to determine maturity.

---

## 3. Contract Dimensions

The v1 contract covers ten dimensions, each grounded in real V2 and Android code:

### 3.1 Subject Identity

| Field | Label | V2 Anchor | Android Anchor |
|---|---|---|---|
| `device_id` | `canonical` | `core/android_participant_truth_ingress.py` | `GalaxyConnectionService.kt` |
| `runtime_attachment_session_id` | `canonical` | `core/attached_runtime_session_registry.py` | `GalaxyConnectionService.kt` |
| `participant_id` | `canonical` | `core/android_participant_truth_ingress.py` | `AutonomousExecutionPipeline.kt` |

### 3.2 Runtime Attachment

| Field | Label | Notes |
|---|---|---|
| `attach` | `canonical` | Initial attach; failed attach must not be silently promoted |
| `device_reconnect` | `canonical` | continuity_resume or new_attachment classification |
| `runtime_attachment_session_id_absent_fallback` | `compat` | Old Android clients without session ID; do not use in new implementations |

### 3.3 Continuity

| Field | Label | Notes |
|---|---|---|
| `continuity_class` | `canonical` | V2-classified: online / resumed / handoff / replay / parallel_subtask / none |
| `local_continuity_handling` | `evidence_only` | Android OfflineTaskQueue; does NOT imply cross-device legality |
| `cross_device_continuity_legality` | `canonical` | Issued exclusively by V2 `UnifiedContinuityLegalityAuthority` |

### 3.4 Participant Truth

| Field | Label | Notes |
|---|---|---|
| `android_participant_truth_message` | `canonical` | Must flow through `core/android_participant_truth_ingress.py` |
| `android_reported_mode` | `evidence_only` | V2 classifies and may override Android self-report |
| `participant_truth_uplink_required` | `canonical` | Bypassing the ingress path is prohibited |

### 3.5 Execution Result

| Field | Label | Notes |
|---|---|---|
| `execution_result_uplink` | `canonical` | Via `unified_runtime_truth_ingress` or `unified_result_ingress` |
| `local_execution_result` | `evidence_only` | Does not constitute canonical closure |
| `canonical_closure` | `canonical` | V2 canonical truth chain only; Android may not self-declare closure |

### 3.6 Handoff / Takeover

| Field | Label | Notes |
|---|---|---|
| `handoff_envelope` | `canonical` | `HandoffEnvelopeV2`; formal cross-device handoff record |
| `local_takeover_result` | `canonical` | `LocalTakeoverResult`; target device takeover confirmation |
| `takeover_candidate_signal` | `transitional` | Will be superseded by participant lifecycle state machine |

### 3.7 Recovery / Replay

| Field | Label | Notes |
|---|---|---|
| `dispatch_continuity_context` | `canonical` | `DispatchContinuityContext`; durable recovery record |
| `execution_interruption_record` | `canonical` | recoverable vs. terminal classification |
| `offline_task_queue` | `evidence_only` | Android local queuing; not canonical replay eligibility |

### 3.8 Diagnostics

| Field | Label | Notes |
|---|---|---|
| `local_visible_diagnostics` | `evidence_only` | Android-local only; not promoted without explicit uplink |
| `participant_diagnostics_uplink` | `transitional` | Format and ingress path not yet fully formalised |
| `operator_visible_diagnostics` | `canonical` | Read-only projection via `core/operator_surface.py` |

### 3.9 Readiness / Posture / Capability / Busy

| Field | Label | Notes |
|---|---|---|
| `capability_truth` | `canonical` | Missing / stale / conflicting = deny condition |
| `android_semantics_contract_state` | `canonical` | complete / partial / missing / malformed / unknown / downgraded / stale / conflicting |
| `busy_signal` | `evidence_only` | Cross-checked with execution lifecycle truth binding |
| `posture_contract` | `canonical` | V2-authoritative `SourcePostureContract` |

### 3.10 Participant Lifecycle

| Field | Label | Notes |
|---|---|---|
| `participant_lifecycle_state` | `canonical` | See `ParticipantLifecycleState` enum |
| `participant_role` | `canonical` | primary / assistant / fallback / suspended / takeover_candidate / degraded |

---

## 4. Participant Lifecycle State Machine

### Roles

| Role | Meaning |
|---|---|
| `primary` | Primary executor; anchors the cognitive session |
| `assistant` | Supplementary executor |
| `fallback` | Pre-registered degraded-completion alternative |
| `suspended` | Explicitly suspended from active execution |
| `takeover_candidate` | Pre-qualified by V2 for takeover |
| `degraded` | Active but in reduced execution model |

### States

```
unregistered
  │ attach_success
  ▼
attaching
  │ attach_success
  ▼
attached ◄──── reconnect_succeeded ──── detached ◄── transport_disconnected
  │ dispatch_issued                        │
  ▼                                        │ recovery_initiated
dispatched                                 ▼
  │ execution_started                  recovering
  ▼                                        │ recovery_completed
executing ──► degraded_state               │
  │ execution_completed                    ▼
  ▼                                      attached
waiting_result
  │ result_accepted_by_center
  ▼
result_accepted
  │ task_closure
  ▼
terminal
```

Key additional transitions:
- `attached → suspended_state` (suspension_ordered)
- `attached → takeover_candidate_state` (takeover_candidate_nominated)
- `takeover_candidate_state → taking_over` (takeover_initiated)
- `taking_over → executing` (takeover_completed)
- `recovering → terminal` (terminal_loss)

### Truth and Closure Implications

Every state transition has explicit truth and closure implications defined in
`contracts/participant_lifecycle_schema.py:PARTICIPANT_STATE_TRANSITIONS`.
Key invariants:

1. **Dispatch eligibility** is only valid in `attached` state.
2. **Canonical closure** is only eligible after `result_accepted`.
3. **Recovery** requires a valid `DispatchContinuityContext`.
4. **Terminal loss** triggers rescheduling or terminal task closure.

---

## 5. Key Policies

### Center Authority Policy
V2 canonical governance is the sole authority for participant lifecycle state
transitions.  Android may signal readiness/posture/busy/capability, but it
cannot unilaterally self-transition lifecycle state.

### Evidence Policy
Evidence supplied by a bounded relative subject is classified as
`evidence_only` until V2 canonical governance accepts and promotes it.
Missing, stale, conflicting, or otherwise degraded evidence must not be
treated as positive canonical truth.

### Uplink Required Policy
Android participant truth MUST be uplinked via `android_participant_truth_ingress.py`.
Bypassing this ingress path is prohibited.

### Label Required Policy
Every field carries an explicit lifecycle label.  A field's presence does not
imply capability maturity.

---

## 6. Cross-Repo Alignment

This contract is designed to be alignable with the Android-side implementation.
Android code anchors for each dimension are documented in
`contracts/distributed_subject_contract_v1.py:SubjectContractField.android_anchor`.

Android-side modules that must remain consistent with this contract:
- `GalaxyConnectionService.kt` — subject identity, attachment, reconnect
- `GalaxyWebSocketClient.kt` — transport reconnect
- `RuntimeController.kt` — lifecycle signalling
- `AutonomousExecutionPipeline.kt` — execution result uplink
- `AndroidContinuityIntegration.kt` — continuity handling
- `OfflineTaskQueue.kt` — local offline queuing (evidence_only)
- `LocalExecutionModeGate.kt` — mode gate (evidence_only)

---

## 7. Constraint Tests

The following regression tests enforce this contract:

```
python -m pytest tests/test_task3_distributed_subject_contract_v1.py -q
```

Tests cover:
- All ten contract dimensions are present in the field registry
- All lifecycle labels are used
- Participant lifecycle state machine transitions are consistent
- `build_contract_manifest()` round-trips through JSON
- `build_lifecycle_schema_manifest()` round-trips through JSON
- `contracts/__init__.py` re-exports all public symbols
- `ParticipantRecord.apply_transition()` enforces allowed transitions only
