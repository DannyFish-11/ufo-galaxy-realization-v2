"""core/attached_runtime_session.py
=====================================
PR package 7 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Canonical Persistent Attached-Runtime Session Semantics.

This module is the **canonical authority** for modelling the session-level
relationship between the main-repo OpenClawd host and a remote/Android
cross-device runtime participant after cross-device enablement.

Background
----------
Prior to PR-7, the main-repo runtime had no stable, first-class notion of an
*attached* cross-device participant that persists across individual requests.
A device/runtime host was treated as present only for the duration of a
handshake or a single request, meaning the system could not distinguish a
transiently connected device from one that had been explicitly attached and
was expected to remain part of the execution surface until explicitly detached,
disconnected, disabled, or invalidated.

PR-7 closes this gap on the MAIN-repo side by providing:

1. :class:`AttachmentState` — canonical enum classifying the lifecycle state
   of an attached runtime session relationship.
2. :class:`AttachmentLifecycleSignal` — canonical enum for the signals that
   drive state transitions in an attached-runtime session lifecycle.
3. :class:`AttachedRuntimeSessionRecord` — stable, serialisable record of a
   single cross-device runtime attachment.  Carries device identity, posture,
   coordination role, attachment state, and timestamps.
4. :class:`AttachedRuntimeSessionSnapshot` — point-in-time snapshot of all
   active attached-runtime sessions for audit, projection, and diff.
5. :class:`AttachedRuntimeSessionRuntime` — in-process ring-buffer singleton
   (128 entries) that accumulates session records across the process lifetime.
6. :func:`attach_runtime_session` — idempotent attach operation; creates a
   new record or re-attaches a previously detached/disconnected one.
7. :func:`apply_lifecycle_signal` — applies an
   :class:`AttachmentLifecycleSignal` to a record, returning the updated copy.
8. :func:`get_attached_runtime_session` — retrieves the most recent record for
   a given ``device_id``.
9. :func:`list_active_attached_sessions` — returns all records whose state is
   ``attached``.
10. :func:`build_attached_runtime_session_snapshot` — assembles a
    :class:`AttachedRuntimeSessionSnapshot` from the current ring-buffer state.
11. Ten policy sentinels documenting canonical attachment-semantics rules.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Posture-preserving** — all ``source_runtime_posture`` semantics from
  PR-533 / PR-1 are honoured.
- **Coordination-role aware** — integrates naturally with PR-538 / PR-6
  ``CoordinationRole`` semantics.
- **Android-host aware** — attachment records carry the ``android_host_role``
  established by PR-5 as an informational field.
- **Lifecycle-stable** — the ``attached`` state is persistent; only explicit
  signals (detach, disconnect, disable, invalidate) terminate it.
- **Graceful degradation** — unknown or missing fields default to the
  conservative safe outcome (``detached`` state, conservative posture).
- **Fully serialisable** — all dataclasses expose ``to_dict()`` / ``to_json()``
  for stable, round-trippable wire representations.

Relationship to other PR packages
----------------------------------
* PR-1  (``core.posture_contract_canonicalization``) — canonicalises the
  posture value stored in session records.
* PR-2  (``core.source_execution_eligibility``) — attachment state informs
  eligibility; an ``attached`` session with ``join_runtime`` posture is
  eligible for local execution.
* PR-3  (``core.canonical_handoff_path``) — handoff envelopes may carry
  ``attachment_session_id`` to associate a handoff with an attached session.
* PR-4  (``core.canonical_session_truth``) — attached sessions contribute
  authoritative result units; only ``attached`` participants should be merged.
* PR-5  (``core.android_runtime_host``) — ``android_host_role`` is stored as
  an informational field in attached-runtime session records.
* PR-538 (``core.multi_device_coordination_authority``) — ``coordination_role``
  is a key session record field, derived and carried forward from PR-538.
* PR package 6 (``core.canonical_capability_scheduling_basis``) — capability
  tier is propagated into attached-runtime session records for scheduling.

Public API
----------
Sentinels::

    ATTACHED_RUNTIME_SESSION_AUTHORITY
    ATTACHED_SESSION_PERSISTS_ACROSS_REQUESTS_POLICY
    TRANSIENT_PRESENCE_DISTINCT_FROM_ATTACHED_SESSION_POLICY
    DETACH_SIGNAL_REQUIRED_FOR_SESSION_TERMINATION_POLICY
    ATTACH_IS_IDEMPOTENT_POLICY
    DISCONNECTED_DOES_NOT_INVALIDATE_SESSION_POLICY
    INVALIDATED_SESSION_IS_TERMINAL_POLICY
    DISABLED_SESSION_NOT_ELIGIBLE_FOR_EXECUTION_POLICY
    ATTACHED_SESSION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY
    ATTACHMENT_LIFECYCLE_IS_POSTURE_AWARE_POLICY
    ATTACHED_RUNTIME_SESSION_PR7_SENTINEL
    ATTACHMENT_LIFECYCLE_ACTION_GOVERNANCE_POLICY

Enums::

    AttachmentState
    AttachmentLifecycleSignal
    AttachmentLifecycleAction

Dataclasses::

    AttachedRuntimeSessionRecord
    AttachedRuntimeSessionSnapshot

Classes::

    AttachedRuntimeSessionRuntime

Functions::

    attach_runtime_session(...) -> AttachedRuntimeSessionRecord
    apply_lifecycle_signal(record, signal, ...) -> AttachedRuntimeSessionRecord
    classify_attach_lifecycle_action(existing, source_runtime_posture) -> AttachmentLifecycleAction
    classify_signal_lifecycle_action(record_or_state, signal) -> AttachmentLifecycleAction
    get_attached_runtime_session(device_id) -> AttachedRuntimeSessionRecord | None
    list_active_attached_sessions() -> list[AttachedRuntimeSessionRecord]
    build_attached_runtime_session_snapshot() -> AttachedRuntimeSessionSnapshot
    get_attached_runtime_session_runtime() -> AttachedRuntimeSessionRuntime
    reset_attached_runtime_session_runtime() -> None
"""

from __future__ import annotations

import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

ATTACHED_RUNTIME_SESSION_AUTHORITY: str = (
    "ATTACHED_RUNTIME_SESSION_AUTHORITY::core.attached_runtime_session is the "
    "canonical authority for persistent attached-runtime session semantics on "
    "the main-repo side (PR package 7, post-533 dual-repo runtime unification)."
)

ATTACHED_SESSION_PERSISTS_ACROSS_REQUESTS_POLICY: str = (
    "POLICY::ATTACHED_SESSION_PERSISTS_ACROSS_REQUESTS: once a device/runtime "
    "host is attached, it remains an attached participant across individual "
    "requests until an explicit detach, disconnect, disable, or invalidation "
    "signal is received."
)

TRANSIENT_PRESENCE_DISTINCT_FROM_ATTACHED_SESSION_POLICY: str = (
    "POLICY::TRANSIENT_PRESENCE_DISTINCT_FROM_ATTACHED_SESSION: a device that "
    "has not received an explicit 'attach' signal is treated as transiently "
    "present only; it must not be assumed to be an attached session participant."
)

DETACH_SIGNAL_REQUIRED_FOR_SESSION_TERMINATION_POLICY: str = (
    "POLICY::DETACH_SIGNAL_REQUIRED_FOR_SESSION_TERMINATION: an attached "
    "session can only reach a terminal or non-active state through an explicit "
    "lifecycle signal (detach, disconnect, disable, or invalidate).  Absence "
    "of recent activity alone does not terminate an attached session."
)

ATTACH_IS_IDEMPOTENT_POLICY: str = (
    "POLICY::ATTACH_IS_IDEMPOTENT: calling attach_runtime_session() for a "
    "device that already has an 'attached' record re-attaches and refreshes "
    "the record without creating a duplicate."
)

DISCONNECTED_DOES_NOT_INVALIDATE_SESSION_POLICY: str = (
    "POLICY::DISCONNECTED_DOES_NOT_INVALIDATE_SESSION: a 'disconnect' signal "
    "moves the session to 'disconnected' state, which is recoverable.  The "
    "session may transition back to 'attached' via a 'reconnect' signal without "
    "requiring a full re-attach handshake."
)

INVALIDATED_SESSION_IS_TERMINAL_POLICY: str = (
    "POLICY::INVALIDATED_SESSION_IS_TERMINAL: once a session reaches the "
    "'invalidated' state it cannot be recovered.  A new attach handshake is "
    "required to re-establish the session."
)

DISABLED_SESSION_NOT_ELIGIBLE_FOR_EXECUTION_POLICY: str = (
    "POLICY::DISABLED_SESSION_NOT_ELIGIBLE_FOR_EXECUTION: a session in the "
    "'disabled' state is not eligible for execution scheduling or result "
    "merge.  It must be re-attached before participating in execution."
)

ATTACHED_SESSION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY: str = (
    "POLICY::ATTACHED_SESSION_REQUIRES_JOIN_RUNTIME_POSTURE: only devices "
    "with 'join_runtime' source_runtime_posture may be attached as first-class "
    "runtime participants.  A 'control_only' device cannot enter the 'attached' "
    "state."
)

ATTACHMENT_LIFECYCLE_IS_POSTURE_AWARE_POLICY: str = (
    "POLICY::ATTACHMENT_LIFECYCLE_IS_POSTURE_AWARE: attachment state "
    "transitions propagate and preserve source_runtime_posture so that "
    "downstream eligibility checks remain consistent with PR-1 through PR-6 "
    "semantics."
)

ATTACHMENT_LIFECYCLE_ACTION_GOVERNANCE_POLICY: str = (
    "POLICY::ATTACHMENT_LIFECYCLE_ACTION_GOVERNANCE: lifecycle governance "
    "intent is explicit and classified into create/reconcile/recover/replace/"
    "deactivate/retire/no_change/rejected actions so attach/signal authority "
    "is easier to reason about without changing runtime behavior."
)

ATTACHED_RUNTIME_SESSION_PR7_SENTINEL: str = (
    "ATTACHED_RUNTIME_SESSION_PR7::canonical-attached-runtime-session-semantics-"
    "post-533-main-repo-pr7-v1"
)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_POSTURE_JOIN_RUNTIME = "join_runtime"
_POSTURE_CONTROL_ONLY = "control_only"
_RING_BUFFER_CAPACITY = 128

# ---------------------------------------------------------------------------
# AttachmentState
# ---------------------------------------------------------------------------


class AttachmentState(str, Enum):
    """Canonical lifecycle states for an attached-runtime session.

    attached
        The remote device/runtime is an active, explicitly attached
        participant.  It is eligible for execution and result contribution.
    detaching
        A detach request has been initiated but not yet acknowledged.
        The session is in transition and should not receive new tasks.
    detached
        The session has been explicitly detached.  The device is no longer
        an attached participant.  Re-attachment requires a new attach signal.
    disconnected
        The transport connection has been lost.  The session record is
        preserved; a reconnect signal can restore the session to ``attached``
        without a full re-attach handshake.
    disabled
        The session has been administratively disabled.  It is not eligible
        for execution or result merge until explicitly re-attached.
    invalidated
        The session has been invalidated (e.g. authentication expired, device
        revoked).  This is a terminal state; a new attach handshake is
        required.
    """

    attached = "attached"
    detaching = "detaching"
    detached = "detached"
    disconnected = "disconnected"
    disabled = "disabled"
    invalidated = "invalidated"

    @classmethod
    def from_string(cls, value: str, default: "AttachmentState" = None) -> "AttachmentState":
        """Return the enum member matching *value*, or *default* / detached."""
        if default is None:
            default = cls.detached
        if not isinstance(value, str):
            return default
        try:
            return cls(value.lower().strip())
        except ValueError:
            return default

    def is_active(self) -> bool:
        """Return True if this state represents an active attached session."""
        return self == AttachmentState.attached

    def is_terminal(self) -> bool:
        """Return True if this state is terminal (requires new attach)."""
        return self in (AttachmentState.invalidated, AttachmentState.detached)

    def is_recoverable(self) -> bool:
        """Return True if the session can recover without a new attach."""
        return self in (AttachmentState.disconnected, AttachmentState.detaching)


# ---------------------------------------------------------------------------
# AttachmentLifecycleSignal
# ---------------------------------------------------------------------------


class AttachmentLifecycleSignal(str, Enum):
    """Canonical signals that drive attached-runtime session lifecycle transitions.

    attach
        Explicitly attach a device/runtime as a session-level participant.
        Idempotent if the device is already attached.
    detach
        Begin explicit detach sequence; moves the session to ``detaching``.
    disconnect
        Record that the transport connection was lost; moves to
        ``disconnected`` (recoverable).
    disable
        Administratively disable the session; moves to ``disabled``.
    invalidate
        Invalidate the session permanently; moves to ``invalidated``
        (terminal).
    reconnect
        Recover a ``disconnected`` or ``detaching`` session back to
        ``attached``.
    """

    attach = "attach"
    detach = "detach"
    disconnect = "disconnect"
    disable = "disable"
    invalidate = "invalidate"
    reconnect = "reconnect"

    @classmethod
    def from_string(cls, value: str, default: "AttachmentLifecycleSignal" = None) -> "AttachmentLifecycleSignal":
        """Return the enum member matching *value*, or *default*."""
        if default is None:
            default = cls.attach
        if not isinstance(value, str):
            return default
        try:
            return cls(value.lower().strip())
        except ValueError:
            return default


class AttachmentLifecycleAction(str, Enum):
    """Lifecycle governance action labels for attach/signal transitions."""

    create = "create"
    reconcile = "reconcile"
    recover = "recover"
    replace = "replace"
    deactivate = "deactivate"
    retire = "retire"
    no_change = "no_change"
    rejected = "rejected"


# ---------------------------------------------------------------------------
# Transition table
# ---------------------------------------------------------------------------

# Maps (current_state, signal) → next_state.
# Missing combinations leave the state unchanged.
_TRANSITION_TABLE: Dict[tuple, AttachmentState] = {
    # attach signal
    (AttachmentState.detached, AttachmentLifecycleSignal.attach): AttachmentState.attached,
    (AttachmentState.disconnected, AttachmentLifecycleSignal.attach): AttachmentState.attached,
    (AttachmentState.disabled, AttachmentLifecycleSignal.attach): AttachmentState.attached,
    (AttachmentState.attached, AttachmentLifecycleSignal.attach): AttachmentState.attached,  # idempotent
    (AttachmentState.detaching, AttachmentLifecycleSignal.attach): AttachmentState.attached,
    # detach signal
    (AttachmentState.attached, AttachmentLifecycleSignal.detach): AttachmentState.detaching,
    (AttachmentState.disconnected, AttachmentLifecycleSignal.detach): AttachmentState.detached,
    (AttachmentState.detaching, AttachmentLifecycleSignal.detach): AttachmentState.detached,
    # disconnect signal
    (AttachmentState.attached, AttachmentLifecycleSignal.disconnect): AttachmentState.disconnected,
    (AttachmentState.detaching, AttachmentLifecycleSignal.disconnect): AttachmentState.disconnected,
    # disable signal
    (AttachmentState.attached, AttachmentLifecycleSignal.disable): AttachmentState.disabled,
    (AttachmentState.disconnected, AttachmentLifecycleSignal.disable): AttachmentState.disabled,
    (AttachmentState.detaching, AttachmentLifecycleSignal.disable): AttachmentState.disabled,
    # invalidate signal (terminal — applies from any non-terminal state)
    (AttachmentState.attached, AttachmentLifecycleSignal.invalidate): AttachmentState.invalidated,
    (AttachmentState.detaching, AttachmentLifecycleSignal.invalidate): AttachmentState.invalidated,
    (AttachmentState.disconnected, AttachmentLifecycleSignal.invalidate): AttachmentState.invalidated,
    (AttachmentState.disabled, AttachmentLifecycleSignal.invalidate): AttachmentState.invalidated,
    (AttachmentState.detached, AttachmentLifecycleSignal.invalidate): AttachmentState.invalidated,
    # reconnect signal
    (AttachmentState.disconnected, AttachmentLifecycleSignal.reconnect): AttachmentState.attached,
    (AttachmentState.detaching, AttachmentLifecycleSignal.reconnect): AttachmentState.attached,
}


def classify_attach_lifecycle_action(
    existing: Optional["AttachedRuntimeSessionRecord"],
    source_runtime_posture: str,
) -> AttachmentLifecycleAction:
    """Classify lifecycle governance intent for an attach operation."""
    posture = (source_runtime_posture or _POSTURE_CONTROL_ONLY).lower().strip()
    if posture != _POSTURE_JOIN_RUNTIME:
        return AttachmentLifecycleAction.rejected
    if existing is None:
        return AttachmentLifecycleAction.create
    if existing.is_active():
        return AttachmentLifecycleAction.reconcile
    return AttachmentLifecycleAction.replace


def classify_signal_lifecycle_action(
    record_or_state: "AttachedRuntimeSessionRecord | AttachmentState",
    signal: AttachmentLifecycleSignal,
) -> AttachmentLifecycleAction:
    """Classify lifecycle governance intent for a signal application."""
    current = (
        record_or_state.attachment_state
        if isinstance(record_or_state, AttachedRuntimeSessionRecord)
        else record_or_state
    )

    if current == AttachmentState.invalidated and signal != AttachmentLifecycleSignal.attach:
        return AttachmentLifecycleAction.retire

    next_state = _TRANSITION_TABLE.get((current, signal))
    if next_state is None or next_state == current:
        return AttachmentLifecycleAction.no_change

    if signal == AttachmentLifecycleSignal.reconnect:
        return AttachmentLifecycleAction.recover
    if signal in (
        AttachmentLifecycleSignal.detach,
        AttachmentLifecycleSignal.disconnect,
        AttachmentLifecycleSignal.disable,
    ):
        return AttachmentLifecycleAction.deactivate
    if signal == AttachmentLifecycleSignal.invalidate:
        return AttachmentLifecycleAction.retire
    if signal == AttachmentLifecycleSignal.attach:
        return (
            AttachmentLifecycleAction.reconcile
            if current == AttachmentState.attached
            else AttachmentLifecycleAction.recover
        )
    return AttachmentLifecycleAction.no_change


# ---------------------------------------------------------------------------
# AttachedRuntimeSessionRecord
# ---------------------------------------------------------------------------


@dataclass
class AttachedRuntimeSessionRecord:
    """Stable, serialisable record of a single cross-device runtime attachment.

    This is the canonical representation of one remote/Android device's
    attached-runtime session relationship on the main-repo side.

    Attributes
    ----------
    record_id
        Unique, stable identifier for this record instance.  Auto-generated
        if not provided.
    device_id
        Identifier of the attached remote/Android device or runtime host.
    session_id
        Optional external session identifier (e.g. galaxy-session-id).
    source_runtime_posture
        Source device's participation posture.  Must be 'join_runtime' for
        the session to be eligible for attachment.
    coordination_role
        Coordination role derived from posture + formation context (PR-538).
    android_host_role
        AndroidRuntimeHostRole string (PR-5).  Optional informational field.
    capability_tier
        CapabilityTier string (PR package 6).  Optional informational field.
    attachment_state
        Current lifecycle state of this attachment.
    previous_state
        Previous lifecycle state before the last transition.  None for new
        records.
    attach_reason
        Human-readable reason / context for the most recent attach.
    last_signal
        The most recent :class:`AttachmentLifecycleSignal` applied.
    attached_at
        Unix epoch seconds when the session was first attached.
    last_transition_at
        Unix epoch seconds when the last state transition occurred.
    metadata
        Arbitrary caller-supplied metadata dict (e.g. device platform info).
    """

    device_id: str
    source_runtime_posture: str = _POSTURE_JOIN_RUNTIME
    coordination_role: str = ""
    android_host_role: str = ""
    capability_tier: str = ""
    attachment_state: AttachmentState = AttachmentState.attached
    previous_state: Optional[AttachmentState] = None
    session_id: str = ""
    attach_reason: str = ""
    last_signal: Optional[AttachmentLifecycleSignal] = None
    attached_at: float = field(default_factory=time.time)
    last_transition_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def runtime_attachment_session_id(self) -> str:
        """Canonical alias for runtime attachment continuity semantics."""
        return self.session_id

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def is_active(self) -> bool:
        """Return True if the session is currently attached and active."""
        return self.attachment_state == AttachmentState.attached

    def is_eligible_for_execution(self) -> bool:
        """Return True if this session is eligible for execution scheduling.

        Requires both ``attached`` state AND ``join_runtime`` posture, in line
        with :data:`ATTACHED_SESSION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY` and
        :data:`DISABLED_SESSION_NOT_ELIGIBLE_FOR_EXECUTION_POLICY`.
        """
        return (
            self.attachment_state == AttachmentState.attached
            and self.source_runtime_posture == _POSTURE_JOIN_RUNTIME
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "record_id": self.record_id,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "source_runtime_posture": self.source_runtime_posture,
            "coordination_role": self.coordination_role,
            "android_host_role": self.android_host_role,
            "capability_tier": self.capability_tier,
            "attachment_state": self.attachment_state.value,
            "previous_state": self.previous_state.value if self.previous_state else None,
            "attach_reason": self.attach_reason,
            "last_signal": self.last_signal.value if self.last_signal else None,
            "attached_at": self.attached_at,
            "last_transition_at": self.last_transition_at,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Return a compact JSON string representation."""
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AttachedRuntimeSessionRecord":
        """Reconstruct a record from a dict produced by :meth:`to_dict`."""
        if not isinstance(data, dict):
            raise ValueError("AttachedRuntimeSessionRecord.from_dict: expected dict")

        raw_state = data.get("attachment_state", AttachmentState.attached.value)
        raw_prev = data.get("previous_state")
        raw_signal = data.get("last_signal")

        state = AttachmentState.from_string(str(raw_state)) if raw_state else AttachmentState.attached
        prev = AttachmentState.from_string(str(raw_prev)) if raw_prev else None
        signal = AttachmentLifecycleSignal.from_string(str(raw_signal)) if raw_signal else None

        return cls(
            record_id=data.get("record_id", str(uuid.uuid4())),
            device_id=data.get("device_id", ""),
            session_id=(
                data.get("runtime_attachment_session_id")
                or data.get("session_id", "")
            ),
            source_runtime_posture=data.get("source_runtime_posture", _POSTURE_JOIN_RUNTIME),
            coordination_role=data.get("coordination_role", ""),
            android_host_role=data.get("android_host_role", ""),
            capability_tier=data.get("capability_tier", ""),
            attachment_state=state,
            previous_state=prev,
            attach_reason=data.get("attach_reason", ""),
            last_signal=signal,
            attached_at=float(data.get("attached_at", time.time())),
            last_transition_at=float(data.get("last_transition_at", time.time())),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# AttachedRuntimeSessionSnapshot
# ---------------------------------------------------------------------------


@dataclass
class AttachedRuntimeSessionSnapshot:
    """Point-in-time snapshot of all attached-runtime session records.

    Attributes
    ----------
    snapshot_id
        Unique identifier for this snapshot.
    records
        List of all :class:`AttachedRuntimeSessionRecord` entries in the
        ring buffer at snapshot time (newest first).
    active_count
        Number of records whose ``attachment_state`` is ``attached``.
    total_count
        Total number of records in the snapshot.
    snapshotted_at
        Unix epoch seconds when this snapshot was assembled.
    policy_sentinels
        List of policy sentinel strings included for audit purposes.
    """

    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    records: List[AttachedRuntimeSessionRecord] = field(default_factory=list)
    active_count: int = 0
    total_count: int = 0
    snapshotted_at: float = field(default_factory=time.time)
    policy_sentinels: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "snapshot_id": self.snapshot_id,
            "records": [r.to_dict() for r in self.records],
            "active_count": self.active_count,
            "total_count": self.total_count,
            "snapshotted_at": self.snapshotted_at,
            "policy_sentinels": self.policy_sentinels,
        }

    def to_json(self) -> str:
        """Return a compact JSON string representation."""
        return json.dumps(self.to_dict(), separators=(",", ":"))


# ---------------------------------------------------------------------------
# AttachedRuntimeSessionRuntime  (128-entry ring buffer)
# ---------------------------------------------------------------------------


class AttachedRuntimeSessionRuntime:
    """In-process ring-buffer singleton for attached-runtime session records.

    Accumulates up to ``capacity`` (128) :class:`AttachedRuntimeSessionRecord`
    entries across the process lifetime.  Oldest entries are silently evicted
    when the buffer is full.

    This class is **not** intended for direct use by callers; use the
    module-level functions instead.
    """

    def __init__(self, capacity: int = _RING_BUFFER_CAPACITY) -> None:
        self._capacity = capacity
        self._buffer: Deque[AttachedRuntimeSessionRecord] = deque(maxlen=capacity)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def push(self, record: AttachedRuntimeSessionRecord) -> None:
        """Append *record* to the ring buffer."""
        self._buffer.append(record)

    def replace_latest_for_device(self, record: AttachedRuntimeSessionRecord) -> bool:
        """Replace the most recent record for ``record.device_id``.

        Returns True if a replacement was made, False if no prior record
        was found (in which case nothing is changed; caller must push).
        """
        for i in range(len(self._buffer) - 1, -1, -1):
            if self._buffer[i].device_id == record.device_id:
                # deque doesn't support index assignment directly
                buf_list = list(self._buffer)
                buf_list[i] = record
                self._buffer = deque(buf_list, maxlen=self._capacity)
                return True
        return False

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_latest_for_device(
        self, device_id: str
    ) -> Optional[AttachedRuntimeSessionRecord]:
        """Return the most recent record for *device_id*, or None."""
        for record in reversed(self._buffer):
            if record.device_id == device_id:
                return record
        return None

    def list_all(self) -> List[AttachedRuntimeSessionRecord]:
        """Return all records, newest first."""
        return list(reversed(self._buffer))

    def list_active(self) -> List[AttachedRuntimeSessionRecord]:
        """Return records whose ``attachment_state`` is ``attached``, newest first."""
        return [r for r in reversed(self._buffer) if r.is_active()]

    def size(self) -> int:
        """Return the current number of records in the buffer."""
        return len(self._buffer)

    def capacity(self) -> int:
        """Return the maximum capacity of the buffer."""
        return self._capacity

    def clear(self) -> None:
        """Remove all records (useful for testing)."""
        self._buffer.clear()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_RUNTIME_SINGLETON: Optional[AttachedRuntimeSessionRuntime] = None


def get_attached_runtime_session_runtime() -> AttachedRuntimeSessionRuntime:
    """Return the module-level :class:`AttachedRuntimeSessionRuntime` singleton.

    Creates the singleton on first call.
    """
    global _RUNTIME_SINGLETON  # noqa: PLW0603
    if _RUNTIME_SINGLETON is None:
        _RUNTIME_SINGLETON = AttachedRuntimeSessionRuntime(capacity=_RING_BUFFER_CAPACITY)
    return _RUNTIME_SINGLETON


def reset_attached_runtime_session_runtime() -> None:
    """Reset the singleton (primarily for test isolation)."""
    global _RUNTIME_SINGLETON  # noqa: PLW0603
    _RUNTIME_SINGLETON = None


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def attach_runtime_session(
    device_id: str,
    *,
    source_runtime_posture: str = _POSTURE_JOIN_RUNTIME,
    coordination_role: str = "",
    android_host_role: str = "",
    capability_tier: str = "",
    session_id: str = "",
    runtime_attachment_session_id: str = "",
    attach_reason: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    runtime: Optional[AttachedRuntimeSessionRuntime] = None,
) -> AttachedRuntimeSessionRecord:
    """Attach a device/runtime as a persistent session-level participant.

    Idempotent: if the device already has an ``attached`` record the existing
    record is refreshed (posture, role, reason, and timestamp updated) rather
    than creating a duplicate.

    A ``control_only`` device cannot be attached as a first-class session
    participant; in that case the returned record has
    ``attachment_state=detached`` and an explanatory ``attach_reason``.

    Parameters
    ----------
    device_id
        Identifier of the device/runtime to attach.
    source_runtime_posture
        Posture of the source device.  Must be 'join_runtime' to achieve
        ``attached`` state.
    coordination_role
        Coordination role for this participant.
    android_host_role
        AndroidRuntimeHostRole string (PR-5), informational.
    capability_tier
        CapabilityTier string (PR package 6), informational.
    session_id
        Optional external session/correlation identifier.
    runtime_attachment_session_id
        Canonical runtime attachment session identifier.  When supplied, this
        takes precedence over ``session_id``.
    attach_reason
        Human-readable reason for this attach operation.
    metadata
        Arbitrary caller-supplied metadata.
    runtime
        Optional runtime to use; defaults to the module singleton.

    Returns
    -------
    AttachedRuntimeSessionRecord
        The newly created or refreshed record.
    """
    if runtime is None:
        runtime = get_attached_runtime_session_runtime()

    posture = (source_runtime_posture or _POSTURE_CONTROL_ONLY).lower().strip()
    resolved_runtime_attachment_session_id = runtime_attachment_session_id or session_id
    existing = runtime.get_latest_for_device(device_id)
    lifecycle_action = classify_attach_lifecycle_action(existing, posture)

    # Policy: only join_runtime posture may attach
    if lifecycle_action == AttachmentLifecycleAction.rejected:
        record = AttachedRuntimeSessionRecord(
            device_id=device_id,
            source_runtime_posture=posture,
            coordination_role=coordination_role or "",
            android_host_role=android_host_role or "",
            capability_tier=capability_tier or "",
            attachment_state=AttachmentState.detached,
            previous_state=None,
            session_id=resolved_runtime_attachment_session_id or "",
            attach_reason=(
                attach_reason
                or f"attach blocked: posture={posture!r} is not join_runtime.  "
                f"Policy: {ATTACHED_SESSION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY}"
            ),
            last_signal=AttachmentLifecycleSignal.attach,
            metadata=metadata or {},
        )
        runtime.push(record)
        return record

    now = time.time()

    if lifecycle_action == AttachmentLifecycleAction.reconcile and existing is not None:
        # Idempotent re-attach: refresh fields on the existing record
        updated = AttachedRuntimeSessionRecord(
            record_id=existing.record_id,
            device_id=device_id,
            source_runtime_posture=posture,
            coordination_role=coordination_role or existing.coordination_role,
            android_host_role=android_host_role or existing.android_host_role,
            capability_tier=capability_tier or existing.capability_tier,
            attachment_state=AttachmentState.attached,
            previous_state=existing.attachment_state,
            session_id=resolved_runtime_attachment_session_id or existing.session_id,
            attach_reason=attach_reason or existing.attach_reason,
            last_signal=AttachmentLifecycleSignal.attach,
            attached_at=existing.attached_at,
            last_transition_at=now,
            metadata={**existing.metadata, **(metadata or {})},
        )
        replaced = runtime.replace_latest_for_device(updated)
        if not replaced:
            runtime.push(updated)
        return updated

    # New attach (or re-attach from non-attached state)
    record = AttachedRuntimeSessionRecord(
        device_id=device_id,
        source_runtime_posture=posture,
        coordination_role=coordination_role or "",
        android_host_role=android_host_role or "",
        capability_tier=capability_tier or "",
        attachment_state=AttachmentState.attached,
        previous_state=existing.attachment_state if existing else None,
        session_id=resolved_runtime_attachment_session_id or "",
        attach_reason=attach_reason or "",
        last_signal=AttachmentLifecycleSignal.attach,
        attached_at=now,
        last_transition_at=now,
        metadata=metadata or {},
    )
    runtime.push(record)
    return record


def apply_lifecycle_signal(
    record: AttachedRuntimeSessionRecord,
    signal: AttachmentLifecycleSignal,
    *,
    reason: str = "",
    runtime: Optional[AttachedRuntimeSessionRuntime] = None,
) -> AttachedRuntimeSessionRecord:
    """Apply a lifecycle signal to an existing session record.

    Returns the updated record.  If the signal results in a state change the
    updated record is persisted into the ring buffer (replacing the old entry
    if possible, otherwise pushing a new entry).

    If the current state is ``invalidated``, no signal other than ``attach``
    can effect a transition (terminal state).

    Parameters
    ----------
    record
        The record to update.
    signal
        The :class:`AttachmentLifecycleSignal` to apply.
    reason
        Optional human-readable reason for this transition.
    runtime
        Optional runtime to use; defaults to the module singleton.

    Returns
    -------
    AttachedRuntimeSessionRecord
        Updated record (may be the same object if no transition occurred).
    """
    if runtime is None:
        runtime = get_attached_runtime_session_runtime()

    current = record.attachment_state
    lifecycle_action = classify_signal_lifecycle_action(record, signal)

    # Terminal: invalidated sessions cannot transition
    if current == AttachmentState.invalidated and signal != AttachmentLifecycleSignal.attach:
        return record

    if lifecycle_action == AttachmentLifecycleAction.no_change:
        return record

    next_state = _TRANSITION_TABLE.get((current, signal))
    if next_state is None:
        return record

    now = time.time()
    updated = AttachedRuntimeSessionRecord(
        record_id=record.record_id,
        device_id=record.device_id,
        source_runtime_posture=record.source_runtime_posture,
        coordination_role=record.coordination_role,
        android_host_role=record.android_host_role,
        capability_tier=record.capability_tier,
        attachment_state=next_state,
        previous_state=current,
        session_id=record.session_id,
        attach_reason=reason or record.attach_reason,
        last_signal=signal,
        attached_at=record.attached_at,
        last_transition_at=now,
        metadata=dict(record.metadata),
    )

    replaced = runtime.replace_latest_for_device(updated)
    if not replaced:
        runtime.push(updated)

    return updated


def get_attached_runtime_session(
    device_id: str,
    *,
    runtime: Optional[AttachedRuntimeSessionRuntime] = None,
) -> Optional[AttachedRuntimeSessionRecord]:
    """Return the most recent session record for *device_id*, or None.

    Parameters
    ----------
    device_id
        The device identifier to look up.
    runtime
        Optional runtime to use; defaults to the module singleton.
    """
    if runtime is None:
        runtime = get_attached_runtime_session_runtime()
    return runtime.get_latest_for_device(device_id)


def list_active_attached_sessions(
    *,
    runtime: Optional[AttachedRuntimeSessionRuntime] = None,
) -> List[AttachedRuntimeSessionRecord]:
    """Return all records whose ``attachment_state`` is ``attached``.

    Parameters
    ----------
    runtime
        Optional runtime to use; defaults to the module singleton.
    """
    if runtime is None:
        runtime = get_attached_runtime_session_runtime()
    return runtime.list_active()


def build_attached_runtime_session_snapshot(
    *,
    runtime: Optional[AttachedRuntimeSessionRuntime] = None,
) -> AttachedRuntimeSessionSnapshot:
    """Assemble a point-in-time snapshot of the ring-buffer state.

    Parameters
    ----------
    runtime
        Optional runtime to use; defaults to the module singleton.
    """
    if runtime is None:
        runtime = get_attached_runtime_session_runtime()

    all_records = runtime.list_all()
    active_count = sum(1 for r in all_records if r.is_active())

    return AttachedRuntimeSessionSnapshot(
        records=all_records,
        active_count=active_count,
        total_count=len(all_records),
        policy_sentinels=[
            ATTACHED_RUNTIME_SESSION_AUTHORITY,
            ATTACHED_SESSION_PERSISTS_ACROSS_REQUESTS_POLICY,
            TRANSIENT_PRESENCE_DISTINCT_FROM_ATTACHED_SESSION_POLICY,
            DETACH_SIGNAL_REQUIRED_FOR_SESSION_TERMINATION_POLICY,
            ATTACH_IS_IDEMPOTENT_POLICY,
            DISCONNECTED_DOES_NOT_INVALIDATE_SESSION_POLICY,
            INVALIDATED_SESSION_IS_TERMINAL_POLICY,
            DISABLED_SESSION_NOT_ELIGIBLE_FOR_EXECUTION_POLICY,
            ATTACHED_SESSION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
            ATTACHMENT_LIFECYCLE_IS_POSTURE_AWARE_POLICY,
        ],
    )
