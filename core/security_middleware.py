"""
安全增强中间件 (Security Middleware)
====================================

为 FastAPI 应用提供安全增强层，与现有安全节点协作：
- Node_05_Auth: JWT 认证
- Node_03_SecretVault: 密钥管理
- Node_65_LoggerCentral: 审计日志
- Node_68_Security: 访问控制

本模块提供：
1. 审计日志中间件：自动记录所有 API 请求
2. 安全响应头中间件
3. 请求 ID 追踪
4. IP 黑名单
"""

import asyncio
import hashlib
import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Callable, Dict, List, Optional, Set

from dataclasses import dataclass, field

logger = logging.getLogger("UFO-Galaxy.SecurityMiddleware")


# ───────────────────── 审计日志 ─────────────────────

@dataclass
class AuditEntry:
    """审计日志条目"""
    request_id: str
    timestamp: float
    method: str
    path: str
    client_ip: str
    user_agent: str
    status_code: int = 0
    latency_ms: float = 0
    user_id: str = ""
    error: str = ""

    def to_dict(self) -> Dict:
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "method": self.method,
            "path": self.path,
            "client_ip": self.client_ip,
            "status_code": self.status_code,
            "latency_ms": round(self.latency_ms, 2),
            "user_id": self.user_id,
            "error": self.error,
        }


class AuditLogger:
    """
    审计日志记录器

    记录所有 API 请求，支持查询和统计。
    """

    def __init__(self, max_entries: int = 5000):
        self._entries: deque = deque(maxlen=max_entries)
        self._by_path: Dict[str, int] = defaultdict(int)
        self._by_status: Dict[int, int] = defaultdict(int)
        self._by_ip: Dict[str, int] = defaultdict(int)
        self._error_count = 0
        self._total_count = 0

    def record(self, entry: AuditEntry):
        """记录审计日志"""
        self._entries.append(entry)
        self._by_path[entry.path] += 1
        self._by_status[entry.status_code] += 1
        self._by_ip[entry.client_ip] += 1
        self._total_count += 1

        if entry.status_code >= 400:
            self._error_count += 1

        # 对安全敏感操作打日志
        if entry.path in ("/login", "/register", "/change-password", "/api/v1/system/config"):
            logger.info(
                f"[AUDIT] {entry.method} {entry.path} "
                f"from {entry.client_ip} → {entry.status_code} "
                f"({entry.latency_ms:.0f}ms)"
            )

    def get_recent(self, limit: int = 50) -> List[Dict]:
        return [e.to_dict() for e in list(self._entries)[-limit:]]

    def get_stats(self) -> Dict:
        return {
            "total_requests": self._total_count,
            "error_requests": self._error_count,
            "top_paths": dict(sorted(
                self._by_path.items(), key=lambda x: x[1], reverse=True
            )[:10]),
            "status_distribution": dict(self._by_status),
            "top_ips": dict(sorted(
                self._by_ip.items(), key=lambda x: x[1], reverse=True
            )[:10]),
        }

    def get_entries_by_ip(self, ip: str, limit: int = 50) -> List[Dict]:
        return [
            e.to_dict() for e in self._entries
            if e.client_ip == ip
        ][-limit:]


# ───────────────────── IP 黑名单 ─────────────────────

class IPBlockList:
    """IP 黑名单管理"""

    def __init__(self):
        self._blocked: Set[str] = set()
        self._auto_block: Dict[str, List[float]] = defaultdict(list)
        self._threshold = 50       # 1 分钟内的最大失败请求数
        self._window = 60          # 检测窗口（秒）
        self._block_duration = 300  # 自动封禁时长（秒）
        self._auto_blocked: Dict[str, float] = {}  # ip → unblock_time

    def add(self, ip: str):
        """手动加入黑名单"""
        self._blocked.add(ip)
        logger.warning(f"[安全] IP 已加入黑名单: {ip}")

    def remove(self, ip: str):
        """移除黑名单"""
        self._blocked.discard(ip)
        self._auto_blocked.pop(ip, None)

    def is_blocked(self, ip: str) -> bool:
        """检查 IP 是否被封禁"""
        if ip in self._blocked:
            return True

        # 检查自动封禁是否过期
        if ip in self._auto_blocked:
            if time.time() < self._auto_blocked[ip]:
                return True
            else:
                del self._auto_blocked[ip]

        return False

    def record_failure(self, ip: str):
        """记录失败请求"""
        now = time.time()
        self._auto_block[ip].append(now)

        # 清理过期记录
        cutoff = now - self._window
        self._auto_block[ip] = [t for t in self._auto_block[ip] if t > cutoff]

        # 检查是否超过阈值
        if len(self._auto_block[ip]) >= self._threshold:
            self._auto_blocked[ip] = now + self._block_duration
            self._auto_block[ip].clear()
            logger.warning(
                f"[安全] IP 自动封禁 {self._block_duration}s: {ip} "
                f"({self._threshold} 次失败请求/{self._window}s)"
            )

    def get_blocked_list(self) -> Dict:
        now = time.time()
        return {
            "permanent": list(self._blocked),
            "auto_blocked": {
                ip: round(expire - now, 0)
                for ip, expire in self._auto_blocked.items()
                if expire > now
            },
        }


# ───────────────────── 速率限制 ─────────────────────

class RateLimiter:
    """
    令牌桶速率限制器

    对每个客户端IP进行独立的速率限制。
    """

    def __init__(
        self,
        requests_per_minute: int = 120,
        burst_size: int = 30,
    ):
        self._rpm = requests_per_minute
        self._burst = burst_size
        self._buckets: Dict[str, Dict] = {}  # ip -> {tokens, last_refill}
        self._cleanup_interval = 300  # 5分钟清理一次过期桶

    def _get_bucket(self, ip: str) -> Dict:
        now = time.time()
        if ip not in self._buckets:
            self._buckets[ip] = {"tokens": self._burst, "last_refill": now}
        bucket = self._buckets[ip]
        # 补充令牌
        elapsed = now - bucket["last_refill"]
        refill = elapsed * (self._rpm / 60.0)
        bucket["tokens"] = min(self._burst, bucket["tokens"] + refill)
        bucket["last_refill"] = now
        return bucket

    def is_allowed(self, ip: str) -> bool:
        """检查请求是否被允许"""
        bucket = self._get_bucket(ip)
        if bucket["tokens"] >= 1:
            bucket["tokens"] -= 1
            return True
        return False

    def get_remaining(self, ip: str) -> int:
        """获取剩余令牌数"""
        bucket = self._get_bucket(ip)
        return max(0, int(bucket["tokens"]))

    def cleanup(self):
        """清理长时间未使用的桶"""
        now = time.time()
        stale = [
            ip for ip, bucket in self._buckets.items()
            if now - bucket["last_refill"] > self._cleanup_interval
        ]
        for ip in stale:
            del self._buckets[ip]

    def get_stats(self) -> Dict:
        return {
            "active_clients": len(self._buckets),
            "requests_per_minute": self._rpm,
            "burst_size": self._burst,
        }


# ───────────────────── 输入验证 ─────────────────────

class InputValidator:
    """
    请求输入安全验证器

    检测和阻止常见的注入攻击模式。
    """

    # 常见的注入攻击模式
    SQL_INJECTION_PATTERNS = [
        r"(?i)(union\s+select)",
        r"(?i)(;\s*drop\s+table)",
        r"(?i)(--\s*$)",
        r"(?i)('\s*or\s+'1'\s*=\s*'1)",
        r"(?i)(;\s*delete\s+from)",
        r"(?i)(;\s*insert\s+into)",
        r"(?i)(;\s*update\s+.*\s+set)",
    ]

    XSS_PATTERNS = [
        r"<script[^>]*>",
        r"javascript\s*:",
        r"on\w+\s*=\s*[\"']",
        r"<iframe[^>]*>",
        r"<object[^>]*>",
        r"<embed[^>]*>",
    ]

    COMMAND_INJECTION_PATTERNS = [
        r";\s*rm\s+-rf",
        r"\|\|\s*rm\s+",
        r"&&\s*rm\s+",
        r"`[^`]*`",
        r"\$\([^)]+\)",
        r";\s*cat\s+/etc/",
        r";\s*wget\s+",
        r";\s*curl\s+.*\|.*sh",
    ]

    PATH_TRAVERSAL_PATTERNS = [
        r"\.\./",
        r"\.\.\\",
        r"%2e%2e%2f",
        r"%2e%2e/",
    ]

    def __init__(self, strict: bool = False):
        import re
        self._strict = strict
        self._sql_re = [re.compile(p) for p in self.SQL_INJECTION_PATTERNS]
        self._xss_re = [re.compile(p) for p in self.XSS_PATTERNS]
        self._cmd_re = [re.compile(p) for p in self.COMMAND_INJECTION_PATTERNS]
        self._path_re = [re.compile(p) for p in self.PATH_TRAVERSAL_PATTERNS]
        self._violations: deque = deque(maxlen=1000)

    def validate(self, value: str, context: str = "") -> Optional[str]:
        """
        验证输入值，返回 None 表示安全，否则返回威胁类型
        """
        if not isinstance(value, str):
            return None

        for pattern in self._sql_re:
            if pattern.search(value):
                self._record_violation("sql_injection", value, context)
                return "sql_injection"

        for pattern in self._xss_re:
            if pattern.search(value):
                self._record_violation("xss", value, context)
                return "xss"

        for pattern in self._cmd_re:
            if pattern.search(value):
                self._record_violation("command_injection", value, context)
                return "command_injection"

        for pattern in self._path_re:
            if pattern.search(value):
                self._record_violation("path_traversal", value, context)
                return "path_traversal"

        return None

    def validate_dict(self, data: Dict[str, Any], context: str = "") -> Optional[str]:
        """递归验证字典中的所有字符串值"""
        for key, value in data.items():
            if isinstance(value, str):
                threat = self.validate(value, f"{context}.{key}")
                if threat:
                    return threat
            elif isinstance(value, dict):
                threat = self.validate_dict(value, f"{context}.{key}")
                if threat:
                    return threat
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, str):
                        threat = self.validate(item, f"{context}.{key}[{i}]")
                        if threat:
                            return threat
                    elif isinstance(item, dict):
                        threat = self.validate_dict(item, f"{context}.{key}[{i}]")
                        if threat:
                            return threat
        return None

    def _record_violation(self, threat_type: str, value: str, context: str):
        self._violations.append({
            "type": threat_type,
            "value": value[:100],
            "context": context,
            "timestamp": time.time()
        })
        logger.warning(f"[安全] 输入验证检测到 {threat_type}: {context} = {value[:50]}...")

    def get_violations(self, limit: int = 50) -> List[Dict]:
        return list(self._violations)[-limit:]

    def get_stats(self) -> Dict:
        violations_by_type: Dict[str, int] = defaultdict(int)
        for v in self._violations:
            violations_by_type[v["type"]] += 1
        return {
            "total_violations": len(self._violations),
            "by_type": dict(violations_by_type)
        }


# ───────────────────── FastAPI 中间件 ─────────────────────

def create_audit_middleware(app, audit_logger: Optional[AuditLogger] = None):
    """
    创建审计日志中间件

    自动记录所有 HTTP 请求。
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

    if audit_logger is None:
        audit_logger = AuditLogger()

    class AuditMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next) -> Response:
            request_id = str(uuid.uuid4())[:12]
            start_time = time.time()

            # 注入 request_id 到 state
            request.state.request_id = request_id

            client_ip = request.client.host if request.client else "unknown"

            entry = AuditEntry(
                request_id=request_id,
                timestamp=start_time,
                method=request.method,
                path=request.url.path,
                client_ip=client_ip,
                user_agent=request.headers.get("user-agent", "")[:200],
            )

            try:
                response = await call_next(request)
                entry.status_code = response.status_code
                entry.latency_ms = (time.time() - start_time) * 1000

                # 添加 request_id 到响应头
                response.headers["X-Request-ID"] = request_id

                return response
            except Exception as e:
                entry.status_code = 500
                entry.error = str(e)[:200]
                entry.latency_ms = (time.time() - start_time) * 1000
                raise
            finally:
                audit_logger.record(entry)

    app.add_middleware(AuditMiddleware)
    return audit_logger


def create_security_headers_middleware(app):
    """
    创建安全响应头中间件

    添加标准安全响应头。
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next) -> Response:
            response = await call_next(request)

            # 安全头
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"

            # 移除可能泄露信息的头
            if "Server" in response.headers:
                del response.headers["Server"]

            return response

    app.add_middleware(SecurityHeadersMiddleware)


def create_ip_block_middleware(app, block_list: Optional[IPBlockList] = None):
    """
    创建 IP 黑名单中间件
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response

    if block_list is None:
        block_list = IPBlockList()

    class IPBlockMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next) -> Response:
            client_ip = request.client.host if request.client else "unknown"

            if block_list.is_blocked(client_ip):
                logger.warning(f"[安全] 已拦截被封禁 IP: {client_ip}")
                return JSONResponse(
                    status_code=403,
                    content={"error": "access_denied", "message": "IP blocked"},
                )

            response = await call_next(request)

            # 记录失败请求
            if response.status_code >= 400:
                block_list.record_failure(client_ip)

            return response

    app.add_middleware(IPBlockMiddleware)
    return block_list


def create_rate_limit_middleware(app, rate_limiter: Optional[RateLimiter] = None):
    """
    创建速率限制中间件
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response

    if rate_limiter is None:
        rate_limiter = RateLimiter()

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next) -> Response:
            client_ip = request.client.host if request.client else "unknown"

            # 跳过健康检查端点
            if request.url.path in ("/health", "/healthz", "/ready"):
                return await call_next(request)

            if not rate_limiter.is_allowed(client_ip):
                logger.warning(f"[安全] 速率限制触发: {client_ip}")
                return JSONResponse(
                    status_code=429,
                    content={"error": "rate_limited", "message": "Too many requests"},
                    headers={"Retry-After": "60"}
                )

            response = await call_next(request)

            # 添加速率限制头
            remaining = rate_limiter.get_remaining(client_ip)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Limit"] = str(rate_limiter._rpm)

            return response

    app.add_middleware(RateLimitMiddleware)
    return rate_limiter


def create_input_validation_middleware(app, validator: Optional[InputValidator] = None):
    """
    创建输入验证中间件

    检查请求体中的注入攻击模式。
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    import json as json_module

    if validator is None:
        validator = InputValidator()

    class InputValidationMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next) -> Response:
            # 只检查 POST/PUT/PATCH 请求
            if request.method in ("POST", "PUT", "PATCH"):
                content_type = request.headers.get("content-type", "")
                if "application/json" in content_type:
                    try:
                        body = await request.body()
                        if body:
                            data = json_module.loads(body)
                            if isinstance(data, dict):
                                threat = validator.validate_dict(data, request.url.path)
                                if threat:
                                    return JSONResponse(
                                        status_code=400,
                                        content={
                                            "error": "input_validation_failed",
                                            "threat_type": threat,
                                            "message": f"Potential {threat} detected in request"
                                        }
                                    )
                    except (json_module.JSONDecodeError, UnicodeDecodeError):
                        pass  # 让后续处理器处理格式错误

            # 检查查询参数
            for key, value in request.query_params.items():
                threat = validator.validate(value, f"query.{key}")
                if threat:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": "input_validation_failed",
                            "threat_type": threat,
                            "message": f"Potential {threat} detected in query parameter"
                        }
                    )

            return await call_next(request)

    app.add_middleware(InputValidationMiddleware)
    return validator


# ───────────────────── 安全管理器 ─────────────────────

class SecurityManager:
    """
    统一安全管理器

    整合审计日志、IP 黑名单、速率限制和输入验证中间件。
    """

    def __init__(self, config: Optional[Dict] = None):
        config = config or {}
        self.audit = AuditLogger()
        self.ip_block = IPBlockList()
        self.rate_limiter = RateLimiter(
            requests_per_minute=config.get("rate_limit_rpm", 120),
            burst_size=config.get("rate_limit_burst", 30)
        )
        self.input_validator = InputValidator(
            strict=config.get("strict_validation", False)
        )

    def setup_middleware(self, app):
        """为 FastAPI 应用安装所有安全中间件"""
        # 注意：中间件按添加的逆序执行
        # 执行顺序：IP Block → Rate Limit → Input Validation → Security Headers → Audit → Handler

        create_audit_middleware(app, self.audit)
        create_security_headers_middleware(app)
        create_input_validation_middleware(app, self.input_validator)
        create_rate_limit_middleware(app, self.rate_limiter)
        create_ip_block_middleware(app, self.ip_block)

        logger.info("安全中间件已全部安装 (审计日志 + 安全头 + IP黑名单 + 速率限制 + 输入验证)")

    def get_dashboard(self) -> Dict:
        return {
            "audit": self.audit.get_stats(),
            "blocked_ips": self.ip_block.get_blocked_list(),
            "rate_limiter": self.rate_limiter.get_stats(),
            "input_validation": self.input_validator.get_stats(),
        }


# ───────────────────── 单例 ─────────────────────

_instance: Optional[SecurityManager] = None


def get_security_manager() -> SecurityManager:
    global _instance
    if _instance is None:
        _instance = SecurityManager()
    return _instance
