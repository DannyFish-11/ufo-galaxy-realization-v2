"""
Node 71 - MultiDeviceCoordination (多设备协调节点)
提供多设备协同控制、任务分配和状态同步能力
"""
import os
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 71 - MultiDeviceCoordination", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class DeviceType(str, Enum):
    """设备类型"""
    DRONE = "drone"
    PRINTER_3D = "printer_3d"
    ROBOT = "robot"
    CAMERA = "camera"
    SENSOR = "sensor"
    ACTUATOR = "actuator"
    DISPLAY = "display"
    SPEAKER = "speaker"


class DeviceState(str, Enum):
    """设备状态"""
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    IDLE = "idle"
    ERROR = "error"
    MAINTENANCE = "maintenance"


class TaskState(str, Enum):
    """任务状态"""
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Device:
    """设备"""
    device_id: str
    name: str
    device_type: DeviceType
    state: DeviceState = DeviceState.OFFLINE
    capabilities: List[str] = field(default_factory=list)
    location: Optional[str] = None
    endpoint: Optional[str] = None
    last_heartbeat: Optional[datetime] = None
    current_task: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CoordinatedTask:
    """协调任务"""
    task_id: str
    name: str
    description: str
    required_devices: List[str]  # 设备类型或 ID
    subtasks: List[Dict[str, Any]] = field(default_factory=list)
    state: TaskState = TaskState.PENDING
    assigned_devices: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: float = 0.0
    results: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceGroup:
    """设备组"""
    group_id: str
    name: str
    device_ids: List[str]
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class MultiDeviceCoordinator:
    """多设备协调器"""
    
    def __init__(self):
        self.devices: Dict[str, Device] = {}
        self.tasks: Dict[str, CoordinatedTask] = {}
        self.groups: Dict[str, DeviceGroup] = {}
        self._task_queue: asyncio.Queue = asyncio.Queue()
        self._is_running = False
    
    def register_device(self, device: Device) -> bool:
        """注册设备"""
        self.devices[device.device_id] = device
        logger.info(f"Registered device: {device.device_id} ({device.name})")
        return True
    
    def unregister_device(self, device_id: str) -> bool:
        """注销设备"""
        if device_id in self.devices:
            del self.devices[device_id]
            return True
        return False
    
    def update_device_state(self, device_id: str, state: DeviceState) -> bool:
        """更新设备状态"""
        if device_id not in self.devices:
            return False
        
        self.devices[device_id].state = state
        self.devices[device_id].last_heartbeat = datetime.now()
        return True
    
    def heartbeat(self, device_id: str) -> bool:
        """设备心跳"""
        if device_id not in self.devices:
            return False
        
        device = self.devices[device_id]
        device.last_heartbeat = datetime.now()
        if device.state == DeviceState.OFFLINE:
            device.state = DeviceState.IDLE
        return True
    
    def create_group(self, name: str, device_ids: List[str]) -> str:
        """创建设备组"""
        group = DeviceGroup(
            group_id=str(uuid.uuid4()),
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
        task = CoordinatedTask(
            task_id=str(uuid.uuid4()),
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
        task.state = TaskState.ASSIGNED
        
        # 更新设备状态
        for device_id in available_devices:
            self.devices[device_id].state = DeviceState.BUSY
            self.devices[device_id].current_task = task_id
        
        logger.info(f"Assigned task {task_id} to devices: {available_devices}")
        return True
    
    def _find_available_devices(self, requirements: List[str]) -> List[str]:
        """查找可用设备"""
        available = []
        
        for req in requirements:
            for device in self.devices.values():
                if device.state != DeviceState.IDLE:
                    continue
                
                # 检查是否匹配（按 ID 或类型）
                if device.device_id == req or device.device_type.value == req:
                    if device.device_id not in available:
                        available.append(device.device_id)
                        break
        
        return available
    
    async def execute_task(self, task_id: str) -> bool:
        """执行协调任务"""
        if task_id not in self.tasks:
            return False
        
        task = self.tasks[task_id]
        
        if task.state != TaskState.ASSIGNED:
            # 先分配任务
            if not await self.assign_task(task_id):
                return False
        
        task.state = TaskState.RUNNING
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
            
            task.state = TaskState.COMPLETED
            task.completed_at = datetime.now()
            task.progress = 1.0
            
            logger.info(f"Task {task_id} completed successfully")
            return True
            
        except Exception as e:
            task.state = TaskState.FAILED
            task.results["error"] = str(e)
            logger.error(f"Task {task_id} failed: {e}")
            return False
        
        finally:
            # 释放设备
            for device_id in task.assigned_devices:
                if device_id in self.devices:
                    self.devices[device_id].state = DeviceState.IDLE
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
        task.state = TaskState.CANCELLED
        
        # 释放设备
        for device_id in task.assigned_devices:
            if device_id in self.devices:
                self.devices[device_id].state = DeviceState.IDLE
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
            result = await self._send_command(device_id, action, params)
            results[device_id] = result
        
        return {"success": True, "results": results}
    
    def get_device(self, device_id: str) -> Optional[Device]:
        """获取设备信息"""
        return self.devices.get(device_id)
    
    def list_devices(self, device_type: Optional[DeviceType] = None,
                     state: Optional[DeviceState] = None) -> List[Device]:
        """列出设备"""
        devices = list(self.devices.values())
        
        if device_type:
            devices = [d for d in devices if d.device_type == device_type]
        if state:
            devices = [d for d in devices if d.state == state]
        
        return devices
    
    def get_status(self) -> Dict[str, Any]:
        """获取协调器状态"""
        return {
            "total_devices": len(self.devices),
            "online_devices": sum(1 for d in self.devices.values() if d.state != DeviceState.OFFLINE),
            "busy_devices": sum(1 for d in self.devices.values() if d.state == DeviceState.BUSY),
            "total_tasks": len(self.tasks),
            "running_tasks": sum(1 for t in self.tasks.values() if t.state == TaskState.RUNNING),
            "completed_tasks": sum(1 for t in self.tasks.values() if t.state == TaskState.COMPLETED),
            "device_groups": len(self.groups)
        }


# 全局实例
coordinator = MultiDeviceCoordinator()


# API 模型
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


# API 端点
@app.get("/health")
async def health_check():
    return {"status": "healthy", "node": "Node_71_MultiDeviceCoordination"}

@app.get("/status")
async def get_status():
    return coordinator.get_status()

@app.post("/devices")
async def register_device(request: RegisterDeviceRequest):
    device = Device(
        device_id=request.device_id,
        name=request.name,
        device_type=DeviceType(request.device_type),
        capabilities=request.capabilities,
        location=request.location,
        endpoint=request.endpoint,
        state=DeviceState.IDLE
    )
    coordinator.register_device(device)
    return {"success": True}

@app.get("/devices")
async def list_devices(device_type: Optional[str] = None, state: Optional[str] = None):
    dt = DeviceType(device_type) if device_type else None
    ds = DeviceState(state) if state else None
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
    success = coordinator.update_device_state(device_id, DeviceState(state))
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
