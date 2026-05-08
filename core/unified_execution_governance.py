"""core/unified_execution_governance.py
========================================
统一执行治理契约 — Unified Execution Governance Contract

背景 (Problem Statement #5)
---------------------------
Android/V2 系统已经具有三类真实存在的执行语义：

- ``goal_execution`` — Android 高层自治目标下发
- ``parallel_subtask`` — 服务器端多设备 Fan-out 协调
- ``takeover_request`` — V2 主动接管 Android 设备

其中 ``takeover_request`` 的 gate 体系（mode gate + session gate + readiness gate）
通过 ``TakeoverEligibilityAssessor`` 与 ``core.android_mode_gate_policy`` 已相对成熟。
但三类执行类型的接受条件、优先级、并发关系并不在一个统一治理模型中，存在策略层分裂风险。

本模块闭合以下空缺：

1. **统一接受条件（Acceptance Conditions）**
   为每种执行类型定义精确的接受条件，合并所有 gate 检查为一次统一调用。

2. **优先级与互斥关系（Priority & Mutual Exclusion）**
   - ``takeover_request`` 具有最高优先级（TAKEOVER > PARALLEL_SUBTASK > GOAL_EXECUTION）
   - active takeover 期间 ``goal_execution`` 和 ``parallel_subtask`` 必须被阻塞
   - 并发执行规则：同一设备同时只能有一个 takeover；goal/parallel 可并发但受资源约束

3. **取消 / 回滚 / 超时 / 失败语义（Cancellation / Rollback / Timeout / Failure）**
   - 统一的 ``CancellationReason``、``RollbackPolicy``、``TimeoutPolicy`` 枚举
   - 每种执行类型的 failure semantics（retry vs fallback vs reject）

4. **跨侧一致治理语义**
   Android 侧（AppSettings gates）与 V2 侧（mode gate policy）通过本模块形成
   一致治理语义，避免单边 patch。

设计原则
--------
- **Additive only** — 不修改现有模块，仅提供新公共 API。
- **Composing, not duplicating** — 委托给现有权威：
  ``core.android_mode_gate_policy``（mode/readiness gates）
  ``core.android_device_state_store``（runtime truth）
  ``core.attached_runtime_session_registry``（session state）
- **Non-raising** — :func:`evaluate_execution_governance` 永不 raise；错误以
  ``accepted=False`` + 详细 ``rejection_reason`` 返回。
- **JSON-serialisable** — 所有 dataclass 暴露 ``to_dict()``。

Authority sentinel
------------------
``UNIFIED_EXECUTION_GOVERNANCE_AUTHORITY`` — 导入此常量以断言本模块是统一执行
治理的权威层。

Public API
----------
Sentinels::

    UNIFIED_EXECUTION_GOVERNANCE_AUTHORITY
    UNIFIED_EXECUTION_GOVERNANCE_CONTRACT_VERSION

Enums::

    ExecutionType
    ExecutionPriority
    CancellationReason
    RollbackPolicy
    TimeoutPolicy
    FailureSemantic
    ConflictResolution

Dataclasses::

    ExecutionGovernanceVerdict
    ExecutionTypePolicy
    ExecutionConflict
    ConflictResolutionResult

Functions::

    get_execution_type_policy(execution_type)
    evaluate_execution_governance(execution_type, device_id, ...)
    resolve_execution_conflict(incoming_type, active_type, device_id)
    is_takeover_active(device_id)
    get_active_execution_type(device_id)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.UnifiedExecutionGovernance")

# ---------------------------------------------------------------------------
# Authority sentinels & contract version
# ---------------------------------------------------------------------------

UNIFIED_EXECUTION_GOVERNANCE_AUTHORITY: str = (
    "UNIFIED_EXECUTION_GOVERNANCE_V1: "
    "core.unified_execution_governance is the single, authoritative unified "
    "governance layer for all three execution types (goal_execution, "
    "parallel_subtask, takeover_request). It evaluates acceptance conditions, "
    "priority, concurrency, cancellation, rollback, timeout, and failure "
    "semantics for each type in a unified policy model. All code that needs to "
    "determine whether an execution type is accepted, or to resolve conflicts "
    "between concurrent execution types, MUST consult this module."
)

UNIFIED_EXECUTION_GOVERNANCE_CONTRACT_VERSION: str = "1.0.0"

# Policy constants referenced in governance decisions
TAKEOVER_BLOCKS_LOWER_PRIORITY: str = (
    "POLICY::TAKEOVER_MUTUAL_EXCLUSION: "
    "An active takeover_request MUST block any incoming goal_execution or "
    "parallel_subtask on the same device. Takeover has the highest execution "
    "priority (PRIORITY_1) AND sets blocks_lower_priority=True. "
    "goal_execution and parallel_subtask (PRIORITY_2, equal priority to each "
    "other) MUST be rejected with rejection_reason='active_takeover_in_progress' "
    "until the takeover completes, times out, or is explicitly cancelled."
)

PRIORITY_ORDER_POLICY: str = (
    "POLICY::EXECUTION_PRIORITY_ORDER: "
    "takeover_request (PRIORITY_1) > goal_execution (PRIORITY_2) = "
    "parallel_subtask (PRIORITY_2). goal_execution and parallel_subtask have "
    "equal numeric priority; when both are active simultaneously on the same "
    "device, the first-arrived execution wins (FIFO). Blocking of lower-priority "
    "types is governed by blocks_lower_priority=True on the takeover policy."
)

CANCELLATION_PROPAGATION_POLICY: str = (
    "POLICY::CANCELLATION_PROPAGATION: "
    "When a takeover_request is cancelled (user-cancelled, timeout, or "
    "mode-switch to local), all blocked goal_execution / parallel_subtask "
    "requests MUST be unblocked or notified. The governance layer records the "
    "cancellation reason and propagates it to blocked executions."
)

UNIFIED_EXECUTION_GOVERNANCE_SENTINEL: str = (
    "UNIFIED_EXECUTION_GOVERNANCE_SENTINEL::v1 present"
)

# ---------------------------------------------------------------------------
# ExecutionType
# ---------------------------------------------------------------------------


class ExecutionType(str, Enum):
    """Canonical execution type taxonomy for the unified governance model.

    Values
    ------
    goal_execution
        Android high-level autonomous goal dispatch.  Triggered by the
        Android ``GoalNormalizer`` → AIP v3 goal_execution message → gateway.
        V2 is the semantic authority; Android is the NL carrier.
    parallel_subtask
        Server-side multi-device fan-out coordination.  V2 dispatches a
        shared task to multiple Android devices simultaneously.  Each device
        runs an independent subtask.
    takeover_request
        V2 actively takes over an Android device for direct UI control.
        Requires mode gate + session gate + readiness gate to pass (the most
        stringent acceptance conditions of the three types).
    unknown
        Execution type could not be determined.  Used as a safe default.
    """

    goal_execution = "goal_execution"
    parallel_subtask = "parallel_subtask"
    takeover_request = "takeover_request"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "ExecutionType":
        """Return the enum member for *value*, or ``unknown`` if not found."""
        try:
            return cls(value)
        except ValueError:
            return cls.unknown


# ---------------------------------------------------------------------------
# ExecutionPriority
# ---------------------------------------------------------------------------


class ExecutionPriority(int, Enum):
    """Numeric execution priority (lower = higher priority).

    Values
    ------
    PRIORITY_1_TAKEOVER = 1
        takeover_request — highest priority.  An active takeover blocks all
        lower-priority executions on the same device.
    PRIORITY_2_PARALLEL = 2
        parallel_subtask — same priority tier as goal_execution, ordered
        after takeover_request.
    PRIORITY_2_GOAL = 2
        goal_execution — same priority as parallel_subtask.  When both are
        present simultaneously, the first one to arrive wins (FIFO).
    PRIORITY_UNKNOWN = 99
        Unknown execution type — treated as lowest priority.
    """

    PRIORITY_1_TAKEOVER = 1
    PRIORITY_2_PARALLEL = 2
    PRIORITY_2_GOAL = 2
    PRIORITY_UNKNOWN = 99


# Map ExecutionType → ExecutionPriority
_EXECUTION_TYPE_PRIORITY: Dict[ExecutionType, int] = {
    ExecutionType.takeover_request: ExecutionPriority.PRIORITY_1_TAKEOVER,
    ExecutionType.parallel_subtask: ExecutionPriority.PRIORITY_2_PARALLEL,
    ExecutionType.goal_execution: ExecutionPriority.PRIORITY_2_GOAL,
    ExecutionType.unknown: ExecutionPriority.PRIORITY_UNKNOWN,
}


# ---------------------------------------------------------------------------
# CancellationReason
# ---------------------------------------------------------------------------


class CancellationReason(str, Enum):
    """Canonical reason for execution cancellation.

    Values are stable, lowercase strings safe for serialisation.
    """

    user_cancelled = "user_cancelled"
    timeout = "timeout"
    mode_switch_to_local = "mode_switch_to_local"
    device_disconnected = "device_disconnected"
    higher_priority_execution = "higher_priority_execution"
    policy_rejected = "policy_rejected"
    operator_override = "operator_override"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# RollbackPolicy
# ---------------------------------------------------------------------------


class RollbackPolicy(str, Enum):
    """Rollback / recovery policy when an execution is cancelled or fails.

    Values
    ------
    none
        No rollback — the execution state is abandoned as-is.  Used for
        read-only or observe-only executions where side effects are minimal.
    best_effort_undo
        Attempt to undo side effects on a best-effort basis.  Failures are
        logged but not surfaced.
    required_undo
        Rollback is mandatory.  If undo fails, an error is raised / surfaced
        to the operator.
    checkpoint_restore
        Restore from the last recorded checkpoint.  Used when execution has
        been progressing incrementally and partial state is recoverable.
    notify_only
        No state change on the device; only notify V2 of the cancellation.
        Appropriate when the device controls its own undo path.
    """

    none = "none"
    best_effort_undo = "best_effort_undo"
    required_undo = "required_undo"
    checkpoint_restore = "checkpoint_restore"
    notify_only = "notify_only"


# ---------------------------------------------------------------------------
# TimeoutPolicy
# ---------------------------------------------------------------------------


class TimeoutPolicy(str, Enum):
    """Timeout policy for an execution type.

    Values
    ------
    none
        No timeout enforced by the governance layer (caller or transport is
        responsible).
    soft
        Advisory timeout — governance records the timeout event and emits a
        warning, but does not forcibly cancel.
    hard
        Hard timeout — governance cancels the execution when the deadline is
        exceeded.  Rollback policy is applied.
    """

    none = "none"
    soft = "soft"
    hard = "hard"


# ---------------------------------------------------------------------------
# FailureSemantic
# ---------------------------------------------------------------------------


class FailureSemantic(str, Enum):
    """Canonical failure response when an execution fails or is rejected.

    Values
    ------
    retry
        Retry the execution, optionally with a delay or on a different device.
        Applicable to transient failures.
    fallback_local
        Fall back to V2-local execution after the Android-side failure.
    reject_with_reason
        Reject with a structured reason — no retry or fallback.  Applicable
        when the failure is non-recoverable or policy prohibits fallback.
    escalate_to_operator
        Escalate to the operator surface for human decision.
    wait_and_requeue
        Hold the request and requeue when the blocking condition resolves.
        Used when a device is temporarily busy (e.g., active takeover).
    """

    retry = "retry"
    fallback_local = "fallback_local"
    reject_with_reason = "reject_with_reason"
    escalate_to_operator = "escalate_to_operator"
    wait_and_requeue = "wait_and_requeue"


# ---------------------------------------------------------------------------
# ConflictResolution
# ---------------------------------------------------------------------------


class ConflictResolution(str, Enum):
    """Resolution strategy when two execution types conflict.

    Values
    ------
    accept_incoming
        Incoming execution type wins; active type is cancelled.
    reject_incoming
        Active execution type wins; incoming is rejected.
    queue_incoming
        Incoming is queued until the active execution completes.
    escalate
        Neither is auto-resolved; operator input required.
    """

    accept_incoming = "accept_incoming"
    reject_incoming = "reject_incoming"
    queue_incoming = "queue_incoming"
    escalate = "escalate"


# ---------------------------------------------------------------------------
# ExecutionTypePolicy
# ---------------------------------------------------------------------------


@dataclass
class ExecutionTypePolicy:
    """Canonical governance policy for a single execution type.

    This captures all governance semantics in one place per execution type.

    Attributes
    ----------
    execution_type
        The :class:`ExecutionType` this policy applies to.
    priority
        Numeric priority (lower = higher priority).
    required_gates
        Names of gates that MUST pass for this type to be accepted.
        These are checked by :func:`evaluate_execution_governance`.
    cancellable
        Whether this execution type can be cancelled mid-flight.
    rollback_on_cancel
        :class:`RollbackPolicy` applied when the execution is cancelled.
    rollback_on_failure
        :class:`RollbackPolicy` applied when the execution fails.
    timeout_policy
        :class:`TimeoutPolicy` governing timeout enforcement.
    default_timeout_s
        Default timeout in seconds (advisory).  ``None`` = no default.
    failure_semantic
        :class:`FailureSemantic` defining the recovery path on failure.
    blocks_lower_priority
        When ``True``, an active instance of this type blocks all
        lower-priority executions on the same device.
    max_concurrent_per_device
        Maximum concurrent executions of this type per device.
        ``1`` means only one at a time; ``-1`` means unlimited.
    """

    execution_type: ExecutionType
    priority: int
    required_gates: List[str]
    cancellable: bool
    rollback_on_cancel: RollbackPolicy
    rollback_on_failure: RollbackPolicy
    timeout_policy: TimeoutPolicy
    default_timeout_s: Optional[float]
    failure_semantic: FailureSemantic
    blocks_lower_priority: bool
    max_concurrent_per_device: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_type": self.execution_type.value,
            "priority": self.priority,
            "required_gates": list(self.required_gates),
            "cancellable": self.cancellable,
            "rollback_on_cancel": self.rollback_on_cancel.value,
            "rollback_on_failure": self.rollback_on_failure.value,
            "timeout_policy": self.timeout_policy.value,
            "default_timeout_s": self.default_timeout_s,
            "failure_semantic": self.failure_semantic.value,
            "blocks_lower_priority": self.blocks_lower_priority,
            "max_concurrent_per_device": self.max_concurrent_per_device,
            "_authority": UNIFIED_EXECUTION_GOVERNANCE_AUTHORITY,
        }


# ---------------------------------------------------------------------------
# Canonical per-type policies
# ---------------------------------------------------------------------------

_GOAL_EXECUTION_POLICY = ExecutionTypePolicy(
    execution_type=ExecutionType.goal_execution,
    priority=ExecutionPriority.PRIORITY_2_GOAL,
    required_gates=[
        "v2_cross_device_switch",
        "session_active",
        "session_posture_join_runtime",
        "android_cross_device_enabled",
        "android_goal_execution_enabled",
    ],
    cancellable=True,
    rollback_on_cancel=RollbackPolicy.notify_only,
    rollback_on_failure=RollbackPolicy.best_effort_undo,
    timeout_policy=TimeoutPolicy.hard,
    default_timeout_s=120.0,
    failure_semantic=FailureSemantic.retry,
    blocks_lower_priority=False,
    max_concurrent_per_device=3,
)

_PARALLEL_SUBTASK_POLICY = ExecutionTypePolicy(
    execution_type=ExecutionType.parallel_subtask,
    priority=ExecutionPriority.PRIORITY_2_PARALLEL,
    required_gates=[
        "v2_cross_device_switch",
        "session_active",
        "session_posture_join_runtime",
        "android_cross_device_enabled",
        "android_parallel_execution_enabled",
    ],
    cancellable=True,
    rollback_on_cancel=RollbackPolicy.notify_only,
    rollback_on_failure=RollbackPolicy.best_effort_undo,
    timeout_policy=TimeoutPolicy.hard,
    default_timeout_s=180.0,
    failure_semantic=FailureSemantic.retry,
    blocks_lower_priority=False,
    max_concurrent_per_device=5,
)

_TAKEOVER_REQUEST_POLICY = ExecutionTypePolicy(
    execution_type=ExecutionType.takeover_request,
    priority=ExecutionPriority.PRIORITY_1_TAKEOVER,
    required_gates=[
        "v2_cross_device_switch",
        "session_active",
        "session_posture_join_runtime",
        "android_cross_device_enabled",
        "device_local_loop_ready",
    ],
    cancellable=True,
    rollback_on_cancel=RollbackPolicy.required_undo,
    rollback_on_failure=RollbackPolicy.checkpoint_restore,
    timeout_policy=TimeoutPolicy.hard,
    default_timeout_s=300.0,
    failure_semantic=FailureSemantic.escalate_to_operator,
    blocks_lower_priority=True,
    max_concurrent_per_device=1,
)

_EXECUTION_TYPE_POLICIES: Dict[ExecutionType, ExecutionTypePolicy] = {
    ExecutionType.goal_execution: _GOAL_EXECUTION_POLICY,
    ExecutionType.parallel_subtask: _PARALLEL_SUBTASK_POLICY,
    ExecutionType.takeover_request: _TAKEOVER_REQUEST_POLICY,
}


def get_execution_type_policy(
    execution_type: ExecutionType,
) -> Optional[ExecutionTypePolicy]:
    """Return the canonical :class:`ExecutionTypePolicy` for *execution_type*.

    Returns ``None`` for :attr:`ExecutionType.unknown`.
    """
    return _EXECUTION_TYPE_POLICIES.get(execution_type)


# ---------------------------------------------------------------------------
# ExecutionGovernanceVerdict
# ---------------------------------------------------------------------------


@dataclass
class ExecutionGovernanceVerdict:
    """Result of unified governance evaluation for an execution request.

    Returned by :func:`evaluate_execution_governance`.

    Attributes
    ----------
    execution_type
        The execution type that was evaluated.
    device_id
        The target Android device identifier.
    accepted
        ``True`` iff the execution is accepted under the unified policy.
    rejection_reason
        Human-readable rejection reason (empty when ``accepted`` is ``True``).
    blocking_gates
        Gate names that prevented acceptance.
    conflict
        ``True`` iff the rejection is due to an active conflicting execution.
    active_conflicting_type
        When ``conflict`` is ``True``, the currently active execution type
        that is blocking the incoming one.
    failure_semantic
        Recommended :class:`FailureSemantic` for the caller to apply.
    policy
        The :class:`ExecutionTypePolicy` that governed this evaluation.
    evaluated_at
        Unix epoch seconds when this verdict was produced.
    """

    execution_type: ExecutionType
    device_id: str
    accepted: bool
    rejection_reason: str = ""
    blocking_gates: List[str] = field(default_factory=list)
    conflict: bool = False
    active_conflicting_type: Optional[ExecutionType] = None
    failure_semantic: Optional[FailureSemantic] = None
    policy: Optional[ExecutionTypePolicy] = None
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_type": self.execution_type.value,
            "device_id": self.device_id,
            "accepted": self.accepted,
            "rejection_reason": self.rejection_reason,
            "blocking_gates": list(self.blocking_gates),
            "conflict": self.conflict,
            "active_conflicting_type": (
                self.active_conflicting_type.value
                if self.active_conflicting_type else None
            ),
            "failure_semantic": (
                self.failure_semantic.value if self.failure_semantic else None
            ),
            "policy": self.policy.to_dict() if self.policy else None,
            "evaluated_at": self.evaluated_at,
            "_authority": UNIFIED_EXECUTION_GOVERNANCE_AUTHORITY,
            "_contract_version": UNIFIED_EXECUTION_GOVERNANCE_CONTRACT_VERSION,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))


# ---------------------------------------------------------------------------
# ExecutionConflict & ConflictResolutionResult
# ---------------------------------------------------------------------------


@dataclass
class ExecutionConflict:
    """Represents a conflict between an incoming and an active execution type.

    Attributes
    ----------
    incoming_type
        The execution type being requested.
    active_type
        The execution type currently running on the device.
    device_id
        The target device.
    incoming_priority
        Numeric priority of the incoming type (lower = higher priority).
    active_priority
        Numeric priority of the active type.
    incoming_wins
        ``True`` iff incoming_priority < active_priority.
    detected_at
        Unix epoch seconds when the conflict was detected.
    """

    incoming_type: ExecutionType
    active_type: ExecutionType
    device_id: str
    incoming_priority: int
    active_priority: int
    incoming_wins: bool = False
    detected_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incoming_type": self.incoming_type.value,
            "active_type": self.active_type.value,
            "device_id": self.device_id,
            "incoming_priority": self.incoming_priority,
            "active_priority": self.active_priority,
            "incoming_wins": self.incoming_wins,
            "detected_at": self.detected_at,
        }


@dataclass
class ConflictResolutionResult:
    """Result of resolving a conflict between two execution types.

    Attributes
    ----------
    conflict
        The :class:`ExecutionConflict` that was resolved.
    resolution
        The :class:`ConflictResolution` strategy applied.
    reason
        Human-readable explanation.
    recommended_failure_semantic
        :class:`FailureSemantic` for the losing side.
    resolved_at
        Unix epoch seconds when resolution was computed.
    """

    conflict: ExecutionConflict
    resolution: ConflictResolution
    reason: str = ""
    recommended_failure_semantic: FailureSemantic = FailureSemantic.reject_with_reason
    resolved_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict": self.conflict.to_dict(),
            "resolution": self.resolution.value,
            "reason": self.reason,
            "recommended_failure_semantic": self.recommended_failure_semantic.value,
            "resolved_at": self.resolved_at,
            "_authority": UNIFIED_EXECUTION_GOVERNANCE_AUTHORITY,
        }


# ---------------------------------------------------------------------------
# Active execution tracking (in-process, non-durable)
# ---------------------------------------------------------------------------

import threading

_active_executions_lock = threading.Lock()
# device_id → list of (ExecutionType, started_at, execution_id)
_active_executions: Dict[str, List[Tuple[ExecutionType, float, str]]] = {}


def _register_active_execution(
    device_id: str,
    execution_type: ExecutionType,
    execution_id: str = "",
) -> None:
    """Register an active execution for *device_id*.

    Internal use only — called by :func:`evaluate_execution_governance` when
    it accepts an execution.  Thread-safe.
    """
    with _active_executions_lock:
        if device_id not in _active_executions:
            _active_executions[device_id] = []
        _active_executions[device_id].append((execution_type, time.time(), execution_id))


def _unregister_active_execution(
    device_id: str,
    execution_type: ExecutionType,
    execution_id: str = "",
) -> bool:
    """Unregister a completed/cancelled execution for *device_id*.

    Returns ``True`` when an entry was found and removed.
    """
    with _active_executions_lock:
        entries = _active_executions.get(device_id, [])
        for i, (et, started_at, eid) in enumerate(entries):
            if et == execution_type and (not execution_id or eid == execution_id):
                entries.pop(i)
                if not entries:
                    _active_executions.pop(device_id, None)
                return True
    return False


def _get_active_executions(
    device_id: str,
) -> List[Tuple[ExecutionType, float, str]]:
    """Return a snapshot of active executions for *device_id*."""
    with _active_executions_lock:
        return list(_active_executions.get(device_id, []))


def _clear_active_executions_for_device(device_id: str) -> None:
    """Clear all tracked active executions for *device_id* (test isolation)."""
    with _active_executions_lock:
        _active_executions.pop(device_id, None)


def _clear_all_active_executions() -> None:
    """Clear all tracked active executions (test isolation)."""
    with _active_executions_lock:
        _active_executions.clear()


# ---------------------------------------------------------------------------
# is_takeover_active / get_active_execution_type
# ---------------------------------------------------------------------------


def is_takeover_active(device_id: str) -> bool:
    """Return ``True`` iff an active takeover_request is registered for *device_id*.

    This checks the in-process active-execution registry.  The registry is
    populated by :func:`evaluate_execution_governance` when it accepts a
    ``takeover_request`` and the caller opts in to registration (which is the
    default).  The caller is responsible for calling
    :func:`notify_execution_completed` when the takeover finishes.

    For V2-authoritative takeover state, also consult
    ``core.takeover_tracking.get_takeover_tracking_runtime()``.

    Parameters
    ----------
    device_id
        Android device identifier.

    Returns
    -------
    bool
        ``True`` iff at least one active takeover_request is registered.
    """
    return any(
        et == ExecutionType.takeover_request
        for (et, _, _) in _get_active_executions(device_id)
    )


def get_active_execution_type(device_id: str) -> Optional[ExecutionType]:
    """Return the highest-priority active execution type for *device_id*, or ``None``.

    If multiple executions are active, the one with the lowest priority number
    (highest importance) is returned.

    Parameters
    ----------
    device_id
        Android device identifier.
    """
    active = _get_active_executions(device_id)
    if not active:
        return None
    # Sort by priority (ascending = highest importance first)
    sorted_active = sorted(active, key=lambda t: _EXECUTION_TYPE_PRIORITY.get(t[0], 99))
    return sorted_active[0][0]


def notify_execution_completed(
    device_id: str,
    execution_type: ExecutionType,
    execution_id: str = "",
) -> bool:
    """Notify the governance layer that an execution has completed or been cancelled.

    Callers MUST call this when a previously accepted execution finishes
    (successfully, via failure, or via cancellation) so that the active-
    execution registry is kept consistent.

    Parameters
    ----------
    device_id
        Android device identifier.
    execution_type
        The :class:`ExecutionType` that completed.
    execution_id
        Optional correlation identifier used during registration.

    Returns
    -------
    bool
        ``True`` when the entry was found and removed.
    """
    removed = _unregister_active_execution(device_id, execution_type, execution_id)
    if removed:
        logger.debug(
            "notify_execution_completed: device_id=%r type=%s id=%r removed from registry",
            device_id, execution_type.value, execution_id,
        )
    else:
        logger.debug(
            "notify_execution_completed: no entry found for device_id=%r type=%s id=%r",
            device_id, execution_type.value, execution_id,
        )
    return removed


def get_execution_runtime_snapshot(
    *,
    device_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return a canonical runtime snapshot of active execution lifecycle state.

    The snapshot is read-only and derived from the unified active-execution
    registry used by :func:`evaluate_execution_governance`.
    """
    requested_device_ids = set(device_ids or [])
    with _active_executions_lock:
        registry_device_ids = set(_active_executions.keys())
    tracked_device_ids = requested_device_ids | registry_device_ids

    devices: List[Dict[str, Any]] = []
    active_device_count = 0
    active_execution_total_count = 0

    for device_id in sorted(tracked_device_ids):
        active_entries = sorted(
            _get_active_executions(device_id),
            key=lambda t: t[1],
        )
        active_items: List[Dict[str, Any]] = []
        for execution_type, started_at, execution_id in active_entries:
            policy = get_execution_type_policy(execution_type)
            active_items.append(
                {
                    "execution_type": execution_type.value,
                    "started_at": float(started_at),
                    "execution_id": execution_id,
                    "priority": int(_EXECUTION_TYPE_PRIORITY.get(execution_type, 99)),
                    "blocks_lower_priority": bool(
                        policy.blocks_lower_priority if policy else False
                    ),
                }
            )

        highest_priority = get_active_execution_type(device_id)
        takeover_active = any(
            item["execution_type"] == ExecutionType.takeover_request.value
            for item in active_items
        )
        active_execution_types = {
            ExecutionType.from_string(item["execution_type"])
            for item in active_items
        }
        blocked_execution_type_values: set[str] = set()
        for active_execution_type in active_execution_types:
            active_policy = get_execution_type_policy(active_execution_type)
            if not active_policy or not active_policy.blocks_lower_priority:
                continue
            active_priority = int(_EXECUTION_TYPE_PRIORITY.get(active_execution_type, 99))
            for candidate_type, candidate_policy in _EXECUTION_TYPE_POLICIES.items():
                if int(candidate_policy.priority) > active_priority:
                    blocked_execution_type_values.add(candidate_type.value)
        blocked_execution_types = sorted(blocked_execution_type_values)

        active_count = len(active_items)
        if active_count > 0:
            active_device_count += 1
        active_execution_total_count += active_count
        devices.append(
            {
                "device_id": device_id,
                "active_execution_count": active_count,
                "active_executions": active_items,
                "takeover_active": takeover_active,
                "highest_priority_execution_type": (
                    highest_priority.value if highest_priority else None
                ),
                "blocked_execution_types": blocked_execution_types,
                "_source": "unified_execution_governance.active_registry",
            }
        )

    return {
        "devices": devices,
        "active_device_count": active_device_count,
        "active_execution_total_count": active_execution_total_count,
        "_authority": UNIFIED_EXECUTION_GOVERNANCE_AUTHORITY,
        "_contract_version": UNIFIED_EXECUTION_GOVERNANCE_CONTRACT_VERSION,
    }


# ---------------------------------------------------------------------------
# _check_mode_readiness_gate
# ---------------------------------------------------------------------------


def _check_mode_readiness_gate(
    device_id: str,
    execution_type: ExecutionType,
) -> Tuple[bool, List[str], str]:
    """Evaluate the mode/readiness gates via android_mode_gate_policy.

    Returns (gates_pass, blocking_gates, detail_reason).
    """
    try:
        from core.android_mode_gate_policy import evaluate_android_mode_readiness
        verdict = evaluate_android_mode_readiness(
            device_id=device_id,
            require_goal_execution=(execution_type == ExecutionType.goal_execution),
            require_parallel_execution=(execution_type == ExecutionType.parallel_subtask),
            require_local_loop_ready=(execution_type == ExecutionType.takeover_request),
        )
        if execution_type == ExecutionType.takeover_request:
            gate_pass = verdict.is_takeover_eligible
            reason = (
                "takeover eligibility: all gates pass"
                if gate_pass
                else f"takeover eligibility failed; blocking_gates={verdict.blocking_gates}"
            )
        else:
            gate_pass = verdict.is_dispatch_eligible
            reason = (
                "dispatch eligibility: all gates pass"
                if gate_pass
                else f"dispatch eligibility failed; blocking_gates={verdict.blocking_gates}"
            )
        return gate_pass, list(verdict.blocking_gates), reason
    except Exception as exc:
        logger.debug(
            "_check_mode_readiness_gate: unavailable for device_id=%r type=%s: %s",
            device_id, execution_type.value, exc,
        )
        return False, ["mode_gate_unavailable"], f"Mode readiness gate unavailable: {exc}"


# ---------------------------------------------------------------------------
# evaluate_execution_governance
# ---------------------------------------------------------------------------


def evaluate_execution_governance(
    execution_type: ExecutionType,
    device_id: str,
    *,
    execution_id: str = "",
    register_if_accepted: bool = True,
    skip_conflict_check: bool = False,
) -> ExecutionGovernanceVerdict:
    """Evaluate unified governance for an incoming execution request.

    This is the **primary API** that all callers MUST use to determine whether
    an execution of *execution_type* is accepted for *device_id*.  It:

    1. Looks up the :class:`ExecutionTypePolicy` for the type.
    2. Checks active conflicts (e.g., active takeover blocks goal_execution).
    3. Evaluates all required gates via ``evaluate_android_mode_readiness()``.
    4. If accepted and ``register_if_accepted`` is ``True``, registers the
       execution in the active-execution registry.

    Parameters
    ----------
    execution_type
        The :class:`ExecutionType` being requested.
    device_id
        Target Android device identifier.
    execution_id
        Optional correlation identifier for the specific execution instance.
    register_if_accepted
        When ``True`` (default), register the execution in the active-
        execution registry upon acceptance.  Set to ``False`` for read-only
        eligibility checks that should not track state.
    skip_conflict_check
        When ``True``, skip the active-conflict check.  Intended only for
        test isolation or operator-override paths.

    Returns
    -------
    ExecutionGovernanceVerdict
        Always returned, never raises.
    """
    import uuid as _uuid

    if not execution_id:
        execution_id = f"egov_{_uuid.uuid4().hex[:12]}"

    policy = _EXECUTION_TYPE_POLICIES.get(execution_type)
    if policy is None:
        return ExecutionGovernanceVerdict(
            execution_type=execution_type,
            device_id=device_id,
            accepted=False,
            rejection_reason=f"No governance policy defined for execution_type={execution_type.value!r}",
            failure_semantic=FailureSemantic.reject_with_reason,
        )

    # Step 1: Conflict check
    if not skip_conflict_check:
        conflict_verdict = _check_execution_conflict(
            incoming_type=execution_type,
            device_id=device_id,
        )
        if conflict_verdict is not None:
            return conflict_verdict

    # Step 2: Mode / readiness gate check
    gates_pass, blocking_gates, gate_reason = _check_mode_readiness_gate(
        device_id=device_id,
        execution_type=execution_type,
    )

    if not gates_pass:
        return ExecutionGovernanceVerdict(
            execution_type=execution_type,
            device_id=device_id,
            accepted=False,
            rejection_reason=f"Mode/readiness gate failed: {gate_reason}",
            blocking_gates=blocking_gates,
            failure_semantic=policy.failure_semantic,
            policy=policy,
        )

    # Step 3: Concurrent execution limit check
    if policy.max_concurrent_per_device > 0:
        current_count = sum(
            1 for (et, _, _) in _get_active_executions(device_id)
            if et == execution_type
        )
        if current_count >= policy.max_concurrent_per_device:
            return ExecutionGovernanceVerdict(
                execution_type=execution_type,
                device_id=device_id,
                accepted=False,
                rejection_reason=(
                    f"Concurrency limit reached: {current_count}/{policy.max_concurrent_per_device} "
                    f"{execution_type.value} executions active for device_id={device_id!r}"
                ),
                failure_semantic=FailureSemantic.wait_and_requeue,
                policy=policy,
            )

    # All checks passed — accept
    if register_if_accepted:
        _register_active_execution(device_id, execution_type, execution_id)
        logger.debug(
            "evaluate_execution_governance: ACCEPTED device_id=%r type=%s id=%r",
            device_id, execution_type.value, execution_id,
        )

    return ExecutionGovernanceVerdict(
        execution_type=execution_type,
        device_id=device_id,
        accepted=True,
        policy=policy,
    )


def _check_execution_conflict(
    incoming_type: ExecutionType,
    device_id: str,
) -> Optional[ExecutionGovernanceVerdict]:
    """Return a rejection verdict if an active execution conflicts with *incoming_type*.

    Returns ``None`` when no conflict is detected (execution can proceed to
    gate checks).
    """
    active_executions = _get_active_executions(device_id)
    if not active_executions:
        return None

    incoming_priority = _EXECUTION_TYPE_PRIORITY.get(incoming_type, 99)

    for (active_type, started_at, _eid) in active_executions:
        active_priority = _EXECUTION_TYPE_PRIORITY.get(active_type, 99)
        active_policy = _EXECUTION_TYPE_POLICIES.get(active_type)

        if active_policy and active_policy.blocks_lower_priority:
            # Active type blocks lower-priority types.
            if incoming_priority > active_priority:
                # Incoming has lower priority (higher number) → blocked.
                return ExecutionGovernanceVerdict(
                    execution_type=incoming_type,
                    device_id=device_id,
                    accepted=False,
                    rejection_reason=(
                        f"Active {active_type.value} (priority={active_priority}) "
                        f"blocks {incoming_type.value} (priority={incoming_priority}). "
                        f"{TAKEOVER_BLOCKS_LOWER_PRIORITY}"
                    ),
                    conflict=True,
                    active_conflicting_type=active_type,
                    failure_semantic=FailureSemantic.wait_and_requeue,
                    policy=_EXECUTION_TYPE_POLICIES.get(incoming_type),
                )
    return None


# ---------------------------------------------------------------------------
# resolve_execution_conflict
# ---------------------------------------------------------------------------


def resolve_execution_conflict(
    incoming_type: ExecutionType,
    active_type: ExecutionType,
    device_id: str,
) -> ConflictResolutionResult:
    """Compute the canonical conflict resolution for two execution types.

    This function determines which execution type wins and recommends the
    failure semantic for the loser.  It does NOT automatically cancel or
    notify — that is the caller's responsibility.

    Parameters
    ----------
    incoming_type
        Execution type being newly requested.
    active_type
        Execution type currently active on the device.
    device_id
        Target device.

    Returns
    -------
    ConflictResolutionResult
    """
    incoming_priority = _EXECUTION_TYPE_PRIORITY.get(incoming_type, 99)
    active_priority = _EXECUTION_TYPE_PRIORITY.get(active_type, 99)
    incoming_wins = incoming_priority < active_priority

    conflict = ExecutionConflict(
        incoming_type=incoming_type,
        active_type=active_type,
        device_id=device_id,
        incoming_priority=incoming_priority,
        active_priority=active_priority,
        incoming_wins=incoming_wins,
    )

    if incoming_wins:
        return ConflictResolutionResult(
            conflict=conflict,
            resolution=ConflictResolution.accept_incoming,
            reason=(
                f"{incoming_type.value} (priority={incoming_priority}) beats "
                f"{active_type.value} (priority={active_priority}). "
                f"Active {active_type.value} should be cancelled."
            ),
            recommended_failure_semantic=FailureSemantic.reject_with_reason,
        )
    elif incoming_priority == active_priority:
        # Same priority — FIFO: active wins.
        return ConflictResolutionResult(
            conflict=conflict,
            resolution=ConflictResolution.reject_incoming,
            reason=(
                f"{incoming_type.value} and {active_type.value} have the same priority "
                f"({incoming_priority}). Active execution wins (FIFO). "
                f"Incoming will be queued."
            ),
            recommended_failure_semantic=FailureSemantic.wait_and_requeue,
        )
    else:
        # Active has higher priority — incoming is blocked.
        return ConflictResolutionResult(
            conflict=conflict,
            resolution=ConflictResolution.reject_incoming,
            reason=(
                f"{active_type.value} (priority={active_priority}) blocks "
                f"{incoming_type.value} (priority={incoming_priority}). "
                f"Incoming is rejected until active completes."
            ),
            recommended_failure_semantic=FailureSemantic.wait_and_requeue,
        )
