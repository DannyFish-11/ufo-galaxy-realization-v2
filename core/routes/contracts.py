"""
core/routes/contracts.py
=========================
Read-only API endpoints exposing the cross-plane contract map.

Endpoints
---------
GET /api/v1/contracts/planes
    Returns all planes and the message-kind names they contain.

GET /api/v1/contracts/messages
    Returns full descriptors for all registered contracts.

Design constraints
------------------
- **Read-only** — these endpoints never write state or trigger side-effects.
- **Always available** — the contract-map package has no heavy dependencies;
  endpoints return a response even if optional runtime modules are absent.
- **No auth required** — contract metadata is non-sensitive architectural
  information, consistent with other diagnostic/observability endpoints.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.Routes.Contracts")


def create_router(service_manager=None, config=None) -> APIRouter:  # noqa: ARG001
    """Create and return the contracts router.

    The ``service_manager`` and ``config`` parameters follow the same
    convention used by all other ``core/routes/`` modules.
    """
    router = APIRouter()

    # ------------------------------------------------------------------
    # GET /api/v1/contracts/planes
    # ------------------------------------------------------------------

    @router.get("/api/v1/contracts/planes")
    async def get_contract_planes() -> JSONResponse:
        """Return the cross-plane contract map — planes summary.

        This endpoint is **read-only**.  It returns a stable JSON payload
        describing all recognised message planes and the contract kinds
        that belong to each plane.

        Response schema
        ---------------
        ::

            {
              "planes": {
                "<plane_name>": {
                  "description": "<human-readable description>",
                  "message_kinds": ["<kind_1>", "<kind_2>", ...]
                },
                ...
              },
              "total_planes": <int>,
              "total_contracts": <int>
            }
        """
        try:
            from core.contract_map import get_planes_snapshot
            payload = get_planes_snapshot()
            return JSONResponse(content=payload, status_code=200)
        except Exception as exc:  # pragma: no cover
            logger.error("contract_planes endpoint error: %s", exc)
            return JSONResponse(
                content={"error": "contract map unavailable", "detail": str(exc)},
                status_code=503,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/contracts/messages
    # ------------------------------------------------------------------

    @router.get("/api/v1/contracts/messages")
    async def get_contract_messages() -> JSONResponse:
        """Return the cross-plane contract map — full message descriptors.

        This endpoint is **read-only**.  It returns a stable JSON payload
        with full descriptor metadata for every registered contract kind.

        Response schema
        ---------------
        ::

            {
              "contracts": {
                "<kind_name>": {
                  "plane": "<plane_name>",
                  "kind": "<kind_name>",
                  "canonical_type": "<dotted.python.Type | null>",
                  "source_module": "<dotted.python.module | null>",
                  "identity_fields": ["field1", ...],
                  "producer_modules": ["module1", ...],
                  "consumer_modules": ["module1", ...],
                  "notes": "<string | null>"
                },
                ...
              },
              "total_contracts": <int>
            }
        """
        try:
            from core.contract_map import get_messages_snapshot
            payload = get_messages_snapshot()
            return JSONResponse(content=payload, status_code=200)
        except Exception as exc:  # pragma: no cover
            logger.error("contract_messages endpoint error: %s", exc)
            return JSONResponse(
                content={"error": "contract map unavailable", "detail": str(exc)},
                status_code=503,
            )

    return router
