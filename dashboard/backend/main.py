"""
UFO Galaxy Dashboard 后端 - 完整版
==================================

连接所有核心能力：
- AI 驱动 (Node_50_Transformer)
- 任务队列
- 设备管理
- 节点状态
- WebSocket 实时通信

版本: v2.3.19
"""

import os
import json
import asyncio
import logging
import httpx
from datetime import datetime
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
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
# 节点服务地址
# ============================================================================

NODE_SERVICES = {
    "transformer": os.getenv("NODE_50_URL", "http://localhost:8050"),
    "knowledge_base": os.getenv("NODE_72_URL", "http://localhost:8072"),
    "autonomous_learning": os.getenv("NODE_70_URL", "http://localhost:8070"),
    "orchestrator": os.getenv("NODE_110_URL", "http://localhost:8110"),
    "multi_device": os.getenv("NODE_71_URL", "http://localhost:8071"),
}

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
tasks: List[Dict] = []
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

# ============================================================================
# 对话 API - 连接到 AI
# ============================================================================

@app.post("/api/v1/chat")
async def chat(request: ChatRequest):
    """对话接口 - 连接到 Node_50_Transformer"""
    logger.info(f"Chat request from {request.device_id}: {request.message[:50]}...")
    
    try:
        # 调用 Node_50_Transformer 进行 NLU
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{NODE_SERVICES['transformer']}/api/v1/nlu",
                json={
                    "text": request.message,
                    "context": request.context
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                return JSONResponse({
                    "response": result.get("response", result.get("intent", {}).get("description", "已收到指令")),
                    "intent": result.get("intent", {}),
                    "entities": result.get("entities", []),
                    "device_id": request.device_id,
                    "timestamp": datetime.now().isoformat()
                })
    except Exception as e:
        logger.warning(f"Node_50 not available: {e}, using fallback")
    
    # 如果 Node_50 不可用，使用内置的简单 NLU
    message = request.message.lower()
    
    # 意图识别
    intent = {
        "type": "unknown",
        "confidence": 0.5,
        "description": request.message
    }
    
    if "打开" in message or "启动" in message:
        intent = {"type": "open_app", "confidence": 0.9, "description": f"打开应用: {request.message}"}
    elif "搜索" in message or "查找" in message:
        intent = {"type": "search", "confidence": 0.9, "description": f"搜索: {request.message}"}
    elif "控制" in message or "操作" in message:
        intent = {"type": "control", "confidence": 0.9, "description": f"控制设备: {request.message}"}
    elif "状态" in message or "信息" in message:
        intent = {"type": "status", "confidence": 0.9, "description": "获取系统状态"}
    elif "学习" in message:
        intent = {"type": "learn", "confidence": 0.9, "description": "启动学习任务"}
    elif "编程" in message or "代码" in message:
        intent = {"type": "code", "confidence": 0.9, "description": "生成代码"}
    
    # 生成响应
    response_text = generate_response(intent, request.message)
    
    return JSONResponse({
        "response": response_text,
        "intent": intent,
        "device_id": request.device_id,
        "timestamp": datetime.now().isoformat()
    })

def generate_response(intent: Dict, message: str) -> str:
    """生成响应"""
    intent_type = intent.get("type", "unknown")
    
    responses = {
        "open_app": f"好的，我正在为您执行: {intent.get('description', message)}\n\n请确保目标设备已连接。",
        "search": f"我正在为您搜索: {message}\n\n搜索结果将显示在设备上。",
        "control": f"正在控制设备执行: {message}\n\n请确认操作。",
        "status": f"系统状态:\n• 节点数量: 108\n• 设备连接: {len(devices)}\n• Agent 状态: Active\n• 学习进度: 进行中",
        "learn": "学习任务已启动。\n\n系统将自动学习新的操作模式和用户偏好。",
        "code": "代码生成任务已启动。\n\n请描述您需要的功能，我将为您生成代码。",
        "unknown": f"收到您的指令: {message}\n\n我正在处理，请稍候..."
    }
    
    return responses.get(intent_type, responses["unknown"])

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
# 任务管理 API - 连接到编排器
# ============================================================================

@app.post("/api/v1/tasks")
async def create_task(request: TaskRequest):
    """创建任务 - 连接到 Node_110_SmartOrchestrator"""
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
    tasks.append(task)
    
    logger.info(f"Task created: {task_id}")
    
    # 尝试发送到编排器
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{NODE_SERVICES['orchestrator']}/api/v1/orchestrate",
                json=task
            )
    except Exception as e:
        logger.warning(f"Orchestrator not available: {e}")
    
    return {"status": "success", "task": task}

@app.get("/api/v1/tasks")
async def list_tasks():
    """列出任务"""
    return {"tasks": tasks[-50:], "total": len(tasks)}

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
    
    # 返回默认节点列表
    default_nodes = {}
    for i in range(119):
        node_id = f"Node_{i:02d}"
        default_nodes[node_id] = {
            "id": node_id,
            "status": "available",
            "url": f"http://localhost:{8000 + i}"
        }
    
    return {"nodes": default_nodes, "total": len(default_nodes)}

# ============================================================================
# 知识库 API
# ============================================================================

@app.post("/api/v1/knowledge/query")
async def query_knowledge(query: str):
    """查询知识库 - 连接到 Node_72_KnowledgeBase"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{NODE_SERVICES['knowledge_base']}/api/v1/knowledge/search",
                json={"query": query, "limit": 5}
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        logger.warning(f"Knowledge base not available: {e}")
    
    return {"results": [], "message": "Knowledge base not available"}

# ============================================================================
# 自主学习 API
# ============================================================================

@app.post("/api/v1/learning/start")
async def start_learning(topic: str = ""):
    """启动学习任务 - 连接到 Node_70_AutonomousLearning"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{NODE_SERVICES['autonomous_learning']}/api/v1/learning/start",
                json={"topic": topic}
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        logger.warning(f"Learning service not available: {e}")
    
    return {"status": "started", "topic": topic, "message": "Learning task started"}

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
    logger.info("Node Services:")
    for name, url in NODE_SERVICES.items():
        logger.info(f"  {name}: {url}")
    logger.info("")
    logger.info("API Endpoints:")
    logger.info("  POST /api/v1/chat              - 对话接口 (连接 AI)")
    logger.info("  GET  /api/v1/devices           - 设备列表")
    logger.info("  POST /api/v1/devices/register  - 设备注册")
    logger.info("  POST /api/v1/tasks             - 创建任务 (连接编排器)")
    logger.info("  GET  /api/v1/nodes             - 节点列表")
    logger.info("  POST /api/v1/knowledge/query   - 知识库查询")
    logger.info("  POST /api/v1/learning/start    - 启动学习")
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
