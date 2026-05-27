"""core/canonical_session_truth.py
====================================
PR-4 (post-533 dual-repo runtime host unification track):
Establish canonical runtime session truth and result merge across local and
cross-device execution — MAIN repo side.

This module is the **canonical authority** for determining and recording the
definitive execution truth for a runtime session.  It answers the question:

    *"Given results from local execution, remote/takeover execution, and
    partial/multi-device contributions, what is the single authoritative
    execution truth for this session?"*

Responsibilities
----------------
1. **Posture-aware result unit filtering** — strip ``control_only`` source
   contributions from the execution pool before merging results, so they are
   never incorrectly treated as execution contributors.
2. **Canonical result merge** — wrap :func:`~contracts.cross_runtime_result_merge.merge_runtime_results`
   with posture-aware pre-filtering and a stable record of the merge decision.
3. **Session truth recording** — a small ring-buffer runtime records each
   ``CanonicalSessionTruthRecord`` so projection, operator, and observability
   layers can read a consistent view without re-computing it.
4. **Snapshot surface** — :func:`build_canonical_session_truth_snapshot`
   produces a ``CanonicalSessionTruthSnapshot`` suitable for embedding in
   :class:`~contracts.runtime_session_snapshot.RuntimeSessionSnapshot`.

Design principles
-----------------
- **Additive only** — does not modify any existing module; callers opt in.
- **Graceful degradation** — ``None`` / unknown posture values fall back to
  ``control_only`` (the conservative default from PR-533 / PR-1).
- **Policy-sentinel anchored** — every behavioural policy documented here is
  referenced by a named string sentinel for audit and observability.
- **Durable audit sink (PR-B2)** — the ring-buffer runtime is still in-process
  authoritative; when a :class:`~core.replay_audit_persistence.DurableAuditStore`
  is attached via :meth:`CanonicalSessionTruthRuntime.set_audit_store`, each
  :class:`CanonicalSessionTruthRecord` is also written to the store so truth
  merge evidence survives process lifetime.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`CANONICAL_SESSION_TRUTH_AUTHORITY`
:data:`CONTROL_ONLY_EXCLUDED_FROM_MERGE_POLICY`
:data:`POSTURE_AWARE_RESULT_FILTER_POLICY`
:data:`CANONICAL_SESSION_TRUTH_PR4_SENTINEL`
:data:`CANONICAL_TRUTH_DURABLE_AUDIT_SENTINEL`

Data types
~~~~~~~~~~
:class:`SessionTruthSource`
:class:`CanonicalSessionTruthRecord`
:class:`CanonicalSessionTruthSnapshot`

Functions
~~~~~~~~~
:func:`filter_result_units_by_posture`
:func:`merge_session_truth`
:func:`record_session_truth`
:func:`build_canonical_session_truth_snapshot`
:func:`get_canonical_session_truth_runtime`
:func:`reset_canonical_session_truth_runtime`
"""

from __future__ import annotations

import dataclasses
import logging
import os
import time
import uuid
from collections import deque
from enum import Enum
from threading import Lock
from typing import Any, Deque, Dict, List, Optional, Sequence

try:
    from core.replay_audit_persistence import (
        append_replay_audit_record as _append_truth_audit_record,
    )
except ImportError:  # noqa: BLE001
    _append_truth_audit_record = None  # type: ignore[assignment]

__all__ = [
    # Authority / policy sentinels
    "CANONICAL_SESSION_TRUTH_AUTHORITY",
    "CONTROL_ONLY_EXCLUDED_FROM_MERGE_POLICY",
    "POSTURE_AWARE_RESULT_FILTER_POLICY",
    "JOIN_RUNTIME_INCLUDED_IN_MERGE_POLICY",
    "OBSERVER_ONLY_ROLE_EXCLUDED_FROM_MERGE_POLICY",
    "SESSION_TRUTH_SOURCE_MUST_BE_CANONICAL_POLICY",
    "PROJECTION_INTEROP_COMPAT_NOT_TRUTH_AUTHORITY_POLICY",
    "CANONICAL_SESSION_TRUTH_PR4_SENTINEL",
    "CANONICAL_TRUTH_DURABLE_AUDIT_SENTINEL",
    "SESSION_TRUTH_SNAPSHOT_IS_DURABLE_POLICY",
    "SESSION_TRUTH_RING_BUFFER_IS_READ_CACHE_SENTINEL",
    "CANONICAL_TRUTH_ADMITS_ONLY_CANONICALIZED_OWNERSHIP_POLICY",
    "PARTICIPANT_OWNERSHIP_BOUNDARY_FIELD_POLICY",
    "NON_CANONICAL_PARTICIPANT_TRUTH_ISOLATED_POLICY",
    # Data types
    "SessionTruthSource",
    "CanonicalSessionTruthRecord",
    "CanonicalSessionTruthRuntime",
    "CanonicalSessionTruthSnapshot",
    "SessionTruthSnapshotStore",
    # Functions
    "filter_result_units_by_posture",
    "merge_session_truth",
    "record_session_truth",
    "build_canonical_session_truth_snapshot",
    "get_canonical_session_truth_runtime",
    "reset_canonical_session_truth_runtime",
    "get_session_truth_snapshot_store",
    "reset_session_truth_snapshot_store",
    "restore_session_truth_from_snapshot",
]

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

CANONICAL_SESSION_TRUTH_AUTHORITY: str = (
    "CANONICAL_SESSION_TRUTH::PR4_AUTHORITY_V1: "
    "core.canonical_session_truth is the canonical authority for runtime "
    "session truth and result merge across local, remote/takeover, and "
    "multi-device execution paths.  "
    "PR-4, post-533 dual-repo runtime host unification track."
)
"""Module-level authority sentinel for canonical session truth (PR-4)."""

CONTROL_ONLY_EXCLUDED_FROM_MERGE_POLICY: str = (
    "CANONICAL_SESSION_TRUTH::CONTROL_ONLY_EXCLUDED_POLICY_V1: "
    "Result units whose source device carries posture='control_only' MUST "
    "NOT be included in the canonical result merge as execution contributors. "
    "control_only sources are observer/controller devices only; they dispatch "
    "commands and receive results but do not contribute execution output. "
    "Excluding them prevents incorrect attribution of authoritative results "
    "to non-executing sources.  "
    "PR-4, post-533 dual-repo runtime host unification track."
)
"""Policy: control_only result units are excluded from canonical merge."""

POSTURE_AWARE_RESULT_FILTER_POLICY: str = (
    "CANONICAL_SESSION_TRUTH::POSTURE_AWARE_FILTER_POLICY_V1: "
    "All result unit collections passed to merge_session_truth() MUST be "
    "pre-filtered through filter_result_units_by_posture() before the "
    "canonical merge is applied.  Callers that bypass this filter violate "
    "the canonical session truth contract.  "
    "PR-4, post-533 dual-repo runtime host unification track."
)
"""Policy: result units must be posture-filtered before canonical merge."""

JOIN_RUNTIME_INCLUDED_IN_MERGE_POLICY: str = (
    "CANONICAL_SESSION_TRUTH::JOIN_RUNTIME_INCLUDED_POLICY_V1: "
    "Result units whose source device carries posture='join_runtime' ARE "
    "included in the canonical result merge and may be selected as the "
    "authoritative primary result.  They are treated as first-class "
    "execution contributors alongside target-side results.  "
    "PR-4, post-533 dual-repo runtime host unification track."
)
"""Policy: join_runtime result units are included in canonical merge."""

CANONICAL_SESSION_TRUTH_PR4_SENTINEL: str = (
    "CANONICAL_SESSION_TRUTH::PR4_INTEGRATED_V1: "
    "PR-4 canonical runtime session truth and result merge is active. "
    "filter_result_units_by_posture() and merge_session_truth() are wired "
    "into the main-repo canonical result path.  source_runtime_posture is "
    "now a first-class input to the session truth merge decision."
)
"""Integration sentinel confirming PR-4 canonical session truth is live."""

OBSERVER_ONLY_ROLE_EXCLUDED_FROM_MERGE_POLICY: str = (
    "CANONICAL_SESSION_TRUTH::OBSERVER_ONLY_ROLE_EXCLUDED_POLICY_V1: "
    "Result units whose contributing device carries coordination_role='observer_only' "
    "MUST NOT be included in the canonical result merge as execution contributors. "
    "observer_only coordination role devices consume runtime state but do not "
    "contribute execution output.  Excluding them prevents incorrect attribution "
    "of authoritative results to non-executing participants.  "
    "PR-4 / PR-6, post-533 dual-repo runtime host unification track."
)
"""Policy: observer_only coordination-role result units are excluded from canonical merge."""

SESSION_TRUTH_SOURCE_MUST_BE_CANONICAL_POLICY: str = (
    "CANONICAL_SESSION_TRUTH::TRUTH_SOURCE_CANONICAL_ONLY_POLICY_V1: "
    "record_session_truth() MUST keep truth_source within SessionTruthSource "
    "canonical values. Unknown or non-canonical values are downgraded to "
    "'unknown' to avoid creating parallel truth authority labels."
)
"""Policy: truth_source must remain inside canonical SessionTruthSource values."""

PROJECTION_INTEROP_COMPAT_NOT_TRUTH_AUTHORITY_POLICY: str = (
    "CANONICAL_SESSION_TRUTH::PROJECTION_INTEROP_COMPAT_NOT_AUTHORITY_POLICY_V1: "
    "projection/interop/compat/legacy labels are read/adaptation surfaces only "
    "and MUST NOT be accepted as canonical truth authority origins."
)
"""Policy: projection/interop/compat surfaces cannot act as truth-source authority."""

CANONICAL_TRUTH_DURABLE_AUDIT_SENTINEL: str = (
    "CANONICAL_SESSION_TRUTH_DURABLE_AUDIT::PR_B2_V1: "
    "CanonicalSessionTruthRuntime now supports an optional durable audit sink "
    "via set_audit_store().  When attached, every CanonicalSessionTruthRecord "
    "is also written to a DurableAuditStore so truth merge evidence survives "
    "process lifetime and is available for postmortem / forensic review.  "
    "The in-memory ring buffer is a read-cache of the durable path — not an "
    "independent truth authority.  (PR-B2, clarified by PR-2)"
)
"""Sentinel confirming durable audit sink support is active on CanonicalSessionTruthRuntime (PR-B2)."""

SESSION_TRUTH_RING_BUFFER_IS_READ_CACHE_SENTINEL: str = (
    "CANONICAL_SESSION_TRUTH::RING_BUFFER_READ_CACHE_V1: "
    "The CanonicalSessionTruthRuntime in-process ring buffer is a READ-CACHE, "
    "not an independent truth authority.  At startup, "
    "restore_session_truth_from_snapshot() repopulates it from the durable "
    "SessionTruthSnapshotStore.  During runtime, every record written to the "
    "ring buffer is ALSO written to the snapshot store (set_snapshot_store). "
    "The ring buffer reflects the durable state and may be cleared and rebuilt "
    "from the durable store at any time.  The SessionTruthSnapshotStore is the "
    "canonical authority for session truth that must survive restarts.  "
    "See core.durable_truth_authority_chain.RING_BUFFER_IS_READ_CACHE_POLICY "
    "for the definitive authority declaration.  (PR-2)"
)
"""Sentinel clarifying the ring buffer's read-cache role vs. durable authority (PR-2)."""

CANONICAL_TRUTH_ADMITS_ONLY_CANONICALIZED_OWNERSHIP_POLICY: str = (
    "CANONICAL_SESSION_TRUTH::OWNERSHIP_ADMISSION_GATE_POLICY_V1: "
    "CanonicalSessionTruthRuntime.record() MUST NOT admit records whose "
    "participant_ownership_boundary is 'participant_local_only', "
    "'fallback_non_canonical', or 'rejected_non_canonical' into the canonical "
    "ring buffer.  Only records with participant_ownership_boundary='canonicalized' "
    "or an empty boundary (backward-compat) are admitted as canonical truth. "
    "Non-canonical records are counted and written to the durable audit store "
    "as evidence but are never added to the canonical ring buffer or snapshot. "
    "This prevents compat/fallback/divergence pollution of the canonical truth "
    "substrate.  (PR-4V2 ownership chain, canonical ownership truth bridge)"
)
"""Policy: canonical ring buffer only admits canonicalized ownership records."""

PARTICIPANT_OWNERSHIP_BOUNDARY_FIELD_POLICY: str = (
    "CANONICAL_SESSION_TRUTH::PARTICIPANT_OWNERSHIP_BOUNDARY_FIELD_POLICY_V1: "
    "CanonicalSessionTruthRecord.participant_ownership_boundary carries the "
    "ownership classification determined at the Android participant truth "
    "ingress boundary.  Allowed values: 'canonicalized', 'participant_local_only', "
    "'fallback_non_canonical', 'rejected_non_canonical', '' (unset / backward-compat). "
    "This field allows deeper truth/replay/recovery consumers to inspect the "
    "ownership origin of a canonical truth record without re-interrogating the "
    "ingress layer.  (PR-4V2 ownership chain, canonical ownership truth bridge)"
)
"""Policy: participant_ownership_boundary field carries ingress ownership classification."""

NON_CANONICAL_PARTICIPANT_TRUTH_ISOLATED_POLICY: str = (
    "CANONICAL_SESSION_TRUTH::NON_CANONICAL_ISOLATED_POLICY_V1: "
    "participant_local_only, fallback_non_canonical, and rejected_non_canonical "
    "records originating from Android participant truth ingress MUST NOT be "
    "silently merged into the canonical truth substrate.  They are isolated at "
    "the CanonicalSessionTruthRuntime admission gate and written to the durable "
    "audit store as non-canonical evidence only.  Callers that need to inspect "
    "non-canonical records must query the durable audit store directly; they "
    "are never returned by the canonical ring buffer read APIs.  "
    "(PR-4V2 ownership chain, canonical ownership truth bridge)"
)
"""Policy: non-canonical participant truth is isolated from canonical substrate."""

# ---------------------------------------------------------------------------
# Internal posture helpers
# ---------------------------------------------------------------------------

_CONTROL_ONLY: str = "control_only"
_JOIN_RUNTIME: str = "join_runtime"
_VALID_POSTURES = frozenset({_CONTROL_ONLY, _JOIN_RUNTIME})

_OBSERVER_ONLY_ROLE: str = "observer_only"

_CANONICAL_TRUTH_SOURCES = frozenset(
    {
        "local",
        "remote_handoff",
        "takeover",
        "multi_device",
        "mesh",
        "unknown",
    }
)
_NON_AUTHORITY_TRUTH_SOURCE_LABELS = (
    "projection",
    "interop",
    "compat",
    "legacy",
    "adapter",
    "bridge",
)

# Ownership boundary values that must NOT be admitted to the canonical ring buffer.
# These originate from the Android participant truth ingress ownership_context and
# represent non-canonical, local-only, fallback, or rejected participant truth.
_NON_CANONICAL_OWNERSHIP_BOUNDARIES: frozenset = frozenset(
    {
        "participant_local_only",
        "fallback_non_canonical",
        "rejected_non_canonical",
    }
)


def _is_non_authority_truth_source_label(normalised: str) -> bool:
    """Return True when *normalised* uses a known non-authority source label."""
    if normalised in _NON_AUTHORITY_TRUTH_SOURCE_LABELS:
        return True
    return any(
        normalised.startswith(f"{label}_") or normalised.startswith(f"{label}-")
        for label in _NON_AUTHORITY_TRUTH_SOURCE_LABELS
    )


def _normalise_posture(hint: Optional[str]) -> str:
    """Return a canonical posture string, defaulting to ``control_only``."""
    if not hint or not isinstance(hint, str):
        return _CONTROL_ONLY
    normalised = hint.strip().lower()
    return normalised if normalised in _VALID_POSTURES else _CONTROL_ONLY


def _normalise_truth_source_label(label: Optional[str]) -> tuple[str, Optional[str]]:
    """Normalise truth_source to canonical labels and downgrade non-authority hints."""
    if label is None:
        return SessionTruthSource.unknown.value, None
    normalised = str(label).strip().lower()
    if normalised in _CANONICAL_TRUTH_SOURCES:
        return normalised, None
    if _is_non_authority_truth_source_label(normalised):
        return (
            SessionTruthSource.unknown.value,
            f"downgraded_non_authority_label:{normalised}",
        )
    return (
        SessionTruthSource.unknown.value,
        f"downgraded_non_canonical_label:{normalised}",
    )


# ---------------------------------------------------------------------------
# SessionTruthSource — where a result unit came from
# ---------------------------------------------------------------------------


class SessionTruthSource(str, Enum):
    """Origin of a result unit relative to the canonical truth merge.

    local
        Result produced by the source device's own local execution.
    remote_handoff
        Result produced by a remote target device that accepted a handoff.
    takeover
        Result produced via a target-side takeover (PR-34).
    multi_device
        Result produced by a multi-device coordinated execution.
    mesh
        Result produced by a mesh-session participant (PR-33).
    unknown
        Origin cannot be determined; treated conservatively.
    """

    local = "local"
    remote_handoff = "remote_handoff"
    takeover = "takeover"
    multi_device = "multi_device"
    mesh = "mesh"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# CanonicalSessionTruthRecord
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CanonicalSessionTruthRecord:
    """Immutable record of a single canonical session truth determination.

    Attributes
    ----------
    record_id:
        Unique identifier for this truth record (UUID4 prefix).
    session_id:
        Runtime-attachment session for which truth was computed.
        (Conversation session semantics are intentionally out of scope here.)
    task_id:
        Optional task identifier.
    trace_id:
        Optional distributed trace identifier.
    source_runtime_posture:
        Posture of the originating source device at truth-determination time.
        Always ``control_only`` or ``join_runtime``.
    source_eligible:
        Whether the source device was eligible to contribute as an execution
        participant (``False`` for ``control_only``).
    total_units_received:
        Total number of result units presented before posture filtering.
    units_after_filter:
        Number of result units remaining after posture filtering.
    filtered_unit_ids:
        IDs of units that were excluded by posture filtering.
    merge_id:
        Identifier of the resulting :class:`~contracts.cross_runtime_result_merge.MergedRuntimeResult`.
    merge_success:
        Whether the canonical merge produced a successful result.
    primary_unit_id:
        ID of the result unit selected as authoritative primary, if any.
    truth_source:
        Highest-priority :class:`SessionTruthSource` represented in the merge.
    reason:
        Human-readable explanation of the truth determination.
    timestamp:
        Unix epoch seconds when this record was created.
    metadata:
        Arbitrary extensibility bag.
    participant_ownership_boundary:
        Ownership classification determined at the Android participant truth
        ingress boundary.  Allowed values: ``'canonicalized'``,
        ``'participant_local_only'``, ``'fallback_non_canonical'``,
        ``'rejected_non_canonical'``, or ``''`` (unset / backward-compat).
        Non-empty non-canonical values cause this record to be blocked from
        the canonical ring buffer admission gate.
        Policy: :data:`PARTICIPANT_OWNERSHIP_BOUNDARY_FIELD_POLICY`.
    """

    record_id: str = dataclasses.field(
        default_factory=lambda: f"cst_{uuid.uuid4().hex[:12]}"
    )
    session_id: str = ""
    task_id: Optional[str] = None
    trace_id: Optional[str] = None
    source_runtime_posture: str = _CONTROL_ONLY
    coordination_role: str = ""
    source_eligible: bool = False
    total_units_received: int = 0
    units_after_filter: int = 0
    filtered_unit_ids: List[str] = dataclasses.field(default_factory=list)
    merge_id: Optional[str] = None
    merge_success: bool = False
    primary_unit_id: Optional[str] = None
    truth_source: str = SessionTruthSource.unknown.value
    reason: str = ""
    timestamp: float = dataclasses.field(default_factory=time.time)
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)
    participant_ownership_boundary: str = ""

    @property
    def runtime_attachment_session_id(self) -> str:
        """Canonical alias for runtime attachment continuity semantics."""
        return self.session_id

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of this record."""
        return {
            "record_id": self.record_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "source_runtime_posture": self.source_runtime_posture,
            "coordination_role": self.coordination_role,
            "source_eligible": self.source_eligible,
            "total_units_received": self.total_units_received,
            "units_after_filter": self.units_after_filter,
            "filtered_unit_ids": list(self.filtered_unit_ids),
            "merge_id": self.merge_id,
            "merge_success": self.merge_success,
            "primary_unit_id": self.primary_unit_id,
            "truth_source": self.truth_source,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
            "participant_ownership_boundary": self.participant_ownership_boundary,
            "authority": CANONICAL_SESSION_TRUTH_AUTHORITY,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CanonicalSessionTruthRecord":
        """Reconstruct a :class:`CanonicalSessionTruthRecord` from a dict."""
        return cls(
            record_id=d.get("record_id") or f"cst_{uuid.uuid4().hex[:12]}",
            session_id=str(d.get("session_id") or ""),
            task_id=d.get("task_id"),
            trace_id=d.get("trace_id"),
            source_runtime_posture=str(
                d.get("source_runtime_posture") or _CONTROL_ONLY
            ),
            coordination_role=str(d.get("coordination_role") or ""),
            source_eligible=bool(d.get("source_eligible", False)),
            total_units_received=int(d.get("total_units_received", 0)),
            units_after_filter=int(d.get("units_after_filter", 0)),
            filtered_unit_ids=list(d.get("filtered_unit_ids") or []),
            merge_id=d.get("merge_id"),
            merge_success=bool(d.get("merge_success", False)),
            primary_unit_id=d.get("primary_unit_id"),
            truth_source=str(
                d.get("truth_source") or SessionTruthSource.unknown.value
            ),
            reason=str(d.get("reason") or ""),
            timestamp=float(d.get("timestamp") or time.time()),
            metadata=dict(d.get("metadata") or {}),
            participant_ownership_boundary=str(
                d.get("participant_ownership_boundary") or ""
            ),
        )


# ---------------------------------------------------------------------------
# CanonicalSessionTruthSnapshot
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CanonicalSessionTruthSnapshot:
    """Point-in-time snapshot of the canonical session truth runtime.

    Attributes
    ----------
    snapshot_id:
        Unique identifier for this snapshot.
    total_records:
        Total number of truth records ever submitted.
    recent_records:
        Most recent truth records (bounded by ``max_recent``).
    control_only_session_count:
        Number of sessions where the source was ``control_only``.
    join_runtime_session_count:
        Number of sessions where the source was ``join_runtime``.
    successful_merge_count:
        Number of records that produced a successful canonical merge.
    timestamp:
        Unix epoch seconds when this snapshot was taken.
    """

    snapshot_id: str = dataclasses.field(
        default_factory=lambda: f"cst_snap_{uuid.uuid4().hex[:8]}"
    )
    total_records: int = 0
    recent_records: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    control_only_session_count: int = 0
    join_runtime_session_count: int = 0
    successful_merge_count: int = 0
    non_canonical_rejected_count: int = 0
    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "total_records": self.total_records,
            "recent_records": list(self.recent_records),
            "control_only_session_count": self.control_only_session_count,
            "join_runtime_session_count": self.join_runtime_session_count,
            "successful_merge_count": self.successful_merge_count,
            "non_canonical_rejected_count": self.non_canonical_rejected_count,
            "timestamp": self.timestamp,
            "authority": CANONICAL_SESSION_TRUTH_AUTHORITY,
        }


# ---------------------------------------------------------------------------
# CanonicalSessionTruthRuntime — ring-buffer singleton
# ---------------------------------------------------------------------------

_RING_BUFFER_SIZE: int = 128


class CanonicalSessionTruthRuntime:
    """In-process ring-buffer recording canonical session truth determinations.

    Thread-safe.  Bounded to :data:`_RING_BUFFER_SIZE` entries.  New entries
    evict the oldest when the buffer is full.

    Durable audit sink (PR-B2)
    --------------------------
    When :meth:`set_audit_store` has been called with a
    :class:`~core.replay_audit_persistence.DurableAuditStore`, every
    :class:`CanonicalSessionTruthRecord` appended to the ring buffer is
    **also** written to the store.  The ring buffer remains the authoritative
    runtime read surface; the durable store provides forensic reviewability
    across process lifetimes.
    """

    def __init__(self, max_size: int = _RING_BUFFER_SIZE) -> None:
        self._max_size = max_size
        self._records: Deque[CanonicalSessionTruthRecord] = deque(maxlen=max_size)
        self._total: int = 0
        self._control_only_count: int = 0
        self._join_runtime_count: int = 0
        self._success_count: int = 0
        self._non_canonical_rejected_count: int = 0
        self._lock: Lock = Lock()
        # Optional durable audit sink (PR-B2)
        self._audit_store: Any = None
        # Optional durable snapshot store (default-on via startup wiring)
        self._snapshot_store: Any = None

    # ── Durable audit sink ───────────────────────────────────────────────

    def set_audit_store(self, store: Any) -> None:
        """Attach a :class:`~core.replay_audit_persistence.DurableAuditStore`.

        Once attached, every :class:`CanonicalSessionTruthRecord` recorded
        here is also written to *store* for durable auditability (PR-B2).

        Parameters
        ----------
        store:
            A :class:`~core.replay_audit_persistence.DurableAuditStore`
            instance.  Pass ``None`` to detach.
        """
        self._audit_store = store

    def set_snapshot_store(self, store: Any) -> None:
        """Attach a :class:`SessionTruthSnapshotStore` for durable session truth recovery.

        Once attached, every :class:`CanonicalSessionTruthRecord` recorded
        here is also written to the snapshot store.  On V2 restart, the
        snapshot is reloaded via :func:`restore_session_truth_from_snapshot`.

        Parameters
        ----------
        store:
            A :class:`SessionTruthSnapshotStore` instance.  Pass ``None`` to
            detach.
        """
        self._snapshot_store = store

    def record(self, rec: CanonicalSessionTruthRecord) -> CanonicalSessionTruthRecord:
        """Add *rec* to the ring buffer and return it.

        Ownership admission gate
        ------------------------
        When *rec* carries a ``participant_ownership_boundary`` value that
        belongs to :data:`_NON_CANONICAL_OWNERSHIP_BOUNDARIES` (i.e.
        ``'participant_local_only'``, ``'fallback_non_canonical'``, or
        ``'rejected_non_canonical'``), the record is **not** admitted to the
        canonical ring buffer or snapshot store.  The rejection is counted via
        ``_non_canonical_rejected_count`` and the record is written to the
        durable audit store (if attached) as non-canonical evidence only.
        Policy: :data:`CANONICAL_TRUTH_ADMITS_ONLY_CANONICALIZED_OWNERSHIP_POLICY`.

        When a durable audit store is attached, admitted records are also
        written to the store for persistent auditability (PR-B2).  When a
        snapshot store is attached, admitted records are also written to the
        snapshot for recovery across V2 restarts.
        """
        ownership_boundary = rec.participant_ownership_boundary
        if ownership_boundary in _NON_CANONICAL_OWNERSHIP_BOUNDARIES:
            # Non-canonical: block admission, count the rejection, audit as evidence.
            with self._lock:
                self._non_canonical_rejected_count += 1
            _logger.debug(
                "CanonicalSessionTruthRuntime: blocked non-canonical record "
                "(ownership_boundary=%r, session=%r, task=%r). Policy: %s",
                ownership_boundary,
                rec.session_id,
                rec.task_id,
                CANONICAL_TRUTH_ADMITS_ONLY_CANONICALIZED_OWNERSHIP_POLICY,
            )
            # Write to durable audit store as non-canonical evidence (not canonical truth).
            if self._audit_store is not None and _append_truth_audit_record is not None:
                try:
                    _append_truth_audit_record(
                        {**rec.to_dict(), "_non_canonical_blocked": True},
                        "non_canonical_truth_blocked",
                        store=self._audit_store,
                    )
                except Exception as _exc:  # noqa: BLE001
                    _logger.debug(
                        "CanonicalSessionTruthRuntime: non-canonical audit append failed: %s",
                        _exc,
                    )
            return rec  # returned but NOT admitted to canonical substrate

        # ── Canonical admission path ─────────────────────────────────────
        with self._lock:
            self._records.append(rec)
            self._total += 1
            if rec.source_runtime_posture == _JOIN_RUNTIME:
                self._join_runtime_count += 1
            else:
                self._control_only_count += 1
            if rec.merge_success:
                self._success_count += 1
        # Write to durable store outside the lock to avoid potential deadlock
        if self._audit_store is not None and _append_truth_audit_record is not None:
            try:
                _append_truth_audit_record(
                    rec.to_dict(),
                    "canonical_truth_merge",
                    store=self._audit_store,
                )
            except Exception as _exc:  # noqa: BLE001
                _logger.debug(
                    "CanonicalSessionTruthRuntime: durable audit append failed: %s",
                    _exc,
                )
        # Write to snapshot store for cross-restart recovery
        if self._snapshot_store is not None:
            try:
                self._snapshot_store.append(rec.to_dict())
            except Exception as _exc:  # noqa: BLE001
                _logger.debug(
                    "CanonicalSessionTruthRuntime: snapshot store append failed: %s",
                    _exc,
                )
        return rec

    def snapshot(self, max_recent: int = 20) -> CanonicalSessionTruthSnapshot:
        """Return a point-in-time :class:`CanonicalSessionTruthSnapshot`."""
        with self._lock:
            recent = list(self._records)[-max_recent:]
            return CanonicalSessionTruthSnapshot(
                total_records=self._total,
                recent_records=[r.to_dict() for r in recent],
                control_only_session_count=self._control_only_count,
                join_runtime_session_count=self._join_runtime_count,
                successful_merge_count=self._success_count,
                non_canonical_rejected_count=self._non_canonical_rejected_count,
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_RUNTIME: Optional[CanonicalSessionTruthRuntime] = None
_RUNTIME_LOCK: Lock = Lock()


def get_canonical_session_truth_runtime() -> CanonicalSessionTruthRuntime:
    """Return the module-level :class:`CanonicalSessionTruthRuntime` singleton.

    Default-on durable wiring
    -------------------------
    When the singleton is first created, this function automatically attaches
    the process-level :class:`SessionTruthSnapshotStore` so that every
    :class:`CanonicalSessionTruthRecord` is written to durable storage
    without requiring an explicit :meth:`CanonicalSessionTruthRuntime.set_snapshot_store`
    call.  This makes session truth durable by default — callers and startup
    code do **not** need to wire the store manually (though doing so again is
    idempotent).

    If the snapshot store cannot be obtained (e.g. import error, I/O error
    creating the directory) the runtime degrades gracefully to in-memory only
    and logs a warning.
    """
    global _RUNTIME
    if _RUNTIME is None:
        with _RUNTIME_LOCK:
            if _RUNTIME is None:
                runtime = CanonicalSessionTruthRuntime()
                # Default-on: attach the durable snapshot store immediately so
                # session truth survives process restarts without any additional
                # wiring by startup code or callers.
                try:
                    from core.session_truth_snapshot import (
                        get_session_truth_snapshot_store,
                    )
                    _snap_store = get_session_truth_snapshot_store()
                    runtime.set_snapshot_store(_snap_store)
                except Exception as _wire_exc:  # noqa: BLE001
                    _logger.warning(
                        "CanonicalSessionTruthRuntime: could not auto-wire "
                        "durable snapshot store — degrading to in-memory only: %s",
                        _wire_exc,
                    )
                _RUNTIME = runtime
    return _RUNTIME


def reset_canonical_session_truth_runtime() -> None:
    """Reset the singleton (test isolation only)."""
    global _RUNTIME
    with _RUNTIME_LOCK:
        _RUNTIME = None


# ---------------------------------------------------------------------------
# SessionTruthSnapshotStore — re-exported from core.session_truth_snapshot
# ---------------------------------------------------------------------------
# The canonical, standalone implementation lives in core.session_truth_snapshot
# to avoid the pydantic dependency chain.  This module re-exports for backward
# compatibility and for callers that already import from canonical_session_truth.
# ---------------------------------------------------------------------------

try:
    from core.session_truth_snapshot import (  # noqa: F401
        SESSION_TRUTH_SNAPSHOT_IS_DURABLE_POLICY,
        SessionTruthSnapshotStore,
        get_session_truth_snapshot_store,
        reset_session_truth_snapshot_store,
        restore_session_truth_from_snapshot,
    )
except ImportError:
    pass  # graceful degradation if standalone module unavailable


# ---------------------------------------------------------------------------
# filter_result_units_by_posture
# ---------------------------------------------------------------------------


def filter_result_units_by_posture(
    result_units: Optional[Sequence[Any]],
    *,
    source_runtime_posture: Optional[str] = None,
    allow_control_only_as_observer: bool = False,
    exclude_observer_only_role: bool = True,
) -> tuple[List[Any], List[str]]:
    """Filter a sequence of result units based on posture and coordination-role semantics.

    Parameters
    ----------
    result_units:
        Sequence of result unit objects (any type carrying a
        ``result_unit_id`` attribute or dict with that key, and optionally
        ``source_runtime_posture`` / ``coordination_role`` fields or a
        ``metadata`` dict carrying those keys).  May be ``None`` or empty —
        returns ``([], [])`` in that case.
    source_runtime_posture:
        The posture of the **session-level** originating source device.
        When ``control_only``, any result unit whose own field or metadata
        marks it as from the source device is excluded.  When ``join_runtime``,
        all units pass through (unless excluded by coordination role).
        ``None`` defaults to ``control_only``.
    allow_control_only_as_observer:
        When ``True``, ``control_only`` units are not excluded but are kept
        as observer contributions.  Defaults to ``False``.
    exclude_observer_only_role:
        When ``True`` (default), result units carrying
        ``coordination_role='observer_only'`` are excluded from the merge,
        regardless of posture.  Set to ``False`` only when caller explicitly
        needs observer contributions in the output.

    Returns
    -------
    (kept_units, excluded_ids):
        ``kept_units`` is the filtered list of result units to include in the
        canonical merge.  ``excluded_ids`` is the list of ``result_unit_id``
        values that were removed (for audit purposes).

    Notes
    -----
    Filtering priority:
    1. ``coordination_role='observer_only'`` — excluded unless
       ``exclude_observer_only_role=False``.
       Policy: :data:`OBSERVER_ONLY_ROLE_EXCLUDED_FROM_MERGE_POLICY`
    2. ``source_runtime_posture='control_only'`` — excluded unless
       ``allow_control_only_as_observer=True``.
       Policy: :data:`CONTROL_ONLY_EXCLUDED_FROM_MERGE_POLICY`

    Units without explicit posture or role context are **kept** by default —
    this preserves backward compatibility with older result paths that predate
    the posture / coordination-role contracts.
    """
    if not result_units:
        return [], []

    normalised_session_posture = _normalise_posture(source_runtime_posture)

    kept: List[Any] = []
    excluded_ids: List[str] = []

    for unit in result_units:
        unit_id = _get_unit_id(unit)

        # Priority 1: coordination_role=observer_only excludes the unit.
        if exclude_observer_only_role:
            unit_role = _get_unit_coordination_role(unit)
            if unit_role == _OBSERVER_ONLY_ROLE:
                excluded_ids.append(unit_id)
                _logger.debug(
                    "canonical_session_truth: excluded unit %r "
                    "(coordination_role=observer_only). Policy: %s",
                    unit_id,
                    OBSERVER_ONLY_ROLE_EXCLUDED_FROM_MERGE_POLICY,
                )
                continue

        # Priority 2: source_runtime_posture=control_only excludes the unit.
        unit_posture = _get_unit_posture(unit)
        if unit_posture == _CONTROL_ONLY:
            if allow_control_only_as_observer:
                kept.append(unit)
            else:
                excluded_ids.append(unit_id)
                _logger.debug(
                    "canonical_session_truth: excluded unit %r (posture=control_only). "
                    "Policy: %s",
                    unit_id,
                    CONTROL_ONLY_EXCLUDED_FROM_MERGE_POLICY,
                )
            continue

        # Unit has join_runtime posture or no explicit posture — keep it.
        kept.append(unit)

    # If the session-level posture is join_runtime but no units were labelled,
    # all units pass through (no source-level filtering needed).
    # If session posture is control_only but no units were labelled as source
    # contributions, they still pass through (remote/target results have no
    # source posture tag by definition).
    _ = normalised_session_posture  # referenced for audit; logic above is unit-level

    return kept, excluded_ids


def _get_unit_id(unit: Any) -> str:
    """Extract ``result_unit_id`` from a result unit (dict or object)."""
    if isinstance(unit, dict):
        return str(unit.get("result_unit_id", ""))
    return str(getattr(unit, "result_unit_id", ""))


def _get_unit_posture(unit: Any) -> Optional[str]:
    """Extract ``source_runtime_posture`` from a result unit (metadata or direct field).

    Metadata takes priority for backward compatibility with units created before
    the PR-4 direct field was added.  The direct field is consulted only when
    metadata carries no explicit posture value and the direct field was
    explicitly set to a non-default (non-empty) value.
    """
    if isinstance(unit, dict):
        meta = unit.get("metadata") or {}
        raw_meta = meta.get("source_runtime_posture") if isinstance(meta, dict) else None
        if raw_meta and isinstance(raw_meta, str):
            normalised = raw_meta.strip().lower()
            if normalised in _VALID_POSTURES:
                return normalised
        # Fall back to top-level field (dict key)
        raw_direct = unit.get("source_runtime_posture")
        if raw_direct and isinstance(raw_direct, str):
            normalised = raw_direct.strip().lower()
            if normalised in _VALID_POSTURES:
                return normalised
    else:
        meta = getattr(unit, "metadata", {}) or {}
        raw_meta = meta.get("source_runtime_posture") if isinstance(meta, dict) else None
        if raw_meta and isinstance(raw_meta, str):
            normalised = raw_meta.strip().lower()
            if normalised in _VALID_POSTURES:
                return normalised
        # Fall back to direct attribute — only when it differs from default
        # (i.e. when explicitly set by the caller, not just the field default).
        # We detect "explicitly set" by checking _model_fields_set when available.
        explicitly_set = False
        fields_set = getattr(unit, "model_fields_set", None)
        if fields_set is not None:
            explicitly_set = "source_runtime_posture" in fields_set
        if explicitly_set:
            raw_direct = getattr(unit, "source_runtime_posture", None)
            if raw_direct and isinstance(raw_direct, str):
                normalised = raw_direct.strip().lower()
                if normalised in _VALID_POSTURES:
                    return normalised

    return None


def _get_unit_coordination_role(unit: Any) -> Optional[str]:
    """Extract ``coordination_role`` from a result unit (metadata or direct field).

    Metadata takes priority for backward compatibility.  The direct field is
    consulted only when metadata carries no coordination_role value and the
    direct field was explicitly set by the caller (detected via
    ``model_fields_set`` for Pydantic models).
    """
    if isinstance(unit, dict):
        meta = unit.get("metadata") or {}
        raw_meta = meta.get("coordination_role") if isinstance(meta, dict) else None
        if raw_meta and isinstance(raw_meta, str):
            return raw_meta.strip().lower()
        # Fall back to top-level field (dict key)
        raw_direct = unit.get("coordination_role")
        if raw_direct and isinstance(raw_direct, str):
            return raw_direct.strip().lower()
    else:
        meta = getattr(unit, "metadata", {}) or {}
        raw_meta = meta.get("coordination_role") if isinstance(meta, dict) else None
        if raw_meta and isinstance(raw_meta, str):
            return raw_meta.strip().lower()
        # Fall back to direct attribute when explicitly set
        explicitly_set = False
        fields_set = getattr(unit, "model_fields_set", None)
        if fields_set is not None:
            explicitly_set = "coordination_role" in fields_set
        if explicitly_set:
            raw_direct = getattr(unit, "coordination_role", None)
            if raw_direct and isinstance(raw_direct, str):
                return raw_direct.strip().lower()

    return None


# ---------------------------------------------------------------------------
# merge_session_truth
# ---------------------------------------------------------------------------


def merge_session_truth(
    result_units: Optional[Sequence[Any]] = None,
    *,
    session_id: str = "",
    runtime_attachment_session_id: str = "",
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    source_runtime_posture: Optional[str] = None,
    coordination_role: Optional[str] = None,
    merge_policy: Optional[str] = None,
    primary_result_unit_id: Optional[str] = None,
    merge_reason: Optional[str] = None,
    allow_control_only_as_observer: bool = False,
    exclude_observer_only_role: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
) -> "MergedRuntimeResult":  # type: ignore[name-defined]
    """Compute the canonical session truth by merging posture-filtered result units.

    This is the **primary API** for establishing canonical runtime session truth
    on the main-repo side.  It applies posture-aware filtering
    (:func:`filter_result_units_by_posture`) before delegating to
    :func:`~contracts.cross_runtime_result_merge.merge_runtime_results`.

    Parameters
    ----------
    result_units:
        All result units (local, remote, takeover, multi-device) for this
        session.  ``None`` or empty produces a failed ``MergedRuntimeResult``.
    session_id:
        Legacy runtime session identifier.
    runtime_attachment_session_id:
        Canonical runtime attachment session identifier.  When supplied, this
        takes precedence over ``session_id``.
    task_id:
        Optional task identifier.
    trace_id:
        Optional distributed trace identifier.
    source_runtime_posture:
        Posture of the originating source device.  Controls which units are
        eligible to be considered execution contributors.
        Defaults to ``control_only`` (safe conservative default).
    coordination_role:
        Multi-device coordination role of the originating source device
        (e.g. ``'source_controller'``, ``'joined_runtime_participant'``,
        ``'observer_only'``).  Propagated to the :class:`MergedRuntimeResult`.
        PR-4 / PR-6.
    merge_policy:
        Optional :class:`~contracts.cross_runtime_result_merge.ResultMergePolicy`
        value string.  Defaults to ``primary_wins``.
    primary_result_unit_id:
        Optional hint identifying the preferred primary result unit.
    merge_reason:
        Human-readable reason for this merge.
    allow_control_only_as_observer:
        When ``True``, control_only-tagged units are kept in the merge
        rather than excluded.  Use only when the caller explicitly wants
        observer contributions reflected in the output.
    exclude_observer_only_role:
        When ``True`` (default), units carrying
        ``coordination_role='observer_only'`` are excluded from the merge.
        Policy: :data:`OBSERVER_ONLY_ROLE_EXCLUDED_FROM_MERGE_POLICY`
    metadata:
        Optional additional metadata to attach to the merge output.

    Returns
    -------
    MergedRuntimeResult
        The canonical merged result.  Always returns a result object; never
        raises.

    Policy references
    -----------------
    :data:`POSTURE_AWARE_RESULT_FILTER_POLICY`
    :data:`CONTROL_ONLY_EXCLUDED_FROM_MERGE_POLICY`
    :data:`JOIN_RUNTIME_INCLUDED_IN_MERGE_POLICY`
    :data:`OBSERVER_ONLY_ROLE_EXCLUDED_FROM_MERGE_POLICY`
    """
    from contracts.cross_runtime_result_merge import (
        ResultMergePolicy,
        RuntimeResultUnit,
        merge_runtime_results,
    )

    normalised_posture = _normalise_posture(source_runtime_posture)
    normalised_role = (coordination_role or "").strip().lower()
    resolved_runtime_attachment_session_id = (
        runtime_attachment_session_id or session_id
    )

    # Step 1: posture-aware + coordination-role filter
    kept_units, excluded_ids = filter_result_units_by_posture(
        result_units,
        source_runtime_posture=normalised_posture,
        allow_control_only_as_observer=allow_control_only_as_observer,
        exclude_observer_only_role=exclude_observer_only_role,
    )

    # Step 2: coerce any dict units to RuntimeResultUnit objects so that
    # merge_runtime_results receives properly-typed inputs.
    coerced_units: List[RuntimeResultUnit] = []
    for u in kept_units:
        if isinstance(u, RuntimeResultUnit):
            coerced_units.append(u)
        elif isinstance(u, dict):
            try:
                coerced_units.append(RuntimeResultUnit.model_validate(u))
            except Exception as _coerce_err:
                _logger.warning(
                    "canonical_session_truth: could not coerce dict unit to "
                    "RuntimeResultUnit (%s); skipping unit",
                    _coerce_err,
                )
        # Non-dict, non-RuntimeResultUnit objects are skipped with a warning
        else:
            _logger.warning(
                "canonical_session_truth: unsupported result unit type %r; skipping",
                type(u),
            )

    # Step 3: resolve merge policy
    resolved_policy = ResultMergePolicy.primary_wins
    if merge_policy:
        try:
            resolved_policy = ResultMergePolicy(merge_policy)
        except ValueError:
            _logger.warning(
                "canonical_session_truth: unknown merge_policy %r; "
                "falling back to primary_wins",
                merge_policy,
            )

    # Step 4: delegate to canonical cross-runtime merge
    _meta = dict(metadata or {})
    _meta.setdefault("source_runtime_posture", normalised_posture)
    _meta.setdefault("coordination_role", normalised_role)
    _meta.setdefault("canonical_session_truth_authority", CANONICAL_SESSION_TRUTH_AUTHORITY)
    _meta.setdefault("excluded_unit_ids", excluded_ids)
    _meta.setdefault("pr4_sentinel", CANONICAL_SESSION_TRUTH_PR4_SENTINEL)

    merged = merge_runtime_results(
        result_units=coerced_units or None,
        session_id=resolved_runtime_attachment_session_id,
        task_id=task_id,
        trace_id=trace_id,
        merge_policy=resolved_policy,
        primary_result_unit_id=primary_result_unit_id,
        merge_reason=merge_reason or "canonical_session_truth:pr4",
        source_runtime_posture=normalised_posture,
        coordination_role=normalised_role,
        metadata=_meta,
    )

    return merged


# ---------------------------------------------------------------------------
# record_session_truth
# ---------------------------------------------------------------------------


def record_session_truth(
    *,
    session_id: str = "",
    runtime_attachment_session_id: str = "",
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    source_runtime_posture: Optional[str] = None,
    coordination_role: Optional[str] = None,
    result_units: Optional[Sequence[Any]] = None,
    merge_policy: Optional[str] = None,
    primary_result_unit_id: Optional[str] = None,
    merge_reason: Optional[str] = None,
    allow_control_only_as_observer: bool = False,
    exclude_observer_only_role: bool = True,
    truth_source: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    participant_ownership_boundary: Optional[str] = None,
) -> "CanonicalSessionTruthRecord":
    """Compute and record the canonical session truth, returning the record.

    Combines :func:`merge_session_truth` with :class:`CanonicalSessionTruthRuntime`
    recording in a single call.  Callers that need both the merge output and the
    record can call :func:`merge_session_truth` and :func:`record_session_truth`
    separately, but this convenience function covers the common case.

    Parameters
    ----------
    session_id, task_id, trace_id, source_runtime_posture, result_units,
    merge_policy, primary_result_unit_id, merge_reason,
    allow_control_only_as_observer, exclude_observer_only_role, metadata:
        See :func:`merge_session_truth` for full parameter documentation.
    coordination_role:
        Multi-device coordination role of the originating source device.
        Stored in the :class:`CanonicalSessionTruthRecord`.  PR-4 / PR-6.
    runtime_attachment_session_id:
        Canonical runtime attachment session identifier.  When supplied, this
        takes precedence over ``session_id``.
    truth_source:
        Optional :class:`SessionTruthSource` value string describing the
        dominant origin of the result (``local``, ``remote_handoff``,
        ``takeover``, ``multi_device``, ``mesh``, or ``unknown``).
    participant_ownership_boundary:
        Optional ownership classification from the Android participant truth
        ingress layer.  When set, propagated to the
        :class:`CanonicalSessionTruthRecord` and evaluated at the
        :class:`CanonicalSessionTruthRuntime` admission gate.  Non-canonical
        values (``'participant_local_only'``, ``'fallback_non_canonical'``,
        ``'rejected_non_canonical'``) cause the record to be blocked from
        the canonical ring buffer.  Policy:
        :data:`CANONICAL_TRUTH_ADMITS_ONLY_CANONICALIZED_OWNERSHIP_POLICY`.

    Returns
    -------
    CanonicalSessionTruthRecord
        The recorded truth determination.
    """
    normalised_posture = _normalise_posture(source_runtime_posture)
    normalised_role = (coordination_role or "").strip().lower()
    resolved_runtime_attachment_session_id = (
        runtime_attachment_session_id or session_id
    )
    is_eligible = normalised_posture == _JOIN_RUNTIME

    # Pre-compute filter stats before full merge (cheap)
    kept_units, excluded_ids = filter_result_units_by_posture(
        result_units,
        source_runtime_posture=normalised_posture,
        allow_control_only_as_observer=allow_control_only_as_observer,
        exclude_observer_only_role=exclude_observer_only_role,
    )

    merged = merge_session_truth(
        result_units=result_units,
        session_id=resolved_runtime_attachment_session_id,
        task_id=task_id,
        trace_id=trace_id,
        source_runtime_posture=normalised_posture,
        coordination_role=normalised_role,
        merge_policy=merge_policy,
        primary_result_unit_id=primary_result_unit_id,
        merge_reason=merge_reason,
        allow_control_only_as_observer=allow_control_only_as_observer,
        exclude_observer_only_role=exclude_observer_only_role,
        metadata=metadata,
    )

    # Determine truth_source from merged result if not provided
    resolved_truth_source = truth_source or SessionTruthSource.unknown.value
    if truth_source is None and merged.primary_result_unit_id:
        # Infer from the primary unit's metadata if available
        primary_units = [
            u for u in (kept_units or [])
            if _get_unit_id(u) == merged.primary_result_unit_id
        ]
        if primary_units:
            primary_unit = primary_units[0]
            meta = (
                primary_unit.get("metadata", {})
                if isinstance(primary_unit, dict)
                else getattr(primary_unit, "metadata", {}) or {}
            )
            resolved_truth_source = (
                meta.get("truth_source", SessionTruthSource.unknown.value)
                if isinstance(meta, dict)
                else SessionTruthSource.unknown.value
            )

    normalised_truth_source, truth_source_downgrade_reason = _normalise_truth_source_label(
        resolved_truth_source
    )
    record_metadata = dict(metadata or {})
    if truth_source_downgrade_reason is not None:
        record_metadata.setdefault("truth_source_original", str(resolved_truth_source))
        record_metadata.setdefault("truth_source_normalized", normalised_truth_source)
        record_metadata.setdefault(
            "truth_source_downgrade_reason",
            truth_source_downgrade_reason,
        )
        record_metadata.setdefault(
            "truth_source_downgrade_policy",
            SESSION_TRUTH_SOURCE_MUST_BE_CANONICAL_POLICY,
        )
        record_metadata.setdefault(
            "truth_surface_boundary_policy",
            PROJECTION_INTEROP_COMPAT_NOT_TRUTH_AUTHORITY_POLICY,
        )
    from core.ugcp_truth_event_model import (  # noqa: PLC0415  (lazy import inside function to avoid transitive pydantic dependency at module load time)
        build_session_truth_authoritative_event,
    )
    authoritative_event = build_session_truth_authoritative_event(
        {
            "record_id": "",
            "session_id": resolved_runtime_attachment_session_id,
            "task_id": task_id,
            "trace_id": trace_id,
            "truth_source": normalised_truth_source,
            "merge_success": bool(getattr(merged, "success", False)),
            "primary_unit_id": getattr(merged, "primary_result_unit_id", None),
            "reason": merge_reason or "",
        }
    ).to_truth_event()
    record_metadata.setdefault("truth_event_type", authoritative_event.event_type)
    record_metadata.setdefault(
        "truth_event_surface_class",
        authoritative_event.payload.get("surface_class"),
    )
    record_metadata.setdefault(
        "truth_event_authoritative_transition",
        authoritative_event.payload.get("authoritative_transition"),
    )
    record_metadata.setdefault(
        "truth_event_ordering_key",
        authoritative_event.payload.get("ordering_key"),
    )

    rec = CanonicalSessionTruthRecord(
        session_id=resolved_runtime_attachment_session_id,
        task_id=task_id,
        trace_id=trace_id,
        source_runtime_posture=normalised_posture,
        coordination_role=normalised_role,
        source_eligible=is_eligible,
        total_units_received=len(list(result_units)) if result_units else 0,
        units_after_filter=len(kept_units),
        filtered_unit_ids=list(excluded_ids),
        merge_id=merged.merge_id,
        merge_success=merged.success,
        primary_unit_id=merged.primary_result_unit_id,
        truth_source=normalised_truth_source,
        reason=(
            f"posture={normalised_posture}, "
            f"coordination_role={normalised_role}, "
            f"kept={len(kept_units)}, "
            f"excluded={len(excluded_ids)}, "
            f"merge_success={merged.success}"
        ),
        metadata=record_metadata,
        participant_ownership_boundary=str(participant_ownership_boundary or ""),
    )

    get_canonical_session_truth_runtime().record(rec)
    return rec


# ---------------------------------------------------------------------------
# build_canonical_session_truth_snapshot
# ---------------------------------------------------------------------------


def build_canonical_session_truth_snapshot(
    max_recent: int = 20,
) -> CanonicalSessionTruthSnapshot:
    """Return a :class:`CanonicalSessionTruthSnapshot` from the singleton runtime."""
    return get_canonical_session_truth_runtime().snapshot(max_recent=max_recent)


# Keep a lazy import alias for the return type annotation used above
try:
    from contracts.cross_runtime_result_merge import MergedRuntimeResult  # noqa: F401
except ImportError:
    pass  # Allows module-level import in environments without pydantic
