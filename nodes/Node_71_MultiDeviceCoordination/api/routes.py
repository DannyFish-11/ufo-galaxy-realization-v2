"""
Node 71 - API Routes Module
RESTful API 路由定义，提供完整的设备管理、任务调度和系统监控接口
"""
import logging
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core import (
    MultiDeviceCoordinatorEngine, CoordinatorConfig, CoordinatorState,
    Device, DeviceType, DeviceState, DeviceRegistry,
    Capability, ResourceConstraints,
    Task, TaskState, TaskPriority, TaskType, SchedulingStrategy,
    FaultToleranceLayer
)

logger = logging.getLogger(__name__)


# ==================== Request/Response Models ====================

class RegisterDeviceRequest(BaseModel):
    """注册设备请求"""
    device_id: str = Field(..., description="设备唯一标识")
    name: str = Field(..., description="设备名称")
    device_type: str = Field(default="unknown", description="设备类型")
    host: str = Field(default="localhost", description="设备主机地址")
    port: int = Field(default=0, description="设备端口")
    capabilities: List[Dict[str, Any]] = Field(default=[], description="设备能力列表")
    location: Optional[str] = Field(default=None, description="设备位置")
    endpoint: Optional[str] = Field(default=None, description="设备API端点")
    tags: List[str] = Field(default=[], description="设备标签")
    metadata: Dict[str, Any] = Field(default={}, description="设备元数据")

    class Config:
        json_schema_extra = {
            "example": {
                "device_id": "drone-001",
                "name": "Scout Drone Alpha",
                "device_type": "drone",
                "host": "192.168.1.100",
                "port": 8080,
                "capabilities": [{"name": "camera", "version": "2.0"}],
                "location": "warehouse-A",
                "tags": ["outdoor", "camera"]
            }
        }


class UpdateDeviceStateRequest(BaseModel):
    """更新设备状态请求"""
    state: str = Field(..., description="新的设备状态")


class CreateTaskRequest(BaseModel):
    """创建任务请求"""
    name: str = Field(..., description="任务名称")
    description: str = Field(default="", description="任务描述")
    task_type: str = Field(default="command", description="任务类型")
    priority: int = Field(default=5, description="优先级 (1=关键, 5=普通, 10=后台)")
    required_devices: List[str] = Field(default=[], description="需要的设备")
    required_capabilities: List[str] = Field(default=[], description="需要的能力")
    subtasks: List[Dict[str, Any]] = Field(default=[], description="子任务列表")
    params: Dict[str, Any] = Field(default={}, description="任务参数")
    timeout: float = Field(default=300.0, description="超时时间(秒)")
    scheduling_strategy: str = Field(default="priority", description="调度策略")
    metadata: Dict[str, Any] = Field(default={}, description="任务元数据")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Multi-device scan",
                "description": "Scan warehouse using multiple devices",
                "task_type": "command",
                "priority": 2,
                "required_devices": ["drone-001", "camera-002"],
                "subtasks": [
                    {
                        "name": "aerial_scan",
                        "action": "scan",
                        "device_id": "drone-001",
                        "params": {"area": "zone-A"}
                    }
                ],
                "timeout": 600.0
            }
        }


class CreateGroupRequest(BaseModel):
    """创建设备组请求"""
    name: str = Field(..., description="组名称")
    device_ids: List[str] = Field(..., description="设备ID列表")
    metadata: Dict[str, Any] = Field(default={}, description="组元数据")


class BroadcastRequest(BaseModel):
    """广播命令请求"""
    action: str = Field(..., description="动作名称")
    params: Dict[str, Any] = Field(default={}, description="动作参数")


class CoordinateRequest(BaseModel):
    """协调任务请求"""
    subtasks: List[Dict[str, Any]] = Field(..., description="子任务列表")


class SuccessResponse(BaseModel):
    """通用成功响应"""
    success: bool = True
    message: str = ""
    data: Optional[Dict[str, Any]] = None


# ==================== Router Factory ====================

def create_router(engine: MultiDeviceCoordinatorEngine) -> APIRouter:
    """
    创建 API 路由器

    Args:
        engine: 核心协调引擎实例

    Returns:
        FastAPI APIRouter
    """
    router = APIRouter()

    # ==================== 系统端点 ====================

    @router.get("/health", tags=["System"])
    async def health_check():
        """健康检查"""
        return {
            "status": "healthy",
            "node": "Node_71_MultiDeviceCoordination",
            "version": "2.1.0",
            "state": engine._state.value
        }

    @router.get("/status", tags=["System"])
    async def get_status():
        """获取系统状态"""
        return engine.get_status()

    @router.get("/stats", tags=["System"])
    async def get_stats():
        """获取统计信息"""
        return engine.get_stats()

    @router.get("/sync/status", tags=["System"])
    async def get_sync_status():
        """获取同步状态"""
        return engine.get_sync_status()

    @router.get("/discovery/status", tags=["System"])
    async def get_discovery_status():
        """获取设备发现状态"""
        return engine.get_discovery_status()

    @router.get("/fault-tolerance/status", tags=["System"])
    async def get_fault_tolerance_status():
        """获取容错层状态"""
        return engine._fault_tolerance.get_status()

    # ==================== 设备端点 ====================

    @router.post("/devices", tags=["Devices"])
    async def register_device(request: RegisterDeviceRequest):
        """注册新设备"""
        try:
            capabilities = [
                Capability(
                    name=cap.get("name", ""),
                    version=cap.get("version", "1.0"),
                    parameters=cap.get("parameters", {}),
                    priority=cap.get("priority", 5)
                )
                for cap in request.capabilities
            ]

            device = Device(
                device_id=request.device_id,
                name=request.name,
                device_type=DeviceType(request.device_type),
                state=DeviceState.IDLE,
                host=request.host,
                port=request.port,
                capabilities=capabilities,
                location=request.location,
                endpoint=request.endpoint,
                tags=set(request.tags),
                metadata=request.metadata
            )

            success = engine.register_device(device)
            if not success:
                raise HTTPException(
                    status_code=409,
                    detail=f"Device {request.device_id} already registered"
                )

            return {
                "success": True,
                "device_id": device.device_id,
                "message": f"Device {device.name} registered successfully"
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.get("/devices", tags=["Devices"])
    async def list_devices(
        device_type: Optional[str] = Query(None, description="按类型过滤"),
        state: Optional[str] = Query(None, description="按状态过滤"),
        location: Optional[str] = Query(None, description="按位置过滤"),
        capability: Optional[str] = Query(None, description="按能力过滤")
    ):
        """列出所有设备"""
        dt = DeviceType(device_type) if device_type else None
        ds = DeviceState(state) if state else None

        devices = engine.list_devices(device_type=dt, state=ds)

        if location:
            devices = [d for d in devices if d.location == location]
        if capability:
            devices = [d for d in devices if d.has_capability(capability)]

        return [d.to_dict() for d in devices]

    @router.get("/devices/{device_id}", tags=["Devices"])
    async def get_device(device_id: str):
        """获取设备详情"""
        device = engine.get_device(device_id)
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        return device.to_dict()

    @router.delete("/devices/{device_id}", tags=["Devices"])
    async def unregister_device(device_id: str):
        """注销设备"""
        success = engine.unregister_device(device_id)
        if not success:
            raise HTTPException(status_code=404, detail="Device not found")
        return {"success": True, "message": f"Device {device_id} unregistered"}

    @router.post("/devices/{device_id}/heartbeat", tags=["Devices"])
    async def device_heartbeat(device_id: str):
        """设备心跳"""
        device = engine.get_device(device_id)
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        device.update_heartbeat()
        return {"success": True, "device_id": device_id}

    @router.put("/devices/{device_id}/state", tags=["Devices"])
    async def update_device_state(device_id: str, request: UpdateDeviceStateRequest):
        """更新设备状态"""
        try:
            new_state = DeviceState(request.state)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid state: {request.state}. "
                       f"Valid states: {[s.value for s in DeviceState]}"
            )

        success = engine.update_device_state(device_id, new_state)
        if not success:
            raise HTTPException(status_code=404, detail="Device not found")
        return {"success": True, "device_id": device_id, "state": request.state}

    # ==================== 任务端点 ====================

    @router.post("/tasks", tags=["Tasks"])
    async def create_task(request: CreateTaskRequest):
        """创建新任务"""
        try:
            task_id = await engine.create_task(
                name=request.name,
                description=request.description,
                required_devices=request.required_devices,
                subtasks=request.subtasks,
                priority=TaskPriority(request.priority),
                timeout=request.timeout
            )
            return {
                "success": True,
                "task_id": task_id,
                "message": f"Task '{request.name}' created"
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.get("/tasks", tags=["Tasks"])
    async def list_tasks(
        state: Optional[str] = Query(None, description="按状态过滤"),
        limit: int = Query(100, ge=1, le=1000, description="返回数量限制")
    ):
        """列出任务"""
        ts = TaskState(state) if state else None
        tasks = engine.list_tasks(state=ts)
        return [t.to_dict() for t in tasks[:limit]]

    @router.get("/tasks/{task_id}", tags=["Tasks"])
    async def get_task(task_id: str):
        """获取任务详情"""
        task = engine.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task.to_dict()

    @router.post("/tasks/{task_id}/execute", tags=["Tasks"])
    async def execute_task(task_id: str):
        """执行任务"""
        task = engine.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        success = await engine.execute_task(task_id)
        return {"success": success, "task_id": task_id}

    @router.post("/tasks/{task_id}/cancel", tags=["Tasks"])
    async def cancel_task(task_id: str):
        """取消任务"""
        success = await engine.cancel_task(task_id)
        if not success:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"success": True, "task_id": task_id}

    @router.post("/tasks/{task_id}/coordinate", tags=["Tasks"])
    async def coordinate_task(task_id: str, request: CoordinateRequest):
        """协调跨设备任务"""
        result = await engine.coordinate_task(task_id, request.subtasks)
        return result

    # ==================== 设备组端点 ====================

    @router.post("/groups", tags=["Groups"])
    async def create_group(request: CreateGroupRequest):
        """创建设备组"""
        group_id = engine.create_device_group(request.name, request.device_ids)
        return {
            "success": True,
            "group_id": group_id,
            "message": f"Group '{request.name}' created with {len(request.device_ids)} devices"
        }

    @router.get("/groups", tags=["Groups"])
    async def list_groups():
        """列出所有设备组"""
        return {
            group_id: {
                "group_id": group_id,
                "device_ids": device_ids,
                "device_count": len(device_ids)
            }
            for group_id, device_ids in engine._device_groups.items()
        }

    @router.get("/groups/{group_id}", tags=["Groups"])
    async def get_group(group_id: str):
        """获取设备组详情"""
        device_ids = engine.get_device_group(group_id)
        if device_ids is None:
            raise HTTPException(status_code=404, detail="Group not found")
        return {
            "group_id": group_id,
            "device_ids": device_ids,
            "device_count": len(device_ids)
        }

    @router.post("/groups/{group_id}/broadcast", tags=["Groups"])
    async def broadcast_to_group(group_id: str, request: BroadcastRequest):
        """向设备组广播命令"""
        result = await engine.broadcast_to_group(
            group_id, request.action, request.params
        )
        return result

    return router
