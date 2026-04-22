# Android Participant Truth Reconciliation — Reviewer Guide (PR-4V2)

> **Purpose**: This document answers the four acceptance criteria for the
> "Reconcile Android participant truth into canonical orchestration state"
> PR (PR-4V2), closing gaps TRUTH-005 and CROSS-002.
>
> Primary module: `core/android_participant_truth_ingress.py`
> Gateway handler: `galaxy_gateway/android/handlers/task_lifecycle.py`
> Tests: `tests/test_pr4v2_android_participant_truth_ingress.py`,
>        `tests/test_pr4v2_task_lifecycle_truth_ingress.py`

---

## AC1: How Android participant truth enters V2 canonical orchestration paths

### Ingestion path

```
Android device
  └── AIP message (WebSocket / HTTP)
       └── galaxy_gateway/android/handlers/task_lifecycle.py
            ├── _try_ingest_participant_truth(message, truth_kind)   [PR-4V2]
            │     └── core.android_participant_truth_ingress
            │           .ingest_android_participant_truth_message(message)
            │                ├── extract_participant_truth_envelope(message)
            │                │     → AndroidParticipantTruthEnvelope
            │                └── reconcile_android_participant_truth(envelope)
            │                      → AndroidParticipantReconcileOutcome
            └── _try_reconcile(message)                             [PR-13]
                  └── core.android_execution_signal_reconciler
                        .reconcile_inbound_message(message)
```

**Entry point for gateway handlers**: `ingest_android_participant_truth_message(message)`
(see `core/android_participant_truth_ingress.py`).

All Android truth flows through a **single reconcile path** — no Android truth
may be applied to V2 canonical state through any other mechanism.

### Identity field extraction rules

`extract_participant_truth_envelope()` harvests identity fields from the raw
inbound message according to the `IDENTITY_FIELDS_ARE_VERBATIM_POLICY`:

| Field | Source order |
|-------|-------------|
| `truth_kind` | `message.truth_kind` / `message.signal_kind` / `message.kind` / `message.type` / `message.message_type` / `payload.*` |
| `device_id` | top-level → `payload.device_id` |
| `task_id` | top-level → `payload.task_id` |
| `contract_id` | `payload.contract_id` → top-level |
| `session_id` | `payload.session_id` → top-level |
| `trace_id` | `payload.trace_id` → top-level |

Identity fields are **never synthesised or overwritten** by the ingress path.

### Supported truth kinds

| `truth_kind` value | Meaning |
|--------------------|---------|
| `cancel` | Android-originated explicit cancel for a delegated execution |
| `failure` | Android-originated explicit failure/error report |
| `result` | Android-originated final result (success or failure with payload) |
| `status` | Android-originated task status update (progress) |
| `task_phase` | Android-reported task lifecycle phase |
| `session_snapshot` | Android local session state snapshot |
| `readiness_assessment` | Android per-device readiness assessment |
| `runtime_state` | Android AgentLocalRuntime execution state |
| `unknown` | Unrecognised — advisory/audit-only |

---

## AC2: Whether cancel/status/failure/result from Android affect canonical runtime state

### Policy

> **`CANCEL_FAILURE_RESULT_AFFECT_CANONICAL_STATE_POLICY`**:
> Android-originated cancel, failure, and result signals MUST materially
> update V2 canonical tracking records (via `apply_acknowledgment_signal`)
> and emit to ReplayFoundation. These signals are NOT merely logged or
> forwarded — they change V2 canonical orchestration truth.

### Truth kind → V2 canonical state impact

| truth_kind | V2 canonical state change | `was_reconciled` | `local_only` |
|------------|--------------------------|------------------|--------------|
| `cancel` | tracking record → `cancelled` phase via `AcknowledgmentSignal.cancelled` | `True` | `False` |
| `failure` | tracking record → `failed` phase via `AcknowledgmentSignal.error` | `True` | `False` |
| `result` (success) | tracking record → `completed` phase via `AcknowledgmentSignal.final_result` | `True` | `False` |
| `result` (failure) | tracking record → `failed` phase via `AcknowledgmentSignal.error` | `True` | `False` |
| `status` | tracking record → `in_progress` phase via `AcknowledgmentSignal.progress` | `True` | `False` |
| `task_phase` | tracking record updated via mapped AcknowledgmentSignal | `True` | `False` |
| `session_snapshot` | `AttachedSessionRegistry` continuity validated; no V2-owned field overwritten | `True`/`False` | `False` |
| `readiness_assessment` | advisory only; no tracking record change | `False` | `True` |
| `runtime_state` | audit-only; no tracking record change | `False` | `True` |
| `unknown` | audit-only | `False` | `True` |

All reconciliation attempts (accepted **and** rejected) emit a
`ReplayFoundation` event with `kind="android_participant_truth_reconciled"`.

---

## AC3: Where participant-local truth ends and canonical orchestration truth begins

### Canonical truth (owned by V2)

V2 is the **single canonical orchestration authority**
(`V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY`).

V2-canonical fields are:
- Tracking record phase (`phase`, terminal/non-terminal lifecycle)
- Session identity (`session_id`, `device_id`, `state`) in `AttachedSessionRegistry`
- Dispatch eligibility gates (V2 admissibility chain)
- ReplayFoundation event stream

These are **never overwritten by Android truth** — only `apply_acknowledgment_signal`
may advance a tracking record's phase.

### Android-local truth (participant-owned)

The following remain Android-local and are **advisory only** in V2:

| Android local surface | V2 handling |
|-----------------------|-------------|
| Device readiness assessment | Timestamp recorded in `AndroidParticipantReconcileOutcome`; does not alter V2 admissibility gates |
| `AgentLocalRuntime` execution state | Emitted to `ReplayFoundation` for audit; no direct canonical state change |
| Raw session snapshot fields beyond `session_id`/`device_id` | Used for continuity validation only; V2-owned fields not overwritten |

### Authority boundary sentinel

```
V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_SENTINEL
  = "V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY::"
    "android-truth-is-advisory-for-device-local-scope-only::"
    "cancel+failure+result-signals-materially-update-v2-canonical-state::"
    "v2-terminal-state-wins-conflict-resolution"
```

---

## AC4: How stale, conflicting, duplicate, or terminal Android signals are handled

### Terminal-state blocking (staleness / conflict)

> **`TERMINAL_V2_STATE_WINS_CONFLICT_POLICY`**:
> When the V2 tracking record is already in a terminal phase
> (`completed` / `failed` / `timed_out` / `cancelled`), any incoming
> Android truth update that would alter the record is **rejected**.
> V2 terminal truth is **immutable** from the Android perspective.

When a terminal record is detected:
- `was_reconciled = False`
- `reject_reason = "terminal_state:already_terminal"`
- A `ReplayFoundation` event is still emitted (audit-complete)

### Non-destructive on miss

> **`RECONCILE_IS_NON_DESTRUCTIVE_ON_MISS_POLICY`**:
> When no matching V2 tracking record or session registry entry is found
> for the given identity keys, reconciliation returns `was_reconciled=False`
> **without creating phantom records or raising exceptions**.

This handles stale or late signals from Android devices whose execution
contracts have already been cleaned up.

### Duplicate signal suppression

The `galaxy_gateway/android/handlers/task_lifecycle.py` handler includes an
in-process **signal guard** (`_signal_guard_accept`):
- Keyed by `idempotency_key` or `message_id`
- 512-slot bounded LRU window
- Duplicate signals are suppressed before reaching the reconciler

### Missing identity key guard

If the incoming message carries neither `contract_id` nor `session_id`,
reconciliation returns `was_reconciled=False` with
`reject_reason="missing_lookup_key"`. No V2 state is changed and a
`ReplayFoundation` event is still emitted.

### Reconciliation outcome fields

| Field | Meaning |
|-------|---------|
| `was_reconciled` | `True` iff at least one V2 canonical record was materially updated |
| `canonical_update` | Human-readable description of what V2 state was updated |
| `local_only` | `True` iff the truth kind is advisory and remains Android-local |
| `reject_reason` | Non-empty when reconciliation was rejected (with reason code) |
| `replay_event_emitted` | `True` iff a `ReplayFoundation` event was emitted |
| `tracking_record_phase` | V2 tracking record phase after reconciliation (empty if no record found) |

---

## Signal flow: end-to-end trace

### cancel signal example

```
Android sends:
  { "type": "task_cancel", "task_id": "T1",
    "payload": { "contract_id": "C1", "session_id": "S1" } }

gateway_handler._try_ingest_participant_truth(msg, truth_kind="cancel")
  → ingest_android_participant_truth_message(msg)
    → extract_participant_truth_envelope(msg)
         truth_kind=cancel, contract_id="C1", session_id="S1"
    → reconcile_android_participant_truth(envelope)
         1. Emit early audit event to ReplayFoundation
         2. Resolve tracking record by contract_id="C1"
         3. Check record phase: not terminal → proceed
         4. apply_acknowledgment_signal(record, AcknowledgmentSignal.cancelled)
            → tracking record phase = cancelled
         5. Emit terminal ReplayFoundation event
         6. Return AndroidParticipantReconcileOutcome(
              was_reconciled=True,
              canonical_update="cancel applied: tracking record phase → cancelled",
              tracking_record_phase="cancelled"
            )
```

### readiness_assessment signal example

```
Android sends:
  { "type": "readiness_assessment", "device_id": "D1",
    "payload": { "ready": true } }

gateway_handler._try_ingest_participant_truth(msg, truth_kind="readiness_assessment")
  → reconcile_android_participant_truth(envelope)
         kind = readiness_assessment → local_only = True
         Emit audit event to ReplayFoundation
         Return AndroidParticipantReconcileOutcome(
           was_reconciled=False,
           local_only=True,
           canonical_update=""
         )
```

---

## Module inventory

| File | Purpose |
|------|---------|
| `core/android_participant_truth_ingress.py` | **Primary**: envelope extraction, reconciliation entry-point, all policy sentinels |
| `galaxy_gateway/android/handlers/task_lifecycle.py` | Gateway integration: calls `_try_ingest_participant_truth()` for each inbound Android lifecycle message |
| `core/runtime/__init__.py` | Re-exports all PR-4V2 public symbols for consumers |
| `tests/test_pr4v2_android_participant_truth_ingress.py` | 76+ tests covering all acceptance criteria (Groups A–T) |
| `tests/test_pr4v2_task_lifecycle_truth_ingress.py` | 24 tests covering gateway handler integration |
| `docs/TRUTH_PROJECTION_CONVERGENCE_MAP.md` | Architecture-level documentation of TRUTH-005 resolution |
| `docs/DUAL_REPO_GAP_MATRIX.md` | Gap registry: TRUTH-005 and CROSS-002 closed |

---

## Policy sentinel index

All reconciliation authority decisions are stated as string sentinels in
`core/android_participant_truth_ingress.py`. The twelve sentinels are:

| Sentinel | Key guarantee |
|----------|---------------|
| `V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY` | V2 is the single canonical orchestration authority |
| `ANDROID_TRUTH_IS_ADVISORY_FOR_DEVICE_SCOPE_POLICY` | Android local truth is advisory for device-local scope only |
| `CANCEL_FAILURE_RESULT_AFFECT_CANONICAL_STATE_POLICY` | cancel/failure/result materially update V2 canonical state |
| `STATUS_SIGNAL_EMITS_PROGRESS_EVENT_POLICY` | status truth advances tracking record to in_progress |
| `TASK_PHASE_RECONCILED_WITH_TRACKING_RECORD_POLICY` | task_phase is reconciled with the V2 tracking record |
| `SESSION_SNAPSHOT_VALIDATES_REGISTRY_CONTINUITY_POLICY` | session_snapshot validates continuity; does not override V2-owned fields |
| `READINESS_ASSESSMENT_IS_ADVISORY_POLICY` | readiness assessment is advisory; does not change V2 dispatch eligibility |
| `RUNTIME_STATE_IS_AUDIT_ONLY_POLICY` | runtime_state is audit-only; no direct canonical state change |
| `TERMINAL_V2_STATE_WINS_CONFLICT_POLICY` | V2 terminal state wins all conflicts; Android updates rejected |
| `RECONCILE_IS_NON_DESTRUCTIVE_ON_MISS_POLICY` | Missing record → was_reconciled=False, no phantom records |
| `RECONCILE_EMITS_AUDIT_EVENT_ALWAYS_POLICY` | All reconciliations (accepted AND rejected) emit ReplayFoundation events |
| `IDENTITY_FIELDS_ARE_VERBATIM_POLICY` | Identity fields extracted verbatim; never synthesised |
