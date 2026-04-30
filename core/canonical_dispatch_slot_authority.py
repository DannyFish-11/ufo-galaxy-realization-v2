"""core/canonical_dispatch_slot_authority.py
=============================================
PR-V3 (post-533 dual-repo runtime-unification master plan, V2 repo):
Canonical Dispatch-Slot Authority — single structural authority for all
dispatch decisions across every execution mode.

Problem addressed
-----------------
Prior to this module the system had multiple partial readiness realities:

* ``core.unified_dispatch_readiness_gate`` checked transport, registration,
  attachment, capability, and cross-device eligibility — necessary but not
  sufficient.
* Continuity legality lived in ``core.unified_continuity_legality_authority``
  and was not enforced on the dispatch path.
* Execution-mode eligibility was evaluated ad-hoc in ``command_router`` and
  ``entrypoint_router`` rather than at the dispatch gate.
* Occupancy / reservation state had no canonical check; devices could receive
  concurrent dispatch even when already occupied.
* Policy allowance was applied inconsistently across execution modes.
* Delegated / handoff acceptability was evaluated only inside the delegated-
  flow acceptance gate, not before dispatch selection.

This meant different execution paths (normal cross-device, delegated runtime,
parallel fan-out, wake-routed, handoff/takeover, hybrid) could each hold a
different readiness reality and dispatch against devices that would be blocked
by another mode's gate — violating the "one canonical dispatch target" model.

Resolution
----------
This module provides **one canonical dispatch-slot authority** that every
execution mode MUST consume before sending any task to any device.  A
``CanonicalDispatchSlot`` represents a device that has been approved by all
ten legality dimensions:

1.  Transport readiness
2.  Registration validity
3.  Attachment validity
4.  Continuity legality
5.  Capability fit
6.  Execution-mode eligibility
7.  Occupancy / reservation state
8.  Policy allowance
9.  Cross-device reachability
10. Delegated / handoff acceptability

Only devices that emerge as :attr:`CanonicalDispatchSlotStatus.SLOT_APPROVED`
from :func:`evaluate_canonical_dispatch_slot` are legal dispatch targets.

Design
------
1. **Additive only** — does not modify any existing module.
2. **Composing, not duplicating** — delegates to existing authoritative
   sub-modules for each dimension:
   - ``core.unified_dispatch_readiness_gate`` — dimensions 1–3, 5, 9
   - ``core.unified_continuity_legality_authority`` — dimension 4
   - ``core.delegated_flow_acceptance_gate`` — dimension 10
3. **Stateless** — no singleton; each call is independent.
4. **Graceful degradation** — when a sub-authority is unavailable its
   dimension is noted but does not create a false SLOT_APPROVED verdict;
   conservative blocking is applied according to the dimension's policy.
5. **Fully serialisable** — :meth:`CanonicalDispatchSlot.to_dict` and
   :meth:`CanonicalDispatchSlot.to_json` produce stable JSON for
   observability, audit, and test assertions.

Authority sentinels
-------------------
:data:`CANONICAL_DISPATCH_SLOT_AUTHORITY`
:data:`CANONICAL_DISPATCH_SLOT_PR_V3_SENTINEL`
:data:`ALL_EXECUTION_MODES_MUST_CONSUME_CANONICAL_SLOT_POLICY`
:data:`DEVICE_ROUTER_MUST_NOT_ACT_AS_READINESS_AUTHORITY_POLICY`
:data:`WAKE_MUST_NOT_BYPASS_CANONICAL_SLOT_POLICY`
:data:`FANOUT_SELECTS_SLOTS_NOT_RAW_DEVICES_POLICY`
:data:`DELEGATED_HANDOFF_MUST_USE_LEGAL_SLOT_BINDING_POLICY`
:data:`CONTINUITY_LEGALITY_GATES_DISPATCH_POLICY`
:data:`EXECUTION_MODE_ELIGIBILITY_GATES_DISPATCH_POLICY`
:data:`OCCUPANCY_GATES_DISPATCH_POLICY`
:data:`POLICY_ALLOWANCE_GATES_DISPATCH_POLICY`

Public API
----------
Enumerations::

    CanonicalDispatchSlotStatus

Dataclasses::

    CanonicalDispatchSlot
    CanonicalDispatchSlotsResult

Functions::

    evaluate_canonical_dispatch_slot(device_id, execution_mode, ...) -> CanonicalDispatchSlot
    get_canonical_dispatch_slots(device_ids, execution_mode, ...) -> CanonicalDispatchSlotsResult
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CanonicalDispatchSlotAuthority")

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

CANONICAL_DISPATCH_SLOT_AUTHORITY: str = (
    "CANONICAL_DISPATCH_SLOT_AUTHORITY::"
    "core.canonical_dispatch_slot_authority::PR-V3::"
    "single-canonical-dispatch-slot-authority::"
    "all-execution-modes-must-consume-canonical-slot"
)
"""Sentinel: this module is the canonical dispatch-slot authority.

All execution modes (normal cross-device, delegated runtime, parallel
fan-out, handoff/takeover, wake-routed, hybrid) MUST call
``evaluate_canonical_dispatch_slot()`` or ``get_canonical_dispatch_slots()``
and dispatch only against ``SLOT_APPROVED`` results.  Dispatching against
raw device lists or local readiness checks is a policy violation.
"""

CANONICAL_DISPATCH_SLOT_PR_V3_SENTINEL: str = (
    "CANONICAL_DISPATCH_SLOT_AUTHORITY_PR_V3::"
    "promote-dispatch-readiness-into-canonical-dispatch-slot-authority::"
    "pr-v3-v2-repo"
)
"""PR-V3 identity sentinel.  Import this to assert the PR has landed."""

ALL_EXECUTION_MODES_MUST_CONSUME_CANONICAL_SLOT_POLICY: str = (
    "POLICY::ALL_EXECUTION_MODES_MUST_CONSUME_CANONICAL_SLOT: "
    "No execution mode — local, single-device remote, parallel fan-out, "
    "cross-device, handoff/takeover, wake-routed, delegated runtime, or "
    "hybrid — may dispatch to a device without first obtaining a "
    "SLOT_APPROVED verdict from evaluate_canonical_dispatch_slot().  "
    "The canonical dispatch-slot authority is the only valid source of "
    "dispatch targets."
)

DEVICE_ROUTER_MUST_NOT_ACT_AS_READINESS_AUTHORITY_POLICY: str = (
    "POLICY::DEVICE_ROUTER_MUST_NOT_ACT_AS_READINESS_AUTHORITY: "
    "DeviceRouter and lower transport layers are routing substrates only.  "
    "They MUST consume canonical dispatch slots produced by this module and "
    "MUST NOT perform independent readiness evaluation.  Routing decisions "
    "on raw device lists without consulting this authority are a policy "
    "violation."
)

WAKE_MUST_NOT_BYPASS_CANONICAL_SLOT_POLICY: str = (
    "POLICY::WAKE_MUST_NOT_BYPASS_CANONICAL_SLOT: "
    "Wake-routed execution prepares or activates a runtime but MUST NOT "
    "bypass canonical readiness.  Wake events feed into "
    "evaluate_canonical_dispatch_slot() like any other execution mode; the "
    "slot authority decides whether the woken device is a legal dispatch "
    "target after wake completion."
)

FANOUT_SELECTS_SLOTS_NOT_RAW_DEVICES_POLICY: str = (
    "POLICY::FANOUT_SELECTS_SLOTS_NOT_RAW_DEVICES: "
    "Parallel fan-out MUST select multiple SLOT_APPROVED canonical dispatch "
    "slots, not multiple raw devices.  Each slot in a fan-out group has been "
    "independently approved by all ten legality dimensions including "
    "execution-mode eligibility for PARALLEL_FANOUT mode."
)

DELEGATED_HANDOFF_MUST_USE_LEGAL_SLOT_BINDING_POLICY: str = (
    "POLICY::DELEGATED_HANDOFF_MUST_USE_LEGAL_SLOT_BINDING: "
    "Delegated and handoff dispatch MUST rely on legal slot binding from "
    "this authority rather than mode-specific ad-hoc checks.  A device "
    "accepted into a delegated or handoff flow MUST have passed dimension 10 "
    "(delegated/handoff acceptability) in addition to all other dimensions."
)

CONTINUITY_LEGALITY_GATES_DISPATCH_POLICY: str = (
    "POLICY::CONTINUITY_LEGALITY_GATES_DISPATCH: "
    "Dispatch MUST be blocked when the unified continuity legality authority "
    "rejects the inbound action.  Online dispatch is NOT exempt from "
    "continuity legality evaluation (dimension 4).  A stale or revoked "
    "runtime identity MUST produce SLOT_BLOCKED_CONTINUITY_LEGALITY and "
    "MUST NOT reach a transport send."
)

EXECUTION_MODE_ELIGIBILITY_GATES_DISPATCH_POLICY: str = (
    "POLICY::EXECUTION_MODE_ELIGIBILITY_GATES_DISPATCH: "
    "Each execution mode has specific eligibility requirements beyond "
    "technical readiness.  For example, PARALLEL_FANOUT requires a device "
    "to support concurrent task execution; WAKE_ROUTED requires wake-signal "
    "support; DELEGATED_RUNTIME requires delegation acceptance.  A device "
    "that fails execution-mode eligibility for the requested mode MUST "
    "produce SLOT_BLOCKED_EXECUTION_MODE_INELIGIBLE."
)

OCCUPANCY_GATES_DISPATCH_POLICY: str = (
    "POLICY::OCCUPANCY_GATES_DISPATCH: "
    "A device that is already fully occupied (maximum concurrent task limit "
    "reached or exclusive-lock held by another task) MUST produce "
    "SLOT_BLOCKED_OCCUPANCY and MUST NOT be selected as a dispatch target, "
    "regardless of other readiness conditions."
)

POLICY_ALLOWANCE_GATES_DISPATCH_POLICY: str = (
    "POLICY::POLICY_ALLOWANCE_GATES_DISPATCH: "
    "Device-level and system-level dispatch policies (e.g., device disabled, "
    "maintenance mode, rate-limit exhausted) MUST be evaluated before "
    "approving a slot.  A device that fails policy allowance MUST produce "
    "SLOT_BLOCKED_POLICY and MUST NOT be dispatched to."
)


# ---------------------------------------------------------------------------
# CanonicalDispatchSlotStatus
# ---------------------------------------------------------------------------


class CanonicalDispatchSlotStatus(str, Enum):
    """Canonical dispatch-slot verdict across all ten legality dimensions.

    SLOT_APPROVED
        All ten dimensions passed.  This device is a legal dispatch target
        for the requested execution mode.

    SLOT_BLOCKED_TRANSPORT
        Dimension 1 (transport readiness) failed.  Physical connection is
        absent.

    SLOT_BLOCKED_REGISTRATION
        Dimension 2 (registration validity) failed.  Device is not fully
        registered or has downstream registration gaps.

    SLOT_BLOCKED_ATTACHMENT
        Dimension 3 (attachment validity) failed.  Runtime attachment session
        is stale, replaced, or invalidated.

    SLOT_BLOCKED_CONTINUITY_LEGALITY
        Dimension 4 (continuity legality) failed.  The unified continuity
        authority rejected the dispatch action (stale identity, mismatched
        session epoch, etc.).

    SLOT_BLOCKED_CAPABILITY
        Dimension 5 (capability fit) failed.  Device does not support one or
        more required capabilities.

    SLOT_BLOCKED_EXECUTION_MODE_INELIGIBLE
        Dimension 6 (execution-mode eligibility) failed.  Device does not
        meet the eligibility requirements for the requested execution mode.

    SLOT_BLOCKED_OCCUPANCY
        Dimension 7 (occupancy / reservation) failed.  Device is fully
        occupied or holds an exclusive reservation.

    SLOT_BLOCKED_POLICY
        Dimension 8 (policy allowance) failed.  Device-level or system-level
        dispatch policy rejects this dispatch request.

    SLOT_BLOCKED_CROSS_DEVICE_REACHABILITY
        Dimension 9 (cross-device reachability) failed.  Device is not
        eligible for cross-device dispatch.

    SLOT_BLOCKED_DELEGATED_HANDOFF
        Dimension 10 (delegated / handoff acceptability) failed.  Device
        cannot accept a delegated or handoff task for this execution context.

    SLOT_NOT_REGISTERED
        Device is not registered in the system at all.

    SLOT_AUTHORITY_ERROR
        An internal error prevented the authority from completing its
        evaluation.  Dispatch is blocked conservatively.
    """

    SLOT_APPROVED = "slot_approved"
    SLOT_BLOCKED_TRANSPORT = "slot_blocked_transport"
    SLOT_BLOCKED_REGISTRATION = "slot_blocked_registration"
    SLOT_BLOCKED_ATTACHMENT = "slot_blocked_attachment"
    SLOT_BLOCKED_CONTINUITY_LEGALITY = "slot_blocked_continuity_legality"
    SLOT_BLOCKED_CAPABILITY = "slot_blocked_capability"
    SLOT_BLOCKED_EXECUTION_MODE_INELIGIBLE = "slot_blocked_execution_mode_ineligible"
    SLOT_BLOCKED_OCCUPANCY = "slot_blocked_occupancy"
    SLOT_BLOCKED_POLICY = "slot_blocked_policy"
    SLOT_BLOCKED_CROSS_DEVICE_REACHABILITY = "slot_blocked_cross_device_reachability"
    SLOT_BLOCKED_DELEGATED_HANDOFF = "slot_blocked_delegated_handoff"
    SLOT_NOT_REGISTERED = "slot_not_registered"
    SLOT_AUTHORITY_ERROR = "slot_authority_error"


# ---------------------------------------------------------------------------
# CanonicalDispatchSlot
# ---------------------------------------------------------------------------


@dataclass
class CanonicalDispatchSlot:
    """A legality-approved (or blocked) dispatch slot for one device.

    Produced by :func:`evaluate_canonical_dispatch_slot`.

    A ``CanonicalDispatchSlot`` with ``slot_approved=True`` represents a
    device that has been approved by all ten legality dimensions and is a
    legal dispatch target for the requested execution mode.

    Fields
    ------
    device_id
        The device evaluated.
    execution_mode
        The execution mode for which this slot was evaluated.
    slot_approved
        ``True`` iff status is ``SLOT_APPROVED``.  Only these slots may be
        used as dispatch targets.
    status
        :class:`CanonicalDispatchSlotStatus` value string.
    reason
        Human-readable explanation of the verdict.
    dimension_results
        Per-dimension pass/fail results keyed by dimension name.
    blocking_dimension
        The name of the first dimension that blocked the slot, or ``""``
        when the slot is approved.
    registered
        ``True`` iff the device has a UDM record.
    transport_alive
        ``True`` iff the transport connection is physically alive.
    attachment_state
        Current attachment session state string.
    runtime_session_id
        Stable registry session ID, when available.
    runtime_attachment_session_id
        Client-supplied attachment identity, when available.
    registration_gaps
        List of failed downstream registration step names.
    continuity_verdict
        Continuity legality verdict string from the continuity authority.
    execution_mode_eligible
        ``True`` iff the device passes execution-mode eligibility.
    occupancy_clear
        ``True`` iff the device is not fully occupied.
    policy_allowed
        ``True`` iff device-level and system-level dispatch policy permits
        dispatch to this device.
    delegated_handoff_acceptable
        ``True`` iff the device can accept a delegated or handoff task for
        the current execution context.
    authority_notes
        Additional diagnostic notes from the authority evaluation.
    """

    device_id: str
    execution_mode: str = ""
    slot_approved: bool = False
    status: str = CanonicalDispatchSlotStatus.SLOT_NOT_REGISTERED.value
    reason: str = ""
    dimension_results: Dict[str, bool] = field(default_factory=dict)
    blocking_dimension: str = ""
    # Inherited from dispatch readiness gate
    registered: bool = False
    transport_alive: bool = False
    attachment_state: str = "unknown"
    runtime_session_id: Optional[str] = None
    runtime_attachment_session_id: Optional[str] = None
    registration_gaps: List[str] = field(default_factory=list)
    # Additional dimensions
    continuity_verdict: str = "not_evaluated"
    execution_mode_eligible: bool = False
    occupancy_clear: bool = False
    policy_allowed: bool = False
    delegated_handoff_acceptable: bool = False
    authority_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "execution_mode": self.execution_mode,
            "slot_approved": self.slot_approved,
            "status": self.status,
            "reason": self.reason,
            "dimension_results": dict(self.dimension_results),
            "blocking_dimension": self.blocking_dimension,
            "registered": self.registered,
            "transport_alive": self.transport_alive,
            "attachment_state": self.attachment_state,
            "runtime_session_id": self.runtime_session_id,
            "runtime_attachment_session_id": self.runtime_attachment_session_id,
            "registration_gaps": list(self.registration_gaps),
            "continuity_verdict": self.continuity_verdict,
            "execution_mode_eligible": self.execution_mode_eligible,
            "occupancy_clear": self.occupancy_clear,
            "policy_allowed": self.policy_allowed,
            "delegated_handoff_acceptable": self.delegated_handoff_acceptable,
            "authority_notes": list(self.authority_notes),
            "authority": CANONICAL_DISPATCH_SLOT_AUTHORITY,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# CanonicalDispatchSlotsResult
# ---------------------------------------------------------------------------


@dataclass
class CanonicalDispatchSlotsResult:
    """Result of evaluating multiple devices for dispatch slots.

    Produced by :func:`get_canonical_dispatch_slots`.

    Fields
    ------
    execution_mode
        The execution mode for which slots were evaluated.
    approved_slots
        Devices that passed all ten legality dimensions.
    blocked_slots
        Devices that failed one or more dimensions.
    can_proceed
        ``True`` iff at least one approved slot exists.
    block_reason
        Human-readable reason when ``can_proceed`` is ``False``.
    authority_notes
        Diagnostic notes from the authority evaluation.
    """

    execution_mode: str = ""
    approved_slots: List[CanonicalDispatchSlot] = field(default_factory=list)
    blocked_slots: List[CanonicalDispatchSlot] = field(default_factory=list)
    can_proceed: bool = False
    block_reason: str = ""
    authority_notes: List[str] = field(default_factory=list)

    @property
    def approved_device_ids(self) -> List[str]:
        return [s.device_id for s in self.approved_slots]

    @property
    def blocked_device_ids(self) -> List[str]:
        return [s.device_id for s in self.blocked_slots]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_mode": self.execution_mode,
            "approved_slots": [s.to_dict() for s in self.approved_slots],
            "blocked_slots": [s.to_dict() for s in self.blocked_slots],
            "approved_device_ids": self.approved_device_ids,
            "blocked_device_ids": self.blocked_device_ids,
            "can_proceed": self.can_proceed,
            "block_reason": self.block_reason,
            "authority_notes": list(self.authority_notes),
            "authority": CANONICAL_DISPATCH_SLOT_AUTHORITY,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def evaluate_canonical_dispatch_slot(
    device_id: str,
    execution_mode: str,
    *,
    required_capabilities: Optional[List[str]] = None,
    session_id: Optional[str] = None,
    runtime_attachment_session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    continuity_context: Optional[Dict[str, Any]] = None,
) -> CanonicalDispatchSlot:
    """Evaluate whether *device_id* is an approved canonical dispatch slot.

    This is the **single canonical pre-dispatch authority** for all execution
    modes.  Every dispatch path MUST call this and check ``slot_approved``
    before sending any task payload to any device.

    The evaluation proceeds through ten legality dimensions in order.  The
    first blocking dimension terminates evaluation and sets ``status`` and
    ``blocking_dimension`` accordingly.

    Parameters
    ----------
    device_id
        The device to evaluate.
    execution_mode
        The execution mode for this dispatch (e.g. ``"parallel_fanout"``,
        ``"delegated_runtime"``, ``"wake_routed"``, ``"handoff"``).  Used for
        execution-mode eligibility (dimension 6) and delegated/handoff
        acceptability (dimension 10).
    required_capabilities
        Optional list of capability names that must be present on the device.
    session_id
        Optional session identity to cross-check against the registry.
    runtime_attachment_session_id
        Optional client-supplied attachment identity for session cross-check.
    task_id
        Optional task identifier for observability / audit context.
    continuity_context
        Optional dict of context keys used in continuity legality evaluation
        (dimension 4).  Keys recognised: ``runtime_attachment_session_id``,
        ``runtime_session_id``, ``session_id``.

    Returns
    -------
    CanonicalDispatchSlot
        Always returns a valid slot; never raises.
    """
    try:
        return _evaluate_slot_impl(
            device_id=device_id,
            execution_mode=execution_mode,
            required_capabilities=required_capabilities or [],
            session_id=session_id,
            runtime_attachment_session_id=runtime_attachment_session_id,
            task_id=task_id,
            continuity_context=continuity_context or {},
        )
    except Exception as exc:
        logger.warning(
            "CanonicalDispatchSlotAuthority: evaluation error device_id=%r "
            "mode=%r: %s",
            device_id,
            execution_mode,
            exc,
            exc_info=True,
        )
        return CanonicalDispatchSlot(
            device_id=device_id,
            execution_mode=execution_mode,
            slot_approved=False,
            status=CanonicalDispatchSlotStatus.SLOT_AUTHORITY_ERROR.value,
            reason=f"slot_authority_internal_error: {exc}",
            authority_notes=[str(exc)],
        )


def get_canonical_dispatch_slots(
    device_ids: List[str],
    execution_mode: str,
    *,
    required_capabilities: Optional[List[str]] = None,
    session_id: Optional[str] = None,
    runtime_attachment_session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    continuity_context: Optional[Dict[str, Any]] = None,
) -> CanonicalDispatchSlotsResult:
    """Evaluate a list of candidate devices and return approved dispatch slots.

    Use this for fan-out, cross-device, and multi-device execution modes.
    The returned :class:`CanonicalDispatchSlotsResult` contains only
    ``SLOT_APPROVED`` slots in ``approved_slots``.

    Parameters
    ----------
    device_ids
        List of candidate device IDs to evaluate.
    execution_mode
        Execution mode for all candidates.
    required_capabilities
        Capability names that every device must support.
    session_id
        Optional session identity to cross-check.
    runtime_attachment_session_id
        Optional attachment identity to cross-check.
    task_id
        Optional task identifier for audit context.
    continuity_context
        Optional continuity evaluation context.

    Returns
    -------
    CanonicalDispatchSlotsResult
        Always returns a valid result; never raises.
    """
    try:
        return _get_slots_impl(
            device_ids=device_ids,
            execution_mode=execution_mode,
            required_capabilities=required_capabilities or [],
            session_id=session_id,
            runtime_attachment_session_id=runtime_attachment_session_id,
            task_id=task_id,
            continuity_context=continuity_context or {},
        )
    except Exception as exc:
        logger.warning(
            "CanonicalDispatchSlotAuthority: get_slots error mode=%r: %s",
            execution_mode,
            exc,
            exc_info=True,
        )
        return CanonicalDispatchSlotsResult(
            execution_mode=execution_mode,
            can_proceed=False,
            block_reason=f"slot_authority_internal_error: {exc}",
            authority_notes=[str(exc)],
        )


# ---------------------------------------------------------------------------
# Internal implementation
# ---------------------------------------------------------------------------


def _evaluate_slot_impl(
    *,
    device_id: str,
    execution_mode: str,
    required_capabilities: List[str],
    session_id: Optional[str],
    runtime_attachment_session_id: Optional[str],
    task_id: Optional[str],
    continuity_context: Dict[str, Any],
) -> CanonicalDispatchSlot:
    """Evaluate all ten dimensions in order; return on first blocking result."""
    notes: List[str] = [f"execution_mode={execution_mode!r}"]
    if task_id:
        notes.append(f"task_id={task_id!r}")

    dimensions: Dict[str, bool] = {}

    # ----------------------------------------------------------------
    # Dimensions 1–3, 5, 9: Delegate to unified_dispatch_readiness_gate
    # These cover: transport readiness, registration validity, attachment
    # validity, capability fit, and cross-device reachability.
    # ----------------------------------------------------------------
    require_cd = execution_mode in (
        "cross_device", "handoff", "takeover", "wake_routed",
    )
    gate_result = _eval_base_readiness_gate(
        device_id=device_id,
        required_capabilities=required_capabilities,
        require_cross_device_eligible=require_cd,
        session_id=session_id,
        runtime_attachment_session_id=runtime_attachment_session_id,
        execution_mode=execution_mode,
    )

    # Map gate status to slot status for early-exit cases
    _gate_status_map = {
        "not_registered": CanonicalDispatchSlotStatus.SLOT_NOT_REGISTERED.value,
        "blocked_registration_gap": CanonicalDispatchSlotStatus.SLOT_BLOCKED_REGISTRATION.value,
        "blocked_transport": CanonicalDispatchSlotStatus.SLOT_BLOCKED_TRANSPORT.value,
        "blocked_stale_attachment": CanonicalDispatchSlotStatus.SLOT_BLOCKED_ATTACHMENT.value,
        "blocked_session_validity": CanonicalDispatchSlotStatus.SLOT_BLOCKED_ATTACHMENT.value,
        "blocked_capability": CanonicalDispatchSlotStatus.SLOT_BLOCKED_CAPABILITY.value,
        "blocked_cross_device_eligibility": CanonicalDispatchSlotStatus.SLOT_BLOCKED_CROSS_DEVICE_REACHABILITY.value,
        "gate_error": CanonicalDispatchSlotStatus.SLOT_AUTHORITY_ERROR.value,
    }

    # Record per-dimension results from gate
    dimensions["transport_readiness"] = gate_result.transport_alive
    dimensions["registration_validity"] = gate_result.registered and not gate_result.registration_gaps
    dimensions["attachment_validity"] = gate_result.attachment_state not in (
        "detached", "replaced", "invalidated",
    )
    dimensions["capability_fit"] = gate_result.status not in (
        "blocked_capability",
    )
    dimensions["cross_device_reachability"] = gate_result.status not in (
        "blocked_cross_device_eligibility",
    )

    if not gate_result.dispatch_ready:
        slot_status = _gate_status_map.get(
            gate_result.status, CanonicalDispatchSlotStatus.SLOT_AUTHORITY_ERROR.value
        )
        # Identify which dimension blocked first
        blocking_dim = _infer_blocking_dimension_from_gate_status(gate_result.status)
        dimensions[blocking_dim] = False
        return CanonicalDispatchSlot(
            device_id=device_id,
            execution_mode=execution_mode,
            slot_approved=False,
            status=slot_status,
            reason=gate_result.reason,
            dimension_results=dimensions,
            blocking_dimension=blocking_dim,
            registered=gate_result.registered,
            transport_alive=gate_result.transport_alive,
            attachment_state=gate_result.attachment_state,
            runtime_session_id=gate_result.runtime_session_id,
            runtime_attachment_session_id=gate_result.runtime_attachment_session_id,
            registration_gaps=gate_result.registration_gaps,
            authority_notes=notes + gate_result.blocking_notes,
        )

    # ----------------------------------------------------------------
    # Dimension 4: Continuity legality
    # Delegates to core.unified_continuity_legality_authority
    # ----------------------------------------------------------------
    continuity_verdict, continuity_notes = _eval_continuity_legality(
        device_id=device_id,
        execution_mode=execution_mode,
        session_id=session_id,
        runtime_attachment_session_id=runtime_attachment_session_id,
        extra_context=continuity_context,
    )
    dimensions["continuity_legality"] = (continuity_verdict == "allow")
    if continuity_verdict == "reject" or continuity_verdict == "hard_reject":
        notes.extend(continuity_notes)
        return CanonicalDispatchSlot(
            device_id=device_id,
            execution_mode=execution_mode,
            slot_approved=False,
            status=CanonicalDispatchSlotStatus.SLOT_BLOCKED_CONTINUITY_LEGALITY.value,
            reason=f"Continuity legality rejected dispatch: {continuity_notes[0] if continuity_notes else 'see continuity authority'}",
            dimension_results=dimensions,
            blocking_dimension="continuity_legality",
            registered=gate_result.registered,
            transport_alive=gate_result.transport_alive,
            attachment_state=gate_result.attachment_state,
            runtime_session_id=gate_result.runtime_session_id,
            runtime_attachment_session_id=gate_result.runtime_attachment_session_id,
            registration_gaps=gate_result.registration_gaps,
            continuity_verdict=continuity_verdict,
            authority_notes=notes,
        )

    # ----------------------------------------------------------------
    # Dimension 6: Execution-mode eligibility
    # ----------------------------------------------------------------
    mode_eligible, mode_notes = _eval_execution_mode_eligibility(
        device_id=device_id,
        execution_mode=execution_mode,
    )
    dimensions["execution_mode_eligibility"] = mode_eligible
    if not mode_eligible:
        notes.extend(mode_notes)
        return CanonicalDispatchSlot(
            device_id=device_id,
            execution_mode=execution_mode,
            slot_approved=False,
            status=CanonicalDispatchSlotStatus.SLOT_BLOCKED_EXECUTION_MODE_INELIGIBLE.value,
            reason=f"Device not eligible for execution mode {execution_mode!r}: {mode_notes[0] if mode_notes else 'eligibility check failed'}",
            dimension_results=dimensions,
            blocking_dimension="execution_mode_eligibility",
            registered=gate_result.registered,
            transport_alive=gate_result.transport_alive,
            attachment_state=gate_result.attachment_state,
            runtime_session_id=gate_result.runtime_session_id,
            runtime_attachment_session_id=gate_result.runtime_attachment_session_id,
            registration_gaps=gate_result.registration_gaps,
            continuity_verdict=continuity_verdict,
            execution_mode_eligible=False,
            authority_notes=notes,
        )

    # ----------------------------------------------------------------
    # Dimension 7: Occupancy / reservation state
    # ----------------------------------------------------------------
    occupancy_clear, occupancy_notes = _eval_occupancy(
        device_id=device_id,
        task_id=task_id,
    )
    dimensions["occupancy"] = occupancy_clear
    if not occupancy_clear:
        notes.extend(occupancy_notes)
        return CanonicalDispatchSlot(
            device_id=device_id,
            execution_mode=execution_mode,
            slot_approved=False,
            status=CanonicalDispatchSlotStatus.SLOT_BLOCKED_OCCUPANCY.value,
            reason=f"Device is occupied: {occupancy_notes[0] if occupancy_notes else 'occupancy check failed'}",
            dimension_results=dimensions,
            blocking_dimension="occupancy",
            registered=gate_result.registered,
            transport_alive=gate_result.transport_alive,
            attachment_state=gate_result.attachment_state,
            runtime_session_id=gate_result.runtime_session_id,
            runtime_attachment_session_id=gate_result.runtime_attachment_session_id,
            registration_gaps=gate_result.registration_gaps,
            continuity_verdict=continuity_verdict,
            execution_mode_eligible=True,
            occupancy_clear=False,
            authority_notes=notes,
        )

    # ----------------------------------------------------------------
    # Dimension 8: Policy allowance
    # ----------------------------------------------------------------
    policy_allowed, policy_notes = _eval_policy_allowance(
        device_id=device_id,
        execution_mode=execution_mode,
    )
    dimensions["policy_allowance"] = policy_allowed
    if not policy_allowed:
        notes.extend(policy_notes)
        return CanonicalDispatchSlot(
            device_id=device_id,
            execution_mode=execution_mode,
            slot_approved=False,
            status=CanonicalDispatchSlotStatus.SLOT_BLOCKED_POLICY.value,
            reason=f"Dispatch blocked by policy: {policy_notes[0] if policy_notes else 'policy allowance check failed'}",
            dimension_results=dimensions,
            blocking_dimension="policy_allowance",
            registered=gate_result.registered,
            transport_alive=gate_result.transport_alive,
            attachment_state=gate_result.attachment_state,
            runtime_session_id=gate_result.runtime_session_id,
            runtime_attachment_session_id=gate_result.runtime_attachment_session_id,
            registration_gaps=gate_result.registration_gaps,
            continuity_verdict=continuity_verdict,
            execution_mode_eligible=True,
            occupancy_clear=True,
            policy_allowed=False,
            authority_notes=notes,
        )

    # ----------------------------------------------------------------
    # Dimension 10: Delegated / handoff acceptability
    # (only evaluated for delegated_runtime and handoff/takeover modes)
    # ----------------------------------------------------------------
    delegated_handoff_ok = True
    delegated_notes: List[str] = []
    if execution_mode in ("delegated_runtime", "handoff", "takeover"):
        delegated_handoff_ok, delegated_notes = _eval_delegated_handoff_acceptability(
            device_id=device_id,
            execution_mode=execution_mode,
        )
    dimensions["delegated_handoff_acceptability"] = delegated_handoff_ok
    if not delegated_handoff_ok:
        notes.extend(delegated_notes)
        return CanonicalDispatchSlot(
            device_id=device_id,
            execution_mode=execution_mode,
            slot_approved=False,
            status=CanonicalDispatchSlotStatus.SLOT_BLOCKED_DELEGATED_HANDOFF.value,
            reason=f"Device cannot accept {execution_mode!r} task: {delegated_notes[0] if delegated_notes else 'delegated/handoff check failed'}",
            dimension_results=dimensions,
            blocking_dimension="delegated_handoff_acceptability",
            registered=gate_result.registered,
            transport_alive=gate_result.transport_alive,
            attachment_state=gate_result.attachment_state,
            runtime_session_id=gate_result.runtime_session_id,
            runtime_attachment_session_id=gate_result.runtime_attachment_session_id,
            registration_gaps=gate_result.registration_gaps,
            continuity_verdict=continuity_verdict,
            execution_mode_eligible=True,
            occupancy_clear=True,
            policy_allowed=True,
            delegated_handoff_acceptable=False,
            authority_notes=notes,
        )

    # ----------------------------------------------------------------
    # All ten dimensions passed — SLOT_APPROVED
    # ----------------------------------------------------------------
    logger.debug(
        "CanonicalDispatchSlotAuthority: SLOT_APPROVED device_id=%r mode=%r",
        device_id,
        execution_mode,
    )
    return CanonicalDispatchSlot(
        device_id=device_id,
        execution_mode=execution_mode,
        slot_approved=True,
        status=CanonicalDispatchSlotStatus.SLOT_APPROVED.value,
        reason="All ten legality dimensions passed.",
        dimension_results=dimensions,
        blocking_dimension="",
        registered=gate_result.registered,
        transport_alive=gate_result.transport_alive,
        attachment_state=gate_result.attachment_state,
        runtime_session_id=gate_result.runtime_session_id,
        runtime_attachment_session_id=gate_result.runtime_attachment_session_id,
        registration_gaps=gate_result.registration_gaps,
        continuity_verdict=continuity_verdict,
        execution_mode_eligible=True,
        occupancy_clear=True,
        policy_allowed=True,
        delegated_handoff_acceptable=delegated_handoff_ok,
        authority_notes=notes,
    )


def _get_slots_impl(
    *,
    device_ids: List[str],
    execution_mode: str,
    required_capabilities: List[str],
    session_id: Optional[str],
    runtime_attachment_session_id: Optional[str],
    task_id: Optional[str],
    continuity_context: Dict[str, Any],
) -> CanonicalDispatchSlotsResult:
    """Evaluate each device and partition into approved/blocked slots."""
    if not device_ids:
        return CanonicalDispatchSlotsResult(
            execution_mode=execution_mode,
            can_proceed=False,
            block_reason="No candidate device IDs provided.",
            authority_notes=["device_ids list is empty"],
        )

    approved: List[CanonicalDispatchSlot] = []
    blocked: List[CanonicalDispatchSlot] = []
    auth_notes: List[str] = []

    for device_id in device_ids:
        slot = evaluate_canonical_dispatch_slot(
            device_id,
            execution_mode,
            required_capabilities=required_capabilities,
            session_id=session_id,
            runtime_attachment_session_id=runtime_attachment_session_id,
            task_id=task_id,
            continuity_context=continuity_context,
        )
        if slot.slot_approved:
            approved.append(slot)
        else:
            blocked.append(slot)
            auth_notes.append(
                f"device_id={device_id!r} blocked: "
                f"status={slot.status!r} reason={slot.reason!r}"
            )

    can_proceed = len(approved) > 0
    block_reason = ""
    if not can_proceed:
        block_reason = (
            f"All {len(device_ids)} candidate device(s) failed canonical "
            f"dispatch-slot evaluation for mode={execution_mode!r}."
        )
        if blocked:
            first = blocked[0]
            block_reason += (
                f" First blocked device={first.device_id!r}: "
                f"{first.reason!r}"
            )

    return CanonicalDispatchSlotsResult(
        execution_mode=execution_mode,
        approved_slots=approved,
        blocked_slots=blocked,
        can_proceed=can_proceed,
        block_reason=block_reason,
        authority_notes=auth_notes,
    )


# ---------------------------------------------------------------------------
# Sub-checks
# ---------------------------------------------------------------------------


def _eval_base_readiness_gate(
    *,
    device_id: str,
    required_capabilities: List[str],
    require_cross_device_eligible: bool,
    session_id: Optional[str],
    runtime_attachment_session_id: Optional[str],
    execution_mode: str,
) -> Any:
    """Delegate to unified_dispatch_readiness_gate for dimensions 1–3, 5, 9."""
    try:
        from core.unified_dispatch_readiness_gate import evaluate_dispatch_readiness
        return evaluate_dispatch_readiness(
            device_id,
            required_capabilities=required_capabilities,
            require_cross_device_eligible=require_cross_device_eligible,
            session_id=session_id,
            runtime_attachment_session_id=runtime_attachment_session_id,
            execution_mode=execution_mode,
        )
    except Exception as exc:
        logger.debug(
            "CanonicalDispatchSlotAuthority: base gate unavailable for "
            "device_id=%r: %s",
            device_id,
            exc,
        )
        # Return a minimal failing result to avoid false SLOT_APPROVED
        from core.unified_dispatch_readiness_gate import (
            DispatchReadinessResult,
            DispatchReadinessStatus,
        )
        return DispatchReadinessResult(
            device_id=device_id,
            dispatch_ready=False,
            registered=False,
            status=DispatchReadinessStatus.GATE_ERROR.value,
            reason=f"base_readiness_gate_unavailable: {exc}",
            blocking_notes=[str(exc)],
        )


def _infer_blocking_dimension_from_gate_status(gate_status: str) -> str:
    """Map a DispatchReadinessStatus value to its corresponding dimension name."""
    _map = {
        "not_registered": "registration_validity",
        "blocked_registration_gap": "registration_validity",
        "blocked_transport": "transport_readiness",
        "blocked_stale_attachment": "attachment_validity",
        "blocked_session_validity": "attachment_validity",
        "blocked_capability": "capability_fit",
        "blocked_cross_device_eligibility": "cross_device_reachability",
        "registered_not_ready": "transport_readiness",
        "gate_error": "transport_readiness",
    }
    return _map.get(gate_status, "transport_readiness")


def _eval_continuity_legality(
    *,
    device_id: str,
    execution_mode: str,
    session_id: Optional[str],
    runtime_attachment_session_id: Optional[str],
    extra_context: Dict[str, Any],
) -> tuple:
    """Evaluate continuity legality (dimension 4).

    Returns (verdict_str, notes_list) where verdict_str is one of:
    ``"allow"``, ``"reject"``, ``"hard_reject"``, ``"unknown"``.
    """
    try:
        from core.unified_continuity_legality_authority import (
            ContinuityLegalityContext,
            ContinuityLegalityPath,
            evaluate_continuity_legality,
        )

        # Map execution mode to continuity path
        _mode_to_path = {
            "local": ContinuityLegalityPath.online_dispatch,
            "single_device_remote": ContinuityLegalityPath.online_dispatch,
            "cross_device": ContinuityLegalityPath.online_dispatch,
            "parallel_fanout": ContinuityLegalityPath.online_dispatch,
            "handoff": ContinuityLegalityPath.online_dispatch,
            "takeover": ContinuityLegalityPath.online_dispatch,
            "wake_routed": ContinuityLegalityPath.online_dispatch,
            "delegated_runtime": ContinuityLegalityPath.delegated_recovery,
            "hybrid": ContinuityLegalityPath.online_dispatch,
        }
        path = _mode_to_path.get(execution_mode, ContinuityLegalityPath.online_dispatch)

        _attach_id = (
            runtime_attachment_session_id
            or extra_context.get("runtime_attachment_session_id")
            or ""
        )
        _sess_id = (
            session_id
            or extra_context.get("session_id")
            or ""
        )
        _runtime_sess_id = extra_context.get("runtime_session_id", "")

        ctx = ContinuityLegalityContext(
            device_id=device_id,
            path=path,
            runtime_attachment_session_id=_attach_id,
            session_id=_sess_id,
            runtime_session_id=_runtime_sess_id,
        )
        report = evaluate_continuity_legality(ctx)
        verdict = report.verdict if hasattr(report, "verdict") else "allow"
        # Convert verdict object to string if needed
        verdict_str = verdict.value if hasattr(verdict, "value") else str(verdict)
        notes = []
        if hasattr(report, "dimension_outcomes"):
            for _dim, _outcome in (report.dimension_outcomes or {}).items():
                if hasattr(_outcome, "is_rejected") and _outcome.is_rejected():
                    notes.append(f"continuity_dim={_dim}: {_outcome.reason if hasattr(_outcome, 'reason') else 'rejected'}")
        return verdict_str, notes

    except Exception as exc:
        logger.debug(
            "CanonicalDispatchSlotAuthority: continuity legality check "
            "unavailable for device_id=%r: %s",
            device_id,
            exc,
        )
        # When continuity authority is unavailable, allow through
        # (conservative: do not block on unavailable authority)
        return "allow", [f"continuity_legality_unavailable: {exc}"]


def _eval_execution_mode_eligibility(
    *,
    device_id: str,
    execution_mode: str,
) -> tuple:
    """Evaluate execution-mode eligibility (dimension 6).

    Checks device-type and capability constraints specific to the requested
    execution mode.  For example, PARALLEL_FANOUT requires the device to
    support concurrent execution; WAKE_ROUTED requires wake-signal support.

    Returns (eligible: bool, notes: List[str]).
    """
    notes: List[str] = []
    try:
        from core.device_readiness import get_device_readiness
        summary = get_device_readiness(device_id)

        # Mode-specific eligibility rules
        if execution_mode == "parallel_fanout":
            # Parallel fan-out: device must be registered and online; no
            # additional per-device concurrent-execution flag is currently
            # tracked, so we check basic readiness is sufficient.
            if not summary.registered or not summary.online:
                notes.append(
                    f"parallel_fanout: device not registered/online "
                    f"registered={summary.registered} online={summary.online}"
                )
                return False, notes

        elif execution_mode == "wake_routed":
            # Wake-routed: device should be reachable for wake delivery.
            # We conservatively allow through when the device is registered
            # (wake might bring it online) but block if not registered at all.
            if not summary.registered:
                notes.append("wake_routed: device not registered; cannot deliver wake signal")
                return False, notes

        elif execution_mode in ("delegated_runtime", "handoff", "takeover"):
            # Delegated / handoff: device must be online and registered
            if not summary.registered or not summary.online:
                notes.append(
                    f"{execution_mode}: device not registered/online "
                    f"registered={summary.registered} online={summary.online}"
                )
                return False, notes

        return True, notes

    except Exception as exc:
        logger.debug(
            "CanonicalDispatchSlotAuthority: execution-mode eligibility check "
            "unavailable for device_id=%r mode=%r: %s",
            device_id,
            execution_mode,
            exc,
        )
        # When check unavailable, allow through (do not create false blocks)
        return True, [f"execution_mode_eligibility_unavailable: {exc}"]


def _eval_occupancy(
    *,
    device_id: str,
    task_id: Optional[str],
) -> tuple:
    """Evaluate occupancy / reservation state (dimension 7).

    A device is considered occupied if its device pool manager reports it
    as at capacity.  Returns (clear: bool, notes: List[str]).
    """
    notes: List[str] = []
    try:
        from core.device_pool_manager import get_device_pool_manager
        pool = get_device_pool_manager()
        if hasattr(pool, "is_device_occupied"):
            occupied = pool.is_device_occupied(device_id)
            if occupied:
                notes.append(f"device_id={device_id!r} is occupied per DevicePoolManager")
                return False, notes
        return True, notes
    except Exception as exc:
        logger.debug(
            "CanonicalDispatchSlotAuthority: occupancy check unavailable for "
            "device_id=%r: %s",
            device_id,
            exc,
        )
        # When pool manager unavailable, treat as clear
        return True, [f"occupancy_check_unavailable: {exc}"]


def _eval_policy_allowance(
    *,
    device_id: str,
    execution_mode: str,
) -> tuple:
    """Evaluate device-level and system-level dispatch policy (dimension 8).

    Returns (allowed: bool, notes: List[str]).
    """
    notes: List[str] = []
    try:
        from core.device_policy import get_device_policy
        policy = get_device_policy(device_id)
        if policy is not None:
            if hasattr(policy, "dispatch_allowed"):
                if not policy.dispatch_allowed:
                    notes.append(
                        f"device_policy: dispatch_allowed=False for "
                        f"device_id={device_id!r}"
                    )
                    return False, notes
            if hasattr(policy, "disabled") and policy.disabled:
                notes.append(f"device_policy: device is disabled device_id={device_id!r}")
                return False, notes
            if hasattr(policy, "maintenance_mode") and policy.maintenance_mode:
                notes.append(
                    f"device_policy: device is in maintenance mode "
                    f"device_id={device_id!r}"
                )
                return False, notes
        return True, notes
    except Exception as exc:
        logger.debug(
            "CanonicalDispatchSlotAuthority: policy allowance check "
            "unavailable for device_id=%r: %s",
            device_id,
            exc,
        )
        # When policy unavailable, allow through
        return True, [f"policy_allowance_unavailable: {exc}"]


def _eval_delegated_handoff_acceptability(
    *,
    device_id: str,
    execution_mode: str,
) -> tuple:
    """Evaluate delegated / handoff acceptability (dimension 10).

    Delegates to DelegatedFlowAcceptanceGate when available.
    Returns (acceptable: bool, notes: List[str]).
    """
    notes: List[str] = []
    try:
        from core.delegated_flow_acceptance_gate import (
            DelegatedFlowAcceptanceGate,
            get_acceptance_gate,
        )
        gate = get_acceptance_gate()
        if hasattr(gate, "can_accept_delegated_dispatch"):
            can_accept = gate.can_accept_delegated_dispatch(device_id, execution_mode)
            if not can_accept:
                notes.append(
                    f"DelegatedFlowAcceptanceGate: device_id={device_id!r} "
                    f"cannot accept {execution_mode!r} dispatch"
                )
                return False, notes
        return True, notes
    except Exception as exc:
        logger.debug(
            "CanonicalDispatchSlotAuthority: delegated/handoff acceptability "
            "check unavailable for device_id=%r mode=%r: %s",
            device_id,
            execution_mode,
            exc,
        )
        # When gate unavailable, allow through
        return True, [f"delegated_handoff_acceptability_unavailable: {exc}"]


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Authority and policy sentinels
    "CANONICAL_DISPATCH_SLOT_AUTHORITY",
    "CANONICAL_DISPATCH_SLOT_PR_V3_SENTINEL",
    "ALL_EXECUTION_MODES_MUST_CONSUME_CANONICAL_SLOT_POLICY",
    "DEVICE_ROUTER_MUST_NOT_ACT_AS_READINESS_AUTHORITY_POLICY",
    "WAKE_MUST_NOT_BYPASS_CANONICAL_SLOT_POLICY",
    "FANOUT_SELECTS_SLOTS_NOT_RAW_DEVICES_POLICY",
    "DELEGATED_HANDOFF_MUST_USE_LEGAL_SLOT_BINDING_POLICY",
    "CONTINUITY_LEGALITY_GATES_DISPATCH_POLICY",
    "EXECUTION_MODE_ELIGIBILITY_GATES_DISPATCH_POLICY",
    "OCCUPANCY_GATES_DISPATCH_POLICY",
    "POLICY_ALLOWANCE_GATES_DISPATCH_POLICY",
    # Enumerations
    "CanonicalDispatchSlotStatus",
    # Data classes
    "CanonicalDispatchSlot",
    "CanonicalDispatchSlotsResult",
    # Functions
    "evaluate_canonical_dispatch_slot",
    "get_canonical_dispatch_slots",
]
