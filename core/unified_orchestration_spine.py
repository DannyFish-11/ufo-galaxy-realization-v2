"""core/unified_orchestration_spine.py
========================================
Unified Orchestration Spine — single canonical entry point for all execution
modes.

Problem addressed
-----------------
Prior to this module, execution modes (local, single-device remote, parallel
fan-out, cross-device, handoff/takeover, wake-routed, delegated runtime,
hybrid) each maintained their own dispatch precondition checks, readiness
gating, and completion contracts.  This created:

- ``parallel_subtask`` fan-out bypassing the unified readiness gate.
- ``wake`` / ``handoff`` / ``delegated`` each using special-cased gating that
  diverged from ordinary dispatch semantics.
- No single place to enforce the ``DISPATCH_MUST_CONSULT_UNIFIED_GATE_POLICY``
  before any task is sent.

This module closes those gaps by providing a single spine that every execution
mode MUST pass through.  The spine:

1. Accepts an :class:`OrchestrationRequest` describing the desired execution.
2. Evaluates dispatch readiness for all target devices via
   :func:`~core.unified_dispatch_readiness_gate.evaluate_dispatch_readiness`.
3. Returns an :class:`OrchestrationDecision` that callers use to proceed or
   abort dispatch.
4. Provides a consistent ``completion_contract`` that all modes share.

Design
------
- **Additive only** — does not modify any existing module.
- **Composing, not duplicating** — delegates readiness evaluation to
  :mod:`core.unified_dispatch_readiness_gate`.
- **Stateless** — no singleton; each call is independent.
- **Graceful degradation** — unavailable sub-systems produce conservative
  blocking decisions; they never produce false READY verdicts.
- **Fully serialisable** — all dataclasses expose ``to_dict()`` / ``to_json()``.

Authority sentinels
-------------------
:data:`UNIFIED_ORCHESTRATION_SPINE_AUTHORITY`
:data:`ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY`
:data:`PARALLEL_FANOUT_MUST_USE_SPINE_POLICY`
:data:`WAKE_HANDOFF_DELEGATED_MUST_USE_SPINE_POLICY`
:data:`SPINE_COMPLETION_CONTRACT_IS_UNIFIED_POLICY`

Public API
----------
Enums::

    ExecutionMode

Dataclasses::

    OrchestrationRequest
    OrchestrationDecision
    DeviceOrchestrationSlot

Functions::

    evaluate_orchestration_request(request) -> OrchestrationDecision
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.UnifiedOrchestrationSpine")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

UNIFIED_ORCHESTRATION_SPINE_AUTHORITY: str = (
    "UNIFIED_ORCHESTRATION_SPINE_AUTHORITY::"
    "core.unified_orchestration_spine is the single canonical orchestration "
    "entry point for all execution modes.  All dispatch paths — local, "
    "single-device remote, parallel fan-out, cross-device, handoff/takeover, "
    "wake-routed, delegated runtime, and hybrid — MUST pass through "
    "evaluate_orchestration_request() before any task is dispatched."
)

ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY: str = (
    "POLICY::ALL_EXECUTION_MODES_MUST_USE_SPINE: "
    "No execution mode may bypass evaluate_orchestration_request(). "
    "This includes local execution (which still requires readiness for the "
    "local target), single-device remote, parallel fan-out, cross-device, "
    "handoff/takeover, wake-routed, delegated runtime, and hybrid executions. "
    "The spine is the single gate that enforces dispatch readiness before "
    "any task payload is sent to any device."
)

PARALLEL_FANOUT_MUST_USE_SPINE_POLICY: str = (
    "POLICY::PARALLEL_FANOUT_MUST_USE_SPINE: "
    "parallel_subtask fan-out MUST route through evaluate_orchestration_request() "
    "with execution_mode=ExecutionMode.PARALLEL_FANOUT.  The spine evaluates "
    "dispatch readiness for each candidate device and returns the set of "
    "dispatch-ready slots.  Fan-out to non-ready devices is blocked at spine "
    "level, not left to per-device ad-hoc checks."
)

WAKE_HANDOFF_DELEGATED_MUST_USE_SPINE_POLICY: str = (
    "POLICY::WAKE_HANDOFF_DELEGATED_MUST_USE_SPINE: "
    "wake-routed, handoff/takeover, and delegated runtime executions MUST use "
    "the same spine and therefore the same readiness gate and completion contract "
    "as ordinary single-device or cross-device dispatch.  Special-cased gating "
    "for these modes is a policy violation."
)

SPINE_COMPLETION_CONTRACT_IS_UNIFIED_POLICY: str = (
    "POLICY::SPINE_COMPLETION_CONTRACT_IS_UNIFIED: "
    "All execution modes share the same completion contract exposed in "
    "OrchestrationDecision.completion_contract.  The contract specifies "
    "expected_result_count, partial_failure_policy, and aggregation_mode. "
    "Callers MUST use this contract to determine when to consider the "
    "orchestration complete rather than implementing mode-specific completion "
    "logic."
)

# ---------------------------------------------------------------------------
# ExecutionMode
# ---------------------------------------------------------------------------


class ExecutionMode(str, Enum):
    """Canonical execution modes supported by the orchestration spine.

    LOCAL
        Single-device local execution; no network dispatch.
    SINGLE_DEVICE_REMOTE
        Remote dispatch to exactly one device over the transport layer.
    PARALLEL_FANOUT
        Simultaneous dispatch to multiple devices (fan-out).  Replaces the
        legacy ``parallel_subtask`` direct fan-out path.
    CROSS_DEVICE
        Coordinated execution spanning multiple devices with result merging.
    HANDOFF
        Transfer of an in-flight task from one device to another.
    TAKEOVER
        A device claims ownership of a task previously held by another.
    WAKE_ROUTED
        Execution routed via a wake-event bus to a target device.
    DELEGATED_RUNTIME
        Execution delegated to an attached runtime (e.g., Android agent).
    HYBRID
        Combination of local and remote execution steps.
    """

    LOCAL = "local"
    SINGLE_DEVICE_REMOTE = "single_device_remote"
    PARALLEL_FANOUT = "parallel_fanout"
    CROSS_DEVICE = "cross_device"
    HANDOFF = "handoff"
    TAKEOVER = "takeover"
    WAKE_ROUTED = "wake_routed"
    DELEGATED_RUNTIME = "delegated_runtime"
    HYBRID = "hybrid"


# ---------------------------------------------------------------------------
# DeviceOrchestrationSlot
# ---------------------------------------------------------------------------


@dataclass
class DeviceOrchestrationSlot:
    """Readiness verdict for a single device within an orchestration request.

    Fields
    ------
    device_id
        The device evaluated.
    dispatch_ready
        True iff the device passed all readiness gates.
    readiness_status
        :class:`~core.unified_dispatch_readiness_gate.DispatchReadinessStatus`
        value string.
    readiness_reason
        Human-readable explanation from the readiness gate.
    subtask_index
        Optional index within a fan-out for ordering and tracking.
    """

    device_id: str
    dispatch_ready: bool = False
    readiness_status: str = "not_evaluated"
    readiness_reason: str = ""
    subtask_index: int = 0
    registration_gaps: List[str] = field(default_factory=list)
    attachment_state: str = "unknown"
    runtime_session_id: Optional[str] = None
    runtime_attachment_session_id: Optional[str] = None
    transport_alive: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "dispatch_ready": self.dispatch_ready,
            "readiness_status": self.readiness_status,
            "readiness_reason": self.readiness_reason,
            "subtask_index": self.subtask_index,
            "registration_gaps": list(self.registration_gaps),
            "attachment_state": self.attachment_state,
            "runtime_session_id": self.runtime_session_id,
            "runtime_attachment_session_id": self.runtime_attachment_session_id,
            "transport_alive": self.transport_alive,
        }


# ---------------------------------------------------------------------------
# OrchestrationRequest
# ---------------------------------------------------------------------------


@dataclass
class OrchestrationRequest:
    """Input to the orchestration spine.

    Fields
    ------
    execution_mode
        :class:`ExecutionMode` describing the intended execution pattern.
    target_device_ids
        List of candidate device IDs to evaluate for dispatch.  For LOCAL
        mode this is typically a single-element list with the local device.
    task_id
        Optional task identifier for correlation.
    session_id
        Optional session identifier for readiness cross-check.
    group_id
        Optional fan-out group identifier.
    required_capabilities
        Capability names the target device(s) must support.
    require_cross_device_eligible
        When True, targets are additionally checked for cross-device eligibility.
    runtime_attachment_session_id
        Optional client-supplied attachment identity for session cross-check.
    metadata
        Arbitrary extensibility bag.
    """

    execution_mode: str = ExecutionMode.SINGLE_DEVICE_REMOTE.value
    target_device_ids: List[str] = field(default_factory=list)
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    group_id: Optional[str] = None
    required_capabilities: List[str] = field(default_factory=list)
    require_cross_device_eligible: bool = False
    runtime_attachment_session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_mode": self.execution_mode,
            "target_device_ids": list(self.target_device_ids),
            "task_id": self.task_id,
            "session_id": self.session_id,
            "group_id": self.group_id,
            "required_capabilities": list(self.required_capabilities),
            "require_cross_device_eligible": self.require_cross_device_eligible,
            "runtime_attachment_session_id": self.runtime_attachment_session_id,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# CompletionContract
# ---------------------------------------------------------------------------


@dataclass
class CompletionContract:
    """Unified completion contract shared across all execution modes.

    Callers MUST use this contract to determine when an orchestration is
    complete rather than implementing mode-specific completion logic.

    Fields
    ------
    expected_result_count
        Number of device results expected before the orchestration is
        considered complete.  Equals len(ready_slots) for fan-out modes.
    partial_failure_policy
        How to handle partial device failures.  One of:
        - ``"fail_all"`` — any failure aborts the orchestration.
        - ``"best_effort"`` — collect all results; partial failure is acceptable.
        - ``"require_majority"`` — at least majority of results must succeed.
    aggregation_mode
        How to aggregate results.  One of:
        - ``"first_wins"`` — use the first result received.
        - ``"all_required"`` — wait for all results.
        - ``"any_success"`` — complete on first successful result.
    """

    expected_result_count: int = 0
    partial_failure_policy: str = "best_effort"
    aggregation_mode: str = "all_required"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expected_result_count": self.expected_result_count,
            "partial_failure_policy": self.partial_failure_policy,
            "aggregation_mode": self.aggregation_mode,
        }


# ---------------------------------------------------------------------------
# OrchestrationDecision
# ---------------------------------------------------------------------------


@dataclass
class OrchestrationDecision:
    """Output from the orchestration spine.

    Fields
    ------
    orchestration_id
        Unique identifier for this orchestration decision instance.
    execution_mode
        The execution mode from the request.
    can_proceed
        True iff at least one device is dispatch-ready and the orchestration
        can proceed.  False when all devices are blocked or the request is
        malformed.
    ready_slots
        Devices that passed all readiness gates and are eligible for dispatch.
    blocked_slots
        Devices that failed one or more readiness gates.
    completion_contract
        Unified completion contract for this orchestration.
    block_reason
        Human-readable reason when can_proceed is False.
    spine_notes
        Additional diagnostic notes from the spine evaluation.
    """

    orchestration_id: str = field(
        default_factory=lambda: f"orch_{uuid.uuid4().hex[:12]}"
    )
    execution_mode: str = ExecutionMode.SINGLE_DEVICE_REMOTE.value
    can_proceed: bool = False
    ready_slots: List[DeviceOrchestrationSlot] = field(default_factory=list)
    blocked_slots: List[DeviceOrchestrationSlot] = field(default_factory=list)
    completion_contract: CompletionContract = field(
        default_factory=CompletionContract
    )
    block_reason: str = ""
    spine_notes: List[str] = field(default_factory=list)

    @property
    def ready_device_ids(self) -> List[str]:
        return [s.device_id for s in self.ready_slots]

    @property
    def blocked_device_ids(self) -> List[str]:
        return [s.device_id for s in self.blocked_slots]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "orchestration_id": self.orchestration_id,
            "execution_mode": self.execution_mode,
            "can_proceed": self.can_proceed,
            "ready_slots": [s.to_dict() for s in self.ready_slots],
            "blocked_slots": [s.to_dict() for s in self.blocked_slots],
            "ready_device_ids": self.ready_device_ids,
            "blocked_device_ids": self.blocked_device_ids,
            "completion_contract": self.completion_contract.to_dict(),
            "block_reason": self.block_reason,
            "spine_notes": list(self.spine_notes),
            "authority": UNIFIED_ORCHESTRATION_SPINE_AUTHORITY,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def evaluate_orchestration_request(
    request: OrchestrationRequest,
) -> OrchestrationDecision:
    """Evaluate an orchestration request through the unified spine.

    This is the **single canonical entry point** for all execution modes.
    Every dispatch path MUST call this before sending any task payload.

    The function:
    1. Validates the request.
    2. Evaluates dispatch readiness for each candidate device via
       :func:`~core.unified_dispatch_readiness_gate.evaluate_dispatch_readiness`.
    3. Partitions devices into ready_slots and blocked_slots.
    4. Derives a :class:`CompletionContract` appropriate for the mode.
    5. Returns an :class:`OrchestrationDecision`.

    Parameters
    ----------
    request
        :class:`OrchestrationRequest` describing the desired execution.

    Returns
    -------
    OrchestrationDecision
        Always returns a valid decision; never raises.
    """
    try:
        return _evaluate_impl(request)
    except Exception as exc:
        logger.warning(
            "UnifiedOrchestrationSpine: evaluation error for mode=%r: %s",
            request.execution_mode,
            exc,
            exc_info=True,
        )
        return OrchestrationDecision(
            execution_mode=request.execution_mode,
            can_proceed=False,
            block_reason=f"spine_internal_error: {exc}",
            spine_notes=[str(exc)],
        )


def _evaluate_impl(request: OrchestrationRequest) -> OrchestrationDecision:
    """Internal spine evaluation."""
    from core.unified_dispatch_readiness_gate import evaluate_dispatch_readiness

    spine_notes: List[str] = []
    mode = request.execution_mode

    # ----------------------------------------------------------------
    # Validate request
    # ----------------------------------------------------------------
    if not request.target_device_ids:
        return OrchestrationDecision(
            execution_mode=mode,
            can_proceed=False,
            block_reason="No target devices specified in orchestration request.",
            spine_notes=[
                "target_device_ids is empty — cannot proceed without at "
                "least one candidate device"
            ],
        )

    # ----------------------------------------------------------------
    # Evaluate readiness per device
    # ----------------------------------------------------------------
    ready_slots: List[DeviceOrchestrationSlot] = []
    blocked_slots: List[DeviceOrchestrationSlot] = []

    require_cd = request.require_cross_device_eligible or mode in (
        ExecutionMode.CROSS_DEVICE.value,
        ExecutionMode.HANDOFF.value,
        ExecutionMode.TAKEOVER.value,
        ExecutionMode.WAKE_ROUTED.value,
    )

    for idx, device_id in enumerate(request.target_device_ids):
        readiness = evaluate_dispatch_readiness(
            device_id,
            required_capabilities=request.required_capabilities,
            require_cross_device_eligible=require_cd,
            session_id=request.session_id,
            runtime_attachment_session_id=request.runtime_attachment_session_id,
            execution_mode=mode,
        )

        slot = DeviceOrchestrationSlot(
            device_id=device_id,
            dispatch_ready=readiness.dispatch_ready,
            readiness_status=readiness.status,
            readiness_reason=readiness.reason,
            subtask_index=idx,
            registration_gaps=readiness.registration_gaps,
            attachment_state=readiness.attachment_state,
            runtime_session_id=readiness.runtime_session_id,
            runtime_attachment_session_id=readiness.runtime_attachment_session_id,
            transport_alive=readiness.transport_alive,
        )

        if readiness.dispatch_ready:
            ready_slots.append(slot)
        else:
            blocked_slots.append(slot)
            spine_notes.append(
                f"device_id={device_id!r} blocked: "
                f"status={readiness.status!r} reason={readiness.reason!r}"
            )

    # ----------------------------------------------------------------
    # Derive completion contract
    # ----------------------------------------------------------------
    completion_contract = _derive_completion_contract(mode, ready_slots)

    # ----------------------------------------------------------------
    # Determine can_proceed
    # ----------------------------------------------------------------
    can_proceed = len(ready_slots) > 0
    block_reason = ""
    if not can_proceed:
        block_reason = (
            f"All {len(request.target_device_ids)} candidate device(s) failed "
            f"dispatch readiness gate for mode={mode!r}."
        )
        if blocked_slots:
            first_blocked = blocked_slots[0]
            block_reason += (
                f" First blocked device={first_blocked.device_id!r}: "
                f"{first_blocked.readiness_reason!r}"
            )

    if blocked_slots:
        spine_notes.append(
            f"{len(blocked_slots)} device(s) blocked by readiness gate; "
            f"{len(ready_slots)} device(s) ready."
        )

    return OrchestrationDecision(
        execution_mode=mode,
        can_proceed=can_proceed,
        ready_slots=ready_slots,
        blocked_slots=blocked_slots,
        completion_contract=completion_contract,
        block_reason=block_reason,
        spine_notes=spine_notes,
    )


def _derive_completion_contract(
    mode: str, ready_slots: List[DeviceOrchestrationSlot]
) -> CompletionContract:
    """Derive the appropriate completion contract for the given mode."""
    count = len(ready_slots)

    if mode in (
        ExecutionMode.LOCAL.value,
        ExecutionMode.SINGLE_DEVICE_REMOTE.value,
        ExecutionMode.DELEGATED_RUNTIME.value,
    ):
        return CompletionContract(
            expected_result_count=count,
            partial_failure_policy="fail_all",
            aggregation_mode="first_wins",
        )

    if mode in (
        ExecutionMode.PARALLEL_FANOUT.value,
        ExecutionMode.CROSS_DEVICE.value,
        ExecutionMode.HYBRID.value,
    ):
        return CompletionContract(
            expected_result_count=count,
            partial_failure_policy="best_effort",
            aggregation_mode="all_required",
        )

    if mode in (
        ExecutionMode.HANDOFF.value,
        ExecutionMode.TAKEOVER.value,
    ):
        return CompletionContract(
            expected_result_count=min(count, 1),
            partial_failure_policy="fail_all",
            aggregation_mode="first_wins",
        )

    if mode == ExecutionMode.WAKE_ROUTED.value:
        return CompletionContract(
            expected_result_count=min(count, 1),
            partial_failure_policy="fail_all",
            aggregation_mode="any_success",
        )

    # Default contract
    return CompletionContract(
        expected_result_count=count,
        partial_failure_policy="best_effort",
        aggregation_mode="all_required",
    )


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    "UNIFIED_ORCHESTRATION_SPINE_AUTHORITY",
    "ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY",
    "PARALLEL_FANOUT_MUST_USE_SPINE_POLICY",
    "WAKE_HANDOFF_DELEGATED_MUST_USE_SPINE_POLICY",
    "SPINE_COMPLETION_CONTRACT_IS_UNIFIED_POLICY",
    "ExecutionMode",
    "DeviceOrchestrationSlot",
    "OrchestrationRequest",
    "OrchestrationDecision",
    "CompletionContract",
    "evaluate_orchestration_request",
]
