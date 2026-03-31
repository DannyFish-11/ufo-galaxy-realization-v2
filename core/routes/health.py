"""
Galaxy - Health Routes
======================

**Domain authority notice**
----------------------------
This module is the **canonical owner** of the ``/api/v1/health/*`` route
surface.  No other module should define routes under this prefix.

Canonical route ownership is declared in ``core/api_routes.py`` via the
``CANONICAL_API_ROUTES_AUTHORITY`` sentinel.

Routes:
  GET /api/v1/health/unified  - 统一健康仪表盘（整合所有健康子系统）
  GET /api/v1/health/quick    - 快速健康概览
"""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.API")

# Authority sentinel — import this from other modules to verify this file
# is the single owner of the /api/v1/health/* route surface.
HEALTH_ROUTES_AUTHORITY = "core.routes.health"


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create health routes router."""
    router = APIRouter()

    @router.get("/api/v1/health/unified")
    async def unified_health_dashboard():
        """统一健康仪表盘（整合所有健康子系统）"""
        try:
            from core.health_integration import get_unified_health_manager
            uhm = get_unified_health_manager()
            return JSONResponse(uhm.get_dashboard())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/health/quick")
    async def unified_health_quick():
        """快速健康概览"""
        try:
            from core.health_integration import get_unified_health_manager
            uhm = get_unified_health_manager()
            return JSONResponse(uhm.get_quick_status())
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    return router
