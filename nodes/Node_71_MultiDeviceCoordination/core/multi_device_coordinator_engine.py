"""
Node 71: Multi-Device Coordination Engine (MDCE) v2.1
多设备协调引擎 - 编排 / 协调消费者

架构定位（PR-7）
-----------------
Node_71 是一个 **编排 / 协调消费者（orchestration / coordination consumer）**，
而非对等的设备注册权威（peer canonical registration authority）。

设备权威边界：
- ``UnifiedDeviceManager`` (UDM) 是设备注册和规范状态的唯一真实来源（SSOT）。
- ``RegisteredRuntimeDevice`` (contracts/registered_runtime_device.py) 是每个设备的
  唯一规范外部读取契约（sole canonical single-device read contract）。
- Node_71 通过 ``canonical_device_view_adapter`` 将规范投影（RegisteredRuntimeDevice）
  转换为本地协调视图（CoordinationDeviceView），用于任务调度和分组管理。
- Node_71 的本地状态（device groups、任务分配、协调 runtime 状态）**仅限于协调范围**，
  不得作为规范设备状态写入 UDM。

功能:
1. 接收 Node 04 (Router) 的跨设备任务
2. 调度 Node 33 (ADB) 和其他设备节点
3. 确保任务在多个设备上并行或串行执行
4. 提供设备发现、状态同步、任务调度和容错恢复能力

本地状态范围：
- 任务调度状态（task scheduling state）
- 设备分组（group membership within Node_71's coordination runtime）
- 协调元数据（coordination metadata）
- 与本地协调相关的活跃度信息（liveness relevant to local coordination）
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
from core.canonical_device_view_adapter import (
    CoordinationDeviceView,
    CoordinationDeviceStatus,
    adapt_registered_runtime_device,
    adapt_registered_runtime_device_dict,
    refresh_coordination_view,
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
    多设备协调引擎 v2.1 — 编排 / 协调消费者（PR-7）

    架构定位
    --------
    本引擎是 **编排 / 协调消费者**。它从规范设备投影
    （``RegisteredRuntimeDevice``）中读取设备信息，并维护本地协调状态，
    但不充当对等的规范设备注册权威。

    规范设备摄取路径（canonical device intake）
    -------------------------------------------
    - 使用 :meth:`ingest_canonical_device_view` 将 ``RegisteredRuntimeDevice``
      投影摄取为本地 ``CoordinationDeviceView``。
    - 也可使用 :meth:`ingest_canonical_device_view_dict` 处理字典格式的投影。

    本地协调状态（coordination-local state）
    ----------------------------------------
    - ``_canonical_views``: 从规范投影衍生的协调视图（仅用于本地调度）。
    - ``_registry``: 传统设备注册表（向后兼容；新代码应优先使用 ``_canonical_views``）。
    - ``_device_groups``: 本地设备分组（协调范围内）。
    - ``_tasks``: 任务调度状态。

    **注意**：``register_device()``、``unregister_device()``、
    ``update_device_state()`` 均为 **协调本地操作**，不写入 UDM，
    不代表规范设备状态变更。

    核心功能:
    1. 设备发现与管理（协调本地视图）
    2. 状态同步与一致性
    3. 任务调度与执行
    4. 容错与恢复
    """
    
    def __init__(self, config: CoordinatorConfig = None):
        self.config = config or CoordinatorConfig()

        # 生成节点ID
        if not self.config.node_id:
            self.config.node_id = f"coordinator-{str(uuid.uuid4())[:8]}"

        # 设备注册表（向后兼容；新代码应通过 _canonical_views 操作）
        self._registry = DeviceRegistry()

        # 规范设备协调视图（canonical intake path — PR-7）
        # key: device_id → CoordinationDeviceView
        # 这些视图来自规范投影（RegisteredRuntimeDevice），仅供本地调度使用，
        # 不代表规范设备真实状态。
        self._canonical_views: Dict[str, CoordinationDeviceView] = {}

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

            # PR-A: Notify multi-device runtime harness of the coordinator-state
            # transition so that mesh session persistence reflects the new running state.
            try:
                import os as _os, sys as _sys
                _prj_root = _os.path.dirname(_os.path.dirname(_os.path.dirname(
                    _os.path.dirname(_os.path.abspath(__file__)))))
                if _prj_root not in _sys.path:
                    _sys.path.insert(0, _prj_root)
                from core.multi_device_runtime_harness import on_coordinator_state_updated
                on_coordinator_state_updated({
                    "session_id": self.config.node_id,
                    "coordinator_id": self.config.node_id,
                    "overall_status": "running",
                    "node_name": self.config.node_name,
                })
            except Exception as _harn_exc:
                logger.debug(
                    "MultiDeviceCoordinatorEngine.start: harness notification failed (non-fatal): %s",
                    _harn_exc,
                )

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

        # PR-A: Notify multi-device runtime harness of the coordinator-state
        # transition so that mesh session persistence reflects the stopped state.
        try:
            import os as _os, sys as _sys
            _prj_root = _os.path.dirname(_os.path.dirname(_os.path.dirname(
                _os.path.dirname(_os.path.abspath(__file__)))))
            if _prj_root not in _sys.path:
                _sys.path.insert(0, _prj_root)
            from core.multi_device_runtime_harness import on_coordinator_state_updated
            on_coordinator_state_updated({
                "session_id": self.config.node_id,
                "coordinator_id": self.config.node_id,
                "overall_status": "stopped",
                "node_name": self.config.node_name,
            })
        except Exception as _harn_exc:
            logger.debug(
                "MultiDeviceCoordinatorEngine.stop: harness notification failed (non-fatal): %s",
                _harn_exc,
            )
    
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
                        # PR-A: Notify runtime harness of the device-timeout health event.
                        try:
                            import os as _os, sys as _sys
                            _prj_root = _os.path.dirname(_os.path.dirname(_os.path.dirname(
                                _os.path.dirname(_os.path.abspath(__file__)))))
                            if _prj_root not in _sys.path:
                                _sys.path.insert(0, _prj_root)
                            from core.multi_device_runtime_harness import (
                                on_device_health_changed,
                                on_participant_readiness_changed,
                                DeviceHealthEvent,
                            )
                            on_device_health_changed(
                                DeviceHealthEvent(
                                    device_id=device.device_id,
                                    health_score=0.0,
                                    is_reachable=False,
                                    event_type="heartbeat_miss",
                                )
                            )
                            on_participant_readiness_changed(
                                device.device_id, "lost", reason="coordinator_heartbeat_miss"
                            )
                        except Exception as _harn_exc:
                            logger.debug(
                                "MultiDeviceCoordinatorEngine._heartbeat_loop: "
                                "harness notification failed (non-fatal): %s",
                                _harn_exc,
                            )
                
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
    
    # ==================== 规范设备摄取（Canonical Device Intake — PR-7）====================

    def ingest_canonical_device_view(self, rrd: Any) -> bool:
        """将规范设备投影（RegisteredRuntimeDevice）摄取为本地协调视图。

        这是 Node_71 **首选的设备摄取路径**（PR-7）。设备信息从规范投影
        （``contracts.registered_runtime_device.RegisteredRuntimeDevice``）中读取，
        并转换为本地 ``CoordinationDeviceView``，供任务调度和设备分组使用。

        **权威边界（Authority boundary）：**
        - 本方法 **不** 向 UDM 写入任何状态。
        - 产生的 ``CoordinationDeviceView`` 仅用于 Node_71 协调运行时。
        - 若设备已存在于本地视图中，则刷新规范投影字段，保留协调本地状态。

        Args:
            rrd: ``contracts.registered_runtime_device.RegisteredRuntimeDevice``
                 实例，或具有相同字段形状的对象。

        Returns:
            bool: 若成功摄取（新增或刷新）则返回 True；若出现错误则返回 False。
        """
        try:
            device_id = getattr(rrd, "device_id", None)
            if not device_id:
                logger.warning("ingest_canonical_device_view: rrd missing device_id, skipping")
                return False

            existing = self._canonical_views.get(str(device_id))
            if existing is not None:
                view = refresh_coordination_view(existing, rrd)
                logger.debug(f"Refreshed canonical view for device: {device_id}")
            else:
                view = adapt_registered_runtime_device(rrd)
                self._stats["devices_registered"] += 1
                logger.info(f"Ingested canonical device view: {device_id}")

            self._canonical_views[view.device_id] = view
            self._emit_event("device_canonical_view_ingested", {
                "device_id": view.device_id,
                "coordination_status": view.coordination_status.value,
            })
            return True
        except Exception as exc:
            logger.error(f"ingest_canonical_device_view error: {exc}")
            return False

    def ingest_canonical_device_view_dict(self, data: Dict[str, Any]) -> bool:
        """将字典格式的规范投影摄取为本地协调视图（canonical intake — PR-7）。

        便捷方法，接受 ``RegisteredRuntimeDevice.to_dict()`` 格式的字典。
        语义与 :meth:`ingest_canonical_device_view` 相同。

        Args:
            data: ``RegisteredRuntimeDevice.to_dict()`` / ``model_dump()`` 的字典表示。

        Returns:
            bool: 成功返回 True；出现错误返回 False。
        """
        try:
            device_id = data.get("device_id", "")
            if not device_id:
                logger.warning("ingest_canonical_device_view_dict: dict missing device_id, skipping")
                return False

            existing = self._canonical_views.get(str(device_id))
            if existing is not None:
                new_view = adapt_registered_runtime_device_dict(data)
                view = refresh_coordination_view(existing, type(
                    "_RRD", (), {
                        "device_id": new_view.device_id,
                        "device_name": new_view.device_name,
                        "device_type": new_view.device_type,
                        "status": new_view.canonical_status,
                        "capabilities": new_view.capabilities,
                        "metadata": new_view.metadata,
                    }
                )())
                # Use the already-adapted view directly to avoid re-adaptation
                view = new_view
                view.current_task_id = existing.current_task_id
                view.assigned_task_ids = list(existing.assigned_task_ids)
                view.group_ids = list(existing.group_ids)
                if existing.current_task_id is not None:
                    view.coordination_status = CoordinationDeviceStatus.BUSY
                logger.debug(f"Refreshed canonical dict view for device: {device_id}")
            else:
                view = adapt_registered_runtime_device_dict(data)
                self._stats["devices_registered"] += 1
                logger.info(f"Ingested canonical dict view for device: {device_id}")

            self._canonical_views[view.device_id] = view
            self._emit_event("device_canonical_view_ingested", {
                "device_id": view.device_id,
                "coordination_status": view.coordination_status.value,
            })
            return True
        except Exception as exc:
            logger.error(f"ingest_canonical_device_view_dict error: {exc}")
            return False

    def remove_canonical_device_view(self, device_id: str) -> bool:
        """从本地协调运行时中移除设备的规范视图。

        这是协调本地操作——仅从 Node_71 的调度范围中移除设备，
        不向 UDM 发送任何注销请求。

        Args:
            device_id: 要移除的设备 ID。

        Returns:
            bool: 若成功移除返回 True；若视图不存在返回 False。
        """
        if device_id not in self._canonical_views:
            return False
        del self._canonical_views[device_id]
        logger.info(f"Removed canonical view for device: {device_id}")
        self._emit_event("device_canonical_view_removed", {"device_id": device_id})
        return True

    def get_canonical_view(self, device_id: str) -> Optional[CoordinationDeviceView]:
        """获取设备的本地协调视图（从规范投影衍生）。

        Returns:
            CoordinationDeviceView 或 None（若未找到）。
        """
        return self._canonical_views.get(device_id)

    def list_canonical_views(
        self,
        available_only: bool = False,
    ) -> List[CoordinationDeviceView]:
        """列出所有本地协调视图。

        Args:
            available_only: 若为 True，仅返回协调状态为 AVAILABLE 的视图。

        Returns:
            List[CoordinationDeviceView]
        """
        views = list(self._canonical_views.values())
        if available_only:
            views = [v for v in views if v.is_available_for_task()]
        return views

    # ==================== 设备管理（协调本地，向后兼容）====================
    # 注意：以下方法为 **协调本地** 操作，不写入 UDM，不代表规范设备状态变更。
    # 新代码应优先使用 ingest_canonical_device_view() 摄取规范投影。

    def register_device(self, device: Device) -> bool:
        """将设备加入本地协调注册表（协调本地，向后兼容）。

        .. deprecated::
            新代码应优先使用 :meth:`ingest_canonical_device_view` 从规范投影摄取设备。
            本方法保留用于向后兼容；它 **仅** 写入 Node_71 本地协调注册表，
            不向 UDM 写入任何状态。
        """
        if self._registry.register(device):
            self._stats["devices_registered"] += 1
            logger.info(f"Device registered to local coordination registry: {device.device_id}")
            self._emit_event("device_registered", {"device": device.to_dict()})
            return True
        return False

    def unregister_device(self, device_id: str) -> bool:
        """从本地协调注册表中移除设备（协调本地，向后兼容）。

        .. deprecated::
            新代码应优先使用 :meth:`remove_canonical_device_view`。
            本方法仅操作 Node_71 本地注册表，不向 UDM 发送注销请求。
        """
        if self._registry.unregister(device_id):
            logger.info(f"Device removed from local coordination registry: {device_id}")
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
        """更新设备的协调本地状态（coordination-local，向后兼容）。

        .. note::
            本方法更新的是 Node_71 本地协调注册表中的设备状态，
            **不** 向 UDM 写入任何规范状态变更。
            新代码应通过 :meth:`ingest_canonical_device_view` 刷新状态，
            或通过 ``CoordinationDeviceView`` 的 ``mark_task_assigned`` /
            ``mark_task_released`` 管理协调本地状态。
        """
        device = self._registry.get(device_id)
        if not device:
            return False

        old_state = device.state
        device.state = state
        device.last_state_change = time.time()

        logger.info(
            f"Device {device_id} coordination-local state changed: "
            f"{old_state.value} -> {state.value} (coordination-only, not canonical)"
        )
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
        """获取统计信息（包含规范视图计数）"""
        devices = self._registry.list_all()
        canonical_views = list(self._canonical_views.values())

        return {
            **self._stats,
            # Legacy coordination registry stats
            "total_devices": len(devices),
            "online_devices": sum(1 for d in devices if d.state != DeviceState.OFFLINE),
            "busy_devices": sum(1 for d in devices if d.state == DeviceState.BUSY),
            "idle_devices": sum(1 for d in devices if d.state == DeviceState.IDLE),
            "offline_devices": sum(1 for d in devices if d.state == DeviceState.OFFLINE),
            # Canonical view stats (PR-7)
            "canonical_views_total": len(canonical_views),
            "canonical_views_available": sum(
                1 for v in canonical_views if v.is_available_for_task()
            ),
            "canonical_views_busy": sum(
                1 for v in canonical_views
                if v.coordination_status == CoordinationDeviceStatus.BUSY
            ),
            # Coordination stats
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
