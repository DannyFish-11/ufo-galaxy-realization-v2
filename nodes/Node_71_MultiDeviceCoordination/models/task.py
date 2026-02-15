"""
Node 71 - Task Models
任务数据模型定义，包含任务状态、依赖关系和执行结果
"""
import time
import uuid
from typing import Dict, List, Optional, Any, Set, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from datetime import datetime
import asyncio


class TaskState(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"          # 等待调度
    QUEUED = "queued"            # 已入队
    SCHEDULED = "scheduled"      # 已调度
    ASSIGNED = "assigned"        # 已分配
    RUNNING = "running"          # 运行中
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败
    CANCELLED = "cancelled"      # 已取消
    TIMEOUT = "timeout"          # 超时
    RETRYING = "retrying"        # 重试中


class TaskPriority(int, Enum):
    """任务优先级枚举"""
    CRITICAL = 1    # 关键任务
    HIGH = 2        # 高优先级
    NORMAL = 5      # 普通优先级
    LOW = 8         # 低优先级
    BACKGROUND = 10 # 后台任务


class TaskType(str, Enum):
    """任务类型枚举"""
    COMMAND = "command"       # 命令执行
    QUERY = "query"           # 查询任务
    TRANSFER = "transfer"     # 数据传输
    SYNC = "sync"             # 同步任务
    BATCH = "batch"           # 批量任务
    WORKFLOW = "workflow"     # 工作流任务
    SCHEDULED = "scheduled"   # 定时任务


class SchedulingStrategy(str, Enum):
    """调度策略枚举"""
    PRIORITY = "priority"           # 优先级调度
    FAIR = "fair"                   # 公平调度
    ROUND_ROBIN = "round_robin"     # 轮询调度
    LEAST_LOADED = "least_loaded"   # 最少负载
    CAPABILITY = "capability"       # 能力匹配
    LOCATION = "location"           # 位置优先
    RANDOM = "random"               # 随机调度


@dataclass
class TaskDependency:
    """任务依赖关系"""
    task_id: str                    # 依赖的任务ID
    condition: str = "success"      # 依赖条件: success, failure, completed
    timeout: float = 0              # 等待超时(秒), 0表示无限等待
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "condition": self.condition,
            "timeout": self.timeout
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskDependency":
        return cls(
            task_id=data["task_id"],
            condition=data.get("condition", "success"),
            timeout=data.get("timeout", 0)
        )


@dataclass
class TaskResource:
    """任务资源需求"""
    cpu_percent: float = 0          # CPU需求百分比
    memory_mb: int = 0              # 内存需求(MB)
    network_mbps: float = 0         # 网络带宽需求(Mbps)
    gpu: bool = False               # 是否需要GPU
    gpu_memory_mb: int = 0          # GPU内存需求(MB)
    storage_mb: int = 0             # 存储需求(MB)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskResource":
        return cls(
            cpu_percent=data.get("cpu_percent", 0),
            memory_mb=data.get("memory_mb", 0),
            network_mbps=data.get("network_mbps", 0),
            gpu=data.get("gpu", False),
            gpu_memory_mb=data.get("gpu_memory_mb", 0),
            storage_mb=data.get("storage_mb", 0)
        )


@dataclass
class RetryPolicy:
    """重试策略"""
    max_retries: int = 3            # 最大重试次数
    retry_delay: float = 1.0        # 重试延迟(秒)
    exponential_backoff: bool = True # 是否指数退避
    max_delay: float = 60.0         # 最大延迟(秒)
    retry_on_errors: List[str] = field(default_factory=list)  # 触发重试的错误类型
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetryPolicy":
        return cls(
            max_retries=data.get("max_retries", 3),
            retry_delay=data.get("retry_delay", 1.0),
            exponential_backoff=data.get("exponential_backoff", True),
            max_delay=data.get("max_delay", 60.0),
            retry_on_errors=data.get("retry_on_errors", [])
        )
    
    def get_delay(self, retry_count: int) -> float:
        """计算重试延迟"""
        if self.exponential_backoff:
            delay = self.retry_delay * (2 ** retry_count)
            return min(delay, self.max_delay)
        return self.retry_delay


@dataclass
class SubTask:
    """子任务定义"""
    subtask_id: str
    name: str
    action: str                                     # 执行动作
    target_device: Optional[str] = None             # 目标设备ID
    params: Dict[str, Any] = field(default_factory=dict)
    state: TaskState = TaskState.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "subtask_id": self.subtask_id,
            "name": self.name,
            "action": self.action,
            "target_device": self.target_device,
            "params": self.params,
            "state": self.state.value,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubTask":
        return cls(
            subtask_id=data["subtask_id"],
            name=data["name"],
            action=data["action"],
            target_device=data.get("target_device"),
            params=data.get("params", {}),
            state=TaskState(data.get("state", "pending")),
            result=data.get("result"),
            error=data.get("error"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at")
        )


@dataclass
class Task:
    """任务完整数据模型"""
    task_id: str
    name: str
    description: str = ""
    
    # 任务类型与优先级
    task_type: TaskType = TaskType.COMMAND
    priority: TaskPriority = TaskPriority.NORMAL
    
    # 状态
    state: TaskState = TaskState.PENDING
    
    # 设备需求
    required_devices: List[str] = field(default_factory=list)  # 设备ID或类型
    required_capabilities: List[str] = field(default_factory=list)  # 必需能力
    preferred_devices: List[str] = field(default_factory=list)  # 首选设备
    
    # 资源需求
    resource_requirements: TaskResource = field(default_factory=TaskResource)
    
    # 子任务
    subtasks: List[SubTask] = field(default_factory=list)
    
    # 依赖关系
    dependencies: List[TaskDependency] = field(default_factory=list)
    
    # 分配的设备
    assigned_devices: List[str] = field(default_factory=list)
    
    # 执行参数
    params: Dict[str, Any] = field(default_factory=dict)
    timeout: float = 300.0  # 超时时间(秒)
    
    # 重试策略
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    retry_count: int = 0
    
    # 调度策略
    scheduling_strategy: SchedulingStrategy = SchedulingStrategy.PRIORITY
    
    # 时间记录
    created_at: float = field(default_factory=time.time)
    scheduled_at: Optional[float] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    # 进度
    progress: float = 0.0
    
    # 结果
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: Set[str] = field(default_factory=set)
    
    # 创建者
    created_by: Optional[str] = None
    
    # 回调
    callback_url: Optional[str] = None
    
    def __post_init__(self):
        if not self.task_id:
            self.task_id = str(uuid.uuid4())
        if isinstance(self.task_type, str):
            self.task_type = TaskType(self.task_type)
        if isinstance(self.priority, int):
            self.priority = TaskPriority(self.priority)
        if isinstance(self.state, str):
            self.state = TaskState(self.state)
        if isinstance(self.scheduling_strategy, str):
            self.scheduling_strategy = SchedulingStrategy(self.scheduling_strategy)
    
    def is_ready(self, completed_tasks: Set[str]) -> bool:
        """检查任务是否就绪(所有依赖已满足)"""
        for dep in self.dependencies:
            if dep.task_id not in completed_tasks:
                return False
            if dep.condition == "success":
                # 需要依赖任务成功完成
                pass  # 由调用方验证
            elif dep.condition == "failure":
                # 需要依赖任务失败
                pass  # 由调用方验证
        return True
    
    def can_retry(self) -> bool:
        """检查是否可以重试"""
        return self.retry_count < self.retry_policy.max_retries
    
    def get_next_retry_delay(self) -> float:
        """获取下次重试延迟"""
        return self.retry_policy.get_delay(self.retry_count)
    
    def update_progress(self, completed_subtasks: int) -> None:
        """更新进度"""
        if self.subtasks:
            self.progress = completed_subtasks / len(self.subtasks)
        else:
            self.progress = 1.0 if self.state == TaskState.COMPLETED else 0.0
    
    def get_duration(self) -> float:
        """获取执行时长"""
        if self.started_at is None:
            return 0.0
        end_time = self.completed_at or time.time()
        return end_time - self.started_at
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "description": self.description,
            "task_type": self.task_type.value,
            "priority": self.priority.value,
            "state": self.state.value,
            "required_devices": self.required_devices,
            "required_capabilities": self.required_capabilities,
            "preferred_devices": self.preferred_devices,
            "resource_requirements": self.resource_requirements.to_dict(),
            "subtasks": [st.to_dict() for st in self.subtasks],
            "dependencies": [dep.to_dict() for dep in self.dependencies],
            "assigned_devices": self.assigned_devices,
            "params": self.params,
            "timeout": self.timeout,
            "retry_policy": self.retry_policy.to_dict(),
            "retry_count": self.retry_count,
            "scheduling_strategy": self.scheduling_strategy.value,
            "created_at": self.created_at,
            "scheduled_at": self.scheduled_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
            "tags": list(self.tags),
            "created_by": self.created_by,
            "callback_url": self.callback_url
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """从字典创建任务"""
        resource_requirements = data.get("resource_requirements", {})
        if isinstance(resource_requirements, dict):
            resource_requirements = TaskResource.from_dict(resource_requirements)
        
        retry_policy = data.get("retry_policy", {})
        if isinstance(retry_policy, dict):
            retry_policy = RetryPolicy.from_dict(retry_policy)
        
        subtasks = [
            SubTask.from_dict(st) if isinstance(st, dict) else st
            for st in data.get("subtasks", [])
        ]
        
        dependencies = [
            TaskDependency.from_dict(dep) if isinstance(dep, dict) else dep
            for dep in data.get("dependencies", [])
        ]
        
        return cls(
            task_id=data["task_id"],
            name=data["name"],
            description=data.get("description", ""),
            task_type=TaskType(data.get("task_type", "command")),
            priority=TaskPriority(data.get("priority", 5)),
            state=TaskState(data.get("state", "pending")),
            required_devices=data.get("required_devices", []),
            required_capabilities=data.get("required_capabilities", []),
            preferred_devices=data.get("preferred_devices", []),
            resource_requirements=resource_requirements,
            subtasks=subtasks,
            dependencies=dependencies,
            assigned_devices=data.get("assigned_devices", []),
            params=data.get("params", {}),
            timeout=data.get("timeout", 300.0),
            retry_policy=retry_policy,
            retry_count=data.get("retry_count", 0),
            scheduling_strategy=SchedulingStrategy(data.get("scheduling_strategy", "priority")),
            created_at=data.get("created_at", time.time()),
            scheduled_at=data.get("scheduled_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            progress=data.get("progress", 0.0),
            result=data.get("result"),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
            tags=set(data.get("tags", [])),
            created_by=data.get("created_by"),
            callback_url=data.get("callback_url")
        )


@dataclass
class TaskQueue:
    """任务队列"""
    _queue: List[Task] = field(default_factory=list)
    _by_state: Dict[TaskState, Set[str]] = field(default_factory=dict)
    
    def enqueue(self, task: Task) -> bool:
        """入队"""
        if any(t.task_id == task.task_id for t in self._queue):
            return False
        
        # 按优先级插入
        inserted = False
        for i, existing in enumerate(self._queue):
            if task.priority.value < existing.priority.value:
                self._queue.insert(i, task)
                inserted = True
                break
        
        if not inserted:
            self._queue.append(task)
        
        # 更新状态索引
        if task.state not in self._by_state:
            self._by_state[task.state] = set()
        self._by_state[task.state].add(task.task_id)
        
        return True
    
    def dequeue(self) -> Optional[Task]:
        """出队"""
        if not self._queue:
            return None
        
        task = self._queue.pop(0)
        
        # 更新状态索引
        if task.state in self._by_state:
            self._by_state[task.state].discard(task.task_id)
        
        return task
    
    def peek(self) -> Optional[Task]:
        """查看队首"""
        return self._queue[0] if self._queue else None
    
    def remove(self, task_id: str) -> Optional[Task]:
        """移除指定任务"""
        for i, task in enumerate(self._queue):
            if task.task_id == task_id:
                removed = self._queue.pop(i)
                if removed.state in self._by_state:
                    self._by_state[removed.state].discard(task_id)
                return removed
        return None
    
    def get(self, task_id: str) -> Optional[Task]:
        """获取指定任务"""
        for task in self._queue:
            if task.task_id == task_id:
                return task
        return None
    
    def update_state(self, task_id: str, new_state: TaskState) -> bool:
        """更新任务状态"""
        task = self.get(task_id)
        if not task:
            return False
        
        old_state = task.state
        if old_state in self._by_state:
            self._by_state[old_state].discard(task_id)
        
        task.state = new_state
        
        if new_state not in self._by_state:
            self._by_state[new_state] = set()
        self._by_state[new_state].add(task_id)
        
        return True
    
    def get_by_state(self, state: TaskState) -> List[Task]:
        """按状态获取任务"""
        task_ids = self._by_state.get(state, set())
        return [t for t in self._queue if t.task_id in task_ids]
    
    def count(self) -> int:
        """队列大小"""
        return len(self._queue)
    
    def is_empty(self) -> bool:
        """是否为空"""
        return len(self._queue) == 0
    
    def clear(self) -> None:
        """清空队列"""
        self._queue.clear()
        self._by_state.clear()
    
    def list_all(self) -> List[Task]:
        """列出所有任务"""
        return list(self._queue)
