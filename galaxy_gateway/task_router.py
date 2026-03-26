"""
Galaxy - 任务路由和调度模块 (Legacy Compatibility Module — PR-S6)

.. deprecated:: PR-S6
    This module (``galaxy_gateway.task_router``) is a **legacy compatibility
    surface** retained for backward compatibility only.

    The canonical server-side task dispatch pipeline is::

        OpenClawd → CommandRouter → TaskEnvelope
        → TaskGraph (core.task_graph)
        → DeviceRouter.route_task
        → Worker/Device
        → ResultEnvelope → OpenClawd feedback

    * :class:`TaskScheduler` — legacy topological scheduler.  Canonical
      replacement: ``core.task_graph.TaskGraph``.
    * :class:`TaskRouter` — legacy raw-HTTP dispatch loop.  Canonical
      replacement: ``galaxy_gateway.device_router.DeviceRouter.route_task()``.
    * :class:`ResultAggregator` — legacy result collector.  Canonical
      replacement: ``core.cross_device_execution_chain`` result envelopes.

    See ``core.orchestration_authority.legacy_paths`` for the registry entries
    (``galaxy_gateway.task_router.TaskScheduler`` and
    ``galaxy_gateway.task_router.TaskRouter``).

功能：
1. 任务路由 - 将任务发送到目标设备（legacy compat — use DeviceRouter for new work）
2. 任务调度 - 管理任务执行顺序和依赖（legacy compat — use core.task_graph for new work）
3. 并行执行 - 支持多设备并行任务
4. 结果聚合 - 收集和聚合任务执行结果
5. 错误处理 - 处理任务失败和重试

作者：Manus AI
日期：2026-01-22
版本：1.0
"""
from core.port_config import get_service_port

import asyncio
import json
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime
import aiohttp

logger = logging.getLogger(__name__)

# ============================================================================
# 数据结构定义
# ============================================================================

class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"       # 等待执行
    RUNNING = "running"       # 正在执行
    COMPLETED = "completed"   # 已完成
    FAILED = "failed"         # 失败
    CANCELLED = "cancelled"   # 已取消
    WAITING = "waiting"       # 等待依赖

@dataclass
class TaskResult:
    """任务执行结果"""
    task_id: str
    device_id: str
    status: TaskStatus
    result: Optional[Any]
    error: Optional[str]
    start_time: datetime
    end_time: Optional[datetime]
    duration: float  # 秒

@dataclass
class ExecutionPlan:
    """执行计划"""
    plan_id: str
    tasks: List[Any]  # Task 对象列表
    execution_order: List[List[str]]  # 执行顺序（分层，每层可并行）
    estimated_duration: float  # 预计总时间（秒）

# ============================================================================
# 任务调度器
# ============================================================================

class TaskScheduler:
    """任务调度器 — Legacy compat topological scheduler.

    .. deprecated:: PR-S6
        ``TaskScheduler`` is a **legacy compatibility scheduler**.  It builds
        topological :class:`ExecutionPlan` objects independently of the
        canonical :mod:`core.task_graph` (TaskGraph).

        Canonical replacement:
            ``core.task_graph.TaskGraph`` — the authoritative dependency-ordered
            multi-device execution planner, which integrates with the canonical
            OpenClawd → CommandRouter → TaskEnvelope → DeviceRouter pipeline.

        ``TaskScheduler`` is retained so gateway-internal code that pre-dates
        the TaskGraph migration does not immediately break.  New code must not
        invoke it as a primary scheduling authority.

        See :mod:`core.orchestration_authority.legacy_paths` for the registry
        entry (``galaxy_gateway.task_router.TaskScheduler``).
    """

    def __init__(self):
        """初始化组件 — PR-S6: emits legacy guardrail on construction."""
        self.initialized_at = datetime.now()
        # PR-S6: emit legacy guardrail — TaskScheduler is a compatibility
        # scheduler only.  The canonical scheduling authority is core.task_graph.
        try:
            from core.orchestration_authority.legacy_paths import emit_legacy_guardrail
            emit_legacy_guardrail(
                caller="galaxy_gateway.task_router.TaskScheduler",
            )
        except Exception:
            pass
    
    def create_execution_plan(self, tasks: List[Any]) -> ExecutionPlan:
        """
        创建执行计划
        
        Args:
            tasks: 任务列表
        
        Returns:
            执行计划
        """
        # 构建依赖图
        task_map = {task.task_id: task for task in tasks}
        
        # 拓扑排序，分层执行
        execution_order = []
        executed = set()
        
        while len(executed) < len(tasks):
            # 找出当前可以执行的任务（依赖都已完成）
            current_layer = []
            
            for task in tasks:
                if task.task_id in executed:
                    continue
                
                # 检查依赖是否都已执行
                dependencies_met = all(dep_id in executed for dep_id in task.depends_on)
                
                if dependencies_met:
                    current_layer.append(task.task_id)
            
            if not current_layer:
                # 检测到循环依赖
                print("Warning: Circular dependency detected!")
                # 强制执行剩余任务
                current_layer = [task.task_id for task in tasks if task.task_id not in executed]
            
            execution_order.append(current_layer)
            executed.update(current_layer)
        
        # 计算预计总时间
        estimated_duration = sum(
            max(task_map[task_id].estimated_duration for task_id in layer)
            for layer in execution_order
        )
        
        return ExecutionPlan(
            plan_id=f"plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            tasks=tasks,
            execution_order=execution_order,
            estimated_duration=estimated_duration
        )

# ============================================================================
# 任务路由器
# ============================================================================

class TaskRouter:
    """任务路由器 — Legacy compat raw-HTTP dispatch loop.

    .. deprecated:: PR-S6
        ``TaskRouter`` is a **legacy compatibility dispatch loop**.  It routes
        tasks to devices via raw HTTP, bypassing the canonical
        DeviceRouter / TaskEnvelope / cross-device chain pipeline.

        Canonical task dispatch::

            OpenClawd → CommandRouter → TaskEnvelope
            → TaskGraph (core.task_graph)
            → DeviceRouter.route_task
            → Worker/Device
            → ResultEnvelope

        Preferred replacements:
            ``galaxy_gateway.device_router.DeviceRouter.route_task()``
            ``core.e2e_orchestrator.process_user_input()``

        ``TaskRouter`` is retained only for backward compatibility.  New
        dispatch code must not be routed through this class.

        See :mod:`core.orchestration_authority.legacy_paths` for the registry
        entry (``galaxy_gateway.task_router.TaskRouter``).
    """

    def __init__(self, device_registry):
        """
        初始化任务路由器 — PR-S6: emits legacy guardrail on construction.

        Args:
            device_registry: 设备注册表
        """
        self.device_registry = device_registry
        self.scheduler = TaskScheduler()
        self.active_tasks: Dict[str, TaskResult] = {}
        # PR-S6: emit legacy guardrail — TaskRouter is a legacy compat
        # dispatch loop.  Canonical dispatch is DeviceRouter.route_task.
        try:
            from core.orchestration_authority.legacy_paths import emit_legacy_guardrail
            emit_legacy_guardrail(
                caller="galaxy_gateway.task_router.TaskRouter",
            )
        except Exception:
            pass
    
    async def execute_tasks(self, tasks: List[Any], trace_id: Optional[str] = None) -> List[TaskResult]:
        """
        执行任务列表

        当 prefer_autonomous 为 True 时，在构建执行计划前检查各任务分配的设备
        是否具备自主执行能力，并记录降级日志（不影响执行）。

        Args:
            tasks: 任务列表
            trace_id: 端到端追踪 ID（如未提供则自动生成）
        
        Returns:
            任务结果列表
        """
        if not tasks:
            return []

        import uuid as _uuid_mod
        _trace_id = trace_id or _uuid_mod.uuid4().hex

        # ── 自主优先检查：记录不具备自主能力的设备（仅日志，不阻断执行）──
        try:
            from galaxy_gateway.autonomous_filter import is_autonomous_device, _prefer_autonomous
            if _prefer_autonomous():
                for task in tasks:
                    device = self.device_registry.get_device(task.device_id)
                    if device is None:
                        continue
                    meta = getattr(device, "metadata", {}) or {}
                    if not is_autonomous_device(meta):
                        logger.warning(
                            "autonomous-first: task %s assigned to non-autonomous device %s; "
                            "downgrading to legacy execution on this device.",
                            task.task_id, task.device_id,
                        )
        except Exception:
            pass

        # 创建执行计划
        plan = self.scheduler.create_execution_plan(tasks)
        
        print(f"\n执行计划:")
        print(f"  计划 ID: {plan.plan_id}")
        print(f"  任务总数: {len(plan.tasks)}")
        print(f"  执行层数: {len(plan.execution_order)}")
        print(f"  预计时间: {plan.estimated_duration:.1f}秒")
        
        # 按层执行任务
        all_results = []
        
        for layer_index, layer in enumerate(plan.execution_order):
            print(f"\n执行第 {layer_index + 1} 层 ({len(layer)} 个任务):")
            
            # 并行执行当前层的所有任务
            layer_tasks = [task for task in tasks if task.task_id in layer]
            layer_results = await asyncio.gather(
                *[self._execute_single_task(task, trace_id=_trace_id) for task in layer_tasks],
                return_exceptions=True
            )
            
            # 处理结果
            for result in layer_results:
                if isinstance(result, Exception):
                    print(f"  任务执行异常: {result}")
                else:
                    all_results.append(result)
                    print(f"  任务 {result.task_id}: {result.status.value}")
        
        return all_results
    
    async def _execute_single_task(self, task: Any, trace_id: Optional[str] = None) -> TaskResult:
        """
        执行单个任务
        
        Args:
            task: 任务对象
            trace_id: 端到端追踪 ID
        
        Returns:
            任务结果
        """
        start_time = datetime.now()

        # ── Lifecycle log: task dispatched ───────────────────────────────────
        try:
            from core.task_logger import emit_task_log
            emit_task_log(
                "task_dispatched",
                task_id=task.task_id,
                trace_id=trace_id,
                device_id=task.device_id,
                task_type="task_router",
                status="dispatched",
            )
        except Exception:
            pass
        
        # 获取目标设备
        device = self.device_registry.get_device(task.device_id)
        
        if not device:
            try:
                from core.task_logger import emit_task_log
                emit_task_log(
                    "task_failed",
                    task_id=task.task_id,
                    trace_id=trace_id,
                    device_id=task.device_id,
                    task_type="task_router",
                    latency_ms=0.0,
                    status="failed",
                    error=f"设备 {task.device_id} 不存在",
                )
            except Exception:
                pass
            return TaskResult(
                task_id=task.task_id,
                device_id=task.device_id,
                status=TaskStatus.FAILED,
                result=None,
                error=f"设备 {task.device_id} 不存在",
                start_time=start_time,
                end_time=datetime.now(),
                duration=0.0
            )
        
        # 检查设备状态
        if device.status.value != "online":
            try:
                from core.task_logger import emit_task_log
                emit_task_log(
                    "task_failed",
                    task_id=task.task_id,
                    trace_id=trace_id,
                    device_id=task.device_id,
                    task_type="task_router",
                    latency_ms=0.0,
                    status="failed",
                    error=f"设备 {device.device_name} 离线",
                )
            except Exception:
                pass
            return TaskResult(
                task_id=task.task_id,
                device_id=task.device_id,
                status=TaskStatus.FAILED,
                result=None,
                error=f"设备 {device.device_name} 离线",
                start_time=start_time,
                end_time=datetime.now(),
                duration=0.0
            )
        
        # 构建任务消息（包含 trace_id）
        task_message = {
            "type": "task",
            "task_id": task.task_id,
            "trace_id": trace_id,
            "intent_type": task.intent_type.value,
            "action": task.action,
            "target": task.target,
            "parameters": task.parameters
        }
        
        # 发送任务到设备
        try:
            result = await self._send_task_to_device(device, task_message)
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            try:
                from core.task_logger import emit_task_log
                emit_task_log(
                    "task_completed",
                    task_id=task.task_id,
                    trace_id=trace_id,
                    device_id=task.device_id,
                    task_type="task_router",
                    latency_ms=round(duration * 1000, 1),
                    status="success",
                )
            except Exception:
                pass
            
            return TaskResult(
                task_id=task.task_id,
                device_id=task.device_id,
                status=TaskStatus.COMPLETED,
                result=result,
                error=None,
                start_time=start_time,
                end_time=end_time,
                duration=duration
            )
        
        except Exception as e:
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            try:
                from core.task_logger import emit_task_log
                emit_task_log(
                    "task_failed",
                    task_id=task.task_id,
                    trace_id=trace_id,
                    device_id=task.device_id,
                    task_type="task_router",
                    latency_ms=round(duration * 1000, 1),
                    status="failed",
                    error=str(e),
                )
            except Exception:
                pass
            
            return TaskResult(
                task_id=task.task_id,
                device_id=task.device_id,
                status=TaskStatus.FAILED,
                result=None,
                error=str(e),
                start_time=start_time,
                end_time=end_time,
                duration=duration
            )
    
    async def _send_task_to_device(self, device, task_message: Dict[str, Any]) -> Any:
        """
        发送任务到设备
        
        Args:
            device: 设备对象
            task_message: 任务消息
        
        Returns:
            执行结果
        """
        # 构建设备 API URL
        # 假设每个设备都有一个 HTTP API 端点
        url = f"http://{device.ip_address}:{get_service_port('dashboard')}/api/execute"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=task_message,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result
                    else:
                        raise Exception(f"设备返回错误: {response.status}")
        
        except aiohttp.ClientError as e:
            raise Exception(f"网络错误: {e}")
        except asyncio.TimeoutError:
            raise Exception("任务执行超时")

# ============================================================================
# 结果聚合器
# ============================================================================

class ResultAggregator:
    """结果聚合器 - 收集和聚合任务执行结果"""
    
    def __init__(self):
        """初始化组件"""
        self.initialized_at = datetime.now()
    
    def aggregate(self, results: List[TaskResult]) -> Dict[str, Any]:
        """
        聚合任务结果
        
        Args:
            results: 任务结果列表
        
        Returns:
            聚合后的结果
        """
        total_tasks = len(results)
        completed_tasks = sum(1 for r in results if r.status == TaskStatus.COMPLETED)
        failed_tasks = sum(1 for r in results if r.status == TaskStatus.FAILED)
        
        total_duration = sum(r.duration for r in results)
        
        # 按设备分组
        by_device = {}
        for result in results:
            if result.device_id not in by_device:
                by_device[result.device_id] = []
            by_device[result.device_id].append(result)
        
        # 收集错误
        errors = [
            {
                "task_id": r.task_id,
                "device_id": r.device_id,
                "error": r.error
            }
            for r in results if r.status == TaskStatus.FAILED
        ]
        
        return {
            "summary": {
                "total_tasks": total_tasks,
                "completed": completed_tasks,
                "failed": failed_tasks,
                "success_rate": completed_tasks / total_tasks if total_tasks > 0 else 0,
                "total_duration": total_duration
            },
            "by_device": {
                device_id: {
                    "total": len(device_results),
                    "completed": sum(1 for r in device_results if r.status == TaskStatus.COMPLETED),
                    "failed": sum(1 for r in device_results if r.status == TaskStatus.FAILED)
                }
                for device_id, device_results in by_device.items()
            },
            "errors": errors,
            "results": [
                {
                    "task_id": r.task_id,
                    "device_id": r.device_id,
                    "status": r.status.value,
                    "result": r.result,
                    "duration": r.duration
                }
                for r in results
            ]
        }

# ============================================================================
# 使用示例
# ============================================================================

async def main():
    """测试示例"""
    from enhanced_nlu_v2 import DeviceRegistry, Device, DeviceType, DeviceStatus, Task, IntentType
    
    # 初始化设备注册表
    device_registry = DeviceRegistry()
    
    # 初始化任务路由器
    router = TaskRouter(device_registry)
    
    # 创建测试任务
    tasks = [
        Task(
            task_id="task_1",
            device_id="phone_b",
            intent_type=IntentType.APP_CONTROL,
            action="open",
            target="wechat",
            parameters={},
            depends_on=[],
            confidence=0.95,
            estimated_duration=2.0
        ),
        Task(
            task_id="task_2",
            device_id="tablet",
            intent_type=IntentType.APP_CONTROL,
            action="play",
            target="music",
            parameters={},
            depends_on=[],
            confidence=0.92,
            estimated_duration=1.5
        ),
        Task(
            task_id="task_3",
            device_id="pc",
            intent_type=IntentType.APP_CONTROL,
            action="open",
            target="chrome",
            parameters={},
            depends_on=["task_1", "task_2"],  # 依赖前两个任务
            confidence=0.90,
            estimated_duration=3.0
        )
    ]
    
    print("="*80)
    print("Galaxy - 任务路由和调度测试")
    print("="*80)
    
    # 执行任务
    results = await router.execute_tasks(tasks)
    
    # 聚合结果
    aggregator = ResultAggregator()
    summary = aggregator.aggregate(results)
    
    print("\n" + "="*80)
    print("执行结果汇总")
    print("="*80)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
