"""
Node 71 - MultiDeviceCoordination (多设备协调节点)
提供多设备协同控制、任务分配和状态同步能力

修复: 真正调用设备控制服务执行操作
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
import httpx
from nodes.common.cors_config import get_cors_origins

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 71 - MultiDeviceCoordination", version="2.1.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


# 统一设备类型 — 从 core.device_types 导入（单一事实来源）
from core.device_types import DeviceType  # noqa: F811,E402


from core.device_types import DeviceStatus  # noqa: F811,E402
from core.schemas.device import DeviceModel  # noqa: E402


class DeviceState(str, Enum):
    """设备状态 — Node_71 扩展状态（含 IDLE/MAINTENANCE），向下兼容 DeviceStatus。"""
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
    """设备 — Node_71 运行时包装层。

    内部委托到 DeviceModel（Pydantic V2 统一模型），
    但保留 state/endpoint 等 Node_71 特有字段。
    """
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

    def to_unified_model(self) -> DeviceModel:
        """转换为统一 DeviceModel。"""
        from core.schemas.device import DeviceCapabilityModel
        # 映射 DeviceState → DeviceStatus
        status_map = {
            DeviceState.ONLINE: DeviceStatus.ONLINE,
            DeviceState.OFFLINE: DeviceStatus.OFFLINE,
            DeviceState.BUSY: DeviceStatus.BUSY,
            DeviceState.IDLE: DeviceStatus.ONLINE,
            DeviceState.ERROR: DeviceStatus.ERROR,
            DeviceState.MAINTENANCE: DeviceStatus.BUSY,
        }
        return DeviceModel(
            device_id=self.device_id,
            name=self.name,
            device_type=self.device_type,
            status=status_map.get(self.state, DeviceStatus.UNKNOWN),
            capabilities=[DeviceCapabilityModel(name=c) for c in self.capabilities],
            location=self.location or "",
            endpoint=self.endpoint or "",
            current_task=self.current_task,
            metadata=self.metadata,
            last_heartbeat=self.last_heartbeat.timestamp() if self.last_heartbeat else 0.0,
        )

    @classmethod
    def from_unified_model(cls, model: DeviceModel) -> "Device":
        """从统一 DeviceModel 创建 Node_71 Device。"""
        status_map = {
            DeviceStatus.ONLINE: DeviceState.ONLINE,
            DeviceStatus.OFFLINE: DeviceState.OFFLINE,
            DeviceStatus.BUSY: DeviceState.BUSY,
            DeviceStatus.ERROR: DeviceState.ERROR,
            DeviceStatus.UNKNOWN: DeviceState.OFFLINE,
        }
        return cls(
            device_id=model.device_id,
            name=model.name,
            device_type=model.device_type,
            state=status_map.get(model.status, DeviceState.OFFLINE),
            capabilities=model.capability_names(),
            location=model.location,
            endpoint=model.endpoint,
            current_task=model.current_task,
            metadata=model.metadata,
            last_heartbeat=datetime.fromtimestamp(model.last_heartbeat) if model.last_heartbeat else None,
        )


@dataclass
class CoordinatedTask:
    """协调任务"""
    task_id: str
    name: str
    description: str
    required_devices: List[str]
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
    """多设备协调器 - 真正执行设备操作"""
    
    def __init__(self):
        self.devices: Dict[str, Device] = {}
        self.tasks: Dict[str, CoordinatedTask] = {}
        self.groups: Dict[str, DeviceGroup] = {}
        self._task_queue: asyncio.Queue = asyncio.Queue()
        self._is_running = False
        
        # 设备控制服务地址 — 优先从 node registry 查找，env-var 为 fallback
        self.device_control_url = self._resolve_node_url(
            "Node_92_AutoControl", "DEVICE_CONTROL_URL", "http://localhost:8092"
        )
        self.auto_control_url = self._resolve_node_url(
            "Node_92_AutoControl", "NODE_92_URL", "http://localhost:8092"
        )
        
        # HTTP 客户端
        self._client: Optional[httpx.AsyncClient] = None
    
    @staticmethod
    def _resolve_node_url(node_id: str, env_var: str, default: str) -> str:
        """Resolve a node URL: registry → env var → default"""
        try:
            from core.node_registry import NodeRegistry
            registry = NodeRegistry.get_instance() if hasattr(NodeRegistry, 'get_instance') else None
            if registry:
                node = registry.get_node(node_id)
                if node and node.config.get("url"):
                    return node.config["url"]
        except Exception:
            pass
        return os.getenv(env_var, default)

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client
    
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
        """执行协调任务 - 真正调用设备控制"""
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
                
                # 真正发送命令到设备
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
        """
        发送命令到设备 - 真正调用设备控制服务
        
        支持的操作:
        - click: 点击
        - input: 输入
        - scroll: 滚动
        - screenshot: 截图
        - open_app: 打开应用
        - press_key: 按键
        """
        if device_id not in self.devices:
            return {"success": False, "error": "Device not found"}
        
        device = self.devices[device_id]
        
        try:
            client = await self._get_client()
            
            # 根据操作类型调用不同的 API
            if action == "click":
                response = await client.post(
                    f"{self.auto_control_url}/click",
                    json={
                        "device_id": device_id,
                        "platform": device.device_type.value,
                        "x": params.get("x", 0),
                        "y": params.get("y", 0),
                        "clicks": params.get("clicks", 1)
                    }
                )
            
            elif action == "input":
                response = await client.post(
                    f"{self.auto_control_url}/input",
                    json={
                        "device_id": device_id,
                        "platform": device.device_type.value,
                        "text": params.get("text", "")
                    }
                )
            
            elif action == "scroll":
                response = await client.post(
                    f"{self.auto_control_url}/scroll",
                    json={
                        "device_id": device_id,
                        "platform": device.device_type.value,
                        "direction": params.get("direction", "down"),
                        "amount": params.get("amount", 500)
                    }
                )
            
            elif action == "screenshot":
                response = await client.post(
                    f"{self.auto_control_url}/screenshot",
                    json={
                        "device_id": device_id,
                        "platform": device.device_type.value
                    }
                )
            
            elif action == "open_app":
                response = await client.post(
                    f"{self.auto_control_url}/open_app",
                    json={
                        "device_id": device_id,
                        "platform": device.device_type.value,
                        "app_name": params.get("app_name", "")
                    }
                )
            
            elif action == "press_key":
                response = await client.post(
                    f"{self.auto_control_url}/press_key",
                    json={
                        "device_id": device_id,
                        "platform": device.device_type.value,
                        "key": params.get("key", "")
                    }
                )
            
            else:
                # 通用命令
                response = await client.post(
                    f"{self.auto_control_url}/execute",
                    json={
                        "device_id": device_id,
                        "action": action,
                        "params": params
                    }
                )
            
            result = response.json()
            logger.info(f"Command sent to {device_id}: {action} -> {result.get('success', False)}")
            return result
        
        except Exception as e:
            logger.error(f"Failed to send command to {device_id}: {e}")
            return {"success": False, "error": str(e)}
    
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
        """广播命令到设备组"""
        if group_id not in self.groups:
            return {"success": False, "error": "Group not found"}
        
        group = self.groups[group_id]
        results = {}
        
        for device_id in group.device_ids:
            if device_id in self.devices:
                result = await self._send_command(device_id, action, params)
                results[device_id] = result
        
        return {"success": True, "results": results}
    
    async def execute_parallel(self, commands: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        并行执行多个设备命令
        
        示例:
        commands = [
            {"device_id": "phone_1", "action": "open_app", "params": {"app_name": "微信"}},
            {"device_id": "phone_2", "action": "screenshot", "params": {}},
            {"device_id": "pc_1", "action": "click", "params": {"x": 100, "y": 200}}
        ]
        """
        tasks = []
        for cmd in commands:
            device_id = cmd.get("device_id")
            action = cmd.get("action")
            params = cmd.get("params", {})
            tasks.append(self._send_command(device_id, action, params))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return {
            "success": True,
            "results": {
                cmd["device_id"]: result if not isinstance(result, Exception) else {"success": False, "error": str(result)}
                for cmd, result in zip(commands, results)
            }
        }
    
    def get_device(self, device_id: str) -> Optional[Device]:
        """获取设备"""
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
    
    def get_task(self, task_id: str) -> Optional[CoordinatedTask]:
        """获取任务"""
        return self.tasks.get(task_id)
    
    def list_tasks(self, state: Optional[TaskState] = None) -> List[CoordinatedTask]:
        """列出任务"""
        tasks = list(self.tasks.values())
        
        if state:
            tasks = [t for t in tasks if t.state == state]
        
        return tasks
    
    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        return {
            "devices": len(self.devices),
            "online_devices": sum(1 for d in self.devices.values() if d.state in [DeviceState.ONLINE, DeviceState.IDLE]),
            "busy_devices": sum(1 for d in self.devices.values() if d.state == DeviceState.BUSY),
            "tasks": len(self.tasks),
            "running_tasks": sum(1 for t in self.tasks.values() if t.state == TaskState.RUNNING),
            "groups": len(self.groups),
            "devices_by_type": {
                dt.value: sum(1 for d in self.devices.values() if d.device_type == dt)
                for dt in DeviceType
            }
        }


# 全局实例
coordinator = MultiDeviceCoordinator()


# API 模型
class RegisterDeviceRequest(BaseModel):
    device_id: str
    name: str
    device_type: str
    capabilities: List[str] = []
    endpoint: Optional[str] = None
    metadata: Dict[str, Any] = {}


class CreateTaskRequest(BaseModel):
    name: str
    description: str
    required_devices: List[str]
    subtasks: List[Dict[str, Any]] = []


class CreateGroupRequest(BaseModel):
    name: str
    device_ids: List[str]


class ExecuteParallelRequest(BaseModel):
    commands: List[Dict[str, Any]]


# API 端点
@app.get("/health")
async def health_check():
    return {"status": "healthy", "node": "Node_71_MultiDeviceCoordination"}


@app.get("/status")
async def get_status():
    return coordinator.get_status()


# 设备管理
@app.post("/devices")
async def register_device(request: RegisterDeviceRequest):
    device = Device(
        device_id=request.device_id,
        name=request.name,
        device_type=DeviceType(request.device_type),
        capabilities=request.capabilities,
        endpoint=request.endpoint,
        metadata=request.metadata,
        state=DeviceState.IDLE
    )
    coordinator.register_device(device)
    return {"success": True, "device_id": device.device_id}


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


@app.delete("/devices/{device_id}")
async def unregister_device(device_id: str):
    success = coordinator.unregister_device(device_id)
    return {"success": success}


# 任务管理
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
    ts = TaskState(state) if state else None
    tasks = coordinator.list_tasks(ts)
    return [asdict(t) for t in tasks]


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    task = coordinator.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return asdict(task)


@app.post("/tasks/{task_id}/execute")
async def execute_task(task_id: str):
    success = await coordinator.execute_task(task_id)
    return {"success": success}


@app.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    success = await coordinator.cancel_task(task_id)
    return {"success": success}


# 设备组
@app.post("/groups")
async def create_group(request: CreateGroupRequest):
    group_id = coordinator.create_group(request.name, request.device_ids)
    return {"group_id": group_id}


@app.post("/groups/{group_id}/broadcast")
async def broadcast_to_group(group_id: str, action: str, params: Dict[str, Any] = {}):
    result = await coordinator.broadcast_to_group(group_id, action, params)
    return result


# 并行执行
@app.post("/execute/parallel")
async def execute_parallel(request: ExecuteParallelRequest):
    """并行执行多个设备命令"""
    result = await coordinator.execute_parallel(request.commands)
    return result


@app.post("/execute/all")
async def execute_on_all_devices(action: str, params: Dict[str, Any] = {}):
    """在所有设备上执行相同命令"""
    commands = [
        {"device_id": device_id, "action": action, "params": params}
        for device_id in coordinator.devices.keys()
    ]
    result = await coordinator.execute_parallel(commands)
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8071)
