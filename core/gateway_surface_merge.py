"""core/gateway_surface_merge.py — 把网关侧独有的能力并进权威 API 层。

从 ``core/api_routes.py`` 抽出来的一段。抽出去有两个理由:那边已经 1500+ 行,
而这段逻辑本身需要不短的说明 —— 说明本身是有价值的,不该为了省行数删掉。

"""

from __future__ import annotations

import logging

logger = logging.getLogger("Galaxy.APIRoutes.GatewayMerge")

__all__ = ["merge_gateway_only_routers", "iter_path_methods"]


def _iter_path_methods(routes, prefix: str = ""):
    """递归展开一棵路由树,产出 ``(完整路径, 方法)``。

    为什么必须递归
    --------------
    新版 FastAPI 的 ``include_router`` **不再把子路由摊平**到父 router 的
    ``routes`` 里,而是塞一个 ``_IncludedRouter`` 包装对象进去 —— 它的
    ``.path`` 是 ``None``,``.methods`` 也是 ``None``。

    这一点让本文件里"跳过已存在的 (路径, 方法)"那段逻辑**一直是空转的**:
    它按 ``getattr(r, "path", None)`` 去建已存在集合,而顶层拿到的全是
    ``(None, None)``,于是任何真实路径都"不存在",从来没跳过过一条。

    先前没暴露出来,是因为在此之前并进来的几个 router 恰好都是网关独有的,
    本来就没有重复。直到并 ``galaxy_gateway.routes.chat``(为了 WebRTC 端点)
    才撞上:它带的 ``POST /api/v1/chat`` 与 ``core.routes.chat`` 撞车,被原样
    追加进去 —— 匹配时先注册的 core 赢,网关那条成了**一条永远命不中的死路由**。
    而"存在但从不生效"正是这套整合一路在清的东西,不该由整合本身制造。

    这里对 ``_IncludedRouter`` 做鸭子判定(``original_router`` 属性)而不是
    ``isinstance``:老版本 FastAPI 根本没有这个类,摊平的路由走 else 分支照样对。
    """
    for route in routes or []:
        sub = getattr(route, "original_router", None)
        if sub is not None:
            ctx = getattr(route, "include_context", None)
            yield from _iter_path_methods(getattr(sub, "routes", []), prefix + (getattr(ctx, "prefix", "") or ""))
            continue
        path = getattr(route, "path", None)
        if path is None:
            continue
        for method in getattr(route, "methods", None) or {None}:
            yield (prefix + path, method)


#: 供测试使用的公开别名 —— 让"权威面里没有重复 (路径, 方法)"可以被真正断言。
iter_path_methods = _iter_path_methods


def merge_gateway_only_routers(router) -> None:
    """把 ``galaxy_gateway`` 侧独有的 router 并进 ``router``(权威 API 层)。"""

    # ── 网关侧独有能力:并入权威 API 层 ────────────────────────────────────
    #
    # 为什么在这里挂
    # --------------
    # 本文件开篇写着"core/api_routes.py 是 Galaxy 的唯一权威 API 入口",
    # unified_launcher 也是这么说的。而实测(把两个 app 各自组装出来逐条比对)
    # 发现这句话当时**不成立**:
    #
    #     统一启动器组装出来的面     354 条
    #     galaxy_gateway.app        59 条
    #     两边都有的                18 条
    #     **只在 galaxy_gateway 上** 41 条
    #
    # 而两个 app 都配在 9000 端口。也就是说"跑哪个入口"决定了这 41 个能力
    # 存不存在,而客户端无从分辨 —— 手机端那三条恒判失败的检查
    # (/api/v1/health、/api/v1/config、/api/v1/devices/list)正是撞在这上面。
    #
    # 这里把其中**确属独有**的那些接进来,让权威层真的成为超集。
    # 之后 galaxy_gateway.app 就是它的一个子集(只跑网关的轻量部署),
    # 那是正当的;而"两个不同的系统抢同一个端口"不是。
    #
    # 没有一并搬进来的是**重复实现**(见 config/api_surface_parity.json):
    # 那些不是漏挂,是同一件事有两套做法、词汇还不一样。设备配对曾经就是这样
    # (/api/v1/pair/* 与 /api/v1/pairing/* 并存),那道题已经了结:留下 core/routes/pairing.py
    # 的 /api/v1/pair/*,另一套连同它的每设备 token 注册表一起删掉了。
    # 剩下的重复项同理 —— 该保留哪一套是产品决定,不该由这次接线顺手定。
    def _merge_router(target, incoming, label: str) -> None:
        """把 ``incoming`` 并进 ``target``,但**跳过已经存在的 (路径, 方法)**。

        直接 include_router 的问题是 FastAPI 会把重复路径也注册进去,匹配时先注册的赢 ——
        后来的那条永远不会被命中,成为一条看不见的死路由。而"存在但从不生效"正是
        本仓一路在清的那类东西,不该在做整合的时候顺手制造一批新的。

        典型例子:``galaxy_gateway/routes/health.py`` 同时定义了 ``/health``、
        ``/health/nats``(权威层已有)与 ``/api/v1/gateway/metrics``(权威层没有)。
        整个挂进去会白添两条死路由;跳过重复之后,只有真正缺的那些被补上。
        """
        existing = set(_iter_path_methods(getattr(target, "routes", [])))
        added, skipped = [], []
        for route in list(getattr(incoming, "routes", [])):
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None) or {None}
            if any((path, m) in existing for m in methods):
                skipped.append(path)
                continue
            target.routes.append(route)
            for m in methods:
                existing.add((path, m))
            added.append(path)
        logger.info(
            "并入权威 API 层 %s:新增 %d 条%s",
            label,
            len(added),
            f",跳过 {len(skipped)} 条已存在({', '.join(sorted(set(skipped))[:4])})" if skipped else "",
        )

    for _mod_path, _attr, _label in (
        ("galaxy_gateway.routes.linux_agent", "router", "Linux Agent (/api/v1/agents/linux/*)"),
        ("galaxy_gateway.routes.sandbox", "router", "Sandbox (/api/v1/agents/sandbox/*)"),
        ("galaxy_gateway.routes.sync_status", "router", "同步状态 (/sync/status)"),
        ("galaxy_gateway.gateway_service", "router", "Gateway v5 (/api/v5/*)"),
        # 客户端配置发现(/api/v1/config)。读环境变量,不依赖 app.state;实测 → 200。
        # 与 core/routes/config.py 的 /api/config 形状不同(一个是给客户端的发现端点,
        # 一个是面板用的完整配置读写),两边都留,不互相顶替。
        ("galaxy_gateway.api.config", "router", "客户端配置发现 (/api/v1/config)"),
        # WebRTC 信令端点发现(/api/v1/webrtc/endpoint)。
        #
        # 这一条是**唯一**一个"网关侧独有、且权威层连近似能力都没有"的路径:
        # 其余 13 条在 core 侧都有对应实现(见 config/api_surface_parity.json),
        # 而这条没有 —— 不搬,跨设备投屏在统一启动器上就没有发现入口。
        #
        # 它长在 galaxy_gateway/routes/chat.py 里(不是某个 webrtc 模块 ——
        # galaxy_gateway.routes.webrtc 并不存在),所以并的是 chat 的 router。
        # chat 的另一条 /api/v1/chat 权威层已有,会被上面的"跳过已存在"挡掉,
        # 不会多出一条永远命不中的死路由。
        #
        # 可搬性照例是实测的,不是推断:挂到只有 core.api_routes 的 app 上真调一次,
        # GET /api/v1/webrtc/endpoint → **403** cross_device_disabled ——
        # 那是这条路由自己的策略应答(跨设备开关没开),说明它跑起来了。
        # 对照组是 llm / health 那两个:同样的挂法得到 503 "Service not ready",
        # 那才是"依赖 gateway 的 app.state、在权威层跑不起来"的样子。
        #
        # 台账里这条原先记的是"依赖网关内部状态,搬迁需先解耦" —— 那句话是推断,
        # 实测把它推翻了。记下来是因为:同一份台账里另外两条**确实**是 503,
        # 一条推断对了、一条推断错了,而只有真调过才知道是哪一条。
        ("galaxy_gateway.routes.chat", "router", "WebRTC 端点发现 (/api/v1/webrtc/endpoint)"),
        # 下面两个**故意不并**,尽管它们确有权威层没有的路径:
        #     galaxy_gateway.routes.llm     → /api/v1/llm/stats
        #     galaxy_gateway.routes.health  → /api/v1/health、/api/v1/gateway/metrics*
        #
        # 它们的处理函数取的是 **galaxy_gateway 那个 app 的 app.state**
        # (Depends(get_llm_router) / _get_state(request, ...)),由
        # galaxy_gateway.bootstrap.lifecycle.lifespan 在启动时装配。权威层的 app
        # 不跑那个 lifespan,并过来之后这些路由**存在但永远 503**。
        #
        # 这是实测出来的,不是推断。第一版把这两个并了进来,起服务真打一遍:
        #     /api/v1/llm/stats  → 503 {"detail":"LLM Router not available"}
        #     /api/v1/health     → 503 {"detail":"Service not ready"}
        # 同一批里 linux_agent / sandbox / sync_status / v5 四个都是 200 ——
        # 差别就在依不依赖 app.state。
        #
        # 为了让"只在 gateway 上"的数字好看而搬一条注定 503 的路由过来,比不搬更糟:
        # 台账会显示"已解决",而实际是多了一条死路由。要真搬,得先让这些处理函数
        # 不再依赖 gateway 的 app.state,那是独立的一件事。
    ):
        try:
            _mod = __import__(_mod_path, fromlist=[_attr])
            _r = getattr(_mod, _attr, None)
            if _r is None:
                logger.info("%s 路由不可用(模块自降级),跳过", _label)
                continue
            _merge_router(router, _r, _label)
        except Exception as _merge_err:  # noqa: BLE001 — 单个可选路由缺席不阻断整层
            logger.warning("%s 并入权威 API 层失败(可选): %s", _label, _merge_err)
