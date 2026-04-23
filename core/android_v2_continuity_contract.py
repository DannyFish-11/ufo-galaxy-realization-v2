#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/android_v2_continuity_contract.py
========================================
PR-L — Android-V2 Joint Continuity Verification Suite.

Problem addressed
-----------------
Android durable participant continuity depends on coordination with V2
recovery, truth, and continuity semantics.  Local Android persistence alone
is not sufficient, and V2-side recovery alone is not sufficient, if the
combined system still behaves ambiguously under reconnect, re-attach,
duplicate entry, stale identity, or in-flight task recovery scenarios.

This module establishes the **joint Android-V2 participant continuity
contract**: the explicit, machine-checkable set of policies and verification
helpers that define how Android attach, reconnect, and re-attach-after-process-
recreation semantics interact with V2 recovery, truth, and continuity
expectations.

Scope
-----
This module covers the following scenario classes:

1. **Android attach** — initial registration, runtime_attachment_session_id
   assignment, and V2 session registry entry creation.
2. **Android reconnect** — transport-layer reconnect after transient
   disconnect; continuity_resume vs new_attachment classification.
3. **Android re-attach after process recreation** — Android process was killed
   and restarted; the prior runtime_attachment_session_id is presented again;
   V2 must classify correctly and not create a duplicate participant entry.
4. **V2 restart with in-flight tasks** — V2 restarts while a task is delegated
   to Android; Android may re-attach and present a result; V2 must accept the
   result against a recovered task record rather than creating a phantom entry.
5. **Stale participant identity** — Android presents an identity (session_id,
   contract_id) that V2 no longer holds an active record for; V2 must reject
   non-destructively without altering canonical state.
6. **Duplicate re-entry suppression** — Android sends duplicate signals for the
   same execution context; V2 must suppress without double-applying.
7. **Partial result continuity** — Android delivers a partial result and later
   a completion; V2 must preserve the partial result until the completion
   supersedes it.

Authority boundary
------------------
Android is the **durable participant runtime** — it runs delegated tasks and
reports truth about execution on the device.  It is NOT the canonical
orchestration authority.  V2 remains the single canonical orchestration
authority (UDM, CanonicalTask, CanonicalSessionTruthRuntime, session registry).

This module explicitly documents and enforces this boundary in machine-
checkable form.

Design
------
- **Additive only** — does not modify any existing module.
- **Policy-sentinel-first** — every boundary and rule is expressed as a
  named, importable, non-empty string constant so CI, tests, and diagnostic
  endpoints can assert it.
- **Verification helpers** — lightweight functions that classify outcomes
  for the seven scenario classes above, suitable for use in integration tests
  and operator diagnostics.
- **Fully serialisable** — all dataclasses produce stable round-trippable
  JSON via ``to_dict()`` / ``to_json()``.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`ANDROID_V2_CONTINUITY_CONTRACT_AUTHORITY`
:data:`ANDROID_V2_CONTINUITY_CONTRACT_PRL_SENTINEL`
:data:`ANDROID_IS_DURABLE_PARTICIPANT_NOT_ORCHESTRATION_AUTHORITY_POLICY`
:data:`V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY`
:data:`ATTACH_MUST_CREATE_REGISTRY_ENTRY_POLICY`
:data:`RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_POLICY`
:data:`REATTACH_AFTER_PROCESS_RECREATION_MUST_NOT_DUPLICATE_PARTICIPANT_POLICY`
:data:`V2_RESTART_RECOVERY_MUST_ACCEPT_ANDROID_RESULT_AGAINST_RECOVERED_TASK_POLICY`
:data:`STALE_IDENTITY_MUST_BE_REJECTED_NON_DESTRUCTIVELY_POLICY`
:data:`DUPLICATE_SIGNAL_MUST_BE_SUPPRESSED_POLICY`
:data:`PARTIAL_RESULT_MUST_BE_PRESERVED_UNTIL_COMPLETION_POLICY`

Enums
~~~~~
:class:`AndroidAttachOutcome`
:class:`ContinuityScenario`
:class:`ContinuityVerificationResult`

Data classes
~~~~~~~~~~~~
:class:`AndroidAttachRecord`
:class:`ContinuityScenarioOutcome`
:class:`JointContinuityContractSnapshot`

Functions
~~~~~~~~~
:func:`classify_attach_outcome`
:func:`classify_reconnect_continuity_outcome`
:func:`classify_reattach_process_recreation_outcome`
:func:`verify_stale_identity_handling`
:func:`verify_duplicate_signal_suppression`
:func:`build_joint_continuity_contract_snapshot`
:func:`get_joint_continuity_contract_snapshot`
:func:`is_android_v2_continuity_healthy`
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

ANDROID_V2_CONTINUITY_CONTRACT_AUTHORITY: str = (
    "ANDROID_V2_CONTINUITY_CONTRACT_AUTHORITY::core.android_v2_continuity_contract "
    "is the canonical authority for the joint Android-V2 participant continuity "
    "contract.  It defines policy, verification helpers, and the authority boundary "
    "between the Android durable participant runtime and the V2 canonical "
    "orchestration authority.  PR-L."
)

ANDROID_V2_CONTINUITY_CONTRACT_PRL_SENTINEL: str = (
    "ANDROID_V2_CONTINUITY_CONTRACT_PRL::android-v2-joint-continuity-verification-suite::"
    "PR-L::package=L::post-533-dual-repo-runtime-unification::"
    "android-durable-participant-v2-canonical-orchestration-authority"
)

# ---------------------------------------------------------------------------
# Authority boundary policy sentinels
# ---------------------------------------------------------------------------

ANDROID_IS_DURABLE_PARTICIPANT_NOT_ORCHESTRATION_AUTHORITY_POLICY: str = (
    "POLICY::ANDROID_IS_DURABLE_PARTICIPANT_NOT_ORCHESTRATION_AUTHORITY_PR-L: "
    "Android is the durable participant runtime for delegated task execution.  "
    "It MUST NOT be treated as the canonical orchestration authority.  It does not "
    "own V2 session truth, task truth, or device truth outside of the execution "
    "scope of tasks explicitly delegated to it.  Android truth enters V2 via the "
    "android_participant_truth_ingress reconciliation path and is subject to V2 "
    "authority rules.  PR-L."
)

V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY: str = (
    "POLICY::V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_PR-L: "
    "V2 (UnifiedDeviceManager, CanonicalTask, CanonicalSessionTruthRuntime, and "
    "the AttachedSessionRegistry) is the single canonical orchestration authority. "
    "All session truth, task truth, and device truth transitions are owned by V2 "
    "and remain authoritative even when Android reports conflicting local state. "
    "Android signals are reconciled into V2 canonical state via the ingress path; "
    "they never override V2 terminal state.  PR-L."
)

# ---------------------------------------------------------------------------
# Attach policy sentinels
# ---------------------------------------------------------------------------

ATTACH_MUST_CREATE_REGISTRY_ENTRY_POLICY: str = (
    "POLICY::ATTACH_MUST_CREATE_REGISTRY_ENTRY_PR-L: "
    "Every Android attach (initial registration) MUST create an entry in the "
    "AttachedSessionRegistry with a stable runtime_attachment_session_id.  "
    "The registry entry is the authoritative V2-side record that dispatch, reuse, "
    "and reconciliation layers consult.  An attach that does not result in a "
    "registry entry is incomplete and MUST be treated as failed.  PR-L."
)

ATTACH_ASSIGNS_CANONICAL_ATTACHMENT_ID_POLICY: str = (
    "POLICY::ATTACH_ASSIGNS_CANONICAL_ATTACHMENT_ID_PR-L: "
    "The runtime_attachment_session_id assigned at attach time is the canonical "
    "stable identity for that Android participant across reconnect, re-attach, and "
    "process-recreation scenarios.  It survives transport-layer session changes. "
    "The V2 registry is authoritative for the stored value; the Android client "
    "MUST present the same value on subsequent reconnects to trigger "
    "continuity_resume classification.  PR-L."
)

# ---------------------------------------------------------------------------
# Reconnect policy sentinels
# ---------------------------------------------------------------------------

RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_POLICY: str = (
    "POLICY::RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_PR-L: "
    "When a reconnect is classified as continuity_resume the "
    "runtime_attachment_session_id MUST be preserved unchanged from the prior "
    "registry entry.  The transport session may change but the attachment identity "
    "remains stable.  reconnect_count MUST be incremented and last_reconnect_at "
    "MUST be updated.  PR-L."
)

RECONNECT_NEW_ATTACHMENT_DOES_NOT_INHERIT_PRIOR_CONTEXT_POLICY: str = (
    "POLICY::RECONNECT_NEW_ATTACHMENT_DOES_NOT_INHERIT_PRIOR_CONTEXT_PR-L: "
    "When a reconnect is classified as new_attachment the prior registry entry "
    "MUST NOT transfer its execution context (in-flight tasks, partial results, "
    "session state) to the new entry.  The new attachment starts with a clean "
    "execution slate.  Any in-flight tasks associated with the prior entry are "
    "handled by V2 recovery semantics independently of the new attachment.  PR-L."
)

# ---------------------------------------------------------------------------
# Re-attach after process recreation policy sentinels
# ---------------------------------------------------------------------------

REATTACH_AFTER_PROCESS_RECREATION_MUST_NOT_DUPLICATE_PARTICIPANT_POLICY: str = (
    "POLICY::REATTACH_AFTER_PROCESS_RECREATION_MUST_NOT_DUPLICATE_PARTICIPANT_PR-L: "
    "When an Android process is recreated and presents the prior "
    "runtime_attachment_session_id, the V2 registry MUST classify this as "
    "continuity_resume (if the entry is active or detached) rather than "
    "new_attachment.  No duplicate participant entry MUST be created.  "
    "The registry's classify_reconnect_outcome() function is the canonical "
    "mechanism for this classification.  PR-L."
)

PROCESS_RECREATION_CONTINUITY_RESUME_REQUIRES_MATCHING_ID_POLICY: str = (
    "POLICY::PROCESS_RECREATION_CONTINUITY_RESUME_REQUIRES_MATCHING_ID_PR-L: "
    "Process-recreation continuity_resume is only granted when the presented "
    "runtime_attachment_session_id matches the stored entry value for the same "
    "device_id.  A process that presents a new or absent ID gets new_attachment "
    "classification, preventing accidental context inheritance from a different "
    "prior session.  PR-L."
)

# ---------------------------------------------------------------------------
# V2 restart recovery with in-flight tasks policy sentinels
# ---------------------------------------------------------------------------

V2_RESTART_RECOVERY_MUST_ACCEPT_ANDROID_RESULT_AGAINST_RECOVERED_TASK_POLICY: str = (
    "POLICY::V2_RESTART_RECOVERY_MUST_ACCEPT_ANDROID_RESULT_AGAINST_RECOVERED_TASK_PR-L: "
    "When V2 restarts and recovers an in-flight task that was delegated to Android, "
    "and Android subsequently re-attaches and delivers a result for that task, "
    "V2 MUST accept the result against the recovered task record rather than "
    "creating a phantom entry.  The task recovery mechanism (runtime restart "
    "recovery / task lifecycle persistence restore) MUST recreate the tracking "
    "context so that signal reconciliation can match the inbound Android result "
    "to the correct V2 task.  PR-L."
)

INFLIGHT_TASK_CONTINUITY_REQUIRES_V2_RECOVERY_COOPERATION_POLICY: str = (
    "POLICY::INFLIGHT_TASK_CONTINUITY_REQUIRES_V2_RECOVERY_COOPERATION_PR-L: "
    "In-flight task continuity across V2 restart is only trustworthy when both "
    "the V2 task recovery mechanism and the Android re-attach path cooperate: "
    "V2 MUST restore the task record; Android MUST re-attach with the correct "
    "runtime_attachment_session_id; and the signal reconciler MUST match "
    "inbound signals to the restored record by contract_id or session_id.  "
    "If either side fails to cooperate the in-flight task is treated as lost "
    "and a new dispatch cycle is required.  PR-L."
)

# ---------------------------------------------------------------------------
# Stale identity policy sentinels
# ---------------------------------------------------------------------------

STALE_IDENTITY_MUST_BE_REJECTED_NON_DESTRUCTIVELY_POLICY: str = (
    "POLICY::STALE_IDENTITY_MUST_BE_REJECTED_NON_DESTRUCTIVELY_PR-L: "
    "When Android presents a session_id or contract_id for which V2 holds no "
    "active record (the record is absent, terminal, replaced, or invalidated), "
    "reconciliation MUST return was_reconciled=False with a descriptive "
    "reject_reason.  V2 canonical state MUST NOT be altered by a stale signal. "
    "No phantom record MUST be created.  PR-L."
)

STALE_ATTACHMENT_ID_PRODUCES_NEW_ATTACHMENT_POLICY: str = (
    "POLICY::STALE_ATTACHMENT_ID_PRODUCES_NEW_ATTACHMENT_PR-L: "
    "When an Android participant presents a runtime_attachment_session_id that "
    "V2 registry holds only in a terminal state (replaced or invalidated), "
    "classify_reconnect_outcome() MUST return new_attachment.  The stale entry "
    "MUST NOT be reactivated.  PR-L."
)

# ---------------------------------------------------------------------------
# Duplicate signal suppression policy sentinels
# ---------------------------------------------------------------------------

DUPLICATE_SIGNAL_MUST_BE_SUPPRESSED_POLICY: str = (
    "POLICY::DUPLICATE_SIGNAL_MUST_BE_SUPPRESSED_PR-L: "
    "Duplicate execution signals from Android (same idempotency_key or "
    "signal_id received more than once) MUST be suppressed before reaching "
    "the V2 signal reconciler.  The in-process signal guard (keyed by "
    "idempotency_key / message_id, bounded LRU window) is the canonical "
    "suppression mechanism.  Duplicate suppression MUST be applied at the "
    "gateway handler layer so that the reconciler state is never double-applied. "
    "PR-L."
)

DUPLICATE_REENTRY_MUST_NOT_CREATE_DUPLICATE_TASK_RECORD_POLICY: str = (
    "POLICY::DUPLICATE_REENTRY_MUST_NOT_CREATE_DUPLICATE_TASK_RECORD_PR-L: "
    "An Android participant that re-enters (re-attaches or reconnects) for an "
    "already-active execution context MUST NOT cause a duplicate task tracking "
    "record to be created.  The registry entry's runtime_session_id is the "
    "canonical identity guard; reconciliation MUST check the registry before "
    "creating any new record.  PR-L."
)

# ---------------------------------------------------------------------------
# Partial result continuity policy sentinels
# ---------------------------------------------------------------------------

PARTIAL_RESULT_MUST_BE_PRESERVED_UNTIL_COMPLETION_POLICY: str = (
    "POLICY::PARTIAL_RESULT_MUST_BE_PRESERVED_UNTIL_COMPLETION_PR-L: "
    "When Android delivers a partial result for a delegated task, V2 MUST "
    "preserve that partial result in the tracking record until a completion "
    "or failure signal supersedes it.  The partial result MUST NOT be "
    "discarded on Android disconnect/reconnect unless V2 explicitly determines "
    "the task has reached a terminal state.  PR-L."
)

PARTIAL_RESULT_IS_SUPERSEDED_BY_TERMINAL_SIGNAL_POLICY: str = (
    "POLICY::PARTIAL_RESULT_IS_SUPERSEDED_BY_TERMINAL_SIGNAL_PR-L: "
    "A partial result is superseded when V2 receives a terminal signal "
    "(result / failure / cancel / timeout) for the same execution context. "
    "Once a terminal signal is accepted the task record is terminal and "
    "no further Android signals can alter it.  The partial result is "
    "considered delivered-and-superseded.  PR-L."
)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AndroidAttachOutcome(str, Enum):
    """Classification of an Android attach or re-attach event."""

    new_registration = "new_registration"
    """Fresh attach — no prior registry entry exists for this device."""

    continuity_resume = "continuity_resume"
    """Re-attach that resumes a prior active or detached session."""

    new_attachment = "new_attachment"
    """Re-attach treated as a fresh attachment (ID mismatch or terminal prior)."""

    failed = "failed"
    """Attach failed — registry could not create an entry."""


class ContinuityScenario(str, Enum):
    """Scenario class for joint Android-V2 continuity verification."""

    attach = "attach"
    reconnect = "reconnect"
    reattach_process_recreation = "reattach_process_recreation"
    v2_restart_inflight_task = "v2_restart_inflight_task"
    stale_identity = "stale_identity"
    duplicate_signal = "duplicate_signal"
    partial_result = "partial_result"


class ContinuityVerificationResult(str, Enum):
    """High-level result of a continuity scenario verification check."""

    pass_ = "pass"
    """The scenario behaved as required by the joint continuity contract."""

    fail = "fail"
    """The scenario violated the joint continuity contract."""

    advisory = "advisory"
    """The scenario produced an advisory outcome — not a hard failure."""

    not_applicable = "not_applicable"
    """The verification check was not applicable in this runtime context."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AndroidAttachRecord:
    """Minimal record of an Android attach or re-attach event for verification."""

    device_id: str
    """V2-side device identifier."""

    runtime_attachment_session_id: str
    """The canonical stable attachment identity assigned or presented."""

    attach_outcome: AndroidAttachOutcome = AndroidAttachOutcome.new_registration
    """How the attach was classified."""

    prior_entry_state: str = ""
    """State of the prior registry entry, if any (active/detached/replaced/invalidated)."""

    registry_entry_created: bool = False
    """True iff a registry entry was created or updated as a result of this attach."""

    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "runtime_attachment_session_id": self.runtime_attachment_session_id,
            "attach_outcome": self.attach_outcome.value,
            "prior_entry_state": self.prior_entry_state,
            "registry_entry_created": self.registry_entry_created,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class ContinuityScenarioOutcome:
    """Result of running a joint continuity verification check for one scenario."""

    scenario: ContinuityScenario
    """The scenario class that was verified."""

    result: ContinuityVerificationResult
    """High-level pass/fail/advisory result."""

    detail: str = ""
    """Human-readable explanation of the outcome."""

    policy_reference: str = ""
    """Name of the policy sentinel that governs this scenario."""

    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario": self.scenario.value,
            "result": self.result.value,
            "detail": self.detail,
            "policy_reference": self.policy_reference,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class JointContinuityContractSnapshot:
    """Snapshot of the Android-V2 joint continuity contract verification state."""

    authority: str = ANDROID_V2_CONTINUITY_CONTRACT_AUTHORITY
    prl_sentinel: str = ANDROID_V2_CONTINUITY_CONTRACT_PRL_SENTINEL

    scenarios_verified: List[ContinuityScenarioOutcome] = field(default_factory=list)

    all_pass: bool = False
    """True iff every verified scenario produced a pass result."""

    fail_count: int = 0
    """Number of scenarios that produced a fail result."""

    advisory_count: int = 0
    """Number of scenarios that produced an advisory result."""

    policy_sentinels: List[str] = field(default_factory=list)
    """All policy sentinels active in this contract snapshot."""

    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "prl_sentinel": self.prl_sentinel,
            "scenarios_verified": [s.to_dict() for s in self.scenarios_verified],
            "all_pass": self.all_pass,
            "fail_count": self.fail_count,
            "advisory_count": self.advisory_count,
            "policy_sentinels": self.policy_sentinels,
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# Verification helpers
# ---------------------------------------------------------------------------


def classify_attach_outcome(
    device_id: str,
    runtime_attachment_session_id: str,
    *,
    prior_entry_state: str = "",
    registry_entry_created: bool = True,
) -> AndroidAttachRecord:
    """Classify an Android attach or re-attach event.

    Parameters
    ----------
    device_id:
        V2-side device identifier.
    runtime_attachment_session_id:
        The runtime_attachment_session_id presented by the Android client.
    prior_entry_state:
        State of the prior registry entry (``""`` if none existed).
    registry_entry_created:
        Whether the registry successfully created or updated an entry.

    Returns
    -------
    AndroidAttachRecord
        Classified attach record.
    """
    if not registry_entry_created:
        outcome = AndroidAttachOutcome.failed
    elif not prior_entry_state:
        outcome = AndroidAttachOutcome.new_registration
    elif prior_entry_state in ("active", "detached"):
        outcome = AndroidAttachOutcome.continuity_resume
    elif prior_entry_state in ("replaced", "invalidated"):
        outcome = AndroidAttachOutcome.new_attachment
    else:
        outcome = AndroidAttachOutcome.new_registration

    return AndroidAttachRecord(
        device_id=device_id,
        runtime_attachment_session_id=runtime_attachment_session_id,
        attach_outcome=outcome,
        prior_entry_state=prior_entry_state,
        registry_entry_created=registry_entry_created,
    )


def classify_reconnect_continuity_outcome(
    reconnect_outcome: str,
    *,
    runtime_attachment_session_id_preserved: bool = True,
    reconnect_count_incremented: bool = True,
) -> ContinuityScenarioOutcome:
    """Verify that a reconnect outcome conforms to the joint continuity contract.

    Parameters
    ----------
    reconnect_outcome:
        The outcome string from ``classify_reconnect_outcome()`` in
        :mod:`core.attached_runtime_session_registry`:
        ``"continuity_resume"`` or ``"new_attachment"``.
    runtime_attachment_session_id_preserved:
        For ``continuity_resume``: True iff the attachment ID was preserved
        through the reconnect.
    reconnect_count_incremented:
        For ``continuity_resume``: True iff reconnect_count was incremented.

    Returns
    -------
    ContinuityScenarioOutcome
    """
    if reconnect_outcome == "continuity_resume":
        if not runtime_attachment_session_id_preserved:
            return ContinuityScenarioOutcome(
                scenario=ContinuityScenario.reconnect,
                result=ContinuityVerificationResult.fail,
                detail=(
                    "continuity_resume classified but "
                    "runtime_attachment_session_id was not preserved"
                ),
                policy_reference="RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_POLICY",
            )
        if not reconnect_count_incremented:
            return ContinuityScenarioOutcome(
                scenario=ContinuityScenario.reconnect,
                result=ContinuityVerificationResult.advisory,
                detail=(
                    "continuity_resume classified but reconnect_count "
                    "was not incremented"
                ),
                policy_reference="RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_POLICY",
            )
        return ContinuityScenarioOutcome(
            scenario=ContinuityScenario.reconnect,
            result=ContinuityVerificationResult.pass_,
            detail="continuity_resume: attachment ID preserved, reconnect_count incremented",
            policy_reference="RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_POLICY",
        )
    elif reconnect_outcome == "new_attachment":
        return ContinuityScenarioOutcome(
            scenario=ContinuityScenario.reconnect,
            result=ContinuityVerificationResult.pass_,
            detail="new_attachment: fresh registration, no prior context inherited",
            policy_reference=(
                "RECONNECT_NEW_ATTACHMENT_DOES_NOT_INHERIT_PRIOR_CONTEXT_POLICY"
            ),
        )
    else:
        return ContinuityScenarioOutcome(
            scenario=ContinuityScenario.reconnect,
            result=ContinuityVerificationResult.fail,
            detail=f"unrecognised reconnect_outcome: {reconnect_outcome!r}",
            policy_reference="RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_POLICY",
        )


def classify_reattach_process_recreation_outcome(
    reconnect_outcome: str,
    *,
    prior_entry_was_active_or_detached: bool,
    attachment_id_matched: bool,
) -> ContinuityScenarioOutcome:
    """Verify a re-attach-after-process-recreation event.

    Parameters
    ----------
    reconnect_outcome:
        Outcome from ``classify_reconnect_outcome()``.
    prior_entry_was_active_or_detached:
        True iff the prior registry entry was active or detached (eligible for
        continuity_resume).
    attachment_id_matched:
        True iff the presented runtime_attachment_session_id matched the stored
        entry value.

    Returns
    -------
    ContinuityScenarioOutcome
    """
    if prior_entry_was_active_or_detached and attachment_id_matched:
        # Contract requires continuity_resume — no duplicate entry
        if reconnect_outcome == "continuity_resume":
            return ContinuityScenarioOutcome(
                scenario=ContinuityScenario.reattach_process_recreation,
                result=ContinuityVerificationResult.pass_,
                detail=(
                    "process-recreation re-attach correctly classified as "
                    "continuity_resume; no duplicate participant entry created"
                ),
                policy_reference=(
                    "REATTACH_AFTER_PROCESS_RECREATION_MUST_NOT_DUPLICATE_PARTICIPANT_POLICY"
                ),
            )
        else:
            return ContinuityScenarioOutcome(
                scenario=ContinuityScenario.reattach_process_recreation,
                result=ContinuityVerificationResult.fail,
                detail=(
                    f"process-recreation re-attach with matching ID should be "
                    f"continuity_resume but got {reconnect_outcome!r}"
                ),
                policy_reference=(
                    "REATTACH_AFTER_PROCESS_RECREATION_MUST_NOT_DUPLICATE_PARTICIPANT_POLICY"
                ),
            )
    else:
        # No match — new_attachment is expected
        if reconnect_outcome == "new_attachment":
            return ContinuityScenarioOutcome(
                scenario=ContinuityScenario.reattach_process_recreation,
                result=ContinuityVerificationResult.pass_,
                detail=(
                    "process-recreation re-attach with absent/mismatched ID "
                    "correctly classified as new_attachment"
                ),
                policy_reference=(
                    "PROCESS_RECREATION_CONTINUITY_RESUME_REQUIRES_MATCHING_ID_POLICY"
                ),
            )
        else:
            return ContinuityScenarioOutcome(
                scenario=ContinuityScenario.reattach_process_recreation,
                result=ContinuityVerificationResult.advisory,
                detail=(
                    f"process-recreation re-attach without matching ID produced "
                    f"{reconnect_outcome!r} (expected new_attachment)"
                ),
                policy_reference=(
                    "PROCESS_RECREATION_CONTINUITY_RESUME_REQUIRES_MATCHING_ID_POLICY"
                ),
            )


def verify_stale_identity_handling(
    was_reconciled: bool,
    reject_reason: str,
    v2_state_altered: bool,
    phantom_record_created: bool,
) -> ContinuityScenarioOutcome:
    """Verify that a stale-identity signal was handled non-destructively.

    Parameters
    ----------
    was_reconciled:
        From the reconciliation outcome — MUST be False for stale signals.
    reject_reason:
        Non-empty string from the reconciliation outcome.
    v2_state_altered:
        True iff V2 canonical state was altered as a side-effect (MUST be False).
    phantom_record_created:
        True iff a phantom tracking record was created (MUST be False).

    Returns
    -------
    ContinuityScenarioOutcome
    """
    if was_reconciled:
        return ContinuityScenarioOutcome(
            scenario=ContinuityScenario.stale_identity,
            result=ContinuityVerificationResult.fail,
            detail="stale identity signal was_reconciled=True (should be False)",
            policy_reference="STALE_IDENTITY_MUST_BE_REJECTED_NON_DESTRUCTIVELY_POLICY",
        )
    if v2_state_altered:
        return ContinuityScenarioOutcome(
            scenario=ContinuityScenario.stale_identity,
            result=ContinuityVerificationResult.fail,
            detail="stale identity signal altered V2 canonical state",
            policy_reference="STALE_IDENTITY_MUST_BE_REJECTED_NON_DESTRUCTIVELY_POLICY",
        )
    if phantom_record_created:
        return ContinuityScenarioOutcome(
            scenario=ContinuityScenario.stale_identity,
            result=ContinuityVerificationResult.fail,
            detail="stale identity signal created a phantom tracking record",
            policy_reference="STALE_IDENTITY_MUST_BE_REJECTED_NON_DESTRUCTIVELY_POLICY",
        )
    if not reject_reason:
        return ContinuityScenarioOutcome(
            scenario=ContinuityScenario.stale_identity,
            result=ContinuityVerificationResult.advisory,
            detail="stale identity rejected non-destructively but reject_reason is empty",
            policy_reference="STALE_IDENTITY_MUST_BE_REJECTED_NON_DESTRUCTIVELY_POLICY",
        )
    return ContinuityScenarioOutcome(
        scenario=ContinuityScenario.stale_identity,
        result=ContinuityVerificationResult.pass_,
        detail=f"stale identity rejected non-destructively; reject_reason={reject_reason!r}",
        policy_reference="STALE_IDENTITY_MUST_BE_REJECTED_NON_DESTRUCTIVELY_POLICY",
    )


def verify_duplicate_signal_suppression(
    signal_suppressed: bool,
    reconciler_called_count: int,
) -> ContinuityScenarioOutcome:
    """Verify that a duplicate Android signal was suppressed before reconciliation.

    Parameters
    ----------
    signal_suppressed:
        True iff the in-process signal guard suppressed the duplicate.
    reconciler_called_count:
        Number of times the reconciler was called for the duplicated signal
        (MUST be ≤ 1 if suppression is correct).

    Returns
    -------
    ContinuityScenarioOutcome
    """
    if not signal_suppressed:
        return ContinuityScenarioOutcome(
            scenario=ContinuityScenario.duplicate_signal,
            result=ContinuityVerificationResult.fail,
            detail="duplicate signal was not suppressed by the signal guard",
            policy_reference="DUPLICATE_SIGNAL_MUST_BE_SUPPRESSED_POLICY",
        )
    if reconciler_called_count > 1:
        return ContinuityScenarioOutcome(
            scenario=ContinuityScenario.duplicate_signal,
            result=ContinuityVerificationResult.fail,
            detail=(
                f"reconciler was called {reconciler_called_count} times "
                f"for a duplicate signal (should be ≤ 1)"
            ),
            policy_reference="DUPLICATE_SIGNAL_MUST_BE_SUPPRESSED_POLICY",
        )
    return ContinuityScenarioOutcome(
        scenario=ContinuityScenario.duplicate_signal,
        result=ContinuityVerificationResult.pass_,
        detail=(
            f"duplicate signal suppressed; reconciler_called_count={reconciler_called_count}"
        ),
        policy_reference="DUPLICATE_SIGNAL_MUST_BE_SUPPRESSED_POLICY",
    )


# ---------------------------------------------------------------------------
# Contract snapshot
# ---------------------------------------------------------------------------

_CONTRACT_POLICY_SENTINELS: List[str] = [
    "ANDROID_IS_DURABLE_PARTICIPANT_NOT_ORCHESTRATION_AUTHORITY_POLICY",
    "V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY",
    "ATTACH_MUST_CREATE_REGISTRY_ENTRY_POLICY",
    "ATTACH_ASSIGNS_CANONICAL_ATTACHMENT_ID_POLICY",
    "RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_POLICY",
    "RECONNECT_NEW_ATTACHMENT_DOES_NOT_INHERIT_PRIOR_CONTEXT_POLICY",
    "REATTACH_AFTER_PROCESS_RECREATION_MUST_NOT_DUPLICATE_PARTICIPANT_POLICY",
    "PROCESS_RECREATION_CONTINUITY_RESUME_REQUIRES_MATCHING_ID_POLICY",
    "V2_RESTART_RECOVERY_MUST_ACCEPT_ANDROID_RESULT_AGAINST_RECOVERED_TASK_POLICY",
    "INFLIGHT_TASK_CONTINUITY_REQUIRES_V2_RECOVERY_COOPERATION_POLICY",
    "STALE_IDENTITY_MUST_BE_REJECTED_NON_DESTRUCTIVELY_POLICY",
    "STALE_ATTACHMENT_ID_PRODUCES_NEW_ATTACHMENT_POLICY",
    "DUPLICATE_SIGNAL_MUST_BE_SUPPRESSED_POLICY",
    "DUPLICATE_REENTRY_MUST_NOT_CREATE_DUPLICATE_TASK_RECORD_POLICY",
    "PARTIAL_RESULT_MUST_BE_PRESERVED_UNTIL_COMPLETION_POLICY",
    "PARTIAL_RESULT_IS_SUPERSEDED_BY_TERMINAL_SIGNAL_POLICY",
]


def build_joint_continuity_contract_snapshot(
    scenarios: Optional[List[ContinuityScenarioOutcome]] = None,
) -> JointContinuityContractSnapshot:
    """Build a snapshot of the joint continuity contract verification state.

    Parameters
    ----------
    scenarios:
        Optional list of already-verified scenario outcomes to include in the
        snapshot.  If omitted the snapshot is built with an empty scenario list
        (useful for importing the contract without running verification).

    Returns
    -------
    JointContinuityContractSnapshot
    """
    verified = scenarios or []
    fail_count = sum(
        1 for s in verified if s.result == ContinuityVerificationResult.fail
    )
    advisory_count = sum(
        1 for s in verified if s.result == ContinuityVerificationResult.advisory
    )
    all_pass = fail_count == 0 and all(
        s.result in (
            ContinuityVerificationResult.pass_,
            ContinuityVerificationResult.advisory,
            ContinuityVerificationResult.not_applicable,
        )
        for s in verified
    )
    return JointContinuityContractSnapshot(
        scenarios_verified=verified,
        all_pass=all_pass,
        fail_count=fail_count,
        advisory_count=advisory_count,
        policy_sentinels=list(_CONTRACT_POLICY_SENTINELS),
    )


def get_joint_continuity_contract_snapshot() -> JointContinuityContractSnapshot:
    """Return the default joint continuity contract snapshot (no scenarios run).

    This is useful for importing the contract at startup and asserting the
    presence of policy sentinels without running live verification.
    """
    return build_joint_continuity_contract_snapshot()


def is_android_v2_continuity_healthy(
    snapshot: Optional[JointContinuityContractSnapshot] = None,
) -> bool:
    """Return True iff the joint continuity contract snapshot has no failures.

    Parameters
    ----------
    snapshot:
        Optional pre-built snapshot.  If omitted a fresh snapshot is built
        (which has no scenarios, so it always returns True — useful as a
        smoke-test that the module is importable).
    """
    if snapshot is None:
        snapshot = get_joint_continuity_contract_snapshot()
    return snapshot.fail_count == 0
