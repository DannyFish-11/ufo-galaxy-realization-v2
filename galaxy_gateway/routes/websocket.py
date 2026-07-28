"""
galaxy_gateway/routes/websocket.py — 设备 WebSocket 入口(规范属主)

CANONICAL DEVICE INGRESS AUTHORITY
==================================
本模块是设备 WebSocket 入口的唯一规范属主。入口面登记(与
DEVICE_WS_INGRESS_SURFACE_REGISTRY 保持一致):

    /ws/device/{device_id}   [CANONICAL]        规范设备入口(唯一)
    /ws/android/{device_id}  [COMPAT]           旧安卓路径参数入口 → 委派规范处理器
    /ws/android              [COMPAT]           旧安卓查询参数入口 → 委派规范处理器
    /ws/ufo3/{device_id}     [COMPAT]           原 [LEGACY-DISABLED];PR-25 起改为
                                                委派规范处理器的兼容入口
    /ws/{device_id}          [DEPRECATED]       已移除——新客户端一律使用 /ws/device/
    /ws                      [DEBUG]            已移除——调试入口不再对外暴露

所有入口面(规范与兼容)统一汇聚到 _handle_android_ws 单处理器,消息处理
与入口记账不会随路由分叉。本模块只主张设备【入口】权威,不主张编排
(orchestration)或就绪(readiness)权威。

PR-GATEWAY-FIX: 同时提供 core/api_routes.py 所需的兼容导出,
实际连接管理委托给 galaxy_gateway.websocket_handler。
"""

import logging

logger = logging.getLogger(__name__)

try:
    from galaxy_gateway.websocket_handler import (
        GatewayWSManager,
        parse_message_strict,
        handle_device_message,
        register_device_ws,
        unregister_device_ws,
    )
except ImportError:
    # Fallback stubs if websocket_handler is not available
    GatewayWSManager = None
    parse_message_strict = None
    handle_device_message = None
    register_device_ws = None
    unregister_device_ws = None

# ── Constants required by core/api_routes.py ──

CANONICAL_DEVICE_INGRESS_AUTHORITY = (
    "galaxy_gateway/routes/websocket.py is the canonical WebSocket device ingress. "
    "All Android Agent and cross-device WebSocket connections MUST enter through "
    "/ws/device/{device_id} handled by this module."
)

DEVICE_WS_INGRESS_SURFACE_REGISTRY = [
    {
        "path": "/ws/device/{device_id}",
        "method": "WS",
        "auth": "AIP_TOKEN",  # device_cert 未实现(诚实化):登记表不再声称一个不存在的凭证层
        "description": "Canonical WebSocket ingress for Android Agent and IoT devices",
        "handler": "_handle_android_ws",
        "classification": "canonical",
    },
    {
        "path": "/ws/android/{device_id}",
        "method": "WS",
        "auth": "AIP_TOKEN",
        "description": "Legacy Android ingress (path param) — delegates to canonical handler",
        "handler": "_handle_android_ws",
        "classification": "compat",
    },
    {
        "path": "/ws/android",
        "method": "WS",
        "auth": "AIP_TOKEN",
        "description": "Legacy Android ingress (query param) — delegates to canonical handler",
        "handler": "_handle_android_ws",
        "classification": "compat",
    },
    {
        "path": "/ws/ufo3/{device_id}",
        "method": "WS",
        "auth": "AIP_TOKEN",
        "description": "Legacy UFO3 ingress — delegates to canonical handler",
        "handler": "_handle_android_ws",
        "classification": "compat",
    },
    # 生产修复(登记表完整性缺口):/ws/webrtc/{device_id} 是本模块实际挂载的
    # 活跃 WS 入口(见下方 webrtc_signaling_ws → proxy_webrtc_signaling),
    # 却从未登记在本表——表声称枚举全部 WS ingress 面,漏项使联合认知审查
    # (core/dual_repo_joint_cognitive_review_2026 的 ws_webrtc_media_only
    # 探针)无法证明"该口仅承载媒体信令、不承载任务/业务 ingress"这一
    # 事实。按事实补登,classification=media(媒体面,非 canonical/compat
    # 业务面)。
    {
        "path": "/ws/webrtc/{device_id}",
        "method": "WS",
        "auth": "AIP_TOKEN",
        "description": (
            "WebRTC signaling proxy — media-only surface (no task/business "
            "ingress); delegates to proxy_webrtc_signaling"
        ),
        "handler": "proxy_webrtc_signaling",
        "classification": "media",
    },
]
# /ws/master 已拆除(幻影门):其 handler GatewayWSManager.handle_master_
# connection 全仓不存在,注册函数 create_device_websocket_routes 也无人
# 调用 —— 挂上即 AttributeError。其历史动机(多中心联邦/算力聚合)已由
# 声明式提供商注册表 + NATS worker 网格覆盖;规划归档见
# docs/FUTURE_EXPANSION_OPTIONS.md。联邦通道若将来真造,走 HTTP
# core.galaxy_federation,不复活这扇 WS 空门。


# ── Canonical Android/device WebSocket handler ──

async def _handle_android_ws(
    websocket,
    device_id: str,
    *,
    ingress_path: str = "/ws/device/{device_id}",
    ingress_classification: str = "canonical",
):
    """Canonical device WebSocket session loop.

    Accepts the connection, then pumps inbound JSON messages through
    :class:`~galaxy_gateway.android_bridge.AndroidBridge` and writes the
    bridge's responses back to the socket. All ingress surfaces (canonical
    and compat) converge on this single handler so message handling and
    ingress accounting cannot diverge per route.
    """
    from fastapi import WebSocketDisconnect
    from galaxy_gateway.android_bridge import android_bridge

    await websocket.accept()
    logger.info(
        "device ws connected: device_id=%s ingress=%s (%s)",
        device_id, ingress_path, ingress_classification,
    )
    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                continue
            # NOTE: do NOT inject the path device_id into the payload — the
            # bridge enforces MISSING_REQUIRED_FIELDS on the payload itself.
            message.setdefault("_ingress_path", ingress_path)
            message.setdefault("_ingress_classification", ingress_classification)
            response = await android_bridge.handle_message(websocket, message)
            if response is not None:
                await websocket.send_json(response)
    except WebSocketDisconnect:
        logger.info("device ws disconnected: device_id=%s", device_id)
    except Exception as exc:
        logger.warning("device ws error for %s: %s", device_id, exc)
    finally:
        if device_id:
            try:
                await android_bridge.disconnect_device(device_id)
            except Exception as exc:
                logger.debug("device ws disconnect cleanup failed: %s", exc)


def register_websocket_routes(app) -> None:
    """Register the canonical and compat device WebSocket ingress routes.

    PR-25: exactly one canonical ingress (``/ws/device/{device_id}``); the
    legacy ``/ws/android`` surfaces remain available but are classified as
    compat and delegate to the same handler.
    """
    from fastapi import WebSocket

    @app.websocket("/ws/device/{device_id}")
    async def websocket_device(websocket: WebSocket, device_id: str):
        """[CANONICAL] 规范设备 WebSocket 入口——所有新客户端必须走这里。"""
        # Resolved via module namespace so tests can monkeypatch the handler.
        await _resolve_android_ws_handler()(
            websocket,
            device_id,
            ingress_path="/ws/device/{device_id}",
            ingress_classification="canonical",
        )

    @app.websocket("/ws/android/{device_id}")
    async def websocket_android_primary(websocket: WebSocket, device_id: str):
        """[COMPAT] 旧安卓入口——NOT the canonical ingress;委派规范处理器。"""
        await _resolve_android_ws_handler()(
            websocket,
            device_id,
            ingress_path="/ws/android/{device_id}",
            ingress_classification="compat",
        )

    @app.websocket("/ws/ufo3/{device_id}")
    async def websocket_ufo3_compat(websocket: WebSocket, device_id: str):
        """[COMPAT] 旧 UFO3 入口——legacy 守卫默认关闭;开启后委派规范处理器。

        PR-1 契约:legacy 协议面默认禁用(GALAXY_ENABLE_LEGACY_PROTOCOLS=1
        显式开启),避免无人使用的历史入口成为常开攻击面。
        """
        if not _LEGACY_PROTOCOLS_ENABLED():
            await websocket.close(
                code=1008,
                reason=(
                    "legacy ufo3 ingress disabled; set "
                    "GALAXY_ENABLE_LEGACY_PROTOCOLS=1 or use /ws/device/{device_id}"
                ),
            )
            return
        await _resolve_android_ws_handler()(
            websocket,
            device_id,
            ingress_path="/ws/ufo3/{device_id}",
            ingress_classification="compat",
        )

    @app.websocket("/ws/webrtc/{device_id}")
    async def webrtc_signaling_ws(websocket: WebSocket, device_id: str):
        from galaxy_gateway.webrtc_proxy import proxy_webrtc_signaling
        await proxy_webrtc_signaling(websocket, device_id)

    @app.websocket("/ws/android")
    async def compat_android_query_ws(websocket: WebSocket):
        device_id = websocket.query_params.get("device_id", "")
        await _resolve_android_ws_handler()(
            websocket,
            device_id,
            ingress_path="/ws/android",
            ingress_classification="compat",
        )


def _LEGACY_PROTOCOLS_ENABLED() -> bool:
    """legacy 协议入口(/ws/ufo3)是否显式开启——默认禁用。"""
    import os
    return os.environ.get("GALAXY_ENABLE_LEGACY_PROTOCOLS", "").strip().lower() in (
        "1", "true", "yes",
    )


def _resolve_android_ws_handler():
    """Late-bind the handler from this module so monkeypatching works."""
    import galaxy_gateway.routes.websocket as _self
    return _self._handle_android_ws


# ── WebSocket endpoint factory (for FastAPI) ──

def create_device_websocket_routes(app, service_manager=None):
    """Register WebSocket endpoints on the FastAPI app."""
    from fastapi import WebSocket

    @app.websocket("/ws/device/{device_id}")
    async def device_ws_endpoint(websocket: WebSocket, device_id: str):
        await websocket.accept()
        if GatewayWSManager is not None:
            manager = GatewayWSManager()
            await manager.handle_device_connection(websocket, device_id)
        else:
            await websocket.close(code=1011, reason="GatewayWSManager not available")

