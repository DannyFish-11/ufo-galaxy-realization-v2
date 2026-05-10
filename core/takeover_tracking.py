"""core/takeover_tracking.py
============================
Canonical Takeover Accept/Reject Tracking for Android Delegated Runtime.

Background
----------
The ``galaxy_gateway.android.handlers.takeover_response`` handler receives
``TAKEOVER_RESPONSE`` messages from the Android runtime and previously
attempted to import this module to persist the accept/reject decision into a
tracking store.  Without this module the import silently degraded and the
takeover decision was never written to a canonical record, leaving the V2
orchestration layer unable to determine whether a given takeover was accepted
or rejected without re-processing the raw audit log.

This module closes that gap by providing:

1. :class:`TakeoverDecision` — canonical enum for the Android response to a
   V2-issued ``TAKEOVER_REQUEST`` (``accepted`` / ``rejected`` / ``unknown``).

2. :class:`TakeoverTrackingRecord` — typed, immutable record that captures the
   full takeover-response context:

   * ``takeover_id`` — correlation key matching the V2-issued
     ``TAKEOVER_REQUEST``.
   * ``device_id`` — Android device that responded.
   * ``decision`` — canonical :class:`TakeoverDecision`.
   * ``session_id`` — attached-runtime session at the time of the response.
   * ``task_id`` / ``trace_id`` — optional correlation fields.
   * ``reason`` — optional human-readable reason string supplied by the
     Android runtime.
   * ``recorded_at`` — wall-clock timestamp of when V2 ingested the response.

3. :class:`TakeoverTrackingRuntime` — in-process ring buffer (size 256)
   accumulating :class:`TakeoverTrackingRecord` instances.  Provides query
   helpers:

   * ``get_by_takeover_id(takeover_id)`` — most recent record for a
     ``takeover_id``.
   * ``get_by_session_id(session_id)`` — all records for a ``session_id``,
     newest-first.
   * ``snapshot()`` — list of all records in the ring, newest-first.

4. :func:`record_takeover_response` — the canonical recording entry-point
   expected by ``galaxy_gateway.android.handlers.takeover_response``.

5. :func:`get_takeover_tracking_runtime` /
   :func:`reset_takeover_tracking_runtime` — singleton accessor and
   test-isolation helper.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Non-raising** — :func:`record_takeover_response` never raises; errors are
  logged at DEBUG level and silently swallowed.
- **Thread-safe** — all mutations to the ring buffer are protected by a
  ``threading.Lock``.
- **Queryable by takeover_id and session_id** — the two most common lookup
  patterns for takeover-response reconciliation are provided as first-class
  queries.
- **JSON-serialisable** — :class:`TakeoverTrackingRecord` exposes
  ``to_dict()`` / ``to_json()`` for wire/audit surfacing.

Authority sentinel
------------------
``TAKEOVER_TRACKING_AUTHORITY`` — import to assert that this module is the
canonical tracking layer for Android takeover responses.

Public API
----------
Sentinels::

    TAKEOVER_TRACKING_AUTHORITY
    TAKEOVER_TRACKING_CONTRACT_VERSION

Enum::

    TakeoverDecision

Dataclasses::

    TakeoverTrackingRecord
    TakeoverTrackingSnapshot

Class::

    TakeoverTrackingRuntime

Functions::

    record_takeover_response(*, takeover_id, device_id, accepted, ...)
        -> TakeoverTrackingRecord
    get_takeover_tracking_runtime() -> TakeoverTrackingRuntime
    reset_takeover_tracking_runtime() -> None
    get_takeover_record(takeover_id, ...) -> TakeoverTrackingRecord | None
    adjudicate_takeover_ownership_convergence(...) -> TakeoverOwnershipConvergenceVerdict
    list_takeover_records_for_session(session_id, ...) -> list[TakeoverTrackingRecord]
    takeover_tracking_snapshot(...) -> TakeoverTrackingSnapshot
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

logger = logging.getLogger("Galaxy.TakeoverTracking")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

TAKEOVER_TRACKING_AUTHORITY: str = (
    "TAKEOVER_TRACKING_AUTHORITY::"
    "core.takeover_tracking is the canonical authority for V2-side "
    "Android takeover accept/reject tracking.  "
    "record_takeover_response() is the single entry-point for persisting "
    "takeover decisions into the V2 process-local ring buffer."
)

TAKEOVER_TRACKING_CONTRACT_VERSION: str = "1.0"

# Policy sentinels

TAKEOVER_RECORD_IS_IMMUTABLE_POLICY: str = (
    "POLICY::TAKEOVER_RECORD_IS_IMMUTABLE: TakeoverTrackingRecord instances "
    "are frozen dataclasses.  Once created they must not be mutated.  A new "
    "record must be created if a correction is needed (e.g. late rejection)."
)

TAKEOVER_TRACKING_NON_RAISING_POLICY: str = (
    "POLICY::TAKEOVER_TRACKING_NON_RAISING: record_takeover_response() MUST "
    "NOT raise under any circumstances.  All exceptions are caught, logged at "
    "DEBUG level, and swallowed.  Gateway handlers must remain stable even if "
    "the tracking layer encounters an error."
)

TAKEOVER_ID_IS_CORRELATION_KEY_POLICY: str = (
    "POLICY::TAKEOVER_ID_IS_CORRELATION_KEY: takeover_id is the primary "
    "correlation key linking the V2-issued TAKEOVER_REQUEST to the Android "
    "TAKEOVER_RESPONSE.  get_takeover_record() looks up by takeover_id first; "
    "session_id is a secondary index only."
)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_RING_BUFFER_CAPACITY: int = 256

# ---------------------------------------------------------------------------
# TakeoverDecision enum
# ---------------------------------------------------------------------------


class TakeoverDecision(str, Enum):
    """Canonical enum for the Android TAKEOVER_RESPONSE decision.

    Values
    ------
    accepted
        The Android runtime accepted the TAKEOVER_REQUEST.
    rejected
        The Android runtime rejected the TAKEOVER_REQUEST.
    unknown
        The decision could not be determined from the response payload.
    """

    accepted = "accepted"
    rejected = "rejected"
    unknown = "unknown"

    @classmethod
    def from_bool(cls, accepted: bool) -> "TakeoverDecision":
        """Return ``accepted`` or ``rejected`` based on a boolean flag."""
        return cls.accepted if accepted else cls.rejected

    @classmethod
    def from_string(cls, value: str) -> "TakeoverDecision":
        """Return the enum member matching *value*, defaulting to ``unknown``."""
        if not isinstance(value, str):
            return cls.unknown
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.unknown


class TakeoverOwnershipState(str, Enum):
    """Canonical ownership convergence states derived from takeover evidence."""

    delegated_takeover_confirmed = "delegated_takeover_confirmed"
    resumed_v2_ownership_confirmed = "resumed_v2_ownership_confirmed"
    unresolved = "unresolved"
    degraded_incomplete_evidence = "degraded_incomplete_evidence"
    degraded_conflicting_evidence = "degraded_conflicting_evidence"


class TakeoverEvidenceQuality(str, Enum):
    """Proof quality for ownership convergence adjudication."""

    strong = "strong"
    partial = "partial"
    missing = "missing"
    conflicting = "conflicting"


# ---------------------------------------------------------------------------
# TakeoverTrackingRecord
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TakeoverTrackingRecord:
    """Immutable record for a single Android TAKEOVER_RESPONSE.

    Attributes
    ----------
    record_id
        Stable UUID for this record entry.
    takeover_id
        Correlation key matching the V2-issued ``TAKEOVER_REQUEST``.
    device_id
        Android device identifier.
    decision
        :class:`TakeoverDecision` — accepted or rejected.
    session_id
        Attached-runtime session id at the time of the response.
    task_id
        Optional task identifier for cross-domain correlation.
    trace_id
        Optional distributed trace identifier.
    reason
        Optional human-readable reason string from the Android runtime.
    recorded_at
        Wall-clock timestamp (``time.time()``) when V2 ingested the response.
    metadata
        Opaque key/value pairs for extensibility.
    """

    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    takeover_id: str = ""
    device_id: str = ""
    decision: TakeoverDecision = TakeoverDecision.unknown
    session_id: str = ""
    task_id: str = ""
    trace_id: str = ""
    reason: str = ""
    recorded_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Derived convenience properties

    @property
    def was_accepted(self) -> bool:
        """Return True when the takeover was accepted."""
        return self.decision == TakeoverDecision.accepted

    @property
    def was_rejected(self) -> bool:
        """Return True when the takeover was rejected."""
        return self.decision == TakeoverDecision.rejected

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "record_id": self.record_id,
            "takeover_id": self.takeover_id,
            "device_id": self.device_id,
            "decision": self.decision.value,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "reason": self.reason,
            "recorded_at": self.recorded_at,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# TakeoverTrackingSnapshot
# ---------------------------------------------------------------------------


@dataclass
class TakeoverTrackingSnapshot:
    """Point-in-time snapshot of all takeover-response tracking records.

    Attributes
    ----------
    records
        List of :class:`TakeoverTrackingRecord`, newest-first.
    total_count
        Total number of records in this snapshot.
    """

    records: List[TakeoverTrackingRecord] = field(default_factory=list)
    total_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "records": [r.to_dict() for r in self.records],
            "total_count": self.total_count,
        }


@dataclass(frozen=True)
class TakeoverOwnershipConvergenceVerdict:
    """Ownership convergence verdict derived from takeover execution evidence."""

    takeover_id: str = ""
    session_id: str = ""
    device_id: str = ""
    ownership_state: TakeoverOwnershipState = TakeoverOwnershipState.unresolved
    evidence_quality: TakeoverEvidenceQuality = TakeoverEvidenceQuality.missing
    is_converged: bool = False
    degraded: bool = True
    diagnosis: List[str] = field(default_factory=list)
    latest_decision: TakeoverDecision = TakeoverDecision.unknown
    total_records: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    unknown_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "takeover_id": self.takeover_id,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "ownership_state": self.ownership_state.value,
            "evidence_quality": self.evidence_quality.value,
            "is_converged": self.is_converged,
            "degraded": self.degraded,
            "diagnosis": list(self.diagnosis),
            "latest_decision": self.latest_decision.value,
            "total_records": self.total_records,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "unknown_count": self.unknown_count,
        }


# ---------------------------------------------------------------------------
# TakeoverTrackingRuntime — in-process ring buffer
# ---------------------------------------------------------------------------


class TakeoverTrackingRuntime:
    """In-process ring buffer accumulating :class:`TakeoverTrackingRecord` instances.

    Thread-safe.  Capacity is fixed at :data:`_RING_BUFFER_CAPACITY` (256).
    All mutations are protected by an internal ``threading.Lock``.
    """

    def __init__(self, capacity: int = _RING_BUFFER_CAPACITY) -> None:
        self._capacity = capacity
        self._ring: Deque[TakeoverTrackingRecord] = deque(maxlen=capacity)
        self._lock: threading.Lock = threading.Lock()

    def record(self, rec: TakeoverTrackingRecord) -> None:
        """Append *rec* to the ring buffer."""
        with self._lock:
            self._ring.appendleft(rec)

    def get_by_takeover_id(self, takeover_id: str) -> Optional[TakeoverTrackingRecord]:
        """Return the most recent record with ``takeover_id == takeover_id``."""
        with self._lock:
            for rec in self._ring:
                if rec.takeover_id == takeover_id:
                    return rec
        return None

    def list_by_takeover_id(self, takeover_id: str) -> List[TakeoverTrackingRecord]:
        """Return all records with ``takeover_id == takeover_id``.

        Records are returned in ring-buffer order, which is newest-first
        because :meth:`record` writes using ``appendleft``.
        """
        with self._lock:
            return [r for r in self._ring if r.takeover_id == takeover_id]

    def get_by_session_id(self, session_id: str) -> List[TakeoverTrackingRecord]:
        """Return all records for *session_id*, newest-first."""
        with self._lock:
            return [r for r in self._ring if r.session_id == session_id]

    def snapshot(self) -> TakeoverTrackingSnapshot:
        """Return a point-in-time snapshot of the ring buffer."""
        with self._lock:
            records = list(self._ring)
        return TakeoverTrackingSnapshot(records=records, total_count=len(records))


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_singleton_lock: threading.Lock = threading.Lock()
_singleton: Optional[TakeoverTrackingRuntime] = None


def get_takeover_tracking_runtime() -> TakeoverTrackingRuntime:
    """Return the process-wide singleton :class:`TakeoverTrackingRuntime`."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = TakeoverTrackingRuntime()
    return _singleton


def reset_takeover_tracking_runtime() -> None:
    """Reset the singleton (test-isolation helper only)."""
    global _singleton
    with _singleton_lock:
        _singleton = None


# ---------------------------------------------------------------------------
# Public recording entry-point
# ---------------------------------------------------------------------------


def record_takeover_response(
    *,
    takeover_id: str,
    device_id: str,
    accepted: bool,
    reason: str = "",
    session_id: Optional[str] = None,
    task_id: str = "",
    trace_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    runtime: Optional[TakeoverTrackingRuntime] = None,
) -> TakeoverTrackingRecord:
    """Record an Android TAKEOVER_RESPONSE in the process-local ring buffer.

    This is the canonical recording entry-point called by
    ``galaxy_gateway.android.handlers.takeover_response``.  It never raises.

    Parameters
    ----------
    takeover_id:
        Correlation key matching the V2-issued ``TAKEOVER_REQUEST``.
    device_id:
        Android device identifier.
    accepted:
        ``True`` if the Android runtime accepted the takeover; ``False`` if
        rejected.
    reason:
        Optional human-readable reason from the Android runtime.
    session_id:
        Optional attached-runtime session id.
    task_id:
        Optional task identifier.
    trace_id:
        Optional distributed trace identifier.
    metadata:
        Optional extra key/value pairs.
    runtime:
        Optional :class:`TakeoverTrackingRuntime` override (for tests).

    Returns
    -------
    TakeoverTrackingRecord
        The record that was created and persisted.
    """
    try:
        decision = TakeoverDecision.from_bool(accepted)
        rec = TakeoverTrackingRecord(
            takeover_id=takeover_id or "",
            device_id=device_id or "",
            decision=decision,
            session_id=session_id or "",
            task_id=task_id or "",
            trace_id=trace_id or "",
            reason=reason or "",
            metadata=dict(metadata) if metadata else {},
        )
        _rt = runtime if runtime is not None else get_takeover_tracking_runtime()
        _rt.record(rec)
        logger.debug(
            "takeover_tracking: recorded takeover_id=%r device_id=%s decision=%s",
            takeover_id,
            device_id,
            decision.value,
        )
        return rec
    except Exception as exc:  # noqa: BLE001
        logger.debug("takeover_tracking: record_takeover_response failed (non-fatal): %s", exc)
        # Return a minimal fallback record to ensure callers always receive a typed result
        try:
            return TakeoverTrackingRecord(
                takeover_id=takeover_id or "",
                device_id=device_id or "",
                decision=TakeoverDecision.unknown,
            )
        except Exception:  # noqa: BLE001
            return TakeoverTrackingRecord()


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def get_takeover_record(
    takeover_id: str,
    *,
    runtime: Optional[TakeoverTrackingRuntime] = None,
) -> Optional[TakeoverTrackingRecord]:
    """Return the most recent :class:`TakeoverTrackingRecord` for *takeover_id*.

    Returns ``None`` if no matching record is found.
    """
    try:
        _rt = runtime if runtime is not None else get_takeover_tracking_runtime()
        return _rt.get_by_takeover_id(takeover_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("takeover_tracking: get_takeover_record failed: %s", exc)
        return None


def list_takeover_records_for_session(
    session_id: str,
    *,
    runtime: Optional[TakeoverTrackingRuntime] = None,
) -> List[TakeoverTrackingRecord]:
    """Return all :class:`TakeoverTrackingRecord` instances for *session_id*,
    newest-first.

    Returns an empty list on error.
    """
    try:
        _rt = runtime if runtime is not None else get_takeover_tracking_runtime()
        return _rt.get_by_session_id(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "takeover_tracking: list_takeover_records_for_session failed: %s", exc
        )
        return []


def adjudicate_takeover_ownership_convergence(
    *,
    takeover_id: str,
    session_id: str = "",
    device_id: str = "",
    runtime: Optional[TakeoverTrackingRuntime] = None,
) -> TakeoverOwnershipConvergenceVerdict:
    """Adjudicate ownership convergence for a takeover from recorded evidence."""
    try:
        _rt = runtime if runtime is not None else get_takeover_tracking_runtime()
        records = _rt.list_by_takeover_id(takeover_id or "") if takeover_id else []
        diagnosis: List[str] = []
        has_missing_takeover_id = not takeover_id
        has_missing_session_id = not session_id
        has_missing_device_id = not device_id
        has_missing_takeover_record = not records

        if has_missing_takeover_id:
            diagnosis.append("missing_takeover_id")
        if has_missing_session_id:
            diagnosis.append("missing_session_id")
        if has_missing_device_id:
            diagnosis.append("missing_device_id")
        if has_missing_takeover_record:
            diagnosis.append("missing_takeover_record")

        accepted_count = sum(1 for r in records if r.decision == TakeoverDecision.accepted)
        rejected_count = sum(1 for r in records if r.decision == TakeoverDecision.rejected)
        unknown_count = sum(1 for r in records if r.decision == TakeoverDecision.unknown)
        latest_decision = TakeoverDecision.unknown
        if records:
            latest_decision = records[0].decision

        has_session_id_conflict = bool(
            session_id
            and records
            and any(r.session_id and r.session_id != session_id for r in records)
        )
        has_device_id_conflict = bool(
            device_id
            and records
            and any(r.device_id and r.device_id != device_id for r in records)
        )
        if has_session_id_conflict:
            diagnosis.append("session_id_conflict")
        if has_device_id_conflict:
            diagnosis.append("device_id_conflict")
        has_multiple_session_ids = len({r.session_id for r in records if r.session_id}) > 1
        has_multiple_device_ids = len({r.device_id for r in records if r.device_id}) > 1
        if has_multiple_session_ids:
            diagnosis.append("multiple_session_ids_for_takeover_id")
        if has_multiple_device_ids:
            diagnosis.append("multiple_device_ids_for_takeover_id")

        has_conflict = accepted_count > 0 and rejected_count > 0
        if has_conflict:
            diagnosis.append("conflicting_takeover_decisions")

        has_missing = (
            has_missing_takeover_id
            or has_missing_session_id
            or has_missing_device_id
            or has_missing_takeover_record
        )
        has_identity_conflict = (
            has_session_id_conflict
            or has_device_id_conflict
            or has_multiple_session_ids
            or has_multiple_device_ids
        )
        if has_conflict or has_identity_conflict:
            return TakeoverOwnershipConvergenceVerdict(
                takeover_id=takeover_id or "",
                session_id=session_id or "",
                device_id=device_id or "",
                ownership_state=TakeoverOwnershipState.degraded_conflicting_evidence,
                evidence_quality=TakeoverEvidenceQuality.conflicting,
                is_converged=False,
                degraded=True,
                diagnosis=diagnosis,
                latest_decision=latest_decision,
                total_records=len(records),
                accepted_count=accepted_count,
                rejected_count=rejected_count,
                unknown_count=unknown_count,
            )

        if has_missing:
            return TakeoverOwnershipConvergenceVerdict(
                takeover_id=takeover_id or "",
                session_id=session_id or "",
                device_id=device_id or "",
                ownership_state=TakeoverOwnershipState.degraded_incomplete_evidence,
                evidence_quality=TakeoverEvidenceQuality.partial if records else TakeoverEvidenceQuality.missing,
                is_converged=False,
                degraded=True,
                diagnosis=diagnosis,
                latest_decision=latest_decision,
                total_records=len(records),
                accepted_count=accepted_count,
                rejected_count=rejected_count,
                unknown_count=unknown_count,
            )

        if latest_decision == TakeoverDecision.accepted:
            diagnosis.append("delegated_takeover_completion_confirmed")
            return TakeoverOwnershipConvergenceVerdict(
                takeover_id=takeover_id,
                session_id=session_id,
                device_id=device_id,
                ownership_state=TakeoverOwnershipState.delegated_takeover_confirmed,
                evidence_quality=TakeoverEvidenceQuality.strong,
                is_converged=True,
                degraded=False,
                diagnosis=diagnosis,
                latest_decision=latest_decision,
                total_records=len(records),
                accepted_count=accepted_count,
                rejected_count=rejected_count,
                unknown_count=unknown_count,
            )

        if latest_decision == TakeoverDecision.rejected:
            diagnosis.append("resumed_v2_ownership_transfer_confirmed")
            return TakeoverOwnershipConvergenceVerdict(
                takeover_id=takeover_id,
                session_id=session_id,
                device_id=device_id,
                ownership_state=TakeoverOwnershipState.resumed_v2_ownership_confirmed,
                evidence_quality=TakeoverEvidenceQuality.strong,
                is_converged=True,
                degraded=False,
                diagnosis=diagnosis,
                latest_decision=latest_decision,
                total_records=len(records),
                accepted_count=accepted_count,
                rejected_count=rejected_count,
                unknown_count=unknown_count,
            )

        diagnosis.append("latest_takeover_decision_unknown")
        return TakeoverOwnershipConvergenceVerdict(
            takeover_id=takeover_id,
            session_id=session_id,
            device_id=device_id,
            ownership_state=TakeoverOwnershipState.unresolved,
            evidence_quality=TakeoverEvidenceQuality.partial,
            is_converged=False,
            degraded=True,
            diagnosis=diagnosis,
            latest_decision=latest_decision,
            total_records=len(records),
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            unknown_count=unknown_count,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "takeover_tracking: adjudicate_takeover_ownership_convergence failed: "
            "takeover_id=%r session_id=%r device_id=%r exc=%s",
            takeover_id,
            session_id,
            device_id,
            exc,
        )
        return TakeoverOwnershipConvergenceVerdict(
            takeover_id=takeover_id or "",
            session_id=session_id or "",
            device_id=device_id or "",
            ownership_state=TakeoverOwnershipState.degraded_incomplete_evidence,
            evidence_quality=TakeoverEvidenceQuality.missing,
            is_converged=False,
            degraded=True,
            diagnosis=["adjudication_error"],
        )


def takeover_tracking_snapshot(
    *,
    runtime: Optional[TakeoverTrackingRuntime] = None,
) -> TakeoverTrackingSnapshot:
    """Return a :class:`TakeoverTrackingSnapshot` of the ring buffer."""
    try:
        _rt = runtime if runtime is not None else get_takeover_tracking_runtime()
        return _rt.snapshot()
    except Exception as exc:  # noqa: BLE001
        logger.debug("takeover_tracking: takeover_tracking_snapshot failed: %s", exc)
        return TakeoverTrackingSnapshot()
