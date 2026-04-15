"""core/delegated_runtime_handoff_contract.py
=============================================
PR package 9 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Canonical Delegated-Runtime Handoff Contract Foundations.

This module is the **canonical authority** for the host-side representation
of the payload, metadata, and contract that is prepared for remote delegated
execution.  It defines a stable, typed, round-trippable contract record that
downstream Android receipt/execution can converge on as one authoritative model
rather than a collection of scattered implicit assumptions.

Background
----------
After PR-8 established the concept of a delegated-runtime dispatch intent and
handoff-preparation state, the host-side orchestration layer still lacks a
single canonical structure for the *contract* that is transmitted when delegated
work is handed off to an attached cross-device runtime surface.  Different code
paths forward handoff payloads, session metadata, posture/role/capability
context, and continuation hints through ad hoc dictionaries, making it
difficult for the Android side to rely on a stable, versioned contract.

PR-9 closes this gap on the MAIN-repo side by providing:

1. :class:`HandoffContractVersion` — canonical enum for the handoff contract
   schema version (v1/v2/unknown).
2. :class:`HandoffContractStatus` — canonical enum for the lifecycle status of
   a prepared handoff contract (draft/sealed/dispatched/expired/cancelled).
3. :class:`DelegatedHandoffContractIdentity` — stable, serialisable record
   capturing the canonical identifiers for a handoff contract: contract_id,
   session_id, device_id, trace_id.
4. :class:`DelegatedHandoffContractMeta` — typed container for the
   posture/role/capability/continuation metadata that accompanies the contract.
5. :class:`DelegatedHandoffContractPayload` — typed container for the task
   payload forwarded to the remote surface.
6. :class:`DelegatedHandoffContractRecord` — stable, immutable top-level record
   that aggregates identity, meta, payload, status, and dispatch-record linkage.
7. :class:`DelegatedHandoffContractSnapshot` — point-in-time snapshot of all
   pending/recent contracts for audit and projection.
8. :class:`DelegatedHandoffContractRuntime` — in-process ring-buffer singleton
   (128 entries) accumulating contract records across the process lifetime.
9. :func:`build_delegated_handoff_contract` — creates a canonical
   :class:`DelegatedHandoffContractRecord` from a dispatch record and task
   payload, enforcing identity/meta normalization.
10. :func:`seal_handoff_contract` — returns a new copy of the contract with
    status advanced to ``sealed``, indicating it is ready for dispatch.
11. :func:`record_handoff_contract` — persists a record to the ring-buffer.
12. :func:`get_handoff_contract` — retrieves the most recent contract for a
    given session_id from the ring-buffer.
13. :func:`list_pending_handoff_contracts` — returns all contracts whose status
    is ``draft`` or ``sealed``.
14. :func:`build_handoff_contract_snapshot` — assembles a
    :class:`DelegatedHandoffContractSnapshot` from the ring-buffer state.
15. Ten policy sentinels documenting canonical handoff-contract rules.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Session-anchored** — every contract record references an attached-session
  id from PR-7; session-less contracts are rejected.
- **Dispatch-record linked** — every contract record references the PR-8
  dispatch record id that authorised the delegation intent.
- **Posture-preserving** — ``source_runtime_posture`` flows from the dispatch
  record into the contract without normalisation or coercion.
- **Version-stable** — the ``contract_version`` field signals the schema
  version to the receiving Android surface so it can apply the correct
  deserialisation path.
- **Status-monotonic** — HandoffContractStatus advances monotonically from
  draft → sealed → dispatched; cancelled/expired are terminal.
- **Fully serialisable** — all dataclasses expose ``to_dict()`` / ``to_json()``
  and ``from_dict()`` for stable, round-trippable wire representations.
- **Graceful degradation** — unknown or missing fields default to the
  conservative safe outcome (``HandoffContractStatus.draft``,
  ``HandoffContractVersion.unknown``).

Relationship to other PR packages
----------------------------------
* PR-1  (``core.posture_contract_canonicalization``) — posture field in
  contracts is validated against the contract-layer canonicalization rules.
* PR-3  (``core.canonical_handoff_path``) — the downstream handoff path
  consumes the contract payload produced here.
* PR-5  (``core.android_runtime_host``) — android_host_role from the dispatch
  record is forwarded as part of the contract meta.
* PR-6  (``core.canonical_capability_scheduling_basis``) — capability_tier is
  forwarded in the contract meta.
* PR-7  (``core.attached_runtime_session``) — every contract is anchored to a
  persistent attached-runtime session record.
* PR-8  (``core.delegated_runtime_dispatch_intent``) — every contract is linked
  to the dispatch record that authorised the delegation intent.
* PR-538 (``core.multi_device_coordination_authority``) — coordination_role is
  forwarded in the contract meta.

Public API
----------
Sentinels::

    DELEGATED_RUNTIME_HANDOFF_CONTRACT_AUTHORITY
    HANDOFF_CONTRACT_REQUIRES_DISPATCH_RECORD_POLICY
    HANDOFF_CONTRACT_REQUIRES_ATTACHED_SESSION_POLICY
    HANDOFF_CONTRACT_VERSION_MUST_BE_EXPLICIT_POLICY
    HANDOFF_CONTRACT_IDENTITY_IS_IMMUTABLE_POLICY
    HANDOFF_CONTRACT_STATUS_IS_MONOTONIC_POLICY
    HANDOFF_CONTRACT_POSTURE_IS_PRESERVED_POLICY
    SEALED_CONTRACT_IS_DISPATCH_READY_POLICY
    HANDOFF_CONTRACT_PAYLOAD_MUST_BE_NON_EMPTY_POLICY
    HANDOFF_CONTRACT_TRACE_ID_IS_PROPAGATED_POLICY
    DELEGATED_RUNTIME_HANDOFF_CONTRACT_PR9_SENTINEL

Enums::

    HandoffContractVersion
    HandoffContractStatus

Dataclasses::

    DelegatedHandoffContractIdentity
    DelegatedHandoffContractMeta
    DelegatedHandoffContractPayload
    DelegatedHandoffContractRecord
    DelegatedHandoffContractSnapshot

Classes::

    DelegatedHandoffContractRuntime

Functions::

    build_delegated_handoff_contract(...) -> DelegatedHandoffContractRecord
    seal_handoff_contract(record, ...) -> DelegatedHandoffContractRecord
    record_handoff_contract(record, ...) -> None
    get_handoff_contract(session_id, ...) -> DelegatedHandoffContractRecord | None
    list_pending_handoff_contracts(...) -> list[DelegatedHandoffContractRecord]
    build_handoff_contract_snapshot(...) -> DelegatedHandoffContractSnapshot
    get_handoff_contract_runtime() -> DelegatedHandoffContractRuntime
    reset_handoff_contract_runtime() -> None
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

DELEGATED_RUNTIME_HANDOFF_CONTRACT_AUTHORITY: str = (
    "DELEGATED_RUNTIME_HANDOFF_CONTRACT_AUTHORITY::"
    "core.delegated_runtime_handoff_contract is the canonical authority for "
    "host-side delegated-runtime handoff contract data and metadata on the "
    "main-repo side (PR package 9, post-533 dual-repo runtime unification)."
)

HANDOFF_CONTRACT_REQUIRES_DISPATCH_RECORD_POLICY: str = (
    "POLICY::HANDOFF_CONTRACT_REQUIRES_DISPATCH_RECORD: every "
    "DelegatedHandoffContractRecord must be linked to a PR-8 "
    "DelegatedRuntimeDispatchRecord via dispatch_record_id.  Contracts that "
    "lack a dispatch record linkage must not be forwarded to the handoff path."
)

HANDOFF_CONTRACT_REQUIRES_ATTACHED_SESSION_POLICY: str = (
    "POLICY::HANDOFF_CONTRACT_REQUIRES_ATTACHED_SESSION: every "
    "DelegatedHandoffContractRecord must be anchored to a valid non-empty "
    "session_id from a PR-7 attached-runtime session.  Session-less contracts "
    "must not be sealed or dispatched."
)

HANDOFF_CONTRACT_VERSION_MUST_BE_EXPLICIT_POLICY: str = (
    "POLICY::HANDOFF_CONTRACT_VERSION_MUST_BE_EXPLICIT: the contract_version "
    "field of every DelegatedHandoffContractRecord must be set to v1 or v2; "
    "HandoffContractVersion.unknown signals a degraded or legacy contract and "
    "must be treated as untrustworthy by the receiving Android surface."
)

HANDOFF_CONTRACT_IDENTITY_IS_IMMUTABLE_POLICY: str = (
    "POLICY::HANDOFF_CONTRACT_IDENTITY_IS_IMMUTABLE: once a "
    "DelegatedHandoffContractRecord is built and persisted, its identity "
    "fields (contract_id, session_id, device_id, trace_id, dispatch_record_id) "
    "must not be mutated.  Advancing status requires producing a new record via "
    "seal_handoff_contract() or record_handoff_contract()."
)

HANDOFF_CONTRACT_STATUS_IS_MONOTONIC_POLICY: str = (
    "POLICY::HANDOFF_CONTRACT_STATUS_IS_MONOTONIC: HandoffContractStatus "
    "advances monotonically from draft → sealed → dispatched.  Regression to "
    "an earlier status is disallowed; cancelled and expired are terminal "
    "statuses that may be reached from any non-dispatched status."
)

HANDOFF_CONTRACT_POSTURE_IS_PRESERVED_POLICY: str = (
    "POLICY::HANDOFF_CONTRACT_POSTURE_IS_PRESERVED: the source_runtime_posture "
    "field in the contract meta flows unchanged from the originating dispatch "
    "record and must not be normalised, coerced, or defaulted to a different "
    "value by the contract builder.  The Android receiving surface relies on "
    "the posture value matching what was evaluated in PR-8."
)

SEALED_CONTRACT_IS_DISPATCH_READY_POLICY: str = (
    "POLICY::SEALED_CONTRACT_IS_DISPATCH_READY: a contract with status=sealed "
    "has been validated and is ready to be forwarded to the remote Android "
    "runtime surface.  Only sealed contracts may be forwarded; draft contracts "
    "must not be dispatched."
)

HANDOFF_CONTRACT_PAYLOAD_MUST_BE_NON_EMPTY_POLICY: str = (
    "POLICY::HANDOFF_CONTRACT_PAYLOAD_MUST_BE_NON_EMPTY: the task payload "
    "carried in DelegatedHandoffContractPayload.task_body must be a non-empty "
    "dict.  Empty task payloads are rejected at build time and produce a "
    "contract with status=cancelled."
)

HANDOFF_CONTRACT_TRACE_ID_IS_PROPAGATED_POLICY: str = (
    "POLICY::HANDOFF_CONTRACT_TRACE_ID_IS_PROPAGATED: the trace_id in "
    "DelegatedHandoffContractIdentity must be propagated from the originating "
    "request or dispatch context.  Auto-generated trace ids are permitted only "
    "when no upstream trace id is available."
)

DELEGATED_RUNTIME_HANDOFF_CONTRACT_PR9_SENTINEL: str = (
    "DELEGATED_RUNTIME_HANDOFF_CONTRACT_PR9_SENTINEL::package=9 "
    "track=post-533-dual-repo-runtime-unification "
    "repo=main "
    "module=core.delegated_runtime_handoff_contract"
)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_POSTURE_JOIN_RUNTIME: str = "join_runtime"
_POSTURE_CONTROL_ONLY: str = "control_only"
_RING_BUFFER_CAPACITY: int = 128

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class HandoffContractVersion(str, Enum):
    """Canonical enum for the delegated-runtime handoff contract schema version.

    Values
    ------
    v1
        First-generation handoff contract schema.  Carries task payload,
        session id, posture, coordination role, and capability tier.
    v2
        Second-generation handoff contract schema.  Extends v1 with
        android_host_role, continuation_hint, and trace propagation fields.
    unknown
        Version could not be determined.  Contract must be treated as
        untrustworthy by the receiving surface.
    """

    v1 = "v1"
    v2 = "v2"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "HandoffContractVersion":
        """Return the enum member matching *value*, defaulting to ``unknown``."""
        if not isinstance(value, str):
            return cls.unknown
        normalised = value.lower().strip()
        try:
            return cls(normalised)
        except ValueError:
            return cls.unknown


class HandoffContractStatus(str, Enum):
    """Canonical enum for the lifecycle status of a prepared handoff contract.

    Values
    ------
    draft
        The contract has been built but not yet validated or sealed.
        Draft contracts must not be forwarded to the remote surface.
    sealed
        The contract has been validated and is ready for dispatch.
        Only sealed contracts may be forwarded.
    dispatched
        The contract has been forwarded to the remote Android runtime surface.
        This is a terminal successful status.
    expired
        The contract was not dispatched within the allowed window.
        Terminal status.
    cancelled
        The contract was explicitly cancelled before dispatch.
        Terminal status.
    """

    draft = "draft"
    sealed = "sealed"
    dispatched = "dispatched"
    expired = "expired"
    cancelled = "cancelled"

    @classmethod
    def from_string(cls, value: str) -> "HandoffContractStatus":
        """Return the enum member matching *value*, defaulting to ``draft``."""
        if not isinstance(value, str):
            return cls.draft
        normalised = value.lower().strip()
        try:
            return cls(normalised)
        except ValueError:
            return cls.draft

    def is_terminal(self) -> bool:
        """Return True if this status is a terminal status."""
        return self in (
            HandoffContractStatus.dispatched,
            HandoffContractStatus.expired,
            HandoffContractStatus.cancelled,
        )

    def is_dispatch_ready(self) -> bool:
        """Return True if the contract may be forwarded to the remote surface."""
        return self == HandoffContractStatus.sealed

    def can_advance_to(self, next_status: "HandoffContractStatus") -> bool:
        """Return True if monotonic advancement to *next_status* is permitted.

        Advancement order: draft(0) → sealed(1) → dispatched(2).
        cancelled and expired may be reached from draft or sealed.
        """
        if self.is_terminal():
            return False
        _order = {
            HandoffContractStatus.draft: 0,
            HandoffContractStatus.sealed: 1,
            HandoffContractStatus.dispatched: 2,
            HandoffContractStatus.expired: 2,
            HandoffContractStatus.cancelled: 2,
        }
        return _order.get(next_status, -1) > _order.get(self, -1)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DelegatedHandoffContractIdentity:
    """Canonical identifiers for a delegated-runtime handoff contract.

    Attributes
    ----------
    contract_id
        Stable UUID for this handoff contract.
    session_id
        Attached-runtime session id from PR-7.  Must be non-empty.
    device_id
        Identity of the remote device/runtime surface.
    trace_id
        Distributed trace identifier propagated from the originating request.
    dispatch_record_id
        ID of the PR-8 DelegatedRuntimeDispatchRecord that authorised this
        contract.  Must be non-empty.
    """

    contract_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    device_id: str = ""
    trace_id: str = ""
    dispatch_record_id: str = ""

    @property
    def delegation_transfer_session_id(self) -> str:
        """Canonical alias for delegation/handoff transfer continuity semantics."""
        return self.session_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "trace_id": self.trace_id,
            "dispatch_record_id": self.dispatch_record_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedHandoffContractIdentity":
        if not isinstance(data, dict):
            raise ValueError(
                "DelegatedHandoffContractIdentity.from_dict: expected dict, "
                f"got {type(data).__name__!r}"
            )
        return cls(
            contract_id=str(data.get("contract_id", "") or str(uuid.uuid4())),
            session_id=str(
                data.get("delegation_transfer_session_id")
                or data.get("execution_transfer_session_id")
                or data.get("session_id", "")
            ),
            device_id=str(data.get("device_id", "")),
            trace_id=str(data.get("trace_id", "")),
            dispatch_record_id=str(data.get("dispatch_record_id", "")),
        )


@dataclass(frozen=True)
class DelegatedHandoffContractMeta:
    """Posture/role/capability/continuation metadata accompanying the contract.

    Attributes
    ----------
    source_runtime_posture
        Posture of the originating session (``join_runtime`` / ``control_only``).
        Flows unchanged from the dispatch record; never coerced.
    coordination_role
        Coordination role at the time of delegation.
    android_host_role
        Android host classification from PR-5.
    capability_tier
        Capability tier from PR-6.
    delegation_intent
        The canonical delegation intent that was resolved in PR-8.
    continuation_hint
        Opaque continuation context for the remote surface.
    contract_version
        Schema version of this contract.
    metadata
        Additional opaque key/value pairs.
    """

    source_runtime_posture: str = _POSTURE_CONTROL_ONLY
    coordination_role: str = ""
    android_host_role: str = ""
    capability_tier: str = "unknown"
    delegation_intent: str = "none"
    continuation_hint: str = ""
    contract_version: HandoffContractVersion = HandoffContractVersion.v2
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_runtime_posture": self.source_runtime_posture,
            "coordination_role": self.coordination_role,
            "android_host_role": self.android_host_role,
            "capability_tier": self.capability_tier,
            "delegation_intent": self.delegation_intent,
            "continuation_hint": self.continuation_hint,
            "contract_version": self.contract_version.value,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedHandoffContractMeta":
        if not isinstance(data, dict):
            raise ValueError(
                "DelegatedHandoffContractMeta.from_dict: expected dict, "
                f"got {type(data).__name__!r}"
            )
        raw_ver = data.get("contract_version", HandoffContractVersion.v2.value)
        return cls(
            source_runtime_posture=str(
                data.get("source_runtime_posture", _POSTURE_CONTROL_ONLY)
            ),
            coordination_role=str(data.get("coordination_role", "")),
            android_host_role=str(data.get("android_host_role", "")),
            capability_tier=str(data.get("capability_tier", "unknown")),
            delegation_intent=str(data.get("delegation_intent", "none")),
            continuation_hint=str(data.get("continuation_hint", "")),
            contract_version=HandoffContractVersion.from_string(str(raw_ver)),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class DelegatedHandoffContractPayload:
    """Task payload forwarded to the remote runtime surface.

    Attributes
    ----------
    task_body
        The primary task payload dict.  Must be non-empty.
    task_id
        Stable identifier for the task within the handoff context.
    capability
        Primary capability required for the task (e.g. ``"screen_control"``).
    exec_mode
        Execution mode hint for the remote surface: ``"local"`` /
        ``"remote"`` / ``"both"``.
    raw_payload
        Original unmodified payload dict preserved for backward compatibility.
    metadata
        Additional opaque key/value pairs.
    """

    task_body: Dict[str, Any] = field(default_factory=dict)
    task_id: str = ""
    capability: str = ""
    exec_mode: str = "remote"
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_body": dict(self.task_body),
            "task_id": self.task_id,
            "capability": self.capability,
            "exec_mode": self.exec_mode,
            "raw_payload": dict(self.raw_payload),
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedHandoffContractPayload":
        if not isinstance(data, dict):
            raise ValueError(
                "DelegatedHandoffContractPayload.from_dict: expected dict, "
                f"got {type(data).__name__!r}"
            )
        return cls(
            task_body=dict(data.get("task_body", {})),
            task_id=str(data.get("task_id", "")),
            capability=str(data.get("capability", "")),
            exec_mode=str(data.get("exec_mode", "remote")),
            raw_payload=dict(data.get("raw_payload", {})),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class DelegatedHandoffContractRecord:
    """Canonical, immutable top-level delegated-runtime handoff contract record.

    This is the primary value type produced by
    :func:`build_delegated_handoff_contract`.  It aggregates the contract
    identity, metadata, task payload, status, and linkage to the PR-8
    dispatch record in a single stable, serialisable structure.

    Attributes
    ----------
    identity
        Canonical identifiers for the contract.
    meta
        Posture/role/capability/continuation metadata.
    payload
        Task payload forwarded to the remote surface.
    status
        Current lifecycle status of the contract.
    created_at
        Unix timestamp when the contract was built.
    sealed_at
        Unix timestamp when the contract was sealed, or 0.0 if not yet sealed.
    reject_reason
        Non-empty string when the contract was rejected at build time.
    """

    identity: DelegatedHandoffContractIdentity = field(
        default_factory=DelegatedHandoffContractIdentity
    )
    meta: DelegatedHandoffContractMeta = field(
        default_factory=DelegatedHandoffContractMeta
    )
    payload: DelegatedHandoffContractPayload = field(
        default_factory=DelegatedHandoffContractPayload
    )
    status: HandoffContractStatus = HandoffContractStatus.draft
    created_at: float = field(default_factory=time.time)
    sealed_at: float = 0.0
    reject_reason: str = ""

    # Convenience accessors -------------------------------------------------

    def is_accepted(self) -> bool:
        """Return True iff the contract was accepted (not rejected and session-anchored)."""
        return (
            not self.reject_reason
            and bool(self.identity.session_id)
            and bool(self.identity.dispatch_record_id)
            and self.status != HandoffContractStatus.cancelled
        )

    def is_rejected(self) -> bool:
        """Return True iff the contract was explicitly rejected at build time."""
        return bool(self.reject_reason)

    def is_pending(self) -> bool:
        """Return True iff the contract is pending dispatch (draft or sealed)."""
        return self.status in (
            HandoffContractStatus.draft,
            HandoffContractStatus.sealed,
        )

    def is_dispatch_ready(self) -> bool:
        """Return True iff the contract is sealed and may be dispatched."""
        return self.status.is_dispatch_ready()

    # Serialisation ---------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "meta": self.meta.to_dict(),
            "payload": self.payload.to_dict(),
            "status": self.status.value,
            "created_at": self.created_at,
            "sealed_at": self.sealed_at,
            "reject_reason": self.reject_reason,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedHandoffContractRecord":
        """Reconstruct a record from a serialised dict.

        Unknown or malformed fields fall back to safe defaults.
        """
        if not isinstance(data, dict):
            raise ValueError(
                "DelegatedHandoffContractRecord.from_dict: expected dict, "
                f"got {type(data).__name__!r}"
            )
        raw_identity = data.get("identity", {})
        raw_meta = data.get("meta", {})
        raw_payload = data.get("payload", {})
        raw_status = data.get("status", HandoffContractStatus.draft.value)

        identity = (
            DelegatedHandoffContractIdentity.from_dict(raw_identity)
            if isinstance(raw_identity, dict)
            else DelegatedHandoffContractIdentity()
        )
        meta = (
            DelegatedHandoffContractMeta.from_dict(raw_meta)
            if isinstance(raw_meta, dict)
            else DelegatedHandoffContractMeta()
        )
        payload_obj = (
            DelegatedHandoffContractPayload.from_dict(raw_payload)
            if isinstance(raw_payload, dict)
            else DelegatedHandoffContractPayload()
        )
        return cls(
            identity=identity,
            meta=meta,
            payload=payload_obj,
            status=HandoffContractStatus.from_string(str(raw_status)),
            created_at=float(data.get("created_at", time.time())),
            sealed_at=float(data.get("sealed_at", 0.0)),
            reject_reason=str(data.get("reject_reason", "")),
        )


@dataclass(frozen=True)
class DelegatedHandoffContractSnapshot:
    """Point-in-time snapshot of all recent delegated-runtime handoff contracts.

    Attributes
    ----------
    snapshot_id
        Stable UUID for this snapshot.
    records
        All contract records in the snapshot, newest-first.
    pending_count
        Number of records with status draft or sealed.
    total_count
        Total number of records in the snapshot.
    snapshotted_at
        Unix timestamp when the snapshot was assembled.
    policy_sentinels
        List of all policy sentinel strings for audit/projection.
    """

    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    records: List[DelegatedHandoffContractRecord] = field(default_factory=list)
    pending_count: int = 0
    total_count: int = 0
    snapshotted_at: float = field(default_factory=time.time)
    policy_sentinels: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "records": [r.to_dict() for r in self.records],
            "pending_count": self.pending_count,
            "total_count": self.total_count,
            "snapshotted_at": self.snapshotted_at,
            "policy_sentinels": list(self.policy_sentinels),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# Ring-buffer runtime
# ---------------------------------------------------------------------------


class DelegatedHandoffContractRuntime:
    """In-process ring-buffer singleton accumulating handoff contract records.

    Capacity: 128 entries.  Oldest entry is evicted when the buffer is full.
    Thread-safety: this class is deliberately not thread-safe; callers that
    need concurrency guarantees must apply external locking.
    """

    _CAPACITY: int = _RING_BUFFER_CAPACITY

    def __init__(self) -> None:
        self._buffer: Deque[DelegatedHandoffContractRecord] = deque(
            maxlen=self._CAPACITY
        )

    @property
    def capacity(self) -> int:
        return self._CAPACITY

    @property
    def size(self) -> int:
        return len(self._buffer)

    def push(self, record: DelegatedHandoffContractRecord) -> None:
        """Append *record* to the ring buffer, evicting the oldest if full."""
        self._buffer.append(record)

    def list_all(self) -> List[DelegatedHandoffContractRecord]:
        """Return all records, newest-first."""
        return list(reversed(self._buffer))

    def list_pending(self) -> List[DelegatedHandoffContractRecord]:
        """Return records with status draft or sealed, newest-first."""
        return [
            r
            for r in reversed(self._buffer)
            if r.status in (HandoffContractStatus.draft, HandoffContractStatus.sealed)
        ]

    def get_latest_for_session(
        self, session_id: str
    ) -> Optional[DelegatedHandoffContractRecord]:
        """Return the most recent record for *session_id*, or None."""
        for record in reversed(self._buffer):
            if record.identity.session_id == session_id:
                return record
        return None

    def clear(self) -> None:
        """Remove all records from the buffer."""
        self._buffer.clear()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_HANDOFF_CONTRACT_RUNTIME_SINGLETON: Optional[DelegatedHandoffContractRuntime] = None


def get_handoff_contract_runtime() -> DelegatedHandoffContractRuntime:
    """Return the module-level singleton :class:`DelegatedHandoffContractRuntime`."""
    global _HANDOFF_CONTRACT_RUNTIME_SINGLETON
    if _HANDOFF_CONTRACT_RUNTIME_SINGLETON is None:
        _HANDOFF_CONTRACT_RUNTIME_SINGLETON = DelegatedHandoffContractRuntime()
    return _HANDOFF_CONTRACT_RUNTIME_SINGLETON


def reset_handoff_contract_runtime() -> None:
    """Reset (replace) the module-level singleton with a fresh instance.

    Intended for test isolation only.
    """
    global _HANDOFF_CONTRACT_RUNTIME_SINGLETON
    _HANDOFF_CONTRACT_RUNTIME_SINGLETON = DelegatedHandoffContractRuntime()


# ---------------------------------------------------------------------------
# Policy sentinels list (for snapshot / audit)
# ---------------------------------------------------------------------------

_ALL_POLICY_SENTINELS: List[str] = [
    HANDOFF_CONTRACT_REQUIRES_DISPATCH_RECORD_POLICY,
    HANDOFF_CONTRACT_REQUIRES_ATTACHED_SESSION_POLICY,
    HANDOFF_CONTRACT_VERSION_MUST_BE_EXPLICIT_POLICY,
    HANDOFF_CONTRACT_IDENTITY_IS_IMMUTABLE_POLICY,
    HANDOFF_CONTRACT_STATUS_IS_MONOTONIC_POLICY,
    HANDOFF_CONTRACT_POSTURE_IS_PRESERVED_POLICY,
    SEALED_CONTRACT_IS_DISPATCH_READY_POLICY,
    HANDOFF_CONTRACT_PAYLOAD_MUST_BE_NON_EMPTY_POLICY,
    HANDOFF_CONTRACT_TRACE_ID_IS_PROPAGATED_POLICY,
    DELEGATED_RUNTIME_HANDOFF_CONTRACT_PR9_SENTINEL,
]

# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def build_delegated_handoff_contract(
    *,
    session_id: str,
    device_id: str = "",
    dispatch_record_id: str,
    trace_id: str = "",
    task_body: Dict[str, Any],
    task_id: str = "",
    capability: str = "",
    exec_mode: str = "remote",
    source_runtime_posture: str = _POSTURE_CONTROL_ONLY,
    coordination_role: str = "",
    android_host_role: str = "",
    capability_tier: str = "unknown",
    delegation_intent: str = "none",
    continuation_hint: str = "",
    contract_version: HandoffContractVersion = HandoffContractVersion.v2,
    raw_payload: Optional[Dict[str, Any]] = None,
    meta_metadata: Optional[Dict[str, Any]] = None,
    payload_metadata: Optional[Dict[str, Any]] = None,
    runtime: Optional[DelegatedHandoffContractRuntime] = None,
) -> DelegatedHandoffContractRecord:
    """Build a canonical :class:`DelegatedHandoffContractRecord`.

    Parameters
    ----------
    session_id:
        Attached-runtime session id from PR-7.  Must be non-empty.
    device_id:
        Identity of the remote device/runtime surface.
    dispatch_record_id:
        ID of the PR-8 DelegatedRuntimeDispatchRecord.  Must be non-empty.
    trace_id:
        Distributed trace identifier.  Auto-generated UUID if empty.
    task_body:
        Primary task payload dict.  Must be non-empty.
    task_id:
        Stable identifier for the task.  Auto-generated UUID if empty.
    capability:
        Primary capability required for the task.
    exec_mode:
        Execution mode hint: ``"local"`` / ``"remote"`` / ``"both"``.
    source_runtime_posture:
        Posture from the dispatch record.  Not coerced.
    coordination_role:
        Coordination role from the dispatch record.
    android_host_role:
        Android host classification from PR-5.
    capability_tier:
        Capability tier from PR-6.
    delegation_intent:
        Resolved delegation intent string from PR-8.
    continuation_hint:
        Opaque continuation context string.
    contract_version:
        Schema version of the contract.
    raw_payload:
        Original unmodified payload dict (backward compat).
    meta_metadata:
        Additional metadata for the meta sub-record.
    payload_metadata:
        Additional metadata for the payload sub-record.
    runtime:
        Ring-buffer to persist the record into.  Uses singleton if None.

    Returns
    -------
    DelegatedHandoffContractRecord
        An accepted (status=draft) or rejected (status=cancelled) record.
    """
    _runtime = runtime if runtime is not None else get_handoff_contract_runtime()

    # Validate: session_id must be non-empty
    if not session_id:
        rejected = DelegatedHandoffContractRecord(
            identity=DelegatedHandoffContractIdentity(
                session_id="",
                device_id=device_id,
                trace_id=trace_id or str(uuid.uuid4()),
                dispatch_record_id=dispatch_record_id,
            ),
            meta=DelegatedHandoffContractMeta(
                source_runtime_posture=source_runtime_posture,
                coordination_role=coordination_role,
                android_host_role=android_host_role,
                capability_tier=capability_tier,
                delegation_intent=delegation_intent,
                continuation_hint=continuation_hint,
                contract_version=contract_version,
                metadata=dict(meta_metadata or {}),
            ),
            payload=DelegatedHandoffContractPayload(
                task_body={},
                task_id=task_id or str(uuid.uuid4()),
                capability=capability,
                exec_mode=exec_mode,
                raw_payload=dict(raw_payload or {}),
                metadata=dict(payload_metadata or {}),
            ),
            status=HandoffContractStatus.cancelled,
            reject_reason=(
                HANDOFF_CONTRACT_REQUIRES_ATTACHED_SESSION_POLICY[:80] + "..."
            ),
        )
        _runtime.push(rejected)
        return rejected

    # Validate: dispatch_record_id must be non-empty
    if not dispatch_record_id:
        rejected = DelegatedHandoffContractRecord(
            identity=DelegatedHandoffContractIdentity(
                session_id=session_id,
                device_id=device_id,
                trace_id=trace_id or str(uuid.uuid4()),
                dispatch_record_id="",
            ),
            meta=DelegatedHandoffContractMeta(
                source_runtime_posture=source_runtime_posture,
                coordination_role=coordination_role,
                android_host_role=android_host_role,
                capability_tier=capability_tier,
                delegation_intent=delegation_intent,
                continuation_hint=continuation_hint,
                contract_version=contract_version,
                metadata=dict(meta_metadata or {}),
            ),
            payload=DelegatedHandoffContractPayload(
                task_body={},
                task_id=task_id or str(uuid.uuid4()),
                capability=capability,
                exec_mode=exec_mode,
                raw_payload=dict(raw_payload or {}),
                metadata=dict(payload_metadata or {}),
            ),
            status=HandoffContractStatus.cancelled,
            reject_reason=(
                HANDOFF_CONTRACT_REQUIRES_DISPATCH_RECORD_POLICY[:80] + "..."
            ),
        )
        _runtime.push(rejected)
        return rejected

    # Validate: task_body must be non-empty
    if not task_body:
        rejected = DelegatedHandoffContractRecord(
            identity=DelegatedHandoffContractIdentity(
                session_id=session_id,
                device_id=device_id,
                trace_id=trace_id or str(uuid.uuid4()),
                dispatch_record_id=dispatch_record_id,
            ),
            meta=DelegatedHandoffContractMeta(
                source_runtime_posture=source_runtime_posture,
                coordination_role=coordination_role,
                android_host_role=android_host_role,
                capability_tier=capability_tier,
                delegation_intent=delegation_intent,
                continuation_hint=continuation_hint,
                contract_version=contract_version,
                metadata=dict(meta_metadata or {}),
            ),
            payload=DelegatedHandoffContractPayload(
                task_body={},
                task_id=task_id or str(uuid.uuid4()),
                capability=capability,
                exec_mode=exec_mode,
                raw_payload=dict(raw_payload or {}),
                metadata=dict(payload_metadata or {}),
            ),
            status=HandoffContractStatus.cancelled,
            reject_reason=(
                HANDOFF_CONTRACT_PAYLOAD_MUST_BE_NON_EMPTY_POLICY[:80] + "..."
            ),
        )
        _runtime.push(rejected)
        return rejected

    # Build the accepted (draft) contract
    resolved_trace_id = trace_id if trace_id else str(uuid.uuid4())
    resolved_task_id = task_id if task_id else str(uuid.uuid4())

    identity = DelegatedHandoffContractIdentity(
        session_id=session_id,
        device_id=device_id,
        trace_id=resolved_trace_id,
        dispatch_record_id=dispatch_record_id,
    )
    meta = DelegatedHandoffContractMeta(
        source_runtime_posture=source_runtime_posture,
        coordination_role=coordination_role,
        android_host_role=android_host_role,
        capability_tier=capability_tier,
        delegation_intent=delegation_intent,
        continuation_hint=continuation_hint,
        contract_version=contract_version,
        metadata=dict(meta_metadata or {}),
    )
    payload_obj = DelegatedHandoffContractPayload(
        task_body=dict(task_body),
        task_id=resolved_task_id,
        capability=capability,
        exec_mode=exec_mode,
        raw_payload=dict(raw_payload or task_body),
        metadata=dict(payload_metadata or {}),
    )
    record = DelegatedHandoffContractRecord(
        identity=identity,
        meta=meta,
        payload=payload_obj,
        status=HandoffContractStatus.draft,
        reject_reason="",
    )
    _runtime.push(record)
    return record


def seal_handoff_contract(
    record: DelegatedHandoffContractRecord,
    *,
    runtime: Optional[DelegatedHandoffContractRuntime] = None,
) -> DelegatedHandoffContractRecord:
    """Return a new :class:`DelegatedHandoffContractRecord` with status=sealed.

    If the record is already terminal, the original record is returned
    unchanged and no new record is persisted.

    Parameters
    ----------
    record:
        The contract record to seal.
    runtime:
        Ring-buffer to persist the sealed record into.  Uses singleton if None.

    Returns
    -------
    DelegatedHandoffContractRecord
        A new sealed record, or the original record if advancement is not
        permitted.
    """
    if not record.status.can_advance_to(HandoffContractStatus.sealed):
        return record
    _runtime = runtime if runtime is not None else get_handoff_contract_runtime()
    sealed = DelegatedHandoffContractRecord(
        identity=record.identity,
        meta=record.meta,
        payload=record.payload,
        status=HandoffContractStatus.sealed,
        created_at=record.created_at,
        sealed_at=time.time(),
        reject_reason=record.reject_reason,
    )
    _runtime.push(sealed)
    return sealed


def record_handoff_contract(
    record: DelegatedHandoffContractRecord,
    *,
    runtime: Optional[DelegatedHandoffContractRuntime] = None,
) -> None:
    """Persist *record* to the ring-buffer singleton.

    Parameters
    ----------
    record:
        The contract record to persist.
    runtime:
        Ring-buffer to persist into.  Uses singleton if None.
    """
    _runtime = runtime if runtime is not None else get_handoff_contract_runtime()
    _runtime.push(record)


def get_handoff_contract(
    session_id: str,
    *,
    runtime: Optional[DelegatedHandoffContractRuntime] = None,
) -> Optional[DelegatedHandoffContractRecord]:
    """Return the most recent contract for *session_id*, or None.

    Parameters
    ----------
    session_id:
        The attached-runtime session id to look up.
    runtime:
        Ring-buffer to query.  Uses singleton if None.
    """
    _runtime = runtime if runtime is not None else get_handoff_contract_runtime()
    return _runtime.get_latest_for_session(session_id)


def list_pending_handoff_contracts(
    *,
    runtime: Optional[DelegatedHandoffContractRuntime] = None,
) -> List[DelegatedHandoffContractRecord]:
    """Return all contracts with status draft or sealed (pending dispatch).

    Parameters
    ----------
    runtime:
        Ring-buffer to query.  Uses singleton if None.
    """
    _runtime = runtime if runtime is not None else get_handoff_contract_runtime()
    return _runtime.list_pending()


def build_handoff_contract_snapshot(
    *,
    runtime: Optional[DelegatedHandoffContractRuntime] = None,
) -> DelegatedHandoffContractSnapshot:
    """Assemble a :class:`DelegatedHandoffContractSnapshot` from the ring-buffer.

    Parameters
    ----------
    runtime:
        Ring-buffer to snapshot.  Uses singleton if None.
    """
    _runtime = runtime if runtime is not None else get_handoff_contract_runtime()
    all_records = _runtime.list_all()
    pending = [
        r
        for r in all_records
        if r.status in (HandoffContractStatus.draft, HandoffContractStatus.sealed)
    ]
    return DelegatedHandoffContractSnapshot(
        records=all_records,
        pending_count=len(pending),
        total_count=len(all_records),
        policy_sentinels=list(_ALL_POLICY_SENTINELS),
    )
