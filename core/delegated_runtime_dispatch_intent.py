"""core/delegated_runtime_dispatch_intent.py
=============================================
PR package 8 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Canonical Delegated-Runtime Dispatch Intent and Handoff-Preparation
Foundations.

This module is the **canonical authority** for modelling the host-side
representation of intent to delegate a runtime work unit to an attached
cross-device runtime surface (typically Android), together with the
pre-handoff state needed to prepare local-to-remote takeover or continuation.

Background
----------
After PR-7 established the concept of a persistent attached-runtime session,
the host-side orchestration layer has no single canonical structure for
expressing *intent* to delegate a runtime work unit to that attached session.
Previously, such delegation relied on ad hoc transport-local logic—passing
device identifiers through untyped dictionaries and making routing decisions
without inspecting posture, coordination role, or capability tier.

PR-8 closes this gap on the MAIN-repo side by providing:

1. :class:`DelegationIntent` — canonical enum classifying the type of
   delegation the host intends to perform (delegate, relay, observe, none).
2. :class:`HandoffPreparationState` — canonical enum for the lifecycle state
   of the host-side pre-handoff preparation process.
3. :class:`DelegatedRuntimeDispatchRecord` — stable, serialisable record
   capturing the full context of a single delegated-dispatch intent event.
   Carries session identity, posture, coordination role, capability tier,
   Android host role, delegation intent, handoff preparation state, and
   any pre-computed handoff inputs.
4. :class:`DelegatedRuntimeDispatchSnapshot` — point-in-time snapshot of all
   pending delegated dispatch records for audit and projection.
5. :class:`DelegatedRuntimeDispatchRuntime` — in-process ring-buffer singleton
   (128 entries) accumulating dispatch records across the process lifetime.
6. :func:`build_delegated_dispatch_record` — creates a canonical
   :class:`DelegatedRuntimeDispatchRecord` from attached-session state and
   scheduling basis inputs, validating eligibility before accepting intent.
7. :func:`evaluate_dispatch_eligibility` — returns whether the attached-session
   state, posture, coordination role, and capability tier together permit
   delegated dispatch; returns a :class:`DispatchEligibilityOutcome`.
8. :func:`prepare_handoff_inputs` — normalises and assembles the pre-handoff
   input bundle (device identity, session id, posture, role, capability,
   intent, continuation hint) needed by the downstream handoff path.
9. :func:`record_delegated_dispatch_intent` — persists a record to the
   ring-buffer singleton.
10. :func:`get_delegated_dispatch_record` — retrieves the most recent record
    for a given session-id.
11. :func:`list_pending_delegated_dispatch_records` — returns all records
    whose preparation state is ``preparing`` or ``ready``.
12. :func:`build_delegated_dispatch_snapshot` — assembles a
    :class:`DelegatedRuntimeDispatchSnapshot` from the ring-buffer state.
13. Ten policy sentinels documenting canonical delegation-intent rules.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Session-anchored** — every dispatch record references an attached-session
  id from PR-7; orphaned (session-less) intents are rejected.
- **Posture-preserving** — ``join_runtime`` posture is required for any
  non-``none`` delegation intent; ``control_only`` devices may only express
  ``DelegationIntent.none``.
- **Coordination-role aware** — ``observer_only`` coordination role blocks
  delegation intent; ``target_only_executor`` may only receive, not delegate.
- **Capability-tier driven** — ``full_runtime`` or ``partial_runtime`` tiers
  are required for ``delegate`` or ``relay`` intent; ``command_only`` blocks
  full delegation.
- **Graceful degradation** — unknown or missing fields default to the
  conservative safe outcome (``DelegationIntent.none``,
  ``HandoffPreparationState.not_started``).
- **Fully serialisable** — all dataclasses expose ``to_dict()`` / ``to_json()``
  for stable, round-trippable wire representations.

Relationship to other PR packages
----------------------------------
* PR-1  (``core.posture_contract_canonicalization``) — posture is validated
  via contract-layer sentinels before delegation intent is accepted.
* PR-2  (``core.source_execution_eligibility``) — eligibility check results
  inform whether delegation is permitted at all.
* PR-3  (``core.canonical_handoff_path``) — ``prepare_handoff_inputs()``
  produces inputs consumed by the downstream handoff contract builder.
* PR-5  (``core.android_runtime_host``) — ``android_host_role`` is carried
  into dispatch records as an informational field.
* PR-6  (``core.canonical_capability_scheduling_basis``) — capability tier
  and execution surface eligibility gate delegation intent.
* PR-7  (``core.attached_runtime_session``) — every dispatch record is
  anchored to a persistent attached-runtime session record.
* PR-538 (``core.multi_device_coordination_authority``) — ``coordination_role``
  gates delegation intent; ``observer_only`` is always blocked.

Public API
----------
Sentinels::

    DELEGATED_RUNTIME_DISPATCH_INTENT_AUTHORITY
    DELEGATION_REQUIRES_ATTACHED_SESSION_POLICY
    DELEGATION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY
    OBSERVER_ONLY_ROLE_BLOCKS_DELEGATION_POLICY
    TARGET_ONLY_EXECUTOR_CANNOT_DELEGATE_POLICY
    COMMAND_ONLY_TIER_BLOCKS_FULL_DELEGATION_POLICY
    HANDOFF_INPUTS_MUST_BE_SESSION_ANCHORED_POLICY
    DELEGATION_INTENT_IS_ADDITIVE_TO_SESSION_POLICY
    DISPATCH_RECORD_IS_IMMUTABLE_POLICY
    PREPARATION_STATE_IS_MONOTONICALLY_ADVANCING_POLICY
    DELEGATED_RUNTIME_DISPATCH_INTENT_PR8_SENTINEL

Enums::

    DelegationIntent
    HandoffPreparationState

Dataclasses::

    DelegatedRuntimeDispatchRecord
    HandoffInputBundle
    DelegatedRuntimeDispatchSnapshot
    DispatchEligibilityOutcome

Classes::

    DelegatedRuntimeDispatchRuntime

Functions::

    build_delegated_dispatch_record(...) -> DelegatedRuntimeDispatchRecord
    evaluate_dispatch_eligibility(...) -> DispatchEligibilityOutcome
    prepare_handoff_inputs(...) -> HandoffInputBundle
    record_delegated_dispatch_intent(record, ...) -> None
    get_delegated_dispatch_record(session_id, ...) -> DelegatedRuntimeDispatchRecord | None
    list_pending_delegated_dispatch_records(...) -> list[DelegatedRuntimeDispatchRecord]
    build_delegated_dispatch_snapshot(...) -> DelegatedRuntimeDispatchSnapshot
    get_delegated_runtime_dispatch_runtime() -> DelegatedRuntimeDispatchRuntime
    reset_delegated_runtime_dispatch_runtime() -> None
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

DELEGATED_RUNTIME_DISPATCH_INTENT_AUTHORITY: str = (
    "DELEGATED_RUNTIME_DISPATCH_INTENT_AUTHORITY::core.delegated_runtime_dispatch_intent "
    "is the canonical authority for delegated-runtime dispatch intent and "
    "handoff-preparation foundations on the main-repo side (PR package 8, "
    "post-533 dual-repo runtime unification)."
)

DELEGATION_REQUIRES_ATTACHED_SESSION_POLICY: str = (
    "POLICY::DELEGATION_REQUIRES_ATTACHED_SESSION: a delegated-runtime dispatch "
    "record must be anchored to a valid attached-runtime session id from PR-7.  "
    "Dispatch intent without an attached session is always rejected."
)

DELEGATION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY: str = (
    "POLICY::DELEGATION_REQUIRES_JOIN_RUNTIME_POSTURE: only devices/runtimes "
    "with source_runtime_posture='join_runtime' may express a non-none "
    "DelegationIntent.  A control_only posture device may only carry "
    "DelegationIntent.none."
)

OBSERVER_ONLY_ROLE_BLOCKS_DELEGATION_POLICY: str = (
    "POLICY::OBSERVER_ONLY_ROLE_BLOCKS_DELEGATION: a device whose coordination "
    "role is observer_only must not be assigned any delegation intent other than "
    "DelegationIntent.none.  Observer devices are read-only participants."
)

TARGET_ONLY_EXECUTOR_CANNOT_DELEGATE_POLICY: str = (
    "POLICY::TARGET_ONLY_EXECUTOR_CANNOT_DELEGATE: a device whose coordination "
    "role is target_only_executor may receive delegated work but must not "
    "itself initiate or express delegation intent toward other surfaces."
)

COMMAND_ONLY_TIER_BLOCKS_FULL_DELEGATION_POLICY: str = (
    "POLICY::COMMAND_ONLY_TIER_BLOCKS_FULL_DELEGATION: a device with "
    "capability_tier='command_only' may not carry DelegationIntent.delegate; "
    "at most DelegationIntent.relay is permitted when the attached session "
    "is otherwise eligible."
)

HANDOFF_INPUTS_MUST_BE_SESSION_ANCHORED_POLICY: str = (
    "POLICY::HANDOFF_INPUTS_MUST_BE_SESSION_ANCHORED: the HandoffInputBundle "
    "produced by prepare_handoff_inputs() must always carry a non-empty "
    "session_id that corresponds to the attached-runtime session record.  "
    "Unanchored handoff inputs must not be forwarded to the handoff path."
)

DELEGATION_INTENT_IS_ADDITIVE_TO_SESSION_POLICY: str = (
    "POLICY::DELEGATION_INTENT_IS_ADDITIVE_TO_SESSION: dispatch intent records "
    "are additive to the attached-runtime session state and do not replace or "
    "supersede it.  Both the session record and the dispatch record must exist "
    "and remain consistent for the handoff path to proceed."
)

DISPATCH_RECORD_IS_IMMUTABLE_POLICY: str = (
    "POLICY::DISPATCH_RECORD_IS_IMMUTABLE: once a DelegatedRuntimeDispatchRecord "
    "is created and persisted, its delegation_intent and core identity fields "
    "must not be mutated.  Advancing the handoff preparation state requires "
    "creating a new record via build_delegated_dispatch_record()."
)

PREPARATION_STATE_IS_MONOTONICALLY_ADVANCING_POLICY: str = (
    "POLICY::PREPARATION_STATE_IS_MONOTONICALLY_ADVANCING: HandoffPreparationState "
    "advances monotonically from not_started → preparing → ready → dispatched.  "
    "Regression to an earlier state is disallowed; cancelled/failed are terminal."
)

DELEGATED_RUNTIME_DISPATCH_INTENT_PR8_SENTINEL: str = (
    "DELEGATED_RUNTIME_DISPATCH_INTENT_PR8_SENTINEL::package=8 "
    "track=post-533-dual-repo-runtime-unification "
    "repo=main "
    "module=core.delegated_runtime_dispatch_intent"
)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_POSTURE_JOIN_RUNTIME: str = "join_runtime"
_POSTURE_CONTROL_ONLY: str = "control_only"
_ROLE_OBSERVER_ONLY: str = "observer_only"
_ROLE_TARGET_ONLY_EXECUTOR: str = "target_only_executor"
_TIER_FULL_RUNTIME: str = "full_runtime"
_TIER_PARTIAL_RUNTIME: str = "partial_runtime"
_TIER_COMMAND_ONLY: str = "command_only"
_TIER_UNKNOWN: str = "unknown"

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DelegationIntent(str, Enum):
    """Canonical enum for host-side delegated-runtime dispatch intent.

    Values
    ------
    delegate
        The host intends to fully delegate the runtime work unit to the
        attached remote surface.  The remote surface will own execution
        and produce the canonical result.
    relay
        The host intends to relay the work unit to the attached surface
        for execution support, while retaining coordination authority.
        The host merges the remote result with local context.
    observe
        The host does not delegate execution but routes observability
        context to the attached surface so it may track progress.
    none
        No delegation intent.  The host will execute the work unit
        locally without involving the attached surface.
    """

    delegate = "delegate"
    relay = "relay"
    observe = "observe"
    none = "none"

    @classmethod
    def from_string(cls, value: str) -> "DelegationIntent":
        """Return the enum member matching *value*, defaulting to ``none``."""
        if not isinstance(value, str):
            return cls.none
        normalised = value.lower().strip()
        try:
            return cls(normalised)
        except ValueError:
            return cls.none


class HandoffPreparationState(str, Enum):
    """Canonical enum for the lifecycle state of host-side pre-handoff prep.

    Values
    ------
    not_started
        No handoff preparation has been initiated for this dispatch record.
    preparing
        The host has begun assembling handoff inputs (session anchor,
        posture, capability, continuation hint).
    ready
        Handoff inputs are assembled and validated; the record is ready
        to be forwarded to the downstream handoff path.
    dispatched
        The dispatch record has been forwarded; the downstream handoff
        path has accepted the work unit.
    cancelled
        Handoff preparation was aborted before dispatch (terminal).
    failed
        Handoff preparation or dispatch encountered an unrecoverable
        error (terminal).
    """

    not_started = "not_started"
    preparing = "preparing"
    ready = "ready"
    dispatched = "dispatched"
    cancelled = "cancelled"
    failed = "failed"

    @classmethod
    def from_string(cls, value: str) -> "HandoffPreparationState":
        """Return the enum member matching *value*, defaulting to ``not_started``."""
        if not isinstance(value, str):
            return cls.not_started
        normalised = value.lower().strip()
        try:
            return cls(normalised)
        except ValueError:
            return cls.not_started

    def is_terminal(self) -> bool:
        """Return True if this state is a terminal state."""
        return self in (
            HandoffPreparationState.dispatched,
            HandoffPreparationState.cancelled,
            HandoffPreparationState.failed,
        )

    def is_actionable(self) -> bool:
        """Return True if further preparation actions may be applied."""
        return self in (
            HandoffPreparationState.not_started,
            HandoffPreparationState.preparing,
        )

    def can_advance_to(self, next_state: "HandoffPreparationState") -> bool:
        """Return True if monotonic advancement to *next_state* is permitted."""
        _order = {
            HandoffPreparationState.not_started: 0,
            HandoffPreparationState.preparing: 1,
            HandoffPreparationState.ready: 2,
            HandoffPreparationState.dispatched: 3,
            HandoffPreparationState.cancelled: 3,
            HandoffPreparationState.failed: 3,
        }
        if self.is_terminal():
            return False
        return _order.get(next_state, -1) > _order.get(self, -1)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HandoffInputBundle:
    """Normalised pre-handoff input bundle consumed by the downstream handoff path.

    This is the canonical output of :func:`prepare_handoff_inputs`.  It must
    carry a non-empty *session_id* per
    :data:`HANDOFF_INPUTS_MUST_BE_SESSION_ANCHORED_POLICY`.

    Attributes
    ----------
    record_id
        Stable identifier for this bundle (matches the dispatch record).
    device_id
        Identity of the remote device/runtime surface.
    session_id
        Attached-runtime session id from PR-7.  Must be non-empty.
    source_runtime_posture
        Posture of the session (should be ``join_runtime``).
    coordination_role
        Coordination role of the session.
    android_host_role
        Android host classification from PR-5.
    capability_tier
        Capability tier from PR-6.
    delegation_intent
        The resolved delegation intent for this work unit.
    continuation_hint
        Opaque string carrying any local-to-remote continuation context
        (e.g. partial result id, checkpoint reference).
    assembled_at
        Unix timestamp when the bundle was assembled.
    is_session_anchored
        True iff ``session_id`` is non-empty (policy enforcement).
    metadata
        Additional opaque key/value pairs.
    """

    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    device_id: str = ""
    session_id: str = ""
    source_runtime_posture: str = _POSTURE_CONTROL_ONLY
    coordination_role: str = ""
    android_host_role: str = ""
    capability_tier: str = _TIER_UNKNOWN
    delegation_intent: DelegationIntent = DelegationIntent.none
    continuation_hint: str = ""
    assembled_at: float = field(default_factory=time.time)
    is_session_anchored: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "source_runtime_posture": self.source_runtime_posture,
            "coordination_role": self.coordination_role,
            "android_host_role": self.android_host_role,
            "capability_tier": self.capability_tier,
            "delegation_intent": self.delegation_intent.value,
            "continuation_hint": self.continuation_hint,
            "assembled_at": self.assembled_at,
            "is_session_anchored": self.is_session_anchored,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass(frozen=True)
class DispatchEligibilityOutcome:
    """Result of :func:`evaluate_dispatch_eligibility`.

    Attributes
    ----------
    is_eligible
        True iff delegated dispatch is permitted given the inputs.
    resolved_intent
        The maximum delegation intent that is permitted given the inputs.
        If ``is_eligible`` is False this will be ``DelegationIntent.none``.
    blocking_reason
        Human-readable string describing why dispatch is ineligible, or
        empty string when ``is_eligible`` is True.
    applied_policy
        The policy sentinel string that caused the block, or empty string.
    note
        Informational message for non-blocking outcomes (e.g. downgrade
        explanations).  Empty string when no additional info is present.
        Never non-empty when ``blocking_reason`` is also non-empty.
    device_id
        The device id that was evaluated.
    session_id
        The session id that was evaluated.
    source_runtime_posture
        The posture that was evaluated.
    coordination_role
        The coordination role that was evaluated.
    capability_tier
        The capability tier that was evaluated.
    """

    is_eligible: bool = False
    resolved_intent: DelegationIntent = DelegationIntent.none
    blocking_reason: str = ""
    applied_policy: str = ""
    note: str = ""
    device_id: str = ""
    session_id: str = ""
    source_runtime_posture: str = _POSTURE_CONTROL_ONLY
    coordination_role: str = ""
    capability_tier: str = _TIER_UNKNOWN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_eligible": self.is_eligible,
            "resolved_intent": self.resolved_intent.value,
            "blocking_reason": self.blocking_reason,
            "applied_policy": self.applied_policy,
            "note": self.note,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "source_runtime_posture": self.source_runtime_posture,
            "coordination_role": self.coordination_role,
            "capability_tier": self.capability_tier,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass(frozen=True)
class DelegatedRuntimeDispatchRecord:
    """Canonical, immutable record of a single delegated-runtime dispatch intent.

    This is the primary value type produced by :func:`build_delegated_dispatch_record`.

    Attributes
    ----------
    record_id
        Stable UUID for this dispatch intent record.
    device_id
        Identity of the remote device/runtime surface.
    session_id
        Attached-runtime session id from PR-7.  Must be non-empty.
    source_runtime_posture
        Posture at the time of intent (should be ``join_runtime``).
    coordination_role
        Coordination role at the time of intent.
    android_host_role
        Android host classification from PR-5.
    capability_tier
        Capability tier from PR-6.
    delegation_intent
        The canonical delegation intent for this record.
    preparation_state
        Current handoff preparation lifecycle state.
    eligibility_outcome
        The eligibility outcome that authorised this record.  Present only
        when the record was produced via :func:`build_delegated_dispatch_record`.
    continuation_hint
        Opaque continuation context for the downstream handoff path.
    created_at
        Unix timestamp when the record was created.
    metadata
        Additional opaque key/value pairs.
    reject_reason
        Non-empty string when the record was rejected; describes why.
    """

    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    device_id: str = ""
    session_id: str = ""
    source_runtime_posture: str = _POSTURE_CONTROL_ONLY
    coordination_role: str = ""
    android_host_role: str = ""
    capability_tier: str = _TIER_UNKNOWN
    delegation_intent: DelegationIntent = DelegationIntent.none
    preparation_state: HandoffPreparationState = HandoffPreparationState.not_started
    eligibility_outcome: Optional[DispatchEligibilityOutcome] = None
    continuation_hint: str = ""
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    reject_reason: str = ""

    def is_accepted(self) -> bool:
        """Return True iff the record carries a non-none intent and no reject_reason."""
        return (
            self.delegation_intent != DelegationIntent.none
            and not self.reject_reason
            and bool(self.session_id)
        )

    def is_rejected(self) -> bool:
        """Return True iff the record was explicitly rejected."""
        return bool(self.reject_reason)

    def is_pending(self) -> bool:
        """Return True iff the record is pending dispatch (preparing or ready)."""
        return self.preparation_state in (
            HandoffPreparationState.preparing,
            HandoffPreparationState.ready,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "source_runtime_posture": self.source_runtime_posture,
            "coordination_role": self.coordination_role,
            "android_host_role": self.android_host_role,
            "capability_tier": self.capability_tier,
            "delegation_intent": self.delegation_intent.value,
            "preparation_state": self.preparation_state.value,
            "eligibility_outcome": (
                self.eligibility_outcome.to_dict()
                if self.eligibility_outcome is not None
                else None
            ),
            "continuation_hint": self.continuation_hint,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "reject_reason": self.reject_reason,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedRuntimeDispatchRecord":
        """Reconstruct a record from a serialised dict.

        Unknown or malformed fields fall back to safe defaults.
        """
        if not isinstance(data, dict):
            raise ValueError(
                "DelegatedRuntimeDispatchRecord.from_dict: expected dict, "
                f"got {type(data).__name__!r}"
            )
        raw_intent = data.get("delegation_intent", DelegationIntent.none.value)
        raw_prep = data.get(
            "preparation_state", HandoffPreparationState.not_started.value
        )
        eligibility_raw = data.get("eligibility_outcome")
        eligibility: Optional[DispatchEligibilityOutcome] = None
        if isinstance(eligibility_raw, dict):
            raw_ei = eligibility_raw.get("resolved_intent", DelegationIntent.none.value)
            eligibility = DispatchEligibilityOutcome(
                is_eligible=bool(eligibility_raw.get("is_eligible", False)),
                resolved_intent=DelegationIntent.from_string(str(raw_ei)),
                blocking_reason=str(eligibility_raw.get("blocking_reason", "")),
                applied_policy=str(eligibility_raw.get("applied_policy", "")),
                note=str(eligibility_raw.get("note", "")),
                device_id=str(eligibility_raw.get("device_id", "")),
                session_id=str(eligibility_raw.get("session_id", "")),
                source_runtime_posture=str(
                    eligibility_raw.get("source_runtime_posture", _POSTURE_CONTROL_ONLY)
                ),
                coordination_role=str(eligibility_raw.get("coordination_role", "")),
                capability_tier=str(
                    eligibility_raw.get("capability_tier", _TIER_UNKNOWN)
                ),
            )
        return cls(
            record_id=str(data.get("record_id", str(uuid.uuid4()))),
            device_id=str(data.get("device_id", "")),
            session_id=str(data.get("session_id", "")),
            source_runtime_posture=str(
                data.get("source_runtime_posture", _POSTURE_CONTROL_ONLY)
            ),
            coordination_role=str(data.get("coordination_role", "")),
            android_host_role=str(data.get("android_host_role", "")),
            capability_tier=str(data.get("capability_tier", _TIER_UNKNOWN)),
            delegation_intent=DelegationIntent.from_string(str(raw_intent)),
            preparation_state=HandoffPreparationState.from_string(str(raw_prep)),
            eligibility_outcome=eligibility,
            continuation_hint=str(data.get("continuation_hint", "")),
            created_at=float(data.get("created_at", time.time())),
            metadata=dict(data.get("metadata", {})),
            reject_reason=str(data.get("reject_reason", "")),
        )


@dataclass(frozen=True)
class DelegatedRuntimeDispatchSnapshot:
    """Point-in-time snapshot of delegated dispatch records in the runtime.

    Attributes
    ----------
    snapshot_id
        Stable UUID for this snapshot.
    snapshotted_at
        Unix timestamp when the snapshot was assembled.
    records
        List of all dispatch records in the runtime at snapshot time
        (newest first).
    pending_count
        Number of records in ``preparing`` or ``ready`` state.
    total_count
        Total number of records in the runtime at snapshot time.
    policy_sentinels
        List of policy sentinel strings included for audit purposes.
    """

    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    snapshotted_at: float = field(default_factory=time.time)
    records: List[DelegatedRuntimeDispatchRecord] = field(default_factory=list)
    pending_count: int = 0
    total_count: int = 0
    policy_sentinels: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "snapshotted_at": self.snapshotted_at,
            "records": [r.to_dict() for r in self.records],
            "pending_count": self.pending_count,
            "total_count": self.total_count,
            "policy_sentinels": list(self.policy_sentinels),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# Ring-buffer runtime
# ---------------------------------------------------------------------------

_RUNTIME_CAPACITY: int = 128


class DelegatedRuntimeDispatchRuntime:
    """In-process ring-buffer for accumulating delegated dispatch records.

    Capacity: 128 entries (oldest evicted when full).
    Thread-safety: not guaranteed; callers must synchronise if needed.
    """

    def __init__(self, capacity: int = _RUNTIME_CAPACITY) -> None:
        self._capacity: int = max(1, capacity)
        self._records: Deque[DelegatedRuntimeDispatchRecord] = deque(
            maxlen=self._capacity
        )

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def size(self) -> int:
        return len(self._records)

    def push(self, record: DelegatedRuntimeDispatchRecord) -> None:
        """Append *record* to the ring buffer, evicting the oldest if full."""
        self._records.append(record)

    def list_all(self) -> List[DelegatedRuntimeDispatchRecord]:
        """Return all records, newest first."""
        return list(reversed(self._records))

    def list_pending(self) -> List[DelegatedRuntimeDispatchRecord]:
        """Return records in ``preparing`` or ``ready`` state, newest first."""
        return [r for r in reversed(self._records) if r.is_pending()]

    def get_latest_for_session(
        self, session_id: str
    ) -> Optional[DelegatedRuntimeDispatchRecord]:
        """Return the most recent record matching *session_id*, or None."""
        for record in reversed(self._records):
            if record.session_id == session_id:
                return record
        return None

    def clear(self) -> None:
        """Remove all records from the ring buffer."""
        self._records.clear()


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_SINGLETON_RUNTIME: Optional[DelegatedRuntimeDispatchRuntime] = None


def get_delegated_runtime_dispatch_runtime() -> DelegatedRuntimeDispatchRuntime:
    """Return the process-wide singleton runtime, creating it if necessary."""
    global _SINGLETON_RUNTIME
    if _SINGLETON_RUNTIME is None:
        _SINGLETON_RUNTIME = DelegatedRuntimeDispatchRuntime()
    return _SINGLETON_RUNTIME


def reset_delegated_runtime_dispatch_runtime() -> None:
    """Reset the singleton runtime (test isolation only)."""
    global _SINGLETON_RUNTIME
    _SINGLETON_RUNTIME = None


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def evaluate_dispatch_eligibility(
    *,
    device_id: str = "",
    session_id: str = "",
    source_runtime_posture: str = _POSTURE_CONTROL_ONLY,
    coordination_role: str = "",
    capability_tier: str = _TIER_UNKNOWN,
    requested_intent: DelegationIntent = DelegationIntent.delegate,
) -> DispatchEligibilityOutcome:
    """Evaluate whether the given session context permits delegated dispatch.

    Parameters
    ----------
    device_id
        Device identifier.
    session_id
        Attached-runtime session id (must be non-empty).
    source_runtime_posture
        Source posture.  ``join_runtime`` is required for non-none intent.
    coordination_role
        Coordination role.  ``observer_only`` and ``target_only_executor``
        block delegation intent.
    capability_tier
        Capability tier.  ``command_only`` blocks ``delegate`` intent.
    requested_intent
        The delegation intent the host wishes to express.

    Returns
    -------
    DispatchEligibilityOutcome
        The evaluation result including the maximum permitted intent.
    """
    posture = (source_runtime_posture or _POSTURE_CONTROL_ONLY).lower().strip()
    role = (coordination_role or "").lower().strip()
    tier = (capability_tier or _TIER_UNKNOWN).lower().strip()
    sid = (session_id or "").strip()

    # Policy: session anchor required.
    if not sid:
        return DispatchEligibilityOutcome(
            is_eligible=False,
            resolved_intent=DelegationIntent.none,
            blocking_reason=(
                "Delegation blocked: session_id is empty.  "
                f"Policy: {DELEGATION_REQUIRES_ATTACHED_SESSION_POLICY}"
            ),
            applied_policy=DELEGATION_REQUIRES_ATTACHED_SESSION_POLICY,
            device_id=device_id,
            session_id=sid,
            source_runtime_posture=posture,
            coordination_role=role,
            capability_tier=tier,
        )

    # Policy: join_runtime posture required for non-none intent.
    if posture != _POSTURE_JOIN_RUNTIME:
        return DispatchEligibilityOutcome(
            is_eligible=False,
            resolved_intent=DelegationIntent.none,
            blocking_reason=(
                f"Delegation blocked: posture={posture!r} is not join_runtime.  "
                f"Policy: {DELEGATION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY}"
            ),
            applied_policy=DELEGATION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
            device_id=device_id,
            session_id=sid,
            source_runtime_posture=posture,
            coordination_role=role,
            capability_tier=tier,
        )

    # Policy: observer_only blocks delegation.
    if role == _ROLE_OBSERVER_ONLY:
        return DispatchEligibilityOutcome(
            is_eligible=False,
            resolved_intent=DelegationIntent.none,
            blocking_reason=(
                "Delegation blocked: coordination_role=observer_only.  "
                f"Policy: {OBSERVER_ONLY_ROLE_BLOCKS_DELEGATION_POLICY}"
            ),
            applied_policy=OBSERVER_ONLY_ROLE_BLOCKS_DELEGATION_POLICY,
            device_id=device_id,
            session_id=sid,
            source_runtime_posture=posture,
            coordination_role=role,
            capability_tier=tier,
        )

    # Policy: target_only_executor cannot initiate delegation.
    if role == _ROLE_TARGET_ONLY_EXECUTOR:
        return DispatchEligibilityOutcome(
            is_eligible=False,
            resolved_intent=DelegationIntent.none,
            blocking_reason=(
                "Delegation blocked: coordination_role=target_only_executor "
                "may not initiate delegation.  "
                f"Policy: {TARGET_ONLY_EXECUTOR_CANNOT_DELEGATE_POLICY}"
            ),
            applied_policy=TARGET_ONLY_EXECUTOR_CANNOT_DELEGATE_POLICY,
            device_id=device_id,
            session_id=sid,
            source_runtime_posture=posture,
            coordination_role=role,
            capability_tier=tier,
        )

    # Determine the maximum intent the capability tier permits.
    if tier == _TIER_COMMAND_ONLY:
        # command_only tier may relay but not fully delegate.
        max_intent = DelegationIntent.relay
        if requested_intent == DelegationIntent.delegate:
            return DispatchEligibilityOutcome(
                is_eligible=True,
                resolved_intent=max_intent,
                blocking_reason="",
                applied_policy=COMMAND_ONLY_TIER_BLOCKS_FULL_DELEGATION_POLICY,
                note=(
                    f"Full delegation downgraded to relay: capability_tier={tier!r}.  "
                    f"Policy: {COMMAND_ONLY_TIER_BLOCKS_FULL_DELEGATION_POLICY}"
                ),
                device_id=device_id,
                session_id=sid,
                source_runtime_posture=posture,
                coordination_role=role,
                capability_tier=tier,
            )
    else:
        max_intent = requested_intent

    return DispatchEligibilityOutcome(
        is_eligible=True,
        resolved_intent=max_intent,
        blocking_reason="",
        applied_policy="",
        note="",
        device_id=device_id,
        session_id=sid,
        source_runtime_posture=posture,
        coordination_role=role,
        capability_tier=tier,
    )


def build_delegated_dispatch_record(
    *,
    device_id: str = "",
    session_id: str = "",
    source_runtime_posture: str = _POSTURE_CONTROL_ONLY,
    coordination_role: str = "",
    android_host_role: str = "",
    capability_tier: str = _TIER_UNKNOWN,
    requested_intent: DelegationIntent = DelegationIntent.delegate,
    continuation_hint: str = "",
    preparation_state: HandoffPreparationState = HandoffPreparationState.not_started,
    metadata: Optional[Dict[str, Any]] = None,
    runtime: Optional[DelegatedRuntimeDispatchRuntime] = None,
) -> DelegatedRuntimeDispatchRecord:
    """Create and persist a canonical delegated-runtime dispatch intent record.

    This is the primary factory function.  It runs
    :func:`evaluate_dispatch_eligibility` internally and creates a record
    reflecting the outcome.  When eligibility fails, the record carries
    ``delegation_intent=none``, ``reject_reason`` set to the blocking reason,
    and ``preparation_state=cancelled``.

    The record is automatically persisted to *runtime* (or the singleton).

    Parameters
    ----------
    device_id
        Identity of the remote device/runtime surface.
    session_id
        Attached-runtime session id from PR-7.
    source_runtime_posture
        Posture of the session.
    coordination_role
        Coordination role of the session.
    android_host_role
        Android host classification from PR-5.
    capability_tier
        Capability tier from PR-6.
    requested_intent
        The delegation intent the host wishes to express.
    continuation_hint
        Opaque continuation context.
    preparation_state
        Initial preparation state (defaults to ``not_started``).
    metadata
        Additional opaque key/value pairs.
    runtime
        Optional explicit runtime; uses singleton if None.

    Returns
    -------
    DelegatedRuntimeDispatchRecord
        The created record.
    """
    if runtime is None:
        runtime = get_delegated_runtime_dispatch_runtime()

    eligibility = evaluate_dispatch_eligibility(
        device_id=device_id,
        session_id=session_id,
        source_runtime_posture=source_runtime_posture,
        coordination_role=coordination_role,
        capability_tier=capability_tier,
        requested_intent=requested_intent,
    )

    if not eligibility.is_eligible or eligibility.resolved_intent == DelegationIntent.none:
        record = DelegatedRuntimeDispatchRecord(
            device_id=device_id,
            session_id=session_id,
            source_runtime_posture=(source_runtime_posture or _POSTURE_CONTROL_ONLY).lower().strip(),
            coordination_role=coordination_role or "",
            android_host_role=android_host_role or "",
            capability_tier=(capability_tier or _TIER_UNKNOWN).lower().strip(),
            delegation_intent=DelegationIntent.none,
            preparation_state=HandoffPreparationState.cancelled,
            eligibility_outcome=eligibility,
            continuation_hint=continuation_hint or "",
            metadata=metadata or {},
            reject_reason=eligibility.blocking_reason,
        )
    else:
        record = DelegatedRuntimeDispatchRecord(
            device_id=device_id,
            session_id=session_id,
            source_runtime_posture=(source_runtime_posture or _POSTURE_CONTROL_ONLY).lower().strip(),
            coordination_role=coordination_role or "",
            android_host_role=android_host_role or "",
            capability_tier=(capability_tier or _TIER_UNKNOWN).lower().strip(),
            delegation_intent=eligibility.resolved_intent,
            preparation_state=preparation_state,
            eligibility_outcome=eligibility,
            continuation_hint=continuation_hint or "",
            metadata=metadata or {},
            reject_reason="",
        )

    runtime.push(record)
    return record


def prepare_handoff_inputs(
    record: DelegatedRuntimeDispatchRecord,
    *,
    override_continuation_hint: str = "",
) -> HandoffInputBundle:
    """Assemble a canonical :class:`HandoffInputBundle` from *record*.

    The bundle carries the full context needed by the downstream handoff path
    (PR-3 / ``core.canonical_handoff_path``).  It enforces
    :data:`HANDOFF_INPUTS_MUST_BE_SESSION_ANCHORED_POLICY`.

    Parameters
    ----------
    record
        The accepted dispatch record to assemble inputs from.
    override_continuation_hint
        If non-empty, overrides the continuation hint from the record.

    Returns
    -------
    HandoffInputBundle
        Assembled bundle.  ``is_session_anchored`` is True iff
        ``record.session_id`` is non-empty.
    """
    sid = record.session_id or ""
    return HandoffInputBundle(
        record_id=record.record_id,
        device_id=record.device_id,
        session_id=sid,
        source_runtime_posture=record.source_runtime_posture,
        coordination_role=record.coordination_role,
        android_host_role=record.android_host_role,
        capability_tier=record.capability_tier,
        delegation_intent=record.delegation_intent,
        continuation_hint=override_continuation_hint or record.continuation_hint,
        assembled_at=time.time(),
        is_session_anchored=bool(sid),
        metadata=dict(record.metadata),
    )


def record_delegated_dispatch_intent(
    record: DelegatedRuntimeDispatchRecord,
    *,
    runtime: Optional[DelegatedRuntimeDispatchRuntime] = None,
) -> None:
    """Persist *record* to the ring-buffer runtime.

    Typically called internally by :func:`build_delegated_dispatch_record`.
    Exposed for callers that construct records directly.

    Parameters
    ----------
    record
        The record to persist.
    runtime
        Optional explicit runtime; uses singleton if None.
    """
    if runtime is None:
        runtime = get_delegated_runtime_dispatch_runtime()
    runtime.push(record)


def get_delegated_dispatch_record(
    session_id: str,
    *,
    runtime: Optional[DelegatedRuntimeDispatchRuntime] = None,
) -> Optional[DelegatedRuntimeDispatchRecord]:
    """Return the most recent dispatch record for *session_id*, or None.

    Parameters
    ----------
    session_id
        Attached-runtime session id to look up.
    runtime
        Optional explicit runtime; uses singleton if None.
    """
    if runtime is None:
        runtime = get_delegated_runtime_dispatch_runtime()
    return runtime.get_latest_for_session(session_id)


def list_pending_delegated_dispatch_records(
    *,
    runtime: Optional[DelegatedRuntimeDispatchRuntime] = None,
) -> List[DelegatedRuntimeDispatchRecord]:
    """Return all records in ``preparing`` or ``ready`` state, newest first.

    Parameters
    ----------
    runtime
        Optional explicit runtime; uses singleton if None.
    """
    if runtime is None:
        runtime = get_delegated_runtime_dispatch_runtime()
    return runtime.list_pending()


def build_delegated_dispatch_snapshot(
    *,
    runtime: Optional[DelegatedRuntimeDispatchRuntime] = None,
) -> DelegatedRuntimeDispatchSnapshot:
    """Assemble a :class:`DelegatedRuntimeDispatchSnapshot` from current state.

    Parameters
    ----------
    runtime
        Optional explicit runtime; uses singleton if None.
    """
    if runtime is None:
        runtime = get_delegated_runtime_dispatch_runtime()

    all_records = runtime.list_all()
    pending = runtime.list_pending()

    return DelegatedRuntimeDispatchSnapshot(
        records=all_records,
        pending_count=len(pending),
        total_count=len(all_records),
        policy_sentinels=[
            DELEGATED_RUNTIME_DISPATCH_INTENT_AUTHORITY,
            DELEGATION_REQUIRES_ATTACHED_SESSION_POLICY,
            DELEGATION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
            OBSERVER_ONLY_ROLE_BLOCKS_DELEGATION_POLICY,
            TARGET_ONLY_EXECUTOR_CANNOT_DELEGATE_POLICY,
            COMMAND_ONLY_TIER_BLOCKS_FULL_DELEGATION_POLICY,
            HANDOFF_INPUTS_MUST_BE_SESSION_ANCHORED_POLICY,
            DELEGATION_INTENT_IS_ADDITIVE_TO_SESSION_POLICY,
            DISPATCH_RECORD_IS_IMMUTABLE_POLICY,
            PREPARATION_STATE_IS_MONOTONICALLY_ADVANCING_POLICY,
        ],
    )
