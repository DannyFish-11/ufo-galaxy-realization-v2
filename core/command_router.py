"""
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
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from core.schemas.task_envelope import TaskEnvelope

logger = logging.getLogger("Galaxy.CommandRouter")

# ── PR-G5: resilience defaults from env vars (safe, backward-compatible) ────
_DEFAULT_MAX_QUEUE_DEPTH: int = int(os.environ.get("GALAXY_ROUTER_MAX_QUEUE_DEPTH", "200"))
_DEFAULT_CB_ENABLED: bool = os.environ.get("GALAXY_ROUTER_CB_ENABLED", "true").lower() not in ("false", "0")
_DEFAULT_ADAPTIVE_CONCURRENCY: bool = os.environ.get(
    "GALAXY_ROUTER_ADAPTIVE_CONCURRENCY", "true"
).lower() not in ("false", "0")


# ============================================================================
# 错误代码 — 结构化、可解释的网关错误（PR-C）
# ============================================================================

class GatewayErrorCode(str, Enum):
    """网关层可解释错误代码"""
    INVALID_ENVELOPE = "INVALID_ENVELOPE"      # 消息体缺少必要字段
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"      # 设备未注册
    DEVICE_OFFLINE = "DEVICE_OFFLINE"          # 设备已注册但当前离线
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"        # 命令执行超时
    DISCONNECT = "DISCONNECT"                  # 连接断开
    EXECUTOR_ERROR = "EXECUTOR_ERROR"          # 执行器内部错误
    INTERNAL_ERROR = "INTERNAL_ERROR"          # 未分类内部错误
    HITL_TIMEOUT = "HITL_TIMEOUT"              # HITL approval window elapsed
    HITL_DENIED = "HITL_DENIED"               # HITL approval denied by operator


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

class CommandMode(str, Enum):
    """命令执行模式"""
    SYNC = "sync"          # 同步：等待结果返回
    ASYNC = "async"        # 异步：立即返回 request_id
    PARALLEL = "parallel"  # 并行：多目标同时执行
    SERIAL = "serial"      # 串行：多目标顺序执行


class CommandStatus(str, Enum):
    """命令状态"""
    PENDING = "pending"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"      # 部分成功
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class CommandRequest:
    """命令请求"""
    request_id: str = field(default_factory=lambda: f"cmd_{uuid.uuid4().hex[:12]}")
    source: str = ""                  # 来源: api / ws / scheduler / ai
    targets: List[str] = field(default_factory=list)   # 目标节点 / 设备
    command: str = ""                 # 命令名称
    params: Dict[str, Any] = field(default_factory=dict)
    mode: CommandMode = CommandMode.SYNC
    timeout: float = 30.0             # 超时秒数
    max_retries: int = 2              # 最大重试次数
    notify_ws: bool = True            # 是否通过 WebSocket 推送结果
    priority: int = 5                 # 优先级 1-10（1=最高）
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
            "completed_at": (
                datetime.fromtimestamp(self.completed_at).isoformat()
                if self.completed_at else None
            ),
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
    _HIGH_RISK_COMMANDS: frozenset = frozenset({
        "delete", "format", "shutdown", "reboot", "wipe",
        "rm", "remove", "purge", "factory_reset",
        "execute_shell", "run_script", "sudo",
        "transfer_funds", "payment", "checkout",
        "drone_takeoff", "arm_system",
        "system_change", "registry_write",
    })

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
            except Exception:
                self._adaptive_sem = None
        else:
            self._adaptive_sem = None

        # Resilience metrics singleton
        try:
            from core.resilience.metrics import get_resilience_metrics
            self._resilience_metrics: Optional[Any] = get_resilience_metrics()
        except Exception:
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
        except Exception:
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
            except Exception:
                return None
        return self._circuit_breakers.get(target)

    def _count_active_requests(self) -> int:
        """Number of requests currently in PENDING / DISPATCHING / RUNNING state."""
        return sum(
            1 for r in self._results.values()
            if r.status in (
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
            metadata={**request.metadata, "throttled": True,
                      "error": "Queue depth limit exceeded; request rejected"},
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
            except Exception:
                pass

        cb_states = {}
        for tgt, cb in self._circuit_breakers.items():
            try:
                cb_states[tgt] = cb.snapshot()
            except Exception:
                pass

        adaptive = {}
        if self._adaptive_sem is not None:
            try:
                adaptive = self._adaptive_sem.snapshot()
            except Exception:
                pass

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
                priority=request.priority if hasattr(request, "priority") and request.priority is not None else _DEFAULT_PRIORITY,
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

        self._stats["total_dispatched"] += 1
        start = time.time()

        # ── PR-G5: admission control ──────────────────────────────────────
        active = self._count_active_requests()
        if self._resilience_metrics is not None:
            try:
                self._resilience_metrics.set_queue_depth(active)
            except Exception:
                pass

        if active >= self._max_queue_depth:
            self._stats["total_rejected"] += 1
            if self._resilience_metrics is not None:
                try:
                    self._resilience_metrics.record_rejected()
                except Exception:
                    pass
            logger.warning(
                "CommandRouter.dispatch: queue depth %d >= limit %d; rejecting %s",
                active, self._max_queue_depth, request.request_id,
            )
            rejected_result = self._make_throttled_result(request)
            self._results[request.request_id] = rejected_result
            return rejected_result

        if self._resilience_metrics is not None:
            try:
                self._resilience_metrics.record_accepted()
            except Exception:
                pass

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
            task = asyncio.create_task(
                self._execute_all(request, cmd_result, start)
            )
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
        if (
            self._cache
            and cmd_result.status == CommandStatus.SUCCESS
            and len(request.targets) == 1
        ):
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
        cb_summary = {
            tgt: cb.state.value
            for tgt, cb in self._circuit_breakers.items()
        }
        if cb_summary:
            base["circuit_breaker_states"] = cb_summary
        return base

    def set_executor(self, executor: Callable[..., Coroutine]):
        """设置/更新执行器"""
        self._executor = executor

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
        """
        if not envelope.targets:
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

        # Extract optional routing params stored in metadata by the compat layer.
        meta = envelope.metadata or {}
        command_id: str = str(meta.get("command_id") or envelope.task_id)
        request_id: str = str(meta.get("request_id") or envelope.task_id)
        retry_candidates: Optional[List[Any]] = meta.get("retry_candidates")  # type: ignore[assignment]
        required_capabilities: Optional[List[str]] = meta.get("required_capabilities")  # type: ignore[assignment]
        try:
            max_retries: int = int(meta.get("max_retries", 2))
        except (TypeError, ValueError):
            max_retries = 2

        return await self._execute_command(
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
            "CommandRouter._execute_command | trace_id=%s task_id=%s command_id=%s "
            "device_id=%s command=%s",
            trace_id, task_id, command_id, device_id, command,
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
        except Exception:
            pass

        # ── Phase 2: HITL gate for high-risk commands ────────────────────────
        if self._is_high_risk_command(command):
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
                    command, hitl_exc,
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
                trace_id, command_id, exc.message,
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
            except Exception:
                pass

            if not _cb_eligible:
                # Device circuit is OPEN or quarantined – skip to next candidate
                tried_devices.add(current_device)
                next_dev = self._pick_retry_device(
                    tried_devices, retry_candidates, required_capabilities
                )
                if next_dev is not None and attempt < max_retries:
                    try:
                        from core.control_plane.audit_ledger import EventType as _EvCB
                        self._emit_audit(
                            _EvCB.TASK_RETRY_SCHEDULED,
                            trace_id=trace_id, task_id=task_id,
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
                    except Exception:
                        pass
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
            result = await self._dispatch_to_device(
                current_device, command, payload, command_id, task_id,
                timeout, attempt_trace, trace_id, t0,
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
            except Exception:
                pass

            if result["success"]:
                if attempt > 0:
                    # Emit TASK_RETRY_SUCCEEDED
                    try:
                        from core.control_plane.audit_ledger import EventType as _EvR
                        self._emit_audit(
                            _EvR.TASK_RETRY_SUCCEEDED,
                            trace_id=trace_id, task_id=task_id, device_id=current_device,
                            message=(
                                f"Retry #{attempt} succeeded on device '{current_device}'"
                            ),
                            payload={"attempt": attempt, "original_device": device_id},
                        )
                    except Exception:
                        pass
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
                            trace_id=trace_id, task_id=task_id, device_id=current_device,
                            message=f"All retries exhausted after {attempt} attempt(s)",
                            payload={
                                "attempt": attempt,
                                "error_code": result.get("error_code"),
                                "original_device": device_id,
                            },
                        )
                    except Exception:
                        pass
                return result

            # ── Pick next candidate and schedule retry ───────────────────
            tried_devices.add(current_device)
            next_dev = self._pick_retry_device(
                tried_devices, retry_candidates, required_capabilities
            )
            if next_dev is None:
                try:
                    from core.control_plane.audit_ledger import EventType as _EvRE
                    self._emit_audit(
                        _EvRE.TASK_RETRY_FAILED,
                        trace_id=trace_id, task_id=task_id, device_id=current_device,
                        message="No eligible retry candidate available",
                        payload={"attempt": attempt, "original_device": device_id},
                    )
                except Exception:
                    pass
                return result

            try:
                from core.control_plane.audit_ledger import EventType as _EvRS
                self._emit_audit(
                    _EvRS.TASK_RETRY_SCHEDULED,
                    trace_id=trace_id, task_id=task_id, device_id=next_dev,
                    message=(
                        f"Retry #{attempt + 1}: rerouting from '{current_device}' "
                        f"to '{next_dev}'"
                    ),
                    payload={
                        "attempt": attempt + 1,
                        "failed_device": current_device,
                        "error_code": result.get("error_code"),
                        "original_device": device_id,
                    },
                )
            except Exception:
                pass

            current_device = next_dev
            attempt += 1

    # ------------------------------------------------------------------
    # Phase 5: inner dispatch helper + retry device picker
    # ------------------------------------------------------------------

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
                result = {
                    **trace_base,
                    "success": True,
                    "result": raw_result,
                    "error_code": None,
                    "error_message": None,
                    "latency_ms": round(latency_ms, 1),
                }
                _get_gateway_trace_store().record(result)
                logger.info(
                    "CommandRouter._dispatch_to_device done | "
                    "trace_id=%s command_id=%s device=%s latency=%.1fms",
                    trace_id, command_id, device_id, latency_ms,
                )
                try:
                    from core.control_plane.audit_ledger import EventType as _EvC
                    self._emit_audit(
                        _EvC.TASK_COMPLETED,
                        trace_id=trace_id, task_id=task_id, device_id=device_id,
                        message=f"Command '{command}' completed on '{device_id}'",
                        payload={"latency_ms": round(latency_ms, 1)},
                    )
                except Exception:
                    pass
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
                    "CommandRouter._dispatch_to_device timeout | "
                    "trace_id=%s command_id=%s device=%s",
                    trace_id, command_id, device_id,
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
                    "CommandRouter._dispatch_to_device disconnect | "
                    "trace_id=%s command_id=%s device=%s error=%s",
                    trace_id, command_id, device_id, exc,
                )
                return result

            except Exception as exc:  # pylint: disable=broad-except
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
                    "CommandRouter._dispatch_to_device executor error | "
                    "trace_id=%s command_id=%s error=%s",
                    trace_id, command_id, exc,
                )
                return result

        # ── No executor: use WebSocket connection manager ────────────────
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
            remaining = [
                c for c in candidates
                if c.device_id not in tried and hreg.is_eligible(c.device_id)
            ]
            if not remaining:
                return None
            best = get_scoring_engine().select_best_device(remaining, required_capabilities)
            return best.device_id if best is not None else None
        except Exception:
            # Fallback: just pick first untried candidate
            for c in candidates:
                if c.device_id not in tried:
                    return c.device_id
            return None

    # ------------------------------------------------------------------
    # Remote Agent Dispatch (PR155)
    # ------------------------------------------------------------------

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
        logger.info(
            "CommandRouter.dispatch_agent_remote | trace_id=%s task_id=%s "
            "agent_id=%s device_id=%s template=%s",
            trace_id, task_id, agent_id, device_id, agent_template,
        )

        payload: Dict[str, Any] = {
            "agent_id": agent_id,
            "agent_template": agent_template,
            "task": task,
            "session_id": session_id,
            "trace_id": trace_id,
            "task_id": task_id,
            "context": context or {},
        }

        cr_result = await self.route_command(
            device_id=device_id,
            command="agent_execute",
            payload=payload,
            command_id=task_id,
            task_id=task_id,
            timeout=timeout,
            trace_id=trace_id,
        )

        # Augment the standard route_command response with agent correlation fields
        cr_result.setdefault("agent_id", agent_id)
        cr_result.setdefault("session_id", session_id)
        cr_result.setdefault("trace_id", trace_id)
        cr_result.setdefault("task_id", task_id)

        logger.info(
            "CommandRouter.dispatch_agent_remote done | trace_id=%s task_id=%s "
            "agent_id=%s success=%s latency=%.1fms",
            trace_id, task_id, agent_id,
            cr_result.get("success"), cr_result.get("latency_ms", 0.0),
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
                    target, request.command, request.params,
                    request.timeout, request.max_retries,
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
                target, request.command, request.params,
                request.timeout, request.max_retries,
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
                    target_result.latency_ms = (
                        (target_result.completed_at - target_result.started_at) * 1000
                    )
                    self._stats["total_fallbacks"] += 1
                    if self._resilience_metrics is not None:
                        try:
                            self._resilience_metrics.record_fallback()
                        except Exception:
                            pass
                    return
                except Exception as e:
                    last_error = f"Fallback failed: {e}"
            else:
                from core.resilience.circuit_breaker import CircuitOpenError
                target_result.status = CommandStatus.FAILED
                target_result.error = str(CircuitOpenError(target, cb.opened_at))
                target_result.completed_at = time.time()
                target_result.latency_ms = (
                    (target_result.completed_at - target_result.started_at) * 1000
                )
                self._stats["total_failed"] += 1
                return

        for attempt in range(max_retries + 1):
            target_result.retries = attempt
            call_start = time.monotonic()
            call_error = False
            try:
                # ── PR-G5: use adaptive semaphore when available ─────────
                sem_ctx = (
                    self._adaptive_sem if self._adaptive_sem is not None
                    else self._semaphore
                )
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
                    except Exception:
                        pass

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
                    except Exception:
                        pass
                if attempt < max_retries:
                    # 指数退避
                    await asyncio.sleep(min(2 ** attempt * 0.5, 5.0))

            except asyncio.CancelledError:
                target_result.status = CommandStatus.CANCELLED
                target_result.completed_at = time.time()
                target_result.latency_ms = (target_result.completed_at - target_result.started_at) * 1000
                raise

            except Exception as e:
                call_error = True
                last_error = str(e)
                logger.warning(f"Command error: {target}/{command}: {e} (attempt {attempt + 1})")
                elapsed_ms = (time.monotonic() - call_start) * 1000
                if self._adaptive_sem is not None:
                    try:
                        await self._adaptive_sem.record(elapsed_ms, error=True)
                    except Exception:
                        pass
                if attempt < max_retries:
                    await asyncio.sleep(min(2 ** attempt * 0.5, 5.0))

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
        except Exception:
            pass
        return None

    async def _cache_set(self, key: str, value: Any, ttl: int = 60):
        """写入缓存"""
        try:
            await self._cache.set(key, json.dumps(value, default=str), ttl)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    async def cleanup(self, max_age_seconds: int = 3600):
        """清理过期的命令结果"""
        now = time.time()
        expired = [
            rid for rid, r in self._results.items()
            if r.completed_at and (now - r.completed_at) > max_age_seconds
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
            self._fallback_enabled = os.environ.get(
                "GALAXY_NATS_EXECUTOR_FALLBACK", "true"
            ).lower() not in ("false", "0")
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
                    raise RuntimeError(
                        f"envelope publish returned failure: {pub_result.get('error', 'unknown')}"
                    )
            except Exception as _env_err:
                logger.debug(
                    "NATSExecutor: TaskEnvelope publish failed (%s), falling back to TaskDispatch",
                    _env_err,
                )
                pub_result = await nats_bus.publish_task_dispatch(target, task)

            if not pub_result.get("success"):
                return await self._use_fallback(target, command, params, reason="publish_failed")

            self._stats["nats_dispatched"] += 1

            try:
                result = await asyncio.wait_for(
                    asyncio.shield(fut), timeout=self._timeout_s
                )
                self._stats["nats_resolved"] += 1
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
            fut.set_result(result)

    async def _use_fallback(self, target: str, command: str, params: dict, reason: str) -> dict:
        if self._fallback and self._fallback_enabled:
            self._stats["fallback_used"] += 1
            logger.warning(
                "NATSExecutor: NATS unavailable for target=%s command=%s, using local fallback (reason=%s)",
                target,
                command,
                reason,
            )
            return await self._fallback(target, command, params)
        return {
            "success": False,
            "error": f"nats_executor_no_result:{reason}",
            "target": target,
            "command": command,
        }

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
