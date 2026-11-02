"""
galaxy_gateway/routes/websocket.py — 设备 WebSocket 入口(规范属主)

CANONICAL DEVICE INGRESS AUTHORITY
==================================
本模块是设备 WebSocket 入口的唯一规范属主。入口面登记(与
DEVICE_WS_INGRESS_SURFACE_REGISTRY 保持一致):

    /ws/device/{device_id}   [CANONICAL]        规范设备入口(唯一)
    /ws/webrtc/{device_id}   [MEDIA]            WebRTC 信令代理(只承载媒体信令)
    /ws/android/{device_id}  [RETIRED]          2026-11-02 退役(所有者定)
    /ws/android              [RETIRED]          2026-11-02 退役
    /ws/ufo3/{device_id}     [RETIRED]          2026-11-02 退役(原默认关,GALAXY_ENABLE_LEGACY_PROTOCOLS 随之删除)
    /ws/{device_id}          [DEPRECATED]       已移除——新客户端一律使用 /ws/device/
    /ws                      [DEBUG]            已移除——调试入口不再对外暴露

退役前核对过:安卓 App 与手表的全部提交历史里一次都没连过这三条(两边一直只连
/ws/device/{device_id}),本仓库里也没有任何客户端、部署配置在用;客户端配置发现
(GET /api/v1/config 的 ws_paths)只再给规范路径。连旧路径的请求在握手时就被拒
(没有这条路由),不会进处理器。``tests/test_retired_device_ingress_stays_retired.py`` 守着。

设备入口统一汇聚到 _handle_android_ws 单处理器,消息处理与入口记账不会随路由分叉。本模块只主张设备【入口】权威,不主张编排
(orchestration)或就绪(readiness)权威。

PR-GATEWAY-FIX: 同时提供 core/api_routes.py 所需的兼容导出(入口权威声明与入口登记表)。
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

#: 后台跑着的智能体回合(设备发起的一整轮,见 galaxy_gateway/device_turns.py):留一个引用,任务不被回收、连接断了也做完
_TURNS: set = set()

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
    bridge's responses back to the socket. The device ingress converges on
    this single handler so message handling and ingress accounting cannot
    diverge per route (the compat surfaces were retired on 2026-11-02).
    """
    from fastapi import WebSocketDisconnect

    from galaxy_gateway.android_bridge import android_bridge
    from galaxy_gateway.device_turns import runs_an_agent_turn

    await websocket.accept()
    logger.info(
        "device ws connected: device_id=%s ingress=%s (%s)",
        device_id,
        ingress_path,
        ingress_classification,
    )

    # 兼容入口用量记账 —— 记在这个**汇合点**上,不在每条路由里各写一遍(分散到各路由里必然漏掉一条,
    # 漏掉的那条正好会显示成「没人用」)。2026-11-02 起没有挂着的兼容 WS 入口了;将来真要加一条,记账已经在这儿。
    if ingress_classification == "compat":
        try:
            from core.compat_usage import record_use  # noqa: PLC0415

            record_use(ingress_path, client_hint=str(device_id or "")[:40])
        except Exception:  # noqa: BLE001 — 记账失败不该打断一条连接
            pass
    # 这条连接自己的凭证:握手头里的 Bearer,或者这条连接上已经回过 auth_ok 的 auth 帧里的令牌。
    # 安卓先发 auth、再发不带令牌的 device_register —— 不把连接的凭证带给登记,认证开着时手机永远登记不上。
    transport_token = _bearer_token(websocket)
    send_lock = asyncio.Lock()

    async def _reply(response) -> None:
        async with send_lock:
            await websocket.send_json(response)

    async def _run_turn(message) -> None:
        """交给智能体的一整轮在后台跑,读循环接着读(这一轮里设备对批准的回答、心跳都靠它),见 galaxy_gateway/device_turns.py。"""
        try:
            response = await android_bridge.handle_message(websocket, message)
            if response is not None:
                await _reply(response)
        except Exception as exc:  # noqa: BLE001 — 连接已经断了 / 回包发不出去:这一轮本身照样做完
            logger.info("device ws turn reply not delivered for %s: %s", device_id, exc)

    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                continue
            # NOTE: do NOT inject the path device_id into the payload — the
            # bridge enforces MISSING_REQUIRED_FIELDS on the payload itself.
            message.setdefault("_ingress_path", ingress_path)
            message.setdefault("_ingress_classification", ingress_classification)
            if transport_token and not _frame_token(message):
                message["_ingress_transport_token"] = transport_token  # 登记照样重新校验(含配对令牌绑设备)
            if runs_an_agent_turn(message):
                task = asyncio.get_running_loop().create_task(_run_turn(message))
                _TURNS.add(task)  # 连接断了也让这一轮做完(已批准的动作不做一半)
                task.add_done_callback(_TURNS.discard)
                continue
            response = await android_bridge.handle_message(websocket, message)
            if response is not None:
                await _reply(response)
            if message.get("type") == "auth" and (response or {}).get("type") == "auth_ok":
                transport_token = _frame_token(message) or transport_token
            if message.get("type") == "device_register" and (response or {}).get("success") is True:
                registered = str(message.get("device_id") or device_id)
                await _resend_a2a(registered)
    except WebSocketDisconnect:
        logger.info("device ws disconnected: device_id=%s", device_id)
    except Exception as exc:
        logger.warning("device ws error for %s: %s", device_id, exc)
    finally:
        # 通话是连接级资源：连接没了，PeerConnection 和 provider 会话必须跟着收掉。
        try:
            from galaxy_gateway.voice_call_route import close_voice_route, voice_route_key

            await close_voice_route(voice_route_key(websocket))
        except Exception as exc:  # noqa: BLE001
            logger.debug("device ws voice route cleanup failed: %s", exc)
        if device_id:
            try:
                await android_bridge.disconnect_device(device_id, websocket=websocket)
            except Exception as exc:
                logger.debug("device ws disconnect cleanup failed: %s", exc)


def _bearer_token(websocket) -> str:
    raw = str(getattr(websocket, "headers", {}).get("authorization") or "").strip()
    return raw[7:].strip() if raw.lower().startswith("bearer ") else ""


def _frame_token(message: dict) -> str:
    """帧自己带的令牌(与 ``core.participant_admission.extract_ingress_token`` 认的字段一致)。"""
    from core.participant_admission import extract_ingress_token

    token, _field = extract_ingress_token(message)
    return token or ""


async def _resend_a2a(device_id: str) -> None:
    """设备(重新)登记上了,登记确认也已经写回去:中心发给它、还没确认的 A2A 消息按序补发。

    放在写完登记确认之后,设备先看到「登记成功」再看到补发的消息。它那边的桥接 Agent 在不在,
    要等它回了这次派遣才算数(``phone_bridge.note_registered``)。
    """
    try:
        from core.a2a_link import resend_unacked
        from core.phone_bridge import note_registered

        note_registered(device_id)

        n = await resend_unacked(device_id)
        if n:
            logger.info("a2a: resent %d unacknowledged message(s) to %s", n, device_id)
    except Exception as exc:  # noqa: BLE001 — 补发失败不打断连接;下次重连再补
        logger.debug("a2a resend to %s failed: %s", device_id, exc)


def register_websocket_routes(app) -> None:
    """Register the device WebSocket ingress routes.

    Exactly one device ingress (``/ws/device/{device_id}``) plus the media-only WebRTC signaling proxy.
    The legacy ``/ws/android`` / ``/ws/android/{device_id}`` / ``/ws/ufo3/{device_id}`` surfaces were
    retired on 2026-11-02 (no client in any of the three repos ever used them).
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

    @app.websocket("/ws/webrtc/{device_id}")
    async def webrtc_signaling_ws(websocket: WebSocket, device_id: str):
        from galaxy_gateway.webrtc_proxy import proxy_webrtc_signaling

        await proxy_webrtc_signaling(websocket, device_id)


def _resolve_android_ws_handler():
    """Late-bind the handler from this module so monkeypatching works."""
    import galaxy_gateway.routes.websocket as _self

    return _self._handle_android_ws
