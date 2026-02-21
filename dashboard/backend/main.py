"""
Galaxy Dashboard 后端 - 统一智能体版本
=====================================

集成所有 108 个节点到统一智能体核心

版本: v2.3.22
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
    from core.ascii_art import GALAXY_ASCII_MINIMAL, GALAXY_ASCII, GALAXY_ASCII_LARGE
    ASCII_AVAILABLE = True
except ImportError:
    ASCII_AVAILABLE = False
    GALAXY_ASCII_MINIMAL = "GALAXY - L4 Autonomous Intelligence System"

# 导入统一智能体核心
try:
    from core.unified_agent_core import unified_core, ProtocolType
    UNIFIED_CORE_AVAILABLE = True
except ImportError:
    UNIFIED_CORE_AVAILABLE = False
    unified_core = None

# 导入多协议支持
try:
    from core.multi_protocol_layer import multi_protocol, ProtocolType as MultiProtocolType
    MULTI_PROTOCOL_AVAILABLE = True
except ImportError:
    MULTI_PROTOCOL_AVAILABLE = False

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("Galaxy")

# 打印 ASCII 艺术字
print(GALAXY_ASCII_MINIMAL)

# 创建应用
app = FastAPI(title="Galaxy Dashboard", version="2.3.22")

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
# 状态存储
# ============================================================================

devices: Dict[str, Dict] = {}
active_websockets: List[WebSocket] = []

# ============================================================================
# 静态文件路由
# ============================================================================

@app.get("/")
async def root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Galaxy Dashboard API", "version": "2.3.22"}

# ============================================================================
# ASCII 艺术字 API
# ============================================================================

@app.get("/api/v1/ascii")
async def get_ascii_art(style: str = "minimal"):
    """获取 ASCII 艺术字"""
    if style == "large":
        return {"ascii": GALAXY_ASCII_LARGE}
    elif style == "normal":
        return {"ascii": GALAXY_ASCII}
    else:
        return {"ascii": GALAXY_ASCII_MINIMAL}

@app.get("/api/v1/system/info")
async def get_system_info():
    """获取系统信息"""
    info = {
        "name": "Galaxy",
        "version": "2.3.22",
        "description": "L4 Autonomous Intelligence System - 统一智能体版本",
        "ascii": GALAXY_ASCII_MINIMAL,
        "features": {
            "ai_driven": True,
            "multi_device": True,
            "autonomous_learning": True,
            "autonomous_thinking": True,
            "autonomous_coding": True,
            "knowledge_base": True,
            "database": True,
            "unified_core": UNIFIED_CORE_AVAILABLE,
            "multi_protocol": MULTI_PROTOCOL_AVAILABLE
        },
        "timestamp": datetime.now().isoformat()
    }
    
    if UNIFIED_CORE_AVAILABLE and unified_core:
        status = unified_core.get_status()
        info["nodes"] = status["total_nodes"]
        info["active_nodes"] = status["active_nodes"]
        info["capabilities"] = len(status["capabilities"])
        info["protocols"] = status["protocols_supported"]
    
    return info

# ============================================================================
# 统一智能体 API
# ============================================================================

@app.get("/api/v1/nodes")
async def list_nodes():
    """列出所有节点"""
    if UNIFIED_CORE_AVAILABLE and unified_core:
        nodes = []
        for node_id, node in unified_core.nodes.items():
            nodes.append({
                "node_id": node.node_id,
                "name": node.name,
                "port": node.port,
                "status": node.status.value,
                "capabilities": node.capabilities,
                "endpoint": node.endpoint
            })
        return {"nodes": nodes, "total": len(nodes)}
    return {"nodes": [], "total": 0}

@app.get("/api/v1/nodes/{node_id}")
async def get_node(node_id: str):
    """获取节点详情"""
    if UNIFIED_CORE_AVAILABLE and unified_core:
        node = unified_core.get_node(node_id)
        if node:
            return {
                "node_id": node.node_id,
                "name": node.name,
                "port": node.port,
                "status": node.status.value,
                "capabilities": node.capabilities,
                "endpoint": node.endpoint,
                "last_heartbeat": node.last_heartbeat.isoformat() if node.last_heartbeat else None
            }
    raise HTTPException(status_code=404, detail="Node not found")

@app.post("/api/v1/nodes/{node_id}/call")
async def call_node(node_id: str, request: dict):
    """调用节点"""
    if UNIFIED_CORE_AVAILABLE and unified_core:
        action = request.get("action", "")
        params = request.get("params", {})
        protocol = request.get("protocol", "http")
        
        protocol_type = ProtocolType.HTTP
        if protocol == "websocket":
            protocol_type = ProtocolType.WEBSOCKET
        elif protocol == "aip":
            protocol_type = ProtocolType.AIP
        elif protocol == "local":
            protocol_type = ProtocolType.LOCAL
        
        result = await unified_core.call_node(node_id, action, params, protocol_type)
        return result
    
    return {"success": False, "error": "Unified core not available"}

@app.post("/api/v1/smart-call")
async def smart_call(request: dict):
    """智能调用 - 自动选择最佳节点"""
    if UNIFIED_CORE_AVAILABLE and unified_core:
        capability = request.get("capability", "")
        action = request.get("action", "")
        params = request.get("params", {})
        prefer_local = request.get("prefer_local", True)
        
        result = await unified_core.smart_call(capability, action, params, prefer_local)
        return result
    
    return {"success": False, "error": "Unified core not available"}

# ============================================================================
# Agent 分发 API
# ============================================================================

@app.post("/api/v1/dispatch")
async def dispatch_agent(request: dict):
    """
    分发 Agent 到目标设备
    
    支持本地轻量 Agent 和远处分发
    """
    if UNIFIED_CORE_AVAILABLE and unified_core:
        task_type = request.get("task_type", "")
        target_device = request.get("target_device", "")
        params = request.get("params", {})
        protocol = request.get("protocol", "http")
        
        protocol_type = ProtocolType.HTTP
        if protocol == "websocket":
            protocol_type = ProtocolType.WEBSOCKET
        elif protocol == "aip":
            protocol_type = ProtocolType.AIP
        
        result = await unified_core.dispatch_agent(task_type, target_device, params, protocol_type)
        return result
    
    return {"success": False, "error": "Unified core not available"}

# ============================================================================
# 自主能力 API
# ============================================================================

@app.post("/api/v1/learn")
async def autonomous_learn(request: dict):
    """自主学习"""
    if UNIFIED_CORE_AVAILABLE and unified_core:
        result = await unified_core.autonomous_learn(request)
        return result
    return {"success": False, "error": "Unified core not available"}

@app.post("/api/v1/think")
async def autonomous_think(request: dict):
    """自主思考"""
    if UNIFIED_CORE_AVAILABLE and unified_core:
        goal = request.get("goal", "")
        context = request.get("context", {})
        result = await unified_core.autonomous_think(goal, context)
        return result
    return {"success": False, "error": "Unified core not available"}

@app.post("/api/v1/code")
async def autonomous_code(request: dict):
    """自主编程"""
    if UNIFIED_CORE_AVAILABLE and unified_core:
        task = request.get("task", "")
        files = request.get("files", [])
        result = await unified_core.autonomous_code(task, files)
        return result
    return {"success": False, "error": "Unified core not available"}

@app.post("/api/v1/knowledge/query")
async def query_knowledge(request: dict):
    """查询知识库"""
    if UNIFIED_CORE_AVAILABLE and unified_core:
        query = request.get("query", "")
        top_k = request.get("top_k", 5)
        result = await unified_core.query_knowledge(query, top_k)
        return result
    return {"success": False, "error": "Unified core not available"}

@app.post("/api/v1/knowledge/store")
async def store_knowledge(request: dict):
    """存储知识"""
    if UNIFIED_CORE_AVAILABLE and unified_core:
        content = request.get("content", "")
        metadata = request.get("metadata", {})
        result = await unified_core.store_knowledge(content, metadata)
        return result
    return {"success": False, "error": "Unified core not available"}

# ============================================================================
# 智能体对话
# ============================================================================

@app.post("/api/v1/chat")
async def chat(request: dict):
    """
    智能体对话 - 统一入口
    
    自动识别意图，调用相应节点
    """
    message = request.get("message", "")
    device_id = request.get("device_id", "")
    protocol = request.get("protocol", "http")
    
    logger.info(f"Chat: {message[:50]}...")
    
    message_lower = message.lower()
    
    # 解析意图
    intent = parse_intent(message)
    
    if UNIFIED_CORE_AVAILABLE and unified_core:
        # 根据意图分发
        if intent["type"] == "device_control":
            result = await unified_core.dispatch_agent(
                intent["action"],
                device_id or "default",
                intent["params"],
                ProtocolType.HTTP if protocol == "http" else ProtocolType.WEBSOCKET
            )
            return JSONResponse({
                "response": f"✅ 已执行: {intent['action']}\n\n结果: {result.get('success', False)}",
                "intent": intent,
                "executed": result.get("success", False),
                "timestamp": datetime.now().isoformat()
            })
        
        elif intent["type"] == "learning":
            result = await unified_core.autonomous_learn(intent["params"])
            return JSONResponse({
                "response": f"✅ 已学习: {intent['params'].get('action', '')}",
                "intent": intent,
                "timestamp": datetime.now().isoformat()
            })
        
        elif intent["type"] == "thinking":
            result = await unified_core.autonomous_think(
                intent["params"].get("goal", message),
                intent["params"].get("context", {})
            )
            return JSONResponse({
                "response": f"✅ 思考结果:\n\n{result.get('result', result)}",
                "intent": intent,
                "timestamp": datetime.now().isoformat()
            })
        
        elif intent["type"] == "coding":
            result = await unified_core.autonomous_code(
                intent["params"].get("task", message),
                intent["params"].get("files", [])
            )
            return JSONResponse({
                "response": f"✅ 代码生成完成:\n\n{result.get('code', result)}",
                "intent": intent,
                "timestamp": datetime.now().isoformat()
            })
        
        elif intent["type"] == "knowledge_query":
            result = await unified_core.query_knowledge(
                intent["params"].get("query", message)
            )
            return JSONResponse({
                "response": f"📚 知识检索结果:\n\n{result.get('results', result)}",
                "intent": intent,
                "timestamp": datetime.now().isoformat()
            })
        
        else:
            # 默认使用 LLM 处理
            result = await unified_core.smart_call("chat", "chat", {"message": message})
            return JSONResponse({
                "response": result.get("response", result.get("result", "处理完成")),
                "intent": intent,
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
    
    if any(kw in message_lower for kw in ["输入", "input"]):
        return {
            "type": "device_control",
            "action": "input",
            "params": {"text": extract_input_text(message)}
        }
    
    # 学习
    if any(kw in message_lower for kw in ["学习", "记住", "learn"]):
        return {
            "type": "learning",
            "params": {
                "type": "observation",
                "action": message,
                "reward": 0.5
            }
        }
    
    # 思考
    if any(kw in message_lower for kw in ["思考", "分析", "think"]):
        return {
            "type": "thinking",
            "params": {
                "goal": message
            }
        }
    
    # 编程
    if any(kw in message_lower for kw in ["写代码", "编程", "code"]):
        return {
            "type": "coding",
            "params": {
                "task": message
            }
        }
    
    # 知识查询
    if any(kw in message_lower for kw in ["查询", "搜索", "知识"]):
        return {
            "type": "knowledge_query",
            "params": {
                "query": message
            }
        }
    
    # 默认
    return {
        "type": "chat",
        "action": "chat",
        "params": {"message": message}
    }


def extract_app_name(message: str) -> str:
    """提取应用名称"""
    apps = ["微信", "淘宝", "抖音", "QQ", "支付宝", "浏览器", "设置"]
    for app in apps:
        if app in message:
            return app
    return ""


def extract_input_text(message: str) -> str:
    """提取输入文本"""
    import re
    match = re.search(r"输入[\"'](.+?)[\"']", message)
    if match:
        return match.group(1)
    return ""


# ============================================================================
# 设备管理 API
# ============================================================================

@app.get("/api/v1/devices")
async def list_devices():
    return {"devices": list(devices.values())}

@app.post("/api/v1/devices/register")
async def register_device(request: dict):
    device_id = request.get("device_id", "")
    platform = request.get("device_type", "android")
    name = request.get("device_name", "Device")
    
    device = {
        "id": device_id,
        "type": platform,
        "name": name,
        "status": "online",
        "registered_at": datetime.now().isoformat()
    }
    devices[device_id] = device
    return {"status": "success", "device": device}

# ============================================================================
# WebSocket
# ============================================================================

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
    logger.info("Galaxy Dashboard v2.3.22 - 统一智能体版本")
    logger.info("=" * 60)
    
    if UNIFIED_CORE_AVAILABLE:
        logger.info("✅ 统一智能体核心已启用")
        status = unified_core.get_status()
        logger.info(f"   节点数: {status['total_nodes']}")
        logger.info(f"   能力数: {len(status['capabilities'])}")
    
    if MULTI_PROTOCOL_AVAILABLE:
        logger.info("✅ 多协议支持已启用")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
