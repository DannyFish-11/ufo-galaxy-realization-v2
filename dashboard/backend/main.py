"""
Galaxy Dashboard 后端
====================

使用已有协议:
- core/node_protocol.py
- enhancements/multidevice/device_protocol.py
- nodes/common/mcp_adapter.py

版本: v2.3.23
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# 导入 ASCII 艺术字
try:
    from core.ascii_art import GALAXY_ASCII_MINIMAL
except ImportError:
    GALAXY_ASCII_MINIMAL = "GALAXY - L4 Autonomous Intelligence System"

# 导入整合核心
try:
    from core.galaxy_core import galaxy_core
    GALAXY_CORE_AVAILABLE = True
except ImportError:
    GALAXY_CORE_AVAILABLE = False
    galaxy_core = None

# 导入已有协议
try:
    from core.node_protocol import Message, MessageHeader, MessageType
    NODE_PROTOCOL_AVAILABLE = True
except ImportError:
    NODE_PROTOCOL_AVAILABLE = False

try:
    from enhancements.multidevice.device_protocol import AIPMessage, AIPProtocol
    DEVICE_PROTOCOL_AVAILABLE = True
except ImportError:
    DEVICE_PROTOCOL_AVAILABLE = False

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("Galaxy")

# 打印 ASCII 艺术字
print(GALAXY_ASCII_MINIMAL)

# 创建应用
app = FastAPI(title="Galaxy Dashboard", version="2.3.23")

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
# 静态文件路由
# ============================================================================

@app.get("/")
async def root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Galaxy Dashboard API", "version": "2.3.23"}

# ============================================================================
# ASCII 艺术字 API
# ============================================================================

@app.get("/api/v1/ascii")
async def get_ascii_art(style: str = "minimal"):
    """获取 ASCII 艺术字"""
    return {"ascii": GALAXY_ASCII_MINIMAL}

@app.get("/api/v1/system/info")
async def get_system_info():
    """获取系统信息"""
    info = {
        "name": "Galaxy",
        "version": "2.3.23",
        "description": "L4 Autonomous Intelligence System",
        "ascii": GALAXY_ASCII_MINIMAL,
        "protocols": {
            "node_protocol": NODE_PROTOCOL_AVAILABLE,
            "device_protocol": DEVICE_PROTOCOL_AVAILABLE,
            "galaxy_core": GALAXY_CORE_AVAILABLE
        },
        "timestamp": datetime.now().isoformat()
    }
    
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        status = galaxy_core.get_status()
        info["nodes"] = status["nodes"]
        info["devices"] = status["devices"]
    
    return info

# ============================================================================
# 节点 API - 使用已有协议
# ============================================================================

@app.get("/api/v1/nodes")
async def list_nodes():
    """列出所有节点"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        return {"nodes": galaxy_core.nodes, "total": len(galaxy_core.nodes)}
    return {"nodes": {}, "total": 0}

@app.post("/api/v1/nodes/{node_id}/call")
async def call_node(node_id: str, request: dict):
    """调用节点 - 使用已有协议"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        action = request.get("action", "")
        params = request.get("params", {})
        result = await galaxy_core.call_node(node_id, action, params)
        return result
    return {"success": False, "error": "Galaxy core not available"}

@app.post("/api/v1/mcp/call")
async def mcp_call(request: dict):
    """
    MCP 调用 - 统一入口
    
    通过 Node_04_Router 路由到具体节点
    """
    node_id = request.get("node_id", "04")
    tool = request.get("tool", "")
    params = request.get("params", {})
    
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        result = await galaxy_core.call_node(node_id, tool, params)
        return result
    
    return {"success": False, "error": "Galaxy core not available"}

# ============================================================================
# 设备 API - 使用 device_protocol
# ============================================================================

@app.get("/api/v1/devices")
async def list_devices():
    """列出所有设备"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        return {"devices": list(galaxy_core.devices.values())}
    return {"devices": []}

@app.post("/api/v1/devices/register")
async def register_device(request: dict):
    """注册设备 - 使用 device_protocol"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        device_id = request.get("device_id", "")
        device_type = request.get("device_type", "android")
        name = request.get("device_name", "Device")
        endpoint = request.get("endpoint", "")
        
        result = await galaxy_core.register_device(device_id, device_type, name, endpoint)
        return result
    
    return {"success": False, "error": "Galaxy core not available"}

@app.post("/api/v1/devices/{device_id}/command")
async def send_device_command(device_id: str, request: dict):
    """发送设备命令 - 使用 device_protocol"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        command = request.get("command", "")
        params = request.get("params", {})
        
        result = await galaxy_core.send_device_command(device_id, command, params)
        return result
    
    return {"success": False, "error": "Galaxy core not available"}

# ============================================================================
# 自主能力 API
# ============================================================================

@app.post("/api/v1/learn")
async def autonomous_learn(request: dict):
    """自主学习"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        result = await galaxy_core.autonomous_learn(request)
        return result
    return {"success": False, "error": "Galaxy core not available"}

@app.post("/api/v1/think")
async def autonomous_think(request: dict):
    """自主思考"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        goal = request.get("goal", "")
        context = request.get("context", {})
        result = await galaxy_core.autonomous_think(goal, context)
        return result
    return {"success": False, "error": "Galaxy core not available"}

@app.post("/api/v1/code")
async def autonomous_code(request: dict):
    """自主编程"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        task = request.get("task", "")
        files = request.get("files", [])
        result = await galaxy_core.autonomous_code(task, files)
        return result
    return {"success": False, "error": "Galaxy core not available"}

@app.post("/api/v1/knowledge/query")
async def query_knowledge(request: dict):
    """查询知识库"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        query = request.get("query", "")
        top_k = request.get("top_k", 5)
        result = await galaxy_core.query_knowledge(query, top_k)
        return result
    return {"success": False, "error": "Galaxy core not available"}

# ============================================================================
# 智能对话
# ============================================================================

@app.post("/api/v1/chat")
async def chat(request: dict):
    """
    智能对话 - 统一入口
    
    自动识别意图，调用相应节点
    """
    message = request.get("message", "")
    device_id = request.get("device_id", "")
    
    logger.info(f"Chat: {message[:50]}...")
    
    message_lower = message.lower()
    
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        # 解析意图
        intent = parse_intent(message)
        
        # 根据意图分发
        if intent["type"] == "device_control":
            result = await galaxy_core.send_device_command(
                device_id or "default",
                intent["action"],
                intent["params"]
            )
            return JSONResponse({
                "response": f"✅ 已执行: {intent['action']}",
                "executed": result.get("success", False),
                "timestamp": datetime.now().isoformat()
            })
        
        elif intent["type"] == "learning":
            result = await galaxy_core.autonomous_learn(intent["params"])
            return JSONResponse({
                "response": "✅ 已学习",
                "timestamp": datetime.now().isoformat()
            })
        
        elif intent["type"] == "thinking":
            result = await galaxy_core.autonomous_think(
                intent["params"].get("goal", message)
            )
            return JSONResponse({
                "response": f"✅ 思考完成",
                "timestamp": datetime.now().isoformat()
            })
        
        elif intent["type"] == "coding":
            result = await galaxy_core.autonomous_code(
                intent["params"].get("task", message)
            )
            return JSONResponse({
                "response": "✅ 代码生成完成",
                "timestamp": datetime.now().isoformat()
            })
        
        elif intent["type"] == "knowledge":
            result = await galaxy_core.query_knowledge(message)
            return JSONResponse({
                "response": "✅ 知识检索完成",
                "timestamp": datetime.now().isoformat()
            })
        
        else:
            # 默认通过 Node_50_Transformer 处理
            result = await galaxy_core.call_node("50", "chat", {"message": message})
            return JSONResponse({
                "response": result.get("response", "处理完成"),
                "timestamp": datetime.now().isoformat()
            })
    
    return JSONResponse({
        "response": f"收到: {message}",
        "timestamp": datetime.now().isoformat()
    })


def parse_intent(message: str) -> Dict[str, Any]:
    """解析意图"""
    message_lower = message.lower()
    
    # 设备控制
    if any(kw in message_lower for kw in ["打开", "启动", "open"]):
        return {
            "type": "device_control",
            "action": "open_app",
            "params": {"app_name": extract_app_name(message)}
        }
    
    if any(kw in message_lower for kw in ["截图", "screenshot"]):
        return {
            "type": "device_control",
            "action": "screenshot",
            "params": {}
        }
    
    if any(kw in message_lower for kw in ["滑动", "滚动", "scroll"]):
        direction = "down"
        if "上" in message_lower:
            direction = "up"
        return {
            "type": "device_control",
            "action": "scroll",
            "params": {"direction": direction}
        }
    
    # 学习
    if any(kw in message_lower for kw in ["学习", "记住", "learn"]):
        return {
            "type": "learning",
            "params": {"action": message, "reward": 0.5}
        }
    
    # 思考
    if any(kw in message_lower for kw in ["思考", "分析", "think"]):
        return {
            "type": "thinking",
            "params": {"goal": message}
        }
    
    # 编程
    if any(kw in message_lower for kw in ["写代码", "编程", "code"]):
        return {
            "type": "coding",
            "params": {"task": message}
        }
    
    # 知识
    if any(kw in message_lower for kw in ["查询", "搜索", "知识"]):
        return {
            "type": "knowledge",
            "params": {"query": message}
        }
    
    return {"type": "chat", "params": {"message": message}}


def extract_app_name(message: str) -> str:
    """提取应用名称"""
    apps = ["微信", "淘宝", "抖音", "QQ", "支付宝", "浏览器", "设置"]
    for app in apps:
        if app in message:
            return app
    return ""


# ============================================================================
# WebSocket
# ============================================================================

active_websockets: List[WebSocket] = []

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif message.get("type") == "chat":
                    result = await chat({"message": message.get("content", "")})
                    await websocket.send_json({
                        "type": "chat_response",
                        "content": result.get("response", "")
                    })
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        active_websockets.remove(websocket)

# ============================================================================
# 启动事件
# ============================================================================

@app.on_event("startup")
async def startup_event():
    logger.info("=" * 60)
    print(GALAXY_ASCII_MINIMAL)
    logger.info("Galaxy Dashboard v2.3.23")
    logger.info("=" * 60)
    
    if NODE_PROTOCOL_AVAILABLE:
        logger.info("✅ node_protocol 已加载")
    
    if DEVICE_PROTOCOL_AVAILABLE:
        logger.info("✅ device_protocol 已加载")
    
    if GALAXY_CORE_AVAILABLE:
        logger.info("✅ galaxy_core 已加载")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)


# ============================================================================
# 仓库协调 API
# ============================================================================

# 导入协调层
try:
    from core.repo_coordinator import repo_coordinator
    REPO_COORDINATOR_AVAILABLE = True
except ImportError:
    REPO_COORDINATOR_AVAILABLE = False
    repo_coordinator = None


@app.post("/api/v1/android/register")
async def register_android_device(request: dict):
    """
    注册 Android 设备
    
    Android 仓库通过此接口注册到主仓库
    """
    if REPO_COORDINATOR_AVAILABLE and repo_coordinator:
        device_id = request.get("device_id", "")
        device_info = request.get("device_info", {})
        result = await repo_coordinator.register_android_device(device_id, device_info)
        return result
    return {"success": False, "error": "Repo coordinator not available"}


@app.post("/api/v1/android/unregister")
async def unregister_android_device(request: dict):
    """注销 Android 设备"""
    if REPO_COORDINATOR_AVAILABLE and repo_coordinator:
        device_id = request.get("device_id", "")
        result = await repo_coordinator.unregister_android_device(device_id)
        return result
    return {"success": False, "error": "Repo coordinator not available"}


@app.post("/api/v1/android/heartbeat")
async def android_heartbeat(request: dict):
    """Android 设备心跳"""
    if REPO_COORDINATOR_AVAILABLE and repo_coordinator:
        device_id = request.get("device_id", "")
        result = await repo_coordinator.heartbeat_android_device(device_id)
        return result
    return {"success": False, "error": "Repo coordinator not available"}


@app.get("/api/v1/android/devices")
async def list_android_devices():
    """列出所有 Android 设备"""
    if REPO_COORDINATOR_AVAILABLE and repo_coordinator:
        devices = repo_coordinator.get_android_devices()
        return {"devices": devices, "total": len(devices)}
    return {"devices": [], "total": 0}


@app.post("/api/v1/android/dispatch")
async def dispatch_to_android(request: dict):
    """
    分发 Agent 到 Android 设备
    
    通过 WebSocket 或 HTTP 发送命令
    """
    if REPO_COORDINATOR_AVAILABLE and repo_coordinator:
        device_id = request.get("device_id", "")
        task_type = request.get("task_type", "")
        params = request.get("params", {})
        result = await repo_coordinator.dispatch_agent_to_android(device_id, task_type, params)
        return result
    return {"success": False, "error": "Repo coordinator not available"}


@app.post("/api/v1/android/broadcast")
async def broadcast_to_android(request: dict):
    """广播到所有 Android 设备"""
    if REPO_COORDINATOR_AVAILABLE and repo_coordinator:
        task_type = request.get("task_type", "")
        params = request.get("params", {})
        result = await repo_coordinator.broadcast_to_all_android(task_type, params)
        return result
    return {"success": False, "error": "Repo coordinator not available"}


@app.get("/api/v1/coordinator/status")
async def get_coordinator_status():
    """获取协调器状态"""
    if REPO_COORDINATOR_AVAILABLE and repo_coordinator:
        return repo_coordinator.get_status()
    return {"error": "Repo coordinator not available"}
