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
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/errors/summary")
    async def error_summary():
        """错误追踪概览"""
        try:
            from core.error_framework import get_error_tracker
            tracker = get_error_tracker()
            return JSONResponse(tracker.get_summary())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/discovery/status")
    async def discovery_status():
        """节点发现服务状态"""
        try:
            from core.node_discovery import get_node_discovery
            disc = get_node_discovery()
            return JSONResponse(disc.get_status())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/security/audit")
    async def security_audit_logs():
        """安全审计日志（最近 50 条）"""
        try:
            from core.security_middleware import get_security_manager
            sec = get_security_manager()
            return JSONResponse(sec.audit.get_recent(50))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/security/stats")
    async def security_stats():
        """安全统计仪表盘"""
        try:
            from core.security_middleware import get_security_manager
            sec = get_security_manager()
            return JSONResponse(sec.get_dashboard())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/config/status")
    async def config_manager_status():
        """配置管理器状态"""
        try:
            from core.config_hot_reload import get_config_manager
            mgr = get_config_manager()
            return JSONResponse(mgr.get_status())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/config/versions")
    async def config_version_history():
        """配置版本历史"""
        try:
            from core.config_hot_reload import get_config_manager
            mgr = get_config_manager()
            return JSONResponse(mgr.versions.get_history(20))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    return router
