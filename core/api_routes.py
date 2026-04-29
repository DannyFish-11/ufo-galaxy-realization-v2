"""
Galaxy - 完整 API 路由模块（规范路由聚合入口）
=================================================

**架构权威声明 (Batch PR-4)**
------------------------------
``core/api_routes.py`` 是 Galaxy 的 **唯一权威 REST API 定义**。
路由所有权由 ``CANONICAL_API_ROUTES_AUTHORITY`` 哨兵声明。

API 路由按域组织于 ``core/routes/`` 子模块，本文件仅负责聚合。
Dashboard/backend 是遗留兼容层，不是 API 权威（见 ``DASHBOARD_LEGACY_SURFACE_AUTHORITY``）。

Domain → 子模块映射：
  /api/v1/system        → core/routes/system.py       （系统状态和管理）
  /api/v1/devices       → core/routes/devices.py      （设备注册和管理）
  /api/v1/nodes         → core/routes/nodes.py        （节点查询和调用）
  /api/v1/agent         → core/routes/nodes.py        （Agent 调度）
  /api/v1/command       → core/routes/command.py      （命令路由引擎）
  /api/v1/ai            → core/routes/ai.py           （AI 意图理解）
  /api/v1/vision        → core/routes/vision.py       （视觉理解）
  /api/v1/tasks         → core/routes/tasks.py        （任务管理）
  /api/v1/chat          → core/routes/chat.py         （对话接口）
  /api/v1/health        → core/routes/health.py       （统一健康管理 ★ Batch PR-4）
  /api/v1/monitoring    → core/routes/monitoring.py   （监控仪表盘 & 告警）
  /api/v1/concurrency   → core/routes/diagnostics.py  （并发状态 ★ Batch PR-4）
  /api/v1/errors        → core/routes/diagnostics.py  （错误追踪 ★ Batch PR-4）
  /api/v1/discovery     → core/routes/diagnostics.py  （节点发现 ★ Batch PR-4）
  /api/v1/security      → core/routes/diagnostics.py  （安全审计 ★ Batch PR-4）
  /api/v1/config        → core/routes/diagnostics.py  （配置管理 ★ Batch PR-4）
  /api/v1/relay         → core/routes/relay.py        （代理转发）
  /api/v1/rag           → core/routes/hybrid.py       （RAG 检索）
  /api/v1/mesh          → core/routes/hybrid.py       （Mesh P2P）
  /api/v1/vault         → core/routes/vault.py        （凭证管理）
  /api/v1/cost          → core/routes/cost.py         （成本追踪）
  /api/v1/channels      → core/routes/channels.py     （渠道插件）
  /api/v1/federation    → core/routes/federation.py   （多实例联邦）
  /api/v1/projection    → core/routes/projection.py   （运行时状态投影）
  /api/v1/operator      → core/routes/operator.py     （算子检查面 ★ PR-510）
  /api/v1/stream        → (inline SSE endpoint below)  （服务端推送流）
  /ws/device            → (create_websocket_routes)    （设备 WebSocket — 兼容路径，非规范主入口，见下文）
  /ws/status            → (create_websocket_routes)    （状态推送 WebSocket）

NOTE — Device WebSocket ingress authority:
  The CANONICAL device ingress is galaxy_gateway/routes/websocket.py /ws/device/{device_id}.
  The /ws/device/{device_id} route in THIS file (core/api_routes.py) is a
  COMPATIBILITY-ONLY path retained for legacy/core-direct clients.  It must NOT
  be treated as a competing primary ingress.  New device clients MUST connect
  through the gateway canonical path instead.
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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from core.unified_response import UnifiedChatResponse

# 导入鉴权模块
try:
    from .auth import require_auth
except ImportError:
    logging.getLogger("Galaxy.API").warning(
        "core.auth 模块未找到，所有需要鉴权的路由将拒绝访问（HTTP 401）。"
        "请确保 core/auth.py 存在。"
    )

    async def require_auth():
        raise HTTPException(status_code=401, detail="鉴权模块不可用，拒绝访问")

logger = logging.getLogger("Galaxy.API")

# ---------------------------------------------------------------------------
# Batch PR-4: Canonical API Routes Authority
# ---------------------------------------------------------------------------
# This sentinel declares that ``core/api_routes.py`` (and its ``core/routes/``
# sub-modules) is the **single source of truth** for route ownership, API
# schemas, and status/projection truth.
#
# ``dashboard/backend/main.py`` is a LEGACY SURFACE (see
# ``DASHBOARD_LEGACY_SURFACE_AUTHORITY`` in that module).  It must not be
# treated as an architectural or status authority.
# ---------------------------------------------------------------------------
CANONICAL_API_ROUTES_AUTHORITY = "core.api_routes"

API_COMPATIBILITY_SURFACE_BOUNDARY_POLICY = (
    "API_COMPATIBILITY_SURFACE_BOUNDARY_POLICY_V1: "
    "Compatibility routes must remain explicitly classified as transitional "
    "surfaces and must not be treated as peer authorities to canonical "
    "/api/v1/* and gateway ingress paths."
)

API_COMPATIBILITY_SURFACE_BOUNDARY_PR8_SENTINEL = (
    "API_COMPATIBILITY_SURFACE_BOUNDARY_PR8_SENTINEL_V1: "
    "Compatibility route surfaces are explicitly catalogued in "
    "get_api_compatibility_surface_registry()."
)


@dataclass(frozen=True)
class APICompatibilitySurface:
    """Explicit compatibility-only route surface metadata."""

    surface_id: str
    path: str
    module: str
    canonical_replacement: str
    compatibility_scope: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "surface_id": self.surface_id,
            "path": self.path,
            "module": self.module,
            "canonical_replacement": self.canonical_replacement,
            "compatibility_scope": self.compatibility_scope,
        }


_API_COMPATIBILITY_SURFACES: tuple[APICompatibilitySurface, ...] = (
    APICompatibilitySurface(
        surface_id="legacy_android_http_device_routes",
        path="/api/devices/*",
        module="core.routes.compat",
        canonical_replacement="/api/v1/devices/* (core.routes.devices)",
        compatibility_scope="legacy_android_http_clients",
    ),
    APICompatibilitySurface(
        surface_id="core_direct_device_websocket_ingress",
        path="/ws/device/{device_id}",
        module="core.api_routes.create_websocket_routes",
        canonical_replacement="/ws/device/{device_id} (galaxy_gateway/routes/websocket.py)",
        compatibility_scope="legacy_core_direct_ws_clients",
    ),
)


def get_api_compatibility_surface_registry() -> List[Dict[str, str]]:
    """Return an explicit list of compatibility-only API surfaces."""
    return [entry.to_dict() for entry in _API_COMPATIBILITY_SURFACES]


# ---------------------------------------------------------------------------
# Re-export shared state and models for backward compatibility
# (other modules that imported from core.api_routes directly still work)
# ---------------------------------------------------------------------------
from core.routes._shared import (
    RouteConnectionPool,
    connection_manager,
    registered_devices,
    task_queue,
    node_status_cache,
    command_results,
    broadcast_event,
    _sse_queues,
    _sse_queues_lock,
)
from core.routes._models import (
    DeviceRegisterRequest,
    DeviceStatusUpdate,
    VisionRequest,
    TaskRequest,
    ChatRequest,
    NodeCallRequest,
    OCRRequest,
    CommandDispatchRequest,
    AIIntentRequest,
    ConversationRequest,
    CommandStatus,
    TargetResult,
    UnifiedCommandRequest,
    UnifiedCommandResponse,
)
from core.routes._helpers import nodes_root, _load_node, _execute_node, _node_instances


# ============================================================================
# 创建路由 (assembles all sub-routers)
# ============================================================================

def create_api_routes(service_manager=None, config=None) -> APIRouter:
    """创建完整的 API 路由（组合各子路由模块）"""

    from core.routes import system, devices, nodes, vision, tasks, command as cmd_routes
    from core.routes import chat, ai, monitoring, relay, hybrid, vault, cost, channels, federation
    from core.routes import compat, twin, sessions
    # Batch PR-4: dedicated health and diagnostics domain modules
    from core.routes import health as health_routes
    from core.routes import diagnostics as diagnostics_routes
    try:
        from core.routes import protocols
    except ImportError:
        protocols = None
    try:
        from core.routes import observability
    except ImportError:
        observability = None
    # C阶段功能路由（可选加载）
    try:
        from core.routes import c_stage
    except ImportError:
        c_stage = None
    # GitHub 插件路由（可选加载）
    try:
        from core.routes import github as github_routes
    except ImportError:
        github_routes = None
    # OpenCode 代码生成路由（可选加载）
    try:
        from core.routes import opencode as opencode_routes
    except ImportError:
        opencode_routes = None

    router = APIRouter()

    # Auth dependency for sensitive route groups.
    # require_auth internally checks is_auth_enabled(), so non-auth deployments are unaffected.
    _auth_deps = [Depends(require_auth)]

    # 按原始顺序 include 各子路由，确保行为与重构前完全一致
    # Sensitive routes: auth required
    router.include_router(system.create_router(service_manager=service_manager, config=config), dependencies=_auth_deps)
    router.include_router(nodes.create_router(service_manager=service_manager, config=config), dependencies=_auth_deps)
    router.include_router(tasks.create_router(service_manager=service_manager, config=config), dependencies=_auth_deps)
    router.include_router(cmd_routes.create_router(service_manager=service_manager, config=config), dependencies=_auth_deps)
    router.include_router(relay.create_router(service_manager=service_manager, config=config), dependencies=_auth_deps)
    router.include_router(vault.create_router(service_manager=service_manager, config=config), dependencies=_auth_deps)
    router.include_router(federation.create_router(service_manager=service_manager, config=config), dependencies=_auth_deps)

    # Exempt routes: no auth required (health, docs, observability, device registration)
    router.include_router(devices.create_router(service_manager=service_manager, config=config))
    router.include_router(vision.create_router(service_manager=service_manager, config=config))
    router.include_router(chat.create_router(service_manager=service_manager, config=config))
    router.include_router(ai.create_router(service_manager=service_manager, config=config))
    router.include_router(monitoring.create_router(service_manager=service_manager, config=config))
    # Batch PR-4: health and diagnostics domain modules (extracted from monitoring)
    router.include_router(health_routes.create_router(service_manager=service_manager, config=config))
    router.include_router(diagnostics_routes.create_router(service_manager=service_manager, config=config))
    router.include_router(hybrid.create_router(service_manager=service_manager, config=config))
    router.include_router(cost.create_router(service_manager=service_manager, config=config))
    router.include_router(channels.create_router(service_manager=service_manager, config=config))
    router.include_router(compat.create_router(service_manager=service_manager, config=config))
    router.include_router(twin.create_router(service_manager=service_manager, config=config))
    router.include_router(sessions.create_router(service_manager=service_manager, config=config))
    if protocols:
        router.include_router(protocols.create_router(service_manager=service_manager, config=config))
    if observability:
        router.include_router(observability.create_router(service_manager=service_manager, config=config))
    if c_stage:
        router.include_router(c_stage.create_router(service_manager=service_manager, config=config))
    if github_routes:
        router.include_router(github_routes.create_router(service_manager=service_manager, config=config))
    if opencode_routes:
        router.include_router(opencode_routes.create_router(service_manager=service_manager, config=config))

    # Control Plane Phase 2: audit ledger and HITL approval routes
    try:
        from core.routes import audit as audit_routes
        router.include_router(audit_routes.create_router())
    except Exception as _e:
        logger.warning("审计路由加载失败（可选）: %s", _e)
    try:
        from core.routes import approvals as approvals_routes
        router.include_router(approvals_routes.create_router())
    except Exception as _e:
        logger.warning("审批路由加载失败（可选）: %s", _e)
    # Control Plane Phase 4: security policy routes
    try:
        from core.routes import security_policy as security_policy_routes
        router.include_router(security_policy_routes.create_router())
    except Exception as _e:
        logger.warning("安全策略路由加载失败（可选）: %s", _e)
    # Control Plane Phase 5: device health & circuit-breaker routes
    try:
        from core.routes.device_health import router as device_health_router
        router.include_router(device_health_router)
    except Exception as _e:
        logger.warning("设备健康路由加载失败（可选）: %s", _e)
    # PR-4 Status Board V2: read-only RuntimeProjection endpoint
    try:
        from core.routes import projection as projection_routes
        router.include_router(projection_routes.create_router())
    except Exception as _e:
        logger.warning("投影路由加载失败（可选）: %s", _e)
    # Read-only device readiness & participation inspection endpoints
    try:
        from core.routes import device_readiness as device_readiness_routes
        router.include_router(device_readiness_routes.create_router())
    except Exception as _e:
        logger.warning("设备就绪路由加载失败（可选）: %s", _e)

    # PR-16: Cross-Plane Contract Map — read-only contract introspection endpoints
    # PR-19: Reliability Contract — GET /api/v1/contracts/reliability is also
    #        served by this router (delivery semantics for existing runtime paths).
    try:
        from core.routes import contracts as contracts_routes
        router.include_router(contracts_routes.create_router())
    except Exception as _e:
        logger.warning("合约路由加载失败（可选）: %s", _e)

    # PR-20: Capability Runtime State — read-only capability runtime summaries.
    #        GET /api/v1/capabilities/runtime
    #        GET /api/v1/capabilities/runtime/{capability_name}
    try:
        from core.routes import capabilities_runtime as cap_runtime_routes
        router.include_router(cap_runtime_routes.create_router())
    except Exception as _e:
        logger.warning("能力运行时路由加载失败（可选）: %s", _e)

    # PR-510: Operator Surface API — read-only operator inspection endpoints.
    #         GET /api/v1/operator/snapshot
    #         GET /api/v1/operator/inspect/task/{task_id}
    #         GET /api/v1/operator/inspect/route/{task_id}
    #         GET /api/v1/operator/inspect/executor/{node_id}
    #         GET /api/v1/operator/inspect/failure/{task_id}
    #         GET /api/v1/operator/inspect/lineage/{task_id}
    try:
        from core.routes import operator as operator_routes
        router.include_router(operator_routes.create_router())
    except Exception as _e:
        logger.warning("算子路由加载失败（可选）: %s", _e)

    # PR-512: Runtime Closure Audit — closure gap sweep integration sentinel.
    #         The audit module is loaded lazily here so that its import errors
    #         never block API startup.  The sentinel asserts the audit layer is
    #         present and machine-checkable.
    try:
        from core.runtime_closure_audit import (  # noqa: F401
            RUNTIME_CLOSURE_AUDIT_AUTHORITY as _RCA_AUTHORITY,
        )
        RUNTIME_CLOSURE_AUDIT_INTEGRATED: str = (
            "API_ROUTES::RUNTIME_CLOSURE_AUDIT_INTEGRATED_V1"
        )
    except ImportError:
        RUNTIME_CLOSURE_AUDIT_INTEGRATED: str = (  # type: ignore[no-redef]
            "API_ROUTES::RUNTIME_CLOSURE_AUDIT_INTEGRATED_UNAVAILABLE"
        )

    # -----------------------------------------------------------------------
    # PR4: Server-Sent Events (SSE) streaming endpoint — /api/v1/stream
    # -----------------------------------------------------------------------
    # Clients that cannot use WebSocket (e.g. HTTP-only proxies, simple JS
    # EventSource) can subscribe here.  The server pushes the same payloads
    # that broadcast_event() emits to WebSocket /ws/status subscribers.
    #
    # Graceful degradation: if the event loop is unavailable or the client
    # disconnects, the generator exits cleanly without raising.
    # -----------------------------------------------------------------------

    # Keep-alive interval (seconds) — also used by StatusPoller in windows_client.
    # Both must stay in sync; see windows_client/main.py StatusPoller.run().
    _SSE_KEEPALIVE_SECS = 30.0

    @router.get("/api/v1/stream")
    async def sse_stream(request: Request):
        """SSE 实时事件流 — 推送 capability_update / device_update / agent_update / mcp_update / skill_update。

        客户端用法 (JavaScript EventSource)::

            const es = new EventSource('/api/v1/stream');
            es.onmessage = (e) => {
              const event = JSON.parse(e.data);
              console.log(event.type, event.data);
            };

        每 30 秒发送一次 keep-alive 注释，防止连接超时。
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=128)

        async def _register():
            async with _sse_queues_lock:
                _sse_queues.add(queue)

        async def _unregister():
            async with _sse_queues_lock:
                _sse_queues.discard(queue)

        async def event_generator():
            await _register()
            try:
                # Send a welcome event immediately so the client knows it's connected
                welcome = json.dumps({"type": "connected", "message": "Galaxy SSE stream connected", "timestamp": datetime.now().isoformat()})
                yield f"data: {welcome}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=_SSE_KEEPALIVE_SECS)
                        yield f"data: {json.dumps(payload)}\n\n"
                    except asyncio.TimeoutError:
                        # Send keep-alive comment
                        yield ": heartbeat\n\n"
                    except asyncio.CancelledError:
                        break
            finally:
                await _unregister()

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )


    # -----------------------------------------------------------------------
    # NOTE (Batch PR-4): All /api/v1/* inline route handlers below this point
    # were dead code — they were already covered by the sub-module routers
    # included above.  They have been removed to declutter the aggregation
    # file.  Canonical route implementations live in core/routes/ sub-modules.
    # -----------------------------------------------------------------------

    return router


# ============================================================================
# LLM 降级调用 (kept here for WebSocket handler)
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
                    "parts": [{"text": "你是 Galaxy 智能助手，一个 L4 级自主性 AI 系统。"}]
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

    messages = [{"role": "system", "content": "你是 Galaxy 智能助手，一个 L4 级自主性 AI 系统。"}]
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
    """创建 WebSocket 端点 — 兼容层 (非规范设备主入口)

    COMPATIBILITY SURFACE — NOT the canonical device ingress.

    The canonical device ingress is galaxy_gateway/routes/websocket.py
    /ws/device/{device_id}.  The routes registered here are retained for
    legacy/core-direct clients only and must not be introduced as a second
    primary device ingress authority.
    """

    from core.openclawd import get_openclawd as _get_openclawd
    compat_ws_enabled = os.getenv("GALAXY_ENABLE_CORE_COMPAT_WS", "").lower() in (
        "1",
        "true",
        "yes",
    )

    # -----------------------------------------------------------------------
    # [COMPAT] /ws/device/{device_id}
    #
    # Compatibility-only device WebSocket path.  This endpoint is NOT the
    # canonical device ingress.  The canonical path is:
    #   galaxy_gateway/routes/websocket.py → /ws/device/{device_id}
    #
    # This route is retained for clients that connect directly to the core
    # layer without going through the gateway.  It must not be extended with
    # new primary-ingress semantics.
    # -----------------------------------------------------------------------
    @app.websocket("/ws/device/{device_id}")
    async def device_websocket(websocket: WebSocket, device_id: str):
        """[COMPAT] 设备 WebSocket 连接 — 兼容路径（非规范主入口）

        Compatibility-only path.  The canonical device ingress is
        galaxy_gateway/routes/websocket.py /ws/device/{device_id}.
        """
        if not compat_ws_enabled:
            await websocket.accept()
            await websocket.send_json(
                {
                    "type": "compat_ws_disabled",
                    "message": "Core compatibility WS ingress is disabled by default.",
                    "recommended_canonical_path": f"/ws/device/{device_id}",
                    "how_to_enable": "Set GALAXY_ENABLE_CORE_COMPAT_WS=true explicitly for fallback use.",
                }
            )
            await websocket.close(code=1008, reason="Core compat WS disabled")
            return

        await connection_manager.connect_device(websocket, device_id)

        # ── SSOT: propagate connection-online state to UDM first ──────────
        # PR-E: device presence/state is governed by UDM (SSOT).
        # The compat cache (registered_devices) is updated only as a
        # read-only mirror AFTER the UDM write, and only if the entry
        # already exists there.
        try:
            from core.unified.device_manager import get_unified_device_manager as _get_udm
            _get_udm().patch_device(device_id, {"status": "online"})
        except Exception as _udm_err:
            logger.debug("compat_ws: UDM online patch failed for %s — %s", device_id, _udm_err)
        # COMPAT_MIRROR_WRITE: update compat cache AFTER UDM write (non-authoritative)
        if device_id in registered_devices:
            registered_devices[device_id]["last_seen"] = datetime.now().isoformat()  # COMPAT_MIRROR_WRITE
            registered_devices[device_id]["status"] = "online"  # COMPAT_MIRROR_WRITE

        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type", "")

                if msg_type == "heartbeat":
                    # SSOT: write heartbeat to UDM first
                    try:
                        from core.unified.device_manager import get_unified_device_manager as _get_udm
                        _get_udm().heartbeat(device_id)
                    except Exception as _udm_hb_err:
                        logger.debug("compat_ws: UDM heartbeat failed for %s — %s", device_id, _udm_hb_err)
                    # COMPAT_MIRROR_WRITE: update compat cache AFTER UDM heartbeat
                    if device_id in registered_devices:
                        registered_devices[device_id]["last_seen"] = datetime.now().isoformat()  # COMPAT_MIRROR_WRITE
                    await websocket.send_json({
                        "type": "heartbeat_ack",
                        "timestamp": datetime.now().isoformat()
                    })

                elif msg_type == "status_update":
                    # COMPAT_MIRROR_WRITE: registered_devices is not truth source; update after UDM
                    if device_id in registered_devices:
                        registered_devices[device_id]["status_detail"] = data.get("status", {})  # COMPAT_MIRROR_WRITE
                        registered_devices[device_id]["last_seen"] = datetime.now().isoformat()  # COMPAT_MIRROR_WRITE
                    await connection_manager.broadcast_status({
                        "type": "device_status_update",
                        "device_id": device_id,
                        "status": data.get("status", {}),
                        "timestamp": datetime.now().isoformat()
                    })

                elif msg_type == "command_result":
                    cmd_id = data.get("command_id")
                    if cmd_id:
                        connection_manager.resolve_command_response(cmd_id, data.get("payload", data))
                    await connection_manager.broadcast_status({
                        "type": "command_result",
                        "device_id": device_id,
                        "data": data,
                        "timestamp": datetime.now().isoformat()
                    })

                elif msg_type == "task_result":
                    task_id = data.get("task_id", "")
                    if task_id:
                        # ── Compat-path idempotency guard ──────────────────
                        # Android OfflineTaskQueue can replay task_result messages
                        # on reconnect.  Suppress duplicate results so that an
                        # already-closed task is not re-processed.
                        _compat_already_seen = False
                        try:
                            from core.durable_result_idempotency import (
                                check_result_idempotency as _check_idem,
                                record_result_idempotency as _record_idem,
                            )
                            if _check_idem(task_id):
                                _compat_already_seen = True
                                logger.debug(
                                    "compat_ws: duplicate task_result suppressed "
                                    "(durable store): task_id=%s device_id=%s",
                                    task_id,
                                    device_id,
                                )
                            else:
                                _record_idem(task_id)
                        except Exception as _idem_err:
                            logger.debug(
                                "compat_ws: idempotency check skipped (non-fatal): %s",
                                _idem_err,
                            )

                        if not _compat_already_seen:
                            # ── Status truth mapping ───────────────────────
                            # Android sends the real status field (success/failed/
                            # error/cancelled).  Map it to an honest completion
                            # status instead of unconditionally claiming "completed".
                            _raw_status = str(data.get("status", "")).lower().strip()
                            if _raw_status in ("failed", "error"):
                                _mapped_status = "failed"
                            elif _raw_status == "cancelled":
                                _mapped_status = "cancelled"
                            elif _raw_status == "degraded":
                                _mapped_status = "degraded"
                            else:
                                _mapped_status = "completed"

                            if task_id in task_queue:
                                task_queue[task_id]["status"] = _mapped_status
                                task_queue[task_id]["result"] = data.get("result", {})
                                task_queue[task_id]["completed_at"] = datetime.now().isoformat()

                            # ── Truth chain (best-effort) ──────────────────
                            # Run the canonical four-step truth chain so that the
                            # execution tracker, lifecycle, and completion ingress
                            # are updated even on the compat path.
                            try:
                                from core.task_result_canonical_truth_chain import (
                                    run_task_result_truth_chain as _run_ttc,
                                )
                                _ttc_outcome = _run_ttc(
                                    data,
                                    task_id=task_id,
                                    result_status=_mapped_status,
                                )
                                if not _ttc_outcome.is_truth_chain_complete:
                                    logger.debug(
                                        "compat_ws: task_result truth chain incomplete "
                                        "task_id=%s: %s",
                                        task_id,
                                        _ttc_outcome.incomplete_reason,
                                    )
                            except Exception as _ttc_err:
                                logger.debug(
                                    "compat_ws: truth chain skipped (non-fatal): %s",
                                    _ttc_err,
                                )

                elif msg_type == "goal_result":
                    # ── goal_result compat-path handler ───────────────────────
                    # Android's OfflineTaskQueue queues goal_result messages
                    # (alongside task_result) and drains them on reconnect with
                    # real status values (success/failed/error/cancelled).
                    # Before this fix there was no handler at all — every
                    # goal_result fell through to the "unknown message type"
                    # branch, meaning goal execution outcomes were silently
                    # discarded on the compat path.
                    #
                    # This handler applies the same three-layer fix that PR #886
                    # applied to task_result:
                    #   1. Idempotency guard  — suppress offline-replay duplicates
                    #   2. Status truth mapping — map Android taxonomy to canonical
                    #   3. Truth chain call    — drive truth_ingress, reconcile,
                    #                           lifecycle update, completion linkage
                    _goal_task_id = data.get("task_id", "") or data.get("goal_id", "")
                    if _goal_task_id:
                        # ── Compat-path idempotency guard ──────────────────
                        _goal_already_seen = False
                        _goal_idem_key = f"goal_result:{_goal_task_id}"
                        try:
                            from core.durable_result_idempotency import (
                                check_result_idempotency as _check_goal_idem,
                                record_result_idempotency as _record_goal_idem,
                            )
                            if _check_goal_idem(_goal_idem_key):
                                _goal_already_seen = True
                                logger.debug(
                                    "compat_ws: duplicate goal_result suppressed "
                                    "(durable store): task_id=%s device_id=%s",
                                    _goal_task_id,
                                    device_id,
                                )
                            else:
                                _record_goal_idem(_goal_idem_key)
                        except Exception as _goal_idem_err:
                            logger.debug(
                                "compat_ws: goal_result idempotency check skipped "
                                "(non-fatal): %s",
                                _goal_idem_err,
                            )

                        if not _goal_already_seen:
                            # ── Status truth mapping ───────────────────────
                            # Android sends real status (success/failed/error/
                            # cancelled/degraded).  Map to canonical V2 status
                            # rather than silently discarding or assuming success.
                            _goal_raw_status = str(data.get("status", "")).lower().strip()
                            if _goal_raw_status in ("failed", "error"):
                                _goal_mapped_status = "failed"
                            elif _goal_raw_status == "cancelled":
                                _goal_mapped_status = "cancelled"
                            elif _goal_raw_status == "degraded":
                                _goal_mapped_status = "degraded"
                            else:
                                _goal_mapped_status = "completed"

                            logger.info(
                                "compat_ws: goal_result task_id=%s status=%s→%s",
                                _goal_task_id, _goal_raw_status, _goal_mapped_status,
                            )

                            if _goal_task_id in task_queue:
                                task_queue[_goal_task_id]["status"] = _goal_mapped_status
                                task_queue[_goal_task_id]["result"] = data.get("result", {})
                                task_queue[_goal_task_id]["completed_at"] = datetime.now().isoformat()

                            # ── Truth chain (best-effort) ──────────────────
                            # Reuse the task_result canonical truth chain for
                            # goal_result — the four steps (truth_ingress,
                            # reconcile, authority_update, completion_linkage)
                            # apply equally to goal execution outcomes.
                            try:
                                from core.task_result_canonical_truth_chain import (
                                    run_task_result_truth_chain as _run_goal_ttc,
                                )
                                _goal_ttc_outcome = _run_goal_ttc(
                                    data,
                                    task_id=_goal_task_id,
                                    result_status=_goal_mapped_status,
                                )
                                if not _goal_ttc_outcome.is_truth_chain_complete:
                                    logger.debug(
                                        "compat_ws: goal_result truth chain incomplete "
                                        "task_id=%s: %s",
                                        _goal_task_id,
                                        _goal_ttc_outcome.incomplete_reason,
                                    )
                            except Exception as _goal_ttc_err:
                                logger.debug(
                                    "compat_ws: goal_result truth chain skipped "
                                    "(non-fatal): %s",
                                    _goal_ttc_err,
                                )

                elif msg_type == "goal_execution_result":
                    # ── goal_execution_result compat-path handler ──────────────
                    # Android sends goal_execution_result (the canonical result type
                    # for goal_execution tasks) on both live connections AND via
                    # OfflineTaskQueue replay on reconnect.
                    #
                    # Before this fix there was NO handler for goal_execution_result
                    # on the compat path — every goal_execution_result fell through
                    # to the "unknown message type" branch, meaning goal execution
                    # outcomes were silently discarded.
                    #
                    # Idempotency, status mapping, truth chain, and completion
                    # linkage are all delegated to the unified result ingress so
                    # there is a single chain for all source channels.
                    _ger_task_id = (
                        data.get("task_id", "")
                        or (data.get("payload") or {}).get("task_id", "")
                        or data.get("goal_id", "")
                    )
                    if _ger_task_id:
                        # ── Status truth mapping ──────────────────────────────
                        _payload_sub = data.get("payload") or {}
                        _ger_raw_status = str(
                            _payload_sub.get("status") or data.get("status", "")
                        ).lower().strip()
                        if _ger_raw_status in ("failed", "error"):
                            _ger_mapped_status = "failed"
                        elif _ger_raw_status == "cancelled":
                            _ger_mapped_status = "cancelled"
                        elif _ger_raw_status == "degraded":
                            _ger_mapped_status = "degraded"
                        else:
                            _ger_mapped_status = "completed"

                        # ── Unified result ingress (idempotency + truth chain +
                        #    completion linkage) ─────────────────────────────────
                        # Idempotency is entirely delegated to ingest_result so
                        # there is no double-check and no premature key recording.
                        _ger_ingress_ok = False
                        _ger_was_dedup = False
                        try:
                            from core.unified_result_ingress import (
                                NormalizedResultEvent,
                                ResultSourceChannel,
                                ingest_result,
                            )
                            _ger_event = NormalizedResultEvent(
                                task_id=_ger_task_id,
                                device_id=device_id,
                                raw_message_type="goal_execution_result",
                                normalized_result_kind="goal_execution_result",
                                normalized_status=_ger_mapped_status,
                                source_channel=ResultSourceChannel.COMPAT_WS,
                                payload=data,
                                trace_id=data.get("trace_id", ""),
                                raw_message=data,
                            )
                            _ger_outcome = ingest_result(_ger_event)
                            _ger_was_dedup = _ger_outcome.was_deduplicated
                            _ger_ingress_ok = True
                            if _ger_was_dedup:
                                logger.debug(
                                    "compat_ws: duplicate goal_execution_result suppressed "
                                    "task_id=%s device_id=%s",
                                    _ger_task_id,
                                    device_id,
                                )
                            elif not _ger_outcome.truth_chain_complete:
                                logger.debug(
                                    "compat_ws: goal_execution_result truth chain incomplete "
                                    "task_id=%s: %s",
                                    _ger_task_id,
                                    _ger_outcome.incomplete_reason,
                                )
                        except Exception as _ger_ingress_err:
                            logger.debug(
                                "compat_ws: goal_execution_result unified ingress skipped "
                                "(non-fatal): %s",
                                _ger_ingress_err,
                            )

                        # Update task_queue only for first-seen results.
                        if not _ger_was_dedup:
                            logger.info(
                                "compat_ws: goal_execution_result task_id=%s status=%s→%s",
                                _ger_task_id, _ger_raw_status, _ger_mapped_status,
                            )
                            if _ger_task_id in task_queue:
                                task_queue[_ger_task_id]["status"] = _ger_mapped_status
                                task_queue[_ger_task_id]["result"] = (
                                    _payload_sub.get("result") or data.get("result", {})
                                )
                                task_queue[_ger_task_id]["completed_at"] = (
                                    datetime.now().isoformat()
                                )

                elif msg_type == "ocr_request":
                    image_b64 = data.get("image", "")
                    mode = data.get("mode", "full")
                    instruction = data.get("instruction", "")

                    try:
                        image_data = base64.b64decode(image_b64)
                        from core.vision_pipeline import VisionPipeline
                        pipeline = VisionPipeline()
                        result = await asyncio.get_running_loop().run_in_executor(
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
                    try:
                        clawd = _get_openclawd()
                        result = await clawd.process(
                            message=data.get("message", ""),
                            device_id=device_id,
                            session_id=data.get("session_id", device_id),
                            context=data.get("context", []),
                        )
                        await websocket.send_json({
                            "type": "chat_reply",
                            "request_id": data.get("request_id", ""),
                            "reply": result.get("response", result.get("reply", "")),
                            "mode": result.get("intent", "chat"),
                            "success": result.get("success", True),
                        })
                    except Exception as e:
                        await websocket.send_json({
                            "type": "chat_reply",
                            "request_id": data.get("request_id", ""),
                            "reply": f"处理消息时出错: {str(e)}"
                        })

                elif msg_type == "command_dispatch":
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
                    try:
                        from core.proxy_relay import get_proxy_relay
                        relay = get_proxy_relay()
                        relay.set_sender(connection_manager.send_to_device)
                        relay.set_online_getter(lambda: list(connection_manager.active_devices.keys()))
                        result = await relay.handle_relay_request_from_device(device_id, data)
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
                    try:
                        from core.mesh_coordinator import get_mesh_coordinator
                        mesh = get_mesh_coordinator()
                        peer = mesh.handle_peer_announce(device_id, data)
                        peer_list = mesh.build_peer_exchange(exclude_device=device_id)
                        await websocket.send_json({
                            "type": "peer_exchange",
                            "peers": peer_list,
                            "your_peer": peer.to_dict(),
                        })
                    except Exception as e:
                        logger.error(f"Peer announce handling failed: {e}")

                elif msg_type == "peer_exchange_request":
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
                    manifest_id = data.get("manifest_id", "")
                    logger.info(f"Agent {manifest_id} 已被设备 {device_id} 接收")
                    await connection_manager.broadcast_status({
                        "type": "agent_deploy_ack",
                        "device_id": device_id,
                        "manifest_id": manifest_id,
                        "timestamp": datetime.now().isoformat(),
                    })

                elif msg_type == "agent_status":
                    await connection_manager.broadcast_status({
                        "type": "agent_status",
                        "device_id": device_id,
                        "manifest_id": data.get("manifest_id", ""),
                        "step": data.get("step", {}),
                        "timestamp": datetime.now().isoformat(),
                    })

                elif msg_type == "agent_result":
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
                    logger.warning(f"未知消息类型: {msg_type} from {device_id}")
                    await websocket.send_json({
                        "type": "error",
                        "message": f"未知消息类型: {msg_type}"
                    })

        except WebSocketDisconnect:
            connection_manager.disconnect_device(device_id)
            # SSOT: propagate offline state to UDM first
            try:
                from core.unified.device_manager import get_unified_device_manager as _get_udm
                _get_udm().patch_device(device_id, {"status": "offline"})
            except Exception as _udm_off_err:
                logger.debug("compat_ws: UDM offline patch failed for %s — %s", device_id, _udm_off_err)
            # COMPAT_MIRROR_WRITE: update compat cache AFTER UDM write (non-authoritative)
            if device_id in registered_devices:
                registered_devices[device_id]["status"] = "offline"  # COMPAT_MIRROR_WRITE
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
        """
        await connection_manager.subscribe_status(websocket)
        try:
            await websocket.send_json({
                "type": "initial_status",
                "devices_online": len(connection_manager.active_devices),
                "devices_registered": len(registered_devices),
                "timestamp": datetime.now().isoformat()
            })

            while True:
                raw = await websocket.receive_text()
                if raw == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.now().isoformat()
                    })
                else:
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
