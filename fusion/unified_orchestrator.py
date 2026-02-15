#!/usr/bin/env python3
"""
UFO Galaxy Fusion - Unified Orchestrator (Reinforced & Production Grade)

统一编排引擎 - 系统级涌现的核心（加固版）

核心职责:
1. 任务分解 (Task Decomposition) - 真实逻辑
2. 智能路由 (Intelligent Routing) - 真实逻辑
3. 跨层级协调 (Cross-layer Coordination) - 真实逻辑
4. 结果聚合 (Result Aggregation) - 真实逻辑
5. 任务生命周期管理 (Task Lifecycle Management) - 完整闭环

作者: Manus AI
日期: 2026-01-26
版本: 1.3.0 (生产级加固)
"""

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
                    # 异步执行任务，不阻塞循环
                    asyncio.create_task(self.execute_task(task))
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
            
            # 3. 执行 (Emergent Capability #3)
            task.status = "executing"
            results = []
            for subtask, plan in execution_plans:
                # 智能选择节点
                node_id = plan.nodes[0]
                task.execution_path.append(node_id)
                
                logger.info(f"⚡ Executing subtask on node: {node_id}")
                
                # 更新节点负载
                self.topology.update_load(node_id, 10)
                
                # 真实执行逻辑，包含重试
                res = await self._execute_with_retry(node_id, subtask)
                
                # 释放节点负载
                self.topology.update_load(node_id, -10)
                
                if res.success:
                    results.append(res.data)
                else:
                    raise Exception(f"Subtask failed on {node_id}: {res.error}")

            # 4. 结果聚合
            task.result = await self._aggregate_results(task, results)
            task.status = "completed"
            task.completed_at = time.time()
            
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
            return {"status": "failed", "error": str(e)}

    async def _execute_with_retry(self, node_id: str, subtask: Dict[str, Any], retries: int = 2) -> ExecutionResult:
        """带重试机制的执行逻辑"""
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
                "capabilities": task.required_capabilities or ["camera"],
            })
            subtasks.append({
                "description": f"[Cognitive] Analyze data",
                "layer": "cognitive",
                "domain": task.preferred_domain or "nlu",
                "capabilities": ["analysis", "processing"],
            })
            subtasks.append({
                "description": f"[Core] Coordination",
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
