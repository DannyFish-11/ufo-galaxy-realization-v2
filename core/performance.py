"""
Galaxy - 性能优化层
========================

融合元气 AI Bot 精髓 - 极速响应：

模块内容：
  1. ResponseCompressor  - gzip/br 响应压缩中间件
  2. RateLimiter          - 滑动窗口限流器
  3. CachingMiddleware    - API 响应缓存中间件
  4. RequestTimer         - 请求耗时追踪中间件
  5. PerformanceMonitor   - 性能指标收集器

目标：
  请求 → Redis 缓存 (1ms) → 返回 (<100ms)
"""

import asyncio
import gzip
import hashlib
import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import StreamingResponse
from starlette.types import ASGIApp

logger = logging.getLogger("Galaxy.Performance")


# ============================================================================
# 0. 客户端断开写保护(纯 ASGI,必须位于中间件链最外层)
# ============================================================================


class ClientDisconnectGuardMiddleware:
    """吞掉「客户端提前断开」后的响应写失败——挂在中间件链最外层的纯 ASGI 护栏。

    根因(Windows 真机日志实证):面板保存 API Key 时,Electron 主进程的
    fetchWithRetry 单次尝试 8s 即 abort 断开重试,而后端 POST /api/config 此前
    要同步等 LLM 路由网络探测(>8s)才返回——BaseHTTPMiddleware 链(压缩/缓存/
    计时等)在客户端已断开后仍向 transport 写响应体,winloop 抛
    "RuntimeError: Cannot call write() when UVStream is closing" 连刷 5+ 次,
    还被通用异常处理器记成内部错误制造恐慌。

    此护栏包裹底层 send:仅当异常命中 core.error_framework.
    is_client_disconnect_error() 的【明确断开特征】时静默降级为 debug 日志并
    丢弃后续写入;其余异常原样上抛,不吞真实错误。必须用纯 ASGI 实现(而非
    BaseHTTPMiddleware),否则它自己也会经由 send 写响应、重蹈覆辙。
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client_gone = False

        async def guarded_send(message):
            nonlocal client_gone
            if client_gone:
                return  # transport 已确认关闭,静默丢弃剩余帧,不再触发写异常
            try:
                await send(message)
            except Exception as exc:  # noqa: BLE001 — 仅窄匹配断开特征,其余照抛
                from core.error_framework import is_client_disconnect_error

                if is_client_disconnect_error(exc):
                    client_gone = True
                    logger.debug(
                        "客户端提前断开,丢弃响应写入 (%s %s): %s",
                        scope.get("method"), scope.get("path"), exc,
                    )
                    return
                raise

        try:
            await self.app(scope, receive, guarded_send)
        except Exception as exc:  # noqa: BLE001 — 同上,窄匹配
            from core.error_framework import is_client_disconnect_error

            if is_client_disconnect_error(exc):
                logger.debug(
                    "客户端提前断开,请求提前终止 (%s %s): %s",
                    scope.get("method"), scope.get("path"), exc,
                )
                return
            raise


# ============================================================================
# 1. 响应压缩中间件
# ============================================================================


def _is_streaming_response(response: Response) -> bool:
    """判断是否为流式响应(SSE / StreamingResponse)——这类响应绝不能被读干缓冲。

    两条判据任一命中即算流式:
      1. isinstance StreamingResponse(FastAPI/Starlette 的流式类型);
      2. content-type 以 text/event-stream 开头(SSE)。
    """
    if isinstance(response, StreamingResponse):
        return True
    ctype = response.headers.get("content-type", "")
    return ctype.startswith("text/event-stream")


class ResponseCompressor(BaseHTTPMiddleware):
    """
    gzip 响应压缩中间件

    - 仅压缩 > min_size 字节的 JSON/Text 响应
    - 检查 Accept-Encoding 头
    - 设置 Content-Encoding 和 Vary 头
    """

    def __init__(self, app: ASGIApp, min_size: int = 1024, level: int = 6):
        super().__init__(app)
        self.min_size = min_size
        self.level = level

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        accept_encoding = request.headers.get("accept-encoding", "")
        if "gzip" not in accept_encoding:
            return await call_next(request)

        response = await call_next(request)

        # 【关键】流式响应(SSE)必须原样透传,绝不可读干。
        # content-type "text/event-stream" 会命中下面的 "text/" 判断,若不在此豁免,
        # 下面的 `async for chunk in body_iterator` 会把整条 SSE 流抽干成一个 buffer
        # 再一次性返回 —— 这正是桌面对话"文字整段蹦出、不逐字流"的根因(逐 token 的
        # delta 帧被攒到生成结束才到达前端)。见 core/routes/chat.py 的
        # media_type="text/event-stream"。
        if _is_streaming_response(response):
            return response

        # 仅压缩 JSON 和文本响应
        content_type = response.headers.get("content-type", "")
        if not any(t in content_type for t in ("application/json", "text/")):
            return response

        # 读取响应体
        body = b""
        async for chunk in response.body_iterator:
            if isinstance(chunk, str):
                body += chunk.encode()
            else:
                body += chunk

        if len(body) < self.min_size:
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        compressed = gzip.compress(body, compresslevel=self.level)
        headers = dict(response.headers)
        headers["content-encoding"] = "gzip"
        headers["content-length"] = str(len(compressed))
        headers["vary"] = "Accept-Encoding"

        return Response(
            content=compressed,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )


# ============================================================================
# 2. 滑动窗口限流器
# ============================================================================


class RateLimiter:
    """
    滑动窗口限流器

    支持：
      - 按 IP 限流
      - 按 API Key 限流
      - 自定义窗口大小和最大请求数
      - 突发容量
    """

    def __init__(self, max_requests: int = 100, window_seconds: int = 60, burst: int = 20):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.burst = burst
        self._windows: Dict[str, List[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str) -> Tuple[bool, dict]:
        """
        检查请求是否允许

        Returns:
            (allowed, info) - info 包含 remaining, reset_at 等
        """
        async with self._lock:
            now = time.time()
            window_start = now - self.window_seconds

            # 清理过期记录
            self._windows[key] = [t for t in self._windows[key] if t > window_start]

            current_count = len(self._windows[key])
            remaining = self.max_requests - current_count

            if current_count >= self.max_requests:
                # 检查突发容量
                recent_burst = sum(1 for t in self._windows[key] if t > now - 1)
                if recent_burst >= self.burst:
                    return False, {
                        "remaining": 0,
                        "limit": self.max_requests,
                        "reset_at": window_start + self.window_seconds,
                        "retry_after": int(self.window_seconds - (now - self._windows[key][0])) + 1,
                    }

            self._windows[key].append(now)
            return True, {
                "remaining": max(0, remaining - 1),
                "limit": self.max_requests,
                "reset_at": now + self.window_seconds,
            }

    async def cleanup(self):
        """清理过期数据"""
        async with self._lock:
            now = time.time()
            expired = [k for k, v in self._windows.items() if not v or v[-1] < now - self.window_seconds * 2]
            for k in expired:
                del self._windows[k]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """限流中间件"""

    def __init__(self, app: ASGIApp, max_requests: int = 200, window_seconds: int = 60):
        super().__init__(app)
        self.limiter = RateLimiter(max_requests=max_requests, window_seconds=window_seconds)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # WebSocket 不限流
        if request.url.path.startswith("/ws"):
            return await call_next(request)

        # 健康检查不限流
        if request.url.path in ("/api/v1/system/health", "/health"):
            return await call_next(request)

        # 获取限流 key（优先 API Key，其次 IP）
        api_key = request.headers.get("x-api-key", "")
        client_ip = request.client.host if request.client else "unknown"

        # 关键修复:本机可信单用户桌面应用(Electron 主进程 + 渲染层 + 面板轮询 +
        # WS + 桌面连续感知帧)全部从 127.0.0.1 打向同一个本地后端、且不带
        # x-api-key，按 IP 分桶会把它们全算作同一个客户端共用一个配额——面板
        # 自身的轮询/感知流量足以把配额提前耗尽，导致用户偶发交互(如保存配置)
        # 被无差别 429，跟同类问题(core/security_middleware.py 的另一个限流层)
        # 是同一根因，一并修。默认放行回环地址；
        # GALAXY_RATE_LIMIT_LOOPBACK=1 可强制限流(如需测试限流本身)。
        if not api_key and client_ip in ("127.0.0.1", "::1", "localhost"):
            if os.environ.get("GALAXY_RATE_LIMIT_LOOPBACK", "0").strip().lower() not in ("1", "true", "yes", "on"):
                return await call_next(request)

        rate_key = f"apikey:{api_key}" if api_key else f"ip:{client_ip}"

        allowed, info = await self.limiter.is_allowed(rate_key)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "retry_after": info.get("retry_after", 60),
                },
                headers={
                    "Retry-After": str(info.get("retry_after", 60)),
                    "X-RateLimit-Limit": str(info["limit"]),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(info["limit"])
        response.headers["X-RateLimit-Remaining"] = str(info["remaining"])
        return response


# ============================================================================
# 3. API 响应缓存中间件
# ============================================================================


class CachingMiddleware(BaseHTTPMiddleware):
    """
    API 响应缓存中间件

    - 仅缓存 GET 请求
    - 基于 URL + Query 生成缓存 key
    - 支持 Cache-Control 头
    - 自动失效
    """

    def __init__(self, app: ASGIApp, cache_backend=None, default_ttl: int = 30):
        super().__init__(app)
        self._cache = cache_backend
        self.default_ttl = default_ttl
        # 可缓存的路径前缀
        self._cacheable = {
            "/api/v1/system/status": 10,
            "/api/v1/devices": 15,
            "/api/v1/nodes": 60,
            "/api/v1/tasks": 5,
        }

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._cache or request.method != "GET":
            return await call_next(request)

        # 检查是否可缓存
        path = request.url.path
        ttl = None
        for prefix, cache_ttl in self._cacheable.items():
            if path.startswith(prefix):
                ttl = cache_ttl
                break

        if ttl is None:
            return await call_next(request)

        # 检查 no-cache
        cache_control = request.headers.get("cache-control", "")
        if "no-cache" in cache_control:
            return await call_next(request)

        # 生成缓存 key
        cache_key = f"http_cache:{hashlib.md5(str(request.url).encode()).hexdigest()}"

        # 尝试缓存命中
        try:
            cached = await self._cache.get(cache_key)
            if cached:
                data = json.loads(cached)
                headers = data.get("headers", {})
                headers["X-Cache"] = "HIT"
                return Response(
                    content=data["body"].encode() if isinstance(data["body"], str) else data["body"],
                    status_code=data.get("status", 200),
                    headers=headers,
                    media_type=data.get("media_type", "application/json"),
                )
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

        # 缓存未命中，执行请求
        response = await call_next(request)

        # 流式响应(SSE)绝不缓存 —— 读干 body_iterator 会破坏流式(防御性:当前只
        # GET 且白名单路径无 SSE,但白名单一旦扩展就可能踩到,提前豁免)。
        if _is_streaming_response(response):
            return response

        # 仅缓存成功响应
        if 200 <= response.status_code < 300:
            body = b""
            async for chunk in response.body_iterator:
                if isinstance(chunk, str):
                    body += chunk.encode()
                else:
                    body += chunk

            # 写入缓存
            try:
                cache_data = json.dumps(
                    {
                        "body": body.decode("utf-8", errors="replace"),
                        "status": response.status_code,
                        "headers": dict(response.headers),
                        "media_type": response.media_type,
                    }
                )
                await self._cache.set(cache_key, cache_data, ttl)
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

            headers = dict(response.headers)
            headers["X-Cache"] = "MISS"
            return Response(
                content=body,
                status_code=response.status_code,
                headers=headers,
                media_type=response.media_type,
            )

        return response


# ============================================================================
# 4. 请求耗时追踪中间件
# ============================================================================


class RequestTimerMiddleware(BaseHTTPMiddleware):
    """请求耗时追踪 - 在响应头中添加 X-Response-Time"""

    def __init__(self, app: ASGIApp, slow_threshold_ms: float = 500):
        super().__init__(app)
        self.slow_threshold_ms = slow_threshold_ms
        self.monitor = PerformanceMonitor.instance()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.time()
        response = await call_next(request)
        elapsed_ms = (time.time() - start) * 1000

        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"

        # 记录指标
        self.monitor.record_request(
            path=request.url.path,
            method=request.method,
            status=response.status_code,
            latency_ms=elapsed_ms,
        )

        # 慢请求告警
        if elapsed_ms > self.slow_threshold_ms:
            logger.warning(
                f"Slow request: {request.method} {request.url.path} "
                f"took {elapsed_ms:.0f}ms (threshold: {self.slow_threshold_ms}ms)"
            )

        return response


# ============================================================================
# 5. 性能指标收集器
# ============================================================================


@dataclass
class EndpointMetrics:
    """单个端点的指标"""

    total_requests: int = 0
    total_errors: int = 0
    latencies: List[float] = field(default_factory=list)
    status_codes: Dict[int, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def avg_latency(self) -> float:
        return sum(self.latencies) / len(self.latencies) if self.latencies else 0

    @property
    def p50_latency(self) -> float:
        if not self.latencies:
            return 0
        s = sorted(self.latencies)
        return s[len(s) // 2]

    @property
    def p99_latency(self) -> float:
        if not self.latencies:
            return 0
        s = sorted(self.latencies)
        idx = int(len(s) * 0.99)
        return s[min(idx, len(s) - 1)]

    def to_dict(self) -> dict:
        return {
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "error_rate": self.total_errors / max(self.total_requests, 1),
            "avg_latency_ms": round(self.avg_latency, 2),
            "p50_latency_ms": round(self.p50_latency, 2),
            "p99_latency_ms": round(self.p99_latency, 2),
        }


class PerformanceMonitor:
    """
    性能指标收集器 (Singleton)

    收集：
      - 每个端点的请求数、错误率、延迟分布
      - 系统整体 QPS、P50/P99
      - 缓存命中率
    """

    _instance = None

    @classmethod
    def instance(cls) -> "PerformanceMonitor":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._endpoints: Dict[str, EndpointMetrics] = defaultdict(EndpointMetrics)
        self._global = EndpointMetrics()
        self._start_time = time.time()
        self._max_latencies = 5000  # 保留最近 N 条延迟记录

    def record_request(self, path: str, method: str, status: int, latency_ms: float):
        """记录请求指标"""
        key = f"{method} {path}"
        ep = self._endpoints[key]
        ep.total_requests += 1
        ep.status_codes[status] += 1
        ep.latencies.append(latency_ms)
        if len(ep.latencies) > self._max_latencies:
            ep.latencies = ep.latencies[-self._max_latencies // 2 :]

        if status >= 400:
            ep.total_errors += 1

        # 全局统计
        self._global.total_requests += 1
        self._global.latencies.append(latency_ms)
        if len(self._global.latencies) > self._max_latencies:
            self._global.latencies = self._global.latencies[-self._max_latencies // 2 :]
        if status >= 400:
            self._global.total_errors += 1

    def get_dashboard(self) -> dict:
        """获取性能仪表盘数据"""
        uptime = time.time() - self._start_time
        qps = self._global.total_requests / max(uptime, 1)

        return {
            "uptime_seconds": round(uptime, 0),
            "global": {
                **self._global.to_dict(),
                "qps": round(qps, 2),
            },
            "endpoints": {
                k: v.to_dict()
                for k, v in sorted(
                    self._endpoints.items(),
                    key=lambda x: x[1].total_requests,
                    reverse=True,
                )[:20]
            },
        }

    def reset(self):
        """重置所有指标"""
        self._endpoints.clear()
        self._global = EndpointMetrics()
        self._start_time = time.time()
