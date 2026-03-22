#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/orchestration/multi_device_plan.py
=========================================
PR-8 — Multi-Device Orchestration Plan Contracts
--------------------------------------------------

This module defines first-class **orchestration plan** and **result** objects
that make the orchestration layer's intent explicit and distinct from the
cross-device execution substrate.

Architectural role
------------------
The orchestration layer (e.g. :class:`~core.swarm_coordinator.SwarmCoordinator`)
is a **coordination/planning layer that operates above the unified cross-device
execution substrate**.  It:

* Selects target devices and assigns agents to them (planning decisions).
* Records those decisions as a first-class :class:`OrchestrationPlan` before
  any substrate dispatch occurs.
* Delegates actual dispatch/transport to the substrate
  (:class:`~core.command_router.CommandRouter`) via its well-defined API.
* Collects per-member raw results from the substrate and aggregates them into
  an :class:`OrchestrationResult`.

**Orchestration ≠ Substrate.**  The substrate (CommandRouter / route_envelope)
is concerned with *how* commands travel to remote devices.  The orchestration
layer is concerned with *which* devices to use and *how to coordinate* them —
decisions that happen logically before and after the substrate transport.

Contracts
---------
* :class:`OrchestrationDecision` — a single device-assignment decision for one
  agent/member within a plan.
* :class:`OrchestrationPlan` — the complete set of pre-dispatch decisions for a
  multi-device coordination round: which agents go to which devices, and why.
* :class:`OrchestrationMemberResult` — per-member result returned by the
  substrate, attached to the plan after all dispatches complete.
* :class:`OrchestrationResult` — aggregated result for the whole plan.

Usage
-----
    from core.orchestration.multi_device_plan import (
        OrchestrationDecision,
        OrchestrationPlan,
        OrchestrationMemberResult,
        OrchestrationResult,
        build_orchestration_plan,
        build_orchestration_result,
    )

    plan = build_orchestration_plan(
        task="Analyse Q3 data",
        session_id="sess_abc",
        trace_id="trace_xyz",
        task_id="task_001",
        decisions=[
            OrchestrationDecision(
                agent_id="a1",
                agent_name="Analyst",
                target_device_id="win_host_01",
                score=0.87,
                resolved_execution_mode="agent_runtime",
                assignment_source="scoring_engine",
            ),
        ],
    )
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Orchestration Decision
# ---------------------------------------------------------------------------


@dataclass
class OrchestrationDecision:
    """A single device-assignment decision for one agent/member.

    Produced by the orchestration layer (scoring engine + SwarmCoordinator)
    *before* any substrate dispatch.

    Parameters
    ----------
    agent_id:
        Identifier for the agent or team member being assigned.
    agent_name:
        Human-readable name.
    target_device_id:
        Device selected for this agent by the orchestration layer.
        ``None`` means no eligible device was found.
    score:
        Composite device score from the
        :class:`~core.control_plane.smart_scheduler.DeviceScoringEngine`.
        ``0.0`` when scoring was not performed.
    resolved_execution_mode:
        Execution mode resolved by the orchestration layer (e.g.
        ``"agent_runtime"`` or ``"command_only"``).  ``None`` when unknown.
    assignment_source:
        Human-readable description of how the device was selected, e.g.
        ``"scoring_engine"`` or ``"caller_provided"``.
    manifest_id:
        Optional manifest identifier for traceability.
    metadata:
        Arbitrary extra information captured by the orchestration layer.
    """

    agent_id: str
    agent_name: str = ""
    target_device_id: Optional[str] = None
    score: float = 0.0
    resolved_execution_mode: Optional[str] = None
    assignment_source: str = ""
    manifest_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Orchestration Plan
# ---------------------------------------------------------------------------


@dataclass
class OrchestrationPlan:
    """Complete set of orchestration decisions for a multi-device coordination
    round.

    An :class:`OrchestrationPlan` is built by the orchestration layer
    *before* any dispatch call reaches the substrate.  It captures the
    planning intent and device-assignment rationale as a first-class object.

    Parameters
    ----------
    plan_id:
        Unique identifier for this plan.
    task:
        High-level task description shared by all members.
    session_id / trace_id / task_id:
        Correlation identifiers propagated from the caller.
    decisions:
        Ordered list of :class:`OrchestrationDecision` objects, one per agent.
    created_at:
        Wall-clock timestamp (seconds since epoch) when the plan was built.
    metadata:
        Arbitrary extra information.
    """

    plan_id: str
    task: str
    session_id: str = ""
    trace_id: str = ""
    task_id: str = ""
    decisions: List[OrchestrationDecision] = field(default_factory=list)
    created_at: float = field(default_factory=time.monotonic)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def assigned_count(self) -> int:
        """Number of members that received a device assignment."""
        return sum(1 for d in self.decisions if d.target_device_id is not None)

    @property
    def unassigned_count(self) -> int:
        """Number of members that did not receive a device assignment."""
        return sum(1 for d in self.decisions if d.target_device_id is None)

    def to_summary_dict(self) -> Dict[str, Any]:
        """Return a compact summary suitable for logging/audit."""
        return {
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "total_members": len(self.decisions),
            "assigned": self.assigned_count,
            "unassigned": self.unassigned_count,
            "devices": [d.target_device_id for d in self.decisions if d.target_device_id],
        }


# ---------------------------------------------------------------------------
# Orchestration Member Result
# ---------------------------------------------------------------------------


@dataclass
class OrchestrationMemberResult:
    """Per-member result returned by the substrate dispatch, attached to a plan.

    Parameters
    ----------
    agent_id:
        The agent/member identifier.
    decision:
        The :class:`OrchestrationDecision` that led to this dispatch.
    success:
        Whether the substrate dispatch succeeded.
    output:
        Raw output/result string from the remote device.
    error:
        Error description when ``success=False``.
    latency_ms:
        Round-trip dispatch latency in milliseconds.
    raw:
        The full raw result dict from the substrate.
    """

    agent_id: str
    decision: OrchestrationDecision
    success: bool = False
    output: str = ""
    error: Optional[str] = None
    latency_ms: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Orchestration Result
# ---------------------------------------------------------------------------


@dataclass
class OrchestrationResult:
    """Aggregated result for a complete :class:`OrchestrationPlan`.

    Produced by the orchestration layer after all substrate dispatches
    complete.  The orchestration layer synthesises the individual
    :class:`OrchestrationMemberResult` objects into a human-readable
    summary and collects aggregate metrics.

    Parameters
    ----------
    plan:
        The :class:`OrchestrationPlan` that was executed.
    member_results:
        Per-member results collected from the substrate.
    synthesized:
        Human-readable synthesis of all successful outputs.
    total_latency_ms:
        Wall-clock time from plan dispatch start to all completions.
    orchestration_layer:
        Name of the orchestration component that produced this result.
        Defaults to ``"SwarmCoordinator"`` for backward compatibility.
    """

    plan: OrchestrationPlan
    member_results: List[OrchestrationMemberResult] = field(default_factory=list)
    synthesized: str = ""
    total_latency_ms: float = 0.0
    orchestration_layer: str = "SwarmCoordinator"

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.member_results if r.success)

    @property
    def failure_count(self) -> int:
        return sum(1 for r in self.member_results if not r.success)

    def to_summary_dict(self) -> Dict[str, Any]:
        """Return a compact summary suitable for logging/audit."""
        return {
            "plan_id": self.plan.plan_id,
            "task_id": self.plan.task_id,
            "trace_id": self.plan.trace_id,
            "orchestration_layer": self.orchestration_layer,
            "total_members": len(self.member_results),
            "succeeded": self.success_count,
            "failed": self.failure_count,
            "total_latency_ms": round(self.total_latency_ms, 1),
        }


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


def build_orchestration_plan(
    task: str,
    decisions: List[OrchestrationDecision],
    *,
    session_id: str = "",
    trace_id: str = "",
    task_id: str = "",
    plan_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> OrchestrationPlan:
    """Build an :class:`OrchestrationPlan` from a list of decisions.

    Parameters
    ----------
    task:
        High-level task description.
    decisions:
        Device-assignment decisions produced by the orchestration layer.
    session_id / trace_id / task_id:
        Correlation identifiers.
    plan_id:
        If empty, a UUID is generated.
    metadata:
        Arbitrary extra metadata.

    Returns
    -------
    OrchestrationPlan
    """
    return OrchestrationPlan(
        plan_id=plan_id or f"orch_plan_{uuid.uuid4().hex[:12]}",
        task=task,
        session_id=session_id,
        trace_id=trace_id,
        task_id=task_id,
        decisions=decisions,
        metadata=dict(metadata or {}),
    )


def build_orchestration_result(
    plan: OrchestrationPlan,
    member_results: List[OrchestrationMemberResult],
    *,
    synthesized: str = "",
    total_latency_ms: float = 0.0,
    orchestration_layer: str = "SwarmCoordinator",
) -> OrchestrationResult:
    """Build an :class:`OrchestrationResult` from a completed plan.

    Parameters
    ----------
    plan:
        The :class:`OrchestrationPlan` that was executed.
    member_results:
        Per-member results from the substrate.
    synthesized:
        Human-readable synthesis of all successful outputs.
    total_latency_ms:
        Total wall-clock dispatch time.
    orchestration_layer:
        Name of the orchestration component.

    Returns
    -------
    OrchestrationResult
    """
    return OrchestrationResult(
        plan=plan,
        member_results=member_results,
        synthesized=synthesized,
        total_latency_ms=total_latency_ms,
        orchestration_layer=orchestration_layer,
    )
