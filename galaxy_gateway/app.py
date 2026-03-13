"""
Galaxy Gateway - 主应用入口

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
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from pydantic import BaseModel

from .protocol import (
    AIPMessage, MessageType, DeviceType, DeviceInfo,
    parse_message, create_error_message
)
from .transport import WebSocketManager
from .handlers import DeviceManager, MessageHandler
from .orchestrator import TaskOrchestrator, TaskPriority
from .webrtc_proxy import (
    check_node95_reachable,
    get_webrtc_endpoint_info,
    proxy_webrtc_signaling,
)
from nodes.common.cors_config import get_cors_origins
from typing import Dict, Any

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
openclawd_instance: Optional[Any] = None  # Phase 3: OpenClawd 统一智能入口
llm_router_instance: Optional[Any] = None  # Phase 6: LLM 路由器（用于统计）


# ============================================================================
# Bearer Auth Middleware
# ============================================================================

# Paths that are always public regardless of auth setting
_AUTH_EXEMPT_PATHS = {"/health", "/api/v1/health"}


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """
    Optional Bearer token middleware for the Galaxy Gateway.

    Enabled when ``GALAXY_AUTH_ENABLED=true`` and ``GALAXY_API_TOKEN`` is set.
    All HTTP requests (REST and the WebSocket upgrade handshake) that carry a
    path not in the exempt list must include::

        Authorization: Bearer <token>

    Alternatively WebSocket clients may pass the token as a query parameter::

        /ws/device/my_device?token=<token>

    Rejected requests receive HTTP 401 with a JSON error payload.
    The middleware is transparent (no-op) when auth is disabled so that
    existing clients continue to work without modification.
    """

    async def dispatch(self, request: Request, call_next):
        from core.auth import is_auth_enabled, get_active_tokens
        import hmac

        if not is_auth_enabled():
            return await call_next(request)

        # Health probes are always public
        if request.url.path in _AUTH_EXEMPT_PATHS:
            return await call_next(request)

        active_tokens = get_active_tokens()
        if not active_tokens:
            # Auth enabled but no active tokens configured — fail safe
            logger.error(
                "GALAXY_AUTH_ENABLED=true but no active API tokens are configured; "
                "rejecting request to %s", request.url.path
            )
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "detail": "Server auth token not configured"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Accept token from Authorization header or ?token= query param (for WS)
        token: Optional[str] = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
        if not token:
            token = request.query_params.get("token", "").strip() or None

        if not token:
            logger.debug("Unauthorized request to %s (missing token)", request.url.path)
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "detail": "Invalid or missing Bearer token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Accept if token matches any active key (constant-time comparison for each)
        for expected in active_tokens:
            if hmac.compare_digest(token, expected):
                return await call_next(request)

        logger.debug("Unauthorized request to %s (invalid token)", request.url.path)
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "detail": "Invalid or missing Bearer token"},
            headers={"WWW-Authenticate": "Bearer"},
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global device_manager, message_handler, websocket_manager, task_orchestrator
    
    # 启动时初始化
    logger.info("Initializing Galaxy Gateway...")
    
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

    # ── Phase 3: 初始化 OpenClawd 统一智能入口 ──
    global openclawd_instance, llm_router_instance
    try:
        from core.openclawd import OpenClawd
        openclawd_instance = OpenClawd()
        logger.info("OpenClawd 已初始化")
    except Exception as e:
        logger.warning(f"OpenClawd 不可用，智能聊天端点将降级: {e}")

    # ── Phase 6: 获取 LLM 路由器引用（用于统计）──
    try:
        from core.multi_llm_router import get_llm_router
        llm_router_instance = get_llm_router()
        logger.info("MultiLLMRouter 引用已获取")
    except Exception as e:
        logger.warning(f"MultiLLMRouter 不可用: {e}")

    logger.info("Galaxy Gateway initialized successfully")

    # ── Log security posture at startup ──
    from core.auth import is_auth_enabled, get_active_tokens
    if is_auth_enabled():
        active = get_active_tokens()
        if active:
            logger.info(
                "🔒 Bearer token auth: ENABLED (%d active token(s)) — key rotation supported",
                len(active),
            )
        else:
            logger.warning(
                "⚠️  Bearer token auth: ENABLED but no active tokens are configured — "
                "all requests will be rejected until a token is set."
            )
    else:
        logger.info(
            "🔓 Bearer token auth: DISABLED (set GALAXY_AUTH_ENABLED=true to enable)"
        )

    _tls_cert = os.getenv("GALAXY_TLS_CERT", "").strip()
    _tls_key = os.getenv("GALAXY_TLS_KEY", "").strip()
    if _tls_cert and _tls_key:
        logger.info("🔐 TLS: ENABLED (cert=%s)", _tls_cert)
    else:
        logger.info("🔓 TLS: DISABLED (set GALAXY_TLS_CERT + GALAXY_TLS_KEY to enable)")

    yield
    
    # 关闭时清理
    logger.info("Shutting down Galaxy Gateway...")
    await task_orchestrator.stop()
    await websocket_manager.stop()
    logger.info("Galaxy Gateway shut down")


# 创建 FastAPI 应用
app = FastAPI(
    title="Galaxy Gateway",
    description="跨平台分布式 Agent 网关",
    version="3.0.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bearer token auth middleware (no-op unless GALAXY_AUTH_ENABLED=true)
app.add_middleware(BearerAuthMiddleware)


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


# ---------------------------------------------------------------------------
# Primary Android WebSocket path
# ---------------------------------------------------------------------------

@app.websocket("/ws/android/{device_id}")
async def websocket_android_primary(websocket: WebSocket, device_id: str):
    """Primary Android WebSocket path — all Android clients should connect here."""
    logger.info("Primary path /ws/android/ used for device %s", device_id)
    await websocket_manager.handle_connection(websocket, device_id)


# ---------------------------------------------------------------------------
# Legacy / backward-compatible WebSocket paths
# ---------------------------------------------------------------------------

@app.websocket("/ws/ufo3/{device_id}")
async def websocket_ufo3(websocket: WebSocket, device_id: str):
    """Legacy UFO3 WebSocket path — routed to the same connection handler."""
    logger.info("Legacy path /ws/ufo3/ used for device %s", device_id)
    await websocket_manager.handle_connection(websocket, device_id)


@app.websocket("/ws/device/{device_id}")
async def websocket_device(websocket: WebSocket, device_id: str):
    """Android device WebSocket path — compat alias for /ws/android/{device_id}."""
    logger.info("Compat path /ws/device/ used for device %s", device_id)
    await websocket_manager.handle_connection(websocket, device_id)


@app.websocket("/ws/android")
async def websocket_android(websocket: WebSocket, device_id: str = Query(None)):
    """Android broadcast WebSocket path — auto-assigns device_id when absent."""
    if not device_id:
        import uuid
        device_id = str(uuid.uuid4())
    logger.info("Compat path /ws/android used, device_id=%s", device_id)
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
# Legacy HTTP device API compatibility shim
# Maps old /api/devices/* paths → current /api/v1/devices/* behaviour
# ============================================================================

# ============================================================================
# Session Roaming REST API
# ============================================================================

class SessionMigrateRequest(BaseModel):
    target_device_id: str


@app.get("/api/v1/sessions")
async def list_sessions(state: Optional[str] = None):
    """列出所有会话（可按状态过滤）"""
    try:
        from galaxy_gateway.session_roaming import session_roaming, SessionState

        filter_state = None
        if state:
            try:
                filter_state = SessionState(state)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid state: {state}")

        sessions = session_roaming.list_sessions(state=filter_state)
        return {"sessions": sessions, "total": len(sessions)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/sessions/{session_id}")
async def get_session(session_id: str):
    """获取单个会话详情"""
    try:
        from galaxy_gateway.session_roaming import session_roaming

        session = session_roaming.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/sessions/{session_id}/migrate")
async def migrate_session(session_id: str, request: SessionMigrateRequest):
    """触发会话迁移到目标设备"""
    try:
        from galaxy_gateway.session_roaming import session_roaming

        success = await session_roaming.migrate_session(
            session_id, request.target_device_id
        )
        if not success:
            raise HTTPException(
                status_code=400,
                detail="Migration failed (session not found or already closed)"
            )
        return {
            "success": True,
            "session_id": session_id,
            "target_device_id": request.target_device_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/sessions/stats")
async def session_stats():
    """获取会话统计信息"""
    try:
        from galaxy_gateway.session_roaming import session_roaming
        return session_roaming.get_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Legacy HTTP device API compatibility shim
# Maps old /api/devices/* paths → current /api/v1/devices/* behaviour
# ============================================================================

class _LegacyRegisterRequest(BaseModel):
    device_id: str
    device_type: str = "android"
    device_name: str = ""
    capabilities: list = []
    os_version: str = ""
    app_version: str = ""


class _LegacyHeartbeatRequest(BaseModel):
    device_id: str
    status: dict = {}


class _LegacyUnregisterRequest(BaseModel):
    device_id: str


@app.post("/api/devices/register")
async def legacy_register_device(req: _LegacyRegisterRequest):
    """
    Legacy registration endpoint — maps to current device-manager logic.
    Android clients calling ``/api/devices/register`` are served here.
    """
    logger.info(
        "Legacy /api/devices/register called for device %s", req.device_id
    )
    if not device_manager:
        raise HTTPException(status_code=503, detail="Service not ready")
    device_info = DeviceInfo(
        device_id=req.device_id,
        device_type=DeviceType(req.device_type) if req.device_type in [dt.value for dt in DeviceType] else DeviceType.UNKNOWN,
        name=req.device_name or req.device_id,
        os_version=req.os_version,
        metadata={"app_version": req.app_version, "capabilities": req.capabilities},
    )
    device_manager.register_device(device_info)
    return {
        "success": True,
        "device_id": req.device_id,
        "message": "设备注册成功",
        "server_version": "3.0.0",
    }


@app.get("/api/devices/list")
async def legacy_list_devices():
    """
    Legacy device-list endpoint — maps to current ``GET /api/devices``.
    """
    logger.info("Legacy /api/devices/list called")
    if not device_manager:
        raise HTTPException(status_code=503, detail="Service not ready")
    devices = device_manager.to_dict()
    return {"devices": devices, "total": len(devices) if isinstance(devices, list) else 0}


@app.post("/api/devices/heartbeat")
async def legacy_device_heartbeat(req: _LegacyHeartbeatRequest):
    """
    Legacy heartbeat endpoint — maps to current device status-update logic.
    """
    logger.info(
        "Legacy /api/devices/heartbeat called for device %s", req.device_id
    )
    if not device_manager:
        raise HTTPException(status_code=503, detail="Service not ready")
    device_manager.update_device_status(req.device_id, "online")
    return {"success": True, "device_id": req.device_id}


@app.post("/api/devices/unregister")
async def legacy_unregister_device(req: _LegacyUnregisterRequest):
    """
    Legacy unregister endpoint — safely unregisters the device when possible.
    """
    logger.info(
        "Legacy /api/devices/unregister called for device %s", req.device_id
    )
    if device_manager:
        device_manager.update_device_status(req.device_id, "offline")
    return {"success": True, "device_id": req.device_id}


# ============================================================================
# WebRTC Signaling Gateway Proxy
# ============================================================================

@app.get("/api/v1/webrtc/endpoint")
async def webrtc_endpoint_info():
    """
    Return WebRTC signaling endpoint metadata.

    Android clients call this endpoint to discover:
    * The Node_95 URL and WS signaling path (direct access).
    * The gateway WebSocket path they can use instead of connecting to
      Node_95 directly (``/ws/webrtc/{device_id}``).

    Returns HTTP 503 when Node_95 is not reachable so that callers can
    detect degraded state early.
    """
    if not await check_node95_reachable():
        raise HTTPException(
            status_code=503,
            detail="Node_95 WebRTC Receiver is not reachable",
        )
    return get_webrtc_endpoint_info()


@app.websocket("/ws/webrtc/{device_id}")
async def webrtc_signaling_proxy(websocket: WebSocket, device_id: str):
    """
    WebSocket passthrough — proxy Android signaling to Node_95.

    Accepts a WebSocket connection from an Android client and relays all
    signaling messages (Offer / Answer / ICE Candidate) to the Node_95
    ``/signaling/{device_id}`` endpoint, forwarding responses back.

    Closes with code 1011 (server error / 503-equivalent) when Node_95 is
    unreachable so the client can fall back gracefully.
    """
    await proxy_webrtc_signaling(websocket, device_id)


# ============================================================================
# Phase 3: 智能聊天端点 — OpenClawd 统一入口
# ============================================================================

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    device_id: Optional[str] = None
    context: Optional[dict] = None


@app.post("/api/v1/chat")
async def chat_endpoint(request: ChatRequest):
    """智能对话端点 — 严格委托给 OpenClawd 统一智能入口

    所有对话请求经由 OpenClawd.process() 路由，确保 CapabilityRegistry
    和 Agent 调度逻辑的一致性。响应包含向后兼容字段 (reply, response,
    intent)，供老版本客户端使用。响应中的 parallel_result 由并行闭环
    ParallelGroupTracker 填充（当可用时）。
    """
    if not openclawd_instance:
        logger.warning("OpenClawd 未初始化，chat 端点不可用")
        raise HTTPException(status_code=503, detail="AI service not available")

    try:
        result = await openclawd_instance.process(
            message=request.message,
            session_id=request.session_id or "gateway_default",
            device_id=request.device_id,
            context=request.context or {},
        )
        # 确保向后兼容字段存在（reply 是 response 的别名，供旧版客户端使用）
        if isinstance(result, dict) and "reply" not in result:
            result = {**result, "reply": result.get("response", "")}
        # 附加 parallel_result（仅当可用且未重复时）
        result = _merge_parallel_result(result)
        return result
    except Exception as e:
        logger.error("OpenClawd 处理失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat processing error: {e}")


def _merge_parallel_result(result: dict) -> dict:
    """将 parallel_result 提升到响应顶层（如可用），不影响现有 reply 行为。

    优先级：
    1. result 已含顶层 parallel_result → 原样返回
    2. result.metadata.parallel_result 存在（来自 OpenClawd 同步并行流）→ 提升至顶层
    3. result 或 result.metadata 含 group_id → 查询网关 ParallelGroupTracker
    """
    if not isinstance(result, dict):
        return result

    if "parallel_result" in result:
        return result

    metadata = result.get("metadata") or {}

    # Case 2: OpenClawd 同步并行结果已嵌在 metadata 中
    if isinstance(metadata, dict) and "parallel_result" in metadata:
        return {**result, "parallel_result": metadata["parallel_result"]}

    # Case 3: 通过 group_id 查询网关 tracker
    group_id = None
    if isinstance(metadata, dict):
        group_id = metadata.get("parallel_group") or metadata.get("group_id")
    if not group_id:
        group_id = result.get("group_id")

    if group_id:
        try:
            from galaxy_gateway.orchestrator.parallel_tracker import get_tracker
            gs = get_tracker().get_group_status(str(group_id))
            if gs is not None:
                return {**result, "parallel_result": gs.to_dict()}
        except Exception as _err:
            logger.debug("parallel_tracker merge skipped: %s", _err)

    return result


# ============================================================================
# Phase 4.2: 挂载 AI Agent 路由（AgentTeam + Swarm + Intent + Memory）
# ============================================================================

try:
    from core.routes.ai import create_router as _create_ai_router
    _ai_router = _create_ai_router()
    app.include_router(_ai_router, tags=["ai-agents"])
    logger.info("AI Agent 路由已挂载 (/api/v1/agents/*, /api/v1/ai/*)")
except Exception as _ai_err:
    logger.warning(f"AI Agent 路由挂载跳过: {_ai_err}")


# ============================================================================
# Phase 5: 挂载 Gateway Service v5.0 路由
# ============================================================================

try:
    from .gateway_service import router as _gateway_v5_router
    app.include_router(_gateway_v5_router, tags=["gateway-v5"])
    logger.info("Gateway v5.0 路由已挂载")
except Exception as _gw5_err:
    logger.warning(f"Gateway v5.0 路由挂载跳过: {_gw5_err}")


# ============================================================================
# Phase 6: 成本/性能追踪端点
# ============================================================================

@app.get("/api/v1/llm/stats")
async def llm_stats():
    """LLM 路由器统计 — 成本、延迟、提供商状态"""
    if not llm_router_instance:
        raise HTTPException(status_code=503, detail="LLM Router not available")
    try:
        return llm_router_instance.get_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 增强 health 端点 — 原 /health 已定义，此处扩展 /api/v1/health
@app.get("/api/v1/health")
async def enhanced_health_check():
    """增强版健康检查 — 包含 LLM 和 AI 模块状态"""
    result: Dict[str, Any] = {
        "status": "healthy",
        "version": "3.0.0",
        "devices_connected": websocket_manager.get_device_count() if websocket_manager else 0,
        "ai_modules": {
            "openclawd": "available" if openclawd_instance else "unavailable",
            "llm_router": "available" if llm_router_instance else "unavailable",
        },
    }
    if llm_router_instance:
        try:
            status = llm_router_instance.get_status()
            result["llm"] = {
                "providers": status.get("providers", {}),
                "total_calls": status.get("total_calls", 0),
            }
        except Exception:
            pass
    return result


# ============================================================================
# 主入口
# ============================================================================

def main():
    """主入口函数"""
    import uvicorn

    try:
        from core.port_config import get_service_port
        _default_gw_port = str(get_service_port("gateway"))
    except Exception:
        _default_gw_port = "8765"
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", _default_gw_port))

    # TLS configuration — both cert and key must be provided to enable HTTPS
    tls_cert = os.getenv("GALAXY_TLS_CERT", "").strip()
    tls_key = os.getenv("GALAXY_TLS_KEY", "").strip()

    if tls_cert and tls_key:
        logger.info(
            "Starting Galaxy Gateway on %s:%s (TLS ENABLED, cert=%s)",
            host, port, tls_cert,
        )
        uvicorn.run(app, host=host, port=port, ssl_certfile=tls_cert, ssl_keyfile=tls_key)
    else:
        logger.info(
            "Starting Galaxy Gateway on %s:%s (TLS DISABLED — "
            "set GALAXY_TLS_CERT + GALAXY_TLS_KEY to enable HTTPS)",
            host, port,
        )
        uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
