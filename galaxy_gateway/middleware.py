"""
galaxy_gateway/middleware.py — HTTP middleware for the Galaxy Gateway.

Contains the optional Bearer-token auth middleware used by the gateway's
FastAPI application.  Extracted from ``app.py`` to keep that module as a
thin composition layer.
"""

import logging
import threading
import time
from collections import defaultdict
from functools import wraps
from typing import Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Paths that are always public regardless of auth setting
_AUTH_EXEMPT_PATHS = {
    "/health", "/health/live", "/health/ready", "/health/nats",
    "/api/v1/health", "/api/v1/config",
    "/metrics",
    "/docs", "/openapi.json",
}


# ============================================================================
# Rate Limiter (in-memory; replaceable with Redis backend)
# ============================================================================

class RateLimiter:
    """Simple in-memory sliding-window rate limiter.

    Thread-safe using an ``RLock``.  Each *key* (typically client IP) is
    allowed ``max_requests`` per ``window_seconds``.
    """

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests: dict = {}
        self._lock = threading.RLock()

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            # Clean stale entries
            if key in self._requests:
                self._requests[key] = [
                    t for t in self._requests[key] if now - t < self.window
                ]
            else:
                self._requests[key] = []

            if len(self._requests[key]) >= self.max_requests:
                return False

            self._requests[key].append(now)
            return True


# Module-level default limiter for auth endpoints
auth_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)


# ============================================================================
# Advanced Rate Limiter — dual limit by IP + target path (Round 4 HIGH fix)
# ============================================================================

class AdvancedRateLimiter:
    """Dual rate limiter: per-IP + per-target path.

    Mitigates brute-force attacks by limiting both the total requests from a
    single IP and the requests directed at a specific endpoint (e.g. auth).
    """

    def __init__(
        self,
        ip_limit: int = 10,
        ip_window: int = 60,
        target_limit: int = 5,
        target_window: int = 60,
    ):
        self.ip_limit = ip_limit
        self.ip_window = ip_window
        self.target_limit = target_limit
        self.target_window = target_window
        self._ip_requests: dict = defaultdict(list)
        self._target_requests: dict = defaultdict(list)
        self._lock = threading.RLock()
        self._cleanup_interval = 300  # 5 minutes
        self._last_cleanup = time.time()

    def is_allowed(self, ip: str, target: str = "default") -> Tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = time.time()

        # Periodic stale-entry cleanup
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup(now)

        with self._lock:
            # IP-level limit
            self._ip_requests[ip] = [
                t for t in self._ip_requests[ip] if now - t < self.ip_window
            ]
            if len(self._ip_requests[ip]) >= self.ip_limit:
                retry_after = int(self.ip_window - (now - self._ip_requests[ip][0]))
                return False, max(retry_after, 1)

            # Target-level limit (stricter — e.g. auth endpoints)
            target_key = f"{ip}:{target}"
            self._target_requests[target_key] = [
                t for t in self._target_requests[target_key]
                if now - t < self.target_window
            ]
            if len(self._target_requests[target_key]) >= self.target_limit:
                retry_after = int(
                    self.target_window - (now - self._target_requests[target_key][0])
                )
                return False, max(retry_after, 1)

            self._ip_requests[ip].append(now)
            self._target_requests[target_key].append(now)
            return True, 0

    def _cleanup(self, now: float) -> None:
        with self._lock:
            for ip in list(self._ip_requests.keys()):
                self._ip_requests[ip] = [
                    t for t in self._ip_requests[ip] if now - t < self.ip_window
                ]
                if not self._ip_requests[ip]:
                    del self._ip_requests[ip]
            for key in list(self._target_requests.keys()):
                self._target_requests[key] = [
                    t for t in self._target_requests[key]
                    if now - t < self.target_window
                ]
                if not self._target_requests[key]:
                    del self._target_requests[key]
            self._last_cleanup = now


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
    The middleware is transparent (no-op) when auth is explicitly disabled
    so that existing clients continue to work without modification.
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
        # PR-HMAC-FIX: compare_digest requires bytes, not str — encode to prevent timing attacks
        try:
            token_bytes = token.encode("ascii")
            for expected in active_tokens:
                if hmac.compare_digest(token_bytes, expected.encode("ascii")):
                    return await call_next(request)
        except UnicodeEncodeError:
            pass  # Reject non-ASCII tokens

        logger.debug("Unauthorized request to %s (invalid token)", request.url.path)
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "detail": "Invalid or missing Bearer token"},
            headers={"WWW-Authenticate": "Bearer"},
        )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate-limiting middleware for the Galaxy Gateway.

    Applies a dual sliding-window rate limit (per-IP + per-target) to all
    state-changing requests under ``/api/``.  Returns HTTP 429 with a
    ``Retry-After`` header when either limit is exceeded.

    The limiter instance can be swapped for a Redis-backed implementation
    without changing this class.
    """

    def __init__(
        self,
        app,
        limiter: Optional[AdvancedRateLimiter] = None,
        ip_limit: int = 10,
        ip_window: int = 60,
        target_limit: int = 5,
        target_window: int = 60,
    ):
        super().__init__(app)
        self.limiter = limiter or AdvancedRateLimiter(
            ip_limit=ip_limit,
            ip_window=ip_window,
            target_limit=target_limit,
            target_window=target_window,
        )

    async def dispatch(self, request: Request, call_next):
        # Round-4 HIGH: rate-limit all state-changing methods, not just POST
        if (
            request.url.path.startswith("/api/")
            and request.method in ("POST", "PUT", "DELETE", "PATCH")
        ):
            client_ip = request.client.host if request.client else "unknown"
            allowed, retry_after = self.limiter.is_allowed(
                client_ip, request.url.path
            )
            if not allowed:
                logger.warning(
                    "Rate limit exceeded for %s on %s", client_ip, request.url.path
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "too_many_requests",
                        "detail": "Too many requests",
                        "retry_after": retry_after,
                    },
                    headers={"Retry-After": str(retry_after)},
                )
        return await call_next(request)
