"""core/attached_runtime_session.py
====================================
PR package 7 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Canonical Attached-Runtime Session Semantics.

This module is the **canonical authority** for persistent attached-runtime
session semantics on the main-repo side.

Background
----------
Prior to PR-7, cross-device/remote runtime participation in the OpenClawd
runtime was modelled as a request-local or handshake-local relationship.
A remote device or Android host that sent a message or participated in a
session was considered "present" for that request and nothing more.  There
was no persistent notion of an *attached* runtime participant that remained
affiliated with the local host until explicitly detached, disconnected,
disabled, or invalidated.

PR-7 closes this gap on the main-repo side by establishing:

1. :class:`AttachmentState` — canonical lifecycle states for an attached
   runtime participant (attached, detaching, detached, disconnected, disabled,
   invalidated).
2. :class:`AttachmentLifecycleSignal` — canonical signals that drive
   state transitions (attach, detach, disconnect, disable, invalidate,
   reconnect).
3. :class:`AttachedRuntimeSessionRecord` — stable, serialisable record of one
   attached runtime participant's session state, including posture,
   coordination role, capability tier, and lifecycle metadata.
4. :class:`AttachedRuntimeSessionSnapshot` — immutable point-in-time snapshot
   of the full attached-runtime session table, suitable for projection and
   audit.
5. :class:`AttachedRuntimeSessionRuntime` — 128-entry ring-buffer singleton
   that persists attached session records across calls within a process.
6. :func:`attach_runtime_session` — idempotent attach operation.
7. :func:`apply_lifecycle_signal` — canonical state-machine driver.
8. :func:`get_attached_runtime_session` — point-in-time lookup.
9. :func:`list_active_attached_sessions` — enumerate all non-terminal sessions.
10. :func:`build_attached_runtime_session_snapshot` — snapshot the full table.
11. Ten policy sentinels documenting canonical attachment lifecycle rules.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Session-persistent** — once a device is attached it remains in the
  registry until an explicit lifecycle signal transitions it to a terminal
  state (detached / disconnected / disabled / invalidated).
- **Posture-preserving** — all ``source_runtime_posture`` semantics from
  PR-533 / PR-1 are honoured and propagated, not replaced.
- **Coordination-role aware** — integrates with the PR-538 / PR-6
  ``CoordinationRole`` model so session records carry the same roles used in
  dispatch and scheduling decisions.
- **Capability-tier aware** — carries the ``CapabilityTier`` established by
  PR-6 to let later layers skip re-computation.
- **Graceful degradation** — missing or unknown fields default to safe
  conservative outcomes.
- **Fully serialisable** — all dataclasses expose ``to_dict()`` / ``to_json()``
  for stable, round-trippable wire representations.

Relationship to other PR packages
----------------------------------
* PR-1  (``core.posture_contract_canonicalization``) — posture values consumed
  here are canonicalised by PR-1's contract layer.
* PR-2  (``core.source_execution_eligibility``) — per-posture eligibility
  checks remain the dispatch-time gate; this module models session persistence.
* PR-4  (``core.canonical_session_truth``) — session truth records may embed
  attached-session snapshots for audit.
* PR-5  (``core.android_runtime_host``) — Android host role is one of the
  capability signals carried in session records.
* PR-6  (``core.canonical_capability_scheduling_basis``) — ``CapabilityTier``
  from PR-6 is carried in each session record to avoid repeated derivation.

Public API
----------
Sentinels::

    ATTACHED_RUNTIME_SESSION_AUTHORITY
    ATTACHED_RUNTIME_SESSION_PERSISTS_UNTIL_EXPLICIT_SIGNAL_POLICY
    TRANSIENT_PRESENCE_IS_NOT_ATTACHED_SESSION_POLICY
    ATTACH_SIGNAL_IS_IDEMPOTENT_POLICY
    DETACH_CLOSES_SESSION_GRACEFULLY_POLICY
    DISCONNECT_MARKS_SESSION_DISCONNECTED_POLICY
    DISABLE_PREVENTS_REATTACH_POLICY
    INVALIDATE_TERMINATES_SESSION_PERMANENTLY_POLICY
    RECONNECT_RESTORES_ATTACHED_STATE_POLICY
    OBSERVER_ONLY_SESSION_CANNOT_BE_PROMOTED_POLICY
    ATTACHED_RUNTIME_SESSION_ALIGNED_PR7

Enums::

    AttachmentState
    AttachmentLifecycleSignal

Dataclasses::

    AttachedRuntimeSessionRecord
    AttachedRuntimeSessionSnapshot

Class::

    AttachedRuntimeSessionRuntime

Functions::

    attach_runtime_session(device_id, ...) -> AttachedRuntimeSessionRecord
    apply_lifecycle_signal(device_id, signal, ...) -> AttachedRuntimeSessionRecord
    get_attached_runtime_session(device_id) -> Optional[AttachedRuntimeSessionRecord]
    list_active_attached_sessions() -> List[AttachedRuntimeSessionRecord]
    build_attached_runtime_session_snapshot() -> AttachedRuntimeSessionSnapshot
"""

from __future__ import annotations

import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Any, Deque, Dict, List, Optional, Tuple

__all__ = [
    # Sentinels
    "ATTACHED_RUNTIME_SESSION_AUTHORITY",
    "ATTACHED_RUNTIME_SESSION_PERSISTS_UNTIL_EXPLICIT_SIGNAL_POLICY",
    "TRANSIENT_PRESENCE_IS_NOT_ATTACHED_SESSION_POLICY",
    "ATTACH_SIGNAL_IS_IDEMPOTENT_POLICY",
    "DETACH_CLOSES_SESSION_GRACEFULLY_POLICY",
    "DISCONNECT_MARKS_SESSION_DISCONNECTED_POLICY",
    "DISABLE_PREVENTS_REATTACH_POLICY",
    "INVALIDATE_TERMINATES_SESSION_PERMANENTLY_POLICY",
    "RECONNECT_RESTORES_ATTACHED_STATE_POLICY",
    "OBSERVER_ONLY_SESSION_CANNOT_BE_PROMOTED_POLICY",
    "ATTACHED_RUNTIME_SESSION_ALIGNED_PR7",
    # Enums
    "AttachmentState",
    "AttachmentLifecycleSignal",
    # Dataclasses
    "AttachedRuntimeSessionRecord",
    "AttachedRuntimeSessionSnapshot",
    # Runtime
    "AttachedRuntimeSessionRuntime",
    # Functions
    "attach_runtime_session",
    "apply_lifecycle_signal",
    "get_attached_runtime_session",
    "list_active_attached_sessions",
    "build_attached_runtime_session_snapshot",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

ATTACHED_RUNTIME_SESSION_AUTHORITY: str = (
    "ATTACHED_RUNTIME_SESSION::AUTHORITY_V1: "
    "core.attached_runtime_session is the canonical authority for persistent "
    "attached-runtime session semantics on the main-repo side.  "
    "PR package 7, post-533 dual-repo runtime unification master plan."
)
"""Module authority sentinel."""

ATTACHED_RUNTIME_SESSION_PERSISTS_UNTIL_EXPLICIT_SIGNAL_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::PERSISTS_UNTIL_EXPLICIT_SIGNAL_V1: "
    "Once a remote device or Android host is attached, its session record "
    "persists in the AttachedRuntimeSessionRuntime until an explicit lifecycle "
    "signal (detach/disconnect/disable/invalidate) transitions it to a terminal "
    "state.  Mere absence of activity does not detach a session."
)
"""Policy: sessions are persistent, not request-local."""

TRANSIENT_PRESENCE_IS_NOT_ATTACHED_SESSION_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::TRANSIENT_PRESENCE_IS_NOT_ATTACHED_V1: "
    "A device that sends a message or participates in a single request without "
    "an explicit attach signal is considered transiently present, not an attached "
    "runtime participant.  Only an explicit attach() call creates a session record."
)
"""Policy: transient presence is distinct from an attached session."""

ATTACH_SIGNAL_IS_IDEMPOTENT_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::ATTACH_SIGNAL_IS_IDEMPOTENT_V1: "
    "Calling attach_runtime_session() for a device that already has an active "
    "(attached) session record returns the existing record without creating a "
    "duplicate.  Attachment metadata (posture, role, tier) is refreshed if "
    "newer values are supplied."
)
"""Policy: attach is idempotent for already-attached devices."""

DETACH_CLOSES_SESSION_GRACEFULLY_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::DETACH_CLOSES_SESSION_GRACEFULLY_V1: "
    "Applying AttachmentLifecycleSignal.detach transitions the session to "
    "AttachmentState.detaching and then immediately to AttachmentState.detached.  "
    "Detached sessions may be re-attached by a subsequent attach() call."
)
"""Policy: detach is a graceful, reversible terminal state."""

DISCONNECT_MARKS_SESSION_DISCONNECTED_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::DISCONNECT_MARKS_SESSION_DISCONNECTED_V1: "
    "Applying AttachmentLifecycleSignal.disconnect transitions the session to "
    "AttachmentState.disconnected, indicating the transport link was lost rather "
    "than an explicit participant decision.  Disconnected sessions may be "
    "restored by a reconnect signal."
)
"""Policy: disconnect represents involuntary transport loss."""

DISABLE_PREVENTS_REATTACH_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::DISABLE_PREVENTS_REATTACH_V1: "
    "Applying AttachmentLifecycleSignal.disable transitions the session to "
    "AttachmentState.disabled.  A disabled session cannot be restored by a "
    "reconnect signal; a new explicit attach() call is required."
)
"""Policy: disable is a stronger terminal state that blocks reconnect."""

INVALIDATE_TERMINATES_SESSION_PERMANENTLY_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::INVALIDATE_TERMINATES_SESSION_PERMANENTLY_V1: "
    "Applying AttachmentLifecycleSignal.invalidate transitions the session to "
    "AttachmentState.invalidated.  An invalidated session is permanently closed "
    "and cannot be restored without full re-registration of the device."
)
"""Policy: invalidation is the permanent terminal state."""

RECONNECT_RESTORES_ATTACHED_STATE_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::RECONNECT_RESTORES_ATTACHED_STATE_V1: "
    "Applying AttachmentLifecycleSignal.reconnect to a disconnected session "
    "restores it to AttachmentState.attached.  Reconnect has no effect on "
    "detached, disabled, or invalidated sessions."
)
"""Policy: reconnect is only valid from disconnected state."""

OBSERVER_ONLY_SESSION_CANNOT_BE_PROMOTED_POLICY: str = (
    "ATTACHED_RUNTIME_SESSION::OBSERVER_ONLY_SESSION_CANNOT_BE_PROMOTED_V1: "
    "A session whose coordination_role is 'observer_only' cannot be promoted "
    "to 'joined_runtime_participant' or 'source_controller' through lifecycle "
    "signals.  Role changes require a new attach() call with updated metadata."
)
"""Policy: observer_only role is not promotable via lifecycle signals."""

ATTACHED_RUNTIME_SESSION_ALIGNED_PR7: str = (
    "ATTACHED_RUNTIME_SESSION::ALIGNED_PR7_V1: "
    "core.attached_runtime_session is aligned with PR package 7 (post-533 "
    "dual-repo runtime unification master plan, MAIN repo side).  Attached-"
    "runtime session semantics are canonical and persistent."
)
"""PR-7 alignment sentinel."""

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

_TERMINAL_STATES_BLOCKING_RECONNECT = frozenset(
    ["detached", "disabled", "invalidated"]
)
_PERMANENTLY_TERMINAL_STATES = frozenset(["invalidated"])


class AttachmentState(str, Enum):
    """Canonical lifecycle states for an attached runtime session.

    States and valid transitions::

        (new) ──attach──▶ attached
        attached ──detach──▶ detaching ──▶ detached
        attached ──disconnect──▶ disconnected
        attached ──disable──▶ disabled
        attached ──invalidate──▶ invalidated
        detached ──attach──▶ attached          (re-attach allowed)
        disconnected ──reconnect──▶ attached   (reconnect allowed)
        disconnected ──disable──▶ disabled
        disconnected ──invalidate──▶ invalidated
        disabled ──invalidate──▶ invalidated
        invalidated  (permanent terminal – no further transitions)
    """

    attached = "attached"
    """Device is an active, confirmed attached runtime participant."""

    detaching = "detaching"
    """Transient intermediate: detach in progress."""

    detached = "detached"
    """Device explicitly detached; may be re-attached."""

    disconnected = "disconnected"
    """Transport link lost; device may reconnect."""

    disabled = "disabled"
    """Runtime host participation disabled; requires explicit re-attach."""

    invalidated = "invalidated"
    """Session permanently invalidated; full re-registration required."""

    @classmethod
    def from_string(cls, value: str) -> "AttachmentState":
        """Return the enum member matching *value*, or ``attached`` as default."""
        for member in cls:
            if member.value == value:
                return member
        return cls.attached

    def is_active(self) -> bool:
        """Return ``True`` if the session is in an active (non-terminal) state."""
        return self in (AttachmentState.attached, AttachmentState.detaching)

    def is_terminal(self) -> bool:
        """Return ``True`` if the session is in a terminal state."""
        return self in (
            AttachmentState.detached,
            AttachmentState.disconnected,
            AttachmentState.disabled,
            AttachmentState.invalidated,
        )

    def allows_reconnect(self) -> bool:
        """Return ``True`` if a reconnect signal may restore this session."""
        return self == AttachmentState.disconnected


class AttachmentLifecycleSignal(str, Enum):
    """Canonical signals that drive :class:`AttachmentState` transitions."""

    attach = "attach"
    """Establish or re-establish a runtime attachment."""

    detach = "detach"
    """Gracefully close the attachment."""

    disconnect = "disconnect"
    """Mark transport link as lost."""

    disable = "disable"
    """Administratively disable the runtime participant."""

    invalidate = "invalidate"
    """Permanently invalidate the session."""

    reconnect = "reconnect"
    """Restore a disconnected session to attached."""

    @classmethod
    def from_string(cls, value: str) -> "AttachmentLifecycleSignal":
        """Return the enum member matching *value*, or ``attach`` as default."""
        for member in cls:
            if member.value == value:
                return member
        return cls.attach


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AttachedRuntimeSessionRecord:
    """Mutable record for one attached runtime participant's session state.

    Attributes
    ----------
    device_id:
        Canonical identifier of the remote device or Android host.
    session_id:
        Auto-generated unique identifier for this attachment session.
    attachment_state:
        Current :class:`AttachmentState`.
    source_runtime_posture:
        Posture value (``'join_runtime'``, ``'control_only'``, etc.) from
        PR-533/PR-1.  Defaults to ``'control_only'``.
    coordination_role:
        Coordination role string from PR-538/PR-6.  Defaults to ``''``.
    capability_tier:
        Capability tier string from PR-6.  Defaults to ``'unknown'``.
    android_host_role:
        Android runtime host role string from PR-5.  Defaults to ``''``.
    attached_at:
        Unix timestamp when the session was first attached.
    last_signal_at:
        Unix timestamp of the most recent lifecycle signal.
    last_signal:
        Most recent :class:`AttachmentLifecycleSignal` applied.
    metadata:
        Arbitrary JSON-serialisable metadata supplied at attach time.
    """

    device_id: str
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    attachment_state: AttachmentState = AttachmentState.attached
    source_runtime_posture: str = "control_only"
    coordination_role: str = ""
    capability_tier: str = "unknown"
    android_host_role: str = ""
    attached_at: float = field(default_factory=time.time)
    last_signal_at: float = field(default_factory=time.time)
    last_signal: Optional[AttachmentLifecycleSignal] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "device_id": self.device_id,
            "session_id": self.session_id,
            "attachment_state": self.attachment_state.value,
            "source_runtime_posture": self.source_runtime_posture,
            "coordination_role": self.coordination_role,
            "capability_tier": self.capability_tier,
            "android_host_role": self.android_host_role,
            "attached_at": self.attached_at,
            "last_signal_at": self.last_signal_at,
            "last_signal": self.last_signal.value if self.last_signal else None,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AttachedRuntimeSessionRecord":
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        last_signal_raw = data.get("last_signal")
        last_signal = (
            AttachmentLifecycleSignal.from_string(last_signal_raw)
            if last_signal_raw
            else None
        )
        return cls(
            device_id=str(data.get("device_id", "")),
            session_id=str(data.get("session_id", str(uuid.uuid4()))),
            attachment_state=AttachmentState.from_string(
                str(data.get("attachment_state", "attached"))
            ),
            source_runtime_posture=str(
                data.get("source_runtime_posture", "control_only")
            ),
            coordination_role=str(data.get("coordination_role", "")),
            capability_tier=str(data.get("capability_tier", "unknown")),
            android_host_role=str(data.get("android_host_role", "")),
            attached_at=float(data.get("attached_at", time.time())),
            last_signal_at=float(data.get("last_signal_at", time.time())),
            last_signal=last_signal,
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class AttachedRuntimeSessionSnapshot:
    """Immutable point-in-time snapshot of the full attached-runtime session table.

    Attributes
    ----------
    snapshot_id:
        Auto-generated unique identifier for this snapshot.
    snapshot_at:
        Unix timestamp when the snapshot was taken.
    records:
        Ordered list of :class:`AttachedRuntimeSessionRecord` dicts
        (serialised for immutability).
    active_count:
        Number of records in an active (non-terminal) state.
    total_count:
        Total number of records captured.
    authority:
        Module authority sentinel.
    alignment_sentinel:
        PR-7 alignment sentinel.
    """

    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    snapshot_at: float = field(default_factory=time.time)
    records: List[Dict[str, Any]] = field(default_factory=list)
    active_count: int = 0
    total_count: int = 0
    authority: str = ATTACHED_RUNTIME_SESSION_AUTHORITY
    alignment_sentinel: str = ATTACHED_RUNTIME_SESSION_ALIGNED_PR7

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_at": self.snapshot_at,
            "records": self.records,
            "active_count": self.active_count,
            "total_count": self.total_count,
            "authority": self.authority,
            "alignment_sentinel": self.alignment_sentinel,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

def _apply_signal_to_state(
    current: AttachmentState,
    signal: AttachmentLifecycleSignal,
) -> AttachmentState:
    """Return the next :class:`AttachmentState` given *current* and *signal*.

    Unknown/no-op transitions return *current* unchanged.
    """
    if signal == AttachmentLifecycleSignal.attach:
        # attach is valid from detached; idempotent from attached;
        # not valid from disabled or invalidated (caller must handle that).
        if current in (
            AttachmentState.detached,
            AttachmentState.attached,
            AttachmentState.disconnected,
        ):
            return AttachmentState.attached
        return current

    if signal == AttachmentLifecycleSignal.detach:
        if current == AttachmentState.attached:
            # Model the two-step detaching → detached atomically.
            return AttachmentState.detached
        return current

    if signal == AttachmentLifecycleSignal.disconnect:
        if current in (AttachmentState.attached, AttachmentState.detaching):
            return AttachmentState.disconnected
        return current

    if signal == AttachmentLifecycleSignal.disable:
        if current != AttachmentState.invalidated:
            return AttachmentState.disabled
        return current

    if signal == AttachmentLifecycleSignal.invalidate:
        return AttachmentState.invalidated

    if signal == AttachmentLifecycleSignal.reconnect:
        if current == AttachmentState.disconnected:
            return AttachmentState.attached
        return current

    return current  # no-op for unknown signals


# ---------------------------------------------------------------------------
# Ring-buffer runtime
# ---------------------------------------------------------------------------

_RING_BUFFER_CAPACITY = 128


class AttachedRuntimeSessionRuntime:
    """128-entry ring-buffer registry of :class:`AttachedRuntimeSessionRecord`.

    Thread-safe.  Oldest records are evicted when capacity is exceeded.
    All mutating operations acquire the internal lock.

    The ring buffer is per-instance; the module-level singleton is
    ``_ATTACHED_RUNTIME_SESSION_RUNTIME`` (created at import time).
    """

    def __init__(self, capacity: int = _RING_BUFFER_CAPACITY) -> None:
        self._capacity = capacity
        self._lock = Lock()
        # Map from device_id → record for O(1) lookup.
        self._index: Dict[str, AttachedRuntimeSessionRecord] = {}
        # Ring buffer of (device_id, session_id) tuples for eviction order.
        self._ring: Deque[Tuple[str, str]] = deque(maxlen=capacity)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_if_full(self) -> None:
        """Remove the oldest entry if the ring is at capacity.

        Called with self._lock held.
        """
        while len(self._ring) >= self._capacity:
            oldest_device_id, oldest_session_id = self._ring.popleft()
            # Only evict from the index if the stored session_id still matches
            # (a newer re-attach would have replaced it).
            current = self._index.get(oldest_device_id)
            if current is not None and current.session_id == oldest_session_id:
                del self._index[oldest_device_id]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def attach(
        self,
        device_id: str,
        *,
        source_runtime_posture: str = "control_only",
        coordination_role: str = "",
        capability_tier: str = "unknown",
        android_host_role: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AttachedRuntimeSessionRecord:
        """Attach (or re-attach) *device_id*.

        If an active session already exists for *device_id*, the session
        metadata is refreshed and the existing record is returned
        (ATTACH_SIGNAL_IS_IDEMPOTENT_POLICY).

        If a terminal session exists for *device_id* (detached / disabled /
        invalidated — except ``invalidated``, which blocks re-attach), a new
        session record is created.

        Returns the canonical :class:`AttachedRuntimeSessionRecord`.
        """
        with self._lock:
            existing = self._index.get(device_id)
            if existing is not None:
                if existing.attachment_state == AttachmentState.invalidated:
                    # Cannot re-attach an invalidated session.
                    return existing
                if existing.attachment_state == AttachmentState.attached:
                    # Idempotent: refresh metadata only.
                    existing.source_runtime_posture = source_runtime_posture
                    existing.coordination_role = coordination_role
                    existing.capability_tier = capability_tier
                    existing.android_host_role = android_host_role
                    if metadata:
                        existing.metadata.update(metadata)
                    existing.last_signal = AttachmentLifecycleSignal.attach
                    existing.last_signal_at = time.time()
                    return existing
                # Terminal or disconnected: create a new session.

            now = time.time()
            record = AttachedRuntimeSessionRecord(
                device_id=device_id,
                attachment_state=AttachmentState.attached,
                source_runtime_posture=source_runtime_posture,
                coordination_role=coordination_role,
                capability_tier=capability_tier,
                android_host_role=android_host_role,
                attached_at=now,
                last_signal_at=now,
                last_signal=AttachmentLifecycleSignal.attach,
                metadata=dict(metadata or {}),
            )
            self._evict_if_full()
            self._index[device_id] = record
            self._ring.append((device_id, record.session_id))
            return record

    def apply_signal(
        self,
        device_id: str,
        signal: AttachmentLifecycleSignal,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[AttachedRuntimeSessionRecord]:
        """Apply *signal* to the session for *device_id*.

        Returns the updated record, or ``None`` if no session is found.
        """
        with self._lock:
            record = self._index.get(device_id)
            if record is None:
                return None
            new_state = _apply_signal_to_state(record.attachment_state, signal)
            record.attachment_state = new_state
            record.last_signal = signal
            record.last_signal_at = time.time()
            if metadata:
                record.metadata.update(metadata)
            return record

    def get(self, device_id: str) -> Optional[AttachedRuntimeSessionRecord]:
        """Return the session record for *device_id*, or ``None``."""
        with self._lock:
            return self._index.get(device_id)

    def list_active(self) -> List[AttachedRuntimeSessionRecord]:
        """Return a list of all records in a non-terminal state."""
        with self._lock:
            return [
                r
                for r in self._index.values()
                if r.attachment_state.is_active()
            ]

    def list_all(self) -> List[AttachedRuntimeSessionRecord]:
        """Return a list of all records regardless of state."""
        with self._lock:
            return list(self._index.values())

    def reset(self) -> None:
        """Clear all records.  Intended for testing only."""
        with self._lock:
            self._index.clear()
            self._ring.clear()

    @property
    def capacity(self) -> int:
        """Maximum number of records the buffer holds."""
        return self._capacity


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_ATTACHED_RUNTIME_SESSION_RUNTIME: AttachedRuntimeSessionRuntime = (
    AttachedRuntimeSessionRuntime()
)


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def attach_runtime_session(
    device_id: str,
    *,
    source_runtime_posture: str = "control_only",
    coordination_role: str = "",
    capability_tier: str = "unknown",
    android_host_role: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    runtime: Optional[AttachedRuntimeSessionRuntime] = None,
) -> AttachedRuntimeSessionRecord:
    """Idempotently attach *device_id* as a persistent runtime participant.

    Parameters
    ----------
    device_id:
        Canonical identifier of the remote device or Android host.
    source_runtime_posture:
        Posture value from PR-533/PR-1 (default ``'control_only'``).
    coordination_role:
        Coordination role string from PR-538/PR-6 (default ``''``).
    capability_tier:
        Capability tier string from PR-6 (default ``'unknown'``).
    android_host_role:
        Android runtime host role from PR-5 (default ``''``).
    metadata:
        Optional dict of arbitrary JSON-serialisable metadata.
    runtime:
        Optional :class:`AttachedRuntimeSessionRuntime` to use instead of
        the module-level singleton (useful in tests).

    Returns
    -------
    AttachedRuntimeSessionRecord
        The canonical session record for *device_id*.
    """
    rt = runtime if runtime is not None else _ATTACHED_RUNTIME_SESSION_RUNTIME
    return rt.attach(
        device_id,
        source_runtime_posture=source_runtime_posture,
        coordination_role=coordination_role,
        capability_tier=capability_tier,
        android_host_role=android_host_role,
        metadata=metadata,
    )


def apply_lifecycle_signal(
    device_id: str,
    signal: AttachmentLifecycleSignal,
    *,
    metadata: Optional[Dict[str, Any]] = None,
    runtime: Optional[AttachedRuntimeSessionRuntime] = None,
) -> Optional[AttachedRuntimeSessionRecord]:
    """Apply *signal* to the session for *device_id*.

    Parameters
    ----------
    device_id:
        Canonical identifier of the remote device or Android host.
    signal:
        The :class:`AttachmentLifecycleSignal` to apply.
    metadata:
        Optional dict of arbitrary JSON-serialisable metadata to merge into
        the record.
    runtime:
        Optional :class:`AttachedRuntimeSessionRuntime` to use instead of
        the module-level singleton.

    Returns
    -------
    AttachedRuntimeSessionRecord | None
        The updated record, or ``None`` if no session was found for
        *device_id*.
    """
    rt = runtime if runtime is not None else _ATTACHED_RUNTIME_SESSION_RUNTIME
    return rt.apply_signal(device_id, signal, metadata=metadata)


def get_attached_runtime_session(
    device_id: str,
    *,
    runtime: Optional[AttachedRuntimeSessionRuntime] = None,
) -> Optional[AttachedRuntimeSessionRecord]:
    """Return the session record for *device_id*, or ``None``.

    Parameters
    ----------
    device_id:
        Canonical identifier of the remote device or Android host.
    runtime:
        Optional :class:`AttachedRuntimeSessionRuntime` to use instead of
        the module-level singleton.
    """
    rt = runtime if runtime is not None else _ATTACHED_RUNTIME_SESSION_RUNTIME
    return rt.get(device_id)


def list_active_attached_sessions(
    *,
    runtime: Optional[AttachedRuntimeSessionRuntime] = None,
) -> List[AttachedRuntimeSessionRecord]:
    """Return all non-terminal attached runtime session records.

    Parameters
    ----------
    runtime:
        Optional :class:`AttachedRuntimeSessionRuntime` to use instead of
        the module-level singleton.
    """
    rt = runtime if runtime is not None else _ATTACHED_RUNTIME_SESSION_RUNTIME
    return rt.list_active()


def build_attached_runtime_session_snapshot(
    *,
    runtime: Optional[AttachedRuntimeSessionRuntime] = None,
) -> AttachedRuntimeSessionSnapshot:
    """Build a point-in-time snapshot of the full attached-runtime session table.

    Parameters
    ----------
    runtime:
        Optional :class:`AttachedRuntimeSessionRuntime` to use instead of
        the module-level singleton.
    """
    rt = runtime if runtime is not None else _ATTACHED_RUNTIME_SESSION_RUNTIME
    all_records = rt.list_all()
    active_count = sum(1 for r in all_records if r.attachment_state.is_active())
    return AttachedRuntimeSessionSnapshot(
        records=[r.to_dict() for r in all_records],
        active_count=active_count,
        total_count=len(all_records),
    )
