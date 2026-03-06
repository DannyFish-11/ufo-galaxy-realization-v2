"""
UFO Galaxy - 完整 API 路由模块
================================

提供 Android 端和 Web UI 需要的所有 REST API 和 WebSocket 端点。

路由分组：
  /api/v1/system      - 系统状态和管理
  /api/v1/devices     - 设备注册和管理
  /api/v1/nodes       - 节点查询和调用
  /api/v1/command     - 命令路由引擎（并行/串行/超时/重试/聚合）
  /api/v1/ai          - AI 意图理解 & 智能推荐
  /api/v1/vision      - 融合视觉理解（OCR + GUI）
  /api/v1/tasks       - 任务管理
  /api/v1/chat        - 对话接口
  /api/v1/monitoring  - 监控仪表盘 & 告警
  /api/v1/health      - 统一健康管理
  /api/v1/concurrency - 并发管理状态
  /api/v1/errors      - 错误追踪概览
  /api/v1/discovery   - 节点发现服务
  /api/v1/security    - 安全审计 & 统计
  /api/v1/config      - 配置管理 & 版本历史
  /ws/device          - 设备 WebSocket 连接
  /ws/status          - 状态推送 WebSocket（含 command_result 推送）
"""

import asyncio
import base64
import json
import logging
import os
import time
import uuid

_startup_time = time.time()
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# 导入鉴权模块
try:
    from .auth import require_auth
except ImportError:
    # 如果导入失败，定义一个空的鉴权函数
    async def require_auth():
        return {"authenticated": True, "dev_mode": True}

logger = logging.getLogger("UFO-Galaxy.API")


# ============================================================================
# 请求/响应模型
# ============================================================================

class DeviceRegisterRequest(BaseModel):
    device_id: str
    device_type: str = "android"
    device_name: str = ""
    capabilities: List[str] = []
    os_version: str = ""
    app_version: str = ""

class DeviceStatusUpdate(BaseModel):
    device_id: str
    status: Dict[str, Any] = {}

class VisionRequest(BaseModel):
    image_base64: Optional[str] = None
    video_chunk: Optional[str] = None  # Base64 encoded video chunk
    mode: str = "full"
    instruction: str = ""
    session_id: Optional[str] = None   # For video stream context
    is_last_chunk: bool = False

class TaskRequest(BaseModel):
    task_type: str
    payload: Dict[str, Any] = {}
    device_id: str = ""
    priority: int = 5

class ChatRequest(BaseModel):
    message: str
    device_id: str = ""
    context: List[Dict[str, str]] = []

class NodeCallRequest(BaseModel):
    node_id: str
    action: str
    params: Dict[str, Any] = {}

class OCRRequest(BaseModel):
    image_base64: str
    mode: str = "free_ocr"
    language: str = "auto"


class CommandDispatchRequest(BaseModel):
    """命令分发请求"""
    source: str = "api"
    targets: List[str] = []
    command: str
    params: Dict[str, Any] = {}
    mode: str = "sync"   # sync | async | parallel | serial
    timeout: float = 30.0
    max_retries: int = 2
    notify_ws: bool = True
    priority: int = 5
    metadata: Dict[str, Any] = {}


class AIIntentRequest(BaseModel):
    """AI 意图解析请求"""
    text: str
    session_id: str = ""
    context: Dict[str, Any] = {}


class ConversationRequest(BaseModel):
    """对话记忆请求"""
    session_id: str
    role: str = "user"
    content: str
    metadata: Dict[str, Any] = {}


# ============================================================================
# 统一命令协议模型
# ============================================================================

from enum import Enum

class CommandStatus(str, Enum):
    """命令状态枚举"""
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class TargetResult(BaseModel):
    """单个目标的执行结果"""
    status: CommandStatus
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class UnifiedCommandRequest(BaseModel):
    """统一命令请求"""
    request_id: Optional[str] = None
    command: str
    targets: List[str]
    params: Dict[str, Any] = {}
    mode: str = "sync"  # sync or async
    timeout: int = 30


class UnifiedCommandResponse(BaseModel):
    """统一命令响应"""
    request_id: str
    status: CommandStatus
    created_at: str
    completed_at: Optional[str] = None
    results: Dict[str, TargetResult]


# ============================================================================
# 连接管理器
# ============================================================================

class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self.active_devices: Dict[str, WebSocket] = {}
        self.status_subscribers: Set[WebSocket] = set()
        # 命令响应等待器: command_id → asyncio.Future
        self._pending_responses: Dict[str, asyncio.Future] = {}
        
    async def connect_device(self, websocket: WebSocket, device_id: str):
        await websocket.accept()
        self.active_devices[device_id] = websocket
        logger.info(f"设备已连接: {device_id}")
        await self.broadcast_status({
            "type": "device_connected",
            "device_id": device_id,
            "timestamp": datetime.now().isoformat()
        })
        
    def disconnect_device(self, device_id: str):
        self.active_devices.pop(device_id, None)
        logger.info(f"设备已断开: {device_id}")
        
    async def send_to_device(self, device_id: str, message: dict) -> bool:
        ws = self.active_devices.get(device_id)
        if ws:
            try:
                await ws.send_json(message)
                return True
            except Exception as e:
                logger.error(f"发送消息到设备 {device_id} 失败: {e}")
                self.disconnect_device(device_id)
        return False
        
    async def broadcast_to_devices(self, message: dict):
        disconnected = []
        for device_id, ws in self.active_devices.items():
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(device_id)
        for d in disconnected:
            self.disconnect_device(d)
            
    async def subscribe_status(self, websocket: WebSocket):
        await websocket.accept()
        self.status_subscribers.add(websocket)
        
    def unsubscribe_status(self, websocket: WebSocket):
        self.status_subscribers.discard(websocket)
        
    async def broadcast_status(self, status: dict):
        disconnected = []
        for ws in self.status_subscribers:
            try:
                await ws.send_json(status)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.status_subscribers.discard(ws)

    async def send_command_and_wait(
        self, device_id: str, command: str, params: dict, timeout: float = 15.0
    ) -> dict:
        """发送命令到设备并等待设备回传结果 (request-response 模式)

        命令消息中包含 command_id, 设备回传 command_result 时须携带同一 command_id,
        由 resolve_command_response() 触发 Future 完成。

        Returns:
            设备返回的 payload, 或 {"error": "..."} 超时/失败。
        """
        command_id = f"cmd_{uuid.uuid4().hex[:12]}"
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_responses[command_id] = future

        message = {
            "type": "command",
            "command_id": command_id,
            "command": command,
            "params": params,
            "timestamp": datetime.now().isoformat(),
        }

        sent = await self.send_to_device(device_id, message)
        if not sent:
            self._pending_responses.pop(command_id, None)
            return {"error": f"Failed to send command to device {device_id}"}

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            return {"error": f"Command {command_id} timed out after {timeout}s"}
        finally:
            self._pending_responses.pop(command_id, None)

    def resolve_command_response(self, command_id: str, payload: dict):
        """设备回传 command_result 时调用，唤醒等待中的 Future"""
        future = self._pending_responses.get(command_id)
        if future and not future.done():
            future.set_result(payload)
            logger.debug(f"命令响应已匹配: {command_id}")
        else:
            logger.debug(f"收到无人等待的命令响应: {command_id}")

    async def push_command_result(self, command_result_dict: dict):
        """推送命令执行结果到所有 status 订阅者和相关设备"""
        # 先尝试匹配 pending response
        cmd_id = command_result_dict.get("command_id")
        if cmd_id:
            self.resolve_command_response(cmd_id, command_result_dict)

        payload = {
            "type": "command_result",
            "data": command_result_dict,
            "timestamp": datetime.now().isoformat(),
        }
        # 推送给 status 订阅者
        await self.broadcast_status(payload)
        # 推送给涉及的设备
        for target in command_result_dict.get("targets", {}).keys():
            if target in self.active_devices:
                await self.send_to_device(target, payload)


# ============================================================================
# 全局状态
# ============================================================================

connection_manager = ConnectionManager()

# 设备注册表
registered_devices: Dict[str, Dict[str, Any]] = {}

# 任务队列
task_queue: Dict[str, Dict[str, Any]] = {}

# 节点状态缓存
node_status_cache: Dict[str, Dict[str, Any]] = {}

# 统一命令结果存储
command_results: Dict[str, Dict[str, Any]] = {}


# ============================================================================
# 创建路由
# ============================================================================

def create_api_routes(service_manager=None, config=None) -> APIRouter:
    """创建完整的 API 路由"""
    
    router = APIRouter()
    
    # ========================================================================
    # /api/v1/system - 系统状态和管理
    # ========================================================================
    
    @router.get("/api/v1/system/status")
    async def system_status():
        """获取系统完整状态"""
        services = service_manager.get_status() if service_manager else {}
        return JSONResponse({
            "status": "running",
            "version": "2.0.0",
            "timestamp": datetime.now().isoformat(),
            "services": services,
            "devices": {
                "registered": len(registered_devices),
                "online": len(connection_manager.active_devices),
                "list": [
                    {
                        "device_id": did,
                        "device_name": info.get("device_name", ""),
                        "device_type": info.get("device_type", ""),
                        "online": did in connection_manager.active_devices,
                        "last_seen": info.get("last_seen", "")
                    }
                    for did, info in registered_devices.items()
                ]
            },
            "nodes": {
                "total": len(node_status_cache),
                "active": sum(1 for n in node_status_cache.values() if n.get("status") == "running")
            },
            "tasks": {
                "total": len(task_queue),
                "pending": sum(1 for t in task_queue.values() if t.get("status") == "pending"),
                "running": sum(1 for t in task_queue.values() if t.get("status") == "running"),
                "completed": sum(1 for t in task_queue.values() if t.get("status") == "completed")
            }
        })
    
    @router.get("/api/v1/system/health")
    async def system_health():
        """健康检查端点"""
        return {"status": "healthy", "timestamp": datetime.now().isoformat()}
    
    @router.get("/api/v1/system/config")
    async def system_config():
        """获取系统配置（脱敏）"""
        if config:
            status = config.get_status_dict()
            return JSONResponse(status)
        return JSONResponse({"error": "config not available"})

    @router.get("/api/config")
    async def get_frontend_config(request: Request = None):
        """
        返回前端所需的非敏感配置。
        注意：敏感 Key (如 OPENAI_API_KEY) 不应直接返回，除非在受控的本地环境。
        """
        # 检查是否是本地请求 (简单判断)
        # 在生产环境中，这里应该有更严格的鉴权
        
        # 获取主机地址，用于构建 WebSocket URL
        host = os.getenv("API_HOST", "localhost")
        port = os.getenv("API_PORT", "8099")
        if request:
            host = request.url.hostname or "localhost"
            port = str(request.url.port or 8099)

        def _is_configured(key_name: str) -> bool:
            val = os.getenv(key_name, "")
            return bool(val and not val.startswith("your-") and not val.startswith("sk-YOUR"))

        config_data = {
            "api_base_url": f"http://{host}:{port}",
            "ws_url": f"ws://{host}:{port}/ws",
            "status": {
                "openai": _is_configured("OPENAI_API_KEY"),
                "deepseek": _is_configured("DEEPSEEK_API_KEY"),
                "anthropic": _is_configured("ANTHROPIC_API_KEY"),
                "gemini": _is_configured("GEMINI_API_KEY"),
                "groq": _is_configured("GROQ_API_KEY"),
                "openrouter": _is_configured("OPENROUTER_API_KEY"),
                "perplexity": _is_configured("SONAR_API_KEY") or _is_configured("PERPLEXITY_API_KEY"),
                "oneapi": _is_configured("ONEAPI_API_KEY"),
                "ocr": _is_configured("DEEPSEEK_OCR2_API_KEY"),
                "ollama": bool(os.getenv("OLLAMA_URL")),
            }
        }
        return JSONResponse(config_data)

    # 支持的 API Key 白名单
    ALLOWED_CONFIG_KEYS = {
        "OPENAI_API_KEY", "OPENAI_API_BASE",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
        "GROQ_API_KEY",
        "XAI_API_KEY",
        "ZHIPU_API_KEY",
        "ONEAPI_URL", "ONEAPI_API_KEY",
        "PERPLEXITY_API_KEY", "SONAR_API_KEY",
        "DEEPSEEK_OCR2_API_KEY",
        "OLLAMA_URL", "VLLM_URL",
    }

    @router.post("/api/config/update")
    async def update_config(request: Request):
        """
        更新配置 - 支持所有 LLM API Key
        写入 .env 文件并即时热更新到 os.environ
        """
        data = await request.json()
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")

        try:
            # 读取现有 .env
            current_env = {}
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, val = line.split("=", 1)
                            current_env[key.strip()] = val.strip()

            # 支持两种格式:
            # 1. 直接 {KEY: VALUE} (旧格式)
            # 2. {"keys": {KEY: VALUE}} (新格式，来自 Dashboard)
            keys_data = data.get("keys", data) if isinstance(data, dict) else data

            updated_keys = []
            for key, val in keys_data.items():
                if key in ALLOWED_CONFIG_KEYS:
                    val = str(val).strip()
                    if val:
                        current_env[key] = val
                        os.environ[key] = val
                        updated_keys.append(key)
                    else:
                        current_env.pop(key, None)
                        os.environ.pop(key, None)
                        updated_keys.append(f"{key} (removed)")

            # 写回 .env
            with open(env_path, "w", encoding="utf-8") as f:
                f.write("# UFO Galaxy - Environment Configuration\n")
                f.write(f"# Updated: {datetime.now().isoformat()}\n\n")
                for key, val in sorted(current_env.items()):
                    f.write(f"{key}={val}\n")

            # 热重载 LLM Manager 以拾取新 API Key
            if updated_keys and any("API_KEY" in k or "URL" in k for k in updated_keys):
                try:
                    llm_manager.reload()
                    logger.info(f"LLM Manager 已热重载 (更新: {updated_keys})")
                except Exception as e:
                    logger.warning(f"LLM Manager 热重载失败: {e}")

            return {"status": "success", "message": "Configuration updated", "updated": updated_keys}
        except Exception as e:
            return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

    # ========================================================================
    # API Manager 静态文件路由
    # ========================================================================
    # 注意：静态文件挂载已移至 unified_launcher.py 中处理，
    # 以便正确使用 app.mount() 并避免路由冲突。
    pass
    
    # ========================================================================
    # /api/v1/devices - 设备注册和管理
    # ========================================================================
    
    @router.post("/api/v1/devices/register")
    async def register_device(req: DeviceRegisterRequest):
        """注册设备"""
        device_info = {
            "device_id": req.device_id,
            "device_type": req.device_type,
            "device_name": req.device_name or f"Device-{req.device_id[:8]}",
            "capabilities": req.capabilities,
            "os_version": req.os_version,
            "app_version": req.app_version,
            "registered_at": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "status": "registered"
        }
        registered_devices[req.device_id] = device_info
        logger.info(f"设备注册: {req.device_id} ({req.device_type})")
        
        return JSONResponse({
            "success": True,
            "device_id": req.device_id,
            "message": "设备注册成功",
            "server_version": "2.0.0",
            "available_nodes": list(node_status_cache.keys())[:20]
        })
    
    @router.post("/api/v1/devices/status")
    async def update_device_status(req: DeviceStatusUpdate):
        """更新设备状态"""
        if req.device_id in registered_devices:
            registered_devices[req.device_id]["last_seen"] = datetime.now().isoformat()
            registered_devices[req.device_id]["status_detail"] = req.status
            
            # 广播状态更新
            await connection_manager.broadcast_status({
                "type": "device_status_update",
                "device_id": req.device_id,
                "status": req.status,
                "timestamp": datetime.now().isoformat()
            })
            
            return {"success": True}
        raise HTTPException(status_code=404, detail="设备未注册")
    
    @router.get("/api/v1/devices")
    async def list_devices():
        """列出所有设备"""
        devices = []
        for did, info in registered_devices.items():
            devices.append({
                **info,
                "online": did in connection_manager.active_devices
            })
        return JSONResponse({"devices": devices, "total": len(devices)})
    
    @router.get("/api/v1/devices/{device_id}")
    async def get_device(device_id: str):
        """获取设备详情"""
        if device_id in registered_devices:
            info = registered_devices[device_id]
            info["online"] = device_id in connection_manager.active_devices
            return JSONResponse(info)
        raise HTTPException(status_code=404, detail="设备未找到")
    
    # ========================================================================
    # /api/v1/nodes - 节点查询和调用
    # ========================================================================
    
    @router.get("/api/v1/nodes")
    async def list_nodes():
        """列出所有可用节点"""
        nodes = []
        # 从节点配置文件加载
        nodes_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nodes")
        if os.path.isdir(nodes_dir):
            for name in sorted(os.listdir(nodes_dir)):
                node_dir = os.path.join(nodes_dir, name)
                if os.path.isdir(node_dir) and os.path.exists(os.path.join(node_dir, "main.py")):
                    config_file = os.path.join(node_dir, "config.json")
                    node_config = {}
                    if os.path.exists(config_file):
                        try:
                            with open(config_file) as f:
                                node_config = json.load(f)
                        except Exception:
                            pass
                    
                    status = node_status_cache.get(name, {})
                    nodes.append({
                        "name": name,
                        "description": node_config.get("description", ""),
                        "group": node_config.get("group", ""),
                        "status": status.get("status", "stopped"),
                        "capabilities": node_config.get("capabilities", [])
                    })
        
        return JSONResponse({"nodes": nodes, "total": len(nodes)})
    
    @router.get("/api/v1/nodes/{node_name}")
    async def get_node(node_name: str):
        """获取节点详情"""
        nodes_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nodes")
        node_dir = os.path.join(nodes_dir, node_name)
        
        if not os.path.isdir(node_dir):
            raise HTTPException(status_code=404, detail=f"节点 {node_name} 未找到")
        
        config_file = os.path.join(node_dir, "config.json")
        node_config = {}
        if os.path.exists(config_file):
            try:
                with open(config_file) as f:
                    node_config = json.load(f)
            except Exception:
                pass
        
        status = node_status_cache.get(node_name, {})
        return JSONResponse({
            "name": node_name,
            "config": node_config,
            "status": status,
            "has_fusion_entry": os.path.exists(os.path.join(node_dir, "fusion_entry.py")),
            "has_dockerfile": os.path.exists(os.path.join(node_dir, "Dockerfile"))
        })
    
    # 节点实例缓存
    _node_instances = {}
    
    def _load_node(node_id: str, node_dir: str, fusion_entry_path: str):
        """加载节点模块，支持模块级 execute 函数和类实例两种模式
        
        注意：不修改 sys.path，避免跨节点导入污染。
        每个 fusion_entry.py 内部使用 importlib.util 绝对路径导入自己的 main.py。
        """
        if node_id in _node_instances:
            return _node_instances[node_id]
        
        import importlib.util
        
        spec = importlib.util.spec_from_file_location(
            f"nodes.{node_id}.fusion_entry", fusion_entry_path,
            submodule_search_locations=[node_dir]
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # 模式1：模块级 execute 函数（新版 fusion_entry）
        if hasattr(module, 'execute') and callable(module.execute):
            _node_instances[node_id] = {"type": "function", "execute": module.execute, "module": module}
            return _node_instances[node_id]
        
        # 模式2：通过 get_node_instance() 获取类实例
        if hasattr(module, 'get_node_instance'):
            instance = module.get_node_instance()
            if hasattr(instance, 'execute'):
                _node_instances[node_id] = {"type": "instance", "instance": instance, "module": module}
                return _node_instances[node_id]
        
        # 模式3：查找模块中的第一个有 execute 方法的类
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and hasattr(attr, 'execute'):
                try:
                    instance = attr()
                    _node_instances[node_id] = {"type": "instance", "instance": instance, "module": module}
                    return _node_instances[node_id]
                except Exception:
                    continue
        
        return None
    
    async def _execute_node(node_info: dict, action: str, params: dict):
        """执行节点操作，处理同步和异步两种方法"""
        import inspect
        
        if node_info["type"] == "function":
            func = node_info["execute"]
            if inspect.iscoroutinefunction(func):
                return await func(action, params)
            else:
                return await asyncio.get_event_loop().run_in_executor(
                    None, func, action, params
                )
        elif node_info["type"] == "instance":
            instance = node_info["instance"]
            method = instance.execute
            if inspect.iscoroutinefunction(method):
                return await method(action, **params)
            else:
                return await asyncio.get_event_loop().run_in_executor(
                    None, lambda: method(action, **params)
                )
        return None
    
    # ========================================================================
    # /api/v1/agent - 自主智能体调度
    # ========================================================================

    from core.scheduler import AutonomousScheduler
    from core.llm_manager import LLMManager
    
    nodes_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nodes")
    scheduler = AutonomousScheduler(nodes_root)
    llm_manager = LLMManager(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"))

    class AutonomousRequest(BaseModel):
        instruction: str
        context: Dict[str, Any] = {}
        model_alias: Optional[str] = None

    class AgentDeployRequest(BaseModel):
        """Agent 部署请求"""
        target_device: str               # 目标设备 ID
        instruction: str                  # 自然语言指令
        execution_mode: str = "react"     # react / sequential / autonomous
        tools: List[Dict[str, Any]] = []  # 工具声明 (可选, 默认使用设备标准工具)
        priority: str = "normal"
        timeout_seconds: int = 300

    @router.post("/api/v1/agent/deploy")
    async def deploy_agent(req: AgentDeployRequest):
        """
        部署 Agent 到端侧设备

        将 AgentManifest 通过 WebSocket 推送到指定设备,
        设备端的 LocalAgentRuntime 接收后自主执行。
        """
        try:
            from core.agent_manifest import AgentManifest

            # 构建 Manifest
            manifest = AgentManifest.create_device_control_agent(
                target_device=req.target_device,
                instruction=req.instruction,
                source_device="server",
            )
            manifest.execution_mode = req.execution_mode
            manifest.priority = req.priority
            manifest.timeout_seconds = req.timeout_seconds
            if req.tools:
                manifest.tools = req.tools

            manifest_dict = manifest.to_dict()
            checksum = manifest.checksum()

            # 通过 WebSocket 推送到设备
            ws_message = {
                "type": "agent_deploy",
                "manifest": manifest_dict,
                "checksum": checksum,
            }

            if req.target_device in connection_manager.active_devices:
                success = await connection_manager.send_to_device(req.target_device, ws_message)
                if success:
                    logger.info(f"Agent {manifest.manifest_id[:8]} deployed to {req.target_device}")
                    return {
                        "success": True,
                        "manifest_id": manifest.manifest_id,
                        "target_device": req.target_device,
                        "checksum": checksum,
                        "status": "deployed",
                    }
                else:
                    return {"success": False, "error": f"WebSocket send failed to {req.target_device}"}
            else:
                # 设备不在线, 缓存 manifest 等待连接
                return {
                    "success": False,
                    "error": f"Device {req.target_device} not connected",
                    "manifest_id": manifest.manifest_id,
                    "status": "queued",
                }
        except Exception as e:
            logger.error(f"Agent deploy failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/agent/autonomous")
    async def autonomous_execute(req: AutonomousRequest):
        """自主调度接口：接收自然语言指令，自动规划并执行节点任务 (ReAct Loop)"""
        try:
            # 定义执行器回调，供 Scheduler 在 ReAct 循环中调用
            async def node_executor(node_id: str, action: str, params: dict):
                # 1. 查找节点目录
                target_node_dir = os.path.join(nodes_root, node_id)
                if not os.path.isdir(target_node_dir):
                    # 尝试模糊匹配 (例如 Node_82_NetworkGuard -> Node_82)
                    for name in os.listdir(nodes_root):
                        if name.startswith(node_id) or node_id in name:
                            target_node_dir = os.path.join(nodes_root, name)
                            node_id = name # 更新为真实名称
                            break
                
                if not os.path.isdir(target_node_dir):
                    return {"error": f"Node {node_id} not found"}

                # 2. 加载节点
                fusion_entry = os.path.join(target_node_dir, "fusion_entry.py")
                if not os.path.exists(fusion_entry):
                    return {"error": f"Node {node_id} has no fusion_entry.py"}
                
                node_instance = _load_node(node_id, target_node_dir, fusion_entry)
                if not node_instance:
                    return {"error": f"Failed to load node {node_id}"}
                
                # 3. 执行节点
                try:
                    result = await _execute_node(node_instance, action, params)
                    return result
                except Exception as e:
                    logger.error(f"Node execution error: {e}")
                    return {"error": str(e)}

            # 注入上下文
            execution_context = req.context.copy()
            execution_context["devices"] = registered_devices
            execution_context["executor"] = node_executor
            
            # 启动 ReAct 循环
            # 如果没有配置 API Key，LLMManager 会报错，这里捕获并降级处理
            try:
                plan_result = await scheduler.plan_and_execute(
                    req.instruction, 
                    llm_manager, 
                    execution_context
                )
                return plan_result
            except ValueError as ve:
                # Fallback: 如果没有配置模型，使用简单的规则匹配 (仅用于演示/测试)
                logger.warning(f"LLM not configured, falling back to rule-based: {ve}")
                executed_tasks = []
                if "唤醒" in req.instruction:
                    for did in registered_devices:
                        await connection_manager.send_to_device(
                            did,
                            {"type": "task", "task_type": "wake_up", "payload": {"msg": req.instruction}},
                        )
                        executed_tasks.append(f"Waking up device {did}")
                    return {
                        "success": True, 
                        "reply": "已通过规则引擎唤醒所有设备 (请配置 LLM 以启用智能调度)",
                        "steps": [{"action": "wake_up", "result": "success"}]
                    }
                raise HTTPException(status_code=500, detail="LLM not configured and no rule matched")

        except Exception as e:
            logger.error(f"Autonomous execution failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/nodes/call")
    async def call_node(req: NodeCallRequest):
        """调用节点执行操作"""
        task_id = str(uuid.uuid4())
        
        nodes_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nodes")
        node_dir = os.path.join(nodes_dir, req.node_id)
        fusion_entry = os.path.join(node_dir, "fusion_entry.py")
        
        if not os.path.isdir(node_dir):
            raise HTTPException(status_code=404, detail=f"节点 {req.node_id} 未找到")
        
        # 记录任务
        task_queue[task_id] = {
            "task_id": task_id,
            "node_id": req.node_id,
            "action": req.action,
            "params": req.params,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
        
        try:
            if os.path.exists(fusion_entry):
                node_info = _load_node(req.node_id, node_dir, fusion_entry)
                
                if node_info:
                    task_queue[task_id]["status"] = "running"
                    result = await _execute_node(node_info, req.action, req.params or {})
                    task_queue[task_id]["status"] = "completed"
                    task_queue[task_id]["result"] = result
                    return JSONResponse({
                        "success": True,
                        "task_id": task_id,
                        "result": result
                    })
                else:
                    logger.warning(f"节点 {req.node_id} 的 fusion_entry.py 没有可调用的 execute 方法")
            
            # 降级：返回任务 ID
            return JSONResponse({
                "success": True,
                "task_id": task_id,
                "status": "queued",
                "message": f"任务已排队，节点 {req.node_id} 将异步处理"
            })
            
        except Exception as e:
            task_queue[task_id]["status"] = "failed"
            task_queue[task_id]["error"] = str(e)
            logger.error(f"节点调用失败: {req.node_id}.{req.action}: {e}")
            return JSONResponse({
                "success": False,
                "task_id": task_id,
                "error": str(e)
            }, status_code=500)
    
    # ========================================================================
    # /api/v1/vision - 融合视觉理解（OCR + GUI）
    # ========================================================================
    
    @router.post("/api/v1/vision/understand")
    async def vision_understand(req: VisionRequest):
        """融合视觉理解：支持图片、视频流及复合指令"""
        try:
            # 处理视频流
            if req.video_chunk:
                # 这里可以集成视频流处理逻辑，例如将帧存入缓冲区或直接送入多模态模型
                # 目前作为示例，我们将其视为单帧处理，或者返回流接收确认
                if not req.image_base64:
                    return JSONResponse({
                        "success": True,
                        "mode": "video_stream",
                        "session_id": req.session_id,
                        "message": "Video chunk received"
                    })
            
            if not req.image_base64:
                 raise HTTPException(status_code=400, detail="Image or video chunk required")

            # 解码图片
            image_data = base64.b64decode(req.image_base64)
            
            # 尝试使用 VisionPipeline
            try:
                from core.vision_pipeline import VisionPipeline
                pipeline = VisionPipeline()
                result = await asyncio.get_event_loop().run_in_executor(
                    None, pipeline.understand, image_data, req.mode, req.instruction
                )
                return JSONResponse({
                    "success": True,
                    "engine": "vision_pipeline",
                    "result": result
                })
            except ImportError:
                pass
            
            # 降级：直接调用 DeepSeek OCR 2
            try:
                from nodes.Node_15_OCR.core.deepseek_ocr_adapter import DeepSeekOCR2Adapter
                adapter = DeepSeekOCR2Adapter()
                result = await asyncio.get_event_loop().run_in_executor(
                    None, adapter.process_image, image_data, req.mode
                )
                return JSONResponse({
                    "success": True,
                    "engine": "deepseek_ocr2",
                    "result": result
                })
            except Exception as e:
                logger.warning(f"DeepSeek OCR 2 调用失败: {e}")
            
            # 最终降级：返回基本信息
            return JSONResponse({
                "success": False,
                "engine": "none",
                "error": "无可用的视觉理解引擎",
                "result": {
                    "raw_text": "",
                    "text_blocks": [],
                    "ui_elements": [],
                    "scene_description": "视觉引擎不可用",
                    "suggested_actions": []
                }
            })
            
        except Exception as e:
            logger.error(f"视觉理解失败: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.post("/api/v1/vision/ocr")
    async def vision_ocr(req: OCRRequest):
        """独立 OCR 接口"""
        try:
            image_data = base64.b64decode(req.image_base64)
            
            # 调用 DeepSeek OCR 2
            try:
                from nodes.Node_15_OCR.core.deepseek_ocr_adapter import DeepSeekOCR2Adapter
                adapter = DeepSeekOCR2Adapter()
                result = await asyncio.get_event_loop().run_in_executor(
                    None, adapter.process_image, image_data, req.mode
                )
                return JSONResponse({
                    "success": True,
                    "engine": "deepseek_ocr2",
                    "text": result.get("text", ""),
                    "blocks": result.get("blocks", []),
                    "confidence": result.get("confidence", 0.0)
                })
            except Exception as e:
                logger.warning(f"DeepSeek OCR 2 调用失败: {e}")
                return JSONResponse({
                    "success": False,
                    "error": str(e),
                    "text": "",
                    "blocks": []
                })
                
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # ========================================================================
    # /api/v1/tasks - 任务管理
    # ========================================================================
    
    @router.post("/api/v1/tasks")
    async def create_task(req: TaskRequest):
        """创建任务"""
        task_id = str(uuid.uuid4())
        task = {
            "task_id": task_id,
            "task_type": req.task_type,
            "payload": req.payload,
            "device_id": req.device_id,
            "priority": req.priority,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
        task_queue[task_id] = task
        
        # 如果指定了设备，通过 WebSocket 发送
        if req.device_id and req.device_id in connection_manager.active_devices:
            await connection_manager.send_to_device(req.device_id, {
                "type": "task",
                "task_id": task_id,
                "task_type": req.task_type,
                "payload": req.payload
            })
            task["status"] = "sent"
        
        return JSONResponse({
            "success": True,
            "task_id": task_id,
            "status": task["status"]
        })
    
    @router.get("/api/v1/tasks/{task_id}")
    async def get_task(task_id: str):
        """获取任务状态"""
        if task_id in task_queue:
            return JSONResponse(task_queue[task_id])
        raise HTTPException(status_code=404, detail="任务未找到")
    
    @router.get("/api/v1/tasks")
    async def list_tasks(status: str = None, limit: int = 50):
        """列出任务"""
        tasks = list(task_queue.values())
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
        return JSONResponse({
            "tasks": tasks[:limit],
            "total": len(tasks)
        })
    
    @router.post("/api/v1/tasks/{task_id}/result")
    async def submit_task_result(task_id: str):
        """提交任务结果（设备回调）"""
        if task_id in task_queue:
            # 从请求体读取结果
            task_queue[task_id]["status"] = "completed"
            task_queue[task_id]["completed_at"] = datetime.now().isoformat()
            return {"success": True}
        raise HTTPException(status_code=404, detail="任务未找到")
    
    # ========================================================================
    # /api/v1/command - 统一命令端点
    # ========================================================================
    
    async def execute_command_on_target(target: str, command: str, params: Dict[str, Any], timeout: int) -> TargetResult:
        """在单个目标上执行命令 — 使用 send_command_and_wait 实现 request-response"""
        started_at = datetime.now(timezone.utc).isoformat()

        try:
            # 检查目标是否在线
            if target not in connection_manager.active_devices:
                return TargetResult(
                    status=CommandStatus.FAILED,
                    output=None,
                    error="Target device not connected",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc).isoformat()
                )

            # 使用 send_command_and_wait 发送并等待设备响应
            result = await connection_manager.send_command_and_wait(
                device_id=target,
                command=command,
                params=params,
                timeout=float(timeout)
            )

            if "error" in result:
                return TargetResult(
                    status=CommandStatus.FAILED,
                    output=None,
                    error=result["error"],
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc).isoformat()
                )

            return TargetResult(
                status=CommandStatus.DONE,
                output=result,
                error=None,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat()
            )
            
        except Exception as e:
            logger.error(f"执行命令失败 (target={target}): {e}")
            return TargetResult(
                status=CommandStatus.FAILED,
                output=None,
                error=str(e),
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat()
            )
    
    @router.post("/api/v1/command/unified")
    async def unified_command(
        req: UnifiedCommandRequest,
        auth: dict = Depends(require_auth)
    ):
        """
        统一命令端点 - 支持多目标、sync/async 模式、超时控制
        
        **功能特性：**
        - 多目标并行执行
        - request_id 追踪
        - sync/async 模式选择
        - 超时控制
        - 结果聚合
        
        **请求示例：**
        ```json
        {
          "request_id": "optional-uuid",
          "command": "screenshot",
          "targets": ["device_1", "device_2"],
          "params": {"quality": 90},
          "mode": "sync",
          "timeout": 30
        }
        ```
        """
        # 生成或使用提供的 request_id
        request_id = req.request_id or str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        
        logger.info(f"收到统一命令: request_id={request_id}, command={req.command}, targets={req.targets}, mode={req.mode}")
        
        # 验证模式
        if req.mode not in ["sync", "async"]:
            raise HTTPException(status_code=400, detail="Invalid mode. Must be 'sync' or 'async'")
        
        # 验证目标列表
        if not req.targets:
            raise HTTPException(status_code=400, detail="Targets list cannot be empty")
        
        # 初始化命令结果
        command_results[request_id] = {
            "request_id": request_id,
            "command": req.command,
            "targets": req.targets,
            "params": req.params,
            "mode": req.mode,
            "status": CommandStatus.QUEUED,
            "created_at": created_at,
            "completed_at": None,
            "results": {}
        }
        
        if req.mode == "sync":
            # 同步模式：并行执行所有目标并等待完成
            command_results[request_id]["status"] = CommandStatus.RUNNING
            
            # 使用 asyncio.gather 并行执行
            tasks = [
                execute_command_on_target(target, req.command, req.params, req.timeout)
                for target in req.targets
            ]
            
            try:
                # 设置超时
                target_results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=req.timeout
                )
                
                # 聚合结果
                results = {}
                for target, result in zip(req.targets, target_results):
                    if isinstance(result, Exception):
                        results[target] = TargetResult(
                            status=CommandStatus.FAILED,
                            output=None,
                            error=str(result),
                            started_at=created_at,
                            completed_at=datetime.now(timezone.utc).isoformat()
                        )
                    else:
                        results[target] = result
                
                # 更新命令结果
                completed_at = datetime.now(timezone.utc).isoformat()
                command_results[request_id]["status"] = CommandStatus.DONE
                command_results[request_id]["completed_at"] = completed_at
                command_results[request_id]["results"] = {
                    k: v.model_dump() for k, v in results.items()
                }
                
                # 返回响应
                return JSONResponse({
                    "request_id": request_id,
                    "status": CommandStatus.DONE,
                    "created_at": created_at,
                    "completed_at": completed_at,
                    "results": command_results[request_id]["results"]
                })
                
            except asyncio.TimeoutError:
                # 超时处理
                completed_at = datetime.now(timezone.utc).isoformat()
                command_results[request_id]["status"] = CommandStatus.FAILED
                command_results[request_id]["completed_at"] = completed_at
                command_results[request_id]["results"] = {
                    target: TargetResult(
                        status=CommandStatus.FAILED,
                        output=None,
                        error="Execution timeout",
                        started_at=created_at,
                        completed_at=completed_at
                    ).model_dump()
                    for target in req.targets
                }
                
                raise HTTPException(status_code=408, detail="Command execution timeout")
                
        else:
            # 异步模式：立即返回 request_id，后台执行
            async def execute_async():
                """后台执行任务"""
                try:
                    command_results[request_id]["status"] = CommandStatus.RUNNING
                    
                    # 并行执行所有目标
                    tasks = [
                        execute_command_on_target(target, req.command, req.params, req.timeout)
                        for target in req.targets
                    ]
                    
                    target_results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # 聚合结果
                    results = {}
                    for target, result in zip(req.targets, target_results):
                        if isinstance(result, Exception):
                            results[target] = TargetResult(
                                status=CommandStatus.FAILED,
                                output=None,
                                error=str(result),
                                started_at=created_at,
                                completed_at=datetime.now(timezone.utc).isoformat()
                            )
                        else:
                            results[target] = result
                    
                    # 更新命令结果
                    completed_at = datetime.now(timezone.utc).isoformat()
                    command_results[request_id]["status"] = CommandStatus.DONE
                    command_results[request_id]["completed_at"] = completed_at
                    command_results[request_id]["results"] = {
                        k: v.model_dump() for k, v in results.items()
                    }
                    
                    # 通过 WebSocket 推送结果
                    await connection_manager.broadcast_status({
                        "type": "command_result",
                        "request_id": request_id,
                        "status": CommandStatus.DONE,
                        "created_at": created_at,
                        "completed_at": completed_at,
                        "results": command_results[request_id]["results"]
                    })
                    
                except Exception as e:
                    logger.error(f"异步命令执行失败: {e}")
                    completed_at = datetime.now(timezone.utc).isoformat()
                    command_results[request_id]["status"] = CommandStatus.FAILED
                    command_results[request_id]["completed_at"] = completed_at
                    command_results[request_id]["results"] = {
                        target: TargetResult(
                            status=CommandStatus.FAILED,
                            output=None,
                            error=str(e),
                            started_at=created_at,
                            completed_at=completed_at
                        ).model_dump()
                        for target in req.targets
                    }
                    
                    # 推送失败结果
                    await connection_manager.broadcast_status({
                        "type": "command_result",
                        "request_id": request_id,
                        "status": CommandStatus.FAILED,
                        "created_at": created_at,
                        "completed_at": completed_at,
                        "results": command_results[request_id]["results"]
                    })
            
            # 创建后台任务
            asyncio.create_task(execute_async())
            
            # 立即返回
            return JSONResponse({
                "request_id": request_id,
                "status": CommandStatus.QUEUED,
                "created_at": created_at,
                "message": "Command queued for async execution. Use GET /api/v1/command/{request_id}/status to check status."
            })
    
    @router.get("/api/v1/command/unified/{request_id}/status")
    async def get_unified_command_status(
        request_id: str,
        auth: dict = Depends(require_auth)
    ):
        """
        查询异步统一命令执行状态和结果
        
        **响应示例：**
        ```json
        {
          "request_id": "xxx",
          "status": "done",
          "created_at": "2026-02-12T10:00:00Z",
          "completed_at": "2026-02-12T10:00:05Z",
          "results": {
            "device_1": {
              "status": "done",
              "output": {...},
              "error": null
            }
          }
        }
        ```
        """
        if request_id not in command_results:
            raise HTTPException(status_code=404, detail="Command not found")
        
        result = command_results[request_id]
        
        return JSONResponse({
            "request_id": result["request_id"],
            "status": result["status"],
            "created_at": result["created_at"],
            "completed_at": result["completed_at"],
            "results": result["results"]
        })
    
    # ========================================================================
    # /api/v1/chat - 智能对话接口 (意图分流: 纯聊天 / Agent 操作)
    # ========================================================================

    # 操作意图关键词 — 命中时走 ReAct Agent 调度而非纯聊天
    _ACTION_KEYWORDS_ZH = [
        "打开", "关闭", "启动", "运行", "安装", "卸载", "截图", "截屏",
        "点击", "滑动", "输入", "搜索", "发送", "下载", "上传",
        "复制", "粘贴", "传输", "同步", "分享",
        "拍照", "录屏", "录音", "播放", "暂停", "停止",
        "查看电量", "查看状态", "连接设备", "断开设备",
        "帮我操作", "帮我执行", "帮我控制",
        "在手机上", "在电脑上", "在平板上", "在设备上",
        "切换应用", "返回桌面", "锁屏", "解锁", "音量",
    ]
    _ACTION_KEYWORDS_EN = [
        "open ", "close ", "launch ", "run ", "install ", "click ",
        "swipe ", "type ", "screenshot", "send ", "download ",
        "upload ", "execute ", "control ", "operate ",
        "on my phone", "on my pc", "on device", "on android",
        "take photo", "record ", "play ", "pause ", "stop ",
    ]

    def _is_action_intent(msg: str) -> bool:
        """判断用户消息是否为操作指令 (需要 Agent 调度)"""
        msg_lower = msg.lower().strip()
        # 太短的消息大概率不是操作指令
        if len(msg_lower) < 4:
            return False
        for kw in _ACTION_KEYWORDS_ZH:
            if kw in msg_lower:
                return True
        for kw in _ACTION_KEYWORDS_EN:
            if kw in msg_lower:
                return True
        return False

    @router.post("/api/v1/chat")
    async def chat(req: ChatRequest):
        """
        统一对话接口 — 智能分流:
        1. 操作指令 → ReAct Agent 调度 (LLM + tool_call → 节点执行)
        2. 纯聊天 → LLM 对话回复

        所有 UI (Dashboard / Windows / Android) 统一调用此端点。
        """
        session_id = req.device_id or "default"

        try:
            # === 融合对话记忆 ===
            try:
                from core.ai_intent import get_conversation_memory
                memory = get_conversation_memory()
                await memory.add_turn(session_id, "user", req.message)
                if not req.context:
                    req.context = await memory.get_context(session_id, max_turns=10)
            except Exception:
                pass

            # === 意图分流 ===
            if _is_action_intent(req.message) and llm_manager.is_available():
                # ── 走 Agent ReAct 调度 ──
                result = await _handle_agent_action(req, session_id)
                return result
            else:
                # ── 走纯 LLM 对话 ──
                result = await _handle_pure_chat(req, session_id)
                return result

        except Exception as e:
            logger.error(f"对话失败: {e}")
            return JSONResponse({
                "success": False,
                "error": str(e),
                "reply": f"处理消息时出错: {str(e)}"
            })

    async def _handle_agent_action(req: ChatRequest, session_id: str) -> JSONResponse:
        """操作指令 → ReAct Agent 调度"""
        try:
            # 构建执行器回调 (复用 autonomous_execute 的逻辑)
            async def node_executor(node_id: str, action: str, params: dict):
                target_node_dir = os.path.join(nodes_root, node_id)
                if not os.path.isdir(target_node_dir):
                    for name in os.listdir(nodes_root):
                        if name.startswith(node_id) or node_id in name:
                            target_node_dir = os.path.join(nodes_root, name)
                            node_id_resolved = name
                            break
                    else:
                        # 尝试通过 WS 发送到已连接设备
                        for did, ws in connection_manager.active_devices.items():
                            try:
                                await ws.send_json({
                                    "type": "task",
                                    "task_type": action,
                                    "payload": params,
                                })
                                return {"success": True, "device": did, "action": action, "via": "websocket"}
                            except Exception:
                                continue
                        return {"error": f"Node {node_id} not found and no device available"}

                if not os.path.isdir(target_node_dir):
                    return {"error": f"Node {node_id} not found"}

                fusion_entry = os.path.join(target_node_dir, "fusion_entry.py")
                if not os.path.exists(fusion_entry):
                    return {"error": f"Node {node_id} has no fusion_entry.py"}

                node_instance = _load_node(node_id, target_node_dir, fusion_entry)
                if not node_instance:
                    return {"error": f"Failed to load node {node_id}"}

                try:
                    result = await _execute_node(node_instance, action, params)
                    return result
                except Exception as e:
                    return {"error": str(e)}

            # ws_sender: 通过 WebSocket 向设备发送任务
            async def ws_sender(device_id: str, message: dict):
                success = await connection_manager.send_to_device(device_id, message)
                if success:
                    return {"success": True, "device_id": device_id, "sent": message.get("task_type", "")}
                return {"success": False, "error": f"Device {device_id} not connected"}

            execution_context = {
                "devices": registered_devices,
                "executor": node_executor,
                "ws_sender": ws_sender,
            }

            plan_result = await scheduler.plan_and_execute(
                req.message,
                llm_manager,
                execution_context,
                max_turns=5,
            )

            reply = plan_result.get("reply", "任务已执行")
            steps = plan_result.get("steps", [])

            # 格式化带执行步骤的回复
            if steps:
                step_summary = "\n".join(
                    f"  {i+1}. [{s.get('node_id', '?')}] {s.get('action', '?')}"
                    for i, s in enumerate(steps)
                )
                full_reply = f"{reply}\n\n执行步骤:\n{step_summary}"
            else:
                full_reply = reply

            # 记录到对话记忆
            try:
                from core.ai_intent import get_conversation_memory
                memory = get_conversation_memory()
                await memory.add_turn(session_id, "assistant", full_reply)
            except Exception:
                pass

            return JSONResponse({
                "success": plan_result.get("success", True),
                "reply": full_reply,
                "model": llm_manager.get_default_model(),
                "mode": "agent_react",
                "steps": steps,
                "session_id": session_id,
            })

        except ValueError as ve:
            # LLM 不可用，降级到纯聊天
            logger.warning(f"Agent 调度失败 (LLM 不可用): {ve}, 降级到纯聊天")
            return await _handle_pure_chat(req, session_id)
        except Exception as e:
            logger.error(f"Agent 调度异常: {e}")
            return JSONResponse({
                "success": False,
                "reply": f"操作调度失败: {str(e)}",
                "mode": "agent_react_error",
                "session_id": session_id,
            })

    async def _handle_pure_chat(req: ChatRequest, session_id: str) -> JSONResponse:
        """纯 LLM 对话 (无工具调用)"""
        # 优先使用统一的 LLMManager
        if llm_manager.is_available():
            try:
                messages = [
                    {"role": "system", "content": (
                        "你是 UFO Galaxy 智能助手，一个 L4 级自主性 AI 系统。\n"
                        "当用户想要操作设备时，请告诉他们直接描述操作指令即可，"
                        "系统会自动调度 Agent 执行。例如: '帮我打开手机上的微信'。"
                    )},
                ]
                for ctx in (req.context or [])[-10:]:
                    messages.append(ctx)
                messages.append({"role": "user", "content": req.message})

                response = await llm_manager.chat_completion(messages=messages)
                reply = response.choices[0].message.content or ""
                model_name = response.model if hasattr(response, "model") else llm_manager.get_default_model()

                try:
                    from core.ai_intent import get_conversation_memory
                    memory = get_conversation_memory()
                    await memory.add_turn(session_id, "assistant", reply)
                except Exception:
                    pass

                return JSONResponse({
                    "success": True,
                    "reply": reply,
                    "model": model_name,
                    "mode": "chat",
                    "session_id": session_id,
                })
            except Exception as e:
                logger.warning(f"LLMManager chat failed: {e}")

        # LLMManager 已处理所有 Provider 的 fallback 链
        # 如果到这里说明没有任何可用的 LLM Provider
        return JSONResponse({
            "success": False,
            "error": "未配置 LLM API Key",
            "reply": (
                "LLM 服务未配置。请在 Dashboard 的 API CONFIG 面板设置 API Key，"
                "或在 .env 文件中设置 OPENAI_API_KEY / DEEPSEEK_API_KEY 等。"
            ),
        })

    async def _save_reply(session_id: str, response: JSONResponse):
        """保存 LLM 回复到对话记忆"""
        try:
            from core.ai_intent import get_conversation_memory
            memory = get_conversation_memory()
            # 从 JSONResponse 提取 reply
            import json as _json
            body = response.body.decode() if hasattr(response, 'body') else ""
            if body:
                data = _json.loads(body)
                if data.get("reply"):
                    await memory.add_turn(session_id, "assistant", data["reply"])
        except Exception:
            pass
    
    # ========================================================================
    # /api/v1/command - 命令路由引擎
    # ========================================================================

    from core.command_router import (
        CommandRouter, CommandRequest, CommandMode,
        CommandStatus as RouterCommandStatus, get_command_router,
    )

    # 初始化命令路由器，绑定 WebSocket 推送回调
    async def _on_command_status_change(cmd_result):
        """命令状态变更 → WebSocket 推送"""
        try:
            await connection_manager.push_command_result(cmd_result.to_dict())
        except Exception as e:
            logger.error(f"Command result push failed: {e}")

    command_router = get_command_router(on_status_change=_on_command_status_change)

    # 设置节点执行器
    async def _command_node_executor(target: str, command: str, params: dict):
        """命令路由 → 节点执行桥接"""
        target_node_dir = os.path.join(nodes_root, target)
        if not os.path.isdir(target_node_dir):
            # 模糊匹配
            for name in os.listdir(nodes_root):
                if name.startswith(target) or target in name:
                    target_node_dir = os.path.join(nodes_root, name)
                    target = name
                    break

        if not os.path.isdir(target_node_dir):
            # 可能是设备目标
            if target in connection_manager.active_devices:
                sent = await connection_manager.send_to_device(target, {
                    "type": "command",
                    "command": command,
                    "params": params,
                })
                return {"sent_to_device": target, "success": sent}
            return {"error": f"Target {target} not found"}

        fusion_entry = os.path.join(target_node_dir, "fusion_entry.py")
        if not os.path.exists(fusion_entry):
            return {"error": f"Target {target} has no fusion_entry.py"}

        node_instance = _load_node(target, target_node_dir, fusion_entry)
        if not node_instance:
            return {"error": f"Failed to load target {target}"}

        return await _execute_node(node_instance, command, params)

    command_router.set_executor(_command_node_executor)

    @router.post("/api/v1/command")
    async def dispatch_command(req: CommandDispatchRequest):
        """
        命令分发接口

        支持模式：
          - sync: 同步等待所有目标返回
          - async: 立即返回 request_id，后台执行
          - parallel: 多目标并行执行
          - serial: 多目标串行执行

        WebSocket 实时推送：当 notify_ws=true 时，结果通过 /ws/status 推送
        """
        cmd_request = CommandRequest(
            source=req.source,
            targets=req.targets if req.targets else ["system"],
            command=req.command,
            params=req.params,
            mode=CommandMode(req.mode),
            timeout=req.timeout,
            max_retries=req.max_retries,
            notify_ws=req.notify_ws,
            priority=req.priority,
            metadata=req.metadata,
        )

        try:
            result = await command_router.dispatch(cmd_request)
            return JSONResponse({
                "success": result.status.value in ("success", "partial"),
                **result.to_dict(),
            })
        except Exception as e:
            logger.error(f"Command dispatch failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/command/{request_id}")
    async def get_command_status(request_id: str):
        """查询命令执行状态和聚合结果"""
        result = await command_router.get_result(request_id)
        if not result:
            raise HTTPException(status_code=404, detail=f"Command {request_id} not found")
        return JSONResponse(result.to_dict())

    @router.delete("/api/v1/command/{request_id}")
    async def cancel_command(request_id: str):
        """取消正在执行的命令"""
        cancelled = await command_router.cancel(request_id)
        if not cancelled:
            raise HTTPException(status_code=404, detail="Command not found or already completed")
        return JSONResponse({"success": True, "message": f"Command {request_id} cancelled"})

    @router.get("/api/v1/command")
    async def command_stats():
        """获取命令路由引擎统计"""
        return JSONResponse(command_router.get_stats())

    # ========================================================================
    # /api/v1/ai - AI 意图理解 & 智能推荐
    # ========================================================================

    from core.ai_intent import (
        get_intent_parser, get_conversation_memory, get_smart_recommender,
    )

    intent_parser = get_intent_parser()
    conversation_memory = get_conversation_memory()
    smart_recommender = get_smart_recommender()

    @router.post("/api/v1/ai/intent")
    async def parse_intent(req: AIIntentRequest):
        """
        AI 意图解析

        自然语言 → 结构化命令
        双级解析：规则引擎 (< 1ms) + LLM (高精度)
        """
        context = req.context
        if req.session_id:
            history = await conversation_memory.get_context(req.session_id)
            context["history"] = history

        parsed = await intent_parser.parse(req.text, context)
        return JSONResponse({
            "success": True,
            **parsed.to_dict(),
        })

    @router.post("/api/v1/ai/conversation")
    async def manage_conversation(req: ConversationRequest):
        """添加对话轮次到记忆系统"""
        await conversation_memory.add_turn(
            session_id=req.session_id,
            role=req.role,
            content=req.content,
            metadata=req.metadata,
        )
        return JSONResponse({
            "success": True,
            "session_id": req.session_id,
            "turns": len(await conversation_memory.get_context(req.session_id, max_turns=100)),
        })

    @router.get("/api/v1/ai/conversation/{session_id}")
    async def get_conversation_context(session_id: str, max_turns: int = 10):
        """获取对话上下文"""
        context = await conversation_memory.get_context(session_id, max_turns)
        summary = await conversation_memory.get_summary(session_id)
        return JSONResponse({
            "session_id": session_id,
            "context": context,
            "summary": summary,
        })

    @router.get("/api/v1/ai/recommendations/{session_id}")
    async def get_recommendations(session_id: str):
        """获取智能推荐"""
        current_context = {
            "devices": registered_devices,
            "tasks": {k: v.get("status") for k, v in task_queue.items()},
        }
        recs = await smart_recommender.get_recommendations(session_id, current_context)
        return JSONResponse({
            "session_id": session_id,
            "recommendations": recs,
        })

    @router.delete("/api/v1/ai/conversation/{session_id}")
    async def clear_conversation(session_id: str):
        """清除对话记忆"""
        await conversation_memory.clear_session(session_id)
        return JSONResponse({"success": True, "message": f"Session {session_id} cleared"})

    # ========================================================================
    # /api/v1/monitoring - 监控仪表盘 & 告警
    # ========================================================================

    from core.monitoring import get_monitoring_manager, AlertSeverity

    monitoring = get_monitoring_manager()

    # 注册默认健康检查
    monitoring.health.register_check("api", lambda: {"status": "healthy"})
    monitoring.health.register_check("cache", lambda: {
        "status": "healthy",
        "backend": "memory",
    })

    @router.get("/api/v1/monitoring/dashboard")
    async def monitoring_dashboard():
        """完整监控仪表盘"""
        from core.performance import PerformanceMonitor
        perf = PerformanceMonitor.instance()

        dashboard = monitoring.get_full_dashboard()
        dashboard["performance"] = perf.get_dashboard()
        dashboard["command_router"] = command_router.get_stats()
        return JSONResponse(dashboard)

    @router.get("/api/v1/monitoring/health")
    async def monitoring_health():
        """健康检查聚合"""
        return JSONResponse(monitoring.health.get_status())

    @router.get("/api/v1/monitoring/alerts")
    async def monitoring_alerts():
        """告警列表"""
        return JSONResponse({
            "active": monitoring.alerts.get_active_alerts(),
            "history": monitoring.alerts.get_history(50),
        })

    @router.get("/api/v1/monitoring/metrics")
    async def monitoring_metrics():
        """系统指标"""
        return JSONResponse(monitoring.metrics.get_dashboard())

    @router.get("/metrics")
    @router.get("/health/metrics")
    async def prometheus_metrics():
        """Prometheus-compatible metrics endpoint (text/plain)"""
        import time as _time
        lines = []
        # Process uptime
        lines.append(f"# HELP process_uptime_seconds Time since process start")
        lines.append(f"# TYPE process_uptime_seconds gauge")
        lines.append(f"process_uptime_seconds {_time.time() - _startup_time:.1f}")

        # Active nodes / agents / devices
        try:
            status = monitoring.health.get_status()
            lines.append(f"# HELP galaxy_active_nodes Number of active nodes")
            lines.append(f"# TYPE galaxy_active_nodes gauge")
            lines.append(f"galaxy_active_nodes {status.get('nodes_active', 0)}")
            lines.append(f"# HELP galaxy_connected_devices Number of connected devices")
            lines.append(f"# TYPE galaxy_connected_devices gauge")
            lines.append(f"galaxy_connected_devices {status.get('devices_connected', 0)}")
        except Exception:
            pass

        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            rss = usage.ru_maxrss * 1024  # KB → bytes
            lines.append(f"# HELP process_resident_memory_bytes Resident memory size in bytes")
            lines.append(f"# TYPE process_resident_memory_bytes gauge")
            lines.append(f"process_resident_memory_bytes {rss}")
            lines.append(f"# HELP process_cpu_seconds_total Total CPU time")
            lines.append(f"# TYPE process_cpu_seconds_total counter")
            lines.append(f"process_cpu_seconds_total {usage.ru_utime + usage.ru_stime:.2f}")
        except Exception:
            pass

        from starlette.responses import Response
        return Response(content="\n".join(lines) + "\n", media_type="text/plain; charset=utf-8")

    @router.get("/api/v1/monitoring/performance")
    async def monitoring_performance():
        """性能指标仪表盘"""
        from core.performance import PerformanceMonitor
        perf = PerformanceMonitor.instance()
        return JSONResponse(perf.get_dashboard())

    # ========================================================================
    # /api/v1/health - 统一健康管理
    # ========================================================================

    @router.get("/api/v1/health/unified")
    async def unified_health_dashboard():
        """统一健康仪表盘（整合所有健康子系统）"""
        try:
            from core.health_integration import get_unified_health_manager
            uhm = get_unified_health_manager()
            return JSONResponse(uhm.get_dashboard())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/health/quick")
    async def unified_health_quick():
        """快速健康概览"""
        try:
            from core.health_integration import get_unified_health_manager
            uhm = get_unified_health_manager()
            return JSONResponse(uhm.get_quick_status())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ========================================================================
    # /api/v1/concurrency - 并发管理
    # ========================================================================

    @router.get("/api/v1/concurrency/status")
    async def concurrency_status():
        """并发管理器状态"""
        try:
            from core.concurrency_manager import get_concurrency_manager
            mgr = get_concurrency_manager()
            return JSONResponse(mgr.get_status())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ========================================================================
    # /api/v1/errors - 错误追踪
    # ========================================================================

    @router.get("/api/v1/errors/summary")
    async def error_summary():
        """错误追踪概览"""
        try:
            from core.error_framework import get_error_tracker
            tracker = get_error_tracker()
            return JSONResponse(tracker.get_summary())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ========================================================================
    # /api/v1/discovery - 节点发现
    # ========================================================================

    @router.get("/api/v1/discovery/status")
    async def discovery_status():
        """节点发现服务状态"""
        try:
            from core.node_discovery import get_node_discovery
            disc = get_node_discovery()
            return JSONResponse(disc.get_status())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ========================================================================
    # /api/v1/security - 安全审计
    # ========================================================================

    @router.get("/api/v1/security/audit")
    async def security_audit_logs():
        """审计日志（最近 50 条）"""
        try:
            from core.security_middleware import get_security_manager
            sec = get_security_manager()
            return JSONResponse(sec.audit.get_recent(50))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/security/stats")
    async def security_stats():
        """安全统计仪表盘"""
        try:
            from core.security_middleware import get_security_manager
            sec = get_security_manager()
            return JSONResponse(sec.get_dashboard())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ========================================================================
    # /api/v1/config - 配置管理
    # ========================================================================

    @router.get("/api/v1/config/status")
    async def config_manager_status():
        """配置管理器状态"""
        try:
            from core.config_hot_reload import get_config_manager
            mgr = get_config_manager()
            return JSONResponse(mgr.get_status())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/config/versions")
    async def config_version_history():
        """配置版本历史"""
        try:
            from core.config_hot_reload import get_config_manager
            mgr = get_config_manager()
            return JSONResponse(mgr.versions.get_history(20))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ========================================================================
    # Phase 2: Proxy-Relay — 设备间指令转发
    # ========================================================================

    from core.proxy_relay import get_proxy_relay, RelayRequest as ProxyRelayRequest

    proxy_relay = get_proxy_relay()

    # 绑定 WS sender 和在线设备获取
    proxy_relay.set_sender(connection_manager.send_to_device)
    proxy_relay.set_online_getter(lambda: list(connection_manager.active_devices.keys()))

    class DeviceRelayRequest(BaseModel):
        """设备间中继请求"""
        source_device: str
        target_device: str
        payload_type: str = "task"     # task / command / agent_deploy / chat / custom
        payload: Dict[str, Any] = {}
        expect_reply: bool = False
        timeout_seconds: float = 30.0
        chain: List[str] = []         # 链式转发目标

    @router.post("/api/v1/relay/send")
    async def relay_send(req: DeviceRelayRequest):
        """
        设备间中继 — Server 代理转发

        流程: source_device → Server(中继) → target_device
        如果 expect_reply=true, 服务端等待 target 回复后返回。
        """
        relay_req = ProxyRelayRequest(
            source_device=req.source_device,
            target_device=req.target_device,
            payload_type=req.payload_type,
            payload=req.payload,
            expect_reply=req.expect_reply,
            timeout_seconds=req.timeout_seconds,
            chain=req.chain,
        )
        result = await proxy_relay.relay(relay_req)
        return JSONResponse(result.to_dict())

    @router.post("/api/v1/relay/broadcast")
    async def relay_broadcast(source_device: str = "", payload_type: str = "task", payload: Dict[str, Any] = {}):
        """从一台设备广播到所有其他在线设备"""
        results = await proxy_relay.relay_broadcast(source_device, payload_type, payload)
        return JSONResponse({
            "source": source_device,
            "targets": {k: v.to_dict() for k, v in results.items()},
        })

    @router.get("/api/v1/relay/stats")
    async def relay_stats():
        """中继统计"""
        return JSONResponse(proxy_relay.get_stats())

    @router.get("/api/v1/relay/history")
    async def relay_history(limit: int = 50):
        """中继历史"""
        return JSONResponse({"history": proxy_relay.get_history(limit)})

    # ========================================================================
    # Phase 3: Hybrid Execution Arbiter — A2A → GUI → VLM 降级链
    # ========================================================================

    from core.hybrid_executor import get_hybrid_arbiter, ExecutionLevel

    hybrid_arbiter = get_hybrid_arbiter()

    class HybridExecuteRequest(BaseModel):
        """混合执行请求"""
        device_id: str
        app_id: str = ""
        action: str = ""
        params: Dict[str, Any] = {}
        instruction: str = ""
        force_level: Optional[str] = None  # a2a / gui / vlm

    @router.post("/api/v1/hybrid/execute")
    async def hybrid_execute(req: HybridExecuteRequest):
        """
        混合执行 — 三级降级: A2A → GUI → VLM

        Level 1 (A2A): 通过 API/MCP 直接调用 (最快, 最准)
        Level 2 (GUI): 通过 UI 自动化操控 (需要 Accessibility)
        Level 3 (VLM): 截图 + 视觉理解 + 推理操作 (兜底)
        """
        force = ExecutionLevel(req.force_level) if req.force_level else None
        result = await hybrid_arbiter.execute(
            device_id=req.device_id,
            app_id=req.app_id,
            action=req.action,
            params=req.params,
            instruction=req.instruction,
            force_level=force,
        )
        return JSONResponse(result.to_dict())

    @router.get("/api/v1/hybrid/stats")
    async def hybrid_stats():
        """混合执行统计"""
        return JSONResponse(hybrid_arbiter.get_stats())

    @router.get("/api/v1/hybrid/registry")
    async def hybrid_registry():
        """应用能力注册表"""
        return JSONResponse({"apps": hybrid_arbiter.registry.list_apps()})

    # ========================================================================
    # Phase 4: RAG Memory + SafeExecutor
    # ========================================================================

    from core.rag_memory import get_rag_memory
    from core.safe_executor import get_safe_executor

    rag_memory = get_rag_memory()
    safe_executor = get_safe_executor()

    class RAGQueryRequest(BaseModel):
        """RAG 检索请求"""
        query: str
        top_k: int = 5
        include_experience: bool = True
        include_knowledge: bool = True
        device_id: str = ""

    class CodeExecuteRequest(BaseModel):
        """安全代码执行请求"""
        code: str
        language: str = "python"
        timeout: int = 15
        stdin: str = ""

    @router.post("/api/v1/rag/query")
    async def rag_query(req: RAGQueryRequest):
        """
        RAG 综合检索 — 经验 + 知识

        返回可注入 Agent prompt 的增强上下文。
        """
        enhanced_context = await rag_memory.enhance_agent_prompt(
            instruction=req.query,
            device_id=req.device_id,
            include_experience=req.include_experience,
            include_knowledge=req.include_knowledge,
        )
        similar_experiences = rag_memory.recall_similar(req.query, top_k=req.top_k, device_id=req.device_id)
        return JSONResponse({
            "enhanced_context": enhanced_context,
            "experiences": [e.to_dict() for e in similar_experiences],
            "patterns": rag_memory.get_learned_patterns(),
        })

    @router.get("/api/v1/rag/stats")
    async def rag_stats():
        """RAG 记忆统计"""
        return JSONResponse(rag_memory.get_stats())

    @router.get("/api/v1/rag/patterns")
    async def rag_patterns():
        """已学习的 Patterns"""
        return JSONResponse({"patterns": rag_memory.get_learned_patterns()})

    @router.post("/api/v1/code/execute")
    async def code_execute(req: CodeExecuteRequest):
        """
        安全代码执行 — Agent 自编码运行时

        安全检查 → 沙箱执行 → 返回结果
        """
        result = await safe_executor.execute(
            code=req.code,
            language=req.language,
            timeout=req.timeout,
            stdin=req.stdin,
        )
        return JSONResponse(result.to_dict())

    @router.get("/api/v1/code/stats")
    async def code_stats():
        """代码执行统计"""
        return JSONResponse(safe_executor.get_stats())

    # ========================================================================
    # Phase 5: P2P Mesh Overlay — 混合组网
    # ========================================================================

    from core.mesh_coordinator import get_mesh_coordinator

    mesh_coordinator = get_mesh_coordinator()

    # 绑定 WS sender + Relay sender
    mesh_coordinator._ws_send = connection_manager.send_to_device

    async def _mesh_relay_send(source, target, payload_type, payload):
        result = await proxy_relay.relay(ProxyRelayRequest(
            source_device=source,
            target_device=target,
            payload_type=payload_type,
            payload=payload,
        ))
        return result.to_dict()

    mesh_coordinator._relay_send = _mesh_relay_send

    class MeshSendRequest(BaseModel):
        """Mesh 发送请求"""
        target_device: str
        payload: Dict[str, Any] = {}
        payload_type: str = "task"
        source_device: str = ""

    class PeerAnnounceRequest(BaseModel):
        """Peer 上报请求"""
        device_id: str
        local_ip: str = ""
        local_port: int = 0
        public_ip: str = ""
        public_port: int = 0
        metadata: Dict[str, Any] = {}

    @router.post("/api/v1/mesh/send")
    async def mesh_send(req: MeshSendRequest):
        """
        Mesh 发送 — P2P 直连 / Relay 自动选路

        自动探测: LAN 可达 → P2P 直连; 否则 → 服务端 Relay 中继。
        """
        result = await mesh_coordinator.send(
            target_device=req.target_device,
            payload=req.payload,
            payload_type=req.payload_type,
            source_device=req.source_device,
        )
        return JSONResponse(result.to_dict())

    @router.post("/api/v1/mesh/peer_announce")
    async def mesh_peer_announce(req: PeerAnnounceRequest):
        """设备上报 LAN 地址信息"""
        peer = mesh_coordinator.handle_peer_announce(req.device_id, req.dict())
        return JSONResponse(peer.to_dict())

    @router.post("/api/v1/mesh/peer_exchange")
    async def mesh_peer_exchange():
        """触发 peer 列表交换 — 广播给所有设备"""
        await mesh_coordinator.broadcast_peer_exchange()
        return JSONResponse({"status": "exchanged", "peers": mesh_coordinator.list_peers()})

    @router.get("/api/v1/mesh/topology")
    async def mesh_topology():
        """获取完整拓扑图 (nodes + edges)"""
        return JSONResponse(mesh_coordinator.get_topology())

    @router.get("/api/v1/mesh/peers")
    async def mesh_peers():
        """获取所有 peer 列表"""
        return JSONResponse({"peers": mesh_coordinator.list_peers()})

    @router.get("/api/v1/mesh/stats")
    async def mesh_stats():
        """Mesh 网络统计"""
        return JSONResponse(mesh_coordinator.get_stats())

    @router.post("/api/v1/mesh/probe")
    async def mesh_probe():
        """手动触发所有 peer 的 TCP 可达性探测"""
        await mesh_coordinator.probe_all_peers()
        return JSONResponse({"status": "probed", "peers": mesh_coordinator.list_peers()})

    # ========================================================================
    # 凭证 Vault API
    # ========================================================================

    # Rate limiters for sensitive endpoints (in-memory token bucket per client IP)
    try:
        from core.security_middleware import RateLimiter as _RateLimiter
        _vault_fetch_limiter = _RateLimiter(requests_per_minute=30, burst_size=10)
        _channel_send_limiter = _RateLimiter(requests_per_minute=60, burst_size=20)
    except Exception:
        _vault_fetch_limiter = None
        _channel_send_limiter = None

    @router.post("/api/v1/vault/credentials")
    async def vault_set_credential(request: Request):
        """管理端写入/更新凭证"""
        body = await request.json()
        key_name = body.get("key_name", "")
        value = body.get("value", "")
        if not key_name or not value:
            raise HTTPException(status_code=400, detail="key_name and value are required")
        try:
            from core.credential_vault import get_vault
            get_vault().set_credential(key_name, value)
            return JSONResponse({"success": True, "key_name": key_name})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/vault/credentials")
    async def vault_list_credentials():
        """列出所有凭证键名（不返回值）"""
        try:
            from core.credential_vault import get_vault
            return JSONResponse({"keys": get_vault().list_credential_keys()})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.delete("/api/v1/vault/credentials/{key_name}")
    async def vault_delete_credential(key_name: str):
        """删除 Vault 内的凭证"""
        try:
            from core.credential_vault import get_vault
            deleted = get_vault().delete_credential(key_name)
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Credential '{key_name}' not found")
            return JSONResponse({"success": True, "key_name": key_name})
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/vault/tokens")
    async def vault_issue_token(request: Request):
        """为 Worker/Device 颁发短期 token"""
        body = await request.json()
        device_id = body.get("device_id", "")
        ttl = int(body.get("ttl", 300))
        scopes = body.get("scopes")  # None 表示全部
        if not device_id:
            raise HTTPException(status_code=400, detail="device_id is required")
        try:
            from core.credential_vault import get_vault
            token = get_vault().issue_token(device_id, ttl=ttl, scopes=scopes)
            return JSONResponse({"success": True, "token": token, "ttl": ttl})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/vault/fetch")
    async def vault_fetch_by_token(request: Request):
        """Worker 用 token 拉取凭证"""
        if _vault_fetch_limiter is not None:
            client_ip = request.client.host if request.client else "unknown"
            if not _vault_fetch_limiter.is_allowed(client_ip):
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
        body = await request.json()
        token = body.get("token", "")
        key_name = body.get("key_name", "")
        if not token or not key_name:
            raise HTTPException(status_code=400, detail="token and key_name are required")
        try:
            from core.credential_vault import get_vault
            value = get_vault().get_credential_by_token(token, key_name)
            if value is None:
                raise HTTPException(status_code=403, detail="Invalid token or insufficient scope")
            return JSONResponse({"success": True, "key_name": key_name, "value": value})
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/vault/audit")
    async def vault_audit_log(limit: int = 100):
        """获取最近 N 条凭证访问审计记录"""
        try:
            from core.credential_vault import get_vault
            return JSONResponse({"records": get_vault().get_audit_log(limit=limit)})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/vault/cleanup")
    async def vault_cleanup_tokens():
        """清理过期 token，返回清理数量"""
        try:
            from core.credential_vault import get_vault
            count = get_vault().cleanup_expired_tokens()
            return JSONResponse({"success": True, "cleaned_up": count})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/vault/health")
    async def vault_health():
        """Vault 健康状态：token 数量、凭证键数量、审计条目数"""
        try:
            from core.credential_vault import get_vault
            return JSONResponse(get_vault().get_health_metrics())
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/vault/tokens/{token}/info")
    async def vault_token_info(token: str):
        """获取 token 元信息（device_id、过期时间、scopes 等，不含凭证值）"""
        try:
            from core.credential_vault import get_vault
            info = get_vault().get_token_info(token)
            if info is None:
                raise HTTPException(status_code=404, detail="Token not found or expired")
            return JSONResponse(info)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/vault/tokens/validate")
    async def vault_validate_token(request: Request):
        """验证 token 有效性，返回 valid 和 device_id"""
        body = await request.json()
        token = body.get("token", "")
        if not token:
            raise HTTPException(status_code=400, detail="token is required")
        try:
            from core.credential_vault import get_vault
            valid, device_id = get_vault().validate_token(token)
            return JSONResponse({"valid": valid, "device_id": device_id})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ========================================================================
    # 成本追踪 API
    # ========================================================================

    @router.get("/api/v1/cost/records")
    async def cost_get_records(limit: int = 50, provider: str = "", model: str = ""):
        """获取最近 N 条 LLM 调用成本记录，支持按 provider/model 过滤"""
        try:
            from core.cost_tracker import get_cost_tracker
            tracker = get_cost_tracker()
            if provider or model:
                records = tracker.get_recent_filtered(
                    limit=limit,
                    provider=provider or None,
                    model=model or None,
                )
            else:
                records = tracker.get_recent(limit=limit)
            return JSONResponse({"records": records})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/cost/summary")
    async def cost_get_summary():
        """获取 LLM 调用成本汇总统计"""
        try:
            from core.cost_tracker import get_cost_tracker
            return JSONResponse(get_cost_tracker().get_summary())
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/cost/health")
    async def cost_health():
        """获取成本追踪器写入健康状态"""
        try:
            from core.cost_tracker import get_cost_tracker
            return JSONResponse(get_cost_tracker().get_write_health())
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ========================================================================
    # 渠道插件 API
    # ========================================================================

    @router.get("/api/v1/channels")
    async def channel_list_plugins():
        """列出已加载的渠道插件"""
        try:
            from core.channel_plugins import get_channel_loader
            return JSONResponse({"plugins": get_channel_loader().list_plugins()})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/channels/load")
    async def channel_load_plugin(request: Request):
        """加载渠道插件（内置或外部路径）"""
        body = await request.json()
        plugin_id = body.get("plugin_id", "")
        path = body.get("path")  # None 表示内置
        config = body.get("config")
        if not plugin_id:
            raise HTTPException(status_code=400, detail="plugin_id is required")
        try:
            from core.channel_plugins import get_channel_loader
            result = await get_channel_loader().load_plugin(plugin_id, path=path, config=config)
            if not result.get("success"):
                raise HTTPException(status_code=400, detail=result.get("error", "load failed"))
            return JSONResponse(result)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/channels/auto_load")
    async def channel_auto_load(request: Request):
        """自动扫描并加载渠道插件目录（默认 external/channels/）"""
        try:
            body = {}
            try:
                body = await request.json()
            except Exception:
                logger.debug("channel_auto_load: no JSON body, using defaults")
            plugins_dir = body.get("directory") if body else None
            from core.channel_plugins import get_channel_loader
            result = await get_channel_loader().auto_load_plugins(plugins_dir=plugins_dir)
            return JSONResponse(result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/channels/{plugin_id}/send")
    async def channel_send_message(plugin_id: str, request: Request):
        """通过指定渠道插件发送消息"""
        if _channel_send_limiter is not None:
            client_ip = request.client.host if request.client else "unknown"
            if not _channel_send_limiter.is_allowed(client_ip):
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
        body = await request.json()
        message = body.get("message", "")
        if not message:
            raise HTTPException(status_code=400, detail="message is required")
        try:
            from core.channel_plugins import get_channel_loader
            result = await get_channel_loader().send(plugin_id, message, **{
                k: v for k, v in body.items() if k != "message"
            })
            return JSONResponse(result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/channels/health")
    async def channel_health_check():
        """检查所有已加载渠道插件健康状态"""
        try:
            from core.channel_plugins import get_channel_loader
            results = await get_channel_loader().health_check_all()
            if not results:
                overall = "unknown"
            elif all(
                isinstance(v, dict) and v.get("healthy", False)
                for v in results.values()
            ):
                overall = "healthy"
            else:
                overall = "degraded"
            return JSONResponse({"health": results, "overall": overall})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/channels/{plugin_id}/schema")
    async def channel_get_schema(plugin_id: str):
        """获取指定渠道插件的配置 schema"""
        try:
            from core.channel_plugins import get_channel_loader
            adapter = get_channel_loader().get_adapter(plugin_id)
            if adapter is None:
                raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not loaded")
            return JSONResponse({"plugin_id": plugin_id, "schema": adapter.get_config_schema()})
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ========================================================================
    # Galaxy Federation API
    # ========================================================================

    @router.get("/api/v1/federation/info")
    async def federation_info():
        """获取本实例联邦信息"""
        try:
            from core.galaxy_federation import get_federation
            return JSONResponse(get_federation().local_info())
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/federation/peers")
    async def federation_list_peers():
        """列出所有已知的联邦 peer 实例"""
        try:
            from core.galaxy_federation import get_federation
            return JSONResponse({"peers": get_federation().list_peers()})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/federation/peers")
    async def federation_register_peer(request: Request):
        """手动注册一个 peer 实例"""
        body = await request.json()
        url = body.get("url", "")
        instance_id = body.get("instance_id", "")
        name = body.get("name", "")
        if not url:
            raise HTTPException(status_code=400, detail="url is required")
        try:
            from core.galaxy_federation import get_federation
            peer = get_federation().register_peer(url, instance_id=instance_id, name=name)
            return JSONResponse({"success": True, "peer": peer.to_dict()})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.delete("/api/v1/federation/peers/{instance_id}")
    async def federation_unregister_peer(instance_id: str):
        """注销指定 peer 实例"""
        try:
            from core.galaxy_federation import get_federation
            removed = get_federation().unregister_peer(instance_id)
            if not removed:
                raise HTTPException(status_code=404, detail=f"Peer '{instance_id}' not found")
            return JSONResponse({"success": True, "instance_id": instance_id})
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/federation/peers/cleanup")
    async def federation_cleanup_peers(max_age: int = 60):
        """移除 last_heartbeat 超过 max_age 秒的 stale peers"""
        try:
            from core.galaxy_federation import get_federation
            removed = get_federation().cleanup_stale_peers(max_age=max_age)
            return JSONResponse({"success": True, "removed": removed})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/federation/heartbeat")
    async def federation_receive_heartbeat(request: Request):
        """接收来自其他实例的心跳"""
        body = await request.json()
        try:
            from core.galaxy_federation import get_federation
            result = get_federation().receive_heartbeat(body)
            return JSONResponse(result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/federation/task")
    async def federation_receive_task(request: Request):
        """接收来自其他实例的转发任务（简单 echo 处理）"""
        body = await request.json()
        from_instance = body.get("from_instance", "unknown")
        task = body.get("task", {})
        logger.info(f"Federation task received from {from_instance}: {task.get('command', '')}")
        # 实际场景中可接入 command_router 处理
        return JSONResponse({
            "success": True,
            "from_instance": from_instance,
            "task_received": task,
        })

    @router.post("/api/v1/federation/forward")
    async def federation_forward_task(request: Request):
        """将任务转发给指定 peer 实例"""
        body = await request.json()
        target = body.get("target", "")
        task = body.get("task", {})
        if not target:
            raise HTTPException(status_code=400, detail="target is required")
        try:
            from core.galaxy_federation import get_federation
            result = await get_federation().forward_task(target, task)
            return JSONResponse(result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/federation/health")
    async def federation_health_summary():
        """联邦健康摘要：本地状态 + peers 数量 + alive/degraded/offline 统计"""
        try:
            from core.galaxy_federation import get_federation, _federation_enabled
            fed = get_federation()
            peers = fed.list_peers()
            alive = sum(1 for p in peers if p["status"] == "healthy")
            degraded = sum(1 for p in peers if p["status"] == "degraded")
            offline = sum(1 for p in peers if p["status"] == "offline")
            return JSONResponse({
                "instance_id": fed.instance_id,
                "local_url": fed.local_url,
                "enabled": _federation_enabled(),
                "peers_count": len(peers),
                "alive": alive,
                "degraded": degraded,
                "offline": offline,
            })
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/federation/peers/{instance_id}/ping")
    async def federation_peer_ping(instance_id: str):
        """检查特定 peer 的最后心跳时间，返回状态和心跳年龄"""
        try:
            from core.galaxy_federation import get_federation
            peer = get_federation().get_peer(instance_id)
            if not peer:
                raise HTTPException(status_code=404, detail=f"Peer '{instance_id}' not found")
            age = time.time() - peer.last_heartbeat
            return JSONResponse({
                "instance_id": instance_id,
                "status": peer.status,
                "last_heartbeat_age_s": round(age, 1),
                "alive": peer.is_alive(),
            })
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return router


# ============================================================================
# LLM 降级调用
# ============================================================================

async def _chat_with_gemini(req: ChatRequest, api_key: str) -> JSONResponse:
    """使用 Gemini API 进行对话"""
    import httpx
    
    contents = []
    for ctx in req.context[-10:]:
        role = "user" if ctx.get("role") == "user" else "model"
        contents.append({"role": role, "parts": [{"text": ctx.get("content", "")}]})
    contents.append({"role": "user", "parts": [{"text": req.message}]})
    
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
            json={
                "contents": contents,
                "systemInstruction": {
                    "parts": [{"text": "你是 UFO Galaxy 智能助手，一个 L4 级自主性 AI 系统。"}]
                }
            }
        )
        resp.raise_for_status()
        data = resp.json()
        reply = data["candidates"][0]["content"]["parts"][0]["text"]
        
        return JSONResponse({
            "success": True,
            "reply": reply,
            "model": "gemini-2.0-flash"
        })


async def _chat_with_openrouter(req: ChatRequest, api_key: str) -> JSONResponse:
    """使用 OpenRouter API 进行对话"""
    import httpx
    
    messages = [{"role": "system", "content": "你是 UFO Galaxy 智能助手，一个 L4 级自主性 AI 系统。"}]
    for ctx in req.context[-10:]:
        messages.append(ctx)
    messages.append({"role": "user", "content": req.message})
    
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "google/gemini-2.0-flash-exp:free",
                "messages": messages,
                "max_tokens": 2048
            }
        )
        resp.raise_for_status()
        data = resp.json()
        reply = data["choices"][0]["message"]["content"]
        
        return JSONResponse({
            "success": True,
            "reply": reply,
            "model": data.get("model", "openrouter")
        })


# ============================================================================
# WebSocket 端点
# ============================================================================

def create_websocket_routes(app: FastAPI, service_manager=None):
    """创建 WebSocket 端点"""
    
    @app.websocket("/ws/device/{device_id}")
    async def device_websocket(websocket: WebSocket, device_id: str):
        """设备 WebSocket 连接 - 双向通信"""
        await connection_manager.connect_device(websocket, device_id)
        
        # 更新设备在线状态
        if device_id in registered_devices:
            registered_devices[device_id]["last_seen"] = datetime.now().isoformat()
            registered_devices[device_id]["status"] = "online"
        
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type", "")
                
                if msg_type == "heartbeat":
                    # 心跳
                    if device_id in registered_devices:
                        registered_devices[device_id]["last_seen"] = datetime.now().isoformat()
                    await websocket.send_json({
                        "type": "heartbeat_ack",
                        "timestamp": datetime.now().isoformat()
                    })
                    
                elif msg_type == "status_update":
                    # 设备状态更新
                    if device_id in registered_devices:
                        registered_devices[device_id]["status_detail"] = data.get("status", {})
                        registered_devices[device_id]["last_seen"] = datetime.now().isoformat()
                    await connection_manager.broadcast_status({
                        "type": "device_status_update",
                        "device_id": device_id,
                        "status": data.get("status", {}),
                        "timestamp": datetime.now().isoformat()
                    })
                    
                elif msg_type == "command_result":
                    # 设备返回的命令执行结果 — 匹配等待中的 Future
                    cmd_id = data.get("command_id")
                    if cmd_id:
                        connection_manager.resolve_command_response(cmd_id, data.get("payload", data))
                    # 同时推送给 status 订阅者
                    await connection_manager.broadcast_status({
                        "type": "command_result",
                        "device_id": device_id,
                        "data": data,
                        "timestamp": datetime.now().isoformat()
                    })

                elif msg_type == "task_result":
                    # 任务结果回调
                    task_id = data.get("task_id", "")
                    if task_id in task_queue:
                        task_queue[task_id]["status"] = "completed"
                        task_queue[task_id]["result"] = data.get("result", {})
                        task_queue[task_id]["completed_at"] = datetime.now().isoformat()
                    
                elif msg_type == "ocr_request":
                    # OCR 请求
                    image_b64 = data.get("image", "")
                    mode = data.get("mode", "full")
                    instruction = data.get("instruction", "")
                    
                    try:
                        image_data = base64.b64decode(image_b64)
                        from core.vision_pipeline import VisionPipeline
                        pipeline = VisionPipeline()
                        result = await asyncio.get_event_loop().run_in_executor(
                            None, pipeline.understand, image_data, mode, instruction
                        )
                        await websocket.send_json({
                            "type": "ocr_result",
                            "request_id": data.get("request_id", ""),
                            "success": True,
                            "result": result
                        })
                    except Exception as e:
                        await websocket.send_json({
                            "type": "ocr_result",
                            "request_id": data.get("request_id", ""),
                            "success": False,
                            "error": str(e)
                        })
                    
                elif msg_type == "chat":
                    # 对话请求 — 复用 /api/v1/chat 的智能分流逻辑
                    try:
                        chat_req = ChatRequest(
                            message=data.get("message", ""),
                            device_id=device_id,
                            context=data.get("context", [])
                        )

                        # 通过内部调用复用 REST chat 端点的智能分流
                        if _is_action_intent(chat_req.message) and llm_manager.is_available():
                            # 操作指令 → ReAct Agent 调度
                            result = await _handle_agent_action(chat_req, device_id)
                            # 从 JSONResponse 提取 body
                            import json as _json
                            body = _json.loads(result.body.decode())
                            await websocket.send_json({
                                "type": "chat_reply",
                                "request_id": data.get("request_id", ""),
                                "reply": body.get("reply", ""),
                                "mode": "agent_react",
                                "steps": body.get("steps", []),
                            })
                        else:
                            # 纯聊天
                            result = await _handle_pure_chat(chat_req, device_id)
                            import json as _json
                            body = _json.loads(result.body.decode())
                            await websocket.send_json({
                                "type": "chat_reply",
                                "request_id": data.get("request_id", ""),
                                "reply": body.get("reply", "LLM 服务未配置"),
                                "mode": "chat",
                            })
                    except Exception as e:
                        await websocket.send_json({
                            "type": "chat_reply",
                            "request_id": data.get("request_id", ""),
                            "reply": f"处理消息时出错: {str(e)}"
                        })
                
                elif msg_type == "command_dispatch":
                    # 通过 WebSocket 分发命令
                    try:
                        from core.command_router import (
                            CommandRequest, CommandMode, get_command_router,
                        )
                        cmd_router = get_command_router()
                        cmd_req = CommandRequest(
                            source=f"ws:{device_id}",
                            targets=data.get("targets", []),
                            command=data.get("command", ""),
                            params=data.get("params", {}),
                            mode=CommandMode(data.get("mode", "sync")),
                            timeout=data.get("timeout", 30.0),
                            notify_ws=True,
                        )
                        result = await cmd_router.dispatch(cmd_req)
                        await websocket.send_json({
                            "type": "command_result",
                            "request_id": result.request_id,
                            "data": result.to_dict(),
                        })
                    except Exception as e:
                        await websocket.send_json({
                            "type": "command_error",
                            "request_id": data.get("request_id", ""),
                            "error": str(e),
                        })

                elif msg_type == "relay_request":
                    # Phase 2: 设备 A 发起 D2D 转发请求
                    try:
                        from core.proxy_relay import get_proxy_relay
                        relay = get_proxy_relay()
                        relay.set_sender(connection_manager.send_to_device)
                        relay.set_online_getter(lambda: list(connection_manager.active_devices.keys()))
                        result = await relay.handle_relay_request_from_device(device_id, data)
                        # 回传结果给 source device
                        await websocket.send_json({
                            "type": "relay_ack",
                            "relay_id": data.get("relay_id", ""),
                            **result.to_dict(),
                        })
                    except Exception as e:
                        await websocket.send_json({
                            "type": "relay_ack",
                            "relay_id": data.get("relay_id", ""),
                            "status": "failed",
                            "error": str(e),
                        })

                elif msg_type == "relay_reply":
                    # Phase 2: 设备 B 回复中继消息
                    try:
                        from core.proxy_relay import get_proxy_relay
                        relay = get_proxy_relay()
                        await relay.handle_relay_reply(
                            relay_id=data.get("relay_id", ""),
                            reply_payload=data.get("payload", {}),
                        )
                    except Exception as e:
                        logger.error(f"Relay reply handling failed: {e}")

                elif msg_type == "peer_announce":
                    # Phase 5: 设备上报 LAN 地址信息
                    try:
                        from core.mesh_coordinator import get_mesh_coordinator
                        mesh = get_mesh_coordinator()
                        peer = mesh.handle_peer_announce(device_id, data)
                        # 回传确认 + 下发 peer 列表
                        peer_list = mesh.build_peer_exchange(exclude_device=device_id)
                        await websocket.send_json({
                            "type": "peer_exchange",
                            "peers": peer_list,
                            "your_peer": peer.to_dict(),
                        })
                    except Exception as e:
                        logger.error(f"Peer announce handling failed: {e}")

                elif msg_type == "peer_exchange_request":
                    # Phase 5: 设备请求最新 peer 列表
                    try:
                        from core.mesh_coordinator import get_mesh_coordinator
                        mesh = get_mesh_coordinator()
                        peer_list = mesh.build_peer_exchange(exclude_device=device_id)
                        await websocket.send_json({
                            "type": "peer_exchange",
                            "peers": peer_list,
                        })
                    except Exception as e:
                        logger.error(f"Peer exchange request failed: {e}")

                elif msg_type == "agent_deploy_ack":
                    # 端侧确认收到 Agent Manifest
                    manifest_id = data.get("manifest_id", "")
                    logger.info(f"Agent {manifest_id} 已被设备 {device_id} 接收")
                    await connection_manager.broadcast_status({
                        "type": "agent_deploy_ack",
                        "device_id": device_id,
                        "manifest_id": manifest_id,
                        "timestamp": datetime.now().isoformat(),
                    })

                elif msg_type == "agent_status":
                    # Agent 执行状态上报 (Thought/Action/Observation)
                    await connection_manager.broadcast_status({
                        "type": "agent_status",
                        "device_id": device_id,
                        "manifest_id": data.get("manifest_id", ""),
                        "step": data.get("step", {}),
                        "timestamp": datetime.now().isoformat(),
                    })

                elif msg_type == "agent_result":
                    # Agent 执行完成结果
                    manifest_id = data.get("manifest_id", "")
                    logger.info(f"Agent {manifest_id} 在设备 {device_id} 执行完成")
                    await connection_manager.broadcast_status({
                        "type": "agent_result",
                        "device_id": device_id,
                        "manifest_id": manifest_id,
                        "result": data.get("result", {}),
                        "timestamp": datetime.now().isoformat(),
                    })

                elif msg_type == "ai_intent":
                    # 通过 WebSocket 调用 AI 意图解析
                    try:
                        from core.ai_intent import get_intent_parser
                        parser = get_intent_parser()
                        parsed = await parser.parse(data.get("text", ""))
                        await websocket.send_json({
                            "type": "ai_intent_result",
                            "request_id": data.get("request_id", ""),
                            **parsed.to_dict(),
                        })
                    except Exception as e:
                        await websocket.send_json({
                            "type": "ai_intent_error",
                            "request_id": data.get("request_id", ""),
                            "error": str(e),
                        })

                else:
                    # 未知消息类型
                    logger.warning(f"未知消息类型: {msg_type} from {device_id}")
                    await websocket.send_json({
                        "type": "error",
                        "message": f"未知消息类型: {msg_type}"
                    })
                    
        except WebSocketDisconnect:
            connection_manager.disconnect_device(device_id)
            if device_id in registered_devices:
                registered_devices[device_id]["status"] = "offline"
            await connection_manager.broadcast_status({
                "type": "device_disconnected",
                "device_id": device_id,
                "timestamp": datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"WebSocket 错误 ({device_id}): {e}")
            connection_manager.disconnect_device(device_id)
    
    @app.websocket("/ws/status")
    async def status_websocket(websocket: WebSocket):
        """
        状态推送 WebSocket - 订阅系统状态变更

        自动接收的推送类型：
          - device_connected / device_disconnected
          - device_status_update
          - command_result (命令执行结果)
          - initial_status (连接时的快照)

        客户端可发送：
          - "ping" → 返回 "pong"
          - JSON {"type": "subscribe_commands"} → 确认订阅命令结果
          - JSON {"type": "get_metrics"} → 返回性能指标
        """
        await connection_manager.subscribe_status(websocket)
        try:
            # 发送当前状态
            await websocket.send_json({
                "type": "initial_status",
                "devices_online": len(connection_manager.active_devices),
                "devices_registered": len(registered_devices),
                "timestamp": datetime.now().isoformat()
            })

            while True:
                # 保持连接，等待客户端消息
                raw = await websocket.receive_text()
                if raw == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.now().isoformat()
                    })
                else:
                    # 尝试解析 JSON 消息
                    try:
                        msg = json.loads(raw)
                        msg_type = msg.get("type", "")

                        if msg_type == "subscribe_commands":
                            await websocket.send_json({
                                "type": "subscribed",
                                "channel": "command_results",
                                "timestamp": datetime.now().isoformat(),
                            })

                        elif msg_type == "get_metrics":
                            from core.performance import PerformanceMonitor
                            perf = PerformanceMonitor.instance()
                            await websocket.send_json({
                                "type": "metrics",
                                "data": perf.get_dashboard(),
                                "timestamp": datetime.now().isoformat(),
                            })

                        elif msg_type == "get_health":
                            from core.monitoring import get_monitoring_manager
                            mon = get_monitoring_manager()
                            await websocket.send_json({
                                "type": "health",
                                "data": mon.health.get_status(),
                                "timestamp": datetime.now().isoformat(),
                            })

                    except (json.JSONDecodeError, ValueError):
                        pass

        except WebSocketDisconnect:
            connection_manager.unsubscribe_status(websocket)
        except Exception:
            connection_manager.unsubscribe_status(websocket)
