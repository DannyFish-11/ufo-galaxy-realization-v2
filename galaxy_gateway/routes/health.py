"""
galaxy_gateway/routes/health.py — Health check and metrics endpoints.

Routes:
  GET /health                          - Basic health check
  GET /api/v1/health                   - Enhanced health (AI module status)
  GET /health/nats                     - NATS control-plane health
  GET /api/v1/gateway/metrics/json     - Gateway metrics (JSON snapshot)
  GET /api/v1/gateway/metrics          - Gateway metrics (Prometheus text)
  GET /gateway/metrics                 - Gateway metrics (Prometheus alias)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from starlette.requests import Request
from starlette.responses import Response

from galaxy_gateway.dependencies import (
    get_websocket_manager,
    get_nats_adapter,
    get_llm_router_instance,
    get_openclawd,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health_check(wsm: Any = Depends(get_websocket_manager)) -> Dict[str, Any]:
    """Basic health check — returns minimal data (Bug 4 fix).

    Previously returned full service details; now returns only status,
    version, and a simple device count to keep responses small and fast.
    """
    return {
        "status": "healthy",
        "version": "3.0.0",
        "devices_connected": wsm.get_device_count(),
    }


@router.get("/health/nats")
async def nats_health(request: Request, nats: Any = Depends(get_nats_adapter)) -> Dict[str, Any]:
    """NATS control-plane health — returns bus stats and adapter state."""
    try:
        from core.nats_bus import nats_bus
        bus_stats: Dict[str, Any] = nats_bus.get_stats()
    except Exception as exc:
        bus_stats = {"error": str(exc)}

    adapter_stats: Dict[str, Any] = {}
    if nats is not None:
        try:
            adapter_stats = nats.get_stats()
        except Exception as exc:
            adapter_stats = {"error": str(exc)}

    connected: bool = bus_stats.get("connected", False)
    nats_url: str = os.getenv("GALAXY_NATS_URL", "nats://localhost:4222")
    return {
        "status": "connected" if connected else "disconnected",
        "required": True,
        "nats_url": nats_url,
        "noop_mode": bus_stats.get("noop_mode", True),
        # Bug 4 fix: only return summary counts, not full internal stats
        "bus_summary": {
            "connected": connected,
            "noop_mode": bus_stats.get("noop_mode", True),
        },
        "adapter_summary": {
            "has_error": "error" in adapter_stats,
        },
        "message": (
            "NATS is connected and operating as the internal scheduling mainline."
            if connected else
            "[ERROR] NATS is REQUIRED but not connected to %s. "
            "Start NATS: nats-server -p 4222" % nats_url
        ),
    }


@router.get("/api/v1/health")
async def enhanced_health_check(
    wsm: Any = Depends(get_websocket_manager),
    openclawd: Any = Depends(get_openclawd),
    llm: Any = Depends(get_llm_router_instance),
) -> Dict[str, Any]:
    """Enhanced health check — includes LLM and AI module status.

    Bug 4 fix: returns a lean summary instead of full internal state.
    """
    result: Dict[str, Any] = {
        "status": "healthy",
        "version": "3.0.0",
        "devices_connected": wsm.get_device_count(),
        "ai_modules": {
            "openclawd": "available" if openclawd is not None else "unavailable",
            "llm_router": "available" if llm is not None else "unavailable",
        },
    }
    if llm is not None:
        try:
            status: Dict[str, Any] = llm.get_status()
            # Bug 4 fix: only return summary counts, not full provider details
            result["llm_summary"] = {
                "provider_count": len(status.get("providers", {})),
                "total_calls": status.get("total_calls", 0),
            }
        except Exception:
            pass
    return result


@router.get("/api/v1/gateway/metrics/json")
async def gateway_metrics_json() -> Any:
    """Return gateway pipeline metrics as a JSON snapshot (Round 7)."""
    from galaxy_gateway.observability import get_gateway_metrics
    from starlette.responses import JSONResponse
    return JSONResponse(get_gateway_metrics().snapshot())


@router.get("/api/v1/gateway/metrics")
@router.get("/gateway/metrics")
async def gateway_metrics_prometheus() -> Response:
    """Prometheus text-format exposition for gateway pipeline metrics (Round 7)."""
    from galaxy_gateway.observability import get_gateway_metrics
    return Response(
        content=get_gateway_metrics().prometheus_text(),
        media_type="text/plain; charset=utf-8",
    )
