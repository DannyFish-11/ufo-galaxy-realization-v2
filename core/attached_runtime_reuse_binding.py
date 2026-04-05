"""core/attached_runtime_reuse_binding.py
==========================================
PR package 14 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Canonical Persistent Attached-Runtime Reuse Binding.

This module is the **canonical authority** for host-side persistent
attached-runtime reuse semantics.  It provides the data model, policy gates,
and ring-buffer runtime needed to treat an attached Android runtime as a
**stable, reusable execution surface** for delegated work, from the moment of
attachment until explicit detach / disable / disconnect / invalidation — without
requiring the caller to re-form ad-hoc targeting on every delegated dispatch.

Background
----------
After PR-11 established dispatch binding (session → device → contract →
tracker identity) and PR-13 established host-side signal reconciliation
(ACK/PROGRESS/RESULT/ERROR/TIMEOUT/CANCELLED), the host-side orchestration
layer can bind and track individual delegated executions.  However, both
layers treat each execution independently: every new delegation must locate
an attached session, verify posture, and reconstruct targeting identity from
scratch.

PR-14 closes this gap by introducing a **persistent reuse binding** record
that sits one level above individual dispatch bindings:

- Established once when an attached Android runtime session becomes an active
  execution surface (i.e. when posture == ``join_runtime`` and state ==
  ``attached``).
- Carries the stable targeting context (session_id, device_id,
  android_host_role, capability_tier, posture, coordination_role) that would
  otherwise be re-derived on every dispatch.
- Caches the ``dispatch_binding_id`` of the most recently established
  :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeDispatchBindingRecord`
  so later recovery/reuse code can reach the last binding without extra
  lookups.
- Exposes an explicit :func:`evaluate_reuse_eligibility` gate whose policy
  mirrors PR-7 attachment semantics: eligible only when state is ``active``
  and not invalidated.
- Invalidated immediately and unconditionally on any of the terminal
  lifecycle signals: detach, disable, disconnect, invalidate.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Session-anchored** — every reuse binding record references a persistent
  attached-session from PR-7; bindings without a session anchor are rejected.
- **Posture-preserving** — ``source_runtime_posture`` flows from the
  attached-session record; only ``join_runtime`` sessions are eligible.
- **Stable targeting** — the identity fields (session_id, device_id,
  android_host_role, capability_tier, coordination_role) are set at
  establishment time and never mutated; later dispatches read from the
  binding rather than reconstructing.
- **Dispatch-binding linked** — the ``dispatch_binding_id`` field is updated
  to the most recent :class:`AndroidRuntimeDispatchBindingRecord` binding_id
  each time a dispatch binding is registered against this reuse binding.
- **Clear-on-invalidation** — any of the terminal attachment lifecycle
  signals (detach, disable, disconnect, invalidate) immediately marks the
  reuse binding as invalidated so eligibility checks return ``ineligible``
  without reading stale state.
- **State-monotonic** — reuse eligibility flows from ``eligible`` →
  ``ineligible``; there is no recovery path back to eligible within the same
  binding record (a new binding must be established after re-attach).
- **Fully serialisable** — all dataclasses expose ``to_dict()`` /
  ``to_json()`` for stable, round-trippable wire representations.
- **Graceful degradation** — unknown or missing fields default to safe
  outcomes (``ineligible`` state, conservative posture).

Relationship to other PR packages
----------------------------------
* PR-1  (``core.posture_contract_canonicalization``) — posture field
  validated against contract-layer rules.
* PR-5  (``core.android_runtime_host``) — android_host_role carried from
  attached-session into reuse binding record.
* PR-6  (``core.canonical_capability_scheduling_basis``) — capability_tier
  carried from attached-session into reuse binding record.
* PR-7  (``core.attached_runtime_session``) — every reuse binding is
  anchored to a persistent attached-runtime session; invalidation signals
  mirror PR-7 lifecycle signals.
* PR-8  (``core.delegated_runtime_dispatch_intent``) — dispatch intent
  records may reference the reuse binding to avoid re-deriving targeting.
* PR-9  (``core.delegated_runtime_handoff_contract``) — handoff contracts
  built for reuse-eligible sessions carry the session_id / device_id from the
  reuse binding without extra lookups.
* PR-10 (``core.delegated_runtime_execution_tracker``) — execution tracking
  records built for reuse-eligible sessions carry session_id from the binding.
* PR-11 (``core.android_runtime_dispatch_binding``) — the dispatch_binding_id
  in a reuse binding record points to the most recently registered
  AndroidRuntimeDispatchBindingRecord.
* PR-13 (``core.android_execution_signal_reconciler``) — reconciled signals
  (ACK/RESULT/ERROR) may be correlated against the reuse binding's
  session_id / device_id for multi-execution continuity.
* PR-538 (``core.multi_device_coordination_authority``) — coordination_role
  is forwarded from the attached session into the reuse binding.

Public API
----------
Sentinels::

    ATTACHED_RUNTIME_REUSE_BINDING_AUTHORITY
    REUSE_BINDING_REQUIRES_ATTACHED_SESSION_POLICY
    REUSE_BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY
    REUSE_BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY
    REUSE_ELIGIBILITY_REQUIRES_ACTIVE_SESSION_POLICY
    REUSE_BINDING_INVALIDATED_ON_DETACH_POLICY
    REUSE_BINDING_INVALIDATED_ON_DISCONNECT_POLICY
    REUSE_BINDING_INVALIDATED_ON_DISABLE_POLICY
    REUSE_BINDING_DISPATCH_BINDING_ID_IS_LATEST_POLICY
    REUSE_BINDING_IS_STABLE_TARGETING_SURFACE_POLICY
    ATTACHED_RUNTIME_REUSE_BINDING_PR14_SENTINEL

Enums::

    ReuseEligibilityStatus
    ReuseInvalidationReason

Dataclasses::

    AttachedRuntimeReuseBindingIdentity
    AttachedRuntimeReuseBindingRecord
    AttachedRuntimeReuseBindingSnapshot

Runtime / ring-buffer::

    AttachedRuntimeReuseBindingRuntime

Functions::

    establish_reuse_binding
    evaluate_reuse_eligibility
    invalidate_reuse_binding
    register_dispatch_binding_id
    record_reuse_binding
    get_reuse_binding
    get_reuse_binding_by_device
    list_eligible_reuse_bindings
    build_reuse_binding_snapshot
    get_reuse_binding_runtime
    reset_reuse_binding_runtime
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

ATTACHED_RUNTIME_REUSE_BINDING_AUTHORITY: str = (
    "ATTACHED_RUNTIME_REUSE_BINDING_AUTHORITY::"
    "core.attached_runtime_reuse_binding is the canonical authority for "
    "persistent attached-runtime reuse binding semantics on the main-repo "
    "side (PR package 14, post-533 dual-repo runtime unification).  All "
    "delegated-dispatch code that targets an attached Android runtime surface "
    "for reuse MUST query the canonical reuse binding rather than re-deriving "
    "targeting identity from scattered fields."
)

REUSE_BINDING_REQUIRES_ATTACHED_SESSION_POLICY: str = (
    "POLICY::REUSE_BINDING_REQUIRES_ATTACHED_SESSION: a reuse binding record "
    "MUST carry a non-empty session_id referencing a persistent attached "
    "runtime session established by PR-7.  Bindings without a session anchor "
    "are rejected and returned with ReuseEligibilityStatus.ineligible."
)

REUSE_BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY: str = (
    "POLICY::REUSE_BINDING_REQUIRES_JOIN_RUNTIME_POSTURE: only Android "
    "sessions whose source_runtime_posture is 'join_runtime' may serve as a "
    "reuse binding surface.  A binding for a 'control_only' session is "
    "rejected at establishment time and ineligible for reuse."
)

REUSE_BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY: str = (
    "POLICY::REUSE_BINDING_REQUIRES_TARGET_DEVICE_ID: a reuse binding record "
    "MUST carry a non-empty device_id identifying the target Android host.  "
    "A binding without a target device id is semantically invalid and will "
    "be rejected at establishment time."
)

REUSE_ELIGIBILITY_REQUIRES_ACTIVE_SESSION_POLICY: str = (
    "POLICY::REUSE_ELIGIBILITY_REQUIRES_ACTIVE_SESSION: a reuse binding is "
    "eligible for delegated dispatch reuse only when its "
    "reuse_eligibility_status is 'eligible' (i.e. the underlying attached "
    "session is active and has not been invalidated).  Callers MUST call "
    "evaluate_reuse_eligibility() or check is_eligible() before reusing a "
    "binding rather than assuming it remains valid across requests."
)

REUSE_BINDING_INVALIDATED_ON_DETACH_POLICY: str = (
    "POLICY::REUSE_BINDING_INVALIDATED_ON_DETACH: when a 'detach' lifecycle "
    "signal is received for an attached session (PR-7), the corresponding "
    "reuse binding MUST be immediately invalidated via invalidate_reuse_binding() "
    "so that subsequent dispatch eligibility checks observe the correct state "
    "without reading stale targeting context."
)

REUSE_BINDING_INVALIDATED_ON_DISCONNECT_POLICY: str = (
    "POLICY::REUSE_BINDING_INVALIDATED_ON_DISCONNECT: when a 'disconnect' "
    "lifecycle signal is received for an attached session (PR-7), the "
    "corresponding reuse binding MUST be immediately invalidated.  "
    "Unlike a suspended dispatch binding (PR-11), a disconnected reuse "
    "binding cannot be automatically resumed; a new binding must be "
    "established after reconnect."
)

REUSE_BINDING_INVALIDATED_ON_DISABLE_POLICY: str = (
    "POLICY::REUSE_BINDING_INVALIDATED_ON_DISABLE: when a 'disable' "
    "lifecycle signal is received for an attached session (PR-7), the "
    "corresponding reuse binding MUST be immediately invalidated so that "
    "the disabled device is not inadvertently targeted for delegated work."
)

REUSE_BINDING_DISPATCH_BINDING_ID_IS_LATEST_POLICY: str = (
    "POLICY::REUSE_BINDING_DISPATCH_BINDING_ID_IS_LATEST: the "
    "dispatch_binding_id field of an AttachedRuntimeReuseBindingRecord "
    "MUST always reference the binding_id of the most recently registered "
    "AndroidRuntimeDispatchBindingRecord for this reuse surface.  Callers "
    "use register_dispatch_binding_id() to update this field after each "
    "new dispatch binding is created."
)

REUSE_BINDING_IS_STABLE_TARGETING_SURFACE_POLICY: str = (
    "POLICY::REUSE_BINDING_IS_STABLE_TARGETING_SURFACE: the identity fields "
    "(session_id, device_id, android_host_role, capability_tier, "
    "coordination_role, source_runtime_posture) of an "
    "AttachedRuntimeReuseBindingRecord are immutable after establishment.  "
    "Dispatch and tracking flows MUST read targeting context from the reuse "
    "binding rather than re-deriving it from the attached session or "
    "capability scheduling records."
)

ATTACHED_RUNTIME_REUSE_BINDING_PR14_SENTINEL: str = (
    "ATTACHED_RUNTIME_REUSE_BINDING_PR14_SENTINEL::package=14 "
    "canonical-attached-runtime-reuse-binding-post-533-main-repo-pr14-v1"
)

_ALL_POLICY_SENTINELS = (
    ATTACHED_RUNTIME_REUSE_BINDING_AUTHORITY,
    REUSE_BINDING_REQUIRES_ATTACHED_SESSION_POLICY,
    REUSE_BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
    REUSE_BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY,
    REUSE_ELIGIBILITY_REQUIRES_ACTIVE_SESSION_POLICY,
    REUSE_BINDING_INVALIDATED_ON_DETACH_POLICY,
    REUSE_BINDING_INVALIDATED_ON_DISCONNECT_POLICY,
    REUSE_BINDING_INVALIDATED_ON_DISABLE_POLICY,
    REUSE_BINDING_DISPATCH_BINDING_ID_IS_LATEST_POLICY,
    REUSE_BINDING_IS_STABLE_TARGETING_SURFACE_POLICY,
)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_POSTURE_JOIN_RUNTIME: str = "join_runtime"
_POSTURE_CONTROL_ONLY: str = "control_only"
_RING_BUFFER_CAPACITY: int = 128

# Lifecycle signals that trigger immediate invalidation of a reuse binding.
# These mirror the terminal / connection-breaking signals from PR-7
# AttachmentLifecycleSignal.
_INVALIDATING_SIGNALS: frozenset = frozenset(
    {"detach", "disconnect", "disable", "invalidate"}
)

# ---------------------------------------------------------------------------
# ReuseEligibilityStatus
# ---------------------------------------------------------------------------


class ReuseEligibilityStatus(str, Enum):
    """Canonical eligibility states for persistent attached-runtime reuse.

    eligible
        The reuse binding is active and may be used as a stable dispatch
        targeting surface for delegated work without re-forming ad-hoc
        targeting.  The underlying attached session is ``attached`` and the
        posture is ``join_runtime``.
    ineligible
        The reuse binding cannot be used for dispatch reuse.  This includes
        newly-rejected bindings, bindings that have been invalidated by a
        detach/disconnect/disable/invalidate lifecycle signal, and bindings
        for sessions with non-``join_runtime`` posture.
    """

    eligible = "eligible"
    ineligible = "ineligible"

    @classmethod
    def from_string(
        cls,
        value: str,
        default: "ReuseEligibilityStatus" = None,
    ) -> "ReuseEligibilityStatus":
        """Return the enum member matching *value*, or *default* / ``ineligible``."""
        if default is None:
            default = cls.ineligible
        if not isinstance(value, str):
            return default
        try:
            return cls(value.lower().strip())
        except ValueError:
            return default


# ---------------------------------------------------------------------------
# ReuseInvalidationReason
# ---------------------------------------------------------------------------


class ReuseInvalidationReason(str, Enum):
    """Canonical reasons why a reuse binding was invalidated.

    detach
        The attached session received a ``detach`` lifecycle signal (PR-7).
    disconnect
        The attached session received a ``disconnect`` lifecycle signal (PR-7).
    disable
        The attached session received a ``disable`` lifecycle signal (PR-7).
    invalidate
        The attached session received an ``invalidate`` lifecycle signal (PR-7).
    bad_posture
        The session's ``source_runtime_posture`` is not ``join_runtime``;
        the binding is ineligible at establishment time.
    missing_session
        The ``session_id`` was empty at establishment time.
    missing_device
        The ``device_id`` was empty at establishment time.
    none
        The binding has not been invalidated.
    """

    detach = "detach"
    disconnect = "disconnect"
    disable = "disable"
    invalidate = "invalidate"
    bad_posture = "bad_posture"
    missing_session = "missing_session"
    missing_device = "missing_device"
    none = "none"

    @classmethod
    def from_string(
        cls,
        value: str,
        default: "ReuseInvalidationReason" = None,
    ) -> "ReuseInvalidationReason":
        """Return the enum member matching *value*, or *default* / ``none``."""
        if default is None:
            default = cls.none
        if not isinstance(value, str):
            return default
        try:
            return cls(value.lower().strip())
        except ValueError:
            return default

    def is_lifecycle_invalidation(self) -> bool:
        """Return True if the reason stems from an attachment lifecycle signal."""
        return self in (
            ReuseInvalidationReason.detach,
            ReuseInvalidationReason.disconnect,
            ReuseInvalidationReason.disable,
            ReuseInvalidationReason.invalidate,
        )


# ---------------------------------------------------------------------------
# AttachedRuntimeReuseBindingIdentity
# ---------------------------------------------------------------------------


@dataclass
class AttachedRuntimeReuseBindingIdentity:
    """Stable, serialisable identity record for a persistent reuse binding.

    All identity fields are set at establishment time and preserved unchanged
    across the lifetime of the reuse binding.  Later dispatch flows MUST read
    targeting context from this identity rather than re-deriving it.

    Attributes
    ----------
    reuse_binding_id
        Unique, stable identifier for this reuse binding instance.
        Auto-generated UUID if not provided.
    session_id
        Attached-runtime session id from PR-7.  Must be non-empty.
    device_id
        Identifier of the target Android device / runtime host.  Must be
        non-empty.
    trace_id
        Distributed trace id propagated from the originating attach
        operation or request.  Auto-generated UUID if not provided.
    """

    session_id: str
    device_id: str
    reuse_binding_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "reuse_binding_id": self.reuse_binding_id,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "trace_id": self.trace_id,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(
        cls, data: Dict[str, Any]
    ) -> "AttachedRuntimeReuseBindingIdentity":
        """Construct from a dict.  Raises ValueError if *data* is not a dict."""
        if not isinstance(data, dict):
            raise ValueError(
                "AttachedRuntimeReuseBindingIdentity.from_dict expects a dict"
            )
        return cls(
            reuse_binding_id=data.get("reuse_binding_id") or str(uuid.uuid4()),
            session_id=data.get("session_id", ""),
            device_id=data.get("device_id", ""),
            trace_id=data.get("trace_id") or str(uuid.uuid4()),
        )


# ---------------------------------------------------------------------------
# AttachedRuntimeReuseBindingRecord
# ---------------------------------------------------------------------------


@dataclass
class AttachedRuntimeReuseBindingRecord:
    """Canonical record for one persistent attached-runtime reuse binding.

    This record is the MAIN-side single authoritative answer to the question
    *"is this attached Android runtime session eligible for reuse as a stable
    delegated-dispatch surface, and what are its canonical targeting
    identifiers?"*.

    Attributes
    ----------
    identity
        The canonical reuse binding identity (reuse_binding_id, session_id,
        device_id, trace_id).
    reuse_eligibility_status
        Current eligibility status (``eligible`` / ``ineligible``).
    invalidation_reason
        The reason the binding was invalidated, or ``none`` if still eligible.
    source_runtime_posture
        Source device's participation posture; must be ``join_runtime`` for an
        eligible binding.
    coordination_role
        Coordination role (from PR-538 / PR-6).
    android_host_role
        Android runtime host role classification string (from PR-5).
    capability_tier
        Capability tier string (from PR-6).
    dispatch_binding_id
        The binding_id of the most recently registered
        AndroidRuntimeDispatchBindingRecord (PR-11) for this reuse surface.
        Updated via :func:`register_dispatch_binding_id`; empty string when no
        dispatch binding has yet been registered.
    is_session_anchored
        True if ``identity.session_id`` is non-empty.
    is_device_bound
        True if ``identity.device_id`` is non-empty.
    established_at
        Unix timestamp when the reuse binding was established.
    invalidated_at
        Unix timestamp when the binding was invalidated, or ``None``.
    metadata
        Optional freeform dict for caller-specific context.
    """

    identity: AttachedRuntimeReuseBindingIdentity
    reuse_eligibility_status: ReuseEligibilityStatus = ReuseEligibilityStatus.ineligible
    invalidation_reason: ReuseInvalidationReason = ReuseInvalidationReason.none
    source_runtime_posture: str = _POSTURE_JOIN_RUNTIME
    coordination_role: str = ""
    android_host_role: str = ""
    capability_tier: str = ""
    dispatch_binding_id: str = ""
    is_session_anchored: bool = False
    is_device_bound: bool = False
    established_at: float = field(default_factory=time.time)
    invalidated_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    def is_eligible(self) -> bool:
        """Return True if the binding is currently eligible for reuse."""
        return self.reuse_eligibility_status == ReuseEligibilityStatus.eligible

    def is_invalidated(self) -> bool:
        """Return True if the binding has been invalidated."""
        return self.reuse_eligibility_status == ReuseEligibilityStatus.ineligible

    def has_dispatch_binding(self) -> bool:
        """Return True if a dispatch binding id has been registered."""
        return bool(self.dispatch_binding_id)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "identity": self.identity.to_dict(),
            "reuse_eligibility_status": self.reuse_eligibility_status.value,
            "invalidation_reason": self.invalidation_reason.value,
            "source_runtime_posture": self.source_runtime_posture,
            "coordination_role": self.coordination_role,
            "android_host_role": self.android_host_role,
            "capability_tier": self.capability_tier,
            "dispatch_binding_id": self.dispatch_binding_id,
            "is_session_anchored": self.is_session_anchored,
            "is_device_bound": self.is_device_bound,
            "established_at": self.established_at,
            "invalidated_at": self.invalidated_at,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# AttachedRuntimeReuseBindingSnapshot
# ---------------------------------------------------------------------------


@dataclass
class AttachedRuntimeReuseBindingSnapshot:
    """Point-in-time snapshot of all reuse binding records in the ring-buffer.

    Attributes
    ----------
    records
        All binding records captured at snapshot time (newest-first).
    eligible_count
        Number of records with ``eligible`` status at snapshot time.
    ineligible_count
        Number of records with ``ineligible`` status at snapshot time.
    snapshot_at
        Unix timestamp when this snapshot was assembled.
    """

    records: List[AttachedRuntimeReuseBindingRecord] = field(default_factory=list)
    eligible_count: int = 0
    ineligible_count: int = 0
    snapshot_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "records": [r.to_dict() for r in self.records],
            "eligible_count": self.eligible_count,
            "ineligible_count": self.ineligible_count,
            "snapshot_at": self.snapshot_at,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# AttachedRuntimeReuseBindingRuntime  (ring-buffer singleton)
# ---------------------------------------------------------------------------


class AttachedRuntimeReuseBindingRuntime:
    """In-process ring-buffer accumulating reuse binding records.

    Capacity is fixed at 128 entries; oldest records are evicted when the
    buffer is full.  Multiple records for the same ``session_id`` or
    ``device_id`` are permitted; lookup functions return the most recent one.

    Parameters
    ----------
    capacity
        Maximum number of records to retain.  Defaults to 128.
    """

    def __init__(self, capacity: int = _RING_BUFFER_CAPACITY) -> None:
        self._capacity = capacity
        self._buf: Deque[AttachedRuntimeReuseBindingRecord] = deque(
            maxlen=capacity
        )

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def push(self, record: AttachedRuntimeReuseBindingRecord) -> None:
        """Append *record* to the ring-buffer, evicting the oldest if full."""
        self._buf.append(record)

    def clear(self) -> None:
        """Remove all records from the ring-buffer."""
        self._buf.clear()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_all(self) -> List[AttachedRuntimeReuseBindingRecord]:
        """Return all records, newest-first."""
        return list(reversed(self._buf))

    def list_eligible(self) -> List[AttachedRuntimeReuseBindingRecord]:
        """Return all eligible records, newest-first."""
        return [
            r
            for r in reversed(self._buf)
            if r.reuse_eligibility_status == ReuseEligibilityStatus.eligible
        ]

    def get_latest_for_session(
        self, session_id: str
    ) -> Optional[AttachedRuntimeReuseBindingRecord]:
        """Return the most recent record for *session_id*, or ``None``."""
        for record in reversed(self._buf):
            if record.identity.session_id == session_id:
                return record
        return None

    def get_latest_for_device(
        self, device_id: str
    ) -> Optional[AttachedRuntimeReuseBindingRecord]:
        """Return the most recent record for *device_id*, or ``None``."""
        for record in reversed(self._buf):
            if record.identity.device_id == device_id:
                return record
        return None

    def size(self) -> int:
        """Return the current number of records in the ring-buffer."""
        return len(self._buf)

    @property
    def capacity(self) -> int:
        """Return the ring-buffer capacity."""
        return self._capacity


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_singleton: Optional[AttachedRuntimeReuseBindingRuntime] = None


def get_reuse_binding_runtime() -> AttachedRuntimeReuseBindingRuntime:
    """Return the process-level ring-buffer singleton, creating it if needed."""
    global _singleton
    if _singleton is None:
        _singleton = AttachedRuntimeReuseBindingRuntime()
    return _singleton


def reset_reuse_binding_runtime() -> None:
    """Replace the singleton with a fresh ring-buffer (test-isolation helper)."""
    global _singleton
    _singleton = AttachedRuntimeReuseBindingRuntime()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_ineligible_binding(
    *,
    session_id: str,
    device_id: str,
    reuse_binding_id: Optional[str],
    trace_id: Optional[str],
    source_runtime_posture: str,
    coordination_role: str,
    android_host_role: str,
    capability_tier: str,
    invalidation_reason: ReuseInvalidationReason,
    runtime: AttachedRuntimeReuseBindingRuntime,
    metadata: Optional[Dict[str, Any]],
) -> AttachedRuntimeReuseBindingRecord:
    """Construct, persist, and return an ineligible reuse binding record."""
    _bid = reuse_binding_id or str(uuid.uuid4())
    _tid = trace_id or str(uuid.uuid4())

    identity = AttachedRuntimeReuseBindingIdentity(
        reuse_binding_id=_bid,
        session_id=session_id,
        device_id=device_id,
        trace_id=_tid,
    )
    record = AttachedRuntimeReuseBindingRecord(
        identity=identity,
        reuse_eligibility_status=ReuseEligibilityStatus.ineligible,
        invalidation_reason=invalidation_reason,
        source_runtime_posture=source_runtime_posture or _POSTURE_CONTROL_ONLY,
        coordination_role=coordination_role,
        android_host_role=android_host_role,
        capability_tier=capability_tier,
        dispatch_binding_id="",
        is_session_anchored=bool(session_id),
        is_device_bound=bool(device_id),
        metadata=metadata if metadata is not None else {},
    )
    runtime.push(record)
    return record


# ---------------------------------------------------------------------------
# Public API — establish / evaluate / invalidate / register
# ---------------------------------------------------------------------------


def establish_reuse_binding(
    *,
    session_id: str,
    device_id: str,
    source_runtime_posture: str = _POSTURE_JOIN_RUNTIME,
    coordination_role: str = "",
    android_host_role: str = "",
    capability_tier: str = "",
    reuse_binding_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
) -> AttachedRuntimeReuseBindingRecord:
    """Establish a canonical persistent attached-runtime reuse binding.

    Creates a new :class:`AttachedRuntimeReuseBindingRecord`, persists it to
    the ring-buffer singleton (or *runtime* if provided), and returns it.

    Validation
    ----------
    * ``session_id`` must be non-empty
      (per :data:`REUSE_BINDING_REQUIRES_ATTACHED_SESSION_POLICY`).
    * ``device_id`` must be non-empty
      (per :data:`REUSE_BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY`).
    * ``source_runtime_posture`` must be ``"join_runtime"``
      (per :data:`REUSE_BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY`).

    Parameters
    ----------
    session_id
        Attached-runtime session id from PR-7.
    device_id
        Target Android device / host id.
    source_runtime_posture
        Participation posture; must be ``"join_runtime"`` for an eligible
        binding.  Defaults to ``"join_runtime"``.
    coordination_role
        Coordination role string (PR-538 / PR-6).
    android_host_role
        Android host role string (PR-5).
    capability_tier
        Capability tier string (PR-6).
    reuse_binding_id
        Override the auto-generated UUID binding id.
    trace_id
        Distributed trace id; auto-generated if absent.
    metadata
        Optional freeform dict.
    runtime
        Override the process-level singleton (test isolation).

    Returns
    -------
    AttachedRuntimeReuseBindingRecord
        An eligible record if all validations pass; an ineligible record with
        a populated ``invalidation_reason`` otherwise.
    """
    _runtime = runtime if runtime is not None else get_reuse_binding_runtime()
    _posture = (source_runtime_posture or "").strip() or _POSTURE_JOIN_RUNTIME

    # --- session_id required ---
    if not session_id:
        return _make_ineligible_binding(
            session_id=session_id,
            device_id=device_id,
            reuse_binding_id=reuse_binding_id,
            trace_id=trace_id,
            source_runtime_posture=_posture,
            coordination_role=coordination_role,
            android_host_role=android_host_role,
            capability_tier=capability_tier,
            invalidation_reason=ReuseInvalidationReason.missing_session,
            runtime=_runtime,
            metadata=metadata,
        )

    # --- device_id required ---
    if not device_id:
        return _make_ineligible_binding(
            session_id=session_id,
            device_id=device_id,
            reuse_binding_id=reuse_binding_id,
            trace_id=trace_id,
            source_runtime_posture=_posture,
            coordination_role=coordination_role,
            android_host_role=android_host_role,
            capability_tier=capability_tier,
            invalidation_reason=ReuseInvalidationReason.missing_device,
            runtime=_runtime,
            metadata=metadata,
        )

    # --- posture must be join_runtime ---
    if _posture != _POSTURE_JOIN_RUNTIME:
        return _make_ineligible_binding(
            session_id=session_id,
            device_id=device_id,
            reuse_binding_id=reuse_binding_id,
            trace_id=trace_id,
            source_runtime_posture=_posture,
            coordination_role=coordination_role,
            android_host_role=android_host_role,
            capability_tier=capability_tier,
            invalidation_reason=ReuseInvalidationReason.bad_posture,
            runtime=_runtime,
            metadata=metadata,
        )

    # --- all validations passed: create eligible binding ---
    _bid = reuse_binding_id or str(uuid.uuid4())
    _tid = trace_id or str(uuid.uuid4())

    identity = AttachedRuntimeReuseBindingIdentity(
        reuse_binding_id=_bid,
        session_id=session_id,
        device_id=device_id,
        trace_id=_tid,
    )
    record = AttachedRuntimeReuseBindingRecord(
        identity=identity,
        reuse_eligibility_status=ReuseEligibilityStatus.eligible,
        invalidation_reason=ReuseInvalidationReason.none,
        source_runtime_posture=_posture,
        coordination_role=coordination_role,
        android_host_role=android_host_role,
        capability_tier=capability_tier,
        dispatch_binding_id="",
        is_session_anchored=True,
        is_device_bound=True,
        metadata=metadata if metadata is not None else {},
    )
    _runtime.push(record)
    return record


def evaluate_reuse_eligibility(
    record: AttachedRuntimeReuseBindingRecord,
    *,
    attached_session: Any = None,
) -> ReuseEligibilityStatus:
    """Evaluate and return the current reuse eligibility for *record*.

    This is the canonical eligibility gate
    (per :data:`REUSE_ELIGIBILITY_REQUIRES_ACTIVE_SESSION_POLICY`).

    Rules
    -----
    1. If the record's ``reuse_eligibility_status`` is already ``ineligible``
       (e.g. previously invalidated), return ``ineligible`` immediately.
    2. If *attached_session* is provided, re-verify that it is active and has
       ``join_runtime`` posture.  If either check fails, return ``ineligible``.
    3. Otherwise return ``eligible``.

    Parameters
    ----------
    record
        The reuse binding record to evaluate.
    attached_session
        Optional live attached-session record (PR-7) to cross-check against.
        When provided, eligibility is re-validated against the session's
        current ``attachment_state`` and ``source_runtime_posture``.

    Returns
    -------
    ReuseEligibilityStatus
    """
    # Fast-path: already invalidated.
    if record.reuse_eligibility_status == ReuseEligibilityStatus.ineligible:
        return ReuseEligibilityStatus.ineligible

    # Cross-check live attached session when provided.
    if attached_session is not None:
        session_state = getattr(attached_session, "attachment_state", None)
        session_posture = getattr(attached_session, "source_runtime_posture", None)

        # PR-7 AttachmentState.attached == "attached"
        state_value = (
            session_state.value
            if hasattr(session_state, "value")
            else str(session_state or "")
        )
        if state_value != "attached":
            return ReuseEligibilityStatus.ineligible

        posture_value = (session_posture or "").strip()
        if posture_value != _POSTURE_JOIN_RUNTIME:
            return ReuseEligibilityStatus.ineligible

    return ReuseEligibilityStatus.eligible


def invalidate_reuse_binding(
    record: AttachedRuntimeReuseBindingRecord,
    *,
    lifecycle_signal: str = "detach",
    runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
) -> AttachedRuntimeReuseBindingRecord:
    """Invalidate *record* due to an attachment lifecycle signal.

    Produces and persists a new :class:`AttachedRuntimeReuseBindingRecord`
    with ``reuse_eligibility_status == ineligible`` and
    ``invalidated_at`` set to the current time.  The original record in the
    ring-buffer is not modified (records are immutable once appended);
    a new record is appended instead.

    Parameters
    ----------
    record
        The existing reuse binding record to invalidate.
    lifecycle_signal
        The attachment lifecycle signal that triggered invalidation; must be
        one of ``"detach"``, ``"disconnect"``, ``"disable"``,
        ``"invalidate"`` (or any string — unknown signals are mapped to
        ``detach`` as a safe default).
    runtime
        Override the process-level singleton (test isolation).

    Returns
    -------
    AttachedRuntimeReuseBindingRecord
        A new record (distinct object) with ``ineligible`` status, already
        persisted to the ring-buffer.
    """
    _runtime = runtime if runtime is not None else get_reuse_binding_runtime()

    _signal = (lifecycle_signal or "").lower().strip()
    if _signal in _INVALIDATING_SIGNALS:
        reason = ReuseInvalidationReason.from_string(_signal)
    else:
        reason = ReuseInvalidationReason.detach  # safe default

    invalidated = AttachedRuntimeReuseBindingRecord(
        identity=record.identity,
        reuse_eligibility_status=ReuseEligibilityStatus.ineligible,
        invalidation_reason=reason,
        source_runtime_posture=record.source_runtime_posture,
        coordination_role=record.coordination_role,
        android_host_role=record.android_host_role,
        capability_tier=record.capability_tier,
        dispatch_binding_id=record.dispatch_binding_id,
        is_session_anchored=record.is_session_anchored,
        is_device_bound=record.is_device_bound,
        established_at=record.established_at,
        invalidated_at=time.time(),
        metadata=dict(record.metadata),
    )
    _runtime.push(invalidated)
    return invalidated


def register_dispatch_binding_id(
    record: AttachedRuntimeReuseBindingRecord,
    dispatch_binding_id: str,
    *,
    runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
) -> AttachedRuntimeReuseBindingRecord:
    """Return a new record with *dispatch_binding_id* updated.

    Per :data:`REUSE_BINDING_DISPATCH_BINDING_ID_IS_LATEST_POLICY`, the
    ``dispatch_binding_id`` field MUST always reference the most recently
    established :class:`AndroidRuntimeDispatchBindingRecord` binding_id.

    This function produces and persists an updated copy of *record* with the
    new ``dispatch_binding_id``.  The original record in the ring-buffer is
    not modified.

    Parameters
    ----------
    record
        The existing reuse binding record to update.
    dispatch_binding_id
        The ``binding_id`` of the newly created
        :class:`AndroidRuntimeDispatchBindingRecord`.
    runtime
        Override the process-level singleton (test isolation).

    Returns
    -------
    AttachedRuntimeReuseBindingRecord
        An updated record (distinct object) already persisted to the ring-buffer.
    """
    _runtime = runtime if runtime is not None else get_reuse_binding_runtime()

    updated = AttachedRuntimeReuseBindingRecord(
        identity=record.identity,
        reuse_eligibility_status=record.reuse_eligibility_status,
        invalidation_reason=record.invalidation_reason,
        source_runtime_posture=record.source_runtime_posture,
        coordination_role=record.coordination_role,
        android_host_role=record.android_host_role,
        capability_tier=record.capability_tier,
        dispatch_binding_id=dispatch_binding_id,
        is_session_anchored=record.is_session_anchored,
        is_device_bound=record.is_device_bound,
        established_at=record.established_at,
        invalidated_at=record.invalidated_at,
        metadata=dict(record.metadata),
    )
    _runtime.push(updated)
    return updated


# ---------------------------------------------------------------------------
# Ring-buffer persistence helpers
# ---------------------------------------------------------------------------


def record_reuse_binding(
    record: AttachedRuntimeReuseBindingRecord,
    *,
    runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
) -> None:
    """Persist *record* to the ring-buffer singleton.

    Callers that construct records directly (rather than via
    :func:`establish_reuse_binding`) MUST call this function to ensure the
    record is visible to lookup functions.
    """
    _runtime = runtime if runtime is not None else get_reuse_binding_runtime()
    _runtime.push(record)


def get_reuse_binding(
    session_id: str,
    *,
    runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
) -> Optional[AttachedRuntimeReuseBindingRecord]:
    """Retrieve the most recent reuse binding record for *session_id*.

    Returns ``None`` if no record exists for the given ``session_id``.
    """
    _runtime = runtime if runtime is not None else get_reuse_binding_runtime()
    return _runtime.get_latest_for_session(session_id)


def get_reuse_binding_by_device(
    device_id: str,
    *,
    runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
) -> Optional[AttachedRuntimeReuseBindingRecord]:
    """Retrieve the most recent reuse binding record for *device_id*.

    Returns ``None`` if no record exists for the given ``device_id``.
    """
    _runtime = runtime if runtime is not None else get_reuse_binding_runtime()
    return _runtime.get_latest_for_device(device_id)


def list_eligible_reuse_bindings(
    *,
    runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
) -> List[AttachedRuntimeReuseBindingRecord]:
    """Return all reuse binding records with ``eligible`` status, newest-first."""
    _runtime = runtime if runtime is not None else get_reuse_binding_runtime()
    return _runtime.list_eligible()


def build_reuse_binding_snapshot(
    *,
    runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
) -> AttachedRuntimeReuseBindingSnapshot:
    """Assemble a point-in-time snapshot from the ring-buffer.

    Parameters
    ----------
    runtime
        Override the process-level singleton (test isolation).

    Returns
    -------
    AttachedRuntimeReuseBindingSnapshot
    """
    _runtime = runtime if runtime is not None else get_reuse_binding_runtime()
    all_records = _runtime.list_all()
    eligible = sum(
        1
        for r in all_records
        if r.reuse_eligibility_status == ReuseEligibilityStatus.eligible
    )
    return AttachedRuntimeReuseBindingSnapshot(
        records=all_records,
        eligible_count=eligible,
        ineligible_count=len(all_records) - eligible,
    )
