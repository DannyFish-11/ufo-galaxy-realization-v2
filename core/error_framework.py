"""
统一错误处理框架 (Unified Error Framework)
==========================================

提供：
- 统一的错误类型层级
- 错误分类和严重性
- 自动恢复策略
- 错误上下文追踪
- 与 FastAPI 集成的错误响应
"""

import logging
import time
import traceback
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque
from functools import wraps

logger = logging.getLogger("UFO-Galaxy.ErrorFramework")


# ───────────────────── 错误分类 ─────────────────────

class ErrorSeverity(Enum):
    """错误严重性"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    FATAL = "fatal"


class ErrorCategory(Enum):
    """错误类别"""
    NETWORK = "network"           # 网络通信错误
    DEVICE = "device"             # 设备交互错误
    LLM = "llm"                   # LLM 调用错误
    AUTH = "auth"                 # 认证/授权错误
    CONFIG = "config"             # 配置错误
    RESOURCE = "resource"         # 资源不足/不可用
    CONCURRENCY = "concurrency"   # 并发/锁错误
    DATA = "data"                 # 数据格式/验证错误
    TIMEOUT = "timeout"           # 超时
    NODE = "node"                 # 节点错误
    INTERNAL = "internal"         # 内部逻辑错误
    EXTERNAL = "external"         # 外部服务错误


class RecoveryStrategy(Enum):
    """恢复策略"""
    RETRY = "retry"               # 重试
    FAILOVER = "failover"         # 故障转移
    DEGRADE = "degrade"           # 降级
    SKIP = "skip"                 # 跳过
    ABORT = "abort"               # 中止
    MANUAL = "manual"             # 需人工介入


# ───────────────────── 错误类型层级 ─────────────────────

class UFOError(Exception):
    """UFO Galaxy 错误基类"""

    def __init__(self, message: str, category: ErrorCategory = ErrorCategory.INTERNAL,
                 severity: ErrorSeverity = ErrorSeverity.ERROR,
                 recovery: RecoveryStrategy = RecoveryStrategy.ABORT,
                 context: Optional[Dict] = None,
                 cause: Optional[Exception] = None):
        super().__init__(message)
        self.message = message
        self.category = category
        self.severity = severity
        self.recovery = recovery
        self.context = context or {}
        self.cause = cause
        self.timestamp = time.time()
        self.error_id = f"err_{int(self.timestamp * 1000)}"
        self.traceback_str = traceback.format_exc() if cause else ""

    def to_dict(self) -> Dict:
        return {
            "error_id": self.error_id,
            "message": self.message,
            "category": self.category.value,
            "severity": self.severity.value,
            "recovery": self.recovery.value,
            "context": self.context,
            "timestamp": self.timestamp,
            "cause": str(self.cause) if self.cause else None,
        }


class NetworkError(UFOError):
    """网络错误"""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, category=ErrorCategory.NETWORK,
                         recovery=RecoveryStrategy.RETRY, **kwargs)


class DeviceError(UFOError):
    """设备错误"""
    def __init__(self, message: str, device_id: str = "", **kwargs):
        ctx = kwargs.pop("context", {})
        ctx["device_id"] = device_id
        super().__init__(message, category=ErrorCategory.DEVICE,
                         recovery=RecoveryStrategy.FAILOVER, context=ctx, **kwargs)


class LLMError(UFOError):
    """LLM 调用错误"""
    def __init__(self, message: str, provider: str = "", model: str = "", **kwargs):
        ctx = kwargs.pop("context", {})
        ctx.update({"provider": provider, "model": model})
        super().__init__(message, category=ErrorCategory.LLM,
                         recovery=RecoveryStrategy.FAILOVER, context=ctx, **kwargs)


class AuthError(UFOError):
    """认证/授权错误"""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, category=ErrorCategory.AUTH,
                         severity=ErrorSeverity.WARNING,
                         recovery=RecoveryStrategy.ABORT, **kwargs)


class ConfigError(UFOError):
    """配置错误"""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, category=ErrorCategory.CONFIG,
                         severity=ErrorSeverity.CRITICAL,
                         recovery=RecoveryStrategy.MANUAL, **kwargs)


class ResourceError(UFOError):
    """资源错误"""
    def __init__(self, message: str, resource: str = "", **kwargs):
        ctx = kwargs.pop("context", {})
        ctx["resource"] = resource
        super().__init__(message, category=ErrorCategory.RESOURCE,
                         recovery=RecoveryStrategy.DEGRADE, context=ctx, **kwargs)


class TimeoutError_(UFOError):
    """超时错误 (名称避免与内置 TimeoutError 冲突)"""
    def __init__(self, message: str, timeout_seconds: float = 0, **kwargs):
        ctx = kwargs.pop("context", {})
        ctx["timeout_seconds"] = timeout_seconds
        super().__init__(message, category=ErrorCategory.TIMEOUT,
                         recovery=RecoveryStrategy.RETRY, context=ctx, **kwargs)


class NodeError(UFOError):
    """节点错误"""
    def __init__(self, message: str, node_id: str = "", **kwargs):
        ctx = kwargs.pop("context", {})
        ctx["node_id"] = node_id
        super().__init__(message, category=ErrorCategory.NODE,
                         recovery=RecoveryStrategy.FAILOVER, context=ctx, **kwargs)


class DataError(UFOError):
    """数据错误"""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, category=ErrorCategory.DATA,
                         severity=ErrorSeverity.WARNING,
                         recovery=RecoveryStrategy.SKIP, **kwargs)


class ConcurrencyError(UFOError):
    """并发错误"""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, category=ErrorCategory.CONCURRENCY,
                         recovery=RecoveryStrategy.RETRY, **kwargs)


# ───────────────────── 错误记录器 ─────────────────────

@dataclass
class ErrorRecord:
    """错误记录"""
    error: UFOError
    handled: bool = False
    recovered: bool = False
    recovery_action: str = ""


class ErrorTracker:
    """
    错误追踪器

    记录所有错误，提供统计和分析。
    """

    def __init__(self, max_records: int = 1000):
        self._records: deque = deque(maxlen=max_records)
        self._by_category: Dict[str, int] = defaultdict(int)
        self._by_severity: Dict[str, int] = defaultdict(int)
        self._recent_errors: Dict[str, List[float]] = defaultdict(list)  # category → timestamps
        self._handlers: Dict[ErrorCategory, List[Callable]] = defaultdict(list)

    def record(self, error: UFOError, handled: bool = False,
               recovered: bool = False, recovery_action: str = ""):
        """记录错误"""
        record = ErrorRecord(
            error=error, handled=handled,
            recovered=recovered, recovery_action=recovery_action,
        )
        self._records.append(record)
        self._by_category[error.category.value] += 1
        self._by_severity[error.severity.value] += 1
        self._recent_errors[error.category.value].append(error.timestamp)

        # 根据严重性记录日志
        log_method = {
            ErrorSeverity.DEBUG: logger.debug,
            ErrorSeverity.INFO: logger.info,
            ErrorSeverity.WARNING: logger.warning,
            ErrorSeverity.ERROR: logger.error,
            ErrorSeverity.CRITICAL: logger.critical,
            ErrorSeverity.FATAL: logger.critical,
        }.get(error.severity, logger.error)

        log_method(
            f"[{error.category.value}] {error.message} "
            f"(recovery={error.recovery.value}, id={error.error_id})"
        )

        # 通知处理器
        for handler in self._handlers.get(error.category, []):
            try:
                handler(error)
            except Exception:
                pass

    def register_handler(self, category: ErrorCategory, handler: Callable):
        """注册错误处理回调"""
        self._handlers[category].append(handler)

    def get_error_rate(self, category: Optional[str] = None,
                       window_seconds: int = 60) -> float:
        """获取最近 N 秒的错误率"""
        now = time.time()
        cutoff = now - window_seconds

        if category:
            timestamps = self._recent_errors.get(category, [])
            count = sum(1 for t in timestamps if t > cutoff)
        else:
            count = sum(
                sum(1 for t in ts if t > cutoff)
                for ts in self._recent_errors.values()
            )

        return count / window_seconds if window_seconds > 0 else 0

    def is_error_spike(self, category: str, threshold: float = 0.5,
                       window: int = 60) -> bool:
        """检测是否有错误峰值"""
        return self.get_error_rate(category, window) > threshold

    def get_summary(self) -> Dict:
        return {
            "total_errors": len(self._records),
            "by_category": dict(self._by_category),
            "by_severity": dict(self._by_severity),
            "error_rate_1m": round(self.get_error_rate(window_seconds=60), 3),
            "error_rate_5m": round(self.get_error_rate(window_seconds=300), 3),
            "recent_errors": [
                r.error.to_dict() for r in list(self._records)[-10:]
            ],
        }


# ───────────────────── 装饰器 ─────────────────────

def error_boundary(category: ErrorCategory = ErrorCategory.INTERNAL,
                   recovery: RecoveryStrategy = RecoveryStrategy.ABORT,
                   default_return=None):
    """
    错误边界装饰器

    将未处理的异常包装为 UFOError 并记录。
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except UFOError:
                raise  # 已经是 UFOError，直接抛出
            except Exception as e:
                ufo_err = UFOError(
                    message=f"{func.__name__} 执行失败: {e}",
                    category=category,
                    recovery=recovery,
                    cause=e,
                )
                _global_tracker.record(ufo_err)
                if recovery == RecoveryStrategy.ABORT:
                    raise ufo_err from e
                return default_return

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except UFOError:
                raise
            except Exception as e:
                ufo_err = UFOError(
                    message=f"{func.__name__} 执行失败: {e}",
                    category=category,
                    recovery=recovery,
                    cause=e,
                )
                _global_tracker.record(ufo_err)
                if recovery == RecoveryStrategy.ABORT:
                    raise ufo_err from e
                return default_return

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ───────────────────── FastAPI 集成 ─────────────────────

def create_error_handlers(app):
    """
    为 FastAPI 应用注册统一错误处理器

    用法：
        from core.error_framework import create_error_handlers
        create_error_handlers(app)
    """
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(UFOError)
    async def ufo_error_handler(request: Request, exc: UFOError):
        _global_tracker.record(exc, handled=True)
        status_code = {
            ErrorCategory.AUTH: 401,
            ErrorCategory.CONFIG: 500,
            ErrorCategory.DATA: 400,
            ErrorCategory.TIMEOUT: 504,
            ErrorCategory.RESOURCE: 503,
        }.get(exc.category, 500)

        return JSONResponse(
            status_code=status_code,
            content=exc.to_dict(),
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception):
        ufo_err = UFOError(
            message=f"未处理的异常: {exc}",
            category=ErrorCategory.INTERNAL,
            severity=ErrorSeverity.ERROR,
            cause=exc,
        )
        _global_tracker.record(ufo_err)
        return JSONResponse(
            status_code=500,
            content=ufo_err.to_dict(),
        )


# ───────────────────── 全局实例 ─────────────────────

_global_tracker = ErrorTracker()


def get_error_tracker() -> ErrorTracker:
    return _global_tracker
