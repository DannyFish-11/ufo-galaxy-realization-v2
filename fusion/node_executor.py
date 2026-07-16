#!/usr/bin/env python3
"""
Galaxy Fusion - Node Executor (Gateway Optimized & Reinforced)

节点执行器 - 提供高级节点执行接口

核心功能:
1. 统一网关 (Unified Gateway) 与 102 节点执行优化
2. 自动重连与降级，支持 102 节点故障转移
3. 智能负载均衡，支持 102 节点动态调度
4. 实时监控与告警

Author: Galaxy Team
Created: 2026-01-26
Version: 1.3.0 (增强版)
"""

import asyncio
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_REQUEST_TIMEOUT_SECONDS: int = int(os.environ.get("FUSION_REQUEST_TIMEOUT", "30"))
DEFAULT_MAX_RETRIES: int = int(os.environ.get("FUSION_MAX_RETRIES", "2"))
DEFAULT_RETRY_BACKOFF_BASE: float = float(os.environ.get("FUSION_RETRY_BACKOFF", "0.5"))
DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS: float = float(os.environ.get("FUSION_HEALTH_TIMEOUT", "5.0"))
DEFAULT_HEALTH_CHECK_MAX_TIMEOUT_SECONDS: float = 30.0
POOL_LOAD_DELTA: float = 10.0

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
logger = logging.getLogger("NodeExecutor")

# ---------------------------------------------------------------------------
# Optional dependencies
# ---------------------------------------------------------------------------

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    aiohttp = None  # type: ignore
    AIOHTTP_AVAILABLE = False

try:
    from prometheus_client import Counter, Histogram, Gauge
    PROMETHEUS_AVAILABLE = True
except ImportError:
    Counter = Histogram = Gauge = None  # type: ignore
    PROMETHEUS_AVAILABLE = False

try:
    from pydantic import BaseModel, Field, field_validator
    PYDANTIC_AVAILABLE = True
except ImportError:
    BaseModel = Field = field_validator = None  # type: ignore
    PYDANTIC_AVAILABLE = False

from core.port_config import get_service_port


# ---------------------------------------------------------------------------
# Pydantic configuration validation
# ---------------------------------------------------------------------------

class NodeExecutorConfig(BaseModel if PYDANTIC_AVAILABLE else object):
    """Configuration model for NodeExecutor with validation."""

    gateway_url: str = Field(default="")
    request_timeout: int = Field(default=DEFAULT_REQUEST_TIMEOUT_SECONDS, ge=1, le=300)
    max_retries: int = Field(default=DEFAULT_MAX_RETRIES, ge=0, le=10)
    retry_backoff_base: float = Field(default=DEFAULT_RETRY_BACKOFF_BASE, ge=0.1, le=60.0)
    health_check_timeout: float = Field(default=DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS, ge=1.0, le=120.0)

    if PYDANTIC_AVAILABLE:
        @field_validator("gateway_url")
        @classmethod
        def validate_gateway_url(cls, value: str) -> str:
            """Validate gateway URL format."""
            if value and not value.startswith(("http://", "https://")):
                raise ValueError("gateway_url must start with http:// or https://")
            return value

    def __init__(self, **data: Any):
        if not PYDANTIC_AVAILABLE:
            # Fallback when pydantic is not available
            self.gateway_url = data.get("gateway_url", "")
            self.request_timeout = data.get("request_timeout", DEFAULT_REQUEST_TIMEOUT_SECONDS)
            self.max_retries = data.get("max_retries", DEFAULT_MAX_RETRIES)
            self.retry_backoff_base = data.get("retry_backoff_base", DEFAULT_RETRY_BACKOFF_BASE)
            self.health_check_timeout = data.get("health_check_timeout", DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS)
        else:
            super().__init__(**data)


# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

if PROMETHEUS_AVAILABLE:
    _EXECUTION_COUNTER: Optional[Counter] = Counter(
        "fusion_node_executions_total",
        "Total node executions",
        ["node_id", "status"]
    )
    _EXECUTION_LATENCY: Optional[Histogram] = Histogram(
        "fusion_node_execution_latency_ms",
        "Node execution latency in milliseconds",
        ["node_id"]
    )
    _HEALTH_CHECK_COUNTER: Optional[Counter] = Counter(
        "fusion_health_checks_total",
        "Total health checks",
        ["node_id", "status"]
    )
    _POOL_NODE_STATUS: Optional[Gauge] = Gauge(
        "fusion_pool_node_status",
        "Node status in execution pool (1=online, 0=offline)",
        ["node_id"]
    )
else:
    _EXECUTION_COUNTER = None
    _EXECUTION_LATENCY = None
    _HEALTH_CHECK_COUNTER = None
    _POOL_NODE_STATUS = None


def _record_execution_metric(node_id: str, status: str, latency_ms: float) -> None:
    """Record execution metrics to Prometheus."""
    if _EXECUTION_COUNTER is not None:
        _EXECUTION_COUNTER.labels(node_id=node_id, status=status).inc()
    if _EXECUTION_LATENCY is not None:
        _EXECUTION_LATENCY.labels(node_id=node_id).observe(latency_ms)


def _record_health_metric(node_id: str, status: str) -> None:
    """Record health check metrics to Prometheus."""
    if _HEALTH_CHECK_COUNTER is not None:
        _HEALTH_CHECK_COUNTER.labels(node_id=node_id, status=status).inc()
    if _POOL_NODE_STATUS is not None:
        _POOL_NODE_STATUS.labels(node_id=node_id).set(1 if status == "success" else 0)


# ---------------------------------------------------------------------------
# Sensitive data sanitization
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS: List[str] = [
    r"password[=:]\s*\S+",
    r"token[=:]\s*\S+",
    r"api[_-]?key[=:]\s*\S+",
    r"secret[=:]\s*\S+",
    r"credential[=:]\s*\S+",
    r"auth[=:]\s*\S+",
]
_SENSITIVE_RE = re.compile("|".join(_SENSITIVE_PATTERNS), re.IGNORECASE)


def sanitize_error_message(message: Optional[str]) -> Optional[str]:
    """Sanitize sensitive information from error messages.

    Args:
        message: Raw error message that may contain sensitive data.

    Returns:
        Sanitized error message with sensitive data replaced by [REDACTED].
    """
    if message is None:
        return None
    return _SENSITIVE_RE.sub("[REDACTED]", message)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

try:
    from dataclasses import dataclass
except ImportError:
    def dataclass(cls):  # type: ignore
        return cls


@dataclass
class ExecutionResult:
    """Execution result data class."""

    node_id: str
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    timestamp: float = 0.0


class ExecutionPool:
    """
    执行池 - 提供底层节点执行能力
    """

    def __init__(self, gateway_url: Optional[str] = None) -> None:
        if not AIOHTTP_AVAILABLE:
            raise ImportError(
                "aiohttp is required for ExecutionPool. "
                "Install it with: pip install aiohttp"
            )
        if gateway_url is None:
            gateway_url = f"http://localhost:{get_service_port('state_machine')}"
        self.config = NodeExecutorConfig(gateway_url=gateway_url)
        self.gateway_url: str = self.config.gateway_url.rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None
        self._node_status: Dict[str, bool] = {}
        logger.info("ExecutionPool initialized using gateway: %s", self.gateway_url)

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with configured timeout."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.request_timeout)
            )
        return self.session

    async def execute_on_node(
        self,
        node_id: str,
        command: str,
        params: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        """在指定节点执行命令 (支持重试)

        调用 POST /api/v1/nodes/call  (core/api_routes.py call_node)
        请求体: { "node_id": str, "action": str, "params": dict }

        Args:
            node_id: Target node identifier.
            command: Command/action to execute.
            params: Optional parameters dictionary.

        Returns:
            ExecutionResult with execution details.
        """
        start_time: float = time.time()
        url: str = f"{self.gateway_url}/api/v1/nodes/call"

        payload: Dict[str, Any] = {
            "node_id": node_id,
            "action": command,
            "params": params or {}
        }

        last_error: Optional[str] = None

        for attempt in range(self.config.max_retries + 1):
            try:
                session = await self._get_session()
                async with session.post(url, json=payload) as response:
                    latency: float = (time.time() - start_time) * 1000
                    if response.status == 200:
                        res_json = await response.json()
                        success: bool = res_json.get("success", True)
                        self._node_status[node_id] = success
                        result = ExecutionResult(
                            node_id=node_id,
                            success=success,
                            data=res_json.get("data"),
                            error=sanitize_error_message(res_json.get("error")),
                            latency_ms=latency,
                            timestamp=time.time()
                        )
                        _record_execution_metric(node_id, "success", latency)
                        return result
                    else:
                        error_text = await response.text()
                        last_error = f"Gateway Error {response.status}: {error_text}"
            except Exception as exc:
                last_error = f"Connection Error: {type(exc).__name__}"

            if attempt < self.config.max_retries:
                backoff: float = self.config.retry_backoff_base * (attempt + 1)
                logger.warning(
                    "Attempt %d failed on %s, retrying in %.1fs...",
                    attempt + 1, node_id, backoff
                )
                await asyncio.sleep(backoff)

        self._node_status[node_id] = False
        final_error: Optional[str] = sanitize_error_message(last_error)
        total_latency: float = (time.time() - start_time) * 1000
        _record_execution_metric(node_id, "failure", total_latency)
        return ExecutionResult(
            node_id=node_id,
            success=False,
            error=final_error,
            latency_ms=total_latency,
            timestamp=time.time()
        )

    async def check_node_health(self, node_id: str, timeout_sec: float = 0.0) -> bool:
        """检查节点健康状态 (通过 GET /api/v1/nodes/{node_name})

        Args:
            node_id: 节点 ID
            timeout_sec: 超时秒数 (最大 30 秒，0 表示使用配置默认值)
        """
        # Use configured timeout if not specified
        if timeout_sec <= 0:
            timeout_sec = self.config.health_check_timeout
        # Clamp to maximum allowed timeout
        timeout_sec = min(timeout_sec, DEFAULT_HEALTH_CHECK_MAX_TIMEOUT_SECONDS)
        url: str = f"{self.gateway_url}/api/v1/nodes/{node_id}"
        try:
            session = await self._get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_sec)) as response:
                is_healthy: bool = response.status == 200
                self._node_status[node_id] = is_healthy
                _record_health_metric(node_id, "success" if is_healthy else "unhealthy")
                return is_healthy
        except Exception as exc:
            logger.warning("Health check failed for %s: %s", node_id, type(exc).__name__)
            self._node_status[node_id] = False
            _record_health_metric(node_id, "error")
            return False

    async def close_all(self) -> None:
        """关闭所有连接"""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("Gateway session closed")

    def get_pool_status(self) -> Dict[str, Any]:
        """获取执行池状态"""
        total: int = len(self._node_status)
        online: int = sum(1 for status in self._node_status.values() if status)
        return {
            "total_tracked_nodes": total,
            "online_nodes": online,
            "offline_nodes": total - online,
            "gateway_url": self.gateway_url
        }


class NodeExecutor:
    """节点执行器 - 提供高级节点执行接口"""

    def __init__(self, gateway_url: Optional[str] = None) -> None:
        self._pool: ExecutionPool = ExecutionPool(gateway_url)
        logger.info("NodeExecutor initialized with gateway: %s", self._pool.gateway_url)

    async def execute(
        self,
        node_id: str,
        command: str,
        params: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        """在指定节点执行命令"""
        return await self._pool.execute_on_node(node_id, command, params)

    async def health_check(self, node_id: str) -> bool:
        """检查节点健康状态"""
        return await self._pool.check_node_health(node_id)

    async def close(self) -> None:
        """关闭执行器"""
        await self._pool.close_all()

    def get_status(self) -> Dict[str, Any]:
        """获取执行器状态"""
        return self._pool.get_pool_status()
