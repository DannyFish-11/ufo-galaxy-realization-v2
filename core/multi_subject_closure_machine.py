#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/multi_subject_closure_machine.py
======================================
PR-8: Unified Multi-Subject Closure State Machine — canonical closure
authority for multi-subject / multi-participant distributed execution.

Background
----------
Previous work established the individual building blocks:

* :mod:`core.multi_subject_truth_convergence_bridge` — bridges formation /
  readiness / participation / result signals into a participant role + failure
  isolation snapshot.
* :mod:`core.canonical_group_completion_closure` — applies group completion
  semantics for parallel / delegated / handoff modes.
* :mod:`core.unified_result_ingress` — single canonical entry point for all
  task result signals.
* :mod:`core.android_participant_truth_ingress` — reconciles Android
  participant truth into V2 canonical state.
* :mod:`core.task_result_canonical_truth_chain` — the four-step must-run
  truth chain for every task_result.

What was missing was a **unified closure state machine** that sits above all
these and:

1. Defines the complete set of canonical multi-subject terminal states
   (including complex ones such as ``takeover_continuation``,
   ``degraded_completion``, ``recovery_completion``).
2. Declares exactly when a multi-subject execution requires reconciliation
   before closure is sealed.
3. Provides the single ``ClosureCandidate`` output type that
   operator / projection / outward-facing layers MUST consume instead of
   reconstructing closure decisions ad-hoc.
4. Enforces that Android (or any participant) local terminal signals are
   **not** promoted to final truth — V2 canonical center is the sole closure
   authority.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │  MULTI-SUBJECT PARTICIPANT SIGNALS                               │
    │  participant truth · formation result · takeover signal          │
    │  recovery signal · handoff terminal · Android uplink             │
    └───────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │  MULTI-SUBJECT TRUTH CONVERGENCE BRIDGE                          │
    │  core/multi_subject_truth_convergence_bridge.py                  │
    │  Derives participant roles, states, failure isolation            │
    └───────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │  MULTI-SUBJECT CLOSURE MACHINE  ← this module                   │
    │  Applies closure state machine → ClosureCandidate output         │
    │  Triggers reconcile-required when needed                         │
    │  V2 is the sole canonical closure authority                      │
    └───────────────────────────┬──────────────────────────────────────┘
                                │  ClosureCandidate (canonical output)
                                ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │  OPERATOR / PROJECTION / OUTWARD-FACING LAYER                    │
    │  Consumes only ClosureCandidate; must not re-derive closure       │
    └──────────────────────────────────────────────────────────────────┘

Policy sentinels
----------------
All authority and boundary rules are expressed as importable string sentinels.
Other modules may import these to assert compliance.

Terminal states covered
-----------------------
success
    All participants completed successfully.
partial_success
    Some participants succeeded, none were lost/failed with a full-quorum
    requirement, and no participant held takeover status.
participant_lost
    One or more primary participants became unreachable with no takeover
    candidate available.
degraded_completion
    Some participants succeeded; others were degraded or lost but a
    sufficient quorum was reached (degraded_success_allowed).
takeover_continuation
    Primary participant failed/lost; a takeover candidate successfully
    continued and reached terminal.
recovery_completion
    A previously failed/suspended participant re-joined and the group
    reached completion via recovery.
failed
    Insufficient participants succeeded to reach any success quorum.
reconcile_required
    The closure machine cannot produce a confident terminal verdict without
    an explicit reconciliation step (e.g. split-brain, conflicting truths).

Reconcile-required trigger conditions
--------------------------------------
``reconcile_required`` is set to ``True`` on a ``ClosureCandidate`` when ANY
of the following conditions hold:

1. ``participant_lost`` AND no takeover candidate is available.
2. Conflicting terminal signals from the same participant (e.g. both
   ``success`` and ``failed`` reported for the same device_id).
3. Participant count in the bridge snapshot is zero but a formation with
   members was provided (empty-formation divergence).
4. The closure ``completion_state`` is ``"failed"`` AND at least one
   participant is ``"degraded"`` (ambiguous failure — may be recoverable).
5. A ``recovery_completion`` is detected but no V2-side recovery record
   corroborates it.

Public API
----------
Sentinels::

    MULTI_SUBJECT_CLOSURE_MACHINE_AUTHORITY
    MULTI_SUBJECT_CLOSURE_MACHINE_PR8_SENTINEL
    V2_IS_SOLE_CANONICAL_CLOSURE_AUTHORITY_POLICY
    NO_PARALLEL_CLOSURE_SYSTEM_POLICY
    PARTICIPANT_LOCAL_TERMINAL_NOT_FINAL_TRUTH_POLICY
    OPERATOR_MUST_CONSUME_CANONICAL_CLOSURE_OUTPUT_POLICY
    RECONCILE_REQUIRED_TRIGGERS_ARE_EXPLICIT_POLICY

Enums::

    ClosureTerminalKind
    ReconcileRequiredTrigger

Dataclasses::

    ParticipantClosureRecord
    ClosureCandidate

Functions::

    build_closure_candidate(bridge_snapshot, *, recovery_device_ids,
                            formation_member_count) -> ClosureCandidate
    get_closure_output(bridge_snapshot, *, recovery_device_ids,
                       formation_member_count) -> ClosureCandidate
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Set

logger = logging.getLogger("Galaxy.MultiSubjectClosureMachine")

_EXPLICIT_MULTI_RESULT_CONFLICT_STATES: FrozenSet[str] = frozenset(
    {
        "multi_result_conflict",
        "multi_subject_result_conflict",
    }
)
_EXPLICIT_PARTIAL_CONTRADICTION_STATES: FrozenSet[str] = frozenset(
    {
        "partial_result_contradiction",
        "partial_subject_contradiction",
    }
)

# ---------------------------------------------------------------------------
# Authority / policy sentinels
# ---------------------------------------------------------------------------

MULTI_SUBJECT_CLOSURE_MACHINE_AUTHORITY: str = (
    "MULTI_SUBJECT_CLOSURE_MACHINE::CANONICAL_GOVERNANCE_V1: "
    "core/multi_subject_closure_machine.py is the unified canonical closure "
    "state machine for multi-subject distributed execution.  It is the single "
    "authority for producing ClosureCandidate outputs that operator / "
    "projection / outward-facing layers must consume."
)

MULTI_SUBJECT_CLOSURE_MACHINE_PR8_SENTINEL: str = (
    "PR-8::MULTI_SUBJECT_CLOSURE_MACHINE_V1: "
    "统一 multi-subject closure / reconciliation / degraded completion 主链."
)

V2_IS_SOLE_CANONICAL_CLOSURE_AUTHORITY_POLICY: str = (
    "POLICY::V2_IS_SOLE_CANONICAL_CLOSURE_AUTHORITY_V1: "
    "V2 (core/multi_subject_closure_machine.py) is the sole canonical "
    "closure authority for multi-subject execution.  No participant — "
    "including Android — may unilaterally finalize the multi-subject closure.  "
    "Participant local terminals are input evidence, not final truth."
)

NO_PARALLEL_CLOSURE_SYSTEM_POLICY: str = (
    "POLICY::NO_PARALLEL_CLOSURE_SYSTEM_V1: "
    "No new parallel closure system, parallel reconciliation center, or "
    "new super-workflow facade may be created.  All multi-subject closure "
    "decisions MUST flow through MultiSubjectClosureMachine."
)

PARTICIPANT_LOCAL_TERMINAL_NOT_FINAL_TRUTH_POLICY: str = (
    "POLICY::PARTICIPANT_LOCAL_TERMINAL_NOT_FINAL_TRUTH_V1: "
    "A participant's locally reported terminal state (e.g. Android "
    "goal_execution_result) is input evidence to the closure machine, not "
    "the final multi-subject truth.  V2 canonical closure arbitrates all "
    "participant truths before sealing a ClosureCandidate."
)

OPERATOR_MUST_CONSUME_CANONICAL_CLOSURE_OUTPUT_POLICY: str = (
    "POLICY::OPERATOR_MUST_CONSUME_CANONICAL_CLOSURE_OUTPUT_V1: "
    "Operator / projection / outward-facing layers MUST consume the "
    "ClosureCandidate produced by get_closure_output() and must NOT "
    "re-derive closure decisions from raw participant signals or bridge "
    "snapshots.  ClosureCandidate is the single canonical boundary output."
)

RECONCILE_REQUIRED_TRIGGERS_ARE_EXPLICIT_POLICY: str = (
    "POLICY::RECONCILE_REQUIRED_TRIGGERS_ARE_EXPLICIT_V1: "
    "The conditions under which reconcile_required=True is set on a "
    "ClosureCandidate are explicitly enumerated in ReconcileRequiredTrigger "
    "and in build_closure_candidate().  No implicit or fail-open reconcile "
    "trigger is permitted."
)

DEGRADED_COMPLETION_IS_IN_MAIN_CHAIN_POLICY: str = (
    "POLICY::DEGRADED_COMPLETION_IS_IN_MAIN_CHAIN_V1: "
    "degraded_completion is a first-class canonical terminal state, not an "
    "edge-case or exception.  It MUST be handled by the closure machine main "
    "chain and MUST be surfaced in ClosureCandidate.terminal_kind."
)

# ---------------------------------------------------------------------------
# ClosureTerminalKind
# ---------------------------------------------------------------------------


class ClosureTerminalKind(str, Enum):
    """Canonical terminal states for multi-subject closure.

    Non-terminal
    ------------
    in_progress
        Not enough participant results have arrived to determine closure.

    Terminal — success family
    -------------------------
    success
        All participants completed successfully.
    degraded_completion
        Quorum participants completed; some were lost or degraded but
        degraded-success policy permits this outcome.

    Terminal — partial family
    -------------------------
    partial_success
        Some participants succeeded, some failed (no quorum requirement
        violated, no participant was lost without a takeover).
    takeover_continuation
        Primary participant lost; a takeover candidate completed.
    recovery_completion
        A previously failed or suspended participant re-joined and
        the group reached terminal via recovery.

    Terminal — failure family
    -------------------------
    participant_lost
        Primary participant unreachable and no takeover candidate available.
    failed
        Insufficient participants succeeded to meet any success quorum.
    reconcile_required
        Closure cannot be confidently sealed — explicit reconciliation
        must be performed by the canonical center before finalizing.
    """

    in_progress = "in_progress"
    success = "success"
    degraded_completion = "degraded_completion"
    partial_success = "partial_success"
    takeover_continuation = "takeover_continuation"
    recovery_completion = "recovery_completion"
    participant_lost = "participant_lost"
    failed = "failed"
    reconcile_required = "reconcile_required"

    @property
    def is_terminal(self) -> bool:
        return self != ClosureTerminalKind.in_progress

    @property
    def is_success_family(self) -> bool:
        return self in {
            ClosureTerminalKind.success,
            ClosureTerminalKind.degraded_completion,
        }

    @property
    def is_partial_family(self) -> bool:
        return self in {
            ClosureTerminalKind.partial_success,
            ClosureTerminalKind.takeover_continuation,
            ClosureTerminalKind.recovery_completion,
        }

    @property
    def is_failure_family(self) -> bool:
        return self in {
            ClosureTerminalKind.participant_lost,
            ClosureTerminalKind.failed,
        }

    @property
    def requires_review(self) -> bool:
        return self not in {
            ClosureTerminalKind.success,
            ClosureTerminalKind.in_progress,
        }


# ---------------------------------------------------------------------------
# ReconcileRequiredTrigger
# ---------------------------------------------------------------------------


class ReconcileRequiredTrigger(str, Enum):
    """Explicit conditions that set reconcile_required=True on ClosureCandidate.

    These are the ONLY legitimate triggers for reconcile_required.
    """

    participant_lost_no_takeover = "participant_lost_no_takeover"
    """Primary participant lost and no takeover candidate is available."""

    conflicting_participant_signals = "conflicting_participant_signals"
    """The same participant_id reported conflicting terminal truths."""

    empty_formation_divergence = "empty_formation_divergence"
    """Formation had members but closure machine saw zero participants."""

    ambiguous_failure_degraded_present = "ambiguous_failure_degraded_present"
    """Closure is 'failed' but degraded participants exist — may be recoverable."""

    recovery_completion_unverified = "recovery_completion_unverified"
    """Recovery completion detected but no corroborating V2 recovery record."""


# ---------------------------------------------------------------------------
# ParticipantClosureRecord
# ---------------------------------------------------------------------------


@dataclass
class ParticipantClosureRecord:
    """Closure-relevant summary for a single participant.

    Derived from the bridge snapshot participant entry; immutable after
    construction.
    """

    device_id: str
    role: str
    state: str
    formation_role: str
    is_source: bool = False
    is_recovery: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "role": self.role,
            "state": self.state,
            "formation_role": self.formation_role,
            "is_source": self.is_source,
            "is_recovery": self.is_recovery,
        }


# ---------------------------------------------------------------------------
# ClosureCandidate
# ---------------------------------------------------------------------------


@dataclass
class ClosureCandidate:
    """The single canonical closure output for a multi-subject execution.

    Produced exclusively by :func:`build_closure_candidate` /
    :func:`get_closure_output`.  Operator / projection / outward-facing layers
    MUST consume this type rather than re-deriving closure decisions from raw
    signals.

    Fields
    ------
    terminal_kind
        The :class:`ClosureTerminalKind` for this execution.
    is_terminal
        True when terminal_kind is not in_progress.
    reconcile_required
        True when the closure machine determined that explicit reconciliation
        must be performed before this candidate may be sealed as final truth.
    reconcile_triggers
        The explicit :class:`ReconcileRequiredTrigger` values that caused
        reconcile_required=True.  Empty when reconcile_required=False.
    participants
        Ordered list of :class:`ParticipantClosureRecord` entries.
    participant_count
        Total number of participants.
    success_count
        Number of participants in 'ready' (success) state.
    degraded_count
        Number of participants in 'degraded' state.
    lost_count
        Number of participants in 'lost' state.
    failed_count
        Number of participants in 'failed' state.
    suspended_count
        Number of participants in 'suspended' state.
    takeover_candidate_device_id
        Device ID of the takeover candidate, if any.
    authority
        Module authority sentinel string.
    bridge_completion_state
        Raw completion_state string from the truth convergence bridge.
    """

    terminal_kind: ClosureTerminalKind = ClosureTerminalKind.in_progress
    is_terminal: bool = False
    reconcile_required: bool = False
    reconcile_triggers: List[str] = field(default_factory=list)
    participants: List[ParticipantClosureRecord] = field(default_factory=list)
    participant_count: int = 0
    success_count: int = 0
    degraded_count: int = 0
    lost_count: int = 0
    failed_count: int = 0
    suspended_count: int = 0
    takeover_candidate_device_id: Optional[str] = None
    authority: str = MULTI_SUBJECT_CLOSURE_MACHINE_AUTHORITY
    bridge_completion_state: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "terminal_kind": self.terminal_kind.value,
            "is_terminal": self.is_terminal,
            "reconcile_required": self.reconcile_required,
            "reconcile_triggers": list(self.reconcile_triggers),
            "participants": [p.to_dict() for p in self.participants],
            "participant_count": self.participant_count,
            "success_count": self.success_count,
            "degraded_count": self.degraded_count,
            "lost_count": self.lost_count,
            "failed_count": self.failed_count,
            "suspended_count": self.suspended_count,
            "takeover_candidate_device_id": self.takeover_candidate_device_id,
            "authority": self.authority,
            "bridge_completion_state": self.bridge_completion_state,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _detect_conflicting_signals(
    participants: List[ParticipantClosureRecord],
) -> bool:
    """Return True if any device_id appears with conflicting states.

    This can happen when two result channels report different states for
    the same participant (e.g. one says 'ready', another says 'failed').
    """
    seen: Dict[str, Set[str]] = {}
    for p in participants:
        seen.setdefault(p.device_id, set()).add(p.state)
    return any(len(states) > 1 for states in seen.values())


def _build_participant_records(
    bridge_participants: List[Dict[str, Any]],
    recovery_device_ids: FrozenSet[str],
) -> List[ParticipantClosureRecord]:
    """Convert raw bridge participant dicts into ParticipantClosureRecord list."""
    records: List[ParticipantClosureRecord] = []
    for p in bridge_participants:
        if not isinstance(p, dict):
            continue
        device_id = str(p.get("device_id", "") or "")
        if not device_id:
            continue
        records.append(
            ParticipantClosureRecord(
                device_id=device_id,
                role=str(p.get("role", "") or "assistant").strip().lower(),
                state=str(p.get("state", "") or "unknown").strip().lower(),
                formation_role=str(p.get("formation_role", "") or "unassigned").strip().lower(),
                is_source=bool(p.get("is_source", False)),
                is_recovery=device_id in recovery_device_ids or bool(p.get("is_recovery", False)),
            )
        )
    return records


def _normalize_token(value: Any) -> str:
    return str(value or "").strip().lower()


def _classify_explicit_conflict_state(
    bridge_completion_state: str,
    bridge_closure: Dict[str, Any],
) -> Optional[str]:
    state = _normalize_token(bridge_completion_state)
    conflict_kind = _normalize_token(bridge_closure.get("conflict_kind"))

    if state in _EXPLICIT_MULTI_RESULT_CONFLICT_STATES:
        return "multi_result_conflict"
    if state in _EXPLICIT_PARTIAL_CONTRADICTION_STATES:
        return "partial_result_contradiction"
    if conflict_kind in _EXPLICIT_MULTI_RESULT_CONFLICT_STATES:
        return "multi_result_conflict"
    if conflict_kind in _EXPLICIT_PARTIAL_CONTRADICTION_STATES:
        return "partial_result_contradiction"
    return None


def _classify_terminal_kind(
    bridge_completion_state: str,
    explicit_conflict_class: Optional[str],
    participants: List[ParticipantClosureRecord],
    recovery_device_ids: FrozenSet[str],
    takeover_candidate_device_id: Optional[str],
    success_count: int,
    degraded_count: int,
    lost_count: int,
    failed_count: int,
) -> ClosureTerminalKind:
    """Map the raw bridge completion_state to a ClosureTerminalKind.

    Explicit mapping (ordered by priority):
    1. success                → ClosureTerminalKind.success
    2. takeover_continuation  → ClosureTerminalKind.takeover_continuation
    3. degraded_completion    → ClosureTerminalKind.degraded_completion
    4. partial_success with recovery participants → recovery_completion
    5. partial_success        → ClosureTerminalKind.partial_success
    6. failed + lost > 0 + no takeover → participant_lost
    7. failed                 → ClosureTerminalKind.failed
    8. (default)              → ClosureTerminalKind.in_progress
    """
    if explicit_conflict_class:
        return ClosureTerminalKind.reconcile_required

    state = _normalize_token(bridge_completion_state)

    if state == "success":
        return ClosureTerminalKind.success

    if state == "takeover_continuation":
        return ClosureTerminalKind.takeover_continuation

    if state == "degraded_completion":
        return ClosureTerminalKind.degraded_completion

    if state == "partial_success":
        # Check whether this is actually a recovery_completion scenario:
        # recovery_completion applies when at least one participant with
        # is_recovery=True is in the success ('ready') state.
        recovery_succeeded = any(
            p.is_recovery and p.state == "ready" for p in participants
        )
        if recovery_succeeded:
            return ClosureTerminalKind.recovery_completion
        return ClosureTerminalKind.partial_success

    if state == "failed":
        # Distinguish participant_lost (primary gone, no takeover available)
        # from generic failure.
        if lost_count > 0 and not takeover_candidate_device_id:
            return ClosureTerminalKind.participant_lost
        return ClosureTerminalKind.failed

    # Unrecognized / in-progress bridge state — stay in_progress.
    return ClosureTerminalKind.in_progress


def _compute_reconcile_triggers(
    terminal_kind: ClosureTerminalKind,
    participants: List[ParticipantClosureRecord],
    recovery_device_ids: FrozenSet[str],
    explicit_conflict_class: Optional[str],
    formation_member_count: int,
    lost_count: int,
    degraded_count: int,
    takeover_candidate_device_id: Optional[str],
) -> List[str]:
    """Return explicit ReconcileRequiredTrigger values that apply."""
    triggers: List[str] = []

    # Trigger 1: participant lost with no takeover
    if terminal_kind == ClosureTerminalKind.participant_lost and not takeover_candidate_device_id:
        triggers.append(ReconcileRequiredTrigger.participant_lost_no_takeover.value)

    # Trigger 2: conflicting signals for same participant
    if _detect_conflicting_signals(participants):
        triggers.append(ReconcileRequiredTrigger.conflicting_participant_signals.value)
    elif explicit_conflict_class in {
        "multi_result_conflict",
        "partial_result_contradiction",
    }:
        triggers.append(ReconcileRequiredTrigger.conflicting_participant_signals.value)

    # Trigger 3: formation declared members but closure machine sees zero participants
    if formation_member_count > 0 and len(participants) == 0:
        triggers.append(ReconcileRequiredTrigger.empty_formation_divergence.value)

    # Trigger 4: failed state but degraded participants present (ambiguous failure)
    if terminal_kind == ClosureTerminalKind.failed and degraded_count > 0:
        triggers.append(ReconcileRequiredTrigger.ambiguous_failure_degraded_present.value)

    # Trigger 5: recovery_completion but no corroborating V2 recovery record
    if terminal_kind == ClosureTerminalKind.recovery_completion and not recovery_device_ids:
        triggers.append(ReconcileRequiredTrigger.recovery_completion_unverified.value)

    return triggers


# ---------------------------------------------------------------------------
# MultiSubjectClosureMachine
# ---------------------------------------------------------------------------


class MultiSubjectClosureMachine:
    """Canonical closure state machine for multi-subject distributed execution.

    This class applies the closure state machine logic defined in this module.
    It accepts a bridge snapshot (from
    :func:`~core.multi_subject_truth_convergence_bridge.build_multi_subject_truth_bridge`)
    and produces a :class:`ClosureCandidate`.

    Design constraints
    ------------------
    * Does NOT import from projection, operator, or outward-facing modules
      (no circular dependencies).
    * Does NOT create new participant truth records — it consumes the bridge.
    * Does NOT allow Android or any participant local terminal to become final
      truth without V2 arbitration.
    * Is NOT a replacement for
      :mod:`core.canonical_group_completion_closure` — that module handles
      the group completion contract for parallel/delegated/handoff modes.
      This module handles the *multi-subject participant-level* closure layer.
    """

    def apply(
        self,
        bridge_snapshot: Dict[str, Any],
        *,
        recovery_device_ids: Optional[Sequence[str]] = None,
        formation_member_count: int = 0,
    ) -> ClosureCandidate:
        """Apply the closure state machine to a bridge snapshot.

        Parameters
        ----------
        bridge_snapshot:
            Output of
            :func:`~core.multi_subject_truth_convergence_bridge.build_multi_subject_truth_bridge`.
        recovery_device_ids:
            Optional sequence of device IDs that are known to be
            re-joining after a prior failure or suspension (recovery path).
        formation_member_count:
            The number of members declared in the original formation.
            Used to detect empty-formation divergence.

        Returns
        -------
        ClosureCandidate
            Canonical closure output.  Never raises.
        """
        if not isinstance(bridge_snapshot, dict):
            logger.warning(
                "MultiSubjectClosureMachine.apply: bridge_snapshot is not a dict; "
                "returning in_progress candidate."
            )
            return ClosureCandidate()

        recovery_ids: FrozenSet[str] = frozenset(recovery_device_ids or [])

        raw_participants: List[Dict[str, Any]] = bridge_snapshot.get("participants") or []
        participants = _build_participant_records(raw_participants, recovery_ids)

        counts = bridge_snapshot.get("counts") or {}
        success_count = int(counts.get("success", 0))
        degraded_count = int(counts.get("degraded", 0))
        lost_count = int(counts.get("lost", 0))
        failed_count = int(counts.get("failed", 0))
        suspended_count = int(counts.get("suspended", 0))

        failure_isolation = bridge_snapshot.get("failure_isolation") or {}
        takeover_candidate_device_id = failure_isolation.get("takeover_candidate")

        bridge_closure = bridge_snapshot.get("closure") or {}
        bridge_completion_state = str(bridge_closure.get("completion_state", "") or "")
        explicit_conflict_class = _classify_explicit_conflict_state(
            bridge_completion_state=bridge_completion_state,
            bridge_closure=bridge_closure,
        )

        terminal_kind = _classify_terminal_kind(
            bridge_completion_state=bridge_completion_state,
            explicit_conflict_class=explicit_conflict_class,
            participants=participants,
            recovery_device_ids=recovery_ids,
            takeover_candidate_device_id=takeover_candidate_device_id,
            success_count=success_count,
            degraded_count=degraded_count,
            lost_count=lost_count,
            failed_count=failed_count,
        )

        reconcile_triggers = _compute_reconcile_triggers(
            terminal_kind=terminal_kind,
            participants=participants,
            recovery_device_ids=recovery_ids,
            explicit_conflict_class=explicit_conflict_class,
            formation_member_count=formation_member_count,
            lost_count=lost_count,
            degraded_count=degraded_count,
            takeover_candidate_device_id=takeover_candidate_device_id,
        )

        return ClosureCandidate(
            terminal_kind=terminal_kind,
            is_terminal=terminal_kind.is_terminal,
            reconcile_required=bool(reconcile_triggers),
            reconcile_triggers=reconcile_triggers,
            participants=participants,
            participant_count=len(participants),
            success_count=success_count,
            degraded_count=degraded_count,
            lost_count=lost_count,
            failed_count=failed_count,
            suspended_count=suspended_count,
            takeover_candidate_device_id=takeover_candidate_device_id or None,
            authority=MULTI_SUBJECT_CLOSURE_MACHINE_AUTHORITY,
            bridge_completion_state=bridge_completion_state,
        )


# Process-level singleton
_MACHINE_INSTANCE: Optional[MultiSubjectClosureMachine] = None


def get_multi_subject_closure_machine() -> MultiSubjectClosureMachine:
    """Return the process-level :class:`MultiSubjectClosureMachine` singleton."""
    global _MACHINE_INSTANCE
    if _MACHINE_INSTANCE is None:
        _MACHINE_INSTANCE = MultiSubjectClosureMachine()
    return _MACHINE_INSTANCE


# ---------------------------------------------------------------------------
# Public convenience functions
# ---------------------------------------------------------------------------


def build_closure_candidate(
    bridge_snapshot: Dict[str, Any],
    *,
    recovery_device_ids: Optional[Sequence[str]] = None,
    formation_member_count: int = 0,
) -> ClosureCandidate:
    """Build a :class:`ClosureCandidate` from a bridge snapshot.

    This is the primary entry point for the multi-subject closure state
    machine.  Callers in coordinator / orchestrator layers should call this
    function after obtaining a bridge snapshot from
    :func:`~core.multi_subject_truth_convergence_bridge.build_multi_subject_truth_bridge`.

    Parameters
    ----------
    bridge_snapshot:
        The dict returned by ``build_multi_subject_truth_bridge(...)``.
    recovery_device_ids:
        Device IDs that are known to be recovering from a prior failure.
    formation_member_count:
        Total members declared in the formation (for divergence detection).

    Returns
    -------
    ClosureCandidate
        Canonical closure output.  Never raises.
    """
    return get_multi_subject_closure_machine().apply(
        bridge_snapshot,
        recovery_device_ids=recovery_device_ids,
        formation_member_count=formation_member_count,
    )


def get_closure_output(
    bridge_snapshot: Dict[str, Any],
    *,
    recovery_device_ids: Optional[Sequence[str]] = None,
    formation_member_count: int = 0,
) -> ClosureCandidate:
    """Canonical consumption gate for operator / projection / outward-facing layers.

    Per ``OPERATOR_MUST_CONSUME_CANONICAL_CLOSURE_OUTPUT_POLICY``, operator
    and projection surfaces MUST call this function rather than reading the
    raw bridge snapshot or re-deriving closure decisions from participant
    signals.

    This is an alias for :func:`build_closure_candidate` with the same
    semantics but a name that makes the operator-consumption role explicit.

    Returns
    -------
    ClosureCandidate
        The canonical closure output for outward-facing consumption.
    """
    return build_closure_candidate(
        bridge_snapshot,
        recovery_device_ids=recovery_device_ids,
        formation_member_count=formation_member_count,
    )
