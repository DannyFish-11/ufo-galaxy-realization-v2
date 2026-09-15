"""nodes/common/node_auth.py — 给节点 HTTP 面装上身份认证

## 这一层回答的问题和权限闸不同

``nodes.common.action_gate`` 回答的是"**这个动作**被声明允许了吗";
这里回答的是"**调用方是谁**"。两个问题都得有答案 ——
只有权限闸,等于"谁都可以,但只能做白名单里的事";在一个能操作桌面、执行命令的
节点上,那还差得远。

此前这些节点的 HTTP 面**没有任何认证**,而且和仓里其余 122 个节点一样绑 0.0.0.0。

## 不是新造轮子

``core.auth`` 已经是一套完整机制:token 轮换、吊销、过期、每设备配对 token,
以及**零配置自签**(``ensure_local_token``,落在 ``$GALAXY_DATA_DIR/`` —— compose 里
那是所有节点共享的 ``galaxy-data`` 卷,所以同一部署内天然共用一个 token)。
网关的 ``routes/sessions.py``、``routes/llm.py`` 和 ``launcher/services.py``
早就在用 ``Depends(require_auth)``。这里只是把同一套接到节点上。

## 为什么用中间件而不是给每条路由加 Depends

9 个节点 81 条路由,逐条改函数签名要动 81 处,漏一处就是一个没人管的口子,
而且没有任何现象。中间件是一处装上、整片生效,豁免表是**显式的白名单**,
少一条只会让某个端点变严,不会变松。

借 ``galaxy_gateway/middleware.py`` 的形状:豁免按 (路径 → 允许的方法) 表达,
而不是纯路径集合 —— 纯路径集合会把同一路径的 GET 和 POST 一起豁免。

## HTTP 中间件管不到 WebSocket

``@app.middleware("http")`` 落到 Starlette 的 ``BaseHTTPMiddleware``,它只处理
``scope["type"] == "http"``;WebSocket 握手的 scope 是 ``"websocket"``,**整条都
不经过它**。所以"给 125 个节点装上了 HTTP 鉴权"并不等于那些节点的 WS 端点也被挡住 ——
实测:装了本模块的 app,``GET /status`` 401,同一个 app 上的 ``@app.websocket``
不带任何令牌照样连上并收到数据。

因此 WS 面另走一层**纯 ASGI 中间件**(``_WebSocketAuthGuard``),在握手被 accept
**之前**判定。凭据只认 ``Authorization`` 头:放进 query string 的令牌会原样进入
访问日志和 Referer,而本仓唯一的 WS 调用方(网关 ``webrtc_proxy`` 与
``Node_96`` 的 WS 传输)都是能设请求头的 Python 客户端;安卓侧走网关
``/ws/webrtc/{deviceId}``,不直连节点。

## 为什么 /health 必须豁免

``deploy/compose/full.yml`` 里每个节点的 healthcheck 是
``curl -sf http://localhost:80XX/health`` —— 裸 curl,不带任何令牌。
把存活探针也要求鉴权,结果是容器永远 unhealthy、反复重启。
它也不暴露任何能力:只报告状态,不动手。
"""

from __future__ import annotations

import logging
import os
from typing import Dict, Optional, Set

logger = logging.getLogger("Galaxy.NodeAuth")

__all__ = ["DEFAULT_EXEMPT", "WS_CLOSE_POLICY_VIOLATION", "install_node_auth"]

#: WS 关闭码 1008 = policy violation。RFC 6455 给的就是"消息违反策略"这一格,
#: 没有单独的"未认证"码;仓里 ``routes/websocket.py`` 回绝 legacy 入口用的也是它。
WS_CLOSE_POLICY_VIOLATION = 1008

#: 默认豁免:只有存活探针。值是允许的 HTTP 方法集合。
#:
#: 刻意**不含** ``/tools`` / ``/status`` —— 它们不动手,但会把这个节点的能力面
#: 摊给未认证方看。动作权限闸放它们过是另一回事(那道闸管的是"能不能做"),
#: 认证这一层没有理由放。
DEFAULT_EXEMPT: Dict[str, Set[str]] = {
    # deploy/compose/full.yml 里 126 个 healthcheck 用的就是这个;另外三个是少数
    # 服务的写法。全部只报告存活,不动手。
    "/health": {"GET", "HEAD"},
    "/healthz": {"GET", "HEAD"},
    "/readyz": {"GET", "HEAD"},
    "/health/live": {"GET", "HEAD"},
}


def _auth_disabled_explicitly() -> bool:
    """``GALAXY_NODE_AUTH=off`` —— 给"确实不想要"的部署留的口子,不是给"还没想好"的。

    注意它只能**关**,不能开:开与不开由 ``core.auth.is_auth_enabled()`` 决定
    (默认 True,``GALAXY_MODE=production`` 强制 True)。这里多一个开关是因为
    节点面的影响范围和网关不同,运维可能需要分别控制。
    """
    return os.getenv("GALAXY_NODE_AUTH", "").strip().lower() in ("off", "0", "false", "no")


async def _authorize(node_id: str, *, authorization, x_device_id, path: str):
    """判定一次调用的身份。放行返回 ``None``,否则返回 ``(status, detail)``。

    HTTP 面和 WebSocket 面共用这一份判定,是为了让两边**不可能**在"拿不到鉴权
    模块怎么办""开关怎么读"这些地方分叉 —— 这类分叉正是 WS 面此前整条漏掉的
    那种缺口的来源。
    """
    try:
        from core.auth import is_auth_enabled, require_auth  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 — 拿不到鉴权就不放行
        logger.error("%s 鉴权模块不可用,拒绝请求 %s: %s", node_id, path, exc)
        return 503, f"auth unavailable; refusing to serve: {exc}"

    if not is_auth_enabled():
        return None

    try:
        await require_auth(authorization=authorization, x_device_id=x_device_id)
    except Exception as exc:  # noqa: BLE001 — HTTPException 也在内
        return getattr(exc, "status_code", 401), getattr(exc, "detail", "unauthorized")

    return None


class _WebSocketAuthGuard:
    """WebSocket 握手前的身份判定 —— 纯 ASGI,因为 HTTP 中间件看不见 WS scope。

    拒绝方式是在 accept **之前**发 ``websocket.close``:按 ASGI 规范,这会让
    服务器用 HTTP 403 回绝握手,连接从来没有建立过。**不能**用"先 accept
    再 close" —— 那样端点的 ``await websocket.accept()`` 已经发生,客户端拿到的是
    一条成功建立又断开的连接,而节点侧的 ``on_connect`` 副作用(Node_95 会把
    ``state.signaling_connections[device_id]`` 填上)已经跑过了。
    """

    def __init__(self, app, node_id: str) -> None:
        self.app = app
        self.node_id = node_id

    async def __call__(self, scope, receive, send):  # noqa: ANN001
        if scope.get("type") != "websocket":
            await self.app(scope, receive, send)
            return

        if _auth_disabled_explicitly():
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        path = scope.get("path", "")
        verdict = await _authorize(
            self.node_id,
            authorization=headers.get("authorization"),
            x_device_id=headers.get("x-device-id"),
            path=path,
        )
        if verdict is None:
            await self.app(scope, receive, send)
            return

        status, detail = verdict
        logger.warning("%s 拒绝未认证 WebSocket 握手 %s: %s", self.node_id, path, detail)
        # 规范要求先收下 websocket.connect,再回绝。
        try:
            await receive()
        except Exception as exc:  # noqa: BLE001
            logger.debug("%s 回绝握手时未能读到 connect 事件: %s", self.node_id, exc)
        await send({"type": "websocket.close", "code": WS_CLOSE_POLICY_VIOLATION, "reason": str(detail)[:120]})


def install_node_auth(app, node_id: str, exempt: Optional[Dict[str, Set[str]]] = None) -> None:
    """给 ``app`` 装上鉴权中间件。

    **拿不到 core.auth 就拒绝一切非豁免请求**,而不是放行。

    ``galaxy_gateway/routes/sessions.py`` 里那个 try/except 在导入失败时退化成
    no-op 依赖 —— 对会话查询也许还行,对一个能点鼠标、跑命令的节点不行:
    鉴权模块导不进来时放行,等于这层没装。
    """
    table = dict(DEFAULT_EXEMPT if exempt is None else exempt)

    @app.middleware("http")
    async def _node_auth_middleware(request, call_next):  # noqa: ANN001
        from starlette.responses import JSONResponse  # noqa: PLC0415

        allowed = table.get(request.url.path)
        if allowed and request.method.upper() in allowed:
            return await call_next(request)

        if _auth_disabled_explicitly():
            return await call_next(request)

        verdict = await _authorize(
            node_id,
            authorization=request.headers.get("authorization"),
            x_device_id=request.headers.get("x-device-id"),
            path=request.url.path,
        )
        if verdict is None:
            return await call_next(request)

        status, detail = verdict
        if status != 503:
            logger.warning("%s 拒绝未认证请求 %s %s: %s", node_id, request.method, request.url.path, detail)
        return JSONResponse(
            status_code=status,
            content={"detail": detail},
            headers={"WWW-Authenticate": "Bearer"} if status != 503 else None,
        )

    app.add_middleware(_WebSocketAuthGuard, node_id=node_id)

    logger.info("%s 已装上 HTTP + WebSocket 鉴权(豁免: %s)", node_id, sorted(table))
