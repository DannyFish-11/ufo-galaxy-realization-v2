"""core/v2_android_recovery_continuity_hardening.py
====================================================
PR-7A (sequence 11) V2-side — Close Continuity, Reconnect, and Recovery
Loops Against Real Android Behavior
==========================================================================

Background
----------
The V2 center-recovery and continuity layer has accumulated recovery
infrastructure across multiple modules:

- Attached runtime session registry (``core.attached_runtime_session_registry``)
- Flow continuity coordinator (``core.flow_continuity_coordinator``)
- Android-V2 continuity contract (``core.android_v2_continuity_contract``)
- Recovery truth surface (``core.recovery_truth_surface``)
- Offline replay ordering contract (``core.offline_replay_ordering_contract``)
- Recovery durability closure validator (``core.recovery_durability_closure_validator``)

These surfaces covered fundamental protocol semantics but were exercised
primarily against mock Android protocol assumptions rather than against the
behavioral constraints imposed by a real Android runtime participant:

- Session reuse classification assumed fixed, well-formed ``runtime_attachment_session_id``
  fields, with no hardening for absent, malformed, or epoch-mismatched values.
- Attached runtime handling did not explicitly surface whether the attached
  runtime was genuinely observed (Android-confirmed) or locally inferred.
- Evidence ingress did not classify whether incoming recovery evidence was
  real-Android-originated, replayed-from-queue, or locally synthesised.
- Recovery closure assessment treated recovery as binary (ok / failed) with
  no quality grading for partial or degraded recoveries.
- Duplicate result handling was tested against well-behaved mock sequences, not
  against realistic out-of-order, replayed, or re-delivered Android results.
- Offline replay interpretation did not expose which replay sequences are
  canonical-convergence-eligible versus which expose truth gaps.

Purpose
-------
This module provides the **V2-side continuity, reconnect, and recovery
hardening layer** for PR-7A (sequence 11).  It does NOT introduce new storage
or duplicate any existing authority.  Instead it:

1. Defines explicit **session reuse hardening** policies covering real Android
   reconnect behaviors: absent attachment ID, epoch mismatch, durable ID
   conflict, and process-recreation identity ambiguity.

2. Classifies **attached runtime handling truth** — whether the attached runtime
   is android_confirmed, locally_inferred, or unverifiable — so callers can
   grade confidence before delegating work.

3. Provides **evidence ingress quality classification** for incoming recovery
   evidence: real_android_originated, replay_queue_drained, locally_synthesised,
   or unknown_provenance.

4. Exposes **recovery closure quality assessment** that grades recovery outcomes
   as full_convergence, partial_convergence, degraded_recovery, or no_recovery,
   and surfaces the diagnosis so truth gaps become diagnosable.

5. Provides **duplicate result detection** helpers that classify whether an
   inbound Android result is a first_delivery, confirmed_duplicate,
   out_of_order_replay, or stale_result relative to a recorded task context.

6. Interprets **offline replay sequences** against real Android behavioral
   constraints and classifies each sequence item as convergence_eligible,
   gap_exposed, stale_dropped, or duplicate_suppressed.

7. Assembles a **RecoveryParticipationReport** that summarises all six
   dimensions for a given device/session so dual-repo reconnect/recovery
   flows can be audited at any point.

Design invariants
-----------------
I-R1  Session reuse MUST NOT silently accept absent or malformed
      ``runtime_attachment_session_id`` values as a continuity-resume signal;
      absent or malformed IDs MUST produce ``new_attachment`` classification
      with explicit reason.

I-R2  Attached runtime truth MUST be graded before execution is delegated;
      an unverifiable or locally_inferred attached runtime degrades delegation
      confidence rather than being optimistically treated as android_confirmed.

I-R3  Recovery evidence ingress MUST carry explicit provenance; unknown_provenance
      evidence MUST be classified as degraded and MUST NOT be treated as full
      Android-confirmed truth.

I-R4  Recovery closure quality MUST be a graded outcome; ``partial_convergence``
      and ``degraded_recovery`` are valid end-states that must be surfaced in
      diagnostics, not collapsed into binary success/failure.

I-R5  Duplicate result detection MUST run before any state mutation; a
      ``confirmed_duplicate`` MUST be suppressed without altering canonical state.

I-R6  Offline replay sequences MUST be interpreted using session epoch and
      sequence position; items that arrive outside the expected window MUST be
      classified as ``stale_dropped`` or ``gap_exposed`` rather than silently
      accepted.

I-R7  Cross-device isolation: recovery hardening state for device A MUST NOT
      influence device B outcomes.

Authority sentinel
------------------
``V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_SENTINEL`` — import this constant to
assert that the PR-7A (sequence 11) hardening layer is present.

Public API
----------
Sentinels / version::

    V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_SENTINEL
    V2_ANDROID_RECOVERY_CONTINUITY_CONTRACT_VERSION
    SESSION_REUSE_MUST_REJECT_ABSENT_ATTACHMENT_ID_POLICY
    SESSION_REUSE_MUST_REJECT_EPOCH_MISMATCH_POLICY
    ATTACHED_RUNTIME_TRUTH_MUST_BE_GRADED_BEFORE_DELEGATION_POLICY
    EVIDENCE_INGRESS_MUST_CARRY_EXPLICIT_PROVENANCE_POLICY
    RECOVERY_CLOSURE_QUALITY_MUST_BE_GRADED_POLICY
    DUPLICATE_RESULT_MUST_BE_SUPPRESSED_BEFORE_STATE_MUTATION_POLICY
    OFFLINE_REPLAY_MUST_RESPECT_SESSION_EPOCH_AND_SEQUENCE_POLICY

Enums::

    SessionReuseOutcome
    AttachedRuntimeTruth
    EvidenceIngressProvenance
    RecoveryClosureQuality
    ResultDeliveryClassification
    ReplayItemClassification

Dataclasses::

    SessionReuseAssessment
    AttachedRuntimeTruthAssessment
    EvidenceIngressAssessment
    RecoveryClosureAssessment
    ResultDeliveryAssessment
    ReplaySequenceItemAssessment
    RecoveryParticipationReport

Functions::

    classify_session_reuse
    assess_attached_runtime_truth
    classify_evidence_ingress
    assess_recovery_closure_quality
    classify_result_delivery
    interpret_replay_sequence
    build_recovery_participation_report
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("Galaxy.V2AndroidRecoveryContinuityHardening")

# ---------------------------------------------------------------------------
# Authority sentinel & contract version
# ---------------------------------------------------------------------------

V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_SENTINEL: str = (
    "V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_SENTINEL::PR7A_SEQ11_V2::present "
    "core.v2_android_recovery_continuity_hardening is the canonical center-side "
    "continuity, reconnect, and recovery hardening layer (PR-7A sequence 11, V2 "
    "side). It closes session reuse, attached runtime handling, evidence ingress, "
    "recovery closure, duplicate result handling, and offline replay interpretation "
    "against real Android behavior rather than mock-only protocol assumptions. "
    "All dual-repo reconnect/recovery regression tests MUST reference this sentinel "
    "to confirm PR-7A hardening is in effect."
)

V2_ANDROID_RECOVERY_CONTINUITY_CONTRACT_VERSION: str = "7a.seq11.0.0"

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

SESSION_REUSE_MUST_REJECT_ABSENT_ATTACHMENT_ID_POLICY: str = (
    "POLICY::SESSION_REUSE_ABSENT_ATTACHMENT_ID_PR7A_SEQ11: "
    "A reconnect or re-attach that presents an absent, empty, or None "
    "runtime_attachment_session_id MUST be classified as new_attachment, not "
    "continuity_resume. Absent ID is not evidence of continuity; it is a "
    "signal that the Android process lost its session identity. The classifier "
    "MUST surface this as an explicit new_attachment_absent_id reason so the "
    "recovery diagnosis chain can identify truth gaps."
)

SESSION_REUSE_MUST_REJECT_EPOCH_MISMATCH_POLICY: str = (
    "POLICY::SESSION_REUSE_EPOCH_MISMATCH_PR7A_SEQ11: "
    "When the presented continuity_epoch does not match the stored epoch for a "
    "device_id the reconnect MUST be classified as new_attachment_epoch_mismatch "
    "regardless of whether the runtime_attachment_session_id matches. Epoch "
    "mismatch indicates that the Android process has undergone a non-transparent "
    "restart that breaks session continuity. This is a real Android behavior that "
    "mock-only tests cannot expose."
)

SESSION_REUSE_MUST_REJECT_DURABLE_ID_CONFLICT_POLICY: str = (
    "POLICY::SESSION_REUSE_DURABLE_ID_CONFLICT_PR7A_SEQ11: "
    "When the presented durable_session_id conflicts with the stored entry for a "
    "device_id (both are non-None and different) the reconnect MUST be classified "
    "as new_attachment_durable_conflict. A durable ID conflict indicates two "
    "independent Android runtime instances are presenting claims for the same "
    "device_id, which is a truth gap requiring operator diagnosis."
)

ATTACHED_RUNTIME_TRUTH_MUST_BE_GRADED_BEFORE_DELEGATION_POLICY: str = (
    "POLICY::ATTACHED_RUNTIME_TRUTH_GRADING_PR7A_SEQ11: "
    "Before delegating execution to an attached Android runtime, V2 MUST grade "
    "the attached runtime truth as android_confirmed, locally_inferred, or "
    "unverifiable. An unverifiable or locally_inferred runtime MUST degrade "
    "delegation confidence and surface a diagnosis reason. This policy closes the "
    "gap where mock-only tests assumed a well-connected runtime without testing "
    "the truth quality of the attachment itself."
)

EVIDENCE_INGRESS_MUST_CARRY_EXPLICIT_PROVENANCE_POLICY: str = (
    "POLICY::EVIDENCE_INGRESS_PROVENANCE_PR7A_SEQ11: "
    "Recovery evidence entering V2 via any ingress path MUST carry an explicit "
    "provenance classification: real_android_originated, replay_queue_drained, "
    "locally_synthesised, or unknown_provenance. Evidence with unknown_provenance "
    "MUST be treated as degraded and MUST NOT be elevated to full Android-confirmed "
    "truth without explicit promotion by the reconciliation authority."
)

RECOVERY_CLOSURE_QUALITY_MUST_BE_GRADED_POLICY: str = (
    "POLICY::RECOVERY_CLOSURE_QUALITY_GRADING_PR7A_SEQ11: "
    "Recovery closure MUST be expressed as a graded outcome: full_convergence, "
    "partial_convergence, degraded_recovery, or no_recovery. Binary success/failure "
    "treatment of recovery is prohibited. partial_convergence and degraded_recovery "
    "are valid canonical end-states that MUST appear in diagnostics and MUST be "
    "regression-protected so truth gaps become observable and diagnosable."
)

DUPLICATE_RESULT_MUST_BE_SUPPRESSED_BEFORE_STATE_MUTATION_POLICY: str = (
    "POLICY::DUPLICATE_RESULT_SUPPRESSION_PR7A_SEQ11: "
    "Duplicate result detection MUST run before any canonical state mutation. "
    "A result classified as confirmed_duplicate or out_of_order_replay MUST be "
    "suppressed without altering task truth, session truth, or canonical state. "
    "This policy applies to both task_result and goal_result handlers and to "
    "Android-originated results delivered after offline queue drain."
)

OFFLINE_REPLAY_MUST_RESPECT_SESSION_EPOCH_AND_SEQUENCE_POLICY: str = (
    "POLICY::OFFLINE_REPLAY_EPOCH_SEQUENCE_PR7A_SEQ11: "
    "Offline replay sequences MUST be interpreted using session epoch and sequence "
    "position. Items arriving outside the expected session epoch MUST be classified "
    "as stale_dropped. Items arriving with a sequence position that implies a gap "
    "relative to the last accepted item MUST be classified as gap_exposed, not "
    "silently accepted. This ensures recovery flows expose truth gaps rather than "
    "silently absorbing replay artefacts."
)

# ---------------------------------------------------------------------------
# SessionReuseOutcome enum
# ---------------------------------------------------------------------------


class SessionReuseOutcome(str, Enum):
    """Outcome of session reuse classification against real Android reconnect behavior.

    Values
    ------
    continuity_resume
        The reconnect presents a matching, epoch-consistent ``runtime_attachment_session_id``
        and optional ``durable_session_id``; the prior session is resumed without
        creating a duplicate registry entry.

    new_attachment_absent_id
        The reconnect presents an absent or empty ``runtime_attachment_session_id``;
        treated as a fresh attachment with explicit truth gap.

    new_attachment_epoch_mismatch
        The reconnect presents a ``continuity_epoch`` that does not match the stored
        epoch for the device; treated as a fresh attachment with an epoch-mismatch
        reason that is diagnosable in recovery flows.

    new_attachment_durable_conflict
        Both presented and stored ``durable_session_id`` are non-None and differ;
        treated as a fresh attachment with a durable conflict reason surfaced for
        operator diagnosis.

    new_attachment_no_prior_entry
        No prior registry entry exists for the device; first-time attach that
        produces a new_attachment without any prior context to inherit.

    new_attachment_id_mismatch
        The presented ``runtime_attachment_session_id`` does not match the stored
        value for the device; continuity_resume cannot be granted.
    """

    continuity_resume = "continuity_resume"
    new_attachment_absent_id = "new_attachment_absent_id"
    new_attachment_epoch_mismatch = "new_attachment_epoch_mismatch"
    new_attachment_durable_conflict = "new_attachment_durable_conflict"
    new_attachment_no_prior_entry = "new_attachment_no_prior_entry"
    new_attachment_id_mismatch = "new_attachment_id_mismatch"


# ---------------------------------------------------------------------------
# AttachedRuntimeTruth enum
# ---------------------------------------------------------------------------


class AttachedRuntimeTruth(str, Enum):
    """Truth grade for an attached Android runtime, evaluated before delegation.

    Values
    ------
    android_confirmed
        The runtime has been confirmed via a fresh, non-stale attach or reconnect
        registry entry with positive heartbeat or lifecycle evidence.

    locally_inferred
        The runtime attachment exists in the registry but has not been confirmed
        by a recent Android-originated signal; the attachment is inferred from
        the prior registration.

    unverifiable
        The runtime attachment status cannot be determined (no registry entry,
        conflicting signals, or stale evidence beyond the staleness window).
    """

    android_confirmed = "android_confirmed"
    locally_inferred = "locally_inferred"
    unverifiable = "unverifiable"


# ---------------------------------------------------------------------------
# EvidenceIngressProvenance enum
# ---------------------------------------------------------------------------


class EvidenceIngressProvenance(str, Enum):
    """Provenance classification for recovery evidence entering V2.

    Values
    ------
    real_android_originated
        Evidence arrived via a live Android participant signal on an active
        WebSocket transport (not from a replay queue or local synthesis).

    replay_queue_drained
        Evidence arrived as part of an offline queue drain after Android
        reconnect; the original signal was queued during a disconnected period.

    locally_synthesised
        Evidence was synthesised locally within V2 (e.g. a timeout-triggered
        inferred completion) without a corresponding Android signal.

    unknown_provenance
        The evidence origin cannot be determined; treated as degraded.
    """

    real_android_originated = "real_android_originated"
    replay_queue_drained = "replay_queue_drained"
    locally_synthesised = "locally_synthesised"
    unknown_provenance = "unknown_provenance"


# ---------------------------------------------------------------------------
# RecoveryClosureQuality enum
# ---------------------------------------------------------------------------


class RecoveryClosureQuality(str, Enum):
    """Graded quality outcome for a recovery closure evaluation.

    Values
    ------
    full_convergence
        Recovery converged to a canonical terminal truth that is consistent
        with all available Android and V2 evidence.

    partial_convergence
        Recovery reached a stable state for some, but not all, in-flight tasks
        or participants. Remaining gaps are surfaced in the diagnosis.

    degraded_recovery
        Recovery reached a stable state but with evidence quality degradations:
        stale evidence accepted, partial results unconfirmed, or truth gaps
        acknowledged but unresolved.

    no_recovery
        Recovery could not produce a stable canonical state; in-flight tasks
        remain unresolved and require operator intervention.
    """

    full_convergence = "full_convergence"
    partial_convergence = "partial_convergence"
    degraded_recovery = "degraded_recovery"
    no_recovery = "no_recovery"


# ---------------------------------------------------------------------------
# ResultDeliveryClassification enum
# ---------------------------------------------------------------------------


class ResultDeliveryClassification(str, Enum):
    """Classification of an inbound Android result relative to the task context.

    Values
    ------
    first_delivery
        The result is the first delivery for this task_id; it MUST be accepted
        and applied to canonical state.

    confirmed_duplicate
        The result has been seen before (same task_id and idempotency key);
        it MUST be suppressed without state mutation.

    out_of_order_replay
        The result arrives for a task_id that already reached a terminal state
        in canonical V2 truth, but via a different (e.g. timeout-triggered)
        path; the arriving result is an out-of-order replay that MUST be suppressed.

    stale_result
        The result timestamp or sequence position is outside the staleness window
        relative to the current canonical state; it MUST be dropped.
    """

    first_delivery = "first_delivery"
    confirmed_duplicate = "confirmed_duplicate"
    out_of_order_replay = "out_of_order_replay"
    stale_result = "stale_result"


# ---------------------------------------------------------------------------
# ReplayItemClassification enum
# ---------------------------------------------------------------------------


class ReplayItemClassification(str, Enum):
    """Classification of a single item in an offline replay sequence.

    Values
    ------
    convergence_eligible
        The item is within the expected session epoch and sequence window;
        it is eligible to be applied and converge canonical state.

    gap_exposed
        The item's sequence position implies a gap relative to the last accepted
        item; applying it would produce a truth gap. The gap is surfaced in
        diagnostics.

    stale_dropped
        The item arrives outside the expected session epoch or beyond the staleness
        window; it MUST be dropped to prevent stale truth from entering canonical
        state.

    duplicate_suppressed
        The item's idempotency key has already been processed; it MUST be
        suppressed.
    """

    convergence_eligible = "convergence_eligible"
    gap_exposed = "gap_exposed"
    stale_dropped = "stale_dropped"
    duplicate_suppressed = "duplicate_suppressed"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SessionReuseAssessment:
    """Result of classifying a session reuse attempt against real Android behavior."""

    device_id: str
    presented_attachment_id: Optional[str]
    stored_attachment_id: Optional[str]
    presented_epoch: Optional[int]
    stored_epoch: Optional[int]
    presented_durable_session_id: Optional[str]
    stored_durable_session_id: Optional[str]
    outcome: SessionReuseOutcome
    diagnosis: str
    policy_reference: str = SESSION_REUSE_MUST_REJECT_ABSENT_ATTACHMENT_ID_POLICY
    assessed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "presented_attachment_id": self.presented_attachment_id,
            "stored_attachment_id": self.stored_attachment_id,
            "presented_epoch": self.presented_epoch,
            "stored_epoch": self.stored_epoch,
            "presented_durable_session_id": self.presented_durable_session_id,
            "stored_durable_session_id": self.stored_durable_session_id,
            "outcome": self.outcome.value,
            "diagnosis": self.diagnosis,
            "policy_reference": self.policy_reference,
            "assessed_at": self.assessed_at,
            "_sentinel": V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_SENTINEL,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


@dataclass
class AttachedRuntimeTruthAssessment:
    """Truth grade for an attached Android runtime before delegation."""

    device_id: str
    runtime_attachment_session_id: Optional[str]
    truth: AttachedRuntimeTruth
    diagnosis: str
    registry_entry_present: bool = False
    last_signal_age_seconds: Optional[float] = None
    policy_reference: str = ATTACHED_RUNTIME_TRUTH_MUST_BE_GRADED_BEFORE_DELEGATION_POLICY
    assessed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "runtime_attachment_session_id": self.runtime_attachment_session_id,
            "truth": self.truth.value,
            "diagnosis": self.diagnosis,
            "registry_entry_present": self.registry_entry_present,
            "last_signal_age_seconds": self.last_signal_age_seconds,
            "policy_reference": self.policy_reference,
            "assessed_at": self.assessed_at,
            "_sentinel": V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_SENTINEL,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


@dataclass
class EvidenceIngressAssessment:
    """Provenance classification for incoming recovery evidence."""

    evidence_id: str
    device_id: str
    provenance: EvidenceIngressProvenance
    is_degraded: bool
    diagnosis: str
    policy_reference: str = EVIDENCE_INGRESS_MUST_CARRY_EXPLICIT_PROVENANCE_POLICY
    assessed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "device_id": self.device_id,
            "provenance": self.provenance.value,
            "is_degraded": self.is_degraded,
            "diagnosis": self.diagnosis,
            "policy_reference": self.policy_reference,
            "assessed_at": self.assessed_at,
            "_sentinel": V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_SENTINEL,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


@dataclass
class RecoveryClosureAssessment:
    """Graded quality assessment of a recovery closure event."""

    device_id: str
    session_id: Optional[str]
    quality: RecoveryClosureQuality
    resolved_task_count: int
    unresolved_task_count: int
    degraded_task_count: int
    diagnosis: str
    gap_descriptions: List[str] = field(default_factory=list)
    policy_reference: str = RECOVERY_CLOSURE_QUALITY_MUST_BE_GRADED_POLICY
    assessed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "session_id": self.session_id,
            "quality": self.quality.value,
            "resolved_task_count": self.resolved_task_count,
            "unresolved_task_count": self.unresolved_task_count,
            "degraded_task_count": self.degraded_task_count,
            "diagnosis": self.diagnosis,
            "gap_descriptions": self.gap_descriptions,
            "policy_reference": self.policy_reference,
            "assessed_at": self.assessed_at,
            "_sentinel": V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_SENTINEL,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


@dataclass
class ResultDeliveryAssessment:
    """Classification of an inbound Android result relative to task truth."""

    task_id: str
    device_id: str
    classification: ResultDeliveryClassification
    idempotency_key: str
    should_suppress: bool
    diagnosis: str
    policy_reference: str = DUPLICATE_RESULT_MUST_BE_SUPPRESSED_BEFORE_STATE_MUTATION_POLICY
    assessed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "device_id": self.device_id,
            "classification": self.classification.value,
            "idempotency_key": self.idempotency_key,
            "should_suppress": self.should_suppress,
            "diagnosis": self.diagnosis,
            "policy_reference": self.policy_reference,
            "assessed_at": self.assessed_at,
            "_sentinel": V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_SENTINEL,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


@dataclass
class ReplaySequenceItemAssessment:
    """Classification of a single item in an offline replay sequence."""

    sequence_index: int
    item_id: str
    session_epoch: Optional[int]
    expected_epoch: Optional[int]
    sequence_position: Optional[int]
    last_accepted_position: Optional[int]
    classification: ReplayItemClassification
    diagnosis: str
    policy_reference: str = OFFLINE_REPLAY_MUST_RESPECT_SESSION_EPOCH_AND_SEQUENCE_POLICY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sequence_index": self.sequence_index,
            "item_id": self.item_id,
            "session_epoch": self.session_epoch,
            "expected_epoch": self.expected_epoch,
            "sequence_position": self.sequence_position,
            "last_accepted_position": self.last_accepted_position,
            "classification": self.classification.value,
            "diagnosis": self.diagnosis,
            "policy_reference": self.policy_reference,
        }


@dataclass
class RecoveryParticipationReport:
    """Full recovery participation report aggregating all six hardening dimensions."""

    device_id: str
    session_id: Optional[str]
    session_reuse: SessionReuseAssessment
    attached_runtime_truth: AttachedRuntimeTruthAssessment
    evidence_ingress: EvidenceIngressAssessment
    recovery_closure: RecoveryClosureAssessment
    replay_items: List[ReplaySequenceItemAssessment]
    overall_recovery_quality: RecoveryClosureQuality
    dual_repo_participation_eligible: bool
    participation_diagnosis: str
    contract_version: str = V2_ANDROID_RECOVERY_CONTINUITY_CONTRACT_VERSION
    built_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "session_id": self.session_id,
            "session_reuse": self.session_reuse.to_dict(),
            "attached_runtime_truth": self.attached_runtime_truth.to_dict(),
            "evidence_ingress": self.evidence_ingress.to_dict(),
            "recovery_closure": self.recovery_closure.to_dict(),
            "replay_items": [r.to_dict() for r in self.replay_items],
            "overall_recovery_quality": self.overall_recovery_quality.value,
            "dual_repo_participation_eligible": self.dual_repo_participation_eligible,
            "participation_diagnosis": self.participation_diagnosis,
            "contract_version": self.contract_version,
            "built_at": self.built_at,
            "_sentinel": V2_ANDROID_RECOVERY_CONTINUITY_HARDENING_SENTINEL,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ---------------------------------------------------------------------------
# classify_session_reuse
# ---------------------------------------------------------------------------

# Staleness window: if the stored epoch differs by more than this many units
# from the presented epoch, classify as epoch_mismatch.
_EPOCH_MISMATCH_THRESHOLD: int = 0  # strict: any difference is a mismatch


def classify_session_reuse(
    *,
    device_id: str,
    presented_attachment_id: Optional[str],
    stored_attachment_id: Optional[str],
    presented_epoch: Optional[int] = None,
    stored_epoch: Optional[int] = None,
    presented_durable_session_id: Optional[str] = None,
    stored_durable_session_id: Optional[str] = None,
) -> SessionReuseAssessment:
    """Classify a session reuse attempt against real Android reconnect behavior.

    Parameters
    ----------
    device_id
        The Android device identifier.
    presented_attachment_id
        The ``runtime_attachment_session_id`` presented by the reconnecting
        Android process.  ``None`` or empty string → new_attachment_absent_id.
    stored_attachment_id
        The ``runtime_attachment_session_id`` held in the V2 registry for
        this device.  ``None`` → no prior entry.
    presented_epoch
        The ``continuity_epoch`` value from the reconnect message.
    stored_epoch
        The ``continuity_epoch`` stored in the registry entry.
    presented_durable_session_id
        The ``durable_session_id`` from the reconnect message.
    stored_durable_session_id
        The ``durable_session_id`` stored in the registry entry.

    Returns
    -------
    SessionReuseAssessment
        Typed, serialisable classification result.
    """
    # --- Absent attachment ID (I-R1) ---
    if not presented_attachment_id:
        return SessionReuseAssessment(
            device_id=device_id,
            presented_attachment_id=presented_attachment_id,
            stored_attachment_id=stored_attachment_id,
            presented_epoch=presented_epoch,
            stored_epoch=stored_epoch,
            presented_durable_session_id=presented_durable_session_id,
            stored_durable_session_id=stored_durable_session_id,
            outcome=SessionReuseOutcome.new_attachment_absent_id,
            diagnosis=(
                "Reconnect presented absent or empty runtime_attachment_session_id; "
                "classified as new_attachment_absent_id per "
                "SESSION_REUSE_MUST_REJECT_ABSENT_ATTACHMENT_ID_POLICY. "
                "This is a real Android behavior exposed by process recreation without "
                "durable identity persistence."
            ),
            policy_reference=SESSION_REUSE_MUST_REJECT_ABSENT_ATTACHMENT_ID_POLICY,
        )

    # --- No prior registry entry ---
    if stored_attachment_id is None:
        return SessionReuseAssessment(
            device_id=device_id,
            presented_attachment_id=presented_attachment_id,
            stored_attachment_id=stored_attachment_id,
            presented_epoch=presented_epoch,
            stored_epoch=stored_epoch,
            presented_durable_session_id=presented_durable_session_id,
            stored_durable_session_id=stored_durable_session_id,
            outcome=SessionReuseOutcome.new_attachment_no_prior_entry,
            diagnosis=(
                "No prior registry entry for device_id; first attach produces "
                "new_attachment_no_prior_entry. No prior context is inherited."
            ),
            policy_reference=SESSION_REUSE_MUST_REJECT_ABSENT_ATTACHMENT_ID_POLICY,
        )

    # --- Epoch mismatch (I-R1, I-R2) ---
    if (
        presented_epoch is not None
        and stored_epoch is not None
        and presented_epoch != stored_epoch
    ):
        return SessionReuseAssessment(
            device_id=device_id,
            presented_attachment_id=presented_attachment_id,
            stored_attachment_id=stored_attachment_id,
            presented_epoch=presented_epoch,
            stored_epoch=stored_epoch,
            presented_durable_session_id=presented_durable_session_id,
            stored_durable_session_id=stored_durable_session_id,
            outcome=SessionReuseOutcome.new_attachment_epoch_mismatch,
            diagnosis=(
                f"continuity_epoch mismatch: presented={presented_epoch!r} "
                f"stored={stored_epoch!r}. Android process has undergone a "
                "non-transparent restart. Classified as new_attachment_epoch_mismatch "
                "per SESSION_REUSE_MUST_REJECT_EPOCH_MISMATCH_POLICY."
            ),
            policy_reference=SESSION_REUSE_MUST_REJECT_EPOCH_MISMATCH_POLICY,
        )

    # --- Durable session ID conflict ---
    if (
        presented_durable_session_id is not None
        and stored_durable_session_id is not None
        and presented_durable_session_id != stored_durable_session_id
    ):
        return SessionReuseAssessment(
            device_id=device_id,
            presented_attachment_id=presented_attachment_id,
            stored_attachment_id=stored_attachment_id,
            presented_epoch=presented_epoch,
            stored_epoch=stored_epoch,
            presented_durable_session_id=presented_durable_session_id,
            stored_durable_session_id=stored_durable_session_id,
            outcome=SessionReuseOutcome.new_attachment_durable_conflict,
            diagnosis=(
                f"durable_session_id conflict: presented={presented_durable_session_id!r} "
                f"stored={stored_durable_session_id!r}. Two independent Android runtime "
                "instances may be competing for the same device_id. Classified as "
                "new_attachment_durable_conflict per "
                "SESSION_REUSE_MUST_REJECT_DURABLE_ID_CONFLICT_POLICY."
            ),
            policy_reference=SESSION_REUSE_MUST_REJECT_DURABLE_ID_CONFLICT_POLICY,
        )

    # --- Attachment ID mismatch ---
    if presented_attachment_id != stored_attachment_id:
        return SessionReuseAssessment(
            device_id=device_id,
            presented_attachment_id=presented_attachment_id,
            stored_attachment_id=stored_attachment_id,
            presented_epoch=presented_epoch,
            stored_epoch=stored_epoch,
            presented_durable_session_id=presented_durable_session_id,
            stored_durable_session_id=stored_durable_session_id,
            outcome=SessionReuseOutcome.new_attachment_id_mismatch,
            diagnosis=(
                f"runtime_attachment_session_id mismatch: "
                f"presented={presented_attachment_id!r} stored={stored_attachment_id!r}. "
                "Continuity_resume cannot be granted; classified as new_attachment_id_mismatch."
            ),
            policy_reference=SESSION_REUSE_MUST_REJECT_ABSENT_ATTACHMENT_ID_POLICY,
        )

    # --- All checks passed: continuity_resume ---
    return SessionReuseAssessment(
        device_id=device_id,
        presented_attachment_id=presented_attachment_id,
        stored_attachment_id=stored_attachment_id,
        presented_epoch=presented_epoch,
        stored_epoch=stored_epoch,
        presented_durable_session_id=presented_durable_session_id,
        stored_durable_session_id=stored_durable_session_id,
        outcome=SessionReuseOutcome.continuity_resume,
        diagnosis=(
            "All session reuse checks passed: matching attachment ID, "
            "consistent epoch, consistent durable_session_id. "
            "Classified as continuity_resume."
        ),
        policy_reference=SESSION_REUSE_MUST_REJECT_ABSENT_ATTACHMENT_ID_POLICY,
    )


# ---------------------------------------------------------------------------
# assess_attached_runtime_truth
# ---------------------------------------------------------------------------

# Staleness threshold in seconds: signals older than this degrade truth
# from android_confirmed to locally_inferred.
_ATTACHED_RUNTIME_STALENESS_THRESHOLD_SECONDS: float = 120.0


def assess_attached_runtime_truth(
    *,
    device_id: str,
    runtime_attachment_session_id: Optional[str],
    registry_entry_present: bool,
    last_signal_age_seconds: Optional[float],
) -> AttachedRuntimeTruthAssessment:
    """Grade the truth of an attached Android runtime before delegation.

    Parameters
    ----------
    device_id
        The Android device identifier.
    runtime_attachment_session_id
        The attachment session ID from the registry (``None`` if no entry).
    registry_entry_present
        Whether a registry entry exists for the device.
    last_signal_age_seconds
        Age of the most recent Android-originated signal for this device
        (heartbeat, lifecycle event, or result).  ``None`` if unknown.

    Returns
    -------
    AttachedRuntimeTruthAssessment
    """
    if not registry_entry_present or runtime_attachment_session_id is None:
        return AttachedRuntimeTruthAssessment(
            device_id=device_id,
            runtime_attachment_session_id=runtime_attachment_session_id,
            truth=AttachedRuntimeTruth.unverifiable,
            diagnosis=(
                "No registry entry or attachment session ID present for device; "
                "runtime truth is unverifiable. Delegation confidence is degraded."
            ),
            registry_entry_present=registry_entry_present,
            last_signal_age_seconds=last_signal_age_seconds,
        )

    if last_signal_age_seconds is None:
        return AttachedRuntimeTruthAssessment(
            device_id=device_id,
            runtime_attachment_session_id=runtime_attachment_session_id,
            truth=AttachedRuntimeTruth.locally_inferred,
            diagnosis=(
                "Registry entry present but no recent signal age available; "
                "runtime truth is locally_inferred from registration only. "
                "Delegation proceeds with degraded confidence."
            ),
            registry_entry_present=True,
            last_signal_age_seconds=None,
        )

    if last_signal_age_seconds <= _ATTACHED_RUNTIME_STALENESS_THRESHOLD_SECONDS:
        return AttachedRuntimeTruthAssessment(
            device_id=device_id,
            runtime_attachment_session_id=runtime_attachment_session_id,
            truth=AttachedRuntimeTruth.android_confirmed,
            diagnosis=(
                f"Registry entry present with fresh signal "
                f"(age={last_signal_age_seconds:.1f}s ≤ "
                f"{_ATTACHED_RUNTIME_STALENESS_THRESHOLD_SECONDS}s threshold). "
                "Runtime truth is android_confirmed."
            ),
            registry_entry_present=True,
            last_signal_age_seconds=last_signal_age_seconds,
        )

    return AttachedRuntimeTruthAssessment(
        device_id=device_id,
        runtime_attachment_session_id=runtime_attachment_session_id,
        truth=AttachedRuntimeTruth.locally_inferred,
        diagnosis=(
            f"Registry entry present but last signal is stale "
            f"(age={last_signal_age_seconds:.1f}s > "
            f"{_ATTACHED_RUNTIME_STALENESS_THRESHOLD_SECONDS}s threshold). "
            "Runtime truth degraded to locally_inferred."
        ),
        registry_entry_present=True,
        last_signal_age_seconds=last_signal_age_seconds,
    )


# ---------------------------------------------------------------------------
# classify_evidence_ingress
# ---------------------------------------------------------------------------

_VALID_PROVENANCE_KEYS: frozenset[str] = frozenset(
    {"real_android", "replay_queue", "locally_synthesised"}
)


def classify_evidence_ingress(
    *,
    evidence_id: str,
    device_id: str,
    provenance_hint: Optional[str],
    from_replay_queue: bool = False,
    from_local_synthesis: bool = False,
) -> EvidenceIngressAssessment:
    """Classify the provenance of incoming recovery evidence.

    Parameters
    ----------
    evidence_id
        Opaque identifier for the evidence record.
    device_id
        The Android device identifier.
    provenance_hint
        Optional caller-supplied provenance hint.  ``"real_android"`` →
        real_android_originated; ``"replay_queue"`` → replay_queue_drained;
        ``"locally_synthesised"`` → locally_synthesised.  Any other value
        (including ``None``) degrades to unknown_provenance unless the
        ``from_*`` flags disambiguate.
    from_replay_queue
        True if the evidence was explicitly identified as coming from an
        offline queue drain.
    from_local_synthesis
        True if the evidence was synthesised locally within V2.

    Returns
    -------
    EvidenceIngressAssessment
    """
    if from_local_synthesis:
        return EvidenceIngressAssessment(
            evidence_id=evidence_id,
            device_id=device_id,
            provenance=EvidenceIngressProvenance.locally_synthesised,
            is_degraded=True,
            diagnosis=(
                "Evidence is locally_synthesised within V2 (no corresponding "
                "Android signal). Treated as degraded per "
                "EVIDENCE_INGRESS_MUST_CARRY_EXPLICIT_PROVENANCE_POLICY."
            ),
        )

    if from_replay_queue:
        return EvidenceIngressAssessment(
            evidence_id=evidence_id,
            device_id=device_id,
            provenance=EvidenceIngressProvenance.replay_queue_drained,
            is_degraded=False,
            diagnosis=(
                "Evidence arrived via offline queue drain after Android reconnect. "
                "Classified as replay_queue_drained; ordering contract applies."
            ),
        )

    if provenance_hint == "real_android":
        return EvidenceIngressAssessment(
            evidence_id=evidence_id,
            device_id=device_id,
            provenance=EvidenceIngressProvenance.real_android_originated,
            is_degraded=False,
            diagnosis=(
                "Evidence arrived via live Android signal on active transport. "
                "Classified as real_android_originated."
            ),
        )

    if provenance_hint == "replay_queue":
        return EvidenceIngressAssessment(
            evidence_id=evidence_id,
            device_id=device_id,
            provenance=EvidenceIngressProvenance.replay_queue_drained,
            is_degraded=False,
            diagnosis=(
                "Evidence provenance hint is replay_queue. "
                "Classified as replay_queue_drained."
            ),
        )

    if provenance_hint == "locally_synthesised":
        return EvidenceIngressAssessment(
            evidence_id=evidence_id,
            device_id=device_id,
            provenance=EvidenceIngressProvenance.locally_synthesised,
            is_degraded=True,
            diagnosis=(
                "Evidence provenance hint is locally_synthesised. "
                "Treated as degraded."
            ),
        )

    # Fallthrough: unknown provenance
    return EvidenceIngressAssessment(
        evidence_id=evidence_id,
        device_id=device_id,
        provenance=EvidenceIngressProvenance.unknown_provenance,
        is_degraded=True,
        diagnosis=(
            f"Evidence provenance could not be determined "
            f"(provenance_hint={provenance_hint!r}, from_replay_queue={from_replay_queue}, "
            f"from_local_synthesis={from_local_synthesis}). "
            "Classified as unknown_provenance and treated as degraded per "
            "EVIDENCE_INGRESS_MUST_CARRY_EXPLICIT_PROVENANCE_POLICY."
        ),
    )


# ---------------------------------------------------------------------------
# assess_recovery_closure_quality
# ---------------------------------------------------------------------------


def assess_recovery_closure_quality(
    *,
    device_id: str,
    session_id: Optional[str],
    resolved_task_count: int,
    unresolved_task_count: int,
    degraded_task_count: int,
    gap_descriptions: Optional[List[str]] = None,
) -> RecoveryClosureAssessment:
    """Assess the quality of a recovery closure for a device/session.

    Parameters
    ----------
    device_id
        The Android device identifier.
    session_id
        Optional V2 session identifier.
    resolved_task_count
        Number of in-flight tasks that reached a canonical terminal truth.
    unresolved_task_count
        Number of in-flight tasks that remain unresolved after recovery.
    degraded_task_count
        Number of in-flight tasks that were resolved but with degraded evidence.
    gap_descriptions
        Optional list of human-readable descriptions of observed truth gaps.

    Returns
    -------
    RecoveryClosureAssessment
    """
    gaps = gap_descriptions or []
    total = resolved_task_count + unresolved_task_count + degraded_task_count

    if total == 0 and not gaps:
        return RecoveryClosureAssessment(
            device_id=device_id,
            session_id=session_id,
            quality=RecoveryClosureQuality.full_convergence,
            resolved_task_count=0,
            unresolved_task_count=0,
            degraded_task_count=0,
            diagnosis="No in-flight tasks and no gaps: trivial full_convergence.",
            gap_descriptions=[],
        )

    if unresolved_task_count > 0:
        if resolved_task_count == 0 and degraded_task_count == 0:
            quality = RecoveryClosureQuality.no_recovery
            diagnosis = (
                f"Recovery produced no resolved tasks "
                f"(unresolved={unresolved_task_count}). "
                "Classified as no_recovery; operator intervention required."
            )
        else:
            quality = RecoveryClosureQuality.partial_convergence
            diagnosis = (
                f"Recovery converged for some tasks "
                f"(resolved={resolved_task_count}, unresolved={unresolved_task_count}, "
                f"degraded={degraded_task_count}). "
                "Classified as partial_convergence; remaining gaps surfaced."
            )
    elif degraded_task_count > 0:
        quality = RecoveryClosureQuality.degraded_recovery
        diagnosis = (
            f"All tasks resolved but with degraded evidence "
            f"(resolved={resolved_task_count}, degraded={degraded_task_count}). "
            "Classified as degraded_recovery."
        )
    else:
        quality = RecoveryClosureQuality.full_convergence
        diagnosis = (
            f"All {resolved_task_count} in-flight tasks resolved with full evidence. "
            "Classified as full_convergence."
        )

    return RecoveryClosureAssessment(
        device_id=device_id,
        session_id=session_id,
        quality=quality,
        resolved_task_count=resolved_task_count,
        unresolved_task_count=unresolved_task_count,
        degraded_task_count=degraded_task_count,
        diagnosis=diagnosis,
        gap_descriptions=gaps,
    )


# ---------------------------------------------------------------------------
# classify_result_delivery
# ---------------------------------------------------------------------------


def classify_result_delivery(
    *,
    task_id: str,
    device_id: str,
    idempotency_key: str,
    durable_seen_keys: set,
    task_already_terminal: bool = False,
) -> ResultDeliveryAssessment:
    """Classify an inbound Android result relative to the task context.

    Parameters
    ----------
    task_id
        The task identifier from the inbound result message.
    device_id
        The Android device identifier.
    idempotency_key
        A stable key derived from (task_id, result_sequence_number, epoch) or
        similar — used for deduplication.
    durable_seen_keys
        Mutable set of idempotency keys already processed (updated in-place
        on first delivery).
    task_already_terminal
        True if the V2 canonical task state is already terminal before this
        result arrives.

    Returns
    -------
    ResultDeliveryAssessment
    """
    # First check: has this exact key been processed?
    if idempotency_key in durable_seen_keys:
        return ResultDeliveryAssessment(
            task_id=task_id,
            device_id=device_id,
            classification=ResultDeliveryClassification.confirmed_duplicate,
            idempotency_key=idempotency_key,
            should_suppress=True,
            diagnosis=(
                f"idempotency_key={idempotency_key!r} already processed; "
                "classified as confirmed_duplicate. "
                "Suppressed without state mutation per "
                "DUPLICATE_RESULT_MUST_BE_SUPPRESSED_BEFORE_STATE_MUTATION_POLICY."
            ),
        )

    # Second check: task already reached terminal state via a different path
    if task_already_terminal:
        return ResultDeliveryAssessment(
            task_id=task_id,
            device_id=device_id,
            classification=ResultDeliveryClassification.out_of_order_replay,
            idempotency_key=idempotency_key,
            should_suppress=True,
            diagnosis=(
                f"task_id={task_id!r} already terminal in canonical V2 state; "
                "inbound result is an out_of_order_replay. "
                "Suppressed to protect canonical terminal truth."
            ),
        )

    # First delivery: register idempotency key
    durable_seen_keys.add(idempotency_key)
    return ResultDeliveryAssessment(
        task_id=task_id,
        device_id=device_id,
        classification=ResultDeliveryClassification.first_delivery,
        idempotency_key=idempotency_key,
        should_suppress=False,
        diagnosis=(
            f"First delivery for task_id={task_id!r}. "
            "Idempotency key registered; result accepted."
        ),
    )


# ---------------------------------------------------------------------------
# interpret_replay_sequence
# ---------------------------------------------------------------------------


def interpret_replay_sequence(
    items: Sequence[Dict[str, Any]],
    *,
    expected_epoch: Optional[int] = None,
    seen_idempotency_keys: Optional[set] = None,
) -> List[ReplaySequenceItemAssessment]:
    """Interpret an offline replay sequence against real Android behavioral constraints.

    Each item dict MUST contain:
      - ``item_id`` (str): unique identifier for the replay item
      - ``session_epoch`` (int, optional): epoch of the session that produced this item
      - ``sequence_position`` (int, optional): position within the session queue

    Optional fields:
      - ``idempotency_key`` (str): stable dedup key; defaults to item_id

    Parameters
    ----------
    items
        Ordered sequence of replay item dicts (drain order from Android queue).
    expected_epoch
        The session epoch V2 considers current.  Items from a different epoch
        are classified as stale_dropped.
    seen_idempotency_keys
        Mutable set of idempotency keys already processed; updated in-place.

    Returns
    -------
    List[ReplaySequenceItemAssessment]
    """
    if seen_idempotency_keys is None:
        seen_idempotency_keys = set()

    assessments: List[ReplaySequenceItemAssessment] = []
    last_accepted_position: Optional[int] = None

    for idx, item in enumerate(items):
        item_id = str(item.get("item_id", f"item_{idx}"))
        item_epoch = item.get("session_epoch")
        seq_pos = item.get("sequence_position")
        idem_key = str(item.get("idempotency_key", item_id))

        # --- Epoch mismatch → stale_dropped ---
        if (
            expected_epoch is not None
            and item_epoch is not None
            and item_epoch != expected_epoch
        ):
            assessments.append(
                ReplaySequenceItemAssessment(
                    sequence_index=idx,
                    item_id=item_id,
                    session_epoch=item_epoch,
                    expected_epoch=expected_epoch,
                    sequence_position=seq_pos,
                    last_accepted_position=last_accepted_position,
                    classification=ReplayItemClassification.stale_dropped,
                    diagnosis=(
                        f"item_epoch={item_epoch!r} != expected_epoch={expected_epoch!r}; "
                        "classified as stale_dropped per "
                        "OFFLINE_REPLAY_MUST_RESPECT_SESSION_EPOCH_AND_SEQUENCE_POLICY."
                    ),
                )
            )
            continue

        # --- Duplicate suppression ---
        if idem_key in seen_idempotency_keys:
            assessments.append(
                ReplaySequenceItemAssessment(
                    sequence_index=idx,
                    item_id=item_id,
                    session_epoch=item_epoch,
                    expected_epoch=expected_epoch,
                    sequence_position=seq_pos,
                    last_accepted_position=last_accepted_position,
                    classification=ReplayItemClassification.duplicate_suppressed,
                    diagnosis=(
                        f"idempotency_key={idem_key!r} already seen; "
                        "classified as duplicate_suppressed."
                    ),
                )
            )
            continue

        # --- Sequence gap detection ---
        if (
            seq_pos is not None
            and last_accepted_position is not None
            and seq_pos > last_accepted_position + 1
        ):
            assessments.append(
                ReplaySequenceItemAssessment(
                    sequence_index=idx,
                    item_id=item_id,
                    session_epoch=item_epoch,
                    expected_epoch=expected_epoch,
                    sequence_position=seq_pos,
                    last_accepted_position=last_accepted_position,
                    classification=ReplayItemClassification.gap_exposed,
                    diagnosis=(
                        f"sequence_position={seq_pos!r} implies gap after "
                        f"last_accepted_position={last_accepted_position!r}; "
                        "classified as gap_exposed. Truth gap surfaced for diagnosis."
                    ),
                )
            )
            seen_idempotency_keys.add(idem_key)
            last_accepted_position = seq_pos
            continue

        # --- Convergence eligible ---
        seen_idempotency_keys.add(idem_key)
        if seq_pos is not None:
            last_accepted_position = seq_pos
        assessments.append(
            ReplaySequenceItemAssessment(
                sequence_index=idx,
                item_id=item_id,
                session_epoch=item_epoch,
                expected_epoch=expected_epoch,
                sequence_position=seq_pos,
                last_accepted_position=last_accepted_position,
                classification=ReplayItemClassification.convergence_eligible,
                diagnosis=(
                    f"Item within expected epoch and sequence window; "
                    "classified as convergence_eligible."
                ),
            )
        )

    return assessments


# ---------------------------------------------------------------------------
# build_recovery_participation_report
# ---------------------------------------------------------------------------


def build_recovery_participation_report(
    *,
    device_id: str,
    session_id: Optional[str],
    session_reuse: SessionReuseAssessment,
    attached_runtime_truth: AttachedRuntimeTruthAssessment,
    evidence_ingress: EvidenceIngressAssessment,
    recovery_closure: RecoveryClosureAssessment,
    replay_items: Optional[List[ReplaySequenceItemAssessment]] = None,
) -> RecoveryParticipationReport:
    """Assemble a full recovery participation report for a device/session.

    This function determines ``overall_recovery_quality`` and
    ``dual_repo_participation_eligible`` by combining the six hardening
    dimensions.

    Parameters
    ----------
    device_id
        The Android device identifier.
    session_id
        Optional V2 session identifier.
    session_reuse, attached_runtime_truth, evidence_ingress, recovery_closure
        Pre-computed hardening dimension assessments.
    replay_items
        Pre-computed replay sequence assessments (empty list if no replay).

    Returns
    -------
    RecoveryParticipationReport
    """
    items = replay_items or []

    # Determine overall quality by finding the worst dimension
    quality_order = [
        RecoveryClosureQuality.full_convergence,
        RecoveryClosureQuality.degraded_recovery,
        RecoveryClosureQuality.partial_convergence,
        RecoveryClosureQuality.no_recovery,
    ]

    worst_quality = recovery_closure.quality

    # Attached runtime truth degradation
    if attached_runtime_truth.truth == AttachedRuntimeTruth.unverifiable:
        if quality_order.index(worst_quality) < quality_order.index(
            RecoveryClosureQuality.degraded_recovery
        ):
            worst_quality = RecoveryClosureQuality.degraded_recovery
    elif attached_runtime_truth.truth == AttachedRuntimeTruth.locally_inferred:
        if quality_order.index(worst_quality) < quality_order.index(
            RecoveryClosureQuality.degraded_recovery
        ):
            worst_quality = RecoveryClosureQuality.degraded_recovery

    # Evidence ingress degradation
    if evidence_ingress.is_degraded:
        if quality_order.index(worst_quality) < quality_order.index(
            RecoveryClosureQuality.degraded_recovery
        ):
            worst_quality = RecoveryClosureQuality.degraded_recovery

    # Replay gap exposure
    gap_count = sum(
        1
        for r in items
        if r.classification == ReplayItemClassification.gap_exposed
    )
    if gap_count > 0:
        if quality_order.index(worst_quality) < quality_order.index(
            RecoveryClosureQuality.degraded_recovery
        ):
            worst_quality = RecoveryClosureQuality.degraded_recovery

    # Dual-repo participation eligibility: requires at least partial_convergence
    # with android_confirmed or locally_inferred runtime truth
    is_eligible = (
        session_reuse.outcome == SessionReuseOutcome.continuity_resume
        and attached_runtime_truth.truth != AttachedRuntimeTruth.unverifiable
        and worst_quality
        in (
            RecoveryClosureQuality.full_convergence,
            RecoveryClosureQuality.partial_convergence,
            RecoveryClosureQuality.degraded_recovery,
        )
    )

    diagnosis_parts = [
        f"session_reuse={session_reuse.outcome.value}",
        f"attached_runtime_truth={attached_runtime_truth.truth.value}",
        f"evidence_provenance={evidence_ingress.provenance.value}",
        f"recovery_closure={recovery_closure.quality.value}",
        f"overall_quality={worst_quality.value}",
        f"dual_repo_eligible={is_eligible}",
    ]
    if gap_count > 0:
        diagnosis_parts.append(f"replay_gaps={gap_count}")

    return RecoveryParticipationReport(
        device_id=device_id,
        session_id=session_id,
        session_reuse=session_reuse,
        attached_runtime_truth=attached_runtime_truth,
        evidence_ingress=evidence_ingress,
        recovery_closure=recovery_closure,
        replay_items=items,
        overall_recovery_quality=worst_quality,
        dual_repo_participation_eligible=is_eligible,
        participation_diagnosis="; ".join(diagnosis_parts),
    )
