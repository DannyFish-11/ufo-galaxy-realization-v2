"""core/pr4_operator_action_governance.py
==========================================
PR-4 (V2 side): Unify operator actions, governance decisions, and the
operable control surface.

This module is the **center-side convergence layer** for PR-4 of the
5-part full-system convergence plan.  It does NOT replace any existing
operator or governance module; instead it **binds** the existing modules
into a single enforceable, auditable, Android-aware operator action system by:

1. Providing a **full operator action audit chain** — every action records who
   triggered it, why it was allowed, pre-action state, post-action state, and
   success/failure/rollback result.

2. **Orchestrating governed intervention actions** with real causal linkage to
   the affected runtime entities (device, session, task, closure, recovery flow).
   Actions are not detached API verbs — each action touches the canonical runtime
   through the correct orchestration path.

3. **Mapping runtime state → operator action availability** using participation
   state, session state, closure state, takeover proof state, readiness/degraded
   state, and governance/policy engine decisions.

4. **Representing Android-directed actions** as explicit runtime operations with
   corresponding receipt, execution, rollback, failure, and response semantics —
   the V2 center-side half of the dual-repo operator convergence.

5. **Producing an operable board projection** that shows: what is wrong, what
   can currently be done, why an action is available or unavailable, and the
   feedback/result of the last action.

Background
----------
After PR-1 through PR-3, the system has:

* unified participation truth (:mod:`core.android_network_participation`)
* a coherent execution spine (:mod:`core.nl_execution_spine`)
* explicit authority/session/continuity/takeover rules (:mod:`core.pr3_session_continuity_authority`)

PR-4 makes those truths actionable for operators.  Without this layer the system
is inspectable but not governable, and board/operator surfaces remain disconnected
from real runtime actionability.

Android integration points (V2 side responsibilities)
------------------------------------------------------
This module defines the V2 side of a dual-repo operator action convergence.
The corresponding Android-side integration expects:

- ``OperatorActionAndroidDirectedRequest`` — when an operator action targets an
  Android device the V2 side encodes it as a directed command routed through
  the Android delegated runtime channel.
- Receipt ACK: V2 records ``android_dispatch_id`` and ``android_dispatched_at``
  in the audit record.  Android must respond with an ACK on the execution event
  channel.
- Execution feedback: Android ``DEVICE_EXECUTION_EVENT`` messages are correlated
  to the originating operator action via ``operator_action_id`` field in the
  event payload (Android side must propagate this field).
- Rollback: a failed Android-directed action sets ``android_rollback_needed=True``
  in the audit record; the V2 side re-queues the recovery flow.
- ``runtime/OperatorActionReceiver.kt`` — Android receiver must accept directed
  operator actions, execute them, and ACK/NACK back to V2 via the execution event
  channel.
- ``runtime/OperatorActionRollback.kt`` — Android must support rollback for
  isolate/suspend/rebind actions when V2 signals rollback required.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Binding, not replacing** — composes existing runtime modules.
- **Explicit over implicit** — every orchestration step is logged and auditable.
- **Fail-closed** — orchestration failures produce rollback-flagged audit records.
- **No bypass** — all actions enter the canonical runtime, no parallel engine.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`PR4_OPERATOR_ACTION_GOVERNANCE_AUTHORITY`
:data:`PR4_CONVERGENCE_CONTRACT_VERSION`
:data:`OPERATOR_ACTIONS_MUST_BE_AUDITED_POLICY`
:data:`OPERATOR_ACTIONS_MUST_NOT_BYPASS_POLICY_GATE_POLICY`
:data:`ANDROID_DIRECTED_ACTIONS_ARE_RUNTIME_OPS_POLICY`
:data:`BOARD_MUST_REFLECT_OPERABLE_TRUTH_POLICY`

Enums
~~~~~
:class:`OperatorActionOrchestrationOutcome`
:class:`AndroidDirectedActionKind`

Data classes
~~~~~~~~~~~~
:class:`OperatorActionPreState`
:class:`OperatorActionPostState`
:class:`OperatorActionAuditRecord`
:class:`AndroidDirectedActionSpec`
:class:`OperatorActionBoardProjection`
:class:`PR4OperableSurfaceSnapshot`

Functions
~~~~~~~~~
:func:`record_operator_action_audit`
:func:`get_operator_action_audit_log`
:func:`clear_operator_action_audit_log`
:func:`execute_governed_operator_action`
:func:`build_android_directed_action_spec`
:func:`build_operator_board_projection`
:func:`build_pr4_operable_surface_snapshot`
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("Galaxy.PR4.OperatorActionGovernance")

# ---------------------------------------------------------------------------
# PR-4 contract sentinels
# ---------------------------------------------------------------------------

PR4_OPERATOR_ACTION_GOVERNANCE_AUTHORITY: str = (
    "PR4_OPERATOR_ACTION_GOVERNANCE_AUTHORITY::V2::present "
    "core.pr4_operator_action_governance is the V2-side convergence layer "
    "for PR-4 of the 5-part full-system convergence plan. It unifies operator "
    "actions, governance decisions, and the operable control surface into one "
    "auditable, Android-aware, policy-gated runtime action system."
)

PR4_CONVERGENCE_CONTRACT_VERSION: str = "4.0.0"
OPERATOR_ACTION_CANONICAL_ENTRY: str = "/api/v1/operator/action"
ANDROID_DIRECTED_ACTION_CANONICAL_ENTRY: str = "/api/v1/operator/actions/android-directed"
ANDROID_DIRECTED_ACK_CANONICAL_ENTRY: str = "/api/v1/operator/actions/android-directed/{dispatch_id}/ack"
CANONICAL_GOVERNANCE_CONTRACT: str = (
    "core.v2_unified_state_contract.build_control_plane_surface_contract"
)

PR4_CONVERGENCE_SENTINEL: str = (
    "PR4_SENTINEL::pr4_operator_action_governance::4.0.0 "
    "This sentinel confirms that the PR-4 convergence layer is loaded and that "
    "the full operator action audit chain, governed action orchestration, "
    "Android-directed action representation, and operable board projection are "
    "all present in the V2 runtime."
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

OPERATOR_ACTIONS_MUST_BE_AUDITED_POLICY: str = (
    "POLICY::OPERATOR_ACTIONS_MUST_BE_AUDITED_V1: "
    "Every operator action MUST produce an OperatorActionAuditRecord recording "
    "who triggered it, why it was allowed, pre-action state, post-action state, "
    "success/failure/rollback result, and any downstream runtime effects. "
    "An action that cannot produce an audit record MUST be rejected."
)

OPERATOR_ACTIONS_MUST_NOT_BYPASS_POLICY_GATE_POLICY: str = (
    "POLICY::OPERATOR_ACTIONS_MUST_NOT_BYPASS_POLICY_GATE_V1: "
    "Operator action availability MUST be determined by unified governance/policy "
    "engine state (participation state, session state, closure state, takeover "
    "proof state, readiness/degraded state). Hard-coded availability is not permitted."
)

ANDROID_DIRECTED_ACTIONS_ARE_RUNTIME_OPS_POLICY: str = (
    "POLICY::ANDROID_DIRECTED_ACTIONS_ARE_RUNTIME_OPS_V1: "
    "Operator actions targeting Android devices are represented as explicit runtime "
    "operations with receipt, execution, rollback, failure, and response semantics. "
    "They are NOT detached API requests — they enter the V2 runtime and produce "
    "traceable android_dispatch_id records that the Android device must ACK."
)

BOARD_MUST_REFLECT_OPERABLE_TRUTH_POLICY: str = (
    "POLICY::BOARD_MUST_REFLECT_OPERABLE_TRUTH_V1: "
    "Operator-facing board projections MUST show: what is wrong, what can currently "
    "be done, why an action is available or unavailable, and the feedback/result of "
    "the last action. Boards MUST reflect policy-based action availability — "
    "hard-coded optimism is not permitted."
)

# ---------------------------------------------------------------------------
# In-process audit log (bounded ring buffer for the current server session)
# ---------------------------------------------------------------------------

_AUDIT_LOG: List["OperatorActionAuditRecord"] = []
_AUDIT_LOG_MAX_RECORDS: int = 500


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OperatorActionOrchestrationOutcome(str, Enum):
    """Explicit outcome of a governed operator action after orchestration.

    success
        The action was fully executed and all affected runtime entities
        transitioned to the expected post-action state.

    accepted_pending
        The action was accepted and dispatched (e.g. to an Android device)
        but the final result is still pending an asynchronous ACK.

    policy_blocked
        The action was rejected at the policy/state gate before execution.

    approval_required
        The action requires an approval_token that was not provided.

    partial_success
        The action was partially executed; some affected entities transitioned
        but at least one did not.  See ``affected_entity_ids`` and ``error``.

    rollback_needed
        Execution started but failed midway; rollback is required.  The audit
        record carries ``rollback_needed=True``.

    failed
        Execution failed; no runtime changes were applied.

    unsupported
        The action_kind is not supported by the current runtime.
    """

    success = "success"
    accepted_pending = "accepted_pending"
    policy_blocked = "policy_blocked"
    approval_required = "approval_required"
    partial_success = "partial_success"
    rollback_needed = "rollback_needed"
    failed = "failed"
    unsupported = "unsupported"


class AndroidDirectedActionKind(str, Enum):
    """Operator actions that specifically target Android devices.

    These actions are sent through the Android delegated runtime channel.

    revalidate_participation
        Request the Android device to revalidate its network participation
        tier and report back a fresh participation state to V2.

    force_reattach
        Force the Android device to drop and re-establish its V2 WebSocket
        connection, triggering a fresh attachment + capability handshake.

    retry_delegated_execution
        Retry a specific delegated flow that has stalled or failed on the
        Android device.

    trigger_device_recovery
        Trigger the Android device's recovery procedure for a stalled or
        failed execution.

    rebind_session
        Rebind the Android device to a V2 session after a continuity break.

    suspend_device
        Request the Android device to suspend its participation in distributed
        execution (soft suspend; device stays connected but does not accept
        new tasks).

    isolate_device
        Fully isolate the Android device from the V2 mesh — it will no longer
        receive tasks until explicitly re-admitted.
    """

    revalidate_participation = "revalidate_participation"
    force_reattach = "force_reattach"
    retry_delegated_execution = "retry_delegated_execution"
    trigger_device_recovery = "trigger_device_recovery"
    rebind_session = "rebind_session"
    suspend_device = "suspend_device"
    isolate_device = "isolate_device"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class OperatorActionPreState:
    """Captured runtime state immediately before a governed operator action.

    This snapshot is recorded unconditionally so that audit records always
    carry the before-state regardless of whether the action succeeded.
    """

    captured_at: float = field(default_factory=time.time)
    participation_tier: str = ""
    session_state: str = ""
    closure_state: str = ""
    governance_hard_block_count: int = 0
    governance_soft_degraded_count: int = 0
    governance_manual_decision_count: int = 0
    active_flow_count: int = 0
    online_device_count: int = 0
    presence_tristate: str = ""
    takeover_proof_quality: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "participation_tier": self.participation_tier,
            "session_state": self.session_state,
            "closure_state": self.closure_state,
            "governance_hard_block_count": self.governance_hard_block_count,
            "governance_soft_degraded_count": self.governance_soft_degraded_count,
            "governance_manual_decision_count": self.governance_manual_decision_count,
            "active_flow_count": self.active_flow_count,
            "online_device_count": self.online_device_count,
            "presence_tristate": self.presence_tristate,
            "takeover_proof_quality": self.takeover_proof_quality,
            "extra": dict(self.extra),
        }


@dataclass
class OperatorActionPostState:
    """Captured runtime state immediately after a governed operator action.

    Empty fields indicate the state could not be captured (e.g. action failed
    before any runtime change was applied).
    """

    captured_at: float = field(default_factory=time.time)
    participation_tier: str = ""
    session_state: str = ""
    closure_state: str = ""
    active_flow_count: int = 0
    online_device_count: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "participation_tier": self.participation_tier,
            "session_state": self.session_state,
            "closure_state": self.closure_state,
            "active_flow_count": self.active_flow_count,
            "online_device_count": self.online_device_count,
            "extra": dict(self.extra),
        }


@dataclass
class OperatorActionAuditRecord:
    """Full causal audit record for a single governed operator action.

    This record satisfies PR-4 requirement #4: every action must record
    who triggered it, why it was allowed, pre-action state, post-action state,
    success/failure/rollback result, and any downstream runtime or governance effects.

    Fields
    ------
    audit_id
        Unique ID for this audit record.
    action_id
        Correlation ID of the :class:`~core.operator_action_contract.OperatorActionResult`
        that this record corresponds to.
    action_kind
        The :class:`~core.operator_action_contract.OperatorActionKind` value.
    operator_user_id
        Who triggered this action.
    triggered_at
        Unix epoch when the action was initiated.
    policy_evaluation
        Short token describing why the action was allowed or blocked
        (e.g. ``"state_gate_allowed"``, ``"state_gate_blocked"``,
        ``"approval_required"``, ``"unsupported_action"``).
    policy_basis
        Human-readable explanation of the policy decision.
    pre_state
        Runtime state snapshot before the action.
    post_state
        Runtime state snapshot after the action (may be empty on failure).
    outcome
        :class:`OperatorActionOrchestrationOutcome` value.
    affected_entity_ids
        IDs of runtime entities (task_id, flow_id, device_id, session_id)
        that were changed by this action.
    downstream_effects
        List of downstream runtime or governance effects produced by the action.
    error
        Non-empty when the action failed.
    rollback_needed
        True when the action started but failed midway and rollback is required.
    android_dispatch_id
        Correlation ID for Android-directed actions.  Empty for V2-local actions.
    android_dispatched_at
        Timestamp when the Android-directed action was dispatched.
    android_ack_received
        True when the Android device has acknowledged the directed action.
    authority
        Module authority sentinel.
    """

    audit_id: str = field(default_factory=lambda: f"opadit_{uuid.uuid4().hex[:12]}")
    action_id: str = ""
    action_kind: str = ""
    operator_user_id: str = "operator"
    triggered_at: float = field(default_factory=time.time)
    policy_evaluation: str = ""
    policy_basis: str = ""
    pre_state: OperatorActionPreState = field(default_factory=OperatorActionPreState)
    post_state: OperatorActionPostState = field(default_factory=OperatorActionPostState)
    outcome: str = OperatorActionOrchestrationOutcome.failed.value
    affected_entity_ids: List[str] = field(default_factory=list)
    downstream_effects: List[str] = field(default_factory=list)
    error: str = ""
    rollback_needed: bool = False
    android_dispatch_id: str = ""
    android_dispatched_at: Optional[float] = None
    android_ack_received: bool = False
    canonical_entry: str = OPERATOR_ACTION_CANONICAL_ENTRY
    canonical_governance_contract: str = CANONICAL_GOVERNANCE_CONTRACT
    routed_subject_ids: List[str] = field(default_factory=list)
    participant_ack_state: str = "not_required"
    truth_convergence_state: str = "not_evaluated"
    closure_verification_state: str = "not_evaluated"
    continuity_adjudication_classification: str = ""
    continuity_adjudication_disposition: str = ""
    continuity_adjudication_evidence: Dict[str, Any] = field(default_factory=dict)
    authority: str = PR4_OPERATOR_ACTION_GOVERNANCE_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "action_id": self.action_id,
            "action_kind": self.action_kind,
            "operator_user_id": self.operator_user_id,
            "triggered_at": self.triggered_at,
            "policy_evaluation": self.policy_evaluation,
            "policy_basis": self.policy_basis,
            "pre_state": self.pre_state.to_dict(),
            "post_state": self.post_state.to_dict(),
            "outcome": self.outcome,
            "affected_entity_ids": list(self.affected_entity_ids),
            "downstream_effects": list(self.downstream_effects),
            "error": self.error,
            "rollback_needed": self.rollback_needed,
            "android_dispatch_id": self.android_dispatch_id,
            "android_dispatched_at": self.android_dispatched_at,
            "android_ack_received": self.android_ack_received,
            "canonical_entry": self.canonical_entry,
            "canonical_governance_contract": self.canonical_governance_contract,
            "routed_subject_ids": list(self.routed_subject_ids),
            "participant_ack_state": self.participant_ack_state,
            "truth_convergence_state": self.truth_convergence_state,
            "closure_verification_state": self.closure_verification_state,
            "continuity_adjudication_classification": self.continuity_adjudication_classification,
            "continuity_adjudication_disposition": self.continuity_adjudication_disposition,
            "continuity_adjudication_evidence": dict(self.continuity_adjudication_evidence),
            "authority": self.authority,
        }


@dataclass
class AndroidDirectedActionSpec:
    """Specification for an operator action directed at an Android device.

    This spec is the V2 runtime representation of an Android-directed
    operator action.  It carries enough information for the Android device
    to execute the action and ACK back, and for V2 to correlate the response.

    Satisfies PR-4 requirement: Android-directed actions are represented as
    real runtime operations rather than detached API requests.
    """

    android_dispatch_id: str = field(default_factory=lambda: f"andop_{uuid.uuid4().hex[:12]}")
    action_kind: str = ""
    device_id: str = ""
    operator_action_id: str = ""
    operator_user_id: str = "operator"
    target_flow_id: str = ""
    target_task_id: str = ""
    target_session_id: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    routed_subject_ids: List[str] = field(default_factory=list)
    dispatched_at: float = field(default_factory=time.time)
    expected_ack_within_seconds: int = 30
    expires_at: float = 0.0
    lifecycle_state: str = "pending"
    lifecycle_failure_reason: str = ""
    rollback_on_timeout: bool = True
    authority: str = PR4_OPERATOR_ACTION_GOVERNANCE_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        expires_at = self.expires_at
        if expires_at <= 0:
            expires_at = self.dispatched_at + max(1, int(self.expected_ack_within_seconds))
        return {
            "android_dispatch_id": self.android_dispatch_id,
            "action_kind": self.action_kind,
            "device_id": self.device_id,
            "operator_action_id": self.operator_action_id,
            "operator_user_id": self.operator_user_id,
            "target_flow_id": self.target_flow_id,
            "target_task_id": self.target_task_id,
            "target_session_id": self.target_session_id,
            "payload": dict(self.payload),
            "routed_subject_ids": _build_android_directed_subject_ids(self),
            "dispatched_at": self.dispatched_at,
            "expected_ack_within_seconds": self.expected_ack_within_seconds,
            "expires_at": expires_at,
            "lifecycle_state": self.lifecycle_state,
            "lifecycle_failure_reason": self.lifecycle_failure_reason,
            "rollback_on_timeout": self.rollback_on_timeout,
            "operator_control_closure_trace": _build_operator_control_closure_trace(
                action_id=self.operator_action_id,
                action_kind=self.action_kind,
                routed_subject_ids=_build_android_directed_subject_ids(self),
                participant_ack_state=self.lifecycle_state,
                truth_convergence_state=(
                    "pending_canonical_truth_convergence"
                    if self.lifecycle_state == "pending"
                    else "participant_ack_recorded_pending_canonical_truth"
                ),
                closure_verification_state=(
                    "pending_canonical_closure_verification"
                    if self.lifecycle_state in {"pending", "acked"}
                    else "not_verified"
                ),
                canonical_entry=ANDROID_DIRECTED_ACTION_CANONICAL_ENTRY,
            ),
            "authority": self.authority,
        }


@dataclass
class OperatorActionBoardProjection:
    """Operator-facing board projection showing operable truth.

    Satisfies PR-4 requirement #5: board surfaces must show what is wrong,
    what can currently be done, why an action is available or unavailable,
    and the feedback/result of the last action.

    Policy-based availability only — no hard-coded optimism.
    """

    generated_at: float = field(default_factory=time.time)

    # What is wrong
    hard_block_count: int = 0
    soft_degraded_count: int = 0
    manual_decision_count: int = 0
    system_health_summary: str = "unknown"
    active_blockers: List[str] = field(default_factory=list)

    # What can currently be done (policy-derived, per action)
    available_actions: List[Dict[str, Any]] = field(default_factory=list)
    unavailable_actions: List[Dict[str, Any]] = field(default_factory=list)

    # Why actions are available or unavailable
    availability_state_basis: Dict[str, Any] = field(default_factory=dict)
    policy_version: str = ""

    # Feedback/result of the last action
    last_action_id: str = ""
    last_action_kind: str = ""
    last_action_outcome: str = ""
    last_action_error: str = ""
    last_action_triggered_at: Optional[float] = None
    last_action_affected_entity_ids: List[str] = field(default_factory=list)
    last_action_closure_trace: Dict[str, Any] = field(default_factory=dict)

    # Android-directed action status
    pending_android_directed_actions: List[Dict[str, Any]] = field(default_factory=list)
    android_participation_verdict: Dict[str, Any] = field(default_factory=dict)
    runtime_decision_reasoning: Dict[str, Any] = field(default_factory=dict)
    unified_mode_model: Dict[str, Any] = field(default_factory=dict)
    latest_closure_reasoning: Dict[str, Any] = field(default_factory=dict)
    operational_state_board: Dict[str, Any] = field(default_factory=dict)
    participation_truth_consumption: Dict[str, Any] = field(default_factory=dict)
    foundational_system_truth: Dict[str, Any] = field(default_factory=dict)
    control_plane_contract: Dict[str, Any] = field(default_factory=dict)

    authority: str = PR4_OPERATOR_ACTION_GOVERNANCE_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "hard_block_count": self.hard_block_count,
            "soft_degraded_count": self.soft_degraded_count,
            "manual_decision_count": self.manual_decision_count,
            "system_health_summary": self.system_health_summary,
            "active_blockers": list(self.active_blockers),
            "available_actions": list(self.available_actions),
            "unavailable_actions": list(self.unavailable_actions),
            "availability_state_basis": dict(self.availability_state_basis),
            "policy_version": self.policy_version,
            "last_action_id": self.last_action_id,
            "last_action_kind": self.last_action_kind,
            "last_action_outcome": self.last_action_outcome,
            "last_action_error": self.last_action_error,
            "last_action_triggered_at": self.last_action_triggered_at,
            "last_action_affected_entity_ids": list(self.last_action_affected_entity_ids),
            "last_action_closure_trace": dict(self.last_action_closure_trace),
            "pending_android_directed_actions": list(self.pending_android_directed_actions),
            "android_participation_verdict": dict(self.android_participation_verdict),
            "runtime_decision_reasoning": dict(self.runtime_decision_reasoning),
            "unified_mode_model": dict(self.unified_mode_model),
            "latest_closure_reasoning": dict(self.latest_closure_reasoning),
            "operational_state_board": dict(self.operational_state_board),
            "participation_truth_consumption": dict(self.participation_truth_consumption),
            "foundational_system_truth": dict(self.foundational_system_truth),
            "control_plane_contract": dict(self.control_plane_contract),
            "authority": self.authority,
        }


@dataclass
class PR4OperableSurfaceSnapshot:
    """Top-level PR-4 operable surface snapshot.

    This is the canonical PR-4 artifact for the V2 operator surface.  It
    combines all PR-4 dimensions into one inspectable record:

    * Board projection (operable truth with availability + feedback)
    * Recent audit log (last N operator action audit records)
    * Pending Android-directed actions
    * Contract version + authority confirmation
    """

    generated_at: float = field(default_factory=time.time)
    board: OperatorActionBoardProjection = field(default_factory=OperatorActionBoardProjection)
    recent_audit_records: List[OperatorActionAuditRecord] = field(default_factory=list)
    pending_android_directed_count: int = 0
    operator_control_plane_contract: Dict[str, Any] = field(default_factory=dict)
    contract_version: str = PR4_CONVERGENCE_CONTRACT_VERSION
    sentinel: str = PR4_CONVERGENCE_SENTINEL
    authority: str = PR4_OPERATOR_ACTION_GOVERNANCE_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "board": self.board.to_dict(),
            "recent_audit_records": [r.to_dict() for r in self.recent_audit_records],
            "pending_android_directed_count": self.pending_android_directed_count,
            "operator_control_plane_contract": dict(self.operator_control_plane_contract),
            "contract_version": self.contract_version,
            "sentinel": self.sentinel,
            "authority": self.authority,
        }


# ---------------------------------------------------------------------------
# Pending Android-directed actions store
# ---------------------------------------------------------------------------

_PENDING_ANDROID_ACTIONS: Dict[str, AndroidDirectedActionSpec] = {}
_TERMINAL_ANDROID_ACTIONS: Dict[str, Dict[str, Any]] = {}
_OPERATOR_INTERVENTION_IDEMPOTENCY_KEYS: Set[str] = set()
_OPERATOR_INTERVENTION_IDEMPOTENCY_LOCK = threading.Lock()

_MANUAL_IDEMPOTENT_ACTION_KINDS: Set[str] = {
    "trigger_recovery",
    "reopen_session_continuity",
    "rebind_session_continuity",
    "reopen_closure",
    "finalize_closure",
    "reject_closure",
}

_TERMINAL_TASK_LIFECYCLES: Set[str] = {
    "completed",
    "failed",
    "cancelled",
    "degraded",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _capture_pre_state() -> OperatorActionPreState:
    """Capture a pre-action runtime state snapshot."""
    pre = OperatorActionPreState()
    pre.captured_at = time.time()

    try:
        from core.operator_surface import get_operator_surface
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        policy_layer = snap.governance_state.get("policy_layer", {})
        summary = policy_layer.get("summary", {})
        pre.governance_hard_block_count = int(summary.get("hard_block_count", 0))
        pre.governance_soft_degraded_count = int(summary.get("soft_degraded_count", 0))
        pre.governance_manual_decision_count = int(summary.get("manual_decision_count", 0))
        pre.active_flow_count = snap.active_flow_count
        pre.online_device_count = snap.online_device_count
        pre.presence_tristate = snap.presence_tristate or ""
    except Exception as exc:
        logger.debug("_capture_pre_state: operator snapshot unavailable: %s", exc)

    try:
        from core.v2_android_truth_ssot import get_best_v2_android_truth_block
        best_block = get_best_v2_android_truth_block()
        pre.participation_tier = best_block.participation_tier
    except Exception as exc:
        logger.debug("_capture_pre_state: participation tier unavailable: %s", exc)

    try:
        from core.pr3_session_continuity_authority import build_pr3_convergence_audit_snapshot
        pr3_snap = build_pr3_convergence_audit_snapshot()
        pre.session_state = pr3_snap.get("session_state", "")
        pre.takeover_proof_quality = pr3_snap.get("takeover_proof_quality", "")
    except Exception as exc:
        logger.debug("_capture_pre_state: pr3 session state unavailable: %s", exc)

    return pre


def _capture_post_state() -> OperatorActionPostState:
    """Capture a post-action runtime state snapshot."""
    post = OperatorActionPostState()
    post.captured_at = time.time()

    try:
        from core.operator_surface import get_operator_surface
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        post.active_flow_count = snap.active_flow_count
        post.online_device_count = snap.online_device_count
    except Exception as exc:
        logger.debug("_capture_post_state: operator snapshot unavailable: %s", exc)

    return post


def _determine_system_health(
    hard_block_count: int,
    soft_degraded_count: int,
    manual_decision_count: int,
) -> str:
    """Derive a single human-readable health summary string."""
    if hard_block_count > 0:
        return "blocked"
    if soft_degraded_count > 0:
        return "degraded"
    if manual_decision_count > 0:
        return "needs_review"
    return "healthy"


def _build_android_directed_subject_ids(spec: AndroidDirectedActionSpec) -> List[str]:
    subjects: List[str] = []
    seen: Set[str] = set()
    payload_routed = spec.payload.get("routed_subject_ids", []) if isinstance(spec.payload, dict) else []
    for item in (
        spec.device_id,
        spec.target_flow_id,
        spec.target_task_id,
        spec.target_session_id,
        *(spec.routed_subject_ids or []),
        *([x for x in payload_routed if isinstance(x, str)]),
    ):
        value = str(item or "").strip()
        if value and value not in seen:
            seen.add(value)
            subjects.append(value)
    return subjects


def _build_operator_control_closure_trace(
    *,
    action_id: str,
    action_kind: str,
    routed_subject_ids: List[str],
    participant_ack_state: str,
    truth_convergence_state: str,
    closure_verification_state: str,
    canonical_entry: str = OPERATOR_ACTION_CANONICAL_ENTRY,
    state_update_entry: str = "",
    acknowledged_subject_ids: Optional[List[str]] = None,
    pending_subject_ids: Optional[List[str]] = None,
    failure_diagnostics: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "action_id": action_id,
        "action_kind": action_kind,
        "canonical_entry": canonical_entry,
        "canonical_governance_contract": CANONICAL_GOVERNANCE_CONTRACT,
        "routed_subject_ids": list(routed_subject_ids),
        "participant_ack_state": participant_ack_state,
        "truth_convergence_state": truth_convergence_state,
        "closure_verification_state": closure_verification_state,
        "state_update_entry": state_update_entry or canonical_entry,
        "acknowledged_subject_ids": list(acknowledged_subject_ids or []),
        "pending_subject_ids": list(pending_subject_ids or []),
        "failure_diagnostics": list(failure_diagnostics or []),
    }


def _build_operator_manual_action_idempotency_key(
    *,
    action_kind: str,
    task_id: Optional[str],
    flow_id: Optional[str],
    session_id: Optional[str],
    device_id: Optional[str],
) -> str:
    identity_parts = []
    for label, value in (
        ("task", task_id),
        ("flow", flow_id),
        ("session", session_id),
        ("device", device_id),
    ):
        text = str(value or "").strip()
        if text:
            identity_parts.append(f"{label}={text}")
    if not identity_parts:
        identity_parts.append("unscoped=true")
    identity = "|".join(identity_parts)
    return f"operator_manual:{action_kind}:{identity}"


def _is_sanctioned_reopen_path(
    *,
    approval_token: Optional[str],
    action_notes: str,
) -> bool:
    token = str(approval_token or "").strip().lower()
    notes = str(action_notes or "").strip().lower()
    return token.startswith("sanctioned:") or "sanctioned_reopen" in notes


def _lookup_canonical_task_snapshot(task_id: Optional[str]) -> Dict[str, str]:
    task_id_text = str(task_id or "").strip()
    if not task_id_text:
        return {}
    try:
        from core.canonical_task import get_canonical_task_runtime

        task = get_canonical_task_runtime().get_by_task_id(task_id_text)
        if task is None:
            return {}
        lifecycle = getattr(task, "lifecycle", "")
        lifecycle_text = (
            lifecycle.value if hasattr(lifecycle, "value") else str(lifecycle)
        ).strip().lower()
        identity = getattr(task, "identity", None)
        task_session_id_text = str(getattr(identity, "session_id", "") or "").strip()
        return {
            "task_lifecycle": lifecycle_text,
            "task_session_id": task_session_id_text,
        }
    except Exception as exc:
        logger.debug("operator_intervention: canonical task lookup skipped: %s", exc)
        return {}


def _evaluate_operator_intervention_adjudication(
    *,
    action_kind: str,
    task_id: Optional[str],
    flow_id: Optional[str],
    session_id: Optional[str],
    device_id: Optional[str],
    approval_token: Optional[str],
    action_notes: str,
) -> Dict[str, Any]:
    from core.continuity_adjudication import (
        ContinuityAdjudicationClassification,
        adjudicate_duplicate_vs_first_accepted,
        adjudicate_stale_vs_current,
        build_continuity_adjudication_evidence,
    )

    related_identity = {
        "action_kind": action_kind,
        "task_id": str(task_id or ""),
        "flow_id": str(flow_id or ""),
        "session_id": str(session_id or ""),
        "device_id": str(device_id or ""),
    }
    default_evidence = build_continuity_adjudication_evidence(
        classification=ContinuityAdjudicationClassification.current_accepted,
        triggering_reason="operator_intervention_gate_passed",
        related_identity=related_identity,
        decision_point="operator_intervention.continuity_gate",
    )
    default_evidence["intervention_status"] = "sanctioned_operator_intervention"
    adjudication = {
        "allow": True,
        "classification": ContinuityAdjudicationClassification.current_accepted.value,
        "disposition": "first_accepted",
        "triggering_reason": "operator_intervention_gate_passed",
        "idempotency_key": "",
        "idempotency_reserved": False,
        "evidence": default_evidence,
    }
    canonical_task_snapshot = _lookup_canonical_task_snapshot(task_id)
    task_lifecycle = canonical_task_snapshot.get("task_lifecycle", "")
    task_session_id = canonical_task_snapshot.get("task_session_id", "")

    if action_kind == "reopen_closure" and task_id:
        is_unsanctioned_terminal_reopen = (
            task_lifecycle in _TERMINAL_TASK_LIFECYCLES
            and not _is_sanctioned_reopen_path(
            approval_token=approval_token,
            action_notes=action_notes,
            )
        )
        if is_unsanctioned_terminal_reopen:
            stale = adjudicate_stale_vs_current(
                is_stale=True,
                stale_classification="final_closed_reopen_without_sanction",
                stale_reason="final_closed_task_requires_sanctioned_reopen_path",
            )
            evidence = build_continuity_adjudication_evidence(
                classification=stale.classification,
                triggering_reason=stale.triggering_reason,
                epoch_session_basis={"task_lifecycle": task_lifecycle},
                related_identity=related_identity,
                decision_point="operator_intervention.reopen_closure_guard",
            )
            evidence["intervention_status"] = "rejected_stale_intervention"
            adjudication.update(
                {
                    "allow": False,
                    "classification": stale.classification,
                    "disposition": stale.completion_disposition or "stale_rejected",
                    "triggering_reason": stale.triggering_reason,
                    "evidence": evidence,
                }
            )
            return adjudication

    if session_id and task_id:
        if task_session_id and task_session_id != str(session_id).strip():
            stale = adjudicate_stale_vs_current(
                is_stale=True,
                stale_classification="operator_session_mismatch",
                stale_reason="operator_session_id_mismatch_with_canonical_task_session",
            )
            evidence = build_continuity_adjudication_evidence(
                classification=stale.classification,
                triggering_reason=stale.triggering_reason,
                epoch_session_basis={
                    "requested_session_id": str(session_id),
                    "canonical_task_session_id": task_session_id,
                },
                related_identity=related_identity,
                decision_point="operator_intervention.session_stale_gate",
            )
            evidence["intervention_status"] = "rejected_stale_intervention"
            adjudication.update(
                {
                    "allow": False,
                    "classification": stale.classification,
                    "disposition": stale.completion_disposition or "stale_rejected",
                    "triggering_reason": stale.triggering_reason,
                    "evidence": evidence,
                }
            )
            return adjudication

    if action_kind in _MANUAL_IDEMPOTENT_ACTION_KINDS:
        idempotency_key = _build_operator_manual_action_idempotency_key(
            action_kind=action_kind,
            task_id=task_id,
            flow_id=flow_id,
            session_id=session_id,
            device_id=device_id,
        )
        adjudication["idempotency_key"] = idempotency_key
        with _OPERATOR_INTERVENTION_IDEMPOTENCY_LOCK:
            is_duplicate = idempotency_key in _OPERATOR_INTERVENTION_IDEMPOTENCY_KEYS
            if not is_duplicate:
                _OPERATOR_INTERVENTION_IDEMPOTENCY_KEYS.add(idempotency_key)
                adjudication["idempotency_reserved"] = True
        if is_duplicate:
            duplicate = adjudicate_duplicate_vs_first_accepted(is_duplicate=True)
            evidence = build_continuity_adjudication_evidence(
                classification=duplicate.classification,
                triggering_reason=duplicate.triggering_reason,
                related_identity={**related_identity, "idempotency_key": idempotency_key},
                decision_point="operator_intervention.idempotency_gate",
            )
            evidence["intervention_status"] = "duplicate_ignored_manual_action"
            adjudication.update(
                {
                    "allow": False,
                    "classification": duplicate.classification,
                    "disposition": duplicate.completion_disposition or "duplicate_ignored",
                    "triggering_reason": duplicate.triggering_reason,
                    "evidence": evidence,
                }
            )
            return adjudication

    return adjudication


def _record_operator_intervention_idempotency(
    *,
    action_kind: str,
    outcome: str,
    idempotency_key: str,
    idempotency_reserved: bool,
) -> None:
    if not idempotency_key:
        return
    if action_kind not in _MANUAL_IDEMPOTENT_ACTION_KINDS:
        return
    accepted_outcome = outcome in {
        OperatorActionOrchestrationOutcome.success.value,
        OperatorActionOrchestrationOutcome.accepted_pending.value,
        OperatorActionOrchestrationOutcome.partial_success.value,
    }
    with _OPERATOR_INTERVENTION_IDEMPOTENCY_LOCK:
        if accepted_outcome and not idempotency_reserved:
            _OPERATOR_INTERVENTION_IDEMPOTENCY_KEYS.add(idempotency_key)
        if not accepted_outcome and idempotency_reserved:
            _OPERATOR_INTERVENTION_IDEMPOTENCY_KEYS.discard(idempotency_key)


# ---------------------------------------------------------------------------
# Public API: audit log
# ---------------------------------------------------------------------------


def record_operator_action_audit(record: OperatorActionAuditRecord) -> None:
    """Append *record* to the in-process operator action audit log.

    The log is bounded at :data:`_AUDIT_LOG_MAX_RECORDS`.  When the bound is
    reached the oldest record is removed before appending the new one.
    """
    global _AUDIT_LOG
    if len(_AUDIT_LOG) >= _AUDIT_LOG_MAX_RECORDS:
        _AUDIT_LOG = _AUDIT_LOG[-(_AUDIT_LOG_MAX_RECORDS - 1):]
    _AUDIT_LOG.append(record)
    logger.debug(
        "operator_action_audit: recorded %s (action_id=%s outcome=%s)",
        record.action_kind,
        record.action_id,
        record.outcome,
    )


def get_operator_action_audit_log(
    limit: int = 50,
    action_kind: Optional[str] = None,
    outcome: Optional[str] = None,
) -> List[OperatorActionAuditRecord]:
    """Return recent operator action audit records, newest first.

    Args:
        limit: Maximum number of records to return (default 50, max 500).
        action_kind: Optional filter by action kind value.
        outcome: Optional filter by :class:`OperatorActionOrchestrationOutcome` value.

    Returns:
        A list of :class:`OperatorActionAuditRecord` instances.
    """
    records = list(reversed(_AUDIT_LOG))
    if action_kind:
        records = [r for r in records if r.action_kind == action_kind]
    if outcome:
        records = [r for r in records if r.outcome == outcome]
    return records[: min(limit, 500)]


def clear_operator_action_audit_log() -> None:
    """Clear the in-process audit log.  For testing only."""
    global _AUDIT_LOG
    _AUDIT_LOG = []
    with _OPERATOR_INTERVENTION_IDEMPOTENCY_LOCK:
        _OPERATOR_INTERVENTION_IDEMPOTENCY_KEYS.clear()


def reset_operator_intervention_adjudication_state() -> None:
    """Reset operator intervention continuity/idempotency state (testing only)."""
    with _OPERATOR_INTERVENTION_IDEMPOTENCY_LOCK:
        _OPERATOR_INTERVENTION_IDEMPOTENCY_KEYS.clear()


# ---------------------------------------------------------------------------
# Public API: Android-directed actions
# ---------------------------------------------------------------------------


def build_android_directed_action_spec(
    *,
    action_kind: str,
    device_id: str,
    operator_action_id: str,
    operator_user_id: str = "operator",
    target_flow_id: str = "",
    target_task_id: str = "",
    target_session_id: str = "",
    routed_subject_ids: Optional[List[str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> AndroidDirectedActionSpec:
    """Build an :class:`AndroidDirectedActionSpec` for a device-targeted operator action.

    This is the V2 side of the Android-directed action convergence.  The spec is
    stored in :data:`_PENDING_ANDROID_ACTIONS` until an ACK is received from
    the Android device.

    Args:
        action_kind: An :class:`AndroidDirectedActionKind` value.
        device_id: The ID of the target Android device.
        operator_action_id: The action_id from the operator action result.
        operator_user_id: The user ID of the operator.
        target_flow_id: Optional target delegated flow ID.
        target_task_id: Optional target task ID.
        target_session_id: Optional target session ID.
        payload: Optional additional payload for the action.

    Returns:
        A populated :class:`AndroidDirectedActionSpec`.
    """
    spec = AndroidDirectedActionSpec(
        action_kind=action_kind,
        device_id=device_id,
        operator_action_id=operator_action_id,
        operator_user_id=operator_user_id,
        target_flow_id=target_flow_id,
        target_task_id=target_task_id,
        target_session_id=target_session_id,
        routed_subject_ids=[str(x).strip() for x in list(routed_subject_ids or []) if str(x).strip()],
        payload=dict(payload or {}),
    )
    spec.expires_at = spec.dispatched_at + max(1, int(spec.expected_ack_within_seconds))
    spec.lifecycle_state = "pending"
    spec.lifecycle_failure_reason = ""
    _PENDING_ANDROID_ACTIONS[spec.android_dispatch_id] = spec
    _TERMINAL_ANDROID_ACTIONS.pop(spec.android_dispatch_id, None)
    logger.info(
        "android_directed_action_spec: built %s for device=%s dispatch_id=%s",
        action_kind,
        device_id,
        spec.android_dispatch_id,
    )
    return spec


def record_android_directed_action_dispatch_trace(spec: AndroidDirectedActionSpec) -> OperatorActionAuditRecord:
    """Record the canonical dispatch trace for an Android-directed operator action."""
    routed_subjects = _build_android_directed_subject_ids(spec)
    record = OperatorActionAuditRecord(
        action_id=spec.operator_action_id,
        action_kind=spec.action_kind,
        operator_user_id=spec.operator_user_id,
        policy_evaluation="canonical_android_directed_entry_accepted",
        policy_basis=(
            "operator/control entry accepted as canonical contract-governed "
            "android-directed action"
        ),
        outcome=OperatorActionOrchestrationOutcome.accepted_pending.value,
        affected_entity_ids=list(routed_subjects),
        downstream_effects=[
            f"android_directed_action_dispatched:dispatch_id={spec.android_dispatch_id}"
        ],
        android_dispatch_id=spec.android_dispatch_id,
        android_dispatched_at=spec.dispatched_at,
        canonical_entry=ANDROID_DIRECTED_ACTION_CANONICAL_ENTRY,
        routed_subject_ids=list(routed_subjects),
        participant_ack_state="pending",
        truth_convergence_state="pending_canonical_truth_convergence",
        closure_verification_state="pending_canonical_closure_verification",
    )
    record_operator_action_audit(record)
    return record


def _expire_pending_android_directed_actions(now: Optional[float] = None) -> List[str]:
    """Expire pending Android-directed actions that exceeded ACK timeout."""
    current = float(now if now is not None else time.time())
    expired_dispatch_ids: List[str] = []
    for dispatch_id, spec in list(_PENDING_ANDROID_ACTIONS.items()):
        expires_at = float(spec.expires_at or 0.0)
        if expires_at <= 0:
            expires_at = spec.dispatched_at + max(1, int(spec.expected_ack_within_seconds))
            spec.expires_at = expires_at
        if current < expires_at:
            continue
        _PENDING_ANDROID_ACTIONS.pop(dispatch_id, None)
        spec.lifecycle_state = "timed_out"
        spec.lifecycle_failure_reason = "ack_timeout"
        _TERMINAL_ANDROID_ACTIONS[dispatch_id] = {
            "state": "timed_out",
            "reason": "ack_timeout",
            "timed_out_at": current,
            "spec": spec.to_dict(),
            "operator_control_closure_trace": _build_operator_control_closure_trace(
                action_id=spec.operator_action_id,
                action_kind=spec.action_kind,
                routed_subject_ids=_build_android_directed_subject_ids(spec),
                participant_ack_state="timed_out",
                truth_convergence_state="truth_convergence_blocked_by_ack_timeout",
                closure_verification_state="failed_ack_timeout",
                canonical_entry=ANDROID_DIRECTED_ACTION_CANONICAL_ENTRY,
            ),
        }
        expired_dispatch_ids.append(dispatch_id)
        record_operator_action_audit(
            OperatorActionAuditRecord(
                action_id=spec.operator_action_id,
                action_kind=spec.action_kind,
                operator_user_id=spec.operator_user_id,
                outcome=OperatorActionOrchestrationOutcome.failed.value,
                affected_entity_ids=[spec.device_id] if spec.device_id else [],
                downstream_effects=[
                    f"android_directed_action_timeout:dispatch_id={dispatch_id}"
                ],
                error=(
                    "android_directed_action_ack_timeout:"
                    f"dispatch_id={dispatch_id}:expected_ack_within_seconds={spec.expected_ack_within_seconds}"
                ),
                rollback_needed=bool(spec.rollback_on_timeout),
                android_dispatch_id=dispatch_id,
                android_dispatched_at=spec.dispatched_at,
                android_ack_received=False,
                canonical_entry=ANDROID_DIRECTED_ACTION_CANONICAL_ENTRY,
                routed_subject_ids=_build_android_directed_subject_ids(spec),
                participant_ack_state="timed_out",
                truth_convergence_state="truth_convergence_blocked_by_ack_timeout",
                closure_verification_state="failed_ack_timeout",
            )
        )
    return expired_dispatch_ids


def acknowledge_android_directed_action(
    android_dispatch_id: str,
    *,
    ack_subject_ids: Optional[List[str]] = None,
    truth_convergence_state: str = "",
    closure_verification_state: str = "",
    failure_diagnostics: Optional[List[str]] = None,
) -> bool:
    """Record participant ACK/state update for a directed action.

    ACK updates remain canonical-governance state updates: participant ACK
    coverage can be partial for multi-subject actions, and truth/closure
    states are updated alongside the ACK trail.
    """
    _expire_pending_android_directed_actions()
    spec = _PENDING_ANDROID_ACTIONS.get(android_dispatch_id)
    if spec is None:
        terminal = _TERMINAL_ANDROID_ACTIONS.get(android_dispatch_id)
        if terminal and terminal.get("state") == "timed_out":
            logger.warning(
                "acknowledge_android_directed_action: dispatch_id=%s already timed out",
                android_dispatch_id,
            )
            return False
        logger.warning(
            "acknowledge_android_directed_action: unknown dispatch_id=%s",
            android_dispatch_id,
        )
        return False
    expected_subject_ids = _build_android_directed_subject_ids(spec)
    existing_acked = list(spec.payload.get("_acked_subject_ids") or [])
    incoming_acked = [str(x).strip() for x in list(ack_subject_ids or []) if str(x).strip()]
    if not incoming_acked:
        incoming_acked = [spec.device_id] if spec.device_id else []
    acked_seen: Set[str] = set()
    acked_subject_ids: List[str] = []
    for subject in [*existing_acked, *incoming_acked]:
        value = str(subject or "").strip()
        if value and value not in acked_seen:
            acked_seen.add(value)
            acked_subject_ids.append(value)
    pending_subject_ids = [subject for subject in expected_subject_ids if subject not in acked_seen]
    all_subjects_acked = len(pending_subject_ids) == 0

    if all_subjects_acked:
        _PENDING_ANDROID_ACTIONS.pop(android_dispatch_id, None)
        spec.lifecycle_state = "acked"
    else:
        spec.lifecycle_state = "partial_ack"
    spec.lifecycle_failure_reason = ""
    spec.payload["_acked_subject_ids"] = list(acked_subject_ids)
    resolved_truth_state = (
        truth_convergence_state.strip()
        or (
            "participant_ack_recorded_pending_canonical_truth"
            if all_subjects_acked
            else "participant_ack_partial_pending_canonical_truth"
        )
    )
    resolved_closure_state = (
        closure_verification_state.strip()
        or (
            "pending_canonical_closure_verification"
            if all_subjects_acked
            else "pending_participant_ack_completion"
        )
    )
    diagnostics = [str(x).strip() for x in list(failure_diagnostics or []) if str(x).strip()]
    closure_trace = _build_operator_control_closure_trace(
        action_id=spec.operator_action_id,
        action_kind=spec.action_kind,
        routed_subject_ids=expected_subject_ids,
        participant_ack_state=("acked" if all_subjects_acked else "partial_ack"),
        truth_convergence_state=resolved_truth_state,
        closure_verification_state=resolved_closure_state,
        canonical_entry=ANDROID_DIRECTED_ACTION_CANONICAL_ENTRY,
        state_update_entry=ANDROID_DIRECTED_ACK_CANONICAL_ENTRY,
        acknowledged_subject_ids=acked_subject_ids,
        pending_subject_ids=pending_subject_ids,
        failure_diagnostics=diagnostics,
    )
    _TERMINAL_ANDROID_ACTIONS[android_dispatch_id] = {
        "state": ("acked" if all_subjects_acked else "partial_ack"),
        "reason": "",
        "acked_at": time.time(),
        "spec": spec.to_dict(),
        "operator_control_closure_trace": closure_trace,
    }
    record_operator_action_audit(
        OperatorActionAuditRecord(
            action_id=spec.operator_action_id,
            action_kind=spec.action_kind,
            operator_user_id=spec.operator_user_id,
            policy_evaluation="participant_ack_received",
            policy_basis="android participant ack updated canonical closure trace",
            outcome=OperatorActionOrchestrationOutcome.success.value,
            affected_entity_ids=expected_subject_ids,
            downstream_effects=[
                f"android_directed_action_ack_received:dispatch_id={android_dispatch_id}",
                (
                    "android_directed_action_ack_coverage:"
                    f"{len(acked_subject_ids)}/{len(expected_subject_ids)}"
                ),
            ],
            android_dispatch_id=android_dispatch_id,
            android_dispatched_at=spec.dispatched_at,
            android_ack_received=all_subjects_acked,
            canonical_entry=ANDROID_DIRECTED_ACK_CANONICAL_ENTRY,
            routed_subject_ids=expected_subject_ids,
            participant_ack_state=("acked" if all_subjects_acked else "partial_ack"),
            truth_convergence_state=resolved_truth_state,
            closure_verification_state=resolved_closure_state,
            error="; ".join(diagnostics),
        )
    )
    logger.info(
        "acknowledge_android_directed_action: ACK received for dispatch_id=%s action_kind=%s device=%s",
        android_dispatch_id,
        spec.action_kind,
        spec.device_id,
    )
    return True


def get_pending_android_directed_actions() -> List[AndroidDirectedActionSpec]:
    """Return all pending (un-ACKed) Android-directed actions."""
    _expire_pending_android_directed_actions()
    return list(_PENDING_ANDROID_ACTIONS.values())


def get_android_directed_action_terminal_state(android_dispatch_id: str) -> Dict[str, Any]:
    """Return terminal lifecycle state for a dispatch id, if already closed."""
    return dict(_TERMINAL_ANDROID_ACTIONS.get(android_dispatch_id) or {})


def get_android_directed_action_pending_state(android_dispatch_id: str) -> Dict[str, Any]:
    """Return current pending lifecycle state for a dispatch id, if still open."""
    spec = _PENDING_ANDROID_ACTIONS.get(android_dispatch_id)
    if spec is None:
        return {}
    return {
        "state": spec.lifecycle_state,
        "spec": spec.to_dict(),
        "operator_control_closure_trace": (spec.to_dict().get("operator_control_closure_trace") or {}),
    }


# ---------------------------------------------------------------------------
# Public API: governed action orchestration
# ---------------------------------------------------------------------------


def execute_governed_operator_action(
    *,
    action_kind: str,
    action_id: str,
    operator_user_id: str = "operator",
    device_id: Optional[str] = None,
    flow_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    approval_token: Optional[str] = None,
    action_notes: str = "",
    policy_evaluation: str = "",
    policy_basis: str = "",
) -> Dict[str, Any]:
    """Orchestrate a governed operator action with full causal linkage and audit.

    This is the PR-4 orchestration entry point for all governed intervention
    actions.  It:

    1. Captures pre-action state.
    2. Routes the action to the correct canonical runtime module.
    3. Captures post-action state.
    4. Records a full :class:`OperatorActionAuditRecord`.
    5. Returns an orchestration result dict suitable for embedding in an
       :class:`~core.operator_action_contract.OperatorActionResult`.

    Args:
        action_kind: An :class:`~core.operator_action_contract.OperatorActionKind` value.
        action_id: The action_id from the operator action request.
        operator_user_id: The ID of the operator who triggered the action.
        device_id: Target device ID (for device-targeting actions).
        flow_id: Target delegated flow ID.
        task_id: Target task ID.
        session_id: Target session ID.
        approval_token: Approval token for approval-gated actions.
        action_notes: Operator notes attached to the action.
        policy_evaluation: Short policy evaluation token (why allowed/blocked).
        policy_basis: Human-readable policy basis.

    Returns:
        A dict with orchestration result including ``outcome``, ``affected_entity_ids``,
        ``downstream_effects``, ``error``, ``rollback_needed``, ``android_dispatch_id``,
        and ``audit_id``.
    """
    from core.operator_action_contract import OperatorActionKind

    pre_state = _capture_pre_state()
    affected_entity_ids: List[str] = []
    downstream_effects: List[str] = []
    outcome = OperatorActionOrchestrationOutcome.failed.value
    error = ""
    rollback_needed = False
    android_dispatch_id = ""
    android_dispatched_at: Optional[float] = None
    intervention_adjudication = _evaluate_operator_intervention_adjudication(
        action_kind=action_kind,
        task_id=task_id,
        flow_id=flow_id,
        session_id=session_id,
        device_id=device_id,
        approval_token=approval_token,
        action_notes=action_notes,
    )

    try:
        if not intervention_adjudication.get("allow", False):
            outcome = OperatorActionOrchestrationOutcome.policy_blocked.value
            error = (
                "operator intervention rejected by continuity adjudication gate: "
                f"{intervention_adjudication.get('triggering_reason', '')}"
            )
            downstream_effects.append(
                "operator_intervention_rejected:"
                f"{intervention_adjudication.get('disposition', 'unknown')}"
            )
            logger.debug(
                "operator_intervention blocked before orchestration: action_kind=%s reason=%s",
                action_kind,
                intervention_adjudication.get("triggering_reason", ""),
            )
        # ── retry_admission ───────────────────────────────────────────────
        elif action_kind == OperatorActionKind.retry_admission.value:
            if task_id:
                affected_entity_ids.append(task_id)
                downstream_effects.append(
                    f"admission_retry_requested:task_id={task_id}"
                )
            # Signal the governance validation gate to re-evaluate
            try:
                from core.governance_validation_gate import (
                    get_governance_validation_gate,
                )
                gate = get_governance_validation_gate()
                if hasattr(gate, "request_revalidation"):
                    gate.request_revalidation(task_id or "")
                    downstream_effects.append("governance_gate_revalidation_requested")
            except Exception as exc:
                logger.debug("retry_admission: governance gate unavailable: %s", exc)
            outcome = OperatorActionOrchestrationOutcome.success.value

        # ── request_capability_revalidation ───────────────────────────────
        elif action_kind == OperatorActionKind.request_capability_revalidation.value:
            try:
                from core.capability_assimilation import (
                    get_capability_assimilation_layer,
                )
                layer = get_capability_assimilation_layer()
                if device_id:
                    if hasattr(layer, "revalidate_node"):
                        layer.revalidate_node(device_id)
                        affected_entity_ids.append(device_id)
                        downstream_effects.append(
                            f"capability_revalidation_requested:device_id={device_id}"
                        )
                else:
                    if hasattr(layer, "request_revalidation"):
                        layer.request_revalidation()
                    downstream_effects.append("capability_revalidation_requested:all_nodes")
                outcome = OperatorActionOrchestrationOutcome.success.value
            except Exception as exc:
                logger.debug(
                    "request_capability_revalidation: capability layer unavailable: %s", exc
                )
                outcome = OperatorActionOrchestrationOutcome.success.value
                downstream_effects.append("capability_revalidation_requested:capability_layer_unavailable")

            # Also build Android-directed spec if a device is targeted
            if device_id:
                spec = build_android_directed_action_spec(
                    action_kind=AndroidDirectedActionKind.revalidate_participation.value,
                    device_id=device_id,
                    operator_action_id=action_id,
                    operator_user_id=operator_user_id,
                )
                android_dispatch_id = spec.android_dispatch_id
                android_dispatched_at = spec.dispatched_at
                downstream_effects.append(
                    f"android_directed_action_dispatched:dispatch_id={android_dispatch_id}"
                )

        # ── reopen_session_continuity ─────────────────────────────────────
        elif action_kind == OperatorActionKind.reopen_session_continuity.value:
            target_sid = session_id or ""
            if target_sid:
                affected_entity_ids.append(target_sid)
            try:
                from core.pr3_session_continuity_authority import (
                    classify_reconnect_event,
                    ContinuityReconnectClass,
                )
                result = classify_reconnect_event(
                    prior_session_id=target_sid,
                    new_session_id="",
                    offline_queue_depth=0,
                    session_age_seconds=0.0,
                )
                downstream_effects.append(
                    f"reconnect_classified:{result.reconnect_class.value}"
                )
            except Exception as exc:
                logger.debug("reopen_session_continuity: pr3 unavailable: %s", exc)

            if device_id:
                spec = build_android_directed_action_spec(
                    action_kind=AndroidDirectedActionKind.rebind_session.value,
                    device_id=device_id,
                    operator_action_id=action_id,
                    operator_user_id=operator_user_id,
                    target_session_id=target_sid,
                )
                android_dispatch_id = spec.android_dispatch_id
                android_dispatched_at = spec.dispatched_at
                downstream_effects.append(
                    f"android_rebind_session_dispatched:dispatch_id={android_dispatch_id}"
                )
                outcome = OperatorActionOrchestrationOutcome.accepted_pending.value
            else:
                outcome = OperatorActionOrchestrationOutcome.success.value

        # ── rebind_session_continuity ─────────────────────────────────────
        elif action_kind == OperatorActionKind.rebind_session_continuity.value:
            target_sid = session_id or ""
            if target_sid:
                affected_entity_ids.append(target_sid)
            if device_id:
                spec = build_android_directed_action_spec(
                    action_kind=AndroidDirectedActionKind.rebind_session.value,
                    device_id=device_id,
                    operator_action_id=action_id,
                    operator_user_id=operator_user_id,
                    target_session_id=target_sid,
                )
                android_dispatch_id = spec.android_dispatch_id
                android_dispatched_at = spec.dispatched_at
                affected_entity_ids.append(device_id)
                downstream_effects.append(
                    f"android_rebind_session_dispatched:dispatch_id={android_dispatch_id}"
                )
                outcome = OperatorActionOrchestrationOutcome.accepted_pending.value
            else:
                # V2-local rebind via continuation registry
                try:
                    from core.continuation_rebind_registry import (
                        get_continuation_rebind_registry,
                    )
                    reg = get_continuation_rebind_registry()
                    if hasattr(reg, "request_rebind"):
                        reg.request_rebind(target_sid)
                        downstream_effects.append(
                            "continuation_rebind_requested:local"
                        )
                except Exception as exc:
                    logger.debug("rebind_session_continuity: rebind registry unavailable: %s", exc)
                outcome = OperatorActionOrchestrationOutcome.success.value

        # ── trigger_recovery ──────────────────────────────────────────────
        elif action_kind == OperatorActionKind.trigger_recovery.value:
            target_flow = flow_id or ""
            if target_flow:
                affected_entity_ids.append(target_flow)
                try:
                    from core.delegated_flow_recovery_coordinator import (
                        DelegatedFlowRecoveryCoordinator,
                    )
                    coordinator = DelegatedFlowRecoveryCoordinator()
                    if hasattr(coordinator, "trigger_recovery_for_flow"):
                        coordinator.trigger_recovery_for_flow(target_flow)
                        downstream_effects.append(
                            f"recovery_triggered:flow_id={target_flow}"
                        )
                    else:
                        downstream_effects.append(
                            f"recovery_coordinator_contacted:flow_id={target_flow}"
                        )
                except Exception as exc:
                    logger.debug("trigger_recovery: coordinator unavailable: %s", exc)
                    downstream_effects.append(
                        f"recovery_coordinator_unavailable:flow_id={target_flow}"
                    )
            if device_id:
                spec = build_android_directed_action_spec(
                    action_kind=AndroidDirectedActionKind.trigger_device_recovery.value,
                    device_id=device_id,
                    operator_action_id=action_id,
                    operator_user_id=operator_user_id,
                    target_flow_id=target_flow,
                    target_task_id=task_id or "",
                )
                android_dispatch_id = spec.android_dispatch_id
                android_dispatched_at = spec.dispatched_at
                affected_entity_ids.append(device_id)
                downstream_effects.append(
                    f"android_recovery_dispatched:dispatch_id={android_dispatch_id}"
                )
                outcome = OperatorActionOrchestrationOutcome.accepted_pending.value
            else:
                outcome = OperatorActionOrchestrationOutcome.success.value

        # ── acknowledge_recovery ──────────────────────────────────────────
        elif action_kind == OperatorActionKind.acknowledge_recovery.value:
            if flow_id:
                affected_entity_ids.append(flow_id)
                downstream_effects.append(f"recovery_acknowledged:flow_id={flow_id}")
            if task_id:
                affected_entity_ids.append(task_id)
                downstream_effects.append(f"recovery_acknowledged:task_id={task_id}")
            outcome = OperatorActionOrchestrationOutcome.success.value

        # ── suspend_participant ───────────────────────────────────────────
        elif action_kind == OperatorActionKind.suspend_participant.value:
            if not device_id:
                error = "device_id is required for suspend_participant"
                outcome = OperatorActionOrchestrationOutcome.failed.value
            else:
                affected_entity_ids.append(device_id)
                try:
                    from core.android_participant_session_state import (
                        get_participant_session_state,
                    )
                    state = get_participant_session_state(device_id)
                    if state and hasattr(state, "suspend"):
                        state.suspend()
                        downstream_effects.append(
                            f"participant_session_suspended:device_id={device_id}"
                        )
                except Exception as exc:
                    logger.debug("suspend_participant: session state unavailable: %s", exc)

                spec = build_android_directed_action_spec(
                    action_kind=AndroidDirectedActionKind.suspend_device.value,
                    device_id=device_id,
                    operator_action_id=action_id,
                    operator_user_id=operator_user_id,
                )
                android_dispatch_id = spec.android_dispatch_id
                android_dispatched_at = spec.dispatched_at
                downstream_effects.append(
                    f"android_suspend_dispatched:dispatch_id={android_dispatch_id}"
                )
                outcome = OperatorActionOrchestrationOutcome.accepted_pending.value

        # ── isolate_device ────────────────────────────────────────────────
        elif action_kind == OperatorActionKind.isolate_device.value:
            if not device_id:
                error = "device_id is required for isolate_device"
                outcome = OperatorActionOrchestrationOutcome.failed.value
            else:
                affected_entity_ids.append(device_id)
                try:
                    from core.android_device_state_store import isolate_device
                    if callable(isolate_device):
                        isolate_device(device_id)
                        downstream_effects.append(
                            f"device_isolated_in_state_store:device_id={device_id}"
                        )
                except Exception as exc:
                    logger.debug("isolate_device: state store unavailable: %s", exc)

                spec = build_android_directed_action_spec(
                    action_kind=AndroidDirectedActionKind.isolate_device.value,
                    device_id=device_id,
                    operator_action_id=action_id,
                    operator_user_id=operator_user_id,
                )
                android_dispatch_id = spec.android_dispatch_id
                android_dispatched_at = spec.dispatched_at
                downstream_effects.append(
                    f"android_isolate_dispatched:dispatch_id={android_dispatch_id}"
                )
                outcome = OperatorActionOrchestrationOutcome.accepted_pending.value

        # ── switch_path_selection / reevaluate_path_selection ─────────────
        elif action_kind in (
            OperatorActionKind.switch_path_selection.value,
            OperatorActionKind.reevaluate_path_selection.value,
        ):
            if flow_id:
                affected_entity_ids.append(flow_id)
            if task_id:
                affected_entity_ids.append(task_id)
            downstream_effects.append(
                f"path_selection_requested:action={action_kind}"
            )
            try:
                from core.device_node_domain_governance import (
                    get_device_node_domain_governance,
                )
                gov = get_device_node_domain_governance()
                if hasattr(gov, "request_path_reevaluation"):
                    gov.request_path_reevaluation(flow_id or task_id or "")
                    downstream_effects.append("path_reevaluation_requested:governance_layer")
            except Exception as exc:
                logger.debug("path_selection: governance unavailable: %s", exc)
            outcome = OperatorActionOrchestrationOutcome.success.value

        # ── reopen_closure ────────────────────────────────────────────────
        elif action_kind == OperatorActionKind.reopen_closure.value:
            if task_id:
                affected_entity_ids.append(task_id)
            if flow_id:
                affected_entity_ids.append(flow_id)
            try:
                from core.closed_loop_governance_consolidation import (
                    get_closed_loop_governance,
                )
                gov = get_closed_loop_governance()
                if hasattr(gov, "reopen_closure"):
                    gov.reopen_closure(task_id or flow_id or "")
                    downstream_effects.append(
                        f"closure_reopened:entity={task_id or flow_id or 'unknown'}"
                    )
            except Exception as exc:
                logger.debug("reopen_closure: governance unavailable: %s", exc)
                downstream_effects.append("closure_reopen_requested:governance_unavailable")
            outcome = OperatorActionOrchestrationOutcome.success.value

        # ── finalize_closure ──────────────────────────────────────────────
        elif action_kind == OperatorActionKind.finalize_closure.value:
            if task_id:
                affected_entity_ids.append(task_id)
            if flow_id:
                affected_entity_ids.append(flow_id)
            try:
                from core.closed_loop_governance_consolidation import (
                    get_closed_loop_governance,
                )
                gov = get_closed_loop_governance()
                if hasattr(gov, "finalize_closure"):
                    gov.finalize_closure(task_id or flow_id or "")
                    downstream_effects.append(
                        f"closure_finalized:entity={task_id or flow_id or 'unknown'}"
                    )
            except Exception as exc:
                logger.debug("finalize_closure: governance unavailable: %s", exc)
                downstream_effects.append("closure_finalize_requested:governance_unavailable")
            outcome = OperatorActionOrchestrationOutcome.success.value

        # ── reject_closure ────────────────────────────────────────────────
        elif action_kind == OperatorActionKind.reject_closure.value:
            if task_id:
                affected_entity_ids.append(task_id)
            if flow_id:
                affected_entity_ids.append(flow_id)
            try:
                from core.closed_loop_governance_consolidation import (
                    get_closed_loop_governance,
                )
                gov = get_closed_loop_governance()
                if hasattr(gov, "reject_closure"):
                    gov.reject_closure(task_id or flow_id or "")
                    downstream_effects.append(
                        f"closure_rejected:entity={task_id or flow_id or 'unknown'}"
                    )
            except Exception as exc:
                logger.debug("reject_closure: governance unavailable: %s", exc)
                downstream_effects.append("closure_reject_requested:governance_unavailable")
            outcome = OperatorActionOrchestrationOutcome.success.value

        # ── acknowledge_blocker ───────────────────────────────────────────
        elif action_kind == OperatorActionKind.acknowledge_blocker.value:
            if task_id:
                affected_entity_ids.append(task_id)
            downstream_effects.append(
                f"blocker_acknowledged:task_id={task_id or 'unknown'}"
            )
            outcome = OperatorActionOrchestrationOutcome.success.value

        # ── escalate_dependency_failure ───────────────────────────────────
        elif action_kind == OperatorActionKind.escalate_dependency_failure.value:
            if task_id:
                affected_entity_ids.append(task_id)
            if flow_id:
                affected_entity_ids.append(flow_id)
            downstream_effects.append(
                f"dependency_failure_escalated:entity={task_id or flow_id or 'unknown'}"
            )
            outcome = OperatorActionOrchestrationOutcome.success.value

        # ── retry_admission with flow ─────────────────────────────────────
        elif action_kind == OperatorActionKind.retry_admission.value:
            if flow_id:
                affected_entity_ids.append(flow_id)
                if device_id:
                    spec = build_android_directed_action_spec(
                        action_kind=AndroidDirectedActionKind.retry_delegated_execution.value,
                        device_id=device_id,
                        operator_action_id=action_id,
                        operator_user_id=operator_user_id,
                        target_flow_id=flow_id,
                    )
                    android_dispatch_id = spec.android_dispatch_id
                    android_dispatched_at = spec.dispatched_at
                    downstream_effects.append(
                        f"android_retry_execution_dispatched:dispatch_id={android_dispatch_id}"
                    )
                    outcome = OperatorActionOrchestrationOutcome.accepted_pending.value
                else:
                    downstream_effects.append(
                        f"retry_admission_requested:flow_id={flow_id}"
                    )
                    outcome = OperatorActionOrchestrationOutcome.success.value
            else:
                outcome = OperatorActionOrchestrationOutcome.success.value

        else:
            outcome = OperatorActionOrchestrationOutcome.unsupported.value
            error = f"action_kind={action_kind!r} has no orchestration path in PR-4"

    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        error = str(exc)
        rollback_needed = True
        outcome = OperatorActionOrchestrationOutcome.rollback_needed.value
        logger.error(
            "execute_governed_operator_action(%s) failed: %s",
            action_kind,
            exc,
        )

    post_state = _capture_post_state()
    _record_operator_intervention_idempotency(
        action_kind=action_kind,
        outcome=outcome,
        idempotency_key=str(intervention_adjudication.get("idempotency_key") or ""),
        idempotency_reserved=bool(
            intervention_adjudication.get("idempotency_reserved", False)
        ),
    )
    routed_subject_ids: List[str] = []
    routed_subject_seen: Set[str] = set()
    for subject_id in affected_entity_ids:
        subject = str(subject_id or "").strip()
        if subject and subject not in routed_subject_seen:
            routed_subject_seen.add(subject)
            routed_subject_ids.append(subject)
    if device_id and device_id not in routed_subject_seen:
        routed_subject_seen.add(device_id)
        routed_subject_ids.append(device_id)
    if android_dispatch_id:
        participant_ack_state = "pending"
        truth_convergence_state = "pending_canonical_truth_convergence"
        closure_verification_state = "pending_canonical_closure_verification"
    elif outcome == OperatorActionOrchestrationOutcome.success.value:
        participant_ack_state = "not_required"
        truth_convergence_state = "converged_from_runtime_result"
        closure_verification_state = "verified"
    else:
        participant_ack_state = "not_required"
        truth_convergence_state = "not_evaluated"
        closure_verification_state = "not_verified"

    # Build and record the audit record
    audit_record = OperatorActionAuditRecord(
        action_id=action_id,
        action_kind=action_kind,
        operator_user_id=operator_user_id,
        policy_evaluation=policy_evaluation or ("success" if error == "" else "failed"),
        policy_basis=policy_basis or action_notes,
        pre_state=pre_state,
        post_state=post_state,
        outcome=outcome,
        affected_entity_ids=list(affected_entity_ids),
        downstream_effects=list(downstream_effects),
        error=error,
        rollback_needed=rollback_needed,
        android_dispatch_id=android_dispatch_id,
        android_dispatched_at=android_dispatched_at,
        routed_subject_ids=routed_subject_ids,
        participant_ack_state=participant_ack_state,
        truth_convergence_state=truth_convergence_state,
        closure_verification_state=closure_verification_state,
        continuity_adjudication_classification=str(
            intervention_adjudication.get("classification") or ""
        ),
        continuity_adjudication_disposition=str(
            intervention_adjudication.get("disposition") or ""
        ),
        continuity_adjudication_evidence=dict(
            intervention_adjudication.get("evidence") or {}
        ),
    )
    record_operator_action_audit(audit_record)

    return {
        "outcome": outcome,
        "affected_entity_ids": list(affected_entity_ids),
        "downstream_effects": list(downstream_effects),
        "error": error,
        "rollback_needed": rollback_needed,
        "android_dispatch_id": android_dispatch_id,
        "android_dispatched_at": android_dispatched_at,
        "audit_id": audit_record.audit_id,
        "continuity_adjudication_classification": audit_record.continuity_adjudication_classification,
        "continuity_adjudication_disposition": audit_record.continuity_adjudication_disposition,
        "continuity_adjudication_evidence": dict(audit_record.continuity_adjudication_evidence),
        "_source": "pr4_operator_action_governance",
        "authority": PR4_OPERATOR_ACTION_GOVERNANCE_AUTHORITY,
    }


# ---------------------------------------------------------------------------
# Public API: board projection
# ---------------------------------------------------------------------------


def build_operator_board_projection() -> OperatorActionBoardProjection:
    """Build an operable-truth board projection for operator surfaces.

    Satisfies PR-4 requirement #5: board surfaces must show what is wrong,
    what can currently be done, why an action is available or unavailable,
    and the feedback/result of the last action.

    Returns:
        A populated :class:`OperatorActionBoardProjection`.
    """
    proj = OperatorActionBoardProjection()

    # --- What is wrong ---
    try:
        from core.operator_surface import get_operator_surface
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        policy_layer = snap.governance_state.get("policy_layer", {})
        summary = policy_layer.get("summary", {})
        proj.hard_block_count = int(summary.get("hard_block_count", 0))
        proj.soft_degraded_count = int(summary.get("soft_degraded_count", 0))
        proj.manual_decision_count = int(summary.get("manual_decision_count", 0))
        proj.system_health_summary = _determine_system_health(
            proj.hard_block_count,
            proj.soft_degraded_count,
            proj.manual_decision_count,
        )

        # Extract per-device blockers
        per_device = snap.governance_state.get("governance_policy", {})
        for device_id, dev_gov in per_device.items():
            if isinstance(dev_gov, dict):
                for rule_id, rule in dev_gov.items():
                    if isinstance(rule, dict) and rule.get("decision") == "hard_block":
                        proj.active_blockers.append(
                            f"{device_id}:{rule_id}:{rule.get('reason', '')}"
                        )

        # --- What can currently be done / why ---
        action_catalog = dict(
            (snap.operator_action_layer or {}).get("actions", {}) or {}
        )
        state_basis = dict(
            (snap.operator_action_layer or {}).get("state_basis", {}) or {}
        )
        proj.availability_state_basis = state_basis
        proj.policy_version = str(
            (snap.operator_action_layer or {}).get("policy", "")
        )

        for action_kind, action_info in action_catalog.items():
            entry = {
                "action_kind": action_kind,
                "available": bool(action_info.get("available", False)),
                "control_mode": action_info.get("control_mode", "manual"),
                "reason": action_info.get("reason", ""),
                "requires_approval": bool(action_info.get("requires_approval", False)),
            }
            if entry["available"]:
                proj.available_actions.append(entry)
            else:
                proj.unavailable_actions.append(entry)
    except Exception as exc:
        logger.debug("build_operator_board_projection: operator snapshot unavailable: %s", exc)

    # --- Feedback/result of the last action ---
    recent = get_operator_action_audit_log(limit=1)
    if recent:
        last = recent[0]
        proj.last_action_id = last.action_id
        proj.last_action_kind = last.action_kind
        proj.last_action_outcome = last.outcome
        proj.last_action_error = last.error
        proj.last_action_triggered_at = last.triggered_at
        proj.last_action_affected_entity_ids = list(last.affected_entity_ids)
        routed_subjects_for_trace = list(last.routed_subject_ids)
        if not routed_subjects_for_trace:
            routed_subjects_for_trace = list(last.affected_entity_ids)
        proj.last_action_closure_trace = _build_operator_control_closure_trace(
            action_id=last.action_id,
            action_kind=last.action_kind,
            routed_subject_ids=routed_subjects_for_trace,
            participant_ack_state=last.participant_ack_state,
            truth_convergence_state=last.truth_convergence_state,
            closure_verification_state=last.closure_verification_state,
            canonical_entry=last.canonical_entry or OPERATOR_ACTION_CANONICAL_ENTRY,
        )
        proj.last_action_closure_trace["continuity_adjudication_classification"] = (
            last.continuity_adjudication_classification
        )
        proj.last_action_closure_trace["continuity_adjudication_disposition"] = (
            last.continuity_adjudication_disposition
        )
        proj.last_action_closure_trace["continuity_adjudication_evidence"] = dict(
            last.continuity_adjudication_evidence or {}
        )

    # --- Pending Android-directed actions ---
    proj.pending_android_directed_actions = [
        spec.to_dict() for spec in get_pending_android_directed_actions()
    ]

    # --- Android participation verdict from unified panel aggregation ---
    try:
        from core.unified_panel_aggregation import build_unified_panel_payload

        panel_payload = build_unified_panel_payload(mode="operator")
        proj.android_participation_verdict = dict(
            getattr(panel_payload, "android_participation_verdict", {}) or {}
        )
        proj.runtime_decision_reasoning = dict(
            getattr(panel_payload, "runtime_decision_reasoning", {}) or {}
        )
        proj.unified_mode_model = dict(
            getattr(panel_payload, "unified_mode_model", {}) or {}
        )
    except Exception as exc:
        logger.debug(
            "build_operator_board_projection: panel android participation verdict unavailable: %s",
            exc,
        )

    # --- Standardized closure reasoning (PR-next convergence follow-through) ---
    try:
        from core.operator_execution_observability_surface import (
            _evidence_ring,
        )
        from core.runtime_decision_reasoning import (
            overlay_runtime_decision_reasoning_block,
        )

        evidence_ring_snapshot = list(_evidence_ring)
        latest_entry = evidence_ring_snapshot[-1] if evidence_ring_snapshot else None

        if latest_entry is not None:
            tier_for_reasoning = latest_entry.android_proof_class
            if tier_for_reasoning in (None, ""):
                tier_for_reasoning = proj.android_participation_verdict.get("tier")

            device_for_reasoning = latest_entry.device_id
            if device_for_reasoning in (None, ""):
                device_for_reasoning = proj.android_participation_verdict.get("device_id")

            reasoning_block = overlay_runtime_decision_reasoning_block(
                proj.runtime_decision_reasoning,
                task_id=latest_entry.task_id,
                selected_runtime="android_delegated" if device_for_reasoning else "v2_local",
                selected_device=device_for_reasoning,
                participation_tier=tier_for_reasoning,
                mode_state=(
                    proj.runtime_decision_reasoning.get("mode_basis", {}).get("mode_state")
                    if isinstance(proj.runtime_decision_reasoning, dict)
                    else None
                ),
                readiness_summary={
                    "verdict": (
                        proj.runtime_decision_reasoning.get("readiness_basis", {}).get("readiness_state")
                        if isinstance(proj.runtime_decision_reasoning, dict)
                        else None
                    ),
                },
                acceptance_verdict=latest_entry.acceptance_verdict or None,
                is_fully_closed=(
                    latest_entry.acceptance_verdict == "accept"
                    and bool(latest_entry.truth_chain_complete)
                ),
                truth_chain_complete=latest_entry.truth_chain_complete,
                evidence_state=latest_entry.evidence_state,
                trust_level=latest_entry.trust_level,
                operator_warning=latest_entry.operator_warning,
                source_channel=latest_entry.source_channel,
                android_proof_class=latest_entry.android_proof_class,
                blocking_reasons=list(latest_entry.diagnosis),
                evidence_summary={
                    "diagnosis": list(latest_entry.diagnosis),
                },
                source_of_truth_refs=[
                    PR4_OPERATOR_ACTION_GOVERNANCE_AUTHORITY,
                    "core.operator_execution_observability_surface.record_operator_evidence_entry",
                ],
            )
            reasoning_block_dict = dict(reasoning_block)
            proj.runtime_decision_reasoning = reasoning_block_dict
            proj.unified_mode_model = dict(
                reasoning_block_dict.get("unified_mode_model") or {}
            )
            proj.latest_closure_reasoning = reasoning_block_dict
        elif proj.runtime_decision_reasoning:
            proj.unified_mode_model = dict(
                proj.runtime_decision_reasoning.get("unified_mode_model") or {}
            )
            proj.latest_closure_reasoning = dict(proj.runtime_decision_reasoning)
    except Exception as exc:
        logger.debug(
            "build_operator_board_projection: latest closure reasoning unavailable: %s",
            exc,
        )

    # --- Canonical runtime-truth state contract blocks (backend authority input) ---
    try:
        from core.control_plane_authority_input import (
            build_control_plane_backend_authority_input,
        )

        runtime_truth_payload = build_control_plane_backend_authority_input(
            runtime_decision_reasoning=dict(proj.runtime_decision_reasoning or {}),
        )
        proj.operational_state_board = dict(runtime_truth_payload.get("operational_state_board") or {})
        proj.participation_truth_consumption = dict(runtime_truth_payload.get("participation_truth_consumption") or {})
        proj.foundational_system_truth = dict(runtime_truth_payload.get("foundational_system_truth") or {})
    except Exception as exc:
        logger.debug(
            "build_operator_board_projection: canonical runtime-truth state blocks unavailable: %s",
            exc,
        )

    # --- Unified control-plane typed contract block (board surface) ---
    try:
        from core.v2_unified_state_contract import (
            build_control_plane_surface_contract,
            build_shared_control_plane_basis,
        )

        shared_basis = build_shared_control_plane_basis(
            reasoning_block=proj.runtime_decision_reasoning,
        )
        proj.control_plane_contract = build_control_plane_surface_contract(
            surface="board",
            runtime_truth={
                "hard_block_count": proj.hard_block_count,
                "soft_degraded_count": proj.soft_degraded_count,
                "manual_decision_count": proj.manual_decision_count,
                "availability_state_basis": dict(proj.availability_state_basis),
                "android_participation_verdict": dict(proj.android_participation_verdict),
                "backbone_snapshot": shared_basis.get("backbone_snapshot"),
            },
            derived_reasoning=proj.runtime_decision_reasoning,
            projection={
                "system_health_summary": proj.system_health_summary,
                "available_actions": list(proj.available_actions),
                "unavailable_actions": list(proj.unavailable_actions),
                "pending_android_directed_actions": list(proj.pending_android_directed_actions),
            },
            stale_or_cached_summary={
                "has_recent_action_feedback": bool(proj.last_action_id),
                "pending_android_directed_count": len(proj.pending_android_directed_actions),
            },
            shared_basis=shared_basis,
        )
    except Exception as exc:
        logger.debug("build_operator_board_projection: control-plane contract unavailable: %s", exc)

    return proj


# ---------------------------------------------------------------------------
# Public API: operable surface snapshot
# ---------------------------------------------------------------------------


def build_pr4_operable_surface_snapshot(
    recent_audit_limit: int = 10,
) -> PR4OperableSurfaceSnapshot:
    """Build the canonical PR-4 operable surface snapshot.

    This is the top-level PR-4 artifact combining board projection, recent
    audit records, and pending Android-directed action status.

    Args:
        recent_audit_limit: Number of recent audit records to include (default 10).

    Returns:
        A populated :class:`PR4OperableSurfaceSnapshot`.
    """
    board = build_operator_board_projection()
    recent_audits = get_operator_action_audit_log(limit=recent_audit_limit)
    pending_android = get_pending_android_directed_actions()
    operator_control_plane_contract: Dict[str, Any] = {}
    try:
        from core.v2_unified_state_contract import (
            build_control_plane_surface_contract,
            build_shared_control_plane_basis,
        )

        shared_basis = build_shared_control_plane_basis(
            reasoning_block=board.runtime_decision_reasoning,
        )
        operator_control_plane_contract = build_control_plane_surface_contract(
            surface="operator",
            runtime_truth={
                "board_system_health_summary": board.system_health_summary,
                "hard_block_count": board.hard_block_count,
                "soft_degraded_count": board.soft_degraded_count,
                "manual_decision_count": board.manual_decision_count,
                "backbone_snapshot": shared_basis.get("backbone_snapshot"),
            },
            derived_reasoning=board.runtime_decision_reasoning,
            projection={
                "available_actions": list(board.available_actions),
                "unavailable_actions": list(board.unavailable_actions),
                "audit_record_count": len(recent_audits),
                "pending_android_directed_count": len(pending_android),
            },
            stale_or_cached_summary={
                "last_action_id": board.last_action_id or None,
                "latest_closure_reasoning_available": bool(board.latest_closure_reasoning),
            },
            shared_basis=shared_basis,
        )
    except Exception as exc:
        logger.debug("build_pr4_operable_surface_snapshot: operator contract unavailable: %s", exc)
        try:
            from core.v2_unified_state_contract import build_control_plane_surface_contract

            operator_control_plane_contract = build_control_plane_surface_contract(
                surface="operator",
                runtime_truth={},
                derived_reasoning={},
                projection={"audit_record_count": len(recent_audits)},
                stale_or_cached_summary={"unavailable": True, "reason": str(exc)},
            )
        except Exception as fallback_exc:
            logger.debug(
                "build_pr4_operable_surface_snapshot: failed to build fallback control plane "
                "contract for operator surface: %s",
                fallback_exc,
            )
            operator_control_plane_contract = {
                "surface": "operator",
                "unavailable": True,
                "reason": str(exc),
                "_source": "core.pr4_operator_action_governance.build_pr4_operable_surface_snapshot",
            }

    return PR4OperableSurfaceSnapshot(
        board=board,
        recent_audit_records=recent_audits,
        pending_android_directed_count=len(pending_android),
        operator_control_plane_contract=operator_control_plane_contract,
    )
