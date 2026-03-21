#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/routes/capabilities_runtime.py
=====================================

PR-20 (V4) — Capability Runtime State

Read-only API endpoints exposing the capability runtime state layer.

Endpoints
---------
GET /api/v1/capabilities/runtime
    Returns a snapshot of all registered capability runtime summaries.

GET /api/v1/capabilities/runtime/{capability_name}
    Returns the runtime summary for a single named capability.

Design constraints
------------------
- **Read-only** — these endpoints never write state or trigger side-effects.
- **Always available** — the capability_runtime package has no heavy
  dependencies; endpoints return a response even if runtime modules are
  absent or the registry is empty.
- Follows the same structural conventions as ``core/routes/contracts.py``
  and other ``core/routes/`` modules.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.Routes.CapabilitiesRuntime")


def create_router(service_manager=None, config=None) -> APIRouter:  # noqa: ARG001
    """Create and return the capability-runtime router.

    The ``service_manager`` and ``config`` parameters follow the same
    convention used by all other ``core/routes/`` modules.
    """
    router = APIRouter()

    # ------------------------------------------------------------------
    # GET /api/v1/capabilities/runtime
    # ------------------------------------------------------------------

    @router.get("/api/v1/capabilities/runtime")
    async def get_capability_runtime_snapshot() -> JSONResponse:
        """Return a snapshot of all capability runtime summaries.

        This endpoint is **read-only**.  It returns a stable JSON payload
        describing the runtime state (availability posture, constraint flags,
        preferred device ids, reliability notes) for every capability
        registered in the runtime registry.

        Response schema
        ---------------
        ::

            {
              "capabilities": {
                "<capability_name>": {
                  "capability_name": "<name>",
                  "availability": "<available|degraded|unavailable|unknown>",
                  "preferred_device_ids": ["<device_id>", ...],
                  "constraint_flags": ["<flag_name>", ...],
                  "reliability_notes": "<string>",
                  "device_bindings": ["<device_id>", ...],
                  "last_updated": <float>,
                  "metadata": { ... },
                  "schema_version": 1
                },
                ...
              },
              "total_capabilities": <int>,
              "schema_version": 1
            }
        """
        try:
            from core.capability_runtime import get_capability_runtime_snapshot
            payload = get_capability_runtime_snapshot()
            return JSONResponse(content=payload, status_code=200)
        except Exception as exc:  # pragma: no cover
            logger.error("capability_runtime_snapshot endpoint error: %s", exc)
            return JSONResponse(
                content={
                    "error": "capability runtime registry unavailable",
                    "detail": str(exc),
                },
                status_code=503,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/capabilities/runtime/{capability_name}
    # ------------------------------------------------------------------

    @router.get("/api/v1/capabilities/runtime/{capability_name}")
    async def get_single_capability_runtime(capability_name: str) -> JSONResponse:
        """Return the runtime summary for a single named capability.

        Returns ``404`` with a degraded sentinel when the capability has no
        recorded runtime state.

        Response schema
        ---------------
        ::

            {
              "capability_name": "<name>",
              "availability": "<available|degraded|unavailable|unknown>",
              "preferred_device_ids": ["<device_id>", ...],
              "constraint_flags": ["<flag_name>", ...],
              "reliability_notes": "<string>",
              "device_bindings": ["<device_id>", ...],
              "last_updated": <float>,
              "metadata": { ... },
              "schema_version": 1
            }
        """
        try:
            from core.capability_runtime import (
                CapabilityRuntimeRegistry,
                UNKNOWN_CAPABILITY_SUMMARY,
            )
            registry = CapabilityRuntimeRegistry.get_instance()
            summary = registry.get_summary(capability_name)

            if summary.capability_name == "__unknown__":
                return JSONResponse(
                    content={
                        **summary.to_dict(),
                        "capability_name": capability_name,
                        "not_found": True,
                    },
                    status_code=404,
                )
            return JSONResponse(content=summary.to_dict(), status_code=200)
        except Exception as exc:  # pragma: no cover
            logger.error(
                "capability_runtime single endpoint error for '%s': %s",
                capability_name, exc,
            )
            return JSONResponse(
                content={
                    "error": "capability runtime registry unavailable",
                    "detail": str(exc),
                },
                status_code=503,
            )

    return router
