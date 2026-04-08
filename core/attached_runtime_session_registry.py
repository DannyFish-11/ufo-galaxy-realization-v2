"""core/attached_runtime_session_registry.py
=============================================
PR package 19 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Authoritative Attached Runtime Session Registry.

This module is the **canonical authority** for the single-source-of-truth
registry that tracks which attached runtime sessions are currently active,
which have been replaced by a newer session for the same device, and which
have been invalidated.  It provides the authoritative lookup surface that
``dispatch``, ``reuse``, and ``reconciliation`` layers MUST consult to resolve
session identity instead of independently caching partial session information.

Background
----------
Prior to PR-19 each layer (dispatch binding, reuse binding, signal ingress,
signal reconciliation) maintained its own partial view of session identity.
This meant no single authority could answer:

- Which session is currently *active* for a given device?
- Has a session been superseded by a newer reattach?
- When should old session entries be invalidated after a reconnect?
- Which session identity should dispatch / reuse / reconciliation use?

PR-19 closes this gap by introducing the
:class:`AttachedRuntimeSessionRegistry` as the canonical single truth source.
All state transitions (register, reconnect, reattach, detach, invalidate,
replace) flow through this registry.  Downstream layers call
:func:`lookup_active_session` or :func:`lookup_session_by_device` to resolve
a session identity before acting.

Design
------
1. **Single truth source** — one registry, one ring buffer (128 entries),
   one module-level singleton.  All callers share the same view.
2. **Device-keyed active pointer** — each device_id maps to exactly one
   *active* session at a time.  A ``register`` or ``reattach`` that creates a
   new session for an already-active device automatically moves the old session
   to ``replaced`` state.
3. **runtime_session_id** — a new stable opaque identifier that is generated
   by the registry at registration time.  It is distinct from the external
   ``session_id`` supplied by callers and survives reconnect without changing.
4. **Authoritative state machine** — entry state transitions are governed by
   :data:`_REGISTRY_TRANSITIONS`.  Illegal transitions are silently no-ops
   that return the original entry unchanged.
5. **Invalidation reason** — every non-active terminal state carries an
   :class:`InvalidationReason` that records *why* the entry left active state.
6. **Fully serialisable** — all dataclasses expose ``to_dict()`` / ``to_json()``
   for stable wire representations.

Public API
----------
Sentinels::

    ATTACHED_RUNTIME_SESSION_REGISTRY_AUTHORITY
    REGISTRY_IS_SINGLE_TRUTH_SOURCE_POLICY
    REGISTRY_DEVICE_HAS_AT_MOST_ONE_ACTIVE_SESSION_POLICY
    REGISTRY_REGISTER_REPLACES_OLD_SESSION_POLICY
    REGISTRY_RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY
    REGISTRY_DETACH_REQUIRES_EXPLICIT_SIGNAL_POLICY
    REGISTRY_INVALIDATED_ENTRY_IS_TERMINAL_POLICY
    REGISTRY_DISPATCH_MUST_CONSULT_REGISTRY_POLICY
    REGISTRY_REUSE_MUST_CONSULT_REGISTRY_POLICY
    REGISTRY_RECONCILIATION_MUST_CONSULT_REGISTRY_POLICY
    REGISTRY_LOOKUP_RETURNS_ACTIVE_ONLY_BY_DEFAULT_POLICY
    ATTACHED_RUNTIME_SESSION_REGISTRY_PR19_SENTINEL

Enums::

    RegistryEntryState
    RegistryTransition
    InvalidationReason

Dataclasses::

    AttachedSessionRegistryEntry
    AttachedSessionRegistrySnapshot

Classes::

    AttachedSessionRegistry

Functions::

    register_session(...) -> AttachedSessionRegistryEntry
    reconnect_session(entry, ...) -> AttachedSessionRegistryEntry
    reattach_session(entry, ...) -> AttachedSessionRegistryEntry
    detach_session(entry, ...) -> AttachedSessionRegistryEntry
    invalidate_session(entry, reason, ...) -> AttachedSessionRegistryEntry
    lookup_active_session(session_id, ...) -> AttachedSessionRegistryEntry | None
    lookup_session_by_device(device_id, ...) -> AttachedSessionRegistryEntry | None
    list_active_sessions(...) -> list[AttachedSessionRegistryEntry]
    build_registry_snapshot(...) -> AttachedSessionRegistrySnapshot
    get_session_registry() -> AttachedSessionRegistry
    reset_session_registry() -> None
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

ATTACHED_RUNTIME_SESSION_REGISTRY_AUTHORITY: str = (
    "ATTACHED_RUNTIME_SESSION_REGISTRY_AUTHORITY::core.attached_runtime_session_registry "
    "is the canonical authority for the single-source-of-truth registry of attached "
    "runtime sessions on the main-repo side (PR package 19, post-533 dual-repo runtime "
    "unification)."
)

REGISTRY_IS_SINGLE_TRUTH_SOURCE_POLICY: str = (
    "POLICY::REGISTRY_IS_SINGLE_TRUTH_SOURCE: the attached runtime session registry is "
    "the sole authoritative source of truth for active session identity.  No other layer "
    "may cache or independently maintain session active/inactive status."
)

REGISTRY_DEVICE_HAS_AT_MOST_ONE_ACTIVE_SESSION_POLICY: str = (
    "POLICY::REGISTRY_DEVICE_HAS_AT_MOST_ONE_ACTIVE_SESSION: at any point in time a "
    "given device_id maps to at most one entry in the 'active' state.  If a new session "
    "is registered for a device that already has an active session the old session MUST "
    "be moved to 'replaced' state before the new session is recorded."
)

REGISTRY_REGISTER_REPLACES_OLD_SESSION_POLICY: str = (
    "POLICY::REGISTRY_REGISTER_REPLACES_OLD_SESSION: calling register_session() for a "
    "device that already has an active session automatically transitions the existing "
    "entry to 'replaced' state with invalidation_reason='replaced', making the new "
    "entry the sole active session for that device."
)

REGISTRY_RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY: str = (
    "POLICY::REGISTRY_RECONNECT_PRESERVES_RUNTIME_SESSION_ID: a reconnect transition "
    "restores the entry to 'active' state without changing its runtime_session_id.  "
    "The stable opaque runtime_session_id persists across reconnects so that upstream "
    "tracking (execution tracker, reuse binding) can identify the same logical session."
)

REGISTRY_DETACH_REQUIRES_EXPLICIT_SIGNAL_POLICY: str = (
    "POLICY::REGISTRY_DETACH_REQUIRES_EXPLICIT_SIGNAL: an entry can only move to "
    "'detached' state through an explicit detach_session() call.  Absence of heartbeat "
    "or activity alone does not detach a session."
)

REGISTRY_INVALIDATED_ENTRY_IS_TERMINAL_POLICY: str = (
    "POLICY::REGISTRY_INVALIDATED_ENTRY_IS_TERMINAL: once an entry reaches 'invalidated' "
    "state it cannot be recovered.  A new register_session() call is required to "
    "re-establish the session, and the old entry's runtime_session_id is retired."
)

REGISTRY_DISPATCH_MUST_CONSULT_REGISTRY_POLICY: str = (
    "POLICY::REGISTRY_DISPATCH_MUST_CONSULT_REGISTRY: all delegated dispatch paths MUST "
    "call lookup_active_session() or lookup_session_by_device() before forming a dispatch "
    "identity to ensure they are acting on the current authoritative session."
)

REGISTRY_REUSE_MUST_CONSULT_REGISTRY_POLICY: str = (
    "POLICY::REGISTRY_REUSE_MUST_CONSULT_REGISTRY: reuse-binding resolution MUST "
    "cross-check the registry to verify that the reuse binding's session_id still "
    "refers to an active registry entry before returning an eligible surface."
)

REGISTRY_RECONCILIATION_MUST_CONSULT_REGISTRY_POLICY: str = (
    "POLICY::REGISTRY_RECONCILIATION_MUST_CONSULT_REGISTRY: signal reconciliation MUST "
    "verify via the registry that the session referenced in an inbound signal envelope "
    "is still active before applying the signal to the host-side tracker."
)

REGISTRY_LOOKUP_RETURNS_ACTIVE_ONLY_BY_DEFAULT_POLICY: str = (
    "POLICY::REGISTRY_LOOKUP_RETURNS_ACTIVE_ONLY_BY_DEFAULT: lookup_active_session() "
    "and lookup_session_by_device() return None for sessions in 'replaced', 'detached', "
    "or 'invalidated' state unless the caller explicitly passes active_only=False."
)

ATTACHED_RUNTIME_SESSION_REGISTRY_PR19_SENTINEL: str = (
    "ATTACHED_RUNTIME_SESSION_REGISTRY_PR19::canonical-authoritative-attached-runtime-"
    "session-registry::package=19::post-533-dual-repo-runtime-unification"
)

# ---------------------------------------------------------------------------
# PR-22 consolidation sentinels
# ---------------------------------------------------------------------------

ATTACHED_RUNTIME_REGISTRY_CONSOLIDATION_PR22_SENTINEL: str = (
    "ATTACHED_RUNTIME_SESSION_REGISTRY_PR22::authoritative-attached-runtime-registry-"
    "consolidation::package=22::post-533-dual-repo-runtime-unification::"
    "registry-is-single-authoritative-truth-for-dispatch-reuse-reconciliation"
)

REGISTRY_IS_AUTHORITATIVE_DISPATCH_GATE_PR22_POLICY: str = (
    "POLICY::REGISTRY_IS_AUTHORITATIVE_DISPATCH_GATE_PR22: "
    "The attached runtime session registry is the authoritative gate for all delegated "
    "dispatch decisions.  Before any delegated dispatch binding is created the registry "
    "MUST be consulted via lookup_active_session() or lookup_session_by_device().  A "
    "session known to the registry as non-active (replaced / detached / invalidated) "
    "MUST NOT be the target of new delegated dispatch."
)

REGISTRY_IS_AUTHORITATIVE_REUSE_GATE_PR22_POLICY: str = (
    "POLICY::REGISTRY_IS_AUTHORITATIVE_REUSE_GATE_PR22: "
    "The attached runtime session registry is the authoritative gate for reuse-binding "
    "resolution.  resolve_reuse_dispatch_surface() and dispatch_with_reuse_binding() "
    "MUST consult the registry before accepting a reuse binding as an eligible dispatch "
    "surface.  A reuse binding whose session_id maps to a non-active registry entry "
    "MUST be treated as rejected regardless of the reuse binding's own eligibility flag."
)

REGISTRY_IS_AUTHORITATIVE_RECONCILIATION_GATE_PR22_POLICY: str = (
    "POLICY::REGISTRY_IS_AUTHORITATIVE_RECONCILIATION_GATE_PR22: "
    "The attached runtime session registry is the authoritative gate for signal "
    "reconciliation.  reconcile_android_execution_signal() and "
    "ingest_delegated_execution_signal() MUST consult the registry before applying "
    "a signal to the host-side execution tracker.  A signal whose session_id maps to "
    "a non-active registry entry MUST NOT mutate the tracker."
)

REGISTRY_KNOWN_NON_ACTIVE_BLOCKS_EXECUTION_PR22_POLICY: str = (
    "POLICY::REGISTRY_KNOWN_NON_ACTIVE_BLOCKS_EXECUTION_PR22: "
    "When the registry contains an entry for a given session_id and that entry is in "
    "state 'replaced', 'detached', or 'invalidated', that session MUST NOT drive any "
    "new dispatch, reuse, or reconciliation action.  The registry's knowledge of "
    "non-active state is the definitive block signal; no side-channel truth may "
    "override this block."
)

REGISTRY_ABSENT_ENTRY_PASSES_THROUGH_PR22_POLICY: str = (
    "POLICY::REGISTRY_ABSENT_ENTRY_PASSES_THROUGH_PR22: "
    "When the registry has no entry for a given session_id the dispatch, reuse, and "
    "reconciliation gates MUST allow the operation to proceed.  Absence of a registry "
    "entry is not evidence of invalidity; it means the registry cannot assert non-active "
    "state and the downstream layer (reuse binding, execution tracker) determines the "
    "outcome using its own truth."
)

# ---------------------------------------------------------------------------
# PR-23 canonical takeover dispatch / delegated fallback authority sentinels
# ---------------------------------------------------------------------------

ATTACHED_RUNTIME_REGISTRY_TAKEOVER_DISPATCH_PR23_SENTINEL: str = (
    "ATTACHED_RUNTIME_SESSION_REGISTRY_PR23::canonical-takeover-dispatch-authority::"
    "package=23::post-533-dual-repo-runtime-unification::"
    "registry-is-single-authoritative-truth-for-takeover-vs-fallback-routing"
)

REGISTRY_IS_CANONICAL_TAKEOVER_DISPATCH_AUTHORITY_PR23_POLICY: str = (
    "POLICY::REGISTRY_IS_CANONICAL_TAKEOVER_DISPATCH_AUTHORITY_PR23: "
    "The attached runtime session registry is the single canonical authority for the "
    "takeover dispatch routing decision.  resolve_takeover_or_fallback_route() MUST "
    "consult this registry as the first and only session-state truth before determining "
    "whether the attached runtime takes over or the delegated fallback path is used.  "
    "No other session-state source may substitute for or override the registry."
)

REGISTRY_TAKEOVER_ELIGIBILITY_REQUIRES_ACTIVE_STATE_PR23_POLICY: str = (
    "POLICY::REGISTRY_TAKEOVER_ELIGIBILITY_REQUIRES_ACTIVE_STATE_PR23: "
    "Only a session in 'active' state in the registry is eligible to win the takeover "
    "dispatch decision.  Sessions in 'replaced', 'detached', or 'invalidated' state "
    "MUST NOT be selected as the takeover target; they MUST produce "
    "TakeoverRouteOutcome.delegated_fallback unconditionally."
)

REGISTRY_REPLACED_SESSION_IS_INELIGIBLE_FOR_TAKEOVER_PR23_POLICY: str = (
    "POLICY::REGISTRY_REPLACED_SESSION_IS_INELIGIBLE_FOR_TAKEOVER_PR23: "
    "When a new session is registered for the same device the old session moves to "
    "'replaced' state and is permanently ineligible for takeover dispatch.  The "
    "registry gate MUST block the replaced session before any reuse-binding "
    "evaluation occurs, ensuring the stale entry can never win takeover selection."
)

# ---------------------------------------------------------------------------
# PR-33: Reconnect and Recovery Consistency sentinels
# ---------------------------------------------------------------------------

REGISTRY_RECONNECT_CONSISTENCY_PR33_SENTINEL: str = (
    "ATTACHED_RUNTIME_SESSION_REGISTRY_PR33::reconnect-recovery-consistency-hardening::"
    "package=33::post-533-dual-repo-runtime-unification::"
    "reconnect-count-and-last-reconnect-at-tracked-per-entry"
)

REGISTRY_RECONNECT_COUNT_IS_MONOTONIC_PR33_POLICY: str = (
    "POLICY::REGISTRY_RECONNECT_COUNT_IS_MONOTONIC_PR33: "
    "The reconnect_count field on AttachedSessionRegistryEntry MUST be incremented "
    "by exactly 1 each time a RegistryTransition.reconnect is applied to the entry.  "
    "It must never decrease.  This counter is the host-side observable evidence that "
    "a session has recovered from one or more disconnects without creating a new "
    "registration."
)

REGISTRY_LAST_RECONNECT_AT_TRACKS_MOST_RECENT_RECONNECT_PR33_POLICY: str = (
    "POLICY::REGISTRY_LAST_RECONNECT_AT_TRACKS_MOST_RECENT_RECONNECT_PR33: "
    "last_reconnect_at MUST be set to the transition timestamp every time "
    "RegistryTransition.reconnect is applied.  It is None when the entry has "
    "never been reconnected (i.e. has been registered but not yet detached and "
    "reconnected).  Callers MAY use this field to detect stale reconnect states "
    "or to surface recovery latency to operators."
)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_RING_BUFFER_CAPACITY: int = 128
_POSTURE_JOIN_RUNTIME: str = "join_runtime"
_POSTURE_CONTROL_ONLY: str = "control_only"


# ---------------------------------------------------------------------------
# RegistryEntryState
# ---------------------------------------------------------------------------


class RegistryEntryState(str, Enum):
    """Lifecycle state of a single entry in the attached runtime session registry.

    Values
    ------
    active
        The session is currently attached and eligible for dispatch/reuse/
        reconciliation lookup.
    replaced
        The session has been superseded by a newer session for the same device.
        This is a terminal state; the entry is retained for audit but is not
        returned by default lookups.
    detached
        The session was explicitly detached.  This is a non-terminal state
        that can recover to ``active`` via a reconnect/reattach transition.
    invalidated
        The session was explicitly invalidated.  This is a terminal state;
        a new register_session() is required to re-establish the session.
    """

    active = "active"
    replaced = "replaced"
    detached = "detached"
    invalidated = "invalidated"

    @classmethod
    def from_string(
        cls,
        value: str,
        default: "RegistryEntryState" = None,
    ) -> "RegistryEntryState":
        """Parse *value* into a :class:`RegistryEntryState`, returning *default* on failure."""
        try:
            return cls(value.lower().strip())
        except (ValueError, AttributeError):
            if default is not None:
                return default
            return cls.active

    def is_active(self) -> bool:
        """Return True if this is the ``active`` state."""
        return self == RegistryEntryState.active

    def is_terminal(self) -> bool:
        """Return True if this state cannot recover without a new registration."""
        return self in (RegistryEntryState.replaced, RegistryEntryState.invalidated)

    def is_recoverable(self) -> bool:
        """Return True if this state can transition back to ``active``."""
        return self == RegistryEntryState.detached


# ---------------------------------------------------------------------------
# RegistryTransition
# ---------------------------------------------------------------------------


class RegistryTransition(str, Enum):
    """Signals that drive state transitions in the registry.

    Values
    ------
    register
        Initial registration of a new session for a device.
    reconnect
        The device reconnected after a transient disconnect.  Restores
        ``active`` state without changing ``runtime_session_id``.
    reattach
        The caller explicitly re-attaches an existing session (e.g. after
        a deliberate detach).  Restores ``active`` state.
    detach
        Explicit detach by the orchestration layer.  Moves to ``detached``.
    invalidate
        Explicit invalidation.  Moves to ``invalidated`` (terminal).
    replace
        Internal signal used when a new register_session() supersedes an
        existing active session.  Moves the old entry to ``replaced``.
    """

    register = "register"
    reconnect = "reconnect"
    reattach = "reattach"
    detach = "detach"
    invalidate = "invalidate"
    replace = "replace"

    @classmethod
    def from_string(
        cls,
        value: str,
        default: "RegistryTransition" = None,
    ) -> "RegistryTransition":
        """Parse *value* into a :class:`RegistryTransition`, returning *default* on failure."""
        try:
            return cls(value.lower().strip())
        except (ValueError, AttributeError):
            if default is not None:
                return default
            return cls.register


# ---------------------------------------------------------------------------
# InvalidationReason
# ---------------------------------------------------------------------------


class InvalidationReason(str, Enum):
    """Reason why an entry left ``active`` state.

    Values
    ------
    none
        No invalidation; the entry is currently active.
    replaced
        A new session registration for the same device superseded this entry.
    detached
        An explicit detach signal was received.
    disconnected
        The device disconnected (recoverable; sub-reason of detached state).
    disabled
        The session was administratively disabled.
    invalidated
        An explicit invalidation signal was received (terminal).
    bad_posture
        The session was invalidated because the device posture changed to a
        non-join-runtime posture.
    missing_session
        The session could not be resolved from the supplied session_id.
    missing_device
        The session could not be resolved from the supplied device_id.
    """

    none = "none"
    replaced = "replaced"
    detached = "detached"
    disconnected = "disconnected"
    disabled = "disabled"
    invalidated = "invalidated"
    bad_posture = "bad_posture"
    missing_session = "missing_session"
    missing_device = "missing_device"

    @classmethod
    def from_string(
        cls,
        value: str,
        default: "InvalidationReason" = None,
    ) -> "InvalidationReason":
        """Parse *value* into an :class:`InvalidationReason`, returning *default* on failure."""
        try:
            return cls(value.lower().strip())
        except (ValueError, AttributeError):
            if default is not None:
                return default
            return cls.none


# ---------------------------------------------------------------------------
# State transition table
# ---------------------------------------------------------------------------

_REGISTRY_TRANSITIONS: Dict[
    tuple[RegistryEntryState, RegistryTransition], RegistryEntryState
] = {
    # From active
    (RegistryEntryState.active, RegistryTransition.register): RegistryEntryState.active,
    (RegistryEntryState.active, RegistryTransition.reconnect): RegistryEntryState.active,
    (RegistryEntryState.active, RegistryTransition.reattach): RegistryEntryState.active,
    (RegistryEntryState.active, RegistryTransition.detach): RegistryEntryState.detached,
    (RegistryEntryState.active, RegistryTransition.invalidate): RegistryEntryState.invalidated,
    (RegistryEntryState.active, RegistryTransition.replace): RegistryEntryState.replaced,
    # From detached (recoverable)
    (RegistryEntryState.detached, RegistryTransition.reconnect): RegistryEntryState.active,
    (RegistryEntryState.detached, RegistryTransition.reattach): RegistryEntryState.active,
    (RegistryEntryState.detached, RegistryTransition.detach): RegistryEntryState.detached,
    (RegistryEntryState.detached, RegistryTransition.invalidate): RegistryEntryState.invalidated,
    (RegistryEntryState.detached, RegistryTransition.replace): RegistryEntryState.replaced,
    # Terminal states — no further transitions
}


def _resolve_transition(
    current_state: RegistryEntryState,
    transition: RegistryTransition,
) -> Optional[RegistryEntryState]:
    """Return the next state for *current_state* + *transition*, or None if illegal."""
    return _REGISTRY_TRANSITIONS.get((current_state, transition))


# ---------------------------------------------------------------------------
# AttachedSessionRegistryEntry
# ---------------------------------------------------------------------------


@dataclass
class AttachedSessionRegistryEntry:
    """A single entry in the :class:`AttachedSessionRegistry`.

    This is the canonical representation of one attached runtime session's
    registry record.  It carries the **unified** set of identity fields that
    dispatch, reuse, and reconciliation layers MUST use.

    Attributes
    ----------
    entry_id
        Unique, stable identifier for this registry entry instance.  Auto-generated.
    session_id
        External session identifier supplied by the caller (e.g. galaxy session id).
    device_id
        Identifier of the attached remote/Android device or runtime host.
    runtime_session_id
        Opaque stable identifier generated by the registry at registration time.
        Persists across reconnect transitions; changes only on new registration.
    attachment_state
        Current lifecycle state of this registry entry.
    invalidation_reason
        Reason why this entry left active state (``none`` while active).
    posture
        Source device participation posture (e.g. 'join_runtime', 'control_only').
    host_role
        AndroidRuntimeHostRole string from PR-5 (informational).
    coordination_role
        Coordination role derived from posture + formation context.
    capability_tier
        CapabilityTier string from PR package 6 (informational).
    last_transition
        The most recent :class:`RegistryTransition` applied.
    previous_state
        Entry state before the last transition.
    registered_at
        Unix epoch seconds when this entry was first registered.
    last_transition_at
        Unix epoch seconds when the last state transition occurred.
    metadata
        Arbitrary caller-supplied metadata dict.
    """

    device_id: str
    session_id: str = ""
    runtime_session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    attachment_state: RegistryEntryState = RegistryEntryState.active
    invalidation_reason: InvalidationReason = InvalidationReason.none
    posture: str = _POSTURE_JOIN_RUNTIME
    host_role: str = ""
    coordination_role: str = ""
    capability_tier: str = ""
    last_transition: Optional[RegistryTransition] = None
    previous_state: Optional[RegistryEntryState] = None
    registered_at: float = field(default_factory=time.time)
    last_transition_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    reconnect_count: int = 0
    last_reconnect_at: Optional[float] = None

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def is_active(self) -> bool:
        """Return True if this entry is currently active."""
        return self.attachment_state == RegistryEntryState.active

    def is_terminal(self) -> bool:
        """Return True if this entry is in a terminal (non-recoverable) state."""
        return self.attachment_state.is_terminal()

    def is_recoverable(self) -> bool:
        """Return True if this entry can transition back to active."""
        return self.attachment_state.is_recoverable()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "entry_id": self.entry_id,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "runtime_session_id": self.runtime_session_id,
            "attachment_state": self.attachment_state.value,
            "invalidation_reason": self.invalidation_reason.value,
            "posture": self.posture,
            "host_role": self.host_role,
            "coordination_role": self.coordination_role,
            "capability_tier": self.capability_tier,
            "last_transition": self.last_transition.value if self.last_transition else None,
            "previous_state": self.previous_state.value if self.previous_state else None,
            "registered_at": self.registered_at,
            "last_transition_at": self.last_transition_at,
            "metadata": self.metadata,
            "reconnect_count": self.reconnect_count,
            "last_reconnect_at": self.last_reconnect_at,
        }

    def to_json(self) -> str:
        """Return a compact JSON string representation."""
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AttachedSessionRegistryEntry":
        """Reconstruct an entry from a dict produced by :meth:`to_dict`."""
        if not isinstance(data, dict):
            raise ValueError("AttachedSessionRegistryEntry.from_dict: expected dict")

        raw_state = data.get("attachment_state", RegistryEntryState.active.value)
        raw_reason = data.get("invalidation_reason", InvalidationReason.none.value)
        raw_transition = data.get("last_transition")
        raw_prev = data.get("previous_state")

        state = RegistryEntryState.from_string(str(raw_state))
        reason = InvalidationReason.from_string(str(raw_reason))
        transition = (
            RegistryTransition.from_string(str(raw_transition))
            if raw_transition
            else None
        )
        prev = RegistryEntryState.from_string(str(raw_prev)) if raw_prev else None

        return cls(
            entry_id=data.get("entry_id", str(uuid.uuid4())),
            session_id=data.get("session_id", ""),
            device_id=data.get("device_id", ""),
            runtime_session_id=data.get("runtime_session_id", str(uuid.uuid4())),
            attachment_state=state,
            invalidation_reason=reason,
            posture=data.get("posture", _POSTURE_JOIN_RUNTIME),
            host_role=data.get("host_role", ""),
            coordination_role=data.get("coordination_role", ""),
            capability_tier=data.get("capability_tier", ""),
            last_transition=transition,
            previous_state=prev,
            registered_at=float(data.get("registered_at", time.time())),
            last_transition_at=float(data.get("last_transition_at", time.time())),
            metadata=data.get("metadata", {}),
            reconnect_count=int(data.get("reconnect_count", 0)),
            last_reconnect_at=float(val) if (val := data.get("last_reconnect_at")) is not None else None,
        )


# ---------------------------------------------------------------------------
# AttachedSessionRegistrySnapshot
# ---------------------------------------------------------------------------


@dataclass
class AttachedSessionRegistrySnapshot:
    """Point-in-time snapshot of all entries in the attached runtime session registry.

    Attributes
    ----------
    snapshot_id
        Unique identifier for this snapshot instance.
    entries
        All :class:`AttachedSessionRegistryEntry` records in the ring buffer
        at snapshot time (newest first).
    active_count
        Number of entries in ``active`` state.
    replaced_count
        Number of entries in ``replaced`` state.
    detached_count
        Number of entries in ``detached`` state.
    invalidated_count
        Number of entries in ``invalidated`` state.
    total_count
        Total number of entries in the snapshot.
    snapshotted_at
        Unix epoch seconds when this snapshot was assembled.
    policy_sentinels
        List of policy sentinel strings included for audit purposes.
    """

    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    entries: List[AttachedSessionRegistryEntry] = field(default_factory=list)
    active_count: int = 0
    replaced_count: int = 0
    detached_count: int = 0
    invalidated_count: int = 0
    total_count: int = 0
    snapshotted_at: float = field(default_factory=time.time)
    policy_sentinels: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "snapshot_id": self.snapshot_id,
            "entries": [e.to_dict() for e in self.entries],
            "active_count": self.active_count,
            "replaced_count": self.replaced_count,
            "detached_count": self.detached_count,
            "invalidated_count": self.invalidated_count,
            "total_count": self.total_count,
            "snapshotted_at": self.snapshotted_at,
            "policy_sentinels": self.policy_sentinels,
        }

    def to_json(self) -> str:
        """Return a compact JSON string representation."""
        return json.dumps(self.to_dict(), separators=(",", ":"))


# ---------------------------------------------------------------------------
# AttachedSessionRegistry  (128-entry ring buffer)
# ---------------------------------------------------------------------------


class AttachedSessionRegistry:
    """In-process ring-buffer registry for attached runtime session entries.

    Accumulates up to ``capacity`` (128) :class:`AttachedSessionRegistryEntry`
    instances across the process lifetime.  Oldest entries are silently evicted
    when the buffer is full (FIFO).

    Design notes
    ------------
    * **Device-keyed active pointer**: ``_active_by_device`` maps each
      ``device_id`` to the ``entry_id`` of the currently active entry.  When a
      new session is registered this map is updated and the old entry is moved
      to ``replaced``.
    * **Session-keyed lookup**: ``_entry_by_session`` maps ``session_id`` →
      ``entry_id`` for the most recent entry with that session_id.
    * Both indices are maintained as plain dicts; stale entries (pointing to
      evicted ring-buffer slots) are silently returned as None by lookups.
    """

    def __init__(self, capacity: int = _RING_BUFFER_CAPACITY) -> None:
        self._capacity = capacity
        self._buffer: Deque[AttachedSessionRegistryEntry] = deque(maxlen=capacity)
        # device_id → entry_id of the current active entry
        self._active_by_device: Dict[str, str] = {}
        # session_id → entry_id of the most recent entry for that session_id
        self._entry_by_session: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_by_entry_id(self, entry_id: str) -> Optional[AttachedSessionRegistryEntry]:
        """Return the entry matching *entry_id*, or None if evicted/not found."""
        for entry in reversed(self._buffer):
            if entry.entry_id == entry_id:
                return entry
        return None

    def _replace_in_buffer(self, updated: AttachedSessionRegistryEntry) -> bool:
        """Replace the entry with the same ``entry_id`` in the buffer in-place.

        Returns True if found and replaced, False otherwise.
        """
        buf_list = list(self._buffer)
        for i, e in enumerate(buf_list):
            if e.entry_id == updated.entry_id:
                buf_list[i] = updated
                self._buffer = deque(buf_list, maxlen=self._capacity)
                return True
        return False

    def _push(self, entry: AttachedSessionRegistryEntry) -> None:
        """Append *entry* to the ring buffer and update lookup indices."""
        self._buffer.append(entry)
        if entry.is_active():
            self._active_by_device[entry.device_id] = entry.entry_id
        if entry.session_id:
            self._entry_by_session[entry.session_id] = entry.entry_id

    def _update_indices(self, entry: AttachedSessionRegistryEntry) -> None:
        """Refresh lookup indices after an in-place buffer replacement."""
        if entry.is_active():
            self._active_by_device[entry.device_id] = entry.entry_id
        elif (
            self._active_by_device.get(entry.device_id) == entry.entry_id
            and not entry.is_active()
        ):
            # Remove stale active pointer
            del self._active_by_device[entry.device_id]

    # ------------------------------------------------------------------
    # Mutation API (called only by module-level functions)
    # ------------------------------------------------------------------

    def push_new(self, entry: AttachedSessionRegistryEntry) -> None:
        """Record a brand-new registry entry (no prior entry for this entry_id)."""
        self._push(entry)

    def apply_transition(
        self,
        entry: AttachedSessionRegistryEntry,
        transition: RegistryTransition,
        *,
        invalidation_reason: InvalidationReason = InvalidationReason.none,
        session_id: str = "",
        posture: str = "",
        host_role: str = "",
        coordination_role: str = "",
        capability_tier: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AttachedSessionRegistryEntry:
        """Apply *transition* to *entry*, returning the updated entry.

        If the transition is valid the updated entry is persisted back into
        the ring buffer (in-place replacement when possible, otherwise push).
        If the transition is illegal (no table entry) the original entry is
        returned unchanged.
        """
        next_state = _resolve_transition(entry.attachment_state, transition)
        if next_state is None:
            # Illegal transition — return unchanged
            return entry

        now = time.time()

        # For reconnect / reattach: restore active pointer
        new_reason = invalidation_reason
        if transition in (RegistryTransition.reconnect, RegistryTransition.reattach):
            new_reason = InvalidationReason.none
        elif transition == RegistryTransition.detach:
            new_reason = (
                invalidation_reason
                if invalidation_reason != InvalidationReason.none
                else InvalidationReason.detached
            )
        elif transition == RegistryTransition.invalidate:
            new_reason = (
                invalidation_reason
                if invalidation_reason != InvalidationReason.none
                else InvalidationReason.invalidated
            )
        elif transition == RegistryTransition.replace:
            new_reason = InvalidationReason.replaced

        updated = AttachedSessionRegistryEntry(
            entry_id=entry.entry_id,
            session_id=session_id if session_id else entry.session_id,
            device_id=entry.device_id,
            runtime_session_id=entry.runtime_session_id,
            attachment_state=next_state,
            invalidation_reason=new_reason,
            posture=(posture.lower().strip() if posture else entry.posture),
            host_role=host_role if host_role else entry.host_role,
            coordination_role=coordination_role if coordination_role else entry.coordination_role,
            capability_tier=capability_tier if capability_tier else entry.capability_tier,
            last_transition=transition,
            previous_state=entry.attachment_state,
            registered_at=entry.registered_at,
            last_transition_at=now,
            metadata={**entry.metadata, **(metadata or {})},
            reconnect_count=(
                entry.reconnect_count + 1
                if transition == RegistryTransition.reconnect
                else entry.reconnect_count
            ),
            last_reconnect_at=(
                now
                if transition == RegistryTransition.reconnect
                else entry.last_reconnect_at
            ),
        )

        replaced = self._replace_in_buffer(updated)
        if not replaced:
            self._push(updated)
        else:
            self._update_indices(updated)

        return updated

    def supersede_active_for_device(self, device_id: str) -> Optional[AttachedSessionRegistryEntry]:
        """Move the current active entry for *device_id* to ``replaced`` state.

        Returns the updated (replaced) entry, or None if no active entry existed.
        Called internally by :func:`register_session` before inserting a new entry.
        """
        entry_id = self._active_by_device.get(device_id)
        if entry_id is None:
            return None
        old_entry = self._get_by_entry_id(entry_id)
        if old_entry is None:
            return None
        if not old_entry.is_active():
            return None
        return self.apply_transition(old_entry, RegistryTransition.replace)

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def get_active_for_device(
        self, device_id: str
    ) -> Optional[AttachedSessionRegistryEntry]:
        """Return the currently active entry for *device_id*, or None."""
        entry_id = self._active_by_device.get(device_id)
        if entry_id is None:
            return None
        entry = self._get_by_entry_id(entry_id)
        if entry is None or not entry.is_active():
            return None
        return entry

    def get_by_session_id(
        self,
        session_id: str,
        *,
        active_only: bool = True,
    ) -> Optional[AttachedSessionRegistryEntry]:
        """Return the most recent entry for *session_id*, or None.

        Parameters
        ----------
        session_id
            External session identifier to look up.
        active_only
            When True (default) only returns the entry if it is currently active.
        """
        entry_id = self._entry_by_session.get(session_id)
        if entry_id is None:
            return None
        entry = self._get_by_entry_id(entry_id)
        if entry is None:
            return None
        if active_only and not entry.is_active():
            return None
        return entry

    def list_all_active(self) -> List[AttachedSessionRegistryEntry]:
        """Return all entries currently in ``active`` state, newest first."""
        return [e for e in reversed(self._buffer) if e.is_active()]

    def list_all(self) -> List[AttachedSessionRegistryEntry]:
        """Return all entries in the ring buffer, newest first."""
        return list(reversed(self._buffer))

    def size(self) -> int:
        """Return the current number of entries in the buffer."""
        return len(self._buffer)

    def capacity(self) -> int:
        """Return the maximum capacity of the buffer."""
        return self._capacity

    def clear(self) -> None:
        """Remove all entries and reset lookup indices (for testing)."""
        self._buffer.clear()
        self._active_by_device.clear()
        self._entry_by_session.clear()

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> AttachedSessionRegistrySnapshot:
        """Return a point-in-time :class:`AttachedSessionRegistrySnapshot`."""
        all_entries = self.list_all()
        active = sum(1 for e in all_entries if e.attachment_state == RegistryEntryState.active)
        replaced = sum(1 for e in all_entries if e.attachment_state == RegistryEntryState.replaced)
        detached = sum(1 for e in all_entries if e.attachment_state == RegistryEntryState.detached)
        invalidated = sum(
            1 for e in all_entries if e.attachment_state == RegistryEntryState.invalidated
        )
        return AttachedSessionRegistrySnapshot(
            entries=all_entries,
            active_count=active,
            replaced_count=replaced,
            detached_count=detached,
            invalidated_count=invalidated,
            total_count=len(all_entries),
            policy_sentinels=[
                ATTACHED_RUNTIME_SESSION_REGISTRY_AUTHORITY,
                REGISTRY_IS_SINGLE_TRUTH_SOURCE_POLICY,
                REGISTRY_DEVICE_HAS_AT_MOST_ONE_ACTIVE_SESSION_POLICY,
                ATTACHED_RUNTIME_SESSION_REGISTRY_PR19_SENTINEL,
            ],
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_REGISTRY_SINGLETON: Optional[AttachedSessionRegistry] = None


def get_session_registry() -> AttachedSessionRegistry:
    """Return the module-level :class:`AttachedSessionRegistry` singleton.

    Creates the singleton on first call.
    """
    global _REGISTRY_SINGLETON  # noqa: PLW0603
    if _REGISTRY_SINGLETON is None:
        _REGISTRY_SINGLETON = AttachedSessionRegistry(capacity=_RING_BUFFER_CAPACITY)
    return _REGISTRY_SINGLETON


def reset_session_registry() -> None:
    """Reset the singleton (primarily for test isolation)."""
    global _REGISTRY_SINGLETON  # noqa: PLW0603
    _REGISTRY_SINGLETON = None


# ---------------------------------------------------------------------------
# Core API — register_session
# ---------------------------------------------------------------------------


def register_session(
    device_id: str,
    *,
    session_id: str = "",
    posture: str = _POSTURE_JOIN_RUNTIME,
    host_role: str = "",
    coordination_role: str = "",
    capability_tier: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    registry: Optional[AttachedSessionRegistry] = None,
) -> AttachedSessionRegistryEntry:
    """Register a new session for *device_id* in the registry.

    If the device already has an active session the old entry is automatically
    moved to ``replaced`` state before the new entry is created (honouring
    :data:`REGISTRY_REGISTER_REPLACES_OLD_SESSION_POLICY`).

    A new ``runtime_session_id`` is generated for every call to
    ``register_session``.

    Parameters
    ----------
    device_id
        Identifier of the device/runtime to register.
    session_id
        Optional external session identifier.
    posture
        Participation posture; defaults to ``join_runtime``.
    host_role
        AndroidRuntimeHostRole string (PR-5), informational.
    coordination_role
        Coordination role for this participant.
    capability_tier
        CapabilityTier string (PR package 6), informational.
    metadata
        Arbitrary caller-supplied metadata.
    registry
        Optional :class:`AttachedSessionRegistry` to use; defaults to the
        module singleton.

    Returns
    -------
    AttachedSessionRegistryEntry
        The newly created active entry.
    """
    if registry is None:
        registry = get_session_registry()

    # Supersede any existing active session for this device
    registry.supersede_active_for_device(device_id)

    now = time.time()
    entry = AttachedSessionRegistryEntry(
        device_id=device_id,
        session_id=session_id or "",
        runtime_session_id=str(uuid.uuid4()),
        attachment_state=RegistryEntryState.active,
        invalidation_reason=InvalidationReason.none,
        posture=(posture or _POSTURE_JOIN_RUNTIME).lower().strip(),
        host_role=host_role or "",
        coordination_role=coordination_role or "",
        capability_tier=capability_tier or "",
        last_transition=RegistryTransition.register,
        previous_state=None,
        registered_at=now,
        last_transition_at=now,
        metadata=metadata or {},
    )
    registry.push_new(entry)
    return entry


# ---------------------------------------------------------------------------
# Core API — reconnect_session
# ---------------------------------------------------------------------------


def reconnect_session(
    entry: AttachedSessionRegistryEntry,
    *,
    session_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    registry: Optional[AttachedSessionRegistry] = None,
) -> AttachedSessionRegistryEntry:
    """Reconnect a previously detached/disconnected session.

    Restores the entry to ``active`` state without changing
    ``runtime_session_id`` (per
    :data:`REGISTRY_RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY`).

    Parameters
    ----------
    entry
        The registry entry to reconnect.
    session_id
        Optional updated external session identifier.
    metadata
        Optional metadata to merge into the entry.
    registry
        Optional :class:`AttachedSessionRegistry` to use; defaults to the
        module singleton.

    Returns
    -------
    AttachedSessionRegistryEntry
        The updated entry in ``active`` state.
    """
    if registry is None:
        registry = get_session_registry()
    return registry.apply_transition(
        entry,
        RegistryTransition.reconnect,
        invalidation_reason=InvalidationReason.none,
        session_id=session_id,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Core API — reattach_session
# ---------------------------------------------------------------------------


def reattach_session(
    entry: AttachedSessionRegistryEntry,
    *,
    session_id: str = "",
    posture: str = "",
    host_role: str = "",
    coordination_role: str = "",
    capability_tier: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    registry: Optional[AttachedSessionRegistry] = None,
) -> AttachedSessionRegistryEntry:
    """Re-attach an existing entry after an explicit detach.

    Restores ``active`` state.  Unlike :func:`register_session`, this
    preserves the existing ``runtime_session_id``.

    Parameters
    ----------
    entry
        The registry entry to re-attach.
    session_id
        Optional updated external session identifier.
    posture / host_role / coordination_role / capability_tier
        Fields to update on the entry; empty string means keep existing value.
    metadata
        Optional metadata to merge into the entry.
    registry
        Optional :class:`AttachedSessionRegistry` to use; defaults to the
        module singleton.

    Returns
    -------
    AttachedSessionRegistryEntry
        The updated entry in ``active`` state.
    """
    if registry is None:
        registry = get_session_registry()
    return registry.apply_transition(
        entry,
        RegistryTransition.reattach,
        invalidation_reason=InvalidationReason.none,
        session_id=session_id,
        posture=posture,
        host_role=host_role,
        coordination_role=coordination_role,
        capability_tier=capability_tier,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Core API — detach_session
# ---------------------------------------------------------------------------


def detach_session(
    entry: AttachedSessionRegistryEntry,
    *,
    reason: InvalidationReason = InvalidationReason.detached,
    metadata: Optional[Dict[str, Any]] = None,
    registry: Optional[AttachedSessionRegistry] = None,
) -> AttachedSessionRegistryEntry:
    """Detach an active session.

    Moves the entry to ``detached`` state (recoverable).

    Parameters
    ----------
    entry
        The registry entry to detach.
    reason
        :class:`InvalidationReason` to record; defaults to ``detached``.
    metadata
        Optional metadata to merge into the entry.
    registry
        Optional :class:`AttachedSessionRegistry` to use; defaults to the
        module singleton.

    Returns
    -------
    AttachedSessionRegistryEntry
        The updated entry in ``detached`` state.
    """
    if registry is None:
        registry = get_session_registry()
    return registry.apply_transition(
        entry,
        RegistryTransition.detach,
        invalidation_reason=reason,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Core API — invalidate_session
# ---------------------------------------------------------------------------


def invalidate_session(
    entry: AttachedSessionRegistryEntry,
    reason: InvalidationReason = InvalidationReason.invalidated,
    *,
    metadata: Optional[Dict[str, Any]] = None,
    registry: Optional[AttachedSessionRegistry] = None,
) -> AttachedSessionRegistryEntry:
    """Invalidate a session (terminal transition).

    Moves the entry to ``invalidated`` state.  After this transition the entry
    cannot be recovered; a new :func:`register_session` call is required.

    Parameters
    ----------
    entry
        The registry entry to invalidate.
    reason
        :class:`InvalidationReason` to record; defaults to ``invalidated``.
    metadata
        Optional metadata to merge into the entry.
    registry
        Optional :class:`AttachedSessionRegistry` to use; defaults to the
        module singleton.

    Returns
    -------
    AttachedSessionRegistryEntry
        The updated entry in ``invalidated`` state.
    """
    if registry is None:
        registry = get_session_registry()
    return registry.apply_transition(
        entry,
        RegistryTransition.invalidate,
        invalidation_reason=reason,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Core API — lookup functions
# ---------------------------------------------------------------------------


def lookup_active_session(
    session_id: str,
    *,
    active_only: bool = True,
    registry: Optional[AttachedSessionRegistry] = None,
) -> Optional[AttachedSessionRegistryEntry]:
    """Look up a registry entry by external *session_id*.

    Parameters
    ----------
    session_id
        External session identifier to look up.
    active_only
        When True (default) returns None for non-active entries, consistent
        with :data:`REGISTRY_LOOKUP_RETURNS_ACTIVE_ONLY_BY_DEFAULT_POLICY`.
    registry
        Optional :class:`AttachedSessionRegistry` to use; defaults to the
        module singleton.

    Returns
    -------
    AttachedSessionRegistryEntry | None
        The matching entry, or None if not found or not active.
    """
    if registry is None:
        registry = get_session_registry()
    return registry.get_by_session_id(session_id, active_only=active_only)


def lookup_session_by_device(
    device_id: str,
    *,
    registry: Optional[AttachedSessionRegistry] = None,
) -> Optional[AttachedSessionRegistryEntry]:
    """Look up the currently active registry entry for *device_id*.

    Always returns only the active entry; non-active entries are not returned.

    Parameters
    ----------
    device_id
        Device identifier to look up.
    registry
        Optional :class:`AttachedSessionRegistry` to use; defaults to the
        module singleton.

    Returns
    -------
    AttachedSessionRegistryEntry | None
        The active entry for *device_id*, or None if not found.
    """
    if registry is None:
        registry = get_session_registry()
    return registry.get_active_for_device(device_id)


def list_active_sessions(
    *,
    registry: Optional[AttachedSessionRegistry] = None,
) -> List[AttachedSessionRegistryEntry]:
    """Return all currently active registry entries (newest first).

    Parameters
    ----------
    registry
        Optional :class:`AttachedSessionRegistry` to use; defaults to the
        module singleton.

    Returns
    -------
    list[AttachedSessionRegistryEntry]
        All entries in ``active`` state, newest first.
    """
    if registry is None:
        registry = get_session_registry()
    return registry.list_all_active()


def build_registry_snapshot(
    *,
    registry: Optional[AttachedSessionRegistry] = None,
) -> AttachedSessionRegistrySnapshot:
    """Return a point-in-time :class:`AttachedSessionRegistrySnapshot`.

    Parameters
    ----------
    registry
        Optional :class:`AttachedSessionRegistry` to use; defaults to the
        module singleton.

    Returns
    -------
    AttachedSessionRegistrySnapshot
        Snapshot of the current registry state.
    """
    if registry is None:
        registry = get_session_registry()
    return registry.snapshot()
