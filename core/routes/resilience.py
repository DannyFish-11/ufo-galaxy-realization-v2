#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy – Resilience Routes (PR-G5)
=====================================

REST endpoints for the resilience / protection layer, consistent with
the G2 observability format.

Routes
------
  GET /api/v1/resilience/metrics       — JSON snapshot (all resilience counters)
  GET /api/v1/resilience/metrics/prom  — Prometheus text exposition
  GET /api/v1/resilience/circuit-breakers — Per-target circuit-breaker states
  POST /api/v1/resilience/circuit-breakers/{target}/reset — Manually reset a CB
"""

import logging

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import JSONResponse, PlainTextResponse

logger = logging.getLogger("Galaxy.API.Resilience")


def create_router() -> APIRouter:
    """Return the resilience API router."""
    router = APIRouter()

    # ── JSON snapshot ─────────────────────────────────────────────────────

    @router.get("/api/v1/resilience/metrics")
    async def resilience_metrics_json():
        """
        Resilience metrics snapshot in JSON format.

        Returns queue depth, rejection rate, fallback activations,
        and circuit-breaker states for all registered targets.
        """
        try:
            from core.resilience.metrics import get_resilience_metrics
            metrics = get_resilience_metrics().snapshot()
        except Exception as exc:
            logger.warning("resilience/metrics error: %s", exc)
            metrics = {}

        router_extra: dict = {}
        try:
            from core.command_router import get_command_router
            cr = get_command_router()
            router_extra = cr.get_resilience_snapshot()
        except Exception as exc:
            logger.warning("resilience/metrics router snapshot error: %s", exc)

        return JSONResponse({
            "resilience_metrics": metrics,
            "router": router_extra,
        })

    # ── Prometheus text exposition ────────────────────────────────────────

    @router.get("/api/v1/resilience/metrics/prom", response_class=PlainTextResponse)
    async def resilience_metrics_prometheus():
        """
        Resilience metrics in Prometheus text exposition format.

        Compatible with the G2 ``/metrics`` endpoint format.
        """
        try:
            from core.resilience.metrics import get_resilience_metrics
            text = get_resilience_metrics().prometheus_text()
        except Exception as exc:
            logger.warning("resilience/metrics/prom error: %s", exc)
            text = "# error generating resilience metrics\n"

        # Append adaptive-semaphore and per-target CB metrics
        try:
            from core.command_router import get_command_router
            cr = get_command_router()
            snap = cr.get_resilience_snapshot()

            as_snap = snap.get("adaptive_semaphore", {})
            if as_snap:
                text += (
                    "# HELP galaxy_adaptive_sem_limit Current adaptive semaphore limit\n"
                    "# TYPE galaxy_adaptive_sem_limit gauge\n"
                    f"galaxy_adaptive_sem_limit {as_snap.get('current_limit', 0)}\n"
                    "# HELP galaxy_adaptive_sem_p99_latency_ms Adaptive semaphore p99 latency\n"
                    "# TYPE galaxy_adaptive_sem_p99_latency_ms gauge\n"
                    f"galaxy_adaptive_sem_p99_latency_ms {as_snap.get('p99_latency_ms', 0)}\n"
                )

            for tgt, cb_snap in snap.get("circuit_breakers", {}).items():
                safe_tgt = tgt.replace("-", "_").replace(".", "_").replace("/", "_")
                state_val = 1 if cb_snap.get("state") == "open" else 0
                text += (
                    f'# HELP galaxy_cb_open{{target="{tgt}"}} 1 if circuit breaker is open\n'
                    f'galaxy_cb_open{{target="{safe_tgt}"}} {state_val}\n'
                    f'galaxy_cb_total_calls{{target="{safe_tgt}"}} {cb_snap.get("total_calls", 0)}\n'
                    f'galaxy_cb_total_fallbacks{{target="{safe_tgt}"}} {cb_snap.get("total_fallbacks", 0)}\n'
                )
        except Exception as exc:
            logger.debug("resilience/metrics/prom CB append error: %s", exc)

        return PlainTextResponse(text, media_type="text/plain; version=0.0.4; charset=utf-8")

    # ── Per-target circuit-breaker states ─────────────────────────────────

    @router.get("/api/v1/resilience/circuit-breakers")
    async def list_circuit_breakers():
        """List all per-target circuit breakers and their current states."""
        try:
            from core.command_router import get_command_router
            cr = get_command_router()
            snap = cr.get_resilience_snapshot()
            return JSONResponse({
                "circuit_breakers": snap.get("circuit_breakers", {}),
                "cb_enabled": snap.get("cb_enabled", False),
            })
        except Exception as exc:
            logger.warning("list_circuit_breakers error: %s", exc)
            return JSONResponse({"circuit_breakers": {}, "cb_enabled": False})

    @router.post("/api/v1/resilience/circuit-breakers/{target}/reset")
    async def reset_circuit_breaker(
        target: str = Path(..., description="Target identifier to reset"),
    ):
        """Manually force a circuit breaker back to CLOSED state."""
        try:
            from core.command_router import get_command_router
            cr = get_command_router()
            cb = cr._circuit_breakers.get(target)
            if cb is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No circuit breaker found for target '{target}'",
                )
            await cb.reset()
            return JSONResponse({"target": target, "state": "closed", "reset": True})
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("reset_circuit_breaker error: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    return router
