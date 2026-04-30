"""core/android_participant_session_state.py
=============================================
PR-11-V2: Canonical Android Participant Session State Model.

Background
----------
The Android delegated runtime integration spans several phases —
handoff dispatch, TAKEOVER_REQUEST / TAKEOVER_RESPONSE negotiation,
active execution, reconciliation, and terminal outcome — yet no single
module has ever held an explicit *session-level* state machine for this
full lifecycle.  State was instead inferred from scattered indicators:

* the ``DelegatedExecutionPhase`` in the execution tracker (PR-10)
* the ``AndroidRuntimeBindingState`` in the dispatch binding (PR-11)
* the ``was_reconciled`` flag in participant truth outcomes (PR-4V2)
* the ``accepted`` flag in raw takeover response messages

The result is that the V2 orchestration layer must consult three different
ring buffers and re-derive the lifecycle position of an Android participant
session each time it needs to reason about it.  This creates:

* multiple state-write paths that can disagree on the *current* phase,
* no single canonical answer to *"is this session still in takeover
  negotiation?"*, and
* no clear boundary between the takeover phase and the execution phase.

This module provides a dedicated **participant session state model** for
the Android delegated runtime lifecycle that sits above the lower-level
tracker and binding records:

1. :class:`AndroidParticipantSessionPhase` — canonical enum representing
   the top-level lifecycle position of a single Android participant session
   as observed from the V2 host side:

   ``pre_dispatch`` → ``handoff_dispatched`` → ``takeover_pending`` →
   ``takeover_accepted`` → ``execution`` → ``reconciling`` →
   ``terminal_success`` / ``terminal_failure`` / ``terminal_cancelled``

2. :class:`AndroidParticipantSessionSignal` — canonical enum for the
   external signals that drive phase transitions.

3. :class:`AndroidParticipantSessionRecord` — immutable, typed record
   that captures the full state of an Android participant session:
   identity fields, current phase, previous phase, associated contract and
   takeover ids, timestamps.

4. :func:`create_participant_session_record` — factory function.

5. :func:`advance_participant_session` — returns a new
   :class:`AndroidParticipantSessionRecord` with the phase advanced
   according to the given :class:`AndroidParticipantSessionSignal`.

6. :class:`AndroidParticipantSessionRuntime` — in-process ring buffer
   (size 256) for session records.

7. :func:`record_participant_session` /
   :func:`get_participant_session` /
   :func:`list_active_participant_sessions` /
   :func:`participant_session_snapshot` — persistence and query helpers.

8. :func:`get_participant_session_runtime` /
   :func:`reset_participant_session_runtime` — singleton accessor and
   test-isolation helper.

9. Policy sentinels documenting canonical session state rules.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Phase-monotonic (with exceptions)** — phase advances in the
  prescribed order; back-transitions to terminal are always permitted;
  lateral transitions within non-terminal phases are allowed for
  graceful handling of out-of-order signals.
- **Signal-driven** — phase transitions are driven exclusively by named
  :class:`AndroidParticipantSessionSignal` values, not by raw boolean flags
  or string comparisons at call sites.
- **Non-raising** — :func:`advance_participant_session` never raises; illegal
  transitions leave the phase unchanged.
- **Thread-safe** — ring buffer mutations are protected by a
  ``threading.Lock``.

Public API
----------
Sentinels::

    ANDROID_PARTICIPANT_SESSION_STATE_AUTHORITY
    ANDROID_PARTICIPANT_SESSION_STATE_CONTRACT_VERSION

Enums::

    AndroidParticipantSessionPhase
    AndroidParticipantSessionSignal

Dataclasses::

    AndroidParticipantSessionRecord
    AndroidParticipantSessionSnapshot

Class::

    AndroidParticipantSessionRuntime

Functions::

    create_participant_session_record(...) -> AndroidParticipantSessionRecord
    advance_participant_session(record, signal, ...) -> AndroidParticipantSessionRecord
    record_participant_session(record, ...) -> None
    get_participant_session(session_id, ...) -> AndroidParticipantSessionRecord | None
    list_active_participant_sessions(...) -> list[AndroidParticipantSessionRecord]
    participant_session_snapshot(...) -> AndroidParticipantSessionSnapshot
    get_participant_session_runtime() -> AndroidParticipantSessionRuntime
    reset_participant_session_runtime() -> None
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.AndroidParticipantSessionState")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

ANDROID_PARTICIPANT_SESSION_STATE_AUTHORITY: str = (
    "ANDROID_PARTICIPANT_SESSION_STATE_AUTHORITY::"
    "core.android_participant_session_state is the canonical source of "
    "session-level lifecycle state for Android participant sessions in the "
    "V2 delegated runtime.  advance_participant_session() is the single "
    "path for phase transitions.  "
    "This module is the CONCRETE Android implementation of the participant-"
    "generic session lifecycle contract defined in "
    "core.participant_authority_interfaces (PR-8).  "
    "AndroidParticipantSessionPhase implements ParticipantSessionPhase; "
    "AndroidParticipantSessionSignal implements ParticipantSessionSignal."
)

ANDROID_PARTICIPANT_SESSION_STATE_CONTRACT_VERSION: str = "1.0"

# Policy sentinels

SESSION_PHASE_IS_SIGNAL_DRIVEN_POLICY: str = (
    "POLICY::SESSION_PHASE_IS_SIGNAL_DRIVEN: Android participant session "
    "phase transitions MUST be driven by named AndroidParticipantSessionSignal "
    "values via advance_participant_session().  Direct phase field mutation is "
    "prohibited.  Records are frozen dataclasses."
)

TERMINAL_PHASE_IS_ABSORBING_POLICY: str = (
    "POLICY::TERMINAL_PHASE_IS_ABSORBING: Once a participant session record "
    "reaches a terminal phase (terminal_success / terminal_failure / "
    "terminal_cancelled) it MUST NOT transition to any other phase.  "
    "advance_participant_session() returns the record unchanged for terminal "
    "records regardless of the signal."
)

SESSION_RECORD_IS_IMMUTABLE_POLICY: str = (
    "POLICY::SESSION_RECORD_IS_IMMUTABLE: AndroidParticipantSessionRecord "
    "instances are frozen dataclasses.  advance_participant_session() returns "
    "a NEW record with the updated phase; the original record is never mutated."
)

UNKNOWN_SIGNAL_IS_NOOP_POLICY: str = (
    "POLICY::UNKNOWN_SIGNAL_IS_NOOP: advance_participant_session() called with "
    "a signal that is not a valid transition from the current phase MUST return "
    "the record unchanged.  It MUST NOT raise."
)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_RING_BUFFER_CAPACITY: int = 256

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AndroidParticipantSessionPhase(str, Enum):
    """Canonical lifecycle phase for an Android participant session (V2 view).

    Phases represent the top-level position of a single Android participant
    session in the delegated runtime lifecycle as observed from the V2 host.

    Values
    ------
    pre_dispatch
        Session record created; handoff contract not yet dispatched.
    handoff_dispatched
        The V2 host has dispatched the handoff contract to the Android runtime.
        Waiting for acknowledgment or takeover negotiation to begin.
    takeover_pending
        V2 has issued a ``TAKEOVER_REQUEST`` to the Android runtime.  Waiting
        for the TAKEOVER_RESPONSE.
    takeover_accepted
        The Android runtime accepted the TAKEOVER_REQUEST.  Execution handover
        is in progress.
    execution
        Active delegated execution is underway on the Android runtime.
    reconciling
        Terminal signal received (or imminent); reconciliation of V2 canonical
        state with Android-reported truth is in progress.
    terminal_success
        Delegated execution completed successfully and V2 canonical state is
        fully reconciled.  Terminal phase.
    terminal_failure
        Delegated execution failed and V2 canonical state reflects the failure.
        Terminal phase.
    terminal_cancelled
        Delegated execution was cancelled (by V2 or the Android runtime) and
        cancellation is recorded in V2 canonical state.  Terminal phase.
    """

    pre_dispatch = "pre_dispatch"
    handoff_dispatched = "handoff_dispatched"
    takeover_pending = "takeover_pending"
    takeover_accepted = "takeover_accepted"
    execution = "execution"
    reconciling = "reconciling"
    terminal_success = "terminal_success"
    terminal_failure = "terminal_failure"
    terminal_cancelled = "terminal_cancelled"

    @classmethod
    def from_string(cls, value: str) -> "AndroidParticipantSessionPhase":
        """Return the enum member matching *value*, defaulting to
        ``pre_dispatch``."""
        if not isinstance(value, str):
            return cls.pre_dispatch
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.pre_dispatch

    def is_terminal(self) -> bool:
        """Return True if this is a terminal phase."""
        return self in (
            AndroidParticipantSessionPhase.terminal_success,
            AndroidParticipantSessionPhase.terminal_failure,
            AndroidParticipantSessionPhase.terminal_cancelled,
        )

    def is_active(self) -> bool:
        """Return True if the session is in an active (non-terminal) phase."""
        return not self.is_terminal()


class AndroidParticipantSessionSignal(str, Enum):
    """Canonical signals that drive Android participant session phase transitions.

    Values
    ------
    handoff_dispatched
        V2 dispatched the handoff contract to the Android runtime.
    takeover_requested
        V2 issued a TAKEOVER_REQUEST to the Android runtime.
    takeover_accepted
        Android accepted the TAKEOVER_REQUEST.
    takeover_rejected
        Android rejected the TAKEOVER_REQUEST.  Causes transition back to
        ``handoff_dispatched`` or ``terminal_failure`` depending on context.
    execution_started
        Android reported that active execution has begun (ACK or first
        PROGRESS signal).
    execution_progressed
        Android reported execution progress (in-flight PROGRESS signal).
    reconciliation_started
        A terminal signal was received and reconciliation is underway.
    result_success
        Execution completed successfully and reconciliation is finished.
    result_failure
        Execution failed and failure is recorded in V2 canonical state.
    result_cancelled
        Execution was cancelled and cancellation is recorded.
    """

    handoff_dispatched = "handoff_dispatched"
    takeover_requested = "takeover_requested"
    takeover_accepted = "takeover_accepted"
    takeover_rejected = "takeover_rejected"
    execution_started = "execution_started"
    execution_progressed = "execution_progressed"
    reconciliation_started = "reconciliation_started"
    result_success = "result_success"
    result_failure = "result_failure"
    result_cancelled = "result_cancelled"

    @classmethod
    def from_string(cls, value: str) -> "AndroidParticipantSessionSignal":
        """Return the enum member matching *value*, defaulting to
        ``execution_progressed``."""
        if not isinstance(value, str):
            return cls.execution_progressed
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.execution_progressed


# ---------------------------------------------------------------------------
# AndroidParticipantSessionRecord
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AndroidParticipantSessionRecord:
    """Immutable record capturing the lifecycle state of an Android participant
    session in the V2 delegated runtime.

    Attributes
    ----------
    record_id
        Stable UUID for this record instance (a new UUID is allocated on each
        :func:`advance_participant_session` call).
    session_id
        Attached-runtime session identifier (primary lookup key).
    device_id
        Android device identifier.
    task_id
        Optional canonical task identifier.
    trace_id
        Optional distributed trace identifier.
    contract_id
        Handoff contract identifier (from PR-9).
    takeover_id
        Takeover identifier issued by V2 in the TAKEOVER_REQUEST, if any.
    phase
        Current :class:`AndroidParticipantSessionPhase`.
    previous_phase
        Phase immediately before the last transition (``None`` for freshly
        created records).
    last_signal
        Most recent :class:`AndroidParticipantSessionSignal` that caused the
        last transition (``None`` for freshly created records).
    created_at
        Wall-clock timestamp when the record was first created.
    updated_at
        Wall-clock timestamp of the most recent transition.
    metadata
        Opaque key/value pairs for extensibility.
    """

    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    device_id: str = ""
    task_id: str = ""
    trace_id: str = ""
    contract_id: str = ""
    takeover_id: str = ""
    phase: AndroidParticipantSessionPhase = AndroidParticipantSessionPhase.pre_dispatch
    previous_phase: Optional[AndroidParticipantSessionPhase] = None
    last_signal: Optional[AndroidParticipantSessionSignal] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "record_id": self.record_id,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "contract_id": self.contract_id,
            "takeover_id": self.takeover_id,
            "phase": self.phase.value,
            "previous_phase": self.previous_phase.value if self.previous_phase else None,
            "last_signal": self.last_signal.value if self.last_signal else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# AndroidParticipantSessionSnapshot
# ---------------------------------------------------------------------------


@dataclass
class AndroidParticipantSessionSnapshot:
    """Point-in-time snapshot of participant session state records.

    Attributes
    ----------
    records
        All records in the ring buffer, newest-first.
    active_count
        Number of records whose phase is non-terminal.
    terminal_count
        Number of records whose phase is terminal.
    total_count
        Total number of records.
    """

    records: List[AndroidParticipantSessionRecord] = field(default_factory=list)
    active_count: int = 0
    terminal_count: int = 0
    total_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "records": [r.to_dict() for r in self.records],
            "active_count": self.active_count,
            "terminal_count": self.terminal_count,
            "total_count": self.total_count,
        }


# ---------------------------------------------------------------------------
# Phase transition table
# ---------------------------------------------------------------------------

# Maps (current_phase, signal) → next_phase.
# If a combination is absent the transition is a no-op.
_TRANSITION_TABLE: Dict[
    tuple,  # (AndroidParticipantSessionPhase, AndroidParticipantSessionSignal)
    AndroidParticipantSessionPhase,
] = {
    # pre_dispatch → handoff_dispatched
    (
        AndroidParticipantSessionPhase.pre_dispatch,
        AndroidParticipantSessionSignal.handoff_dispatched,
    ): AndroidParticipantSessionPhase.handoff_dispatched,
    # handoff_dispatched → takeover_pending
    (
        AndroidParticipantSessionPhase.handoff_dispatched,
        AndroidParticipantSessionSignal.takeover_requested,
    ): AndroidParticipantSessionPhase.takeover_pending,
    # handoff_dispatched → execution (direct — no takeover negotiation)
    (
        AndroidParticipantSessionPhase.handoff_dispatched,
        AndroidParticipantSessionSignal.execution_started,
    ): AndroidParticipantSessionPhase.execution,
    # takeover_pending → takeover_accepted
    (
        AndroidParticipantSessionPhase.takeover_pending,
        AndroidParticipantSessionSignal.takeover_accepted,
    ): AndroidParticipantSessionPhase.takeover_accepted,
    # takeover_pending → handoff_dispatched (rejected — retry path)
    (
        AndroidParticipantSessionPhase.takeover_pending,
        AndroidParticipantSessionSignal.takeover_rejected,
    ): AndroidParticipantSessionPhase.handoff_dispatched,
    # takeover_accepted → execution
    (
        AndroidParticipantSessionPhase.takeover_accepted,
        AndroidParticipantSessionSignal.execution_started,
    ): AndroidParticipantSessionPhase.execution,
    # execution → execution (progress updates stay in execution)
    (
        AndroidParticipantSessionPhase.execution,
        AndroidParticipantSessionSignal.execution_progressed,
    ): AndroidParticipantSessionPhase.execution,
    # execution → reconciling
    (
        AndroidParticipantSessionPhase.execution,
        AndroidParticipantSessionSignal.reconciliation_started,
    ): AndroidParticipantSessionPhase.reconciling,
    # reconciling → terminal_*
    (
        AndroidParticipantSessionPhase.reconciling,
        AndroidParticipantSessionSignal.result_success,
    ): AndroidParticipantSessionPhase.terminal_success,
    (
        AndroidParticipantSessionPhase.reconciling,
        AndroidParticipantSessionSignal.result_failure,
    ): AndroidParticipantSessionPhase.terminal_failure,
    (
        AndroidParticipantSessionPhase.reconciling,
        AndroidParticipantSessionSignal.result_cancelled,
    ): AndroidParticipantSessionPhase.terminal_cancelled,
    # execution → terminal_* (direct terminal without explicit reconcile signal)
    (
        AndroidParticipantSessionPhase.execution,
        AndroidParticipantSessionSignal.result_success,
    ): AndroidParticipantSessionPhase.terminal_success,
    (
        AndroidParticipantSessionPhase.execution,
        AndroidParticipantSessionSignal.result_failure,
    ): AndroidParticipantSessionPhase.terminal_failure,
    (
        AndroidParticipantSessionPhase.execution,
        AndroidParticipantSessionSignal.result_cancelled,
    ): AndroidParticipantSessionPhase.terminal_cancelled,
    # handoff_dispatched → terminal_* (e.g. early cancellation)
    (
        AndroidParticipantSessionPhase.handoff_dispatched,
        AndroidParticipantSessionSignal.result_cancelled,
    ): AndroidParticipantSessionPhase.terminal_cancelled,
    (
        AndroidParticipantSessionPhase.handoff_dispatched,
        AndroidParticipantSessionSignal.result_failure,
    ): AndroidParticipantSessionPhase.terminal_failure,
    # takeover_pending → terminal_* (e.g. crash during negotiation)
    (
        AndroidParticipantSessionPhase.takeover_pending,
        AndroidParticipantSessionSignal.result_failure,
    ): AndroidParticipantSessionPhase.terminal_failure,
    (
        AndroidParticipantSessionPhase.takeover_pending,
        AndroidParticipantSessionSignal.result_cancelled,
    ): AndroidParticipantSessionPhase.terminal_cancelled,
    # takeover_accepted → terminal_* (e.g. crash immediately after accept)
    (
        AndroidParticipantSessionPhase.takeover_accepted,
        AndroidParticipantSessionSignal.result_failure,
    ): AndroidParticipantSessionPhase.terminal_failure,
    (
        AndroidParticipantSessionPhase.takeover_accepted,
        AndroidParticipantSessionSignal.result_cancelled,
    ): AndroidParticipantSessionPhase.terminal_cancelled,
}


# ---------------------------------------------------------------------------
# Factory and transition helpers
# ---------------------------------------------------------------------------


def create_participant_session_record(
    *,
    session_id: str,
    device_id: str = "",
    task_id: str = "",
    trace_id: str = "",
    contract_id: str = "",
    takeover_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> AndroidParticipantSessionRecord:
    """Create a new :class:`AndroidParticipantSessionRecord` in ``pre_dispatch`` phase.

    Parameters
    ----------
    session_id:
        Attached-runtime session identifier.  Must be non-empty.
    device_id:
        Android device identifier.
    task_id:
        Optional canonical task identifier.
    trace_id:
        Optional distributed trace identifier.
    contract_id:
        Handoff contract identifier.
    takeover_id:
        Optional takeover identifier (usually set later when a TAKEOVER_REQUEST
        is issued).
    metadata:
        Optional extra key/value pairs.

    Returns
    -------
    AndroidParticipantSessionRecord
    """
    now = time.time()
    return AndroidParticipantSessionRecord(
        session_id=session_id or "",
        device_id=device_id or "",
        task_id=task_id or "",
        trace_id=trace_id or "",
        contract_id=contract_id or "",
        takeover_id=takeover_id or "",
        phase=AndroidParticipantSessionPhase.pre_dispatch,
        previous_phase=None,
        last_signal=None,
        created_at=now,
        updated_at=now,
        metadata=dict(metadata) if metadata else {},
    )


def advance_participant_session(
    record: AndroidParticipantSessionRecord,
    signal: AndroidParticipantSessionSignal,
    *,
    takeover_id: str = "",
    metadata_update: Optional[Dict[str, Any]] = None,
) -> AndroidParticipantSessionRecord:
    """Return a new record with the phase advanced according to *signal*.

    If the current phase is terminal, or if *(current_phase, signal)* has no
    entry in the transition table, the original *record* is returned unchanged.

    Parameters
    ----------
    record:
        Current :class:`AndroidParticipantSessionRecord`.
    signal:
        :class:`AndroidParticipantSessionSignal` to apply.
    takeover_id:
        Optional takeover identifier to attach to the new record (relevant
        when signal is ``takeover_requested`` or ``takeover_accepted``).
    metadata_update:
        Optional extra key/value pairs merged into ``record.metadata``.

    Returns
    -------
    AndroidParticipantSessionRecord
        Updated record (new instance) if the transition was valid, otherwise
        the original *record* unchanged.
    """
    try:
        if record.phase.is_terminal():
            return record

        next_phase = _TRANSITION_TABLE.get((record.phase, signal))
        if next_phase is None:
            # No valid transition — return record unchanged
            return record

        merged_meta = dict(record.metadata)
        if metadata_update:
            merged_meta.update(metadata_update)

        return AndroidParticipantSessionRecord(
            record_id=str(uuid.uuid4()),
            session_id=record.session_id,
            device_id=record.device_id,
            task_id=record.task_id,
            trace_id=record.trace_id,
            contract_id=record.contract_id,
            takeover_id=takeover_id or record.takeover_id,
            phase=next_phase,
            previous_phase=record.phase,
            last_signal=signal,
            created_at=record.created_at,
            updated_at=time.time(),
            metadata=merged_meta,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "advance_participant_session: transition failed (non-fatal): %s", exc
        )
        return record


# ---------------------------------------------------------------------------
# AndroidParticipantSessionRuntime — in-process ring buffer
# ---------------------------------------------------------------------------


class AndroidParticipantSessionRuntime:
    """In-process ring buffer for :class:`AndroidParticipantSessionRecord`.

    Thread-safe (``threading.Lock``).  Capacity is
    :data:`_RING_BUFFER_CAPACITY` (256).

    The ring stores the **most recent** record per ``session_id``;
    :meth:`record` appends to the left side of the deque.
    Lookup helpers return the newest matching record.
    """

    def __init__(self, capacity: int = _RING_BUFFER_CAPACITY) -> None:
        self._capacity = capacity
        self._ring: Deque[AndroidParticipantSessionRecord] = deque(maxlen=capacity)
        self._lock: threading.Lock = threading.Lock()

    def record(self, rec: AndroidParticipantSessionRecord) -> None:
        """Append *rec* to the ring (newest first)."""
        with self._lock:
            self._ring.appendleft(rec)

    def get_by_session_id(
        self, session_id: str
    ) -> Optional[AndroidParticipantSessionRecord]:
        """Return the most recent record for *session_id*, or ``None``."""
        with self._lock:
            for rec in self._ring:
                if rec.session_id == session_id:
                    return rec
        return None

    def list_active(self) -> List[AndroidParticipantSessionRecord]:
        """Return all non-terminal records, newest-first."""
        with self._lock:
            return [r for r in self._ring if r.phase.is_active()]

    def snapshot(self) -> AndroidParticipantSessionSnapshot:
        """Return a point-in-time snapshot."""
        with self._lock:
            records = list(self._ring)
        active = sum(1 for r in records if r.phase.is_active())
        terminal = sum(1 for r in records if r.phase.is_terminal())
        return AndroidParticipantSessionSnapshot(
            records=records,
            active_count=active,
            terminal_count=terminal,
            total_count=len(records),
        )


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_singleton_lock: threading.Lock = threading.Lock()
_singleton: Optional[AndroidParticipantSessionRuntime] = None


def get_participant_session_runtime() -> AndroidParticipantSessionRuntime:
    """Return the process-wide singleton :class:`AndroidParticipantSessionRuntime`."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = AndroidParticipantSessionRuntime()
    return _singleton


def reset_participant_session_runtime() -> None:
    """Reset the singleton (test-isolation helper only)."""
    global _singleton
    with _singleton_lock:
        _singleton = None


# ---------------------------------------------------------------------------
# Persistence and query helpers
# ---------------------------------------------------------------------------


def record_participant_session(
    rec: AndroidParticipantSessionRecord,
    *,
    runtime: Optional[AndroidParticipantSessionRuntime] = None,
) -> None:
    """Persist *rec* to the ring buffer (never raises)."""
    try:
        _rt = runtime if runtime is not None else get_participant_session_runtime()
        _rt.record(rec)
    except Exception as exc:  # noqa: BLE001
        logger.debug("android_participant_session_state: record failed: %s", exc)


def get_participant_session(
    session_id: str,
    *,
    runtime: Optional[AndroidParticipantSessionRuntime] = None,
) -> Optional[AndroidParticipantSessionRecord]:
    """Return the most recent :class:`AndroidParticipantSessionRecord` for
    *session_id*, or ``None`` if not found."""
    try:
        _rt = runtime if runtime is not None else get_participant_session_runtime()
        return _rt.get_by_session_id(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("android_participant_session_state: get failed: %s", exc)
        return None


def list_active_participant_sessions(
    *,
    runtime: Optional[AndroidParticipantSessionRuntime] = None,
) -> List[AndroidParticipantSessionRecord]:
    """Return all non-terminal :class:`AndroidParticipantSessionRecord` instances,
    newest-first."""
    try:
        _rt = runtime if runtime is not None else get_participant_session_runtime()
        return _rt.list_active()
    except Exception as exc:  # noqa: BLE001
        logger.debug("android_participant_session_state: list_active failed: %s", exc)
        return []


def participant_session_snapshot(
    *,
    runtime: Optional[AndroidParticipantSessionRuntime] = None,
) -> AndroidParticipantSessionSnapshot:
    """Return a :class:`AndroidParticipantSessionSnapshot` of the ring buffer."""
    try:
        _rt = runtime if runtime is not None else get_participant_session_runtime()
        return _rt.snapshot()
    except Exception as exc:  # noqa: BLE001
        logger.debug("android_participant_session_state: snapshot failed: %s", exc)
        return AndroidParticipantSessionSnapshot()
