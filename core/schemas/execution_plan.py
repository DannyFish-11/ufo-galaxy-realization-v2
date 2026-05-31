#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.schemas.execution_plan — Canonical Execution Plan Schema
=============================================================

PR-11 — Canonical Execution Plan Model

Defines structured first-class objects representing **execution intent**
before any runtime dispatch occurs.  The plan is produced by the subject
decision core (:class:`~core.openclawd.OpenClawd`) after its decision
logic has resolved the target mode but before any actual execution step
is taken.

Architectural role
------------------
The execution plan sits at the boundary between the *decision* phase
(which path / which device / which mode?) and the *execution* phase
(actually dispatching the envelope to the substrate):

::

    OpenClawd (decision core)
        1. _determine_execution_path()   ← existing decision logic
        2. build_execution_plan()        ← NEW: express intent as a plan
        3. _delegate_*() / _dispatch_*() ← existing dispatch (unchanged)

The plan is an **additive, inspectable record** of that intent.  Every
existing dispatch path continues to work exactly as before; the plan is
only attached as metadata for observability, diagnostics, and future
lifecycle tracking.

Main concepts
-------------
:class:`ExecutionStepType`
    Stable enum of the recognised execution styles.  Maps 1-to-1 onto
    the delegation-point labels used throughout the codebase.

:class:`ExecutionStep`
    One concrete step inside a plan.  Carries target device(s),
    :class:`~core.schemas.remote_execution.RemoteExecutionMode` where
    relevant, required capabilities, and lightweight constraint metadata.

:class:`ExecutionPlan`
    The complete plan: an ordered list of :class:`ExecutionStep` objects
    produced before execution starts.  Serialisable, hashable on
    ``plan_id``.

:func:`build_execution_plan`
    Principal builder — derive a plan from the resolved execution path,
    delegation point, and optional step hints.

:func:`plan_summary`
    Compact serialisable summary for embedding in response metadata.

Relationship to other schemas
------------------------------
* :class:`~core.schemas.remote_execution.RemoteExecutionMode` — used on
  remote/orchestration steps to record the wire-level execution style.
* :class:`~core.orchestration.multi_device_plan.OrchestrationPlan` —
  the deeper per-member scheduling decisions produced by
  :class:`~core.swarm_coordinator.SwarmCoordinator`.  An
  :class:`ExecutionPlan` step of type ``ORCHESTRATION`` references the
  orchestration plan by ID for traceability.
* :class:`~core.schemas.execution_authority.ExecutionLayerRole` —
  authority metadata stamped alongside the plan in response dicts.

Backward compatibility
----------------------
All fields are either required primitives or Optional with safe defaults.
Consumers that do not inspect the plan continue to work unchanged.  The
plan is always placed under the ``execution_plan`` key in response dicts,
so existing code that only reads ``success``, ``response``, or ``metadata``
is unaffected.

Usage::

    from core.schemas.execution_plan import (
        ExecutionStepType,
        ExecutionStep,
        ExecutionPlan,
        build_execution_plan,
        plan_summary,
    )

    # Build a plan for a local execution path
    plan = build_execution_plan(
        execution_path="local",
        delegation_point="local",
        trace_id="trace-abc",
        session_id="sess-123",
    )
    assert plan.steps[0].step_type == ExecutionStepType.LOCAL_MANIFESTATION
    print(plan_summary(plan))
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


__all__ = [
    "ExecutionStepType",
    "ExecutionStep",
    "ExecutionPlan",
    "build_execution_plan",
    "plan_summary",
    "plan_from_orchestration_decisions",
    "_stamp_plan_lifecycle",
]

# PR-12: Import lifecycle types (fail-soft — avoids circular-import risk).
try:
    from core.schemas.execution_lifecycle import (
        ExecutionLifecycleState as _ELS,
        LifecycleTransition as _LT,
    )
    _LIFECYCLE_OK = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _ELS = None  # type: ignore[assignment,misc]
    _LT = None   # type: ignore[assignment,misc]
    _LIFECYCLE_OK = False


# ---------------------------------------------------------------------------
# ExecutionStepType
# ---------------------------------------------------------------------------


class ExecutionStepType(str, Enum):
    """Canonical execution step types.

    Each value maps onto the delegation-point labels used in OpenClawd
    and the cross-device substrate.  Values are stable lowercase strings
    suitable for serialisation, logging, and API responses.

    Attributes
    ----------
    LOCAL_MANIFESTATION:
        Execution confined to the local Windows device via the System API
        (``DecisionExecutor`` / ``WindowsExecutionArbiter``).
        Corresponds to ``delegation_point="local"``.

    REMOTE_COMMAND:
        Structured command dispatched to a remote device via the gateway
        command path (``command_only`` mode).
        Corresponds to ``delegation_point="single_remote"`` +
        ``RemoteExecutionMode.command_only``.

    REMOTE_AGENT:
        Full agent runtime dispatched to a remote device
        (``agent_runtime`` mode).
        Corresponds to ``delegation_point="single_remote"`` +
        ``RemoteExecutionMode.agent_runtime``.

    ORCHESTRATION:
        Multi-device fan-out via the orchestration layer
        (``SwarmCoordinator``).
        Corresponds to ``delegation_point="multi_device_orchestration"``.

    OBSERVE:
        No-op / observe-only path — subject responds without acting.
        Corresponds to ``execution_path="none"``.
    """

    LOCAL_MANIFESTATION = "local_manifestation"
    REMOTE_COMMAND = "remote_command"
    REMOTE_AGENT = "remote_agent"
    ORCHESTRATION = "orchestration"
    OBSERVE = "observe"


# ---------------------------------------------------------------------------
# ExecutionStep
# ---------------------------------------------------------------------------


@dataclass
class ExecutionStep:
    """One concrete step inside an :class:`ExecutionPlan`.

    A step represents a single unit of execution intent — one delegation
    to one or more target devices with a well-defined mode and capability
    requirements.

    Parameters
    ----------
    step_id:
        Unique identifier for this step (UUID hex by default).
    step_type:
        The execution style for this step.
    target_devices:
        Device IDs this step targets.  Empty for local steps; ``["*"]``
        can represent an any-device fan-out intent.
    remote_execution_mode:
        Wire-level execution mode string (``"agent_runtime"`` or
        ``"command_only"``).  ``None`` for local or observe steps.
    required_capabilities:
        Optional list of device capabilities needed to run this step,
        propagated from the caller's ``required_capabilities`` hint.
    authority_origin:
        Layer that produced this step (e.g.
        ``"subject_decision_authority"``).
    timeout_ms:
        Optional timeout hint in milliseconds.  ``None`` means no
        explicit constraint.
    depends_on:
        Step IDs that must complete before this step starts.  Empty list
        means this step can run immediately.
    orchestration_plan_id:
        For ``ORCHESTRATION`` steps: the
        :class:`~core.orchestration.multi_device_plan.OrchestrationPlan`
        ``plan_id`` produced by :class:`~core.swarm_coordinator.SwarmCoordinator`.
        Allows traceability from the high-level plan down to the
        per-member scheduling decisions.
    metadata:
        Arbitrary extra information for diagnostics and future use.
    """

    step_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    step_type: ExecutionStepType = ExecutionStepType.OBSERVE
    target_devices: List[str] = field(default_factory=list)
    remote_execution_mode: Optional[str] = None
    required_capabilities: List[str] = field(default_factory=list)
    authority_origin: str = "subject_decision_authority"
    timeout_ms: Optional[int] = None
    depends_on: List[str] = field(default_factory=list)
    orchestration_plan_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    # PR-12: per-step lifecycle state and transition trail.
    lifecycle_state: Optional[str] = None
    lifecycle_trail: List[Any] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        d: Dict[str, Any] = {
            "step_id": self.step_id,
            "step_type": self.step_type.value,
            "target_devices": list(self.target_devices),
            "remote_execution_mode": self.remote_execution_mode,
            "required_capabilities": list(self.required_capabilities),
            "authority_origin": self.authority_origin,
            "timeout_ms": self.timeout_ms,
            "depends_on": list(self.depends_on),
            "orchestration_plan_id": self.orchestration_plan_id,
            "metadata": dict(self.metadata),
            # PR-12: lifecycle
            "lifecycle_state": self.lifecycle_state,
            "lifecycle_trail": [
                t.to_dict() if hasattr(t, "to_dict") else t
                for t in (self.lifecycle_trail or [])
            ],
        }
        return d


# ---------------------------------------------------------------------------
# ExecutionPlan
# ---------------------------------------------------------------------------


@dataclass
class ExecutionPlan:
    """Complete execution intent for one request, expressed as ordered steps.

    An :class:`ExecutionPlan` is built by :class:`~core.openclawd.OpenClawd`
    after its decision logic resolves the execution path but *before* any
    actual dispatch occurs.  It is an additive, inspectable record of the
    subject core's intent.

    Parameters
    ----------
    plan_id:
        Unique identifier for this plan (UUID hex by default).
    trace_id:
        Correlation ID propagated from the originating runtime session.
    session_id:
        Session identifier for context continuity.
    execution_path:
        The resolved execution path label (``"local"``, ``"cross_device"``,
        ``"hybrid"``, ``"none"``).  Mirrors
        :meth:`OpenClawd._determine_execution_path`.
    delegation_point:
        The delegation boundary label (``"local"``, ``"single_remote"``,
        ``"multi_device_orchestration"``).  ``None`` for observe paths.
    steps:
        Ordered list of :class:`ExecutionStep` objects.  For single-path
        requests this will typically contain exactly one step.
    created_at:
        Wall-clock timestamp (seconds since epoch) when the plan was built.
    metadata:
        Arbitrary extra information for diagnostics.
    """

    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    trace_id: str = ""
    session_id: str = ""
    execution_path: str = "none"
    delegation_point: Optional[str] = None
    steps: List[ExecutionStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # PR-12: plan-level lifecycle state and transition trail.
    lifecycle_state: Optional[str] = None
    lifecycle_trail: List[Any] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def primary_step_type(self) -> Optional[ExecutionStepType]:
        """Return the step type of the first step, or ``None`` if empty."""
        return self.steps[0].step_type if self.steps else None

    @property
    def is_local_only(self) -> bool:
        """``True`` when all steps are local-manifestation steps."""
        return bool(self.steps) and all(
            s.step_type == ExecutionStepType.LOCAL_MANIFESTATION for s in self.steps
        )

    @property
    def is_remote(self) -> bool:
        """``True`` when any step targets a remote device."""
        return any(
            s.step_type in (ExecutionStepType.REMOTE_COMMAND, ExecutionStepType.REMOTE_AGENT)
            for s in self.steps
        )

    @property
    def is_orchestration(self) -> bool:
        """``True`` when any step is an orchestration fan-out."""
        return any(s.step_type == ExecutionStepType.ORCHESTRATION for s in self.steps)

    @property
    def is_observe(self) -> bool:
        """``True`` when the plan is a no-op / observe-only plan."""
        return bool(self.steps) and all(
            s.step_type == ExecutionStepType.OBSERVE for s in self.steps
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "plan_id": self.plan_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "execution_path": self.execution_path,
            "delegation_point": self.delegation_point,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            # PR-12: lifecycle
            "lifecycle_state": self.lifecycle_state,
            "lifecycle_trail": [
                t.to_dict() if hasattr(t, "to_dict") else t
                for t in (self.lifecycle_trail or [])
            ],
        }


# ---------------------------------------------------------------------------
# Builder: build_execution_plan
# ---------------------------------------------------------------------------

# Mapping: (execution_path, delegation_point) → ExecutionStepType
_PATH_TO_STEP_TYPE: Dict[tuple, ExecutionStepType] = {
    ("local", "local"): ExecutionStepType.LOCAL_MANIFESTATION,
    ("cross_device", "single_remote"): ExecutionStepType.REMOTE_AGENT,
    ("cross_device", "multi_device_orchestration"): ExecutionStepType.ORCHESTRATION,
    ("hybrid", "local"): ExecutionStepType.LOCAL_MANIFESTATION,
    ("none", None): ExecutionStepType.OBSERVE,
    ("none", "local"): ExecutionStepType.OBSERVE,
}


def _resolve_step_type(
    execution_path: str,
    delegation_point: Optional[str],
    remote_execution_mode: Optional[str],
) -> ExecutionStepType:
    """Resolve the :class:`ExecutionStepType` from path + delegation + mode.

    The ``remote_execution_mode`` refines single-remote steps into
    ``REMOTE_COMMAND`` vs ``REMOTE_AGENT``.
    """
    key = (execution_path, delegation_point)
    if key in _PATH_TO_STEP_TYPE:
        base = _PATH_TO_STEP_TYPE[key]
        # Refine REMOTE_AGENT → REMOTE_COMMAND when mode says command_only.
        if base == ExecutionStepType.REMOTE_AGENT and remote_execution_mode == "command_only":
            return ExecutionStepType.REMOTE_COMMAND
        return base

    # Fallback heuristics
    if execution_path in ("cross_device", "hybrid") or delegation_point == "single_remote":
        if remote_execution_mode == "command_only":
            return ExecutionStepType.REMOTE_COMMAND
        return ExecutionStepType.REMOTE_AGENT
    if execution_path == "local" or delegation_point == "local":
        return ExecutionStepType.LOCAL_MANIFESTATION
    if delegation_point == "multi_device_orchestration":
        return ExecutionStepType.ORCHESTRATION
    return ExecutionStepType.OBSERVE


def _stamp_plan_lifecycle(plan: "ExecutionPlan") -> None:
    """PR-12: Stamp the initial lifecycle state on a newly-built plan.

    Sets ``plan.lifecycle_state = "planned"`` and records a creation
    transition.  Each step gets ``lifecycle_state = "created"`` with its
    own entry transition.  Fail-soft: if the lifecycle module is not
    available the function is a no-op.
    """
    if not _LIFECYCLE_OK or _ELS is None or _LT is None:
        return
    try:
        plan_transition = _LT.make(
            to_state=_ELS.PLANNED,
            from_state=_ELS.CREATED,
            reason="execution_plan_built",
        )
        plan.lifecycle_state = _ELS.PLANNED.value
        plan.lifecycle_trail = [plan_transition]

        for step in plan.steps:
            step_transition = _LT.make(
                to_state=_ELS.CREATED,
                from_state=None,
                reason="step_initialised",
            )
            step.lifecycle_state = _ELS.CREATED.value
            step.lifecycle_trail = [step_transition]
    except Exception as exc:
        pass  # lifecycle stamping is always additive / non-breaking


def build_execution_plan(
    *,
    execution_path: str = "none",
    delegation_point: Optional[str] = None,
    trace_id: str = "",
    session_id: str = "",
    device_id: Optional[str] = None,
    remote_execution_mode: Optional[str] = None,
    required_capabilities: Optional[List[str]] = None,
    orchestration_plan_id: Optional[str] = None,
    timeout_ms: Optional[int] = None,
    extra_steps: Optional[List[ExecutionStep]] = None,
    plan_metadata: Optional[Dict[str, Any]] = None,
) -> ExecutionPlan:
    """Build an :class:`ExecutionPlan` from resolved decision-core outputs.

    This is the principal builder, called by
    :class:`~core.openclawd.OpenClawd` after
    :meth:`~core.openclawd.OpenClawd._determine_execution_path` has
    resolved the execution branch but before any dispatch is delegated.

    All parameters are keyword-only to prevent positional-argument
    confusion with the many nullable fields.

    Parameters
    ----------
    execution_path:
        Resolved path label (``"local"`` | ``"cross_device"`` |
        ``"hybrid"`` | ``"none"``).
    delegation_point:
        Delegation boundary label (``"local"`` | ``"single_remote"`` |
        ``"multi_device_orchestration"`` | ``None``).
    trace_id:
        End-to-end correlation identifier.
    session_id:
        Session identifier.
    device_id:
        Primary target device ID (if known at plan-build time).
    remote_execution_mode:
        Wire-level execution mode (``"agent_runtime"`` | ``"command_only"``).
    required_capabilities:
        Device capability requirements propagated from the caller.
    orchestration_plan_id:
        For orchestration steps: the
        :class:`~core.orchestration.multi_device_plan.OrchestrationPlan`
        ``plan_id`` for traceability.
    timeout_ms:
        Optional timeout constraint in milliseconds.
    extra_steps:
        Additional :class:`ExecutionStep` objects to append after the
        primary step (e.g. a local step alongside a remote step in
        ``hybrid`` paths).
    plan_metadata:
        Arbitrary extra information to attach to the plan.

    Returns
    -------
    ExecutionPlan
        A fully-constructed execution plan with at least one step.
    """
    caps = list(required_capabilities or [])

    # ── Build the primary step ────────────────────────────────────────────
    primary_type = _resolve_step_type(execution_path, delegation_point, remote_execution_mode)

    target_devices: List[str] = []
    if device_id:
        target_devices = [device_id]
    if primary_type == ExecutionStepType.ORCHESTRATION and not target_devices:
        target_devices = ["*"]  # fan-out intent; concrete targets determined by scheduler

    primary_step = ExecutionStep(
        step_type=primary_type,
        target_devices=target_devices,
        remote_execution_mode=remote_execution_mode,
        required_capabilities=caps,
        timeout_ms=timeout_ms,
        orchestration_plan_id=orchestration_plan_id,
    )

    steps: List[ExecutionStep] = [primary_step]

    # ── For hybrid paths add a local step if the primary is remote ────────
    if execution_path == "hybrid" and primary_type != ExecutionStepType.LOCAL_MANIFESTATION:
        local_step = ExecutionStep(
            step_type=ExecutionStepType.LOCAL_MANIFESTATION,
            target_devices=[],
            depends_on=[],
        )
        steps.append(local_step)

    if extra_steps:
        steps.extend(extra_steps)

    _metadata = dict(plan_metadata or {})
    _metadata.setdefault("intent_layer", "planner_intent")
    _metadata.setdefault("intent_truth", "planned_not_executed")
    _metadata.setdefault("tool_invocation_truth", "not_invoked_by_plan")
    _metadata.setdefault("side_effect_execution_truth", "not_executed_by_plan")
    _metadata.setdefault("runtime_authority", "subject_decision_authority")
    _metadata.setdefault("repo_mutation_authorization_truth", "not_authorized_by_plan")

    plan = ExecutionPlan(
        trace_id=trace_id,
        session_id=session_id,
        execution_path=execution_path,
        delegation_point=delegation_point,
        steps=steps,
        metadata=_metadata,
    )

    # PR-12: stamp the initial lifecycle state on the plan and all steps.
    _stamp_plan_lifecycle(plan)

    return plan


# ---------------------------------------------------------------------------
# Builder: plan_from_orchestration_decisions
# ---------------------------------------------------------------------------


def plan_from_orchestration_decisions(
    *,
    decisions: List[Dict[str, Any]],
    task: str = "",
    trace_id: str = "",
    session_id: str = "",
    orchestration_plan_id: str = "",
) -> ExecutionPlan:
    """Build an :class:`ExecutionPlan` from a list of orchestration decisions.

    This builder is used by :class:`~core.swarm_coordinator.SwarmCoordinator`
    to represent a multi-device orchestration intent as an
    :class:`ExecutionPlan`.  Each decision becomes one
    :class:`ExecutionStep` of type :attr:`ExecutionStepType.ORCHESTRATION`.

    Parameters
    ----------
    decisions:
        List of decision dicts, each with at least:
        ``{"agent_id": str, "target_device_id": str | None,
        "resolved_execution_mode": str | None}``.
    task:
        High-level task description.
    trace_id / session_id:
        Correlation identifiers.
    orchestration_plan_id:
        The ``plan_id`` of the
        :class:`~core.orchestration.multi_device_plan.OrchestrationPlan`
        these decisions belong to.

    Returns
    -------
    ExecutionPlan
        One orchestration step per decision (or a single fan-out step
        when decisions are empty).
    """
    if not decisions:
        # No concrete decisions: represent as a single fan-out intent
        fan_out = ExecutionStep(
            step_type=ExecutionStepType.ORCHESTRATION,
            target_devices=["*"],
            orchestration_plan_id=orchestration_plan_id or None,
            metadata={"task": task},
        )
        plan = ExecutionPlan(
            trace_id=trace_id,
            session_id=session_id,
            execution_path="cross_device",
            delegation_point="multi_device_orchestration",
            steps=[fan_out],
        )
        _stamp_plan_lifecycle(plan)
        return plan

    steps: List[ExecutionStep] = []
    for dec in decisions:
        device_id = dec.get("target_device_id")
        mode = dec.get("resolved_execution_mode")
        agent_id = dec.get("agent_id", "")

        # Determine sub-type for individual member: agent_runtime vs command_only
        if mode == "command_only":
            stype = ExecutionStepType.REMOTE_COMMAND
        else:
            stype = ExecutionStepType.REMOTE_AGENT

        step = ExecutionStep(
            step_type=stype,
            target_devices=[device_id] if device_id else ["*"],
            remote_execution_mode=mode,
            orchestration_plan_id=orchestration_plan_id or None,
            metadata={"agent_id": agent_id, "task": task},
        )
        steps.append(step)

    plan = ExecutionPlan(
        trace_id=trace_id,
        session_id=session_id,
        execution_path="cross_device",
        delegation_point="multi_device_orchestration",
        steps=steps,
    )
    _stamp_plan_lifecycle(plan)
    return plan


# ---------------------------------------------------------------------------
# plan_summary
# ---------------------------------------------------------------------------


def plan_summary(plan: Optional[ExecutionPlan]) -> Dict[str, Any]:
    """Return a compact, JSON-safe summary of an :class:`ExecutionPlan`.

    Safe to call with ``None``; returns a minimal observe-path summary.

    Parameters
    ----------
    plan:
        The plan to summarise, or ``None``.

    Returns
    -------
    dict
        Keys: ``plan_id``, ``execution_path``, ``delegation_point``,
        ``step_count``, ``primary_step_type``, ``is_local_only``,
        ``is_remote``, ``is_orchestration``, ``is_observe``,
        ``trace_id``, ``session_id``.
    """
    if plan is None:
        return {
            "plan_id": None,
            "execution_path": "none",
            "delegation_point": None,
            "step_count": 0,
            "primary_step_type": ExecutionStepType.OBSERVE.value,
            "is_local_only": False,
            "is_remote": False,
            "is_orchestration": False,
            "is_observe": True,
            "trace_id": "",
            "session_id": "",
            "lifecycle_state": None,
            "intent_truth": "planned_not_executed",
            "tool_invocation_truth": "not_invoked_by_plan",
            "side_effect_execution_truth": "not_executed_by_plan",
            "repo_mutation_authorization_truth": "not_authorized_by_plan",
        }
    return {
        "plan_id": plan.plan_id,
        "execution_path": plan.execution_path,
        "delegation_point": plan.delegation_point,
        "step_count": len(plan.steps),
        "primary_step_type": plan.primary_step_type.value if plan.primary_step_type else None,
        "is_local_only": plan.is_local_only,
        "is_remote": plan.is_remote,
        "is_orchestration": plan.is_orchestration,
        "is_observe": plan.is_observe,
        "trace_id": plan.trace_id,
        "session_id": plan.session_id,
        # PR-12: include lifecycle state in summary
        "lifecycle_state": plan.lifecycle_state,
        "intent_truth": (plan.metadata or {}).get("intent_truth", "planned_not_executed"),
        "tool_invocation_truth": (plan.metadata or {}).get("tool_invocation_truth", "not_invoked_by_plan"),
        "side_effect_execution_truth": (plan.metadata or {}).get(
            "side_effect_execution_truth", "not_executed_by_plan"
        ),
        "repo_mutation_authorization_truth": (plan.metadata or {}).get(
            "repo_mutation_authorization_truth", "not_authorized_by_plan"
        ),
    }
