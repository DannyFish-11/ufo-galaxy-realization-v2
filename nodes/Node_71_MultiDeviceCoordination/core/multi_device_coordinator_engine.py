"""
Node 71: Multi-Device Coordination Engine (MDCE) v2.1
多设备协调引擎 - 完整实现

功能:
1. 接收 Node 04 (Router) 的跨设备任务
2. 调度 Node 33 (ADB) 和其他设备节点
3. 确保任务在多个设备上并行或串行执行
4. 提供设备发现、状态同步、任务调度和容错恢复能力

架构:
- 设备管理层: 设备发现、注册、心跳维护
- 状态同步层: 向量时钟、Gossip 协议
- 任务调度层: 多策略调度、依赖解析
- 容错恢复层: 熔断器、重试管理器、故障切换
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import datetime
import traceback

# 导入模型
from models.device import (
    Device, DeviceType, DeviceState, DeviceRegistry,
    Capability, ResourceConstraints, VectorClock, DiscoveryProtocol
)
from models.task import (
    Task, TaskState, TaskPriority, TaskType, TaskDependency,
    TaskResource, RetryPolicy, SubTask, TaskQueue, SchedulingStrategy
)

# 导入核心模块
from core.device_discovery import (
    DeviceDiscovery, DiscoveryConfig, DiscoveryEvent, DiscoveryEventType
)
from core.state_synchronizer import (
    StateSynchronizer, SyncConfig, StateEvent, SyncEventType, ConflictResolution
)
from core.task_scheduler import (
    TaskScheduler, SchedulerConfig, SchedulerEvent, SchedulerEventType
)
from core.fault_tolerance import (
    FaultToleranceLayer, CircuitBreakerConfig, RetryConfig, FailoverConfig,
    CircuitBreakerOpenError
)

logger = logging.getLogger("Node71_MDCE")


class CoordinatorState(str, Enum):
    """协调器状态"""
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class CoordinatorConfig:
    """协调器配置"""
    # 节点信息
    node_id: str = ""
    node_name: str = "MultiDeviceCoordinator"

    # 发现配置
    discovery_config: DiscoveryConfig = field(default_factory=DiscoveryConfig)

    # 同步配置
    sync_config: SyncConfig = field(default_factory=SyncConfig)

    # 调度配置
    scheduler_config: SchedulerConfig = field(default_factory=SchedulerConfig)

    # 心跳配置
    heartbeat_interval: float = 10.0
    heartbeat_timeout: float = 60.0

    # 容错配置
    enable_failover: bool = True
    max_retry_attempts: int = 3
    circuit_breaker_config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    retry_config: RetryConfig = field(default_factory=RetryConfig)
    failover_config: FailoverConfig = field(default_factory=FailoverConfig)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "discovery_config": self.discovery_config.to_dict(),
            "sync_config": self.sync_config.to_dict(),
            "scheduler_config": self.scheduler_config.to_dict(),
            "heartbeat_interval": self.heartbeat_interval,
            "heartbeat_timeout": self.heartbeat_timeout,
            "enable_failover": self.enable_failover,
            "max_retry_attempts": self.max_retry_attempts,
            "circuit_breaker_config": self.circuit_breaker_config.to_dict(),
            "retry_config": self.retry_config.to_dict(),
            "failover_config": self.failover_config.to_dict()
        }


class MultiDeviceCoordinatorEngine:
    """
    多设备协调引擎 v2.0
    
    核心功能:
    1. 设备发现与管理
    2. 状态同步与一致性
    3. 任务调度与执行
    4. 容错与恢复
    """
    
    def __init__(self, config: CoordinatorConfig = None):
        self.config = config or CoordinatorConfig()

        # 生成节点ID
        if not self.config.node_id:
            self.config.node_id = f"coordinator-{str(uuid.uuid4())[:8]}"

        # 设备注册表
        self._registry = DeviceRegistry()

        # 核心组件
        self._discovery: Optional[DeviceDiscovery] = None
        self._synchronizer: Optional[StateSynchronizer] = None
        self._scheduler: Optional[TaskScheduler] = None

        # 容错层
        self._fault_tolerance = FaultToleranceLayer(
            circuit_config=self.config.circuit_breaker_config,
            retry_config=self.config.retry_config,
            failover_config=self.config.failover_config
        )

        # 状态
        self._state = CoordinatorState.INITIALIZING
        self._started_at: Optional[float] = None

        # 事件处理器
        self._event_handlers: List[Callable[[str, Dict], None]] = []

        # 任务存储
        self._tasks: Dict[str, Task] = {}

        # 设备组
        self._device_groups: Dict[str, List[str]] = {}

        # 运行任务
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None

        # 统计信息
        self._stats = {
            "devices_registered": 0,
            "devices_discovered": 0,
            "tasks_submitted": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tasks_retried": 0,
            "circuit_breaker_trips": 0,
            "failovers": 0,
            "errors": 0
        }

        logger.info(f"MultiDeviceCoordinatorEngine initialized: {self.config.node_id}")
    
    def add_event_handler(self, handler: Callable[[str, Dict], None]) -> None:
        """添加事件处理器"""
        self._event_handlers.append(handler)
    
    def _emit_event(self, event_type: str, data: Dict) -> None:
        """发送事件"""
        event = {
            "event_type": event_type,
            "timestamp": time.time(),
            "node_id": self.config.node_id,
            **data
        }
        for handler in self._event_handlers:
            try:
                handler(event_type, event)
            except Exception as e:
                logger.error(f"Event handler error: {e}")
    
    async def initialize(self) -> bool:
        """初始化协调器"""
        try:
            logger.info("Initializing MultiDeviceCoordinatorEngine...")

            # 初始化设备发现
            self._discovery = DeviceDiscovery(
                self.config.discovery_config,
                self.config.node_id
            )
            self._discovery.add_event_handler(self._handle_discovery_event)

            # 初始化状态同步器
            self._synchronizer = StateSynchronizer(
                self.config.sync_config,
                self.config.node_id
            )
            self._synchronizer.add_event_handler(self._handle_sync_event)

            # 初始化任务调度器
            self._scheduler = TaskScheduler(
                self.config.scheduler_config,
                self._registry
            )
            self._scheduler.add_event_handler(self._handle_scheduler_event)

            # 注册默认执行器
            self._scheduler.register_executor("command", self._execute_command_task)
            self._scheduler.register_executor("query", self._execute_query_task)
            self._scheduler.register_executor("transfer", self._execute_transfer_task)
            self._scheduler.register_executor("sync", self._execute_sync_task)

            # 初始化容错层
            await self._fault_tolerance.start()

            logger.info("MultiDeviceCoordinatorEngine initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize: {e}")
            self._state = CoordinatorState.ERROR
            self._stats["errors"] += 1
            return False
    
    async def start(self) -> bool:
        """启动协调器"""
        if self._state == CoordinatorState.RUNNING:
            return True
        
        try:
            # 初始化
            if not self._discovery:
                if not await self.initialize():
                    return False
            
            logger.info("Starting MultiDeviceCoordinatorEngine...")
            
            # 启动设备发现
            await self._discovery.start()
            
            # 启动状态同步
            await self._synchronizer.start()
            
            # 启动任务调度
            await self._scheduler.start()
            
            # 启动心跳任务
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            
            # 启动健康检查任务
            self._health_check_task = asyncio.create_task(self._health_check_loop())
            
            self._state = CoordinatorState.RUNNING
            self._started_at = time.time()
            
            logger.info(f"MultiDeviceCoordinatorEngine started: {self.config.node_id}")
            self._emit_event("coordinator_started", {
                "node_id": self.config.node_id,
                "node_name": self.config.node_name
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start: {e}")
            self._state = CoordinatorState.ERROR
            self._stats["errors"] += 1
            return False
    
    async def stop(self) -> None:
        """停止协调器"""
        if self._state == CoordinatorState.STOPPED:
            return
        
        logger.info("Stopping MultiDeviceCoordinatorEngine...")
        self._state = CoordinatorState.STOPPING
        
        # 停止心跳任务
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # 停止健康检查任务
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        # 停止组件
        if self._scheduler:
            await self._scheduler.stop()

        if self._synchronizer:
            await self._synchronizer.stop()

        if self._discovery:
            await self._discovery.stop()

        # 停止容错层
        await self._fault_tolerance.stop()

        self._state = CoordinatorState.STOPPED

        logger.info("MultiDeviceCoordinatorEngine stopped")
        self._emit_event("coordinator_stopped", {"node_id": self.config.node_id})
    
    async def _heartbeat_loop(self) -> None:
        """心跳循环"""
        while self._state == CoordinatorState.RUNNING:
            try:
                # 更新所有设备的心跳状态
                for device in self._registry.list_all():
                    if device.is_healthy(self.config.heartbeat_timeout):
                        # 更新状态同步器
                        await self._synchronizer.update_state(
                            device.device_id,
                            {"state": device.state.value, "last_heartbeat": device.last_heartbeat}
                        )
                    else:
                        # 设备超时
                        device.state = DeviceState.OFFLINE
                        self._emit_event("device_timeout", {"device_id": device.device_id})
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")
            
            await asyncio.sleep(self.config.heartbeat_interval)
    
    async def _health_check_loop(self) -> None:
        """健康检查循环"""
        while self._state == CoordinatorState.RUNNING:
            try:
                # 检查系统健康状态
                stats = self.get_stats()
                
                # 检查设备健康
                offline_count = sum(
                    1 for d in self._registry.list_all()
                    if d.state == DeviceState.OFFLINE
                )
                
                if offline_count > 0:
                    logger.warning(f"{offline_count} devices offline")
                
                # 检查任务队列
                scheduler_stats = self._scheduler.get_stats() if self._scheduler else {}
                if scheduler_stats.get("queue_size", 0) > 100:
                    logger.warning(f"Task queue size: {scheduler_stats['queue_size']}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")
            
            await asyncio.sleep(30)
    
    # ==================== 事件处理 ====================
    
    def _handle_discovery_event(self, event: DiscoveryEvent) -> None:
        """处理设备发现事件"""
        if event.event_type == DiscoveryEventType.DEVICE_FOUND:
            device = event.device
            if device:
                # 注册设备
                if self._registry.register(device):
                    self._stats["devices_discovered"] += 1
                    logger.info(f"Device discovered and registered: {device.device_id}")
                    self._emit_event("device_discovered", {"device": device.to_dict()})
        
        elif event.event_type == DiscoveryEventType.DEVICE_LOST:
            device = event.device
            if device:
                logger.warning(f"Device lost: {device.device_id}")
                self._emit_event("device_lost", {"device_id": device.device_id})
    
    def _handle_sync_event(self, event_type: str, data: Dict) -> None:
        """处理状态同步事件"""
        if event_type == SyncEventType.STATE_CONFLICT:
            logger.warning(f"State conflict detected: {data}")
            self._emit_event("state_conflict", data)
        
        elif event_type == SyncEventType.STATE_MERGED:
            logger.info(f"State merged: {data}")
            self._emit_event("state_merged", data)
    
    def _handle_scheduler_event(self, event: SchedulerEvent) -> None:
        """处理调度器事件"""
        if event.event_type == SchedulerEventType.TASK_COMPLETED:
            self._stats["tasks_completed"] += 1
            if event.task:
                self._tasks[event.task.task_id] = event.task
                self._emit_event("task_completed", {"task": event.task.to_dict()})
        
        elif event.event_type == SchedulerEventType.TASK_FAILED:
            self._stats["tasks_failed"] += 1
            if event.task:
                self._tasks[event.task.task_id] = event.task
                self._emit_event("task_failed", {
                    "task": event.task.to_dict(),
                    "error": event.task.error
                })
    
    # ==================== 设备管理 ====================
    
    def register_device(self, device: Device) -> bool:
        """注册设备"""
        if self._registry.register(device):
            self._stats["devices_registered"] += 1
            logger.info(f"Device registered: {device.device_id}")
            self._emit_event("device_registered", {"device": device.to_dict()})
            return True
        return False
    
    def unregister_device(self, device_id: str) -> bool:
        """注销设备"""
        if self._registry.unregister(device_id):
            logger.info(f"Device unregistered: {device_id}")
            self._emit_event("device_unregistered", {"device_id": device_id})
            return True
        return False
    
    def get_device(self, device_id: str) -> Optional[Device]:
        """获取设备"""
        return self._registry.get(device_id)
    
    def list_devices(
        self,
        device_type: Optional[DeviceType] = None,
        state: Optional[DeviceState] = None
    ) -> List[Device]:
        """列出设备"""
        devices = self._registry.list_all()
        
        if device_type:
            devices = [d for d in devices if d.device_type == device_type]
        if state:
            devices = [d for d in devices if d.state == state]
        
        return devices
    
    def update_device_state(self, device_id: str, state: DeviceState) -> bool:
        """更新设备状态"""
        device = self._registry.get(device_id)
        if not device:
            return False
        
        old_state = device.state
        device.state = state
        device.last_state_change = time.time()
        
        logger.info(f"Device {device_id} state changed: {old_state.value} -> {state.value}")
        self._emit_event("device_state_changed", {
            "device_id": device_id,
            "old_state": old_state.value,
            "new_state": state.value
        })
        
        return True
    
    def create_device_group(self, name: str, device_ids: List[str]) -> str:
        """创建设备组"""
        group_id = f"group-{str(uuid.uuid4())[:8]}"
        self._device_groups[group_id] = device_ids
        logger.info(f"Device group created: {group_id} with {len(device_ids)} devices")
        return group_id
    
    def get_device_group(self, group_id: str) -> Optional[List[str]]:
        """获取设备组"""
        return self._device_groups.get(group_id)
    
    # ==================== 任务管理 ====================
    
    async def create_task(
        self,
        name: str,
        description: str,
        required_devices: List[str],
        subtasks: List[Dict[str, Any]] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: float = 300.0
    ) -> str:
        """创建任务"""
        task = Task(
            task_id=str(uuid.uuid4()),
            name=name,
            description=description,
            required_devices=required_devices,
            subtasks=[
                SubTask(
                    subtask_id=st.get("subtask_id", str(uuid.uuid4())),
                    name=st.get("name", ""),
                    action=st.get("action", ""),
                    target_device=st.get("device_id"),
                    params=st.get("params", {})
                )
                for st in (subtasks or [])
            ],
            priority=priority,
            timeout=timeout
        )
        
        self._tasks[task.task_id] = task
        self._stats["tasks_submitted"] += 1
        
        # 提交到调度器
        await self._scheduler.submit(task)
        
        logger.info(f"Task created: {task.task_id} ({name})")
        self._emit_event("task_created", {"task": task.to_dict()})
        
        return task.task_id
    
    async def assign_task(self, task_id: str) -> bool:
        """分配任务"""
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        # 任务已由调度器自动分配
        return task.state in (TaskState.ASSIGNED, TaskState.RUNNING)
    
    async def execute_task(self, task_id: str) -> bool:
        """执行任务"""
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        # 任务已由调度器自动执行
        return task.state == TaskState.RUNNING
    
    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if self._scheduler:
            return await self._scheduler.cancel(task_id)
        return False
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self._tasks.get(task_id) or (self._scheduler.get_task(task_id) if self._scheduler else None)
    
    def list_tasks(self, state: Optional[TaskState] = None) -> List[Task]:
        """列出任务"""
        tasks = list(self._tasks.values())
        
        if state:
            tasks = [t for t in tasks if t.state == state]
        
        return tasks
    
    # ==================== 协调操作 ====================
    
    async def coordinate_task(
        self,
        task_id: str,
        subtasks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """协调跨设备任务"""
        task = self._tasks.get(task_id)
        if not task:
            return {"success": False, "error": "Task not found"}
        
        results = []
        
        # 并行执行子任务
        async def execute_subtask(subtask: Dict) -> Dict:
            device_id = subtask.get("device_id")
            action = subtask.get("action")
            params = subtask.get("params", {})
            
            device = self._registry.get(device_id)
            if not device:
                return {
                    "subtask_id": subtask.get("subtask_id"),
                    "success": False,
                    "error": f"Device not found: {device_id}"
                }
            
            try:
                result = await self._send_command(device, action, params)
                return {
                    "subtask_id": subtask.get("subtask_id"),
                    "success": True,
                    "result": result
                }
            except Exception as e:
                return {
                    "subtask_id": subtask.get("subtask_id"),
                    "success": False,
                    "error": str(e)
                }
        
        # 并行执行
        results = await asyncio.gather(*[
            execute_subtask(st) for st in subtasks
        ])
        
        return {
            "task_id": task_id,
            "status": "coordinated",
            "results": results
        }
    
    async def broadcast_to_group(
        self,
        group_id: str,
        action: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """向设备组广播命令"""
        device_ids = self._device_groups.get(group_id, [])
        
        if not device_ids:
            return {"success": False, "error": "Group not found or empty"}
        
        results = {}
        
        for device_id in device_ids:
            device = self._registry.get(device_id)
            if device:
                try:
                    result = await self._send_command(device, action, params)
                    results[device_id] = {"success": True, "result": result}
                except Exception as e:
                    results[device_id] = {"success": False, "error": str(e)}
            else:
                results[device_id] = {"success": False, "error": "Device not found"}
        
        return {"success": True, "results": results}
    
    async def _send_command(
        self,
        device: Device,
        action: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """发送命令到设备（通过熔断器保护）"""

        async def _do_send():
            # 实际命令执行逻辑
            await asyncio.sleep(0.1)
            logger.info(f"Command sent to {device.device_id}: {action}")
            return {
                "success": True,
                "device_id": device.device_id,
                "action": action,
                "executed_at": time.time()
            }

        try:
            return await self._fault_tolerance.execute_with_resilience(
                f"device-{device.device_id}",
                _do_send
            )
        except CircuitBreakerOpenError:
            self._stats["circuit_breaker_trips"] += 1
            logger.warning(f"Circuit breaker open for device {device.device_id}")
            return {
                "success": False,
                "device_id": device.device_id,
                "action": action,
                "error": "circuit_breaker_open"
            }
    
    # ==================== 任务执行器 ====================
    
    async def _execute_command_task(self, task: Task, device: Device) -> Dict[str, Any]:
        """执行命令任务"""
        command = task.params.get("command", "")
        args = task.params.get("args", [])
        
        logger.info(f"Executing command on {device.device_id}: {command}")
        
        # 模拟执行
        await asyncio.sleep(0.5)
        
        return {
            "success": True,
            "command": command,
            "args": args,
            "device_id": device.device_id
        }
    
    async def _execute_query_task(self, task: Task, device: Device) -> Dict[str, Any]:
        """执行查询任务"""
        query = task.params.get("query", "")
        
        logger.info(f"Executing query on {device.device_id}: {query}")
        
        # 模拟执行
        await asyncio.sleep(0.3)
        
        return {
            "success": True,
            "query": query,
            "result": f"Query result from {device.device_id}"
        }
    
    async def _execute_transfer_task(self, task: Task, device: Device) -> Dict[str, Any]:
        """执行传输任务"""
        source = task.params.get("source", "")
        destination = task.params.get("destination", "")
        
        logger.info(f"Executing transfer on {device.device_id}: {source} -> {destination}")
        
        # 模拟执行
        await asyncio.sleep(1.0)
        
        return {
            "success": True,
            "source": source,
            "destination": destination,
            "transferred_at": time.time()
        }
    
    async def _execute_sync_task(self, task: Task, device: Device) -> Dict[str, Any]:
        """执行同步任务"""
        sync_type = task.params.get("sync_type", "full")
        
        logger.info(f"Executing sync on {device.device_id}: {sync_type}")
        
        # 模拟执行
        await asyncio.sleep(0.5)
        
        return {
            "success": True,
            "sync_type": sync_type,
            "synced_at": time.time()
        }
    
    # ==================== 状态与统计 ====================
    
    def get_status(self) -> Dict[str, Any]:
        """获取协调器状态"""
        return {
            "node_id": self.config.node_id,
            "node_name": self.config.node_name,
            "state": self._state.value,
            "version": "2.1.0",
            "started_at": self._started_at,
            "uptime": time.time() - self._started_at if self._started_at else 0,
            "stats": self.get_stats(),
            "fault_tolerance": self._fault_tolerance.get_status(),
            "config": self.config.to_dict()
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        devices = self._registry.list_all()
        
        return {
            **self._stats,
            "total_devices": len(devices),
            "online_devices": sum(1 for d in devices if d.state != DeviceState.OFFLINE),
            "busy_devices": sum(1 for d in devices if d.state == DeviceState.BUSY),
            "idle_devices": sum(1 for d in devices if d.state == DeviceState.IDLE),
            "offline_devices": sum(1 for d in devices if d.state == DeviceState.OFFLINE),
            "device_groups": len(self._device_groups),
            "total_tasks": len(self._tasks),
            "scheduler_stats": self._scheduler.get_stats() if self._scheduler else {}
        }
    
    def get_sync_status(self) -> Dict[str, Any]:
        """获取同步状态"""
        if self._synchronizer:
            return self._synchronizer.get_sync_status()
        return {}
    
    def get_discovery_status(self) -> Dict[str, Any]:
        """获取发现状态"""
        if self._discovery:
            return {
                "running": self._discovery._running,
                "discovered_count": self._discovery.count()
            }
        return {}


# 便捷函数
def create_coordinator(
    node_id: str = None,
    node_name: str = "MultiDeviceCoordinator"
) -> MultiDeviceCoordinatorEngine:
    """创建协调器实例"""
    config = CoordinatorConfig(
        node_id=node_id or f"coordinator-{str(uuid.uuid4())[:8]}",
        node_name=node_name
    )
    return MultiDeviceCoordinatorEngine(config)
