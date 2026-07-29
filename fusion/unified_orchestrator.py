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
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import time

from .topology_manager import TopologyManager, RoutingStrategy, NodeInfo
from .node_executor import ExecutionPool, ExecutionResult

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("UnifiedOrchestrator")

# ---------------------------------------------------------------------------
# PR-3: Execution Spine Integration — facade authority sentinel
# ---------------------------------------------------------------------------

#: Affirms that UnifiedOrchestrator is a deprecated execution facade.
#: Primary dispatch authority belongs to CommandRouter via the canonical
#: execution spine (core.execution_spine → CommandRouter.route_envelope).
#: This module is retained for backward compatibility only.
UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY: str = "UNIFIED_ORCHESTRATOR_FACADE_V1"

# ---------------------------------------------------------------------------
# PR-6: Task Graph Runtime — contributor sentinel
# ---------------------------------------------------------------------------

#: Affirms that UnifiedOrchestrator is a task graph contributor.
#: Its execution results are projected onto the unified TaskGraphRuntime via
#: ``core.task_graph_runtime.project_workflow_to_graph``.
UNIFIED_ORCHESTRATOR_GRAPH_CONTRIBUTOR: str = "UNIFIED_ORCHESTRATOR_GRAPH_CONTRIBUTOR_V1"

# ---------------------------------------------------------------------------
# PR-A: Canonical Task Spine — facade demotion sentinel
# ---------------------------------------------------------------------------

#: Affirms that UnifiedOrchestrator is a facade/planner helper under the
#: PR-A canonical execution spine.  All system-level dispatch MUST go through
#: CanonicalTask → TaskEnvelope → CommandRouter.route_envelope().
#: This module is registered in core.legacy_dispatch_registry as FACADE_ONLY.
UNIFIED_ORCHESTRATOR_CANONICAL_TASK_FACADE: str = (
    "UNIFIED_ORCHESTRATOR::CANONICAL_TASK_FACADE_V1: "
    "This module is a planner/facade helper only. "
    "System-level dispatch authority belongs to CommandRouter.route_envelope()."
)


class TaskPriority(Enum):
    """任务优先级"""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


class TaskType(Enum):
    """任务类型"""
    PERCEPTION = "perception"      # 感知任务（数据采集）
    COGNITIVE = "cognitive"        # 认知任务（分析处理）
    COORDINATION = "coordination"  # 协调任务（系统管理）
    HYBRID = "hybrid"              # 混合任务（跨层级）


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
    min_reliability: float = 0.95
    
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
    """执行计划"""
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
    ):
        self.topology = topology_manager
        self.execution_pool = execution_pool
        self.enable_predictive_routing = enable_predictive_routing
        self.enable_adaptive_balancing = enable_adaptive_balancing
        
        # 任务管理
        self.tasks: Dict[str, Task] = {}
        self.task_queue = asyncio.Queue()
        self.is_running = False
        self._worker_task = None
        # Strong refs to in-flight execute_task() tasks.  asyncio only keeps a
        # weak ref to bare create_task() results, so a fire-and-forget task can
        # be garbage-collected before it finishes; retain until each completes.
        self._inflight_tasks: set = set()
        
        # 性能统计
        self.stats = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "average_latency_ms": 0.0
        }
        
        logger.info("🚀 UnifiedOrchestrator initialized")

    async def start(self):
        """启动编排引擎"""
        if self.is_running:
            return
        
        logger.info("🚀 Starting UnifiedOrchestrator worker...")
        self.is_running = True
        self._worker_task = asyncio.create_task(self._task_worker())
        logger.info("✅ UnifiedOrchestrator worker is now running")

    async def stop(self):
        """停止编排引擎并清理资源"""
        if not self.is_running:
            return
        
        logger.info("🛑 Stopping UnifiedOrchestrator...")
        self.is_running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        
        # 清理执行池资源
        if hasattr(self.execution_pool, 'close_all'):
            await self.execution_pool.close_all()
            
        logger.info("✅ UnifiedOrchestrator stopped and resources cleaned")

    async def submit_task(self, task: Task) -> str:
        """提交任务到异步处理队列"""
        self.tasks[task.task_id] = task
        await self.task_queue.put(task.task_id)
        self.stats["total_tasks"] += 1
        logger.info(f"📥 Task submitted: {task.task_id} ({task.description})")
        return task.task_id

    async def _task_worker(self):
        """后台任务处理循环"""
        while self.is_running:
            try:
                # 等待任务，带超时以便检查 is_running 状态
                task_id = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)
                task = self.tasks.get(task_id)
                if task:
                    # 异步执行任务，不阻塞循环。保留强引用直至完成,避免任务被 GC
                    # 提前回收(事件循环只持有弱引用)。
                    _exec = asyncio.create_task(self.execute_task(task))
                    self._inflight_tasks.add(_exec)
                    _exec.add_done_callback(self._inflight_tasks.discard)
                self.task_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"❌ Error in task worker loop: {e}", exc_info=True)

    async def execute_task(self, task: Task) -> Dict[str, Any]:
        """执行任务的完整生命周期"""
        start_time = time.time()
        task.status = "analyzing"
        task.started_at = start_time

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
        except Exception:
            pass

        try:
            # 1. 任务分解 (Emergent Capability #1)
            logger.info(f"🔍 Analyzing task: {task.task_id}")
            subtasks = await self._decompose_task(task)
            
            # 2. 规划与路由 (Emergent Capability #2)
            logger.info(f"📋 Planning execution for {len(subtasks)} subtask(s)")
            execution_plans = []
            for subtask in subtasks:
                plan = await self._generate_execution_plan(subtask)
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
            except Exception:
                pass
            
            # 3. 执行 (Emergent Capability #3)
            task.status = "executing"
            results = []

            # ── PR-508: Fanout for multi-subtask execution ───────────────────
            _subtask_ids: list = []
            for subtask, plan in execution_plans:
                _st_id = subtask.get("task_id") or f"{task.task_id}:sub:{len(_subtask_ids)}"
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
                except Exception:
                    pass

            for (subtask, plan), _st_id in zip(execution_plans, _subtask_ids):
                # 智能选择节点
                node_id = plan.nodes[0]
                task.execution_path.append(node_id)
                
                logger.info(f"⚡ Executing subtask on node: {node_id}")

                # 标记节点忙碌 / 执行后恢复。TopologyManager.update_load 的语义是
                # 【设置绝对归一化负载 (0.0-1.0)】,不是增量。此前传 +10 / -10 当作
                # 增减量,会把负载先设成 10、执行后设成 -10;而 find_best_node 的
                # LOAD_BALANCED 走 min(load),负载 -10 的节点反而永远最优、被反复选中
                # ——负载均衡被彻底反转。改为:保存原负载 → 临时抬升(封顶 1.0)→
                # finally 恢复原值,既能反映执行期忙碌,又不破坏 [0,1] 契约。
                _prior_load = self.topology.get_load(node_id)
                self.topology.update_load(node_id, min(1.0, _prior_load + 0.1))

                # 真实执行逻辑，包含重试。用 try/finally 确保无论执行是否抛异常
                # 都恢复原负载,避免节点负载被永久抬高而最终被误判为过载不再调度。
                try:
                    res = await self._execute_with_retry(node_id, subtask, subtask_id=_st_id)
                finally:
                    self.topology.update_load(node_id, _prior_load)

                if res.success:
                    results.append(res.data)
                else:
                    raise Exception(f"Subtask failed on {node_id}: {res.error}")

            # 4. 结果聚合
            task.result = await self._aggregate_results(task, results)
            task.status = "completed"
            task.completed_at = time.time()

            # ── PR-508: Lifecycle: planned → running → completed ─────────────
            try:
                from core.task_graph_runtime import (
                    get_task_graph_runtime as _get_tgr_uo3,
                    GraphNodeState as _GNS_uo3,
                )
                _t3 = _get_tgr_uo3()
                _t3.transition(task.task_id, _GNS_uo3.RUNNING)
                _t3.transition(task.task_id, _GNS_uo3.COMPLETED)
            except Exception:
                pass
            
            # 更新统计
            latency = (task.completed_at - start_time) * 1000
            self._update_stats(latency)
            
            logger.info(f"✅ Task completed: {task.task_id} in {latency:.1f}ms")
            return task.result

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            self.stats["failed_tasks"] += 1
            logger.error(f"❌ Task failed: {task.task_id} - {e}")
            # ── PR-508: Lifecycle: failed ────────────────────────────────────
            try:
                from core.task_graph_runtime import (
                    get_task_graph_runtime as _get_tgr_uo4,
                    GraphNodeState as _GNS_uo4,
                )
                _get_tgr_uo4().transition(task.task_id, _GNS_uo4.FAILED)
            except Exception:
                pass
            return {"status": "failed", "error": str(e)}

    async def _execute_with_retry(self, node_id: str, subtask: Dict[str, Any], retries: int = 2, subtask_id: str = "") -> ExecutionResult:
        """带重试机制的执行逻辑"""
        _eff_subtask_id = subtask_id or subtask.get("task_id") or f"subtask:{node_id}"
        for attempt in range(retries + 1):
            res = await self.execution_pool.execute_on_node(
                node_id, 
                command="process", 
                params={"description": subtask.get("description")}
            )
            if res.success:
                return res
            if attempt < retries:
                logger.warning(f"⚠️ Attempt {attempt+1} failed on {node_id}, retrying...")
                # ── PR-508: Register retry in TaskGraphRuntime ───────────────
                try:
                    from core.task_graph_runtime import (
                        get_task_graph_runtime as _get_tgr_rt,
                        WorkflowContributorKind as _WCK_rt,
                        GraphNode as _GN_rt,
                    )
                    _retry_id = f"{_eff_subtask_id}:retry:{attempt + 1}"
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
                except Exception:
                    pass
                await asyncio.sleep(0.5 * (attempt + 1))
        return res

    async def _decompose_task(self, task: Task) -> List[Dict[str, Any]]:
        """将复杂任务分解为跨层级子任务序列 (真实逻辑)"""
        subtasks = []
        if task.task_type == TaskType.HYBRID:
            # 跨层级流水线：感知 -> 认知 -> 核心
            subtasks.append({
                "description": f"[Perception] {task.description}",
                "layer": "perception",
                "domain": task.preferred_domain or "vision",
                # 能力名必须来自 topology 里【真实声明】的词汇表,否则
                # TopologyManager 按能力筛选时一个节点也匹配不到。
                # config/topology.json 实际声明的 18 项能力是:
                #   authentication / general / http / image_processing /
                #   information_retrieval / knowledge_management / lock_management /
                #   media_processing / memory / network / nlu / orchestration /
                #   routing / search / security / state_management /
                #   text_processing / vision
                # 而这里原本硬编码的 camera / analysis / processing / coordination /
                # decision 五个,没有任何一个在表里(实测交集为空)—— 于是 HYBRID
                # 分解出来的三个子任务全都找不到可执行节点,整条 fusion 任务必然失败。
                "capabilities": task.required_capabilities or ["vision"],
            })
            subtasks.append({
                "description": f"[Cognitive] Analyze data",
                "layer": "cognitive",
                "domain": task.preferred_domain or "nlu",
                "capabilities": ["nlu", "text_processing"],
            })
            subtasks.append({
                "description": f"[Core] Coordination",
                "layer": "core",
                "domain": "task_management",
                "capabilities": ["orchestration"],
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
        return {
            TaskType.PERCEPTION: "perception",
            TaskType.COGNITIVE: "cognitive",
            TaskType.COORDINATION: "core"
        }.get(task_type, "cognitive")

    async def _generate_execution_plan(self, subtask: Dict[str, Any]) -> Optional[ExecutionPlan]:
        """生成执行计划，选择最优节点 (真实逻辑)"""
        strategy = self._select_routing_strategy(subtask)
        target_node = self.topology.find_best_node(
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
            stats = self.topology.get_topology_stats()
            # 如果系统整体负载超过 70%，强制开启负载均衡模式
            if stats.get("average_load", 0) > 0.7:
                return RoutingStrategy.LOAD_BALANCED
        
        # 默认优先考虑域亲和性，以减少跨域数据传输开销
        if subtask.get("domain"):
            return RoutingStrategy.DOMAIN_AFFINITY
        return RoutingStrategy.LOAD_BALANCED

    async def _aggregate_results(self, task: Task, results: List[Any]) -> Dict[str, Any]:
        """聚合子任务结果 (真实逻辑)"""
        combined_data = {}
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

    def _update_stats(self, latency_ms: float):
        """更新系统统计数据"""
        self.stats["completed_tasks"] += 1
        n = self.stats["completed_tasks"]
        curr_avg = self.stats["average_latency_ms"]
        self.stats["average_latency_ms"] = (curr_avg * (n - 1) + latency_ms) / n

    def get_stats(self) -> Dict[str, Any]:
        """获取系统运行统计"""
        return {
            **self.stats,
            "topology_stats": self.topology.get_topology_stats(),
            "queue_size": self.task_queue.qsize()
        }
