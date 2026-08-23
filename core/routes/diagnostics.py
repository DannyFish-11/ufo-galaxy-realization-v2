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

    return router
