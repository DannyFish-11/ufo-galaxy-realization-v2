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
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple

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
EXECUTION_BUSY_THRESHOLD_SECONDS: float = 60.0
ANDROID_RUNTIME_SEMANTICS_STALE_AFTER_SECONDS: float = 120.0
STALE_ANDROID_RUNTIME_TRUTH_DOWNGRADES_AUTHORITY_POLICY: str = (
    "POLICY::STALE_ANDROID_RUNTIME_TRUTH_DOWNGRADES_AUTHORITY_V1: "
    "Android-reported runtime truth on the canonical V2 execution-governance "
    "path MUST be freshness-gated. When android_semantics_age_s is unavailable "
    "or exceeds ANDROID_RUNTIME_SEMANTICS_STALE_AFTER_SECONDS, Android-reported "
    "semantics MUST be downgraded to unknown/non-authoritative input rather than "
    "silently driving canonical governance decisions as fresh runtime truth."
)

CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY: str = (
    "POLICY::CANONICAL_PROOF_INPUT_DIAGNOSIS_V1: "
    "Canonical governance diagnosis MUST classify Android/runtime proof inputs "
    "as one of: complete, stale, conflicting, malformed, unknown, downgraded, "
    "partial, or missing. "
    "Semantic conflicts between Android-reported fields (e.g., cross_device mode "
    "with cross_device_eligibility=False, or local_inference_available=True with "
    "local_intelligence_status=disabled) MUST be surfaced as 'conflicting' rather "
    "than collapsing into generic denial reasons. "
    "Android-reported downgrade signals MUST be surfaced as 'downgraded'. "
    "Unrecognised contract keys MUST be surfaced as 'unknown'. "
    "Each degraded state MUST carry explicit degradation_causes and conflict "
    "descriptions for debuggability. Only 'complete' is a passing classification; "
    "all other classes are explicitly non-passing."
)

# ---------------------------------------------------------------------------
# PR-5: Android execution lifecycle truth quality constants and policy
# ---------------------------------------------------------------------------

#: Seconds after which an Android execution event is considered stale when
#: V2 has active executions tracked locally.
ANDROID_EXECUTION_LIFECYCLE_TRUTH_STALE_AFTER_SECONDS: float = 60.0

#: Sentinel identifying the PR-5 execution lifecycle truth binding module.
EXECUTION_LIFECYCLE_TRUTH_BINDING_SENTINEL: str = (
    "EXECUTION_LIFECYCLE_TRUTH_BINDING_SENTINEL::PR5_V2 present"
)

#: Contract version for the lifecycle truth binding data model.
EXECUTION_LIFECYCLE_TRUTH_BINDING_CONTRACT_VERSION: str = "5.0.0"

ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY: str = (
    "POLICY::ANDROID_EXECUTION_LIFECYCLE_TRUTH_V1: "
    "V2 execution runtime snapshots and decision causality MUST reflect the "
    "quality of Android-remote lifecycle confirmation, not only V2-local "
    "bookkeeping.  The truth quality MUST be one of: "
    "v2_local_only (no active execution, no Android events), "
    "android_remote_confirmed (V2 active AND recent Android events agree), "
    "stale_remote (V2 active AND Android events exist but are too old), "
    "missing_remote (V2 active AND no Android lifecycle evidence received), "
    "conflicting_remote (contradiction between V2-local and Android-remote state). "
    "Degraded truth quality (missing_remote, stale_remote, conflicting_remote) "
    "MUST cause diagnosable governance degradation and MUST be visible in "
    "decision_causality and runtime snapshot outputs."
)

_ANDROID_REPORTED_RUNTIME_TRUTH_FIELDS: Tuple[str, ...] = (
    "android_reported_mode",
    "android_reported_mode_state",
    "android_reported_mode_readiness_state",
    "android_reported_cross_device_eligibility",
    "android_reported_goal_execution_eligibility",
    "android_reported_parallel_execution_eligibility",
    "android_reported_local_intelligence_status",
    "android_reported_local_inference_ready",
    "android_reported_local_inference_available",
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
    delegated_execution = "delegated_execution"
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
    PRIORITY_2_DELEGATED = 2
    PRIORITY_UNKNOWN = 99


# Map ExecutionType → ExecutionPriority
_EXECUTION_TYPE_PRIORITY: Dict[ExecutionType, int] = {
    ExecutionType.takeover_request: ExecutionPriority.PRIORITY_1_TAKEOVER,
    ExecutionType.parallel_subtask: ExecutionPriority.PRIORITY_2_PARALLEL,
    ExecutionType.goal_execution: ExecutionPriority.PRIORITY_2_GOAL,
    ExecutionType.delegated_execution: ExecutionPriority.PRIORITY_2_DELEGATED,
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
# Execution lifecycle / replay / interruption / uplink enums
# ---------------------------------------------------------------------------


class ExecutionLifecyclePhase(str, Enum):
    created = "created"
    admitted = "admitted"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    timed_out = "timed_out"
    interrupted = "interrupted"
    retrying = "retrying"
    replayed = "replayed"
    cancelled = "cancelled"


class InterruptionReason(str, Enum):
    operator_interrupt = "operator_interrupt"
    takeover_preempted = "takeover_preempted"
    device_disconnect = "device_disconnect"
    policy_interrupt = "policy_interrupt"
    unknown = "unknown"


class ReplayReason(str, Enum):
    timeout_replay = "timeout_replay"
    failure_replay = "failure_replay"
    operator_replay = "operator_replay"
    recovery_replay = "recovery_replay"
    unknown = "unknown"


class UplinkKind(str, Enum):
    result_uplink = "result_uplink"
    state_uplink = "state_uplink"


class AndroidExecutionLifecycleTruthQuality(str, Enum):
    """Quality of Android-remote lifecycle confirmation vs V2-local execution tracking.

    This enum classifies the reliability of execution runtime truth as seen
    from the V2 control plane.  It is the primary output of the PR-5 data
    model introduced by :func:`get_execution_lifecycle_truth_binding`.

    Values
    ------
    v2_local_only
        No active V2-tracked executions and no Android events — idle baseline
        state where V2 local bookkeeping and Android are in silent agreement.
    android_remote_confirmed
        V2 has active tracked executions AND recent Android execution events
        confirm the activity within the staleness threshold.  Highest quality.
    stale_remote
        V2 has active tracked executions AND Android events exist but are older
        than :data:`ANDROID_EXECUTION_LIFECYCLE_TRUTH_STALE_AFTER_SECONDS`.
        Governance should treat runtime truth as degraded.
    missing_remote
        V2 has active tracked executions BUT no Android lifecycle evidence has
        been received for this device.  Governance must not rely on Android
        confirmation.
    conflicting_remote
        Contradiction between V2-local state and Android-remote state.
        Examples: V2 tracks an active execution but Android reports a terminal
        phase; or Android reports an active execution that V2 has no record of.
        Requires explicit investigation and causes governance degradation.
    """

    v2_local_only = "v2_local_only"
    android_remote_confirmed = "android_remote_confirmed"
    stale_remote = "stale_remote"
    missing_remote = "missing_remote"
    conflicting_remote = "conflicting_remote"


# Map AndroidExecutionLifecycleTruthQuality → canonical governance impact label.
# Callers that gate on truth quality MUST consult this mapping rather than
# hard-coding impact strings.
_ANDROID_LIFECYCLE_TRUTH_GOVERNANCE_IMPACT: Mapping[
    AndroidExecutionLifecycleTruthQuality, str
] = MappingProxyType(
    {
        AndroidExecutionLifecycleTruthQuality.v2_local_only: "none",
        AndroidExecutionLifecycleTruthQuality.android_remote_confirmed: "none",
        AndroidExecutionLifecycleTruthQuality.stale_remote: "degraded",
        AndroidExecutionLifecycleTruthQuality.missing_remote: "degraded",
        AndroidExecutionLifecycleTruthQuality.conflicting_remote: "blocked",
    }
)

# Set of truth qualities that indicate the runtime snapshot is degraded and
# that governance decisions should surface a diagnostic reason.
_ANDROID_LIFECYCLE_TRUTH_DEGRADED_QUALITIES: frozenset[
    AndroidExecutionLifecycleTruthQuality
] = frozenset(
    {
        AndroidExecutionLifecycleTruthQuality.stale_remote,
        AndroidExecutionLifecycleTruthQuality.missing_remote,
        AndroidExecutionLifecycleTruthQuality.conflicting_remote,
    }
)


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

_DELEGATED_EXECUTION_POLICY = ExecutionTypePolicy(
    execution_type=ExecutionType.delegated_execution,
    priority=ExecutionPriority.PRIORITY_2_DELEGATED,
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
    default_timeout_s=240.0,
    failure_semantic=FailureSemantic.fallback_local,
    blocks_lower_priority=False,
    max_concurrent_per_device=2,
)

_EXECUTION_TYPE_POLICIES: Dict[ExecutionType, ExecutionTypePolicy] = {
    ExecutionType.goal_execution: _GOAL_EXECUTION_POLICY,
    ExecutionType.parallel_subtask: _PARALLEL_SUBTASK_POLICY,
    ExecutionType.takeover_request: _TAKEOVER_REQUEST_POLICY,
    ExecutionType.delegated_execution: _DELEGATED_EXECUTION_POLICY,
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
# Lifecycle / uplink event models
# ---------------------------------------------------------------------------


@dataclass
class ExecutionLifecycleEvent:
    execution_id: str
    device_id: str
    execution_type: ExecutionType
    phase: ExecutionLifecyclePhase
    attempt: int = 1
    failure_semantic: Optional[FailureSemantic] = None
    interruption_reason: Optional[InterruptionReason] = None
    replay_reason: Optional[ReplayReason] = None
    detail: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    event_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "device_id": self.device_id,
            "execution_type": self.execution_type.value,
            "phase": self.phase.value,
            "attempt": int(self.attempt),
            "failure_semantic": self.failure_semantic.value if self.failure_semantic else None,
            "interruption_reason": self.interruption_reason.value if self.interruption_reason else None,
            "replay_reason": self.replay_reason.value if self.replay_reason else None,
            "detail": self.detail,
            "metadata": dict(self.metadata),
            "event_at": float(self.event_at),
        }


@dataclass
class ExecutionUplinkRecord:
    execution_id: str
    device_id: str
    execution_type: ExecutionType
    kind: UplinkKind
    payload: Dict[str, Any]
    sequence: int
    recorded_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "device_id": self.device_id,
            "execution_type": self.execution_type.value,
            "kind": self.kind.value,
            "payload": dict(self.payload),
            "sequence": int(self.sequence),
            "recorded_at": float(self.recorded_at),
        }


# ---------------------------------------------------------------------------
# PR-5: ExecutionLifecycleTruthBinding — Android lifecycle truth quality model
# ---------------------------------------------------------------------------


@dataclass
class ExecutionLifecycleTruthBinding:
    """Binding quality between V2-local execution tracking and Android-remote
    lifecycle evidence.

    This dataclass captures the PR-5 data model that distinguishes V2-local
    tracked execution state from Android-remote-confirmed state, stale remote
    state, missing remote state, and conflicting remote state.

    Produced by :func:`get_execution_lifecycle_truth_binding` and embedded
    in :func:`get_execution_runtime_snapshot` per-device entries and in
    ``decision_causality`` via :mod:`core.unified_governance_semantics`.

    Attributes
    ----------
    device_id
        The Android device identifier.
    android_lifecycle_truth_quality
        Canonical :class:`AndroidExecutionLifecycleTruthQuality` classification
        for this device's execution state.
    android_lifecycle_truth_reason
        Human-readable reason string explaining the quality classification.
    android_lifecycle_truth_degraded
        ``True`` when the quality is one of ``stale_remote``, ``missing_remote``,
        or ``conflicting_remote`` — signals that governance decisions MUST
        surface a diagnostic reason.
    android_lifecycle_truth_governance_impact
        Canonical governance impact label: ``"none"`` | ``"degraded"`` | ``"blocked"``.
    active_execution_count
        Number of active executions tracked locally by V2 for this device.
    latest_android_event_phase
        Most recent Android-reported execution phase (from
        ``android_device_state_store``), or ``None`` if unavailable.
    latest_android_event_age_s
        Age in seconds of the most recent Android execution event, or ``None``
        if unavailable.
    assessed_at
        Unix epoch seconds when this binding was assessed.
    """

    device_id: str
    android_lifecycle_truth_quality: AndroidExecutionLifecycleTruthQuality
    android_lifecycle_truth_reason: str = ""
    android_lifecycle_truth_degraded: bool = False
    android_lifecycle_truth_governance_impact: str = "none"
    active_execution_count: int = 0
    latest_android_event_phase: Optional[str] = None
    latest_android_event_age_s: Optional[float] = None
    assessed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "android_lifecycle_truth_quality": self.android_lifecycle_truth_quality.value,
            "android_lifecycle_truth_reason": self.android_lifecycle_truth_reason,
            "android_lifecycle_truth_degraded": self.android_lifecycle_truth_degraded,
            "android_lifecycle_truth_governance_impact": (
                self.android_lifecycle_truth_governance_impact
            ),
            "active_execution_count": self.active_execution_count,
            "latest_android_event_phase": self.latest_android_event_phase,
            "latest_android_event_age_s": self.latest_android_event_age_s,
            "assessed_at": float(self.assessed_at),
            "_policy": ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY,
            "_contract_version": EXECUTION_LIFECYCLE_TRUTH_BINDING_CONTRACT_VERSION,
        }


# ---------------------------------------------------------------------------
# Active execution tracking (in-process, non-durable)
# ---------------------------------------------------------------------------

_active_executions_lock = threading.Lock()
# device_id → list of (ExecutionType, started_at, execution_id)
_active_executions: Dict[str, List[Tuple[ExecutionType, float, str]]] = {}
_execution_lifecycle_lock = threading.Lock()
_execution_uplink_lock = threading.Lock()
_execution_lifecycle_history: Dict[str, List[ExecutionLifecycleEvent]] = {}
_execution_uplink_records: Dict[str, List[ExecutionUplinkRecord]] = {}
_uplink_sequence: int = 0

_EXECUTION_LIFECYCLE_TRANSITIONS: Dict[
    ExecutionLifecyclePhase,
    frozenset[ExecutionLifecyclePhase],
] = {
    ExecutionLifecyclePhase.created: frozenset(
        {
            ExecutionLifecyclePhase.admitted,
            ExecutionLifecyclePhase.cancelled,
            ExecutionLifecyclePhase.interrupted,
        }
    ),
    ExecutionLifecyclePhase.admitted: frozenset(
        {
            ExecutionLifecyclePhase.running,
            ExecutionLifecyclePhase.succeeded,
            ExecutionLifecyclePhase.failed,
            ExecutionLifecyclePhase.timed_out,
            ExecutionLifecyclePhase.interrupted,
            ExecutionLifecyclePhase.cancelled,
        }
    ),
    ExecutionLifecyclePhase.running: frozenset(
        {
            ExecutionLifecyclePhase.succeeded,
            ExecutionLifecyclePhase.failed,
            ExecutionLifecyclePhase.timed_out,
            ExecutionLifecyclePhase.interrupted,
            ExecutionLifecyclePhase.cancelled,
        }
    ),
    ExecutionLifecyclePhase.failed: frozenset(
        {
            ExecutionLifecyclePhase.retrying,
            ExecutionLifecyclePhase.replayed,
            ExecutionLifecyclePhase.cancelled,
        }
    ),
    ExecutionLifecyclePhase.timed_out: frozenset(
        {
            ExecutionLifecyclePhase.retrying,
            ExecutionLifecyclePhase.replayed,
            ExecutionLifecyclePhase.cancelled,
        }
    ),
    ExecutionLifecyclePhase.interrupted: frozenset(
        {
            ExecutionLifecyclePhase.retrying,
            ExecutionLifecyclePhase.replayed,
            ExecutionLifecyclePhase.cancelled,
        }
    ),
    ExecutionLifecyclePhase.retrying: frozenset(
        {
            ExecutionLifecyclePhase.running,
            ExecutionLifecyclePhase.failed,
            ExecutionLifecyclePhase.timed_out,
            ExecutionLifecyclePhase.interrupted,
        }
    ),
    ExecutionLifecyclePhase.replayed: frozenset(
        {
            ExecutionLifecyclePhase.running,
            ExecutionLifecyclePhase.failed,
            ExecutionLifecyclePhase.timed_out,
            ExecutionLifecyclePhase.interrupted,
        }
    ),
    ExecutionLifecyclePhase.succeeded: frozenset(),
    ExecutionLifecyclePhase.cancelled: frozenset(),
}


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


def _clear_execution_governance_runtime_state() -> None:
    """Clear active, lifecycle, and uplink runtime state (test isolation)."""
    global _uplink_sequence
    _clear_all_active_executions()
    with _execution_lifecycle_lock:
        _execution_lifecycle_history.clear()
    with _execution_uplink_lock:
        _execution_uplink_records.clear()
        _uplink_sequence = 0


def get_execution_lifecycle_matrix() -> Dict[str, Any]:
    """Return canonical lifecycle matrix for all governed execution modes."""
    return {
        "execution_types": {
            execution_type.value: {
                "priority": int(policy.priority),
                "timeout_policy": policy.timeout_policy.value,
                "default_timeout_s": policy.default_timeout_s,
                "failure_semantic": policy.failure_semantic.value,
                "max_concurrent_per_device": policy.max_concurrent_per_device,
            }
            for execution_type, policy in _EXECUTION_TYPE_POLICIES.items()
        },
        "transitions": {
            phase.value: sorted(next_phase.value for next_phase in next_phases)
            for phase, next_phases in _EXECUTION_LIFECYCLE_TRANSITIONS.items()
        },
        "governance_semantics": {
            "failure": ExecutionLifecyclePhase.failed.value,
            "timeout": ExecutionLifecyclePhase.timed_out.value,
            "retry": ExecutionLifecyclePhase.retrying.value,
            "replay": ExecutionLifecyclePhase.replayed.value,
            "interruption": ExecutionLifecyclePhase.interrupted.value,
        },
        "_authority": UNIFIED_EXECUTION_GOVERNANCE_AUTHORITY,
        "_contract_version": UNIFIED_EXECUTION_GOVERNANCE_CONTRACT_VERSION,
    }


def _is_transition_allowed(
    previous_phase: Optional[ExecutionLifecyclePhase],
    next_phase: ExecutionLifecyclePhase,
) -> bool:
    if previous_phase is None:
        return next_phase in {
            ExecutionLifecyclePhase.created,
            ExecutionLifecyclePhase.admitted,
        }
    if previous_phase == next_phase:
        return True
    return next_phase in _EXECUTION_LIFECYCLE_TRANSITIONS.get(previous_phase, frozenset())


def record_execution_lifecycle_event(
    execution_id: str,
    device_id: str,
    execution_type: ExecutionType,
    phase: ExecutionLifecyclePhase,
    *,
    failure_semantic: Optional[FailureSemantic] = None,
    interruption_reason: Optional[InterruptionReason] = None,
    replay_reason: Optional[ReplayReason] = None,
    detail: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    enforce_transition: bool = True,
) -> bool:
    """Record lifecycle event if transition is valid under the canonical matrix."""
    with _execution_lifecycle_lock:
        history = _execution_lifecycle_history.setdefault(execution_id, [])
        previous_phase = history[-1].phase if history else None
        if enforce_transition and not _is_transition_allowed(previous_phase, phase):
            return False
        attempt = history[-1].attempt if history else 1
        if phase in {ExecutionLifecyclePhase.retrying, ExecutionLifecyclePhase.replayed}:
            attempt += 1
        history.append(
            ExecutionLifecycleEvent(
                execution_id=execution_id,
                device_id=device_id,
                execution_type=execution_type,
                phase=phase,
                attempt=attempt,
                failure_semantic=failure_semantic,
                interruption_reason=interruption_reason,
                replay_reason=replay_reason,
                detail=detail,
                metadata=dict(metadata or {}),
            )
        )
        return True


def get_execution_lifecycle_history(execution_id: str) -> List[Dict[str, Any]]:
    with _execution_lifecycle_lock:
        return [event.to_dict() for event in _execution_lifecycle_history.get(execution_id, [])]


def _record_execution_uplink(
    execution_id: str,
    device_id: str,
    execution_type: ExecutionType,
    kind: UplinkKind,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    global _uplink_sequence
    with _execution_uplink_lock:
        _uplink_sequence += 1
        record = ExecutionUplinkRecord(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=execution_type,
            kind=kind,
            payload=dict(payload),
            sequence=_uplink_sequence,
        )
        _execution_uplink_records.setdefault(execution_id, []).append(record)
        return record.to_dict()


def record_result_uplink(
    execution_id: str,
    device_id: str,
    execution_type: ExecutionType,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    return _record_execution_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=execution_type,
        kind=UplinkKind.result_uplink,
        payload=payload,
    )


def record_state_uplink(
    execution_id: str,
    device_id: str,
    execution_type: ExecutionType,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    return _record_execution_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=execution_type,
        kind=UplinkKind.state_uplink,
        payload=payload,
    )


def get_all_uplink_records(execution_id: str) -> List[Dict[str, Any]]:
    with _execution_uplink_lock:
        return [record.to_dict() for record in _execution_uplink_records.get(execution_id, [])]


_TERMINAL_LIFECYCLE_PHASES: frozenset[str] = frozenset(
    {
        ExecutionLifecyclePhase.succeeded.value,
        ExecutionLifecyclePhase.failed.value,
        ExecutionLifecyclePhase.timed_out.value,
        ExecutionLifecyclePhase.interrupted.value,
        ExecutionLifecyclePhase.cancelled.value,
    }
)
_SUCCESSFUL_REPORTED_STATUSES: frozenset[str] = frozenset(
    {"ok", "success", "succeeded", "completed", "done"}
)
_FAILED_REPORTED_STATUSES: frozenset[str] = frozenset({"failed", "failure", "error"})
_CANCELLED_REPORTED_STATUSES: frozenset[str] = frozenset({"cancelled", "canceled"})
_ABORTED_REPORTED_STATUSES: frozenset[str] = frozenset({"aborted", "abort"})
_TIMED_OUT_REPORTED_STATUSES: frozenset[str] = frozenset({"timed_out", "timeout"})
_INTERRUPTED_REPORTED_STATUSES: frozenset[str] = frozenset({"interrupted", "interrupt"})
_PARTIAL_SUCCESS_REPORTED_STATUSES: frozenset[str] = frozenset(
    {"partial", "partial_success", "partially_succeeded", "degraded_success"}
)
_EXCEPTIONAL_RUNTIME_HEALTH_STATES: frozenset[str] = frozenset({"degraded", "recovered"})
_CANONICAL_TERMINAL_OUTCOME_SUCCESS: str = "success"
_CANONICAL_TERMINAL_OUTCOME_PARTIAL_SUCCESS: str = "partial_success"
_CANONICAL_TERMINAL_OUTCOME_FAILURE: str = "failure"
_CANONICAL_TERMINAL_OUTCOME_ABORTED: str = "aborted"
_CANONICAL_TERMINAL_OUTCOME_TIMEOUT: str = "timeout"
_CANONICAL_TERMINAL_OUTCOME_INTERRUPTED: str = "interrupted"
_TERMINAL_OUTCOME_VALUES: frozenset[str] = frozenset(
    {
        _CANONICAL_TERMINAL_OUTCOME_SUCCESS,
        _CANONICAL_TERMINAL_OUTCOME_PARTIAL_SUCCESS,
        _CANONICAL_TERMINAL_OUTCOME_FAILURE,
        _CANONICAL_TERMINAL_OUTCOME_ABORTED,
        _CANONICAL_TERMINAL_OUTCOME_TIMEOUT,
        _CANONICAL_TERMINAL_OUTCOME_INTERRUPTED,
    }
)
_LIFECYCLE_PHASE_TO_CANONICAL_TERMINAL_OUTCOME: Mapping[str, str] = MappingProxyType(
    {
        ExecutionLifecyclePhase.succeeded.value: _CANONICAL_TERMINAL_OUTCOME_SUCCESS,
        ExecutionLifecyclePhase.failed.value: _CANONICAL_TERMINAL_OUTCOME_FAILURE,
        ExecutionLifecyclePhase.timed_out.value: _CANONICAL_TERMINAL_OUTCOME_TIMEOUT,
        ExecutionLifecyclePhase.cancelled.value: _CANONICAL_TERMINAL_OUTCOME_ABORTED,
        ExecutionLifecyclePhase.interrupted.value: _CANONICAL_TERMINAL_OUTCOME_INTERRUPTED,
    }
)


def _normalize_reported_outcome(payload: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(payload, dict) or not payload:
        return None

    normalized_status = str(payload.get("status") or "").strip().lower()
    if normalized_status in _SUCCESSFUL_REPORTED_STATUSES:
        return ExecutionLifecyclePhase.succeeded.value
    if normalized_status in _FAILED_REPORTED_STATUSES:
        return ExecutionLifecyclePhase.failed.value
    if normalized_status in _CANCELLED_REPORTED_STATUSES:
        return ExecutionLifecyclePhase.cancelled.value
    if normalized_status in _ABORTED_REPORTED_STATUSES:
        return ExecutionLifecyclePhase.cancelled.value
    if normalized_status in _TIMED_OUT_REPORTED_STATUSES:
        return ExecutionLifecyclePhase.timed_out.value
    if normalized_status in _INTERRUPTED_REPORTED_STATUSES:
        return ExecutionLifecyclePhase.interrupted.value
    if normalized_status in _PARTIAL_SUCCESS_REPORTED_STATUSES:
        return _CANONICAL_TERMINAL_OUTCOME_PARTIAL_SUCCESS
    normalized_outcome = str(payload.get("outcome") or "").strip().lower()
    if normalized_outcome in _TERMINAL_OUTCOME_VALUES:
        return normalized_outcome

    normalized_terminal_phase = str(payload.get("terminal_phase") or "").strip().lower()
    if normalized_terminal_phase in _TERMINAL_LIFECYCLE_PHASES:
        return normalized_terminal_phase
    normalized_phase = str(payload.get("phase") or "").strip().lower()
    if normalized_phase in _TERMINAL_LIFECYCLE_PHASES:
        return normalized_phase
    if normalized_phase in {
        ExecutionLifecyclePhase.running.value,
        ExecutionLifecyclePhase.admitted.value,
        ExecutionLifecyclePhase.created.value,
        ExecutionLifecyclePhase.interrupted.value,
        ExecutionLifecyclePhase.retrying.value,
        ExecutionLifecyclePhase.replayed.value,
    }:
        return normalized_phase
    return None


def _normalize_terminal_outcome(outcome: Optional[str]) -> Optional[str]:
    normalized = str(outcome or "").strip().lower()
    if not normalized:
        return None
    if normalized in _LIFECYCLE_PHASE_TO_CANONICAL_TERMINAL_OUTCOME:
        return _LIFECYCLE_PHASE_TO_CANONICAL_TERMINAL_OUTCOME[normalized]
    if normalized in _TERMINAL_OUTCOME_VALUES:
        return normalized
    return None


def _merge_reported_terminal_outcomes(
    result_outcome: Optional[str],
    state_outcome: Optional[str],
) -> Optional[str]:
    result_terminal = _normalize_terminal_outcome(result_outcome)
    state_terminal = _normalize_terminal_outcome(state_outcome)
    if result_terminal and state_terminal:
        if result_terminal == state_terminal:
            return result_terminal
        # partial_success is reserved for explicit mixed success/failure evidence.
        # Other terminal mismatches (e.g. timeout vs failure) are treated as
        # conflicts and keep deterministic precedence rather than collapsing to
        # partial_success.
        if {result_terminal, state_terminal} == {
            _CANONICAL_TERMINAL_OUTCOME_SUCCESS,
            _CANONICAL_TERMINAL_OUTCOME_FAILURE,
        }:
            # Mixed terminal success/failure means some execution units produced
            # value while others failed, so this is the canonical partial_success
            # branch rather than a pure terminal conflict.
            return _CANONICAL_TERMINAL_OUTCOME_PARTIAL_SUCCESS
        # For non success/failure terminal mismatches, keep deterministic
        # precedence to the latest state uplink terminal observation.
        return state_terminal
    return result_terminal or state_terminal


def _normalize_reported_runtime_health(state_payload: Optional[Dict[str, Any]]) -> str:
    if not isinstance(state_payload, dict) or not state_payload:
        return "unknown"
    if bool(state_payload.get("recovered")):
        return "recovered"
    if bool(state_payload.get("degraded")):
        return "degraded"
    return "stable"


def _extract_reported_runtime_health_reason(state_payload: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(state_payload, dict) or not state_payload:
        return None
    raw_reason = state_payload.get("reason")
    if raw_reason is None:
        return None
    reason = str(raw_reason).strip()
    return reason or None


def get_uplink_truth_state(execution_id: str) -> Dict[str, Any]:
    lifecycle_history = get_execution_lifecycle_history(execution_id)
    uplink_records = get_all_uplink_records(execution_id)
    latest_phase = lifecycle_history[-1]["phase"] if lifecycle_history else None
    latest_result_payload = None
    latest_state_payload = None
    latest_result_recorded_at = None
    latest_state_recorded_at = None
    for record in uplink_records:
        if record["kind"] == UplinkKind.result_uplink.value:
            latest_result_payload = record["payload"]
            latest_result_recorded_at = float(record.get("recorded_at", 0.0) or 0.0)
        elif record["kind"] == UplinkKind.state_uplink.value:
            latest_state_payload = record["payload"]
            latest_state_recorded_at = float(record.get("recorded_at", 0.0) or 0.0)

    latest_lifecycle_event_at = (
        float(lifecycle_history[-1].get("event_at", 0.0) or 0.0)
        if lifecycle_history
        else 0.0
    )
    lifecycle_terminal_outcome = _normalize_terminal_outcome(latest_phase)
    is_terminal = bool(lifecycle_terminal_outcome)
    reported_result_outcome = _normalize_reported_outcome(latest_result_payload)
    reported_state_outcome = _normalize_reported_outcome(latest_state_payload)
    reported_result_terminal_outcome = _normalize_terminal_outcome(reported_result_outcome)
    reported_state_terminal_outcome = _normalize_terminal_outcome(reported_state_outcome)
    reported_terminal_outcome = _merge_reported_terminal_outcomes(
        reported_result_outcome,
        reported_state_outcome,
    )
    reported_runtime_health = _normalize_reported_runtime_health(latest_state_payload)
    reported_runtime_health_reason = _extract_reported_runtime_health_reason(latest_state_payload)
    # reported_outcome keeps backward-compatible phase-level projection
    # (legacy callers may rely on running/admitted/etc). Terminal callers
    # should use *_terminal_outcome fields for canonical completion closure.
    reported_outcome = reported_result_outcome or reported_state_outcome
    has_incomplete_uplink_data = bool(
        latest_result_payload is None or latest_state_payload is None
    )
    has_partial_authoritative_observation = bool(
        latest_phase and has_incomplete_uplink_data
    )
    if reported_result_terminal_outcome and reported_state_terminal_outcome:
        if reported_result_terminal_outcome == reported_state_terminal_outcome:
            reported_terminal_outcome_recorded_at = max(
                float(latest_result_recorded_at or 0.0),
                float(latest_state_recorded_at or 0.0),
            )
        elif {reported_result_terminal_outcome, reported_state_terminal_outcome} == {
            _CANONICAL_TERMINAL_OUTCOME_SUCCESS,
            _CANONICAL_TERMINAL_OUTCOME_FAILURE,
        }:
            reported_terminal_outcome_recorded_at = max(
                float(latest_result_recorded_at or 0.0),
                float(latest_state_recorded_at or 0.0),
            )
        else:
            reported_terminal_outcome_recorded_at = latest_state_recorded_at
    elif reported_result_terminal_outcome:
        reported_terminal_outcome_recorded_at = latest_result_recorded_at
    elif reported_state_terminal_outcome:
        reported_terminal_outcome_recorded_at = latest_state_recorded_at
    else:
        reported_terminal_outcome_recorded_at = None
    outcome_conflict = bool(
        lifecycle_terminal_outcome
        and reported_terminal_outcome
        and reported_terminal_outcome != lifecycle_terminal_outcome
    )
    delayed_observation = bool(
        outcome_conflict
        and latest_lifecycle_event_at > 0.0
        and reported_terminal_outcome_recorded_at is not None
        and reported_terminal_outcome_recorded_at > 0.0
        and reported_terminal_outcome_recorded_at
        > latest_lifecycle_event_at
    )
    in_progress_terminal_observation = bool(
        latest_phase and not lifecycle_terminal_outcome and reported_terminal_outcome
    )
    terminal_truth_authoritative_source = (
        "center_lifecycle"
        if lifecycle_terminal_outcome
        else (
            "reported_uplink"
            if (reported_terminal_outcome and not latest_phase)
            else "none"
        )
    )
    canonical_terminal_outcome = (
        lifecycle_terminal_outcome
        if lifecycle_terminal_outcome
        else (reported_terminal_outcome if not latest_phase else None)
    )
    if outcome_conflict:
        reconciliation_status = (
            "delayed_conflict_center_truth_retained"
            if delayed_observation
            else "conflict_center_truth_retained"
        )
        reconciliation_reason = (
            "reported_terminal_outcome_arrived_after_authoritative_terminal_phase"
            if delayed_observation
            else "reported_terminal_outcome_conflicts_with_authoritative_lifecycle"
        )
    elif is_terminal and has_partial_authoritative_observation:
        reconciliation_status = "accepted_partial_observation"
        reconciliation_reason = "authoritative_terminal_phase_with_partial_uplink_observation"
    elif is_terminal:
        reconciliation_status = "accepted"
        reconciliation_reason = "authoritative_terminal_phase_aligned_with_observation"
    elif in_progress_terminal_observation:
        reconciliation_status = "terminal_observation_held_for_lifecycle_authority"
        reconciliation_reason = "reported_terminal_outcome_arrived_before_authoritative_lifecycle_termination"
    elif latest_phase:
        reconciliation_status = "in_progress"
        reconciliation_reason = "authoritative_lifecycle_not_terminal"
    elif reported_terminal_outcome:
        reconciliation_status = "uplink_only_terminal_observation"
        reconciliation_reason = "reported_terminal_outcome_without_lifecycle_authority"
    elif reported_outcome:
        reconciliation_status = "uplink_only_observation"
        reconciliation_reason = "reported_observation_without_lifecycle_authority"
    else:
        reconciliation_status = "missing"
        reconciliation_reason = "no_lifecycle_or_uplink_observation"
    canonical_runtime_health = (
        reported_runtime_health
        if reported_runtime_health in _EXCEPTIONAL_RUNTIME_HEALTH_STATES
        else "stable"
    )
    canonical_outcome = latest_phase or reported_outcome or reported_terminal_outcome

    return {
        "execution_id": execution_id,
        "lifecycle_phase": latest_phase,
        "is_terminal": is_terminal,
        "result_uplink": latest_result_payload,
        "state_uplink": latest_state_payload,
        "result_uplink_count": sum(
            1 for record in uplink_records if record["kind"] == UplinkKind.result_uplink.value
        ),
        "state_uplink_count": sum(
            1 for record in uplink_records if record["kind"] == UplinkKind.state_uplink.value
        ),
        "lifecycle_event_count": len(lifecycle_history),
        "reported_outcome": reported_outcome,
        "canonical_outcome": canonical_outcome,
        "reported_terminal_outcome": reported_terminal_outcome,
        "canonical_terminal_outcome": canonical_terminal_outcome,
        "terminal_truth_authoritative_source": terminal_truth_authoritative_source,
        "terminal_truth_determined": canonical_terminal_outcome is not None,
        "authoritative_outcome_source": (
            "center_lifecycle"
            if latest_phase
            else ("reported_uplink" if (reported_outcome or reported_terminal_outcome) else "none")
        ),
        "reported_runtime_health": reported_runtime_health,
        "reported_runtime_health_reason": reported_runtime_health_reason,
        "canonical_runtime_health": canonical_runtime_health,
        "canonical_runtime_health_reason": (
            reported_runtime_health_reason
            if canonical_runtime_health in _EXCEPTIONAL_RUNTIME_HEALTH_STATES
            else None
        ),
        "reconciliation_status": reconciliation_status,
        "reconciliation_reason": reconciliation_reason,
        "reconciliation_conflict": outcome_conflict,
        "reconciliation_delayed_observation": delayed_observation,
        "reconciliation_partial_observation": has_partial_authoritative_observation,
        "reconciliation_terminal_observation_held": in_progress_terminal_observation,
        "_authority": UNIFIED_EXECUTION_GOVERNANCE_AUTHORITY,
        "_contract_version": UNIFIED_EXECUTION_GOVERNANCE_CONTRACT_VERSION,
    }


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
    *,
    completion_phase: ExecutionLifecyclePhase = ExecutionLifecyclePhase.succeeded,
    failure_semantic: Optional[FailureSemantic] = None,
    interruption_reason: Optional[InterruptionReason] = None,
    replay_reason: Optional[ReplayReason] = None,
    metadata: Optional[Dict[str, Any]] = None,
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
        if execution_id:
            record_execution_lifecycle_event(
                execution_id=execution_id,
                device_id=device_id,
                execution_type=execution_type,
                phase=completion_phase,
                failure_semantic=failure_semantic,
                interruption_reason=interruption_reason,
                replay_reason=replay_reason,
                detail="execution_terminalized",
                metadata=metadata,
            )
            record_result_uplink(
                execution_id=execution_id,
                device_id=device_id,
                execution_type=execution_type,
                payload={
                    "terminal_phase": completion_phase.value,
                    "failure_semantic": failure_semantic.value if failure_semantic else None,
                    "interruption_reason": interruption_reason.value if interruption_reason else None,
                    "replay_reason": replay_reason.value if replay_reason else None,
                },
            )
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


def _resolve_local_inference_availability(
    *,
    report_semantics: Optional[Dict[str, Any]],
    device_snapshot: Any,
) -> bool:
    """Return canonical local-inference availability with Android-report precedence."""
    if isinstance(report_semantics, dict):
        reported_value = report_semantics.get("local_inference_available")
        if reported_value is not None:
            return bool(reported_value)

    inferred_value = getattr(device_snapshot, "is_local_ai_ready", None)
    if callable(inferred_value):
        try:
            return bool(inferred_value())
        except Exception as exc:
            logger.debug(
                "_resolve_local_inference_availability: snapshot local-ai probe failed: %s",
                exc,
            )
            return False
    return False


def _clear_android_reported_runtime_truth(snapshot: Dict[str, Any]) -> None:
    """Downgrade Android-reported runtime truth to unknown/non-authoritative."""
    for field_name in _ANDROID_REPORTED_RUNTIME_TRUTH_FIELDS:
        snapshot[field_name] = None


def _has_android_reported_runtime_truth(snapshot: Dict[str, Any]) -> bool:
    """Return True when the snapshot currently carries Android-reported truth."""
    return any(snapshot.get(field_name) is not None for field_name in _ANDROID_REPORTED_RUNTIME_TRUTH_FIELDS)


def _normalize_android_semantics_age_s(snapshot: Dict[str, Any]) -> Optional[float]:
    """Return normalized Android semantics age, deriving from absorbed_at when needed."""
    raw_age_s = snapshot.get("android_semantics_age_s")
    age_s: Optional[float]
    try:
        age_s = float(raw_age_s) if raw_age_s is not None else None
    except (TypeError, ValueError):
        age_s = None

    if age_s is None:
        try:
            absorbed_at = float(snapshot.get("android_semantics_absorbed_at", 0.0) or 0.0)
        except (TypeError, ValueError):
            absorbed_at = 0.0
        if absorbed_at > 0.0:
            age_s = float(time.time() - absorbed_at)

    if age_s is None:
        return None

    if age_s < 0:
        logger.warning(
            "_normalize_android_semantics_age_s: negative semantics age=%s",
            age_s,
        )
    return max(0.0, age_s)


def _apply_android_runtime_truth_freshness_governance(
    snapshot: Dict[str, Any],
    *,
    device_snapshot: Any,
) -> None:
    """Freshness-gate Android-reported runtime truth before governance consumes it."""
    snapshot["android_semantics_freshness_threshold_s"] = (
        ANDROID_RUNTIME_SEMANTICS_STALE_AFTER_SECONDS
    )
    snapshot["android_semantics_freshness_state"] = "unknown"
    snapshot["android_semantics_freshness_reason"] = "no_android_runtime_truth"
    snapshot["android_runtime_truth_authority"] = "unknown"
    snapshot["android_runtime_truth_usable"] = False

    has_android_truth = _has_android_reported_runtime_truth(snapshot)
    normalized_age_s = _normalize_android_semantics_age_s(snapshot)
    snapshot["android_semantics_age_s"] = normalized_age_s

    if not has_android_truth:
        return

    if not snapshot.get("android_semantics_contract_complete", False):
        _clear_android_reported_runtime_truth(snapshot)
        snapshot["local_inference_available"] = _resolve_local_inference_availability(
            report_semantics=None,
            device_snapshot=device_snapshot,
        )
        contract_state = str(
            snapshot.get("android_semantics_contract_state") or "incomplete"
        ).strip().lower()
        snapshot["android_semantics_freshness_reason"] = (
            f"android_semantics_contract_{contract_state}"
        )
        snapshot["android_runtime_truth_authority"] = "downgraded_to_unknown"
        return

    if normalized_age_s is None:
        _clear_android_reported_runtime_truth(snapshot)
        snapshot["local_inference_available"] = _resolve_local_inference_availability(
            report_semantics=None,
            device_snapshot=device_snapshot,
        )
        snapshot["android_semantics_freshness_reason"] = "android_semantics_age_unavailable"
        snapshot["android_runtime_truth_authority"] = "downgraded_to_unknown"
        return

    if normalized_age_s > ANDROID_RUNTIME_SEMANTICS_STALE_AFTER_SECONDS:
        _clear_android_reported_runtime_truth(snapshot)
        snapshot["local_inference_available"] = _resolve_local_inference_availability(
            report_semantics=None,
            device_snapshot=device_snapshot,
        )
        snapshot["android_semantics_freshness_state"] = "stale"
        snapshot["android_semantics_freshness_reason"] = "android_semantics_age_exceeds_threshold"
        snapshot["android_runtime_truth_authority"] = "downgraded_to_unknown"
        return

    snapshot["android_semantics_freshness_state"] = "fresh"
    snapshot["android_semantics_freshness_reason"] = "android_semantics_age_within_threshold"
    snapshot["android_runtime_truth_authority"] = "authoritative"
    snapshot["android_runtime_truth_usable"] = True


def _get_android_runtime_pressure_snapshot(device_id: str) -> Dict[str, Any]:
    """Return Android runtime pressure truth for *device_id* (best effort)."""
    snapshot: Dict[str, Any] = {
        "offline_queue_depth": 0,
        "current_fallback_tier": None,
        "local_inference_available": False,
        "android_reported_mode": None,
        "android_reported_mode_state": None,
        "android_reported_mode_readiness_state": None,
        "android_reported_cross_device_eligibility": None,
        "android_reported_goal_execution_eligibility": None,
        "android_reported_parallel_execution_eligibility": None,
        "android_reported_local_intelligence_status": None,
        "android_reported_local_inference_ready": None,
        "android_reported_local_inference_available": None,
        "android_semantics_contract_state": "missing",
        "android_semantics_contract_complete": False,
        "android_semantics_missing_keys": [],
        "android_semantics_malformed_keys": [],
        "android_semantics_unknown_keys": [],
        "android_semantics_conflicts": [],
        "android_semantics_downgraded_reasons": [],
        "android_semantics_governance_readiness_impact": "block",
        "android_semantics_contract_diagnosis": None,
        "android_semantics_absorbed_at": 0.0,
        "android_semantics_reported_at": None,
        "android_semantics_age_s": None,
        "android_semantics_freshness_threshold_s": ANDROID_RUNTIME_SEMANTICS_STALE_AFTER_SECONDS,
        "android_semantics_freshness_state": "unknown",
        "android_semantics_freshness_reason": "no_android_runtime_truth",
        "android_runtime_truth_authority": "unknown",
        "android_runtime_truth_usable": False,
        "runtime_health_status": "unknown",
        "execution_busy": False,
        "snapshot_reconciliation_status": "unavailable",
        "snapshot_reconciliation_reason": "no_snapshot_reconciliation_data",
        "snapshot_conflict": False,
        "snapshot_ordering_basis": "none",
        "snapshot_last_updated_at": 0.0,
        "snapshot_reconciliation_applied": False,
        "latest_execution_event_phase": None,
        "latest_execution_event_absorbed_at": 0.0,
        "latest_execution_event_age_s": None,
        "execution_busy_window_seconds": EXECUTION_BUSY_THRESHOLD_SECONDS,
    }
    try:
        from core.android_device_state_store import (
            get_device_capability_report_semantics,
            get_device_state_snapshot,
            get_device_snapshot_reconciliation,
            list_recent_execution_events,
        )

        report_semantics = get_device_capability_report_semantics(device_id)
        if isinstance(report_semantics, dict) and report_semantics:
            snapshot["android_reported_mode"] = report_semantics.get("canonical_mode")
            snapshot["android_reported_mode_state"] = report_semantics.get("reported_mode_state")
            snapshot["android_reported_mode_readiness_state"] = report_semantics.get(
                "mode_readiness_state"
            )
            snapshot["android_reported_cross_device_eligibility"] = report_semantics.get(
                "cross_device_eligibility"
            )
            snapshot["android_reported_goal_execution_eligibility"] = report_semantics.get(
                "goal_execution_eligibility"
            )
            snapshot["android_reported_parallel_execution_eligibility"] = report_semantics.get(
                "parallel_execution_eligibility"
            )
            snapshot["android_reported_local_intelligence_status"] = report_semantics.get(
                "local_intelligence_status"
            )
            snapshot["android_reported_local_inference_ready"] = report_semantics.get(
                "local_inference_ready"
            )
            snapshot["android_reported_local_inference_available"] = report_semantics.get(
                "local_inference_available"
            )
            snapshot["android_semantics_contract_state"] = (
                report_semantics.get("canonical_gate_metadata_state") or "missing"
            )
            snapshot["android_semantics_contract_complete"] = bool(
                report_semantics.get("canonical_gate_metadata_complete", False)
            )
            snapshot["android_semantics_missing_keys"] = list(
                report_semantics.get("missing_canonical_gate_metadata_keys") or []
            )
            snapshot["android_semantics_malformed_keys"] = list(
                report_semantics.get("malformed_canonical_gate_metadata_keys") or []
            )
            snapshot["android_semantics_unknown_keys"] = list(
                report_semantics.get("unknown_canonical_gate_metadata_keys") or []
            )
            snapshot["android_semantics_conflicts"] = list(
                report_semantics.get("canonical_gate_semantic_conflicts") or []
            )
            snapshot["android_semantics_downgraded_reasons"] = list(
                report_semantics.get("downgraded_canonical_gate_metadata_reasons") or []
            )
            snapshot["android_semantics_governance_readiness_impact"] = str(
                report_semantics.get("canonical_gate_governance_readiness_impact")
                or "block"
            )
            snapshot["android_semantics_contract_diagnosis"] = (
                report_semantics.get("canonical_gate_contract_diagnosis")
            )
            _semantics_absorbed_at = report_semantics.get("absorbed_at")
            try:
                snapshot["android_semantics_absorbed_at"] = float(_semantics_absorbed_at or 0.0)
            except (TypeError, ValueError):
                snapshot["android_semantics_absorbed_at"] = 0.0
            _semantics_reported_at = report_semantics.get("reported_at")
            try:
                snapshot["android_semantics_reported_at"] = (
                    float(_semantics_reported_at)
                    if _semantics_reported_at is not None
                    else None
                )
            except (TypeError, ValueError):
                snapshot["android_semantics_reported_at"] = None
            _semantics_age_s = report_semantics.get("semantics_age_s")
            try:
                snapshot["android_semantics_age_s"] = (
                    float(_semantics_age_s) if _semantics_age_s is not None else None
                )
            except (TypeError, ValueError):
                snapshot["android_semantics_age_s"] = None
        device_snapshot = get_device_state_snapshot(device_id)
        if device_snapshot is not None:
            _queue_depth = getattr(device_snapshot, "offline_queue_depth", None)
            if isinstance(_queue_depth, int) and _queue_depth > 0:
                snapshot["offline_queue_depth"] = int(_queue_depth)
            snapshot["current_fallback_tier"] = getattr(
                device_snapshot, "current_fallback_tier", None
            )
            snapshot["local_inference_available"] = _resolve_local_inference_availability(
                report_semantics=report_semantics,
                device_snapshot=device_snapshot,
            )
            _health = getattr(device_snapshot, "runtime_health_snapshot", None)
            if isinstance(_health, dict):
                snapshot["runtime_health_status"] = str(
                    _health.get("status") or _health.get("state") or _health.get("health") or "unknown"
                ).strip().lower() or "unknown"
            reconciliation = get_device_snapshot_reconciliation(device_id)
            if isinstance(reconciliation, dict):
                snapshot["snapshot_reconciliation_status"] = str(
                    reconciliation.get("status", "unavailable")
                )
                snapshot["snapshot_reconciliation_reason"] = str(
                    reconciliation.get("reason", "unknown")
                )
                snapshot["snapshot_conflict"] = bool(reconciliation.get("conflict", False))
                snapshot["snapshot_ordering_basis"] = str(
                    reconciliation.get("ordering_basis", "none")
                )
                snapshot["snapshot_reconciliation_applied"] = bool(
                    reconciliation.get("applied", False)
                )
                _updated_at = reconciliation.get("updated_at", 0.0)
                try:
                    snapshot["snapshot_last_updated_at"] = float(_updated_at or 0.0)
                except (TypeError, ValueError):
                    snapshot["snapshot_last_updated_at"] = 0.0

        _apply_android_runtime_truth_freshness_governance(
            snapshot,
            device_snapshot=device_snapshot,
        )

        recent_events = list_recent_execution_events(flow_id=None, device_id=device_id, limit=1)
        if recent_events:
            recent_event = recent_events[0]
            _phase = str(getattr(recent_event, "phase", "") or "").strip().lower()
            _absorbed = float(getattr(recent_event, "absorbed_at", 0) or 0)
            _raw_age_s = float(time.time() - _absorbed)
            if _raw_age_s < 0:
                logger.warning(
                    "_get_android_runtime_pressure_snapshot: negative event age for %r (phase=%s, age=%s)",
                    device_id,
                    _phase,
                    _raw_age_s,
                )
            _age_s = max(0.0, _raw_age_s)
            snapshot["latest_execution_event_phase"] = _phase or None
            snapshot["latest_execution_event_absorbed_at"] = _absorbed
            snapshot["latest_execution_event_age_s"] = _age_s
            if _phase in {
                "planning",
                "grounding",
                "execution",
                "replan",
                "running",
                "admitted",
                "execution_started",
                "execution_progress",
                "active",
                "activating",
            } and _age_s < EXECUTION_BUSY_THRESHOLD_SECONDS:
                snapshot["execution_busy"] = True
    except Exception as exc:
        logger.debug(
            "_get_android_runtime_pressure_snapshot: unavailable for %r: %s",
            device_id,
            exc,
        )
    return snapshot


# ---------------------------------------------------------------------------
# PR-5: Android execution lifecycle truth quality classification
# ---------------------------------------------------------------------------

# Android execution phases considered "actively executing" on the Android side.
_ANDROID_ACTIVE_EXECUTION_PHASES: frozenset[str] = frozenset(
    {
        "planning",
        "grounding",
        "execution",
        "replan",
        "running",
        "admitted",
        # Android runtime truth uplink phase vocabulary (PR-5B / sequencer).
        "execution_started",
        "execution_progress",
        "active",
        "activating",
    }
)
# Android execution phases that indicate terminal completion on the Android side.
_ANDROID_TERMINAL_EXECUTION_PHASES: frozenset[str] = frozenset(
    {
        "completed",
        "succeeded",
        "failed",
        "cancelled",
        "canceled",
        "error",
        "timed_out",
        "timeout",
        # Android runtime emits stagnation_detected as a terminal failed outcome.
        "stagnation_detected",
        # Android runtime gate_decision marks a gate-terminal resolution event.
        "gate_decision",
    }
)


def _classify_android_execution_lifecycle_truth_quality(
    *,
    active_execution_count: int,
    latest_execution_event_phase: Optional[str],
    latest_execution_event_age_s: Optional[float],
) -> Tuple[str, str]:
    """Classify Android execution lifecycle truth quality for a single device.

    Parameters
    ----------
    active_execution_count:
        Number of active executions currently tracked by V2-local registry.
    latest_execution_event_phase:
        Most recent Android-reported execution event phase, or ``None`` if no
        events have been received.
    latest_execution_event_age_s:
        Age in seconds of the most recent Android event, or ``None``.

    Returns
    -------
    Tuple[str, str]
        ``(quality_value, reason)`` where *quality_value* is an
        :class:`AndroidExecutionLifecycleTruthQuality` string value and
        *reason* is a human-readable diagnostic string.
    """
    v2_has_active = active_execution_count > 0
    android_has_event = latest_execution_event_phase is not None
    # Normalize the phase string once to avoid redundant conversions.
    normalized_phase: str = (
        str(latest_execution_event_phase).lower() if android_has_event else ""
    )
    android_active = android_has_event and normalized_phase in _ANDROID_ACTIVE_EXECUTION_PHASES
    android_terminal = android_has_event and normalized_phase in _ANDROID_TERMINAL_EXECUTION_PHASES

    def _age_str() -> str:
        if latest_execution_event_age_s is None:
            return "unknown"
        return f"{latest_execution_event_age_s:.1f}s"

    # ── No V2 active executions ──────────────────────────────────────────────
    if not v2_has_active:
        if android_active:
            # Android is reporting an active execution that V2 has no record of.
            return (
                AndroidExecutionLifecycleTruthQuality.conflicting_remote.value,
                (
                    f"android_reports_active_phase={latest_execution_event_phase!r}"
                    f"(age={_age_str()})_but_v2_has_no_active_execution_tracked"
                ),
            )
        # Both idle or Android shows terminal/no event — clean idle state.
        return (
            AndroidExecutionLifecycleTruthQuality.v2_local_only.value,
            "no_active_execution_in_v2_or_android_confirmed_idle",
        )

    # ── V2 has active executions ─────────────────────────────────────────────
    if not android_has_event:
        # V2 is tracking executions but no Android evidence received at all.
        return (
            AndroidExecutionLifecycleTruthQuality.missing_remote.value,
            "v2_tracking_active_execution_but_no_android_lifecycle_evidence_received",
        )

    if android_terminal:
        # Android has reported terminal completion but V2 still tracks as active.
        return (
            AndroidExecutionLifecycleTruthQuality.conflicting_remote.value,
            (
                f"android_reports_terminal_phase={latest_execution_event_phase!r}"
                f"(age={_age_str()})_but_v2_still_tracking_active_execution"
            ),
        )

    if android_active:
        # Android confirms active execution — check staleness.
        if latest_execution_event_age_s is None:
            return (
                AndroidExecutionLifecycleTruthQuality.stale_remote.value,
                (
                    "android_reports_active_but_event_age_unavailable_"
                    "treating_as_stale"
                ),
            )
        if (
            latest_execution_event_age_s
            > ANDROID_EXECUTION_LIFECYCLE_TRUTH_STALE_AFTER_SECONDS
        ):
            return (
                AndroidExecutionLifecycleTruthQuality.stale_remote.value,
                (
                    f"android_event_age={_age_str()}_exceeds_stale_threshold="
                    f"{ANDROID_EXECUTION_LIFECYCLE_TRUTH_STALE_AFTER_SECONDS}s"
                ),
            )
        return (
            AndroidExecutionLifecycleTruthQuality.android_remote_confirmed.value,
            (
                f"android_confirms_active_phase={latest_execution_event_phase!r}"
                f"_age={_age_str()}_within_threshold"
            ),
        )

    # Android has an event with an unknown/unclassified phase while V2 is active.
    if latest_execution_event_age_s is not None and (
        latest_execution_event_age_s
        > ANDROID_EXECUTION_LIFECYCLE_TRUTH_STALE_AFTER_SECONDS
    ):
        return (
            AndroidExecutionLifecycleTruthQuality.stale_remote.value,
            (
                f"android_unclassified_phase={latest_execution_event_phase!r}"
                f"_age={_age_str()}_exceeds_stale_threshold"
            ),
        )
    return (
        AndroidExecutionLifecycleTruthQuality.v2_local_only.value,
        (
            f"v2_active_android_has_unclassified_phase="
            f"{latest_execution_event_phase!r}"
        ),
    )


def get_execution_lifecycle_truth_binding(
    device_id: str,
) -> ExecutionLifecycleTruthBinding:
    """Return the Android execution lifecycle truth binding for *device_id*.

    Reads the V2-local active execution registry and the Android execution
    event store to produce a canonical :class:`ExecutionLifecycleTruthBinding`
    that classifies how well Android-remote lifecycle state confirms V2-local
    tracking.

    This is the primary PR-5 public API.  Callers that build runtime snapshots
    or decision causality MUST call this function rather than reading V2-local
    tracking alone.

    Never raises — returns a ``v2_local_only`` binding on any error.

    Parameters
    ----------
    device_id:
        The Android device identifier to assess.

    Returns
    -------
    ExecutionLifecycleTruthBinding
        Always returned; never raises.
    """
    try:
        active_entries = _get_active_executions(device_id)
        active_count = len(active_entries)

        # Read Android execution event truth from the pressure snapshot
        # (already reads from android_device_state_store in a best-effort way).
        pressure = _get_android_runtime_pressure_snapshot(device_id)
        latest_phase = pressure.get("latest_execution_event_phase")
        latest_age_s: Optional[float] = pressure.get("latest_execution_event_age_s")

        quality_value, reason = _classify_android_execution_lifecycle_truth_quality(
            active_execution_count=active_count,
            latest_execution_event_phase=latest_phase,
            latest_execution_event_age_s=latest_age_s,
        )
        quality = AndroidExecutionLifecycleTruthQuality(quality_value)
        degraded = quality in _ANDROID_LIFECYCLE_TRUTH_DEGRADED_QUALITIES
        impact = str(
            _ANDROID_LIFECYCLE_TRUTH_GOVERNANCE_IMPACT.get(quality, "none")
        )
        return ExecutionLifecycleTruthBinding(
            device_id=device_id,
            android_lifecycle_truth_quality=quality,
            android_lifecycle_truth_reason=reason,
            android_lifecycle_truth_degraded=degraded,
            android_lifecycle_truth_governance_impact=impact,
            active_execution_count=active_count,
            latest_android_event_phase=latest_phase,
            latest_android_event_age_s=latest_age_s,
        )
    except Exception as exc:  # noqa: BLE001
        # Broad catch is intentional: this function is documented to never raise.
        # The possible sources of failure include ImportError, AttributeError, and
        # ValueError from the android_device_state_store layer, as well as any
        # unexpected runtime exception.  A safe fallback binding is returned so
        # callers are never disrupted by store unavailability.
        logger.debug(
            "get_execution_lifecycle_truth_binding: assessment failed for %r: %s",
            device_id,
            exc,
        )
        return ExecutionLifecycleTruthBinding(
            device_id=device_id,
            android_lifecycle_truth_quality=AndroidExecutionLifecycleTruthQuality.v2_local_only,
            android_lifecycle_truth_reason=f"assessment_error:{type(exc).__name__}",
            android_lifecycle_truth_degraded=False,
            android_lifecycle_truth_governance_impact="none",
        )


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
        runtime_pressure = _get_android_runtime_pressure_snapshot(device_id)
        # PR-5: Compute Android execution lifecycle truth binding for this device.
        truth_binding = get_execution_lifecycle_truth_binding(device_id)
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
                "offline_queue_depth": int(runtime_pressure.get("offline_queue_depth", 0) or 0),
                "current_fallback_tier": runtime_pressure.get("current_fallback_tier"),
                "local_inference_available": bool(runtime_pressure.get("local_inference_available", False)),
                "android_reported_mode": runtime_pressure.get("android_reported_mode"),
                "android_reported_mode_state": runtime_pressure.get("android_reported_mode_state"),
                "android_reported_mode_readiness_state": runtime_pressure.get(
                    "android_reported_mode_readiness_state"
                ),
                "android_reported_cross_device_eligibility": runtime_pressure.get(
                    "android_reported_cross_device_eligibility"
                ),
                "android_reported_goal_execution_eligibility": runtime_pressure.get(
                    "android_reported_goal_execution_eligibility"
                ),
                "android_reported_parallel_execution_eligibility": runtime_pressure.get(
                    "android_reported_parallel_execution_eligibility"
                ),
                "android_reported_local_intelligence_status": runtime_pressure.get(
                    "android_reported_local_intelligence_status"
                ),
                "android_reported_local_inference_ready": runtime_pressure.get(
                    "android_reported_local_inference_ready"
                ),
                "android_reported_local_inference_available": runtime_pressure.get(
                    "android_reported_local_inference_available"
                ),
                "android_semantics_contract_state": runtime_pressure.get(
                    "android_semantics_contract_state"
                ),
                "android_semantics_contract_complete": bool(
                    runtime_pressure.get("android_semantics_contract_complete", False)
                ),
                "android_semantics_missing_keys": list(
                    runtime_pressure.get("android_semantics_missing_keys", [])
                ),
                "android_semantics_malformed_keys": list(
                    runtime_pressure.get("android_semantics_malformed_keys", [])
                ),
                "android_semantics_unknown_keys": list(
                    runtime_pressure.get("android_semantics_unknown_keys", [])
                ),
                "android_semantics_conflicts": list(
                    runtime_pressure.get("android_semantics_conflicts", [])
                ),
                "android_semantics_downgraded_reasons": list(
                    runtime_pressure.get("android_semantics_downgraded_reasons", [])
                ),
                "android_semantics_governance_readiness_impact": str(
                    runtime_pressure.get(
                        "android_semantics_governance_readiness_impact",
                        "block",
                    )
                    or "block"
                ),
                "android_semantics_contract_diagnosis": runtime_pressure.get(
                    "android_semantics_contract_diagnosis"
                ),
                "android_semantics_absorbed_at": float(
                    runtime_pressure.get("android_semantics_absorbed_at", 0.0) or 0.0
                ),
                "android_semantics_reported_at": (
                    float(runtime_pressure.get("android_semantics_reported_at"))
                    if runtime_pressure.get("android_semantics_reported_at") is not None
                    else None
                ),
                "android_semantics_age_s": (
                    float(runtime_pressure.get("android_semantics_age_s"))
                    if runtime_pressure.get("android_semantics_age_s") is not None
                    else None
                ),
                "android_semantics_freshness_threshold_s": float(
                    runtime_pressure.get(
                        "android_semantics_freshness_threshold_s",
                        ANDROID_RUNTIME_SEMANTICS_STALE_AFTER_SECONDS,
                    )
                    or ANDROID_RUNTIME_SEMANTICS_STALE_AFTER_SECONDS
                ),
                "android_semantics_freshness_state": runtime_pressure.get(
                    "android_semantics_freshness_state"
                ),
                "android_semantics_freshness_reason": runtime_pressure.get(
                    "android_semantics_freshness_reason"
                ),
                "android_runtime_truth_authority": runtime_pressure.get(
                    "android_runtime_truth_authority"
                ),
                "android_runtime_truth_usable": bool(
                    runtime_pressure.get("android_runtime_truth_usable", False)
                ),
                "runtime_health_status": str(runtime_pressure.get("runtime_health_status", "unknown") or "unknown"),
                "execution_busy": bool(runtime_pressure.get("execution_busy", False)),
                "snapshot_reconciliation_status": str(
                    runtime_pressure.get("snapshot_reconciliation_status", "unavailable")
                ),
                "snapshot_reconciliation_reason": str(
                    runtime_pressure.get("snapshot_reconciliation_reason", "unknown")
                ),
                "snapshot_conflict": bool(runtime_pressure.get("snapshot_conflict", False)),
                "snapshot_ordering_basis": str(
                    runtime_pressure.get("snapshot_ordering_basis", "none")
                ),
                "snapshot_last_updated_at": float(
                    runtime_pressure.get("snapshot_last_updated_at", 0.0) or 0.0
                ),
                "snapshot_reconciliation_applied": bool(
                    runtime_pressure.get("snapshot_reconciliation_applied", False)
                ),
                "latest_execution_event_phase": runtime_pressure.get("latest_execution_event_phase"),
                "latest_execution_event_absorbed_at": float(
                    runtime_pressure.get("latest_execution_event_absorbed_at", 0.0) or 0.0
                ),
                "latest_execution_event_age_s": (
                    float(runtime_pressure.get("latest_execution_event_age_s"))
                    if runtime_pressure.get("latest_execution_event_age_s") is not None
                    else None
                ),
                "execution_busy_window_seconds": float(
                    runtime_pressure.get(
                        "execution_busy_window_seconds", EXECUTION_BUSY_THRESHOLD_SECONDS
                    )
                    or EXECUTION_BUSY_THRESHOLD_SECONDS
                ),
                # ── PR-5: Android execution lifecycle truth binding ───────────
                "android_lifecycle_truth_quality": truth_binding.android_lifecycle_truth_quality.value,
                "android_lifecycle_truth_reason": truth_binding.android_lifecycle_truth_reason,
                "android_lifecycle_truth_degraded": truth_binding.android_lifecycle_truth_degraded,
                "android_lifecycle_truth_governance_impact": (
                    truth_binding.android_lifecycle_truth_governance_impact
                ),
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
            require_parallel_execution=(
                execution_type in {ExecutionType.parallel_subtask, ExecutionType.delegated_execution}
            ),
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

    if register_if_accepted:
        record_execution_lifecycle_event(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=execution_type,
            phase=ExecutionLifecyclePhase.created,
            detail="execution_request_received",
            enforce_transition=False,
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
        record_execution_lifecycle_event(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=execution_type,
            phase=ExecutionLifecyclePhase.admitted,
            detail="execution_admitted_by_governance",
        )
        record_state_uplink(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=execution_type,
            payload={
                "governance_state": "admitted",
                "accepted": True,
            },
        )
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


# ---------------------------------------------------------------------------
# Android semantics conflict detection
# ---------------------------------------------------------------------------

# Local intelligence statuses that are semantically incompatible with
# local_inference_available=True.
#
# These token values are canonical Android-side report values that explicitly
# indicate the local AI/inference runtime is off or not functional.  Any device
# that simultaneously reports local_inference_available=True and one of these
# status values is producing contradictory metadata — one field claims inference
# is available while the other claims it is not operational.
#
# This set is intentionally conservative.  Add only status tokens that have
# established, cross-repo meaning (i.e., defined in the Android capability
# report contract).  Do not add ambiguous or transitional states (e.g.,
# "initializing") that may temporarily precede availability.
_LOCAL_INTELLIGENCE_UNAVAILABLE_STATUSES: frozenset = frozenset({
    "disabled",
    "unavailable",
    "not_available",
    "none",
    "off",
})


def _detect_android_semantics_conflicts(snapshot: Dict[str, Any]) -> List[str]:
    """Detect semantic conflicts in Android-reported capability/gate fields.

    Returns a list of human-readable conflict descriptions.  An empty list
    means no semantic conflicts were detected.

    Checks the following known conflicting pairs:

    1. ``mode=cross_device`` but ``cross_device_eligibility=False``
       — the device reports cross-device mode but denies cross-device
       eligibility simultaneously.

    2. ``goal_execution_eligibility=True`` but ``cross_device_eligibility=False``
       — goal execution requires cross-device mode; reporting goal eligibility
       without cross-device eligibility is semantically contradictory.

    3. ``local_inference_available=True`` but ``local_intelligence_status``
       is one of the known-unavailable tokens — the device simultaneously
       reports inference as available and its status as disabled/unavailable.

    4. ``local_inference_ready=True`` but ``local_inference_available=False``
       — inference is flagged ready but also flagged unavailable; a device
       that is ready MUST be available.

    Parameters
    ----------
    snapshot:
        A runtime pressure snapshot dict as built by
        :func:`_get_android_runtime_pressure_snapshot` or an equivalent
        dict carrying ``android_reported_*`` fields.

    Returns
    -------
    List[str]
        Stable, lowercase conflict-description tokens suitable for structured
        diagnostics output and regression-test assertions.
    """
    conflicts: List[str] = []

    reported_mode = (snapshot.get("android_reported_mode") or "").strip().lower()
    cross_device_eligibility = snapshot.get("android_reported_cross_device_eligibility")
    goal_execution_eligibility = snapshot.get("android_reported_goal_execution_eligibility")
    local_inference_available = snapshot.get("android_reported_local_inference_available")
    local_inference_ready = snapshot.get("android_reported_local_inference_ready")
    local_intelligence_status = str(
        snapshot.get("android_reported_local_intelligence_status") or ""
    ).strip().lower()

    # Conflict 1: mode=cross_device but cross_device_eligibility=False
    if reported_mode == "cross_device" and cross_device_eligibility is False:
        conflicts.append(
            "mode_cross_device_conflicts_with_cross_device_eligibility_false"
        )

    # Conflict 2: goal_execution_eligibility=True but cross_device_eligibility=False
    if goal_execution_eligibility is True and cross_device_eligibility is False:
        conflicts.append(
            "goal_execution_eligibility_true_conflicts_with_cross_device_eligibility_false"
        )

    # Conflict 3: local_inference_available=True but status is a known-unavailable token
    if (
        local_inference_available is True
        and local_intelligence_status
        and local_intelligence_status in _LOCAL_INTELLIGENCE_UNAVAILABLE_STATUSES
    ):
        conflicts.append(
            f"local_inference_available_true_conflicts_with_local_intelligence_status_{local_intelligence_status}"
        )

    # Conflict 4: local_inference_ready=True but local_inference_available=False
    if local_inference_ready is True and local_inference_available is False:
        conflicts.append(
            "local_inference_ready_true_conflicts_with_local_inference_available_false"
        )

    return conflicts


# ---------------------------------------------------------------------------
# Canonical proof input diagnosis
# ---------------------------------------------------------------------------

_CANONICAL_PROOF_INPUT_CONTRACT_STATES: frozenset = frozenset(
    {
        "complete",
        "stale",
        "conflicting",
        "malformed",
        "unknown",
        "downgraded",
        "partial",
        "missing",
        # Ingress may collapse semantic contradiction into coarse contract-state.
        "incompatible",
    }
)


def _normalize_diagnosis_token_list(raw_value: Any) -> List[str]:
    """Normalize diagnosis token inputs into a stable list-of-strings form."""
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        token = raw_value.strip()
        return [token] if token else []
    if isinstance(raw_value, (list, tuple, set, frozenset)):
        normalized: List[str] = []
        for item in raw_value:
            token = str(item).strip()
            if token:
                normalized.append(token)
        return normalized
    token = str(raw_value).strip()
    return [token] if token else []


def classify_canonical_proof_input_diagnosis(
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """Classify Android/runtime proof inputs and return a structured diagnosis.

    This is the canonical observability helper for understanding *why* a
    governance decision degraded.  It synthesises all individual proof-input
    fields from *snapshot* into a single, stable, structured diagnosis so
    that operators, regression tests, and contract validators can inspect
    the root cause of any canonical degradation in one place.

    Classification priority (highest → lowest):

    1. ``"conflicting"`` — semantically incompatible fields were reported.
    2. ``"malformed"`` — one or more required canonical gate metadata keys carry
       invalid / unparseable values.
    3. ``"unknown"`` — the payload contains unknown canonical gate metadata keys,
       indicating contract drift between Android and V2.
    4. ``"downgraded"`` — the contract is syntactically valid but Android itself
       reports degraded capability truth that must reduce canonical readiness.
    5. ``"stale"`` — semantics are present but older than the freshness threshold.
    6. ``"partial"`` — some required canonical gate metadata keys are absent.
    7. ``"missing"`` — no Android capability semantics were reported at all.
    8. ``"complete"`` — all keys present, no conflicts, fresh.

    Parameters
    ----------
    snapshot:
        A runtime pressure snapshot dict as produced by
        :func:`_get_android_runtime_pressure_snapshot` or an equivalent dict
        carrying the ``android_semantics_*`` and ``android_reported_*`` fields.
        The function is deliberately lenient — missing keys are treated as
        their safe defaults.

    Returns
    -------
    Dict[str, Any]
        ``proof_input_class``
            One of the eight classification strings above.
        ``proof_input_detail``
            A single human-readable sentence explaining the classification.
        ``proof_input_conflicts``
            List of semantic conflict tokens (empty when class ≠ "conflicting").
        ``proof_input_degradation_causes``
            List of specific cause tokens explaining why the class is not
            "complete".  Empty when class is "complete".
        ``_policy``
            Reference to :data:`CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY`.
    """
    degradation_causes: List[str] = []
    # Degradation-cause format convention:
    #   "<cause_type>:<cause_value>"
    # cause_type is a stable, lowercase token identifying the kind of issue.
    # cause_value is a detail string (key list, reason token, etc.).
    # This format is stable across versions; consumers may split on the first
    # ":" to extract cause_type for programmatic checks.

    snapshot_dict: Dict[str, Any] = snapshot if isinstance(snapshot, dict) else {}
    contract_state = str(
        snapshot_dict.get("android_semantics_contract_state") or "missing"
    ).strip().lower()
    missing_keys: List[str] = _normalize_diagnosis_token_list(
        snapshot_dict.get("android_semantics_missing_keys")
    )
    malformed_keys: List[str] = _normalize_diagnosis_token_list(
        snapshot_dict.get("android_semantics_malformed_keys")
    )
    unknown_keys: List[str] = _normalize_diagnosis_token_list(
        snapshot_dict.get("android_semantics_unknown_keys")
    )
    downgraded_reasons: List[str] = _normalize_diagnosis_token_list(
        snapshot_dict.get("android_semantics_downgraded_reasons")
    )
    freshness_state = str(
        snapshot_dict.get("android_semantics_freshness_state") or "unknown"
    ).strip().lower()
    freshness_reason = str(
        snapshot_dict.get("android_semantics_freshness_reason") or ""
    ).strip()
    runtime_truth_authority = str(
        snapshot_dict.get("android_runtime_truth_authority") or "unknown"
    ).strip().lower()

    if contract_state not in _CANONICAL_PROOF_INPUT_CONTRACT_STATES:
        degradation_causes.append(
            f"unrecognized_android_semantics_contract_state:{contract_state}"
        )
        return {
            "proof_input_class": "unknown",
            "proof_input_detail": (
                "Android capability report contains unrecognized "
                f"contract_state={contract_state!r}"
            ),
            "proof_input_conflicts": [],
            "proof_input_degradation_causes": degradation_causes,
            "_policy": CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY,
        }

    # --- semantic conflict check (highest priority) ---
    detected_conflicts = _detect_android_semantics_conflicts(snapshot_dict)
    ingress_conflicts = _normalize_diagnosis_token_list(
        snapshot_dict.get("android_semantics_conflicts")
    )
    if detected_conflicts or contract_state == "incompatible":
        # Merge locally re-derived conflicts with any ingress-side conflicts that
        # survived in the runtime snapshot so diagnosis remains stable end-to-end.
        all_conflicts = sorted(
            set(detected_conflicts + ingress_conflicts)
        )
        if not all_conflicts:
            # Defensive fallback: ingress may have already classified the contract as
            # incompatible even when only the coarse state survived transport.
            all_conflicts = ["android_capability_contract_incompatible"]
        for conflict in all_conflicts:
            degradation_causes.append(f"semantic_conflict:{conflict}")
        return {
            "proof_input_class": "conflicting",
            "proof_input_detail": (
                f"Android-reported fields carry {len(all_conflicts)} semantic "
                f"conflict(s): {', '.join(all_conflicts)}"
            ),
            "proof_input_conflicts": all_conflicts,
            "proof_input_degradation_causes": degradation_causes,
            "_policy": CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY,
        }

    # --- malformed (next priority) ---
    if malformed_keys or contract_state == "malformed":
        cause_keys = malformed_keys or []
        degradation_causes.append(
            f"malformed_canonical_gate_metadata_keys:{cause_keys}"
        )
        return {
            "proof_input_class": "malformed",
            "proof_input_detail": (
                f"Android capability report has malformed canonical gate metadata; "
                f"malformed_keys={cause_keys}"
            ),
            "proof_input_conflicts": [],
            "proof_input_degradation_causes": degradation_causes,
            "_policy": CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY,
        }

    # --- unknown contract drift (next priority) ---
    if unknown_keys or contract_state == "unknown":
        cause_keys = unknown_keys or []
        degradation_causes.append(
            f"unknown_canonical_gate_metadata_keys:{cause_keys}"
        )
        return {
            "proof_input_class": "unknown",
            "proof_input_detail": (
                "Android capability report contains unknown canonical gate "
                f"metadata keys: {cause_keys}"
            ),
            "proof_input_conflicts": [],
            "proof_input_degradation_causes": degradation_causes,
            "_policy": CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY,
        }

    # --- downgraded but not malformed/drifted ---
    if downgraded_reasons or contract_state == "downgraded":
        cause_reasons = downgraded_reasons or [
            "android_capability_contract_downgraded"
        ]
        degradation_causes.append(
            f"android_semantics_downgraded:{cause_reasons}"
        )
        return {
            "proof_input_class": "downgraded",
            "proof_input_detail": (
                "Android capability report is canonically downgraded by Android-"
                f"reported degraded truth; downgraded_reasons={cause_reasons}"
            ),
            "proof_input_conflicts": [],
            "proof_input_degradation_causes": degradation_causes,
            "_policy": CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY,
        }

    # --- stale (next priority) ---
    if freshness_state == "stale" or runtime_truth_authority == "downgraded_to_unknown":
        degradation_causes.append(
            f"android_semantics_stale:{freshness_reason or 'reason_unavailable'}"
        )
        return {
            "proof_input_class": "stale",
            "proof_input_detail": (
                f"Android semantics are stale or authority downgraded; "
                f"freshness_state={freshness_state!r}, "
                f"reason={freshness_reason!r}, "
                f"truth_authority={runtime_truth_authority!r}"
            ),
            "proof_input_conflicts": [],
            "proof_input_degradation_causes": degradation_causes,
            "_policy": CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY,
        }

    # --- partial (missing keys but present) ---
    if missing_keys or contract_state == "partial":
        cause_keys = missing_keys or []
        degradation_causes.append(
            f"missing_canonical_gate_metadata_keys:{cause_keys}"
        )
        return {
            "proof_input_class": "partial",
            "proof_input_detail": (
                f"Android capability report is missing {len(cause_keys)} required "
                f"canonical gate metadata key(s): {cause_keys}"
            ),
            "proof_input_conflicts": [],
            "proof_input_degradation_causes": degradation_causes,
            "_policy": CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY,
        }

    # --- missing (no semantics at all) ---
    if contract_state == "missing":
        degradation_causes.append("android_semantics_contract_state:missing")
        return {
            "proof_input_class": "missing",
            "proof_input_detail": (
                "No Android capability semantics have been reported for this device."
            ),
            "proof_input_conflicts": [],
            "proof_input_degradation_causes": degradation_causes,
            "_policy": CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY,
        }

    # --- complete ---
    return {
        "proof_input_class": "complete",
        "proof_input_detail": (
            "Android capability semantics are complete, fresh, and conflict-free."
        ),
        "proof_input_conflicts": [],
        "proof_input_degradation_causes": [],
        "_policy": CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY,
    }
