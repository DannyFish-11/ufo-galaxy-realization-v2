"""
Node 71 - MultiDeviceCoordination (多设备协调节点)
提供多设备协同控制、任务分配和状态同步能力
v2.0 - 重构版本，集成新的核心引擎
"""
import os
import sys
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid

# 添加当前目录到路径，确保导入本地 core 模块
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# 导入本地核心模块
from core import (
    MultiDeviceCoordinatorEngine, CoordinatorConfig, CoordinatorState,
    Device, DeviceType, DeviceState, DeviceRegistry,
    Task, TaskState, TaskPriority, TaskType, SchedulingStrategy,
    DiscoveryConfig, SyncConfig, SchedulerConfig
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 71 - MultiDeviceCoordination", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


# ==================== 兼容性数据类 ====================

class DeviceTypeCompat(str, Enum):
    """设备类型（兼容性）"""
    DRONE = "drone"
    PRINTER_3D = "printer_3d"
    ROBOT = "robot"
    CAMERA = "camera"
    SENSOR = "sensor"
    ACTUATOR = "actuator"
    DISPLAY = "display"
    SPEAKER = "speaker"


class DeviceStateCompat(str, Enum):
    """设备状态（兼容性）"""
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    IDLE = "idle"
    ERROR = "error"
    MAINTENANCE = "maintenance"


class TaskStateCompat(str, Enum):
    """任务状态（兼容性）"""
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DeviceCompat:
    """设备（兼容性）"""
    device_id: str
    name: str
    device_type: DeviceTypeCompat
    state: DeviceStateCompat = DeviceStateCompat.OFFLINE
    capabilities: List[str] = field(default_factory=list)
    location: Optional[str] = None
    endpoint: Optional[str] = None
    last_heartbeat: Optional[datetime] = None
    current_task: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CoordinatedTaskCompat:
    """协调任务（兼容性）"""
    task_id: str
    name: str
    description: str
    required_devices: List[str]
    subtasks: List[Dict[str, Any]] = field(default_factory=list)
    state: TaskStateCompat = TaskStateCompat.PENDING
    assigned_devices: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: float = 0.0
    results: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceGroupCompat:
    """设备组（兼容性）"""
    group_id: str
    name: str
    device_ids: List[str]
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ==================== 兼容性适配器 ====================

class MultiDeviceCoordinator:
    """
    多设备协调器（兼容性包装器）
    封装新的核心引擎，提供向后兼容的 API
    """
    
    def __init__(self):
        # 创建配置
        config = CoordinatorConfig(
            node_id=f"node71-{str(uuid.uuid4())[:8]}",
            node_name="MultiDeviceCoordinator"
        )
        
        # 初始化核心引擎
        self._engine = MultiDeviceCoordinatorEngine(config)
        
        # 兼容性存储
        self.devices: Dict[str, DeviceCompat] = {}
        self.tasks: Dict[str, CoordinatedTaskCompat] = {}
        self.groups: Dict[str, DeviceGroupCompat] = {}
        self._task_queue: asyncio.Queue = asyncio.Queue()
        self._is_running = False
        
        # 启动引擎
        self._start_engine()
    
    def _start_engine(self):
        """启动核心引擎"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._engine.start())
            else:
                loop.run_until_complete(self._engine.start())
            logger.info("Core engine started")
        except Exception as e:
            logger.error(f"Failed to start core engine: {e}")
    
    def _convert_device(self, device: Device) -> DeviceCompat:
        """转换设备对象"""
        return DeviceCompat(
            device_id=device.device_id,
            name=device.name,
            device_type=DeviceTypeCompat(device.device_type.value),
            state=DeviceStateCompat(device.state.value),
            capabilities=[cap.name for cap in device.capabilities],
            location=device.location,
            endpoint=device.endpoint,
            last_heartbeat=datetime.fromtimestamp(device.last_heartbeat) if device.last_heartbeat else None,
            current_task=device.current_task,
            metadata=device.metadata
        )
    
    def _convert_task(self, task: Task) -> CoordinatedTaskCompat:
        """转换任务对象"""
        return CoordinatedTaskCompat(
            task_id=task.task_id,
            name=task.name,
            description=task.description,
            required_devices=task.required_devices,
            subtasks=[st.to_dict() for st in task.subtasks],
            state=TaskStateCompat(task.state.value),
            assigned_devices=task.assigned_devices,
            created_at=datetime.fromtimestamp(task.created_at),
            started_at=datetime.fromtimestamp(task.started_at) if task.started_at else None,
            completed_at=datetime.fromtimestamp(task.completed_at) if task.completed_at else None,
            progress=task.progress,
            results=task.result or {}
        )
    
    def register_device(self, device: DeviceCompat) -> bool:
        """注册设备"""
        # 创建新设备对象
        new_device = Device(
            device_id=device.device_id,
            name=device.name,
            device_type=DeviceType(device.device_type.value),
            state=DeviceState(device.state.value),
            capabilities=[],
            location=device.location,
            endpoint=device.endpoint,
            metadata=device.metadata
        )
        
        # 注册到引擎
        self._engine.register_device(new_device)
        
        # 兼容性存储
        self.devices[device.device_id] = device
        logger.info(f"Registered device: {device.device_id} ({device.name})")
        return True
    
    def unregister_device(self, device_id: str) -> bool:
        """注销设备"""
        self._engine.unregister_device(device_id)
        if device_id in self.devices:
            del self.devices[device_id]
            return True
        return False
    
    def update_device_state(self, device_id: str, state: DeviceStateCompat) -> bool:
        """更新设备状态"""
        self._engine.update_device_state(device_id, DeviceState(state.value))
        if device_id in self.devices:
            self.devices[device_id].state = state
            self.devices[device_id].last_heartbeat = datetime.now()
            return True
        return False
    
    def heartbeat(self, device_id: str) -> bool:
        """设备心跳"""
        if device_id not in self.devices:
            return False
        
        device = self.devices[device_id]
        device.last_heartbeat = datetime.now()
        if device.state == DeviceStateCompat.OFFLINE:
            device.state = DeviceStateCompat.IDLE
        return True
    
    def create_group(self, name: str, device_ids: List[str]) -> str:
        """创建设备组"""
        group_id = self._engine.create_device_group(name, device_ids)
        
        group = DeviceGroupCompat(
            group_id=group_id,
            name=name,
            device_ids=device_ids
        )
        self.groups[group.group_id] = group
        logger.info(f"Created device group: {group.group_id} ({name})")
        return group.group_id
    
    async def create_task(self, name: str, description: str,
                          required_devices: List[str],
                          subtasks: List[Dict[str, Any]] = None) -> str:
        """创建协调任务"""
        task_id = await self._engine.create_task(
            name=name,
            description=description,
            required_devices=required_devices,
            subtasks=subtasks
        )
        
        # 创建兼容性任务对象
        task = CoordinatedTaskCompat(
            task_id=task_id,
            name=name,
            description=description,
            required_devices=required_devices,
            subtasks=subtasks or []
        )
        
        self.tasks[task.task_id] = task
        await self._task_queue.put(task.task_id)
        logger.info(f"Created coordinated task: {task.task_id} ({name})")
        return task.task_id
    
    async def assign_task(self, task_id: str) -> bool:
        """分配任务到设备"""
        if task_id not in self.tasks:
            return False
        
        task = self.tasks[task_id]
        
        # 查找可用设备
        available_devices = self._find_available_devices(task.required_devices)
        
        if len(available_devices) < len(task.required_devices):
            logger.warning(f"Not enough devices for task {task_id}")
            return False
        
        # 分配设备
        task.assigned_devices = available_devices
        task.state = TaskStateCompat.ASSIGNED
        
        # 更新设备状态
        for device_id in available_devices:
            self.devices[device_id].state = DeviceStateCompat.BUSY
            self.devices[device_id].current_task = task_id
        
        logger.info(f"Assigned task {task_id} to devices: {available_devices}")
        return True
    
    def _find_available_devices(self, requirements: List[str]) -> List[str]:
        """查找可用设备"""
        available = []
        
        for req in requirements:
            for device_id, device in self.devices.items():
                if device.state != DeviceStateCompat.IDLE:
                    continue
                
                # 检查是否匹配（按 ID 或类型）
                if device.device_id == req or device.device_type.value == req:
                    if device_id not in available:
                        available.append(device_id)
                        break
        
        return available
    
    async def execute_task(self, task_id: str) -> bool:
        """执行协调任务"""
        if task_id not in self.tasks:
            return False
        
        task = self.tasks[task_id]
        
        if task.state != TaskStateCompat.ASSIGNED:
            # 先分配任务
            if not await self.assign_task(task_id):
                return False
        
        task.state = TaskStateCompat.RUNNING
        task.started_at = datetime.now()
        
        try:
            # 执行子任务
            total_subtasks = len(task.subtasks) or 1
            completed = 0
            
            for subtask in task.subtasks:
                device_id = subtask.get("device_id")
                action = subtask.get("action")
                params = subtask.get("params", {})
                
                # 发送命令到设备
                result = await self._send_command(device_id, action, params)
                
                subtask["result"] = result
                subtask["completed"] = True
                
                completed += 1
                task.progress = completed / total_subtasks
            
            task.state = TaskStateCompat.COMPLETED
            task.completed_at = datetime.now()
            task.progress = 1.0
            
            logger.info(f"Task {task_id} completed successfully")
            return True
            
        except Exception as e:
            task.state = TaskStateCompat.FAILED
            task.results["error"] = str(e)
            logger.error(f"Task {task_id} failed: {e}")
            return False
        
        finally:
            # 释放设备
            for device_id in task.assigned_devices:
                if device_id in self.devices:
                    self.devices[device_id].state = DeviceStateCompat.IDLE
                    self.devices[device_id].current_task = None
    
    async def _send_command(self, device_id: str, action: str,
                            params: Dict[str, Any]) -> Dict[str, Any]:
        """发送命令到设备"""
        if device_id not in self.devices:
            return {"success": False, "error": "Device not found"}
        
        device = self.devices[device_id]
        
        # 模拟命令执行
        await asyncio.sleep(0.5)
        
        logger.info(f"Sent command to {device_id}: {action}")
        return {"success": True, "device": device_id, "action": action}
    
    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if task_id not in self.tasks:
            return False
        
        task = self.tasks[task_id]
        task.state = TaskStateCompat.CANCELLED
        
        # 释放设备
        for device_id in task.assigned_devices:
            if device_id in self.devices:
                self.devices[device_id].state = DeviceStateCompat.IDLE
                self.devices[device_id].current_task = None
        
        return True
    
    async def broadcast_to_group(self, group_id: str, action: str,
                                 params: Dict[str, Any]) -> Dict[str, Any]:
        """向设备组广播命令"""
        if group_id not in self.groups:
            return {"success": False, "error": "Group not found"}
        
        group = self.groups[group_id]
        results = {}
        
        for device_id in group.device_ids:
            device = self.devices.get(device_id)
            if device:
                try:
                    result = await self._send_command(device_id, action, params)
                    results[device_id] = result
                except Exception as e:
                    results[device_id] = {"success": False, "error": str(e)}
            else:
                results[device_id] = {"success": False, "error": "Device not found"}
        
        return {"success": True, "results": results}
    
    def get_device(self, device_id: str) -> Optional[DeviceCompat]:
        """获取设备信息"""
        return self.devices.get(device_id)
    
    def list_devices(self, device_type: Optional[DeviceTypeCompat] = None,
                     state: Optional[DeviceStateCompat] = None) -> List[DeviceCompat]:
        """列出设备"""
        devices = list(self.devices.values())
        
        if device_type:
            devices = [d for d in devices if d.device_type == device_type]
        if state:
            devices = [d for d in devices if d.state == state]
        
        return devices
    
    def get_status(self) -> Dict[str, Any]:
        """获取协调器状态"""
        engine_status = self._engine.get_status()
        
        return {
            "total_devices": len(self.devices),
            "online_devices": sum(1 for d in self.devices.values() if d.state != DeviceStateCompat.OFFLINE),
            "busy_devices": sum(1 for d in self.devices.values() if d.state == DeviceStateCompat.BUSY),
            "total_tasks": len(self.tasks),
            "running_tasks": sum(1 for t in self.tasks.values() if t.state == TaskStateCompat.RUNNING),
            "completed_tasks": sum(1 for t in self.tasks.values() if t.state == TaskStateCompat.COMPLETED),
            "device_groups": len(self.groups),
            "engine_status": engine_status
        }


# 全局实例
coordinator = MultiDeviceCoordinator()


# ==================== API 模型 ====================

class RegisterDeviceRequest(BaseModel):
    device_id: str
    name: str
    device_type: str
    capabilities: List[str] = []
    location: Optional[str] = None
    endpoint: Optional[str] = None

class CreateTaskRequest(BaseModel):
    name: str
    description: str
    required_devices: List[str]
    subtasks: List[Dict[str, Any]] = []

class CreateGroupRequest(BaseModel):
    name: str
    device_ids: List[str]

class BroadcastRequest(BaseModel):
    action: str
    params: Dict[str, Any] = {}


# ==================== API 端点 ====================

@app.get("/health")
async def health_check():
    return {"status": "healthy", "node": "Node_71_MultiDeviceCoordination", "version": "2.0.0"}

@app.get("/status")
async def get_status():
    return coordinator.get_status()

@app.post("/devices")
async def register_device(request: RegisterDeviceRequest):
    device = DeviceCompat(
        device_id=request.device_id,
        name=request.name,
        device_type=DeviceTypeCompat(request.device_type),
        capabilities=request.capabilities,
        location=request.location,
        endpoint=request.endpoint,
        state=DeviceStateCompat.IDLE
    )
    coordinator.register_device(device)
    return {"success": True}

@app.get("/devices")
async def list_devices(device_type: Optional[str] = None, state: Optional[str] = None):
    dt = DeviceTypeCompat(device_type) if device_type else None
    ds = DeviceStateCompat(state) if state else None
    devices = coordinator.list_devices(dt, ds)
    return [asdict(d) for d in devices]

@app.get("/devices/{device_id}")
async def get_device(device_id: str):
    device = coordinator.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return asdict(device)

@app.post("/devices/{device_id}/heartbeat")
async def device_heartbeat(device_id: str):
    success = coordinator.heartbeat(device_id)
    return {"success": success}

@app.put("/devices/{device_id}/state")
async def update_state(device_id: str, state: str):
    success = coordinator.update_device_state(device_id, DeviceStateCompat(state))
    return {"success": success}

@app.post("/tasks")
async def create_task(request: CreateTaskRequest):
    task_id = await coordinator.create_task(
        request.name,
        request.description,
        request.required_devices,
        request.subtasks
    )
    return {"task_id": task_id}

@app.get("/tasks")
async def list_tasks(state: Optional[str] = None):
    tasks = list(coordinator.tasks.values())
    if state:
        tasks = [t for t in tasks if t.state.value == state]
    return [asdict(t) for t in tasks]

@app.post("/tasks/{task_id}/execute")
async def execute_task(task_id: str):
    success = await coordinator.execute_task(task_id)
    return {"success": success}

@app.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    success = await coordinator.cancel_task(task_id)
    return {"success": success}

@app.post("/groups")
async def create_group(request: CreateGroupRequest):
    group_id = coordinator.create_group(request.name, request.device_ids)
    return {"group_id": group_id}

@app.get("/groups")
async def list_groups():
    return [asdict(g) for g in coordinator.groups.values()]

@app.post("/groups/{group_id}/broadcast")
async def broadcast(group_id: str, request: BroadcastRequest):
    result = await coordinator.broadcast_to_group(group_id, request.action, request.params)
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8071)
