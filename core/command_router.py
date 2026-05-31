"""
core/command_router.py — Cross-Device Liminal Domain Expansion Router
=======================================================================

**Unified-Subject Architecture — Cross-Device Execution Loop**
---------------------------------------------------------------
``CommandRouter`` is the subject's **cross-device liminal domain expansion**
layer.  When ``OpenClawd._determine_execution_path()`` resolves the liminal
branch to ``"cross_device"`` or ``"hybrid"``, this module is invoked to route
commands to remote devices via the galaxy gateway.

Cross-device routing is **not** a parallel system alongside the subject — it
is the subject's liminal execution expanding beyond the local Windows host.
The liminal phase inside ``OpenClawd`` decides whether to branch locally,
cross-device, or both (hybrid).

In the unified subject flow::

    DesktopPresenceRuntime (shell)
        └─ LIMINAL: OpenClawd (core)
              └─ Stage 3: Branch → execution_path = "cross_device" | "hybrid"
              └─ Stage 4: Manifest
                    └─ DecisionExecutor (local Windows loop, for local/hybrid)
                    └─ CommandRouter (this module) ← CROSS-DEVICE expansion loop
                         Routes to remote devices via galaxy_gateway
                         (gateway is internal substrate, not a primary entrypoint)

**Relationship to the gateway**

The ``galaxy_gateway`` is the *internal cross-device execution substrate* of
the subject — it is the plumbing for cross-device routing, not a primary
subject entrypoint.  This router is the internal client of that substrate.

**PR-7: Unified Cross-Device Substrate (single substrate root)**

Both remote execution styles — ``command_only`` and ``agent_runtime`` — share
the same substrate root: :meth:`CommandRouter.route_envelope`.  They differ
only in *what* is carried in the :class:`~core.schemas.task_envelope.TaskEnvelope`
and how downstream handlers interpret it:

* ``command_only``  — structured command/task dispatch
  (:meth:`OpenClawd.send_gateway_command` → :meth:`route_envelope`)
* ``agent_runtime`` — agent deploy+execute dispatch
  (:meth:`dispatch_agent_remote` / :meth:`_deploy_agent_then_execute`
  → :meth:`route_envelope`)

All paths stamp :class:`~core.schemas.remote_execution.RemoteExecutionMode`
in the envelope *before* entering :meth:`route_envelope` so that mode
metadata is observable end-to-end without inspecting payload shapes.

**PR-8: Orchestration layer vs. substrate boundary**

``CommandRouter`` is the **execution substrate**, not the orchestration layer.

* **Orchestration layer** (:class:`~core.swarm_coordinator.SwarmCoordinator`,
  :class:`~core.control_plane.smart_scheduler.DeviceScoringEngine`) — decides
  *which* devices to use and *how to coordinate* multiple targets.  It
  expresses intent/selection/coordination decisions.  It does NOT perform
  transport routing.

* **Substrate layer** (this module, :meth:`route_envelope`) — handles
  *how* commands travel to remote devices: ACL enforcement, lifecycle
  management, NATS/WebSocket dispatch, timeout/retry.  It does NOT make
  device-selection or coordination decisions.

The orchestration layer calls :meth:`dispatch_agent_remote` or
:meth:`route_envelope` only *after* planning decisions are complete.  The
substrate then handles the transport/execution concerns exclusively.

Galaxy - 命令路由引擎
==========================

核心命令分发器，支持：
  - 请求 ID 追踪（全链路可追溯）
  - 并行 / 串行调度模式
  - 超时控制与自动重试
  - 多目标结果聚合
  - WebSocket 实时结果推送
  - 缓存命中（热命令 < 5ms）

融合元气 AI Bot 精髓：
  极速 - 缓存 + 并行，P99 < 100ms
  智能 - 意图感知优先级调度
  流畅 - 事件总线驱动实时反馈
  可靠 - 重试 + 熔断 + 降级
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

from core.schemas.task_envelope import TaskEnvelope

logger = logging.getLogger("Galaxy.CommandRouter")

COMMAND_ROUTER_ENTRYPOINT_ROLE: str = "internal_entry"
"""Entrypoint role contract (PR-01): cross-device substrate internal stage entry only."""

# ── PR-G5: resilience defaults from env vars (safe, backward-compatible) ────
_DEFAULT_MAX_QUEUE_DEPTH: int = int(os.environ.get("GALAXY_ROUTER_MAX_QUEUE_DEPTH", "200"))
_DEFAULT_CB_ENABLED: bool = os.environ.get("GALAXY_ROUTER_CB_ENABLED", "true").lower() not in ("false", "0")
_DEFAULT_ADAPTIVE_CONCURRENCY: bool = os.environ.get("GALAXY_ROUTER_ADAPTIVE_CONCURRENCY", "true").lower() not in (
    "false",
    "0",
)


# ============================================================================
# 错误代码 — 结构化、可解释的网关错误（PR-C）
# ============================================================================


class GatewayErrorCode(str, Enum):
    """网关层可解释错误代码"""

    INVALID_ENVELOPE = "INVALID_ENVELOPE"  # 消息体缺少必要字段
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"  # 设备未注册
    DEVICE_OFFLINE = "DEVICE_OFFLINE"  # 设备已注册但当前离线
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"  # 命令执行超时
    DISCONNECT = "DISCONNECT"  # 连接断开
    EXECUTOR_ERROR = "EXECUTOR_ERROR"  # 执行器内部错误
    INTERNAL_ERROR = "INTERNAL_ERROR"  # 未分类内部错误
    HITL_TIMEOUT = "HITL_TIMEOUT"  # HITL approval window elapsed
    HITL_DENIED = "HITL_DENIED"  # HITL approval denied by operator
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"  # PR-1 P0: target lacks required capabilities
    V3_SLOT_BLOCKED = "V3_SLOT_BLOCKED"  # PR-V3: canonical dispatch slot authority blocked all targets


@dataclass
class GatewayError(Exception):
    """结构化网关错误，携带可解释错误代码"""

    code: GatewayErrorCode
    message: str
    command_id: str = ""
    task_id: str = ""
    device_id: str = ""

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

    def to_dict(self) -> dict:
        return {
            "error": True,
            "error_code": self.code.value,
            "error_message": self.message,
            "command_id": self.command_id,
            "task_id": self.task_id,
            "device_id": self.device_id,
        }


# ============================================================================
# 协议信封验证（PR-C）
# ============================================================================

_REQUIRED_ENVELOPE_FIELDS: Tuple[str, ...] = ("command",)


def validate_command_envelope(
    device_id: str,
    command: str,
    payload: Dict[str, Any],
    command_id: str,
    task_id: str,
) -> None:
    """
    验证命令信封完整性。

    规则：
      - device_id 不能为空
      - command 不能为空
      - command_id 必须为非空字符串
      - task_id 必须为非空字符串
      - payload 必须为 dict（可为空 dict）

    Raises:
        GatewayError: 当信封不符合规范时，携带 INVALID_ENVELOPE 错误代码。
    """
    errors = []
    if not device_id:
        errors.append("device_id 为空")
    if not command:
        errors.append("command 为空")
    if not command_id:
        errors.append("command_id 为空")
    if not task_id:
        errors.append("task_id 为空")
    if not isinstance(payload, dict):
        errors.append(f"payload 必须为 dict，实际类型: {type(payload).__name__}")
    if errors:
        raise GatewayError(
            code=GatewayErrorCode.INVALID_ENVELOPE,
            message="; ".join(errors),
            command_id=command_id,
            task_id=task_id,
            device_id=device_id,
        )


# ============================================================================
# 命令模型
# ============================================================================

# ---------------------------------------------------------------------------
# PR (Canonical Execution Chain): Orchestration authority sentinel.
#
# CommandRouter is the canonical command orchestration authority for the
# Galaxy runtime.  After OpenClawd (the subject/execution core) accepts a
# request and branches to the device-dispatch path, ALL command orchestration
# decisions — ACL enforcement, HITL gating, lifecycle state transitions,
# retry / circuit-breaker, and TaskEnvelope propagation — MUST pass through
# this module.
#
# Authority chain:
#   route layer → OpenClawd → CommandRouter (here) → DeviceRouter → device
#
# Side-path orchestrators (e2e_orchestrator, capability_orchestrator, etc.)
# must delegate to CommandRouter.route_envelope() or act only as facades
# over it.  They MUST NOT own independent dispatch authority.
# ---------------------------------------------------------------------------
COMMAND_ROUTER_ORCHESTRATION_AUTHORITY: str = "core.command_router.CommandRouter"
"""Sentinel: CommandRouter is the canonical command orchestration authority.

Import this symbol to assert that a call site is within the canonical
execution chain (OpenClawd → CommandRouter → DeviceRouter → device).
"""

# PR-7: canonical dispatch spine sentinel — aligns with
# COMMAND_ROUTER_DISPATCH_SPINE_AUTHORITY in cross_device_execution_chain.
COMMAND_ROUTER_DISPATCH_SPINE_AUTHORITY: str = "COMMAND_ROUTER_DISPATCH_SPINE_V1"
"""Sentinel: CommandRouter.route_envelope is the *sole* canonical dispatch
spine for cross-device tasks.  All cross-device dispatch MUST enter through
route_envelope.  Direct send_to_device shortcuts outside this spine are
legacy compat paths and must be registered as such.
"""

# PR-3: Execution Spine Integration — legacy ingress governance sentinel.
COMMAND_ROUTER_LEGACY_INGRESS_POLICY: str = (
    "LEGACY_INGRESS_NORMALIZE_V1: non-envelope inputs entering CommandRouter "
    "are normalized to TaskEnvelope via core.execution_spine before dispatch; "
    "legacy call sources are recorded in the ExecutionSpine ingress log."
)
"""Policy sentinel: CommandRouter normalises non-envelope inputs and records
legacy call sources via the execution spine (core.execution_spine).

Importable to assert that an integration point is aware of the ingress
governance policy introduced in PR-3.
"""

# PR-4: Agent Bus & Fabric Convergence — transport strategy sentinel.
# CommandRouter is the transport strategy selection layer: it decides which
# carrier/substrate (direct / gateway / NATS / relay / mesh) to use for each
# dispatch, records the decision via core.agent_bus_fabric.record_fabric_event,
# and enforces the canonical TaskEnvelope/ResultEnvelope contract on every path.
COMMAND_ROUTER_TRANSPORT_STRATEGY_APPLIED: str = (
    "COMMAND_ROUTER::TRANSPORT_STRATEGY_LAYER_V1: CommandRouter selects "
    "transport strategy via core.agent_bus_fabric.select_transport_strategy() "
    "and records every dispatch decision for fabric observability."
)

COMMAND_ROUTER_PROBLEM_SPINE_ALIGNMENT_POLICY: str = (
    "COMMAND_ROUTER_PROBLEM_SPINE_ALIGNMENT_V1: route_envelope() must preserve "
    "task_id/trace_id metadata so NL problem-routing traces remain joinable "
    "with result-ingress closure semantics."
)
"""Policy sentinel: CommandRouter keeps NL problem spine traceability aligned."""

CANONICAL_TASK_SPINE_INTEGRATED: str = (
    "COMMAND_ROUTER::CANONICAL_TASK_SPINE_V1: CommandRouter.route_envelope() "
    "is the sole system-level dispatch spine for CanonicalTask→TaskEnvelope→"
    "transport execution. All legacy dispatch shortcuts are registered in "
    "core.legacy_dispatch_registry."
)

COMMAND_ROUTER_DUAL_GRAPH_INTEGRATED: str = (
    "COMMAND_ROUTER::DUAL_GRAPH_SELECTION_V1: CommandRouter consumes both "
    "the capability selection plane (core.capability_graph_selection) and "
    "the network topology runtime (core.network_topology_runtime) via "
    "core.capability_network_bridge to make joint provider+path routing "
    "decisions. Direct capability or topology reads outside the bridge are "
    "governance violations."
)

# PR-506: Execution Spine Write Integration sentinel.
#
# CommandRouter.route_envelope() is now the canonical write path for:
#   • TaskGraphRuntime  — envelope registration and result completion
#   • ReplayFoundation  — route-decision and task-execution records,
#                         retry and fallback replay events
#   • AuditEventSemantics — task_accepted / task_dispatched /
#                           task_completed / task_failed /
#                           retry_triggered / fallback_triggered events
#
# All writes are non-blocking (wrapped in try/except) so that observability
# failures never abort the canonical dispatch path.
#
# Compat / degraded paths that bypass route_envelope are marked via
# EXECUTION_SPINE_COMPAT_DEGRADED_AUDIT in their respective code paths so
# that they remain audit-visible rather than becoming silent black holes.
EXECUTION_SPINE_WRITE_INTEGRATED: str = (
    "COMMAND_ROUTER::EXECUTION_SPINE_WRITE_V1: "
    "route_envelope() is the production write path for TaskGraphRuntime, "
    "ReplayFoundation, and AuditEventSemantics. "
    "Retry and fallback events are written from _execute_command(). "
    "Compat dispatch() paths emit degraded audit markers."
)

#: PR-530: Confirms that CommandRouter carries ``trace_id`` from the incoming
#: TaskEnvelope into every result dict and every audit/replay event it emits.
#: This closes the spine-observability gap between OpenClawd and CommandRouter:
#: a request's ``trace_id`` is now visible end-to-end from process() through
#: route_envelope() through the audit layer.
COMMAND_ROUTER_CORRELATION_HARDENED: str = (
    "COMMAND_ROUTER::CORRELATION_HARDENED_V1: "
    "route_envelope() result dict carries trace_id from TaskEnvelope; "
    "dispatch() compat path propagates trace_id from metadata; "
    "full OpenClawd → CommandRouter → audit/replay correlation confirmed."
)

# PR-512: Runtime Closure Audit integration sentinel.
# The closure audit layer (core/runtime_closure_audit.py) covers all
# PR-506–511 layers including this module.  This sentinel asserts that
# CommandRouter participates in the PR-512 closure audit sweep.
RUNTIME_CLOSURE_AUDIT_INTEGRATED: str = (
    "COMMAND_ROUTER::RUNTIME_CLOSURE_AUDIT_INTEGRATED_V1: "
    "CommandRouter.route_envelope() is covered by the PR-512 closure audit. "
    "Sentinel verified by RuntimeClosureAudit.verify_all_layers()."
)

# PR-513 / GAP-512-004: CommandRouter now queries canonical capability/network
# truth before selecting dispatch targets.
CAPABILITY_NETWORK_CANONICAL_QUERY_INTEGRATED: str = (
    "COMMAND_ROUTER::CAPABILITY_NETWORK_CANONICAL_QUERY_V1: "
    "CommandRouter.route_envelope() calls query_routable_executors() and "
    "query_network_path() from capability_network_runtime_policy before "
    "dispatch so routing decisions reflect canonical capability/network truth "
    "(GAP-512-004)."
)

# PR-518 / GAP-517-001: CommandRouter is the sole canonical cross-device
# dispatcher.  When route_envelope() receives an envelope with
# metadata["cross_device"] == "true", it delegates to
# _route_cross_device_envelope() which invokes the DeviceRouter substrate
# (DeviceRouter.route_task) for execution plumbing, while all canonical
# audit/trace/graph work remains in route_envelope().
# Closes GAP-517-001 (cross-device REST ingress canonicalisation).
COMMAND_ROUTER_CROSS_DEVICE_CANONICAL_PATH: str = (
    "COMMAND_ROUTER::CROSS_DEVICE_CANONICAL_PATH_V1: "
    "route_envelope() is the sole canonical cross-device dispatcher. "
    "Envelopes with metadata['cross_device']=='true' are routed via "
    "_route_cross_device_envelope() → DeviceRouter.route_task() substrate. "
    "Resolves GAP-517-001."
)

# PR-532 / GAP-517-002: CommandRouter is also the sole canonical parallel
# device-entry dispatcher.  The REST parallel endpoint now submits a top-level
# TaskEnvelope with metadata["parallel_fanout"] == "true"; route_envelope()
# delegates to _route_parallel_fanout_envelope() which creates canonical
# sub-envelopes and admits each through CommandRouter before reaching the
# device substrate.
COMMAND_ROUTER_PARALLEL_FANOUT_CANONICAL_PATH: str = (
    "COMMAND_ROUTER::PARALLEL_FANOUT_CANONICAL_PATH_V1: "
    "route_envelope() detects metadata['parallel_fanout']=='true' and uses "
    "_route_parallel_fanout_envelope() to fan out canonical sub-envelopes. "
    "Resolves GAP-517-002."
)

# PR-518: metadata key that identifies the canonical substrate caller when
# DeviceRouter invokes CrossDeviceCoordinator.  Passed via context dict so
# that coordinators can detect and warn on non-canonical invocations (GAP-517-003).
_CROSS_DEVICE_SUBSTRATE_CALLER_KEY: str = "_galaxy_cross_device_substrate_caller"

# PR-3 (UCS follow-up): Capability graph selection enforcement sentinel.
#
# CommandRouter.route_envelope() now passes required_capabilities to
# query_routable_executors() so routing decisions reflect the canonical
# capability graph rather than issuing an unfiltered advisory query.
# When required_capabilities is set and routable executors are found in the
# canonical graph, the selected targets are validated/filtered against the
# confirmed capability graph entries.  Targets not confirmed in the graph
# receive a structured warning; confirmed targets proceed unchanged.
# Falls back gracefully when the capability layer is unavailable.
# Closes GAP-512-004.
CAPABILITY_GRAPH_SELECTION_ENFORCED: str = (
    "COMMAND_ROUTER::CAPABILITY_GRAPH_SELECTION_ENFORCED_V1: "
    "route_envelope() passes required_capabilities to query_routable_executors() "
    "and enforces target validation against the canonical capability graph "
    "when capabilities are specified. Unconfirmed targets emit structured "
    "warnings; routing falls back gracefully if the layer is unavailable. "
    "Closes GAP-512-004."
)

# PR-1 P0: Capability-Aware Scheduling Closure sentinel.
#
# When required_capabilities is set and an explicit device_id target is NOT
# confirmed in the capability graph:
#   - If the capability graph contains alternative routable executors, the
#     envelope targets are replaced with those alternatives (controlled
#     fallback — not silent bypass).
#   - If no routable alternatives exist, routing is rejected with a
#     structured CAPABILITY_MISMATCH error rather than proceeding blindly.
# In both cases the decision is logged at WARNING level so routing choices
# remain observable and auditable.  Explicit device_id can no longer
# silently bypass capability verification.
CAPABILITY_MISMATCH_CONTROLLED_DECISION: str = (
    "COMMAND_ROUTER::CAPABILITY_MISMATCH_CONTROLLED_DECISION_V1: "
    "When required_capabilities is set and all explicit targets fail the "
    "capability graph check, route_envelope() falls back to confirmed-capable "
    "alternatives from query_routable_executors() when available, or rejects "
    "the dispatch with CAPABILITY_MISMATCH when no capable executor exists. "
    "Explicit device_id no longer silently bypasses capability verification. "
    "PR-1 P0 closure."
)

# PR-E: Explicit executor target typing — first-class dispatch routing.
#
# route_envelope() now inspects envelope.executor_target_type as the
# *primary* branching input for dispatch path selection.  When the field is
# set, no ID guessing or metadata heuristic is needed:
#
#   ExecutorTargetType.android_device  → _route_cross_device_envelope()
#   ExecutorTargetType.node_service    → _route_cross_device_envelope()
#   ExecutorTargetType.go_worker       → _route_worker_envelope() (MasterBrain)
#   ExecutorTargetType.local           → _execute_command() (local runtime)
#
# When executor_target_type is None the existing metadata-based heuristics
# (cross_device / parallel_fanout flags) remain active for backward compat.
#
# Boundary between direct envelope routing and MasterBrain/worker dispatch
# -------------------------------------------------------------------------
# Direct envelope routing (android_device / node_service / local):
#   CommandRouter remains the sole orchestration authority.  Envelopes travel
#   directly to the target via DeviceRouter or the local executor.  All
#   canonical audit / trace / graph writes occur in route_envelope() itself.
#
# MasterBrain/worker dispatch (go_worker):
#   CommandRouter delegates to _route_worker_envelope(), which calls
#   MasterBrain.dispatch_task().  MasterBrain owns worker selection, NATS
#   publication, and worker-level retry.  CommandRouter remains the
#   *system-level* canonical authority (ACL, lifecycle, audit, trace) while
#   MasterBrain is the *worker-domain* authority (worker selection, NATS
#   routing, worker lifecycle).  The two authorities are non-overlapping.
EXECUTOR_TARGET_TYPE_ROUTING_POLICY: str = (
    "COMMAND_ROUTER::EXECUTOR_TARGET_TYPE_ROUTING_V1: "
    "route_envelope() uses TaskEnvelope.executor_target_type as the primary "
    "dispatch branch selector. android_device/node_service → "
    "_route_cross_device_envelope(); go_worker → _route_worker_envelope() "
    "(MasterBrain); local → _execute_command(). "
    "None falls back to metadata heuristics for backward compat. (PR-E)"
)

MASTERBRAIN_WORKER_DISPATCH_BOUNDARY: str = (
    "COMMAND_ROUTER::MASTERBRAIN_WORKER_DISPATCH_BOUNDARY_V1: "
    "For go_worker targets, CommandRouter is the system-level authority "
    "(ACL, lifecycle, audit, trace) while MasterBrain is the worker-domain "
    "authority (worker selection, NATS routing, worker lifecycle). "
    "CommandRouter delegates via _route_worker_envelope() → "
    "MasterBrain.dispatch_task(). The two authority domains are "
    "non-overlapping. (PR-E)"
)

POLICY_ENGINE_CONSULTED_ON_HEURISTIC_PATH: str = (
    "COMMAND_ROUTER::POLICY_ENGINE_CONSULTED_ON_HEURISTIC_PATH_PR5A: "
    "When executor_target_type is None, route_envelope() consults "
    "apply_target_selection_policy() from "
    "core.runtime.execution_target_policy_engine before falling through to "
    "legacy metadata heuristics.  The policy decision is recorded in "
    "envelope.metadata['_policy_selection_decision'] for downstream "
    "observability.  Legacy heuristic branches are not changed — backward "
    "compat is preserved.  This is the canonical production call site for "
    "the policy engine on the main routing path.  PR-5A."
)

# PR-ALIGN / SCHED-002: Target admissibility validation in cross-device dispatch.
#
# _route_cross_device_envelope() now calls validate_target_device() for each
# target in the envelope before delegating to DeviceRouter, ensuring that only
# devices that pass the canonical admissibility chain (readiness → participation
# → capability) are routed.  Invalid targets are excluded with a structured
# warning; the validated primary target is propagated as context["device_id"] so
# DeviceRouter uses the canonical target rather than re-selecting from its local
# session cache.  Gracefully degrades when the validator is unavailable.
# Closes the gap between CommandRouter's validated target set and DeviceRouter's
# independent device selection path.  Resolves SCHED-002.
COMMAND_ROUTER_TARGET_ADMISSIBILITY_VALIDATED: str = (
    "COMMAND_ROUTER::TARGET_ADMISSIBILITY_VALIDATED_V1: "
    "_route_cross_device_envelope() validates envelope targets via "
    "core.target_device_validator.validate_target_device() before dispatch. "
    "Invalid targets are excluded; validated primary target is passed as "
    "context['device_id'] to DeviceRouter.  Graceful degradation if validator "
    "unavailable.  Resolves SCHED-002."
)

# PR-dispatch-discipline: Uniform constraint chain enforcement across all paths.
#
# route_envelope() now runs a unified pre-dispatch constraint gate that applies
# admissibility, session-truth/posture, and topology checks BEFORE any execution
# branching occurs.  This ensures all intended dispatch paths — including local,
# cross-device, worker, and parallel-fanout sub-envelopes — are subject to the
# same constraint chain, not only _route_cross_device_envelope().
#
# Gate A — Session-truth / posture-aware filter
#   Consults core.source_execution_eligibility.check_source_execution_eligibility()
#   using the source_runtime_posture hint from envelope.metadata.  Records the
#   posture eligibility decision in _constraint_chain_trace so that downstream
#   layers and reviewers can verify the constraint was consulted.
#
# Gate B — Admissibility chain for device targets
#   Validates envelope targets via core.target_device_validator.validate_target_device()
#   (readiness → participation → capability layers) before any path branching.
#   Excluded targets are filtered out with a structured warning; when all
#   targets fail the check the dispatch proceeds with originals (graceful
#   degradation) rather than silently dropping.
#
# Both gates degrade gracefully when their backing modules are unavailable —
# the import is wrapped in try/except, the constraint check is skipped, and
# the trace entry records the skip reason so gaps remain observable rather
# than invisible.
#
# The trace dict is propagated into the result under "_constraint_chain_trace"
# for end-to-end reviewability.
DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT: str = (
    "COMMAND_ROUTER::DISPATCH_CONSTRAINT_CHAIN_UNIFORM_V1: "
    "route_envelope() applies a unified pre-dispatch constraint gate covering "
    "admissibility (readiness→participation→capability via target_device_validator), "
    "session-truth posture (source_runtime_posture via source_execution_eligibility), "
    "and topology/network path (via capability_network_runtime_policy) across ALL "
    "dispatch paths before execution branching. "
    "Constraint chain trace propagated to result under '_constraint_chain_trace' "
    "for end-to-end route-decision reviewability. "
    "Graceful degradation preserves backward compat when backing modules are absent."
)

# Sentinel confirming that session-truth posture is consulted at the dispatch
# level in route_envelope(), not only in result-merge / post-execution paths.
SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED: str = (
    "COMMAND_ROUTER::SESSION_TRUTH_POSTURE_DISPATCH_FILTER_V1: "
    "route_envelope() consults canonical session-truth posture "
    "(envelope.metadata['source_runtime_posture']) via "
    "core.source_execution_eligibility.check_source_execution_eligibility() "
    "as Gate A of the unified pre-dispatch constraint chain. "
    "Posture decision (eligible/posture/reason) is recorded in "
    "_constraint_chain_trace for reviewability. "
    "control_only sources that attempt non-cross-device local dispatch "
    "are flagged in the trace; join_runtime sources pass without restriction."
)


class CommandMode(str, Enum):
    """命令执行模式"""

    SYNC = "sync"  # 同步：等待结果返回
    ASYNC = "async"  # 异步：立即返回 request_id
    PARALLEL = "parallel"  # 并行：多目标同时执行
    SERIAL = "serial"  # 串行：多目标顺序执行


class _RouteResultProxy:
    """Minimal adapter that presents a raw result dict as a ResultEnvelope-like
    object so that :meth:`TaskGraphRuntime.complete_from_result_envelope` can
    consume it without requiring the full ``ResultEnvelope`` type.

    PR-506: Used in :meth:`CommandRouter.route_envelope` to close the graph node
    from the raw dict returned by :meth:`_execute_command`.
    """

    __slots__ = ("task_id", "success", "result", "error")

    def __init__(self, task_id: str, success: bool, result_data: Any, error: str) -> None:
        self.task_id = task_id
        self.success = success
        self.result = result_data
        self.error = error


@dataclass
class _ParallelSubtask:
    """Internal helper for canonical parallel fan-out bookkeeping."""

    index: int
    info: Dict[str, Any]
    envelope: TaskEnvelope


class CommandStatus(str, Enum):
    """命令状态"""

    PENDING = "pending"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"  # 部分成功
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class CommandRequest:
    """命令请求"""

    request_id: str = field(default_factory=lambda: f"cmd_{uuid.uuid4().hex[:12]}")
    source: str = ""  # 来源: api / ws / scheduler / ai
    targets: List[str] = field(default_factory=list)  # 目标节点 / 设备
    command: str = ""  # 命令名称
    params: Dict[str, Any] = field(default_factory=dict)
    mode: CommandMode = CommandMode.SYNC
    timeout: float = 30.0  # 超时秒数
    max_retries: int = 2  # 最大重试次数
    notify_ws: bool = True  # 是否通过 WebSocket 推送结果
    priority: int = 5  # 优先级 1-10（1=最高）
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class TargetResult:
    """单个目标的执行结果"""

    target: str
    status: CommandStatus = CommandStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    retries: int = 0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


@dataclass
class CommandResult:
    """聚合命令结果"""

    request_id: str
    status: CommandStatus = CommandStatus.PENDING
    targets: Dict[str, TargetResult] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    total_latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "status": self.status.value,
            "targets": {
                t: {
                    "target": r.target,
                    "status": r.status.value,
                    "result": r.result,
                    "error": r.error,
                    "latency_ms": round(r.latency_ms, 2),
                    "retries": r.retries,
                }
                for t, r in self.targets.items()
            },
            "total_latency_ms": round(self.total_latency_ms, 2),
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "completed_at": (datetime.fromtimestamp(self.completed_at).isoformat() if self.completed_at else None),
            "metadata": self.metadata,
        }


# ============================================================================
# 命令路由引擎
# ============================================================================


class CommandRouter:
    """
    命令路由引擎

    职责：
      1. 接收 CommandRequest → 分配 request_id
      2. 按 mode 调度到目标（parallel / serial / sync / async）
      3. 每个目标有独立 timeout + retry
      4. 聚合所有目标结果
      5. 通过回调推送实时状态变更
    """

    # Phase 2: commands that require HITL approval before execution
    _HIGH_RISK_COMMANDS: frozenset = frozenset(
        {
            "delete",
            "format",
            "shutdown",
            "reboot",
            "wipe",
            "rm",
            "remove",
            "purge",
            "factory_reset",
            "execute_shell",
            "run_script",
            "sudo",
            "transfer_funds",
            "payment",
            "checkout",
            "drone_takeoff",
            "arm_system",
            "system_change",
            "registry_write",
        }
    )

    def __init__(
        self,
        executor: Optional[Callable[..., Coroutine]] = None,
        cache_backend=None,
        on_status_change: Optional[Callable] = None,
        max_concurrent: int = 20,
        max_queue_depth: int = _DEFAULT_MAX_QUEUE_DEPTH,
        cb_enabled: bool = _DEFAULT_CB_ENABLED,
        adaptive_concurrency: bool = _DEFAULT_ADAPTIVE_CONCURRENCY,
    ):
        """
        Args:
            executor: 异步执行函数 (target, command, params) -> result
            cache_backend: 缓存后端（CacheManager 实例）
            on_status_change: 状态变更回调（用于 WebSocket 推送）
            max_concurrent: 最大并发执行数（静态上限；自适应模式以此为初始值）
            max_queue_depth: 入队等待上限；超出时直接返回 429 降级响应（PR-G5）
            cb_enabled: 启用每目标熔断器（PR-G5）
            adaptive_concurrency: 启用自适应并发控制（PR-G5）
        """
        self._executor = executor
        self._cache = cache_backend
        self._on_status_change = on_status_change
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent

        # ── PR-G5: resilience controls ───────────────────────────────────
        self._max_queue_depth = max_queue_depth
        self._cb_enabled = cb_enabled
        self._adaptive_concurrency_enabled = adaptive_concurrency

        # Per-target circuit breakers (created lazily)
        self._circuit_breakers: Dict[str, Any] = {}

        # Adaptive semaphore (replaces static semaphore when enabled)
        if adaptive_concurrency:
            try:
                from core.resilience.adaptive_semaphore import AdaptiveSemaphore

                self._adaptive_sem: Optional[Any] = AdaptiveSemaphore(
                    initial_limit=max_concurrent,
                    max_limit=max(max_concurrent * 3, 50),
                )
            except Exception as exc:
                logger.debug("Fallback triggered: %s", exc)
                self._adaptive_sem = None
        else:
            self._adaptive_sem = None

        # Resilience metrics singleton
        try:
            from core.resilience.metrics import get_resilience_metrics

            self._resilience_metrics: Optional[Any] = get_resilience_metrics()
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            self._resilience_metrics = None

        # 请求存储（内存，可扩展到 Redis）
        self._results: Dict[str, CommandResult] = {}
        self._pending_futures: Dict[str, asyncio.Task] = {}

        # 统计
        self._stats = {
            "total_dispatched": 0,
            "total_success": 0,
            "total_failed": 0,
            "total_timeout": 0,
            "cache_hits": 0,
            "avg_latency_ms": 0.0,
            # PR-G5 additions
            "total_rejected": 0,
            "total_fallbacks": 0,
        }
        self._latencies: List[float] = []

    # ------------------------------------------------------------------
    # Control Plane Phase 2 helpers
    # ------------------------------------------------------------------

    def _is_high_risk_command(self, command: str) -> bool:
        """Return True when *command* matches a known high-risk pattern."""
        cmd_lower = command.lower()
        return any(kw in cmd_lower for kw in self._HIGH_RISK_COMMANDS)

    def _emit_audit(
        self,
        event_type,
        *,
        source: str = "command_router",
        message: str = "",
        trace_id: Optional[str] = None,
        task_id: Optional[str] = None,
        device_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Append a :class:`TraceEvent` to the shared ledger; never raises."""
        try:
            from core.control_plane._globals import get_audit_ledger
            from core.control_plane.audit_ledger import Severity

            return get_audit_ledger().append(
                event_type,
                severity=Severity.INFO,
                source=source,
                message=message,
                trace_id=trace_id,
                task_id=task_id,
                device_id=device_id,
                payload=payload or {},
            )
        except Exception as exc:
            return None

    # ------------------------------------------------------------------
    # PR-G5: resilience helpers
    # ------------------------------------------------------------------

    def _get_circuit_breaker(self, target: str) -> Optional[Any]:
        """Return the per-target :class:`CircuitBreaker`, creating it lazily."""
        if not self._cb_enabled:
            return None
        if target not in self._circuit_breakers:
            try:
                from core.resilience.circuit_breaker import CircuitBreaker

                self._circuit_breakers[target] = CircuitBreaker(target=target)
            except Exception as exc:
                return None
        return self._circuit_breakers.get(target)

    def _count_active_requests(self) -> int:
        """Number of requests currently in PENDING / DISPATCHING / RUNNING state."""
        return sum(
            1
            for r in self._results.values()
            if r.status
            in (
                CommandStatus.PENDING,
                CommandStatus.DISPATCHING,
                CommandStatus.RUNNING,
            )
        )

    def _make_throttled_result(self, request: CommandRequest) -> CommandResult:
        """Build a FAILED CommandResult representing a queue-full rejection."""
        cmd_result = CommandResult(
            request_id=request.request_id,
            status=CommandStatus.FAILED,
            metadata={**request.metadata, "throttled": True, "error": "Queue depth limit exceeded; request rejected"},
        )
        for target in request.targets:
            tr = TargetResult(target=target)
            tr.status = CommandStatus.FAILED
            tr.error = "throttled"
            cmd_result.targets[target] = tr
        cmd_result.completed_at = time.time()
        return cmd_result

    def get_resilience_snapshot(self) -> Dict[str, Any]:
        """Return a combined resilience snapshot: metrics + per-target CB states."""
        metrics = {}
        if self._resilience_metrics is not None:
            try:
                metrics = self._resilience_metrics.snapshot()
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

        cb_states = {}
        for tgt, cb in self._circuit_breakers.items():
            try:
                cb_states[tgt] = cb.snapshot()
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

        adaptive = {}
        if self._adaptive_sem is not None:
            try:
                adaptive = self._adaptive_sem.snapshot()
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

        return {
            "metrics": metrics,
            "circuit_breakers": cb_states,
            "adaptive_semaphore": adaptive,
            "queue_depth": self._count_active_requests(),
            "max_queue_depth": self._max_queue_depth,
            "cb_enabled": self._cb_enabled,
            "adaptive_concurrency_enabled": self._adaptive_concurrency_enabled,
        }

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def dispatch(self, request: CommandRequest) -> CommandResult:
        """兼容层（PR-2）：接收旧 CommandRequest 后立即转换为 TaskEnvelope 完成统一路由。

        新代码应直接构造 :class:`~core.schemas.task_envelope.TaskEnvelope` 并调用
        :meth:`route_envelope`。此方法保留以兼容尚未迁移的调用方。

        内部唯一任务格式：TaskEnvelope（PR-2）。
        """
        # Default fallback values for optional CommandRequest fields.
        _DEFAULT_PRIORITY = 5
        _DEFAULT_TIMEOUT = 30.0

        # PR-2: 立即将 CommandRequest 转换为 TaskEnvelope，统一内部追踪标识。
        try:
            from core.schemas.task_envelope import TaskEnvelope as _TE

            _dispatch_envelope = _TE(
                task_id=request.request_id,
                trace_id=(request.metadata or {}).get("trace_id") or None,
                source=request.source,
                targets=list(request.targets),
                tool_name=request.command,
                args=dict(request.params or {}),
                priority=(
                    request.priority
                    if hasattr(request, "priority") and request.priority is not None
                    else _DEFAULT_PRIORITY
                ),
                timeout=request.timeout if hasattr(request, "timeout") and request.timeout else _DEFAULT_TIMEOUT,
                metadata=dict(request.metadata or {}),
            )
            logger.debug(
                "CommandRouter.dispatch compat | task_id=%s trace_id=%s command=%s targets=%s",
                _dispatch_envelope.task_id,
                _dispatch_envelope.trace_id,
                _dispatch_envelope.tool_name,
                _dispatch_envelope.targets,
            )
        except Exception as _env_err:
            logger.debug("CommandRouter.dispatch: TaskEnvelope construction skipped — %s", _env_err)

        # ── PR-506: Compat path — emit degraded audit marker ─────────────────
        # The legacy dispatch() method does not go through route_envelope, so
        # graph/replay/audit writes are not automatic.  Emit a TASK_DEGRADED
        # audit event so that compat callers remain audit-visible rather than
        # becoming observability black holes.
        try:
            from core.audit_event_semantics import audit_task_accepted as _audit_compat_accepted

            _compat_meta = request.metadata or {}
            _compat_targets = list(request.targets)
            _compat_task_id = request.request_id
            _compat_trace_id = _compat_meta.get("trace_id", "") or ""
            _audit_compat_accepted(
                _compat_task_id,
                trace_id=_compat_trace_id,
                source="command_router.dispatch[compat_degraded]",
                origin=request.source if hasattr(request, "source") else "compat",
                goal=request.command if hasattr(request, "command") else "",
            )
        except Exception as _guardrail_exc:
            logger.debug("route_command: legacy guardrail emission skipped - %s", _guardrail_exc)

        self._stats["total_dispatched"] += 1
        start = time.time()

        # ── PR-G5: admission control ──────────────────────────────────────
        active = self._count_active_requests()
        if self._resilience_metrics is not None:
            try:
                self._resilience_metrics.set_queue_depth(active)
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

        if active >= self._max_queue_depth:
            self._stats["total_rejected"] += 1
            if self._resilience_metrics is not None:
                try:
                    self._resilience_metrics.record_rejected()
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)
            logger.warning(
                "CommandRouter.dispatch: queue depth %d >= limit %d; rejecting %s",
                active,
                self._max_queue_depth,
                request.request_id,
            )
            rejected_result = self._make_throttled_result(request)
            self._results[request.request_id] = rejected_result
            return rejected_result

        if self._resilience_metrics is not None:
            try:
                self._resilience_metrics.record_accepted()
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

        # 初始化结果
        cmd_result = CommandResult(
            request_id=request.request_id,
            status=CommandStatus.DISPATCHING,
            metadata=request.metadata,
        )
        for target in request.targets:
            cmd_result.targets[target] = TargetResult(target=target)

        self._results[request.request_id] = cmd_result
        await self._notify(cmd_result)

        # 尝试缓存命中
        if self._cache and request.mode == CommandMode.SYNC and len(request.targets) == 1:
            cache_key = f"cmd:{request.targets[0]}:{request.command}:{json.dumps(request.params, sort_keys=True)}"
            cached = await self._cache_get(cache_key)
            if cached is not None:
                self._stats["cache_hits"] += 1
                target = request.targets[0]
                cmd_result.targets[target].status = CommandStatus.SUCCESS
                cmd_result.targets[target].result = cached
                cmd_result.targets[target].latency_ms = (time.time() - start) * 1000
                cmd_result.status = CommandStatus.SUCCESS
                cmd_result.completed_at = time.time()
                cmd_result.total_latency_ms = (time.time() - start) * 1000
                await self._notify(cmd_result)
                return cmd_result

        # 按模式调度
        if request.mode == CommandMode.ASYNC:
            # 异步：启动后台任务，立即返回
            task = asyncio.create_task(self._execute_all(request, cmd_result, start))
            self._pending_futures[request.request_id] = task
            return cmd_result

        elif request.mode == CommandMode.PARALLEL:
            await self._execute_parallel(request, cmd_result)

        elif request.mode == CommandMode.SERIAL:
            await self._execute_serial(request, cmd_result)

        else:  # SYNC
            await self._execute_parallel(request, cmd_result)

        # 聚合最终状态
        self._finalize_result(cmd_result, start)
        await self._notify(cmd_result)

        # 缓存成功的单目标 SYNC 结果
        if self._cache and cmd_result.status == CommandStatus.SUCCESS and len(request.targets) == 1:
            cache_key = f"cmd:{request.targets[0]}:{request.command}:{json.dumps(request.params, sort_keys=True)}"
            target = request.targets[0]
            await self._cache_set(cache_key, cmd_result.targets[target].result, ttl=60)

        return cmd_result

    async def get_result(self, request_id: str) -> Optional[CommandResult]:
        """查询命令结果"""
        return self._results.get(request_id)

    async def cancel(self, request_id: str) -> bool:
        """取消命令"""
        result = self._results.get(request_id)
        if not result:
            return False
        if result.status in (CommandStatus.SUCCESS, CommandStatus.FAILED):
            return False

        # 取消后台任务
        task = self._pending_futures.pop(request_id, None)
        if task and not task.done():
            task.cancel()

        result.status = CommandStatus.CANCELLED
        result.completed_at = time.time()
        await self._notify(result)
        return True

    def get_stats(self) -> dict:
        """获取统计信息（PR-G5: includes resilience counters）"""
        base = {
            **self._stats,
            "active_commands": self._count_active_requests(),
            "total_tracked": len(self._results),
            "max_queue_depth": self._max_queue_depth,
            "cb_enabled": self._cb_enabled,
            "adaptive_concurrency_enabled": self._adaptive_concurrency_enabled,
        }
        # Attach per-target CB summary
        cb_summary = {tgt: cb.state.value for tgt, cb in self._circuit_breakers.items()}
        if cb_summary:
            base["circuit_breaker_states"] = cb_summary
        return base

    def set_executor(self, executor: Callable[..., Coroutine]):
        """设置/更新执行器"""
        self._executor = executor

    # ------------------------------------------------------------------
    # PR-3: Execution Spine Integration — legacy ingress normalization
    # ------------------------------------------------------------------

    def normalize_legacy_ingress(
        self,
        payload: Any,
        *,
        source: str = "unknown",
    ) -> Any:
        """Normalize a non-envelope payload to a ``TaskEnvelope`` and record it.

        This method is the CommandRouter-side counterpart of
        :func:`core.execution_spine.normalize_ingress_to_envelope`.  It is
        intended for callers that have a reference to the router and want to
        normalize + record a legacy ingress in a single call before passing
        the result to :meth:`route_envelope`.

        Parameters
        ----------
        payload:
            Arbitrary execution frame (dict or ``TaskEnvelope``).
        source:
            Human-readable label for the call origin (e.g. ``"scheduler"``,
            ``"bridge"``, ``"galaxy_orchestrator"``).

        Returns
        -------
        TaskEnvelope
            Normalized envelope, ready for :meth:`route_envelope`.
        """
        try:
            from core.execution_spine import (
                ExecutionIngressSource,
                normalize_ingress_to_envelope,
                record_legacy_ingress,
            )

            try:
                src = ExecutionIngressSource(source)
            except ValueError:
                src = ExecutionIngressSource.UNKNOWN

            # Record as legacy ingress for observability
            try:
                from core.schemas.task_envelope import TaskEnvelope as _TE

                is_canonical = isinstance(payload, _TE)
            except Exception as exc:
                logger.debug("Fallback triggered: %s", exc)
                is_canonical = False

            if not is_canonical:
                record_legacy_ingress(
                    src,
                    payload,
                    reason=f"CommandRouter.normalize_legacy_ingress called from {source}",
                )
            return normalize_ingress_to_envelope(payload, source=src)
        except Exception as exc:
            logger.debug(
                "normalize_legacy_ingress: execution_spine unavailable (%s); " "returning payload unchanged",
                exc,
            )
            return payload

    # ------------------------------------------------------------------
    # 统一网关命令路径（PR-1: route_envelope 为主入口）
    # ------------------------------------------------------------------

    async def route_envelope(self, envelope: "TaskEnvelope") -> Dict[str, Any]:
        """Primary entry-point for all internal routing (PR-1).

        All new code and entry points MUST construct a
        :class:`~core.schemas.task_envelope.TaskEnvelope` and call this
        method.  Legacy callers can continue to use :meth:`route_command`
        which now serves as a compatibility shim that wraps the legacy
        parameters into a TaskEnvelope and delegates here.

        Optional routing hints stored in ``envelope.metadata``:

        * ``command_id``            — explicit command identifier (defaults to task_id)
        * ``request_id``            — caller-assigned request id (defaults to task_id)
        * ``retry_candidates``      — list of alternative device IDs for retry
        * ``required_capabilities`` — capability filter for candidate selection
        * ``max_retries``           — override default retry limit (int)
        * ``caller_level``          — ACL privilege level of the caller (int, default 0)
        * ``agent_capabilities``    — capabilities of the executing agent (list)

        PR-5: ACL check + lifecycle state transitions applied here.
        """
        # ── PR-H: Instantiate live routing explanation collector ──────────────
        # One builder per route_envelope call.  Signals are recorded at each
        # decision point below and assembled into a RouteExplanation at the end.
        try:
            from core.routing_explanation.live_decision import (
                LiveRoutingDecisionBuilder as _LRDBuilder,
                live_explanation_to_record_str as _expl_to_str,
                ROUTE_PATH_CROSS_DEVICE as _P_CROSS,
                ROUTE_PATH_WORKER as _P_WORKER,
                ROUTE_PATH_LOCAL as _P_LOCAL,
                ROUTE_PATH_PARALLEL_FANOUT as _P_FANOUT,
            )

            _live_expl_builder: Optional[object] = _LRDBuilder(
                task_id=envelope.task_id,
                trace_id=envelope.trace_id or "",
            )
        except Exception as _lrdb_exc:
            logger.debug("route_envelope: LiveRoutingDecisionBuilder unavailable: %s", _lrdb_exc)
            _live_expl_builder = None

        # ── Canonical chain: stamp COMMAND_ROUTER_ORCHESTRATION stage ────────
        # Emit a MainlineChainStage.COMMAND_ROUTER_ORCHESTRATION event so
        # observability and tests can verify the canonical chain is traversed.
        try:
            from core.mainline_convergence import (
                build_mainline_trace,
                get_mainline_convergence_registry,
                MainlineChainStage,
            )

            _trace = build_mainline_trace(
                trace_id=envelope.trace_id or "",
                task_id=envelope.task_id,
                session_id=(envelope.metadata or {}).get("session_id", ""),
                device_id=envelope.target or "",
                entry_stage=MainlineChainStage.COMMAND_ROUTER_ORCHESTRATION,
                authority_role=COMMAND_ROUTER_ORCHESTRATION_AUTHORITY,
                source="command_router.route_envelope",
            )
            get_mainline_convergence_registry().record(_trace)
        except Exception as _mc_exc:
            logger.debug(
                "route_envelope: mainline_convergence stamp skipped (non-fatal): %s",
                _mc_exc,
            )

        # PR-2: surface additive NL-problem trace alignment at dispatch ingress.
        _meta_for_trace = envelope.metadata or {}
        _problem_trace = _meta_for_trace.get("problem_execution_trace")
        if isinstance(_problem_trace, dict):
            logger.debug(
                "route_envelope: problem spine trace alignment task_id=%s trace_id=%s runtime_session_id=%s",
                envelope.task_id,
                envelope.trace_id or "",
                _problem_trace.get("runtime_session_id", ""),
            )

        # ── PR-5 Cap 5: ACL check before anything else ──────────────────────
        try:
            from core.acl_enforcer import get_acl_enforcer

            _meta = envelope.metadata or {}
            acl_result = get_acl_enforcer().check(
                envelope=envelope,
                caller_level=int(_meta.get("caller_level", 0)),
                agent_capabilities=_meta.get("agent_capabilities"),
            )
            if not acl_result.allowed:
                return {
                    "request_id": envelope.task_id,
                    "task_id": envelope.task_id,
                    "trace_id": envelope.trace_id,
                    "command_id": envelope.task_id,
                    "device_id": "",
                    "command": envelope.tool_name,
                    "via": "command_router",
                    "success": False,
                    "result": None,
                    "error_code": "ACL_DENIED",
                    "error_message": acl_result.reason,
                    "latency_ms": 0.0,
                }
        except Exception as _acl_exc:
            logger.debug("ACL check skipped (fail-open): %s", _acl_exc)

        # ── HITL pre-check in route_envelope ──────────────────────────────────
        # Detect high-risk tool names before dispatch; stamp _hitl_required in
        # the result so callers know they must provide _hitl_approved in payload.
        _tool_name_for_hitl = (envelope.tool_name or "").lower()
        if self._is_high_risk_command(_tool_name_for_hitl):
            _env_meta = envelope.metadata or {}
            if not _env_meta.get("_hitl_approved"):
                logger.debug(
                    "route_envelope: high-risk tool_name=%r detected; "
                    "_hitl_required will be stamped if not pre-approved",
                    envelope.tool_name,
                )
                # stamp _hitl_required into metadata so downstream can detect it
                envelope = envelope.model_copy(
                    update={
                        "metadata": {
                            **_env_meta,
                            "_hitl_required": True,
                        }
                    }
                )
        try:
            from core.task_memory import get_task_memory

            _mem = get_task_memory()
            _recent = _mem.get_recent_summaries(n=3)
            if _recent:
                logger.debug(
                    "task.memory_inject | task_id=%s injecting %d recent summaries",
                    envelope.task_id,
                    len(_recent),
                )
                # Store injected context in metadata for planner/executor access
                envelope = envelope.model_copy(
                    update={
                        "metadata": {
                            **envelope.metadata,
                            "_injected_memory_summaries": [s.result_summary for s in _recent],
                        }
                    }
                )
        except Exception as _guardrail_exc:
            logger.debug("route_command: legacy guardrail emission skipped — %s", _guardrail_exc)

        if not envelope.targets:
            # PR-518/GAP-517-001: Cross-device envelopes are allowed to have
            # empty targets — device selection is performed by the DeviceRouter
            # substrate inside _route_cross_device_envelope().
            _early_meta = envelope.metadata or {}
            if _early_meta.get("cross_device") == "true":
                pass  # targets resolved by substrate; skip pool/error check
            else:
                # PR-3: When required_capabilities are present but no explicit target is
                # given, delegate to DevicePoolManager to select a suitable device.
                # Explicit targets (even empty-string) must NOT be overridden here —
                # only truly target-less envelopes trigger automatic selection.
                _caps_for_pool: Optional[List[str]] = None
                _meta_caps_early = _early_meta.get("required_capabilities")
                if envelope.required_capabilities:
                    _caps_for_pool = list(envelope.required_capabilities)
                elif isinstance(_meta_caps_early, list) and _meta_caps_early:
                    _caps_for_pool = [str(c) for c in _meta_caps_early]

                _pool_selected: Optional[str] = None
                if _caps_for_pool is not None:
                    # PR-CC: Try capability_graph_selection first (scoring-aware).
                    _cap_graph_selected: Optional[str] = None
                    _cap_graph_fallbacks: List[str] = []
                    try:
                        from core.capability_graph_selection import (
                            select_best_provider as _cgraph_best,
                            select_fallback_providers as _cgraph_fallback,
                        )

                        _cgraph_record = _cgraph_best(required_capabilities=_caps_for_pool)
                        if _cgraph_record is not None:
                            _cap_graph_selected = getattr(_cgraph_record, "node_id", None)
                            if _cap_graph_selected:
                                logger.debug(
                                    "PR-CC: capability_graph_selection selected %s for caps=%s",
                                    _cap_graph_selected,
                                    _caps_for_pool,
                                )
                        _cgraph_fb_records = _cgraph_fallback(
                            required_capabilities=_caps_for_pool,
                            exclude_ids=[_cap_graph_selected] if _cap_graph_selected else [],
                        )
                        _cap_graph_fallbacks = [
                            getattr(r, "node_id", None)
                            for r in _cgraph_fb_records
                            if getattr(r, "node_id", None)
                        ]
                    except Exception as _cgraph_exc:
                        logger.debug(
                            "PR-CC: capability_graph_selection unavailable (fail-open): %s",
                            _cgraph_exc,
                        )

                    if _cap_graph_selected:
                        _pool_selected = _cap_graph_selected
                        # Store fallback candidates in envelope metadata for retry logic.
                        if _cap_graph_fallbacks:
                            _early_meta = dict(_early_meta)
                            _early_meta["_capability_graph_fallbacks"] = _cap_graph_fallbacks
                    else:
                        # Fallback: DevicePoolManager
                        try:
                            from core.device_pool_manager import get_device_pool_manager

                            _pool_selected = get_device_pool_manager().select_device(
                                required_capabilities=_caps_for_pool,
                            )
                            if _pool_selected:
                                logger.debug(
                                    "PR-3: DevicePoolManager selected %s for caps=%s",
                                    _pool_selected,
                                    _caps_for_pool,
                                )
                        except Exception as _pool_exc:
                            logger.warning(
                                "PR-3: DevicePoolManager.select_device failed (fail-open): %s",
                                _pool_exc,
                            )

                if _pool_selected:
                    _update: Dict[str, Any] = {"targets": [_pool_selected]}
                    if _cap_graph_fallbacks:
                        # Use _early_meta as base to preserve any updates made
                        # during capability graph selection (e.g. existing fallbacks
                        # already stamped into _early_meta at line above).
                        _merged_meta = dict(_early_meta)
                        _merged_meta["_capability_graph_fallbacks"] = _cap_graph_fallbacks
                        _update["metadata"] = _merged_meta
                    envelope = envelope.model_copy(update=_update)
                else:
                    return {
                        "request_id": envelope.task_id,
                        "task_id": envelope.task_id,
                        "trace_id": envelope.trace_id,
                        "command_id": envelope.task_id,
                        "device_id": "",
                        "command": envelope.tool_name,
                        "via": "command_router",
                        "success": False,
                        "result": None,
                        "error_code": GatewayErrorCode.INVALID_ENVELOPE.value,
                        "error_message": "TaskEnvelope.targets 为空，无法路由",
                        "latency_ms": 0.0,
                    }

        # ── ENFORCE: Unified pre-dispatch constraint chain ────────────────────
        # Applies admissibility, session-truth/posture, and topology checks
        # uniformly across ALL dispatch paths before execution branching.
        # See DISPATCH_CONSTRAINT_CHAIN_UNIFORM_ENFORCEMENT sentinel.
        #
        # Gate A — session-truth / posture-aware filter.
        # Gate B — admissibility chain for device targets.
        #
        # Both gates degrade gracefully when backing modules are unavailable.
        # The trace dict is propagated to the result under
        # "_constraint_chain_trace" for end-to-end reviewability.
        _constraint_chain_trace: Dict[str, Any] = {
            "admissibility_applied": False,
            "admissibility_validated": [],
            "admissibility_excluded": [],
            "posture_filter_applied": False,
            "posture_eligible": None,
            "posture_value": None,
        }

        # ── Gate A: Posture-aware session-truth filter ────────────────────────
        # Consult canonical session-truth posture (source_runtime_posture) to
        # record whether the source device is eligible for local execution.
        # control_only sources that land on a non-cross-device path are flagged
        # in the trace; join_runtime sources pass without restriction.
        # See SESSION_TRUTH_POSTURE_DISPATCH_FILTER_APPLIED sentinel.
        _meta_posture_hint = (envelope.metadata or {}).get("source_runtime_posture")
        if _meta_posture_hint is not None:
            try:
                from core.source_execution_eligibility import (
                    check_source_execution_eligibility as _check_src_posture,
                )

                _posture_elig = _check_src_posture(_meta_posture_hint)
                _constraint_chain_trace["posture_filter_applied"] = True
                _constraint_chain_trace["posture_eligible"] = _posture_elig.eligible
                _constraint_chain_trace["posture_value"] = _posture_elig.posture
                logger.debug(
                    "route_envelope [constraint-chain/posture-gate]: "
                    "source_runtime_posture=%r eligible=%s task_id=%s",
                    _posture_elig.posture,
                    _posture_elig.eligible,
                    envelope.task_id,
                )
                # Flag control_only sources on non-cross-device paths — they
                # should not be executing locally.  Warn; do not block (backward
                # compat preserved; hard enforcement can be added incrementally).
                if not _posture_elig.eligible:
                    _meta_pf = envelope.metadata or {}
                    _is_cross_device_hint = (
                        _meta_pf.get("cross_device") == "true"
                        or (
                            envelope.executor_target_type is not None
                            and str(envelope.executor_target_type)
                            in ("android_device", "node_service")
                        )
                    )
                    if not _is_cross_device_hint:
                        logger.debug(
                            "route_envelope [constraint-chain/posture-gate]: "
                            "control_only source on non-cross-device path; "
                            "flagged in constraint trace — task_id=%s",
                            envelope.task_id,
                        )
            except Exception as _posture_gate_exc:
                logger.debug(
                    "route_envelope: posture-gate skipped (graceful degradation): %s",
                    _posture_gate_exc,
                )

            # ── PR-H: Record posture gate result into live explanation ────────
            if _live_expl_builder is not None and _constraint_chain_trace.get("posture_filter_applied"):
                try:
                    _live_expl_builder.record_posture_gate(
                        posture=str(_constraint_chain_trace.get("posture_value") or ""),
                        eligible=bool(_constraint_chain_trace.get("posture_eligible", True)),
                    )
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)

        # ── Gate B: Admissibility chain for device targets ───────────────────
        # Validates envelope targets via the canonical admissibility chain
        # (readiness → participation → capability) before any path branching,
        # ensuring all dispatch paths are subject to the same constraint — not
        # only _route_cross_device_envelope (which has its own per-path check
        # for defence-in-depth).
        # Excluded targets are filtered with a structured warning; when all
        # targets fail, dispatch proceeds with originals (graceful degradation).
        _pre_adm_targets = list(envelope.targets)
        if _pre_adm_targets:
            try:
                from core.target_device_validator import (
                    validate_target_device as _vtd_pre,
                )

                _req_caps_adm: Optional[List[str]] = (
                    list(envelope.required_capabilities)
                    if envelope.required_capabilities
                    else None
                )
                _adm_validated: List[str] = []
                _adm_excluded: List[str] = []
                for _adm_t in _pre_adm_targets:
                    try:
                        _adm_vr = _vtd_pre(
                            _adm_t, required_capabilities=_req_caps_adm
                        )
                        _readiness_was_consulted = not any(
                            r.startswith("readiness-unavailable")
                            for r in (_adm_vr.reasons or [])
                        )
                        if _readiness_was_consulted and not _adm_vr.ready:
                            _adm_excluded.append(_adm_t)
                            logger.debug(
                                "route_envelope [constraint-chain/admissibility-gate]: "
                                "target %r excluded — registered=%s ready=%s "
                                "reasons=%s task_id=%s",
                                _adm_t,
                                _adm_vr.registered,
                                _adm_vr.ready,
                                _adm_vr.reasons,
                                envelope.task_id,
                            )
                        else:
                            _adm_validated.append(_adm_t)
                    except Exception as exc:
                        # Include by default on per-target error (graceful).
                        _adm_validated.append(_adm_t)

                _constraint_chain_trace["admissibility_applied"] = True
                _constraint_chain_trace["admissibility_validated"] = list(
                    _adm_validated
                )
                _constraint_chain_trace["admissibility_excluded"] = list(
                    _adm_excluded
                )

                if _adm_validated and len(_adm_validated) < len(_pre_adm_targets):
                    logger.warning(
                        "route_envelope [constraint-chain/admissibility-gate]: "
                        "filtered %d → %d target(s); excluded: %s task_id=%s",
                        len(_pre_adm_targets),
                        len(_adm_validated),
                        _adm_excluded,
                        envelope.task_id,
                    )
                    envelope = envelope.model_copy(
                        update={"targets": _adm_validated}
                    )
                elif not _adm_validated and _adm_excluded:
                    # All targets failed — warn but proceed (graceful degradation).
                    logger.warning(
                        "route_envelope [constraint-chain/admissibility-gate]: "
                        "all %d target(s) failed admissibility check; "
                        "proceeding with originals (graceful degradation) "
                        "task_id=%s",
                        len(_pre_adm_targets),
                        envelope.task_id,
                    )
            except Exception as _adm_pre_exc:
                logger.debug(
                    "route_envelope: pre-dispatch admissibility gate skipped: %s",
                    _adm_pre_exc,
                )

            # ── PR-H: Record admissibility gate into live explanation ─────────
            if _live_expl_builder is not None and _constraint_chain_trace.get("admissibility_applied"):
                try:
                    _adm_excl_pairs = [
                        (dev_id, ["failed admissibility check"])
                        for dev_id in (_constraint_chain_trace.get("admissibility_excluded") or [])
                    ]
                    _live_expl_builder.record_admissibility_gate(
                        validated=list(_constraint_chain_trace.get("admissibility_validated") or []),
                        excluded=_adm_excl_pairs,
                    )
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)

        # ── PR-5 Cap 1: lifecycle transition created → running ───────────────
        try:
            from core.task_lifecycle import get_lifecycle_manager

            _lcm = get_lifecycle_manager()
            envelope = _lcm.mark_running(envelope)
        except Exception as _lc_exc:
            logger.debug("Lifecycle mark_running skipped: %s", _lc_exc)

        # ── PR-WEBRTC-TASK-LIFECYCLE: WebRTC signaling handshake ──────────────
        # When the envelope declares that it requires a WebRTC video stream,
        # initiate (or wait for) the signaling handshake before proceeding to
        # capability enforcement and dispatch.  This closes the gap between
        # "task needs video" and "video is ready".
        #
        # Flow:
        #   1. If requires_webrtc is False (default) → skip entirely.
        #   2. Determine the target device (explicit webrtc_target_device or
        #      first envelope target).
        #   3. Check if WebRTC is already ready for that device; if yes, skip.
        #   4. Otherwise call initiate_webrtc_for_task() and await readiness.
        #   5. On failure → return a structured error (task blocked).
        #   6. On success → stamp webrtc_ready metadata and continue.
        _webrtc_task_trigger_applied = False
        _webrtc_task_trigger_result: Optional[Dict[str, Any]] = None
        if envelope.requires_webrtc:
            _wrtc_t0 = time.monotonic()
            _webrtc_task_trigger_applied = True

            # Resolve target device
            _wrtc_device: Optional[str] = envelope.webrtc_target_device
            if not _wrtc_device and envelope.targets:
                _wrtc_device = envelope.targets[0]

            if not _wrtc_device:
                _wrtc_elapsed = (time.monotonic() - _wrtc_t0) * 1000
                logger.warning(
                    "route_envelope [PR-WEBRTC-TASK-LIFECYCLE]: "
                    "requires_webrtc=True but no device resolved task_id=%s",
                    envelope.task_id,
                )
                return {
                    "request_id": envelope.task_id,
                    "task_id": envelope.task_id,
                    "trace_id": envelope.trace_id,
                    "command_id": (envelope.metadata or {}).get("command_id", envelope.task_id),
                    "device_id": "",
                    "command": envelope.tool_name,
                    "via": "command_router",
                    "success": False,
                    "result": None,
                    "error_code": GatewayErrorCode.INVALID_ENVELOPE.value,
                    "error_message": (
                        "requires_webrtc=True but neither webrtc_target_device "
                        "nor targets are set; cannot determine which device "
                        "should provide the video stream"
                    ),
                    "latency_ms": round(_wrtc_elapsed, 1),
                }

            try:
                from galaxy_gateway.webrtc_proxy import (
                    is_webrtc_ready_for_device,
                    initiate_webrtc_for_task,
                )

                # Fast path: already ready
                if is_webrtc_ready_for_device(_wrtc_device):
                    logger.debug(
                        "route_envelope [PR-WEBRTC-TASK-LIFECYCLE]: "
                        "WebRTC already ready for device=%s task_id=%s",
                        _wrtc_device,
                        envelope.task_id,
                    )
                    _webrtc_task_trigger_result = {
                        "applied": True,
                        "device_id": _wrtc_device,
                        "ready": True,
                        "waited": False,
                        "latency_ms": 0.0,
                    }
                else:
                    logger.info(
                        "route_envelope [PR-WEBRTC-TASK-LIFECYCLE]: "
                        "initiating WebRTC for device=%s task_id=%s trace_id=%s",
                        _wrtc_device,
                        envelope.task_id,
                        envelope.trace_id,
                    )
                    _wrtc_ready_result = await initiate_webrtc_for_task(
                        device_id=_wrtc_device,
                        trace_id=envelope.trace_id or "",
                    )
                    _wrtc_elapsed = (time.monotonic() - _wrtc_t0) * 1000
                    if not _wrtc_ready_result.success:
                        logger.warning(
                            "route_envelope [PR-WEBRTC-TASK-LIFECYCLE]: "
                            "WebRTC initiation failed device=%s task_id=%s reason=%s",
                            _wrtc_device,
                            envelope.task_id,
                            _wrtc_ready_result.message,
                        )
                        return {
                            "request_id": envelope.task_id,
                            "task_id": envelope.task_id,
                            "trace_id": envelope.trace_id,
                            "command_id": (envelope.metadata or {}).get(
                                "command_id", envelope.task_id
                            ),
                            "device_id": _wrtc_device,
                            "command": envelope.tool_name,
                            "via": "command_router",
                            "success": False,
                            "result": None,
                            "error_code": "WEBRTC_TASK_INIT_FAILED",
                            "error_message": _wrtc_ready_result.message,
                            "webrtc_task_trigger": {
                                "applied": True,
                                "device_id": _wrtc_device,
                                "ready": False,
                                "waited": True,
                                "latency_ms": _wrtc_ready_result.latency_ms,
                            },
                            "latency_ms": round(_wrtc_elapsed, 1),
                        }
                    # Success — stamp metadata and continue
                    _webrtc_task_trigger_result = {
                        "applied": True,
                        "device_id": _wrtc_device,
                        "ready": True,
                        "waited": True,
                        "latency_ms": _wrtc_ready_result.latency_ms,
                    }
                    logger.info(
                        "route_envelope [PR-WEBRTC-TASK-LIFECYCLE]: "
                        "WebRTC ready for device=%s task_id=%s latency_ms=%.1f",
                        _wrtc_device,
                        envelope.task_id,
                        _wrtc_ready_result.latency_ms,
                    )

            except Exception as _wrtc_exc:
                logger.debug("Fallback triggered: %s", _wrtc_exc)
                _wrtc_elapsed = (time.monotonic() - _wrtc_t0) * 1000
                logger.warning(
                    "route_envelope [PR-WEBRTC-TASK-LIFECYCLE]: "
                    "WebRTC integration error task_id=%s error=%s",
                    envelope.task_id,
                    _wrtc_exc,
                )
                # Fail-open: log the error but do NOT block dispatch.
                # This preserves backward compatibility when the webrtc_proxy
                # module is unavailable or the ingress bridge is not configured.
                _webrtc_task_trigger_result = {
                    "applied": True,
                    "device_id": _wrtc_device,
                    "ready": False,
                    "waited": False,
                    "error": str(_wrtc_exc),
                    "latency_ms": round(_wrtc_elapsed, 1),
                }

            # Stamp webrtc_task_trigger result into envelope metadata so
            # downstream components can see what happened.
            if _webrtc_task_trigger_result is not None:
                envelope = envelope.model_copy(
                    update={
                        "metadata": {
                            **(envelope.metadata or {}),
                            "_webrtc_task_trigger": _webrtc_task_trigger_result,
                        }
                    }
                )

        # ── PR-3 / GAP-512-004 closure: Capability graph enforcement ─────────
        # query_routable_executors() is now called with required_capabilities so
        # routing decisions reflect the canonical capability graph rather than
        # issuing an unfiltered advisory query.
        # Enforcement logic:
        #   1. If required_capabilities is set and the canonical layer returns
        #      confirmed executors, validate the envelope targets against them.
        #   2. Targets confirmed in the capability graph proceed unchanged.
        #   3. Targets NOT confirmed in the graph emit a structured warning so
        #      that capability coverage gaps become observable.
        #   4. Fully falls back gracefully when the capability layer is unavailable.
        # Closes GAP-512-004 (capability graph convergence no longer advisory-only).
        _cap_query_caps: Optional[List[str]] = None
        _meta_for_cap_query = envelope.metadata or {}
        if envelope.required_capabilities:
            _cap_query_caps = list(envelope.required_capabilities)
        elif isinstance(_meta_for_cap_query.get("required_capabilities"), list):
            _cap_query_caps = [str(c) for c in _meta_for_cap_query["required_capabilities"]]

        # PR-CAP-DEFAULT: capability-aware routing is the default main path.
        # When no required_capabilities are declared but explicit target(s) are
        # present, infer capabilities from the tool_name so the capability gate
        # activates automatically.  This closes the bypass gap where an explicit
        # device_id without required_capabilities skipped all capability checking.
        # See CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE in
        # core.mainline_routing_enforcement and
        # core.capability_aware_routing_default for the policy definition.
        if _cap_query_caps is None and list(envelope.targets):
            try:
                from core.capability_aware_routing_default import (
                    infer_dispatch_capabilities as _infer_caps,
                )

                _inferred_caps = _infer_caps(envelope.tool_name or "")
                if _inferred_caps:
                    _cap_query_caps = _inferred_caps
                    logger.debug(
                        "route_envelope [CAP-DEFAULT]: inferred required_capabilities=%s "
                        "from tool_name=%r for explicit target(s) %s — "
                        "capability-aware routing is the default main path",
                        _cap_query_caps,
                        envelope.tool_name,
                        list(envelope.targets),
                    )
            except Exception as _infer_err:
                logger.debug(
                    "route_envelope [CAP-DEFAULT]: capability inference skipped "
                    "for tool_name=%r: %s",
                    envelope.tool_name,
                    _infer_err,
                )

        # PR-H: pre-initialize capability tracking variables so they are always
        # in scope for the live explanation wiring block below, regardless of
        # whether the capability enforcement try block was entered or completed.
        _cap_confirmed_targets: Optional[List[str]] = None
        _cap_unconfirmed_targets: Optional[List[str]] = None
        try:
            from core.capability_network_runtime_policy import (
                query_routable_executors as _query_exec,
                query_network_path as _query_path,
            )

            _routable = _query_exec(_cap_query_caps)
            logger.debug(
                "route_envelope: capability/network query returned %d routable executor(s) "
                "(required_caps=%s)",
                len(_routable),
                _cap_query_caps,
            )

            # ── Enforcement: validate/filter targets against capability graph ─
            if _cap_query_caps and _routable:
                _canonical_ids = {e.node_id for e in _routable}
                _current_targets = list(envelope.targets)
                _confirmed_targets = [t for t in _current_targets if t in _canonical_ids]
                _unconfirmed_targets = [t for t in _current_targets if t not in _canonical_ids]
                # PR-H: expose to outer scope for live explanation wiring
                _cap_confirmed_targets = _confirmed_targets
                _cap_unconfirmed_targets = _unconfirmed_targets

                if _confirmed_targets:
                    if _unconfirmed_targets:
                        # Some targets are not in the capability graph — filter to confirmed.
                        logger.warning(
                            "route_envelope [GAP-512-004]: target(s) %s not confirmed in "
                            "capability graph for caps=%s; routing to confirmed target(s)=%s only",
                            _unconfirmed_targets,
                            _cap_query_caps,
                            _confirmed_targets,
                        )
                        envelope = envelope.model_copy(
                            update={"targets": _confirmed_targets}
                        )
                    else:
                        logger.debug(
                            "route_envelope: all %d target(s) confirmed in capability "
                            "graph for caps=%s",
                            len(_confirmed_targets),
                            _cap_query_caps,
                        )
                elif _current_targets:
                    # PR-1 P0 Capability-Aware Scheduling Closure:
                    # Targets specified but NONE are confirmed in the capability
                    # graph.  This is a capability mismatch — the explicit
                    # device_id(s) cannot serve the requested capabilities.
                    # Controlled decision semantics:
                    #   1. Fallback: use the routable alternatives from the
                    #      capability graph (_routable already populated).
                    #   2. Reject: if no routable alternatives, return a
                    #      structured CAPABILITY_MISMATCH error.
                    # Neither path silently bypasses capability verification.
                    _fallback_targets = [e.node_id for e in _routable if hasattr(e, "node_id")]
                    if _fallback_targets:
                        logger.warning(
                            "route_envelope [PR-1-P0 capability-mismatch/fallback]: "
                            "target(s) %s not confirmed in capability graph for "
                            "caps=%s; falling back to capable alternative(s) %s",
                            _current_targets,
                            _cap_query_caps,
                            _fallback_targets,
                        )
                        _cap_confirmed_targets = _fallback_targets
                        _cap_unconfirmed_targets = _current_targets
                        envelope = envelope.model_copy(update={"targets": _fallback_targets})
                        envelope = envelope.model_copy(
                            update={
                                "metadata": {
                                    **(envelope.metadata or {}),
                                    "capability_mismatch_override": True,
                                    "original_targets": _current_targets,
                                    "fallback_reason": "capability_mismatch",
                                }
                            }
                        )
                    else:
                        logger.warning(
                            "route_envelope [PR-1-P0 capability-mismatch/reject]: "
                            "target(s) %s not confirmed in capability graph for "
                            "caps=%s and no capable alternatives found; "
                            "rejecting dispatch",
                            _current_targets,
                            _cap_query_caps,
                        )
                        _cap_unconfirmed_targets = _current_targets
                        _t0_val = locals().get("_t0_val") or 0.0
                        return {
                            "request_id": envelope.task_id,
                            "task_id": envelope.task_id,
                            "trace_id": envelope.trace_id,
                            "command_id": (envelope.metadata or {}).get(
                                "command_id", envelope.task_id
                            ),
                            "device_id": _current_targets[0] if _current_targets else "",
                            "command": envelope.tool_name,
                            "via": "command_router",
                            "success": False,
                            "result": None,
                            "error_code": GatewayErrorCode.CAPABILITY_MISMATCH.value,
                            "error_message": (
                                f"Target device(s) {_current_targets} do not satisfy "
                                f"required capabilities {_cap_query_caps} and no "
                                f"capable alternatives are available"
                            ),
                            "latency_ms": 0.0,
                        }
            elif _cap_query_caps and not _routable:
                # PR-1 P0 Capability-Aware Scheduling Closure:
                # The capability graph returned ZERO capable executors for the
                # requested capabilities AND the envelope has explicit targets.
                # When explicit targets are present, this is a capability mismatch
                # with no fallback — reject with a structured error rather than
                # silently proceeding.
                # When there are no explicit targets (selection was left to
                # automatic resolution), log and proceed so the fallback resolution
                # path can still try (graceful degradation for target-less requests).
                _current_targets_for_empty = list(envelope.targets)
                if _current_targets_for_empty:
                    logger.warning(
                        "route_envelope [PR-1-P0 capability-mismatch/reject]: "
                        "capability graph has no executors for caps=%s and "
                        "explicit target(s) %s cannot be verified; "
                        "rejecting dispatch",
                        _cap_query_caps,
                        _current_targets_for_empty,
                    )
                    _cap_unconfirmed_targets = _current_targets_for_empty
                    return {
                        "request_id": envelope.task_id,
                        "task_id": envelope.task_id,
                        "trace_id": envelope.trace_id,
                        "command_id": (envelope.metadata or {}).get(
                            "command_id", envelope.task_id
                        ),
                        "device_id": _current_targets_for_empty[0] if _current_targets_for_empty else "",
                        "command": envelope.tool_name,
                        "via": "command_router",
                        "success": False,
                        "result": None,
                        "error_code": GatewayErrorCode.CAPABILITY_MISMATCH.value,
                        "error_message": (
                            f"No executor found in capability graph for capabilities "
                            f"{_cap_query_caps}; target device(s) "
                            f"{_current_targets_for_empty} cannot be verified"
                        ),
                        "latency_ms": 0.0,
                    }
                else:
                    logger.debug(
                        "route_envelope: capability graph returned no executors for caps=%s; "
                        "proceeding with existing targets (no explicit target, graceful degradation)",
                        _cap_query_caps,
                    )

            # ── Canonical path observability ─────────────────────────────────
            _target_list = list(envelope.targets)
            if _target_list:
                _primary_target = _target_list[0]
                _path_result = _query_path("command_router", _primary_target)
                logger.debug(
                    "route_envelope: canonical path to '%s' — reachable=%s state=%s",
                    _primary_target,
                    _path_result.is_reachable,
                    _path_result.path_state,
                )
        except Exception as _cap_exc:
            logger.debug("route_envelope: capability/network canonical query skipped: %s", _cap_exc)

        # ── PR-H: Record capability enforcement into live explanation ─────────
        if _live_expl_builder is not None:
            try:
                if _cap_confirmed_targets is not None or _cap_unconfirmed_targets is not None:
                    _live_expl_builder.record_capability_enforcement(
                        confirmed=list(_cap_confirmed_targets or []),
                        unconfirmed=list(_cap_unconfirmed_targets or []),
                        required_caps=_cap_query_caps,
                    )
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

        # ── PR-V3: Canonical dispatch slot legality gate ──────────────────────
        # V3 canonical_dispatch_slot_authority is the single canonical pre-dispatch
        # legality authority for all execution modes.  Call get_canonical_dispatch_slots()
        # with the current (already ACL/admissibility/capability-filtered) targets and
        # filter to SLOT_APPROVED targets only.  If no target survives, block dispatch
        # with a structured V3_SLOT_BLOCKED error.
        #
        # This closes the dispatch split-brain: V3 was previously a shadow authority
        # (declared but not on the real hot path).  After this gate it is the live
        # pre-dispatch legality authority for all targets.
        #
        # Placement: after ACL, admissibility, and capability enforcement, before
        # task-graph registration and actual dispatch branching.
        _v3_slot_gate_applied = False
        _v3_approved_targets: List[str] = []
        _v3_blocked_targets: List[str] = []
        _v3_block_reason: str = ""
        _v3_slot_result = None
        _v3_authority_mode = str(
            (envelope.metadata or {}).get("canonical_dispatch_authority_mode")
            or (envelope.metadata or {}).get("canonical_governance_mode")
            or os.environ.get("GALAXY_CANONICAL_DISPATCH_AUTHORITY_MODE", "compat")
        ).strip().lower()
        _v3_pre_targets = list(envelope.targets)
        if _v3_pre_targets:
            try:
                from core.canonical_dispatch_slot_authority import (
                    get_canonical_dispatch_slots as _get_slots,
                )

                _v3_meta = envelope.metadata or {}
                # Resolve execution mode in priority order: explicit metadata field,
                # parallel_fanout hint, cross_device hint, executor_target_type, default.
                if _v3_meta.get("execution_mode"):
                    _v3_exec_mode = str(_v3_meta["execution_mode"])
                elif _v3_meta.get("parallel_fanout") == "true":
                    _v3_exec_mode = "parallel_fanout"
                elif _v3_meta.get("cross_device") == "true":
                    _v3_exec_mode = "cross_device"
                elif envelope.executor_target_type is not None:
                    _v3_exec_mode = str(envelope.executor_target_type)
                else:
                    _v3_exec_mode = "cross_device"
                _v3_required_caps: Optional[List[str]] = (
                    list(envelope.required_capabilities)
                    if envelope.required_capabilities
                    else None
                )
                _v3_session_id = str(_v3_meta.get("session_id", "") or "")
                _v3_attachment_sid = str(
                    _v3_meta.get("runtime_attachment_session_id", "") or ""
                )
                _v3_continuity_ctx: Dict[str, Any] = {
                    k: v
                    for k, v in _v3_meta.items()
                    if k.startswith("continuity_")
                }

                _v3_slot_result = _get_slots(
                    device_ids=_v3_pre_targets,
                    execution_mode=_v3_exec_mode,
                    required_capabilities=_v3_required_caps,
                    session_id=_v3_session_id or None,
                    runtime_attachment_session_id=_v3_attachment_sid or None,
                    task_id=envelope.task_id,
                    continuity_context=_v3_continuity_ctx or None,
                    authority_mode=_v3_authority_mode,
                )
                _v3_slot_gate_applied = True
                _v3_approved_targets = list(_v3_slot_result.approved_device_ids)
                _v3_blocked_targets = list(_v3_slot_result.blocked_device_ids)
                _v3_block_reason = _v3_slot_result.block_reason or ""

                if _v3_approved_targets:
                    if _v3_blocked_targets:
                        # Some targets blocked — filter to approved only.
                        logger.warning(
                            "route_envelope [V3-slot-gate]: %d target(s) blocked by "
                            "canonical slot authority; dispatching to %d approved: %s "
                            "(blocked: %s) task_id=%s",
                            len(_v3_blocked_targets),
                            len(_v3_approved_targets),
                            _v3_approved_targets,
                            _v3_blocked_targets,
                            envelope.task_id,
                        )
                    else:
                        logger.debug(
                            "route_envelope [V3-slot-gate]: all %d target(s) SLOT_APPROVED "
                            "task_id=%s",
                            len(_v3_approved_targets),
                            envelope.task_id,
                        )
                    if set(_v3_approved_targets) != set(_v3_pre_targets):
                        envelope = envelope.model_copy(
                            update={"targets": _v3_approved_targets}
                        )
                else:
                    # All targets blocked — hard reject.
                    _blocked_detail = "; ".join(
                        f"{s.device_id}: {s.reason} (dim={s.blocking_dimension})"
                        for s in (_v3_slot_result.blocked_slots if _v3_slot_result else [])
                    )
                    logger.warning(
                        "route_envelope [V3-slot-gate]: ALL target(s) blocked by "
                        "canonical slot authority — block_reason=%r blocked=%s "
                        "task_id=%s",
                        _v3_block_reason,
                        _v3_blocked_targets,
                        envelope.task_id,
                    )
                    _v3_blocked_result: Dict[str, Any] = {
                        "request_id": envelope.task_id,
                        "task_id": envelope.task_id,
                        "trace_id": envelope.trace_id,
                        "command_id": (envelope.metadata or {}).get(
                            "command_id", envelope.task_id
                        ),
                        "device_id": _v3_pre_targets[0] if _v3_pre_targets else "",
                        "command": envelope.tool_name,
                        "via": "command_router",
                        "success": False,
                        "result": None,
                        "error_code": GatewayErrorCode.V3_SLOT_BLOCKED.value,
                        "error_message": (
                            f"V3 canonical slot authority blocked all dispatch targets. "
                            f"block_reason={_v3_block_reason!r}. "
                            f"Detail: {_blocked_detail}"
                        ),
                        "v3_slot_gate": {
                            "applied": True,
                            "approved": [],
                            "blocked": _v3_blocked_targets,
                            "block_reason": _v3_block_reason,
                        },
                        "latency_ms": 0.0,
                    }
                    if envelope.remote_execution_mode is not None:
                        _v3_blocked_result["remote_execution_mode"] = envelope.remote_execution_mode.value
                    _v3_blocked_result["execution_substrate_role"] = "execution_substrate"
                    _v3_blocked_result["arch_layer_id"] = "execution_substrate"
                    _v3_blocked_result["tool_invocation_truth"] = {
                        "route_envelope_invoked": True,
                        "dispatch_executed": False,
                    }
                    _v3_blocked_result["repo_mutation_truth"] = {
                        "in_scope": False,
                        "mutation_applied": False,
                    }
                    # Stamp lifecycle state (always "failed" since success=False)
                    try:
                        from core.schemas.execution_lifecycle import ExecutionLifecycleState as _ELS_v3
                        _v3_blocked_result["lifecycle_state"] = _ELS_v3.FAILED.value
                        if envelope.remote_execution_mode is not None:
                            _v3_blocked_result["lifecycle_via_waiting_remote"] = True
                    except Exception as exc:
                        logger.warning("Exception suppressed: %s", exc)
                    # Stamp failure domain from V3_SLOT_BLOCKED error code
                    try:
                        from core.failure_domains import classify_from_error_code as _cfe_v3
                        _fd_v3 = _cfe_v3(GatewayErrorCode.V3_SLOT_BLOCKED.value)
                        _v3_blocked_result["failure_domain"] = _fd_v3.domain.value
                        _v3_blocked_result["failure_is_retryable"] = _fd_v3.is_retryable
                    except Exception as exc:
                        logger.warning("Exception suppressed: %s", exc)
                    # Stamp introspection snapshot
                    _v3_blocked_result["introspection_snapshot"] = {
                        "authority_role": "execution_substrate",
                        "execution_path": "local",
                        "execution_substrate_role": "execution_substrate",
                        "execution_mode": _v3_blocked_result.get("remote_execution_mode"),
                        "lifecycle_state": _v3_blocked_result.get("lifecycle_state"),
                        "failure_domain": _v3_blocked_result.get("failure_domain"),
                        "failure_is_retryable": _v3_blocked_result.get("failure_is_retryable"),
                        "success": False,
                        "tool_invocation_truth": _v3_blocked_result.get("tool_invocation_truth"),
                        "repo_mutation_truth": _v3_blocked_result.get("repo_mutation_truth"),
                    }
                    return _v3_blocked_result

            except Exception as _v3_exc:
                logger.debug("Fallback triggered: %s", _v3_exc)
                _v3_block_reason = f"slot_authority_unavailable:{_v3_exc}"
                if _v3_authority_mode == "strict":
                    logger.warning(
                        "route_envelope [V3-slot-gate]: strict mode blocks dispatch on authority error: %s",
                        _v3_exc,
                    )
                    return {
                        "request_id": envelope.task_id,
                        "task_id": envelope.task_id,
                        "trace_id": envelope.trace_id,
                        "command_id": (envelope.metadata or {}).get("command_id", envelope.task_id),
                        "device_id": _v3_pre_targets[0] if _v3_pre_targets else "",
                        "command": envelope.tool_name,
                        "via": "command_router",
                        "success": False,
                        "result": None,
                        "error_code": GatewayErrorCode.V3_SLOT_BLOCKED.value,
                        "error_message": (
                            "V3 canonical slot authority unavailable in strict mode; "
                            f"dispatch blocked. Details: {_v3_exc}"
                        ),
                        "v3_slot_gate": {
                            "applied": False,
                            "mode": _v3_authority_mode,
                            "approved": [],
                            "blocked": list(_v3_pre_targets),
                            "block_reason": _v3_block_reason,
                        },
                        "latency_ms": 0.0,
                    }
                logger.warning(
                    "route_envelope [V3-slot-gate]: compat fallback on authority error mode=%s err=%s",
                    _v3_authority_mode,
                    _v3_exc,
                )

        # ── PR-H: Record V3 slot gate into live explanation ───────────────────
        if _live_expl_builder is not None and _v3_slot_gate_applied:
            try:
                _live_expl_builder.record_v3_slot_gate(  # type: ignore[attr-defined]
                    approved=_v3_approved_targets,
                    blocked=_v3_blocked_targets,
                    block_reason=_v3_block_reason,
                )
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

        # Stamp V3 slot gate result into constraint chain trace for end-to-end
        # reviewability.
        _constraint_chain_trace["v3_slot_gate_applied"] = _v3_slot_gate_applied
        _constraint_chain_trace["v3_slot_gate_mode"] = _v3_authority_mode
        _constraint_chain_trace["v3_approved_targets"] = _v3_approved_targets
        _constraint_chain_trace["v3_blocked_targets"] = _v3_blocked_targets
        _constraint_chain_trace["v3_block_reason"] = _v3_block_reason

        # ── PR-506: Register envelope in TaskGraphRuntime ────────────────────
        try:
            from core.task_graph_runtime import (
                get_task_graph_runtime,
                WorkflowContributorKind,
                GraphNodeState as _GNS,
            )

            _tgr = get_task_graph_runtime()
            _tgr.register_envelope(
                envelope,
                contributor=WorkflowContributorKind.COMMAND_ROUTER,
            )
            # ── PR-508: Lifecycle transitions: queued → admitted → routed ────
            _tgr.transition(envelope.task_id, _GNS.ADMITTED)
            _tgr.transition(envelope.task_id, _GNS.ROUTED)
        except Exception as _tgr_reg_exc:
            logger.debug(
                "route_envelope: TaskGraphRuntime.register_envelope skipped: %s",
                _tgr_reg_exc,
            )

        # ── PR-506: Emit audit accepted + dispatched ─────────────────────────
        try:
            from core.audit_event_semantics import (
                audit_task_accepted,
                audit_task_dispatched,
            )

            _meta_audit = envelope.metadata or {}
            audit_task_accepted(
                envelope.task_id,
                trace_id=envelope.trace_id or "",
                session_id=str(_meta_audit.get("session_id", "")),
                source="command_router.route_envelope",
                origin=envelope.source or "",
                goal=envelope.tool_name or "",
            )
            audit_task_dispatched(
                envelope.task_id,
                trace_id=envelope.trace_id or "",
                source="command_router.route_envelope",
                targets=list(envelope.targets),
                transport="",
            )
        except Exception as _audit_pre_exc:
            logger.debug(
                "route_envelope: AuditEventSemantics pre-dispatch writes skipped: %s",
                _audit_pre_exc,
            )

        # ── PR-506: Record route decision in ReplayFoundation ────────────────
        # PR-H: Build a partial live explanation from signals collected so far
        # (posture gate, admissibility gate, capability enforcement) and use it
        # as the route_explanation instead of the static placeholder string.
        _pre_dispatch_expl_str = "canonical dispatch via CommandRouter.route_envelope"
        if _live_expl_builder is not None:
            try:
                _pre_dispatch_expl = _live_expl_builder.build()
                _pre_dispatch_expl_str = _expl_to_str(_pre_dispatch_expl)
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)
        try:
            from core.replay_foundation import (
                record_route_decision as _record_route,
                emit_runtime_event as _emit_ev,
                ReplayEventKind,
            )

            _record_route(
                task_id=envelope.task_id,
                trace_id=envelope.trace_id or "",
                selected_targets=list(envelope.targets),
                effective_path="command_router",
                route_explanation=_pre_dispatch_expl_str,
            )
            _emit_ev(
                ReplayEventKind.ROUTE_DECISION,
                task_id=envelope.task_id,
                trace_id=envelope.trace_id or "",
                source="command_router.route_envelope",
                message=f"dispatching {envelope.tool_name!r} to {list(envelope.targets)}",
            )
        except Exception as _replay_pre_exc:
            logger.debug(
                "route_envelope: ReplayFoundation route writes skipped: %s",
                _replay_pre_exc,
            )

        # ── PR-G: Emit dispatch decision event for observability sink ─────────
        # Emit before executing so the event is recorded even if dispatch fails.
        try:
            from core.runtime.runtime_observability_sink import emit_dispatch_decision_event

            _obs_meta = envelope.metadata or {}
            _obs_targets = list(envelope.targets)
            _obs_mode = "local"
            if _obs_meta.get("cross_device") == "true":
                _obs_mode = "remote_handoff"
            elif _obs_meta.get("parallel_fanout") == "true":
                _obs_mode = "staged_mesh"
            elif envelope.executor_target_type is not None:
                _obs_mode = str(envelope.executor_target_type)
            emit_dispatch_decision_event(
                mode=_obs_mode,
                event_kind="plan_selected",
                dispatch_id=envelope.task_id,
                trace_id=envelope.trace_id or "",
                task_id=envelope.task_id,
                session_id=str(_obs_meta.get("session_id", "")),
                source_device_id=str(envelope.source or ""),
                executor_target_type=str(envelope.executor_target_type or ""),
                target_device_id=_obs_targets[0] if _obs_targets else "",
                has_continuity_context=bool(_obs_meta.get("continuity_context")),
                has_mesh_session=bool(_obs_meta.get("mesh_session_id")),
                decision_reason="command_router.route_envelope",
                success=True,
            )
        except Exception as _obs_exc:
            logger.debug(
                "route_envelope: observability dispatch emit skipped (non-fatal): %s",
                _obs_exc,
            )

        # Extract optional routing params stored in metadata by the compat layer.
        meta = envelope.metadata or {}
        command_id: str = str(meta.get("command_id") or envelope.task_id)
        request_id: str = str(meta.get("request_id") or envelope.task_id)
        retry_candidates: Optional[List[Any]] = meta.get("retry_candidates")  # type: ignore[assignment]
        # required_capabilities: prefer explicit field, fall back to metadata (with explicit cast)
        _meta_caps = meta.get("required_capabilities")
        required_capabilities: Optional[List[str]] = (
            list(envelope.required_capabilities)
            if envelope.required_capabilities
            else ([str(c) for c in _meta_caps] if isinstance(_meta_caps, list) else None)
        )
        try:
            max_retries: int = int(meta.get("max_retries", 2))
        except (TypeError, ValueError):
            max_retries = 2

        # ── PR-E: Explicit executor target type routing (first-class) ────────
        # When envelope.executor_target_type is set, route_envelope() branches
        # primarily on the explicit target type rather than metadata heuristics.
        # This is the canonical PR-E dispatch path.
        #
        # Mapping:
        #   android_device / node_service → _route_cross_device_envelope()
        #   go_worker                     → _route_worker_envelope() (MasterBrain)
        #   local                         → _execute_command() (local runtime)
        #
        # When executor_target_type is None the existing metadata-based heuristics
        # below remain active for backward compatibility.
        _explicit_target_type = envelope.executor_target_type
        if _explicit_target_type is not None:
            try:
                from core.schemas.remote_execution import ExecutorTargetType as _ETT
            except Exception as exc:
                logger.debug("Fallback triggered: %s", exc)
                _ETT = None  # type: ignore[assignment]

            if _ETT is not None and _explicit_target_type in (
                _ETT.android_device,
                _ETT.node_service,
            ):
                # Android device or node service — route via cross-device substrate.
                # PR-H: record path selection
                if _live_expl_builder is not None:
                    try:
                        _live_expl_builder.record_route_path_selection(
                            _P_CROSS,
                            selected_target=envelope.target,
                            reason=(
                                f"explicit executor_target_type='{_explicit_target_type}' "
                                "→ cross-device substrate (DeviceRouter)"
                            ),
                        )
                    except Exception as exc:
                        logger.warning("Exception suppressed: %s", exc)
                result = await self._route_cross_device_envelope(
                    envelope=envelope,
                    command_id=command_id,
                    request_id=request_id,
                )
            elif _ETT is not None and _explicit_target_type == _ETT.go_worker:
                # Go worker — delegate to MasterBrain/worker dispatch boundary.
                # PR-H: record path selection
                if _live_expl_builder is not None:
                    try:
                        _live_expl_builder.record_route_path_selection(
                            _P_WORKER,
                            selected_target=envelope.target,
                            reason=(
                                "explicit executor_target_type='go_worker' "
                                "→ MasterBrain worker domain"
                            ),
                        )
                    except Exception as exc:
                        logger.warning("Exception suppressed: %s", exc)
                result = await self._route_worker_envelope(
                    envelope=envelope,
                    command_id=command_id,
                    request_id=request_id,
                )
            else:
                # local (or unknown explicit type) — local runtime execution.
                # PR-H: record path selection
                if _live_expl_builder is not None:
                    try:
                        _live_expl_builder.record_route_path_selection(
                            _P_LOCAL,
                            selected_target=envelope.target,
                            reason=(
                                f"explicit executor_target_type='{_explicit_target_type}' "
                                "→ local runtime execution"
                            ),
                        )
                    except Exception as exc:
                        logger.warning("Exception suppressed: %s", exc)
                result = await self._execute_command(
                    device_id=envelope.target,
                    command=envelope.tool_name,
                    payload=envelope.args,
                    command_id=command_id,
                    task_id=envelope.task_id,
                    timeout=envelope.timeout,
                    request_id=request_id,
                    trace_id=envelope.trace_id,
                    retry_candidates=retry_candidates,
                    required_capabilities=required_capabilities,
                    max_retries=max_retries,
                )
        # ── PR-518/GAP-517-001: Cross-device canonical dispatch path ─────────
        # Fallback heuristic (backward compat): when executor_target_type is
        # not set, check metadata["cross_device"] / ["parallel_fanout"].
        # ── PR-5A: Policy engine consultation (heuristic path) ───────────────
        # When executor_target_type is None (i.e. we are in the heuristic
        # branch), consult apply_target_selection_policy() before the legacy
        # metadata branches.  The decision is recorded for observability but
        # does NOT override the heuristic routing — backward compat is preserved.
        elif meta.get("cross_device") == "true":
            # PR-5A: invoke policy engine as an observability side-effect only.
            try:
                from core.runtime.execution_target_policy_engine import (
                    apply_target_selection_policy as _apply_tsp_cd,
                )

                _tsp_cd = _apply_tsp_cd(
                    executor_target_type="android_device",
                    candidate_device_ids=list(envelope.targets),
                    task_id=envelope.task_id,
                    trace_id=envelope.trace_id,
                    metadata={"source": "command_router.route_envelope.cross_device"},
                )
                if _tsp_cd is not None:
                    logger.debug(
                        "route_envelope[cross_device]: policy_engine decision=%s task_id=%s",
                        getattr(_tsp_cd, "policy_kind", None),
                        envelope.task_id,
                    )
            except Exception as exc:
                logger.debug("Suppressed: %s", exc)
            # PR-H: record heuristic cross-device path selection
            if _live_expl_builder is not None:
                try:
                    _live_expl_builder.record_route_path_selection(
                        _P_CROSS,
                        selected_target=envelope.target,
                        reason="metadata cross_device=true → cross-device substrate (DeviceRouter)",
                    )
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)
            result = await self._route_cross_device_envelope(
                envelope=envelope,
                command_id=command_id,
                request_id=request_id,
            )
        elif meta.get("parallel_fanout") == "true":
            # PR-H: record parallel fanout path selection
            if _live_expl_builder is not None:
                try:
                    _live_expl_builder.record_route_path_selection(
                        _P_FANOUT,
                        selected_target=None,
                        reason="metadata parallel_fanout=true → canonical parallel fan-out",
                    )
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)
            result = await self._route_parallel_fanout_envelope(
                envelope=envelope,
                command_id=command_id,
                request_id=request_id,
            )
        else:
            # PR-5A: invoke policy engine for the local (heuristic) path.
            try:
                from core.runtime.execution_target_policy_engine import (
                    apply_target_selection_policy as _apply_tsp_local,
                )

                _ps_candidate_ids = list(envelope.targets) if envelope.targets else []
                _ps_readiness_map: Dict[str, str] = {}
                for _cid in _ps_candidate_ids:
                    try:
                        from core.device_readiness import get_device_readiness as _gdr

                        _r = _gdr(_cid)
                        if _r is not None:
                            _ps_readiness_map[_cid] = str(
                                getattr(_r, "readiness_status", None)
                                or getattr(_r, "status", None)
                                or "unknown"
                            )
                    except Exception as exc:
                        logger.debug("Suppressed: %s", exc)

                _ps_decision = _apply_tsp_local(
                    executor_target_type=None,
                    candidate_device_ids=_ps_candidate_ids,
                    readiness_map=_ps_readiness_map,
                    task_id=envelope.task_id,
                    trace_id=envelope.trace_id,
                    metadata={"source": "command_router.route_envelope.local_heuristic"},
                )
                if _ps_decision is not None:
                    logger.debug(
                        "route_envelope[local]: policy_engine decision=%s reason=%r task_id=%s",
                        getattr(_ps_decision, "policy_kind", None),
                        getattr(_ps_decision, "decision_reason", None),
                        envelope.task_id,
                    )
                    _ps_dict = (
                        _ps_decision.to_dict()
                        if hasattr(_ps_decision, "to_dict")
                        else {}
                    )
                    envelope = envelope.model_copy(
                        update={
                            "metadata": {
                                **envelope.metadata,
                                "_policy_selection_decision": _ps_dict,
                            }
                        }
                    )
            except Exception as exc:
                logger.debug("Suppressed: %s", exc)
            # PR-H: record local path selection
            if _live_expl_builder is not None:
                try:
                    _live_expl_builder.record_route_path_selection(
                        _P_LOCAL,
                        selected_target=envelope.target,
                        reason=(
                            "no explicit executor_target_type or cross-device/fanout metadata; "
                            "dispatching via local execution runtime"
                        ),
                    )
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)
            result = await self._execute_command(
                device_id=envelope.target,
                command=envelope.tool_name,
                payload=envelope.args,
                command_id=command_id,
                task_id=envelope.task_id,
                timeout=envelope.timeout,
                request_id=request_id,
                trace_id=envelope.trace_id,
                retry_candidates=retry_candidates,
                required_capabilities=required_capabilities,
                max_retries=max_retries,
            )

        # ── Propagate constraint chain trace into result ──────────────────────
        # Attach the pre-dispatch constraint chain trace to the result so that
        # reviewers can verify which checks were applied and why a route was
        # accepted or rejected across the full constraint chain.
        # Only attached when at least one gate was actually consulted (additive).
        if _constraint_chain_trace.get("admissibility_applied") or _constraint_chain_trace.get(
            "posture_filter_applied"
        ):
            result.setdefault("_constraint_chain_trace", _constraint_chain_trace)

        # ── PR-WEBRTC-TASK-LIFECYCLE: propagate trigger result ────────────────
        # If WebRTC task trigger was applied, attach its result dict to the
        # response so callers and observability sinks can see the outcome.
        if _webrtc_task_trigger_applied and _webrtc_task_trigger_result is not None:
            result.setdefault("_webrtc_task_trigger", _webrtc_task_trigger_result)

        # ── PR-H: Finalise live routing explanation and attach to result ───────
        # Now that the dispatch path has been selected and the result is known,
        # record the outcome and produce the full RouteExplanation + summary.
        # Attach it to the result dict so operators and reviewers can inspect
        # actual decision causality without re-running routing logic.
        if _live_expl_builder is not None:
            try:
                _live_expl_builder.record_result_outcome(
                    success=bool(result.get("success")),
                    error_code=str(result.get("error_code") or ""),
                    via=str(result.get("via") or ""),
                )
                _final_explanation = _live_expl_builder.build()
                _final_summary = _live_expl_builder.build_summary()
                result.setdefault("routing_explanation", _final_explanation.to_dict())
                result.setdefault("routing_explanation_summary", _final_summary.to_dict())
            except Exception as _expl_fin_exc:
                logger.debug(
                    "route_envelope: live explanation finalisation skipped (non-fatal): %s",
                    _expl_fin_exc,
                )

        # ── PR-506: Close graph / replay / audit from result ─────────────────
        try:
            from core.task_graph_runtime import (
                get_task_graph_runtime as _get_tgr,
                WorkflowContributorKind as _WCK,
            )
            from core.replay_foundation import (
                TaskExecutionRecord as _TER,
                get_replay_foundation as _get_rf,
                emit_runtime_event as _emit_ev2,
                ReplayEventKind as _REK,
            )
            from core.audit_event_semantics import (
                audit_task_completed as _audit_completed,
                audit_task_failed as _audit_failed,
            )
            import time as _time_mod

            _is_success = bool(result.get("success"))
            _err_code = result.get("error_code", "") or ""
            _tr_id = result.get("trace_id", "") or envelope.trace_id or ""
            _t_id = result.get("task_id", "") or envelope.task_id

            # 1. Close the TaskGraphRuntime node using the module-level proxy
            _proxy = _RouteResultProxy(
                task_id=_t_id,
                success=_is_success,
                result_data=result.get("result"),
                error=str(_err_code) if _err_code else (result.get("error_message") or ""),
            )
            _get_tgr().complete_from_result_envelope(
                _proxy,
                contributor=_WCK.COMMAND_ROUTER,
            )

            # 2. Record TaskExecutionRecord in ReplayFoundation
            _exec_rec = _TER(
                task_id=_t_id,
                trace_id=_tr_id,
                requested_action=envelope.tool_name or "",
                selected_targets=list(envelope.targets),
                final_lifecycle="completed" if _is_success else "failed",
                success=_is_success,
                error_code=_err_code,
                failure_domain=result.get("failure_domain", "") or "",
                completed_at=_time_mod.time(),
            )
            _get_rf().record_execution(_exec_rec)

            # 3. Emit replay runtime event so replay_task_timeline is populated
            _ev_kind = _REK.TASK_COMPLETED if _is_success else _REK.TASK_FAILED
            _emit_ev2(
                _ev_kind,
                task_id=_t_id,
                trace_id=_tr_id,
                source="command_router.route_envelope",
                message=(f"task {'completed' if _is_success else 'failed'}: " f"{envelope.tool_name!r}"),
                payload=(
                    {}
                    if _is_success
                    else {
                        "error_code": _err_code,
                        "failure_domain": result.get("failure_domain", ""),
                    }
                ),
            )

            # 4. Emit canonical audit event
            if _is_success:
                _audit_completed(
                    _t_id,
                    trace_id=_tr_id,
                    source="command_router.route_envelope",
                    success=True,
                )
            else:
                _audit_failed(
                    _t_id,
                    trace_id=_tr_id,
                    source="command_router.route_envelope",
                    error_code=_err_code,
                    failure_domain=result.get("failure_domain", "") or "",
                )
        except Exception as _result_close_exc:
            logger.debug(
                "route_envelope: graph/replay/audit result-close skipped: %s",
                _result_close_exc,
            )

        # ── PR-5 Cap 1: lifecycle transition running → done/failed ───────────
        try:
            from core.task_lifecycle import get_lifecycle_manager

            _lcm = get_lifecycle_manager()
            if result.get("success"):
                _lcm.mark_done(
                    envelope,
                    result_summary=str(result.get("result", ""))[:200],
                )
            else:
                _lcm.mark_failed(
                    envelope,
                    error=str(result.get("error_message", "unknown"))[:200],
                )
        except Exception as _lc_exc:
            logger.debug("Lifecycle terminal transition skipped: %s", _lc_exc)

        # ── PR-5 RemoteExecutionMode: propagate through result ───────────────
        if envelope.remote_execution_mode is not None:
            result["remote_execution_mode"] = envelope.remote_execution_mode.value

        # PR-9: stamp execution substrate authority role (additive, non-breaking).
        result.setdefault("execution_substrate_role", "execution_substrate")
        # PR-10: stamp architecture diagnostics layer identifier (additive).
        result.setdefault("arch_layer_id", "execution_substrate")
        result.setdefault(
            "tool_invocation_truth",
            {
                "route_envelope_invoked": True,
                "dispatch_executed": True,
            },
        )
        result.setdefault(
            "repo_mutation_truth",
            {
                # CommandRouter is a transport substrate; repo mutation side effects are out of scope here.
                "in_scope": False,
                "mutation_applied": False,
            },
        )

        # PR-12: stamp canonical lifecycle state on substrate result (additive).
        try:
            from core.schemas.execution_lifecycle import ExecutionLifecycleState as _ELS

            _lc_state = _ELS.SUCCEEDED.value if result.get("success") else _ELS.FAILED.value
            result.setdefault("lifecycle_state", _lc_state)
            # Remote dispatch: record that we went through waiting_remote
            _is_remote = envelope.remote_execution_mode is not None
            if _is_remote:
                result.setdefault("lifecycle_via_waiting_remote", True)
        except Exception as _lc12_exc:
            logger.debug("PR-12 lifecycle stamp skipped: %s", _lc12_exc)

        # PR-13: stamp failure domain on failed results (additive, non-breaking).
        if not result.get("success"):
            try:
                from core.failure_domains import classify_from_error_code as _cfe

                _fd_cls = _cfe(result.get("error_code"))
                result.setdefault("failure_domain", _fd_cls.domain.value)
                result.setdefault("failure_is_retryable", _fd_cls.is_retryable)
            except Exception as _fd_exc:
                logger.debug("PR-13 failure_domain stamp skipped: %s", _fd_exc)

        # PR-14: stamp additive introspection hints on substrate result.
        # PR-1: execution_path="local" normalised to match the canonical local
        #        execution chain (core/local_execution_chain.py).
        result.setdefault(
            "introspection_snapshot",
            {
                "authority_role": "execution_substrate",
                "execution_path": "local",
                "execution_substrate_role": result.get("execution_substrate_role", "execution_substrate"),
                "execution_mode": result.get("remote_execution_mode"),
                "lifecycle_state": result.get("lifecycle_state"),
                "failure_domain": result.get("failure_domain"),
                "failure_is_retryable": result.get("failure_is_retryable"),
                "success": result.get("success"),
                "tool_invocation_truth": result.get("tool_invocation_truth"),
                "repo_mutation_truth": result.get("repo_mutation_truth"),
            },
        )

        return result

    async def route_command(
        self,
        device_id: str,
        command: str,
        payload: Dict[str, Any],
        command_id: str,
        task_id: str,
        timeout: float = 30.0,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        retry_candidates: Optional[List[Any]] = None,
        required_capabilities: Optional[List[str]] = None,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """Compatibility shim (PR-1): wraps legacy params in a TaskEnvelope
        and delegates to :meth:`route_envelope`.

        New code should construct a TaskEnvelope directly and call
        ``route_envelope`` instead.  This method is preserved for callers
        that have not yet been migrated and for external integrations that
        depend on the existing signature.
        """
        # PR-3 convergence: route_command is a compat shim only.
        # Keep behavior stable but emit a structured guardrail so this path is
        # explicitly downgraded from canonical ingress authority.
        try:
            from core.orchestration_authority.legacy_paths import emit_legacy_guardrail

            emit_legacy_guardrail(
                caller="core.command_router.CommandRouter.route_command",
                trace_id=trace_id,
                override_recommendation=(
                    "Construct TaskEnvelope and call CommandRouter.route_envelope() "
                    "directly for canonical ingress."
                ),
            )
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

        from core.schemas.task_envelope import TaskEnvelope as _TaskEnvelope

        envelope = _TaskEnvelope(
            task_id=task_id,
            trace_id=trace_id or f"trace_{uuid.uuid4().hex[:12]}",
            source="compat",
            targets=[device_id] if device_id else [],
            tool_name=command,
            args=payload or {},
            timeout=timeout,
            metadata={
                "request_id": request_id or f"req_{uuid.uuid4().hex[:12]}",
                "command_id": command_id,
                "retry_candidates": retry_candidates,
                "required_capabilities": required_capabilities,
                "max_retries": max_retries,
            },
        )
        return await self.route_envelope(envelope)

    # ------------------------------------------------------------------
    # Canonical device-transport delegation (canonical chain step:
    # CommandRouter → DeviceRouter)
    # ------------------------------------------------------------------

    async def _route_cross_device_envelope(
        self,
        envelope: "TaskEnvelope",
        command_id: str,
        request_id: str,
    ) -> Dict[str, Any]:
        """PR-518/GAP-517-001: Canonical cross-device dispatch via substrate.

        Called by :meth:`route_envelope` when ``metadata["cross_device"] == "true"``.
        Delegates execution to :meth:`galaxy_gateway.device_router.DeviceRouter.route_task`
        (substrate execution plumbing) while all canonical audit/trace/graph
        work has already been performed in :meth:`route_envelope`.

        The context passed to DeviceRouter includes ``_CROSS_DEVICE_SUBSTRATE_CALLER_KEY``
        so that CrossDeviceCoordinator can detect canonical invocations and
        suppress legacy-bypass warnings (GAP-517-003).

        CommandRouter remains the single canonical cross-device dispatcher;
        DeviceRouter and CrossDeviceCoordinator are substrate plumbing only.
        """
        import time as _time_m

        _t0 = _time_m.monotonic()
        try:
            from galaxy_gateway.device_router import device_router as _dr

            context = dict(envelope.args or {})
            _meta = envelope.metadata or {}
            context["task_id"] = envelope.task_id
            context["trace_id"] = envelope.trace_id
            context["route_mode"] = str(
                _meta.get("route_mode")
                or context.get("route_mode")
                or "cross_device"
            )
            if _meta.get("source_device_id"):
                context["source_device_id"] = _meta.get("source_device_id")
            if _meta.get("source_runtime_posture"):
                context["source_runtime_posture"] = _meta.get("source_runtime_posture")
            # Substrate-caller sentinel: signals to DeviceRouter / CrossDeviceCoordinator
            # that this invocation originates from the canonical CommandRouter path.
            context[_CROSS_DEVICE_SUBSTRATE_CALLER_KEY] = "command_router.route_envelope"

            # ── PR-ALIGN / SCHED-002: Validate targets against canonical ────────
            # admissibility chain (readiness → capability) before handing off to
            # DeviceRouter substrate.  Invalid targets are excluded with a
            # structured warning.  The validated primary target is passed as
            # context["device_id"] so DeviceRouter uses the canonical target rather
            # than re-selecting independently from its local session cache.
            # Gracefully degrades when the validator is unavailable.
            _envelope_targets = list(envelope.targets) if envelope.targets else []
            if _envelope_targets:
                try:
                    from core.target_device_validator import validate_target_device as _vtd

                    _req_caps: Optional[List[str]] = (
                        list(envelope.required_capabilities)
                        if envelope.required_capabilities
                        else None
                    )
                    _validated_ready_targets: List[str] = []
                    for _tid in _envelope_targets:
                        _tvr = _vtd(_tid, required_capabilities=_req_caps)
                        _readiness_consulted = not any(
                            r.startswith("readiness-unavailable")
                            for r in (_tvr.reasons or [])
                        )
                        if _readiness_consulted:
                            if _tvr.ready:
                                _validated_ready_targets.append(_tid)
                            else:
                                logger.warning(
                                    "_route_cross_device_envelope [SCHED-002]: "
                                    "target %r excluded by admissibility check — "
                                    "registered=%s ready=%s reasons=%s task_id=%s",
                                    _tid,
                                    _tvr.registered,
                                    _tvr.ready,
                                    _tvr.reasons,
                                    envelope.task_id,
                                )
                        else:
                            # Readiness module unavailable — include by default
                            _validated_ready_targets.append(_tid)

                    if _validated_ready_targets:
                        if len(_validated_ready_targets) < len(_envelope_targets):
                            logger.warning(
                                "_route_cross_device_envelope [SCHED-002]: "
                                "filtered %d → %d target(s) after admissibility "
                                "check; excluded: %s task_id=%s",
                                len(_envelope_targets),
                                len(_validated_ready_targets),
                                [t for t in _envelope_targets if t not in _validated_ready_targets],
                                envelope.task_id,
                            )
                            envelope = envelope.model_copy(update={"targets": _validated_ready_targets})
                    else:
                        # All targets were checked and all failed readiness —
                        # warn loudly but proceed with original set to degrade
                        # gracefully (the canonical target was not reachable, but
                        # we surface the warning rather than silently dropping).
                        logger.warning(
                            "_route_cross_device_envelope [SCHED-002]: all %d "
                            "target(s) failed admissibility check; proceeding "
                            "with original set (graceful degradation) task_id=%s",
                            len(_envelope_targets),
                            envelope.task_id,
                        )
                except Exception as _adm_exc:
                    logger.debug(
                        "_route_cross_device_envelope: admissibility validation "
                        "skipped (graceful degradation): %s",
                        _adm_exc,
                    )

            # Propagate the validated primary target as device_id so DeviceRouter
            # uses the canonical target set from the admissibility check above
            # rather than independently re-selecting from its local session cache.
            if envelope.target:
                context["device_id"] = envelope.target

            raw = await _dr.route_task(envelope.tool_name, context=context)
            _latency_ms = (_time_m.monotonic() - _t0) * 1000
            return {
                "request_id": request_id,
                "task_id": envelope.task_id,
                "trace_id": envelope.trace_id,
                "command_id": command_id,
                "device_id": "",
                "command": envelope.tool_name,
                "via": "command_router.cross_device_substrate",
                "success": raw.get("success", False),
                "result": raw,
                "error_code": None if raw.get("success") else "CROSS_DEVICE_SUBSTRATE_FAILED",
                "error_message": raw.get("error"),
                "latency_ms": round(_latency_ms, 1),
            }
        except Exception as _exc:
            logger.debug("Fallback triggered: %s", _exc)
            _latency_ms = (_time_m.monotonic() - _t0) * 1000
            logger.error(
                "_route_cross_device_envelope failed | task_id=%s error=%s",
                envelope.task_id,
                _exc,
            )
            return {
                "request_id": request_id,
                "task_id": envelope.task_id,
                "trace_id": envelope.trace_id,
                "command_id": command_id,
                "device_id": "",
                "command": envelope.tool_name,
                "via": "command_router.cross_device_substrate",
                "success": False,
                "result": None,
                "error_code": "CROSS_DEVICE_SUBSTRATE_ERROR",
                "error_message": str(_exc),
                "latency_ms": round(_latency_ms, 1),
            }

    async def _route_worker_envelope(
        self,
        envelope: "TaskEnvelope",
        command_id: str,
        request_id: str,
    ) -> Dict[str, Any]:
        """PR-E: Delegate dispatch to MasterBrain for go_worker targets.

        Called by :meth:`route_envelope` when
        ``envelope.executor_target_type == ExecutorTargetType.go_worker``.

        Authority boundary
        ------------------
        * **CommandRouter** (this module) is the *system-level* authority:
          ACL enforcement, lifecycle state transitions, audit/trace writes,
          and the canonical ``TaskEnvelope`` contract all happen in
          :meth:`route_envelope` *before* this method is called.

        * **MasterBrain** is the *worker-domain* authority: it owns worker
          selection (least-loaded, device-type matching), NATS/JetStream
          publication, and worker-level retry.

        The two authority domains are non-overlapping.  Callers MUST NOT
        invoke :class:`~core.master_brain.MasterBrain` directly for
        go_worker tasks — route through :meth:`route_envelope` so that
        system-level concerns are always enforced.
        """
        import time as _time_m

        _t0 = _time_m.monotonic()
        try:
            from core.master_brain import get_master_brain

            mb = get_master_brain()
            if mb is None:
                _latency_ms = (_time_m.monotonic() - _t0) * 1000
                return {
                    "request_id": request_id,
                    "task_id": envelope.task_id,
                    "trace_id": envelope.trace_id,
                    "command_id": command_id,
                    "device_id": envelope.target,
                    "command": envelope.tool_name,
                    "via": "command_router.worker_masterbrain",
                    "success": False,
                    "result": None,
                    "error_code": "WORKER_DISPATCH_UNAVAILABLE",
                    "error_message": "distributed_control_plane_disabled_or_unavailable",
                    "latency_ms": round(_latency_ms, 1),
                    "distributed_dispatch": False,
                    "execution_path": "distributed_unavailable",
                    "completion_state": "dispatch_unavailable",
                    "closure_complete": True,
                    "dispatch_attempted": False,
                    "dispatch_accepted": False,
                    "execution_started": False,
                    "result_received": False,
                    "result_pending_closure": False,
                    "task_outcome_known": True,
                    "lifecycle_state": "not_started",
                }
            raw_task: Dict[str, Any] = {
                "task_id": envelope.task_id,
                "trace_id": envelope.trace_id,
                "tool_name": envelope.tool_name,
                "args": dict(envelope.args or {}),
                "target_worker_id": envelope.target,
                "timeout": envelope.timeout,
            }
            raw = await mb.execute_distributed_task(raw_task)
            _latency_ms = (_time_m.monotonic() - _t0) * 1000
            selected_worker_raw = raw.get("worker_id")
            selected_worker_str = selected_worker_raw.strip() if isinstance(selected_worker_raw, str) else ""
            selected_worker = (
                selected_worker_str
                if selected_worker_str
                else (envelope.target or "")
            )
            result = {
                "request_id": request_id,
                "task_id": envelope.task_id,
                "trace_id": envelope.trace_id,
                "command_id": command_id,
                "device_id": selected_worker,
                "worker_id": selected_worker,
                "command": envelope.tool_name,
                "via": "command_router.worker_masterbrain",
                "success": bool(raw.get("success")),
                "result": raw,
                "error_code": None if raw.get("success") else "WORKER_DISPATCH_FAILED",
                "error_message": raw.get("error"),
                "latency_ms": round(_latency_ms, 1),
            }
            self._copy_execution_truth_fields(result, raw)
            return result
        except Exception as _exc:
            logger.debug("Fallback triggered: %s", _exc)
            _latency_ms = (_time_m.monotonic() - _t0) * 1000
            logger.error(
                "_route_worker_envelope failed | task_id=%s error=%s",
                envelope.task_id,
                _exc,
            )
            return {
                "request_id": request_id,
                "task_id": envelope.task_id,
                "trace_id": envelope.trace_id,
                "command_id": command_id,
                "device_id": envelope.target,
                "command": envelope.tool_name,
                "via": "command_router.worker_masterbrain",
                "success": False,
                "result": None,
                "error_code": "WORKER_DISPATCH_ERROR",
                "error_message": str(_exc),
                "latency_ms": round(_latency_ms, 1),
            }

    async def _route_parallel_fanout_envelope(
        self,
        envelope: TaskEnvelope,
        command_id: str,
        request_id: str,
    ) -> Dict[str, Any]:
        """PR-532/GAP-517-002: Canonical parallel fan-out via sub-envelopes."""
        import time as _time_m

        _t0 = _time_m.monotonic()
        _commands = envelope.args.get("commands")
        if not isinstance(_commands, list) or not _commands:
            _latency_ms = (_time_m.monotonic() - _t0) * 1000
            return {
                "request_id": request_id,
                "task_id": envelope.task_id,
                "trace_id": envelope.trace_id,
                "command_id": command_id,
                "device_id": "",
                "command": envelope.tool_name,
                "via": "command_router.parallel_fanout",
                "success": False,
                "result": None,
                "error_code": GatewayErrorCode.INVALID_ENVELOPE.value,
                "error_message": "Parallel fan-out requires a non-empty commands list",
                "latency_ms": round(_latency_ms, 1),
            }

        _subtasks: List[_ParallelSubtask] = []
        _processed: List[Dict[str, Any]] = []
        _base_meta = dict(envelope.metadata or {})
        _base_meta.pop("parallel_fanout", None)

        for _idx, _raw in enumerate(_commands):
            if not isinstance(_raw, dict):
                _processed.append(
                    {
                        "index": _idx,
                        "device_id": "",
                        "command": "",
                        "task_id": f"{envelope.task_id}__p{_idx:02d}",
                        "trace_id": envelope.trace_id,
                        "success": False,
                        "result": None,
                        "error_code": GatewayErrorCode.INVALID_ENVELOPE.value,
                        "error_message": "Parallel command entry must be an object",
                        "via": "command_router.parallel_fanout",
                    }
                )
                continue

            _device_id = str(_raw.get("device_id") or "").strip()
            _command = str(_raw.get("command") or "").strip()
            _params = _raw.get("params")
            if not isinstance(_params, dict):
                logger.debug(
                    "_route_parallel_fanout_envelope: replacing non-dict params for %s[%d] (%s)",
                    _device_id or "<missing-device>",
                    _idx,
                    type(_params).__name__,
                )
                _params = {}
            _sub_task_id = f"{envelope.task_id}__p{_idx:02d}"

            if not _device_id or not _command:
                _processed.append(
                    {
                        "index": _idx,
                        "device_id": _device_id,
                        "command": _command,
                        "task_id": _sub_task_id,
                        "trace_id": envelope.trace_id,
                        "success": False,
                        "result": None,
                        "error_code": GatewayErrorCode.INVALID_ENVELOPE.value,
                        "error_message": "Parallel command entries require device_id and command",
                        "via": "command_router.parallel_fanout",
                    }
                )
                continue

            _sub_meta = dict(_base_meta)
            _sub_meta.update(
                {
                    "parallel_parent_task_id": envelope.task_id,
                    "parallel_index": str(_idx),
                    "request_id": f"{request_id}:p{_idx}",
                    "command_id": f"{command_id}:p{_idx}",
                }
            )

            _subtasks.append(
                _ParallelSubtask(
                    index=_idx,
                    info={
                        "device_id": _device_id,
                        "command": _command,
                    },
                    envelope=TaskEnvelope(
                        task_id=_sub_task_id,
                        trace_id=envelope.trace_id,
                        session_id=envelope.session_id,
                        source=envelope.source or "command_router.parallel_fanout",
                        targets=[_device_id],
                        tool_name=_command,
                        args=_params,
                        priority=envelope.priority,
                        timeout=envelope.timeout,
                        permission_level=envelope.permission_level,
                        required_capabilities=list(envelope.required_capabilities),
                        metadata=_sub_meta,
                        remote_execution_mode=envelope.remote_execution_mode,
                    ),
                )
            )

        _results = await asyncio.gather(
            *(self.route_envelope(_subtask.envelope) for _subtask in _subtasks),
            return_exceptions=True,
        )

        for _subtask, _result in zip(_subtasks, _results):
            _idx = _subtask.index
            _info = _subtask.info
            _env = _subtask.envelope
            if isinstance(_result, Exception):
                _processed.append(
                    {
                        "index": _idx,
                        "device_id": _info["device_id"],
                        "command": _info["command"],
                        "task_id": _env.task_id,
                        "trace_id": _env.trace_id,
                        "success": False,
                        "result": None,
                        "error_code": "PARALLEL_SUBTASK_EXCEPTION",
                        "error_message": str(_result),
                        "via": "command_router.parallel_fanout",
                    }
                )
                continue

            _processed.append(
                {
                    "index": _idx,
                    "device_id": _info["device_id"],
                    "command": _info["command"],
                    "task_id": _result.get("task_id", _env.task_id),
                    "trace_id": _result.get("trace_id", _env.trace_id),
                    "request_id": _result.get("request_id"),
                    "command_id": _result.get("command_id"),
                    "success": bool(_result.get("success")),
                    "result": _result.get("result"),
                    "error_code": _result.get("error_code"),
                    "error_message": _result.get("error_message"),
                    "via": _result.get("via", "command_router"),
                }
            )

        _processed.sort(key=lambda _entry: int(_entry.get("index", 0)))
        _success_count = sum(1 for _entry in _processed if _entry.get("success"))
        _overall_success = bool(_processed) and _success_count == len(_processed)
        _latency_ms = (_time_m.monotonic() - _t0) * 1000

        return {
            "request_id": request_id,
            "task_id": envelope.task_id,
            "trace_id": envelope.trace_id,
            "command_id": command_id,
            "device_id": "",
            "command": envelope.tool_name,
            "via": "command_router.parallel_fanout",
            "success": _overall_success,
            "result": {
                "success": _overall_success,
                "total": len(_processed),
                "successful": _success_count,
                "failed": len(_processed) - _success_count,
                "results": _processed,
            },
            "error_code": None if _overall_success else "PARALLEL_SUBTASK_FAILURE",
            "error_message": None if _overall_success else "One or more parallel commands failed",
            "latency_ms": round(_latency_ms, 1),
        }

    async def _dispatch_via_device_router(
        self,
        device_id: str,
        command: str,
        payload: Dict[str, Any],
        task_id: str,
        trace_id: str,
        command_id: str,
        timeout: float = 30.0,
    ) -> Optional[Dict[str, Any]]:
        """Delegate transport dispatch to ``DeviceRouter`` (canonical chain).

        This method implements the ``CommandRouter → DeviceRouter`` hop in
        the canonical execution chain::

            OpenClawd → CommandRouter (orchestration)
                → _dispatch_via_device_router()
                    → DeviceRouter.send_command_to_device() (transport)
                        → WebSocket / device

        It attempts to look up the target device in ``DeviceRouter``'s live
        session table and delegates the actual send to
        :meth:`galaxy_gateway.device_router.DeviceRouter.send_command_to_device`.
        When ``DeviceRouter`` is unavailable or the device is not registered
        in its table the caller falls back to ``connection_manager`` directly.

        Returns:
            Result dict on success (keys: ``success``, ``result``,
            ``error_message``, ``task_id``, ``trace_id``, ``via``), or
            ``None`` when DeviceRouter is unavailable / device not found.

        Note:
            This method **must not** call :meth:`route_envelope` — doing so
            would create an infinite recursion.  It is intended as the
            terminal transport step after all orchestration decisions are
            complete.
        """
        try:
            from galaxy_gateway.device_router import device_router as _dr  # lazy import

            device = _dr.get_device(device_id)
            if device is None:
                return None  # device not in DeviceRouter — caller will fall back

            # Build a minimal task dict compatible with DeviceRouter.dispatch_task.
            # We deliberately do NOT route back through route_envelope to avoid
            # recursion; we call send_command_to_device which is the terminal
            # WebSocket sender on DeviceRouter.
            result = await _dr.send_command_to_device(
                device_id=device_id,
                command=command,
                payload=payload,
                task_id=task_id,
                trace_id=trace_id,
                timeout=timeout,
            )
            if result is not None:
                result.setdefault("command_id", command_id)
                result.setdefault("via", "command_router->device_router")
            return result
        except Exception as _dr_exc:
            logger.debug(
                "CommandRouter._dispatch_via_device_router unavailable " "(will fall back): %s",
                _dr_exc,
            )
            return None

    async def _execute_command(
        self,
        device_id: str,
        command: str,
        payload: Dict[str, Any],
        command_id: str,
        task_id: str,
        timeout: float = 30.0,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        retry_candidates: Optional[List[Any]] = None,
        required_capabilities: Optional[List[str]] = None,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """Internal execution engine, called by :meth:`route_envelope`.

        Contains the full routing logic: audit events, HITL gate, envelope
        validation, circuit-breaker, device dispatch and retry loop.

        統一网关命令路径：OpenClawd → command_router → gateway/device → result

        所有命令必须经由此方法执行，确保：
          1. 协议信封验证（invalid_envelope 立即返回错误）
          2. 全链路 trace ID（request_id / task_id / command_id / device_id）
          3. 超时与断连结构化错误代码
          4. 结果写入 GatewayTraceStore 供可观测接口查询

        Returns:
            {
                "success": bool,
                "result": any,
                "error_code": str | None,   # GatewayErrorCode 值
                "error_message": str | None,
                "request_id": str,
                "task_id": str,
                "command_id": str,
                "device_id": str,
                "latency_ms": float,
                "via": "command_router",
            }
        """
        request_id = request_id or f"req_{uuid.uuid4().hex[:12]}"
        trace_id = trace_id or f"trace_{uuid.uuid4().hex[:12]}"
        t0 = time.monotonic()

        trace_base = {
            "request_id": request_id,
            "task_id": task_id,
            "trace_id": trace_id,
            "command_id": command_id,
            "device_id": device_id,
            "command": command,
            "via": "command_router",
        }

        logger.info(
            "CommandRouter._execute_command | trace_id=%s task_id=%s command_id=%s " "device_id=%s command=%s",
            trace_id,
            task_id,
            command_id,
            device_id,
            command,
        )

        # ── Phase 2: emit TASK_DISPATCHED audit event ────────────────────────
        try:
            from core.control_plane.audit_ledger import EventType as _EvType

            self._emit_audit(
                _EvType.TASK_DISPATCHED,
                trace_id=trace_id,
                task_id=task_id,
                device_id=device_id,
                message=f"Dispatching command '{command}' to device '{device_id}'",
                payload={"command": command, "command_id": command_id},
            )
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

        # ── Early HITL gate: _hitl_approved payload flag ─────────────────────
        # Fast-path check: block high-risk commands that lack pre-approval.
        # If payload carries _hitl_approved=True, emit an approval audit event
        # and skip the full interceptor.  Otherwise return HITL_APPROVAL_REQUIRED
        # immediately so callers know they must obtain approval first.
        if self._is_high_risk_command(command):
            if payload.get("_hitl_approved") is True:
                self._emit_audit(
                    "HITL_PRE_APPROVED",
                    trace_id=trace_id,
                    task_id=task_id,
                    device_id=device_id,
                    message=(
                        f"HITL pre-approved via payload flag for high-risk command '{command}'"
                    ),
                    payload={"command": command},
                )
            else:
                latency_ms = (time.monotonic() - t0) * 1000
                self._emit_audit(
                    "HITL_REQUIRED",
                    trace_id=trace_id,
                    task_id=task_id,
                    device_id=device_id,
                    message=(
                        f"HITL approval required for high-risk command '{command}'"
                    ),
                    payload={"command": command},
                )
                result = {
                    **trace_base,
                    "success": False,
                    "result": None,
                    "error_code": "HITL_APPROVAL_REQUIRED",
                    "error_message": (
                        f"High-risk command '{command}' requires HITL approval. "
                        "Include _hitl_approved=True in payload after obtaining approval."
                    ),
                    "requires_hitl": True,
                    "latency_ms": round(latency_ms, 1),
                }
                _get_gateway_trace_store().record(result)
                return result

        # ── Async security interceptor HITL gate ─────────────────────────────
        # This gate runs ONLY for high-risk commands that have already passed the
        # fast-path gate above (i.e., _hitl_approved=True was provided).
        # It provides additional policy enforcement via an external interceptor
        # (e.g., time-bounded approval windows managed by a security service).
        # If the interceptor is unavailable the gate degrades gracefully (fail-open).
        if self._is_high_risk_command(command) and payload.get("_hitl_approved") is True:
            try:
                from core.control_plane._globals import get_security_interceptor
                from core.control_plane.security_interceptor import (
                    RiskLevel,
                    ApprovalTimeoutError,
                    ApprovalDeniedError,
                )
                from core.control_plane.audit_ledger import EventType as _EvHITL

                interceptor = get_security_interceptor()
                try:
                    ack_token = await interceptor.require_approval(
                        action=command,
                        task_id=task_id,
                        risk_level=RiskLevel.HIGH,
                        requestor="command_router",
                        context={"device_id": device_id, "command": command, "payload": payload},
                    )
                    self._emit_audit(
                        _EvHITL.APPROVAL_GRANTED,
                        trace_id=trace_id,
                        task_id=task_id,
                        device_id=device_id,
                        message=f"HITL approval granted for '{command}'",
                        payload={"ack_token": ack_token},
                    )
                except ApprovalTimeoutError as exc:
                    latency_ms = (time.monotonic() - t0) * 1000
                    self._emit_audit(
                        _EvHITL.APPROVAL_TIMED_OUT,
                        source="command_router.hitl",
                        trace_id=trace_id,
                        task_id=task_id,
                        device_id=device_id,
                        message=f"HITL approval timed out for '{command}'",
                    )
                    result = {
                        **trace_base,
                        "success": False,
                        "result": None,
                        "error_code": GatewayErrorCode.HITL_TIMEOUT.value,
                        "error_message": f"High-risk command '{command}' requires approval (timed out after {exc.timeout_seconds}s). "
                        f"Use POST /api/v1/approvals/{exc.request_id} to approve.",
                        "approval_request_id": exc.request_id,
                        "latency_ms": round(latency_ms, 1),
                    }
                    _get_gateway_trace_store().record(result)
                    return result
                except ApprovalDeniedError as exc:
                    latency_ms = (time.monotonic() - t0) * 1000
                    self._emit_audit(
                        _EvHITL.APPROVAL_DENIED,
                        source="command_router.hitl",
                        trace_id=trace_id,
                        task_id=task_id,
                        device_id=device_id,
                        message=f"HITL approval denied for '{command}': {exc.reason}",
                    )
                    result = {
                        **trace_base,
                        "success": False,
                        "result": None,
                        "error_code": GatewayErrorCode.HITL_DENIED.value,
                        "error_message": f"High-risk command '{command}' was denied: {exc.reason}",
                        "approval_request_id": exc.request_id,
                        "latency_ms": round(latency_ms, 1),
                    }
                    _get_gateway_trace_store().record(result)
                    return result
            except Exception as hitl_exc:
                # If the HITL subsystem itself fails, log and proceed (fail-open)
                logger.warning(
                    "CommandRouter HITL gate failed (fail-open) | command=%s error=%s",
                    command,
                    hitl_exc,
                )

        # ── 1. 协议信封校验 ──────────────────────────────────────────────
        try:
            validate_command_envelope(device_id, command, payload, command_id, task_id)
        except GatewayError as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            result = {
                **trace_base,
                "success": False,
                "result": None,
                "error_code": exc.code.value,
                "error_message": exc.message,
                "latency_ms": round(latency_ms, 1),
            }
            _get_gateway_trace_store().record(result)
            logger.warning(
                "CommandRouter._execute_command envelope invalid | trace_id=%s command_id=%s error=%s",
                trace_id,
                command_id,
                exc.message,
            )
            return result

        # ── 2. Phase 5: dispatch with optional retry loop ────────────────
        current_device = device_id
        tried_devices: set = set()
        attempt = 0

        while True:
            # ── Phase 5: circuit-breaker eligibility check (fail-open) ──
            _cb_eligible = True
            try:
                from core.control_plane._globals import get_health_registry as _get_hreg

                _cb_eligible = _get_hreg().is_eligible(current_device)
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

            if not _cb_eligible:
                # Device circuit is OPEN or quarantined – skip to next candidate
                tried_devices.add(current_device)
                next_dev = self._pick_retry_device(tried_devices, retry_candidates, required_capabilities)
                if next_dev is not None and attempt < max_retries:
                    try:
                        from core.control_plane.audit_ledger import EventType as _EvCB

                        self._emit_audit(
                            _EvCB.TASK_RETRY_SCHEDULED,
                            trace_id=trace_id,
                            task_id=task_id,
                            device_id=next_dev,
                            message=(
                                f"Retry #{attempt + 1}: circuit open on '{current_device}', "
                                f"rerouting to '{next_dev}'"
                            ),
                            payload={
                                "attempt": attempt + 1,
                                "skipped_device": current_device,
                                "reason": "circuit_open_or_quarantined",
                            },
                        )
                    except Exception as exc:
                        logger.warning("Exception suppressed: %s", exc)
                    # ── PR-506: Record fallback event (circuit-breaker bypass) ──
                    try:
                        from core.replay_foundation import (
                            record_fallback as _rec_fallback,
                            emit_runtime_event as _emit_ev_cb,
                            ReplayEventKind as _REK_cb,
                        )
                        from core.audit_event_semantics import (
                            audit_fallback_triggered as _audit_fb_cb,
                        )

                        _rec_fallback(
                            primary_task_id=task_id,
                            fallback_task_id=f"{task_id}:cb_fallback:{attempt + 1}",
                            reason="circuit_open_or_quarantined",
                            trace_id=trace_id,
                            primary_failure_domain="device",
                            primary_error_code="DEVICE_OFFLINE",
                        )
                        _emit_ev_cb(
                            _REK_cb.FALLBACK_TRIGGERED,
                            task_id=task_id,
                            trace_id=trace_id,
                            source="command_router._execute_command",
                            message=(f"circuit-breaker fallback: '{current_device}' → '{next_dev}'"),
                            payload={"attempt": attempt + 1, "skipped_device": current_device},
                        )
                        _audit_fb_cb(
                            task_id,
                            trace_id=trace_id,
                            source="command_router._execute_command",
                            reason="circuit_open_or_quarantined",
                            fallback_task_id=f"{task_id}:cb_fallback:{attempt + 1}",
                        )
                    except Exception as exc:
                        logger.warning("Exception suppressed: %s", exc)
                    # ── PR-508: Register fallback in TaskGraphRuntime ─────────
                    try:
                        from core.task_graph_runtime import (
                            get_task_graph_runtime as _get_tgr_fb,
                            WorkflowContributorKind as _WCK_fb,
                            GraphNode as _GN_fb,
                        )

                        _fb_task_id = f"{task_id}:cb_fallback:{attempt + 1}"
                        _tgr_fb = _get_tgr_fb()
                        _fb_stub = _GN_fb(
                            task_id=_fb_task_id,
                            contributor=_WCK_fb.COMMAND_ROUTER,
                            device_id=next_dev or "",
                            tool_name=command or "",
                        )
                        _tgr_fb.register_node(_fb_stub)
                        _tgr_fb.register_fallback(
                            primary_task_id=task_id,
                            fallback_task_id=_fb_task_id,
                            reason="circuit_open_or_quarantined",
                            contributor=_WCK_fb.COMMAND_ROUTER,
                        )
                    except Exception as exc:
                        logger.warning("Exception suppressed: %s", exc)
                    current_device = next_dev
                    attempt += 1
                    continue
                # No eligible candidate – return circuit-open error
                latency_ms = (time.monotonic() - t0) * 1000
                cb_result = {
                    **trace_base,
                    "device_id": current_device,
                    "success": False,
                    "result": None,
                    "error_code": GatewayErrorCode.DEVICE_OFFLINE.value,
                    "error_message": (
                        f"Device '{current_device}' circuit is open or quarantined "
                        "and no eligible alternative is available."
                    ),
                    "latency_ms": round(latency_ms, 1),
                }
                _get_gateway_trace_store().record(cb_result)
                return cb_result

            # ── Delegate to inner dispatch helper ───────────────────────
            attempt_trace = {**trace_base, "device_id": current_device}
            # ── PR-508: Lifecycle transitions: routed → dispatch → running ──
            try:
                from core.task_graph_runtime import (
                    get_task_graph_runtime as _get_tgr_exec,
                    GraphNodeState as _GNS_exec,
                )

                _tgr_exec = _get_tgr_exec()
                _tgr_exec.transition(task_id, _GNS_exec.DISPATCH)
                _tgr_exec.transition(task_id, _GNS_exec.RUNNING)
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)
            result = await self._dispatch_to_device(
                current_device,
                command,
                payload,
                command_id,
                task_id,
                timeout,
                attempt_trace,
                trace_id,
                t0,
            )

            # ── Phase 5: record outcome in health registry ───────────────
            try:
                from core.control_plane._globals import get_health_registry as _get_hreg2

                _hreg = _get_hreg2()
                if result["success"]:
                    _hreg.record_success(current_device)
                else:
                    _hreg.record_failure(
                        current_device,
                        error=result.get("error_message") or result.get("error_code", ""),
                    )
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

            if result["success"]:
                if attempt > 0:
                    # Emit TASK_RETRY_SUCCEEDED
                    try:
                        from core.control_plane.audit_ledger import EventType as _EvR

                        self._emit_audit(
                            _EvR.TASK_RETRY_SUCCEEDED,
                            trace_id=trace_id,
                            task_id=task_id,
                            device_id=current_device,
                            message=(f"Retry #{attempt} succeeded on device '{current_device}'"),
                            payload={"attempt": attempt, "original_device": device_id},
                        )
                    except Exception as exc:
                        logger.warning("Exception suppressed: %s", exc)
                return result

            # ── Failure: decide whether to retry ────────────────────────
            _retryable_codes = {
                GatewayErrorCode.COMMAND_TIMEOUT.value,
                GatewayErrorCode.DISCONNECT.value,
                GatewayErrorCode.EXECUTOR_ERROR.value,
            }
            is_retryable = result.get("error_code") in _retryable_codes

            if not is_retryable or retry_candidates is None or attempt >= max_retries:
                if attempt > 0:
                    try:
                        from core.control_plane.audit_ledger import EventType as _EvRF

                        self._emit_audit(
                            _EvRF.TASK_RETRY_FAILED,
                            trace_id=trace_id,
                            task_id=task_id,
                            device_id=current_device,
                            message=f"All retries exhausted after {attempt} attempt(s)",
                            payload={
                                "attempt": attempt,
                                "error_code": result.get("error_code"),
                                "original_device": device_id,
                            },
                        )
                    except Exception as exc:
                        logger.warning("Exception suppressed: %s", exc)
                return result

            # ── Pick next candidate and schedule retry ───────────────────
            tried_devices.add(current_device)
            next_dev = self._pick_retry_device(tried_devices, retry_candidates, required_capabilities)
            if next_dev is None:
                try:
                    from core.control_plane.audit_ledger import EventType as _EvRE

                    self._emit_audit(
                        _EvRE.TASK_RETRY_FAILED,
                        trace_id=trace_id,
                        task_id=task_id,
                        device_id=current_device,
                        message="No eligible retry candidate available",
                        payload={"attempt": attempt, "original_device": device_id},
                    )
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)
                return result

            try:
                from core.control_plane.audit_ledger import EventType as _EvRS

                self._emit_audit(
                    _EvRS.TASK_RETRY_SCHEDULED,
                    trace_id=trace_id,
                    task_id=task_id,
                    device_id=next_dev,
                    message=(f"Retry #{attempt + 1}: rerouting from '{current_device}' " f"to '{next_dev}'"),
                    payload={
                        "attempt": attempt + 1,
                        "failed_device": current_device,
                        "error_code": result.get("error_code"),
                        "original_device": device_id,
                    },
                )
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

            # ── PR-506: Record retry event in ReplayFoundation + AuditEventSemantics ─
            try:
                from core.replay_foundation import (
                    record_retry as _rec_retry,
                    emit_runtime_event as _emit_ev_rt,
                    ReplayEventKind as _REK_rt,
                )
                from core.audit_event_semantics import (
                    audit_retry_triggered as _audit_retry,
                )

                _rec_retry(
                    original_task_id=task_id,
                    retry_task_id=f"{task_id}:retry:{attempt + 1}",
                    reason=result.get("error_code", "retryable_failure") or "retryable_failure",
                    attempt_number=attempt + 1,
                    trace_id=trace_id,
                    original_error_code=result.get("error_code", "") or "",
                )
                _emit_ev_rt(
                    _REK_rt.RETRY_TRIGGERED,
                    task_id=task_id,
                    trace_id=trace_id,
                    source="command_router._execute_command",
                    message=(
                        f"retry #{attempt + 1}: '{current_device}' → '{next_dev}' "
                        f"after {result.get('error_code', 'failure')!r}"
                    ),
                    payload={
                        "attempt": attempt + 1,
                        "failed_device": current_device,
                        "next_device": next_dev,
                        "error_code": result.get("error_code", ""),
                    },
                )
                _audit_retry(
                    task_id,
                    trace_id=trace_id,
                    source="command_router._execute_command",
                    retry_task_id=f"{task_id}:retry:{attempt + 1}",
                    attempt_number=attempt + 1,
                    reason=result.get("error_code", "retryable_failure") or "retryable_failure",
                )
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

            # ── PR-508: Register retry in TaskGraphRuntime ────────────────────
            try:
                from core.task_graph_runtime import (
                    get_task_graph_runtime as _get_tgr_retry,
                    WorkflowContributorKind as _WCK_retry,
                )

                _retry_task_id = f"{task_id}:retry:{attempt + 1}"
                _tgr_retry = _get_tgr_retry()
                # Register retry node (stub) so edge can be wired
                from core.task_graph_runtime import GraphNode as _GN_retry, GraphNodeState as _GNS_retry

                _retry_stub = _GN_retry(
                    task_id=_retry_task_id,
                    contributor=_WCK_retry.COMMAND_ROUTER,
                    device_id=next_dev or "",
                    tool_name=command or "",
                )
                _tgr_retry.register_node(_retry_stub)
                _tgr_retry.register_retry(
                    original_task_id=task_id,
                    retry_task_id=_retry_task_id,
                    attempt_number=attempt + 1,
                    reason=result.get("error_code", "retryable_failure") or "retryable_failure",
                    contributor=_WCK_retry.COMMAND_ROUTER,
                )
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

            current_device = next_dev
            attempt += 1

    # ------------------------------------------------------------------
    # Phase 5: inner dispatch helper + retry device picker
    # ------------------------------------------------------------------

    @staticmethod
    def _evaluate_executor_result(raw_result: Any) -> tuple[bool, str]:
        """Evaluate executor return payload into canonical success/error semantics."""
        if not isinstance(raw_result, dict):
            return raw_result is not None, ""

        if "success" in raw_result:
            success = bool(raw_result.get("success"))
        else:
            success = not bool(
                raw_result.get("error")
                or raw_result.get("error_message")
                or raw_result.get("error_code")
            )

        error_message = str(
            raw_result.get("error")
            or raw_result.get("error_message")
            or raw_result.get("message")
            or ""
        )
        return success, error_message

    @staticmethod
    def _copy_execution_truth_fields(result: dict, raw_result: Any) -> None:
        """Propagate distributed-runtime truth markers from executor payload."""
        if not isinstance(raw_result, dict):
            return
        for marker_field in (
            "distributed_dispatch",
            "execution_path",
            "fallback_used",
            "fallback_reason",
            "nats_publish_state",
            "completion_state",
            "closure_complete",
            "dispatch_attempted",
            "dispatch_accepted",
            "execution_started",
            "result_received",
            "result_pending_closure",
            "task_outcome_known",
            "lifecycle_state",
            "temporal_worker_active",
            "temporal_runtime_available",
            "temporal_client_connected",
            "temporal_workflow_type",
            "workflow_id",
            "run_id",
            "worker_id",
        ):
            if marker_field in raw_result:
                result[marker_field] = raw_result[marker_field]

    async def _dispatch_to_device(
        self,
        device_id: str,
        command: str,
        payload: Dict[str, Any],
        command_id: str,
        task_id: str,
        timeout: float,
        trace_base: Dict[str, Any],
        trace_id: str,
        t0: float,
    ) -> Dict[str, Any]:
        """Attempt a single dispatch to *device_id*.  Never retries.

        Returns the standard result dict (``success``, ``error_code``, etc.).
        """
        if self._executor:
            try:
                # PR-2: inject envelope identifiers into params so executor
                # (e.g. NATSExecutor) can reuse the TaskEnvelope's task_id
                # instead of generating a new UUID.  Keys prefixed with
                # "_galaxy_" are reserved for internal metadata and removed
                # by the executor before forwarding to the device.
                _exec_params = dict(payload)
                _exec_params.setdefault("_galaxy_task_id", task_id)
                _exec_params.setdefault("_galaxy_trace_id", trace_id)
                raw_result = await asyncio.wait_for(
                    self._executor(device_id, command, _exec_params),
                    timeout=timeout,
                )
                latency_ms = (time.monotonic() - t0) * 1000
                raw_success, raw_error_message = self._evaluate_executor_result(raw_result)
                result = {
                    **trace_base,
                    "success": raw_success,
                    "result": raw_result,
                    "error_code": None if raw_success else GatewayErrorCode.EXECUTOR_ERROR.value,
                    "error_message": None if raw_success else (raw_error_message or "Executor returned failure"),
                    "latency_ms": round(latency_ms, 1),
                }
                self._copy_execution_truth_fields(result, raw_result)
                _get_gateway_trace_store().record(result)
                if raw_success:
                    self._stats["total_success"] = self._stats.get("total_success", 0) + 1
                    logger.info(
                        "CommandRouter._dispatch_to_device done | " "trace_id=%s command_id=%s device=%s latency=%.1fms",
                        trace_id,
                        command_id,
                        device_id,
                        latency_ms,
                    )
                    try:
                        from core.control_plane.audit_ledger import EventType as _EvC

                        self._emit_audit(
                            _EvC.TASK_COMPLETED,
                            trace_id=trace_id,
                            task_id=task_id,
                            device_id=device_id,
                            message=f"Command '{command}' completed on '{device_id}'",
                            payload={"latency_ms": round(latency_ms, 1)},
                        )
                    except Exception as exc:
                        logger.warning("Exception suppressed: %s", exc)
                else:
                    self._stats["total_failed"] = self._stats.get("total_failed", 0) + 1
                    logger.warning(
                        "CommandRouter._dispatch_to_device executor returned failure | "
                        "trace_id=%s command_id=%s device=%s error=%s",
                        trace_id,
                        command_id,
                        device_id,
                        result["error_message"],
                    )
                return result

            except asyncio.TimeoutError:
                latency_ms = (time.monotonic() - t0) * 1000
                result = {
                    **trace_base,
                    "success": False,
                    "result": None,
                    "error_code": GatewayErrorCode.COMMAND_TIMEOUT.value,
                    "error_message": f"命令超时（{timeout}s）: {command} @ {device_id}",
                    "latency_ms": round(latency_ms, 1),
                }
                self._stats["total_timeout"] += 1
                _get_gateway_trace_store().record(result)
                logger.warning(
                    "CommandRouter._dispatch_to_device timeout | " "trace_id=%s command_id=%s device=%s",
                    trace_id,
                    command_id,
                    device_id,
                )
                return result

            except (ConnectionError, OSError) as exc:
                latency_ms = (time.monotonic() - t0) * 1000
                result = {
                    **trace_base,
                    "success": False,
                    "result": None,
                    "error_code": GatewayErrorCode.DISCONNECT.value,
                    "error_message": f"设备连接断开: {exc}",
                    "latency_ms": round(latency_ms, 1),
                }
                self._stats["total_failed"] += 1
                _get_gateway_trace_store().record(result)
                logger.warning(
                    "CommandRouter._dispatch_to_device disconnect | " "trace_id=%s command_id=%s device=%s error=%s",
                    trace_id,
                    command_id,
                    device_id,
                    exc,
                )
                return result

            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("Fallback triggered: %s", exc)
                latency_ms = (time.monotonic() - t0) * 1000
                result = {
                    **trace_base,
                    "success": False,
                    "result": None,
                    "error_code": GatewayErrorCode.EXECUTOR_ERROR.value,
                    "error_message": str(exc),
                    "latency_ms": round(latency_ms, 1),
                }
                self._stats["total_failed"] += 1
                _get_gateway_trace_store().record(result)
                logger.error(
                    "CommandRouter._dispatch_to_device executor error | " "trace_id=%s command_id=%s error=%s",
                    trace_id,
                    command_id,
                    exc,
                )
                return result

        # ── Canonical chain: delegate to DeviceRouter (preferred transport path)
        # This implements the CommandRouter → DeviceRouter hop in the canonical
        # execution chain.  DeviceRouter.send_command_to_device() is the terminal
        # transport step that owns the WebSocket session handles.
        # Falls through to connection_manager when DeviceRouter is unavailable.
        _dr_result = await self._dispatch_via_device_router(
            device_id=device_id,
            command=command,
            payload=payload,
            task_id=task_id,
            trace_id=trace_id,
            command_id=command_id,
            timeout=timeout,
        )
        if _dr_result is not None:
            latency_ms = (time.monotonic() - t0) * 1000
            result = {
                **trace_base,
                "success": _dr_result.get("success", False),
                "result": _dr_result.get("result"),
                "error_code": (
                    GatewayErrorCode.DEVICE_OFFLINE.value
                    if not _dr_result.get("success") and "timeout" in str(_dr_result.get("error", ""))
                    else (None if _dr_result.get("success") else GatewayErrorCode.EXECUTOR_ERROR.value)
                ),
                "error_message": _dr_result.get("error"),
                "latency_ms": round(latency_ms, 1),
            }
            _get_gateway_trace_store().record(result)
            return result

        # ── Fallback: use WebSocket connection manager ────────────────
        try:
            from core.routes._shared import connection_manager

            if device_id not in connection_manager.active_devices:
                latency_ms = (time.monotonic() - t0) * 1000
                result = {
                    **trace_base,
                    "success": False,
                    "result": None,
                    "error_code": GatewayErrorCode.DEVICE_OFFLINE.value,
                    "error_message": f"设备 {device_id} 未连接",
                    "latency_ms": round(latency_ms, 1),
                }
                _get_gateway_trace_store().record(result)
                return result

            sent = await connection_manager.send_to_device(
                device_id,
                {
                    "type": "command",
                    "command": command,
                    "payload": payload,
                    "command_id": command_id,
                    "task_id": task_id,
                    "request_id": trace_base.get("request_id", ""),
                },
            )
            latency_ms = (time.monotonic() - t0) * 1000
            result = {
                **trace_base,
                "success": sent,
                "result": f"命令已发送到 {device_id}" if sent else f"发送失败: {device_id}",
                "error_code": None if sent else GatewayErrorCode.DEVICE_OFFLINE.value,
                "error_message": None if sent else f"设备 {device_id} 发送失败",
                "latency_ms": round(latency_ms, 1),
            }
            _get_gateway_trace_store().record(result)
            return result

        except (asyncio.TimeoutError, ConnectionError, OSError) as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            error_code = (
                GatewayErrorCode.COMMAND_TIMEOUT.value
                if isinstance(exc, asyncio.TimeoutError)
                else GatewayErrorCode.DISCONNECT.value
            )
            result = {
                **trace_base,
                "success": False,
                "result": None,
                "error_code": error_code,
                "error_message": str(exc),
                "latency_ms": round(latency_ms, 1),
            }
            _get_gateway_trace_store().record(result)
            return result

        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Fallback triggered: %s", exc)
            latency_ms = (time.monotonic() - t0) * 1000
            result = {
                **trace_base,
                "success": False,
                "result": None,
                "error_code": GatewayErrorCode.INTERNAL_ERROR.value,
                "error_message": str(exc),
                "latency_ms": round(latency_ms, 1),
            }
            _get_gateway_trace_store().record(result)
            return result

    def _pick_retry_device(
        self,
        tried: set,
        candidates: Optional[List[Any]],
        required_capabilities: Optional[List[str]],
    ) -> Optional[str]:
        """Select the best untried, eligible device from *candidates*.

        Returns the ``device_id`` string, or ``None`` if no candidate
        qualifies.
        """
        if not candidates:
            return None
        try:
            from core.control_plane._globals import get_scoring_engine, get_health_registry

            hreg = get_health_registry()
            remaining = [c for c in candidates if c.device_id not in tried and hreg.is_eligible(c.device_id)]
            if not remaining:
                return None
            best = get_scoring_engine().select_best_device(remaining, required_capabilities)
            return best.device_id if best is not None else None
        except Exception as exc:
            # Fallback: just pick first untried candidate
            for c in candidates:
                if c.device_id not in tried:
                    return c.device_id
            return None

    # ------------------------------------------------------------------
    # Remote Agent Dispatch (PR155 + physical-device pre-deploy policy)
    # ------------------------------------------------------------------

    async def _deploy_agent_then_execute(
        self,
        device_id: str,
        device_type: str,
        agent_id: str,
        agent_template: str,
        task: str,
        session_id: str,
        trace_id: str,
        task_id: str,
        context: Optional[Dict[str, Any]] = None,
        timeout: float = 60.0,
    ) -> Dict[str, Any]:
        """Two-step dispatch for physical devices: agent_deploy → agent_execute.

        Step 1 – Build an :class:`~core.agent_manifest.AgentManifest` for the
        target device and send it as an ``agent_deploy`` WebSocket message via
        :mod:`core.routes._shared.connection_manager`.

        Step 2 – On successful send, immediately forward ``agent_execute`` via
        :meth:`route_command` so that the remote agent receives its task.

        Default behaviour:
          * Deployment is considered successful when the WebSocket ``send``
            call returns ``True``.
          * If the device is offline or the send fails the method returns an
            error dict immediately (no queuing).

        Parameters
        ----------
        device_id:
            Target device identifier.
        device_type:
            Resolved device-type string (used for observability only).
        agent_id, agent_template, task, session_id, trace_id, task_id,
        context, timeout:
            Same semantics as :meth:`dispatch_agent_remote`.

        Returns
        -------
        dict
            Same envelope shape as :meth:`dispatch_agent_remote`.
        """
        from core.agent_manifest import AgentManifest
        from core.routes._shared import connection_manager

        logger.info(
            "CommandRouter._deploy_agent_then_execute | " "device_id=%s device_type=%s trace_id=%s task_id=%s",
            device_id,
            device_type,
            trace_id,
            task_id,
        )

        # ── Step 1: agent_deploy ─────────────────────────────────────────
        if device_id not in connection_manager.active_devices:
            logger.warning(
                "agent_predeploy_required but device offline | " "device_id=%s device_type=%s trace_id=%s task_id=%s",
                device_id,
                device_type,
                trace_id,
                task_id,
            )
            return {
                "success": False,
                "agent_id": agent_id,
                "task_id": task_id,
                "trace_id": trace_id,
                "session_id": session_id,
                "device_id": device_id,
                "result": None,
                "error_code": "device_offline",
                "error_message": (f"agent_deploy failed: device {device_id} is not connected"),
                "via": "command_router",
            }

        manifest = AgentManifest.create_device_control_agent(
            target_device=device_id,
            instruction=task,
            source_device="server",
        )

        deploy_message = {
            "type": "agent_deploy",
            "manifest": manifest.to_dict(),
            "checksum": manifest.checksum(),
            "trace_id": trace_id,
            "task_id": task_id,
        }

        deploy_sent = await connection_manager.send_to_device(device_id, deploy_message)

        if not deploy_sent:
            logger.warning(
                "agent_deploy send failed | device_id=%s trace_id=%s task_id=%s",
                device_id,
                trace_id,
                task_id,
            )
            return {
                "success": False,
                "agent_id": agent_id,
                "task_id": task_id,
                "trace_id": trace_id,
                "session_id": session_id,
                "device_id": device_id,
                "result": None,
                "error_code": "deploy_failed",
                "error_message": (f"agent_deploy WebSocket send failed for device {device_id}"),
                "via": "command_router",
            }

        logger.info(
            "agent_deploy sent successfully | manifest_id=%s device_id=%s " "trace_id=%s task_id=%s",
            manifest.manifest_id[:8],
            device_id,
            trace_id,
            task_id,
        )

        # ── Step 2: agent_execute ────────────────────────────────────────
        payload: Dict[str, Any] = {
            "agent_id": agent_id,
            "agent_template": agent_template,
            "task": task,
            "session_id": session_id,
            "trace_id": trace_id,
            "task_id": task_id,
            "manifest_id": manifest.manifest_id,
            "context": context or {},
        }

        # PR-7: route via route_envelope (unified substrate root) with
        # remote_execution_mode=agent_runtime stamped in the envelope so that
        # mode metadata is observable end-to-end without inspecting payload.
        from core.schemas.task_envelope import TaskEnvelope as _TaskEnvelope
        from core.schemas.remote_execution import RemoteExecutionMode as _REM

        _agent_envelope = _TaskEnvelope(
            task_id=task_id,
            trace_id=trace_id or f"trace_{uuid.uuid4().hex[:12]}",
            source="command_router._deploy_agent_then_execute",
            targets=[device_id] if device_id else [],
            tool_name="agent_execute",
            args=payload,
            timeout=timeout,
            remote_execution_mode=_REM.agent_runtime,
            metadata={
                "command_id": task_id,
                "request_id": task_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "substrate_path": "agent_runtime",
            },
        )
        cr_result = await self.route_envelope(_agent_envelope)

        cr_result.setdefault("agent_id", agent_id)
        cr_result.setdefault("session_id", session_id)
        cr_result.setdefault("trace_id", trace_id)
        cr_result.setdefault("task_id", task_id)
        cr_result.setdefault("remote_execution_mode", "agent_runtime")

        logger.info(
            "CommandRouter._deploy_agent_then_execute done | "
            "trace_id=%s task_id=%s agent_id=%s success=%s latency=%.1fms",
            trace_id,
            task_id,
            agent_id,
            cr_result.get("success"),
            cr_result.get("latency_ms", 0.0),
        )
        return cr_result

    async def dispatch_agent_remote(
        self,
        device_id: str,
        agent_id: str,
        agent_template: str,
        task: str,
        session_id: str,
        trace_id: str,
        task_id: str,
        context: Optional[Dict[str, Any]] = None,
        timeout: float = 60.0,
    ) -> Dict[str, Any]:
        """Dispatch an ``agent_execute`` command to a remote device.

        This implements the **Remote Agent Dispatch** contract (PR155).
        The ``agent_execute`` payload is forwarded via :meth:`route_command`
        so that all existing trace/error/backflow machinery is reused.

        **Physical-device pre-deploy policy** (scheme A):
        When the target device is a physical/electronic device
        (ANDROID / IOS / WINDOWS / MACOS / LINUX / IOT / ROBOT / DRONE)
        the method automatically enforces a strict two-step flow:

        1. ``agent_deploy`` — pushes an :class:`~core.agent_manifest.AgentManifest`
           to the device via WebSocket.
        2. ``agent_execute`` — forwards the task once the deploy succeeds.

        Non-physical targets (cloud, browser, …) keep the existing
        direct-dispatch behaviour.

        Parameters
        ----------
        device_id:
            Target device identifier (must be registered/online).
        agent_id:
            Unique ID of the agent being dispatched (preserved in result).
        agent_template:
            Agent role or template name (e.g. ``"analyst"``, ``"executor"``).
        task:
            Natural-language instruction for the remote agent to execute.
        session_id:
            Session identifier — threaded through result for backflow.
        trace_id:
            Request trace ID — preserved end-to-end for observability.
        task_id:
            Task identifier — preserved in result and backflow.
        context:
            Optional extra context dict passed to the remote agent.
        timeout:
            Maximum seconds to wait for a remote result (default 60 s).

        Returns
        -------
        dict
            Standard route_command envelope plus ``agent_id``, ``task_id``,
            ``trace_id``, ``session_id`` so callers can correlate easily::

                {
                    "success": bool,
                    "agent_id": str,
                    "task_id": str,
                    "trace_id": str,
                    "session_id": str,
                    "device_id": str,
                    "result": any,
                    "error_code": str | None,
                    "latency_ms": float,
                    "via": "command_router",
                }
        """
        from core.device_policy import requires_agent_deploy
        from core.unified.device_manager import get_unified_device_manager

        logger.info(
            "CommandRouter.dispatch_agent_remote | trace_id=%s task_id=%s " "agent_id=%s device_id=%s template=%s",
            trace_id,
            task_id,
            agent_id,
            device_id,
            agent_template,
        )

        # ── Physical-device pre-deploy policy ───────────────────────────
        device_type: str = get_unified_device_manager().get_device_type(device_id) or "unknown"
        if requires_agent_deploy(device_type):
            logger.info(
                "agent_predeploy_required | device_id=%s device_type=%s " "trace_id=%s task_id=%s",
                device_id,
                device_type,
                trace_id,
                task_id,
            )
            return await self._deploy_agent_then_execute(
                device_id=device_id,
                device_type=device_type,
                agent_id=agent_id,
                agent_template=agent_template,
                task=task,
                session_id=session_id,
                trace_id=trace_id,
                task_id=task_id,
                context=context,
                timeout=timeout,
            )

        # ── Non-physical: direct agent_execute (original path) ──────────
        payload: Dict[str, Any] = {
            "agent_id": agent_id,
            "agent_template": agent_template,
            "task": task,
            "session_id": session_id,
            "trace_id": trace_id,
            "task_id": task_id,
            "context": context or {},
        }

        # PR-7: route via route_envelope (unified substrate root) with
        # remote_execution_mode=agent_runtime stamped in the envelope so that
        # both command_only and agent_runtime modes traverse the same substrate
        # entry point.  route_command (compat shim) is intentionally bypassed
        # here to avoid the envelope being built without an explicit mode.
        from core.schemas.task_envelope import TaskEnvelope as _TaskEnvelope
        from core.schemas.remote_execution import RemoteExecutionMode as _REM

        _agent_envelope = _TaskEnvelope(
            task_id=task_id,
            trace_id=trace_id or f"trace_{uuid.uuid4().hex[:12]}",
            source="command_router.dispatch_agent_remote",
            targets=[device_id] if device_id else [],
            tool_name="agent_execute",
            args=payload,
            timeout=timeout,
            remote_execution_mode=_REM.agent_runtime,
            metadata={
                "command_id": task_id,
                "request_id": task_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "substrate_path": "agent_runtime",
            },
        )
        cr_result = await self.route_envelope(_agent_envelope)

        # Augment with agent correlation fields for callers that need them.
        cr_result.setdefault("agent_id", agent_id)
        cr_result.setdefault("session_id", session_id)
        cr_result.setdefault("trace_id", trace_id)
        cr_result.setdefault("task_id", task_id)
        cr_result.setdefault("remote_execution_mode", "agent_runtime")

        logger.info(
            "CommandRouter.dispatch_agent_remote done | trace_id=%s task_id=%s "
            "agent_id=%s success=%s latency=%.1fms",
            trace_id,
            task_id,
            agent_id,
            cr_result.get("success"),
            cr_result.get("latency_ms", 0.0),
        )
        return cr_result

    # ------------------------------------------------------------------
    # 内部调度
    # ------------------------------------------------------------------

    async def _execute_all(self, request: CommandRequest, cmd_result: CommandResult, start: float):
        """后台执行所有目标（用于 ASYNC 模式）"""
        try:
            if request.mode in (CommandMode.ASYNC, CommandMode.PARALLEL):
                await self._execute_parallel(request, cmd_result)
            else:
                await self._execute_serial(request, cmd_result)
            self._finalize_result(cmd_result, start)
            await self._notify(cmd_result)
        except asyncio.CancelledError:
            cmd_result.status = CommandStatus.CANCELLED
            cmd_result.completed_at = time.time()
            await self._notify(cmd_result)
        except Exception as e:
            logger.error(f"Background execution failed: {e}")
            cmd_result.status = CommandStatus.FAILED
            cmd_result.completed_at = time.time()
            cmd_result.metadata["error"] = str(e)
            await self._notify(cmd_result)
        finally:
            self._pending_futures.pop(request.request_id, None)

    async def _execute_parallel(self, request: CommandRequest, cmd_result: CommandResult):
        """并行执行所有目标"""
        cmd_result.status = CommandStatus.RUNNING

        tasks = []
        for target in request.targets:
            task = asyncio.create_task(
                self._execute_single_with_retry(
                    target,
                    request.command,
                    request.params,
                    request.timeout,
                    request.max_retries,
                    cmd_result.targets[target],
                )
            )
            tasks.append(task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_serial(self, request: CommandRequest, cmd_result: CommandResult):
        """串行执行所有目标"""
        cmd_result.status = CommandStatus.RUNNING

        for target in request.targets:
            await self._execute_single_with_retry(
                target,
                request.command,
                request.params,
                request.timeout,
                request.max_retries,
                cmd_result.targets[target],
            )
            # 串行模式下：如果某目标失败且不是最后一个，继续执行
            # （可配置为"遇到失败即停止"）

    async def _execute_single_with_retry(
        self,
        target: str,
        command: str,
        params: dict,
        timeout: float,
        max_retries: int,
        target_result: TargetResult,
    ):
        """执行单个目标，带超时和重试（PR-G5: 集成熔断器和自适应并发）"""
        if not self._executor:
            target_result.status = CommandStatus.FAILED
            target_result.error = "No executor configured"
            return

        target_result.started_at = time.time()
        last_error = None
        cb = self._get_circuit_breaker(target)

        # ── PR-G5: circuit-breaker fast-path ────────────────────────────
        if cb is not None and cb.is_open:
            if cb.has_fallback:
                try:
                    fallback_result = await cb._fallback(target, command, params)
                    target_result.status = CommandStatus.SUCCESS
                    target_result.result = fallback_result
                    target_result.completed_at = time.time()
                    target_result.latency_ms = (target_result.completed_at - target_result.started_at) * 1000
                    self._stats["total_fallbacks"] += 1
                    if self._resilience_metrics is not None:
                        try:
                            self._resilience_metrics.record_fallback()
                        except Exception as exc:
                            logger.warning("Exception suppressed: %s", exc)
                    return
                except Exception as e:
                    logger.debug("Fallback triggered: %s", e)
                    last_error = f"Fallback failed: {e}"
            else:
                from core.resilience.circuit_breaker import CircuitOpenError

                target_result.status = CommandStatus.FAILED
                target_result.error = str(CircuitOpenError(target, cb.opened_at))
                target_result.completed_at = time.time()
                target_result.latency_ms = (target_result.completed_at - target_result.started_at) * 1000
                self._stats["total_failed"] += 1
                return

        for attempt in range(max_retries + 1):
            target_result.retries = attempt
            call_start = time.monotonic()
            call_error = False
            try:
                # ── PR-G5: use adaptive semaphore when available ─────────
                sem_ctx = self._adaptive_sem if self._adaptive_sem is not None else self._semaphore
                executor_coro = self._executor(target, command, params)
                async with sem_ctx:
                    if cb is not None:
                        # Wrap execution in the circuit breaker guard;
                        # asyncio.wait_for enforces per-call timeout inside the guard.
                        async def _guarded_call(_coro=executor_coro, _t=timeout):
                            return await asyncio.wait_for(_coro, timeout=_t)

                        result = await cb.call(_guarded_call)
                    else:
                        result = await asyncio.wait_for(
                            executor_coro,
                            timeout=timeout,
                        )

                elapsed_ms = (time.monotonic() - call_start) * 1000
                if self._adaptive_sem is not None:
                    try:
                        await self._adaptive_sem.record(elapsed_ms, error=False)
                    except Exception as exc:
                        logger.warning("Exception suppressed: %s", exc)

                target_result.status = CommandStatus.SUCCESS
                target_result.result = result
                target_result.completed_at = time.time()
                target_result.latency_ms = (target_result.completed_at - target_result.started_at) * 1000
                return

            except asyncio.TimeoutError:
                call_error = True
                last_error = f"Timeout after {timeout}s"
                logger.warning(f"Command timeout: {target}/{command} (attempt {attempt + 1})")
                elapsed_ms = (time.monotonic() - call_start) * 1000
                if self._adaptive_sem is not None:
                    try:
                        await self._adaptive_sem.record(elapsed_ms, error=True)
                    except Exception as exc:
                        logger.warning("Exception suppressed: %s", exc)
                if attempt < max_retries:
                    # 指数退避
                    await asyncio.sleep(min(2**attempt * 0.5, 5.0))

            except asyncio.CancelledError:
                target_result.status = CommandStatus.CANCELLED
                target_result.completed_at = time.time()
                target_result.latency_ms = (target_result.completed_at - target_result.started_at) * 1000
                raise

            except Exception as e:
                logger.debug("Fallback triggered: %s", e)
                call_error = True
                last_error = str(e)
                logger.warning(f"Command error: {target}/{command}: {e} (attempt {attempt + 1})")
                elapsed_ms = (time.monotonic() - call_start) * 1000
                if self._adaptive_sem is not None:
                    try:
                        await self._adaptive_sem.record(elapsed_ms, error=True)
                    except Exception as exc:
                        logger.warning("Exception suppressed: %s", exc)
                if attempt < max_retries:
                    await asyncio.sleep(min(2**attempt * 0.5, 5.0))

        # 所有重试耗尽
        target_result.status = CommandStatus.TIMEOUT if "Timeout" in (last_error or "") else CommandStatus.FAILED
        target_result.error = last_error
        target_result.completed_at = time.time()
        target_result.latency_ms = (target_result.completed_at - target_result.started_at) * 1000

        if "Timeout" in (last_error or ""):
            self._stats["total_timeout"] += 1
        else:
            self._stats["total_failed"] += 1

    def _finalize_result(self, cmd_result: CommandResult, start: float):
        """聚合最终状态"""
        statuses = {r.status for r in cmd_result.targets.values()}

        if all(s == CommandStatus.SUCCESS for s in statuses):
            cmd_result.status = CommandStatus.SUCCESS
            self._stats["total_success"] += 1
        elif any(s == CommandStatus.SUCCESS for s in statuses):
            cmd_result.status = CommandStatus.PARTIAL
        elif any(s == CommandStatus.TIMEOUT for s in statuses):
            cmd_result.status = CommandStatus.TIMEOUT
        else:
            cmd_result.status = CommandStatus.FAILED
            self._stats["total_failed"] += 1

        cmd_result.completed_at = time.time()
        cmd_result.total_latency_ms = (cmd_result.completed_at - start) * 1000

        # 更新平均延迟
        self._latencies.append(cmd_result.total_latency_ms)
        if len(self._latencies) > 1000:
            self._latencies = self._latencies[-500:]
        self._stats["avg_latency_ms"] = sum(self._latencies) / len(self._latencies)

    # ------------------------------------------------------------------
    # 通知 / 缓存
    # ------------------------------------------------------------------

    async def _notify(self, cmd_result: CommandResult):
        """通知状态变更"""
        if self._on_status_change:
            try:
                if asyncio.iscoroutinefunction(self._on_status_change):
                    await self._on_status_change(cmd_result)
                else:
                    self._on_status_change(cmd_result)
            except Exception as e:
                logger.error(f"Status change notification failed: {e}")

    async def _cache_get(self, key: str):
        """从缓存读取"""
        try:
            raw = await self._cache.get(key)
            if raw is not None:
                return json.loads(raw)
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
        return None

    async def _cache_set(self, key: str, value: Any, ttl: int = 60):
        """写入缓存"""
        try:
            await self._cache.set(key, json.dumps(value, default=str), ttl)
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    async def cleanup(self, max_age_seconds: int = 3600):
        """清理过期的命令结果"""
        now = time.time()
        expired = [
            rid for rid, r in self._results.items() if r.completed_at and (now - r.completed_at) > max_age_seconds
        ]
        for rid in expired:
            del self._results[rid]
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired command results")


# ============================================================================
# 全局命令路由实例
# ============================================================================

_command_router: Optional[CommandRouter] = None


def get_command_router(**kwargs) -> CommandRouter:
    """
    获取全局命令路由实例

    首次调用创建实例，后续调用返回已有实例。
    如果实例已存在但传入了 on_status_change / executor / cache_backend，
    则动态更新这些属性（避免单例初始化顺序问题）。
    """
    global _command_router
    if _command_router is None:
        _command_router = CommandRouter(**kwargs)
    else:
        # 动态更新可变属性
        if "on_status_change" in kwargs and kwargs["on_status_change"] is not None:
            _command_router._on_status_change = kwargs["on_status_change"]
        if "executor" in kwargs and kwargs["executor"] is not None:
            _command_router._executor = kwargs["executor"]
        if "cache_backend" in kwargs and kwargs["cache_backend"] is not None:
            _command_router._cache = kwargs["cache_backend"]
    return _command_router


# ============================================================================
# NATS Executor (Phase D)
# ============================================================================


class NATSExecutor:
    """Wraps commands as NATS TaskDispatch messages and resolves results.

    - Publishes ``TaskDispatch`` to ``galaxy.tasks.dispatch.{worker_id}`` via
      :class:`~core.nats_bus.NATSBus`.
    - Subscribes to ``galaxy.tasks.result.*`` to fulfil pending futures.
    - Falls back to *fallback_executor* when NATS is not connected and
      *fallback_enabled* is True (default True).

    Usage::

        nats_exec = NATSExecutor(fallback_executor=existing_local_executor)
        await nats_exec.start()                 # subscribe to results
        command_router.set_executor(nats_exec)  # register as executor

    Env vars:
        GALAXY_NATS_EXECUTOR_FALLBACK  — "true"/"false" (default "true")
        GALAXY_NATS_EXECUTOR_TIMEOUT   — per-task NATS timeout in seconds (default 30)
    """

    def __init__(
        self,
        fallback_executor: Optional[Callable[..., Coroutine]] = None,
        fallback_enabled: Optional[bool] = None,
        timeout_s: float = float(os.environ.get("GALAXY_NATS_EXECUTOR_TIMEOUT", "30")),
    ) -> None:
        self._fallback = fallback_executor
        if fallback_enabled is None:
            self._fallback_enabled = os.environ.get("GALAXY_NATS_EXECUTOR_FALLBACK", "true").lower() not in (
                "false",
                "0",
            )
        else:
            self._fallback_enabled = fallback_enabled
        self._timeout_s = timeout_s

        # task_id → asyncio.Future for pending NATS dispatches
        self._pending: Dict[str, asyncio.Future] = {}
        self._started = False
        self._stats = {
            "nats_dispatched": 0,
            "nats_resolved": 0,
            "nats_timeout": 0,
            "fallback_used": 0,
        }

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Subscribe to galaxy.tasks.result.* to receive task results."""
        if self._started:
            return
        try:
            from core.nats_bus import nats_bus

            if not nats_bus.is_connected():
                logger.debug("NATSExecutor: NATS not connected, skipping result subscription")
                return

            await nats_bus.subscribe_task_results(self._on_task_result)
            self._started = True
            logger.info("NATSExecutor: subscribed to galaxy.tasks.result.*")
        except Exception as exc:
            logger.warning("NATSExecutor.start error: %s", exc)

    async def stop(self) -> None:
        """Cancel all pending result futures."""
        self._started = False
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    # ── Executor interface ───────────────────────────────────────────────────

    async def __call__(
        self,
        target: str,
        command: str,
        params: dict,
    ) -> dict:
        """Execute *command* on *target* via NATS TaskDispatch.

        Signature matches the ``CommandRouter`` executor protocol:
        ``async (target: str, command: str, params: dict) -> dict``
        """
        try:
            from core.nats_bus import nats_bus

            if not nats_bus.is_connected():
                return await self._use_fallback(target, command, params, reason="nats_not_connected")

            return await self._dispatch_via_nats(target, command, params)
        except Exception as exc:
            logger.error("NATSExecutor: unexpected error — %s", exc)
            return await self._use_fallback(target, command, params, reason=str(exc))

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _dispatch_via_nats(self, target: str, command: str, params: dict) -> dict:
        from core.nats_bus import nats_bus
        from core.schemas.contracts import (
            TaskDispatchModel,
            TaskType,
            DeviceCommandPayloadModel,
            TimestampModel,
        )
        from datetime import datetime, timezone

        # PR-2: extract envelope identifiers injected by _dispatch_to_device
        # (keys prefixed with "_galaxy_" are internal metadata, not device params).
        params = dict(params)
        galaxy_task_id: Optional[str] = params.pop("_galaxy_task_id", None)
        galaxy_trace_id: Optional[str] = params.pop("_galaxy_trace_id", None)

        task_id = galaxy_task_id or str(uuid.uuid4())
        trace_id = galaxy_trace_id or f"trace_{uuid.uuid4().hex[:12]}"
        ts = TimestampModel(seconds=int(datetime.now(timezone.utc).timestamp()))
        device_payload = DeviceCommandPayloadModel(
            command=command,
            params={k: str(v) for k, v in params.items() if isinstance(v, (str, int, float, bool))},
            target_device_id=target,
        )
        task = TaskDispatchModel(
            task_id=task_id,
            task_type=TaskType.DEVICE_CMD,
            target_worker_id=target,
            device_payload=device_payload,
            created_at=ts,
            # PR-2: propagate TaskEnvelope trace_id into NATS context for
            # cross-component correlation.
            context={"trace_id": trace_id} if trace_id else {},
        )

        # Register future before publish to avoid race condition
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[task_id] = fut

        try:
            # PR-3: Publish as TaskEnvelope (primary NATS transport format).
            # Falls back to legacy TaskDispatch publish on any error so that
            # backward-compatible consumers still receive the message.
            pub_result: dict = {"success": False}
            try:
                from core.schemas.task_envelope import TaskEnvelope as _TaskEnvelope

                _envelope = _TaskEnvelope(
                    task_id=task_id,
                    trace_id=trace_id,
                    source="command_router",
                    targets=[target],
                    tool_name=command,
                    args=params,
                    timeout=self._timeout_s,
                )
                pub_result = await nats_bus.publish_task_envelope(target, _envelope)
                if not pub_result.get("success"):
                    raise RuntimeError(f"envelope publish returned failure: {pub_result.get('error', 'unknown')}")
            except Exception as _env_err:
                logger.debug(
                    "NATSExecutor: TaskEnvelope publish failed (%s), falling back to TaskDispatch",
                    _env_err,
                )
                pub_result = await nats_bus.publish_task_dispatch(target, task)

            if pub_result.get("noop"):
                return await self._use_fallback(
                    target,
                    command,
                    params,
                    reason="nats_noop_transport",
                    publish_state=pub_result,
                )

            if not pub_result.get("success"):
                return await self._use_fallback(target, command, params, reason="publish_failed")

            self._stats["nats_dispatched"] += 1

            try:
                result = await asyncio.wait_for(asyncio.shield(fut), timeout=self._timeout_s)
                self._stats["nats_resolved"] += 1
                if isinstance(result, dict):
                    self._apply_execution_markers(
                        result,
                        distributed_dispatch=True,
                        execution_path="nats_distributed",
                        fallback_used=False,
                    )
                return result
            except asyncio.TimeoutError:
                self._stats["nats_timeout"] += 1
                logger.warning(
                    "NATSExecutor: task %s timed out after %.1fs, falling back",
                    task_id,
                    self._timeout_s,
                )
                return await self._use_fallback(target, command, params, reason="nats_timeout")
        finally:
            self._pending.pop(task_id, None)

    async def _on_task_result(self, data: dict) -> None:
        """Handle an incoming task result from NATS.

        PR-3: Accepts both TaskEnvelope-shaped results (``_nats_schema ==
        "TaskEnvelope"``) and legacy TaskResult dicts.  For TaskEnvelope
        results the execution status and output are read from
        ``metadata.success`` / ``metadata.result`` / ``metadata.error``; for
        legacy results the existing ``status`` field is used.
        """
        nats_schema = data.get("_nats_schema", "")
        if nats_schema == "TaskEnvelope":
            # TaskEnvelope result: status carried in metadata
            task_id = data.get("task_id", "")
            meta = data.get("metadata") or {}
            success = bool(meta.get("success", True))
            result_data = meta.get("result")
            error = meta.get("error")
        else:
            # Legacy TaskResult format
            task_id = data.get("task_id", "")
            status = data.get("status", "")
            success = status in ("completed", "success")
            result_data = data.get("result")
            error = data.get("error")

        fut = self._pending.get(task_id)
        if fut and not fut.done():
            result = {
                "success": success,
                "result": result_data,
                "error": error,
                "task_id": task_id,
            }
            self._apply_execution_markers(
                result,
                distributed_dispatch=True,
                execution_path="nats_distributed",
                fallback_used=False,
            )
            fut.set_result(result)

    @staticmethod
    def _apply_execution_markers(
        payload: dict,
        *,
        distributed_dispatch: bool,
        execution_path: str,
        fallback_used: bool,
        fallback_reason: str = "",
    ) -> dict:
        payload.setdefault("distributed_dispatch", distributed_dispatch)
        payload.setdefault("execution_path", execution_path)
        payload.setdefault("fallback_used", fallback_used)
        if fallback_reason:
            payload.setdefault("fallback_reason", fallback_reason)
        return payload

    async def _use_fallback(
        self,
        target: str,
        command: str,
        params: dict,
        reason: str,
        publish_state: Optional[dict] = None,
    ) -> dict:
        if self._fallback and self._fallback_enabled:
            self._stats["fallback_used"] += 1
            logger.warning(
                "NATSExecutor: NATS unavailable for target=%s command=%s, using local fallback (reason=%s)",
                target,
                command,
                reason,
            )
            fallback_result = await self._fallback(target, command, params)
            if isinstance(fallback_result, dict):
                out = dict(fallback_result)
            else:
                fallback_success = (
                    fallback_result if isinstance(fallback_result, bool) else (fallback_result is not None)
                )
                out = {"success": fallback_success, "result": fallback_result}
            self._apply_execution_markers(
                out,
                distributed_dispatch=False,
                execution_path="local_fallback",
                fallback_used=True,
                fallback_reason=reason,
            )
            if publish_state is not None and "nats_publish_state" not in out:
                out["nats_publish_state"] = publish_state
            return out
        out = {
            "success": False,
            "error": f"nats_executor_no_result:{reason}",
            "target": target,
            "command": command,
        }
        self._apply_execution_markers(
            out,
            distributed_dispatch=False,
            execution_path="distributed_unavailable",
            fallback_used=False,
            fallback_reason=reason,
        )
        if publish_state is not None:
            out["nats_publish_state"] = publish_state
        return out

    def get_stats(self) -> dict:
        return {**self._stats, "pending": len(self._pending), "started": self._started}


_nats_executor: Optional[NATSExecutor] = None


def get_nats_executor(
    fallback_executor: Optional[Callable[..., Coroutine]] = None,
) -> NATSExecutor:
    """Return (or create) the module-level :class:`NATSExecutor` singleton."""
    global _nats_executor
    if _nats_executor is None:
        _nats_executor = NATSExecutor(fallback_executor=fallback_executor)
    elif fallback_executor is not None and _nats_executor._fallback is None:
        _nats_executor._fallback = fallback_executor
    return _nats_executor


# ============================================================================
# 网关 Trace 存储（PR-C 可观测性）
# ============================================================================


class GatewayTraceStore:
    """
    轻量级内存 trace 存储。

    - 保存最近 _MAX_ENTRIES 条 route_command 调用记录
    - 支持按 task_id 或 command_id 快速查询
    - stats() 使用 O(1) 计数器，避免全表扫描
    - 线程安全（asyncio 单线程模型，无需额外锁）
    """

    _MAX_ENTRIES = 1000

    def __init__(self) -> None:
        # 顺序列表（最旧在前），同时维护两个索引
        self._entries: List[Dict[str, Any]] = []
        self._by_command_id: Dict[str, Dict[str, Any]] = {}
        self._by_task_id: Dict[str, List[Dict[str, Any]]] = {}
        # O(1) counters
        self._total_recorded: int = 0
        self._total_failed: int = 0

    def record(self, trace: Dict[str, Any]) -> None:
        """记录一条 trace 条目"""
        entry = {**trace, "recorded_at": datetime.now(timezone.utc).isoformat()}
        self._entries.append(entry)
        self._total_recorded += 1
        if not trace.get("success"):
            self._total_failed += 1

        # 超出上限时，淘汰最旧的条目
        if len(self._entries) > self._MAX_ENTRIES:
            oldest = self._entries.pop(0)
            self._by_command_id.pop(oldest.get("command_id", ""), None)
            old_tid = oldest.get("task_id", "")
            if old_tid and old_tid in self._by_task_id:
                lst = self._by_task_id[old_tid]
                if oldest in lst:
                    lst.remove(oldest)
                if not lst:
                    del self._by_task_id[old_tid]

        cmd_id = entry.get("command_id", "")
        if cmd_id:
            self._by_command_id[cmd_id] = entry

        task_id = entry.get("task_id", "")
        if task_id:
            self._by_task_id.setdefault(task_id, []).append(entry)

    def lookup_by_command_id(self, command_id: str) -> Optional[Dict[str, Any]]:
        """按 command_id 查询 trace"""
        return self._by_command_id.get(command_id)

    def lookup_by_task_id(self, task_id: str) -> List[Dict[str, Any]]:
        """按 task_id 查询 trace 列表"""
        return list(self._by_task_id.get(task_id, []))

    def recent(self, n: int = 50) -> List[Dict[str, Any]]:
        """返回最近 n 条 trace（最新在前）"""
        return list(reversed(self._entries[-n:]))

    def stats(self) -> Dict[str, Any]:
        """返回 trace 存储统计（O(1) 计数器）"""
        return {
            "total_recorded": self._total_recorded,
            "total_failed": self._total_failed,
            "total_success": self._total_recorded - self._total_failed,
            "unique_command_ids": len(self._by_command_id),
            "unique_task_ids": len(self._by_task_id),
        }


_gateway_trace_store: Optional[GatewayTraceStore] = None


def _get_gateway_trace_store() -> GatewayTraceStore:
    """获取全局 GatewayTraceStore 单例"""
    global _gateway_trace_store
    if _gateway_trace_store is None:
        _gateway_trace_store = GatewayTraceStore()
    return _gateway_trace_store


def get_gateway_trace_store() -> GatewayTraceStore:
    """公开接口：获取全局 GatewayTraceStore 单例"""
    return _get_gateway_trace_store()
