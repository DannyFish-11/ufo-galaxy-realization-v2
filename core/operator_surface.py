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
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.OperatorSurface")

__all__ = [
    # Authority sentinels
    "OPERATOR_SURFACE_AUTHORITY",
    "OPERATOR_SURFACE_LAYER_POSITION",
    "OPERATOR_SURFACE_CONTRACT_VERSION",
    "OPERATOR_SURFACE_PROJECTION_POLICY",
    # Role boundary sentinels
    "OPERATOR_CONSOLE_ROLE",
    "STATUS_BOARD_ROLE",
    "TOPOLOGY_VIEWER_ROLE",
    # Dataclasses
    "TaskInspection",
    "RouteInspection",
    "ExecutorInspection",
    "FailureDomainInspection",
    "LineageInspection",
    "DevicePresenceSummary",
    "OperatorSnapshot",
    # Class
    "OperatorSurface",
    # Helpers
    "get_operator_surface",
    "reset_operator_surface",
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
    """

    snapshot_id: str = field(
        default_factory=lambda: f"snap_{uuid.uuid4().hex[:12]}"
    )
    generated_at: float = field(default_factory=time.time)

    # Task runtime summary
    active_task_count: int = 0
    recent_tasks: List[Dict[str, Any]] = field(default_factory=list)

    # Device presence summary
    online_device_count: int = 0
    device_summaries: List[Dict[str, Any]] = field(default_factory=list)

    # Topology summary
    topology_node_count: int = 0
    topology_edge_count: int = 0

    # Capability summary
    capability_provider_count: int = 0
    online_provider_count: int = 0

    # Authority declaration
    authority: str = OPERATOR_SURFACE_AUTHORITY
    contract_version: str = OPERATOR_SURFACE_CONTRACT_VERSION
    projection_policy: str = OPERATOR_SURFACE_PROJECTION_POLICY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "generated_at": self.generated_at,
            "active_task_count": self.active_task_count,
            "recent_tasks": self.recent_tasks,
            "online_device_count": self.online_device_count,
            "device_summaries": self.device_summaries,
            "topology_node_count": self.topology_node_count,
            "topology_edge_count": self.topology_edge_count,
            "capability_provider_count": self.capability_provider_count,
            "online_provider_count": self.online_provider_count,
            "authority": self.authority,
            "contract_version": self.contract_version,
            "projection_policy": self.projection_policy,
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
                target_at_failure=(
                    task.routing.selected_targets[0]
                    if task.routing.selected_targets else ""
                ),
                transport_at_failure=getattr(
                    task.routing, "transport_preference", ""
                ),
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

        Returns ``None`` if the task is not known.
        """
        try:
            from core.canonical_task import get_canonical_task_runtime
            runtime = get_canonical_task_runtime()
            task = runtime.get_by_task_id(task_id)
            if task is None:
                return None

            retry_chain: List[str] = []
            fallback_chain: List[str] = []
            timeline: List[Dict[str, Any]] = []

            try:
                from core.task_graph_runtime import get_task_graph_runtime
                tgr = get_task_graph_runtime()
                retry_chain = [
                    r.retry_task_id for r in tgr.get_retry_lineage(task_id)
                ]
                fallback_chain = [
                    fb.fallback_task_id for fb in tgr.get_fallback_lineage(task_id)
                ]
            except Exception:
                pass

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
        except Exception as exc:
            logger.warning("inspect_lineage(%s) failed: %s", task_id, exc)
            return None

    # ── Operator Snapshot ────────────────────────────────────────────────

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
            logger.debug(
                "operator_snapshot: capability assimilation unavailable: %s", exc
            )

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
            snap.online_device_count = max(
                0, topo_snap.total_nodes - unavailable - latent
            )
        except Exception as exc:
            logger.debug(
                "operator_snapshot: network topology unavailable: %s", exc
            )

        return snap


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
