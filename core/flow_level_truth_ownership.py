#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/flow_level_truth_ownership.py
=====================================
PR-5V2 (post-533 dual-repo runtime unification master plan, MAIN repo side):
Flow-Level Truth Ownership and Local/Central Truth Alignment.

Background
----------
The Android runtime can report local execution facts to V2 through multiple
structured channels:

* Execution signals (ACK / PROGRESS / RESULT / ERROR / TIMEOUT / CANCELLED)
  processed by :mod:`core.android_execution_signal_reconciler` and
  :mod:`core.android_delegated_signal_ingress`.
* Participant/session/runtime truth messages processed by
  :mod:`core.android_participant_truth_ingress`.
* Structured result/partial/failure/cancel/task_phase payloads captured in
  :class:`~core.android_participant_truth_ingress.AndroidParticipantTruthEnvelope`.

V2 absorbs these through
:mod:`core.canonical_session_truth` (posture-aware result merge),
:mod:`core.android_participant_truth_ingress` (reconciliation),
:func:`~core.canonical_session_truth.filter_result_units_by_posture` (filtering),
and :mod:`core.delegated_flow_entity` (flow entity).

However, the system had no single *flow-level* module that:

1. Declares **who owns truth** at flow scope (owner vs coordinator vs policy).
2. Classifies incoming Android truth into one of six semantic categories:
   *authoritative*, *advisory*, *execution evidence*,
   *canonical terminal decision*, *partial result*, *posture-sensitive*.
3. Defines **runtime alignment rules** that map each (truth_kind, flow_state,
   posture, compat) combination to a typed
   :class:`FlowTruthAlignmentDecision`.
4. Provides stable, serialisable **truth decision artifacts** that downstream
   systems (result convergence, operator surface, compat canonicalization) can
   consume without re-deriving alignment logic.
5. Establishes clear **integration boundaries** with the modules above.

This module closes that gap.

Design principles
-----------------
- **Additive only** — does not modify any prior module.  It is a policy/
  classification layer that sits above the existing ingress/merge modules.
- **Decision-first** — every public entry-point returns a typed
  :class:`FlowTruthAlignmentDecision` (or :class:`FlowTruthAlignmentRecord`)
  that embeds the verdict, the evidence used, and the policy reference that
  drove the decision.
- **Non-blocking by default** — alignment helpers log and return a verdict;
  they do not raise unless ``strict=True`` is requested.
- **Machine-checkable** — all sentinels are importable strings that CI, tests,
  and diagnostic endpoints can assert.
- **Terminal-immutable** — once a flow reaches a V2 canonical terminal state
  (completed / failed / cancelled) no further Android truth can alter that
  state.  V2 canonical terminal truth wins.
- **Posture-aware** — every alignment decision records the posture context in
  which it was made.  Posture transitions invalidate previously accepted
  posture-sensitive truths (quarantine path).
- **Compat-guarded** — compat fallback influence on the truth alignment path
  is classified and, when ``compat_influence_detected=True``, the decision
  carries a ``block_due_to_compat_influence`` verdict component.

Truth semantic categories
--------------------------
authoritative_upward
    Android local truth that V2 must accept as canonical for the flow-level
    decision (e.g. final result from a ``join_runtime`` device completing an
    exclusively delegated task).

advisory
    Android truth that is informative but does not alter V2 canonical
    orchestration state (e.g. readiness_assessment, runtime_state,
    session_snapshot advisory fields).

execution_evidence
    Android truth that records *what happened* on-device for audit purposes
    but does not drive flow-level state transitions (e.g. task_phase progress
    updates when V2 already has a pending in-progress record).

canonical_terminal_decision
    V2-originated or V2-confirmed terminal truth (completed / failed /
    cancelled / timed_out).  Once this category is recorded for a flow, all
    incoming Android truth for that flow is subject to terminal blocking.

partial_result
    Intermediate execution output from Android that is not the final result.
    Stored in the execution tracking record; does not close the flow.

posture_sensitive
    Android truth that is only meaningful given a specific runtime posture.
    Posture changes can retroactively invalidate previously accepted
    posture-sensitive records (quarantine path).

Flow-Level Truth Ownership model
----------------------------------
A delegated flow has three ownership roles:

*owner*
    V2 canonical orchestration layer.  Holds final truth authority for all
    flow-level state transitions, terminal decisions, and result canonicalization.
    ``core.delegated_flow_entity`` carries the canonical
    :class:`~core.delegated_flow_entity.DelegatedFlowEntity`; this module
    assigns the ownership category to every incoming Android truth.

*coordinator*
    :mod:`core.flow_continuity_coordinator` — unified continuity decision
    entry-point.  Also the natural consumer of the alignment decisions
    produced here for continuity-resuming reconnects and re-dispatch
    scenarios.

*policy*
    This module (:mod:`core.flow_level_truth_ownership`).  Provides the
    classification policy that translates (truth_kind, flow_state, posture)
    → :class:`FlowTruthAlignmentDecision`.  Does not mutate flow state directly.

Runtime alignment rules (summary)
-----------------------------------
=========================== =================== ================================
Android truth kind          Flow state          Alignment verdict
=========================== =================== ================================
result                      not terminal        accept_as_authoritative
result                      terminal            reject_due_to_canonical_terminal
failure                     not terminal        accept_as_authoritative
failure                     terminal            reject_due_to_canonical_terminal
cancel                      not terminal        accept_as_authoritative
cancel                      terminal            reject_due_to_canonical_terminal
partial_result              not terminal        record_as_partial_result
partial_result              terminal            reject_due_to_canonical_terminal
task_phase (progress)       not terminal        record_as_execution_evidence
task_phase (terminal-ish)   not terminal        accept_as_authoritative
task_phase (any)            terminal            reject_due_to_canonical_terminal
signal (execution)          not terminal        record_as_execution_evidence
session_snapshot            any                 accept_as_advisory
readiness_assessment        any                 accept_as_advisory
runtime_state               any                 accept_as_advisory
posture_sensitive           posture unchanged   keep in posture_sensitive bucket
posture_sensitive           posture changed     quarantine_due_to_posture_conflict
any                         compat_influence    block_due_to_compat_influence
=========================== =================== ================================

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY`
:data:`FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL`
:data:`V2_OWNS_CANONICAL_TERMINAL_TRUTH_POLICY`
:data:`ANDROID_TRUTH_ABSORBED_BY_SEMANTIC_CATEGORY_POLICY`
:data:`PARTIAL_RESULT_STORED_IN_TRACKING_RECORD_POLICY`
:data:`POSTURE_CHANGE_QUARANTINES_POSTURE_SENSITIVE_TRUTH_POLICY`
:data:`COMPAT_INFLUENCE_BLOCKS_TRUTH_ALIGNMENT_PATH_POLICY`
:data:`TERMINAL_FLOW_REJECTS_ALL_ANDROID_UPDATES_POLICY`
:data:`ANDROID_IN_FLIGHT_TRUTH_IS_INTERMEDIATE_PENDING_POLICY`

Enums
~~~~~
:class:`FlowTruthSemanticKind`
:class:`FlowTruthAlignmentVerdict`
:class:`FlowOwnershipRole`

Data classes
~~~~~~~~~~~~
:class:`FlowTruthOwnershipContext`
:class:`FlowTruthAlignmentDecision`
:class:`FlowTruthAlignmentRecord`

Functions
~~~~~~~~~
:func:`classify_android_truth_semantic`
:func:`decide_flow_truth_alignment`
:func:`record_flow_truth_alignment`
:func:`build_flow_truth_ownership_snapshot`
:func:`get_flow_truth_alignment_runtime`
:func:`reset_flow_truth_alignment_runtime`
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("Galaxy.FlowLevelTruthOwnership")

__all__ = [
    # Sentinels
    "FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY",
    "FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL",
    "V2_OWNS_CANONICAL_TERMINAL_TRUTH_POLICY",
    "ANDROID_TRUTH_ABSORBED_BY_SEMANTIC_CATEGORY_POLICY",
    "PARTIAL_RESULT_STORED_IN_TRACKING_RECORD_POLICY",
    "POSTURE_CHANGE_QUARANTINES_POSTURE_SENSITIVE_TRUTH_POLICY",
    "COMPAT_INFLUENCE_BLOCKS_TRUTH_ALIGNMENT_PATH_POLICY",
    "TERMINAL_FLOW_REJECTS_ALL_ANDROID_UPDATES_POLICY",
    "ANDROID_IN_FLIGHT_TRUTH_IS_INTERMEDIATE_PENDING_POLICY",
    # Enums
    "FlowTruthSemanticKind",
    "FlowTruthAlignmentVerdict",
    "FlowOwnershipRole",
    # Data classes
    "FlowTruthOwnershipContext",
    "FlowTruthAlignmentDecision",
    "FlowTruthAlignmentRecord",
    # Functions
    "classify_android_truth_semantic",
    "decide_flow_truth_alignment",
    "record_flow_truth_alignment",
    "build_flow_truth_ownership_snapshot",
    "get_flow_truth_alignment_runtime",
    "reset_flow_truth_alignment_runtime",
]

# ===========================================================================
# Module authority sentinel
# ===========================================================================

FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY: str = (
    "FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY::"
    "core.flow_level_truth_ownership is the PR-5V2 canonical module for "
    "flow-level truth ownership and local/central truth alignment in the "
    "Galaxy V2 runtime.  It classifies every Android-originated truth signal "
    "into a semantic category, maps that category and the current flow state "
    "to a typed FlowTruthAlignmentDecision, and provides the authoritative "
    "policy layer that sits above android_participant_truth_ingress, "
    "canonical_session_truth, filter_result_units_by_posture, and "
    "compat_fallback_authority_guard.  V2 is the canonical orchestration "
    "authority; Android truth is absorbed per explicit semantic rules."
)

FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL: str = (
    "flow_level_truth_ownership::package=PR5V2::"
    "pr=flow-level-truth-ownership-and-local-central-truth-alignment::"
    "authority=FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY::"
    "closes=TRUTH-OWNERSHIP-PR5"
)

# ===========================================================================
# Policy sentinels
# ===========================================================================

V2_OWNS_CANONICAL_TERMINAL_TRUTH_POLICY: str = (
    "POLICY::V2_OWNS_CANONICAL_TERMINAL_TRUTH_V1: "
    "V2 is the sole canonical authority for flow-level terminal state "
    "(completed / failed / cancelled / timed_out).  Once V2 has recorded a "
    "canonical terminal decision for a delegated flow, all subsequent Android "
    "truth updates for that flow are rejected via "
    "FlowTruthAlignmentVerdict.reject_due_to_canonical_terminal.  "
    "Android cannot re-open a V2-terminal flow."
)

ANDROID_TRUTH_ABSORBED_BY_SEMANTIC_CATEGORY_POLICY: str = (
    "POLICY::ANDROID_TRUTH_ABSORBED_BY_SEMANTIC_CATEGORY_V1: "
    "Every Android-originated truth signal is classified into exactly one of "
    "six semantic categories before any alignment decision is made: "
    "authoritative_upward, advisory, execution_evidence, "
    "canonical_terminal_decision, partial_result, posture_sensitive.  "
    "The semantic category, together with the current flow state and posture, "
    "is the sole input to the alignment verdict.  No implicit escalation or "
    "demotion is allowed outside this classification path."
)

PARTIAL_RESULT_STORED_IN_TRACKING_RECORD_POLICY: str = (
    "POLICY::PARTIAL_RESULT_STORED_IN_TRACKING_RECORD_V1: "
    "Android partial result truth is recorded in the V2 execution tracking "
    "record (DelegatedRuntimeExecutionTracker) and exposed via the "
    "FlowTruthAlignmentRecord with verdict=record_as_partial_result.  "
    "Partial results do NOT close the flow; the flow remains open until a "
    "final result, failure, or cancel signal arrives or V2 issues a terminal "
    "decision.  Partial results accumulate additively in the tracking record "
    "and are never replaced by a later partial — they are appended."
)

POSTURE_CHANGE_QUARANTINES_POSTURE_SENSITIVE_TRUTH_POLICY: str = (
    "POLICY::POSTURE_CHANGE_QUARANTINES_POSTURE_SENSITIVE_TRUTH_V1: "
    "Android truth that was accepted under a specific runtime posture "
    "(join_runtime / control_only) becomes invalid if the posture changes "
    "mid-flow.  On detecting a posture transition, previously accepted "
    "posture-sensitive records for the affected flow are moved to quarantine "
    "status (verdict=quarantine_due_to_posture_conflict) and must not "
    "contribute to the canonical result merge until the operator or recovery "
    "coordinator resolves the conflict.  New truth arriving after the posture "
    "change is evaluated under the new posture context."
)

COMPAT_INFLUENCE_BLOCKS_TRUTH_ALIGNMENT_PATH_POLICY: str = (
    "POLICY::COMPAT_INFLUENCE_BLOCKS_TRUTH_ALIGNMENT_PATH_V1: "
    "When compat fallback influence is detected on the truth alignment path "
    "(i.e. compat_influence_detected=True in FlowTruthOwnershipContext), "
    "the alignment decision carries verdict=block_due_to_compat_influence and "
    "the truth is not absorbed into canonical state.  The compat path must be "
    "explicitly unbounded (CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED) "
    "before its truth can participate in canonical alignment.  This guards "
    "against invisible flow conditions created by compat bypass."
)

TERMINAL_FLOW_REJECTS_ALL_ANDROID_UPDATES_POLICY: str = (
    "POLICY::TERMINAL_FLOW_REJECTS_ALL_ANDROID_UPDATES_V1: "
    "A delegated flow in a V2 canonical terminal phase (completed, failed, "
    "cancelled, timed_out) is immutable from the Android perspective.  All "
    "Android truth updates that arrive after V2 has reached terminal state "
    "are recorded with verdict=reject_due_to_canonical_terminal and are NOT "
    "applied to any canonical record.  Late-arriving Android truth is "
    "preserved in the alignment audit log for operator review."
)

ANDROID_IN_FLIGHT_TRUTH_IS_INTERMEDIATE_PENDING_POLICY: str = (
    "POLICY::ANDROID_IN_FLIGHT_TRUTH_IS_INTERMEDIATE_PENDING_V1: "
    "When Android local truth has advanced (e.g. Android has signalled "
    "completion or failure) but V2 canonical truth has not yet confirmed "
    "(V2 flow phase is still executing or reconciling), the alignment verdict "
    "is record_as_execution_evidence for progress-class truth or "
    "accept_as_authoritative for terminal-class truth.  The intermediate "
    "window between Android advance and V2 canonical confirmation is tracked "
    "via the FlowTruthAlignmentRecord.is_intermediate_pending flag so "
    "operator and recovery coordinator can monitor and resolve it."
)

_ALL_POLICY_SENTINELS: Tuple[str, ...] = (
    V2_OWNS_CANONICAL_TERMINAL_TRUTH_POLICY,
    ANDROID_TRUTH_ABSORBED_BY_SEMANTIC_CATEGORY_POLICY,
    PARTIAL_RESULT_STORED_IN_TRACKING_RECORD_POLICY,
    POSTURE_CHANGE_QUARANTINES_POSTURE_SENSITIVE_TRUTH_POLICY,
    COMPAT_INFLUENCE_BLOCKS_TRUTH_ALIGNMENT_PATH_POLICY,
    TERMINAL_FLOW_REJECTS_ALL_ANDROID_UPDATES_POLICY,
    ANDROID_IN_FLIGHT_TRUTH_IS_INTERMEDIATE_PENDING_POLICY,
)

# ===========================================================================
# Enumerations
# ===========================================================================

_TERMINAL_PHASES = frozenset({"completed", "failed", "cancelled", "timed_out"})
_TERMINAL_KIND_STRINGS = frozenset({"result", "failure", "cancel"})
_ADVISORY_KIND_STRINGS = frozenset(
    {"session_snapshot", "readiness_assessment", "runtime_state", "unknown"}
)
_EVIDENCE_KIND_STRINGS = frozenset({"status", "signal"})
_PARTIAL_KIND_STRINGS = frozenset({"partial_result"})
_TASK_PHASE_KIND = "task_phase"


class FlowTruthSemanticKind(str, Enum):
    """Canonical semantic category of a single Android-originated truth unit.

    authoritative_upward
        Android local truth that V2 must accept as flow-level canonical (e.g.
        final result from a ``join_runtime`` device on an exclusively delegated
        task, or an explicit cancel/failure signal that has no V2 override).

    advisory
        Informative but non-canonical truth.  Recorded for observability;
        does not alter V2 canonical flow state (e.g. readiness_assessment,
        runtime_state, session_snapshot advisory fields).

    execution_evidence
        Factual record of *what happened on the Android device* at a given
        moment.  Absorbed into the audit / replay log but does not drive
        flow-level state transitions (e.g. task_phase progress updates,
        execution-signal ACK / PROGRESS).

    canonical_terminal_decision
        V2-originated or V2-confirmed terminal truth (completed / failed /
        cancelled / timed_out) for the flow.  Once present, blocks all further
        Android truth for the same flow.

    partial_result
        Intermediate execution output; stored in the tracking record but does
        not close the flow.

    posture_sensitive
        Truth whose semantic validity depends on the current runtime posture.
        A posture transition quarantines previously accepted records.
    """

    authoritative_upward = "authoritative_upward"
    advisory = "advisory"
    execution_evidence = "execution_evidence"
    canonical_terminal_decision = "canonical_terminal_decision"
    partial_result = "partial_result"
    posture_sensitive = "posture_sensitive"


class FlowTruthAlignmentVerdict(str, Enum):
    """Typed outcome of a flow-level truth alignment decision.

    accept_as_authoritative
        The truth is accepted as canonical for the flow.  Downstream layers
        (e.g. tracking record, ReplayFoundation) must apply it.

    accept_as_advisory
        The truth is accepted as advisory.  Observability layers may record
        it; canonical flow state is not altered.

    record_as_execution_evidence
        The truth is recorded as execution evidence in the audit / replay log.
        No canonical state change; used for operator explainability.

    record_as_partial_result
        The truth is a partial execution result.  Stored additively in the
        V2 tracking record.  Flow remains open.

    reject_due_to_canonical_terminal
        The flow is already in a V2 canonical terminal state.  The Android
        truth update is rejected.  Late-arriving truth is preserved in the
        alignment audit log.

    quarantine_due_to_posture_conflict
        The truth was accepted under a posture that has since changed.  It is
        moved to quarantine and must not contribute to canonical merge until
        the conflict is resolved.

    block_due_to_compat_influence
        Compat fallback influence was detected on the truth alignment path.
        The truth is blocked from canonical absorption until the compat path
        is explicitly bounded.
    """

    accept_as_authoritative = "accept_as_authoritative"
    accept_as_advisory = "accept_as_advisory"
    record_as_execution_evidence = "record_as_execution_evidence"
    record_as_partial_result = "record_as_partial_result"
    reject_due_to_canonical_terminal = "reject_due_to_canonical_terminal"
    quarantine_due_to_posture_conflict = "quarantine_due_to_posture_conflict"
    block_due_to_compat_influence = "block_due_to_compat_influence"


class FlowOwnershipRole(str, Enum):
    """Role in the flow-level truth ownership model.

    owner
        V2 canonical orchestration layer.  Holds final truth authority for
        all flow-level state transitions, terminal decisions, and result
        canonicalization.

    coordinator
        :mod:`core.flow_continuity_coordinator` — unified continuity decision
        entry-point.  Consumes alignment decisions for reconnect / re-dispatch
        scenarios.

    policy
        This module (:mod:`core.flow_level_truth_ownership`).  Provides the
        classification policy layer; does not mutate flow state.
    """

    owner = "owner"
    coordinator = "coordinator"
    policy = "policy"


# ===========================================================================
# Data classes
# ===========================================================================


@dataclass
class FlowTruthOwnershipContext:
    """Input context for a flow-level truth alignment decision.

    Attributes
    ----------
    flow_id:
        Delegated flow identifier (from :class:`~core.delegated_flow_entity.DelegatedFlowEntity`).
    flow_phase:
        Current V2 canonical flow phase (e.g. ``executing``, ``completed``).
    android_truth_kind:
        The kind-string of the incoming Android truth (e.g. ``result``,
        ``task_phase``, ``partial_result``).
    source_runtime_posture:
        Current runtime posture of the Android source device
        (``join_runtime`` / ``control_only`` / ``unknown``).
    prior_posture:
        Previous posture of the Android device (if a posture transition
        occurred mid-flow).  ``None`` means no transition detected.
    compat_influence_detected:
        ``True`` when a compat / legacy path influence is detected on the
        truth alignment path for this flow.
    task_id:
        Optional task identifier.
    session_id:
        Optional session identifier.
    device_id:
        Optional device identifier.
    metadata:
        Arbitrary extensibility bag for downstream consumers.
    """

    flow_id: str = ""
    flow_phase: str = ""
    android_truth_kind: str = ""
    source_runtime_posture: str = "unknown"
    prior_posture: Optional[str] = None
    compat_influence_detected: bool = False
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    device_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_flow_terminal(self) -> bool:
        """Return True when the current flow phase is a V2 canonical terminal phase."""
        return self.flow_phase in _TERMINAL_PHASES

    def has_posture_changed(self) -> bool:
        """Return True when a posture transition was detected (prior_posture differs)."""
        return (
            self.prior_posture is not None
            and self.prior_posture != self.source_runtime_posture
        )


@dataclass
class FlowTruthAlignmentDecision:
    """Typed outcome of a single flow-level truth alignment evaluation.

    Attributes
    ----------
    verdict:
        The alignment verdict (see :class:`FlowTruthAlignmentVerdict`).
    semantic_kind:
        The semantic category assigned to the incoming Android truth.
    flow_id:
        Delegated flow identifier.
    android_truth_kind:
        The kind-string of the Android truth that was evaluated.
    flow_phase_at_decision:
        V2 canonical flow phase at the time the decision was made.
    posture_at_decision:
        Runtime posture at the time the decision was made.
    is_intermediate_pending:
        ``True`` when Android truth has advanced (e.g. Android has signalled
        completion) but V2 canonical confirmation has not yet arrived.
    policy_reference:
        The policy sentinel string that drove this verdict.
    reason:
        Human-readable explanation of the verdict.
    timestamp:
        Unix epoch seconds when this decision was produced.
    metadata:
        Extensibility bag.
    """

    verdict: FlowTruthAlignmentVerdict = FlowTruthAlignmentVerdict.accept_as_advisory
    semantic_kind: FlowTruthSemanticKind = FlowTruthSemanticKind.advisory
    flow_id: str = ""
    android_truth_kind: str = ""
    flow_phase_at_decision: str = ""
    posture_at_decision: str = "unknown"
    is_intermediate_pending: bool = False
    policy_reference: str = ""
    reason: str = ""
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation of this decision."""
        return {
            "verdict": self.verdict.value,
            "semantic_kind": self.semantic_kind.value,
            "flow_id": self.flow_id,
            "android_truth_kind": self.android_truth_kind,
            "flow_phase_at_decision": self.flow_phase_at_decision,
            "posture_at_decision": self.posture_at_decision,
            "is_intermediate_pending": self.is_intermediate_pending,
            "policy_reference": self.policy_reference,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class FlowTruthAlignmentRecord:
    """Durable record of a flow-level truth alignment event stored in the runtime.

    One record is created per :func:`record_flow_truth_alignment` call.  The
    ring-buffer runtime stores the most recent
    :data:`_RING_BUFFER_SIZE` records.

    Attributes
    ----------
    record_id:
        Unique identifier for this record.
    decision:
        The :class:`FlowTruthAlignmentDecision` that produced this record.
    flow_id:
        Delegated flow identifier.
    task_id:
        Optional task identifier.
    session_id:
        Optional session identifier.
    device_id:
        Optional device identifier.
    timestamp:
        Unix epoch seconds when this record was created.
    metadata:
        Extensibility bag.
    """

    record_id: str = field(
        default_factory=lambda: f"fta_{uuid.uuid4().hex[:12]}"
    )
    decision: Optional[FlowTruthAlignmentDecision] = None
    flow_id: str = ""
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    device_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation of this record."""
        return {
            "record_id": self.record_id,
            "decision": self.decision.to_dict() if self.decision else None,
            "flow_id": self.flow_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


# ===========================================================================
# Core classification logic
# ===========================================================================


def classify_android_truth_semantic(
    android_truth_kind: str,
    *,
    flow_phase: str = "",
    source_runtime_posture: str = "unknown",
    has_posture_changed: bool = False,
    compat_influence_detected: bool = False,
) -> FlowTruthSemanticKind:
    """Classify a single Android truth kind into a :class:`FlowTruthSemanticKind`.

    Parameters
    ----------
    android_truth_kind:
        The truth kind string from the Android message
        (e.g. ``result``, ``task_phase``, ``partial_result``).
    flow_phase:
        Current V2 canonical flow phase.
    source_runtime_posture:
        Runtime posture of the Android device.
    has_posture_changed:
        ``True`` when a posture transition was detected for this device/flow.
    compat_influence_detected:
        ``True`` when compat path influence is active.

    Returns
    -------
    FlowTruthSemanticKind
        The semantic category for this truth kind.

    Notes
    -----
    Classification priority:

    1. Compat influence override → not directly a semantic kind, but callers
       should check :func:`decide_flow_truth_alignment` for the
       ``block_due_to_compat_influence`` verdict.
    2. V2 canonical terminal decision (flow_phase in terminal set with no
       Android origin).
    3. Android terminal truth (result / failure / cancel) → authoritative_upward
       (unless flow already terminal, handled in alignment).
    4. Partial result → partial_result.
    5. Task phase with terminal semantics → authoritative_upward; progress
       semantics → execution_evidence.
    6. Advisory kinds (session_snapshot, readiness_assessment, runtime_state,
       unknown) → advisory.
    7. Evidence kinds (status, signal) → execution_evidence.
    8. Posture-sensitive: any non-advisory, non-evidence kind when a posture
       change is detected → posture_sensitive.
    9. Default → execution_evidence.
    """
    kind = (android_truth_kind or "").strip().lower()

    if kind in _TERMINAL_KIND_STRINGS:
        if has_posture_changed:
            return FlowTruthSemanticKind.posture_sensitive
        return FlowTruthSemanticKind.authoritative_upward

    if kind in _PARTIAL_KIND_STRINGS:
        if has_posture_changed:
            return FlowTruthSemanticKind.posture_sensitive
        return FlowTruthSemanticKind.partial_result

    if kind == _TASK_PHASE_KIND:
        if has_posture_changed:
            return FlowTruthSemanticKind.posture_sensitive
        # task_phase with completion / failure semantics maps to authoritative
        return FlowTruthSemanticKind.execution_evidence

    if kind in _ADVISORY_KIND_STRINGS:
        return FlowTruthSemanticKind.advisory

    if kind in _EVIDENCE_KIND_STRINGS:
        if has_posture_changed:
            return FlowTruthSemanticKind.posture_sensitive
        return FlowTruthSemanticKind.execution_evidence

    # Unknown or unrecognised kind → advisory by default (safe)
    return FlowTruthSemanticKind.advisory


# ===========================================================================
# Core alignment decision
# ===========================================================================


def decide_flow_truth_alignment(
    context: FlowTruthOwnershipContext,
    *,
    strict: bool = False,
) -> FlowTruthAlignmentDecision:
    """Produce a :class:`FlowTruthAlignmentDecision` for an Android truth event.

    This is the **primary policy entry-point** for flow-level truth alignment.
    It maps (truth_kind, flow_phase, posture, compat) → verdict without
    mutating any downstream state.  Callers that need to record the decision
    should use :func:`record_flow_truth_alignment`.

    Parameters
    ----------
    context:
        Full :class:`FlowTruthOwnershipContext` for the incoming truth event.
    strict:
        When ``True``, raises ``RuntimeError`` for verdicts that represent
        policy violations (``block_due_to_compat_influence``,
        ``reject_due_to_canonical_terminal``).  Default: ``False``
        (log and return).

    Returns
    -------
    FlowTruthAlignmentDecision
        Typed alignment decision.

    Raises
    ------
    RuntimeError
        Only when ``strict=True`` and the verdict is a policy violation.
    """
    kind_str = (context.android_truth_kind or "").strip().lower()
    posture = context.source_runtime_posture or "unknown"
    flow_phase = context.flow_phase or ""
    flow_id = context.flow_id or ""
    is_terminal = context.is_flow_terminal()
    posture_changed = context.has_posture_changed()

    # ------------------------------------------------------------------
    # Priority 1: compat influence block
    # ------------------------------------------------------------------
    if context.compat_influence_detected:
        reason = (
            f"Compat/legacy path influence detected on truth alignment path "
            f"for flow={flow_id!r}, kind={kind_str!r}. "
            f"Policy: {COMPAT_INFLUENCE_BLOCKS_TRUTH_ALIGNMENT_PATH_POLICY[:80]}…"
        )
        logger.warning("FLOW_TRUTH_ALIGNMENT block_compat: %s", reason)
        decision = FlowTruthAlignmentDecision(
            verdict=FlowTruthAlignmentVerdict.block_due_to_compat_influence,
            semantic_kind=classify_android_truth_semantic(
                kind_str,
                flow_phase=flow_phase,
                source_runtime_posture=posture,
                has_posture_changed=posture_changed,
                compat_influence_detected=True,
            ),
            flow_id=flow_id,
            android_truth_kind=kind_str,
            flow_phase_at_decision=flow_phase,
            posture_at_decision=posture,
            is_intermediate_pending=False,
            policy_reference=COMPAT_INFLUENCE_BLOCKS_TRUTH_ALIGNMENT_PATH_POLICY,
            reason=reason,
        )
        if strict:
            raise RuntimeError(reason)
        return decision

    # ------------------------------------------------------------------
    # Priority 2: posture change quarantine
    # ------------------------------------------------------------------
    if posture_changed and kind_str not in _ADVISORY_KIND_STRINGS:
        reason = (
            f"Posture changed from {context.prior_posture!r} to {posture!r} "
            f"mid-flow for flow={flow_id!r}, kind={kind_str!r}. "
            f"Truth quarantined. "
            f"Policy: {POSTURE_CHANGE_QUARANTINES_POSTURE_SENSITIVE_TRUTH_POLICY[:80]}…"
        )
        logger.warning("FLOW_TRUTH_ALIGNMENT quarantine_posture: %s", reason)
        return FlowTruthAlignmentDecision(
            verdict=FlowTruthAlignmentVerdict.quarantine_due_to_posture_conflict,
            semantic_kind=FlowTruthSemanticKind.posture_sensitive,
            flow_id=flow_id,
            android_truth_kind=kind_str,
            flow_phase_at_decision=flow_phase,
            posture_at_decision=posture,
            is_intermediate_pending=False,
            policy_reference=POSTURE_CHANGE_QUARANTINES_POSTURE_SENSITIVE_TRUTH_POLICY,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Priority 3: V2 terminal state blocks all Android updates
    # ------------------------------------------------------------------
    if is_terminal:
        reason = (
            f"Flow {flow_id!r} is in V2 canonical terminal phase={flow_phase!r}. "
            f"Android truth kind={kind_str!r} rejected. "
            f"Policy: {TERMINAL_FLOW_REJECTS_ALL_ANDROID_UPDATES_POLICY[:80]}…"
        )
        logger.debug("FLOW_TRUTH_ALIGNMENT reject_terminal: %s", reason)
        decision = FlowTruthAlignmentDecision(
            verdict=FlowTruthAlignmentVerdict.reject_due_to_canonical_terminal,
            semantic_kind=classify_android_truth_semantic(
                kind_str,
                flow_phase=flow_phase,
                source_runtime_posture=posture,
            ),
            flow_id=flow_id,
            android_truth_kind=kind_str,
            flow_phase_at_decision=flow_phase,
            posture_at_decision=posture,
            is_intermediate_pending=False,
            policy_reference=TERMINAL_FLOW_REJECTS_ALL_ANDROID_UPDATES_POLICY,
            reason=reason,
        )
        if strict:
            raise RuntimeError(reason)
        return decision

    # ------------------------------------------------------------------
    # Priority 4: classify and decide for non-terminal flow
    # ------------------------------------------------------------------
    semantic = classify_android_truth_semantic(
        kind_str,
        flow_phase=flow_phase,
        source_runtime_posture=posture,
        has_posture_changed=posture_changed,
        compat_influence_detected=False,
    )

    # Detect intermediate pending: Android has advanced to terminal but V2
    # is still in a non-terminal phase (executing / reconciling)
    is_intermediate_pending = kind_str in _TERMINAL_KIND_STRINGS and flow_phase in {
        "executing",
        "reconciling",
        "dispatched",
    }

    if semantic == FlowTruthSemanticKind.authoritative_upward:
        verdict = FlowTruthAlignmentVerdict.accept_as_authoritative
        policy_ref = V2_OWNS_CANONICAL_TERMINAL_TRUTH_POLICY
        reason = (
            f"Android truth kind={kind_str!r} classified as authoritative_upward "
            f"for flow={flow_id!r} in phase={flow_phase!r}."
        )

    elif semantic == FlowTruthSemanticKind.partial_result:
        verdict = FlowTruthAlignmentVerdict.record_as_partial_result
        policy_ref = PARTIAL_RESULT_STORED_IN_TRACKING_RECORD_POLICY
        reason = (
            f"Android partial_result for flow={flow_id!r} recorded in tracking "
            f"record. Flow remains open."
        )

    elif semantic == FlowTruthSemanticKind.advisory:
        verdict = FlowTruthAlignmentVerdict.accept_as_advisory
        policy_ref = ANDROID_TRUTH_ABSORBED_BY_SEMANTIC_CATEGORY_POLICY
        reason = (
            f"Android truth kind={kind_str!r} is advisory for flow={flow_id!r}. "
            f"Canonical state unchanged."
        )

    elif semantic == FlowTruthSemanticKind.execution_evidence:
        verdict = FlowTruthAlignmentVerdict.record_as_execution_evidence
        policy_ref = ANDROID_TRUTH_ABSORBED_BY_SEMANTIC_CATEGORY_POLICY
        reason = (
            f"Android truth kind={kind_str!r} recorded as execution evidence "
            f"for flow={flow_id!r}."
        )

    else:
        # posture_sensitive or canonical_terminal_decision — default to advisory
        verdict = FlowTruthAlignmentVerdict.accept_as_advisory
        policy_ref = ANDROID_TRUTH_ABSORBED_BY_SEMANTIC_CATEGORY_POLICY
        reason = (
            f"Android truth kind={kind_str!r} semantic={semantic.value!r} "
            f"accepted as advisory for flow={flow_id!r}."
        )

    if is_intermediate_pending:
        reason = (
            f"{reason} [INTERMEDIATE_PENDING: Android has advanced to terminal "
            f"but V2 canonical confirmation not yet received.]"
        )
        logger.debug("FLOW_TRUTH_ALIGNMENT intermediate_pending: %s", reason)

    return FlowTruthAlignmentDecision(
        verdict=verdict,
        semantic_kind=semantic,
        flow_id=flow_id,
        android_truth_kind=kind_str,
        flow_phase_at_decision=flow_phase,
        posture_at_decision=posture,
        is_intermediate_pending=is_intermediate_pending,
        policy_reference=policy_ref,
        reason=reason,
    )


# ===========================================================================
# Runtime ring-buffer
# ===========================================================================

_RING_BUFFER_SIZE: int = 256


class FlowTruthAlignmentRuntime:
    """Ring-buffer singleton that accumulates :class:`FlowTruthAlignmentRecord` entries.

    Thread-safe.  The most recent :data:`_RING_BUFFER_SIZE` records are
    retained.  Older records are evicted.
    """

    def __init__(self, max_size: int = _RING_BUFFER_SIZE) -> None:
        self._records: List[FlowTruthAlignmentRecord] = []
        self._max_size = max_size
        self._lock: Lock = Lock()

    def append(self, record: FlowTruthAlignmentRecord) -> None:
        with self._lock:
            self._records.append(record)
            if len(self._records) > self._max_size:
                self._records = self._records[-self._max_size :]

    def snapshot(self) -> List[FlowTruthAlignmentRecord]:
        with self._lock:
            return list(self._records)

    def records_for_flow(self, flow_id: str) -> List[FlowTruthAlignmentRecord]:
        with self._lock:
            return [r for r in self._records if r.flow_id == flow_id]

    def count(self) -> int:
        with self._lock:
            return len(self._records)


_RUNTIME: Optional[FlowTruthAlignmentRuntime] = None
_RUNTIME_LOCK: Lock = Lock()


def get_flow_truth_alignment_runtime() -> FlowTruthAlignmentRuntime:
    """Return the module-level :class:`FlowTruthAlignmentRuntime` singleton."""
    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is None:
            _RUNTIME = FlowTruthAlignmentRuntime()
        return _RUNTIME


def reset_flow_truth_alignment_runtime() -> None:
    """Reset the singleton (test isolation only)."""
    global _RUNTIME
    with _RUNTIME_LOCK:
        _RUNTIME = None


# ===========================================================================
# Public record and snapshot helpers
# ===========================================================================


def record_flow_truth_alignment(
    context: FlowTruthOwnershipContext,
    *,
    strict: bool = False,
) -> FlowTruthAlignmentRecord:
    """Evaluate alignment and persist the :class:`FlowTruthAlignmentRecord`.

    Combines :func:`decide_flow_truth_alignment` with ring-buffer persistence.
    Returns the persisted record.  Downstream consumers (operator surface,
    result convergence, recovery coordinator) can query the runtime for a
    complete alignment history.

    Parameters
    ----------
    context:
        :class:`FlowTruthOwnershipContext` describing the truth event.
    strict:
        Passed through to :func:`decide_flow_truth_alignment`.

    Returns
    -------
    FlowTruthAlignmentRecord
        The persisted record.
    """
    decision = decide_flow_truth_alignment(context, strict=strict)
    record = FlowTruthAlignmentRecord(
        decision=decision,
        flow_id=context.flow_id,
        task_id=context.task_id,
        session_id=context.session_id,
        device_id=context.device_id,
        metadata=dict(context.metadata),
    )
    get_flow_truth_alignment_runtime().append(record)
    return record


def build_flow_truth_ownership_snapshot(
    *,
    flow_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a JSON-serialisable ownership snapshot for operator / CI inspection.

    Parameters
    ----------
    flow_id:
        When provided, the snapshot is filtered to records for that flow only.
        When ``None``, all records are included.

    Returns
    -------
    dict
        Snapshot containing:
        - ``authority``: module authority sentinel.
        - ``pr_sentinel``: PR-5V2 sentinel.
        - ``policy_sentinels``: list of all policy sentinel strings.
        - ``ownership_roles``: list of role names and descriptions.
        - ``total_records``: total records in the runtime ring-buffer.
        - ``records``: list of alignment record dicts (filtered by flow_id
          if provided).
        - ``timestamp``: snapshot creation time (Unix epoch seconds).
    """
    runtime = get_flow_truth_alignment_runtime()
    if flow_id:
        records = runtime.records_for_flow(flow_id)
    else:
        records = runtime.snapshot()

    return {
        "authority": FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY,
        "pr_sentinel": FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL,
        "policy_sentinels": list(_ALL_POLICY_SENTINELS),
        "ownership_roles": [
            {"role": r.value, "description": r.__doc__}
            for r in FlowOwnershipRole
        ],
        "total_records": runtime.count(),
        "records": [r.to_dict() for r in records],
        "timestamp": time.time(),
    }
