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

logger = logging.getLogger("Galaxy.SecurityMiddleware")


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
            response.headers.pop("Server", None)

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


# ───────────────────── 安全管理器 ─────────────────────

class SecurityManager:
    """
    统一安全管理器

    整合审计日志、IP 黑名单和安全中间件。
    """

    def __init__(self):
        self.audit = AuditLogger()
        self.ip_block = IPBlockList()

    def setup_middleware(self, app):
        """为 FastAPI 应用安装所有安全中间件"""
        # 注意：中间件按添加的逆序执行
        # 执行顺序：IP Block → Security Headers → Audit → Handler

        create_audit_middleware(app, self.audit)
        create_security_headers_middleware(app)
        create_ip_block_middleware(app, self.ip_block)

        logger.info("安全中间件已全部安装 (审计日志 + 安全头 + IP 黑名单)")

    def get_dashboard(self) -> Dict:
        return {
            "audit": self.audit.get_stats(),
            "blocked_ips": self.ip_block.get_blocked_list(),
        }


# ───────────────────── 单例 ─────────────────────

_instance: Optional[SecurityManager] = None


def get_security_manager() -> SecurityManager:
    global _instance
    if _instance is None:
        _instance = SecurityManager()
    return _instance
