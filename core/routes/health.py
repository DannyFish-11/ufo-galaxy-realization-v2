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


def _build_quasi_platform_health_assertion() -> dict:
    """Build runtime quasi-platform integrity assertion for health surfaces."""
    try:
        from core.bounded_subject_platform_boundary import (
            build_quasi_platform_runtime_assertion_report,
        )

        report = build_quasi_platform_runtime_assertion_report()
        status = "intact" if bool(report.get("intact")) else "degraded"
        return {
            "status": status,
            "intact": bool(report.get("intact")),
            "violations": list(report.get("violations") or []),
            "checked_axes": list(report.get("checked_axes") or []),
            "final_acceptance_boundary_flags": dict(report.get("final_acceptance_boundary_flags") or {}),
            "assertion_source": report.get("_source"),
        }
    except Exception as exc:
        logger.warning("quasi-platform health assertion unavailable: %s", exc)
        return {
            "status": "error",
            "intact": False,
            "violations": [f"assertion_unavailable:{exc}"],
            "checked_axes": [],
            "final_acceptance_boundary_flags": {},
            "assertion_source": "core.routes.health._build_quasi_platform_health_assertion",
        }


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create health routes router."""
    router = APIRouter()

    @router.get("/api/v1/health/unified")
    async def unified_health_dashboard():
        """统一健康仪表盘（整合所有健康子系统）"""
        try:
            from core.health_integration import get_unified_health_manager
            uhm = get_unified_health_manager()
            payload = dict(uhm.get_dashboard() or {})
            payload["quasi_platform_state_integrity"] = _build_quasi_platform_health_assertion()
            return JSONResponse(payload)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/api/v1/health/quick")
    async def unified_health_quick():
        """快速健康概览"""
        try:
            from core.health_integration import get_unified_health_manager
            uhm = get_unified_health_manager()
            payload = dict(uhm.get_quick_status() or {})
            payload["quasi_platform_state_integrity"] = _build_quasi_platform_health_assertion()
            return JSONResponse(payload)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    return router
