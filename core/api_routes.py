"""
UFO Galaxy - 完整 API 路由模块
================================

提供 Android 端和 Web UI 需要的所有 REST API 和 WebSocket 端点。

路由分组（由 core/routes/ 各子模块实现）：
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
from core.unified_response import UnifiedChatResponse

# 导入鉴权模块
try:
    from .auth import require_auth
except ImportError:
    async def require_auth():
        return {"authenticated": True, "dev_mode": True}

logger = logging.getLogger("UFO-Galaxy.API")

# ---------------------------------------------------------------------------
# Re-export shared state and models for backward compatibility
# (other modules that imported from core.api_routes directly still work)
# ---------------------------------------------------------------------------
from core.routes._shared import (
    ConnectionManager,
    connection_manager,
    registered_devices,
    task_queue,
    node_status_cache,
    command_results,
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
from core.routes.chat import _is_action_intent


# ============================================================================
# 创建路由 (assembles all sub-routers)
# ============================================================================

def create_api_routes(service_manager=None, config=None) -> APIRouter:
    """创建完整的 API 路由（组合各子路由模块）"""

    from core.routes import system, devices, nodes, vision, tasks, command as cmd_routes
    from core.routes import chat, ai, monitoring, relay, hybrid, vault, cost, channels, federation

    router = APIRouter()

    # 按原始顺序 include 各子路由，确保行为与重构前完全一致
    router.include_router(system.create_router(service_manager=service_manager, config=config))
    router.include_router(devices.create_router(service_manager=service_manager, config=config))
    router.include_router(nodes.create_router(service_manager=service_manager, config=config))
    router.include_router(vision.create_router(service_manager=service_manager, config=config))
    router.include_router(tasks.create_router(service_manager=service_manager, config=config))
    router.include_router(cmd_routes.create_router(service_manager=service_manager, config=config))
    router.include_router(chat.create_router(service_manager=service_manager, config=config))
    router.include_router(ai.create_router(service_manager=service_manager, config=config))
    router.include_router(monitoring.create_router(service_manager=service_manager, config=config))
    router.include_router(relay.create_router(service_manager=service_manager, config=config))
    router.include_router(hybrid.create_router(service_manager=service_manager, config=config))
    router.include_router(vault.create_router(service_manager=service_manager, config=config))
    router.include_router(cost.create_router(service_manager=service_manager, config=config))
    router.include_router(channels.create_router(service_manager=service_manager, config=config))
    router.include_router(federation.create_router(service_manager=service_manager, config=config))

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

    from core.routes.chat import _handle_agent_action, _handle_pure_chat
    from core.scheduler import AutonomousScheduler
    from core.llm_manager import LLMManager

    _scheduler = AutonomousScheduler(nodes_root)
    _llm_manager = LLMManager(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"))

    @app.websocket("/ws/device/{device_id}")
    async def device_websocket(websocket: WebSocket, device_id: str):
        """设备 WebSocket 连接 - 双向通信"""
        await connection_manager.connect_device(websocket, device_id)

        if device_id in registered_devices:
            registered_devices[device_id]["last_seen"] = datetime.now().isoformat()
            registered_devices[device_id]["status"] = "online"

        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type", "")

                if msg_type == "heartbeat":
                    if device_id in registered_devices:
                        registered_devices[device_id]["last_seen"] = datetime.now().isoformat()
                    await websocket.send_json({
                        "type": "heartbeat_ack",
                        "timestamp": datetime.now().isoformat()
                    })

                elif msg_type == "status_update":
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
                    if task_id in task_queue:
                        task_queue[task_id]["status"] = "completed"
                        task_queue[task_id]["result"] = data.get("result", {})
                        task_queue[task_id]["completed_at"] = datetime.now().isoformat()

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
                        chat_req = ChatRequest(
                            message=data.get("message", ""),
                            device_id=device_id,
                            context=data.get("context", [])
                        )

                        if _is_action_intent(chat_req.message) and _llm_manager.is_available():
                            result = await _handle_agent_action(chat_req, device_id, _scheduler, _llm_manager)
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
                            result = await _handle_pure_chat(chat_req, device_id, _llm_manager)
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
