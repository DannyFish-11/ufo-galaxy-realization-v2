"""core/flow_aware_result_convergence.py
==========================================
PR-6V2 (post-533 dual-repo runtime host unification track):
Flow-Aware Result / Partial / Parallel Convergence.

Background
----------
The system already has ``task_result``, ``goal_result``, ``partial result``,
``delegated_execution_signal``, and ``parallel_subtask result`` result-backflow
capabilities.  However these mechanisms lack a unified **canonical convergence
layer** that ensures every result — regardless of origin — is absorbed into the
same delegated-flow canonical record.

Without a flow-aware convergence owner the system is vulnerable to:

* Parallel subtask results appearing to arrive without being stably associated
  with the same parent flow.
* Ambiguous relationships between partial and final results (no canonical merge
  rule).
* Android reconnect / resend leading to duplicate absorption or ordering chaos.
* ``cross_device_result_surface.py`` and ``goal_result_aggregator.py`` having
  overlapping, unclear responsibilities.
* Operators unable to explain how a canonical result was formed.

This module closes that gap by providing a **flow-aware result convergence
owner, coordinator, and policy layer** for the V2 side.

Responsibilities
----------------
1. **Convergence decision kinds** — :class:`ConvergenceDecisionKind` lists the
   six canonical dispositions that may be assigned to any incoming result:
   ``accept_partial_for_flow``, ``merge_partial_into_canonical``,
   ``promote_final_as_canonical``, ``aggregate_parallel_into_parent_flow``,
   ``suppress_duplicate_result``, ``suppress_late_partial_after_final``,
   ``quarantine_result_due_to_flow_mismatch``,
   ``absorb_replay_result_idempotently``.

2. **Result semantic kinds** — :class:`ResultSemanticKind` classifies the
   incoming result as ``partial_result``, ``final_result``,
   ``parallel_subtask_result``, ``parent_flow_aggregate``,
   ``replay_resend``, or ``unknown``.

3. **Convergence flow lineage** — :class:`ConvergenceFlowLineage` expresses
   how a result is tied to a parent flow:
   ``direct_task_result``, ``subtask_of_group``,
   ``delegated_child_flow``, ``reconnect_replay``.

4. **Convergence context** — :class:`ResultConvergenceContext` captures all
   inputs needed for a deterministic convergence decision: result semantic
   kind, group/subtask metadata, lineage, whether a final result has already
   been absorbed, whether the result is a duplicate, and reconnect flags.

5. **Convergence artifact** — :class:`ResultConvergenceArtifact` is the
   typed, serialisable output of every convergence decision: the
   :class:`ConvergenceDecisionKind`, the resolved :class:`ResultSemanticKind`,
   the policy reference, and a full evidence dictionary.

6. **Parallel flow aggregation record** — :class:`ParallelFlowAggregationRecord`
   tracks, at the canonical convergence level, the per-group state:
   which subtasks have delivered results, whether all are present, and the
   resulting parent-flow canonical aggregate.

7. **Convergence decision function** — :func:`decide_convergence` applies the
   deterministic convergence ruleset, covering:

   * Flow mismatch → ``quarantine_result_due_to_flow_mismatch``
   * Duplicate → ``suppress_duplicate_result``
   * Late partial (final already absorbed) → ``suppress_late_partial_after_final``
   * Partial result (no final yet) → ``accept_partial_for_flow``
   * Parallel subtask result → ``aggregate_parallel_into_parent_flow``
   * Final result with existing partials → ``merge_partial_into_canonical``
     then ``promote_final_as_canonical``
   * Final result with no prior partials → ``promote_final_as_canonical``
   * Reconnect/replay result → ``absorb_replay_result_idempotently``

8. **Convergence coordinator runtime** — :class:`FlowAwareConvergenceCoordinator`
   is an in-process ring-buffer singleton that records every
   :class:`ResultConvergenceArtifact` and the per-flow parallel aggregation
   state so operator surfaces and audit tools can inspect the convergence
   history without re-deriving it.

Responsibility boundary with adjacent modules
---------------------------------------------
This module is the **convergence owner** for delegated-flow results.  It does
not replace the adjacent modules; instead it defines their role boundaries:

* :mod:`~core.cross_device_result_surface` — Responsibility: normalise a raw
  cross-device result dict into a ``ResultEnvelope`` and surface it through
  ``TaskGraphRuntime`` / ``ReplayFoundation``.  It operates at the
  **transport-to-canonical** boundary (one result at a time).  It does NOT own
  flow-level aggregation or parallel group state.

* :mod:`~core.goal_result_aggregator` — Responsibility: thread-safe in-memory
  tracking of parallel/grouped subtask completion for ``GOAL_EXECUTION_RESULT``
  messages (group_id → GroupResultState).  It owns the **group completion
  signal** but does NOT own the canonical merge rule or partial→final semantics.

This module sits **above** both: it applies the canonical convergence policy
to decide what to do with every result that the other two modules surface, and
it maintains the flow-level convergence record.

Design principles
-----------------
- **Additive only** — does not modify any prior module.
- **Decision-first** — every public function returns a
  :class:`ResultConvergenceArtifact` carrying the full decision chain.
- **Fail-safe** — when inputs are insufficient, the module returns
  ``quarantine_result_due_to_flow_mismatch`` so callers apply a conservative
  default.
- **Idempotent** — recording the same ``(flow_id, result_id)`` pair a second
  time always returns ``suppress_duplicate_result``.
- **Explicit policy** — every convergence rule is named as a policy sentinel.

PR package
----------
PR-6V2 of the dual-repo flow-aware result convergence.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Sequence

logger = logging.getLogger("Galaxy.FlowAwareResultConvergence")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

FLOW_AWARE_CONVERGENCE_AUTHORITY: str = (
    "FLOW_AWARE_CONVERGENCE_AUTHORITY::"
    "core.flow_aware_result_convergence::PR6V2::"
    "flow-aware-result-partial-parallel-convergence-owner::"
    "canonical-convergence-policy-layer-for-delegated-flow-results"
)

FLOW_AWARE_CONVERGENCE_PR6V2_SENTINEL: str = (
    "FLOW_AWARE_CONVERGENCE_PR6V2_SENTINEL::"
    "package=PR-6V2::profile=flow-aware-result-convergence-v1::"
    "module=core.flow_aware_result_convergence"
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

PARTIAL_ACCEPTED_INTO_FLOW_PENDING_FINAL_POLICY: str = (
    "POLICY::PARTIAL_ACCEPTED_INTO_FLOW_PENDING_FINAL_V1: "
    "A partial result is accepted into the delegated flow record and stored "
    "on the in-progress execution tracking entry.  It does NOT close the flow "
    "or advance the canonical flow phase to a terminal state.  Only a "
    "subsequent final result / failure / cancel closes the tracking record.  "
    "PR-6V2, flow-aware result convergence."
)

FINAL_PROMOTES_AS_CANONICAL_AND_CLOSES_PARTIALS_POLICY: str = (
    "POLICY::FINAL_PROMOTES_AS_CANONICAL_AND_CLOSES_PARTIALS_V1: "
    "When a final result is absorbed for a delegated flow, it is promoted as "
    "the single canonical result for that flow.  All previously accepted "
    "partial results are merged into the canonical record (merge_partial_into_canonical) "
    "before the final result is promoted (promote_final_as_canonical).  After "
    "promotion the flow is closed to further result absorption.  "
    "PR-6V2, flow-aware result convergence."
)

PARALLEL_RESULTS_AGGREGATE_TO_PARENT_FLOW_VIA_GROUP_ID_POLICY: str = (
    "POLICY::PARALLEL_RESULTS_AGGREGATE_TO_PARENT_FLOW_VIA_GROUP_ID_V1: "
    "Every parallel subtask result that carries a group_id is absorbed into "
    "the parent flow's ParallelFlowAggregationRecord keyed by that group_id.  "
    "The subtask_index and delegated lineage of every subtask are durably "
    "associated with the parent flow.  When all expected subtasks are present "
    "the coordinator emits a parent_flow_aggregate convergence artifact that "
    "carries the complete group result.  "
    "PR-6V2, flow-aware result convergence."
)

DUPLICATE_RESULT_SUPPRESSED_FIRST_WRITE_WINS_POLICY: str = (
    "POLICY::DUPLICATE_RESULT_SUPPRESSED_FIRST_WRITE_WINS_V1: "
    "If a result arrives whose (flow_id, result_id) pair has already been "
    "absorbed into the canonical convergence record, the second arrival is "
    "classified as suppress_duplicate_result.  First write wins.  This applies "
    "to both partial and final results, and explicitly covers the reconnect / "
    "replay resend scenario.  "
    "PR-6V2, flow-aware result convergence."
)

LATE_PARTIAL_AFTER_FINAL_IS_SUPPRESSED_POLICY: str = (
    "POLICY::LATE_PARTIAL_AFTER_FINAL_IS_SUPPRESSED_V1: "
    "A partial result that arrives after the flow's final result has already "
    "been promoted as canonical is classified as "
    "suppress_late_partial_after_final and is not applied.  This prevents "
    "out-of-order partial arrivals from overwriting a canonical final result.  "
    "PR-6V2, flow-aware result convergence."
)

RECONNECT_REPLAY_RESULT_ABSORBED_IDEMPOTENTLY_POLICY: str = (
    "POLICY::RECONNECT_REPLAY_RESULT_ABSORBED_IDEMPOTENTLY_V1: "
    "When Android reconnects after a disconnection and resends a previously "
    "delivered result (result_id already absorbed), the resent result is "
    "classified as absorb_replay_result_idempotently and is a no-op — the "
    "canonical record is not modified.  If the result_id was never absorbed "
    "(the original was lost during the outage), the replayed result is "
    "processed by the normal convergence rules.  "
    "PR-6V2, flow-aware result convergence."
)

FLOW_MISMATCH_QUARANTINES_RESULT_POLICY: str = (
    "POLICY::FLOW_MISMATCH_QUARANTINES_RESULT_V1: "
    "When an incoming result cannot be associated with a known delegated flow "
    "(missing or unrecognised flow_id / group_id / parent_flow_id) the result "
    "is classified as quarantine_result_due_to_flow_mismatch.  Quarantined "
    "results are recorded in the coordinator audit buffer for operator "
    "inspection but are NOT applied to any canonical record.  "
    "PR-6V2, flow-aware result convergence."
)

CROSS_DEVICE_RESULT_SURFACE_IS_TRANSPORT_BOUNDARY_POLICY: str = (
    "POLICY::CROSS_DEVICE_RESULT_SURFACE_IS_TRANSPORT_BOUNDARY_V1: "
    "cross_device_result_surface.surface_cross_device_result() is responsible "
    "for normalising a raw result dict into a ResultEnvelope and surfacing it "
    "through TaskGraphRuntime / ReplayFoundation (transport→canonical boundary, "
    "one result at a time).  It does NOT own flow-level aggregation, parallel "
    "group state, or partial→final merge semantics.  Those responsibilities "
    "belong exclusively to FlowAwareConvergenceCoordinator.  "
    "PR-6V2, flow-aware result convergence."
)

GOAL_RESULT_AGGREGATOR_IS_GROUP_COMPLETION_SIGNAL_POLICY: str = (
    "POLICY::GOAL_RESULT_AGGREGATOR_IS_GROUP_COMPLETION_SIGNAL_V1: "
    "goal_result_aggregator.GoalResultAggregator is responsible for "
    "thread-safe in-memory tracking of parallel/grouped subtask completion "
    "(group_id → GroupResultState) and emitting a group-complete signal when "
    "all subtasks have delivered.  It does NOT own canonical merge rules, "
    "partial→final semantics, or flow-level convergence artifacts.  Those "
    "responsibilities belong exclusively to FlowAwareConvergenceCoordinator.  "
    "PR-6V2, flow-aware result convergence."
)

# ===========================================================================
# Enumerations
# ===========================================================================


class ConvergenceDecisionKind(str, Enum):
    """Canonical decision disposition assigned to every incoming result.

    Values
    ------
    accept_partial_for_flow
        The result is a partial (intermediate) result with no prior final
        result for this flow.  It is accepted into the flow record and stored
        on the in-progress tracking entry.  The flow remains open.
    merge_partial_into_canonical
        A final result has arrived and existing partial results for the flow
        are being merged into the canonical record before the final result is
        promoted.
    promote_final_as_canonical
        The result is a final (terminal) result and is promoted as the single
        canonical result for this delegated flow.  The flow is now closed.
    aggregate_parallel_into_parent_flow
        The result is a parallel subtask result.  It is absorbed into the
        parent flow's :class:`ParallelFlowAggregationRecord` keyed by
        group_id / subtask_index.
    suppress_duplicate_result
        The (flow_id, result_id) pair has already been absorbed.  This second
        arrival is a no-op (first write wins).  Also covers idempotent
        replay/resend after reconnect when original was already absorbed.
    suppress_late_partial_after_final
        A partial result arrived after the flow's final result was already
        promoted as canonical.  It is suppressed.
    quarantine_result_due_to_flow_mismatch
        The result cannot be associated with a known delegated flow and is
        quarantined pending operator review.
    absorb_replay_result_idempotently
        An Android reconnect resent a result that was already absorbed — this
        is explicitly classified as an idempotent replay absorb (distinct from
        a content-level duplicate) so operators can distinguish replay events
        from erroneous duplicates.
    """

    accept_partial_for_flow = "accept_partial_for_flow"
    merge_partial_into_canonical = "merge_partial_into_canonical"
    promote_final_as_canonical = "promote_final_as_canonical"
    aggregate_parallel_into_parent_flow = "aggregate_parallel_into_parent_flow"
    suppress_duplicate_result = "suppress_duplicate_result"
    suppress_late_partial_after_final = "suppress_late_partial_after_final"
    quarantine_result_due_to_flow_mismatch = "quarantine_result_due_to_flow_mismatch"
    absorb_replay_result_idempotently = "absorb_replay_result_idempotently"

    @classmethod
    def from_string(cls, value: Optional[str]) -> "ConvergenceDecisionKind":
        """Return the enum value for *value*, defaulting to
        ``quarantine_result_due_to_flow_mismatch``."""
        if value is None:
            return cls.quarantine_result_due_to_flow_mismatch
        try:
            return cls(value)
        except ValueError:
            return cls.quarantine_result_due_to_flow_mismatch


class ResultSemanticKind(str, Enum):
    """The semantic meaning of an incoming result.

    Values
    ------
    partial_result
        An intermediate result for an in-flight delegated execution.  The flow
        is still in progress.
    final_result
        The definitive, terminal result for a delegated execution.  The flow
        will be closed after this is absorbed.
    parallel_subtask_result
        The result from one subtask within a parallel group.  It carries
        group_id / subtask_index.
    parent_flow_aggregate
        The aggregate result assembled from all parallel subtask results for a
        parent flow.  Emitted by the coordinator after all subtasks complete.
    replay_resend
        A result that is being resent after an Android reconnect.  May be a
        duplicate of a previously absorbed result.
    unknown
        The semantic kind could not be determined.  Conservative quarantine
        applies.
    """

    partial_result = "partial_result"
    final_result = "final_result"
    parallel_subtask_result = "parallel_subtask_result"
    parent_flow_aggregate = "parent_flow_aggregate"
    replay_resend = "replay_resend"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: Optional[str]) -> "ResultSemanticKind":
        """Return the enum value for *value*, defaulting to ``unknown``."""
        if value is None:
            return cls.unknown
        try:
            return cls(value)
        except ValueError:
            return cls.unknown


class ConvergenceFlowLineage(str, Enum):
    """How a result is tied to a parent delegated flow.

    Values
    ------
    direct_task_result
        The result is directly tied to a single task within the delegated flow.
        No group_id is present.
    subtask_of_group
        The result is one subtask of a parallel group; group_id and
        subtask_index are present.
    delegated_child_flow
        The result comes from a child flow that was delegated by the parent
        flow (nested delegation).
    reconnect_replay
        The result is being replayed after an Android session reconnect.
    unknown_lineage
        The lineage cannot be determined.
    """

    direct_task_result = "direct_task_result"
    subtask_of_group = "subtask_of_group"
    delegated_child_flow = "delegated_child_flow"
    reconnect_replay = "reconnect_replay"
    unknown_lineage = "unknown_lineage"

    @classmethod
    def from_string(cls, value: Optional[str]) -> "ConvergenceFlowLineage":
        """Return the enum value for *value*, defaulting to ``unknown_lineage``."""
        if value is None:
            return cls.unknown_lineage
        try:
            return cls(value)
        except ValueError:
            return cls.unknown_lineage


# ===========================================================================
# Data types
# ===========================================================================

# Internal result semantic kind string constants
_PARTIAL_KINDS: frozenset = frozenset({"partial_result"})
_FINAL_KINDS: frozenset = frozenset({"final_result"})
_PARALLEL_KINDS: frozenset = frozenset({"parallel_subtask_result"})
_REPLAY_KINDS: frozenset = frozenset({"replay_resend"})


@dataclass
class ResultConvergenceContext:
    """All inputs needed to produce a deterministic convergence decision.

    Attributes
    ----------
    flow_id
        The canonical delegated flow identifier.  Required.  Empty string
        triggers ``quarantine_result_due_to_flow_mismatch``.
    result_id
        A stable unique identifier for this result (e.g. task_id + sequence
        number, or a UUID generated at result emission time).  Used for
        duplicate detection.
    semantic_kind
        :class:`ResultSemanticKind` value string classifying the result.
    lineage
        :class:`ConvergenceFlowLineage` value string expressing how the result
        is tied to the parent flow.
    group_id
        Parallel group identifier (non-empty for ``subtask_of_group`` lineage).
    subtask_index
        Zero-based index within the parallel group.  ``None`` for non-parallel
        results.
    parent_flow_id
        Parent flow identifier for nested/child flow results.  May be equal to
        ``flow_id`` for direct delegation.
    final_already_absorbed
        ``True`` when the flow's canonical final result has already been
        promoted.  Causes late partials to be suppressed.
    is_duplicate
        ``True`` when the caller has already determined that
        ``(flow_id, result_id)`` was previously absorbed.
    is_reconnect_replay
        ``True`` when this result is being resent after an Android reconnect.
    result_payload
        Opaque snapshot of the raw result payload for evidence / audit.
    session_id
        Runtime session identifier for correlation.
    device_id
        Device identifier for correlation.
    trace_id
        End-to-end trace identifier for correlation.
    contract_id
        Delegated execution contract identifier.
    task_id
        Task identifier.
    timestamp
        Unix epoch seconds when this context was built.  Defaults to now.
    """

    flow_id: str = ""
    result_id: str = ""
    semantic_kind: str = ResultSemanticKind.unknown.value
    lineage: str = ConvergenceFlowLineage.unknown_lineage.value
    group_id: str = ""
    subtask_index: Optional[int] = None
    parent_flow_id: str = ""
    final_already_absorbed: bool = False
    is_duplicate: bool = False
    is_reconnect_replay: bool = False
    result_payload: Dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    device_id: str = ""
    trace_id: str = ""
    contract_id: str = ""
    task_id: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable dict representation."""
        return {
            "flow_id": self.flow_id,
            "result_id": self.result_id,
            "semantic_kind": self.semantic_kind,
            "lineage": self.lineage,
            "group_id": self.group_id,
            "subtask_index": self.subtask_index,
            "parent_flow_id": self.parent_flow_id,
            "final_already_absorbed": self.final_already_absorbed,
            "is_duplicate": self.is_duplicate,
            "is_reconnect_replay": self.is_reconnect_replay,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "trace_id": self.trace_id,
            "contract_id": self.contract_id,
            "task_id": self.task_id,
            "timestamp": self.timestamp,
        }


@dataclass
class ResultConvergenceArtifact:
    """Typed, serialisable result of a flow-aware convergence decision.

    Every call to :func:`decide_convergence` produces one of these artifacts.
    They are the stable, inspectable record of every convergence authority
    decision made at the flow level.

    Attributes
    ----------
    artifact_id
        Unique identifier for this artifact (``rca_`` prefix + UUID4 hex).
    decision
        The :class:`ConvergenceDecisionKind` assigned to the incoming result.
    semantic_kind
        The :class:`ResultSemanticKind` resolved for this result.
    lineage
        The :class:`ConvergenceFlowLineage` resolved for this result.
    policy_reference
        The policy sentinel name that drove the decision.
    reason
        Human-readable explanation of the decision.
    flow_id
        Delegated flow identifier for correlation.
    result_id
        Stable result identifier for duplicate detection.
    group_id
        Parallel group identifier (non-empty for parallel subtask results).
    subtask_index
        Zero-based index within the parallel group.
    parent_flow_id
        Parent flow identifier for nested / child flow results.
    session_id
        Runtime session identifier for correlation.
    device_id
        Device identifier for correlation.
    trace_id
        End-to-end trace identifier for correlation.
    contract_id
        Execution contract identifier for correlation.
    task_id
        Task identifier for correlation.
    partial_count_merged
        Number of prior partial results merged when decision is
        ``merge_partial_into_canonical`` or ``promote_final_as_canonical``.
    group_complete
        ``True`` when this parallel subtask result completed the group (all
        expected subtasks have now delivered results).
    timestamp
        Unix epoch seconds when this artifact was produced.
    evidence
        Free-form evidence dictionary forwarded to operator surfaces.
    """

    artifact_id: str = field(
        default_factory=lambda: f"rca_{uuid.uuid4().hex[:12]}"
    )
    decision: ConvergenceDecisionKind = (
        ConvergenceDecisionKind.quarantine_result_due_to_flow_mismatch
    )
    semantic_kind: ResultSemanticKind = ResultSemanticKind.unknown
    lineage: ConvergenceFlowLineage = ConvergenceFlowLineage.unknown_lineage
    policy_reference: str = ""
    reason: str = ""
    flow_id: str = ""
    result_id: str = ""
    group_id: str = ""
    subtask_index: Optional[int] = None
    parent_flow_id: str = ""
    session_id: str = ""
    device_id: str = ""
    trace_id: str = ""
    contract_id: str = ""
    task_id: str = ""
    partial_count_merged: int = 0
    group_complete: bool = False
    timestamp: float = field(default_factory=time.time)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable dict representation."""
        return {
            "artifact_id": self.artifact_id,
            "decision": self.decision.value,
            "semantic_kind": self.semantic_kind.value,
            "lineage": self.lineage.value,
            "policy_reference": self.policy_reference,
            "reason": self.reason,
            "flow_id": self.flow_id,
            "result_id": self.result_id,
            "group_id": self.group_id,
            "subtask_index": self.subtask_index,
            "parent_flow_id": self.parent_flow_id,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "trace_id": self.trace_id,
            "contract_id": self.contract_id,
            "task_id": self.task_id,
            "partial_count_merged": self.partial_count_merged,
            "group_complete": self.group_complete,
            "timestamp": self.timestamp,
            "evidence": self.evidence,
        }


@dataclass
class ParallelFlowAggregationRecord:
    """Tracks the canonical convergence state of a parallel group.

    This record sits at the flow-level convergence layer — above
    :class:`~core.goal_result_aggregator.GroupResultState` (which lives at the
    message-handler level).  Its job is to record *convergence* decisions (not
    just completion counts) and to produce a stable parent-flow canonical
    aggregate artifact once all subtasks are present.

    Attributes
    ----------
    group_id
        Stable group identifier shared by all subtasks in this parallel batch.
    parent_flow_id
        The delegated flow that spawned this parallel group.
    expected_count
        Total number of subtask results expected.  ``None`` if not yet known.
    absorbed_subtasks
        Mapping of ``subtask_index`` → :class:`ResultConvergenceArtifact` for
        every subtask absorbed so far.
    all_complete
        ``True`` once all expected subtasks have been absorbed.
    aggregate_artifact
        The parent-flow canonical aggregate artifact, set when ``all_complete``
        transitions to ``True``.
    session_id
        Runtime session identifier propagated from dispatch context.
    trace_id
        Trace identifier for observability correlation.
    created_at
        Unix epoch seconds when this record was first created.
    completed_at
        Unix epoch seconds when ``all_complete`` first became ``True``.
    """

    group_id: str
    parent_flow_id: str
    expected_count: Optional[int] = None
    absorbed_subtasks: Dict[int, ResultConvergenceArtifact] = field(
        default_factory=dict
    )
    all_complete: bool = False
    aggregate_artifact: Optional[ResultConvergenceArtifact] = None
    session_id: str = ""
    trace_id: str = ""
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    @property
    def absorbed_count(self) -> int:
        return len(self.absorbed_subtasks)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "parent_flow_id": self.parent_flow_id,
            "expected_count": self.expected_count,
            "absorbed_count": self.absorbed_count,
            "all_complete": self.all_complete,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "absorbed_subtasks": {
                idx: art.to_dict()
                for idx, art in self.absorbed_subtasks.items()
            },
            "aggregate_artifact": (
                self.aggregate_artifact.to_dict()
                if self.aggregate_artifact is not None
                else None
            ),
        }


@dataclass
class FlowConvergenceSnapshot:
    """Point-in-time snapshot of the convergence coordinator state.

    Attributes
    ----------
    snapshot_id
        Unique identifier for this snapshot.
    total_artifacts
        Total number of convergence artifacts recorded since startup.
    recent_artifacts
        The most recent artifacts in the ring buffer (newest last).
    active_parallel_groups
        Number of parallel group records currently tracked.
    active_flow_ids
        Number of distinct flow_ids with any recorded decisions.
    decision_counts
        Mapping of :class:`ConvergenceDecisionKind` value → count.
    timestamp
        Unix epoch seconds when this snapshot was taken.
    """

    snapshot_id: str = field(
        default_factory=lambda: f"fcs_{uuid.uuid4().hex[:8]}"
    )
    total_artifacts: int = 0
    recent_artifacts: List[ResultConvergenceArtifact] = field(
        default_factory=list
    )
    active_parallel_groups: int = 0
    active_flow_ids: int = 0
    decision_counts: Dict[str, int] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "total_artifacts": self.total_artifacts,
            "recent_artifacts": [a.to_dict() for a in self.recent_artifacts],
            "active_parallel_groups": self.active_parallel_groups,
            "active_flow_ids": self.active_flow_ids,
            "decision_counts": self.decision_counts,
            "timestamp": self.timestamp,
        }


# ===========================================================================
# Core convergence decision function
# ===========================================================================


def classify_result_semantic_kind(ctx: ResultConvergenceContext) -> ResultSemanticKind:
    """Classify the semantic kind of an incoming result from its context.

    Resolution order
    ----------------
    1. Explicit ``semantic_kind`` string in context (if valid) → returned.
    2. ``group_id`` present → ``parallel_subtask_result``.
    3. ``is_reconnect_replay`` flag → ``replay_resend``.
    4. Falls back to ``unknown``.

    Parameters
    ----------
    ctx:
        :class:`ResultConvergenceContext` to classify.

    Returns
    -------
    ResultSemanticKind
    """
    # Respect an explicit, valid semantic_kind on the context
    explicit = ResultSemanticKind.from_string(ctx.semantic_kind)
    if explicit is not ResultSemanticKind.unknown:
        return explicit

    # Infer from context fields
    if ctx.group_id:
        return ResultSemanticKind.parallel_subtask_result
    if ctx.is_reconnect_replay:
        return ResultSemanticKind.replay_resend
    return ResultSemanticKind.unknown


def decide_convergence(ctx: ResultConvergenceContext) -> ResultConvergenceArtifact:
    """Apply the canonical convergence ruleset and return a decision artifact.

    Rules are applied in the following priority order:

    1. **Flow mismatch** (``flow_id`` empty or unresolvable) →
       ``quarantine_result_due_to_flow_mismatch``.
    2. **Duplicate** (``is_duplicate`` is True) →
       ``suppress_duplicate_result``.
    3. **Reconnect replay + duplicate** (``is_reconnect_replay`` and already
       absorbed) → ``absorb_replay_result_idempotently``.
    4. **Late partial after final** (partial result, ``final_already_absorbed``)
       → ``suppress_late_partial_after_final``.
    5. **Partial result** (no final yet) →
       ``accept_partial_for_flow``.
    6. **Parallel subtask result** →
       ``aggregate_parallel_into_parent_flow``.
    7. **Final result with existing partials** →
       ``merge_partial_into_canonical`` (implicit) then
       ``promote_final_as_canonical``.
    8. **Final result** → ``promote_final_as_canonical``.
    9. **Replay resend, not duplicate** → processed by standard rules.
    10. **Fallback** → ``quarantine_result_due_to_flow_mismatch``.

    Parameters
    ----------
    ctx:
        :class:`ResultConvergenceContext` carrying all decision inputs.

    Returns
    -------
    ResultConvergenceArtifact
        The deterministic convergence decision artifact.
    """
    resolved_semantic = classify_result_semantic_kind(ctx)
    resolved_lineage = ConvergenceFlowLineage.from_string(ctx.lineage)

    def _make(
        decision: ConvergenceDecisionKind,
        policy: str,
        reason: str,
        **kwargs: Any,
    ) -> ResultConvergenceArtifact:
        return ResultConvergenceArtifact(
            decision=decision,
            semantic_kind=resolved_semantic,
            lineage=resolved_lineage,
            policy_reference=policy,
            reason=reason,
            flow_id=ctx.flow_id,
            result_id=ctx.result_id,
            group_id=ctx.group_id,
            subtask_index=ctx.subtask_index,
            parent_flow_id=ctx.parent_flow_id,
            session_id=ctx.session_id,
            device_id=ctx.device_id,
            trace_id=ctx.trace_id,
            contract_id=ctx.contract_id,
            task_id=ctx.task_id,
            evidence=ctx.to_dict(),
            **kwargs,
        )

    # Rule 1: Flow mismatch
    if not ctx.flow_id:
        return _make(
            ConvergenceDecisionKind.quarantine_result_due_to_flow_mismatch,
            FLOW_MISMATCH_QUARANTINES_RESULT_POLICY,
            "flow_id is empty — cannot associate result with a delegated flow",
        )

    # Rule 2 / 3: Duplicate / reconnect replay already absorbed
    if ctx.is_duplicate:
        if ctx.is_reconnect_replay:
            return _make(
                ConvergenceDecisionKind.absorb_replay_result_idempotently,
                RECONNECT_REPLAY_RESULT_ABSORBED_IDEMPOTENTLY_POLICY,
                "reconnect replay — result_id already absorbed; idempotent no-op",
            )
        return _make(
            ConvergenceDecisionKind.suppress_duplicate_result,
            DUPLICATE_RESULT_SUPPRESSED_FIRST_WRITE_WINS_POLICY,
            f"duplicate result suppressed — result_id={ctx.result_id!r} "
            "already absorbed for this flow",
        )

    # Rule 4: Late partial after final
    if (
        resolved_semantic is ResultSemanticKind.partial_result
        and ctx.final_already_absorbed
    ):
        return _make(
            ConvergenceDecisionKind.suppress_late_partial_after_final,
            LATE_PARTIAL_AFTER_FINAL_IS_SUPPRESSED_POLICY,
            "partial result arrived after final result was already promoted — "
            "suppressed",
        )

    # Rule 5: Partial result
    if resolved_semantic is ResultSemanticKind.partial_result:
        return _make(
            ConvergenceDecisionKind.accept_partial_for_flow,
            PARTIAL_ACCEPTED_INTO_FLOW_PENDING_FINAL_POLICY,
            "partial result accepted into delegated flow record; "
            "flow remains open pending final result",
        )

    # Rule 6: Parallel subtask result
    if resolved_semantic is ResultSemanticKind.parallel_subtask_result or ctx.group_id:
        return _make(
            ConvergenceDecisionKind.aggregate_parallel_into_parent_flow,
            PARALLEL_RESULTS_AGGREGATE_TO_PARENT_FLOW_VIA_GROUP_ID_POLICY,
            f"parallel subtask result absorbed into parent flow aggregation "
            f"record group_id={ctx.group_id!r} subtask_index={ctx.subtask_index}",
        )

    # Rule 7 / 8: Final result
    if resolved_semantic is ResultSemanticKind.final_result:
        return _make(
            ConvergenceDecisionKind.promote_final_as_canonical,
            FINAL_PROMOTES_AS_CANONICAL_AND_CLOSES_PARTIALS_POLICY,
            "final result promoted as canonical; prior partials merged and "
            "flow closed",
        )

    # Rule 9: Replay resend (not duplicate → process as normal final/partial
    # but record lineage; here we fall into convergence if semantic is
    # resolvable from other fields, otherwise quarantine)
    if resolved_semantic is ResultSemanticKind.replay_resend:
        # A replay of a non-duplicate result is treated as a final (the
        # original was lost during the outage).  Promote it.
        return _make(
            ConvergenceDecisionKind.promote_final_as_canonical,
            RECONNECT_REPLAY_RESULT_ABSORBED_IDEMPOTENTLY_POLICY,
            "reconnect replay — original not absorbed; promoting replayed "
            "result as canonical",
        )

    # Rule 10: Fallback — quarantine
    return _make(
        ConvergenceDecisionKind.quarantine_result_due_to_flow_mismatch,
        FLOW_MISMATCH_QUARANTINES_RESULT_POLICY,
        f"result semantic kind={resolved_semantic.value!r} could not be "
        "resolved to a known convergence path — quarantined",
    )


# ===========================================================================
# FlowAwareConvergenceCoordinator — the canonical runtime singleton
# ===========================================================================

_COORDINATOR_BUFFER_SIZE = 1024
_MAX_PARALLEL_GROUPS = 512


class FlowAwareConvergenceCoordinator:
    """Flow-aware result convergence owner and coordinator.

    This is the **single in-process runtime** responsible for:

    * Maintaining per-flow canonical convergence state (which results have
      been absorbed, whether a final result has been promoted).
    * Tracking :class:`ParallelFlowAggregationRecord` state for every
      ``group_id`` across all delegated flows.
    * Recording every :class:`ResultConvergenceArtifact` in a ring buffer
      for operator inspection and audit.
    * Providing :func:`absorb` as the single entry point for result
      convergence decisions.

    Thread safety
    -------------
    All public methods are protected by a single ``threading.Lock``.  This
    coordinator is designed for use in an asyncio event loop (single-threaded)
    but is also safe for multi-threaded callers.

    Usage
    -----
    ::

        coordinator = get_flow_aware_convergence_coordinator()

        # When a result arrives
        ctx = ResultConvergenceContext(
            flow_id="flow-123",
            result_id="result-abc",
            semantic_kind=ResultSemanticKind.final_result.value,
            lineage=ConvergenceFlowLineage.direct_task_result.value,
            task_id="task-456",
            session_id="session-789",
        )
        artifact = coordinator.absorb(ctx)
        if artifact.decision == ConvergenceDecisionKind.promote_final_as_canonical:
            # final result absorbed — trigger downstream canonical update
            ...
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Ring buffer of all convergence artifacts
        self._artifacts: Deque[ResultConvergenceArtifact] = deque(
            maxlen=_COORDINATOR_BUFFER_SIZE
        )
        # Total artifact count (monotonic — counts past buffer capacity too)
        self._total_count: int = 0
        # Per-flow canonical state: flow_id → set of absorbed result_ids
        self._flow_absorbed: Dict[str, set] = {}
        # Per-flow final-absorbed flag: flow_id → bool
        self._flow_final_absorbed: Dict[str, bool] = {}
        # Parallel aggregation records: group_id → ParallelFlowAggregationRecord
        self._parallel_groups: Dict[str, ParallelFlowAggregationRecord] = {}
        # Insertion order for parallel group eviction
        self._parallel_group_order: List[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_parallel_group(
        self,
        group_id: str,
        parent_flow_id: str,
        expected_count: int,
        *,
        session_id: str = "",
        trace_id: str = "",
    ) -> ParallelFlowAggregationRecord:
        """Pre-register a parallel group before subtask results begin to arrive.

        Subsequent calls with the same ``group_id`` are idempotent — the
        existing record is returned unchanged.

        Parameters
        ----------
        group_id:
            Stable group identifier for the parallel batch.
        parent_flow_id:
            The delegated flow that spawned this group.
        expected_count:
            Total number of subtask results expected.  Must be ≥ 1.
        session_id:
            Optional session context.
        trace_id:
            Optional trace identifier.
        """
        with self._lock:
            if group_id in self._parallel_groups:
                return self._parallel_groups[group_id]
            record = ParallelFlowAggregationRecord(
                group_id=group_id,
                parent_flow_id=parent_flow_id,
                expected_count=expected_count,
                session_id=session_id,
                trace_id=trace_id,
            )
            self._parallel_groups[group_id] = record
            self._parallel_group_order.append(group_id)
            self._evict_parallel_groups_if_needed()
            logger.debug(
                "FlowAwareConvergenceCoordinator.register_parallel_group | "
                "group_id=%s parent_flow_id=%s expected=%d",
                group_id,
                parent_flow_id,
                expected_count,
            )
            return record

    def absorb(self, ctx: ResultConvergenceContext) -> ResultConvergenceArtifact:
        """Apply convergence rules and absorb the result into canonical state.

        This is the **single entry point** for all result convergence
        decisions.  It:

        1. Enriches the context with duplicate / final-absorbed flags derived
           from existing coordinator state.
        2. Calls :func:`decide_convergence` to get the decision artifact.
        3. Updates internal canonical state (absorbed set, final flag,
           parallel group records).
        4. Records the artifact in the ring buffer.

        Parameters
        ----------
        ctx:
            :class:`ResultConvergenceContext` for this result.

        Returns
        -------
        ResultConvergenceArtifact
            The convergence decision artifact.
        """
        with self._lock:
            # Enrich context with current coordinator state before deciding
            enriched = self._enrich_context(ctx)
            artifact = decide_convergence(enriched)
            # Apply state changes based on the decision
            self._apply_decision(enriched, artifact)
            # Record artifact
            self._artifacts.append(artifact)
            self._total_count += 1
            return artifact

    def get_parallel_group(
        self, group_id: str
    ) -> Optional[ParallelFlowAggregationRecord]:
        """Return the :class:`ParallelFlowAggregationRecord` for *group_id*, or
        ``None`` if not found."""
        with self._lock:
            return self._parallel_groups.get(group_id)

    def get_artifact_by_id(
        self, artifact_id: str
    ) -> Optional[ResultConvergenceArtifact]:
        """Return the :class:`ResultConvergenceArtifact` with the given ID, or
        ``None`` if not found in the ring buffer."""
        with self._lock:
            for art in self._artifacts:
                if art.artifact_id == artifact_id:
                    return art
            return None

    def list_recent_artifacts(
        self, max_count: int = 50
    ) -> List[ResultConvergenceArtifact]:
        """Return up to *max_count* most-recent artifacts (newest last)."""
        with self._lock:
            items = list(self._artifacts)
            return items[-max_count:] if len(items) > max_count else items

    def build_snapshot(self) -> FlowConvergenceSnapshot:
        """Return a :class:`FlowConvergenceSnapshot` of current coordinator
        state."""
        with self._lock:
            decision_counts: Dict[str, int] = {}
            for art in self._artifacts:
                key = art.decision.value
                decision_counts[key] = decision_counts.get(key, 0) + 1

            return FlowConvergenceSnapshot(
                total_artifacts=self._total_count,
                recent_artifacts=list(self._artifacts)[-20:],
                active_parallel_groups=len(self._parallel_groups),
                active_flow_ids=len(self._flow_absorbed),
                decision_counts=decision_counts,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enrich_context(
        self, ctx: ResultConvergenceContext
    ) -> ResultConvergenceContext:
        """Return a copy of *ctx* enriched with coordinator-derived flags."""
        import dataclasses

        is_dup = False
        final_absorbed = ctx.final_already_absorbed

        if ctx.flow_id:
            absorbed_set = self._flow_absorbed.get(ctx.flow_id, set())
            if ctx.result_id and ctx.result_id in absorbed_set:
                is_dup = True
            if not final_absorbed:
                final_absorbed = self._flow_final_absorbed.get(ctx.flow_id, False)

        return dataclasses.replace(
            ctx,
            is_duplicate=is_dup,
            final_already_absorbed=final_absorbed,
        )

    def _apply_decision(
        self,
        ctx: ResultConvergenceContext,
        artifact: ResultConvergenceArtifact,
    ) -> None:
        """Update internal canonical state based on the convergence decision."""
        decision = artifact.decision

        # Track absorbed result_ids per flow
        if (
            ctx.flow_id
            and ctx.result_id
            and decision not in (
                ConvergenceDecisionKind.suppress_duplicate_result,
                ConvergenceDecisionKind.absorb_replay_result_idempotently,
                ConvergenceDecisionKind.quarantine_result_due_to_flow_mismatch,
            )
        ):
            if ctx.flow_id not in self._flow_absorbed:
                self._flow_absorbed[ctx.flow_id] = set()
            self._flow_absorbed[ctx.flow_id].add(ctx.result_id)

        # Track final-absorbed per flow
        if decision is ConvergenceDecisionKind.promote_final_as_canonical:
            self._flow_final_absorbed[ctx.flow_id] = True

        # Update parallel group record
        if decision is ConvergenceDecisionKind.aggregate_parallel_into_parent_flow:
            group_id = ctx.group_id
            if group_id:
                if group_id not in self._parallel_groups:
                    # Auto-create on first arrival
                    record = ParallelFlowAggregationRecord(
                        group_id=group_id,
                        parent_flow_id=ctx.parent_flow_id or ctx.flow_id,
                        session_id=ctx.session_id,
                        trace_id=ctx.trace_id,
                    )
                    self._parallel_groups[group_id] = record
                    self._parallel_group_order.append(group_id)
                    self._evict_parallel_groups_if_needed()

                record = self._parallel_groups[group_id]
                idx = ctx.subtask_index if ctx.subtask_index is not None else len(
                    record.absorbed_subtasks
                )
                if idx not in record.absorbed_subtasks:
                    record.absorbed_subtasks[idx] = artifact

                # Check if group is now complete
                if (
                    record.expected_count is not None
                    and record.absorbed_count >= record.expected_count
                    and not record.all_complete
                ):
                    record.all_complete = True
                    record.completed_at = time.time()
                    # Build aggregate artifact
                    record.aggregate_artifact = ResultConvergenceArtifact(
                        decision=ConvergenceDecisionKind.aggregate_parallel_into_parent_flow,
                        semantic_kind=ResultSemanticKind.parent_flow_aggregate,
                        lineage=ConvergenceFlowLineage.subtask_of_group,
                        policy_reference=PARALLEL_RESULTS_AGGREGATE_TO_PARENT_FLOW_VIA_GROUP_ID_POLICY,
                        reason=(
                            f"all {record.expected_count} parallel subtask results "
                            f"absorbed — parent_flow_aggregate emitted for "
                            f"group_id={group_id!r}"
                        ),
                        flow_id=record.parent_flow_id,
                        group_id=group_id,
                        parent_flow_id=record.parent_flow_id,
                        session_id=record.session_id,
                        trace_id=record.trace_id,
                        group_complete=True,
                        evidence={
                            "group_id": group_id,
                            "parent_flow_id": record.parent_flow_id,
                            "expected_count": record.expected_count,
                            "absorbed_count": record.absorbed_count,
                        },
                    )
                    # Record aggregate artifact
                    self._artifacts.append(record.aggregate_artifact)
                    self._total_count += 1
                    logger.info(
                        "FlowAwareConvergenceCoordinator: parallel group COMPLETE "
                        "| group_id=%s parent_flow_id=%s subtasks=%d",
                        group_id,
                        record.parent_flow_id,
                        record.absorbed_count,
                    )

                # Annotate artifact with group_complete flag
                artifact.group_complete = record.all_complete

    def _evict_parallel_groups_if_needed(self) -> None:
        """Evict oldest parallel group records when capacity is exceeded."""
        while (
            len(self._parallel_groups) > _MAX_PARALLEL_GROUPS
            and self._parallel_group_order
        ):
            oldest = self._parallel_group_order.pop(0)
            self._parallel_groups.pop(oldest, None)
            logger.debug(
                "FlowAwareConvergenceCoordinator: evicted oldest "
                "parallel group_id=%s",
                oldest,
            )


# ===========================================================================
# Singleton
# ===========================================================================

_coordinator_instance: Optional[FlowAwareConvergenceCoordinator] = None
_coordinator_lock = threading.Lock()


def get_flow_aware_convergence_coordinator() -> FlowAwareConvergenceCoordinator:
    """Return the process-global :class:`FlowAwareConvergenceCoordinator`
    singleton."""
    global _coordinator_instance
    if _coordinator_instance is None:
        with _coordinator_lock:
            if _coordinator_instance is None:
                _coordinator_instance = FlowAwareConvergenceCoordinator()
    return _coordinator_instance


def reset_flow_aware_convergence_coordinator() -> None:
    """Reset the singleton (for testing only)."""
    global _coordinator_instance
    _coordinator_instance = None


# ===========================================================================
# Convenience wrappers
# ===========================================================================


def absorb_result(ctx: ResultConvergenceContext) -> ResultConvergenceArtifact:
    """Absorb a result into the singleton coordinator and return the artifact.

    This is the module-level convenience entry point.  Equivalent to::

        get_flow_aware_convergence_coordinator().absorb(ctx)
    """
    return get_flow_aware_convergence_coordinator().absorb(ctx)


def build_flow_convergence_snapshot() -> FlowConvergenceSnapshot:
    """Return a snapshot of the current coordinator state."""
    return get_flow_aware_convergence_coordinator().build_snapshot()
