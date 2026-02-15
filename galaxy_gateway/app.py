"""
UFO Galaxy Gateway - 主应用入口

FastAPI 应用，提供:
1. WebSocket 端点供设备连接
2. REST API 供管理和任务提交
3. 健康检查端点
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .protocol import (
    AIPMessage, MessageType, DeviceType, DeviceInfo,
    parse_message, create_error_message
)
from .transport import WebSocketManager
from .handlers import DeviceManager, MessageHandler
from .orchestrator import TaskOrchestrator, TaskPriority

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 全局组件
device_manager: Optional[DeviceManager] = None
message_handler: Optional[MessageHandler] = None
websocket_manager: Optional[WebSocketManager] = None
task_orchestrator: Optional[TaskOrchestrator] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global device_manager, message_handler, websocket_manager, task_orchestrator
    
    # 启动时初始化
    logger.info("Initializing UFO Galaxy Gateway...")
    
    device_manager = DeviceManager()
    message_handler = MessageHandler(device_manager)
    
    async def on_message(device_id: str, message: AIPMessage):
        response = await message_handler.handle_message(device_id, message)
        if response:
            await websocket_manager.send_message(device_id, response)
    
    async def on_connect(device_id: str):
        logger.info(f"Device connected: {device_id}")
    
    async def on_disconnect(device_id: str):
        logger.info(f"Device disconnected: {device_id}")
        device_manager.update_device_status(device_id, "offline")
    
    websocket_manager = WebSocketManager(
        heartbeat_interval=30,
        heartbeat_timeout=90,
        on_message=on_message,
        on_connect=on_connect,
        on_disconnect=on_disconnect
    )
    
    task_orchestrator = TaskOrchestrator(
        device_manager=device_manager,
        message_handler=message_handler,
        websocket_manager=websocket_manager
    )
    
    await websocket_manager.start()
    await task_orchestrator.start()
    
    logger.info("UFO Galaxy Gateway initialized successfully")
    
    yield
    
    # 关闭时清理
    logger.info("Shutting down UFO Galaxy Gateway...")
    await task_orchestrator.stop()
    await websocket_manager.stop()
    logger.info("UFO Galaxy Gateway shut down")


# 创建 FastAPI 应用
app = FastAPI(
    title="UFO Galaxy Gateway",
    description="跨平台分布式 Agent 网关",
    version="3.0.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# WebSocket 端点
# ============================================================================

@app.websocket("/ws/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str):
    """设备 WebSocket 连接端点"""
    await websocket_manager.handle_connection(websocket, device_id)


@app.websocket("/ws")
async def websocket_endpoint_auto(websocket: WebSocket, device_id: str = Query(None)):
    """自动分配设备 ID 的 WebSocket 端点"""
    if not device_id:
        import uuid
        device_id = str(uuid.uuid4())
    await websocket_manager.handle_connection(websocket, device_id)


# ============================================================================
# REST API 端点
# ============================================================================

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "version": "3.0.0",
        "devices_connected": websocket_manager.get_device_count() if websocket_manager else 0
    }


@app.get("/api/devices")
async def get_devices():
    """获取所有设备"""
    if not device_manager:
        raise HTTPException(status_code=503, detail="Service not ready")
    return device_manager.to_dict()


@app.get("/api/devices/{device_id}")
async def get_device(device_id: str):
    """获取单个设备信息"""
    if not device_manager:
        raise HTTPException(status_code=503, detail="Service not ready")
    
    device = device_manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    return {
        "device": device.model_dump(),
        "is_connected": websocket_manager.is_device_connected(device_id) if websocket_manager else False
    }


@app.get("/api/devices/connected")
async def get_connected_devices():
    """获取已连接设备列表"""
    if not websocket_manager:
        raise HTTPException(status_code=503, detail="Service not ready")
    
    return {
        "connected_devices": websocket_manager.get_connected_devices(),
        "count": websocket_manager.get_device_count()
    }


# 任务提交请求模型
class TaskRequest(BaseModel):
    user_request: str
    target_device: Optional[str] = None
    priority: str = "normal"
    timeout: int = 300


@app.post("/api/tasks")
async def submit_task(request: TaskRequest):
    """提交任务"""
    if not task_orchestrator:
        raise HTTPException(status_code=503, detail="Service not ready")
    
    priority_map = {
        "low": TaskPriority.LOW,
        "normal": TaskPriority.NORMAL,
        "high": TaskPriority.HIGH,
        "urgent": TaskPriority.URGENT
    }
    priority = priority_map.get(request.priority.lower(), TaskPriority.NORMAL)
    
    task = await task_orchestrator.submit_task(
        user_request=request.user_request,
        target_device=request.target_device,
        priority=priority,
        timeout=request.timeout
    )
    
    return {
        "task_id": task.task_id,
        "status": task.status.value,
        "assigned_device": task.assigned_device
    }


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    """获取任务状态"""
    if not task_orchestrator:
        raise HTTPException(status_code=503, detail="Service not ready")
    
    task = task_orchestrator.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return {
        "task_id": task.task_id,
        "user_request": task.user_request,
        "status": task.status.value,
        "assigned_device": task.assigned_device,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "error": task.error,
        "results": [r.model_dump() for r in task.results]
    }


@app.get("/api/tasks")
async def get_all_tasks():
    """获取所有任务"""
    if not task_orchestrator:
        raise HTTPException(status_code=503, detail="Service not ready")
    
    tasks = task_orchestrator.get_all_tasks()
    return {
        "total": len(tasks),
        "tasks": [
            {
                "task_id": t.task_id,
                "user_request": t.user_request[:100],
                "status": t.status.value,
                "assigned_device": t.assigned_device
            }
            for t in tasks
        ]
    }


@app.delete("/api/tasks/{task_id}")
async def cancel_task(task_id: str):
    """取消任务"""
    if not task_orchestrator:
        raise HTTPException(status_code=503, detail="Service not ready")
    
    success = await task_orchestrator.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot cancel task")
    
    return {"status": "cancelled", "task_id": task_id}


# 发送命令请求模型
class CommandRequest(BaseModel):
    device_id: str
    command_type: str  # click, swipe, input, screenshot, etc.
    parameters: dict = {}


@app.post("/api/commands")
async def send_command(request: CommandRequest):
    """直接发送命令到设备"""
    if not websocket_manager:
        raise HTTPException(status_code=503, detail="Service not ready")
    
    if not websocket_manager.is_device_connected(request.device_id):
        raise HTTPException(status_code=404, detail="Device not connected")
    
    # 构建消息
    message_type_map = {
        "click": MessageType.GUI_CLICK,
        "swipe": MessageType.GUI_SWIPE,
        "input": MessageType.GUI_INPUT,
        "scroll": MessageType.GUI_SCROLL,
        "screenshot": MessageType.GUI_SCREENSHOT,
        "screen_content": MessageType.GUI_SCREEN_CONTENT
    }
    
    msg_type = message_type_map.get(request.command_type)
    if not msg_type:
        raise HTTPException(status_code=400, detail=f"Unknown command type: {request.command_type}")
    
    message = AIPMessage(
        type=msg_type,
        device_id=request.device_id,
        payload=request.parameters
    )
    
    success = await websocket_manager.send_message(request.device_id, message)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send command")
    
    return {"status": "sent", "message_id": message.message_id}


# ============================================================================
# 主入口
# ============================================================================

def main():
    """主入口函数"""
    import uvicorn
    
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    
    logger.info(f"Starting UFO Galaxy Gateway on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
