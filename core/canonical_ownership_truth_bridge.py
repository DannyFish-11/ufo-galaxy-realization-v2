#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/canonical_ownership_truth_bridge.py
=========================================
PR-4V2 Canonical Ownership Truth Bridge — Ownership from Ingress to Truth Continuity Main Chain.

Bridges the ``ownership_context`` produced at the Android participant truth
ingress boundary (``core.android_participant_truth_ingress``) into the deeper
canonical truth / replay / recovery / provenance substrates:

- :class:`~core.canonical_session_truth.CanonicalSessionTruthRecord`
- :class:`~core.replay_foundation.TaskExecutionRecord`
- :class:`~core.replay_foundation.ReplayFoundation` admission behavior
- Recovery eligibility routing

Architecture role
-----------------
::

    Android Participant Truth Ingress
      │  ownership_context {
      │    ownership_status: canonicalized | participant_local_only |
      │                      fallback_non_canonical | rejected_non_canonical
      │    authority_scope: v2_canonical_orchestration | android_participant_local
      │    participant_identity: <device_id>
      │    participant_identity_divergence: bool
      │    canonical_session_identity: {...}
      │    truth_kind: <kind>
      │  }
      │
      ▼
    CanonicalOwnershipTruthBridge  (this module)
      │
      ├─► admit_to_canonical_truth_substrate()
      │     Returns False for non-canonical boundary values.
      │     Gates whether a record enters the canonical ring buffer.
      │
      ├─► build_ownership_aware_session_truth_record()
      │     Constructs a CanonicalSessionTruthRecord with
      │     participant_ownership_boundary populated from ingress context.
      │
      ├─► build_ownership_aware_replay_execution_record()
      │     Constructs a TaskExecutionRecord with
      │     participant_ownership_boundary populated from ingress context.
      │
      └─► record_participant_truth_with_ownership()
            End-to-end bridge: ingress outcome → canonical truth record
            with ownership admission gate enforced.

Design invariants
-----------------
1. **Admission gate.** Only ``'canonicalized'`` ownership records enter the
   canonical ring buffer.  ``'participant_local_only'``,
   ``'fallback_non_canonical'``, and ``'rejected_non_canonical'`` records are
   counted and stored as non-canonical evidence in the durable audit store but
   are never returned by canonical ring buffer read APIs.

2. **Provenance preservation.** Replay execution records carry the ownership
   boundary so that replay/recovery consumers can distinguish canonical
   execution history from participant-local or fallback execution paths.

3. **Recovery eligibility.** Recovery admission functions consult the
   ownership boundary before routing records into canonical recovery paths.
   Non-canonical records are routed to isolated non-canonical recovery paths.

4. **No silent mixing.** ``fallback_non_canonical`` and
   ``rejected_non_canonical`` records are never mixed into canonical truth
   substrates.  They may appear in the durable audit store labelled as
   non-canonical evidence.

Public API
----------
Sentinels::

    CANONICAL_OWNERSHIP_TRUTH_BRIDGE_AUTHORITY
    NON_CANONICAL_TRUTH_EXCLUDED_FROM_CANONICAL_SUBSTRATE_POLICY
    OWNERSHIP_AWARE_REPLAY_RECORD_POLICY
    RECOVERY_ELIGIBILITY_REQUIRES_CANONICAL_OWNERSHIP_POLICY
    CANONICAL_OWNERSHIP_TRUTH_BRIDGE_PR4V2_SENTINEL

Enumerations::

    OwnershipBoundary

Functions::

    extract_ownership_boundary(ownership_context) -> str
    admit_to_canonical_truth_substrate(ownership_boundary) -> bool
    build_ownership_aware_session_truth_record(...) -> CanonicalSessionTruthRecord
    build_ownership_aware_replay_execution_record(...) -> TaskExecutionRecord
    record_participant_truth_with_ownership(...) -> CanonicalSessionTruthRecord
    is_recovery_eligible(ownership_boundary) -> bool
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, Optional, Sequence

__all__ = [
    # Sentinels
    "CANONICAL_OWNERSHIP_TRUTH_BRIDGE_AUTHORITY",
    "NON_CANONICAL_TRUTH_EXCLUDED_FROM_CANONICAL_SUBSTRATE_POLICY",
    "OWNERSHIP_AWARE_REPLAY_RECORD_POLICY",
    "RECOVERY_ELIGIBILITY_REQUIRES_CANONICAL_OWNERSHIP_POLICY",
    "CANONICAL_OWNERSHIP_TRUTH_BRIDGE_PR4V2_SENTINEL",
    # Enumerations
    "OwnershipBoundary",
    # Functions
    "extract_ownership_boundary",
    "admit_to_canonical_truth_substrate",
    "build_ownership_aware_session_truth_record",
    "build_ownership_aware_replay_execution_record",
    "record_participant_truth_with_ownership",
    "is_recovery_eligible",
]

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

CANONICAL_OWNERSHIP_TRUTH_BRIDGE_AUTHORITY: str = (
    "CANONICAL_OWNERSHIP_TRUTH_BRIDGE::PR4V2_AUTHORITY_V1: "
    "core.canonical_ownership_truth_bridge is the canonical authority for "
    "bridging participant ownership context from the Android truth ingress "
    "boundary into the deeper truth/replay/recovery/provenance substrates. "
    "It enforces the ownership admission gate that prevents non-canonical "
    "participant truth from polluting the canonical truth main chain. "
    "(PR-4V2 canonical ownership truth chain)"
)
"""Module-level authority sentinel for the canonical ownership truth bridge."""

NON_CANONICAL_TRUTH_EXCLUDED_FROM_CANONICAL_SUBSTRATE_POLICY: str = (
    "CANONICAL_OWNERSHIP_TRUTH_BRIDGE::NON_CANONICAL_EXCLUDED_POLICY_V1: "
    "Participant truth records with ownership_boundary='participant_local_only', "
    "'fallback_non_canonical', or 'rejected_non_canonical' MUST NOT enter the "
    "canonical truth substrate (CanonicalSessionTruthRuntime ring buffer, "
    "canonical snapshot, or canonical recovery paths).  Only records with "
    "ownership_boundary='canonicalized' or unset (backward-compat) are "
    "eligible for canonical truth admission.  Non-canonical records are "
    "isolated in the durable audit store as non-canonical evidence.  "
    "(PR-4V2 canonical ownership truth chain)"
)
"""Policy: non-canonical participant truth is excluded from canonical substrate."""

OWNERSHIP_AWARE_REPLAY_RECORD_POLICY: str = (
    "CANONICAL_OWNERSHIP_TRUTH_BRIDGE::REPLAY_RECORD_OWNERSHIP_POLICY_V1: "
    "TaskExecutionRecord.participant_ownership_boundary MUST be populated "
    "from the Android participant truth ingress ownership_context when a "
    "replay record is built for an Android-originated truth event.  This "
    "propagates ownership context through the replay substrate so that "
    "replay consumers can distinguish canonical execution from participant-"
    "local or fallback execution paths without re-interrogating the ingress "
    "layer.  (PR-4V2 canonical ownership truth chain)"
)
"""Policy: replay records carry participant ownership boundary from ingress."""

RECOVERY_ELIGIBILITY_REQUIRES_CANONICAL_OWNERSHIP_POLICY: str = (
    "CANONICAL_OWNERSHIP_TRUTH_BRIDGE::RECOVERY_ELIGIBILITY_POLICY_V1: "
    "Recovery paths that restore canonical session state MUST verify that "
    "source records carry ownership_boundary='canonicalized' before admitting "
    "them to the canonical recovery substrate.  Records with "
    "'participant_local_only', 'fallback_non_canonical', or "
    "'rejected_non_canonical' MUST be routed to isolated non-canonical "
    "recovery paths and MUST NOT be treated as authoritative canonical "
    "recovery evidence.  (PR-4V2 canonical ownership truth chain)"
)
"""Policy: canonical recovery requires canonicalized ownership boundary."""

CANONICAL_OWNERSHIP_TRUTH_BRIDGE_PR4V2_SENTINEL: str = (
    "CANONICAL_OWNERSHIP_TRUTH_BRIDGE::PR4V2_INTEGRATED_V1: "
    "PR-4V2 canonical ownership truth bridge is active.  "
    "Participant ownership context from the Android truth ingress boundary "
    "now flows into CanonicalSessionTruthRecord.participant_ownership_boundary "
    "and TaskExecutionRecord.participant_ownership_boundary.  "
    "The CanonicalSessionTruthRuntime admission gate rejects non-canonical "
    "records.  Recovery eligibility is ownership-gated.  "
    "(PR-4V2 canonical ownership truth chain)"
)
"""Integration sentinel confirming the PR-4V2 ownership truth bridge is live."""

# ---------------------------------------------------------------------------
# OwnershipBoundary enumeration
# ---------------------------------------------------------------------------


class OwnershipBoundary(str, Enum):
    """Ownership boundary classification for participant-originated truth records.

    These values map directly to the ``ownership_status`` produced by
    :func:`~core.android_participant_truth_ingress._build_ownership_context`.

    Attributes
    ----------
    canonicalized:
        The participant truth was reconciled and promoted to canonical V2
        orchestration state.  Eligible for canonical truth admission.
    participant_local_only:
        The participant truth is valid but scoped to the Android device's
        local state only.  NOT eligible for canonical truth admission.
    fallback_non_canonical:
        The participant truth used a compat/fallback path.  NOT eligible for
        canonical truth admission.
    rejected_non_canonical:
        The participant truth was rejected (e.g. identity divergence, missing
        identity, terminal state conflict).  NOT eligible for canonical truth
        admission.
    unset:
        No ownership context was provided (backward-compatibility).  Treated
        as eligible by default to avoid breaking pre-ownership-chain callers.
    """

    canonicalized = "canonicalized"
    participant_local_only = "participant_local_only"
    fallback_non_canonical = "fallback_non_canonical"
    rejected_non_canonical = "rejected_non_canonical"
    unset = ""


# Boundary values that exclude a record from canonical truth admission.
_NON_CANONICAL_BOUNDARIES: frozenset = frozenset(
    {
        OwnershipBoundary.participant_local_only.value,
        OwnershipBoundary.fallback_non_canonical.value,
        OwnershipBoundary.rejected_non_canonical.value,
    }
)

# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def extract_ownership_boundary(ownership_context: Optional[Dict[str, Any]]) -> str:
    """Extract the ``ownership_status`` string from an ingress ``ownership_context``.

    Parameters
    ----------
    ownership_context:
        The dict produced by
        :func:`~core.android_participant_truth_ingress._build_ownership_context`,
        typically accessed as ``AndroidParticipantReconcileOutcome.ownership_context``.
        May be ``None`` or empty.

    Returns
    -------
    str
        The ``ownership_status`` value, or ``''`` when the context is absent
        or the field is missing.
    """
    if not ownership_context:
        return ""
    return str(ownership_context.get("ownership_status") or "")


def admit_to_canonical_truth_substrate(ownership_boundary: str) -> bool:
    """Determine whether a record with *ownership_boundary* may enter the canonical substrate.

    Parameters
    ----------
    ownership_boundary:
        The ownership boundary value from an ingress
        :class:`~core.android_participant_truth_ingress.AndroidParticipantReconcileOutcome`.

    Returns
    -------
    bool
        ``True`` when the record is eligible for canonical truth admission
        (``'canonicalized'`` or ``''`` / unset).
        ``False`` when the record must be excluded
        (``'participant_local_only'``, ``'fallback_non_canonical'``,
        ``'rejected_non_canonical'``).

    Policy
    ------
    :data:`NON_CANONICAL_TRUTH_EXCLUDED_FROM_CANONICAL_SUBSTRATE_POLICY`
    """
    return ownership_boundary not in _NON_CANONICAL_BOUNDARIES


def is_recovery_eligible(ownership_boundary: str) -> bool:
    """Return ``True`` when *ownership_boundary* allows canonical recovery admission.

    Non-canonical ownership boundaries must not be routed into canonical
    recovery paths.

    Parameters
    ----------
    ownership_boundary:
        The ownership boundary value, e.g. from
        :func:`extract_ownership_boundary`.

    Returns
    -------
    bool
        ``True`` only when *ownership_boundary* is ``'canonicalized'`` or
        ``''`` (unset / backward-compat).

    Policy
    ------
    :data:`RECOVERY_ELIGIBILITY_REQUIRES_CANONICAL_OWNERSHIP_POLICY`
    """
    return ownership_boundary not in _NON_CANONICAL_BOUNDARIES


# ---------------------------------------------------------------------------
# build_ownership_aware_session_truth_record
# ---------------------------------------------------------------------------


def build_ownership_aware_session_truth_record(
    *,
    session_id: str = "",
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    source_runtime_posture: Optional[str] = None,
    coordination_role: Optional[str] = None,
    result_units: Optional[Sequence[Any]] = None,
    merge_reason: Optional[str] = None,
    truth_source: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    ownership_context: Optional[Dict[str, Any]] = None,
    participant_ownership_boundary: Optional[str] = None,
) -> Any:
    """Build and record an ownership-aware :class:`~core.canonical_session_truth.CanonicalSessionTruthRecord`.

    Combines :func:`~core.canonical_session_truth.record_session_truth` with
    the ownership admission gate.  The ``participant_ownership_boundary`` is
    extracted from *ownership_context* (if provided) or taken directly from
    *participant_ownership_boundary*.

    When the resolved boundary is non-canonical (``'participant_local_only'``,
    ``'fallback_non_canonical'``, or ``'rejected_non_canonical'``), the record
    is still constructed and returned, but the
    :class:`~core.canonical_session_truth.CanonicalSessionTruthRuntime`
    admission gate will block it from entering the canonical ring buffer.

    Parameters
    ----------
    session_id, task_id, trace_id, source_runtime_posture, coordination_role,
    result_units, merge_reason, truth_source, metadata:
        Forwarded to :func:`~core.canonical_session_truth.record_session_truth`.
    ownership_context:
        The ``ownership_context`` dict from an
        :class:`~core.android_participant_truth_ingress.AndroidParticipantReconcileOutcome`.
        The ``ownership_status`` value is extracted and used as
        ``participant_ownership_boundary`` when *participant_ownership_boundary*
        is not explicitly provided.
    participant_ownership_boundary:
        Explicit override for the ownership boundary.  When provided, takes
        precedence over the value extracted from *ownership_context*.

    Returns
    -------
    CanonicalSessionTruthRecord
        The constructed (and conditionally admitted) truth record.
    """
    from core.canonical_session_truth import (  # noqa: PLC0415
        CanonicalSessionTruthRecord,
        get_canonical_session_truth_runtime,
    )

    resolved_boundary = participant_ownership_boundary
    if resolved_boundary is None and ownership_context:
        resolved_boundary = extract_ownership_boundary(ownership_context)

    _meta = dict(metadata or {})
    if ownership_context:
        _meta.setdefault("ownership_context", ownership_context)
    if resolved_boundary is not None:
        _meta.setdefault("participant_ownership_boundary", resolved_boundary)
        _meta.setdefault(
            "ownership_admission_eligible",
            admit_to_canonical_truth_substrate(resolved_boundary),
        )
        _meta.setdefault(
            "ownership_admission_policy",
            NON_CANONICAL_TRUTH_EXCLUDED_FROM_CANONICAL_SUBSTRATE_POLICY,
        )

    rec = CanonicalSessionTruthRecord(
        session_id=session_id,
        task_id=task_id or "",
        trace_id=trace_id or "",
        source_runtime_posture=source_runtime_posture or "",
        coordination_role=coordination_role or "",
        truth_source=truth_source or "",
        metadata=_meta,
        participant_ownership_boundary=resolved_boundary or "",
    )
    get_canonical_session_truth_runtime().record(rec)
    return rec


# ---------------------------------------------------------------------------
# build_ownership_aware_replay_execution_record
# ---------------------------------------------------------------------------


def build_ownership_aware_replay_execution_record(
    base_record: Any,
    ownership_context: Optional[Dict[str, Any]] = None,
    participant_ownership_boundary: Optional[str] = None,
) -> Any:
    """Return a copy of *base_record* with ``participant_ownership_boundary`` populated.

    Creates a new :class:`~core.replay_foundation.TaskExecutionRecord` that
    is identical to *base_record* except that ``participant_ownership_boundary``
    is set from *ownership_context* or *participant_ownership_boundary*.

    This is the primary mechanism for propagating ownership context from the
    Android participant truth ingress layer into the replay substrate.

    Parameters
    ----------
    base_record:
        A :class:`~core.replay_foundation.TaskExecutionRecord` to copy.
    ownership_context:
        The ``ownership_context`` dict from an
        :class:`~core.android_participant_truth_ingress.AndroidParticipantReconcileOutcome`.
        The ``ownership_status`` value is extracted as the boundary when
        *participant_ownership_boundary* is not explicitly provided.
    participant_ownership_boundary:
        Explicit override.  When provided, takes precedence over the value
        extracted from *ownership_context*.

    Returns
    -------
    TaskExecutionRecord
        A new record with ``participant_ownership_boundary`` set.  The
        original *base_record* is not mutated.

    Policy
    ------
    :data:`OWNERSHIP_AWARE_REPLAY_RECORD_POLICY`
    """
    from core.replay_foundation import TaskExecutionRecord  # noqa: PLC0415

    resolved_boundary = participant_ownership_boundary
    if resolved_boundary is None and ownership_context:
        resolved_boundary = extract_ownership_boundary(ownership_context)

    try:
        d = base_record.to_dict()
        d["participant_ownership_boundary"] = resolved_boundary or ""
        return TaskExecutionRecord.from_dict(d)
    except Exception as exc:
        _logger.warning(
            "build_ownership_aware_replay_execution_record: failed to copy record: %s",
            exc,
        )
        return base_record


# ---------------------------------------------------------------------------
# record_participant_truth_with_ownership
# ---------------------------------------------------------------------------


def record_participant_truth_with_ownership(
    outcome: Any,
    *,
    task_id: Optional[str] = None,
    result_units: Optional[Sequence[Any]] = None,
    merge_reason: Optional[str] = None,
    truth_source: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Any:
    """Bridge an :class:`~core.android_participant_truth_ingress.AndroidParticipantReconcileOutcome`
    into a :class:`~core.canonical_session_truth.CanonicalSessionTruthRecord`.

    This is the end-to-end bridge entry point.  It:

    1. Extracts ownership context from *outcome*.
    2. Determines the ``participant_ownership_boundary``.
    3. Calls :func:`build_ownership_aware_session_truth_record` which:
       a. Builds the :class:`~core.canonical_session_truth.CanonicalSessionTruthRecord`
          with the ownership boundary populated.
       b. Submits to :class:`~core.canonical_session_truth.CanonicalSessionTruthRuntime`
          which applies the admission gate — non-canonical records are blocked.

    The returned record reflects the truth determination and ownership
    boundary.  When the record was blocked by the admission gate, it is
    still returned (for caller inspection) but was **not** added to the
    canonical ring buffer.

    Parameters
    ----------
    outcome:
        An :class:`~core.android_participant_truth_ingress.AndroidParticipantReconcileOutcome`
        instance (or any object exposing ``.ownership_context``,
        ``.session_id``, ``.envelope``, ``.was_reconciled``).
    task_id:
        Optional task identifier to attach to the truth record.
    result_units:
        Optional result units to merge into the truth record.
    merge_reason:
        Optional human-readable reason for the merge.
    truth_source:
        Optional :class:`~core.canonical_session_truth.SessionTruthSource`
        value string.
    metadata:
        Optional additional metadata.

    Returns
    -------
    CanonicalSessionTruthRecord
        The constructed (and conditionally admitted) canonical session truth record.
    """
    ownership_context: Dict[str, Any] = {}
    try:
        ownership_context = dict(outcome.ownership_context or {})
    except Exception:
        pass

    session_id = ""
    try:
        session_id = str(outcome.envelope.session_id or "")
    except Exception:
        pass

    trace_id = None
    try:
        trace_id = outcome.envelope.trace_id or None
    except Exception:
        pass

    boundary = extract_ownership_boundary(ownership_context)
    _logger.debug(
        "record_participant_truth_with_ownership: session=%r, task=%r, "
        "ownership_boundary=%r, canonical_eligible=%s",
        session_id,
        task_id,
        boundary,
        admit_to_canonical_truth_substrate(boundary),
    )

    return build_ownership_aware_session_truth_record(
        session_id=session_id,
        task_id=task_id,
        trace_id=trace_id,
        result_units=result_units,
        merge_reason=merge_reason or f"participant_ownership_bridge:{boundary or 'unset'}",
        truth_source=truth_source,
        metadata=metadata,
        ownership_context=ownership_context,
        participant_ownership_boundary=boundary,
    )
