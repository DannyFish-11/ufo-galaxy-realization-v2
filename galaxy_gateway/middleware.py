"""
galaxy_gateway/middleware.py — HTTP middleware for the Galaxy Gateway.

Contains the optional Bearer-token auth middleware used by the gateway's
FastAPI application.  Extracted from ``app.py`` to keep that module as a
thin composition layer.
"""

import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Paths that are always public regardless of auth setting
_AUTH_EXEMPT_PATHS = {"/health", "/api/v1/health", "/api/v1/config"}


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """
    Optional Bearer token middleware for the Galaxy Gateway.

    Enabled when ``GALAXY_AUTH_ENABLED=true`` and ``GALAXY_API_TOKEN`` is set.
    All HTTP requests (REST and the WebSocket upgrade handshake) that carry a
    path not in the exempt list must include::

        Authorization: Bearer <token>

    Alternatively WebSocket clients may pass the token as a query parameter::

        /ws/device/my_device?token=<token>

    Rejected requests receive HTTP 401 with a JSON error payload.
    The middleware is transparent (no-op) when auth is disabled so that
    existing clients continue to work without modification.
    """

    async def dispatch(self, request: Request, call_next):
        from core.auth import is_auth_enabled, get_active_tokens
        import hmac

        if not is_auth_enabled():
            return await call_next(request)

        # Health probes are always public
        if request.url.path in _AUTH_EXEMPT_PATHS:
            return await call_next(request)

        active_tokens = get_active_tokens()
        if not active_tokens:
            # Auth enabled but no active tokens configured — fail safe
            logger.error(
                "GALAXY_AUTH_ENABLED=true but no active API tokens are configured; "
                "rejecting request to %s", request.url.path
            )
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "detail": "Server auth token not configured"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Accept token from Authorization header or ?token= query param (for WS)
        token: Optional[str] = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
        if not token:
            token = request.query_params.get("token", "").strip() or None

        if not token:
            logger.debug("Unauthorized request to %s (missing token)", request.url.path)
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "detail": "Invalid or missing Bearer token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Accept if token matches any active key (constant-time comparison for each)
        for expected in active_tokens:
            if hmac.compare_digest(token, expected):
                return await call_next(request)

        logger.debug("Unauthorized request to %s (invalid token)", request.url.path)
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "detail": "Invalid or missing Bearer token"},
            headers={"WWW-Authenticate": "Bearer"},
        )
