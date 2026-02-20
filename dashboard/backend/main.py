"""
UFO Galaxy Dashboard 后端
==========================

提供完整的 API 服务：
- 设备管理
- 对话接口
- 任务管理
- 节点状态
- WebSocket 实时通信

版本: v2.3.19
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("UFO-Galaxy-Dashboard")

# 创建应用
app = FastAPI(title="UFO³ Galaxy Dashboard", version="2.3.19")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "public")

# ============================================================================
# 数据模型
# ============================================================================

class ChatRequest(BaseModel):
    message: str
    device_id: str = ""
    context: List[Dict[str, str]] = []

class DeviceRegisterRequest(BaseModel):
    device_id: str
    device_type: str = "android"
    device_name: str = ""
    capabilities: List[str] = []

class TaskRequest(BaseModel):
    task_type: str
    payload: Dict[str, Any] = {}
    device_id: str = ""
    priority: int = 5

# ============================================================================
# 状态存储
# ============================================================================

devices: Dict[str, Dict] = {}
nodes: Dict[str, Dict] = {}
active_websockets: List[WebSocket] = []

# ============================================================================
# 静态文件路由
# ============================================================================

@app.get("/")
async def root():
    """返回前端页面"""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "UFO³ Galaxy Dashboard API", "version": "2.3.19"}

@app.get("/api")
async def api_info():
    """API 信息"""
    return {
        "name": "UFO³ Galaxy Dashboard API",
        "version": "2.3.19",
        "endpoints": {
            "chat": "/api/v1/chat",
            "devices": "/api/v1/devices",
            "tasks": "/api/v1/tasks",
            "nodes": "/api/v1/nodes",
            "websocket": "/ws"
        }
    }

# ============================================================================
# 对话 API
# ============================================================================

@app.post("/api/v1/chat")
async def chat(request: ChatRequest):
    """对话接口"""
    logger.info(f"Chat request from {request.device_id}: {request.message[:50]}...")
    
    # TODO: 连接到 Node_50_Transformer 进行真正的 NLU
    # 目前返回模拟响应
    
    message = request.message.lower()
    
    # 简单的意图识别
    if "打开" in message or "启动" in message:
        response = f"好的，我正在为您执行: {request.message}\n\n请确保目标设备已连接。"
    elif "搜索" in message or "查找" in message:
        response = f"我正在为您搜索: {request.message}\n\n搜索结果将显示在设备上。"
    elif "控制" in message or "操作" in message:
        response = f"正在控制设备执行: {request.message}\n\n请确认操作。"
    elif "状态" in message or "信息" in message:
        response = f"系统状态:\n• 节点数量: 108\n• 设备连接: {len(devices)}\n• Agent 状态: Active"
    elif "帮助" in message or "help" in message:
        response = """我可以帮你：

📱 设备控制
• 打开/关闭应用
• 控制手机、平板、电脑
• 截图、录屏

🔍 信息查询
• 搜索网络
• 查询天气、新闻
• 获取设备状态

🤖 智能任务
• 复杂任务编排
• 跨设备协同
• 自动化流程

请告诉我你想做什么？"""
    else:
        response = f"收到您的指令: {request.message}\n\n我正在处理，请稍候..."
    
    return JSONResponse({
        "response": response,
        "device_id": request.device_id,
        "timestamp": datetime.now().isoformat()
    })

# ============================================================================
# 设备管理 API
# ============================================================================

@app.get("/api/v1/devices")
async def list_devices():
    """列出所有设备"""
    return {
        "devices": list(devices.values()),
        "total": len(devices)
    }

@app.post("/api/v1/devices/register")
async def register_device(request: DeviceRegisterRequest):
    """注册设备"""
    device = {
        "id": request.device_id,
        "type": request.device_type,
        "name": request.device_name or f"Device-{request.device_id[:8]}",
        "capabilities": request.capabilities,
        "status": "online",
        "registered_at": datetime.now().isoformat()
    }
    devices[request.device_id] = device
    logger.info(f"Device registered: {request.device_id}")
    
    # 广播设备上线
    await broadcast_message({
        "type": "device_online",
        "device": device
    })
    
    return {"status": "success", "device": device}

@app.delete("/api/v1/devices/{device_id}")
async def unregister_device(device_id: str):
    """注销设备"""
    if device_id in devices:
        del devices[device_id]
        logger.info(f"Device unregistered: {device_id}")
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Device not found")

# ============================================================================
# 任务管理 API
# ============================================================================

@app.post("/api/v1/tasks")
async def create_task(request: TaskRequest):
    """创建任务"""
    task_id = f"task-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    task = {
        "id": task_id,
        "type": request.task_type,
        "payload": request.payload,
        "device_id": request.device_id,
        "priority": request.priority,
        "status": "pending",
        "created_at": datetime.now().isoformat()
    }
    
    logger.info(f"Task created: {task_id}")
    
    # TODO: 发送到任务队列
    
    return {"status": "success", "task": task}

@app.get("/api/v1/tasks")
async def list_tasks():
    """列出任务"""
    # TODO: 从任务队列获取
    return {"tasks": [], "total": 0}

# ============================================================================
# 节点管理 API
# ============================================================================

@app.get("/api/v1/nodes")
async def list_nodes():
    """列出所有节点"""
    # 从配置加载节点
    try:
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "config", "node_registry.json")
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
                return {
                    "nodes": config.get("nodes", {}),
                    "total": len(config.get("nodes", {}))
                }
    except Exception as e:
        logger.error(f"Failed to load nodes: {e}")
    
    return {"nodes": {}, "total": 0}

# ============================================================================
# WebSocket
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 端点"""
    await websocket.accept()
    active_websockets.append(websocket)
    logger.info(f"WebSocket connected, total: {len(active_websockets)}")
    
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                await handle_websocket_message(websocket, message)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON"})
    except WebSocketDisconnect:
        active_websockets.remove(websocket)
        logger.info(f"WebSocket disconnected, total: {len(active_websockets)}")

async def handle_websocket_message(websocket: WebSocket, message: Dict):
    """处理 WebSocket 消息"""
    msg_type = message.get("type", "")
    
    if msg_type == "ping":
        await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})
    elif msg_type == "chat":
        # 转发到对话 API
        request = ChatRequest(
            message=message.get("content", ""),
            device_id=message.get("device_id", "")
        )
        response = await chat(request)
        await websocket.send_json({
            "type": "chat_response",
            "content": response.get("response", ""),
            "timestamp": datetime.now().isoformat()
        })
    else:
        await websocket.send_json({"type": "ack", "message": f"Received: {msg_type}"})

async def broadcast_message(message: Dict):
    """广播消息到所有 WebSocket"""
    for ws in active_websockets:
        try:
            await ws.send_json(message)
        except:
            pass

# ============================================================================
# 启动事件
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """启动事件"""
    logger.info("=" * 60)
    logger.info("UFO³ Galaxy Dashboard Starting...")
    logger.info("=" * 60)
    logger.info(f"Version: 2.3.19")
    logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("")
    logger.info("API Endpoints:")
    logger.info("  POST /api/v1/chat              - 对话接口")
    logger.info("  GET  /api/v1/devices           - 设备列表")
    logger.info("  POST /api/v1/devices/register  - 设备注册")
    logger.info("  POST /api/v1/tasks             - 创建任务")
    logger.info("  GET  /api/v1/nodes             - 节点列表")
    logger.info("  WS   /ws                       - WebSocket")
    logger.info("=" * 60)

@app.on_event("shutdown")
async def shutdown_event():
    """关闭事件"""
    logger.info("Dashboard shutdown complete")

# ============================================================================
# 主入口
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)
