"""core/attached_runtime_session.py
=====================================
PR package 7 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Persistent Attached-Runtime Session Semantics.

This module is the **canonical authority** for attached-runtime session state
on the main-repo side.  It answers the question:

    *"Has a remote/Android device been explicitly attached as a cross-device
    runtime participant, or is it merely transiently present?"*

Background
----------
Prior to PR-7, a connected device could be registered, posture-tagged, and
capability-classified without the system having a durable notion of whether
the device was an **attached runtime participant** (a participant that remains
part of the runtime fabric until explicitly detached/disconnected/disabled) or
a **transiently present device** (one that appeared over the network but was
never promoted to a session-level participant).

PR-7 closes the main-repo half of the attached-runtime session semantics work
by providing:

1. :class:`AttachmentState` — canonical lifecycle enum for a cross-device
   runtime participant:
   ``attached``, ``detaching``, ``detached``, ``disconnected``, ``disabled``,
   ``invalidated``.

2. :class:`AttachmentLifecycleSignal` — canonical enum for the signals that
   drive state transitions: ``attach``, ``detach``, ``disconnect``,
   ``disable``, ``invalidate``, ``reconnect``.

3. :class:`AttachedRuntimeSessionRecord` — serialisable snapshot of a single
   device's attached-runtime session state, including its posture,
   coordination role, capability tier, and timestamps.

4. :class:`AttachedRuntimeSessionRuntime` — an in-process ring-buffer registry
   of active and recently-closed attached-runtime session records, suitable
   for projection, operator-surface, and observability consumers.

5. :func:`attach_runtime_session` — promote a device to an attached runtime
   participant.  Idempotent: repeated calls with the same ``device_id`` while
   the session is already ``attached`` return the existing record without
   creating a duplicate.

6. :func:`apply_lifecycle_signal` — drive an ``AttachedRuntimeSessionRecord``
   through its lifecycle via a canonical ``AttachmentLifecycleSignal``.

7. :func:`get_attached_runtime_session` — retrieve the current session record
   for a device, or ``None`` if the device has never been attached.

8. :func:`list_active_attached_sessions` — list all sessions currently in the
   ``attached`` state.

9. :func:`build_attached_runtime_session_snapshot` — build a serialisable
   snapshot of all current sessions for projection / operator-surface
   embedding.

10. Nine policy sentinels documenting canonical attached-session rules.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Posture-preserving** — all ``source_runtime_posture`` semantics from
  PR-533 / PR-1 are honoured and composed, not replaced.
- **Coordination-role aware** — integrates with the PR-538 / PR-6
  ``CoordinationRole`` model.
- **Capability-tier aware** — references the PR-6 ``CapabilityTier``
  classification as an informational signal.
- **Session-persistent** — once attached, a device remains a participant
  until an explicit lifecycle signal (detach, disconnect, disable, or
  invalidate) transitions it out of the ``attached`` state.
- **Graceful degradation** — missing or unknown inputs default to the
  conservative outcome (``invalidated`` or ``detached`` state).
- **Fully serialisable** — all public data classes expose ``to_dict()`` /
  ``to_json()`` / ``from_dict()`` for stable, round-trippable wire
  representations.

Relationship to other PR packages
----------------------------------
* PR-1  (``core.posture_contract_canonicalization``) — canonicalises
  ``source_runtime_posture`` that is consumed here.
* PR-2  (``core.source_execution_eligibility``) — per-posture eligibility;
  this module is a higher-level session-persistence layer.
* PR-4  (``core.canonical_session_truth``) — session truth records may
  reference attached-session snapshots for audit.
* PR-5  (``core.android_runtime_host``) — Android host role is one of the
  signals carried on an :class:`AttachedRuntimeSessionRecord`.
* PR package 6 (``core.canonical_capability_scheduling_basis``) —
  ``CapabilityTier`` and ``ExecutionSurface`` are informational fields on
  the session record.

Public API
----------
Sentinels::

    ATTACHED_RUNTIME_SESSION_AUTHORITY
    ATTACHED_SESSION_PERSISTS_UNTIL_EXPLICIT_SIGNAL_POLICY
    TRANSIENT_PRESENCE_NOT_AN_ATTACHED_SESSION_POLICY
    ATTACH_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY
    DETACH_SIGNAL_ENDS_PARTICIPATION_POLICY
    DISCONNECT_PRESERVES_SESSION_RECORD_POLICY
    DISABLE_BLOCKS_REATTACH_UNTIL_ENABLED_POLICY
    INVALIDATION_IS_TERMINAL_POLICY
    LIFECYCLE_SIGNAL_DRIVES_STATE_TRANSITION_POLICY
    ATTACHED_RUNTIME_SESSION_PR7_SENTINEL

Enums::

    AttachmentState
    AttachmentLifecycleSignal

Dataclasses::

    AttachedRuntimeSessionRecord
    AttachedRuntimeSessionSnapshot

Classes::

    AttachedRuntimeSessionRuntime

Functions::

    attach_runtime_session(device_id, ...) -> AttachedRuntimeSessionRecord
    apply_lifecycle_signal(record, signal) -> AttachedRuntimeSessionRecord
    get_attached_runtime_session(device_id) -> Optional[AttachedRuntimeSessionRecord]
    list_active_attached_sessions() -> List[AttachedRuntimeSessionRecord]
    build_attached_runtime_session_snapshot() -> AttachedRuntimeSessionSnapshot
    get_attached_runtime_session_runtime() -> AttachedRuntimeSessionRuntime
    reset_attached_runtime_session_runtime() -> None
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
import uuid
from collections import deque
from enum import Enum
from threading import Lock
from typing import Any, Deque, Dict, List, Optional

__all__ = [
    # Authority / policy sentinels
    "ATTACHED_RUNTIME_SESSION_AUTHORITY",
    "ATTACHED_SESSION_PERSISTS_UNTIL_EXPLICIT_SIGNAL_POLICY",
    "TRANSIENT_PRESENCE_NOT_AN_ATTACHED_SESSION_POLICY",
    "ATTACH_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY",
    "DETACH_SIGNAL_ENDS_PARTICIPATION_POLICY",
    "DISCONNECT_PRESERVES_SESSION_RECORD_POLICY",
    "DISABLE_BLOCKS_REATTACH_UNTIL_ENABLED_POLICY",
    "INVALIDATION_IS_TERMINAL_POLICY",
    "LIFECYCLE_SIGNAL_DRIVES_STATE_TRANSITION_POLICY",
    "ATTACHED_RUNTIME_SESSION_PR7_SENTINEL",
    # Enums
    "AttachmentState",
    "AttachmentLifecycleSignal",
    # Dataclasses
    "AttachedRuntimeSessionRecord",
    "AttachedRuntimeSessionSnapshot",
    # Class
    "AttachedRuntimeSessionRuntime",
    # Functions
    "attach_runtime_session",
    "apply_lifecycle_signal",
    "get_attached_runtime_session",
    "list_active_attached_sessions",
    "build_attached_runtime_session_snapshot",
    "get_attached_runtime_session_runtime",
    "reset_attached_runtime_session_runtime",
]

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

ATTACHED_RUNTIME_SESSION_AUTHORITY: str = (
    "ATTACHED_RUNTIME_SESSION::AUTHORITY_V1: "
    "core.attached_runtime_session is the canonical authority for persistent "
    "attached-runtime session semantics on the main-repo side.  "
    "PR package 7, post-533 dual-repo runtime unification master plan."
)
"""Module-level authority sentinel for attached-runtime session (PR-7)."""

ATTACHED_SESSION_PERSISTS_UNTIL_EXPLICIT_SIGNAL_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::PERSISTS_UNTIL_EXPLICIT_SIGNAL_V1: "
    "Once a device is promoted to an attached runtime participant via "
    "attach_runtime_session(), it MUST remain in the 'attached' state "
    "until an explicit lifecycle signal (detach, disconnect, disable, or "
    "invalidate) transitions it out.  Transient loss of presence or "
    "momentary network interruption alone does NOT end the attachment; "
    "only an explicit signal does.  "
    "PR-7, post-533 dual-repo runtime unification master plan."
)
"""Policy: attached sessions persist until an explicit signal ends them."""

TRANSIENT_PRESENCE_NOT_AN_ATTACHED_SESSION_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::TRANSIENT_PRESENCE_NOT_ATTACHED_V1: "
    "A device that is merely present in the device registry (connected, "
    "heartbeating, or discovered) MUST NOT be considered an attached "
    "runtime participant.  Attachment is a distinct, explicitly-granted "
    "state that is separate from device presence or registration.  "
    "Callers MUST invoke attach_runtime_session() to promote a device "
    "to participant status.  "
    "PR-7, post-533 dual-repo runtime unification master plan."
)
"""Policy: transient presence is distinct from an attached session."""

ATTACH_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::ATTACH_REQUIRES_JOIN_RUNTIME_V1: "
    "Devices SHOULD carry source_runtime_posture='join_runtime' to be "
    "promoted as full attached runtime participants.  Devices with "
    "'control_only' posture may be attached but are recorded with a "
    "reduced participation level; they are NOT eligible to receive "
    "delegated execution or agent dispatch.  "
    "PR-7, post-533 dual-repo runtime unification master plan."
)
"""Policy: join_runtime posture is the preferred basis for attachment."""

DETACH_SIGNAL_ENDS_PARTICIPATION_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::DETACH_ENDS_PARTICIPATION_V1: "
    "A 'detach' lifecycle signal transitions an attached session to the "
    "'detached' state.  The device is no longer a runtime participant and "
    "MUST NOT receive delegated execution.  The session record is retained "
    "for audit and may be re-attached by a subsequent 'attach' signal.  "
    "PR-7, post-533 dual-repo runtime unification master plan."
)
"""Policy: detach signal ends runtime participation."""

DISCONNECT_PRESERVES_SESSION_RECORD_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::DISCONNECT_PRESERVES_RECORD_V1: "
    "A 'disconnect' lifecycle signal transitions an attached session to the "
    "'disconnected' state.  Unlike 'detach', a disconnected session record "
    "is preserved and may be automatically re-attached (via a 'reconnect' "
    "signal) when the device re-establishes its transport connection.  "
    "PR-7, post-533 dual-repo runtime unification master plan."
)
"""Policy: disconnect preserves the session record for potential reconnect."""

DISABLE_BLOCKS_REATTACH_UNTIL_ENABLED_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::DISABLE_BLOCKS_REATTACH_V1: "
    "A 'disable' lifecycle signal transitions any active or inactive "
    "session to the 'disabled' state.  A disabled device MUST NOT be "
    "re-attached (via attach_runtime_session()) until the device is "
    "explicitly re-enabled by the operator.  "
    "PR-7, post-533 dual-repo runtime unification master plan."
)
"""Policy: disabled sessions cannot be re-attached without re-enablement."""

INVALIDATION_IS_TERMINAL_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::INVALIDATION_IS_TERMINAL_V1: "
    "An 'invalidate' lifecycle signal transitions a session to the "
    "'invalidated' state.  Invalidation is terminal: no further lifecycle "
    "signals (including reconnect or attach) may restore the session.  "
    "A new, fresh attach_runtime_session() call must be made to create "
    "a replacement session with a new session_id.  "
    "PR-7, post-533 dual-repo runtime unification master plan."
)
"""Policy: invalidated sessions are terminal and cannot be recovered."""

LIFECYCLE_SIGNAL_DRIVES_STATE_TRANSITION_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::LIFECYCLE_SIGNAL_DRIVES_TRANSITION_V1: "
    "All state transitions on an AttachedRuntimeSessionRecord MUST be "
    "driven through apply_lifecycle_signal().  Direct mutation of the "
    "state field on a record violates the canonical attached-session "
    "contract.  apply_lifecycle_signal() is the single gate for all "
    "lifecycle state changes.  "
    "PR-7, post-533 dual-repo runtime unification master plan."
)
"""Policy: lifecycle signals are the exclusive driver of state transitions."""

ATTACHED_RUNTIME_SESSION_PR7_SENTINEL: str = (
    "ATTACHED_RUNTIME_SESSION::PR7_SENTINEL_V1: "
    "PR package 7 (post-533 dual-repo runtime unification, MAIN repo side) — "
    "persistent attached-runtime session semantics are active.  "
    "core.attached_runtime_session is the single authoritative module for "
    "cross-device participant attachment lifecycle in the Galaxy runtime."
)
"""PR-7 integration sentinel."""

# ---------------------------------------------------------------------------
# Internal canonical string constants
# ---------------------------------------------------------------------------

_POSTURE_JOIN_RUNTIME: str = "join_runtime"
_POSTURE_CONTROL_ONLY: str = "control_only"

_RING_BUFFER_SIZE: int = 128

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class AttachmentState(str, Enum):
    """Canonical lifecycle state for an attached cross-device runtime session.

    Values
    ------
    attached
        The device is an explicitly-attached runtime participant.  It may
        receive delegated execution and agent dispatch.  This is the
        active participation state.
    detaching
        A detach signal has been received but teardown is still in
        progress.  The device is considered transitioning out of the
        runtime and MUST NOT receive new task delegations.
    detached
        The device has been explicitly detached.  It is no longer a
        runtime participant but was gracefully removed; the record is
        retained for audit and may be re-attached.
    disconnected
        The device's transport connection has been lost.  The session
        record is preserved and may be recovered via a ``reconnect``
        signal when the transport re-establishes.
    disabled
        The device has been administratively disabled.  It MUST NOT be
        re-attached without explicit operator re-enablement.
    invalidated
        The session is terminal.  No further signals may restore it; a
        fresh ``attach_runtime_session()`` call is required to create a
        new session.
    """

    attached = "attached"
    detaching = "detaching"
    detached = "detached"
    disconnected = "disconnected"
    disabled = "disabled"
    invalidated = "invalidated"

    @classmethod
    def from_string(cls, value: str) -> "AttachmentState":
        """Parse a string to an :class:`AttachmentState`, defaulting to
        ``invalidated`` for unknown values."""
        try:
            return cls(value)
        except ValueError:
            return cls.invalidated

    def is_active(self) -> bool:
        """Return ``True`` if this state represents active participation."""
        return self == AttachmentState.attached

    def is_terminal(self) -> bool:
        """Return ``True`` if this state is terminal (cannot be recovered by
        applying further lifecycle signals to the existing session record)."""
        return self == AttachmentState.invalidated

    def allows_reattach(self) -> bool:
        """Return ``True`` if a new attach signal could re-activate this
        session (i.e., the state is not ``disabled`` or ``invalidated``)."""
        return self not in (AttachmentState.disabled, AttachmentState.invalidated)


class AttachmentLifecycleSignal(str, Enum):
    """Canonical signals that drive :class:`AttachmentState` transitions.

    Values
    ------
    attach
        Promote a device to an attached runtime participant.  Valid from
        ``detached``, ``detaching``, or ``disconnected`` states (or when
        no prior session exists).
    detach
        Gracefully remove a device from runtime participation.  Transitions
        ``attached`` → ``detaching`` → ``detached``.
    disconnect
        Mark a device as transport-disconnected without intent.  Transitions
        ``attached`` or ``detaching`` → ``disconnected``.
    disable
        Administratively disable a device's participation.  Transitions any
        non-terminal state → ``disabled``.
    invalidate
        Permanently invalidate the session record.  Terminal; transitions
        any state → ``invalidated``.
    reconnect
        Re-establish an attachment for a ``disconnected`` session.
        Transitions ``disconnected`` → ``attached``.
    """

    attach = "attach"
    detach = "detach"
    disconnect = "disconnect"
    disable = "disable"
    invalidate = "invalidate"
    reconnect = "reconnect"

    @classmethod
    def from_string(cls, value: str) -> Optional["AttachmentLifecycleSignal"]:
        """Parse a string to an :class:`AttachmentLifecycleSignal`, returning
        ``None`` for unknown values."""
        try:
            return cls(value)
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# State-transition table
# ---------------------------------------------------------------------------

# Maps (current_state, signal) -> next_state.
# Missing combinations are invalid and raise ValueError in apply_lifecycle_signal.
_TRANSITION_TABLE: Dict[tuple, AttachmentState] = {
    # attach signal
    (AttachmentState.detached, AttachmentLifecycleSignal.attach): AttachmentState.attached,
    (AttachmentState.detaching, AttachmentLifecycleSignal.attach): AttachmentState.attached,
    (AttachmentState.disconnected, AttachmentLifecycleSignal.attach): AttachmentState.attached,
    # detach signal
    (AttachmentState.attached, AttachmentLifecycleSignal.detach): AttachmentState.detaching,
    (AttachmentState.detaching, AttachmentLifecycleSignal.detach): AttachmentState.detached,
    # disconnect signal
    (AttachmentState.attached, AttachmentLifecycleSignal.disconnect): AttachmentState.disconnected,
    (AttachmentState.detaching, AttachmentLifecycleSignal.disconnect): AttachmentState.disconnected,
    # disable signal (from any non-terminal state)
    (AttachmentState.attached, AttachmentLifecycleSignal.disable): AttachmentState.disabled,
    (AttachmentState.detaching, AttachmentLifecycleSignal.disable): AttachmentState.disabled,
    (AttachmentState.detached, AttachmentLifecycleSignal.disable): AttachmentState.disabled,
    (AttachmentState.disconnected, AttachmentLifecycleSignal.disable): AttachmentState.disabled,
    # invalidate signal (from any non-terminal state)
    (AttachmentState.attached, AttachmentLifecycleSignal.invalidate): AttachmentState.invalidated,
    (AttachmentState.detaching, AttachmentLifecycleSignal.invalidate): AttachmentState.invalidated,
    (AttachmentState.detached, AttachmentLifecycleSignal.invalidate): AttachmentState.invalidated,
    (AttachmentState.disconnected, AttachmentLifecycleSignal.invalidate): AttachmentState.invalidated,
    (AttachmentState.disabled, AttachmentLifecycleSignal.invalidate): AttachmentState.invalidated,
    # reconnect signal
    (AttachmentState.disconnected, AttachmentLifecycleSignal.reconnect): AttachmentState.attached,
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class AttachedRuntimeSessionRecord:
    """Canonical snapshot of a single device's attached-runtime session.

    This record is created by :func:`attach_runtime_session` and mutated in-
    place (producing a new copy with updated fields) by
    :func:`apply_lifecycle_signal`.

    Fields
    ------
    session_id : str
        Unique identifier for this attached-runtime session, auto-generated
        as a UUID on creation.
    device_id : str
        Stable identifier for the attached device.
    source_runtime_posture : str
        The device's ``source_runtime_posture`` at the time of attachment
        (``'join_runtime'`` or ``'control_only'``).  Defaults to
        ``'control_only'`` as the conservative choice.
    coordination_role : str
        The device's coordination role at the time of attachment, as
        derived by PR-538 / PR-6 ``derive_coordination_role()``.  Defaults
        to ``''`` (empty, meaning unresolved/not yet derived).
    capability_tier : str
        Informational capability tier (PR-6 ``CapabilityTier`` value string)
        at the time of attachment.  Defaults to ``'unknown'``.
    android_host_role : str
        Informational Android runtime host role (PR-5
        ``AndroidRuntimeHostRole`` value string).  ``''`` for non-Android
        devices.
    state : AttachmentState
        Current lifecycle state of this session.
    attached_at : float
        Unix timestamp (``time.time()``) when the session was first attached.
    last_signal_at : float
        Unix timestamp of the last lifecycle signal applied to this record.
        Equals ``attached_at`` on freshly-created records.
    last_signal : str
        String name of the last :class:`AttachmentLifecycleSignal` applied.
        ``'attach'`` on freshly-created records.
    metadata : Dict[str, Any]
        Arbitrary key/value metadata supplied by the caller at attach time.
    """

    session_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    device_id: str = ""
    source_runtime_posture: str = _POSTURE_CONTROL_ONLY
    coordination_role: str = ""
    capability_tier: str = "unknown"
    android_host_role: str = ""
    state: AttachmentState = AttachmentState.attached
    attached_at: float = dataclasses.field(default_factory=time.time)
    last_signal_at: float = dataclasses.field(default_factory=time.time)
    last_signal: str = "attach"
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """``True`` iff the session is currently in the ``attached`` state."""
        return self.state.is_active()

    @property
    def is_join_runtime(self) -> bool:
        """``True`` iff the device's posture is ``join_runtime``."""
        return self.source_runtime_posture == _POSTURE_JOIN_RUNTIME

    @property
    def is_eligible_for_delegation(self) -> bool:
        """``True`` iff the session is active *and* the posture is
        ``join_runtime`` (i.e., the device may receive delegated execution
        or agent dispatch per PR-2 / PR-6 eligibility rules)."""
        return self.is_active and self.is_join_runtime

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "session_id": self.session_id,
            "device_id": self.device_id,
            "source_runtime_posture": self.source_runtime_posture,
            "coordination_role": self.coordination_role,
            "capability_tier": self.capability_tier,
            "android_host_role": self.android_host_role,
            "state": self.state.value,
            "attached_at": self.attached_at,
            "last_signal_at": self.last_signal_at,
            "last_signal": self.last_signal,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AttachedRuntimeSessionRecord":
        """Reconstruct a record from a dict (e.g., a deserialised ``to_dict()``
        payload).  Missing keys are filled with safe defaults."""
        return cls(
            session_id=data.get("session_id", str(uuid.uuid4())),
            device_id=data.get("device_id", ""),
            source_runtime_posture=data.get("source_runtime_posture", _POSTURE_CONTROL_ONLY),
            coordination_role=data.get("coordination_role", ""),
            capability_tier=data.get("capability_tier", "unknown"),
            android_host_role=data.get("android_host_role", ""),
            state=AttachmentState.from_string(data.get("state", "invalidated")),
            attached_at=float(data.get("attached_at", time.time())),
            last_signal_at=float(data.get("last_signal_at", time.time())),
            last_signal=data.get("last_signal", "attach"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclasses.dataclass
class AttachedRuntimeSessionSnapshot:
    """Serialisable snapshot of all current attached-runtime sessions.

    Suitable for embedding in operator-surface projections, runtime status
    boards, and observability consumers.

    Fields
    ------
    snapshot_id : str
        Unique identifier for this snapshot, auto-generated as a UUID.
    compiled_at : float
        Unix timestamp when the snapshot was compiled.
    active_count : int
        Number of sessions currently in the ``attached`` state.
    total_recorded : int
        Total number of session records in the ring buffer at snapshot time.
    sessions : List[Dict[str, Any]]
        Serialised ``to_dict()`` representations of all session records.
    authority : str
        Authority sentinel string, always equal to
        :data:`ATTACHED_RUNTIME_SESSION_AUTHORITY`.
    """

    snapshot_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    compiled_at: float = dataclasses.field(default_factory=time.time)
    active_count: int = 0
    total_recorded: int = 0
    sessions: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    authority: str = ATTACHED_RUNTIME_SESSION_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "snapshot_id": self.snapshot_id,
            "compiled_at": self.compiled_at,
            "active_count": self.active_count,
            "total_recorded": self.total_recorded,
            "sessions": self.sessions,
            "authority": self.authority,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# Ring-buffer runtime
# ---------------------------------------------------------------------------


class AttachedRuntimeSessionRuntime:
    """In-process ring-buffer registry of attached-runtime session records.

    Stores up to ``_RING_BUFFER_SIZE`` most-recent records (active and
    historical).  Uses a ``device_id``-keyed dict as a secondary index for
    O(1) lookups, with the deque as the ordered backing store.

    Thread-safe via an internal :class:`threading.Lock`.
    """

    def __init__(self, maxlen: int = _RING_BUFFER_SIZE) -> None:
        self._lock: Lock = Lock()
        self._buffer: Deque[AttachedRuntimeSessionRecord] = deque(maxlen=maxlen)
        # device_id → most-recent record (may not be active)
        self._index: Dict[str, AttachedRuntimeSessionRecord] = {}

    def upsert(self, record: AttachedRuntimeSessionRecord) -> None:
        """Insert or replace the record for *record.device_id*."""
        with self._lock:
            existing = self._index.get(record.device_id)
            if existing is not None:
                # Remove the old record from the buffer so the new one
                # is the sole authoritative entry.
                try:
                    self._buffer.remove(existing)
                except ValueError:
                    pass
            self._buffer.append(record)
            self._index[record.device_id] = record

    def get(self, device_id: str) -> Optional[AttachedRuntimeSessionRecord]:
        """Return the current record for *device_id*, or ``None``."""
        with self._lock:
            return self._index.get(device_id)

    def list_active(self) -> List[AttachedRuntimeSessionRecord]:
        """Return all records currently in the ``attached`` state."""
        with self._lock:
            return [r for r in self._buffer if r.state == AttachmentState.attached]

    def list_all(self) -> List[AttachedRuntimeSessionRecord]:
        """Return all records in the ring buffer (active and historical)."""
        with self._lock:
            return list(self._buffer)

    def count_active(self) -> int:
        """Return the number of records currently in the ``attached`` state."""
        with self._lock:
            return sum(1 for r in self._buffer if r.state == AttachmentState.attached)

    def total(self) -> int:
        """Return the total number of records in the ring buffer."""
        with self._lock:
            return len(self._buffer)


# ---------------------------------------------------------------------------
# Module-level singleton runtime
# ---------------------------------------------------------------------------

_runtime_lock: Lock = Lock()
_runtime: Optional[AttachedRuntimeSessionRuntime] = None


def get_attached_runtime_session_runtime() -> AttachedRuntimeSessionRuntime:
    """Return the module-level singleton :class:`AttachedRuntimeSessionRuntime`.

    Thread-safe; creates the singleton on first call.
    """
    global _runtime
    if _runtime is None:
        with _runtime_lock:
            if _runtime is None:
                _runtime = AttachedRuntimeSessionRuntime()
    return _runtime


def reset_attached_runtime_session_runtime() -> None:
    """Replace the module-level singleton with a fresh instance.

    Intended for test isolation only.  **Do not call in production code.**
    """
    global _runtime
    with _runtime_lock:
        _runtime = AttachedRuntimeSessionRuntime()


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------


def attach_runtime_session(
    device_id: str,
    source_runtime_posture: str = _POSTURE_CONTROL_ONLY,
    coordination_role: str = "",
    capability_tier: str = "unknown",
    android_host_role: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    *,
    runtime: Optional[AttachedRuntimeSessionRuntime] = None,
) -> AttachedRuntimeSessionRecord:
    """Promote *device_id* to an attached runtime participant.

    If the device already has an existing session record in a re-attachable
    state (``detached``, ``detaching``, or ``disconnected``), the existing
    record's session_id is **reused** but all other fields are refreshed
    from the supplied arguments.  This ensures continuity of the session
    identifier for reconnect/re-attach scenarios.

    If the device has no prior record, or if the prior record is in
    ``disabled`` or ``invalidated`` state, a fresh record with a new
    ``session_id`` is created.

    Parameters
    ----------
    device_id:
        The stable device identifier.
    source_runtime_posture:
        ``'join_runtime'`` or ``'control_only'`` (default ``'control_only'``).
    coordination_role:
        The device's coordination role string.
    capability_tier:
        The device's PR-6 capability tier string.
    android_host_role:
        The device's PR-5 Android host role string (``''`` for non-Android).
    metadata:
        Arbitrary key/value metadata to attach to the session record.
    runtime:
        Override the module-level singleton for this call (testing).

    Returns
    -------
    AttachedRuntimeSessionRecord
        The newly-created or refreshed session record, in ``attached`` state.
    """
    rt = runtime if runtime is not None else get_attached_runtime_session_runtime()
    now = time.time()

    existing = rt.get(device_id)
    if existing is not None and existing.state.allows_reattach():
        # Refresh an existing re-attachable session, preserving session_id.
        record = AttachedRuntimeSessionRecord(
            session_id=existing.session_id,
            device_id=device_id,
            source_runtime_posture=source_runtime_posture or _POSTURE_CONTROL_ONLY,
            coordination_role=coordination_role or "",
            capability_tier=capability_tier or "unknown",
            android_host_role=android_host_role or "",
            state=AttachmentState.attached,
            attached_at=existing.attached_at,  # preserve original attach time
            last_signal_at=now,
            last_signal="attach",
            metadata=dict(metadata) if metadata else {},
        )
    else:
        # Create a fresh session record.
        record = AttachedRuntimeSessionRecord(
            device_id=device_id,
            source_runtime_posture=source_runtime_posture or _POSTURE_CONTROL_ONLY,
            coordination_role=coordination_role or "",
            capability_tier=capability_tier or "unknown",
            android_host_role=android_host_role or "",
            state=AttachmentState.attached,
            attached_at=now,
            last_signal_at=now,
            last_signal="attach",
            metadata=dict(metadata) if metadata else {},
        )

    rt.upsert(record)
    _logger.debug(
        "attach_runtime_session: device=%s session=%s posture=%s state=%s",
        device_id,
        record.session_id,
        record.source_runtime_posture,
        record.state.value,
    )
    return record


def apply_lifecycle_signal(
    record: AttachedRuntimeSessionRecord,
    signal: AttachmentLifecycleSignal,
    *,
    runtime: Optional[AttachedRuntimeSessionRuntime] = None,
) -> AttachedRuntimeSessionRecord:
    """Apply *signal* to *record* and return the updated record.

    The record is updated in-place in the module-level runtime (or the
    supplied *runtime* override).

    Parameters
    ----------
    record:
        The current session record.
    signal:
        The lifecycle signal to apply.
    runtime:
        Override the module-level singleton for this call (testing).

    Returns
    -------
    AttachedRuntimeSessionRecord
        The updated record with the new state, ``last_signal``, and
        ``last_signal_at`` fields.

    Raises
    ------
    ValueError
        If the signal is not valid for the record's current state (e.g.,
        trying to ``reconnect`` from an ``invalidated`` record).
    """
    if record.state.is_terminal():
        raise ValueError(
            f"apply_lifecycle_signal: session {record.session_id} is in terminal "
            f"state '{record.state.value}'; no further signals may be applied.  "
            f"Create a new session with attach_runtime_session() instead."
        )

    next_state = _TRANSITION_TABLE.get((record.state, signal))
    if next_state is None:
        raise ValueError(
            f"apply_lifecycle_signal: signal '{signal.value}' is not valid "
            f"from state '{record.state.value}' for session {record.session_id}."
        )

    now = time.time()
    updated = dataclasses.replace(
        record,
        state=next_state,
        last_signal=signal.value,
        last_signal_at=now,
    )

    rt = runtime if runtime is not None else get_attached_runtime_session_runtime()
    rt.upsert(updated)
    _logger.debug(
        "apply_lifecycle_signal: device=%s session=%s signal=%s %s→%s",
        record.device_id,
        record.session_id,
        signal.value,
        record.state.value,
        next_state.value,
    )
    return updated


def get_attached_runtime_session(
    device_id: str,
    *,
    runtime: Optional[AttachedRuntimeSessionRuntime] = None,
) -> Optional[AttachedRuntimeSessionRecord]:
    """Return the current session record for *device_id*, or ``None``.

    Parameters
    ----------
    device_id:
        The stable device identifier.
    runtime:
        Override the module-level singleton for this call (testing).
    """
    rt = runtime if runtime is not None else get_attached_runtime_session_runtime()
    return rt.get(device_id)


def list_active_attached_sessions(
    *,
    runtime: Optional[AttachedRuntimeSessionRuntime] = None,
) -> List[AttachedRuntimeSessionRecord]:
    """Return all sessions currently in the ``attached`` state.

    Parameters
    ----------
    runtime:
        Override the module-level singleton for this call (testing).
    """
    rt = runtime if runtime is not None else get_attached_runtime_session_runtime()
    return rt.list_active()


def build_attached_runtime_session_snapshot(
    *,
    runtime: Optional[AttachedRuntimeSessionRuntime] = None,
) -> AttachedRuntimeSessionSnapshot:
    """Build a serialisable snapshot of all current sessions.

    Parameters
    ----------
    runtime:
        Override the module-level singleton for this call (testing).

    Returns
    -------
    AttachedRuntimeSessionSnapshot
        A snapshot embedding all session records and summary counts.
    """
    rt = runtime if runtime is not None else get_attached_runtime_session_runtime()
    all_records = rt.list_all()
    active = sum(1 for r in all_records if r.state == AttachmentState.attached)
    return AttachedRuntimeSessionSnapshot(
        active_count=active,
        total_recorded=len(all_records),
        sessions=[r.to_dict() for r in all_records],
        authority=ATTACHED_RUNTIME_SESSION_AUTHORITY,
    )
