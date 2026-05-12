#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/operator_surface.py
=========================
PR-E: Operator Surface — Unified Canonical Runtime Operator Surface.

Establishes the single **Operator Surface** authority that exposes every
canonical runtime dimension to operator consoles, status boards, and
inspection views.  All data consumed here is read from canonical runtime
projections — the surface itself performs **no independent truth inference**.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │  OPERATOR SURFACE  (this module, Layer 10)                      │
    │                                                                  │
    │  Consumes (read-only) from:                                     │
    │    • CanonicalTaskRuntime   — task lifecycle / task graph       │
    │    • TaskGraphRuntime       — task graph / lineage / fanout     │
    │    • NetworkTopologyRuntime — path state / topology             │
    │    • CapabilityAssimilationLayer — capability / presence        │
    │    • PolicyConvergenceOutput — route / admissibility decision   │
    │    • ReplayFoundation       — replay / audit records            │
    │                                                                  │
    │  Exposes (read-only projections):                               │
    │    • inspect_task(task_id)          → TaskInspection            │
    │    • inspect_route(task_id)         → RouteInspection           │
    │    • inspect_executor(node_id)      → ExecutorInspection        │
    │    • inspect_failure_domain(task_id)→ FailureDomainInspection   │
    │    • inspect_lineage(task_id)       → LineageInspection         │
    │    • inspect_recovery(task_id)      → RecoveryInspection        │
    │    • inspect_partial_result(task_id)→ PartialResultInspection   │
    │    • inspect_audit_evidence(task_id)→ AuditEvidenceInspection   │
    │    • end_to_end_review(task_id)     → EndToEndReviewSummary     │
    │    • operator_snapshot()            → OperatorSnapshot          │
    │                                                                  │
    │  Role boundaries:                                               │
    │    • operator_console / inspection view — deep single-task view │
    │    • status_board — compact runtime projection overview         │
    │    • topology / task graph viewers — graph structure views      │
    └──────────────────────────────────────────────────────────────────┘

Projection discipline
---------------------
The Operator Surface enforces the **projection-only principle**:

1.  All surfaces (operator console, status board, topology viewer) MUST
    consume canonical runtime projections from this module.
2.  Surfaces MUST NOT infer system truth from legacy sources or raw subsystem
    internals.
3.  This module is the authoritative convergence point for all operator-visible
    runtime state.

Governed by ``OPERATOR_SURFACE_PROJECTION_POLICY``.

Public API
----------
Authority sentinels::

    OPERATOR_SURFACE_AUTHORITY
    OPERATOR_SURFACE_LAYER_POSITION
    OPERATOR_SURFACE_CONTRACT_VERSION
    OPERATOR_SURFACE_PROJECTION_POLICY

Role boundary sentinels::

    OPERATOR_CONSOLE_ROLE
    STATUS_BOARD_ROLE
    TOPOLOGY_VIEWER_ROLE

Dataclasses::

    TaskInspection
    RouteInspection
    ExecutorInspection
    FailureDomainInspection
    LineageInspection
    RecoveryInspection
    PartialResultInspection
    AuditEvidenceInspection
    EndToEndReviewSummary
    DevicePresenceSummary
    OperatorSnapshot

Class::

    OperatorSurface

Helpers::

    get_operator_surface() -> OperatorSurface
    reset_operator_surface() -> None   # testing only
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.OperatorSurface")

# ---------------------------------------------------------------------------
# Flow-level surface re-exports
# ---------------------------------------------------------------------------
# These are re-exported here so that code that only imports from
# core.operator_surface can access the flow-level types without a separate
# import of core.flow_level_operator_surface.
try:
    from core.flow_level_operator_surface import (  # noqa: F401
        AndroidExecutionPhase,
        AndroidCanonicalExecutionEvent,
        FlowOperatorProjection,
    )
except Exception:  # pragma: no cover
    pass  # graceful degradation if module is unavailable

# PR-3: Operator action contract re-exports — lazy so callers that only need
# the read surface do not transitively import the async action path.
try:
    from core.operator_action_contract import (  # noqa: F401
        OperatorActionKind,
        OperatorActionRequest,
        OperatorActionResult,
        OPERATOR_ACTION_CONTRACT_AUTHORITY,
        OPERATOR_CONTROL_PLANE_IS_CANONICAL_AUTHORITY,
        OPERATOR_ACTION_ENTRY_MODE,
        build_operator_action_result_from_runtime_result,
    )
except Exception:  # pragma: no cover
    pass  # graceful degradation if module is unavailable

__all__ = [
    # Authority sentinels
    "OPERATOR_SURFACE_AUTHORITY",
    "OPERATOR_SURFACE_LAYER_POSITION",
    "OPERATOR_SURFACE_CONTRACT_VERSION",
    "OPERATOR_SURFACE_PROJECTION_POLICY",
    "OPERATOR_ACTION_LAYER_POLICY",
    # Role boundary sentinels
    "OPERATOR_CONSOLE_ROLE",
    "STATUS_BOARD_ROLE",
    "TOPOLOGY_VIEWER_ROLE",
    # Snapshot constants
    "ANDROID_ECOSYSTEM_SNAPSHOT_KEYS",
    # Dataclasses
    "TaskInspection",
    "RouteInspection",
    "ExecutorInspection",
    "FailureDomainInspection",
    "LineageInspection",
    "RecoveryInspection",
    "PartialResultInspection",
    "AuditEvidenceInspection",
    "EndToEndReviewSummary",
    "DevicePresenceSummary",
    "OperatorSnapshot",
    # Flow-level surface re-exports
    "AndroidExecutionPhase",
    "AndroidCanonicalExecutionEvent",
    "FlowOperatorProjection",
    # Class
    "OperatorSurface",
    # Helpers
    "get_operator_surface",
    "reset_operator_surface",
    # Action contract (PR-3) — re-exported for convenience
    "OperatorActionRequest",
    "OperatorActionResult",
    "OperatorActionKind",
    "OPERATOR_ACTION_CONTRACT_AUTHORITY",
    "OPERATOR_CONTROL_PLANE_IS_CANONICAL_AUTHORITY",
    "OPERATOR_ACTION_ENTRY_MODE",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

OPERATOR_SURFACE_AUTHORITY: str = "OPERATOR_SURFACE_V1"
"""Sentinel: this module is the canonical operator surface authority.
Import to assert that a UI/console component reads only from canonical projections."""

OPERATOR_SURFACE_LAYER_POSITION: int = 10
"""Layer position in the Galaxy architecture stack.
OperatorSurface sits above CanonicalTask (layer 9) and reads from all canonical
runtime layers (layers 6–9)."""

OPERATOR_SURFACE_CONTRACT_VERSION: str = "1.0"
"""Version of the OperatorSurface contract."""

OPERATOR_SURFACE_PROJECTION_POLICY: str = (
    "REQUIRED: All operator/UI surfaces must consume canonical runtime "
    "projections from OperatorSurface; no surface may infer system truth from "
    "raw subsystem internals or legacy sources."
)
"""Policy: surfaces read projections, never assemble truth independently."""

# ---------------------------------------------------------------------------
# Role boundary sentinels
# ---------------------------------------------------------------------------

OPERATOR_CONSOLE_ROLE: str = "OPERATOR_CONSOLE"
"""Role: deep single-task inspection view — uses inspect_* methods."""

STATUS_BOARD_ROLE: str = "STATUS_BOARD"
"""Role: compact runtime overview — uses operator_snapshot()."""

TOPOLOGY_VIEWER_ROLE: str = "TOPOLOGY_VIEWER"
"""Role: graph structure display — consumes graph/topology projections from snapshot."""

# ---------------------------------------------------------------------------
# Snapshot constants
# ---------------------------------------------------------------------------

ANDROID_ECOSYSTEM_SNAPSHOT_KEYS: frozenset = frozenset({
    "total_devices_with_snapshot",
    "local_ai_ready_count",
    "model_ready_count",
    "accessibility_ready_count",
    "overlay_ready_count",
    "local_loop_ready_count",
    "pending_first_download_count",
})
"""Whitelist of count-level keys retained in OperatorSnapshot.android_ecosystem.

These keys correspond to the aggregate count fields returned by
:func:`~core.android_device_state_store.get_device_ecosystem_summary`.
The per-device ``devices`` list is intentionally excluded — full per-device
detail is the responsibility of GET /api/v1/operator/devices/ecosystem.
"""

OPERATOR_ACTION_LAYER_POLICY: str = (
    "OPERATOR_ACTION_LAYER_POLICY_V1: Operator actions are policy-aware and "
    "state-gated. Availability is derived from unified governance/runtime "
    "state. Approval-gated actions require approval_token and all actions must "
    "be traceable through canonical transition/audit recording."
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TaskInspection:
    """Canonical read-only projection of a single task for the operator console."""

    task_id: str = ""
    trace_id: str = ""
    session_id: str = ""
    parent_task_id: str = ""
    root_task_id: str = ""

    # Intent
    goal: str = ""
    origin: str = ""
    requested_action: str = ""

    # Lifecycle
    lifecycle: str = ""
    created_at: Optional[float] = None
    admitted_at: Optional[float] = None
    routed_at: Optional[float] = None
    dispatched_at: Optional[float] = None
    completed_at: Optional[float] = None

    # Routing / targets
    selected_targets: List[str] = field(default_factory=list)
    transport_strategy: str = ""
    effective_path: str = ""

    # Execution
    tool_name: str = ""

    # Result
    success: Optional[bool] = None
    error_code: str = ""
    failure_domain: str = ""
    degradation_reason: str = ""

    # Graph relations
    retry_of: str = ""
    fallback_of: str = ""
    children: List[str] = field(default_factory=list)

    # Source
    _source: str = "canonical_task_runtime"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "parent_task_id": self.parent_task_id,
            "root_task_id": self.root_task_id,
            "goal": self.goal,
            "origin": self.origin,
            "requested_action": self.requested_action,
            "lifecycle": self.lifecycle,
            "created_at": self.created_at,
            "admitted_at": self.admitted_at,
            "routed_at": self.routed_at,
            "dispatched_at": self.dispatched_at,
            "completed_at": self.completed_at,
            "selected_targets": self.selected_targets,
            "transport_strategy": self.transport_strategy,
            "effective_path": self.effective_path,
            "tool_name": self.tool_name,
            "success": self.success,
            "error_code": self.error_code,
            "failure_domain": self.failure_domain,
            "degradation_reason": self.degradation_reason,
            "retry_of": self.retry_of,
            "fallback_of": self.fallback_of,
            "children": self.children,
            "_source": self._source,
        }


@dataclass
class RouteInspection:
    """Canonical read-only projection of routing decisions for a task."""

    task_id: str = ""
    trace_id: str = ""

    # Route decision
    selected_targets: List[str] = field(default_factory=list)
    transport_strategy: str = ""
    route_preference: str = ""
    effective_path: str = ""
    fallback_available: bool = False

    # Policy inputs that drove the decision
    capability_fit: bool = False
    policy_score: float = 0.0
    transport_present: bool = False
    transport_usable: bool = False
    device_routable: bool = False
    admissibility_verdict: str = ""

    # Explanation
    route_explanation: str = ""
    degradation_reason: str = ""

    _source: str = "admissibility_policy_convergence"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "selected_targets": self.selected_targets,
            "transport_strategy": self.transport_strategy,
            "route_preference": self.route_preference,
            "effective_path": self.effective_path,
            "fallback_available": self.fallback_available,
            "capability_fit": self.capability_fit,
            "policy_score": self.policy_score,
            "transport_present": self.transport_present,
            "transport_usable": self.transport_usable,
            "device_routable": self.device_routable,
            "admissibility_verdict": self.admissibility_verdict,
            "route_explanation": self.route_explanation,
            "degradation_reason": self.degradation_reason,
            "_source": self._source,
        }


@dataclass
class ExecutorInspection:
    """Canonical read-only projection of an executor/provider for the operator."""

    node_id: str = ""
    node_kind: str = ""

    # Capability summary
    capability_tags: List[str] = field(default_factory=list)
    execution_modes: List[str] = field(default_factory=list)
    max_concurrency: int = 1

    # Presence
    presence_state: str = ""
    last_heartbeat: Optional[float] = None
    is_online: bool = False

    # Fabric
    fabric_address: str = ""
    fabric_reachable: bool = False

    _source: str = "capability_assimilation"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_kind": self.node_kind,
            "capability_tags": self.capability_tags,
            "execution_modes": self.execution_modes,
            "max_concurrency": self.max_concurrency,
            "presence_state": self.presence_state,
            "last_heartbeat": self.last_heartbeat,
            "is_online": self.is_online,
            "fabric_address": self.fabric_address,
            "fabric_reachable": self.fabric_reachable,
            "_source": self._source,
        }


@dataclass
class FailureDomainInspection:
    """Canonical read-only projection of failure domain information for a task."""

    task_id: str = ""
    trace_id: str = ""
    failure_domain: str = ""
    error_code: str = ""
    error_message: str = ""

    # Context at failure
    lifecycle_at_failure: str = ""
    target_at_failure: str = ""
    transport_at_failure: str = ""

    # Fallback / retry history
    retry_count: int = 0
    fallback_triggered: bool = False
    fallback_target: str = ""

    # Policy context
    degradation_reason: str = ""
    policy_decision: str = ""

    _source: str = "task_graph_runtime"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "failure_domain": self.failure_domain,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "lifecycle_at_failure": self.lifecycle_at_failure,
            "target_at_failure": self.target_at_failure,
            "transport_at_failure": self.transport_at_failure,
            "retry_count": self.retry_count,
            "fallback_triggered": self.fallback_triggered,
            "fallback_target": self.fallback_target,
            "degradation_reason": self.degradation_reason,
            "policy_decision": self.policy_decision,
            "_source": self._source,
        }


@dataclass
class LineageInspection:
    """Canonical read-only projection of task lineage / timeline for a task."""

    task_id: str = ""
    trace_id: str = ""
    root_task_id: str = ""

    # Ancestry
    parent_task_id: str = ""
    ancestor_chain: List[str] = field(default_factory=list)

    # Descendant tree
    children: List[str] = field(default_factory=list)

    # Retry / fallback chain
    retry_chain: List[str] = field(default_factory=list)
    fallback_chain: List[str] = field(default_factory=list)

    # Timeline events (ordered)
    timeline: List[Dict[str, Any]] = field(default_factory=list)

    _source: str = "task_graph_runtime"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "root_task_id": self.root_task_id,
            "parent_task_id": self.parent_task_id,
            "ancestor_chain": self.ancestor_chain,
            "children": self.children,
            "retry_chain": self.retry_chain,
            "fallback_chain": self.fallback_chain,
            "timeline": self.timeline,
            "_source": self._source,
        }


@dataclass
class RecoveryInspection:
    """Canonical read-only projection of recovery disposition for a task.

    Surfaces how a task was handled after an interruption or restart, derived
    from the canonical lifecycle registry and the durable task lifecycle
    snapshot.  This is the primary operator-facing surface for recovery
    disposition reviewability.

    Attributes
    ----------
    task_id:
        The canonical task identifier.
    trace_id:
        Distributed trace identifier.
    is_recovered:
        ``True`` when this task was present in a lifecycle snapshot and had
        a recovery action taken on it.
    recovery_disposition:
        One of ``"resumable"``, ``"replay_only"``, ``"reissuable"``,
        ``"terminal_on_interrupt"``, or ``""`` when not recovered.
    current_owner:
        Current lifecycle ownership stage from the live registry, e.g.
        ``"device_dispatch"``, ``"routing"``, ``"gateway_ingress"``.
        Empty when the task is not currently pending.
    snapshot_id:
        Identifier of the lifecycle snapshot that sourced this recovery, if any.
    interrupted_at:
        Wall-clock timestamp of the interruption, if available.
    recovery_action_taken:
        Whether a concrete runtime registry action was taken for this task
        (i.e. it was registered in the lifecycle registry under its disposition
        ownership stage).  ``False`` for terminal records that are excluded
        from the pending registry.
    recovery_note:
        Human-readable summary of what happened during recovery.
    """

    task_id: str = ""
    trace_id: str = ""
    is_recovered: bool = False
    recovery_disposition: str = ""
    current_owner: str = ""
    snapshot_id: str = ""
    interrupted_at: Optional[float] = None
    recovery_action_taken: bool = False
    recovery_note: str = ""

    _source: str = "task_lifecycle_registry"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "is_recovered": self.is_recovered,
            "recovery_disposition": self.recovery_disposition,
            "current_owner": self.current_owner,
            "snapshot_id": self.snapshot_id,
            "interrupted_at": self.interrupted_at,
            "recovery_action_taken": self.recovery_action_taken,
            "recovery_note": self.recovery_note,
            "_source": self._source,
        }


@dataclass
class PartialResultInspection:
    """Canonical read-only projection of partial-result outcome for a task.

    Surfaces the hybrid orchestration partial-result disposition for a task,
    derived from :class:`~core.hybrid_orchestration_continuity.HybridOrchestrationRecord`.

    Attributes
    ----------
    task_id:
        The canonical task identifier.
    execution_id:
        The hybrid execution identifier (from HybridOrchestrationRecord).
    lifecycle_state:
        Current hybrid lifecycle state (e.g. ``"completed"``, ``"interrupted"``).
    partial_result_disposition:
        How the partial result was handled: ``"preserved"``, ``"invalidated"``,
        ``"merged"``, ``"resumed"``, or ``""`` when no partial result exists.
    partial_result_origin:
        Origin of the partial result: ``"local"``, ``"remote"``, or ``""``.
    resume_count:
        Number of times this hybrid execution has been resumed.
    has_partial_result:
        ``True`` when a partial result snapshot is present.
    interruption_reason:
        Human-readable reason for interruption, if available.
    """

    task_id: str = ""
    execution_id: str = ""
    lifecycle_state: str = ""
    partial_result_disposition: str = ""
    partial_result_origin: str = ""
    resume_count: int = 0
    has_partial_result: bool = False
    interruption_reason: str = ""

    _source: str = "hybrid_orchestration_continuity_registry"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "execution_id": self.execution_id,
            "lifecycle_state": self.lifecycle_state,
            "partial_result_disposition": self.partial_result_disposition,
            "partial_result_origin": self.partial_result_origin,
            "resume_count": self.resume_count,
            "has_partial_result": self.has_partial_result,
            "interruption_reason": self.interruption_reason,
            "_source": self._source,
        }


@dataclass
class AuditEvidenceInspection:
    """Canonical read-only projection of durable audit evidence for a task.

    Derived from the :class:`~core.replay_audit_persistence.DurableAuditStore`.
    Surfaces whether durable audit evidence exists for a task so operators
    can assess postmortem evidence completeness without raw JSONL spelunking.

    Attributes
    ----------
    task_id:
        The canonical task identifier.
    has_evidence:
        ``True`` when at least one durable audit record references this task.
    evidence_count:
        Total number of durable audit records referencing this task.
    by_kind:
        Dict mapping :class:`~core.replay_audit_persistence.AuditRecordKind`
        string values to counts of records of that kind.
    earliest_record_at:
        Timestamp of the earliest matching audit record, or ``None``.
    latest_record_at:
        Timestamp of the most recent matching audit record, or ``None``.
    audit_kinds_present:
        Sorted list of audit record kind strings present for this task.
    """

    task_id: str = ""
    has_evidence: bool = False
    evidence_count: int = 0
    by_kind: Dict[str, int] = field(default_factory=dict)
    earliest_record_at: Optional[float] = None
    latest_record_at: Optional[float] = None
    audit_kinds_present: List[str] = field(default_factory=list)

    _source: str = "durable_audit_store"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "has_evidence": self.has_evidence,
            "evidence_count": self.evidence_count,
            "by_kind": dict(self.by_kind),
            "earliest_record_at": self.earliest_record_at,
            "latest_record_at": self.latest_record_at,
            "audit_kinds_present": list(self.audit_kinds_present),
            "_source": self._source,
        }


@dataclass
class EndToEndReviewSummary:
    """Unified end-to-end operator review summary for a single task.

    Combines all inspection dimensions into a single postmortem-ready view
    so operators can determine what happened across routing, recovery,
    partial-result handling, and audit evidence without manually assembling
    data from multiple surfaces.

    Attributes
    ----------
    task_id:
        The canonical task identifier.
    trace_id:
        Distributed trace identifier.
    generated_at:
        Wall-clock timestamp when this summary was generated.
    task:
        :class:`TaskInspection` for core lifecycle/intent/result fields.
        ``None`` if the task is not known to the canonical runtime.
    route:
        :class:`RouteInspection` for routing decision details.
        ``None`` if no routing data is available.
    recovery:
        :class:`RecoveryInspection` for recovery disposition.
        ``None`` if the task has no recovery record.
    partial_result:
        :class:`PartialResultInspection` for partial-result outcome.
        ``None`` if no hybrid execution record is found.
    audit_evidence:
        :class:`AuditEvidenceInspection` for durable evidence coverage.
        Always present (zero counts when no evidence exists).
    lineage:
        :class:`LineageInspection` for task lineage / timeline.
        ``None`` if lineage is unavailable.
    reviewable:
        ``True`` when sufficient data exists to perform a meaningful
        postmortem review (at least a task record or audit evidence).
    review_notes:
        List of human-readable notes about evidence gaps or notable findings.
    """

    task_id: str = ""
    trace_id: str = ""
    generated_at: float = field(default_factory=time.time)

    task: Optional["TaskInspection"] = None
    route: Optional["RouteInspection"] = None
    recovery: Optional["RecoveryInspection"] = None
    partial_result: Optional["PartialResultInspection"] = None
    audit_evidence: Optional["AuditEvidenceInspection"] = None
    lineage: Optional["LineageInspection"] = None

    reviewable: bool = False
    review_notes: List[str] = field(default_factory=list)

    authority: str = OPERATOR_SURFACE_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "generated_at": self.generated_at,
            "task": self.task.to_dict() if self.task is not None else None,
            "route": self.route.to_dict() if self.route is not None else None,
            "recovery": self.recovery.to_dict() if self.recovery is not None else None,
            "partial_result": self.partial_result.to_dict() if self.partial_result is not None else None,
            "audit_evidence": self.audit_evidence.to_dict() if self.audit_evidence is not None else None,
            "lineage": self.lineage.to_dict() if self.lineage is not None else None,
            "reviewable": self.reviewable,
            "review_notes": list(self.review_notes),
            "authority": self.authority,
        }


@dataclass
class DevicePresenceSummary:
    """Compact projection of device presence and readiness."""

    device_id: str = ""
    presence_state: str = ""
    is_ready: bool = False
    is_participating: bool = False
    last_seen: Optional[float] = None
    transport_role: str = ""
    capability_tags: List[str] = field(default_factory=list)

    _source: str = "network_topology_runtime"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "presence_state": self.presence_state,
            "is_ready": self.is_ready,
            "is_participating": self.is_participating,
            "last_seen": self.last_seen,
            "transport_role": self.transport_role,
            "capability_tags": self.capability_tags,
            "_source": self._source,
        }


@dataclass
class OperatorSnapshot:
    """Compact runtime snapshot for status board / operator overview.

    Contains all canonical runtime dimensions in a single serialisable view.
    Generated by :meth:`OperatorSurface.operator_snapshot`.

    Role boundary
    -------------
    This snapshot is the **global system overview** surface.  It exposes
    count-level summaries only — not per-item detail lists.  Callers that need
    full per-device state should read from the ecosystem route
    (``GET /api/v1/operator/devices/ecosystem``); callers that need per-flow
    detail should read from the flows route
    (``GET /api/v1/operator/flows``).
    """

    snapshot_id: str = field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:12]}")
    generated_at: float = field(default_factory=time.time)

    # Task runtime summary
    active_task_count: int = 0
    recent_tasks: List[Dict[str, Any]] = field(default_factory=list)

    # Delegated flow summary (PR-4)
    # Count of active delegated flows derived from DelegatedFlowEntityRuntime.
    # For per-flow detail see GET /api/v1/operator/flows.
    active_flow_count: int = 0

    # Device presence summary
    online_device_count: int = 0
    device_summaries: List[Dict[str, Any]] = field(default_factory=list)

    # Topology summary
    topology_node_count: int = 0
    topology_edge_count: int = 0

    # Capability summary
    capability_provider_count: int = 0
    online_provider_count: int = 0

    # Source-runtime posture summary
    source_runtime_posture_counts: Dict[str, int] = field(default_factory=dict)
    recent_source_runtime_postures: List[Dict[str, Any]] = field(default_factory=list)

    # Android ecosystem summary (PR-RT, PR-4)
    # Compact count-level summary from core.android_device_state_store.
    # Only the keys in ANDROID_ECOSYSTEM_SNAPSHOT_KEYS are included — the
    # ``devices`` per-item list is intentionally excluded; it is owned by
    # GET /api/v1/operator/devices/ecosystem.
    # Keys present: total_devices_with_snapshot, local_ai_ready_count,
    # model_ready_count, accessibility_ready_count, overlay_ready_count,
    # local_loop_ready_count, pending_first_download_count.
    android_ecosystem: Dict[str, Any] = field(default_factory=dict)

    # Authority declaration
    authority: str = OPERATOR_SURFACE_AUTHORITY
    contract_version: str = OPERATOR_SURFACE_CONTRACT_VERSION
    projection_policy: str = OPERATOR_SURFACE_PROJECTION_POLICY

    # ── PR-8 V2: Desktop shell / presence manifestation summary ───────────
    # Reflects the current shell expansion mode and subject presence tri-state
    # without creating a parallel truth store.  Values are read from the
    # canonical singletons (SystemStateMachine and DesktopPresenceRuntime)
    # at snapshot time.
    #
    # desktop_shell_state: current UI shell mode (dormant/island/sidesheet/
    #     fullagent).  Empty string when the SystemStateMachine singleton
    #     is unavailable (e.g. headless test environments).
    # presence_tristate: dominant subject tri-state across all in-flight
    #     runtime sessions (silent/liminal/manifest).  Reports "silent"
    #     when no session is active.
    # manifestation_summary: compact aggregated view combining both layers
    #     so operator surfaces can inspect the current AI body manifestation
    #     state in a single field.
    desktop_shell_state: str = ""
    presence_tristate: str = ""
    manifestation_summary: Dict[str, Any] = field(default_factory=dict)
    governance_state: Dict[str, Any] = field(default_factory=dict)
    mesh_runtime_state: Dict[str, Any] = field(default_factory=dict)
    operator_action_layer: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "generated_at": self.generated_at,
            "active_task_count": self.active_task_count,
            "recent_tasks": self.recent_tasks,
            "active_flow_count": self.active_flow_count,
            "online_device_count": self.online_device_count,
            "device_summaries": self.device_summaries,
            "topology_node_count": self.topology_node_count,
            "topology_edge_count": self.topology_edge_count,
            "capability_provider_count": self.capability_provider_count,
            "online_provider_count": self.online_provider_count,
            "source_runtime_posture_counts": dict(self.source_runtime_posture_counts),
            "recent_source_runtime_postures": list(self.recent_source_runtime_postures),
            "android_ecosystem": dict(self.android_ecosystem),
            "authority": self.authority,
            "contract_version": self.contract_version,
            "projection_policy": self.projection_policy,
            # PR-8 V2: shell/presence manifestation fields
            "desktop_shell_state": self.desktop_shell_state,
            "presence_tristate": self.presence_tristate,
            "manifestation_summary": dict(self.manifestation_summary),
            "governance_state": dict(self.governance_state),
            "mesh_runtime_state": dict(self.mesh_runtime_state),
            "operator_action_layer": dict(self.operator_action_layer),
        }


# ---------------------------------------------------------------------------
# OperatorSurface — main class
# ---------------------------------------------------------------------------


class OperatorSurface:
    """Unified canonical operator surface for the Galaxy runtime.

    This is the **sole** authority for all operator-visible runtime state.
    It reads from canonical runtime projections and exposes read-only views.

    Surfaces (operator console, status board, topology viewer) must read
    from this class — they must NOT query legacy sources or raw subsystem
    internals directly.

    Design invariants
    -----------------
    1.  **Read-only projections only.**  No mutation of canonical state.
    2.  **Graceful degradation.**  If a canonical runtime is unavailable, the
        surface returns empty/default projections rather than raising.
    3.  **Source-annotated.**  Every projection dataclass carries a ``_source``
        field indicating which canonical runtime layer provided the data.
    4.  **Authority-declared.**  Every snapshot includes the authority sentinel
        so downstream consumers can verify provenance.
    """

    def __init__(self) -> None:
        self._surface_id: str = f"ops_{uuid.uuid4().hex[:8]}"

    # ── Task Inspection ──────────────────────────────────────────────────

    def inspect_task(self, task_id: str) -> Optional[TaskInspection]:
        """Return a read-only :class:`TaskInspection` for *task_id*.

        Returns ``None`` if the task is not known to the canonical runtime.
        """
        try:
            from core.canonical_task import get_canonical_task_runtime

            runtime = get_canonical_task_runtime()
            task = runtime.get_by_task_id(task_id)
            if task is None:
                return None
            # Gracefully resolve enum values
            origin_val = ""
            try:
                origin_val = task.intent.origin.value
            except Exception:
                origin_val = str(getattr(task.intent, "origin", ""))

            lifecycle_val = ""
            try:
                lifecycle_val = task.lifecycle.value
            except Exception:
                lifecycle_val = str(task.lifecycle)

            failure_domain_val = ""
            try:
                fd = task.result.failure_domain
                failure_domain_val = fd.value if hasattr(fd, "value") else str(fd)
            except Exception:
                pass

            return TaskInspection(
                task_id=task.identity.task_id,
                trace_id=task.identity.trace_id,
                session_id=task.identity.session_id,
                parent_task_id=task.identity.parent_task_id,
                root_task_id=task.identity.root_task_id,
                goal=task.intent.goal,
                origin=origin_val,
                requested_action=task.intent.requested_action,
                lifecycle=lifecycle_val,
                created_at=task.created_at,
                admitted_at=task.admitted_at,
                routed_at=task.routed_at,
                dispatched_at=task.dispatched_at,
                completed_at=task.completed_at,
                selected_targets=list(task.routing.selected_targets),
                transport_strategy=getattr(task.routing, "transport_preference", ""),
                effective_path=task.routing.effective_path,
                tool_name=task.execution.tool,
                success=task.result.success,
                error_code=task.result.error_code,
                failure_domain=failure_domain_val,
                retry_of=task.graph.retry_of,
                fallback_of=task.graph.fallback_of,
                children=list(task.graph.children),
            )
        except Exception as exc:
            logger.warning("inspect_task(%s) failed: %s", task_id, exc)
            return None

    # ── Route Inspection ─────────────────────────────────────────────────

    def inspect_route(self, task_id: str) -> Optional[RouteInspection]:
        """Return a read-only :class:`RouteInspection` for *task_id*.

        Combines routing fields from CanonicalTask with policy convergence
        output where available.

        Returns ``None`` if the task is not known.
        """
        try:
            from core.canonical_task import get_canonical_task_runtime

            runtime = get_canonical_task_runtime()
            task = runtime.get_by_task_id(task_id)
            if task is None:
                return None
            return RouteInspection(
                task_id=task.identity.task_id,
                trace_id=task.identity.trace_id,
                selected_targets=list(task.routing.selected_targets),
                transport_strategy=getattr(task.routing, "transport_preference", ""),
                route_preference=task.routing.route_preference,
                effective_path=task.routing.effective_path,
            )
        except Exception as exc:
            logger.warning("inspect_route(%s) failed: %s", task_id, exc)
            return None

    # ── Executor Inspection ──────────────────────────────────────────────

    def inspect_executor(self, node_id: str) -> Optional[ExecutorInspection]:
        """Return a read-only :class:`ExecutorInspection` for *node_id*.

        Returns ``None`` if the node is not known to the capability assimilation
        layer.
        """
        try:
            from core.capability_assimilation import (
                get_capability_assimilation_layer,
            )

            layer = get_capability_assimilation_layer()
            record = layer.get_record(node_id)
            if record is None:
                return None
            presence = record.fabric_presence
            exec_profile = record.execution_profile
            cap = record.capability_descriptor
            kind_val = ""
            try:
                kind_val = exec_profile.participant_kind.value
            except Exception:
                kind_val = str(getattr(exec_profile, "participant_kind", ""))
            presence_val = ""
            try:
                presence_val = presence.presence_state.value
            except Exception:
                presence_val = str(getattr(presence, "presence_state", ""))
            return ExecutorInspection(
                node_id=record.node_id,
                node_kind=kind_val,
                capability_tags=list(getattr(cap, "tags", [])),
                execution_modes=list(getattr(exec_profile, "modes", [])),
                max_concurrency=getattr(exec_profile, "max_concurrency", 1),
                presence_state=presence_val,
                last_heartbeat=getattr(presence, "last_heartbeat", None),
                is_online=getattr(presence, "is_online", False),
                fabric_address=getattr(presence, "fabric_address", ""),
                fabric_reachable=getattr(presence, "fabric_reachable", False),
            )
        except Exception as exc:
            logger.warning("inspect_executor(%s) failed: %s", node_id, exc)
            return None

    # ── Failure Domain Inspection ────────────────────────────────────────

    def inspect_failure_domain(self, task_id: str) -> Optional[FailureDomainInspection]:
        """Return a read-only :class:`FailureDomainInspection` for *task_id*.

        Returns ``None`` if the task is not known or has not failed.
        """
        try:
            from core.canonical_task import get_canonical_task_runtime

            runtime = get_canonical_task_runtime()
            task = runtime.get_by_task_id(task_id)
            if task is None:
                return None

            failure_domain_val = ""
            try:
                fd = task.result.failure_domain
                failure_domain_val = fd.value if hasattr(fd, "value") else str(fd)
            except Exception:
                pass

            lifecycle_val = ""
            try:
                lifecycle_val = task.lifecycle.value
            except Exception:
                lifecycle_val = str(task.lifecycle)

            # Retry / fallback count from task graph runtime
            retry_count = 0
            fallback_triggered = False
            fallback_target = ""
            try:
                from core.task_graph_runtime import get_task_graph_runtime

                tgr = get_task_graph_runtime()
                retry_chain = tgr.get_retry_lineage(task_id)
                fallback_chain = tgr.get_fallback_lineage(task_id)
                retry_count = len(retry_chain)
                if fallback_chain:
                    fallback_triggered = True
                    last_fb = fallback_chain[-1]
                    fallback_target = last_fb.fallback_task_id
            except Exception:
                pass

            return FailureDomainInspection(
                task_id=task.identity.task_id,
                trace_id=task.identity.trace_id,
                failure_domain=failure_domain_val,
                error_code=task.result.error_code,
                error_message=getattr(task.result, "result_summary", ""),
                lifecycle_at_failure=lifecycle_val,
                target_at_failure=(task.routing.selected_targets[0] if task.routing.selected_targets else ""),
                transport_at_failure=getattr(task.routing, "transport_preference", ""),
                retry_count=retry_count,
                fallback_triggered=fallback_triggered,
                fallback_target=fallback_target,
            )
        except Exception as exc:
            logger.warning("inspect_failure_domain(%s) failed: %s", task_id, exc)
            return None

    # ── Lineage Inspection ───────────────────────────────────────────────

    def inspect_lineage(self, task_id: str) -> Optional[LineageInspection]:
        """Return a read-only :class:`LineageInspection` for *task_id*.

        PR-508: Falls back to TaskGraphRuntime-backed lineage when the task is
        not found in CanonicalTaskRuntime, so that lineage is graph-backed for
        all production tasks regardless of which path registered them.

        Returns ``None`` if the task is not known to any runtime.
        """
        retry_chain: List[str] = []
        fallback_chain: List[str] = []
        timeline: List[Dict[str, Any]] = []

        # ── Attempt to pull retry/fallback lineage from TaskGraphRuntime ──
        tgr_node = None
        try:
            from core.task_graph_runtime import get_task_graph_runtime

            tgr = get_task_graph_runtime()
            retry_chain = [r.retry_task_id for r in tgr.get_retry_lineage(task_id)]
            fallback_chain = [fb.fallback_task_id for fb in tgr.get_fallback_lineage(task_id)]
            tgr_node = tgr.get_node_by_task_id(task_id)
        except Exception:
            pass

        # ── Try canonical task for rich timeline/ancestry data ────────────
        try:
            from core.canonical_task import get_canonical_task_runtime

            runtime = get_canonical_task_runtime()
            task = runtime.get_by_task_id(task_id)
            if task is not None:
                # Build timeline from task timestamps
                for label, ts_val in [
                    ("created", task.created_at),
                    ("admitted", task.admitted_at),
                    ("planned", getattr(task, "planned_at", None)),
                    ("routed", task.routed_at),
                    ("dispatched", task.dispatched_at),
                    ("running", getattr(task, "running_at", None)),
                    ("completed", task.completed_at),
                ]:
                    if ts_val is not None:
                        timeline.append({"event": label, "ts": ts_val})
                timeline.sort(key=lambda e: e["ts"])

                return LineageInspection(
                    task_id=task.identity.task_id,
                    trace_id=task.identity.trace_id,
                    root_task_id=task.identity.root_task_id or task.identity.task_id,
                    parent_task_id=task.identity.parent_task_id,
                    children=list(task.graph.children),
                    retry_chain=retry_chain,
                    fallback_chain=fallback_chain,
                    timeline=timeline,
                )
        except Exception:
            pass

        # ── PR-508: Fall back to TaskGraphRuntime-only lineage ────────────
        if tgr_node is not None:
            # Build a minimal timeline from graph node timestamps
            for label, ts_val in [
                ("queued", tgr_node.queued_at),
                ("dispatch", tgr_node.dispatch_at),
                ("running", tgr_node.running_at),
                ("result", tgr_node.result_at),
                ("completed", tgr_node.completed_at),
            ]:
                if ts_val is not None:
                    timeline.append({"event": label, "ts": ts_val})
            timeline.sort(key=lambda e: e["ts"])

            return LineageInspection(
                task_id=task_id,
                trace_id=tgr_node.trace_id,
                root_task_id=task_id,
                parent_task_id="",
                children=[],
                retry_chain=retry_chain,
                fallback_chain=fallback_chain,
                timeline=timeline,
                _source="task_graph_runtime",
            )

        logger.warning("inspect_lineage(%s): task not found in any runtime", task_id)
        return None

    # ── Recovery Inspection ──────────────────────────────────────────────

    def inspect_recovery(self, task_id: str) -> Optional[RecoveryInspection]:
        """Return a read-only :class:`RecoveryInspection` for *task_id*.

        Derives recovery disposition from the live
        :class:`~core.task_envelope_lifecycle_registry.TaskEnvelopeLifecycleRegistry`
        (current ownership stage) and the durable lifecycle snapshot
        (whether this task appeared in a recovery pass).

        Returns ``None`` if the task has no current pending lifecycle record
        and no recovered snapshot record.
        """
        try:
            from core.task_envelope_lifecycle_registry import get_lifecycle_registry
        except Exception:
            return None

        trace_id = ""

        # ── Check live lifecycle registry ─────────────────────────────────
        current_owner = ""
        try:
            registry = get_lifecycle_registry()
            record = registry.get_record(task_id)
            if record is not None:
                current_owner = record.owner.value if hasattr(record.owner, "value") else str(record.owner)
                trace_id = getattr(record, "trace_id", "")
        except Exception as exc:
            logger.debug("inspect_recovery(%s): registry query failed: %s", task_id, exc)

        # ── Check durable snapshot for recovery history ───────────────────
        snapshot_id = ""
        interrupted_at = None
        recovery_disposition = ""
        recovery_action_taken = False
        is_recovered = False
        recovery_note = ""

        try:
            from core.task_lifecycle_persistence import (
                classify_disposition,
                get_task_lifecycle_store,
                InFlightTaskDisposition,
            )
            store = get_task_lifecycle_store()
            snapshot = store.load()
            if snapshot is not None:
                for raw_rec in snapshot.records:
                    if raw_rec.get("task_id") == task_id:
                        is_recovered = True
                        snapshot_id = snapshot.snapshot_id
                        interrupted_at = snapshot.created_at
                        owner_str = raw_rec.get("owner", "")
                        disp = classify_disposition(owner_str)
                        recovery_disposition = disp.value
                        recovery_action_taken = (
                            disp != InFlightTaskDisposition.TERMINAL_ON_INTERRUPT
                        )
                        recovery_note = (
                            f"Recovered from snapshot {snapshot_id}: "
                            f"disposition={recovery_disposition}, "
                            f"prior_owner={owner_str!r}"
                        )
                        if not current_owner:
                            current_owner = owner_str
                        break
        except Exception as exc:
            logger.debug(
                "inspect_recovery(%s): snapshot query failed: %s", task_id, exc
            )

        if not current_owner and not is_recovered:
            return None

        # Derive trace_id from canonical task if still empty
        if not trace_id:
            try:
                from core.canonical_task import get_canonical_task_runtime
                ct = get_canonical_task_runtime().get_by_task_id(task_id)
                if ct is not None:
                    trace_id = ct.identity.trace_id
            except Exception:
                pass

        if not recovery_note and current_owner:
            recovery_note = f"Task currently pending under owner={current_owner!r}."

        return RecoveryInspection(
            task_id=task_id,
            trace_id=trace_id,
            is_recovered=is_recovered,
            recovery_disposition=recovery_disposition,
            current_owner=current_owner,
            snapshot_id=snapshot_id,
            interrupted_at=interrupted_at,
            recovery_action_taken=recovery_action_taken,
            recovery_note=recovery_note,
        )

    # ── Partial-Result Inspection ────────────────────────────────────────

    def inspect_partial_result(self, task_id: str) -> Optional[PartialResultInspection]:
        """Return a read-only :class:`PartialResultInspection` for *task_id*.

        Derived from
        :class:`~core.hybrid_orchestration_continuity.HybridOrchestrationContinuityRegistry`.
        Returns ``None`` if no hybrid execution record is associated with
        *task_id*.
        """
        try:
            from core.hybrid_orchestration_continuity import (
                get_continuity_registry,
            )
        except Exception:
            return None

        try:
            registry = get_continuity_registry()
            records = registry.list_all()
            # Find the most-recently-updated record for this task_id
            matching = [r for r in records if r.task_id == task_id]
            if not matching:
                return None
            rec = max(matching, key=lambda r: r.updated_at)
            lifecycle_val = ""
            try:
                lifecycle_val = rec.lifecycle_state.value
            except Exception:
                lifecycle_val = str(rec.lifecycle_state)
            return PartialResultInspection(
                task_id=task_id,
                execution_id=rec.execution_id,
                lifecycle_state=lifecycle_val,
                partial_result_disposition=rec.partial_result_disposition or "",
                partial_result_origin=rec.partial_result_origin or "",
                resume_count=rec.resume_count,
                has_partial_result=rec.partial_result_snapshot is not None,
                interruption_reason=rec.interruption_reason or "",
            )
        except Exception as exc:
            logger.warning("inspect_partial_result(%s) failed: %s", task_id, exc)
            return None

    # ── Private helpers ──────────────────────────────────────────────────

    @staticmethod
    def _extract_task_id_from_payload(payload: Dict[str, Any]) -> Optional[str]:
        """Return the task_id from an audit payload dict, trying canonical field names.

        Checks ``task_id``, ``canonical_task_id``, and ``execution_task_id``
        in order, returning the first truthy value found.
        """
        return (
            payload.get("task_id")
            or payload.get("canonical_task_id")
            or payload.get("execution_task_id")
        )

    @staticmethod
    def _is_reviewable(
        task_insp: Optional["TaskInspection"],
        audit_insp: "AuditEvidenceInspection",
        recovery_insp: Optional["RecoveryInspection"],
    ) -> bool:
        """Return True when sufficient evidence exists for a postmortem review."""
        return (
            task_insp is not None
            or audit_insp.has_evidence
            or recovery_insp is not None
        )

    # ── Audit Evidence Inspection ────────────────────────────────────────

    def inspect_audit_evidence(self, task_id: str) -> AuditEvidenceInspection:
        """Return an :class:`AuditEvidenceInspection` for *task_id*.

        Scans the :class:`~core.replay_audit_persistence.DurableAuditStore`
        for all records whose payload contains *task_id* and aggregates
        evidence counts by kind.

        Always returns a valid :class:`AuditEvidenceInspection` (empty
        counts when no evidence exists or the store is unavailable).
        """
        insp = AuditEvidenceInspection(task_id=task_id)
        try:
            from core.replay_audit_persistence import get_replay_audit_store
        except Exception:
            return insp

        try:
            store = get_replay_audit_store()
            all_records = store.load_all()
            by_kind: Dict[str, int] = {}
            timestamps: List[float] = []
            for audit_rec in all_records:
                payload_task_id = self._extract_task_id_from_payload(audit_rec.payload)
                if payload_task_id == task_id:
                    kind = audit_rec.kind
                    by_kind[kind] = by_kind.get(kind, 0) + 1
                    timestamps.append(audit_rec.recorded_at)
            insp.evidence_count = sum(by_kind.values())
            insp.by_kind = by_kind
            insp.has_evidence = insp.evidence_count > 0
            insp.audit_kinds_present = sorted(by_kind.keys())
            if timestamps:
                insp.earliest_record_at = min(timestamps)
                insp.latest_record_at = max(timestamps)
        except Exception as exc:
            logger.debug("inspect_audit_evidence(%s) failed: %s", task_id, exc)
        return insp

    # ── End-to-End Review ────────────────────────────────────────────────

    def end_to_end_review(self, task_id: str) -> EndToEndReviewSummary:
        """Return a unified :class:`EndToEndReviewSummary` for *task_id*.

        Aggregates all inspection dimensions — task lifecycle, routing decision,
        recovery disposition, partial-result outcome, audit evidence, and lineage
        — into a single postmortem-ready view.

        Always returns a valid :class:`EndToEndReviewSummary` (fields are
        ``None`` or empty when individual dimensions are unavailable).
        """
        summary = EndToEndReviewSummary(task_id=task_id)
        notes: List[str] = []

        # Task
        task_insp = self.inspect_task(task_id)
        summary.task = task_insp
        if task_insp is not None:
            summary.trace_id = task_insp.trace_id or ""

        # Route
        route_insp = self.inspect_route(task_id)
        summary.route = route_insp

        # Recovery
        recovery_insp = self.inspect_recovery(task_id)
        summary.recovery = recovery_insp
        if recovery_insp is not None and recovery_insp.is_recovered:
            notes.append(
                f"Recovery: disposition={recovery_insp.recovery_disposition!r}, "
                f"action_taken={recovery_insp.recovery_action_taken}"
            )

        # Partial result
        partial_insp = self.inspect_partial_result(task_id)
        summary.partial_result = partial_insp
        if partial_insp is not None and partial_insp.has_partial_result:
            notes.append(
                f"Partial result: disposition={partial_insp.partial_result_disposition!r}, "
                f"origin={partial_insp.partial_result_origin!r}, "
                f"resume_count={partial_insp.resume_count}"
            )

        # Audit evidence
        audit_insp = self.inspect_audit_evidence(task_id)
        summary.audit_evidence = audit_insp
        if not audit_insp.has_evidence:
            notes.append(
                "Audit evidence: no durable audit records found for this task_id."
            )

        # Lineage
        lineage_insp = self.inspect_lineage(task_id)
        summary.lineage = lineage_insp

        # Populate trace_id from lineage if still empty
        if not summary.trace_id and lineage_insp is not None:
            summary.trace_id = lineage_insp.trace_id or ""

        # Reviewability: enough data to reason about what happened
        summary.reviewable = self._is_reviewable(task_insp, audit_insp, recovery_insp)
        if not summary.reviewable:
            notes.append(
                "Task not found in canonical runtime, lifecycle registry, "
                "or durable audit store — insufficient evidence for review."
            )

        summary.review_notes = notes
        return summary

    # ── Flow-Level Inspection ────────────────────────────────────────────

    def inspect_flow(self, flow_id: str) -> Optional["FlowOperatorProjection"]:
        """Return a read-only :class:`~core.flow_level_operator_surface.FlowOperatorProjection` for *flow_id*.

        Delegates to :class:`~core.flow_level_operator_surface.FlowLevelOperatorSurface`
        which aggregates flow identity, lineage, Android execution phase,
        recovery status, truth alignment, and result convergence into a
        single canonical projection.

        Returns ``None`` if *flow_id* is not known to the delegated flow
        entity runtime.
        """
        try:
            from core.flow_level_operator_surface import (
                get_flow_level_operator_surface,
            )
            return get_flow_level_operator_surface().inspect_flow(flow_id)
        except Exception as exc:
            logger.warning("inspect_flow(%s) failed: %s", flow_id, exc)
            return None

    # ── Operator Snapshot ────────────────────────────────────────────────

    @staticmethod
    def _governance_summary_from_snapshot(snapshot: OperatorSnapshot) -> Dict[str, int]:
        policy_layer = snapshot.governance_state.get("policy_layer", {})
        summary = policy_layer.get("summary", {})
        return {
            "hard_block_count": int(summary.get("hard_block_count", 0)),
            "soft_degraded_count": int(summary.get("soft_degraded_count", 0)),
            "manual_decision_count": int(summary.get("manual_decision_count", 0)),
        }

    def _build_operator_action_availability(self, snapshot: OperatorSnapshot) -> Dict[str, Any]:
        """Build policy-aware operator action availability for a given snapshot."""
        from core.operator_action_contract import OperatorActionKind

        summary = self._governance_summary_from_snapshot(snapshot)
        has_hard_block = summary["hard_block_count"] > 0
        has_soft_degraded = summary["soft_degraded_count"] > 0
        has_manual_decision = summary["manual_decision_count"] > 0
        has_active_flows = snapshot.active_flow_count > 0
        has_online_devices = snapshot.online_device_count > 0
        continuity_unstable = snapshot.presence_tristate in {"liminal", "manifest"}

        catalog: Dict[str, Dict[str, Any]] = {
            OperatorActionKind.dispatch.value: {
                "control_mode": "manual",
                "available": True,
                "reason": "Canonical operator task dispatch entry path.",
            },
            OperatorActionKind.device_dispatch.value: {
                "control_mode": "manual",
                "available": True,
                "reason": (
                    "Target-device dispatch always uses canonical routing; runtime may "
                    "still reject unavailable devices safely."
                ),
            },
            OperatorActionKind.flow_cancel.value: {
                "control_mode": "manual",
                "available": True,
                "reason": "Flow cancellation request is always accepted for canonical evaluation.",
            },
            OperatorActionKind.retry_admission.value: {
                "control_mode": "manual",
                "available": has_hard_block or has_manual_decision,
                "reason": "Admission retry is meaningful on blocked/manual governance outcomes.",
            },
            OperatorActionKind.request_capability_revalidation.value: {
                "control_mode": "automatic",
                "available": has_online_devices or has_soft_degraded or has_manual_decision,
                "reason": "Capability revalidation can be requested when devices/governance indicate drift.",
            },
            OperatorActionKind.reopen_session_continuity.value: {
                "control_mode": "manual",
                "available": continuity_unstable or has_active_flows,
                "reason": "Continuity reopen is exposed only when continuity appears unstable.",
            },
            OperatorActionKind.rebind_session_continuity.value: {
                "control_mode": "manual",
                "available": continuity_unstable or has_active_flows,
                "reason": "Continuity rebind is exposed only when continuity appears unstable.",
            },
            OperatorActionKind.trigger_recovery.value: {
                "control_mode": "manual",
                "available": has_soft_degraded or has_hard_block,
                "reason": "Recovery trigger is policy-valid during degraded/blocked operation.",
            },
            OperatorActionKind.acknowledge_recovery.value: {
                "control_mode": "automatic",
                "available": has_soft_degraded or has_hard_block or has_manual_decision,
                "reason": "Recovery acknowledgement is surfaced when governance tracks recovery work.",
            },
            OperatorActionKind.suspend_participant.value: {
                "control_mode": "approval_gated",
                "available": has_online_devices and (has_soft_degraded or has_hard_block),
                "reason": "Participant suspension is high-impact and requires degraded/blocked evidence.",
            },
            OperatorActionKind.isolate_device.value: {
                "control_mode": "approval_gated",
                "available": has_online_devices and (has_soft_degraded or has_hard_block),
                "reason": "Device isolation is high-impact and requires degraded/blocked evidence.",
            },
            OperatorActionKind.switch_path_selection.value: {
                "control_mode": "manual",
                "available": has_active_flows or has_soft_degraded or has_hard_block,
                "reason": "Path switching is exposed when active flow or policy risk is present.",
            },
            OperatorActionKind.reevaluate_path_selection.value: {
                "control_mode": "automatic",
                "available": has_active_flows or has_soft_degraded or has_hard_block,
                "reason": "Path re-evaluation can be requested while flow/policy is unsettled.",
            },
            OperatorActionKind.reopen_closure.value: {
                "control_mode": "approval_gated",
                "available": has_manual_decision or has_hard_block,
                "reason": "Closure reopen requires explicit governance concern.",
            },
            OperatorActionKind.finalize_closure.value: {
                "control_mode": "approval_gated",
                "available": not has_hard_block and not has_soft_degraded,
                "reason": "Closure finalization requires no active blocked/degraded policy signal.",
            },
            OperatorActionKind.reject_closure.value: {
                "control_mode": "approval_gated",
                "available": has_manual_decision or has_hard_block,
                "reason": "Closure rejection requires explicit governance concern.",
            },
            OperatorActionKind.acknowledge_blocker.value: {
                "control_mode": "manual",
                "available": has_hard_block or has_manual_decision,
                "reason": "Blocker acknowledgement is exposed only when blockers are present.",
            },
            OperatorActionKind.escalate_dependency_failure.value: {
                "control_mode": "approval_gated",
                "available": True,
                "reason": "Dependency escalation is high-impact and policy-tracked.",
            },
        }

        for action in catalog.values():
            action["requires_approval"] = action["control_mode"] == "approval_gated"
            action["operator_executable"] = action["control_mode"] in {
                "manual",
                "automatic",
                "approval_gated",
            }
        return {
            "authority": OPERATOR_SURFACE_AUTHORITY,
            "policy": OPERATOR_ACTION_LAYER_POLICY,
            "mode_legend": {
                "automatic": "Policy-derived or auto-reconcilable action type.",
                "manual": "Operator can execute directly when state-gated policy allows.",
                "approval_gated": "Operator action requires explicit approval_token.",
            },
            "state_basis": {
                "hard_block_count": summary["hard_block_count"],
                "soft_degraded_count": summary["soft_degraded_count"],
                "manual_decision_count": summary["manual_decision_count"],
                "active_flow_count": snapshot.active_flow_count,
                "online_device_count": snapshot.online_device_count,
                "presence_tristate": snapshot.presence_tristate,
            },
            "actions": catalog,
        }

    def get_operator_action_availability(self) -> Dict[str, Any]:
        """Return policy-aware operator action availability derived from current state."""
        return self._build_operator_action_availability(self.operator_snapshot())

    def operator_snapshot(self) -> OperatorSnapshot:
        """Return a compact :class:`OperatorSnapshot` of the current runtime.

        Aggregates data from all canonical runtime layers.
        Always returns a valid snapshot (empty values on failure).
        """
        snap = OperatorSnapshot()

        # Task runtime
        try:
            from core.canonical_task import get_canonical_task_runtime

            runtime = get_canonical_task_runtime()
            ct_snap = runtime.snapshot()
            snap.active_task_count = ct_snap.total_tasks
            snap.recent_tasks = [
                {
                    "task_id": r.get("task_id", ""),
                    "lifecycle": r.get("lifecycle", ""),
                    "tool": r.get("tool", ""),
                }
                for r in list(ct_snap.recent_records)[:20]
            ]
        except Exception as exc:
            logger.debug("operator_snapshot: task runtime unavailable: %s", exc)

        # Capability assimilation (devices / providers)
        try:
            from core.capability_assimilation import (
                get_capability_assimilation_layer,
            )

            layer = get_capability_assimilation_layer()
            layer_snap = layer.snapshot()
            snap.capability_provider_count = layer_snap.get("total_nodes", 0)
            # online providers: from by_presence_state where state == "online"
            by_presence = layer_snap.get("by_presence_state", {})
            snap.online_provider_count = by_presence.get("online", 0)
        except Exception as exc:
            logger.debug("operator_snapshot: capability assimilation unavailable: %s", exc)

        # Network topology
        try:
            from core.network_topology_runtime import get_network_topology_runtime

            topo_runtime = get_network_topology_runtime()
            topo_snap = topo_runtime.snapshot()
            snap.topology_node_count = topo_snap.total_nodes
            snap.topology_edge_count = topo_snap.total_edges
            # Count "available" nodes from nodes_by_state
            unavailable = topo_snap.nodes_by_state.get("unavailable", 0)
            latent = topo_snap.nodes_by_state.get("latent", 0)
            snap.online_device_count = max(0, topo_snap.total_nodes - unavailable - latent)
        except Exception as exc:
            logger.debug("operator_snapshot: network topology unavailable: %s", exc)

        # Source-runtime posture authority
        try:
            from core.source_runtime_posture import build_source_runtime_posture_snapshot

            posture_snap = build_source_runtime_posture_snapshot()
            snap.source_runtime_posture_counts = {
                "control_only": posture_snap.control_only_count,
                "join_runtime": posture_snap.join_runtime_count,
            }
            snap.recent_source_runtime_postures = [record.to_dict() for record in posture_snap.recent_records[-10:]]
        except Exception as exc:
            logger.debug("operator_snapshot: source runtime posture unavailable: %s", exc)

        # Android ecosystem — compact count summary from DEVICE_STATE_SNAPSHOT (PR-RT, PR-4)
        # Intentionally excludes the per-device ``devices`` list — that detail
        # is owned by GET /api/v1/operator/devices/ecosystem.  The snapshot only
        # carries the whitelisted count-level keys defined in
        # ANDROID_ECOSYSTEM_SNAPSHOT_KEYS.
        try:
            from core.android_device_state_store import get_device_ecosystem_summary
            eco = get_device_ecosystem_summary()
            snap.android_ecosystem = {
                k: v for k, v in eco.items() if k in ANDROID_ECOSYSTEM_SNAPSHOT_KEYS
            }
            filtered = set(eco.keys()) - ANDROID_ECOSYSTEM_SNAPSHOT_KEYS
            if filtered:
                logger.debug(
                    "operator_snapshot: ecosystem summary filtered %d key(s) not in whitelist: %s",
                    len(filtered),
                    sorted(filtered),
                )
        except Exception as exc:
            logger.debug("operator_snapshot: delegated flow count unavailable: %s", exc)

        # Delegated flow count — active flows from DelegatedFlowEntityRuntime (PR-4)
        # For per-flow detail see GET /api/v1/operator/flows.
        try:
            from core.delegated_flow_entity import get_delegated_flow_entity_runtime
            flow_runtime = get_delegated_flow_entity_runtime()
            all_entities = flow_runtime.list_all()
            snap.active_flow_count = sum(
                1 for e in all_entities if e.phase.is_active()
            )
        except Exception as exc:
            logger.debug("operator_snapshot: delegated flow count unavailable: %s", exc)

        # PR-8 V2: Desktop shell state — read the current UI clothing mode from
        # the SystemStateMachine singleton.  Gracefully degrades when the module
        # is unavailable (e.g. headless / non-desktop deployments).
        try:
            from system_integration.state_machine_ui_integration import (
                SystemStateMachine as _SSM,
            )
            _ssm = _SSM()
            snap.desktop_shell_state = _ssm.current_state.value
        except Exception as exc:
            logger.debug("operator_snapshot: desktop shell state unavailable: %s", exc)

        # PR-8 V2: Presence tri-state — read the dominant tri-state from the
        # DesktopPresenceRuntime singleton.  This tells operator surfaces
        # whether the subject is currently at rest, processing, or manifesting.
        try:
            from core.desktop_presence_runtime import get_desktop_presence_runtime as _get_dpr
            _psum = _get_dpr().presence_summary()
            snap.presence_tristate = _psum.get("dominant_tristate", "silent")
        except Exception as exc:
            logger.debug("operator_snapshot: presence tristate unavailable: %s", exc)

        # PR-8 V2: Compose manifestation_summary by combining shell and presence
        # state.  This is a derived, read-only view — no new truth is stored.
        if snap.desktop_shell_state or snap.presence_tristate:
            snap.manifestation_summary = {
                "desktop_shell_state": snap.desktop_shell_state,
                "presence_tristate": snap.presence_tristate,
                "_source": "operator_surface.operator_snapshot",
            }

        # Unified governance semantics (V2 authority vs Android autonomy)
        try:
            from core.unified_governance_semantics import build_unified_governance_state

            snap.governance_state = build_unified_governance_state()
            snap.mesh_runtime_state = dict(snap.governance_state.get("mesh_runtime_state", {}))
        except Exception as exc:
            logger.debug("operator_snapshot: governance semantics unavailable: %s", exc)

        try:
            snap.operator_action_layer = self._build_operator_action_availability(snap)
        except Exception as exc:
            logger.debug("operator_snapshot: operator action layer unavailable: %s", exc)

        return snap

    # ── Operator Action (PR-3: Control-Plane Activation) ─────────────────

    async def execute_operator_action(
        self,
        request: "OperatorActionRequest",
    ) -> "OperatorActionResult":
        """Execute an operator-originated action via the canonical runtime path.

        This is the **sole** entry point for operator-panel-originated actions.
        All action kinds are routed through the canonical execution path —
        no parallel dispatch engine is introduced.

        Action routing
        --------------
        ``dispatch`` / ``device_dispatch``
            Delegates to :meth:`~core.desktop_presence_runtime.DesktopPresenceRuntime.handle_request`
            with ``source="operator"`` and ``entry_mode="operator_action"``.
            This enters the tri-state lifecycle → OpenClawd → canonical dispatch
            chain identically to a chat-originated request, but is stamped with
            the ``"operator"`` carrier tag so it can be identified in traces.

        ``flow_cancel``
            Retrieves the target :class:`~core.delegated_flow_entity.DelegatedFlowEntity`
            by ``request.flow_id`` and applies the ``cancel`` signal via
            :func:`~core.delegated_flow_entity.advance_flow_phase`.
            Terminal flows are not affected (safe semantics).

        Args:
            request: The :class:`~core.operator_action_contract.OperatorActionRequest`
                     describing the action to execute.

        Returns:
            An :class:`~core.operator_action_contract.OperatorActionResult` with
            ``accepted=True`` on success, or ``accepted=False`` with a non-empty
            ``error`` field on failure.
        """
        from core.operator_action_contract import (
            OperatorActionKind,
            OperatorActionResult,
            OPERATOR_ACTION_ENTRY_MODE,
            build_operator_action_result_from_runtime_result as build_result_from_runtime_result,
        )

        action_kind = request.action_kind
        availability = self.get_operator_action_availability()
        actions_catalog = dict(availability.get("actions") or {})
        action_policy = dict(actions_catalog.get(action_kind) or {})

        if not action_policy:
            return OperatorActionResult(
                action_kind=action_kind,
                accepted=False,
                error=f"unsupported action_kind: {action_kind!r}",
                runtime_result={
                    "policy_evaluation": "unsupported_action",
                    "policy": OPERATOR_ACTION_LAYER_POLICY,
                },
            )

        if not action_policy.get("available", False):
            return OperatorActionResult(
                action_kind=action_kind,
                accepted=False,
                error=(
                    "action blocked by policy/state gate: "
                    f"{action_policy.get('reason', 'not currently available')}"
                ),
                runtime_result={
                    "policy_evaluation": "state_gate_blocked",
                    "policy": OPERATOR_ACTION_LAYER_POLICY,
                    "control_mode": action_policy.get("control_mode", "manual"),
                },
            )

        if action_policy.get("control_mode") == "approval_gated" and not request.approval_token:
            return OperatorActionResult(
                action_kind=action_kind,
                accepted=False,
                error="approval_token is required for approval-gated operator action",
                runtime_result={
                    "policy_evaluation": "approval_required",
                    "policy": OPERATOR_ACTION_LAYER_POLICY,
                    "control_mode": "approval_gated",
                },
            )

        # ── dispatch / device_dispatch ────────────────────────────────────
        if action_kind in (
            OperatorActionKind.dispatch.value,
            OperatorActionKind.device_dispatch.value,
        ):
            try:
                from core.desktop_presence_runtime import get_desktop_presence_runtime
                runtime = get_desktop_presence_runtime()
                result = await runtime.handle_request(
                    message=request.message,
                    source="operator",
                    device_id=request.device_id,
                    session_id=request.session_id or None,
                    user_id=request.user_id or "operator",
                    context=list(request.context) if request.context else None,
                    required_capabilities=(
                        list(request.required_capabilities)
                        if request.required_capabilities
                        else None
                    ),
                    entry_mode=OPERATOR_ACTION_ENTRY_MODE,
                )
                rr = result if isinstance(result, dict) else {}
                rr.setdefault("operator_action_layer_policy", OPERATOR_ACTION_LAYER_POLICY)
                rr.setdefault("control_mode", action_policy.get("control_mode", "manual"))
                rr.setdefault("approval_gated", action_policy.get("requires_approval", False))
                return build_result_from_runtime_result(
                    action_kind=action_kind,
                    runtime_result=rr,
                )
            except Exception as exc:
                logger.error(
                    "execute_operator_action(%s) runtime delegation failed: %s",
                    action_kind,
                    exc,
                )
                return OperatorActionResult(
                    action_kind=action_kind,
                    accepted=False,
                    error=str(exc),
                    runtime_result={
                        "policy_evaluation": "runtime_delegation_failed",
                        "policy": OPERATOR_ACTION_LAYER_POLICY,
                        "control_mode": action_policy.get("control_mode", "manual"),
                    },
                )

        # ── flow_cancel ───────────────────────────────────────────────────
        if action_kind == OperatorActionKind.flow_cancel.value:
            flow_id = request.flow_id or ""
            if not flow_id:
                return OperatorActionResult(
                    action_kind=action_kind,
                    accepted=False,
                    error="flow_id is required for flow_cancel action",
                )
            try:
                from core.delegated_flow_entity import (
                    get_delegated_flow,
                    advance_flow_phase,
                    DelegatedFlowSignal,
                )
                entity = get_delegated_flow(flow_id)
                if entity is None:
                    return OperatorActionResult(
                        action_kind=action_kind,
                        accepted=False,
                        error=f"flow '{flow_id}' not found",
                    )
                # advance_flow_phase is safe for terminal flows — it is a no-op
                # when the transition is not valid for the current phase.
                updated = advance_flow_phase(entity, DelegatedFlowSignal.cancel)
                cancelled = getattr(updated.phase, "value", str(updated.phase))
                return OperatorActionResult(
                    action_kind=action_kind,
                    accepted=True,
                    runtime_result={
                        "flow_id": flow_id,
                        "phase_after_cancel": cancelled,
                        "_source": "delegated_flow_entity_runtime",
                        "operator_action_layer_policy": OPERATOR_ACTION_LAYER_POLICY,
                        "control_mode": action_policy.get("control_mode", "manual"),
                        "approval_gated": action_policy.get("requires_approval", False),
                    },
                )
            except Exception as exc:
                logger.error(
                    "execute_operator_action(flow_cancel, flow_id=%s) failed: %s",
                    flow_id,
                    exc,
                )
                return OperatorActionResult(
                    action_kind=action_kind,
                    accepted=False,
                    error=str(exc),
                    runtime_result={
                        "policy_evaluation": "flow_cancellation_failed",
                        "policy": OPERATOR_ACTION_LAYER_POLICY,
                        "control_mode": action_policy.get("control_mode", "manual"),
                    },
                )

        # ── Governed intervention actions (policy + audit, no bypass path) ─
        if action_kind in {
            OperatorActionKind.retry_admission.value,
            OperatorActionKind.request_capability_revalidation.value,
            OperatorActionKind.reopen_session_continuity.value,
            OperatorActionKind.rebind_session_continuity.value,
            OperatorActionKind.trigger_recovery.value,
            OperatorActionKind.acknowledge_recovery.value,
            OperatorActionKind.suspend_participant.value,
            OperatorActionKind.isolate_device.value,
            OperatorActionKind.switch_path_selection.value,
            OperatorActionKind.reevaluate_path_selection.value,
            OperatorActionKind.reopen_closure.value,
            OperatorActionKind.finalize_closure.value,
            OperatorActionKind.reject_closure.value,
            OperatorActionKind.acknowledge_blocker.value,
            OperatorActionKind.escalate_dependency_failure.value,
        }:
            return OperatorActionResult(
                action_kind=action_kind,
                accepted=True,
                runtime_result={
                    "_source": "operator_action_layer",
                    "policy": OPERATOR_ACTION_LAYER_POLICY,
                    "control_mode": action_policy.get("control_mode", "manual"),
                    "approval_gated": action_policy.get("requires_approval", False),
                    "approval_token_present": bool(request.approval_token),
                    "operator_notes": request.action_notes,
                    "disposition": "governed_intervention_recorded",
                    "governance_basis": dict(availability.get("state_basis") or {}),
                },
            )

        return OperatorActionResult(
            action_kind=action_kind,
            accepted=False,
            error=f"unsupported action_kind: {action_kind!r}",
            runtime_result={
                "policy_evaluation": "unsupported_action",
                "policy": OPERATOR_ACTION_LAYER_POLICY,
            },
        )


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

_SURFACE: Optional[OperatorSurface] = None


def get_operator_surface() -> OperatorSurface:
    """Return the singleton :class:`OperatorSurface` instance."""
    global _SURFACE
    if _SURFACE is None:
        _SURFACE = OperatorSurface()
    return _SURFACE


def reset_operator_surface() -> None:
    """Reset the singleton — for testing only."""
    global _SURFACE
    _SURFACE = None
