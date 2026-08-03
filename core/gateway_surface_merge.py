"""core/gateway_surface_merge.py — 把网关侧独有的能力并进权威 API 层。

从 ``core/api_routes.py`` 抽出来的一段。抽出去有两个理由:那边已经 1500+ 行,
而这段逻辑本身需要不短的说明 —— 说明本身是有价值的,不该为了省行数删掉。

"""

from __future__ import annotations

import logging

logger = logging.getLogger("Galaxy.APIRoutes.GatewayMerge")

__all__ = ["merge_gateway_only_routers"]


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
    # 那些不是漏挂,是同一件事有两套做法、词汇还不一样(最典型的是设备配对:
    # core/routes/pairing.py 用 /api/v1/pair/*,galaxy_gateway/api/pairing.py
    # 用 /api/v1/pairing/*)。把两套一起挂上去只会让一个 app 里有两个配对系统,
    # 那是把问题翻倍而不是解决 —— 该保留哪一套是产品决定,不该由这次接线顺手定。
    def _merge_router(target, incoming, label: str) -> None:
        """把 ``incoming`` 并进 ``target``,但**跳过已经存在的 (路径, 方法)**。

        直接 include_router 的问题是 FastAPI 会把重复路径也注册进去,匹配时先注册的赢 ——
        后来的那条永远不会被命中,成为一条看不见的死路由。而"存在但从不生效"正是
        本仓一路在清的那类东西,不该在做整合的时候顺手制造一批新的。

        典型例子:``galaxy_gateway/routes/health.py`` 同时定义了 ``/health``、
        ``/health/nats``(权威层已有)与 ``/api/v1/gateway/metrics``(权威层没有)。
        整个挂进去会白添两条死路由;跳过重复之后,只有真正缺的那些被补上。
        """
        existing = {
            (getattr(r, "path", None), m) for r in target.routes for m in (getattr(r, "methods", None) or {None})
        }
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
        # 设备准入审批(/api/v1/pairing/*)。
        #
        # 它**不是** core/routes/pairing.py 的重复实现 —— 两者是同一条路的两个阶段:
        #   core    /api/v1/pair/*     PairingCodeRegistry:短码 → 配对链接的短时映射
        #                              (card / peers / trust —— "你是谁、怎么找到我")
        #   gateway /api/v1/pairing/*  DeviceEnrollmentCoordinator + DeviceTokenRegistry
        #                              (enroll / approve / deny / pending —— "我批不批你进来")
        # 一个是发现与换名片,一个是准入与发令牌。缺了后者,设备能被找到但进不来。
        #
        # 可搬性实测:挂在只有 core.api_routes 的 app 上,GET /api/v1/pairing/pending → 200
        # (它走 core.device_enrollment 的模块级单例,不碰 gateway 的 app.state)。
        ("galaxy_gateway.api.pairing", "router", "设备准入审批 (/api/v1/pairing/*)"),
        # 客户端配置发现(/api/v1/config)。读环境变量,不依赖 app.state;实测 → 200。
        # 与 core/routes/config.py 的 /api/config 形状不同(一个是给客户端的发现端点,
        # 一个是面板用的完整配置读写),两边都留,不互相顶替。
        ("galaxy_gateway.api.config", "router", "客户端配置发现 (/api/v1/config)"),
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
