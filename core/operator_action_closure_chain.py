"""core/operator_action_closure_chain.py
========================================
任务6 (Task-6) V2-side — Operator / Control-Plane Closure Loop
================================================================

Background
----------
After PR-1 through PR-5 the system has a solid **observation** surface
(operator board projection, multi-subject truth bridge, Android evidence
ingress) but the **governance** side is incomplete:

* Operator actions are dispatched and audited, but there is no single
  canonical record tracking the full lifecycle of one action from dispatch
  through every subject's acknowledgement, truth convergence, to a final
  closure verdict.
* Multi-subject actions (involving more than one device/participant) have
  no unified ack-collection or convergence point.
* Closure verification is not explicitly surfaced to the operator.

This module provides the **minimal canonical action → ack → truth →
closure chain** for the operator / control plane.  It does NOT replace
any existing module; it WIRES together:

* :mod:`core.operator_action_contract`  — action entry wire types
* :mod:`core.pr4_operator_action_governance` — audit records & Android ack
* :mod:`core.multi_subject_truth_convergence_bridge` — participant truth
* canonical governance constraints (operator must not be authority center)

Design invariants
-----------------
I-C1  Every operator action that enters the chain MUST have a unique
      ``action_id`` and be traceable end-to-end.
I-C2  Operator / control plane MUST NOT become a new authority center;
      all closure decisions are derived from canonical truth, not from
      the operator plane itself.
I-C3  Subject acks are *collected* here but do not *produce* canonical
      truth — they only advance the chain state to ``truth_convergence``
      when the canonical truth modules confirm convergence.
I-C4  Closure is ``verified`` only when canonical truth confirms the
      action's intended effect AND all routed subjects have acked or been
      accounted for.
I-C5  This module is additive only.  It does not modify any existing
      audit, governance, or truth module.

Public API
----------
Authority::

    OPERATOR_ACTION_CLOSURE_CHAIN_AUTHORITY
    OPERATOR_ACTION_CLOSURE_CHAIN_CONTRACT_VERSION
    OPERATOR_CONTROL_PLANE_MUST_NOT_BE_AUTHORITY_CENTER_POLICY
    CANONICAL_GOVERNANCE_CONSTRAINTS_POLICY

Enum::

    ClosureChainStage

Dataclasses::

    SubjectAckEntry
    ClosureChainRecord

Functions::

    open_closure_chain(action_id, action_kind, routed_subjects, ...)
    record_subject_ack(action_id, subject_id, ack_state, ...)
    record_truth_convergence(action_id, ...)
    verify_closure(action_id, ...)
    get_closure_chain_record(action_id)
    get_all_closure_chain_records(limit)
    clear_closure_chain_store()          # test helper
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.OperatorActionClosureChain")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

OPERATOR_ACTION_CLOSURE_CHAIN_AUTHORITY: str = (
    "OPERATOR_ACTION_CLOSURE_CHAIN_AUTHORITY::TASK6::V2: "
    "core.operator_action_closure_chain is the minimal canonical "
    "action → ack → truth → closure traceable chain for the V2 "
    "operator/control plane.  Operator actions enter here, subjects "
    "ack here, truth convergence is recorded here, and closure is "
    "verified here — all under canonical governance constraints."
)

OPERATOR_ACTION_CLOSURE_CHAIN_CONTRACT_VERSION: str = "1.0.0"

# Policy sentinels (importable proofs of design constraints)

OPERATOR_CONTROL_PLANE_MUST_NOT_BE_AUTHORITY_CENTER_POLICY: str = (
    "POLICY::OPERATOR_CONTROL_PLANE_MUST_NOT_BE_AUTHORITY_CENTER: "
    "The operator/control plane MUST NOT become a new authority center. "
    "All closure decisions are derived from canonical truth modules "
    "(unified_result_ingress, task_result_canonical_truth_chain, "
    "multi_subject_truth_convergence_bridge).  The operator chain only "
    "COLLECTS and OBSERVES; it never PRODUCES canonical truth."
)

CANONICAL_GOVERNANCE_CONSTRAINTS_POLICY: str = (
    "POLICY::CANONICAL_GOVERNANCE_CONSTRAINTS: "
    "Operator actions MUST enter via OperatorSurface.execute_operator_action() "
    "→ canonical runtime.  The closure chain records what happened; it does not "
    "grant, revoke, or bypass canonical governance."
)

MULTI_SUBJECT_ACK_COLLECTION_POLICY: str = (
    "POLICY::MULTI_SUBJECT_ACK_COLLECTION: "
    "Subject acks are collected per-subject.  Truth convergence advances only "
    "when the canonical truth bridge (multi_subject_truth_convergence_bridge "
    "or pr4_operator_action_governance) confirms convergence.  Partial acks "
    "do not advance to closure without canonical confirmation."
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ClosureChainStage(str, Enum):
    """Ordered stages of one operator action's closure lifecycle.

    Stages progress monotonically: ``dispatched`` → ``acked`` (or
    ``partial_ack``) → ``truth_convergence`` → ``closed``.
    An action may also reach ``failed`` or ``policy_blocked`` at any
    stage.
    """

    dispatched = "dispatched"
    partial_ack = "partial_ack"      # some subjects acked, not all
    acked = "acked"                  # all routed subjects acked
    truth_convergence = "truth_convergence"   # canonical truth confirmed
    closed = "closed"                # closure verified
    failed = "failed"
    policy_blocked = "policy_blocked"


class AckState(str, Enum):
    pending = "pending"
    acked = "acked"
    nacked = "nacked"
    timeout = "timeout"
    skipped = "skipped"    # subject was excluded (e.g. lost before ack)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SubjectAckEntry:
    """Per-subject ack record within a closure chain."""

    subject_id: str
    subject_kind: str = "device"          # "device", "agent", "participant"
    ack_state: str = AckState.pending.value
    acked_at: Optional[float] = None
    ack_payload: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "subject_kind": self.subject_kind,
            "ack_state": self.ack_state,
            "acked_at": self.acked_at,
            "ack_payload": dict(self.ack_payload),
            "notes": list(self.notes),
        }


@dataclass
class ClosureChainRecord:
    """Full traceable record for one operator action's closure lifecycle.

    The record advances through :class:`ClosureChainStage` values.
    All fields are populated by the public functions in this module.
    """

    # --- Identity ---
    action_id: str
    action_kind: str
    operator_user_id: str = "operator"
    trace_id: str = ""

    # --- Routing ---
    routed_subjects: List[str] = field(default_factory=list)
    subject_acks: Dict[str, SubjectAckEntry] = field(default_factory=dict)

    # --- Lifecycle ---
    stage: str = ClosureChainStage.dispatched.value
    dispatched_at: float = field(default_factory=time.time)
    last_updated_at: float = field(default_factory=time.time)

    # --- Truth convergence ---
    truth_convergence_payload: Dict[str, Any] = field(default_factory=dict)
    truth_chain_complete: bool = False
    canonical_truth_refs: List[str] = field(default_factory=list)

    # --- Closure ---
    closure_verified: bool = False
    closure_verdict: str = ""          # "success", "partial", "failed", "requires_review"
    closure_payload: Dict[str, Any] = field(default_factory=dict)
    closure_verified_at: Optional[float] = None

    # --- Governance ---
    authority: str = OPERATOR_ACTION_CLOSURE_CHAIN_AUTHORITY
    contract_version: str = OPERATOR_ACTION_CLOSURE_CHAIN_CONTRACT_VERSION
    policy_violations: List[str] = field(default_factory=list)

    # --- Error / Notes ---
    error: str = ""
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_kind": self.action_kind,
            "operator_user_id": self.operator_user_id,
            "trace_id": self.trace_id,
            "routed_subjects": list(self.routed_subjects),
            "subject_acks": {
                sid: ack.to_dict() for sid, ack in self.subject_acks.items()
            },
            "stage": self.stage,
            "dispatched_at": self.dispatched_at,
            "last_updated_at": self.last_updated_at,
            "truth_convergence_payload": dict(self.truth_convergence_payload),
            "truth_chain_complete": self.truth_chain_complete,
            "canonical_truth_refs": list(self.canonical_truth_refs),
            "closure_verified": self.closure_verified,
            "closure_verdict": self.closure_verdict,
            "closure_payload": dict(self.closure_payload),
            "closure_verified_at": self.closure_verified_at,
            "authority": self.authority,
            "contract_version": self.contract_version,
            "policy_violations": list(self.policy_violations),
            "error": self.error,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# In-memory store  (keyed by action_id, newest-first list for retrieval)
# ---------------------------------------------------------------------------

_MAX_STORE_SIZE = 500
_CLOSURE_CHAIN_STORE: Dict[str, ClosureChainRecord] = {}
_CLOSURE_CHAIN_ORDER: List[str] = []    # insertion order for newest-first retrieval


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def open_closure_chain(
    *,
    action_id: str,
    action_kind: str,
    routed_subjects: Optional[List[str]] = None,
    operator_user_id: str = "operator",
    trace_id: str = "",
    notes: Optional[List[str]] = None,
) -> ClosureChainRecord:
    """Register a new operator action in the closure chain.

    Should be called immediately after an operator action is dispatched
    (typically from within :func:`core.pr4_operator_action_governance
    .execute_governed_operator_action` or the operator route handler).

    Parameters
    ----------
    action_id:
        Unique action ID (e.g. ``opact_<hex>``).
    action_kind:
        The :class:`~core.operator_action_contract.OperatorActionKind`
        value string.
    routed_subjects:
        List of subject IDs (device IDs, agent IDs, …) that were routed
        this action.  Can be empty for V2-local actions with no
        explicit target.
    operator_user_id:
        The operator's identity for auditing.
    trace_id:
        Correlation trace ID for the overall task/session.
    notes:
        Free-form notes to attach to the record.
    """
    if not action_id:
        action_id = f"opact_{uuid.uuid4().hex[:12]}"

    subjects = list(routed_subjects or [])
    subject_acks: Dict[str, SubjectAckEntry] = {
        sid: SubjectAckEntry(subject_id=sid)
        for sid in subjects
    }

    record = ClosureChainRecord(
        action_id=action_id,
        action_kind=action_kind,
        operator_user_id=operator_user_id,
        trace_id=trace_id,
        routed_subjects=subjects,
        subject_acks=subject_acks,
        notes=list(notes or []),
    )

    _store_record(record)
    logger.debug(
        "closure_chain: opened action_id=%s kind=%s subjects=%s",
        action_id, action_kind, subjects,
    )
    return record


def record_subject_ack(
    *,
    action_id: str,
    subject_id: str,
    ack_state: str = AckState.acked.value,
    ack_payload: Optional[Dict[str, Any]] = None,
    notes: Optional[List[str]] = None,
) -> Optional[ClosureChainRecord]:
    """Record that a subject has acknowledged an operator action.

    Advances the chain stage to ``partial_ack`` or ``acked`` depending
    on whether all routed subjects have acked.

    Parameters
    ----------
    action_id:
        The action being acked.
    subject_id:
        The subject (device/agent) that sent the ack.
    ack_state:
        One of :class:`AckState` values.
    ack_payload:
        Optional additional data from the ack event.
    notes:
        Optional notes.

    Returns
    -------
    The updated :class:`ClosureChainRecord`, or ``None`` if the
    action_id is not found.
    """
    record = _CLOSURE_CHAIN_STORE.get(action_id)
    if record is None:
        logger.warning("closure_chain: record_subject_ack for unknown action_id=%s", action_id)
        return None

    # Register subject if not already known (dynamic multi-subject scenario)
    if subject_id not in record.subject_acks:
        record.subject_acks[subject_id] = SubjectAckEntry(subject_id=subject_id)
        if subject_id not in record.routed_subjects:
            record.routed_subjects.append(subject_id)

    ack_entry = record.subject_acks[subject_id]
    ack_entry.ack_state = ack_state
    ack_entry.acked_at = time.time()
    ack_entry.ack_payload = dict(ack_payload or {})
    if notes:
        ack_entry.notes.extend(notes)

    record.last_updated_at = time.time()

    # Advance stage
    all_acked = _all_subjects_resolved(record)
    any_acked = any(
        e.ack_state == AckState.acked.value for e in record.subject_acks.values()
    )
    if record.stage == ClosureChainStage.dispatched.value:
        if all_acked:
            record.stage = ClosureChainStage.acked.value
        elif any_acked:
            record.stage = ClosureChainStage.partial_ack.value
    elif record.stage == ClosureChainStage.partial_ack.value and all_acked:
        record.stage = ClosureChainStage.acked.value

    logger.debug(
        "closure_chain: subject_ack action_id=%s subject=%s ack=%s new_stage=%s",
        action_id, subject_id, ack_state, record.stage,
    )
    return record


def record_truth_convergence(
    *,
    action_id: str,
    truth_convergence_payload: Optional[Dict[str, Any]] = None,
    canonical_truth_refs: Optional[List[str]] = None,
    truth_chain_complete: bool = False,
    notes: Optional[List[str]] = None,
) -> Optional[ClosureChainRecord]:
    """Record that canonical truth has been updated for an action's effects.

    This step is driven by the canonical truth ingress modules
    (e.g. :mod:`core.unified_runtime_truth_ingress`,
    :mod:`core.task_result_canonical_truth_chain`,
    :mod:`core.multi_subject_truth_convergence_bridge`), NOT by the
    operator plane itself.  The operator plane merely records what
    canonical truth says.

    Parameters
    ----------
    action_id:
        The action whose effects have converged in canonical truth.
    truth_convergence_payload:
        The canonical truth snapshot at the time of convergence.
    canonical_truth_refs:
        References to the canonical truth module(s) that confirmed
        convergence.
    truth_chain_complete:
        Whether the canonical truth chain is fully closed for this action.
    notes:
        Optional notes.
    """
    record = _CLOSURE_CHAIN_STORE.get(action_id)
    if record is None:
        logger.warning("closure_chain: record_truth_convergence for unknown action_id=%s", action_id)
        return None

    record.truth_convergence_payload = dict(truth_convergence_payload or {})
    record.truth_chain_complete = truth_chain_complete
    record.canonical_truth_refs = list(canonical_truth_refs or [])
    record.last_updated_at = time.time()

    # Advance stage to truth_convergence if not already at/past closure
    if record.stage in {
        ClosureChainStage.dispatched.value,
        ClosureChainStage.partial_ack.value,
        ClosureChainStage.acked.value,
    }:
        record.stage = ClosureChainStage.truth_convergence.value

    if notes:
        record.notes.extend(notes)

    logger.debug(
        "closure_chain: truth_convergence action_id=%s complete=%s stage=%s",
        action_id, truth_chain_complete, record.stage,
    )
    return record


def verify_closure(
    *,
    action_id: str,
    closure_verdict: str = "success",
    closure_payload: Optional[Dict[str, Any]] = None,
    notes: Optional[List[str]] = None,
) -> Optional[ClosureChainRecord]:
    """Verify and finalize the closure of an operator action.

    This is the terminal step.  Closure is ``verified`` only when:
    * truth convergence has been recorded (``truth_chain_complete=True``),
      OR the closure_verdict is ``failed``/``policy_blocked``/``requires_review``,
    * all routed subjects have acked or been accounted for (or there are
      no routed subjects for V2-local actions).

    Parameters
    ----------
    action_id:
        The action to close.
    closure_verdict:
        One of ``"success"``, ``"partial"``, ``"failed"``,
        ``"policy_blocked"``, ``"requires_review"``.
    closure_payload:
        Optional additional closure metadata.
    notes:
        Optional notes.

    Returns
    -------
    The updated :class:`ClosureChainRecord`, or ``None`` if the
    action_id is not found.
    """
    record = _CLOSURE_CHAIN_STORE.get(action_id)
    if record is None:
        logger.warning("closure_chain: verify_closure for unknown action_id=%s", action_id)
        return None

    record.closure_verdict = closure_verdict
    record.closure_payload = dict(closure_payload or {})
    record.closure_verified_at = time.time()
    record.last_updated_at = time.time()

    # Check closure conditions
    all_subjects_resolved = _all_subjects_resolved(record)
    truth_ok = (
        record.truth_chain_complete
        or closure_verdict in {"failed", "policy_blocked", "requires_review"}
        or not record.routed_subjects   # V2-local action, no subjects to wait for
    )
    subjects_ok = (
        all_subjects_resolved
        or not record.routed_subjects   # V2-local action
        or closure_verdict in {"failed", "policy_blocked"}
    )

    if truth_ok and subjects_ok:
        record.closure_verified = True
        record.stage = ClosureChainStage.closed.value
    else:
        # Record what prevented full closure
        if not truth_ok:
            record.notes.append("closure_deferred: truth_chain_complete=False")
        if not subjects_ok:
            pending = [
                sid for sid, e in record.subject_acks.items()
                if e.ack_state == AckState.pending.value
            ]
            record.notes.append(
                f"closure_deferred: pending_acks={pending}"
            )
        record.stage = ClosureChainStage.truth_convergence.value
        record.closure_verified = False

    if notes:
        record.notes.extend(notes)

    logger.debug(
        "closure_chain: verify_closure action_id=%s verdict=%s verified=%s stage=%s",
        action_id, closure_verdict, record.closure_verified, record.stage,
    )
    return record


def get_closure_chain_record(action_id: str) -> Optional[ClosureChainRecord]:
    """Return the :class:`ClosureChainRecord` for an action_id, or ``None``."""
    return _CLOSURE_CHAIN_STORE.get(action_id)


def get_all_closure_chain_records(
    *,
    limit: int = 50,
    stage: Optional[str] = None,
    action_kind: Optional[str] = None,
) -> List[ClosureChainRecord]:
    """Return closure chain records newest-first with optional filters.

    Parameters
    ----------
    limit:
        Maximum records to return (default 50, max 500).
    stage:
        If provided, only records at this :class:`ClosureChainStage`.
    action_kind:
        If provided, only records for this action kind.
    """
    limit = max(1, min(limit, _MAX_STORE_SIZE))
    # Newest first
    ids = list(reversed(_CLOSURE_CHAIN_ORDER))
    results: List[ClosureChainRecord] = []
    for aid in ids:
        if len(results) >= limit:
            break
        record = _CLOSURE_CHAIN_STORE.get(aid)
        if record is None:
            continue
        if stage is not None and record.stage != stage:
            continue
        if action_kind is not None and record.action_kind != action_kind:
            continue
        results.append(record)
    return results


def get_closure_chain_summary() -> Dict[str, Any]:
    """Return a summary of all closure chain records.

    Useful for the operator board / status endpoints.
    """
    total = len(_CLOSURE_CHAIN_STORE)
    stage_counts: Dict[str, int] = {}
    for record in _CLOSURE_CHAIN_STORE.values():
        stage_counts[record.stage] = stage_counts.get(record.stage, 0) + 1

    open_actions = [
        aid for aid, r in _CLOSURE_CHAIN_STORE.items()
        if r.stage not in {
            ClosureChainStage.closed.value,
            ClosureChainStage.failed.value,
            ClosureChainStage.policy_blocked.value,
        }
    ]
    verified_count = sum(
        1 for r in _CLOSURE_CHAIN_STORE.values() if r.closure_verified
    )
    return {
        "total_actions": total,
        "open_actions": len(open_actions),
        "verified_closures": verified_count,
        "stage_counts": stage_counts,
        "authority": OPERATOR_ACTION_CLOSURE_CHAIN_AUTHORITY,
        "contract_version": OPERATOR_ACTION_CLOSURE_CHAIN_CONTRACT_VERSION,
    }


def clear_closure_chain_store() -> None:
    """Clear all records.  Test helper only — do not call in production."""
    _CLOSURE_CHAIN_STORE.clear()
    _CLOSURE_CHAIN_ORDER.clear()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _store_record(record: ClosureChainRecord) -> None:
    if record.action_id in _CLOSURE_CHAIN_STORE:
        # Update in place
        _CLOSURE_CHAIN_STORE[record.action_id] = record
        return
    _CLOSURE_CHAIN_STORE[record.action_id] = record
    _CLOSURE_CHAIN_ORDER.append(record.action_id)
    # Trim oldest if over limit
    while len(_CLOSURE_CHAIN_ORDER) > _MAX_STORE_SIZE:
        oldest_id = _CLOSURE_CHAIN_ORDER.pop(0)
        _CLOSURE_CHAIN_STORE.pop(oldest_id, None)


def _all_subjects_resolved(record: ClosureChainRecord) -> bool:
    """Return True if every routed subject has a non-pending ack."""
    if not record.routed_subjects:
        return True
    for sid in record.routed_subjects:
        ack = record.subject_acks.get(sid)
        if ack is None or ack.ack_state == AckState.pending.value:
            return False
    return True


# ---------------------------------------------------------------------------
# Operator action entry helper
# ---------------------------------------------------------------------------


def open_chain_for_operator_action(
    *,
    action_id: str,
    action_kind: str,
    operator_user_id: str = "operator",
    trace_id: str = "",
    device_id: Optional[str] = None,
    extra_subjects: Optional[List[str]] = None,
) -> ClosureChainRecord:
    """Convenience wrapper to open a closure chain for a governed operator action.

    Automatically builds the routed_subjects list from ``device_id`` and
    ``extra_subjects``.  This is the recommended entry point when called
    from :func:`core.pr4_operator_action_governance.execute_governed_operator_action`.

    Parameters
    ----------
    action_id:
        The ``action_id`` from the operator action request.
    action_kind:
        The :class:`~core.operator_action_contract.OperatorActionKind` value.
    operator_user_id:
        The operator's identity.
    trace_id:
        Correlation trace ID.
    device_id:
        Primary target device (if any).
    extra_subjects:
        Additional subject IDs (agents, participants) involved.
    """
    subjects: List[str] = []
    if device_id:
        subjects.append(device_id)
    subjects.extend(extra_subjects or [])
    # Deduplicate while preserving order
    seen = set()
    unique_subjects: List[str] = []
    for s in subjects:
        if s not in seen:
            seen.add(s)
            unique_subjects.append(s)

    return open_closure_chain(
        action_id=action_id,
        action_kind=action_kind,
        routed_subjects=unique_subjects,
        operator_user_id=operator_user_id,
        trace_id=trace_id,
    )


__all__ = [
    "OPERATOR_ACTION_CLOSURE_CHAIN_AUTHORITY",
    "OPERATOR_ACTION_CLOSURE_CHAIN_CONTRACT_VERSION",
    "OPERATOR_CONTROL_PLANE_MUST_NOT_BE_AUTHORITY_CENTER_POLICY",
    "CANONICAL_GOVERNANCE_CONSTRAINTS_POLICY",
    "MULTI_SUBJECT_ACK_COLLECTION_POLICY",
    "ClosureChainStage",
    "AckState",
    "SubjectAckEntry",
    "ClosureChainRecord",
    "open_closure_chain",
    "open_chain_for_operator_action",
    "record_subject_ack",
    "record_truth_convergence",
    "verify_closure",
    "get_closure_chain_record",
    "get_all_closure_chain_records",
    "get_closure_chain_summary",
    "clear_closure_chain_store",
]
