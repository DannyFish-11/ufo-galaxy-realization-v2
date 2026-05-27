"""core/android_participant_truth_ingress.py
=============================================
PR-4V2 (post-533 dual-repo runtime integration): Android Participant/Session/
Runtime Truth Ingress and Canonical Reconciliation into V2 Orchestration State.

Background
----------
The Android-side runtime maintains local participant/session/task/runtime truth
that is authoritative on-device.  Previous PR packages (PR-13, PR-16, PR-18,
PR-21) addressed the inbound *execution-signal* reconciliation path (ACK /
PROGRESS / RESULT / ERROR / TIMEOUT / CANCELLED).  However, the broader
*participant/session/runtime truth* surfaces — Android session snapshots,
per-device readiness assessments, current task phase, and AgentLocalRuntime
execution state — had no explicit reconciliation protocol with V2 canonical
orchestration state (identified as gap TRUTH-005 in DUAL_REPO_FULL_REAUDIT.md
and TRUTH_PROJECTION_CONVERGENCE_MAP.md §4).

This module closes the V2 half of the Android runtime truth and protocol
reconciliation loop by providing:

1. :class:`AndroidParticipantTruthKind` — canonical enum for the kind of
   Android-originated truth being reported:
   ``session_snapshot`` / ``readiness_assessment`` / ``task_phase`` /
   ``runtime_state`` / ``cancel`` / ``status`` / ``failure`` / ``result``.

2. :class:`AndroidParticipantTruthEnvelope` — typed, immutable carrier that
   harvests the structured Android-originated truth together with canonical
   identity fields (``device_id``, ``session_id``, ``contract_id``,
   ``task_id``, ``trace_id``) and an opaque ``payload`` snapshot.

3. :class:`AndroidParticipantReconcileOutcome` — typed result of a
   reconciliation attempt, carrying the updated canonical state snapshot,
   a ``was_reconciled`` flag, an explicit ``canonical_update`` describing what
   V2 state was affected, a ``local_only`` flag for truth that remains
   Android-local, and a ``reject_reason`` when reconciliation was skipped.

4. :func:`extract_participant_truth_envelope` — extracts an
   :class:`AndroidParticipantTruthEnvelope` from a raw inbound message dict.

5. :func:`reconcile_android_participant_truth` — canonical entry-point that
   accepts an :class:`AndroidParticipantTruthEnvelope`, resolves V2 canonical
   records via :class:`~core.delegated_runtime_execution_tracker.DelegatedExecutionTrackingRuntime`
   and :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry`,
   applies the reconciliation behavior, emits terminal-state events to the
   :mod:`~core.replay_foundation`, and returns a typed
   :class:`AndroidParticipantReconcileOutcome`.

6. :func:`ingest_android_participant_truth_message` — convenience wrapper
   combining extraction + reconciliation in one call.

7. Twelve policy sentinels documenting canonical reconciliation rules and the
   authority boundary between Android local truth and V2 canonical orchestration
   truth.

8. One PR sentinel (``ANDROID_PARTICIPANT_TRUTH_INGRESS_PR4V2_SENTINEL``).

Authority boundary
------------------
This module is the definitive statement of the authority decision for
TRUTH-005:

**V2 is the single canonical orchestration authority.**  Android truth is
authoritative only for the device-local execution scope (what is happening
*on the Android device*).  When Android truth enters V2 via this ingress path
it is reconciled into V2 canonical state using the following rules:

* ``cancel`` / ``failure`` / ``result`` signals **materially update** V2
  canonical tracking records and emit to ReplayFoundation — they are not
  merely logged.
* ``task_phase`` truth is reconciled with the V2-side tracking record: if
  V2 is already in a terminal state, the Android phase update is rejected
  (V2 wins).  If V2 is not yet terminal and Android reports completion or
  failure, the signal is applied.
* ``session_snapshot`` truth is used to validate session continuity in the
  :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry`
  but does NOT override V2-owned session fields.
* ``readiness_assessment`` truth updates the ``last_android_readiness_ts``
  advisory field on the tracking record but does not change V2 dispatch
  eligibility gates (V2 admissibility chain remains authoritative).
* ``runtime_state`` truth is advisory; it is recorded to ReplayFoundation for
  audit purposes but does not alter V2 canonical state directly.
* ``status`` truth emits a progress event to the tracking record and to
  ReplayFoundation — same as a ``progress`` execution signal.

Design principles
-----------------
- **Additive only** — does not modify any prior module.
- **Explicit over implicit** — all authority decisions and conflict-resolution
  rules are stated as policy sentinels.
- **Single reconcile path** — all Android participant/session/runtime truth
  is reconciled through :func:`reconcile_android_participant_truth`; no
  other path may apply Android truth to V2 canonical state.
- **Non-destructive on miss** — if no matching V2 record is found the
  function returns an outcome with ``was_reconciled=False``; it never creates
  phantom records.
- **Terminal-blocking** — V2 tracking records in terminal state block further
  phase updates from Android (V2 terminal truth wins).
- **Audit-complete** — all reconciliations (accepted AND rejected) emit a
  ReplayFoundation event so the canonical event stream is complete.

PR package numbering
--------------------
PR-4V2 of the dual-repo Android runtime truth reconciliation closure.
Companion Android-repo PR: ``Close Android runtime truth and protocol
reconciliation gaps``.
"""

from __future__ import annotations

import copy
import threading as _threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

logger_name = "Galaxy.AndroidParticipantTruthIngress"

try:
    import logging as _logging

    _logger = _logging.getLogger(logger_name)
except Exception:  # pragma: no cover
    _logger = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Imports from prior PR packages — all guarded for loadability
# ---------------------------------------------------------------------------

try:
    from core.delegated_runtime_execution_tracker import (
        AcknowledgmentSignal,
        DelegatedExecutionResult,
        DelegatedExecutionTrackingRecord,
        DelegatedExecutionTrackingRuntime,
        apply_acknowledgment_signal,
        apply_result,
        get_execution_tracking_runtime,
    )

    _TRACKER_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _TRACKER_AVAILABLE = False
    AcknowledgmentSignal = None  # type: ignore[assignment,misc]
    DelegatedExecutionResult = None  # type: ignore[assignment,misc]
    DelegatedExecutionTrackingRecord = None  # type: ignore[assignment,misc]
    DelegatedExecutionTrackingRuntime = None  # type: ignore[assignment,misc]
    apply_acknowledgment_signal = None  # type: ignore[assignment]
    apply_result = None  # type: ignore[assignment]
    get_execution_tracking_runtime = None  # type: ignore[assignment]

try:
    from core.attached_runtime_session_registry import (
        AttachedSessionRegistry,
        get_session_registry,
        lookup_active_session,
    )

    _REGISTRY_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _REGISTRY_AVAILABLE = False
    AttachedSessionRegistry = None  # type: ignore[assignment,misc]
    get_session_registry = None  # type: ignore[assignment]
    lookup_active_session = None  # type: ignore[assignment]

try:
    from core.replay_foundation import emit_runtime_event as _emit_runtime_event

    _REPLAY_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _REPLAY_AVAILABLE = False
    _emit_runtime_event = None  # type: ignore[assignment]

# PR-10-V2: unified Android delegated runtime audit recorder.
try:
    from core.android_delegated_runtime_audit import (
        record_participant_truth_terminal_update as _audit_terminal_update,
    )

    _DELEGATED_AUDIT_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _DELEGATED_AUDIT_AVAILABLE = False
    _audit_terminal_update = None  # type: ignore[assignment]

# PR-4V2-GOV: FlowTruthAlignmentRuntime (PR-5V2) — governance_artifact alignment.
# When a governance_artifact truth kind arrives we call align_and_record() so that
# FlowTruthAlignmentRuntime accumulates a FlowTruthDecisionArtifact.  This makes
# Android governance/readiness/acceptance/strategy evaluator outputs visible to
# DelegatedFlowReadinessGate._evaluate_truth_ownership() as canonical gate inputs.
try:
    from core.flow_level_truth_ownership import (
        FlowTruthAlignmentContext as _FlowTruthAlignmentContext,
        align_and_record as _align_and_record,
    )

    _FLOW_TRUTH_ALIGNMENT_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _FLOW_TRUTH_ALIGNMENT_AVAILABLE = False
    _FlowTruthAlignmentContext = None  # type: ignore[assignment,misc]
    _align_and_record = None  # type: ignore[assignment]

# PR-4V2-Recovery: Android continuity recovery-state router.
# When a recovery_state truth kind arrives we route the recovery phase to an
# explicit V2 canonical handling path using the recovery-state router.
try:
    from core.android_continuity_recovery_state_router import (
        RecoveryStateRoutingDecision as _RecoveryStateRoutingDecision,
        route_recovery_state_from_payload as _route_recovery_state_from_payload,
    )

    _RECOVERY_STATE_ROUTER_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _RECOVERY_STATE_ROUTER_AVAILABLE = False
    _RecoveryStateRoutingDecision = None  # type: ignore[assignment,misc]
    _route_recovery_state_from_payload = None  # type: ignore[assignment]

try:
    from core.session_identity import build_canonical_session_identity

    _SESSION_IDENTITY_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _SESSION_IDENTITY_AVAILABLE = False
    build_canonical_session_identity = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Module authority marker
# ---------------------------------------------------------------------------

ANDROID_PARTICIPANT_TRUTH_INGRESS_AUTHORITY: str = (
    "core.android_participant_truth_ingress::PR4V2::"
    "android-participant-session-runtime-truth-ingress-and-canonical-"
    "reconciliation-into-v2-orchestration-state::"
    "concrete-android-implementation-of-participant-generic-result-ingress-"
    "contract-defined-in-core.participant_authority_interfaces-PR-8::"
    "AndroidParticipantTruthKind-implements-ParticipantResultKind"
)

# ---------------------------------------------------------------------------
# Authority-boundary sentinel
# ---------------------------------------------------------------------------

V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_SENTINEL: str = (
    "V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY::"
    "core.android_participant_truth_ingress::PR4V2::"
    "windows-desktop-v2-holds-single-canonical-orchestration-authority::"
    "android-truth-is-advisory-for-device-local-scope-only::"
    "cancel+failure+result-signals-materially-update-v2-canonical-state::"
    "v2-terminal-state-wins-conflict-resolution"
)

# ---------------------------------------------------------------------------
# Policy sentinels — document canonical reconciliation rules
# ---------------------------------------------------------------------------

V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY: str = (
    "POLICY::V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY: "
    "Windows/Desktop V2 is the single canonical orchestration authority.  "
    "Android truth enters V2 via this ingress path and is reconciled INTO "
    "V2 canonical state.  Android does not own or override V2 canonical fields."
)

ANDROID_TRUTH_IS_ADVISORY_FOR_DEVICE_SCOPE_POLICY: str = (
    "POLICY::ANDROID_TRUTH_IS_ADVISORY_FOR_DEVICE_SCOPE: "
    "Android local truth (session snapshot, readiness assessment, runtime state) "
    "is authoritative for the device-local execution scope.  It becomes "
    "canonical V2 state only when explicitly reconciled by this module.  "
    "Android local fields that have no V2 equivalent remain local-only."
)

CANCEL_FAILURE_RESULT_AFFECT_CANONICAL_STATE_POLICY: str = (
    "POLICY::CANCEL_FAILURE_RESULT_AFFECT_CANONICAL_STATE: "
    "Android-originated cancel, failure, and result signals MUST materially "
    "update V2 canonical tracking records (via apply_acknowledgment_signal) "
    "and emit to ReplayFoundation.  These signals are NOT merely logged or "
    "forwarded — they change V2 canonical orchestration truth."
)

STATUS_SIGNAL_EMITS_PROGRESS_EVENT_POLICY: str = (
    "POLICY::STATUS_SIGNAL_EMITS_PROGRESS_EVENT_POLICY: "
    "Android-originated status signals emit a progress acknowledgment to the "
    "V2 tracking record and a ReplayFoundation event.  They advance the "
    "tracking record to in_progress if it is in acknowledged state."
)

TASK_PHASE_RECONCILED_WITH_TRACKING_RECORD_POLICY: str = (
    "POLICY::TASK_PHASE_RECONCILED_WITH_TRACKING_RECORD: "
    "Android-reported task phase is reconciled with the V2 tracking record.  "
    "If the V2 record is already terminal, the Android phase update is rejected "
    "(V2 terminal state wins).  If V2 is not yet terminal and Android reports "
    "completion or failure the corresponding signal is applied."
)

SESSION_SNAPSHOT_VALIDATES_REGISTRY_CONTINUITY_POLICY: str = (
    "POLICY::SESSION_SNAPSHOT_VALIDATES_REGISTRY_CONTINUITY: "
    "Android session snapshot truth is used to validate session continuity in "
    "the AttachedSessionRegistry.  It does NOT override V2-owned session fields "
    "(session_id, device_id, state).  Mismatches are recorded as conflicts."
)

READINESS_ASSESSMENT_IS_ADVISORY_POLICY: str = (
    "POLICY::READINESS_ASSESSMENT_IS_ADVISORY: "
    "Android readiness assessment is advisory.  It does not change V2 dispatch "
    "eligibility gates — those remain controlled by the V2 admissibility chain.  "
    "The assessment timestamp is recorded in the reconcile outcome for "
    "observability."
)

RUNTIME_STATE_IS_AUDIT_ONLY_POLICY: str = (
    "POLICY::RUNTIME_STATE_IS_AUDIT_ONLY: "
    "Android AgentLocalRuntime state truth is advisory.  It is emitted to "
    "ReplayFoundation for audit purposes but does NOT directly alter V2 "
    "canonical orchestration state."
)

TERMINAL_V2_STATE_WINS_CONFLICT_POLICY: str = (
    "POLICY::TERMINAL_V2_STATE_WINS_CONFLICT: "
    "When the V2 tracking record is already in a terminal phase (completed / "
    "failed / timed_out / cancelled), any incoming Android truth update that "
    "would alter the record is rejected.  V2 terminal truth is immutable from "
    "the Android perspective."
)

RECONCILE_IS_NON_DESTRUCTIVE_ON_MISS_POLICY: str = (
    "POLICY::RECONCILE_IS_NON_DESTRUCTIVE_ON_MISS: "
    "When no matching V2 tracking record or session registry entry is found "
    "for the given identity keys, reconciliation returns was_reconciled=False "
    "without creating phantom records or raising exceptions."
)

RECONCILE_EMITS_AUDIT_EVENT_ALWAYS_POLICY: str = (
    "POLICY::RECONCILE_EMITS_AUDIT_EVENT_ALWAYS: "
    "All reconciliation attempts — accepted AND rejected — emit a "
    "ReplayFoundation runtime event.  This ensures the canonical audit stream "
    "is complete regardless of outcome."
)

IDENTITY_FIELDS_ARE_VERBATIM_POLICY: str = (
    "POLICY::IDENTITY_FIELDS_ARE_VERBATIM: "
    "device_id, session_id, contract_id, task_id, and trace_id are extracted "
    "verbatim from the inbound Android truth message.  The ingress path MUST "
    "NOT synthesise or overwrite identity fields."
)

RECONCILIATION_SIGNAL_DISTINCT_FROM_DELEGATED_POLICY: str = (
    "POLICY::RECONCILIATION_SIGNAL_DISTINCT_FROM_DELEGATED: "
    "Android reconciliation_signal is an explicit state reconciliation push from "
    "the Android RuntimeController and is distinct from delegated_execution_signal. "
    "reconciliation_signal carries a 'phase' or 'status' field in its payload "
    "that is mapped to an AcknowledgmentSignal via the phase-to-ack map and "
    "applied to the V2 tracking record.  V2 terminal state still wins if the "
    "record is already in a terminal phase.  reconciliation_signal MUST NOT "
    "duplicate terminal event processing already applied by delegated_execution_signal."
)

GOVERNANCE_ARTIFACT_IS_CANONICAL_GATE_INPUT_POLICY: str = (
    "POLICY::GOVERNANCE_ARTIFACT_IS_CANONICAL_GATE_INPUT: "
    "Android-originated evaluator artifacts (governance, readiness, acceptance, "
    "strategy) that arrive via the governance_artifact truth kind are FIRST-CLASS "
    "canonical gate inputs, not advisory-only signals.  They MUST be aligned via "
    "align_and_record() from core.flow_level_truth_ownership so that the "
    "FlowTruthAlignmentRuntime accumulates a decision artifact.  This makes them "
    "visible to DelegatedFlowReadinessGate.truth_ownership dimension evaluation.  "
    "The distinction: readiness_assessment remains advisory (READINESS_ASSESSMENT_IS_ADVISORY_POLICY); "
    "governance_artifact is authoritative upward and reaches the canonical gate.  "
    "PR-4V2-GOV: wire Android evaluator artifacts into canonical readiness/governance flow."
)

RECOVERY_STATE_MUST_BE_EXPLICITLY_ROUTED_POLICY: str = (
    "POLICY::RECOVERY_STATE_EXPLICIT_ROUTING_PR4V2_RECOVERY: "
    "Android-originated recovery_state truth kind MUST be routed through the "
    "android_continuity_recovery_state_router rather than treated as generic "
    "metadata.  Each recovery phase category maps to an explicit V2 canonical "
    "handling route: reject_stale_artifact, trigger_reconciliation, "
    "require_closure_review, accept_advisory_evidence, or mark_recovery_pending. "
    "Advisory recovered_inflight evidence MUST NOT directly produce canonical "
    "closure.  Stale recovery artifacts MUST be rejected.  V2 remains the "
    "canonical closure authority throughout.  "
    "PR-4V2-Recovery: close the gap between Android recovery-state semantics "
    "and explicit V2 canonical consumption."
)

_ALL_POLICY_SENTINELS: Tuple[str, ...] = (
    V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY,
    ANDROID_TRUTH_IS_ADVISORY_FOR_DEVICE_SCOPE_POLICY,
    CANCEL_FAILURE_RESULT_AFFECT_CANONICAL_STATE_POLICY,
    STATUS_SIGNAL_EMITS_PROGRESS_EVENT_POLICY,
    TASK_PHASE_RECONCILED_WITH_TRACKING_RECORD_POLICY,
    SESSION_SNAPSHOT_VALIDATES_REGISTRY_CONTINUITY_POLICY,
    READINESS_ASSESSMENT_IS_ADVISORY_POLICY,
    RUNTIME_STATE_IS_AUDIT_ONLY_POLICY,
    TERMINAL_V2_STATE_WINS_CONFLICT_POLICY,
    RECONCILE_IS_NON_DESTRUCTIVE_ON_MISS_POLICY,
    RECONCILE_EMITS_AUDIT_EVENT_ALWAYS_POLICY,
    IDENTITY_FIELDS_ARE_VERBATIM_POLICY,
    RECONCILIATION_SIGNAL_DISTINCT_FROM_DELEGATED_POLICY,
    GOVERNANCE_ARTIFACT_IS_CANONICAL_GATE_INPUT_POLICY,
    RECOVERY_STATE_MUST_BE_EXPLICITLY_ROUTED_POLICY,
)

# ---------------------------------------------------------------------------
# PR sentinel
# ---------------------------------------------------------------------------

ANDROID_PARTICIPANT_TRUTH_INGRESS_PR4V2_SENTINEL: str = (
    "android_participant_truth_ingress::package=PR4V2::pr=android-runtime-truth-"
    "reconciliation-into-v2-canonical-orchestration::"
    "authority=ANDROID_PARTICIPANT_TRUTH_INGRESS_AUTHORITY::"
    "closes=TRUTH-005"
)

# ---------------------------------------------------------------------------
# AndroidParticipantTruthKind enum
# ---------------------------------------------------------------------------


class AndroidParticipantTruthKind(str, Enum):
    """Canonical enum for the kind of Android-originated truth being reported.

    Values
    ------
    session_snapshot
        Android-side local session state snapshot (e.g. SQLite session record).
    readiness_assessment
        Android-side per-device readiness assessment.
    task_phase
        Android-side current task lifecycle phase (pending / running /
        completed / failed / cancelled).
    runtime_state
        Android-side AgentLocalRuntime execution state.
    cancel
        Android-originated explicit cancel signal for a delegated execution.
    status
        Android-originated task status update (maps to a progress signal on
        the V2 tracking record).
    failure
        Android-originated explicit failure/error report for a delegated
        execution.
    result
        Android-originated final result for a delegated execution (success or
        failure outcome with payload).
    unknown
        Unrecognised truth kind; defaults to advisory/audit-only handling.
    """

    session_snapshot = "session_snapshot"
    readiness_assessment = "readiness_assessment"
    task_phase = "task_phase"
    runtime_state = "runtime_state"
    cancel = "cancel"
    status = "status"
    failure = "failure"
    result = "result"
    reconciliation_signal = "reconciliation_signal"
    governance_artifact = "governance_artifact"
    recovery_state = "recovery_state"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: Optional[str]) -> "AndroidParticipantTruthKind":
        """Return the matching kind or ``unknown`` for unrecognised values."""
        if not value:
            return cls.unknown
        normalised = str(value).strip().lower()
        for member in cls:
            if member.value == normalised:
                return member
        return cls.unknown

    def is_terminal_signal(self) -> bool:
        """Return True iff this kind carries a terminal execution outcome."""
        return self in (
            AndroidParticipantTruthKind.cancel,
            AndroidParticipantTruthKind.failure,
            AndroidParticipantTruthKind.result,
            AndroidParticipantTruthKind.reconciliation_signal,
        )

    def affects_canonical_state(self) -> bool:
        """Return True iff this kind materially updates V2 canonical state."""
        return self in (
            AndroidParticipantTruthKind.cancel,
            AndroidParticipantTruthKind.failure,
            AndroidParticipantTruthKind.result,
            AndroidParticipantTruthKind.status,
            AndroidParticipantTruthKind.task_phase,
            AndroidParticipantTruthKind.reconciliation_signal,
            AndroidParticipantTruthKind.governance_artifact,
        )

    def is_non_closure_signal(self) -> bool:
        """Return True iff this kind must never assert canonical task closure."""
        return self in (
            AndroidParticipantTruthKind.session_snapshot,
            AndroidParticipantTruthKind.readiness_assessment,
            AndroidParticipantTruthKind.runtime_state,
            AndroidParticipantTruthKind.status,
            AndroidParticipantTruthKind.recovery_state,
            AndroidParticipantTruthKind.unknown,
        )


# ---------------------------------------------------------------------------
# AndroidParticipantTruthEnvelope dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AndroidParticipantTruthEnvelope:
    """Typed, immutable carrier for an Android-originated participant/session/
    runtime truth message.

    Attributes
    ----------
    truth_kind
        The :class:`AndroidParticipantTruthKind` identifying what aspect of
        Android-local truth is being reported.
    device_id
        Android device identifier.
    session_id
        Attached runtime session identifier (may be empty for truth kinds that
        are not session-scoped).
    contract_id
        Delegated execution contract identifier (may be empty).
    task_id
        Task identifier (may be empty).
    trace_id
        End-to-end trace identifier (may be empty).
    envelope_id
        UUID assigned by this ingress module to this specific envelope for
        idempotency / audit purposes.
    received_at
        Unix timestamp (float) when this envelope was created.
    payload
        Opaque snapshot of the raw Android truth payload as received.
    task_phase_value
        For ``task_phase`` truths: the Android-reported phase string
        (e.g. ``"running"``, ``"completed"``, ``"failed"``, ``"cancelled"``).
    result_success
        For ``result`` truths: whether Android reports success (True) or
        failure (False).  None when not applicable.
    result_payload
        For ``result`` truths: optional result payload dict from Android.
    """

    truth_kind: AndroidParticipantTruthKind = AndroidParticipantTruthKind.unknown
    device_id: str = ""
    session_id: str = ""
    contract_id: str = ""
    task_id: str = ""
    trace_id: str = ""
    envelope_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    received_at: float = field(default_factory=time.time)
    payload: Dict[str, Any] = field(default_factory=dict)
    schema_gate_evidence: Dict[str, Any] = field(default_factory=dict)
    task_phase_value: str = ""
    result_success: Optional[bool] = None
    result_payload: Dict[str, Any] = field(default_factory=dict)

    def has_lookup_key(self) -> bool:
        """Return True iff at least one of contract_id or session_id is set."""
        return bool(self.contract_id) or bool(self.session_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "truth_kind": self.truth_kind.value,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "contract_id": self.contract_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "envelope_id": self.envelope_id,
            "received_at": self.received_at,
            "payload": dict(self.payload),
            "schema_gate_evidence": dict(self.schema_gate_evidence),
            "task_phase_value": self.task_phase_value,
            "result_success": self.result_success,
            "result_payload": dict(self.result_payload),
        }


# ---------------------------------------------------------------------------
# AndroidParticipantReconcileOutcome dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AndroidParticipantReconcileOutcome:
    """Typed result of a single Android participant truth reconciliation attempt.

    Attributes
    ----------
    envelope
        The :class:`AndroidParticipantTruthEnvelope` that was processed.
    was_reconciled
        True iff at least one V2 canonical record was materially updated.
    canonical_update
        Human-readable description of what V2 canonical state was updated.
        Empty string when was_reconciled is False.
    local_only
        True iff the truth kind is advisory/audit-only and remains Android-local
        with no V2 canonical state change.
    reject_reason
        Non-empty string when reconciliation was rejected (no matching record,
        terminal state, missing identity keys, etc.).
    replay_event_emitted
        True iff a ReplayFoundation event was emitted for this reconciliation.
    tracking_record_phase
        String representation of the V2 tracking record phase after
        reconciliation (empty if no record was found).
    """

    envelope: Optional[AndroidParticipantTruthEnvelope] = None
    was_reconciled: bool = False
    canonical_update: str = ""
    local_only: bool = False
    reject_reason: str = ""
    replay_event_emitted: bool = False
    tracking_record_phase: str = ""
    recovery_state_routing: Dict[str, Any] = field(default_factory=dict)
    schema_gate_evidence: Dict[str, Any] = field(default_factory=dict)
    ownership_context: Dict[str, Any] = field(default_factory=dict)

    def is_accepted(self) -> bool:
        return self.was_reconciled and not self.reject_reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "was_reconciled": self.was_reconciled,
            "canonical_update": self.canonical_update,
            "local_only": self.local_only,
            "reject_reason": self.reject_reason,
            "replay_event_emitted": self.replay_event_emitted,
            "tracking_record_phase": self.tracking_record_phase,
            "recovery_state_routing": dict(self.recovery_state_routing),
            "schema_gate_evidence": dict(self.schema_gate_evidence),
            "ownership_context": dict(self.ownership_context),
            "envelope": self.envelope.to_dict() if self.envelope else None,
        }


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

_TRUTH_KIND_FIELD_ALIASES = ("truth_kind", "signal_kind", "kind", "type", "message_type")


def _extract_str(
    message: Dict[str, Any],
    *keys: str,
    default: str = "",
) -> str:
    """Extract first non-empty string value from top-level or payload sub-dict."""
    payload: Dict[str, Any] = message.get("payload", {}) or {}
    for key in keys:
        v = message.get(key) or payload.get(key)
        if v and isinstance(v, str):
            return v.strip()
    return default


def _extract_schema_gate_evidence(message: Dict[str, Any]) -> Dict[str, Any]:
    """Return stamped cross-repo schema gate evidence from the richest known location.

    Precedence is top-level internal stamping first (``_cross_repo_schema_version_gate``),
    then response-style top-level aliasing (``schema_version_gate``), then the same keys
    inside ``payload`` for callers that forwarded a nested envelope. This keeps degraded
    compat evidence attached even when messages cross handler, bridge, and wrapper
    boundaries before entering canonical participant truth ingress.
    """
    payload = message.get("payload")
    payload_mapping = payload if isinstance(payload, dict) else {}
    for candidate in (
        message.get("_cross_repo_schema_version_gate"),
        message.get("schema_version_gate"),
        payload_mapping.get("_cross_repo_schema_version_gate"),
        payload_mapping.get("schema_version_gate"),
    ):
        if isinstance(candidate, dict):
            return dict(candidate)
    return {}


def extract_participant_truth_envelope(
    message: Dict[str, Any],
) -> AndroidParticipantTruthEnvelope:
    """Extract an :class:`AndroidParticipantTruthEnvelope` from a raw message dict.

    Identity field extraction rules
    --------------------------------
    * ``device_id``, ``task_id`` — top-level first, then ``payload`` sub-dict.
    * ``contract_id``, ``session_id``, ``trace_id`` — ``payload`` sub-dict
      first, then top-level (delegated routing fields Android sends in payload).
    * ``truth_kind`` — checked under several alias keys.
    * ``task_phase_value`` — extracted from ``payload.task_phase`` or
      ``payload.phase`` or ``payload.status``.
    * ``result_success`` — extracted from ``payload.success`` (bool) or
      inferred from ``payload.result_kind`` / ``payload.status``.
    * ``result_payload`` — extracted from ``payload.result`` or ``payload.data``.
    """
    if not isinstance(message, dict):
        message = {}

    payload: Dict[str, Any] = message.get("payload", {}) or {}

    # truth_kind — check multiple aliases
    raw_kind: str = ""
    for alias in _TRUTH_KIND_FIELD_ALIASES:
        v = message.get(alias) or payload.get(alias)
        if v and isinstance(v, str):
            raw_kind = v
            break
    truth_kind = AndroidParticipantTruthKind.from_string(raw_kind)

    # device_id / task_id: top-level takes precedence, fallback to payload
    device_id = str(message.get("device_id") or payload.get("device_id") or "")
    task_id = str(message.get("task_id") or payload.get("task_id") or "")

    # contract_id / session_id / trace_id: payload takes precedence over top-level
    contract_id = str(payload.get("contract_id") or message.get("contract_id") or "")
    session_id = str(payload.get("session_id") or message.get("session_id") or "")
    trace_id = str(payload.get("trace_id") or message.get("trace_id") or "")

    # task_phase_value
    task_phase_value = str(
        payload.get("task_phase") or payload.get("phase") or payload.get("status") or ""
    )

    # result_success
    result_success: Optional[bool] = None
    raw_success = payload.get("success")
    if isinstance(raw_success, bool):
        result_success = raw_success
    else:
        rk = str(payload.get("result_kind") or "").lower()
        if rk == "success":
            result_success = True
        elif rk in ("failure", "failed", "error"):
            result_success = False

    # result_payload
    raw_result = payload.get("result") or payload.get("data")
    result_payload: Dict[str, Any] = {}
    if isinstance(raw_result, dict):
        result_payload = raw_result

    # Closure-bearing extraction fields are kind-gated to make non-closure
    # semantics machine-obvious and resilient to future refactors.
    if truth_kind not in (
        AndroidParticipantTruthKind.task_phase,
        AndroidParticipantTruthKind.unknown,
    ):
        task_phase_value = ""
    if truth_kind not in (
        AndroidParticipantTruthKind.result,
        AndroidParticipantTruthKind.unknown,
    ):
        result_success = None
        result_payload = {}

    return AndroidParticipantTruthEnvelope(
        truth_kind=truth_kind,
        device_id=device_id,
        session_id=session_id,
        contract_id=contract_id,
        task_id=task_id,
        trace_id=trace_id,
        payload=dict(payload),
        schema_gate_evidence=_extract_schema_gate_evidence(message),
        task_phase_value=task_phase_value,
        result_success=result_success,
        result_payload=result_payload,
    )


# ---------------------------------------------------------------------------
# _emit_audit_event — internal helper
# ---------------------------------------------------------------------------

_TERMINAL_TRUTH_KINDS = frozenset(
    {
        AndroidParticipantTruthKind.cancel.value,
        AndroidParticipantTruthKind.failure.value,
        AndroidParticipantTruthKind.result.value,
        AndroidParticipantTruthKind.reconciliation_signal.value,
    }
)

_NON_CLOSURE_TRUTH_KINDS = frozenset(
    {
        AndroidParticipantTruthKind.session_snapshot.value,
        AndroidParticipantTruthKind.readiness_assessment.value,
        AndroidParticipantTruthKind.runtime_state.value,
        AndroidParticipantTruthKind.status.value,
        AndroidParticipantTruthKind.recovery_state.value,
        AndroidParticipantTruthKind.unknown.value,
    }
)

_COMPAT_FALLBACK_NON_CANONICAL = "compat_fallback_non_canonical"

_TERMINAL_TRACKING_PHASES = frozenset(
    {
        "completed",
        "failed",
        "cancelled",
        "canceled",
        "timeout",
        "timed_out",
        "error",
    }
)


def _enforce_non_closure_truth_barrier(
    *,
    kind: AndroidParticipantTruthKind,
    was_reconciled: bool,
    canonical_update: str,
    reject_reason: str,
    tracking_record_phase: str,
) -> Tuple[bool, str, str, str]:
    """Block non-closure truth kinds from ever claiming terminal closure."""
    if kind.value not in _NON_CLOSURE_TRUTH_KINDS:
        return was_reconciled, canonical_update, reject_reason, tracking_record_phase

    phase = (tracking_record_phase or "").strip().lower()
    update_lower = (canonical_update or "").strip().lower()
    claims_terminal_phase = phase in _TERMINAL_TRACKING_PHASES
    claims_closure = any(
        marker in update_lower
        for marker in ("closure", "final_result", "tracking_record_completed", "→v2_phase=completed")
    )
    if not claims_terminal_phase and not claims_closure:
        return was_reconciled, canonical_update, reject_reason, tracking_record_phase

    reason = reject_reason or f"non_closure_truth_kind_blocked:{kind.value}"
    if claims_terminal_phase:
        reason = f"{reason}:terminal_phase={phase}"
    if claims_closure:
        reason = f"{reason}:closure_claim_detected"
    return False, "", reason, ""


def _emit_audit_event(
    *,
    truth_kind: str,
    envelope: AndroidParticipantTruthEnvelope,
    was_reconciled: bool,
    canonical_update: str,
    reject_reason: str,
    policy: str,
    recovery_state_routing: Optional[Dict[str, Any]] = None,
    ownership_context: Optional[Dict[str, Any]] = None,
) -> bool:
    """Emit a ReplayFoundation runtime event for this reconciliation attempt.

    Parameters
    ----------
    truth_kind
        The reconciled Android truth kind being emitted for audit.
    envelope
        The source Android participant truth envelope.
    was_reconciled
        Whether this truth materially updated canonical V2 state.
    canonical_update
        Human-readable description of any canonical state update applied.
    reject_reason
        Rejection reason when the truth was not canonically reconciled.
    policy
        Policy sentinel describing the canonical rule under which this
        reconciliation attempt was handled.
    recovery_state_routing
        Optional structured Android recovery-state routing decision to include
        in the emitted audit payload for observability.

    Returns True iff the event was successfully emitted.
    """
    if not _REPLAY_AVAILABLE or _emit_runtime_event is None:
        return False
    try:
        _emit_runtime_event(
            kind="android_participant_truth_reconciled",
            task_id=envelope.task_id or "",
            trace_id=envelope.trace_id or "",
            source="android_participant_truth_ingress",
            message=(
                f"Android participant truth reconciled: "
                f"truth_kind={truth_kind} "
                f"device_id={envelope.device_id or ''} "
                f"session_id={envelope.session_id or ''} "
                f"contract_id={envelope.contract_id or ''} "
                f"was_reconciled={was_reconciled}"
            ),
            payload={
                "truth_kind": truth_kind,
                "device_id": envelope.device_id,
                "session_id": envelope.session_id,
                "contract_id": envelope.contract_id,
                "task_id": envelope.task_id,
                "trace_id": envelope.trace_id,
                "was_reconciled": was_reconciled,
                "canonical_update": canonical_update,
                "reject_reason": reject_reason,
                "policy": policy,
                "recovery_state_routing": recovery_state_routing or {},
                "ownership_context": ownership_context or {},
            },
        )
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# _map_phase_to_ack_signal — internal helper
# ---------------------------------------------------------------------------

_PHASE_TO_ACK: Dict[str, Any] = {}  # populated lazily below


def _get_phase_to_ack_map() -> Dict[str, Any]:
    """Return lazy-initialised mapping from Android phase string to AcknowledgmentSignal."""
    global _PHASE_TO_ACK
    if _PHASE_TO_ACK or not _TRACKER_AVAILABLE or AcknowledgmentSignal is None:
        return _PHASE_TO_ACK
    _PHASE_TO_ACK = {
        "pending": AcknowledgmentSignal.ack,
        "ack": AcknowledgmentSignal.ack,
        "acknowledged": AcknowledgmentSignal.ack,
        "running": AcknowledgmentSignal.progress,
        "in_progress": AcknowledgmentSignal.progress,
        "progress": AcknowledgmentSignal.progress,
        "continue": AcknowledgmentSignal.progress,
        "completed": AcknowledgmentSignal.final_result,
        "done": AcknowledgmentSignal.final_result,
        "success": AcknowledgmentSignal.final_result,
        "finished": AcknowledgmentSignal.final_result,
        "failed": AcknowledgmentSignal.error,
        "error": AcknowledgmentSignal.error,
        "failure": AcknowledgmentSignal.error,
        "cancelled": AcknowledgmentSignal.cancelled,
        "cancel": AcknowledgmentSignal.cancelled,
        "timed_out": AcknowledgmentSignal.timeout,
        "timeout": AcknowledgmentSignal.timeout,
    }
    return _PHASE_TO_ACK


# ---------------------------------------------------------------------------
# _is_terminal_phase — internal helper
# ---------------------------------------------------------------------------

_TERMINAL_PHASES = frozenset({"completed", "failed", "timed_out", "cancelled"})


def _is_record_terminal(record: Any) -> bool:
    """Return True iff the tracking record is in a terminal phase."""
    try:
        phase = getattr(record, "phase", None)
        if phase is None:
            return False
        # Prefer the enum's is_terminal() method if available
        if hasattr(phase, "is_terminal"):
            return bool(phase.is_terminal())
        # Fallback: string check against phase value
        phase_val = str(phase).lower()
        return any(t in phase_val for t in _TERMINAL_PHASES)
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# reconcile_android_participant_truth — canonical entry-point
# ---------------------------------------------------------------------------


def reconcile_android_participant_truth(
    envelope: AndroidParticipantTruthEnvelope,
    *,
    runtime: Optional[Any] = None,
    registry: Optional[Any] = None,
) -> AndroidParticipantReconcileOutcome:
    """Canonical entry-point for Android participant/session/runtime truth reconciliation.

    Accepts an :class:`AndroidParticipantTruthEnvelope`, resolves the V2
    canonical records, applies reconciliation behavior per the policy sentinels,
    emits a ReplayFoundation audit event, and returns a typed
    :class:`AndroidParticipantReconcileOutcome`.

    Reconciliation steps
    --------------------
    1. Emit an early audit event (RECONCILE_EMITS_AUDIT_EVENT_ALWAYS_POLICY).
    2. For terminal truth kinds (cancel / failure / result):
       a. Resolve the tracking record by ``contract_id`` (preferred) or
          ``session_id`` (fallback).
       b. If the record is already terminal, reject (V2 terminal wins).
       c. Map truth_kind → AcknowledgmentSignal and apply to the tracker.
       d. Emit to ReplayFoundation with terminal signal recorded sentinel.
    3. For ``status``:
       Apply progress AcknowledgmentSignal to the tracker if a record is found.
    4. For ``task_phase``:
       Map the phase string to an AcknowledgmentSignal and apply (if non-terminal
       V2 record found, and the Android phase maps to a terminal signal).
    5. For ``session_snapshot``:
       Validate session continuity in AttachedSessionRegistry; record conflicts.
    6. For ``readiness_assessment`` and ``runtime_state``:
       Advisory only; emit to ReplayFoundation as audit event.
    7. Return a typed :class:`AndroidParticipantReconcileOutcome`.

    Parameters
    ----------
    envelope:
        The AndroidParticipantTruthEnvelope to reconcile.
    runtime:
        Optional :class:`~core.delegated_runtime_execution_tracker.DelegatedExecutionTrackingRuntime`
        instance.  If None the global singleton is used (when available).
    registry:
        Optional :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry`
        instance.  If None the global singleton is used (when available).
    """
    truth_kind_str: str = envelope.truth_kind.value

    # ------------------------------------------------------------------
    # Resolve runtime and registry
    # ------------------------------------------------------------------
    _runtime: Any = runtime
    if _runtime is None and _TRACKER_AVAILABLE and get_execution_tracking_runtime is not None:
        try:
            _runtime = get_execution_tracking_runtime()
        except Exception:  # noqa: BLE001
            _runtime = None

    _registry: Any = registry
    if _registry is None and _REGISTRY_AVAILABLE and get_session_registry is not None:
        try:
            _registry = get_session_registry()
        except Exception:  # noqa: BLE001
            _registry = None

    # ------------------------------------------------------------------
    # Route by truth_kind
    # ------------------------------------------------------------------

    was_reconciled = False
    canonical_update = ""
    local_only = False
    reject_reason = ""
    tracking_record_phase = ""
    recovery_state_routing: Dict[str, Any] = {}

    kind = envelope.truth_kind

    if kind in (
        AndroidParticipantTruthKind.cancel,
        AndroidParticipantTruthKind.failure,
        AndroidParticipantTruthKind.result,
    ):
        was_reconciled, canonical_update, reject_reason, tracking_record_phase = (
            _reconcile_terminal_signal(envelope, _runtime, kind)
        )

    elif kind == AndroidParticipantTruthKind.status:
        was_reconciled, canonical_update, reject_reason, tracking_record_phase = (
            _reconcile_status_signal(envelope, _runtime)
        )

    elif kind == AndroidParticipantTruthKind.task_phase:
        was_reconciled, canonical_update, reject_reason, tracking_record_phase = (
            _reconcile_task_phase(envelope, _runtime)
        )

    elif kind == AndroidParticipantTruthKind.session_snapshot:
        was_reconciled, canonical_update, reject_reason, tracking_record_phase = (
            _reconcile_session_snapshot(envelope, _registry)
        )

    elif kind == AndroidParticipantTruthKind.reconciliation_signal:
        was_reconciled, canonical_update, reject_reason, tracking_record_phase = (
            _reconcile_reconciliation_signal(envelope, _runtime)
        )

    elif kind == AndroidParticipantTruthKind.governance_artifact:
        was_reconciled, canonical_update, reject_reason, tracking_record_phase = (
            _reconcile_governance_artifact(envelope)
        )

    elif kind == AndroidParticipantTruthKind.recovery_state:
        (
            was_reconciled,
            canonical_update,
            reject_reason,
            tracking_record_phase,
            recovery_state_routing,
        ) = (
            _reconcile_recovery_state(envelope)
        )
        # Advisory and pending routes are local-only (no canonical state mutation).
        # Rejected and reconciliation-required routes are NOT local_only — they
        # surface as explicit reject_reason for the caller to act on.
        if not reject_reason:
            local_only = True

    elif kind in (
        AndroidParticipantTruthKind.readiness_assessment,
        AndroidParticipantTruthKind.runtime_state,
        AndroidParticipantTruthKind.unknown,
    ):
        # Advisory / audit-only: local_only = True
        local_only = True
        canonical_update = ""
        reject_reason = ""

    (
        was_reconciled,
        canonical_update,
        reject_reason,
        tracking_record_phase,
    ) = _enforce_non_closure_truth_barrier(
        kind=kind,
        was_reconciled=was_reconciled,
        canonical_update=canonical_update,
        reject_reason=reject_reason,
        tracking_record_phase=tracking_record_phase,
    )

    ownership_context = _build_ownership_context(
        envelope=envelope,
        kind=kind,
        was_reconciled=was_reconciled,
        local_only=local_only,
        reject_reason=reject_reason,
        canonical_update=canonical_update,
    )

    # ------------------------------------------------------------------
    # Emit ReplayFoundation audit event (always)
    # ------------------------------------------------------------------
    replay_event_emitted = _emit_audit_event(
        truth_kind=truth_kind_str,
        envelope=envelope,
        was_reconciled=was_reconciled,
        canonical_update=canonical_update,
        reject_reason=reject_reason,
        policy=(
            RECOVERY_STATE_MUST_BE_EXPLICITLY_ROUTED_POLICY
            if kind == AndroidParticipantTruthKind.recovery_state
            else CANCEL_FAILURE_RESULT_AFFECT_CANONICAL_STATE_POLICY
        ),
        recovery_state_routing=recovery_state_routing,
        ownership_context=ownership_context,
    )

    # PR-10-V2: Emit to the unified Android delegated runtime audit recorder
    # for terminal truth updates so the handoff→takeover→reconciliation chain
    # is fully traceable by task_id / session_id.
    if (
        was_reconciled
        and tracking_record_phase
        and _audit_terminal_update is not None
        and truth_kind_str in _TERMINAL_TRUTH_KINDS
    ):
        try:
            _audit_terminal_update(
                task_id=envelope.task_id or "",
                session_id=envelope.session_id or "",
                trace_id=envelope.trace_id or "",
                device_id=envelope.device_id or "",
                contract_id=envelope.contract_id or "",
                truth_kind=truth_kind_str,
                terminal_phase=tracking_record_phase,
                canonical_update=canonical_update,
            )
        except Exception:  # noqa: BLE001
            pass  # audit is non-fatal

    outcome = AndroidParticipantReconcileOutcome(
        envelope=envelope,
        was_reconciled=was_reconciled,
        canonical_update=canonical_update,
        local_only=local_only,
        reject_reason=reject_reason,
        replay_event_emitted=replay_event_emitted,
        tracking_record_phase=tracking_record_phase,
        recovery_state_routing=recovery_state_routing,
        schema_gate_evidence=dict(envelope.schema_gate_evidence),
        ownership_context=ownership_context,
    )
    # PR-10: Record the outcome for the operator review surface.
    _record_last_reconciliation_outcome(outcome)
    return outcome


# ---------------------------------------------------------------------------
# Internal reconcile helpers
# ---------------------------------------------------------------------------


def _resolve_tracking_record(
    envelope: AndroidParticipantTruthEnvelope,
    runtime: Any,
) -> Optional[Any]:
    """Resolve the V2 tracking record for the given envelope identity keys.

    Prefers ``contract_id`` lookup; falls back to ``session_id``.
    Returns None if not found or runtime unavailable.
    """
    if runtime is None or not _TRACKER_AVAILABLE:
        return None
    try:
        if envelope.contract_id:
            record = runtime.get_latest_for_contract(envelope.contract_id)
            if record is not None:
                return record
        if envelope.session_id:
            return runtime.get_latest_for_session(envelope.session_id)
    except Exception:  # noqa: BLE001
        pass
    return None


def _reconcile_terminal_signal(
    envelope: AndroidParticipantTruthEnvelope,
    runtime: Any,
    kind: AndroidParticipantTruthKind,
) -> Tuple[bool, str, str, str]:
    """Reconcile a terminal Android signal (cancel / failure / result).

    Returns (was_reconciled, canonical_update, reject_reason, phase_str).
    """
    if not envelope.has_lookup_key():
        return False, "", "missing_lookup_key", ""

    record = _resolve_tracking_record(envelope, runtime)
    if record is None:
        return False, "", "no_matching_tracking_record", ""

    if _is_record_terminal(record):
        phase_str = str(getattr(record, "phase", "") or "")
        return (
            False,
            "",
            f"v2_terminal_state_wins:record_already_in_{phase_str}",
            phase_str,
        )

    # Map kind → tracker mutation
    if not _TRACKER_AVAILABLE or AcknowledgmentSignal is None:
        return False, "", "tracker_unavailable", ""

    try:
        if kind == AndroidParticipantTruthKind.cancel:
            if apply_acknowledgment_signal is None:
                return False, "", "tracker_unavailable", ""
            updated = apply_acknowledgment_signal(
                record,
                AcknowledgmentSignal.cancelled,
                runtime=runtime,
            )
            update_desc = "cancel_signal_applied→tracking_record_cancelled"
        else:
            if apply_result is None or DelegatedExecutionResult is None:
                return False, "", "tracker_unavailable", ""
            is_success = (
                kind != AndroidParticipantTruthKind.failure
                and envelope.result_success is not False
            )
            result_obj = DelegatedExecutionResult(
                success=is_success,
                result_payload=copy.deepcopy(envelope.result_payload),
                error_detail=(
                    _extract_terminal_error_detail(envelope.payload)
                    if not is_success
                    else ""
                ),
                completed_at=time.time(),
            )
            updated = apply_result(record, result_obj, runtime=runtime)
            update_desc = (
                "result_success_signal_applied→tracking_record_completed_with_result"
                if is_success
                else "result_failure_signal_applied→tracking_record_failed_with_result"
            )
        phase_str = str(getattr(updated, "phase", "") or "")
        return True, update_desc, "", phase_str
    except Exception as exc:  # noqa: BLE001
        return False, "", f"apply_signal_error:{exc}", ""


def _extract_terminal_error_detail(payload: Dict[str, Any]) -> str:
    """Return the most useful terminal error detail from an Android truth payload."""
    return (
        str(payload.get("error_message") or "")
        or str(payload.get("error") or "")
        or str(payload.get("details") or "")
        or "android participant truth terminal failure"
    )


def _reconcile_status_signal(
    envelope: AndroidParticipantTruthEnvelope,
    runtime: Any,
) -> Tuple[bool, str, str, str]:
    """Reconcile an Android status (progress) signal.

    Returns (was_reconciled, canonical_update, reject_reason, phase_str).
    """
    if not envelope.has_lookup_key():
        return False, "", "missing_lookup_key", ""

    record = _resolve_tracking_record(envelope, runtime)
    if record is None:
        return False, "", "no_matching_tracking_record", ""

    if _is_record_terminal(record):
        phase_str = str(getattr(record, "phase", "") or "")
        return False, "", f"v2_terminal_state_wins:record_already_in_{phase_str}", phase_str

    if not _TRACKER_AVAILABLE or AcknowledgmentSignal is None or apply_acknowledgment_signal is None:
        return False, "", "tracker_unavailable", ""

    try:
        updated = apply_acknowledgment_signal(record, AcknowledgmentSignal.progress, runtime=runtime)
        phase_str = str(getattr(updated, "phase", "") or "")
        return True, "status_progress_signal_applied→tracking_record_in_progress", "", phase_str
    except Exception as exc:  # noqa: BLE001
        return False, "", f"apply_signal_error:{exc}", ""


def _reconcile_task_phase(
    envelope: AndroidParticipantTruthEnvelope,
    runtime: Any,
) -> Tuple[bool, str, str, str]:
    """Reconcile Android-reported task phase into the V2 tracking record.

    Only applies the phase if:
    - A matching record exists and is non-terminal (TERMINAL_V2_STATE_WINS_CONFLICT_POLICY).
    - The Android phase maps to a meaningful AcknowledgmentSignal.
    - The mapped signal advances the record (non-trivial transition).

    Returns (was_reconciled, canonical_update, reject_reason, phase_str).
    """
    if not envelope.has_lookup_key():
        return False, "", "missing_lookup_key", ""

    record = _resolve_tracking_record(envelope, runtime)
    if record is None:
        return False, "", "no_matching_tracking_record", ""

    if _is_record_terminal(record):
        phase_str = str(getattr(record, "phase", "") or "")
        return False, "", f"v2_terminal_state_wins:record_already_in_{phase_str}", phase_str

    if not _TRACKER_AVAILABLE or AcknowledgmentSignal is None or apply_acknowledgment_signal is None:
        return False, "", "tracker_unavailable", ""

    phase_map = _get_phase_to_ack_map()
    normalised_phase = (envelope.task_phase_value or "").strip().lower()
    ack_signal = phase_map.get(normalised_phase)
    if ack_signal is None:
        return False, "", f"unmapped_android_phase:{normalised_phase}", ""

    try:
        updated = apply_acknowledgment_signal(record, ack_signal, runtime=runtime)
        phase_str = str(getattr(updated, "phase", "") or "")
        return (
            True,
            f"task_phase_reconciled:android={normalised_phase}→v2_ack={ack_signal}→v2_phase={phase_str}",
            "",
            phase_str,
        )
    except Exception as exc:  # noqa: BLE001
        return False, "", f"apply_signal_error:{exc}", ""


def _reconcile_session_snapshot(
    envelope: AndroidParticipantTruthEnvelope,
    registry: Any,
) -> Tuple[bool, str, str, str]:
    """Validate Android session snapshot against AttachedSessionRegistry.

    Checks session continuity: if Android reports a session_id that is
    present in the registry but NOT in active state, this constitutes a
    conflict (V2 may have superseded or invalidated the session).

    Returns (was_reconciled, canonical_update, reject_reason, phase_str).
    """
    if not envelope.session_id:
        return False, "", "missing_session_id", ""

    if not _REGISTRY_AVAILABLE or registry is None or lookup_active_session is None:
        return (
            False,
            f"{_COMPAT_FALLBACK_NON_CANONICAL}:session_snapshot_registry_unavailable",
            f"registry_unavailable:{_COMPAT_FALLBACK_NON_CANONICAL}",
            "",
        )

    try:
        active_entry = lookup_active_session(envelope.session_id, registry=registry)
        if active_entry is not None:
            registry_device_id = str(getattr(active_entry, "device_id", "") or "")
            runtime_session_id = str(getattr(active_entry, "runtime_session_id", "") or "")
            if not envelope.device_id:
                return (
                    False,
                    f"{_COMPAT_FALLBACK_NON_CANONICAL}:session_snapshot_missing_participant_identity",
                    f"session_snapshot_missing_participant_identity:{_COMPAT_FALLBACK_NON_CANONICAL}",
                    "",
                )
            if registry_device_id and registry_device_id != envelope.device_id:
                return (
                    False,
                    "",
                    "session_snapshot_participant_divergence:"
                    f"android_device_id={envelope.device_id}:"
                    f"canonical_device_id={registry_device_id}",
                    "",
                )
            return (
                True,
                "session_snapshot_continuity_confirmed:"
                f"runtime_attachment_session_id={envelope.session_id}|"
                f"participant_id={envelope.device_id}|"
                f"runtime_session_id={runtime_session_id}",
                "",
                "active",
            )
        else:
            return (
                False,
                "",
                f"session_snapshot_conflict:runtime_attachment_session_id={envelope.session_id}_not_active_in_v2",
                "",
            )
    except Exception as exc:  # noqa: BLE001
        return False, "", f"registry_lookup_error:{exc}", ""


def _build_ownership_context(
    *,
    envelope: AndroidParticipantTruthEnvelope,
    kind: AndroidParticipantTruthKind,
    was_reconciled: bool,
    local_only: bool,
    reject_reason: str,
    canonical_update: str,
) -> Dict[str, Any]:
    participant_identity = (envelope.device_id or "").strip()
    fallback_non_canonical = (
        _COMPAT_FALLBACK_NON_CANONICAL in (reject_reason or "")
        or _COMPAT_FALLBACK_NON_CANONICAL in (canonical_update or "")
    )
    participant_divergence = "participant_divergence" in (reject_reason or "")
    if was_reconciled:
        ownership_status = "canonicalized"
    elif local_only:
        ownership_status = "participant_local_only"
    elif fallback_non_canonical:
        ownership_status = "fallback_non_canonical"
    else:
        ownership_status = "rejected_non_canonical"

    authority_scope = (
        "v2_canonical_orchestration"
        if ownership_status == "canonicalized"
        else "android_participant_local"
    )

    canonical_session_identity: Dict[str, str] = {
        "conversation_session_id": "",
        "control_session_id": "",
        "runtime_attachment_session_id": envelope.session_id or "",
        "source_session_id": envelope.session_id or "",
        "device_id": participant_identity,
    }

    if (
        _SESSION_IDENTITY_AVAILABLE
        and build_canonical_session_identity is not None
        and (envelope.session_id or envelope.payload.get("conversation_session_id"))
    ):
        try:
            runtime_session_claim = _extract_runtime_session_claim(envelope)
            identity = build_canonical_session_identity(
                session_id=envelope.session_id or "",
                device_id=participant_identity,
                runtime_session_id=runtime_session_claim,
                payload=envelope.payload,
                create_session=False,
            )
            canonical_session_identity = identity.as_metadata()
        except Exception:
            pass

    canonical_session_identity["runtime_attachment_session_id"] = (
        canonical_session_identity.get("runtime_attachment_session_id")
        or envelope.session_id
        or ""
    )

    return {
        "truth_kind": kind.value,
        "authority_scope": authority_scope,
        "ownership_status": ownership_status,
        "participant_identity": participant_identity,
        "participant_identity_attached": bool(participant_identity),
        "participant_identity_divergence": participant_divergence,
        "canonical_session_identity": canonical_session_identity,
    }


def _extract_runtime_session_claim(envelope: AndroidParticipantTruthEnvelope) -> str:
    """Extract runtime session claim from Android payload in canonical priority order."""
    payload = envelope.payload or {}
    return str(
        payload.get("runtime_session_id")
        or payload.get("attached_runtime_session_id")
        or payload.get("runtime_attachment_session_id")
        or envelope.session_id
        or ""
    )


def _reconcile_reconciliation_signal(
    envelope: AndroidParticipantTruthEnvelope,
    runtime: Any,
) -> Tuple[bool, str, str, str]:
    """Reconcile an Android explicit reconciliation_signal into V2 canonical state.

    The reconciliation_signal carries a ``phase`` or ``status`` field in its
    payload that represents the Android RuntimeController's current view of
    the execution state.  This is distinct from ``delegated_execution_signal``
    in that it is an explicit push from Android to reconcile V2 state rather
    than a lifecycle event.

    Phase-to-AcknowledgmentSignal mapping
    --------------------------------------
    1. ``task_phase_value`` (extracted from ``payload.phase`` / ``payload.status``)
       is looked up in the ``_get_phase_to_ack_map()`` table.
    2. **Fallback**: if the phase map produces no match (empty or unrecognised
       ``task_phase_value``), the ``result_success`` field is used to infer the
       signal: ``True`` → ``final_result``, ``False`` → ``error``.
    3. If neither source provides a mapping the reconciliation is rejected with
       ``unmapped_reconciliation_phase``.

    Per RECONCILIATION_SIGNAL_DISTINCT_FROM_DELEGATED_POLICY:
    - V2 terminal state still wins (TERMINAL_V2_STATE_WINS_CONFLICT_POLICY).
    - Missing lookup key or missing record → was_reconciled=False.

    Returns (was_reconciled, canonical_update, reject_reason, phase_str).
    """
    if not envelope.has_lookup_key():
        return False, "", "missing_lookup_key", ""

    record = _resolve_tracking_record(envelope, runtime)
    if record is None:
        return False, "", "no_matching_tracking_record", ""

    if _is_record_terminal(record):
        phase_str = str(getattr(record, "phase", "") or "")
        return False, "", f"v2_terminal_state_wins:record_already_in_{phase_str}", phase_str

    if not _TRACKER_AVAILABLE or AcknowledgmentSignal is None or apply_acknowledgment_signal is None:
        return False, "", "tracker_unavailable", ""

    phase_map = _get_phase_to_ack_map()
    # Prefer task_phase_value (extracted from payload.phase / payload.status),
    # falling back to result_success to infer terminal signal.
    normalised_phase = (envelope.task_phase_value or "").strip().lower()
    ack_signal = phase_map.get(normalised_phase)

    if ack_signal is None and envelope.result_success is not None:
        # Infer from result_success when no explicit phase was provided
        ack_signal = (
            AcknowledgmentSignal.final_result
            if envelope.result_success
            else AcknowledgmentSignal.error
        )
        normalised_phase = "success" if envelope.result_success else "failure"

    if ack_signal is None:
        return False, "", f"unmapped_reconciliation_phase:{normalised_phase}", ""

    try:
        updated = apply_acknowledgment_signal(record, ack_signal, runtime=runtime)
        phase_str = str(getattr(updated, "phase", "") or "")
        return (
            True,
            f"reconciliation_signal_applied:android_phase={normalised_phase}"
            f"→v2_ack={ack_signal}→v2_phase={phase_str}",
            "",
            phase_str,
        )
    except Exception as exc:  # noqa: BLE001
        return False, "", f"apply_signal_error:{exc}", ""


def _reconcile_governance_artifact(
    envelope: AndroidParticipantTruthEnvelope,
) -> Tuple[bool, str, str, str]:
    """Reconcile an Android evaluator governance/readiness/acceptance/strategy artifact.

    This is the canonical entry-point for Android-originated evaluator artifacts
    (DeviceReadinessArtifact, DeviceGovernanceArtifact, DeviceAcceptanceArtifact,
    DeviceStrategyArtifact) that have been forwarded via the ``governance_artifact``
    truth kind.

    Unlike advisory truth kinds (``readiness_assessment``, ``runtime_state``), a
    ``governance_artifact`` is a **first-class canonical gate input**.  It is
    reconciled by calling ``align_and_record()`` from
    :mod:`~core.flow_level_truth_ownership`, which writes a
    :class:`~core.flow_level_truth_ownership.FlowTruthDecisionArtifact` to
    :class:`~core.flow_level_truth_ownership.FlowTruthAlignmentRuntime`.  This
    ensures the artifact is visible to
    :meth:`~core.delegated_flow_readiness_gate.DelegatedFlowReadinessGate._evaluate_truth_ownership`
    as a canonical dimension input.

    Policy: GOVERNANCE_ARTIFACT_IS_CANONICAL_GATE_INPUT_POLICY (defined above).

    Returns (was_reconciled, canonical_update, reject_reason, phase_str).
    """
    if not _FLOW_TRUTH_ALIGNMENT_AVAILABLE or _align_and_record is None or _FlowTruthAlignmentContext is None:
        # flow_level_truth_ownership unavailable — treat as audit-only with no gate visibility
        return (
            False,
            "",
            "flow_truth_alignment_unavailable:governance_artifact_not_aligned",
            "",
        )

    try:
        ctx = _FlowTruthAlignmentContext(
            truth_kind="governance_artifact",
            task_phase_value=envelope.task_phase_value or "",
            v2_canonical_flow_phase="",  # no specific flow phase required
            device_posture="",
            posture_changed=False,
            compat_influence_active=False,
            delegated_flow_id=envelope.contract_id or envelope.session_id or "",
            session_id=envelope.session_id or "",
            contract_id=envelope.contract_id or "",
            task_id=envelope.task_id or "",
            trace_id=envelope.trace_id or "",
            truth_payload=dict(envelope.payload),
        )
        artifact = _align_and_record(ctx)
        canonical_update = (
            f"governance_artifact_aligned:"
            f"device_id={envelope.device_id or ''}"
            f"→decision={artifact.decision.value}"
            f"→semantic={artifact.semantic_kind.value}"
        )
        return True, canonical_update, "", ""
    except Exception as exc:  # noqa: BLE001
        return False, "", f"governance_artifact_align_error:{exc}", ""


def _reconcile_recovery_state(
    envelope: AndroidParticipantTruthEnvelope,
) -> Tuple[bool, str, str, str, Dict[str, Any]]:
    """Route an Android recovery_state truth kind through the recovery-state router.

    This handler implements explicit routing for Android continuity recovery-state
    semantics.  It calls ``route_recovery_state_from_payload()`` from
    :mod:`~core.android_continuity_recovery_state_router` to map the Android
    recovery phase to an explicit V2 canonical handling route.

    Routing outcomes per recovery phase
    ------------------------------------
    - ``reconnect_initiated`` / ``recovery_in_progress`` →
      ``mark_recovery_pending``: advisory/pending, local_only=True, no canonical
      state mutation.
    - ``recovered_inflight`` →
      ``accept_advisory_evidence``: advisory evidence only, local_only=True.
      MUST NOT directly produce canonical closure.
    - ``stale_recovery_artifact`` →
      ``reject_stale_artifact``: rejected outright, was_reconciled=False,
      reject_reason set.
    - ``reconciliation_required`` →
      ``trigger_reconciliation``: was_reconciled=False (reconciliation path must
      be invoked by the caller), reject_reason=reconciliation_path_required.
    - ``lost_inflight`` →
      ``require_closure_review``: was_reconciled=False, reject_reason set,
      closure review required.
    - ``unknown`` →
      ``accept_advisory_evidence`` (degraded): advisory, local_only=True.

    Policy: RECOVERY_STATE_MUST_BE_EXPLICITLY_ROUTED_POLICY.

    Returns (was_reconciled, canonical_update, reject_reason, phase_str).
    """
    if not _RECOVERY_STATE_ROUTER_AVAILABLE or _route_recovery_state_from_payload is None:
        # Router unavailable — fall back to advisory-only handling
        return (
            False,
            "",
            "recovery_state_router_unavailable:treated_as_advisory",
            "",
            {},
        )

    try:
        decision = _route_recovery_state_from_payload(
            envelope.payload,
            device_id=envelope.device_id or "",
            session_id=envelope.session_id or "",
            task_id=envelope.task_id or "",
        )
    except Exception as exc:  # noqa: BLE001
        return False, "", f"recovery_state_routing_error:{exc}", "", {}

    try:
        routing_decision = decision.to_dict()
    except Exception as exc:  # noqa: BLE001
        # Preserve the stable observability subset of RecoveryStateRoutingDecision
        # even if full serialisation fails.  Downstream review/audit consumers rely
        # on these keys to understand how Android recovery evidence was routed.
        routing_decision = {
            "recovery_phase": decision.recovery_phase.value,
            "v2_route": decision.v2_route.value,
            "policy_reference": decision.policy_reference,
            "diagnosis": f"{decision.diagnosis} to_dict_error:{exc}",
            "is_canonical_closure_blocked": decision.is_canonical_closure_blocked,
            "is_advisory_only": decision.is_advisory_only,
            "is_degraded": decision.is_degraded,
            "device_id": decision.device_id,
            "session_id": decision.session_id,
            "task_id": decision.task_id,
            "raw_phase_str": decision.raw_phase_str,
        }

    route_value = decision.v2_route.value

    if route_value == "reject_stale_artifact":
        return (
            False,
            "",
            f"recovery_state_rejected:stale_recovery_artifact:"
            f"phase={decision.recovery_phase.value}",
            "",
            routing_decision,
        )

    if route_value == "trigger_reconciliation":
        return (
            False,
            "",
            f"recovery_state_reconciliation_path_required:"
            f"phase={decision.recovery_phase.value}",
            "",
            routing_decision,
        )

    if route_value == "require_closure_review":
        return (
            False,
            "",
            f"recovery_state_closure_review_required:"
            f"phase={decision.recovery_phase.value}:lost_inflight",
            "",
            routing_decision,
        )

    # mark_recovery_pending or accept_advisory_evidence — advisory/local-only
    # was_reconciled=False, local_only handled by caller (advisory branch)
    canonical_update = (
        f"recovery_state_advisory_routed:"
        f"phase={decision.recovery_phase.value}"
        f"→route={route_value}"
        f"→degraded={decision.is_degraded}"
    )
    return False, canonical_update, "", "", routing_decision


def ingest_android_participant_truth_message(
    message: Dict[str, Any],
    *,
    runtime: Optional[Any] = None,
    registry: Optional[Any] = None,
) -> AndroidParticipantReconcileOutcome:
    """Convenience wrapper: extract envelope from raw message and reconcile.

    This is the single-call entry-point for gateway handlers that receive
    Android participant/session/runtime truth messages and want to ingest
    them into V2 canonical orchestration state.

    Parameters
    ----------
    message:
        Raw inbound Android truth message as a dict.
    runtime:
        Optional :class:`~core.delegated_runtime_execution_tracker.DelegatedExecutionTrackingRuntime`.
    registry:
        Optional :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry`.

    Returns
    -------
    AndroidParticipantReconcileOutcome
    """
    envelope = extract_participant_truth_envelope(message)
    return reconcile_android_participant_truth(envelope, runtime=runtime, registry=registry)


# ---------------------------------------------------------------------------
# PR-10: Last reconciliation outcome — operator review surface support
# ---------------------------------------------------------------------------

# Advisory-only field names that are never applied to V2 canonical state.
_ADVISORY_ONLY_RECONCILE_FIELDS = ("readiness_assessment", "runtime_state")

_last_reconciliation_lock: _threading.Lock = _threading.Lock()
_last_reconciliation_outcome: Optional[Dict[str, Any]] = None


def _record_last_reconciliation_outcome(outcome: AndroidParticipantReconcileOutcome) -> None:
    """Record the last reconciliation outcome for operator review surface access.

    Called internally after every reconcile_android_participant_truth() call.
    Stores a serialisable snapshot for the PR-10 orchestration review surface.

    This function is **observational only** and MUST NOT influence canonical
    reconciliation logic.
    """
    global _last_reconciliation_outcome  # noqa: PLW0603
    try:
        envelope = outcome.envelope
        snapshot: Dict[str, Any] = {
            "was_reconciled": outcome.was_reconciled,
            "v2_terminal_state_blocked": bool(
                outcome.reject_reason and "terminal" in outcome.reject_reason.lower()
            ),
            "advisory_only_fields_skipped": list(_ADVISORY_ONLY_RECONCILE_FIELDS)
            if outcome.local_only
            else [],
            "applied_signal_types": [outcome.canonical_update] if outcome.was_reconciled else [],
            "device_id": envelope.device_id if envelope else None,
            "task_id": envelope.task_id if envelope else None,
            "reject_reason": outcome.reject_reason,
            "recovery_state_routing": dict(outcome.recovery_state_routing),
            "schema_gate_evidence": dict(outcome.schema_gate_evidence),
            "ownership_context": dict(outcome.ownership_context),
        }
        with _last_reconciliation_lock:
            _last_reconciliation_outcome = snapshot
    except Exception:  # noqa: BLE001
        pass


def get_last_reconciliation_outcome() -> Optional[Dict[str, Any]]:
    """Return the most recent Android/V2 reconciliation outcome as a dict.

    This is a **read-only observability accessor** for the PR-10 operator
    review surface.  It returns the outcome of the last call to
    :func:`reconcile_android_participant_truth` in this process.

    Returns ``None`` when no reconciliation has been performed since startup.

    The returned dict keys are:

    - ``was_reconciled`` — bool
    - ``v2_terminal_state_blocked`` — bool
    - ``advisory_only_fields_skipped`` — list[str]
    - ``applied_signal_types`` — list[str]
    - ``device_id`` — str or None
    - ``task_id`` — str or None
    - ``reject_reason`` — str
    - ``recovery_state_routing`` — dict[str, Any]
    """
    with _last_reconciliation_lock:
        if _last_reconciliation_outcome is None:
            return None
        return dict(_last_reconciliation_outcome)


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Authority and sentinel constants
    "ANDROID_PARTICIPANT_TRUTH_INGRESS_AUTHORITY",
    "V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_SENTINEL",
    "ANDROID_PARTICIPANT_TRUTH_INGRESS_PR4V2_SENTINEL",
    # Policy sentinels
    "V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY",
    "ANDROID_TRUTH_IS_ADVISORY_FOR_DEVICE_SCOPE_POLICY",
    "CANCEL_FAILURE_RESULT_AFFECT_CANONICAL_STATE_POLICY",
    "STATUS_SIGNAL_EMITS_PROGRESS_EVENT_POLICY",
    "TASK_PHASE_RECONCILED_WITH_TRACKING_RECORD_POLICY",
    "SESSION_SNAPSHOT_VALIDATES_REGISTRY_CONTINUITY_POLICY",
    "READINESS_ASSESSMENT_IS_ADVISORY_POLICY",
    "RUNTIME_STATE_IS_AUDIT_ONLY_POLICY",
    "TERMINAL_V2_STATE_WINS_CONFLICT_POLICY",
    "RECONCILE_IS_NON_DESTRUCTIVE_ON_MISS_POLICY",
    "RECONCILE_EMITS_AUDIT_EVENT_ALWAYS_POLICY",
    "IDENTITY_FIELDS_ARE_VERBATIM_POLICY",
    "GOVERNANCE_ARTIFACT_IS_CANONICAL_GATE_INPUT_POLICY",
    "RECOVERY_STATE_MUST_BE_EXPLICITLY_ROUTED_POLICY",
    # Enums
    "AndroidParticipantTruthKind",
    # Dataclasses
    "AndroidParticipantTruthEnvelope",
    "AndroidParticipantReconcileOutcome",
    # Functions
    "extract_participant_truth_envelope",
    "reconcile_android_participant_truth",
    "ingest_android_participant_truth_message",
    # PR-10: operator review surface support
    "get_last_reconciliation_outcome",
]
