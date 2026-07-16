"""
galaxy_gateway/middleware.py — HTTP middleware for the Galaxy Gateway.

Contains the optional Bearer-token auth middleware used by the gateway's
FastAPI application.  Extracted from ``app.py`` to keep that module as a
thin composition layer.

Middleware execution order (Bug 6 — documented)
================================================
FastAPI middlewares execute in **reverse registration order** (LIFO):

1. CORSMiddleware   (registered first, executes last on request / first on response)
2. BearerAuthMiddleware (executes second)
3. RateLimitMiddleware  (registered last, executes first on request)

This means a request flows through:
    RateLimitMiddleware → BearerAuthMiddleware → CORSMiddleware → handler

And the response flows back through:
    handler → CORSMiddleware → BearerAuthMiddleware → RateLimitMiddleware

Security headers (Bug 8) are added by SecurityHeadersMiddleware which is
registered last so it executes first on the response path, ensuring all
outgoing responses carry the security headers.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (Bug 16 — extracted magic numbers)
# ---------------------------------------------------------------------------
DEFAULT_RATE_LIMIT_MAX_REQUESTS: int = 10
DEFAULT_RATE_LIMIT_WINDOW_SECONDS: int = 60
CLEANUP_INTERVAL_SECONDS: int = 300  # 5 minutes between stale-key cleanups
AUTH_RATE_LIMIT_MAX_REQUESTS: int = 10
AUTH_RATE_LIMIT_WINDOW_SECONDS: int = 60

# Paths that are always public regardless of auth setting
_AUTH_EXEMPT_PATHS: frozenset = frozenset({
    "/health", "/health/live", "/health/ready", "/health/nats",
    "/api/v1/health", "/api/v1/config",
    "/metrics",
    "/docs", "/openapi.json",
})

# ---------------------------------------------------------------------------
# Rate Limiter (in-memory; replaceable with Redis backend)
# ---------------------------------------------------------------------------

class RateLimiter:
    """Simple in-memory sliding-window rate limiter.

    Thread-safe using an ``RLock``.  Each *key* (typically client IP) is
    allowed ``max_requests`` per ``window_seconds``.
    """

    def __init__(self, max_requests: int = DEFAULT_RATE_LIMIT_MAX_REQUESTS, window_seconds: int = DEFAULT_RATE_LIMIT_WINDOW_SECONDS):
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests: Dict[str, List[float]] = {}
        self._lock = threading.RLock()
        self._cleanup_interval = CLEANUP_INTERVAL_SECONDS  # 5 minutes
        self._last_cleanup = time.time()

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            # Periodic cleanup of stale keys to prevent unbounded memory growth
            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup_stale_keys(now)

            # Clean stale entries for the current key
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

    def _cleanup_stale_keys(self, now: float) -> None:
        """Remove keys with all stale entries to prevent memory leak."""
        stale_keys = [
            k for k, timestamps in self._requests.items()
            if not timestamps or all(now - t >= self.window for t in timestamps)
        ]
        for k in stale_keys:
            del self._requests[k]
        self._last_cleanup = now


# Module-level default limiter for auth endpoints
auth_rate_limiter = RateLimiter(max_requests=AUTH_RATE_LIMIT_MAX_REQUESTS, window_seconds=AUTH_RATE_LIMIT_WINDOW_SECONDS)


# ---------------------------------------------------------------------------
# Advanced Rate Limiter — dual limit by IP + target path (Round 4 HIGH fix)
# ---------------------------------------------------------------------------

class AdvancedRateLimiter:
    """Dual rate limiter: per-IP + per-target path.

    Mitigates brute-force attacks by limiting both the total requests from a
    single IP and the requests directed at a specific endpoint (e.g. auth).
    """

    def __init__(
        self,
        ip_limit: int = DEFAULT_RATE_LIMIT_MAX_REQUESTS,
        ip_window: int = DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
        target_limit: int = 5,
        target_window: int = DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
    ):
        self.ip_limit = ip_limit
        self.ip_window = ip_window
        self.target_limit = target_limit
        self.target_window = target_window
        self._ip_requests: Dict[str, List[float]] = defaultdict(list)
        self._target_requests: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.RLock()
        self._cleanup_interval = CLEANUP_INTERVAL_SECONDS  # 5 minutes
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


# ---------------------------------------------------------------------------
# Security Headers Middleware (Bug 8 fix)
# ---------------------------------------------------------------------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all outgoing responses.

    Headers added:
      - X-Content-Type-Options: nosniff
      - X-Frame-Options: DENY
      - X-XSS-Protection: 1; mode=block
      - Referrer-Policy: strict-origin-when-cross-origin
      - Permissions-Policy: geolocation=(), microphone=(), camera=()
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        # Only add to HTTP responses (not WebSocket upgrades)
        if hasattr(response, "headers"):
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


# ---------------------------------------------------------------------------
# Request ID Middleware (Bug 7 fix — use UUID instead of simple counter)
# ---------------------------------------------------------------------------

class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assign a unique request ID (UUID4) to every incoming request.

    The ID is stored in ``request.state.request_id`` and echoed back in the
    ``X-Request-Id`` response header for client-side tracing.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id: str = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = request_id  # type: ignore[attr-defined]
        response = await call_next(request)
        if hasattr(response, "headers"):
            response.headers["X-Request-Id"] = request_id
        return response


# ---------------------------------------------------------------------------
# Bearer Auth Middleware
# ---------------------------------------------------------------------------

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

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
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

        # SECURITY FIX: Reject token passed in URL query parameters.
        # Token must only be provided via Authorization header.
        if "token" in request.query_params:
            logger.warning("Token passed in URL query params — rejected")
            return JSONResponse(
                status_code=403,
                content={"error": "forbidden", "detail": "Token must be in Authorization header, not URL"},
            )

        # Accept token from Authorization header only
        token: Optional[str] = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

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


# ---------------------------------------------------------------------------
# Rate Limit Middleware
# ---------------------------------------------------------------------------

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
        ip_limit: int = DEFAULT_RATE_LIMIT_MAX_REQUESTS,
        ip_window: int = DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
        target_limit: int = 5,
        target_window: int = DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
    ):
        super().__init__(app)
        self.limiter = limiter or AdvancedRateLimiter(
            ip_limit=ip_limit,
            ip_window=ip_window,
            target_limit=target_limit,
            target_window=target_window,
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
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
