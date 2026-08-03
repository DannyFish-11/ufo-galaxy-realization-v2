"""core/auth_surface_merge.py — 把 OAuth 登录面并进权威 API 层。

与 ``core/gateway_surface_merge.py`` 同一类事,但来源不同:那边搬的是
``galaxy_gateway`` 侧独有的能力,这边搬的是 ``nodes/Node_05_Auth`` 里
**从来没有被任何进程挂载过**的登录面。抽成单独一个模块,是因为
``core/api_routes.py`` 已经顶着行数预算,而这段说明本身有价值,不该为了省行数删掉。

这一族此前的真实状态
--------------------
``register_oauth_routes()`` 定义在 ``nodes/Node_05_Auth/oauth_routes.py``,而全仓
(排除 ``.venv``)只有它自己那一行 —— 从来没有被调用过。``Node_05_Auth`` 自己的
``main.py`` 挂的是 ``/login`` / ``/refresh`` / ``/register`` 那一族,不含 ``/auth/``。

也就是说这 10 条路由**不在 9000 上,也不在 Node_05 自己的 8005 上** —— 任何进程
都没有服务过它们。后果是两个客户端的登录链路都是断的:

* WearOS ``DeviceFlowManager`` → ``/auth/oauth/device/{start,poll}``(设备码登录)
* Android ``OAuthManager``     → ``/auth/oauth/{google,github,logout,refresh}``

而没有任何断言会红 —— 它只在真机连真服务端时表现为一个 404,那时候第一反应
永远是"服务是不是没起来"。

为什么并在权威层,而不是让 Node_05 自己挂
----------------------------------------
两个客户端都是拿各自的 ``serverUrl``(即统一启动器的 9000)去打 ``/auth/`` 的。
并在这里,客户端一行都不用改;挂在 8005 则要么改两个客户端各配一个 auth base url,
要么再加一层反代 —— 都是在给"一个中心"这件事反着使劲。

可搬性照例是**实测**的,不是推断:挂到只有 ``core.api_routes`` 的 app 上,
新增 10 条,``GET /auth/oauth/health`` → 200、``/providers`` → 200、
``POST /auth/oauth/device/start`` → 400(缺参数)。该模块只用路由装饰器,
不碰 ``app.state``,所以传 ``APIRouter`` 与传 ``FastAPI`` 等价。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("Galaxy.APIRoutes.AuthMerge")

__all__ = ["merge_auth_routes"]


def merge_auth_routes(router) -> None:
    """把 ``/auth/oauth/*`` 并进 ``router``(权威 API 层)。

    整段包在 try 里:登录面缺席不该阻断整个权威 API 层 —— 但也不该静悄悄,
    所以每条失败路径都会说明白发生了什么。
    """
    try:
        from fastapi import APIRouter

        from nodes.Node_05_Auth.oauth_routes import register_oauth_routes

        oauth_router = APIRouter()
        register_oauth_routes(oauth_router)

        if not oauth_router.routes:
            # register_oauth_routes 在缺 httpx / PyJWT / FastAPI 时会**静默 return**。
            # 那种情况下路由是空的,而 include_router 一个空 router 不会报错 ——
            # 于是"登录面挂上了"和"依赖没装所以什么都没挂"看起来一模一样。
            # 这里把它说出来,别让缺依赖伪装成成功。
            logger.warning("OAuth 登录面未注册任何路由(httpx / PyJWT 缺失?),/auth/oauth/* 将不可用")
            return

        router.include_router(oauth_router)
        logger.info("OAuth 登录面已并入权威 API 层:/auth/oauth/*(%d 条)", len(oauth_router.routes))
    except Exception as exc:  # noqa: BLE001 — 登录面缺席不阻断权威 API
        logger.warning("OAuth 登录面并入权威 API 层失败(可选): %s", exc)
