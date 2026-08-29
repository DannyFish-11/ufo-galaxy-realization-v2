"""
Galaxy - Diagnostics Routes
============================

**Domain authority notice**
----------------------------
This module is the **canonical owner** of the system-diagnostics route
surface.  Diagnostic endpoints expose operational state for operators and
monitoring integrations — they are **not** the canonical projection truth
for desktop consumers (see ``core/routes/projection.py`` for that).

Canonical route ownership is declared in ``core/api_routes.py`` via the
``CANONICAL_API_ROUTES_AUTHORITY`` sentinel.

Routes:
  GET /api/v1/concurrency/status  - 并发管理器状态
  GET /api/v1/errors/summary      - 错误追踪概览
  GET /api/v1/discovery/status    - 节点发现服务状态
  GET /api/v1/security/audit      - 安全审计日志
  GET /api/v1/security/stats      - 安全统计仪表盘
  GET /api/v1/config/status       - 配置管理器状态
  GET /api/v1/config/versions     - 配置版本历史
"""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.API")

# Authority sentinel — import this from other modules to verify this file
# is the single owner of the diagnostics route surface.
DIAGNOSTICS_ROUTES_AUTHORITY = "core.routes.diagnostics"


def _failed(what: str) -> JSONResponse:
    """记录异常栈到服务端日志,只回给调用方一句不带内部细节的话。

    为什么不 ``return {"error": str(e)}``
    -------------------------------------
    CodeQL alert 1066(information exposure through an exception)报的就是这个:
    异常消息里带着内部模块路径、对象名、栈上下文,直接回出去等于交给任何能打到
    这个端点的人。而**诊断端点**天生就是给"能连上但不该知道内部结构"的人用的,
    正是最不该泄的那一类。

    排查需要的东西一点没少 —— ``logger.exception`` 把完整栈写进服务端日志,
    那才是运维该去看的地方。
    """
    logger.exception("%s 失败", what)
    return JSONResponse({"error": f"{what} unavailable — see server logs"}, status_code=500)


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create system diagnostics routes router."""
    router = APIRouter()

    @router.get("/api/v1/concurrency/status")
    async def concurrency_status():
        """并发管理器状态"""
        try:
            from core.concurrency_manager import get_concurrency_manager

            mgr = get_concurrency_manager()
            return JSONResponse(mgr.get_status())
        except Exception:
            return _failed("concurrency status")

    @router.get("/api/v1/errors/summary")
    async def error_summary():
        """错误追踪概览"""
        try:
            from core.error_framework import get_error_tracker

            tracker = get_error_tracker()
            return JSONResponse(tracker.get_summary())
        except Exception:
            return _failed("error summary")

    @router.get("/api/v1/discovery/status")
    async def discovery_status():
        """节点发现服务状态"""
        try:
            from core.node_discovery import get_node_discovery

            disc = get_node_discovery()
            return JSONResponse(disc.get_status())
        except Exception:
            return _failed("discovery status")

    @router.get("/api/v1/security/execution-isolation")
    async def execution_isolation_status():
        """智能体自写代码**当前跑在多硬的边界里**。

        放在 security 一族下是有意的:这不是性能指标,是"模型生成的代码此刻有没有
        真边界"。``is_isolated=false`` 意味着它跑在同一个内核、同一个用户下 ——
        那是需要被看见的事实,而在这个端点之前,整个系统里没有任何一处说得出它。

        只读:不触发容器拉起(见 ``isolation_report``)。
        """
        try:
            from core.execution_isolation import isolation_report

            return JSONResponse(isolation_report())
        except Exception:
            return _failed("execution isolation status")

    @router.get("/api/v1/security/context-provenance")
    async def context_provenance_status():
        """最近一次进模型的上下文,是由谁写的那些段构成的。

        模型没有指令通道与数据通道之分 —— 系统提示、用户的话、抓回来的网页、
        MCP 工具描述,对它来说是同一条 token 流。这个端点回答的是:**这一轮里
        有没有不可信内容进过上下文**,以及工具闸因此收到了多紧。

        ``floor`` 是**下界**:一次工具调用被哪一段诱发无法归因,所以按上下文里
        出现过的最低信任来源算。``recorded=false`` 表示还没装配过 —— 那按
        unknown(最低)处理,不是按可信处理。

        只读:不触发任何装配。响应里**不含正文**,只有来源与长度。
        """
        try:
            from core.context_provenance import provenance_report

            return JSONResponse(provenance_report())
        except Exception:
            return _failed("context provenance status")

    @router.get("/api/v1/runtime/domain")
    async def runtime_domain_status():
        """这一拍在哪儿跑 —— 连续体的第二公共维度,以及它凭什么这么判。

        为什么这一位需要一个自己的端点
        ------------------------------
        整套"按作用域分权威"(本地的事本地说了算,跨设备的事中心说了算)都站在
        这一位上。而这一位有一个必须被看见的取值:``domain = null``,意思是
        **判不出来** —— 它和 ``local`` 不是一回事,绝不能被读成一回事。

        判不出来的时刻,恰恰是连接刚抖动、编队刚建立、注册表还没同步的时刻,
        也就是最需要中心仲裁的时刻。如果那时候被静默当成"本地",权威就会在
        最不该的时候被交给本地。所以这个端点把 ``null`` 显式报出来。

        ``remote_sessions`` 同理:``null`` = 注册表问不到,与"问到了,是 0 台"
        必须分得开 —— 后者判得出作用域(就是本地),前者判不出。

        只读:不触发任何连接、不改变任何状态。
        """
        try:
            from core.continuum.runtime_domain_resolver import domain_report

            return JSONResponse(domain_report())
        except Exception:
            return _failed("runtime domain status")

    @router.get("/api/v1/runtime/scope-authority")
    async def scope_authority_status():
        """这个作用域下谁说了算,以及权威易过几次手。

        与上一个端点的分工
        ------------------
        ``/api/v1/runtime/domain`` 回答**在哪儿跑**(事实);这一个回答**谁说了算**
        (据此得出的归属)。分开是因为两者会不一致地失效:作用域判得出但权威规则改错了,
        与作用域根本判不出来,是两种不同的故障,合成一个端点就分不出是哪一种。

        三个必须被看见的取值
        --------------------
        * ``authority = "undecidable"`` —— 说不出来谁说了算,**不是**"默认本地"。
          这一档下本地写入一律不收。
        * ``migration_degraded = true`` —— 迁移语义是**降级来的**(判不出来时退到
          非破坏性的共享语义),不是判出来的。降级必须留痕,否则它看起来和判出来一样。
        * ``handovers`` —— 权威易手记录。一个会话从 local 变成 cross_device 的那一刻
          权威换了人;不记下来,事后就没有任何一处能回答"那次冲突发生时谁说了算"。

        只读:不触发任何连接、不改变任何状态。
        """
        try:
            from core.scope_authority import authority_report, recent_handovers

            payload = authority_report()
            payload["handovers"] = recent_handovers()
            return JSONResponse(payload)
        except Exception:
            return _failed("scope authority status")

    @router.get("/api/v1/compat/usage")
    async def compat_usage_status():
        """那些旧面,到底还有没有人在用。

        为什么需要这个端点
        ------------------
        "旧 REST 别名与兼容 WS 入口什么时候退役"(路线图 Q6,挡着 C5/C6)一直定不了,
        不是缺决心,是**缺数据** —— 此前这些面只有一行 ``logger.info``,日志会滚,
        没有任何一处能回答"上周有多少次调用、是谁在调"。

        最容易读错的一格:``calls = 0``
        ------------------------------
        计数在进程内,重启归零。所以 0 的射程只有 ``uptime_seconds`` 这么长,
        **不等于"没人用"**。据此提前退役会打死还在用的客户端 —— 而这正是
        C5/C6 那两项要防的事。响应里的 ``zero_means`` 把这句话原样写着。

        要回答"过去两周多少次",抓 Prometheus 的
        ``galaxy_compat_surface_calls_total``(带 surface/kind 标签,跨重启由外部
        时序库留存)。这个端点是便于当场看一眼的视图,不是那份权威数据。

        ``sunset_at = null`` 是**故意的**:退役日期还没定,而它正是这份数据要支撑
        的东西。先编一个日期发到 ``Sunset`` 头上再回头验证,顺序是反的。

        只读:不触发任何连接、不改变任何状态。
        """
        try:
            from core.compat_usage import usage_report

            return JSONResponse(usage_report())
        except Exception:
            return _failed("compat usage status")

    @router.get("/api/v1/security/connection-provenance")
    async def connection_provenance_status():
        """两条"对端还是我登记过的那个吗"的复验,合在一处报。

        - provider 地址:改掉 base_url,密钥与对话全文会照常发往新地址,
          而一切看起来都正常工作;
        - MCP 工具清单:描述与入参 schema 直接进模型上下文,服务器随时能改。

        ``trust_on_first_use`` 那一位要单独看:TOFU 的钉子只挡"后来被改了",
        挡不住"一开始就是坏的"。混进总数里报会让人高估这道闸。

        只读:不触发任何连接。
        """
        try:
            from core.endpoint_admission import endpoint_report
            from core.mcp_tool_pins import pins_report

            return JSONResponse({"endpoints": endpoint_report(), "mcp_tools": pins_report()})
        except Exception:
            return _failed("connection provenance status")

    @router.get("/api/v1/security/egress")
    async def egress_status():
        """这次运行往外连了哪儿,以及这道闸**有没有实际拦截效力**。

        ``enforcing`` 那一位是整份报告里最要紧的:``mode=audit``(默认)下它是
        ``false``——audit 只记账不拦。不给这一位,``mode`` 字段会被读成"已防护"。

        只读:不改任何出站行为。
        """
        try:
            from core.egress_guard import egress_report

            return JSONResponse(egress_report())
        except Exception:
            return _failed("egress status")

    @router.get("/api/v1/security/weights-admission")
    async def weights_admission_status():
        """权重从哪来、允不允许执行它自带的代码。

        与 execution-isolation 并列放在 security 一族下,是因为它们是**同一个问题的
        两半**:那边管"模型写的代码跑在多硬的边界里",这边管"模型自己带的代码allow
        不允许跑" —— 而后者根本不走 SafeExecutor,容器边界对它无效。

        只读:不触发任何下载或加载。
        """
        try:
            from core.weights_admission import weights_report

            return JSONResponse(weights_report())
        except Exception:
            return _failed("weights admission status")

    @router.get("/api/v1/security/audit")
    async def security_audit_logs():
        """安全审计日志（最近 50 条）"""
        try:
            from core.security_middleware import get_security_manager

            sec = get_security_manager()
            return JSONResponse(sec.audit.get_recent(50))
        except Exception:
            return _failed("security audit logs")

    @router.get("/api/v1/security/stats")
    async def security_stats():
        """安全统计仪表盘"""
        try:
            from core.security_middleware import get_security_manager

            sec = get_security_manager()
            return JSONResponse(sec.get_dashboard())
        except Exception:
            return _failed("security stats")

    @router.get("/api/v1/config/status")
    async def config_manager_status():
        """配置管理器状态"""
        try:
            from core.config_hot_reload import get_config_manager

            mgr = get_config_manager()
            return JSONResponse(mgr.get_status())
        except Exception:
            return _failed("config manager status")

    @router.get("/api/v1/config/versions")
    async def config_version_history():
        """配置版本历史"""
        try:
            from core.config_hot_reload import get_config_manager

            mgr = get_config_manager()
            return JSONResponse(mgr.versions.get_history(20))
        except Exception:
            return _failed("config version history")

    @router.get("/api/v1/mesh/participation-summary")
    async def mesh_participation_summary():
        """网格/会话/编队参与状态的统一快照。

        ``core/mesh_participation_summary.py`` 把六个子系统(设备编队、body mesh
        注册表、mesh session、mesh membership、session coordinator、跨设备策略)
        的状态摊平成一份可序列化的视图。它是**只读**的,不改任何编排行为。

        在这个端点之前它没有任何生产消费方 —— 一个建好了却没接出去的诊断面,
        只有测试在看。而"网格里现在到底谁在、各是什么角色"恰恰是排查多设备问题
        时第一个要问的事。
        """
        try:
            from core.mesh_participation_summary import get_current_mesh_participation_summary

            summary = get_current_mesh_participation_summary()
            payload = summary.to_dict() if hasattr(summary, "to_dict") else summary
            return JSONResponse(payload)
        except Exception:
            # 六个子系统里任何一个在半初始化状态下抛,都会走到这里 ——
            # CodeQL alert 1066 报的正是这六条流。细节只进日志,见 _failed。
            return _failed("mesh participation summary")

    @router.get("/api/v1/runtime/phase-ledger")
    async def runtime_phase_ledger(hours: int = 72):
        """三态转移的耐久账 —— 最近 ``hours`` 小时(默认 72,即三天)。

        为什么需要这个端点:三态此前**一处都不落盘**。``DecisionTimeline`` 是
        进程内的 list,``RenderPosture`` 每拍现算,``_execution_lifecycle_history``
        是模块级 dict —— 全都活不过一次重启。于是"这三天它是静着还是在表达"
        这件事根本问不出来。

        读的时候要拿 ``status.empty_means`` 一起看:**读到空不等于这段什么都没
        发生**。账本不在、或这段落在进程不在的时间里,同样是空。两者要靠记录上
        的 ``epoch`` 分开 —— 相邻两条 epoch 不同,中间那段就是不可知,不是安静。
        """
        try:
            import time as _time

            from core.phase_transition_ledger import ledger_status, read_window

            span = max(1, min(int(hours), 24 * 90)) * 3600.0
            now = _time.time()
            records = read_window(now - span, now + 1.0)
            return JSONResponse(
                {
                    "status": ledger_status(),
                    "window_hours": span / 3600.0,
                    "record_count": len(records),
                    "records": records,
                }
            )
        except Exception:
            return _failed("phase transition ledger")

    return router
