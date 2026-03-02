"""
Node 71 - Task Scheduler Module
任务调度模块，实现多策略任务分配和执行管理
"""
import asyncio
import logging
import time
import uuid
from typing import Dict, List, Optional, Any, Callable, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import datetime
import heapq
import random

from models.device import Device, DeviceState, DeviceRegistry
from models.task import (
    Task, TaskState, TaskPriority, TaskType, TaskDependency,
    TaskResource, RetryPolicy, SubTask, TaskQueue,
    SchedulingStrategy
)

logger = logging.getLogger(__name__)


class SchedulerEventType(str, Enum):
    """调度器事件类型"""
    TASK_SCHEDULED = "task_scheduled"
    TASK_ASSIGNED = "task_assigned"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_RETRY = "task_retry"
    TASK_TIMEOUT = "task_timeout"
    DEVICE_SELECTED = "device_selected"
    SCHEDULER_STARTED = "scheduler_started"
    SCHEDULER_STOPPED = "scheduler_stopped"


@dataclass
class SchedulerEvent:
    """调度器事件"""
    event_type: SchedulerEventType
    task: Optional[Task] = None
    device: Optional[Device] = None
    message: str = ""
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "task": self.task.to_dict() if self.task else None,
            "device": self.device.to_dict() if self.device else None,
            "message": self.message,
            "timestamp": self.timestamp
        }


@dataclass
class SchedulerConfig:
    """调度器配置"""
    # 调度策略
    default_strategy: SchedulingStrategy = SchedulingStrategy.PRIORITY
    
    # 并发控制
    max_concurrent_tasks: int = 100          # 最大并发任务数
    max_tasks_per_device: int = 10           # 每设备最大任务数
    
    # 超时设置
    task_timeout: float = 300.0              # 默认任务超时(秒)
    assignment_timeout: float = 30.0         # 分配超时(秒)
    
    # 重试设置
    default_retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    
    # 负载均衡
    load_balance_interval: float = 60.0      # 负载均衡检查间隔
    rebalance_threshold: float = 0.3         # 重平衡阈值
    
    # 优先级
    priority_aging: bool = True              # 是否启用优先级老化
    priority_aging_interval: float = 60.0    # 优先级老化间隔
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "default_strategy": self.default_strategy.value,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "max_tasks_per_device": self.max_tasks_per_device,
            "task_timeout": self.task_timeout,
            "assignment_timeout": self.assignment_timeout,
            "default_retry_policy": self.default_retry_policy.to_dict(),
            "load_balance_interval": self.load_balance_interval,
            "rebalance_threshold": self.rebalance_threshold,
            "priority_aging": self.priority_aging,
            "priority_aging_interval": self.priority_aging_interval
        }


class DeviceSelector:
    """
    设备选择器
    实现多种设备选择策略
    """
    
    def __init__(self, registry: DeviceRegistry):
        self.registry = registry
    
    def select(
        self,
        task: Task,
        strategy: SchedulingStrategy,
        excluded: Set[str] = None
    ) -> Optional[Device]:
        """选择设备"""
        excluded = excluded or set()
        
        # 获取候选设备
        candidates = self._get_candidates(task, excluded)
        
        if not candidates:
            return None
        
        # 根据策略选择
        if strategy == SchedulingStrategy.PRIORITY:
            return self._select_by_priority(candidates, task)
        elif strategy == SchedulingStrategy.FAIR:
            return self._select_fair(candidates)
        elif strategy == SchedulingStrategy.ROUND_ROBIN:
            return self._select_round_robin(candidates)
        elif strategy == SchedulingStrategy.LEAST_LOADED:
            return self._select_least_loaded(candidates)
        elif strategy == SchedulingStrategy.CAPABILITY:
            return self._select_by_capability(candidates, task)
        elif strategy == SchedulingStrategy.LOCATION:
            return self._select_by_location(candidates, task)
        elif strategy == SchedulingStrategy.RANDOM:
            return self._select_random(candidates)
        else:
            return self._select_by_priority(candidates, task)
    
    def _get_candidates(self, task: Task, excluded: Set[str]) -> List[Device]:
        """获取候选设备"""
        candidates = []
        
        # 首先检查首选设备
        for device_id in task.preferred_devices:
            if device_id in excluded:
                continue
            device = self.registry.get(device_id)
            if device and device.can_accept_task():
                candidates.append(device)
        
        # 如果首选设备不可用，检查能力匹配
        if not candidates and task.required_capabilities:
            for cap in task.required_capabilities:
                devices = self.registry.get_by_capability(cap)
                for device in devices:
                    if device.device_id not in excluded and device.can_accept_task():
                        if device not in candidates:
                            candidates.append(device)
        
        # 如果还没有候选，检查设备类型
        if not candidates and task.required_devices:
            for req in task.required_devices:
                # 尝试按ID查找
                device = self.registry.get(req)
                if device and device.can_accept_task() and device.device_id not in excluded:
                    candidates.append(device)
                    continue
                
                # 尝试按类型查找
                try:
                    from models.device import DeviceType
                    device_type = DeviceType(req)
                    devices = self.registry.get_by_type(device_type)
                    for d in devices:
                        if d.device_id not in excluded and d.can_accept_task():
                            if d not in candidates:
                                candidates.append(d)
                except ValueError:
                    pass
        
        # 如果还是没有候选，使用所有可用设备
        if not candidates:
            candidates = [d for d in self.registry.get_available_devices()
                         if d.device_id not in excluded]
        
        return candidates
    
    def _select_by_priority(self, candidates: List[Device], task: Task) -> Optional[Device]:
        """按优先级选择"""
        # 按设备优先级和负载排序
        sorted_devices = sorted(
            candidates,
            key=lambda d: (d.priority, d.current_load, -d.weight)
        )
        return sorted_devices[0] if sorted_devices else None
    
    def _select_fair(self, candidates: List[Device]) -> Optional[Device]:
        """公平调度"""
        # 选择已完成任务最少的设备
        sorted_devices = sorted(candidates, key=lambda d: d.completed_tasks)
        return sorted_devices[0] if sorted_devices else None
    
    def _select_round_robin(self, candidates: List[Device]) -> Optional[Device]:
        """轮询调度"""
        if not candidates:
            return None
        # 简单实现：随机选择一个
        return random.choice(candidates)
    
    def _select_least_loaded(self, candidates: List[Device]) -> Optional[Device]:
        """最少负载"""
        sorted_devices = sorted(candidates, key=lambda d: d.current_load)
        return sorted_devices[0] if sorted_devices else None
    
    def _select_by_capability(self, candidates: List[Device], task: Task) -> Optional[Device]:
        """按能力选择"""
        if not task.required_capabilities:
            return self._select_least_loaded(candidates)
        
        # 找到具有所有必需能力的设备
        matching = []
        for device in candidates:
            has_all = all(device.has_capability(cap) for cap in task.required_capabilities)
            if has_all:
                matching.append(device)
        
        if matching:
            return self._select_least_loaded(matching)
        return None
    
    def _select_by_location(self, candidates: List[Device], task: Task) -> Optional[Device]:
        """按位置选择"""
        # 从任务元数据获取位置偏好
        preferred_location = task.metadata.get("preferred_location")
        
        if preferred_location:
            location_devices = [d for d in candidates if d.location == preferred_location]
            if location_devices:
                return self._select_least_loaded(location_devices)
        
        return self._select_least_loaded(candidates)
    
    def _select_random(self, candidates: List[Device]) -> Optional[Device]:
        """随机选择"""
        if not candidates:
            return None
        return random.choice(candidates)


class TaskExecutor:
    """
    任务执行器
    负责任务的实际执行
    """
    
    def __init__(self):
        self._executors: Dict[str, Callable] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}
    
    def register_executor(self, task_type: str, executor: Callable) -> None:
        """注册执行器"""
        self._executors[task_type] = executor
    
    async def execute(self, task: Task, device: Device) -> Dict[str, Any]:
        """执行任务"""
        task_type = task.task_type.value
        
        executor = self._executors.get(task_type)
        
        if executor:
            try:
                if asyncio.iscoroutinefunction(executor):
                    result = await executor(task, device)
                else:
                    result = executor(task, device)
                return {"success": True, "result": result}
            except Exception as e:
                return {"success": False, "error": str(e)}
        else:
            # 默认执行器：模拟执行
            return await self._default_execute(task, device)
    
    async def _default_execute(self, task: Task, device: Device) -> Dict[str, Any]:
        """默认执行器"""
        # 模拟执行时间
        await asyncio.sleep(0.5)
        
        return {
            "success": True,
            "task_id": task.task_id,
            "device_id": device.device_id,
            "executed_at": time.time()
        }
    
    def cancel(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self._running_tasks:
            self._running_tasks[task_id].cancel()
            return True
        return False


class DependencyResolver:
    """
    任务依赖解析器
    处理任务间的依赖关系
    """
    
    def __init__(self):
        self._dependency_graph: Dict[str, Set[str]] = {}    # task_id -> dependent_task_ids
        self._reverse_graph: Dict[str, Set[str]] = {}       # task_id -> tasks_that_depend_on_it
        self._completed: Set[str] = set()
        self._failed: Set[str] = set()
    
    def add_task(self, task: Task) -> None:
        """添加任务依赖"""
        task_id = task.task_id
        deps = {dep.task_id for dep in task.dependencies}
        
        self._dependency_graph[task_id] = deps
        
        for dep_id in deps:
            if dep_id not in self._reverse_graph:
                self._reverse_graph[dep_id] = set()
            self._reverse_graph[dep_id].add(task_id)
    
    def remove_task(self, task_id: str) -> None:
        """移除任务"""
        # 从依赖图中移除
        deps = self._dependency_graph.pop(task_id, set())
        
        for dep_id in deps:
            if dep_id in self._reverse_graph:
                self._reverse_graph[dep_id].discard(task_id)
        
        # 从反向依赖图中移除
        dependents = self._reverse_graph.pop(task_id, set())
        for dep_task_id in dependents:
            if dep_task_id in self._dependency_graph:
                self._dependency_graph[dep_task_id].discard(task_id)
        
        # 从已完成/失败集合中移除
        self._completed.discard(task_id)
        self._failed.discard(task_id)
    
    def mark_completed(self, task_id: str) -> List[str]:
        """标记任务完成，返回可以执行的任务"""
        self._completed.add(task_id)
        return self._get_ready_tasks()
    
    def mark_failed(self, task_id: str) -> List[str]:
        """标记任务失败"""
        self._failed.add(task_id)
        # 失败的任务可能导致依赖它的任务也无法执行
        return []
    
    def is_ready(self, task_id: str) -> bool:
        """检查任务是否就绪"""
        deps = self._dependency_graph.get(task_id, set())
        
        for dep_id in deps:
            if dep_id not in self._completed:
                return False
        
        return True
    
    def _get_ready_tasks(self) -> List[str]:
        """获取就绪的任务"""
        ready = []
        for task_id, deps in self._dependency_graph.items():
            if task_id not in self._completed and task_id not in self._failed:
                if self.is_ready(task_id):
                    ready.append(task_id)
        return ready
    
    def get_dependents(self, task_id: str) -> Set[str]:
        """获取依赖指定任务的所有任务"""
        return self._reverse_graph.get(task_id, set())
    
    def get_dependencies(self, task_id: str) -> Set[str]:
        """获取指定任务的所有依赖"""
        return self._dependency_graph.get(task_id, set())
    
    def has_cycle(self, task_id: str) -> bool:
        """检查是否存在循环依赖"""
        visited = set()
        path = set()
        
        def dfs(current: str) -> bool:
            if current in path:
                return True
            if current in visited:
                return False
            
            visited.add(current)
            path.add(current)
            
            for dep_id in self._dependency_graph.get(current, set()):
                if dfs(dep_id):
                    return True
            
            path.remove(current)
            return False
        
        return dfs(task_id)


class TaskScheduler:
    """
    任务调度器
    管理任务的调度、执行和监控
    """
    
    def __init__(
        self,
        config: SchedulerConfig,
        registry: DeviceRegistry
    ):
        self.config = config
        self.registry = registry
        
        # 组件
        self._selector = DeviceSelector(registry)
        self._executor = TaskExecutor()
        self._resolver = DependencyResolver()
        
        # 任务队列
        self._queue = TaskQueue()
        self._running: Dict[str, Task] = {}           # task_id -> Task
        self._completed: Dict[str, Task] = {}
        self._failed: Dict[str, Task] = {}
        
        # 事件处理器
        self._event_handlers: List[Callable[[SchedulerEvent], None]] = []
        
        # 运行状态
        self._running_flag = False
        self._scheduler_task: Optional[asyncio.Task] = None
        self._monitor_task: Optional[asyncio.Task] = None
        
        # 统计
        self._stats = {
            "scheduled": 0,
            "completed": 0,
            "failed": 0,
            "retries": 0
        }
    
    def add_event_handler(self, handler: Callable[[SchedulerEvent], None]) -> None:
        """添加事件处理器"""
        self._event_handlers.append(handler)
    
    def _emit_event(self, event: SchedulerEvent) -> None:
        """发送事件"""
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}")
    
    def register_executor(self, task_type: str, executor: Callable) -> None:
        """注册任务执行器"""
        self._executor.register_executor(task_type, executor)
    
    async def start(self) -> bool:
        """启动调度器"""
        if self._running_flag:
            return True
        
        self._running_flag = True
        
        # 启动调度任务
        self._scheduler_task = asyncio.create_task(self._schedule_loop())
        
        # 启动监控任务
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        logger.info("Task scheduler started")
        self._emit_event(SchedulerEvent(
            event_type=SchedulerEventType.SCHEDULER_STARTED,
            message="Task scheduler started"
        ))
        
        return True
    
    async def stop(self) -> None:
        """停止调度器"""
        self._running_flag = False
        
        for task in [self._scheduler_task, self._monitor_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # 取消所有运行中的任务
        for task_id in list(self._running.keys()):
            self._executor.cancel(task_id)
        
        logger.info("Task scheduler stopped")
        self._emit_event(SchedulerEvent(
            event_type=SchedulerEventType.SCHEDULER_STOPPED,
            message="Task scheduler stopped"
        ))
    
    async def _schedule_loop(self) -> None:
        """调度循环"""
        while self._running_flag:
            try:
                await self._process_queue()
            except Exception as e:
                logger.error(f"Schedule loop error: {e}")
            
            await asyncio.sleep(0.1)
    
    async def _process_queue(self) -> None:
        """处理任务队列"""
        # 检查并发限制
        if len(self._running) >= self.config.max_concurrent_tasks:
            return
        
        # 获取下一个任务
        task = self._queue.peek()
        if not task:
            return
        
        # 检查依赖
        if not self._resolver.is_ready(task.task_id):
            # 依赖未满足，跳过
            self._queue.dequeue()
            # 重新入队等待
            self._queue.enqueue(task)
            return
        
        # 选择设备
        device = self._selector.select(
            task,
            task.scheduling_strategy,
            excluded=set()
        )
        
        if not device:
            # 没有可用设备，等待
            return
        
        # 从队列移除
        self._queue.dequeue()
        
        # 分配任务
        await self._assign_task(task, device)
    
    async def _assign_task(self, task: Task, device: Device) -> bool:
        """分配任务到设备"""
        task.state = TaskState.ASSIGNED
        task.assigned_devices = [device.device_id]
        task.scheduled_at = time.time()
        
        device.current_task = task.task_id
        device.assigned_tasks.append(task.task_id)
        device.state = DeviceState.BUSY
        
        self._running[task.task_id] = task
        
        self._emit_event(SchedulerEvent(
            event_type=SchedulerEventType.TASK_ASSIGNED,
            task=task,
            device=device,
            message=f"Task {task.task_id} assigned to device {device.device_id}"
        ))
        
        # 启动任务执行
        asyncio.create_task(self._execute_task(task, device))
        
        return True
    
    async def _execute_task(self, task: Task, device: Device) -> None:
        """执行任务"""
        task.state = TaskState.RUNNING
        task.started_at = time.time()
        
        self._emit_event(SchedulerEvent(
            event_type=SchedulerEventType.TASK_STARTED,
            task=task,
            device=device,
            message=f"Task {task.task_id} started"
        ))
        
        try:
            # 执行任务
            result = await asyncio.wait_for(
                self._executor.execute(task, device),
                timeout=task.timeout or self.config.task_timeout
            )
            
            if result.get("success"):
                await self._complete_task(task, device, result)
            else:
                await self._fail_task(task, device, result.get("error", "Unknown error"))
                
        except asyncio.TimeoutError:
            await self._handle_timeout(task, device)
        except asyncio.CancelledError:
            await self._cancel_task(task, device)
        except Exception as e:
            await self._fail_task(task, device, str(e))
    
    async def _complete_task(self, task: Task, device: Device, result: Dict) -> None:
        """完成任务"""
        task.state = TaskState.COMPLETED
        task.completed_at = time.time()
        task.result = result
        task.progress = 1.0
        
        # 更新设备状态
        device.completed_tasks += 1
        device.current_task = None
        if task.task_id in device.assigned_tasks:
            device.assigned_tasks.remove(task.task_id)
        device.state = DeviceState.IDLE
        
        # 移动到已完成
        self._running.pop(task.task_id, None)
        self._completed[task.task_id] = task
        
        # 更新依赖解析器
        self._resolver.mark_completed(task.task_id)
        
        # 更新统计
        self._stats["completed"] += 1
        
        self._emit_event(SchedulerEvent(
            event_type=SchedulerEventType.TASK_COMPLETED,
            task=task,
            device=device,
            message=f"Task {task.task_id} completed"
        ))
    
    async def _fail_task(self, task: Task, device: Device, error: str) -> None:
        """任务失败"""
        task.error = error
        
        # 检查是否可以重试
        if task.can_retry():
            await self._retry_task(task, device)
        else:
            task.state = TaskState.FAILED
            task.completed_at = time.time()
            
            # 更新设备状态
            device.failed_tasks += 1
            device.current_task = None
            if task.task_id in device.assigned_tasks:
                device.assigned_tasks.remove(task.task_id)
            device.state = DeviceState.IDLE
            
            # 移动到失败
            self._running.pop(task.task_id, None)
            self._failed[task.task_id] = task
            
            # 更新依赖解析器
            self._resolver.mark_failed(task.task_id)
            
            # 更新统计
            self._stats["failed"] += 1
            
            self._emit_event(SchedulerEvent(
                event_type=SchedulerEventType.TASK_FAILED,
                task=task,
                device=device,
                message=f"Task {task.task_id} failed: {error}"
            ))
    
    async def _retry_task(self, task: Task, device: Device) -> None:
        """重试任务"""
        task.retry_count += 1
        task.state = TaskState.RETRYING
        
        # 更新统计
        self._stats["retries"] += 1
        
        self._emit_event(SchedulerEvent(
            event_type=SchedulerEventType.TASK_RETRY,
            task=task,
            device=device,
            message=f"Task {task.task_id} retrying ({task.retry_count}/{task.retry_policy.max_retries})"
        ))
        
        # 等待重试延迟
        delay = task.get_next_retry_delay()
        await asyncio.sleep(delay)
        
        # 重新执行
        task.state = TaskState.PENDING
        await self._assign_task(task, device)
    
    async def _handle_timeout(self, task: Task, device: Device) -> None:
        """处理超时"""
        task.state = TaskState.TIMEOUT
        task.error = "Task timeout"
        
        # 更新设备状态
        device.failed_tasks += 1
        device.current_task = None
        if task.task_id in device.assigned_tasks:
            device.assigned_tasks.remove(task.task_id)
        device.state = DeviceState.IDLE
        
        self._running.pop(task.task_id, None)
        self._failed[task.task_id] = task
        
        self._emit_event(SchedulerEvent(
            event_type=SchedulerEventType.TASK_TIMEOUT,
            task=task,
            device=device,
            message=f"Task {task.task_id} timed out"
        ))
    
    async def _cancel_task(self, task: Task, device: Device) -> None:
        """取消任务"""
        task.state = TaskState.CANCELLED
        task.completed_at = time.time()
        
        # 更新设备状态
        device.current_task = None
        if task.task_id in device.assigned_tasks:
            device.assigned_tasks.remove(task.task_id)
        device.state = DeviceState.IDLE
        
        self._running.pop(task.task_id, None)
    
    async def _monitor_loop(self) -> None:
        """监控循环"""
        while self._running_flag:
            try:
                await self._check_timeouts()
                await self._update_loads()
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
            
            await asyncio.sleep(5)
    
    async def _check_timeouts(self) -> None:
        """检查超时任务"""
        current_time = time.time()
        timed_out = []
        
        for task_id, task in self._running.items():
            if task.started_at:
                elapsed = current_time - task.started_at
                if elapsed > (task.timeout or self.config.task_timeout):
                    timed_out.append(task_id)
        
        for task_id in timed_out:
            task = self._running.get(task_id)
            if task:
                device_id = task.assigned_devices[0] if task.assigned_devices else None
                device = self.registry.get(device_id) if device_id else None
                if device:
                    await self._handle_timeout(task, device)
    
    async def _update_loads(self) -> None:
        """更新设备负载"""
        for device in self.registry.list_all():
            assigned_count = len(device.assigned_tasks)
            max_tasks = device.resource_constraints.max_concurrent_tasks
            device.current_load = assigned_count / max_tasks if max_tasks > 0 else 0
    
    async def submit(self, task: Task) -> str:
        """提交任务"""
        # 设置默认值
        if not task.timeout:
            task.timeout = self.config.task_timeout
        if not task.retry_policy:
            task.retry_policy = self.config.default_retry_policy
        
        # 添加到依赖解析器
        self._resolver.add_task(task)
        
        # 入队
        self._queue.enqueue(task)
        
        # 更新统计
        self._stats["scheduled"] += 1
        
        self._emit_event(SchedulerEvent(
            event_type=SchedulerEventType.TASK_SCHEDULED,
            task=task,
            message=f"Task {task.task_id} scheduled"
        ))
        
        return task.task_id
    
    async def cancel(self, task_id: str) -> bool:
        """取消任务"""
        # 检查队列
        task = self._queue.remove(task_id)
        if task:
            task.state = TaskState.CANCELLED
            self._resolver.remove_task(task_id)
            return True
        
        # 检查运行中
        task = self._running.get(task_id)
        if task:
            self._executor.cancel(task_id)
            return True
        
        return False
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        # 检查队列
        task = self._queue.get(task_id)
        if task:
            return task
        
        # 检查运行中
        task = self._running.get(task_id)
        if task:
            return task
        
        # 检查已完成
        task = self._completed.get(task_id)
        if task:
            return task
        
        # 检查失败
        return self._failed.get(task_id)
    
    def get_tasks_by_state(self, state: TaskState) -> List[Task]:
        """按状态获取任务"""
        if state == TaskState.PENDING or state == TaskState.QUEUED:
            return self._queue.get_by_state(state)
        elif state == TaskState.RUNNING:
            return list(self._running.values())
        elif state == TaskState.COMPLETED:
            return list(self._completed.values())
        elif state == TaskState.FAILED:
            return list(self._failed.values())
        return []
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "queue_size": self._queue.count(),
            "running_count": len(self._running),
            "completed_count": len(self._completed),
            "failed_count": len(self._failed)
        }
    
    def get_status(self) -> Dict[str, Any]:
        """获取调度器状态"""
        return {
            "running": self._running_flag,
            "config": self.config.to_dict(),
            "stats": self.get_stats(),
            "queue": {
                "size": self._queue.count(),
                "pending": len(self._queue.get_by_state(TaskState.PENDING))
            }
        }
