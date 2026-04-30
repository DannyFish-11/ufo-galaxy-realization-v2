"""core/unified_orchestration_spine.py
========================================
Unified Orchestration Spine — orchestration session governor for multi-step
and multi-device execution sessions.

Architectural scope (V4 corrected)
------------------------------------
V4 ``unified_orchestration_spine`` governs **multi-step orchestration
sessions** — scenarios that involve coordinating multiple devices, multiple
dispatch steps, or complex completion semantics.  Concretely, V4 is the
session authority for:

- parallel fan-out execution (``PARALLEL_FANOUT``),
- delegated runtime execution (``DELEGATED_RUNTIME``),
- wake-routed execution (``WAKE_ROUTED``),
- handoff / takeover flows (``HANDOFF``, ``TAKEOVER``),
- cross-device coordinated execution (``CROSS_DEVICE``),
- hybrid local-plus-remote sessions (``HYBRID``).

V4 is **not** the universal synchronous per-request gate.  Simple per-request
execution (including ordinary ``LOCAL`` and ``SINGLE_DEVICE_REMOTE`` paths)
continues to be governed by the existing cognitive/dispatch spine:
``OpenClawd._determine_execution_path()`` → ``CommandRouter.route_envelope()``.
Forcing V4 into every per-request call would mis-layer the architecture and
create a false split-brain system model.

Problem originally addressed
-----------------------------
Prior to this module, multi-step execution modes (parallel fan-out,
cross-device, handoff/takeover, wake-routed, delegated runtime, hybrid) each
maintained their own dispatch precondition checks, readiness gating, and
completion contracts.  This created:

- ``parallel_subtask`` fan-out bypassing the unified readiness gate.
- ``wake`` / ``handoff`` / ``delegated`` each using special-cased gating that
  diverged from ordinary dispatch semantics.
- No single place to enforce dispatch readiness before complex multi-step
  tasks were sent.

This module closes those gaps by providing a single spine that all **multi-step
orchestration sessions** use.  The spine:

1. Accepts an :class:`OrchestrationRequest` describing the desired execution.
2. Evaluates dispatch readiness for all target devices via the V3
   :func:`~core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots`
   (all ten legality dimensions).
3. Returns an :class:`OrchestrationDecision` that callers use to proceed or
   abort dispatch.
4. Provides a consistent ``completion_contract`` that all orchestration
   sessions share.
5. Exposes a ``lifecycle_stage`` reflecting the current orchestration phase
   and an ``audit_record`` for observability / projection semantics.

V4 structural closure
---------------------
PR-V4 upgrades the spine to consume the V3 canonical dispatch-slot authority
(:mod:`core.canonical_dispatch_slot_authority`) instead of calling the lower
dispatch readiness gate directly.  This means every multi-step orchestration
session now passes through **all ten legality dimensions** — including
continuity legality, execution-mode eligibility, occupancy, policy allowance,
and delegated/handoff acceptability — in a single unified evaluation.

Design
------
- **Additive only** — does not modify any existing module.
- **Composing, not duplicating** — delegates slot evaluation to
  :mod:`core.canonical_dispatch_slot_authority` (V3).
- **Stateless** — no singleton; each call is independent.
- **Graceful degradation** — unavailable sub-systems produce conservative
  blocking decisions; they never produce false READY verdicts.
- **Fully serialisable** — all dataclasses expose ``to_dict()`` / ``to_json()``.

Authority sentinels
-------------------
:data:`UNIFIED_ORCHESTRATION_SPINE_AUTHORITY`
:data:`ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY`
:data:`V4_IS_NOT_PER_REQUEST_GATE_POLICY`
:data:`ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY`
:data:`PARALLEL_FANOUT_MUST_USE_SPINE_POLICY`
:data:`WAKE_HANDOFF_DELEGATED_MUST_USE_SPINE_POLICY`
:data:`SPINE_COMPLETION_CONTRACT_IS_UNIFIED_POLICY`
:data:`CANONICAL_DISPATCH_SLOT_AUTHORITY_IS_SPINE_CONSUMER_POLICY`
:data:`ORCHESTRATION_SPINE_V4_CONSUMES_CANONICAL_SLOT_POLICY`

Public API
----------
Enums::

    ExecutionMode
    OrchestrationLifecycleStage

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

# Lazy import of canonical dispatch-slot authority (V3).  Imported at module
# level so callers and tests can patch core.unified_orchestration_spine.get_canonical_dispatch_slots.
try:
    from core.canonical_dispatch_slot_authority import (
        get_canonical_dispatch_slots,
    )
except ImportError:  # pragma: no cover
    get_canonical_dispatch_slots = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

UNIFIED_ORCHESTRATION_SPINE_AUTHORITY: str = (
    "UNIFIED_ORCHESTRATION_SPINE_AUTHORITY::"
    "core.unified_orchestration_spine is the V4 orchestration session governor "
    "for multi-step and multi-device execution sessions.  It governs parallel "
    "fan-out, delegated runtime, wake-routed, handoff/takeover, cross-device, "
    "and hybrid orchestration sessions.  "
    "PR-V4: the spine consumes core.canonical_dispatch_slot_authority "
    "(all ten legality dimensions) as the slot-readiness authority, eliminating "
    "per-mode special-cased gating across multi-step sessions.  Lifecycle stage "
    "and audit projection semantics are unified across all orchestration sessions.  "
    "V4 is NOT the universal synchronous per-request gate; simple per-request "
    "execution remains governed by OpenClawd._determine_execution_path() and "
    "CommandRouter.route_envelope()."
)

ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY: str = (
    "POLICY::ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE: "
    "core.unified_orchestration_spine (V4) governs multi-step orchestration "
    "sessions — scenarios that coordinate multiple devices, multiple dispatch "
    "steps, or complex completion semantics.  This includes: parallel fan-out "
    "(PARALLEL_FANOUT), delegated runtime (DELEGATED_RUNTIME), wake-routed "
    "(WAKE_ROUTED), handoff/takeover (HANDOFF, TAKEOVER), cross-device "
    "(CROSS_DEVICE), and hybrid (HYBRID) execution sessions.  "
    "The spine is NOT the universal gate for every per-request call.  Simple "
    "LOCAL or SINGLE_DEVICE_REMOTE requests governed by a single unambiguous "
    "execution path do not require V4; they remain on the direct cognitive/"
    "dispatch spine (OpenClawd → CommandRouter).  V4 adds session-level "
    "orchestration authority, lifecycle tracking, and canonical completion "
    "contracts for complex multi-step flows."
)

V4_IS_NOT_PER_REQUEST_GATE_POLICY: str = (
    "POLICY::V4_IS_NOT_PER_REQUEST_GATE: "
    "V4 unified_orchestration_spine MUST NOT be inserted as a mandatory "
    "synchronous gate on every per-request call through OpenClawd.process() "
    "or CommandRouter.route_envelope().  Doing so would force unnecessary "
    "latency onto the per-request hot path, mis-layer the architecture by "
    "conflating orchestration-session authority with per-request routing "
    "authority, and produce a false system model where all execution is "
    "incorrectly described as going through V4.  "
    "The validated per-request path remains: "
    "OpenClawd.process() → _determine_execution_path() → CommandRouter.route_envelope(). "
    "V4 is called by orchestration handlers that initiate multi-step sessions "
    "(e.g., goal_execution, parallel fan-out launchers, delegated runtime "
    "coordinators) — not by the per-request cognitive spine."
)

ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY: str = (
    "POLICY::ALL_ORCHESTRATION_SESSION_MODES_MUST_USE_SPINE: "
    "All multi-step orchestration sessions — regardless of execution mode "
    "(parallel fan-out, delegated, handoff, takeover, wake-routed, cross-device, "
    "hybrid) — MUST use evaluate_orchestration_request() as their pre-dispatch "
    "session authority.  This ensures all ten legality dimensions are enforced "
    "uniformly for complex multi-device flows.  "
    "NOTE: This policy applies to orchestration sessions, not to simple "
    "per-request execution.  Simple per-request dispatch (direct local or "
    "single-device-remote paths chosen by _determine_execution_path()) is "
    "governed by the cognitive/dispatch spine, not by this orchestration spine."
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

CANONICAL_DISPATCH_SLOT_AUTHORITY_IS_SPINE_CONSUMER_POLICY: str = (
    "POLICY::CANONICAL_DISPATCH_SLOT_AUTHORITY_IS_SPINE_CONSUMER: "
    "core.canonical_dispatch_slot_authority (PR-V3) is the canonical dispatch-slot "
    "authority that ALL execution modes MUST consume.  This spine "
    "(core.unified_orchestration_spine) is the orchestration-layer consumer of "
    "the canonical dispatch-slot authority: it calls evaluate_canonical_dispatch_slot() "
    "or get_canonical_dispatch_slots() and dispatches only against SLOT_APPROVED "
    "results.  DeviceRouter and lower transport layers receive pre-approved slots "
    "from this spine and MUST NOT perform independent readiness evaluation."
)

ORCHESTRATION_SPINE_V4_CONSUMES_CANONICAL_SLOT_POLICY: str = (
    "POLICY::ORCHESTRATION_SPINE_V4_CONSUMES_CANONICAL_SLOT: "
    "PR-V4 structural closure: the orchestration spine MUST call "
    "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots() "
    "as its sole slot-evaluation authority for ALL execution modes.  "
    "This replaces the previous direct usage of evaluate_dispatch_readiness() "
    "and ensures all ten legality dimensions (transport, registration, attachment, "
    "continuity legality, capability, execution-mode eligibility, occupancy, "
    "policy allowance, cross-device reachability, delegated/handoff acceptability) "
    "are enforced uniformly across local, single-device-remote, parallel-fanout, "
    "cross-device, handoff, takeover, wake-routed, delegated-runtime, and hybrid "
    "execution modes.  Mode-specific bypass of any dimension is a policy violation."
)

ORCHESTRATION_SPINE_LIFECYCLE_STAGE_IS_UNIFIED_POLICY: str = (
    "POLICY::ORCHESTRATION_SPINE_LIFECYCLE_STAGE_IS_UNIFIED: "
    "All execution modes share the same lifecycle stage progression expressed "
    "through OrchestrationLifecycleStage.  Callers MUST NOT infer lifecycle "
    "meaning from mode-specific side-contracts; they MUST read the "
    "OrchestrationDecision.lifecycle_stage field set by the spine.  "
    "This ensures handoff, delegated, wake-routed, parallel-fanout, and all "
    "other modes advance through the same PRE_EVALUATION → SLOT_EVALUATION → "
    "DISPATCH_EVALUATED → DISPATCHING → AWAITING_RESULT → COMPLETE / "
    "PARTIAL_FAILURE / ABORTED sequence."
)

ORCHESTRATION_SPINE_AUDIT_RECORD_IS_CANONICAL_POLICY: str = (
    "POLICY::ORCHESTRATION_SPINE_AUDIT_RECORD_IS_CANONICAL: "
    "Each OrchestrationDecision carries a canonical audit_record that "
    "contains the orchestration_id, execution_mode, lifecycle_stage, "
    "ready_device_count, blocked_device_count, and completion_contract "
    "snapshot.  This record is the authoritative projection source for "
    "observability systems; mode-specific projection paths MUST NOT "
    "supplement it with separate completion or lifecycle reality."
)

# V5 sentinels — canonical group completion, delegated completion, and
# partial failure semantics.

ORCHESTRATION_SPINE_V5_COMPLETION_CLOSURE_POLICY: str = (
    "POLICY::ORCHESTRATION_SPINE_V5_COMPLETION_CLOSURE: "
    "PR-V5 structural closure: all advanced execution modes (parallel "
    "fan-out, delegated, handoff, takeover, wake-routed, cross-device, "
    "hybrid) MUST determine their canonical terminal state by calling "
    "core.canonical_group_completion_closure.apply_completion_closure() "
    "with the CompletionContract from this spine.  No mode may maintain a "
    "private completion contract, treat a subtask success as group "
    "completion, treat a delegated ACK as delegated terminal completion, "
    "or emit a terminal state outside the canonical closure.  "
    "PR-V5, canonical group completion, delegated completion, and partial "
    "failure semantics."
)

COMPLETION_CONTRACT_V5_BLOCKED_DEVICE_EXCLUSION_POLICY: str = (
    "POLICY::COMPLETION_CONTRACT_V5_BLOCKED_DEVICE_EXCLUSION: "
    "CompletionContract.blocked_device_exclusion governs how blocked (non-"
    "ready) device slots affect the canonical completion outcome.  Allowed "
    "values: 'exclude_from_contract' (shrink effective expected count), "
    "'promote_to_partial_failure' (count each as a failure), "
    "'abort_on_any_blocked' (abort the orchestration immediately).  "
    "The spine sets this field per execution mode in "
    "_derive_completion_contract().  Callers MUST NOT override it.  "
    "PR-V5, canonical group completion closure."
)

COMPLETION_CONTRACT_V5_DEGRADED_SUCCESS_POLICY: str = (
    "POLICY::COMPLETION_CONTRACT_V5_DEGRADED_SUCCESS: "
    "CompletionContract.degraded_success_allowed=True permits the canonical "
    "closure to produce CanonicalTerminalKind.degraded_success when all "
    "received device results succeeded but some device slots were excluded "
    "by blocked_device_exclusion='exclude_from_contract'.  When False (the "
    "default) the same scenario produces partial_success or "
    "aggregate_failure depending on the partial_failure_policy.  "
    "PR-V5, canonical group completion closure."
)

COMPLETION_CONTRACT_V5_AGGREGATE_TIMEOUT_POLICY: str = (
    "POLICY::COMPLETION_CONTRACT_V5_AGGREGATE_TIMEOUT: "
    "CompletionContract.aggregate_timeout_seconds, when set, provides the "
    "wall-clock deadline for the entire orchestration.  When this deadline "
    "elapses before the effective expected result count is satisfied, the "
    "canonical closure produces CanonicalTerminalKind.aggregate_timeout.  "
    "This is a canonical terminal state; callers MUST close the "
    "orchestration rather than continuing to wait.  "
    "PR-V5, canonical group completion closure."
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
# OrchestrationLifecycleStage
# ---------------------------------------------------------------------------


class OrchestrationLifecycleStage(str, Enum):
    """Unified lifecycle stage progression for all execution modes.

    All execution modes advance through the same stage sequence, ensuring
    that handoff, delegated, wake-routed, parallel-fanout, and ordinary
    dispatch share a single lifecycle reality.

    PRE_EVALUATION
        Request accepted; slot evaluation has not yet started.
    SLOT_EVALUATION
        Canonical dispatch-slot authority is being consulted.
    DISPATCH_EVALUATED
        Slot evaluation complete; can_proceed determined.  Ready slots are
        available for dispatch or all slots are blocked.
    DISPATCHING
        Task payload is being sent to approved dispatch slots.
    AWAITING_RESULT
        Dispatch complete; awaiting device results per completion contract.
    PARTIAL_FAILURE
        One or more device results indicate failure; partial_failure_policy
        governs whether the orchestration continues or aborts.
    COMPLETE
        All expected results received and completion contract satisfied.
    ABORTED
        Orchestration aborted due to all-blocked outcome, internal error, or
        explicit cancellation before dispatch.
    """

    PRE_EVALUATION = "pre_evaluation"
    SLOT_EVALUATION = "slot_evaluation"
    DISPATCH_EVALUATED = "dispatch_evaluated"
    DISPATCHING = "dispatching"
    AWAITING_RESULT = "awaiting_result"
    PARTIAL_FAILURE = "partial_failure"
    COMPLETE = "complete"
    ABORTED = "aborted"


# ---------------------------------------------------------------------------
# Canonical slot status → legacy readiness status mapping
# ---------------------------------------------------------------------------

# Maps CanonicalDispatchSlotStatus values (from V3 authority) back to the
# DispatchReadinessStatus vocabulary that DeviceOrchestrationSlot.readiness_status
# has historically exposed.  This preserves backward compatibility for callers
# that check readiness_status against DispatchReadinessStatus values.
_CANONICAL_SLOT_TO_READINESS_STATUS: Dict[str, str] = {
    "slot_approved": "dispatch_ready",
    "slot_blocked_transport": "blocked_transport",
    "slot_blocked_registration": "blocked_registration_gap",
    "slot_blocked_attachment": "blocked_stale_attachment",
    "slot_blocked_continuity_legality": "blocked_continuity_legality",
    "slot_blocked_capability": "blocked_capability",
    "slot_blocked_execution_mode_ineligible": "blocked_execution_mode_ineligible",
    "slot_blocked_occupancy": "blocked_occupancy",
    "slot_blocked_policy": "blocked_policy",
    "slot_blocked_cross_device_reachability": "blocked_cross_device_eligibility",
    "slot_blocked_delegated_handoff": "blocked_stale_attachment",
    "slot_not_registered": "not_registered",
    "slot_authority_error": "gate_error",
}


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
        Legacy :class:`~core.unified_dispatch_readiness_gate.DispatchReadinessStatus`
        value string, mapped from the canonical slot status for backward
        compatibility.  Callers that check this field against
        ``DispatchReadinessStatus`` values continue to work unchanged.
    readiness_reason
        Human-readable explanation from the readiness gate.
    subtask_index
        Optional index within a fan-out for ordering and tracking.
    slot_status
        Canonical :class:`~core.canonical_dispatch_slot_authority.CanonicalDispatchSlotStatus`
        value string from the V3 authority.  Use this field for new code;
        ``readiness_status`` is provided for backward compatibility only.
    blocking_dimension
        The name of the first legality dimension that blocked the slot, or
        ``""`` when the slot is approved.  One of: ``transport_readiness``,
        ``registration_validity``, ``attachment_validity``,
        ``continuity_legality``, ``capability_fit``,
        ``execution_mode_eligibility``, ``occupancy``,
        ``policy_allowance``, ``cross_device_reachability``,
        ``delegated_handoff_acceptability``.
    dimension_results
        Per-dimension pass/fail results keyed by dimension name.  All ten
        dimensions are present when evaluation reached them; earlier-blocked
        slots carry only the dimensions evaluated before the blocking one.
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
    slot_status: str = ""
    blocking_dimension: str = ""
    dimension_results: Dict[str, Any] = field(default_factory=dict)

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
            "slot_status": self.slot_status,
            "blocking_dimension": self.blocking_dimension,
            "dimension_results": dict(self.dimension_results),
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
    blocked_device_exclusion
        V5: How blocked (non-ready) device slots affect the canonical
        completion outcome.  One of:
        - ``"exclude_from_contract"`` — shrink effective expected count.
        - ``"promote_to_partial_failure"`` — count each blocked slot as a
          failure and apply the partial_failure_policy.
        - ``"abort_on_any_blocked"`` — abort the entire orchestration when
          any device slot is blocked.
        Set by :func:`_derive_completion_contract` per execution mode.
        Callers MUST NOT override this value.
    degraded_success_allowed
        V5: When True, the canonical closure may produce
        ``CanonicalTerminalKind.degraded_success`` when all received device
        results succeeded but some slots were excluded via
        ``blocked_device_exclusion="exclude_from_contract"``.  Defaults to
        False; degraded success is an explicit opt-in.
    aggregate_timeout_seconds
        V5: Wall-clock deadline for the entire orchestration.  When set and
        the deadline elapses before the effective expected result count is
        satisfied, the canonical closure produces
        ``CanonicalTerminalKind.aggregate_timeout``.  None means no timeout.
    """

    expected_result_count: int = 0
    partial_failure_policy: str = "best_effort"
    aggregation_mode: str = "all_required"
    blocked_device_exclusion: str = "exclude_from_contract"
    degraded_success_allowed: bool = False
    aggregate_timeout_seconds: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expected_result_count": self.expected_result_count,
            "partial_failure_policy": self.partial_failure_policy,
            "aggregation_mode": self.aggregation_mode,
            "blocked_device_exclusion": self.blocked_device_exclusion,
            "degraded_success_allowed": self.degraded_success_allowed,
            "aggregate_timeout_seconds": self.aggregate_timeout_seconds,
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
    lifecycle_stage
        Current :class:`OrchestrationLifecycleStage` value string.  Set to
        ``DISPATCH_EVALUATED`` upon return from
        :func:`evaluate_orchestration_request`; callers advance the stage
        as the orchestration progresses.
    audit_record
        Canonical audit / projection snapshot produced at evaluation time.
        Contains ``orchestration_id``, ``execution_mode``, ``lifecycle_stage``,
        ``ready_device_count``, ``blocked_device_count``, and a
        ``completion_contract`` snapshot.  Observability consumers MUST use
        this record as their canonical projection source.
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
    lifecycle_stage: str = OrchestrationLifecycleStage.DISPATCH_EVALUATED.value
    audit_record: Dict[str, Any] = field(default_factory=dict)

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
            "lifecycle_stage": self.lifecycle_stage,
            "audit_record": dict(self.audit_record),
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

    This is the **canonical entry point for multi-step orchestration sessions**.
    Orchestration handlers that initiate complex multi-device or multi-step
    flows (parallel fan-out, delegated runtime, wake-routed, handoff/takeover,
    cross-device, hybrid) MUST call this before dispatching task payloads.

    This function is **not** a universal per-request gate.  Simple per-request
    dispatch paths governed by ``OpenClawd._determine_execution_path()`` and
    ``CommandRouter.route_envelope()`` do not call this function; they remain
    on the direct cognitive/dispatch spine.

    The function:
    1. Validates the request.
    2. Evaluates dispatch readiness for each candidate device via
       :func:`~core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots`
       (all ten legality dimensions).
    3. Partitions devices into ready_slots and blocked_slots.
    4. Derives a :class:`CompletionContract` appropriate for the session mode.
    5. Returns an :class:`OrchestrationDecision`.

    Parameters
    ----------
    request
        :class:`OrchestrationRequest` describing the desired orchestration session.

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


def _slot_from_canonical(
    canonical_slot: Any,
    *,
    dispatch_ready: bool,
    device_order: Dict[str, int],
) -> DeviceOrchestrationSlot:
    """Build a :class:`DeviceOrchestrationSlot` from a canonical slot result.

    Maps the V3 ``CanonicalDispatchSlot.status`` to the legacy
    ``DispatchReadinessStatus`` vocabulary for the ``readiness_status`` field
    while also exposing the canonical status in the new ``slot_status`` field.
    """
    readiness_status = _CANONICAL_SLOT_TO_READINESS_STATUS.get(
        canonical_slot.status, canonical_slot.status
    )
    return DeviceOrchestrationSlot(
        device_id=canonical_slot.device_id,
        dispatch_ready=dispatch_ready,
        readiness_status=readiness_status,
        readiness_reason=canonical_slot.reason,
        subtask_index=device_order.get(canonical_slot.device_id, 0),
        registration_gaps=list(canonical_slot.registration_gaps),
        attachment_state=canonical_slot.attachment_state,
        runtime_session_id=canonical_slot.runtime_session_id,
        runtime_attachment_session_id=canonical_slot.runtime_attachment_session_id,
        transport_alive=canonical_slot.transport_alive,
        slot_status=canonical_slot.status,
        blocking_dimension=canonical_slot.blocking_dimension,
        dimension_results=dict(canonical_slot.dimension_results),
    )


def _evaluate_impl(request: OrchestrationRequest) -> OrchestrationDecision:
    """Internal spine evaluation — V4: uses canonical dispatch-slot authority."""
    if get_canonical_dispatch_slots is None:
        raise RuntimeError(
            "core.canonical_dispatch_slot_authority is unavailable; "
            "cannot evaluate orchestration request."
        )

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
            lifecycle_stage=OrchestrationLifecycleStage.ABORTED.value,
        )

    # ----------------------------------------------------------------
    # Evaluate all target devices via canonical dispatch-slot authority
    # (all ten legality dimensions)
    # ----------------------------------------------------------------
    continuity_context: Dict[str, Any] = (
        (request.metadata or {}).get("continuity_context") or {}
    )
    slots_result = get_canonical_dispatch_slots(
        device_ids=request.target_device_ids,
        execution_mode=mode,
        required_capabilities=request.required_capabilities,
        session_id=request.session_id,
        runtime_attachment_session_id=request.runtime_attachment_session_id,
        task_id=request.task_id,
        continuity_context=continuity_context,
    )

    # ----------------------------------------------------------------
    # Map canonical slot results to DeviceOrchestrationSlot objects
    # ----------------------------------------------------------------
    ready_slots: List[DeviceOrchestrationSlot] = []
    blocked_slots: List[DeviceOrchestrationSlot] = []

    # Build device_id → subtask index for ordering
    device_order = {did: idx for idx, did in enumerate(request.target_device_ids)}

    for canonical_slot in slots_result.approved_slots:
        ready_slots.append(
            _slot_from_canonical(canonical_slot, dispatch_ready=True, device_order=device_order)
        )

    for canonical_slot in slots_result.blocked_slots:
        blocked_slots.append(
            _slot_from_canonical(canonical_slot, dispatch_ready=False, device_order=device_order)
        )
        spine_notes.append(
            f"device_id={canonical_slot.device_id!r} blocked: "
            f"slot_status={canonical_slot.status!r} "
            f"blocking_dimension={canonical_slot.blocking_dimension!r} "
            f"reason={canonical_slot.reason!r}"
        )

    # ----------------------------------------------------------------
    # Derive completion contract
    # ----------------------------------------------------------------
    completion_contract = _derive_completion_contract(mode, ready_slots)

    # ----------------------------------------------------------------
    # Determine can_proceed and lifecycle stage
    # ----------------------------------------------------------------
    can_proceed = len(ready_slots) > 0
    block_reason = slots_result.block_reason
    if not can_proceed and not block_reason:
        block_reason = (
            f"All {len(request.target_device_ids)} candidate device(s) failed "
            f"canonical dispatch-slot evaluation for mode={mode!r}."
        )
        if blocked_slots:
            first_blocked = blocked_slots[0]
            block_reason += (
                f" First blocked device={first_blocked.device_id!r}: "
                f"{first_blocked.readiness_reason!r}"
            )

    lifecycle_stage = (
        OrchestrationLifecycleStage.DISPATCH_EVALUATED.value
        if can_proceed
        else OrchestrationLifecycleStage.ABORTED.value
    )

    if blocked_slots:
        spine_notes.append(
            f"{len(blocked_slots)} device(s) blocked by canonical slot authority; "
            f"{len(ready_slots)} device(s) ready."
        )

    # ----------------------------------------------------------------
    # Build the orchestration_id and audit_record
    # ----------------------------------------------------------------
    # We build the decision first to get the orchestration_id, then we
    # populate audit_record after creation using the id.
    decision = OrchestrationDecision(
        execution_mode=mode,
        can_proceed=can_proceed,
        ready_slots=ready_slots,
        blocked_slots=blocked_slots,
        completion_contract=completion_contract,
        block_reason=block_reason,
        spine_notes=spine_notes,
        lifecycle_stage=lifecycle_stage,
    )

    decision.audit_record = {
        "orchestration_id": decision.orchestration_id,
        "execution_mode": mode,
        "lifecycle_stage": lifecycle_stage,
        "ready_device_count": len(ready_slots),
        "blocked_device_count": len(blocked_slots),
        "completion_contract": completion_contract.to_dict(),
        "authority": UNIFIED_ORCHESTRATION_SPINE_AUTHORITY,
    }

    return decision


def _derive_completion_contract(
    mode: str, ready_slots: List[DeviceOrchestrationSlot]
) -> CompletionContract:
    """Derive the appropriate completion contract for the given mode.

    V5: populates blocked_device_exclusion, degraded_success_allowed, and
    aggregate_timeout_seconds per execution mode so the canonical completion
    closure has the correct semantics for each mode.
    """
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
            blocked_device_exclusion="promote_to_partial_failure",
            degraded_success_allowed=False,
            aggregate_timeout_seconds=None,
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
            blocked_device_exclusion="exclude_from_contract",
            degraded_success_allowed=True,
            aggregate_timeout_seconds=None,
        )

    if mode in (
        ExecutionMode.HANDOFF.value,
        ExecutionMode.TAKEOVER.value,
    ):
        return CompletionContract(
            expected_result_count=min(count, 1),
            partial_failure_policy="fail_all",
            aggregation_mode="first_wins",
            blocked_device_exclusion="promote_to_partial_failure",
            degraded_success_allowed=False,
            aggregate_timeout_seconds=None,
        )

    if mode == ExecutionMode.WAKE_ROUTED.value:
        return CompletionContract(
            expected_result_count=min(count, 1),
            partial_failure_policy="fail_all",
            aggregation_mode="any_success",
            blocked_device_exclusion="exclude_from_contract",
            degraded_success_allowed=False,
            aggregate_timeout_seconds=None,
        )

    # Default contract
    return CompletionContract(
        expected_result_count=count,
        partial_failure_policy="best_effort",
        aggregation_mode="all_required",
        blocked_device_exclusion="exclude_from_contract",
        degraded_success_allowed=False,
        aggregate_timeout_seconds=None,
    )


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    "UNIFIED_ORCHESTRATION_SPINE_AUTHORITY",
    "ORCHESTRATION_SPINE_MULTI_STEP_SESSION_SCOPE_POLICY",
    "V4_IS_NOT_PER_REQUEST_GATE_POLICY",
    "ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY",
    "PARALLEL_FANOUT_MUST_USE_SPINE_POLICY",
    "WAKE_HANDOFF_DELEGATED_MUST_USE_SPINE_POLICY",
    "SPINE_COMPLETION_CONTRACT_IS_UNIFIED_POLICY",
    "CANONICAL_DISPATCH_SLOT_AUTHORITY_IS_SPINE_CONSUMER_POLICY",
    "ORCHESTRATION_SPINE_V4_CONSUMES_CANONICAL_SLOT_POLICY",
    "ORCHESTRATION_SPINE_LIFECYCLE_STAGE_IS_UNIFIED_POLICY",
    "ORCHESTRATION_SPINE_AUDIT_RECORD_IS_CANONICAL_POLICY",
    "ORCHESTRATION_SPINE_V5_COMPLETION_CLOSURE_POLICY",
    "COMPLETION_CONTRACT_V5_BLOCKED_DEVICE_EXCLUSION_POLICY",
    "COMPLETION_CONTRACT_V5_DEGRADED_SUCCESS_POLICY",
    "COMPLETION_CONTRACT_V5_AGGREGATE_TIMEOUT_POLICY",
    "ExecutionMode",
    "OrchestrationLifecycleStage",
    "DeviceOrchestrationSlot",
    "OrchestrationRequest",
    "OrchestrationDecision",
    "CompletionContract",
    "evaluate_orchestration_request",
]
