"""contracts/execution_target_policy.py
========================================
Execution Target Selection and Failure Handling Policy Contracts — PR-I.

This module defines the **canonical policy contracts** for policy-driven
target selection and failure handling in multi-device runtime execution.
It answers the architectural question:

    *"How does the runtime make explicit, inspectable, and evolvable
    decisions about which execution target to choose and how to respond
    to failures, degraded readiness, and temporary unavailability —
    without embedding those heuristics in core routing code?"*

As the runtime dispatch chain has grown across prior PRs:

- **PR-A** — device lifecycle integration
- **PR-B** — mesh session lifecycle
- **PR-D** — source dispatch orchestrator production wiring
- **PR-E** — explicit executor target typing
- **PR-F** — continuity/recovery context
- **PR-G** — runtime observability
- **PR-H** — contract validation and compatibility

… target selection and failure handling have remained largely implicit:
target choice delegated to first-active heuristics in
``_select_target_from_candidates`` and failure response scattered across
ad-hoc fallback logic in routing paths.

This module introduces a **policy layer** that captures these decisions as
explicit, inspectable, and serialisable contract objects.

This module provides:

- Sentinel constants affirming the policy authority (see below).
- :class:`TargetSelectionPolicyKind` — enum of policy strategies for
  selecting among android_device, node_service, go_worker, and local
  execution targets.
- :class:`FailureHandlingPolicyKind` — enum of policy responses to
  degraded readiness, temporary unavailability, and recoverable
  interruption.
- :class:`DegradedReadinessPolicyKind` — enum of responses to degraded
  but not fully unavailable executor readiness.
- :class:`TargetSelectionDecision` — structured, serialisable record of
  which target was selected and why.
- :class:`FailureHandlingDecision` — structured, serialisable record of
  which failure response was chosen and why.
- Builder functions for all decision types.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fully serialisable** — all contracts produce stable, round-trippable
  JSON via ``to_dict`` / ``to_json``.
- **Graceful defaults** — all fields beyond required identity fields are
  optional; callers with partial context always produce a valid decision.
- **Backward compatible** — absent inputs always produce a safe conservative
  policy decision; no existing execution path is altered.
- **Explicit and inspectable** — every decision carries a
  ``decision_reason`` string that explains the choice without requiring
  source-code inspection.

Sentinels
---------
:data:`EXECUTION_TARGET_POLICY_IS_AUTHORITY`
    Affirms this module is the canonical execution target policy contracts
    authority for PR-I.
:data:`TARGET_SELECTION_IS_POLICY_DRIVEN_POLICY`
    Affirms that executor target selection MUST be driven by an explicit
    policy decision rather than implicit routing heuristics.
:data:`FAILURE_HANDLING_IS_EXPLICIT_POLICY`
    Affirms that failure and degraded-state responses MUST be represented
    as explicit policy decisions, not only implicit routing fallback logic.
:data:`POLICY_SEPARATION_FROM_ROUTING_MECHANICS_POLICY`
    Affirms that selection policy and failure policy MUST be represented
    separately from core routing mechanics so that both can evolve
    independently.
:data:`BACKWARD_COMPAT_DURING_POLICY_MIGRATION_POLICY`
    Affirms that existing execution paths remain functional while the
    policy layer is adopted; policy decisions are additive, not replacing
    existing path selection.

Usage::

    from contracts.execution_target_policy import (
        TargetSelectionPolicyKind,
        FailureHandlingPolicyKind,
        DegradedReadinessPolicyKind,
        TargetSelectionDecision,
        FailureHandlingDecision,
        build_target_selection_decision,
        build_failure_handling_decision,
    )

    # Select an explicit executor target
    decision = build_target_selection_decision(
        policy_kind=TargetSelectionPolicyKind.explicit_executor_type,
        selected_executor_type="android_device",
        selected_device_id="dev_abc",
        decision_reason="executor_target_type=android_device from TaskEnvelope",
    )

    # Handle a degraded-readiness failure
    failure_decision = build_failure_handling_decision(
        policy_kind=FailureHandlingPolicyKind.fallback_local,
        failure_kind="readiness_degraded",
        decision_reason="target device readiness=degraded; fallback to local",
        is_recoverable=True,
    )
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

EXECUTION_TARGET_POLICY_IS_AUTHORITY: str = (
    "EXECUTION_TARGET_POLICY_IS_AUTHORITY: "
    "contracts/execution_target_policy.py is the canonical policy contracts "
    "authority for PR-I.  It defines TargetSelectionDecision and "
    "FailureHandlingDecision as the explicit, inspectable, and serialisable "
    "representations of runtime target selection and failure response policy.  "
    "All production target selection and failure handling that introduces a "
    "new policy decision point MUST produce one of these contracts.  PR-I."
)

TARGET_SELECTION_IS_POLICY_DRIVEN_POLICY: str = (
    "POLICY::TARGET_SELECTION_IS_POLICY_DRIVEN_PR-I: "
    "Executor target selection among android_device, node_service, go_worker, "
    "and local MUST be driven by an explicit TargetSelectionDecision produced by "
    "the policy engine rather than by implicit first-active heuristics embedded in "
    "core routing code.  Each decision MUST carry a policy_kind and a non-empty "
    "decision_reason so that the selection rationale is inspectable without reading "
    "source code.  Backward compatibility with existing execution paths is "
    "preserved: when no policy engine is consulted, the existing heuristics "
    "continue to operate and are not broken.  PR-I."
)

FAILURE_HANDLING_IS_EXPLICIT_POLICY: str = (
    "POLICY::FAILURE_HANDLING_IS_EXPLICIT_PR-I: "
    "Failure and degraded-state responses (retry, fallback_local, reject, "
    "escalate) MUST be represented as explicit FailureHandlingDecision records "
    "rather than only implicit routing fallback logic.  Every failure policy "
    "decision MUST identify the failure_kind, the chosen FailureHandlingPolicyKind, "
    "whether the failure is recoverable, and a human-readable decision_reason.  "
    "This makes failure handling observable and testable without runtime inspection.  "
    "PR-I."
)

POLICY_SEPARATION_FROM_ROUTING_MECHANICS_POLICY: str = (
    "POLICY::POLICY_SEPARATION_FROM_ROUTING_MECHANICS_PR-I: "
    "Target selection policy (TargetSelectionDecision) and failure handling policy "
    "(FailureHandlingDecision) MUST be separable from core routing mechanics so "
    "that each can evolve independently.  The routing layer consults the policy "
    "layer at defined decision points; it does not embed selection or failure "
    "logic inline.  This separation is enforced by requiring that all policy "
    "decisions pass through the policy engine functions rather than being "
    "expressed as scattered conditionals in routing methods.  PR-I."
)

BACKWARD_COMPAT_DURING_POLICY_MIGRATION_POLICY: str = (
    "POLICY::BACKWARD_COMPAT_DURING_POLICY_MIGRATION_PR-I: "
    "During the migration to explicit policy-driven target selection and failure "
    "handling, existing execution paths MUST remain functional.  Policy decision "
    "points are additive: when a policy decision is not yet present for a given "
    "routing path, the existing implicit heuristics continue to apply.  No existing "
    "path is removed or broken by the introduction of the policy layer.  PR-I."
)

EXECUTION_TARGET_POLICY_PR_I_SENTINEL: str = (
    "EXECUTION_TARGET_POLICY_PR_I_SENTINEL: "
    "PR-I policy-driven target selection and failure handling contracts are present "
    "and active.  TargetSelectionDecision and FailureHandlingDecision records can "
    "be produced for any executor target selection or failure response in the "
    "multi-device runtime."
)


# ---------------------------------------------------------------------------
# TargetSelectionPolicyKind
# ---------------------------------------------------------------------------


class TargetSelectionPolicyKind(str, Enum):
    """Policy strategy for selecting the executor target.

    Values are lowercase strings safe for serialisation and policy analysis.
    """

    explicit_executor_type = "explicit_executor_type"
    """Selection driven by an explicit ``executor_target_type`` field in the
    ``TaskEnvelope``.  The policy defers directly to the declared type rather
    than applying any heuristics."""

    readiness_weighted = "readiness_weighted"
    """Selection driven by candidate readiness scores.  Candidates are ranked
    by readiness (ready > degraded > recovering) and the highest-readiness
    eligible candidate is chosen."""

    mesh_topology = "mesh_topology"
    """Selection driven by current mesh session topology.  The policy favours
    candidates that are active mesh participants with appropriate roles."""

    capability_match = "capability_match"
    """Selection driven by capability matching against task requirements.
    Candidates that declare the required capability are preferred."""

    fallback_local = "fallback_local"
    """No suitable remote target found; fall back to local execution.  This
    policy kind signals that local execution is the result of exhausting all
    remote options, not of a deliberate local preference."""

    default_local = "default_local"
    """Local execution is the deliberate policy choice (not a fallback).  The
    task domain, execution policy, or task envelope explicitly prefer local
    execution."""


# ---------------------------------------------------------------------------
# FailureHandlingPolicyKind
# ---------------------------------------------------------------------------


class FailureHandlingPolicyKind(str, Enum):
    """Policy response to a failure, temporary unavailability, or degraded state.

    Values are lowercase strings safe for serialisation and policy analysis.
    """

    retry = "retry"
    """Retry the dispatch attempt, optionally with a delay or on a different
    candidate target.  Applicable to transient failures (device briefly
    unreachable, transport error)."""

    fallback_local = "fallback_local"
    """Fall back to local execution after remote failure.  The original remote
    attempt is recorded as failed; local execution proceeds as the recovery
    path."""

    reject_with_reason = "reject_with_reason"
    """Reject the task with a structured reason.  No retry or fallback is
    attempted.  Applicable when the failure is non-recoverable or policy
    explicitly prohibits fallback."""

    escalate_to_operator = "escalate_to_operator"
    """Escalate to the operator surface for human decision.  Used for
    ambiguous failure states where automated recovery would be risky."""

    wait_and_requeue = "wait_and_requeue"
    """Wait for the target to become available again and requeue the task.
    Applicable to temporary unavailability with expected recovery horizon."""


# ---------------------------------------------------------------------------
# DegradedReadinessPolicyKind
# ---------------------------------------------------------------------------


class DegradedReadinessPolicyKind(str, Enum):
    """Policy response to a target that is in degraded (not fully unavailable)
    readiness state.

    Values are lowercase strings safe for serialisation and policy analysis.
    """

    accept_degraded = "accept_degraded"
    """Accept the degraded target and proceed with dispatch.  The dispatch
    decision records the degraded state for observability, but does not block
    execution."""

    fallback_local = "fallback_local"
    """Treat degraded readiness as a disqualifying condition and fall back to
    local execution."""

    wait_for_recovery = "wait_for_recovery"
    """Hold the task pending recovery of the degraded target.  Requeue once
    readiness improves above the threshold."""

    reject_degraded = "reject_degraded"
    """Reject the task because the only available target is in degraded state
    and policy requires fully-ready targets."""

    escalate = "escalate"
    """Escalate the degraded-readiness condition to the operator surface."""


# ---------------------------------------------------------------------------
# TargetSelectionDecision
# ---------------------------------------------------------------------------


@dataclass
class TargetSelectionDecision:
    """Structured, serialisable record of an executor target selection decision.

    Produced by the policy engine when it determines which execution target
    to choose for a given task and dispatch context.

    Attributes
    ----------
    decision_id:
        Auto-generated UUID4 for this decision record.
    timestamp:
        Unix timestamp when the decision was made.
    policy_kind:
        :class:`TargetSelectionPolicyKind` strategy applied.
    selected_executor_type:
        The chosen executor target type (``"android_device"``,
        ``"node_service"``, ``"go_worker"``, ``"local"``, or ``None`` if
        no target was selected).
    selected_device_id:
        The device identifier of the selected target, if applicable.
    selected_session_id:
        The session identifier associated with the selected target, if any.
    decision_reason:
        Human-readable explanation of why this target was chosen.
    candidates_considered:
        List of candidate executor types or device IDs that were evaluated
        but not selected.  Useful for observability and debugging.
    trace_id:
        Correlation trace ID for the originating request.
    task_id:
        Task identifier for the task being dispatched.
    mesh_session_id:
        Active mesh session identifier, if relevant to this selection.
    readiness:
        Readiness state of the selected target (``"ready"``, ``"degraded"``,
        ``"recovering"``, ``"unknown"``).
    metadata:
        Arbitrary key-value extensibility bag.
    """

    decision_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    policy_kind: str = TargetSelectionPolicyKind.default_local.value
    selected_executor_type: Optional[str] = None
    selected_device_id: Optional[str] = None
    selected_session_id: Optional[str] = None
    decision_reason: str = ""
    candidates_considered: List[str] = field(default_factory=list)
    trace_id: Optional[str] = None
    task_id: Optional[str] = None
    mesh_session_id: Optional[str] = None
    readiness: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "decision_id": self.decision_id,
            "timestamp": self.timestamp,
            "policy_kind": self.policy_kind,
            "selected_executor_type": self.selected_executor_type,
            "selected_device_id": self.selected_device_id,
            "selected_session_id": self.selected_session_id,
            "decision_reason": self.decision_reason,
            "candidates_considered": list(self.candidates_considered),
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "mesh_session_id": self.mesh_session_id,
            "readiness": self.readiness,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TargetSelectionDecision":
        """Reconstruct a :class:`TargetSelectionDecision` from a dict.

        Unknown or missing fields are silently ignored / defaulted.
        """
        try:
            policy_kind = TargetSelectionPolicyKind(
                data.get("policy_kind", TargetSelectionPolicyKind.default_local.value)
            ).value
        except (ValueError, KeyError):
            policy_kind = TargetSelectionPolicyKind.default_local.value

        return cls(
            decision_id=data.get("decision_id") or uuid.uuid4().hex,
            timestamp=float(data.get("timestamp") or time.time()),
            policy_kind=policy_kind,
            selected_executor_type=data.get("selected_executor_type"),
            selected_device_id=data.get("selected_device_id"),
            selected_session_id=data.get("selected_session_id"),
            decision_reason=str(data.get("decision_reason") or ""),
            candidates_considered=list(data.get("candidates_considered") or []),
            trace_id=data.get("trace_id"),
            task_id=data.get("task_id"),
            mesh_session_id=data.get("mesh_session_id"),
            readiness=data.get("readiness"),
            metadata=dict(data.get("metadata") or {}),
        )


# ---------------------------------------------------------------------------
# FailureHandlingDecision
# ---------------------------------------------------------------------------


@dataclass
class FailureHandlingDecision:
    """Structured, serialisable record of a failure handling policy decision.

    Produced by the policy engine when it determines how to respond to a
    dispatch failure, degraded readiness, or temporary target unavailability.

    Attributes
    ----------
    decision_id:
        Auto-generated UUID4 for this decision record.
    timestamp:
        Unix timestamp when the decision was made.
    policy_kind:
        :class:`FailureHandlingPolicyKind` strategy chosen.
    failure_kind:
        The kind of failure or degradation that triggered this decision
        (e.g. ``"readiness_degraded"``, ``"target_unavailable"``,
        ``"transport_error"``, ``"capability_mismatch"``).
    is_recoverable:
        ``True`` if the failure is expected to be recoverable (e.g. transient
        network error, device reconnecting).  ``False`` for terminal or
        capability-structural failures.
    recommended_action:
        Short string recommending what the caller should do next
        (e.g. ``"retry_after_delay"``, ``"proceed_local"``,
        ``"reject_task"``, ``"wait_and_requeue"``).
    decision_reason:
        Human-readable explanation of why this failure handling policy was
        chosen.
    degraded_readiness_policy:
        :class:`DegradedReadinessPolicyKind` applied when the failure
        involves a degraded (not fully unavailable) target.  ``None`` if
        not applicable.
    prior_executor_type:
        The executor target type that failed, if known.
    prior_device_id:
        The device ID of the target that failed, if known.
    trace_id:
        Correlation trace ID for the originating request.
    task_id:
        Task identifier for the task that triggered the failure.
    errors:
        List of structured error descriptions from the failed attempt.
    metadata:
        Arbitrary key-value extensibility bag.
    """

    decision_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    policy_kind: str = FailureHandlingPolicyKind.reject_with_reason.value
    failure_kind: str = "unknown"
    is_recoverable: bool = False
    recommended_action: str = "reject_task"
    decision_reason: str = ""
    degraded_readiness_policy: Optional[str] = None
    prior_executor_type: Optional[str] = None
    prior_device_id: Optional[str] = None
    trace_id: Optional[str] = None
    task_id: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "decision_id": self.decision_id,
            "timestamp": self.timestamp,
            "policy_kind": self.policy_kind,
            "failure_kind": self.failure_kind,
            "is_recoverable": self.is_recoverable,
            "recommended_action": self.recommended_action,
            "decision_reason": self.decision_reason,
            "degraded_readiness_policy": self.degraded_readiness_policy,
            "prior_executor_type": self.prior_executor_type,
            "prior_device_id": self.prior_device_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "errors": list(self.errors),
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FailureHandlingDecision":
        """Reconstruct a :class:`FailureHandlingDecision` from a dict.

        Unknown or missing fields are silently ignored / defaulted.
        """
        try:
            policy_kind = FailureHandlingPolicyKind(
                data.get("policy_kind", FailureHandlingPolicyKind.reject_with_reason.value)
            ).value
        except (ValueError, KeyError):
            policy_kind = FailureHandlingPolicyKind.reject_with_reason.value

        degraded_readiness_policy = data.get("degraded_readiness_policy")
        if degraded_readiness_policy is not None:
            try:
                degraded_readiness_policy = DegradedReadinessPolicyKind(
                    degraded_readiness_policy
                ).value
            except (ValueError, KeyError):
                degraded_readiness_policy = None

        return cls(
            decision_id=data.get("decision_id") or uuid.uuid4().hex,
            timestamp=float(data.get("timestamp") or time.time()),
            policy_kind=policy_kind,
            failure_kind=str(data.get("failure_kind") or "unknown"),
            is_recoverable=bool(data.get("is_recoverable", False)),
            recommended_action=str(data.get("recommended_action") or "reject_task"),
            decision_reason=str(data.get("decision_reason") or ""),
            degraded_readiness_policy=degraded_readiness_policy,
            prior_executor_type=data.get("prior_executor_type"),
            prior_device_id=data.get("prior_device_id"),
            trace_id=data.get("trace_id"),
            task_id=data.get("task_id"),
            errors=list(data.get("errors") or []),
            metadata=dict(data.get("metadata") or {}),
        )


# ---------------------------------------------------------------------------
# Builder functions
# ---------------------------------------------------------------------------


def build_target_selection_decision(
    *,
    policy_kind: TargetSelectionPolicyKind = TargetSelectionPolicyKind.default_local,
    selected_executor_type: Optional[str] = None,
    selected_device_id: Optional[str] = None,
    selected_session_id: Optional[str] = None,
    decision_reason: str = "",
    candidates_considered: Optional[List[str]] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    mesh_session_id: Optional[str] = None,
    readiness: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> TargetSelectionDecision:
    """Build a :class:`TargetSelectionDecision` from available context signals.

    All parameters are optional.  The builder always produces a valid decision
    and never raises.

    Parameters
    ----------
    policy_kind:
        The :class:`TargetSelectionPolicyKind` strategy being applied.
    selected_executor_type:
        The chosen executor target type string.
    selected_device_id:
        Device identifier of the selected target.
    selected_session_id:
        Session identifier associated with the selected target.
    decision_reason:
        Human-readable explanation of the selection choice.
    candidates_considered:
        List of candidate types or device IDs that were evaluated.
    trace_id:
        Correlation trace ID.
    task_id:
        Task identifier.
    mesh_session_id:
        Active mesh session identifier, if relevant.
    readiness:
        Readiness state of the selected target.
    metadata:
        Extra metadata key-value pairs.

    Returns
    -------
    TargetSelectionDecision
        The populated decision record.
    """
    try:
        policy_kind_val = (
            policy_kind.value
            if isinstance(policy_kind, TargetSelectionPolicyKind)
            else str(policy_kind)
        )
        return TargetSelectionDecision(
            policy_kind=policy_kind_val,
            selected_executor_type=selected_executor_type,
            selected_device_id=selected_device_id,
            selected_session_id=selected_session_id,
            decision_reason=decision_reason or "",
            candidates_considered=list(candidates_considered or []),
            trace_id=trace_id,
            task_id=task_id,
            mesh_session_id=mesh_session_id,
            readiness=readiness,
            metadata=dict(metadata or {}),
        )
    except Exception:  # noqa: BLE001
        return TargetSelectionDecision(
            decision_reason="build_target_selection_decision: error building decision"
        )


def build_failure_handling_decision(
    *,
    policy_kind: FailureHandlingPolicyKind = FailureHandlingPolicyKind.reject_with_reason,
    failure_kind: str = "unknown",
    is_recoverable: bool = False,
    recommended_action: str = "",
    decision_reason: str = "",
    degraded_readiness_policy: Optional[DegradedReadinessPolicyKind] = None,
    prior_executor_type: Optional[str] = None,
    prior_device_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    errors: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> FailureHandlingDecision:
    """Build a :class:`FailureHandlingDecision` from available failure context.

    All parameters are optional.  The builder always produces a valid decision
    and never raises.

    Parameters
    ----------
    policy_kind:
        The :class:`FailureHandlingPolicyKind` strategy chosen.
    failure_kind:
        String describing the kind of failure or degradation.
    is_recoverable:
        Whether the failure is expected to be recoverable.
    recommended_action:
        Short string recommending the next action for the caller.
    decision_reason:
        Human-readable explanation of the policy choice.
    degraded_readiness_policy:
        :class:`DegradedReadinessPolicyKind` when applicable.
    prior_executor_type:
        The executor type that failed.
    prior_device_id:
        The device ID that failed.
    trace_id:
        Correlation trace ID.
    task_id:
        Task identifier.
    errors:
        Structured error descriptions from the failed attempt.
    metadata:
        Extra metadata key-value pairs.

    Returns
    -------
    FailureHandlingDecision
        The populated decision record.
    """
    try:
        policy_kind_val = (
            policy_kind.value
            if isinstance(policy_kind, FailureHandlingPolicyKind)
            else str(policy_kind)
        )
        degraded_val = (
            degraded_readiness_policy.value
            if isinstance(degraded_readiness_policy, DegradedReadinessPolicyKind)
            else (str(degraded_readiness_policy) if degraded_readiness_policy else None)
        )
        # Derive recommended_action from policy_kind when not explicitly provided
        if not recommended_action:
            _action_map = {
                FailureHandlingPolicyKind.retry.value: "retry_after_delay",
                FailureHandlingPolicyKind.fallback_local.value: "proceed_local",
                FailureHandlingPolicyKind.reject_with_reason.value: "reject_task",
                FailureHandlingPolicyKind.escalate_to_operator.value: "escalate",
                FailureHandlingPolicyKind.wait_and_requeue.value: "wait_and_requeue",
            }
            recommended_action = _action_map.get(policy_kind_val, "reject_task")

        return FailureHandlingDecision(
            policy_kind=policy_kind_val,
            failure_kind=failure_kind or "unknown",
            is_recoverable=bool(is_recoverable),
            recommended_action=recommended_action,
            decision_reason=decision_reason or "",
            degraded_readiness_policy=degraded_val,
            prior_executor_type=prior_executor_type,
            prior_device_id=prior_device_id,
            trace_id=trace_id,
            task_id=task_id,
            errors=list(errors or []),
            metadata=dict(metadata or {}),
        )
    except Exception:  # noqa: BLE001
        return FailureHandlingDecision(
            decision_reason="build_failure_handling_decision: error building decision"
        )


__all__ = [
    # Sentinels
    "EXECUTION_TARGET_POLICY_IS_AUTHORITY",
    "TARGET_SELECTION_IS_POLICY_DRIVEN_POLICY",
    "FAILURE_HANDLING_IS_EXPLICIT_POLICY",
    "POLICY_SEPARATION_FROM_ROUTING_MECHANICS_POLICY",
    "BACKWARD_COMPAT_DURING_POLICY_MIGRATION_POLICY",
    "EXECUTION_TARGET_POLICY_PR_I_SENTINEL",
    # Enums
    "TargetSelectionPolicyKind",
    "FailureHandlingPolicyKind",
    "DegradedReadinessPolicyKind",
    # Dataclasses
    "TargetSelectionDecision",
    "FailureHandlingDecision",
    # Builders
    "build_target_selection_decision",
    "build_failure_handling_decision",
]
