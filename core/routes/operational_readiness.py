"""
core/routes/operational_readiness.py
====================================
Read-only operational readiness and clone-to-use acceptance routes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.operational_readiness_surface import (
    OPERATIONAL_READINESS_SURFACE_AUTHORITY,
    build_operational_readiness_report,
    collect_app_route_paths,
)

logger = logging.getLogger("Galaxy.Routes.OperationalReadiness")


def create_router(service_manager=None, config=None) -> APIRouter:  # noqa: ARG001
    """Create the read-only operational readiness router.

    ``service_manager`` and ``config`` are intentionally accepted for parity
    with the other ``core/routes`` factories, even though this surface is
    projection-only and does not currently consume them.
    """
    router = APIRouter()

    @router.get("/api/v1/projection/operational-readiness")
    async def get_operational_readiness(request: Request) -> JSONResponse:
        route_paths = collect_app_route_paths(request.app)
        report = build_operational_readiness_report(route_paths=route_paths)
        payload = report.to_dict()
        payload["route_surface_authority"] = OPERATIONAL_READINESS_SURFACE_AUTHORITY
        return JSONResponse(content=payload)

    @router.get("/api/v1/projection/clone-to-use-acceptance")
    async def get_clone_to_use_acceptance(request: Request) -> JSONResponse:
        route_paths = collect_app_route_paths(request.app)
        report = build_operational_readiness_report(route_paths=route_paths)
        payload = {
            "authority": OPERATIONAL_READINESS_SURFACE_AUTHORITY,
            "contract_version": report.contract_version,
            "validation": report.validation,
            "chain_state": report.chain_state.to_dict(),
            "clone_to_use_acceptance": report.clone_to_use_acceptance,
            "android_v2_minimum_standard": report.android_v2_minimum_standard,
            "state_contract": report.state_contract,
        }
        return JSONResponse(content=payload)

    return router
