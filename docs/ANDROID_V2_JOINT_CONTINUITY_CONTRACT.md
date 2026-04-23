# Android-V2 Joint Continuity Contract — Reviewer Guide (PR-L)

> **Purpose**: This document is the reviewer-usable specification of the
> Android-V2 joint participant continuity contract.  It answers the four
> acceptance criteria for PR-L and provides a single location where a reviewer
> can understand how Android attach, reconnect, and re-attach semantics now
> behave across V2 continuity scenarios.
>
> Primary module: `core/android_v2_continuity_contract.py`
> Tests: `tests/test_prl_android_v2_joint_continuity.py`
> Related modules:
> - `core/attached_runtime_session_registry.py` — registry authority (PR-19/PR-G)
> - `core/android_participant_truth_ingress.py` — truth ingress (PR-4V2)
> - `core/attached_runtime_recovery_readiness.py` — signal guard (PR-15/PR-18)
> - `galaxy_gateway/android/handlers/registration.py` — reconnect consumer (PR-G)
> - `contracts/dispatch_continuity.py` — continuity context contracts (PR-F/PR-G)

---

## AC1: How Android attach, reconnect, and re-attach semantics now behave across V2 continuity scenarios

### Attach (initial registration)

```
Android device
  └── AIP WebSocket message (type: register / attach)
       └── galaxy_gateway/android/handlers/registration.py
            └── handle_device_registration(...)
                 └── core.attached_runtime_session_registry
                       .register_session(device_id, runtime_attachment_session_id=...)
                            → AttachedSessionRegistryEntry (active)
```

**Contract rules for attach** (from `ATTACH_MUST_CREATE_REGISTRY_ENTRY_POLICY`):

- Every Android attach MUST result in a registry entry in the
  `AttachedSessionRegistry`.
- The registry assigns a stable `runtime_attachment_session_id` if the client
  does not supply one (backward compat fallback).
- The client-supplied `runtime_attachment_session_id` is the canonical stable
  identity for that participant across all future reconnects and re-attaches.
- An attach that does not produce a registry entry is treated as failed.

### Reconnect

```
Android device (transport reconnects)
  └── AIP WebSocket message (type: device_reconnect)
       └── galaxy_gateway/android/handlers/registration.py
            └── handle_device_reconnect(...)
                 ├── core.attached_runtime_session_registry
                 │     .classify_reconnect_outcome(device_id,
                 │         runtime_attachment_session_id=presented_id)
                 │          → "continuity_resume" | "new_attachment"
                 │
                 ├── continuity_resume path
                 │     └── .reconnect_session(entry, ...)
                 │           → attachment ID preserved, reconnect_count++
                 │
                 └── new_attachment path
                       └── .register_session(device_id, ...)
                             → fresh entry, no prior context inherited
```

**Classification decision** (`classify_reconnect_outcome()` in
`core/attached_runtime_session_registry.py`):

| Condition | Outcome |
|-----------|---------|
| No prior entry for device | `new_attachment` |
| Prior entry in terminal state (`replaced`/`invalidated`) | `new_attachment` |
| Prior entry active/detached AND `runtime_attachment_session_id` matches | `continuity_resume` |
| Prior entry active/detached AND ID does not match | `new_attachment` |
| Prior entry active/detached AND ID absent (old client) | `continuity_resume` (backward compat) |

**Contract rules for reconnect** (from
`RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_POLICY`):

- On `continuity_resume`, the `runtime_attachment_session_id` MUST be preserved
  unchanged.  Only the transport session changes.
- `reconnect_count` MUST be incremented; `last_reconnect_at` MUST be updated.
- On `new_attachment`, the prior entry's execution context does NOT transfer.
  Any in-flight tasks from the prior session are handled by V2 recovery
  independently.

### Re-attach after process recreation

Process recreation (Android kills/restarts the app) is handled identically to
a reconnect at the V2 protocol layer.  The key difference is that the Android
client must persist the `runtime_attachment_session_id` across process
recreation so it can present it on re-attach.

**Contract rules** (from
`REATTACH_AFTER_PROCESS_RECREATION_MUST_NOT_DUPLICATE_PARTICIPANT_POLICY`):

- When Android presents the prior `runtime_attachment_session_id` and the V2
  registry has an active or detached entry for the same device, the outcome
  MUST be `continuity_resume` — no duplicate participant entry is created.
- If the ID is absent or does not match, `new_attachment` applies and a fresh
  entry is created.
- `classify_reattach_process_recreation_outcome()` in
  `core/android_v2_continuity_contract.py` provides the canonical verification
  function for this scenario.

---

## AC2: How cross-system continuity is validated under restart, interruption, and stale or duplicate re-entry conditions

### V2 restart with in-flight tasks

```
V2 restarts
  └── core/runtime_restart_recovery.py
       └── recover_runtime_state(...)
            └── task_lifecycle_persistence → restore in-flight task records

Android re-attaches
  └── registry: continuity_resume (attachment ID matches)

Android delivers result
  └── galaxy_gateway/android/handlers/task_lifecycle.py
       └── _try_reconcile(message)
            └── core.android_execution_signal_reconciler
                  .reconcile_inbound_message(message)
                       → matches by contract_id / session_id
                       → applies result to recovered task record
```

**Contract rules** (from
`V2_RESTART_RECOVERY_MUST_ACCEPT_ANDROID_RESULT_AGAINST_RECOVERED_TASK_POLICY`):

- V2 MUST restore in-flight task records from `TaskLifecyclePersistenceStore`
  on restart.
- When Android re-attaches and delivers a result, the reconciler MUST match
  the inbound signal to the recovered task by `contract_id` or `session_id`.
- A result that arrives for a recovered task MUST be applied to the recovered
  record, not create a phantom entry.
- If either V2 recovery or Android re-attach fails, the task is considered
  lost and a new dispatch cycle is required
  (`INFLIGHT_TASK_CONTINUITY_REQUIRES_V2_RECOVERY_COOPERATION_POLICY`).

### Stale identity rejection

When Android presents a `session_id` or `contract_id` for which V2 holds no
active record (absent, terminal, replaced, or invalidated):

1. `reconcile_android_participant_truth()` returns
   `was_reconciled=False` with a non-empty `reject_reason`.
2. V2 canonical state is NOT altered.
3. No phantom tracking record is created.
4. A `ReplayFoundation` event is still emitted (audit-only).

**Verification function**: `verify_stale_identity_handling()` in
`core/android_v2_continuity_contract.py` checks all four conditions.

**Policy reference**:
`STALE_IDENTITY_MUST_BE_REJECTED_NON_DESTRUCTIVELY_POLICY`.

### Duplicate signal suppression

Duplicate Android signals (same `idempotency_key` / `message_id`) are
suppressed by the in-process signal guard before reaching the reconciler:

```
Android sends duplicate signal
  └── galaxy_gateway/android/handlers/task_lifecycle.py
       └── _signal_guard_accept(idempotency_key)
            → False (duplicate detected)
            → signal suppressed; reconciler NOT called again
```

**Guard characteristics**:
- Keyed by `idempotency_key` or `message_id`.
- 512-slot bounded LRU window.
- Suppression happens at the gateway handler layer.

**Verification function**: `verify_duplicate_signal_suppression()` in
`core/android_v2_continuity_contract.py`.

**Policy reference**: `DUPLICATE_SIGNAL_MUST_BE_SUPPRESSED_POLICY`.

### Stale attachment ID (terminal entry)

When an Android client presents a `runtime_attachment_session_id` that maps
only to a terminal registry entry (`replaced` or `invalidated`):

- `classify_reconnect_outcome()` returns `new_attachment`.
- The terminal entry is NOT reactivated.
- A fresh registry entry is created.

**Policy reference**: `STALE_ATTACHMENT_ID_PRODUCES_NEW_ATTACHMENT_POLICY`.

---

## AC3: Whether Android-V2 continuity is now documented and testable as a joint contract

### Contract module

`core/android_v2_continuity_contract.py` is the single canonical location for:

1. **16 policy sentinels** — each names an explicit contract rule covering one
   of the seven scenario classes (attach, reconnect, re-attach-after-process-
   recreation, V2-restart-inflight-task, stale-identity, duplicate-signal,
   partial-result).
2. **3 enums** — `AndroidAttachOutcome`, `ContinuityScenario`,
   `ContinuityVerificationResult`.
3. **3 dataclasses** — `AndroidAttachRecord`, `ContinuityScenarioOutcome`,
   `JointContinuityContractSnapshot` — all fully serialisable to JSON.
4. **6 verification helpers** — `classify_attach_outcome()`,
   `classify_reconnect_continuity_outcome()`,
   `classify_reattach_process_recreation_outcome()`,
   `verify_stale_identity_handling()`,
   `verify_duplicate_signal_suppression()`,
   `build_joint_continuity_contract_snapshot()`.
5. **2 convenience functions** — `get_joint_continuity_contract_snapshot()`,
   `is_android_v2_continuity_healthy()`.

### Test coverage

`tests/test_prl_android_v2_joint_continuity.py` contains 72 tests across
52 coverage groups (A through AZ) that verify:

- All sentinels are importable, non-empty, and contain `PR-L`.
- All enums have the correct values.
- All dataclasses have required fields and produce JSON-serialisable dicts.
- Each verification helper produces the correct outcome for each input
  combination (pass / fail / advisory).
- Snapshot aggregation (fail_count, advisory_count, all_pass) is correct.

A reviewer can run:
```bash
pytest tests/test_prl_android_v2_joint_continuity.py -v
```
to verify all 72 checks pass.

### Cross-referencing with companion repo

The Android-side counterpart (`ufo-galaxy-android`) is responsible for:
- Persisting `runtime_attachment_session_id` across process recreation.
- Presenting the persisted ID on every reconnect/re-attach.
- Using stable `contract_id` / `session_id` in all task lifecycle signals.
- Suppressing local duplicate emissions where possible.

The V2-side contract in this module defines what V2 expects from Android and
how V2 will classify each inbound event.  The Android companion implementation
is reviewed against these contract rules.

---

## AC4: Whether durable participant continuity is now materially more trustworthy than before

### Before PR-L

- Android and V2 each had local continuity mechanisms but there was no
  explicit, machine-checkable joint contract.
- A reviewer had to infer cross-system behaviour from two independent
  module docstrings and test suites.
- Edge cases (stale identity, duplicate re-entry, process recreation,
  V2-restart inflight recovery) were not explicitly verified as joint scenarios.

### After PR-L

1. **Explicit authority boundary** — `ANDROID_IS_DURABLE_PARTICIPANT_NOT_ORCHESTRATION_AUTHORITY_POLICY`
   and `V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY` explicitly state the
   boundary in importable, machine-checkable form.

2. **Seven scenario classes explicitly covered** — each has a named policy
   sentinel, a verification helper, and test coverage.

3. **Classification decision is auditable** — `classify_reconnect_outcome()`
   in `AttachedSessionRegistry` is the single canonical classification
   function; `classify_reattach_process_recreation_outcome()` wraps the result
   and checks it against the contract.

4. **Stale and duplicate handling is contract-guarded** — both
   `verify_stale_identity_handling()` and `verify_duplicate_signal_suppression()`
   check the four required invariants explicitly.

5. **Snapshot-based health check** — `get_joint_continuity_contract_snapshot()`
   produces a JSON-serialisable snapshot that CI, operator tooling, or a
   reviewer can assert against.  `is_android_v2_continuity_healthy()` is a
   single-call health gate.

6. **72 passing tests** — verifiable by running the test suite; no manual
   inference required.

---

## Quick-reference: seven scenario classes and their contract rules

| Scenario | Policy sentinel | Verification function |
|----------|-----------------|-----------------------|
| Attach | `ATTACH_MUST_CREATE_REGISTRY_ENTRY_POLICY` | `classify_attach_outcome()` |
| Reconnect | `RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_POLICY` | `classify_reconnect_continuity_outcome()` |
| Re-attach (process recreation) | `REATTACH_AFTER_PROCESS_RECREATION_MUST_NOT_DUPLICATE_PARTICIPANT_POLICY` | `classify_reattach_process_recreation_outcome()` |
| V2 restart + inflight task | `V2_RESTART_RECOVERY_MUST_ACCEPT_ANDROID_RESULT_AGAINST_RECOVERED_TASK_POLICY` | (V2 recovery + reconciler path) |
| Stale identity | `STALE_IDENTITY_MUST_BE_REJECTED_NON_DESTRUCTIVELY_POLICY` | `verify_stale_identity_handling()` |
| Duplicate signal | `DUPLICATE_SIGNAL_MUST_BE_SUPPRESSED_POLICY` | `verify_duplicate_signal_suppression()` |
| Partial result | `PARTIAL_RESULT_MUST_BE_PRESERVED_UNTIL_COMPLETION_POLICY` | (reconciler tracking state) |

---

## Constraints honoured

- Android is NOT redefined as canonical orchestration authority.
  (`ANDROID_IS_DURABLE_PARTICIPANT_NOT_ORCHESTRATION_AUTHORITY_POLICY`)
- Continuity verification is NOT reduced to isolated local persistence checks.
  (cross-system registry + reconciler path + signal guard all contribute)
- No broad redesign — this module is additive only.
- The contract is explicit enough for cross-repo review and maintenance.
  (16 named policy sentinels, 6 verification helpers, 72 tests, this guide)
