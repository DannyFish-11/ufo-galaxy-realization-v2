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
from typing import Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 鉴权豁免表（B1 / B6 修复）
# ---------------------------------------------------------------------------
#
# 此前是一个纯路径集合，有两个问题：
#
#   1. **不分方法**。``/api/v1/config`` 一旦进表，该路径下的 GET 与 POST 一起
#      被豁免 —— 读配置和写配置拿到同一个待遇。豁免读是合理的（面板角标要在
#      未登录时也能显示"已配置/未配置"），豁免写不是。
#   2. **生产下过宽**。``/metrics`` 暴露内部拓扑、设备数、任务量；
#      ``/docs`` + ``/openapi.json`` 把完整 API 面交给未认证方。开发期方便，
#      生产期是信息泄漏。
#
# 现在：豁免以 (路径 → 允许的方法集合) 表达，且分成「始终豁免」与
# 「仅非生产豁免」两张表。
#
# 注意：这里收紧的是**中间件层**。写端点自身还应有 ``Depends(require_auth)``
# 作为第二道（见 core/routes/perception.py），不要把中间件当唯一防线 ——
# ``is_auth_enabled()`` 默认为 False，中间件在默认部署下整个是 no-op。

# 只读探针：任何模式下都公开。值为允许的 HTTP 方法集合。
_AUTH_EXEMPT: dict = {
    "/health": {"GET", "HEAD"},
    "/health/live": {"GET", "HEAD"},
    "/health/ready": {"GET", "HEAD"},
    "/health/nats": {"GET", "HEAD"},
    "/api/v1/health": {"GET", "HEAD"},
    # 面板角标读端点：只豁免 GET。同路径的 POST（写配置）必须过鉴权。
    "/api/v1/config": {"GET", "HEAD"},
}

# 仅在非生产模式豁免；GALAXY_MODE=production 下一律要鉴权。
_AUTH_EXEMPT_NON_PRODUCTION: dict = {
    "/metrics": {"GET", "HEAD"},
    "/docs": {"GET", "HEAD"},
    "/openapi.json": {"GET", "HEAD"},
}


def _is_exempt(path: str, method: str) -> bool:
    """返回 ``(path, method)`` 是否属于鉴权豁免。"""
    import os

    method = (method or "").upper()
    allowed = _AUTH_EXEMPT.get(path)
    if allowed and method in allowed:
        return True
    if os.environ.get("GALAXY_MODE", "").strip().lower() != "production":
        allowed = _AUTH_EXEMPT_NON_PRODUCTION.get(path)
        if allowed and method in allowed:
            return True
    return False


# 兼容别名：外部（测试/文档）曾直接引用这个名字读取豁免路径集合。
# 保留为路径视图，但**不要**再用它做鉴权判定 —— 判定请走 _is_exempt()。
_AUTH_EXEMPT_PATHS = frozenset(_AUTH_EXEMPT) | frozenset(_AUTH_EXEMPT_NON_PRODUCTION)


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
                self._requests[key] = [t for t in self._requests[key] if now - t < self.window]
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
            self._ip_requests[ip] = [t for t in self._ip_requests[ip] if now - t < self.ip_window]
            if len(self._ip_requests[ip]) >= self.ip_limit:
                retry_after = int(self.ip_window - (now - self._ip_requests[ip][0]))
                return False, max(retry_after, 1)

            # Target-level limit (stricter — e.g. auth endpoints)
            target_key = f"{ip}:{target}"
            self._target_requests[target_key] = [
                t for t in self._target_requests[target_key] if now - t < self.target_window
            ]
            if len(self._target_requests[target_key]) >= self.target_limit:
                retry_after = int(self.target_window - (now - self._target_requests[target_key][0]))
                return False, max(retry_after, 1)

            self._ip_requests[ip].append(now)
            self._target_requests[target_key].append(now)
            return True, 0

    def _cleanup(self, now: float) -> None:
        with self._lock:
            for ip in list(self._ip_requests.keys()):
                self._ip_requests[ip] = [t for t in self._ip_requests[ip] if now - t < self.ip_window]
                if not self._ip_requests[ip]:
                    del self._ip_requests[ip]
            for key in list(self._target_requests.keys()):
                self._target_requests[key] = [t for t in self._target_requests[key] if now - t < self.target_window]
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
        import hmac

        from core.auth import get_active_tokens, is_auth_enabled

        if not is_auth_enabled():
            return await call_next(request)

        # 只读探针公开；写方法一律不豁免（B1/B6）
        if _is_exempt(request.url.path, request.method):
            return await call_next(request)

        active_tokens = get_active_tokens()
        if not active_tokens:
            # Auth enabled but no active tokens configured — fail safe
            logger.error(
                "GALAXY_AUTH_ENABLED=true but no active API tokens are configured; " "rejecting request to %s",
                request.url.path,
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
        if request.url.path.startswith("/api/") and request.method in ("POST", "PUT", "DELETE", "PATCH"):
            client_ip = request.client.host if request.client else "unknown"
            allowed, retry_after = self.limiter.is_allowed(client_ip, request.url.path)
            if not allowed:
                logger.warning("Rate limit exceeded for %s on %s", client_ip, request.url.path)
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
