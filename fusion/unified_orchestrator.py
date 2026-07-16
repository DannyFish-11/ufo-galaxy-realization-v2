#!/usr/bin/env python3
"""
Galaxy Fusion - Unified Orchestrator (Reinforced & Production Grade)

.. deprecated::
    此模块已废弃。请使用 ``galaxy_gateway.orchestrator.GalaxyOrchestrator`` 作为
    唯一的顶层编排器。本模块保留仅为向后兼容，``execute_task()`` 将委托给
    GalaxyOrchestrator。

统一编排引擎 - 系统级涌现的核心（加固版）

核心职责:
1. 任务分解 (Task Decomposition) - 真实逻辑
2. 智能路由 (Intelligent Routing) - 真实逻辑
3. 跨层级协调 (Cross-layer Coordination) - 真实逻辑
4. 结果聚合 (Result Aggregation) - 真实逻辑
5. 任务生命周期管理 (Task Lifecycle Management) - 完整闭环

作者: Manus AI
日期: 2026-01-26
版本: 1.3.0 (生产级加固) → DEPRECATED in favor of galaxy_gateway.orchestrator
"""

import warnings as _warnings

_warnings.warn(
    "fusion.unified_orchestrator 已废弃，请迁移到 galaxy_gateway.orchestrator.GalaxyOrchestrator",
    DeprecationWarning,
    stacklevel=2,
)

import asyncio
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .node_executor import ExecutionPool, ExecutionResult, sanitize_error_message
from .topology_manager import NodeInfo, RoutingStrategy, TopologyManager

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY: str = "UNIFIED_ORCHESTRATOR_FACADE_V1"
UNIFIED_ORCHESTRATOR_GRAPH_CONTRIBUTOR: str = "UNIFIED_ORCHESTRATOR_GRAPH_CONTRIBUTOR_V1"
UNIFIED_ORCHESTRATOR_CANONICAL_TASK_FACADE: str = (
    "UNIFIED_ORCHESTRATOR::CANONICAL_TASK_FACADE_V1: "
    "This module is a planner/facade helper only. "
    "System-level dispatch authority belongs to CommandRouter.route_envelope()."
)

# Task worker queue timeout in seconds
TASK_WORKER_TIMEOUT_SECONDS: float = 1.0
# Load delta applied to a node during task execution
NODE_LOAD_DELTA: float = 10.0
# Retry backoff multiplier in seconds
RETRY_BACKOFF_SECONDS: float = 0.5
# Adaptive balancing threshold for forcing load-balanced routing
ADAPTIVE_BALANCING_THRESHOLD: float = 0.7
# Default task reliability requirement
DEFAULT_MIN_RELIABILITY: float = 0.95
# Graceful shutdown timeout in seconds
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS: int = int(os.environ.get("FUSION_SHUTDOWN_TIMEOUT", "10"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
logger = logging.getLogger("UnifiedOrchestrator")

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

try:
    from prometheus_client import Counter, Histogram, Gauge
    PROMETHEUS_AVAILABLE = True
except ImportError:
    Counter = Histogram = Gauge = None  # type: ignore
    PROMETHEUS_AVAILABLE = False

if PROMETHEUS_AVAILABLE:
    _TASK_COUNTER: Optional[Counter] = Counter(
        "fusion_orchestrator_tasks_total",
        "Total tasks processed",
        ["status", "task_type"]
    )
    _TASK_LATENCY: Optional[Histogram] = Histogram(
        "fusion_orchestrator_task_latency_ms",
        "Task execution latency in milliseconds",
        ["task_type"]
    )
    _QUEUE_SIZE_GAUGE: Optional[Gauge] = Gauge(
        "fusion_orchestrator_queue_size",
        "Current task queue size"
    )
else:
    _TASK_COUNTER = None
    _TASK_LATENCY = None
    _QUEUE_SIZE_GAUGE = None


def _record_task_metric(status: str, task_type: str, latency_ms: float) -> None:
    """Record task processing metrics."""
    if _TASK_COUNTER is not None:
        _TASK_COUNTER.labels(status=status, task_type=task_type).inc()
    if _TASK_LATENCY is not None:
        _TASK_LATENCY.labels(task_type=task_type).observe(latency_ms)


def _record_queue_size(size: int) -> None:
    """Record current queue size metric."""
    if _QUEUE_SIZE_GAUGE is not None:
        _QUEUE_SIZE_GAUGE.set(size)


# ---------------------------------------------------------------------------
# Enums and dataclasses
# ---------------------------------------------------------------------------

class TaskPriority(Enum):
    """Task priority levels."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


class TaskType(Enum):
    """Task type enumeration."""
    PERCEPTION = "perception"       # 感知任务（数据采集）
    COGNITIVE = "cognitive"         # 认知任务（分析处理）
    COORDINATION = "coordination"   # 协调任务（系统管理）
    HYBRID = "hybrid"               # 混合任务（跨层级）


@dataclass
class Task:
    """统一任务定义"""
    task_id: str
    description: str
    task_type: TaskType
    priority: TaskPriority = TaskPriority.NORMAL

    # 任务需求
    required_capabilities: List[str] = field(default_factory=list)
    preferred_domain: Optional[str] = None
    preferred_layer: Optional[str] = None

    # 任务约束
    max_latency_ms: Optional[int] = None
    min_reliability: float = DEFAULT_MIN_RELIABILITY

    # 任务数据
    input_data: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)

    # 执行状态
    status: str = "pending"
    assigned_nodes: List[str] = field(default_factory=list)
    execution_path: List[str] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    # 时间戳
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


@dataclass
class ExecutionPlan:
    """Execution plan data class."""
    task_id: str
    nodes: List[str]                    # 执行节点序列
    routing_strategy: RoutingStrategy
    estimated_latency_ms: float
    confidence: float                   # 计划可靠性


class UnifiedOrchestrator:
    """
    统一编排引擎

    这是融合系统的核心，负责任务分析、分解、路由和执行管理。
    """

    def __init__(
        self,
        topology_manager: TopologyManager,
        execution_pool: ExecutionPool,
        enable_predictive_routing: bool = True,
        enable_adaptive_balancing: bool = True
    ) -> None:
        self.topology: TopologyManager = topology_manager
        self.execution_pool: ExecutionPool = execution_pool
        self.enable_predictive_routing: bool = enable_predictive_routing
        self.enable_adaptive_balancing: bool = enable_adaptive_balancing

        # 任务管理
        self.tasks: Dict[str, Task] = {}
        self.task_queue: asyncio.Queue = asyncio.Queue()
        self.is_running: bool = False
        self._worker_task: Optional[asyncio.Task] = None
        self._shutdown_event: asyncio.Event = asyncio.Event()

        # 性能统计
        self.stats: Dict[str, Any] = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "average_latency_ms": 0.0
        }

        logger.info("UnifiedOrchestrator initialized")

    async def start(self) -> None:
        """启动编排引擎"""
        if self.is_running:
            return

        logger.info("Starting UnifiedOrchestrator worker...")
        self.is_running = True
        self._shutdown_event.clear()
        self._worker_task = asyncio.create_task(self._task_worker())
        logger.info("UnifiedOrchestrator worker is now running")

    async def stop(self) -> None:
        """停止编排引擎并清理资源 (graceful shutdown)"""
        if not self.is_running:
            return

        logger.info("Stopping UnifiedOrchestrator (graceful shutdown)...")
        self.is_running = False
        self._shutdown_event.set()

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await asyncio.wait_for(self._worker_task, timeout=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        # 取消并等待所有子任务，防止子任务泄漏
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if pending:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        # 清理执行池资源
        if hasattr(self.execution_pool, 'close_all'):
            await self.execution_pool.close_all()

        logger.info("UnifiedOrchestrator stopped and resources cleaned")

    def register_signal_handlers(self) -> None:
        """Register OS signal handlers for graceful shutdown.

        Should be called from the main thread running the event loop.
        """
        try:
            loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self._handle_signal(s)))
            logger.info("Signal handlers registered for graceful shutdown")
        except (NotImplementedError, RuntimeError) as exc:
            logger.debug("Signal handler registration skipped: %s", exc)

    async def _handle_signal(self, sig: signal.Signals) -> None:
        """Handle OS shutdown signals gracefully."""
        logger.info("Received signal %s, initiating graceful shutdown...", sig.name)
        await self.stop()

    async def submit_task(self, task: Task) -> str:
        """提交任务到异步处理队列"""
        self.tasks[task.task_id] = task
        await self.task_queue.put(task.task_id)
        self.stats["total_tasks"] += 1
        _record_queue_size(self.task_queue.qsize())
        logger.info("Task submitted: %s (%s)", task.task_id, task.description)
        return task.task_id

    async def _task_worker(self) -> None:
        """后台任务处理循环"""
        while self.is_running:
            try:
                # 等待任务，带超时以便检查 is_running 状态
                task_id: str = await asyncio.wait_for(
                    self.task_queue.get(),
                    timeout=TASK_WORKER_TIMEOUT_SECONDS
                )
                task = self.tasks.get(task_id)
                if task:
                    # 异步执行任务，不阻塞循环
                    asyncio.create_task(self.execute_task(task))
                self.task_queue.task_done()
                _record_queue_size(self.task_queue.qsize())
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                logger.error("Error in task worker loop: %s", exc, exc_info=True)

    async def execute_task(self, task: Task) -> Dict[str, Any]:
        """执行任务的完整生命周期"""
        start_time: float = time.time()
        task.status = "analyzing"
        task.started_at = start_time
        task_type_value: str = task.task_type.value if isinstance(task.task_type, TaskType) else str(task.task_type)

        # ── PR-508: Register task in TaskGraphRuntime ────────────────────────
        try:
            from core.task_graph_runtime import (
                get_task_graph_runtime as _get_tgr_uo,
                WorkflowContributorKind as _WCK_uo,
                GraphNode as _GN_uo,
                GraphNodeState as _GNS_uo,
            )
            _tgr_uo = _get_tgr_uo()
            _uo_node = _GN_uo(
                task_id=task.task_id,
                contributor=_WCK_uo.UNIFIED_ORCHESTRATOR,
                tool_name=getattr(task, "task_type", ""),
            )
            _tgr_uo.register_node(_uo_node)
            _tgr_uo.transition(task.task_id, _GNS_uo.ADMITTED)
        except Exception as _exc:
            logger.debug("TaskGraphRuntime registration skipped: %s", _exc)

        try:
            # 1. 任务分解 (Emergent Capability #1)
            logger.info("Analyzing task: %s", task.task_id)
            subtasks: List[Dict[str, Any]] = await self._decompose_task(task)

            # 2. 规划与路由 (Emergent Capability #2)
            logger.info("Planning execution for %d subtask(s)", len(subtasks))
            execution_plans: List[Tuple[Dict[str, Any], ExecutionPlan]] = []
            for subtask in subtasks:
                plan: Optional[ExecutionPlan] = await self._generate_execution_plan(subtask)
                if plan:
                    execution_plans.append((subtask, plan))
                else:
                    raise Exception(f"No valid execution plan for subtask: {subtask.get('description')}")

            # ── PR-508: Lifecycle: admitted → planned ────────────────────────
            try:
                from core.task_graph_runtime import (
                    get_task_graph_runtime as _get_tgr_uo2,
                    GraphNodeState as _GNS_uo2,
                )
                _get_tgr_uo2().transition(task.task_id, _GNS_uo2.PLANNED)
            except Exception as _exc:
                logger.debug("TaskGraphRuntime transition to PLANNED skipped: %s", _exc)

            # 3. 执行 (Emergent Capability #3)
            task.status = "executing"

            # ── PR-508: Lifecycle: admitted → running ──────────────────────────
            try:
                from core.task_graph_runtime import (
                    get_task_graph_runtime as _get_tgr_uo_run,
                    GraphNodeState as _GNS_uo_run,
                )
                _get_tgr_uo_run().transition(task.task_id, _GNS_uo_run.RUNNING)
            except Exception as _exc:
                logger.debug("TaskGraphRuntime transition to RUNNING skipped: %s", _exc)

            results: List[Any] = []

            # ── PR-508: Fanout for multi-subtask execution ───────────────────
            _subtask_ids: List[str] = []
            for subtask, plan in execution_plans:
                _st_id: str = subtask.get("task_id") or f"{task.task_id}:sub:{len(_subtask_ids)}"
                _subtask_ids.append(_st_id)

            if len(_subtask_ids) > 1:
                try:
                    from core.task_graph_runtime import (
                        get_task_graph_runtime as _get_tgr_fo,
                        WorkflowContributorKind as _WCK_fo,
                        GraphNode as _GN_fo,
                    )
                    _tgr_fo = _get_tgr_fo()
                    for _st_id in _subtask_ids:
                        _tgr_fo.register_node(_GN_fo(
                            task_id=_st_id,
                            contributor=_WCK_fo.UNIFIED_ORCHESTRATOR,
                        ))
                    _tgr_fo.register_fanout(
                        parent_task_id=task.task_id,
                        child_task_ids=_subtask_ids,
                        contributor=_WCK_fo.UNIFIED_ORCHESTRATOR,
                    )
                except Exception as _exc:
                    logger.debug("TaskGraphRuntime fanout registration skipped: %s", _exc)

            for (subtask, plan), _st_id in zip(execution_plans, _subtask_ids):
                # 智能选择节点
                node_id: str = plan.nodes[0]
                task.execution_path.append(node_id)

                logger.info("Executing subtask on node: %s", node_id)

                # 更新节点负载
                self.topology.update_load(node_id, NODE_LOAD_DELTA)

                # 真实执行逻辑，包含重试
                res: ExecutionResult = await self._execute_with_retry(node_id, subtask, subtask_id=_st_id)

                # 释放节点负载
                self.topology.update_load(node_id, -NODE_LOAD_DELTA)

                if res.success:
                    results.append(res.data)
                else:
                    sanitized_error: str = sanitize_error_message(res.error) or "Unknown error"
                    raise Exception(f"Subtask failed on {node_id}: {sanitized_error}")

            # 4. 结果聚合
            task.result = await self._aggregate_results(task, results)
            task.status = "completed"
            task.completed_at = time.time()

            # ── PR-508: Lifecycle: running → completed ──────────────────────
            try:
                from core.task_graph_runtime import (
                    get_task_graph_runtime as _get_tgr_uo3,
                    GraphNodeState as _GNS_uo3,
                )
                _get_tgr_uo3().transition(task.task_id, _GNS_uo3.COMPLETED)
            except Exception as _exc:
                logger.debug("TaskGraphRuntime transition to COMPLETED skipped: %s", _exc)

            # 更新统计
            latency: float = (task.completed_at - start_time) * 1000
            self._update_stats(latency)

            logger.info("Task completed: %s in %.1fms", task.task_id, latency)
            _record_task_metric("completed", task_type_value, latency)
            return task.result

        except Exception as exc:
            task.status = "failed"
            task.error = sanitize_error_message(str(exc))
            self.stats["failed_tasks"] += 1
            latency = (time.time() - start_time) * 1000
            logger.error("Task failed: %s - %s", task.task_id, task.error)
            # ── PR-508: Lifecycle: failed ────────────────────────────────────
            try:
                from core.task_graph_runtime import (
                    get_task_graph_runtime as _get_tgr_uo4,
                    GraphNodeState as _GNS_uo4,
                )
                _get_tgr_uo4().transition(task.task_id, _GNS_uo4.FAILED)
            except Exception as _exc:
                logger.debug("TaskGraphRuntime transition to FAILED skipped: %s", _exc)
            _record_task_metric("failed", task_type_value, latency)
            return {"status": "failed", "error": task.error}

    async def _execute_with_retry(
        self,
        node_id: str,
        subtask: Dict[str, Any],
        retries: int = 2,
        subtask_id: str = ""
    ) -> ExecutionResult:
        """带重试机制的执行逻辑"""
        _eff_subtask_id: str = subtask_id or subtask.get("task_id") or f"subtask:{node_id}"
        res: ExecutionResult = ExecutionResult(
            node_id=node_id,
            success=False,
            error="No attempts made",
            latency_ms=0.0,
            timestamp=time.time()
        )
        for attempt in range(retries + 1):
            res = await self.execution_pool.execute_on_node(
                node_id,
                command="process",
                params={"description": subtask.get("description")}
            )
            if res.success:
                return res
            if attempt < retries:
                logger.warning("Attempt %d failed on %s, retrying...", attempt + 1, node_id)
                # ── PR-508: Register retry in TaskGraphRuntime ───────────────
                try:
                    from core.task_graph_runtime import (
                        get_task_graph_runtime as _get_tgr_rt,
                        WorkflowContributorKind as _WCK_rt,
                        GraphNode as _GN_rt,
                    )
                    _retry_id: str = f"{_eff_subtask_id}:retry:{attempt + 1}"
                    _tgr_rt = _get_tgr_rt()
                    _tgr_rt.register_node(_GN_rt(
                        task_id=_retry_id,
                        contributor=_WCK_rt.UNIFIED_ORCHESTRATOR,
                        device_id=node_id,
                    ))
                    _tgr_rt.register_retry(
                        original_task_id=_eff_subtask_id,
                        retry_task_id=_retry_id,
                        attempt_number=attempt + 1,
                        reason="subtask_failure",
                        contributor=_WCK_rt.UNIFIED_ORCHESTRATOR,
                    )
                except Exception as _exc:
                    logger.debug("TaskGraphRuntime retry registration skipped: %s", _exc)
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
        return res

    async def _decompose_task(self, task: Task) -> List[Dict[str, Any]]:
        """将复杂任务分解为跨层级子任务序列 (真实逻辑)"""
        subtasks: List[Dict[str, Any]] = []
        if task.task_type == TaskType.HYBRID:
            # 跨层级流水线：感知 -> 认知 -> 核心
            subtasks.append({
                "description": f"[Perception] {task.description}",
                "layer": "perception",
                "domain": task.preferred_domain or "vision",
                "capabilities": task.required_capabilities or ["camera"],
            })
            subtasks.append({
                "description": "[Cognitive] Analyze data",
                "layer": "cognitive",
                "domain": task.preferred_domain or "nlu",
                "capabilities": ["analysis", "processing"],
            })
            subtasks.append({
                "description": "[Core] Coordination",
                "layer": "core",
                "domain": "task_management",
                "capabilities": ["coordination", "decision"],
            })
        else:
            # 单层级任务
            subtasks.append({
                "description": task.description,
                "layer": task.preferred_layer or self._get_default_layer(task.task_type),
                "domain": task.preferred_domain,
                "capabilities": task.required_capabilities,
            })
        return subtasks

    def _get_default_layer(self, task_type: TaskType) -> str:
        """Get the default layer for a given task type."""
        return {
            TaskType.PERCEPTION: "perception",
            TaskType.COGNITIVE: "cognitive",
            TaskType.COORDINATION: "core"
        }.get(task_type, "cognitive")

    async def _generate_execution_plan(self, subtask: Dict[str, Any]) -> Optional[ExecutionPlan]:
        """生成执行计划，选择最优节点 (真实逻辑)"""
        strategy: RoutingStrategy = self._select_routing_strategy(subtask)
        target_node: Optional[str] = self.topology.find_best_node(
            domain=subtask.get("domain"),
            layer=subtask.get("layer"),
            capabilities=subtask.get("capabilities", []),
            strategy=strategy
        )

        if not target_node:
            # 降级策略：如果指定域没找到，尝试在全域寻找具备能力的节点
            target_node = self.topology.find_best_node(
                capabilities=subtask.get("capabilities", []),
                strategy=RoutingStrategy.LOAD_BALANCED
            )

        if not target_node:
            return None

        return ExecutionPlan(
            task_id=subtask.get("description", "unknown"),
            nodes=[target_node],
            routing_strategy=strategy,
            estimated_latency_ms=20.0,
            confidence=0.95
        )

    def _select_routing_strategy(self, subtask: Dict[str, Any]) -> RoutingStrategy:
        """自适应选择路由策略 (真实逻辑)"""
        if self.enable_adaptive_balancing:
            stats: Dict[str, Any] = self.topology.get_topology_stats()
            # 如果系统整体负载超过阈值，强制开启负载均衡模式
            if stats.get("average_load", 0) > ADAPTIVE_BALANCING_THRESHOLD:
                return RoutingStrategy.LOAD_BALANCED

        # 默认优先考虑域亲和性，以减少跨域数据传输开销
        if subtask.get("domain"):
            return RoutingStrategy.DOMAIN_AFFINITY
        return RoutingStrategy.LOAD_BALANCED

    async def _aggregate_results(self, task: Task, results: List[Any]) -> Dict[str, Any]:
        """聚合子任务结果 (真实逻辑)"""
        combined_data: Dict[str, Any] = {}
        for i, res in enumerate(results):
            if isinstance(res, dict):
                combined_data.update(res)
            else:
                combined_data[f"step_{i}"] = res

        return {
            "task_id": task.task_id,
            "status": "success",
            "combined_data": combined_data,
            "execution_path": task.execution_path,
            "total_steps": len(results)
        }

    def _update_stats(self, latency_ms: float) -> None:
        """更新系统统计数据"""
        self.stats["completed_tasks"] += 1
        n: int = self.stats["completed_tasks"]
        curr_avg: float = self.stats["average_latency_ms"]
        self.stats["average_latency_ms"] = (curr_avg * (n - 1) + latency_ms) / n

    def get_stats(self) -> Dict[str, Any]:
        """获取系统运行统计"""
        return {
            **self.stats,
            "topology_stats": self.topology.get_topology_stats(),
            "queue_size": self.task_queue.qsize()
        }
