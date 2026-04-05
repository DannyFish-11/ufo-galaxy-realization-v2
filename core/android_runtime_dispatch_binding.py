"""core/android_runtime_dispatch_binding.py
=============================================
PR package 11 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Canonical MAIN-Side Attached-Android-Runtime Dispatch Binding Basis.

This module is the **canonical authority** for the host-side representation
of the targeting identity that binds a delegated-dispatch/handoff intent to a
specific attached Android runtime surface.  It introduces a stable, typed
binding record that explicitly captures the relationship between an attached
runtime session (PR-7), a target Android host/device (PR-5), a delegated
handoff contract (PR-9), and an execution tracker (PR-10), so that
dispatch, handoff planning, and later takeover/reuse all converge on one
canonical targeting model rather than scattered implicit field assumptions.

Background
----------
After PR-10 established execution-tracking foundations, the host-side
orchestration layer can track delegated work but still lacks a single
canonical record that binds *which attached Android runtime session* a
specific dispatch/handoff is targeting.  Today, the identity relationship
between:

- the attached-session id (PR-7)
- the target Android host/device id (PR-5)
- the handoff contract id (PR-9)
- the execution tracker id (PR-10)

may live in separate ad hoc fields across different modules or be inferred
implicitly from call-site context.  This means later Android receipt, local
takeover, and persistent-reuse code must reconstruct or guess the targeting
identity rather than reading it from one authoritative binding record.

PR-11 closes this gap on the MAIN-repo side by providing:

1. :class:`AndroidRuntimeBindingState` — canonical enum for the lifecycle
   state of a dispatch binding
   (``unbound`` / ``binding`` / ``bound`` / ``dispatching`` / ``suspended``
   / ``released``).
2. :class:`AndroidRuntimeBindingSignal` — canonical enum for the signals
   that drive binding state transitions
   (``bind`` / ``confirm`` / ``dispatch`` / ``suspend`` / ``resume``
   / ``release``).
3. :class:`AndroidRuntimeDispatchBindingIdentity` — stable, serialisable
   record capturing the canonical targeting identifiers: binding_id,
   session_id, device_id, contract_id, tracker_id, trace_id.
4. :class:`AndroidRuntimeDispatchBindingRecord` — canonical, immutable
   top-level binding record aggregating identity, binding state,
   posture/role/capability context, and lifecycle timestamps.  This is the
   single authoritative answer to *"which Android runtime surface is this
   dispatch targeting?"*
5. :class:`AndroidRuntimeDispatchBindingSnapshot` — point-in-time snapshot
   of all recent binding records for audit and projection.
6. :class:`AndroidRuntimeDispatchBindingRuntime` — in-process ring-buffer
   singleton (128 entries) accumulating binding records across the process
   lifetime.
7. :func:`create_android_dispatch_binding` — creates a canonical
   :class:`AndroidRuntimeDispatchBindingRecord` from attached-session,
   device, contract, and tracker identity inputs, defaulting to state
   ``unbound``.
8. :func:`advance_binding_state` — returns a new record with the binding
   state advanced according to the given
   :class:`AndroidRuntimeBindingSignal`, preserving all identity fields.
9. :func:`resolve_dispatch_binding` — convenience factory that constructs a
   binding record directly from an attached-session record (PR-7), a handoff
   contract record (PR-9), and an execution tracking record (PR-10), pulling
   identity fields from each and validating cross-record consistency.
10. :func:`record_dispatch_binding` — persists a binding record to the
    ring-buffer singleton.
11. :func:`get_dispatch_binding` — retrieves the most recent binding record
    for a given ``session_id`` from the ring-buffer.
12. :func:`get_dispatch_binding_by_contract` — retrieves the most recent
    binding record for a given ``contract_id``.
13. :func:`list_bound_dispatch_bindings` — returns all binding records in
    an active (non-released) state, newest-first.
14. :func:`build_dispatch_binding_snapshot` — assembles a
    :class:`AndroidRuntimeDispatchBindingSnapshot` from the ring-buffer.
15. :func:`get_dispatch_binding_runtime` /
    :func:`reset_dispatch_binding_runtime` — singleton accessor and
    test-isolation helper.
16. Ten policy sentinels documenting canonical dispatch-binding rules.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Session-anchored** — every binding record references an attached-session
  id from PR-7; unanchored bindings are rejected at creation time.
- **Device-bound** — the target device_id must be non-empty; a binding
  without a target device is semantically invalid.
- **Contract-linked** — when a handoff contract id is available it must be
  propagated into the binding identity so handoff planning and takeover can
  reach the canonical binding without extra lookups.
- **Tracker-linked** — when an execution tracker id is available it must
  likewise be propagated into the binding identity.
- **Posture-preserving** — ``source_runtime_posture`` flows from the
  attached-session record into the binding unchanged.
- **State-monotonic** — :class:`AndroidRuntimeBindingState` advances
  predictably via the signal-driven transition table; illegal transitions
  leave the state unchanged rather than raising.
- **Released-is-terminal** — once a binding reaches ``released`` it cannot
  be re-advanced; a new binding must be created for the next dispatch cycle.
- **Fully serialisable** — all dataclasses expose ``to_dict()`` /
  ``to_json()`` and ``from_dict()`` for stable, round-trippable wire
  representations.
- **Graceful degradation** — unknown or missing fields default to safe
  outcomes (``unbound`` state, empty strings for optional ids).

Relationship to other PR packages
----------------------------------
* PR-1  (``core.posture_contract_canonicalization``) — posture field is
  validated against the contract-layer canonicalization rules.
* PR-3  (``core.canonical_handoff_path``) — the canonical handoff path
  consumes the binding record's contract_id when constructing envelopes.
* PR-5  (``core.android_runtime_host``) — android_host_role is read from
  the device record and stored in the binding.
* PR-6  (``core.canonical_capability_scheduling_basis``) — capability_tier
  is forwarded from the attached session or dispatch record.
* PR-7  (``core.attached_runtime_session``) — every binding is anchored to
  a persistent attached-runtime session record.
* PR-8  (``core.delegated_runtime_dispatch_intent``) — the dispatch intent
  record produces the session_id, device_id, and capability context that
  feed into the binding.
* PR-9  (``core.delegated_runtime_handoff_contract``) — the handoff contract
  id is carried in the binding identity to link contract and binding.
* PR-10 (``core.delegated_runtime_execution_tracker``) — the execution
  tracker id is carried in the binding identity to link tracker and binding.
* PR-538 (``core.multi_device_coordination_authority``) — coordination_role
  is forwarded from the attached session into the binding.

Public API
----------
Sentinels::

    ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY
    BINDING_REQUIRES_ATTACHED_SESSION_POLICY
    BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY
    BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY
    BINDING_SESSION_ID_MUST_MATCH_CONTRACT_POLICY
    BINDING_STATE_IS_MONOTONIC_POLICY
    RELEASED_BINDING_IS_TERMINAL_POLICY
    BINDING_CONTRACT_ID_IS_IMMUTABLE_POLICY
    DISPATCH_BINDING_REQUIRES_CONTRACT_ID_POLICY
    BINDING_TRACKER_ID_IS_PROPAGATED_POLICY
    ANDROID_RUNTIME_DISPATCH_BINDING_PR11_SENTINEL

Enums::

    AndroidRuntimeBindingState
    AndroidRuntimeBindingSignal

Dataclasses::

    AndroidRuntimeDispatchBindingIdentity
    AndroidRuntimeDispatchBindingRecord
    AndroidRuntimeDispatchBindingSnapshot

Runtime / ring-buffer::

    AndroidRuntimeDispatchBindingRuntime

Functions::

    create_android_dispatch_binding
    advance_binding_state
    resolve_dispatch_binding
    record_dispatch_binding
    get_dispatch_binding
    get_dispatch_binding_by_contract
    list_bound_dispatch_bindings
    build_dispatch_binding_snapshot
    get_dispatch_binding_runtime
    reset_dispatch_binding_runtime
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

ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY: str = (
    "ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY::"
    "core.android_runtime_dispatch_binding is the canonical authority for the "
    "MAIN-side attached-Android-runtime dispatch binding identity.  All "
    "dispatch/handoff planning code that targets an attached Android runtime "
    "surface MUST construct or resolve an AndroidRuntimeDispatchBindingRecord "
    "to express the targeting relationship rather than scattering session, "
    "device, contract, and tracker ids across ad hoc fields."
)

BINDING_REQUIRES_ATTACHED_SESSION_POLICY: str = (
    "POLICY::BINDING_REQUIRES_ATTACHED_SESSION: a dispatch binding record "
    "MUST carry a non-empty session_id referencing a persistent attached "
    "runtime session established by PR-7.  Bindings without a session anchor "
    "are rejected and returned in the 'released' terminal state with a "
    "reject_reason explaining the violation."
)

BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY: str = (
    "POLICY::BINDING_REQUIRES_JOIN_RUNTIME_POSTURE: only Android devices "
    "whose source_runtime_posture is 'join_runtime' may serve as a dispatch "
    "binding target.  A binding constructed for a 'control_only' device is "
    "rejected and returned in the 'released' terminal state."
)

BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY: str = (
    "POLICY::BINDING_REQUIRES_TARGET_DEVICE_ID: a dispatch binding record "
    "MUST carry a non-empty device_id identifying the target Android host.  "
    "A binding without a target device id is semantically invalid and will "
    "be rejected."
)

BINDING_SESSION_ID_MUST_MATCH_CONTRACT_POLICY: str = (
    "POLICY::BINDING_SESSION_ID_MUST_MATCH_CONTRACT: when a handoff contract "
    "record is used to resolve a binding via resolve_dispatch_binding(), the "
    "session_id embedded in the contract identity must match the session_id "
    "of the attached-session record.  Mismatches cause the binding to be "
    "rejected."
)

BINDING_STATE_IS_MONOTONIC_POLICY: str = (
    "POLICY::BINDING_STATE_IS_MONOTONIC: AndroidRuntimeBindingState advances "
    "predictably via the signal-driven transition table defined in this "
    "module.  Callers must apply the appropriate AndroidRuntimeBindingSignal "
    "rather than constructing records with an arbitrary state value."
)

RELEASED_BINDING_IS_TERMINAL_POLICY: str = (
    "POLICY::RELEASED_BINDING_IS_TERMINAL: once an "
    "AndroidRuntimeDispatchBindingRecord reaches the 'released' state no "
    "further state transitions are permitted.  Callers that need to re-bind "
    "after a release must call create_android_dispatch_binding() to start a "
    "new binding lifecycle."
)

BINDING_CONTRACT_ID_IS_IMMUTABLE_POLICY: str = (
    "POLICY::BINDING_CONTRACT_ID_IS_IMMUTABLE: the contract_id field of an "
    "AndroidRuntimeDispatchBindingIdentity is set at creation time and must "
    "not change across state transitions.  advance_binding_state() preserves "
    "all identity fields unchanged."
)

DISPATCH_BINDING_REQUIRES_CONTRACT_ID_POLICY: str = (
    "POLICY::DISPATCH_BINDING_REQUIRES_CONTRACT_ID: before a binding can "
    "advance to 'dispatching' state it MUST carry a non-empty contract_id.  "
    "Attempting to dispatch a binding without a contract_id is rejected and "
    "the binding state remains unchanged."
)

BINDING_TRACKER_ID_IS_PROPAGATED_POLICY: str = (
    "POLICY::BINDING_TRACKER_ID_IS_PROPAGATED: the tracker_id field in an "
    "AndroidRuntimeDispatchBindingIdentity flows from the execution tracker "
    "record (PR-10) into the binding at creation or resolve time and is "
    "preserved across all state transitions without modification."
)

ANDROID_RUNTIME_DISPATCH_BINDING_PR11_SENTINEL: str = (
    "ANDROID_RUNTIME_DISPATCH_BINDING_PR11_SENTINEL::package=11 "
    "canonical-android-runtime-dispatch-binding-post-533-main-repo-pr11-v1"
)

_ALL_POLICY_SENTINELS = (
    ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY,
    BINDING_REQUIRES_ATTACHED_SESSION_POLICY,
    BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
    BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY,
    BINDING_SESSION_ID_MUST_MATCH_CONTRACT_POLICY,
    BINDING_STATE_IS_MONOTONIC_POLICY,
    RELEASED_BINDING_IS_TERMINAL_POLICY,
    BINDING_CONTRACT_ID_IS_IMMUTABLE_POLICY,
    DISPATCH_BINDING_REQUIRES_CONTRACT_ID_POLICY,
    BINDING_TRACKER_ID_IS_PROPAGATED_POLICY,
)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_POSTURE_JOIN_RUNTIME: str = "join_runtime"
_POSTURE_CONTROL_ONLY: str = "control_only"
_RING_BUFFER_CAPACITY: int = 128

# ---------------------------------------------------------------------------
# AndroidRuntimeBindingState
# ---------------------------------------------------------------------------


class AndroidRuntimeBindingState(str, Enum):
    """Canonical lifecycle states for an attached-Android-runtime dispatch binding.

    unbound
        The binding record has been created but the attached Android session
        has not yet been confirmed as the dispatch target.  This is the
        initial state for all new binding records.
    binding
        The host has initiated the binding handshake with the attached Android
        runtime session and is awaiting confirmation.
    bound
        The attached Android runtime session has been confirmed as the
        dispatch target.  The binding is ready to accept a handoff contract
        and proceed to dispatch.
    dispatching
        A handoff contract has been associated with this binding and the
        delegated payload has been sent to the target Android runtime surface.
        The binding is awaiting an acknowledgment or result.
    suspended
        The binding has been temporarily suspended (e.g. Android session
        entered 'disconnected' state).  The binding is preserved; a
        ``resume`` signal can restore it to ``bound`` when connectivity is
        re-established.
    released
        The binding has been explicitly released.  This is a terminal state.
        A new binding record must be created for the next dispatch cycle.
    """

    unbound = "unbound"
    binding = "binding"
    bound = "bound"
    dispatching = "dispatching"
    suspended = "suspended"
    released = "released"

    @classmethod
    def from_string(
        cls,
        value: str,
        default: "AndroidRuntimeBindingState" = None,
    ) -> "AndroidRuntimeBindingState":
        """Return the enum member matching *value*, or *default* / ``unbound``."""
        if default is None:
            default = cls.unbound
        if not isinstance(value, str):
            return default
        try:
            return cls(value.lower().strip())
        except ValueError:
            return default

    def is_active(self) -> bool:
        """Return True if the binding is in an active (non-released) state."""
        return self != AndroidRuntimeBindingState.released

    def is_terminal(self) -> bool:
        """Return True if the binding is in its terminal state (released)."""
        return self == AndroidRuntimeBindingState.released

    def is_dispatch_ready(self) -> bool:
        """Return True if the binding is ready to accept a dispatch payload."""
        return self == AndroidRuntimeBindingState.bound

    def is_recoverable(self) -> bool:
        """Return True if the binding can be recovered without a new create."""
        return self == AndroidRuntimeBindingState.suspended


# ---------------------------------------------------------------------------
# AndroidRuntimeBindingSignal
# ---------------------------------------------------------------------------


class AndroidRuntimeBindingSignal(str, Enum):
    """Canonical signals that drive binding state transitions.

    bind
        Initiate the binding handshake with the attached Android runtime
        session; transitions from ``unbound`` to ``binding``.
    confirm
        Confirm that the Android runtime session has accepted the binding;
        transitions from ``binding`` to ``bound``.
    dispatch
        Associate a handoff contract with the binding and mark the delegated
        payload as sent; transitions from ``bound`` to ``dispatching``.
    suspend
        Record that the Android session became temporarily unavailable;
        transitions from ``bound`` or ``dispatching`` to ``suspended``.
    resume
        Recover a suspended binding back to ``bound``;
        transitions from ``suspended`` to ``bound``.
    release
        Explicitly release the binding; transitions to ``released``
        (terminal) from any non-terminal state.
    """

    bind = "bind"
    confirm = "confirm"
    dispatch = "dispatch"
    suspend = "suspend"
    resume = "resume"
    release = "release"

    @classmethod
    def from_string(
        cls,
        value: str,
        default: "AndroidRuntimeBindingSignal" = None,
    ) -> "AndroidRuntimeBindingSignal":
        """Return the enum member matching *value*, or *default*."""
        if default is None:
            default = cls.bind
        if not isinstance(value, str):
            return default
        try:
            return cls(value.lower().strip())
        except ValueError:
            return default


# ---------------------------------------------------------------------------
# Transition table
# ---------------------------------------------------------------------------

_TRANSITION_TABLE: Dict[tuple, AndroidRuntimeBindingState] = {
    # bind signal
    (AndroidRuntimeBindingState.unbound, AndroidRuntimeBindingSignal.bind): AndroidRuntimeBindingState.binding,
    (AndroidRuntimeBindingState.bound, AndroidRuntimeBindingSignal.bind): AndroidRuntimeBindingState.bound,  # idempotent
    # confirm signal
    (AndroidRuntimeBindingState.binding, AndroidRuntimeBindingSignal.confirm): AndroidRuntimeBindingState.bound,
    (AndroidRuntimeBindingState.bound, AndroidRuntimeBindingSignal.confirm): AndroidRuntimeBindingState.bound,  # idempotent
    # dispatch signal
    (AndroidRuntimeBindingState.bound, AndroidRuntimeBindingSignal.dispatch): AndroidRuntimeBindingState.dispatching,
    (AndroidRuntimeBindingState.dispatching, AndroidRuntimeBindingSignal.dispatch): AndroidRuntimeBindingState.dispatching,  # idempotent
    # suspend signal
    (AndroidRuntimeBindingState.bound, AndroidRuntimeBindingSignal.suspend): AndroidRuntimeBindingState.suspended,
    (AndroidRuntimeBindingState.dispatching, AndroidRuntimeBindingSignal.suspend): AndroidRuntimeBindingState.suspended,
    (AndroidRuntimeBindingState.binding, AndroidRuntimeBindingSignal.suspend): AndroidRuntimeBindingState.suspended,
    # resume signal
    (AndroidRuntimeBindingState.suspended, AndroidRuntimeBindingSignal.resume): AndroidRuntimeBindingState.bound,
    # release signal — terminal from any non-terminal state
    (AndroidRuntimeBindingState.unbound, AndroidRuntimeBindingSignal.release): AndroidRuntimeBindingState.released,
    (AndroidRuntimeBindingState.binding, AndroidRuntimeBindingSignal.release): AndroidRuntimeBindingState.released,
    (AndroidRuntimeBindingState.bound, AndroidRuntimeBindingSignal.release): AndroidRuntimeBindingState.released,
    (AndroidRuntimeBindingState.dispatching, AndroidRuntimeBindingSignal.release): AndroidRuntimeBindingState.released,
    (AndroidRuntimeBindingState.suspended, AndroidRuntimeBindingSignal.release): AndroidRuntimeBindingState.released,
}


# ---------------------------------------------------------------------------
# AndroidRuntimeDispatchBindingIdentity
# ---------------------------------------------------------------------------


@dataclass
class AndroidRuntimeDispatchBindingIdentity:
    """Stable, serialisable identity record for an attached-Android-runtime dispatch binding.

    This is the single canonical answer to *"which Android runtime surface is
    this dispatch targeting?"*.  All identity fields are set at creation time
    and preserved unchanged across binding state transitions.

    Attributes
    ----------
    binding_id
        Unique, stable identifier for this binding instance.  Auto-generated
        if not provided.
    session_id
        Attached-runtime session id from PR-7.  Must be non-empty.
    device_id
        Identifier of the target Android device / runtime host.  Must be
        non-empty.
    contract_id
        Handoff contract id from PR-9.  May be empty when the binding is
        first created (before a contract is sealed and associated); should
        be populated before advancing to ``dispatching`` state.
    tracker_id
        Execution tracker id from PR-10.  May be empty before tracking
        begins; should be populated alongside the contract_id.
    trace_id
        Distributed trace id propagated from the originating request.
        Auto-generated UUID if not provided.
    """

    session_id: str
    device_id: str
    binding_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    contract_id: str = ""
    tracker_id: str = ""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "binding_id": self.binding_id,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "contract_id": self.contract_id,
            "tracker_id": self.tracker_id,
            "trace_id": self.trace_id,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AndroidRuntimeDispatchBindingIdentity":
        """Construct from a dict.  Raises ValueError if *data* is not a dict."""
        if not isinstance(data, dict):
            raise ValueError(
                "AndroidRuntimeDispatchBindingIdentity.from_dict expects a dict"
            )
        return cls(
            binding_id=data.get("binding_id") or str(uuid.uuid4()),
            session_id=data.get("session_id", ""),
            device_id=data.get("device_id", ""),
            contract_id=data.get("contract_id", ""),
            tracker_id=data.get("tracker_id", ""),
            trace_id=data.get("trace_id") or str(uuid.uuid4()),
        )


# ---------------------------------------------------------------------------
# AndroidRuntimeDispatchBindingRecord
# ---------------------------------------------------------------------------


@dataclass
class AndroidRuntimeDispatchBindingRecord:
    """Canonical, immutable record representing one attached-Android dispatch binding.

    This record is the MAIN-side canonical representation of the targeting
    identity that binds a delegated-dispatch/handoff intent to a specific
    attached Android runtime surface.  It explicitly captures the
    session → device → contract → tracker identity chain so that later
    takeover and persistent-reuse code has one stable model to read rather
    than reconstructing identity from scattered fields.

    Attributes
    ----------
    identity
        The canonical targeting identity (binding_id, session_id, device_id,
        contract_id, tracker_id, trace_id).
    binding_state
        Current lifecycle state of this binding.
    source_runtime_posture
        Source device's participation posture; must be 'join_runtime' for a
        valid binding.
    coordination_role
        Coordination role (from PR-538 / PR-6).
    android_host_role
        Android runtime host role classification string (from PR-5).
    capability_tier
        Capability tier string (from PR-6).
    is_session_anchored
        True when session_id is non-empty (invariant: always True for
        accepted bindings).
    is_device_bound
        True when device_id is non-empty (invariant: always True for
        accepted bindings).
    reject_reason
        Non-empty string describing why the binding was rejected, if
        applicable.  Empty for accepted bindings.
    created_at
        Unix epoch seconds when the binding record was first created.
    updated_at
        Unix epoch seconds when the binding record was last updated.
    metadata
        Arbitrary caller-supplied metadata.
    """

    identity: AndroidRuntimeDispatchBindingIdentity
    binding_state: AndroidRuntimeBindingState = AndroidRuntimeBindingState.unbound
    source_runtime_posture: str = _POSTURE_JOIN_RUNTIME
    coordination_role: str = ""
    android_host_role: str = ""
    capability_tier: str = ""
    is_session_anchored: bool = True
    is_device_bound: bool = True
    reject_reason: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def is_accepted(self) -> bool:
        """Return True if the binding was accepted (no reject reason and anchored)."""
        return (
            not self.reject_reason
            and self.is_session_anchored
            and self.is_device_bound
        )

    def is_rejected(self) -> bool:
        """Return True if the binding was rejected."""
        return bool(self.reject_reason)

    def is_active(self) -> bool:
        """Return True if the binding is in an active (non-released) state."""
        return self.binding_state.is_active()

    def is_terminal(self) -> bool:
        """Return True if the binding is in its terminal (released) state."""
        return self.binding_state.is_terminal()

    def is_dispatch_ready(self) -> bool:
        """Return True if the binding is ready to accept a dispatch payload.

        Per DISPATCH_BINDING_REQUIRES_CONTRACT_ID_POLICY, a binding is only
        truly dispatch-ready when it is in ``bound`` state AND has a
        non-empty contract_id.
        """
        return (
            self.binding_state.is_dispatch_ready()
            and bool(self.identity.contract_id)
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "identity": self.identity.to_dict(),
            "binding_state": self.binding_state.value,
            "source_runtime_posture": self.source_runtime_posture,
            "coordination_role": self.coordination_role,
            "android_host_role": self.android_host_role,
            "capability_tier": self.capability_tier,
            "is_session_anchored": self.is_session_anchored,
            "is_device_bound": self.is_device_bound,
            "reject_reason": self.reject_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AndroidRuntimeDispatchBindingRecord":
        """Construct from a dict.  Raises ValueError if *data* is not a dict."""
        if not isinstance(data, dict):
            raise ValueError(
                "AndroidRuntimeDispatchBindingRecord.from_dict expects a dict"
            )
        raw_identity = data.get("identity", {})
        identity = (
            AndroidRuntimeDispatchBindingIdentity.from_dict(raw_identity)
            if isinstance(raw_identity, dict)
            else AndroidRuntimeDispatchBindingIdentity(session_id="", device_id="")
        )
        return cls(
            identity=identity,
            binding_state=AndroidRuntimeBindingState.from_string(
                data.get("binding_state", "unbound")
            ),
            source_runtime_posture=data.get(
                "source_runtime_posture", _POSTURE_JOIN_RUNTIME
            ),
            coordination_role=data.get("coordination_role", ""),
            android_host_role=data.get("android_host_role", ""),
            capability_tier=data.get("capability_tier", ""),
            is_session_anchored=bool(data.get("is_session_anchored", True)),
            is_device_bound=bool(data.get("is_device_bound", True)),
            reject_reason=data.get("reject_reason", ""),
            created_at=float(data.get("created_at", 0.0)),
            updated_at=float(data.get("updated_at", 0.0)),
            metadata=dict(data.get("metadata", {})),
        )


# ---------------------------------------------------------------------------
# AndroidRuntimeDispatchBindingSnapshot
# ---------------------------------------------------------------------------


@dataclass
class AndroidRuntimeDispatchBindingSnapshot:
    """Point-in-time snapshot of all recent Android dispatch binding records.

    Attributes
    ----------
    records
        All binding records held in the ring-buffer at snapshot time.
    active_count
        Number of binding records in an active (non-released) state.
    total_count
        Total number of records in the snapshot.
    policy_sentinels
        List of policy sentinel strings confirming PR-11 alignment.
    """

    records: List[AndroidRuntimeDispatchBindingRecord] = field(default_factory=list)
    active_count: int = 0
    total_count: int = 0
    policy_sentinels: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "records": [r.to_dict() for r in self.records],
            "active_count": self.active_count,
            "total_count": self.total_count,
            "policy_sentinels": list(self.policy_sentinels),
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# AndroidRuntimeDispatchBindingRuntime  (ring-buffer singleton)
# ---------------------------------------------------------------------------


class AndroidRuntimeDispatchBindingRuntime:
    """In-process ring-buffer accumulating Android dispatch binding records.

    Holds at most :data:`_RING_BUFFER_CAPACITY` (128) records; oldest entries
    are evicted when the buffer is full.  Thread-safety is not guaranteed;
    designed for single-process in-memory use only.

    Parameters
    ----------
    capacity
        Maximum number of records.  Defaults to 128.
    """

    def __init__(self, capacity: int = _RING_BUFFER_CAPACITY) -> None:
        self._capacity = capacity
        self._buffer: Deque[AndroidRuntimeDispatchBindingRecord] = deque(
            maxlen=capacity
        )

    @property
    def capacity(self) -> int:
        """Return the maximum capacity of the ring-buffer."""
        return self._capacity

    def push(self, record: AndroidRuntimeDispatchBindingRecord) -> None:
        """Append *record* to the ring-buffer, evicting the oldest if full."""
        self._buffer.append(record)

    def list_all(self) -> List[AndroidRuntimeDispatchBindingRecord]:
        """Return all records, newest-first."""
        return list(reversed(self._buffer))

    def list_active(self) -> List[AndroidRuntimeDispatchBindingRecord]:
        """Return all records in an active (non-released) state, newest-first."""
        return [r for r in reversed(self._buffer) if r.binding_state.is_active()]

    def get_latest_for_session(
        self, session_id: str
    ) -> Optional[AndroidRuntimeDispatchBindingRecord]:
        """Return the most recent record for *session_id*, or None."""
        for record in reversed(self._buffer):
            if record.identity.session_id == session_id:
                return record
        return None

    def get_latest_for_contract(
        self, contract_id: str
    ) -> Optional[AndroidRuntimeDispatchBindingRecord]:
        """Return the most recent record for *contract_id*, or None."""
        for record in reversed(self._buffer):
            if record.identity.contract_id == contract_id:
                return record
        return None

    def get_latest_for_device(
        self, device_id: str
    ) -> Optional[AndroidRuntimeDispatchBindingRecord]:
        """Return the most recent record for *device_id*, or None."""
        for record in reversed(self._buffer):
            if record.identity.device_id == device_id:
                return record
        return None

    def clear(self) -> None:
        """Clear all records from the ring-buffer."""
        self._buffer.clear()

    def size(self) -> int:
        """Return the current number of records in the ring-buffer."""
        return len(self._buffer)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_singleton: Optional[AndroidRuntimeDispatchBindingRuntime] = None


def get_dispatch_binding_runtime() -> AndroidRuntimeDispatchBindingRuntime:
    """Return the process-level ring-buffer singleton, creating it if needed."""
    global _singleton
    if _singleton is None:
        _singleton = AndroidRuntimeDispatchBindingRuntime()
    return _singleton


def reset_dispatch_binding_runtime() -> None:
    """Reset (replace) the singleton for test isolation.

    After calling this the old singleton is discarded and the next call to
    :func:`get_dispatch_binding_runtime` will create a fresh instance.
    """
    global _singleton
    _singleton = AndroidRuntimeDispatchBindingRuntime()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_rejected_binding(
    *,
    session_id: str,
    device_id: str,
    binding_id: Optional[str],
    trace_id: Optional[str],
    contract_id: str,
    tracker_id: str,
    source_runtime_posture: str,
    coordination_role: str,
    android_host_role: str,
    capability_tier: str,
    reject_reason: str,
    runtime: AndroidRuntimeDispatchBindingRuntime,
) -> AndroidRuntimeDispatchBindingRecord:
    """Create and persist a rejected (released) binding record."""
    record = AndroidRuntimeDispatchBindingRecord(
        identity=AndroidRuntimeDispatchBindingIdentity(
            binding_id=binding_id or str(uuid.uuid4()),
            session_id=session_id,
            device_id=device_id,
            contract_id=contract_id,
            tracker_id=tracker_id,
            trace_id=trace_id or str(uuid.uuid4()),
        ),
        binding_state=AndroidRuntimeBindingState.released,
        source_runtime_posture=source_runtime_posture,
        coordination_role=coordination_role,
        android_host_role=android_host_role,
        capability_tier=capability_tier,
        is_session_anchored=bool(session_id),
        is_device_bound=bool(device_id),
        reject_reason=reject_reason,
    )
    runtime.push(record)
    return record


# ---------------------------------------------------------------------------
# Public API — core functions
# ---------------------------------------------------------------------------


def create_android_dispatch_binding(
    *,
    session_id: str,
    device_id: str,
    source_runtime_posture: str = _POSTURE_JOIN_RUNTIME,
    coordination_role: str = "",
    android_host_role: str = "",
    capability_tier: str = "",
    contract_id: str = "",
    tracker_id: str = "",
    trace_id: Optional[str] = None,
    binding_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    runtime: Optional[AndroidRuntimeDispatchBindingRuntime] = None,
) -> AndroidRuntimeDispatchBindingRecord:
    """Create a canonical attached-Android-runtime dispatch binding record.

    The new record is persisted to the ring-buffer singleton (or *runtime* if
    provided) and returned.

    Validation
    ----------
    * ``session_id`` must be non-empty
      (per :data:`BINDING_REQUIRES_ATTACHED_SESSION_POLICY`).
    * ``device_id`` must be non-empty
      (per :data:`BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY`).
    * ``source_runtime_posture`` must be ``'join_runtime'``
      (per :data:`BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY`).

    Rejection
    ---------
    If any validation rule is violated the function returns a binding record
    in the ``released`` (terminal) state with the ``reject_reason`` field
    populated.

    Parameters
    ----------
    session_id
        Attached-runtime session id (PR-7).  Must be non-empty.
    device_id
        Target Android device / runtime host id.  Must be non-empty.
    source_runtime_posture
        Source device participation posture.  Must be ``'join_runtime'``.
    coordination_role
        Coordination role (PR-538 / PR-6).  Optional.
    android_host_role
        Android runtime host role string (PR-5).  Optional.
    capability_tier
        Capability tier string (PR-6).  Optional.
    contract_id
        Handoff contract id (PR-9).  Optional at creation time.
    tracker_id
        Execution tracker id (PR-10).  Optional at creation time.
    trace_id
        Distributed trace id.  Auto-generated UUID if not provided.
    binding_id
        Explicit binding id.  Auto-generated UUID if not provided.
    metadata
        Arbitrary caller-supplied metadata.
    runtime
        Ring-buffer to persist the record to.  Uses singleton if None.

    Returns
    -------
    AndroidRuntimeDispatchBindingRecord
        Newly created binding record (or a rejected/released record on
        validation failure).
    """
    _runtime = runtime if runtime is not None else get_dispatch_binding_runtime()
    _meta = dict(metadata) if metadata else {}

    # --- validation ---
    if not session_id:
        return _make_rejected_binding(
            session_id=session_id,
            device_id=device_id,
            binding_id=binding_id,
            trace_id=trace_id,
            contract_id=contract_id,
            tracker_id=tracker_id,
            source_runtime_posture=source_runtime_posture,
            coordination_role=coordination_role,
            android_host_role=android_host_role,
            capability_tier=capability_tier,
            reject_reason=(
                "BINDING_REQUIRES_ATTACHED_SESSION: session_id is empty"
            ),
            runtime=_runtime,
        )

    if not device_id:
        return _make_rejected_binding(
            session_id=session_id,
            device_id=device_id,
            binding_id=binding_id,
            trace_id=trace_id,
            contract_id=contract_id,
            tracker_id=tracker_id,
            source_runtime_posture=source_runtime_posture,
            coordination_role=coordination_role,
            android_host_role=android_host_role,
            capability_tier=capability_tier,
            reject_reason=(
                "BINDING_REQUIRES_TARGET_DEVICE_ID: device_id is empty"
            ),
            runtime=_runtime,
        )

    posture_normalised = (source_runtime_posture or "").strip().lower()
    if posture_normalised != _POSTURE_JOIN_RUNTIME:
        return _make_rejected_binding(
            session_id=session_id,
            device_id=device_id,
            binding_id=binding_id,
            trace_id=trace_id,
            contract_id=contract_id,
            tracker_id=tracker_id,
            source_runtime_posture=source_runtime_posture,
            coordination_role=coordination_role,
            android_host_role=android_host_role,
            capability_tier=capability_tier,
            reject_reason=(
                "BINDING_REQUIRES_JOIN_RUNTIME_POSTURE: "
                f"source_runtime_posture '{source_runtime_posture}' is not "
                "'join_runtime'"
            ),
            runtime=_runtime,
        )

    now = time.time()
    record = AndroidRuntimeDispatchBindingRecord(
        identity=AndroidRuntimeDispatchBindingIdentity(
            binding_id=binding_id or str(uuid.uuid4()),
            session_id=session_id,
            device_id=device_id,
            contract_id=contract_id,
            tracker_id=tracker_id,
            trace_id=trace_id or str(uuid.uuid4()),
        ),
        binding_state=AndroidRuntimeBindingState.unbound,
        source_runtime_posture=_POSTURE_JOIN_RUNTIME,
        coordination_role=coordination_role,
        android_host_role=android_host_role,
        capability_tier=capability_tier,
        is_session_anchored=True,
        is_device_bound=True,
        reject_reason="",
        created_at=now,
        updated_at=now,
        metadata=_meta,
    )
    _runtime.push(record)
    return record


def advance_binding_state(
    record: AndroidRuntimeDispatchBindingRecord,
    signal: AndroidRuntimeBindingSignal,
    *,
    runtime: Optional[AndroidRuntimeDispatchBindingRuntime] = None,
) -> AndroidRuntimeDispatchBindingRecord:
    """Apply *signal* to *record*, returning a new record with updated state.

    If the record is already in the terminal ``released`` state the original
    record is returned unchanged
    (per :data:`RELEASED_BINDING_IS_TERMINAL_POLICY`).

    If the (current_state, signal) pair is not in the transition table the
    original record is returned unchanged
    (per :data:`BINDING_STATE_IS_MONOTONIC_POLICY`).

    Special gate: before advancing to ``dispatching`` via the ``dispatch``
    signal, the record's ``contract_id`` must be non-empty
    (per :data:`DISPATCH_BINDING_REQUIRES_CONTRACT_ID_POLICY`).  If the gate
    fails the record is returned unchanged.

    Parameters
    ----------
    record
        The existing binding record to update.
    signal
        The :class:`AndroidRuntimeBindingSignal` to apply.
    runtime
        Ring-buffer to persist the updated record to.  Uses singleton if None.

    Returns
    -------
    AndroidRuntimeDispatchBindingRecord
        Updated record (or *record* unchanged if no valid transition exists).
    """
    if record.binding_state.is_terminal():
        return record

    _runtime = runtime if runtime is not None else get_dispatch_binding_runtime()

    key = (record.binding_state, signal)
    new_state = _TRANSITION_TABLE.get(key)
    if new_state is None:
        return record

    # Gate: dispatch signal requires a non-empty contract_id
    if (
        signal == AndroidRuntimeBindingSignal.dispatch
        and not record.identity.contract_id
    ):
        return record

    updated = AndroidRuntimeDispatchBindingRecord(
        identity=record.identity,
        binding_state=new_state,
        source_runtime_posture=record.source_runtime_posture,
        coordination_role=record.coordination_role,
        android_host_role=record.android_host_role,
        capability_tier=record.capability_tier,
        is_session_anchored=record.is_session_anchored,
        is_device_bound=record.is_device_bound,
        reject_reason=record.reject_reason,
        created_at=record.created_at,
        updated_at=time.time(),
        metadata=dict(record.metadata),
    )
    _runtime.push(updated)
    return updated


def resolve_dispatch_binding(
    attached_session: Any,
    handoff_contract: Any,
    execution_tracker: Any,
    *,
    android_host_role: str = "",
    capability_tier: str = "",
    binding_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    runtime: Optional[AndroidRuntimeDispatchBindingRuntime] = None,
) -> AndroidRuntimeDispatchBindingRecord:
    """Convenience factory: construct a binding from PR-7, PR-9, and PR-10 records.

    Pulls ``session_id``, ``device_id``, ``source_runtime_posture``, and
    ``coordination_role`` from the attached-session record; pulls
    ``contract_id`` and ``trace_id`` from the handoff-contract record; pulls
    ``tracker_id`` from the execution-tracker record.

    Cross-record consistency check
    --------------------------------
    The ``session_id`` embedded in *handoff_contract* (via
    ``identity.session_id``) must match the ``session_id`` of
    *attached_session* (via ``session_id`` attribute or
    ``identity.session_id``), per
    :data:`BINDING_SESSION_ID_MUST_MATCH_CONTRACT_POLICY`.

    If the check fails a rejected binding is returned.

    Parameters
    ----------
    attached_session
        An :class:`~core.attached_runtime_session.AttachedRuntimeSessionRecord`
        instance or compatible object with ``device_id``, ``session_id``,
        ``source_runtime_posture``, and ``coordination_role`` attributes.
    handoff_contract
        A :class:`~core.delegated_runtime_handoff_contract.DelegatedHandoffContractRecord`
        instance or compatible object with ``identity.contract_id``,
        ``identity.session_id``, and ``identity.trace_id`` attributes.
    execution_tracker
        A :class:`~core.delegated_runtime_execution_tracker.DelegatedExecutionTrackingRecord`
        instance or compatible object with ``identity.tracker_id`` attribute.
    android_host_role
        Optional Android host role string override.
    capability_tier
        Optional capability tier string override.
    binding_id
        Explicit binding id.  Auto-generated if not provided.
    metadata
        Arbitrary caller-supplied metadata.
    runtime
        Ring-buffer to persist the record to.  Uses singleton if None.

    Returns
    -------
    AndroidRuntimeDispatchBindingRecord
        Newly created binding record (or a rejected/released record on
        validation failure).
    """
    _runtime = runtime if runtime is not None else get_dispatch_binding_runtime()

    # --- extract session fields ---
    session_id: str = (
        getattr(attached_session, "session_id", None)
        or ""
    )
    device_id: str = (
        getattr(attached_session, "device_id", None)
        or ""
    )
    posture: str = (
        getattr(attached_session, "source_runtime_posture", None)
        or _POSTURE_JOIN_RUNTIME
    )
    coordination_role: str = (
        getattr(attached_session, "coordination_role", None)
        or ""
    )
    _ah_role = android_host_role or getattr(attached_session, "android_host_role", "") or ""
    _cap_tier = capability_tier or getattr(attached_session, "capability_tier", "") or ""

    # --- extract contract fields ---
    contract_identity = getattr(handoff_contract, "identity", None)
    contract_session_id: str = (
        getattr(contract_identity, "session_id", None) or ""
    )
    contract_id: str = (
        getattr(contract_identity, "contract_id", None) or ""
    )
    trace_id: Optional[str] = getattr(contract_identity, "trace_id", None) or None

    # --- extract tracker fields ---
    tracker_identity = getattr(execution_tracker, "identity", None)
    tracker_id: str = (
        getattr(tracker_identity, "tracker_id", None) or ""
    )

    # --- cross-record consistency check ---
    if session_id and contract_session_id and contract_session_id != session_id:
        return _make_rejected_binding(
            session_id=session_id,
            device_id=device_id,
            binding_id=binding_id,
            trace_id=trace_id,
            contract_id=contract_id,
            tracker_id=tracker_id,
            source_runtime_posture=posture,
            coordination_role=coordination_role,
            android_host_role=_ah_role,
            capability_tier=_cap_tier,
            reject_reason=(
                "BINDING_SESSION_ID_MUST_MATCH_CONTRACT: "
                f"attached session_id '{session_id}' does not match "
                f"contract session_id '{contract_session_id}'"
            ),
            runtime=_runtime,
        )

    return create_android_dispatch_binding(
        session_id=session_id,
        device_id=device_id,
        source_runtime_posture=posture,
        coordination_role=coordination_role,
        android_host_role=_ah_role,
        capability_tier=_cap_tier,
        contract_id=contract_id,
        tracker_id=tracker_id,
        trace_id=trace_id,
        binding_id=binding_id,
        metadata=metadata,
        runtime=_runtime,
    )


def record_dispatch_binding(
    record: AndroidRuntimeDispatchBindingRecord,
    *,
    runtime: Optional[AndroidRuntimeDispatchBindingRuntime] = None,
) -> None:
    """Persist *record* to the ring-buffer singleton (or *runtime* if provided)."""
    _runtime = runtime if runtime is not None else get_dispatch_binding_runtime()
    _runtime.push(record)


def get_dispatch_binding(
    session_id: str,
    *,
    runtime: Optional[AndroidRuntimeDispatchBindingRuntime] = None,
) -> Optional[AndroidRuntimeDispatchBindingRecord]:
    """Return the most recent binding record for *session_id*, or None."""
    _runtime = runtime if runtime is not None else get_dispatch_binding_runtime()
    return _runtime.get_latest_for_session(session_id)


def get_dispatch_binding_by_contract(
    contract_id: str,
    *,
    runtime: Optional[AndroidRuntimeDispatchBindingRuntime] = None,
) -> Optional[AndroidRuntimeDispatchBindingRecord]:
    """Return the most recent binding record for *contract_id*, or None."""
    _runtime = runtime if runtime is not None else get_dispatch_binding_runtime()
    return _runtime.get_latest_for_contract(contract_id)


def list_bound_dispatch_bindings(
    *,
    runtime: Optional[AndroidRuntimeDispatchBindingRuntime] = None,
) -> List[AndroidRuntimeDispatchBindingRecord]:
    """Return all binding records in an active (non-released) state, newest-first."""
    _runtime = runtime if runtime is not None else get_dispatch_binding_runtime()
    return _runtime.list_active()


def build_dispatch_binding_snapshot(
    *,
    runtime: Optional[AndroidRuntimeDispatchBindingRuntime] = None,
) -> AndroidRuntimeDispatchBindingSnapshot:
    """Assemble a :class:`AndroidRuntimeDispatchBindingSnapshot` from the ring-buffer.

    Parameters
    ----------
    runtime
        Ring-buffer to snapshot.  Uses singleton if None.
    """
    _runtime = runtime if runtime is not None else get_dispatch_binding_runtime()
    all_records = _runtime.list_all()
    active = [r for r in all_records if r.binding_state.is_active()]
    return AndroidRuntimeDispatchBindingSnapshot(
        records=all_records,
        active_count=len(active),
        total_count=len(all_records),
        policy_sentinels=list(_ALL_POLICY_SENTINELS),
    )
