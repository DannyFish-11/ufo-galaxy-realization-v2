"""core/android_delegated_runtime_audit.py
==========================================
PR-10-V2: Unified Audit / Observability Layer for Android Delegated Runtime Flows.

Establishes a **single** audit surface that records every key wire event in the
Android delegated-runtime / handoff / takeover / reconciliation flow.

Background
----------
Previous PR packages (PR-02-V2 through PR-08-V2) wired the Android delegated
execution protocol into the V2 gateway — but the key lifecycle events
(delegated_execution_signal, handoff_envelope_v2_result,
TAKEOVER_REQUEST / TAKEOVER_RESPONSE, reconciliation_signal, participant truth
terminal updates) were each logged in isolation with DEBUG/INFO calls inside
their respective handlers.  There was no unified observability surface that
allowed a developer to ask *"show me every audit event for task_id X across the
full handoff → takeover → reconciliation chain"*.

This module closes that gap by providing:

1. ``AndroidDelegatedAuditEventKind`` — canonical string constants for the six
   key wire-event types.  These string values are stable and must not be
   renamed.

2. ``AndroidDelegatedAuditRecord`` — a thin, typed extension of
   :class:`~core.audit_event_semantics.AuditEventRecord` that carries
   Android-specific correlation fields (``handoff_id``, ``takeover_id``,
   ``contract_id``, ``device_id``, ``participant_role``, ``state_transition``).

3. ``AndroidDelegatedRuntimeAuditRecorder`` — singleton class that:

   * wraps the shared :class:`~core.audit_event_semantics.AuditEventSemantics`
     singleton so that Android delegated audit records are visible alongside
     all other system audit records;
   * maintains a secondary in-process ring buffer (size 512) of
     :class:`AndroidDelegatedAuditRecord` objects so callers can ask
     *"all events for task_id X"* without scanning the full audit ring.

4. Convenience recording helpers — one per event type — that handlers call
   after processing each wire event:

   * :func:`record_delegated_execution_signal`
   * :func:`record_handoff_v2_result`
   * :func:`record_takeover_request`
   * :func:`record_takeover_response`
   * :func:`record_reconciliation_signal`
   * :func:`record_participant_truth_terminal_update`

5. Query helpers:

   * :func:`get_android_audit_for_task` — all records for a given task_id
   * :func:`get_android_audit_for_session` — all records for a given session_id
   * :func:`android_audit_snapshot` — full ring snapshot

Design goals
------------
* **Non-intrusive** — handlers import and call a single helper; the helper
  never raises, never blocks, and degrades gracefully when the underlying
  :class:`~core.audit_event_semantics.AuditEventSemantics` is unavailable.
* **Unified** — all Android delegated-runtime events flow through the same
  singleton recorder so they are indexed together.
* **Queryable by task** — the secondary task-indexed store makes it cheap to
  reconstruct the full timeline for a single task.
* **JSON-serialisable** — :class:`AndroidDelegatedAuditRecord` exposes
  ``to_dict()`` / ``to_json()`` so that the records can be surfaced through the
  existing ``/api/v1/audit`` routes.

Authority sentinel
------------------
``ANDROID_DELEGATED_RUNTIME_AUDIT_AUTHORITY`` — import this sentinel to assert
that a consumer uses the canonical Android delegated runtime audit layer.

Public API
----------
Sentinel / version::

    ANDROID_DELEGATED_RUNTIME_AUDIT_AUTHORITY
    ANDROID_DELEGATED_RUNTIME_AUDIT_CONTRACT_VERSION

Event kind constants::

    AndroidDelegatedAuditEventKind

Dataclass::

    AndroidDelegatedAuditRecord

Class::

    AndroidDelegatedRuntimeAuditRecorder

Singleton accessors::

    get_android_delegated_audit_recorder() -> AndroidDelegatedRuntimeAuditRecorder
    reset_android_delegated_audit_recorder() -> None   # testing only

Recording helpers::

    record_delegated_execution_signal(...)  -> AndroidDelegatedAuditRecord
    record_handoff_v2_result(...)           -> AndroidDelegatedAuditRecord
    record_takeover_request(...)            -> AndroidDelegatedAuditRecord
    record_takeover_response(...)           -> AndroidDelegatedAuditRecord
    record_reconciliation_signal(...)       -> AndroidDelegatedAuditRecord
    record_participant_truth_terminal_update(...) -> AndroidDelegatedAuditRecord

Query helpers::

    get_android_audit_for_task(task_id)    -> List[AndroidDelegatedAuditRecord]
    get_android_audit_for_session(sid)     -> List[AndroidDelegatedAuditRecord]
    android_audit_snapshot()               -> AndroidDelegatedAuditSnapshot
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.AndroidDelegatedRuntimeAudit")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

ANDROID_DELEGATED_RUNTIME_AUDIT_AUTHORITY: str = (
    "ANDROID_DELEGATED_RUNTIME_AUDIT_V1"
)
"""Sentinel: import to assert that the unified Android delegated runtime audit
layer is available.  Must be a non-empty string."""

ANDROID_DELEGATED_RUNTIME_AUDIT_CONTRACT_VERSION: str = "1.0"
"""Schema version of this audit contract."""

# ---------------------------------------------------------------------------
# Event kind constants
# ---------------------------------------------------------------------------


class AndroidDelegatedAuditEventKind:
    """Canonical string constants for Android delegated runtime wire events.

    String values are stable identifiers — do not rename them.
    """

    DELEGATED_EXECUTION_SIGNAL: str = "android_delegated_execution_signal"
    """Android delegated execution lifecycle signal received (PR-16 ingress)."""

    HANDOFF_V2_RESULT: str = "android_handoff_v2_result"
    """Android HandoffEnvelopeV2 uplink response received (PR-02-V2 ingress)."""

    TAKEOVER_REQUEST: str = "android_takeover_request"
    """V2 issued a TAKEOVER_REQUEST downlink to the Android runtime."""

    TAKEOVER_RESPONSE: str = "android_takeover_response"
    """Android returned a TAKEOVER_RESPONSE (accept/reject) to V2."""

    RECONCILIATION_SIGNAL: str = "android_reconciliation_signal"
    """Android RuntimeController pushed a reconciliation_signal to V2."""

    PARTICIPANT_TRUTH_TERMINAL_UPDATE: str = (
        "android_participant_truth_terminal_update"
    )
    """Android participant truth ingress applied a terminal state update to V2
    canonical orchestration records."""

    # Convenience tuple for iteration
    ALL: tuple = (
        DELEGATED_EXECUTION_SIGNAL,
        HANDOFF_V2_RESULT,
        TAKEOVER_REQUEST,
        TAKEOVER_RESPONSE,
        RECONCILIATION_SIGNAL,
        PARTICIPANT_TRUTH_TERMINAL_UPDATE,
    )


# ---------------------------------------------------------------------------
# AndroidDelegatedAuditRecord
# ---------------------------------------------------------------------------


@dataclass
class AndroidDelegatedAuditRecord:
    """Lightweight audit record for a single Android delegated runtime wire event.

    Extends the fields required by
    :class:`~core.audit_event_semantics.AuditEventRecord` with additional
    Android-specific correlation fields so that the full chain —
    handoff → takeover → reconciliation — can be reconstructed for a single
    task.

    All fields default to empty/None so that callers only need to populate the
    fields that are relevant to their event type.
    """

    # -- Identity / unique ID -----------------------------------------------
    audit_id: str = field(
        default_factory=lambda: f"adra_{uuid.uuid4().hex[:16]}"
    )
    recorded_at: float = field(default_factory=time.time)

    # -- Event kind (one of AndroidDelegatedAuditEventKind.*) ---------------
    kind: str = AndroidDelegatedAuditEventKind.DELEGATED_EXECUTION_SIGNAL

    # -- Task / session traceability ----------------------------------------
    task_id: str = ""
    session_id: str = ""
    trace_id: str = ""

    # -- Android correlation fields ----------------------------------------
    device_id: str = ""
    contract_id: str = ""
    handoff_id: str = ""
    takeover_id: str = ""
    participant_role: str = ""
    """The participant / runtime role (e.g. 'android', 'v2', 'delegated')."""

    # -- State transition summary ------------------------------------------
    state_transition: str = ""
    """Human-readable summary of the state change, e.g.
    'phase=running → phase=completed' or 'takeover accepted'."""

    was_successful: Optional[bool] = None
    """For result/response events: whether the outcome was successful."""

    reject_reason: str = ""
    """For rejected/skipped events: why the event was not applied."""

    # -- Emitting component --------------------------------------------------
    source: str = ""
    """Component / handler that emitted this audit record."""

    # -- Free-form message --------------------------------------------------
    message: str = ""

    # -- Opaque extra payload -----------------------------------------------
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "audit_id": self.audit_id,
            "recorded_at": self.recorded_at,
            "kind": self.kind,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "device_id": self.device_id,
            "contract_id": self.contract_id,
            "handoff_id": self.handoff_id,
            "takeover_id": self.takeover_id,
            "participant_role": self.participant_role,
            "state_transition": self.state_transition,
            "was_successful": self.was_successful,
            "reject_reason": self.reject_reason,
            "source": self.source,
            "message": self.message,
            "payload": self.payload,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict(), default=str)


# ---------------------------------------------------------------------------
# AndroidDelegatedAuditSnapshot
# ---------------------------------------------------------------------------


@dataclass
class AndroidDelegatedAuditSnapshot:
    """Point-in-time snapshot of the Android delegated runtime audit ring."""

    snapshot_id: str = field(
        default_factory=lambda: f"adrasnap_{uuid.uuid4().hex[:12]}"
    )
    generated_at: float = field(default_factory=time.time)
    event_count: int = 0
    recent_events: List[Dict[str, Any]] = field(default_factory=list)
    authority: str = ANDROID_DELEGATED_RUNTIME_AUDIT_AUTHORITY
    contract_version: str = ANDROID_DELEGATED_RUNTIME_AUDIT_CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "generated_at": self.generated_at,
            "event_count": self.event_count,
            "recent_events": self.recent_events,
            "authority": self.authority,
            "contract_version": self.contract_version,
        }


# ---------------------------------------------------------------------------
# Lazy import helper for AuditEventSemantics
# ---------------------------------------------------------------------------


def _get_shared_semantics():
    """Return the shared AuditEventSemantics singleton, or None on failure."""
    try:
        from core.audit_event_semantics import (
            AuditEventRecord,
            get_audit_event_semantics,
        )

        return get_audit_event_semantics(), AuditEventRecord
    except Exception:  # noqa: BLE001
        return None, None


# ---------------------------------------------------------------------------
# AndroidDelegatedRuntimeAuditRecorder
# ---------------------------------------------------------------------------


class AndroidDelegatedRuntimeAuditRecorder:
    """Singleton recorder for Android delegated runtime audit events.

    Maintains a 512-entry ring buffer of
    :class:`AndroidDelegatedAuditRecord` objects and a secondary
    task-keyed index so callers can efficiently retrieve all events for a
    given task.

    Records are also forwarded to the shared
    :class:`~core.audit_event_semantics.AuditEventSemantics` singleton so
    that Android delegated events are visible alongside other system audit
    events in the standard audit query routes.
    """

    _MAX_RING: int = 512

    def __init__(self) -> None:
        self._ring: Deque[AndroidDelegatedAuditRecord] = deque(
            maxlen=self._MAX_RING
        )
        self._by_task: Dict[str, List[AndroidDelegatedAuditRecord]] = {}
        self._by_session: Dict[str, List[AndroidDelegatedAuditRecord]] = {}

    # ------------------------------------------------------------------
    # Core recording
    # ------------------------------------------------------------------

    def record(
        self, record: AndroidDelegatedAuditRecord
    ) -> AndroidDelegatedAuditRecord:
        """Append *record* to the ring buffer and secondary indexes.

        Forwards a corresponding lightweight entry to the shared
        :class:`~core.audit_event_semantics.AuditEventSemantics` ring so
        that Android delegated events are visible in standard audit queries.

        Never raises; all exceptions are caught and logged at DEBUG level.
        """
        try:
            self._ring.append(record)
            if record.task_id:
                self._by_task.setdefault(record.task_id, []).append(record)
            if record.session_id:
                self._by_session.setdefault(record.session_id, []).append(
                    record
                )

            # Forward to shared AuditEventSemantics ring
            semantics, AuditEventRecord = _get_shared_semantics()
            if semantics is not None and AuditEventRecord is not None:
                try:
                    shared_rec = AuditEventRecord(
                        kind=record.kind,
                        task_id=record.task_id,
                        trace_id=record.trace_id,
                        session_id=record.session_id,
                        source=record.source,
                        message=record.message,
                        payload={
                            "device_id": record.device_id,
                            "contract_id": record.contract_id,
                            "handoff_id": record.handoff_id,
                            "takeover_id": record.takeover_id,
                            "participant_role": record.participant_role,
                            "state_transition": record.state_transition,
                            "was_successful": record.was_successful,
                            "reject_reason": record.reject_reason,
                            **record.payload,
                        },
                    )
                    semantics.record(shared_rec)
                except Exception as _exc:  # noqa: BLE001
                    logger.debug(
                        "AndroidDelegatedRuntimeAuditRecorder: "
                        "shared semantics forward skipped: %s",
                        _exc,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "AndroidDelegatedRuntimeAuditRecorder.record failed "
                "(non-fatal): %s",
                exc,
            )
        return record

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_by_task(
        self, task_id: str
    ) -> List[AndroidDelegatedAuditRecord]:
        """Return all audit records for *task_id* in insertion order."""
        return list(self._by_task.get(task_id, []))

    def get_by_session(
        self, session_id: str
    ) -> List[AndroidDelegatedAuditRecord]:
        """Return all audit records for *session_id* in insertion order."""
        return list(self._by_session.get(session_id, []))

    def get_by_kind(
        self, kind: str
    ) -> List[AndroidDelegatedAuditRecord]:
        """Return all ring entries matching *kind*."""
        return [r for r in self._ring if r.kind == kind]

    def all_events(self) -> List[AndroidDelegatedAuditRecord]:
        """Return a snapshot copy of all ring entries."""
        return list(self._ring)

    def snapshot(self) -> AndroidDelegatedAuditSnapshot:
        """Return an :class:`AndroidDelegatedAuditSnapshot`."""
        recent = list(self._ring)[-20:]
        return AndroidDelegatedAuditSnapshot(
            event_count=len(self._ring),
            recent_events=[r.to_dict() for r in recent],
        )


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

_RECORDER: Optional[AndroidDelegatedRuntimeAuditRecorder] = None


def get_android_delegated_audit_recorder() -> AndroidDelegatedRuntimeAuditRecorder:
    """Return the process-wide singleton recorder."""
    global _RECORDER
    if _RECORDER is None:
        _RECORDER = AndroidDelegatedRuntimeAuditRecorder()
    return _RECORDER


def reset_android_delegated_audit_recorder() -> None:
    """Reset the singleton — for testing only."""
    global _RECORDER
    _RECORDER = None


# ---------------------------------------------------------------------------
# Convenience recording helpers
# ---------------------------------------------------------------------------


def record_delegated_execution_signal(
    *,
    task_id: str = "",
    session_id: str = "",
    trace_id: str = "",
    device_id: str = "",
    contract_id: str = "",
    signal_kind: str = "",
    signal_id: str = "",
    emission_seq: Any = None,
    phase: str = "",
    was_updated: bool = False,
    reject_reason: str = "",
    source: str = "android_handler.delegated_signal",
    extra: Optional[Dict[str, Any]] = None,
) -> AndroidDelegatedAuditRecord:
    """Record receipt of an Android ``delegated_execution_signal`` wire event.

    Parameters
    ----------
    task_id, session_id, trace_id, device_id, contract_id:
        Identity fields extracted from the envelope.
    signal_kind:
        The :class:`~core.android_execution_signal_reconciler.DelegatedSignalKind`
        value (e.g. ``"result"``, ``"ack"``, ``"progress"``).
    signal_id:
        Unique ID assigned to this signal by Android.
    emission_seq:
        Monotonic emission sequence number from Android.
    phase:
        Resulting phase after reconciliation (e.g. ``"completed"``).
    was_updated:
        Whether the signal caused a canonical state update.
    reject_reason:
        Non-empty when the signal was rejected / skipped.
    source:
        Emitting component name.
    extra:
        Optional additional key/value pairs to include in payload.
    """
    state_transition = ""
    if signal_kind and phase:
        state_transition = f"signal={signal_kind} → phase={phase}"
    elif signal_kind:
        state_transition = f"signal={signal_kind}"

    rec = AndroidDelegatedAuditRecord(
        kind=AndroidDelegatedAuditEventKind.DELEGATED_EXECUTION_SIGNAL,
        task_id=task_id,
        session_id=session_id,
        trace_id=trace_id,
        device_id=device_id,
        contract_id=contract_id,
        participant_role="android",
        state_transition=state_transition,
        was_successful=was_updated if reject_reason == "" else None,
        reject_reason=reject_reason,
        source=source,
        message=(
            f"delegated_execution_signal kind={signal_kind!r} "
            f"updated={was_updated}"
        ),
        payload={
            "signal_kind": signal_kind,
            "signal_id": signal_id,
            "emission_seq": emission_seq,
            "phase": phase,
            **(extra or {}),
        },
    )
    return get_android_delegated_audit_recorder().record(rec)


def record_handoff_v2_result(
    *,
    task_id: str = "",
    session_id: str = "",
    trace_id: str = "",
    device_id: str = "",
    handoff_id: str = "",
    response_kind: str = "",
    was_correlated: bool = False,
    callback_invoked: bool = False,
    reject_reason: str = "",
    source: str = "android_handler.handoff_v2_result",
    extra: Optional[Dict[str, Any]] = None,
) -> AndroidDelegatedAuditRecord:
    """Record receipt of an Android HandoffEnvelopeV2 uplink response.

    Parameters
    ----------
    task_id, session_id, trace_id, device_id:
        Identity fields extracted from the envelope.
    handoff_id:
        The handoff correlation identifier.
    response_kind:
        The :class:`~contracts.android_handoff_response.HandoffResponseKind`
        value (e.g. ``"result"``, ``"ack"``, ``"failure"``).
    was_correlated:
        Whether the response was successfully correlated to a pending dispatch.
    callback_invoked:
        Whether the registered callback was invoked.
    reject_reason:
        Non-empty when correlation failed.
    source:
        Emitting component name.
    extra:
        Optional additional key/value pairs.
    """
    state_transition = f"handoff_response kind={response_kind}"
    if was_correlated:
        state_transition += " correlated=true"
    if callback_invoked:
        state_transition += " callback=invoked"

    rec = AndroidDelegatedAuditRecord(
        kind=AndroidDelegatedAuditEventKind.HANDOFF_V2_RESULT,
        task_id=task_id,
        session_id=session_id,
        trace_id=trace_id,
        device_id=device_id,
        handoff_id=handoff_id,
        participant_role="android",
        state_transition=state_transition,
        was_successful=was_correlated,
        reject_reason=reject_reason,
        source=source,
        message=(
            f"handoff_v2_result kind={response_kind!r} "
            f"correlated={was_correlated}"
        ),
        payload={
            "response_kind": response_kind,
            "callback_invoked": callback_invoked,
            **(extra or {}),
        },
    )
    return get_android_delegated_audit_recorder().record(rec)


def record_takeover_request(
    *,
    task_id: str = "",
    session_id: str = "",
    trace_id: str = "",
    device_id: str = "",
    takeover_id: str = "",
    reason: str = "",
    source: str = "android_bridge.takeover",
    extra: Optional[Dict[str, Any]] = None,
) -> AndroidDelegatedAuditRecord:
    """Record that V2 issued a TAKEOVER_REQUEST downlink to Android.

    Parameters
    ----------
    task_id, session_id, trace_id, device_id:
        Identity fields for the task being taken over.
    takeover_id:
        Unique identifier assigned to this takeover request.
    reason:
        Human-readable reason for the takeover.
    source:
        Emitting component name.
    extra:
        Optional additional key/value pairs.
    """
    rec = AndroidDelegatedAuditRecord(
        kind=AndroidDelegatedAuditEventKind.TAKEOVER_REQUEST,
        task_id=task_id,
        session_id=session_id,
        trace_id=trace_id,
        device_id=device_id,
        takeover_id=takeover_id,
        participant_role="v2",
        state_transition=f"takeover_request issued takeover_id={takeover_id!r}",
        was_successful=None,
        source=source,
        message=f"takeover_request issued to device={device_id!r}",
        payload={
            "reason": reason,
            **(extra or {}),
        },
    )
    return get_android_delegated_audit_recorder().record(rec)


def record_takeover_response(
    *,
    task_id: str = "",
    session_id: str = "",
    trace_id: str = "",
    device_id: str = "",
    takeover_id: str = "",
    accepted: bool = False,
    reason: str = "",
    source: str = "android_handler.takeover_response",
    extra: Optional[Dict[str, Any]] = None,
) -> AndroidDelegatedAuditRecord:
    """Record receipt of an Android ``takeover_response`` wire event.

    Parameters
    ----------
    task_id, session_id, trace_id, device_id:
        Identity fields extracted from the message.
    takeover_id:
        Correlation identifier matching the original takeover_request.
    accepted:
        Whether Android accepted (True) or rejected (False) the takeover.
    reason:
        Optional human-readable reason from Android.
    source:
        Emitting component name.
    extra:
        Optional additional key/value pairs.
    """
    decision = "accepted" if accepted else "rejected"
    rec = AndroidDelegatedAuditRecord(
        kind=AndroidDelegatedAuditEventKind.TAKEOVER_RESPONSE,
        task_id=task_id,
        session_id=session_id,
        trace_id=trace_id,
        device_id=device_id,
        takeover_id=takeover_id,
        participant_role="android",
        state_transition=f"takeover_response decision={decision}",
        was_successful=accepted,
        source=source,
        message=(
            f"takeover_response from device={device_id!r} "
            f"takeover_id={takeover_id!r} decision={decision}"
        ),
        payload={
            "accepted": accepted,
            "reason": reason,
            **(extra or {}),
        },
    )
    return get_android_delegated_audit_recorder().record(rec)


def record_reconciliation_signal(
    *,
    task_id: str = "",
    session_id: str = "",
    trace_id: str = "",
    device_id: str = "",
    contract_id: str = "",
    truth_kind: str = "",
    phase: str = "",
    was_reconciled: bool = False,
    canonical_update: str = "",
    reject_reason: str = "",
    source: str = "android_handler.reconciliation_signal",
    extra: Optional[Dict[str, Any]] = None,
) -> AndroidDelegatedAuditRecord:
    """Record receipt of an Android ``reconciliation_signal`` wire event.

    Parameters
    ----------
    task_id, session_id, trace_id, device_id, contract_id:
        Identity fields extracted from the envelope.
    truth_kind:
        The :class:`~core.android_participant_truth_ingress.AndroidParticipantTruthKind`
        value (e.g. ``"task_phase"``, ``"result"``, ``"cancel"``).
    phase:
        Resulting tracking record phase after reconciliation.
    was_reconciled:
        Whether the signal caused a canonical state update.
    canonical_update:
        Human-readable description of V2 canonical state that was updated.
    reject_reason:
        Non-empty when reconciliation was rejected.
    source:
        Emitting component name.
    extra:
        Optional additional key/value pairs.
    """
    state_transition = ""
    if truth_kind and phase:
        state_transition = f"truth={truth_kind} → phase={phase}"
    elif canonical_update:
        state_transition = canonical_update

    rec = AndroidDelegatedAuditRecord(
        kind=AndroidDelegatedAuditEventKind.RECONCILIATION_SIGNAL,
        task_id=task_id,
        session_id=session_id,
        trace_id=trace_id,
        device_id=device_id,
        contract_id=contract_id,
        participant_role="android",
        state_transition=state_transition,
        was_successful=was_reconciled if reject_reason == "" else None,
        reject_reason=reject_reason,
        source=source,
        message=(
            f"reconciliation_signal truth_kind={truth_kind!r} "
            f"reconciled={was_reconciled}"
        ),
        payload={
            "truth_kind": truth_kind,
            "phase": phase,
            "canonical_update": canonical_update,
            **(extra or {}),
        },
    )
    return get_android_delegated_audit_recorder().record(rec)


def record_participant_truth_terminal_update(
    *,
    task_id: str = "",
    session_id: str = "",
    trace_id: str = "",
    device_id: str = "",
    contract_id: str = "",
    truth_kind: str = "",
    terminal_phase: str = "",
    canonical_update: str = "",
    source: str = "android_participant_truth_ingress",
    extra: Optional[Dict[str, Any]] = None,
) -> AndroidDelegatedAuditRecord:
    """Record that Android participant truth ingress applied a terminal state update.

    This is distinct from :func:`record_reconciliation_signal`: it records the
    moment that the participant truth ingress module determines that the V2
    canonical tracking record must transition to a **terminal** phase
    (completed / failed / cancelled).

    Parameters
    ----------
    task_id, session_id, trace_id, device_id, contract_id:
        Identity fields extracted from the truth envelope.
    truth_kind:
        The truth kind that triggered the terminal update.
    terminal_phase:
        The terminal phase that was applied to the V2 canonical record
        (e.g. ``"completed"``, ``"failed"``, ``"cancelled"``).
    canonical_update:
        Human-readable description of the V2 canonical update.
    source:
        Emitting component name.
    extra:
        Optional additional key/value pairs.
    """
    rec = AndroidDelegatedAuditRecord(
        kind=AndroidDelegatedAuditEventKind.PARTICIPANT_TRUTH_TERMINAL_UPDATE,
        task_id=task_id,
        session_id=session_id,
        trace_id=trace_id,
        device_id=device_id,
        contract_id=contract_id,
        participant_role="android",
        state_transition=(
            f"truth={truth_kind} → terminal_phase={terminal_phase}"
        ),
        was_successful=True,
        source=source,
        message=(
            f"participant_truth terminal update: truth_kind={truth_kind!r} "
            f"terminal_phase={terminal_phase!r}"
        ),
        payload={
            "truth_kind": truth_kind,
            "terminal_phase": terminal_phase,
            "canonical_update": canonical_update,
            **(extra or {}),
        },
    )
    return get_android_delegated_audit_recorder().record(rec)


# ---------------------------------------------------------------------------
# Module-level query helpers (convenience wrappers over the singleton)
# ---------------------------------------------------------------------------


def get_android_audit_for_task(
    task_id: str,
) -> List[AndroidDelegatedAuditRecord]:
    """Return all audit records for *task_id* in insertion order."""
    return get_android_delegated_audit_recorder().get_by_task(task_id)


def get_android_audit_for_session(
    session_id: str,
) -> List[AndroidDelegatedAuditRecord]:
    """Return all audit records for *session_id* in insertion order."""
    return get_android_delegated_audit_recorder().get_by_session(session_id)


def android_audit_snapshot() -> AndroidDelegatedAuditSnapshot:
    """Return a point-in-time snapshot of the Android delegated audit ring."""
    return get_android_delegated_audit_recorder().snapshot()


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels / version
    "ANDROID_DELEGATED_RUNTIME_AUDIT_AUTHORITY",
    "ANDROID_DELEGATED_RUNTIME_AUDIT_CONTRACT_VERSION",
    # Event kind constants
    "AndroidDelegatedAuditEventKind",
    # Dataclasses
    "AndroidDelegatedAuditRecord",
    "AndroidDelegatedAuditSnapshot",
    # Class
    "AndroidDelegatedRuntimeAuditRecorder",
    # Singleton accessors
    "get_android_delegated_audit_recorder",
    "reset_android_delegated_audit_recorder",
    # Recording helpers
    "record_delegated_execution_signal",
    "record_handoff_v2_result",
    "record_takeover_request",
    "record_takeover_response",
    "record_reconciliation_signal",
    "record_participant_truth_terminal_update",
    # Query helpers
    "get_android_audit_for_task",
    "get_android_audit_for_session",
    "android_audit_snapshot",
]
