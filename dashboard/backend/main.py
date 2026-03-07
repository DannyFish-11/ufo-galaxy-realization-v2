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

try:
    from core.unified_response import UnifiedChatResponse
except ImportError:
    # Fallback: define a minimal UnifiedChatResponse for standalone mode
    from pydantic import BaseModel as _BaseModel
    class UnifiedChatResponse(_BaseModel):
        success: bool = True
        response: str = ""
        intent: str = ""
        confidence: float = 0.0
        mode: str = "chat"
        suggestions: list = []
        data: dict = {}
        error: str = ""
        session_id: str = ""
from nodes.common.cors_config import get_cors_origins

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
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
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "public")

# 挂载静态文件目录（CSS/JS/图片等资源）
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

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
# Agent API
# ============================================================================

@app.get("/api/v1/agents")
async def list_agents():
    """列出所有 Agent"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        agents = galaxy_core.agents if hasattr(galaxy_core, "agents") else {}
        return {"agents": list(agents.values()) if isinstance(agents, dict) else agents}
    return {"agents": []}

# ============================================================================
# LLM 提供商 API
# ============================================================================

@app.get("/api/v1/llm/providers")
async def list_llm_providers():
    """列出可用的 LLM 提供商"""
    providers = []
    llm_env_map = [
        ("openai", "OPENAI_API_KEY", "gpt-4o", 8, 9),
        ("anthropic", "ANTHROPIC_API_KEY", "claude-3-5-sonnet-20241022", 7, 10),
        ("deepseek", "DEEPSEEK_API_KEY", "deepseek-chat", 9, 8),
        ("zhipu", "ZHIPU_API_KEY", "glm-4", 8, 8),
        ("groq", "GROQ_API_KEY", "llama-3.3-70b-versatile", 10, 8),
        ("gemini", "GEMINI_API_KEY", "gemini-1.5-pro", 8, 9),
    ]
    for provider, env_key, model, speed, quality in llm_env_map:
        providers.append({
            "provider": provider,
            "model": model,
            "speed_score": speed,
            "quality_score": quality,
            "available": bool(os.environ.get(env_key, "")),
        })
    return {"providers": providers}

# ============================================================================
# 统一聊天 API (/api/v1/chat)
# ============================================================================

@app.post("/api/v1/chat")
async def chat_unified(request: dict):
    """统一聊天入口 - 与 /api/v1/dashboard/chat 功能相同"""
    return await chat(request)

# ============================================================================
# 并行执行 API
# ============================================================================

@app.post("/api/v1/execute/parallel")
async def execute_parallel(request: dict):
    """并行执行多设备命令"""
    commands = request.get("commands", [])
    results = {}
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        tasks = []
        for cmd in commands:
            device_id = cmd.get("device_id", "")
            action = cmd.get("action", "")
            params = cmd.get("params", {})
            tasks.append(galaxy_core.send_device_command(device_id, action, params))
        if tasks:
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            for cmd, result in zip(commands, task_results):
                device_id = cmd.get("device_id", "")
                results[device_id] = result if not isinstance(result, Exception) else {"success": False, "error": str(result)}
        return {"success": True, "results": results}
    # 无 galaxy_core 时返回空结果
    for cmd in commands:
        results[cmd.get("device_id", "")] = {"success": False, "error": "Galaxy core not available"}
    return {"success": False, "results": results}

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

async def get_parsed_intent_modern(message: str, context: Optional[List] = None) -> Optional[Dict[str, Any]]:
    """
    使用 core.ai_intent.IntentParser 进行意图解析（现代版）

    返回与旧 parse_intent() 兼容的 dict 格式，失败时返回 None。
    """
    try:
        from core.ai_intent import get_intent_parser
        parser = get_intent_parser()
        ctx = {"history": context} if context else None
        parsed = await parser.parse(message, ctx)
        # 映射 ParsedIntent → 旧 dict 格式
        intent_type = parsed.intent
        action = parsed.command
        params = parsed.params
        # 保持旧代码分发可用的 type/action 结构
        return {
            "type": intent_type,
            "action": action,
            "params": params,
            "confidence": parsed.confidence,
            "suggestions": parsed.suggestions,
            "targets": parsed.targets,
        }
    except Exception as e:
        logger.debug(f"Modern intent parser failed, will fallback: {e}")
        return None


@app.post("/api/v1/dashboard/chat")
async def chat(request: dict):
    """
    Dashboard 智能对话入口

    路由: /api/v1/dashboard/chat (避免与 core/api_routes.py 的 /api/v1/chat 冲突)
    返回: UnifiedChatResponse 格式
    """
    message = request.get("message", "")
    device_id = request.get("device_id", "")
    context = request.get("context", [])
    session_id = device_id or "dashboard-default"

    logger.info(f"Dashboard chat: {message[:50]}...")

    # === 对话记忆：记录用户消息 ===
    memory = None
    try:
        from core.ai_intent import get_conversation_memory
        memory = get_conversation_memory()
        await memory.add_turn(session_id, "user", message)
        if not context:
            context = await memory.get_context(session_id, max_turns=10)
    except Exception as e:
        logger.debug(f"Conversation memory load failed: {e}")

    # === 意图解析：优先使用现代解析器 ===
    intent = await get_parsed_intent_modern(message, context)
    if intent is None:
        intent = parse_intent(message)

    intent_type = intent.get("type", "chat")
    confidence = intent.get("confidence", 0.5)
    suggestions = intent.get("suggestions", [])

    def _make_response(response_text: str, success: bool = True, mode: str = "chat",
                       extra_data: Dict = None, error: str = "") -> JSONResponse:
        resp = UnifiedChatResponse(
            success=success,
            response=response_text,
            intent=intent_type,
            confidence=confidence,
            mode=mode,
            suggestions=suggestions,
            data=extra_data or {},
            error=error,
            session_id=session_id,
        )
        return JSONResponse(resp.to_json_response())

    async def _save_assistant_reply(reply_text: str):
        if memory:
            try:
                await memory.add_turn(session_id, "assistant", reply_text)
            except Exception as e:
                logger.debug(f"Failed to save assistant reply to memory: {e}")

    if GALAXY_CORE_AVAILABLE and galaxy_core:
        try:
            if intent_type == "device_control":
                result = await galaxy_core.send_device_command(
                    device_id or "default",
                    intent.get("action", ""),
                    intent.get("params", {}),
                )
                reply = f"已执行: {intent.get('action', '')}"
                await _save_assistant_reply(reply)
                return _make_response(reply, mode="agent_react",
                                      extra_data={"executed": result.get("success", False)})

            elif intent_type == "learning":
                await galaxy_core.autonomous_learn(intent.get("params", {}))
                reply = "已学习"
                await _save_assistant_reply(reply)
                return _make_response(reply, mode="agent_react")

            elif intent_type == "thinking":
                await galaxy_core.autonomous_think(intent.get("params", {}).get("goal", message))
                reply = "思考完成"
                await _save_assistant_reply(reply)
                return _make_response(reply, mode="agent_react")

            elif intent_type == "coding":
                await galaxy_core.autonomous_code(intent.get("params", {}).get("task", message))
                reply = "代码生成完成"
                await _save_assistant_reply(reply)
                return _make_response(reply, mode="agent_react")

            elif intent_type == "knowledge":
                result = await galaxy_core.query_knowledge(message)
                reply = "知识检索完成"
                await _save_assistant_reply(reply)
                return _make_response(reply, mode="agent_react", extra_data=result)

            else:
                # 默认通过 Node_50_Transformer 处理
                result = await galaxy_core.call_node("50", "chat", {"message": message})
                reply = result.get("response", "处理完成")
                await _save_assistant_reply(reply)
                return _make_response(reply)
        except Exception as e:
            logger.error(f"Galaxy core dispatch failed: {e}")
            # 降级到 LLM
            pass

    # 如果 galaxy_core 不可用，尝试调用 LLM
    if API_MANAGER_AVAILABLE and api_manager:
        try:
            result = await api_manager.call_llm([
                {"role": "user", "content": message}
            ])
            if result.get("success"):
                reply = result.get("content", "处理完成")
                await _save_assistant_reply(reply)
                return _make_response(reply, mode="chat",
                                      extra_data={"model": result.get("model", "")})
            else:
                return _make_response(
                    f"LLM 调用失败: {result.get('error', 'Unknown error')}",
                    success=False, error=result.get("error", "Unknown error"))
        except Exception as e:
            return _make_response(f"错误: {str(e)}", success=False, error=str(e))

    reply = f"收到: {message}\n\n提示: 请配置 API Key 以启用智能对话功能。"
    return _make_response(reply, success=False, mode="fallback",
                          error="未配置 LLM API Key")


def parse_intent(message: str) -> Dict[str, Any]:
    """
    简单关键词意图解析 (fallback)

    当 core.ai_intent.IntentParser 不可用时使用此版本。
    """
    message_lower = message.lower()

    # 设备控制
    if any(kw in message_lower for kw in ["打开", "启动", "open"]):
        return {
            "type": "device_control",
            "action": "open_app",
            "params": {"app_name": extract_app_name(message)},
            "confidence": 0.5,
            "suggestions": [],
        }

    if any(kw in message_lower for kw in ["截图", "screenshot"]):
        return {
            "type": "device_control",
            "action": "screenshot",
            "params": {},
            "confidence": 0.5,
            "suggestions": [],
        }

    if any(kw in message_lower for kw in ["滑动", "滚动", "scroll"]):
        direction = "down"
        if "上" in message_lower:
            direction = "up"
        return {
            "type": "device_control",
            "action": "scroll",
            "params": {"direction": direction},
            "confidence": 0.5,
            "suggestions": [],
        }

    # 学习
    if any(kw in message_lower for kw in ["学习", "记住", "learn"]):
        return {"type": "learning", "params": {"action": message, "reward": 0.5},
                "confidence": 0.5, "suggestions": []}

    # 思考
    if any(kw in message_lower for kw in ["思考", "分析", "think"]):
        return {"type": "thinking", "params": {"goal": message},
                "confidence": 0.5, "suggestions": []}

    # 编程
    if any(kw in message_lower for kw in ["写代码", "编程", "code"]):
        return {"type": "coding", "params": {"task": message},
                "confidence": 0.5, "suggestions": []}

    # 知识
    if any(kw in message_lower for kw in ["查询", "搜索", "知识"]):
        return {"type": "knowledge", "params": {"query": message},
                "confidence": 0.5, "suggestions": []}

    return {"type": "chat", "params": {"message": message},
            "confidence": 0.3, "suggestions": []}


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
                    ws_response = await chat({"message": message.get("content", "")})
                    # chat() returns a JSONResponse; extract body as dict
                    if hasattr(ws_response, "body"):
                        body = json.loads(ws_response.body)
                    else:
                        body = ws_response if isinstance(ws_response, dict) else {}
                    await websocket.send_json({
                        "type": "chat_response",
                        "content": body.get("response", "")
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


# ============================================================================
# API 配置管理
# ============================================================================

# 导入 API 管理器
try:
    from core.api_manager import api_manager
    API_MANAGER_AVAILABLE = True
except ImportError:
    API_MANAGER_AVAILABLE = False
    api_manager = None


@app.get("/api/v1/config")
async def get_config():
    """获取完整配置"""
    if API_MANAGER_AVAILABLE and api_manager:
        return api_manager.get_config()
    return {"status": "standalone", "api_manager_available": False, "config": {}}


@app.post("/api/v1/config")
async def update_config(request: dict):
    """更新配置"""
    if API_MANAGER_AVAILABLE and api_manager:
        success = api_manager.update_config(request)
        return {"success": success}
    return {"success": False, "error": "API manager not available"}


@app.get("/api/v1/config/models")
async def get_models():
    """获取所有模型"""
    if API_MANAGER_AVAILABLE and api_manager:
        return {"models": api_manager.get_models()}
    return {"models": []}


@app.get("/api/v1/config/models/available")
async def get_available_models():
    """获取可用模型"""
    if API_MANAGER_AVAILABLE and api_manager:
        return {"models": api_manager.get_available_models()}
    return {"models": []}


@app.post("/api/v1/config/api-key")
async def set_api_key(request: dict):
    """设置 API Key"""
    if API_MANAGER_AVAILABLE and api_manager:
        category = request.get("category", "direct_models")  # 默认是 direct_models
        key_name = request.get("provider", "")  # 兼容旧参数名
        api_key = request.get("api_key", "")
        
        # 如果 provider 是 oneapi，则 category 是 oneapi
        if key_name == "oneapi":
            category = "oneapi"
            key_name = ""
        
        success = api_manager.set_api_key(category, key_name, api_key)
        return {"success": success}
    return {"success": False, "error": "API manager not available"}


@app.get("/api/v1/config/nodes")
async def get_config_nodes():
    """获取所有节点配置"""
    if API_MANAGER_AVAILABLE and api_manager:
        return {"nodes": api_manager.get_nodes()}
    return {"nodes": []}


@app.post("/api/v1/config/nodes/check")
async def check_nodes():
    """检查所有节点"""
    if API_MANAGER_AVAILABLE and api_manager:
        results = await api_manager.check_all_nodes()
        return {"results": results}
    return {"results": {}}


@app.get("/api/v1/config/status")
async def get_config_status():
    """获取配置状态"""
    if API_MANAGER_AVAILABLE and api_manager:
        return api_manager.get_status()
    return {
        "status": "standalone",
        "api_manager_available": False,
        "models_configured": False,
        "nodes_active": 0,
        "message": "Running in standalone mode - core API manager not loaded"
    }


@app.post("/api/v1/config/test-llm")
async def test_llm(request: dict):
    """测试 LLM 调用"""
    if API_MANAGER_AVAILABLE and api_manager:
        message = request.get("message", "Hello, this is a test.")
        result = await api_manager.call_llm([
            {"role": "user", "content": message}
        ])
        return result
    return {"success": False, "error": "API manager not available"}
"""
Dashboard 后端 API 扩展
======================

添加到 main.py 的 API 接口
"""

# 将以下代码添加到 dashboard/backend/main.py 的末尾

# ============================================================================
# 工具 API 管理
# ============================================================================

@app.get("/api/v1/config/tools")
async def get_tools():
    """获取所有工具"""
    if API_MANAGER_AVAILABLE and api_manager:
        return {"tools": api_manager.get_tools()}
    return {"tools": []}


@app.get("/api/v1/config/tools/available")
async def get_available_tools():
    """获取可用工具"""
    if API_MANAGER_AVAILABLE and api_manager:
        return {"tools": api_manager.get_available_tools()}
    return {"tools": []}


@app.post("/api/v1/config/tools/api-key")
async def set_tool_api_key(request: dict):
    """设置工具 API Key"""
    if API_MANAGER_AVAILABLE and api_manager:
        tool_id = request.get("tool_id", "")
        api_key = request.get("api_key", "")
        success = api_manager.set_api_key("tools", tool_id, api_key)
        return {"success": success}
    return {"success": False, "error": "API manager not available"}


# ============================================================================
# API 验证 - 关键功能
# ============================================================================

@app.post("/api/v1/config/validate")
async def validate_api(request: dict):
    """
    验证 API Key 是否有效
    
    这是关键功能，确保 API Key 真的能用
    """
    if API_MANAGER_AVAILABLE and api_manager:
        category = request.get("category", "")  # oneapi, direct_models, tools
        key_name = request.get("key_name", "")
        
        result = await api_manager.validate_api_key(category, key_name)
        return result
    
    return {"valid": False, "error": "API manager not available"}


@app.post("/api/v1/config/validate-all")
async def validate_all_apis():
    """验证所有已配置的 API"""
    if API_MANAGER_AVAILABLE and api_manager:
        results = {}
        
        # 验证 OneAPI
        if api_manager.config.get("oneapi", {}).get("api_key"):
            results["oneapi"] = await api_manager.validate_api_key("oneapi", "")
        
        # 验证直接模型
        for provider, config in api_manager.config.get("direct_models", {}).items():
            if config.get("api_key"):
                results[provider] = await api_manager.validate_api_key("direct_models", provider)
        
        # 验证工具
        for tool_id, config in api_manager.config.get("tools", {}).items():
            if config.get("api_key"):
                results[tool_id] = await api_manager.validate_api_key("tools", tool_id)
        
        return {"results": results}
    
    return {"results": {}}


# ============================================================================
# 环境变量同步
# ============================================================================

@app.post("/api/v1/config/sync-env")
async def sync_to_env():
    """
    将配置同步到环境变量
    
    这是关键功能，确保节点能读取到 API Key
    """
    if API_MANAGER_AVAILABLE and api_manager:
        results = api_manager.sync_to_env()
        return {"success": True, "synced": results}
    return {"success": False, "error": "API manager not available"}


@app.get("/api/v1/config/env-status")
async def get_env_status():
    """获取环境变量状态"""
    env_keys = [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
        "ZHIPU_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY",
        "OPENROUTER_API_KEY", "BRAVE_API_KEY", "NOTION_API_KEY",
        "OPENWEATHER_API_KEY"
    ]
    
    status = {}
    for key in env_keys:
        value = os.environ.get(key, "")
        status[key] = {
            "configured": bool(value),
            "masked": value[:8] + "..." if len(value) > 8 else ""
        }
    
    return {"status": status}


# ============================================================================
# 联邦健康摘要
# ============================================================================

@app.get("/api/v1/federation/health")
async def get_federation_health():
    """联邦健康摘要：本地状态 + peers 数量 + alive/degraded/offline 统计"""
    try:
        from core.galaxy_federation import get_federation, _federation_enabled
        fed = get_federation()
        peers = fed.list_peers()
        return {
            "instance_id": fed.instance_id,
            "local_url": fed.local_url,
            "enabled": _federation_enabled(),
            "peers_count": len(peers),
            "alive": sum(1 for p in peers if p["status"] == "healthy"),
            "degraded": sum(1 for p in peers if p["status"] == "degraded"),
            "offline": sum(1 for p in peers if p["status"] == "offline"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
