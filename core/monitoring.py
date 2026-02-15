"""
UFO Galaxy - 监控告警系统
=========================

融合元气 AI Bot 精髓 - 可靠性 99.99%：

模块内容：
  1. CircuitBreaker    - 熔断器（故障自动隔离）
  2. HealthAggregator  - 健康检查聚合器
  3. AlertManager      - 告警管理器
  4. MetricsCollector  - 系统指标采集器

目标：
  多实例 → 故障自动转移 → 系统永远可用
"""

import asyncio
import logging
import os
import platform
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

logger = logging.getLogger("UFO-Galaxy.Monitoring")


# ============================================================================
# 1. 熔断器
# ============================================================================

class CircuitState(str, Enum):
    CLOSED = "closed"       # 正常：请求通过
    OPEN = "open"           # 熔断：请求直接拒绝
    HALF_OPEN = "half_open" # 探测：允许少量请求试探


class CircuitBreaker:
    """
    熔断器

    状态转换：
      CLOSED → (连续失败 >= threshold) → OPEN
      OPEN   → (等待 recovery_timeout) → HALF_OPEN
      HALF_OPEN → (探测成功) → CLOSED
      HALF_OPEN → (探测失败) → OPEN
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self._half_open_calls = 0

    def can_execute(self) -> bool:
        """检查是否允许执行"""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if self.last_failure_time and (time.time() - self.last_failure_time) > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info(f"Circuit breaker [{self.name}]: OPEN → HALF_OPEN")
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            return self._half_open_calls < self.half_open_max_calls

        return False

    def record_success(self):
        """记录成功"""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.half_open_max_calls:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
                logger.info(f"Circuit breaker [{self.name}]: HALF_OPEN → CLOSED")
        elif self.state == CircuitState.CLOSED:
            self.failure_count = max(0, self.failure_count - 1)

    def record_failure(self):
        """记录失败"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self._half_open_calls = 0
            logger.warning(f"Circuit breaker [{self.name}]: HALF_OPEN → OPEN")
        elif self.state == CircuitState.CLOSED and self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit breaker [{self.name}]: CLOSED → OPEN (failures: {self.failure_count})")

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure": (
                datetime.fromtimestamp(self.last_failure_time).isoformat()
                if self.last_failure_time else None
            ),
        }

    async def execute(self, func: Callable[..., Coroutine], *args, **kwargs):
        """通过熔断器执行异步函数"""
        if not self.can_execute():
            raise CircuitBreakerOpenError(f"Circuit breaker [{self.name}] is OPEN")

        if self.state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1

        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise


class CircuitBreakerOpenError(Exception):
    pass


# ============================================================================
# 2. 健康检查聚合器
# ============================================================================

@dataclass
class ComponentHealth:
    """组件健康状态"""
    name: str
    status: str = "unknown"         # healthy / degraded / unhealthy / unknown
    latency_ms: float = 0.0
    last_check: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    consecutive_failures: int = 0


class HealthAggregator:
    """
    健康检查聚合器

    定期检查所有组件健康状态，并聚合为系统级别的健康评估。
    """

    def __init__(self, check_interval: float = 30.0):
        self.check_interval = check_interval
        self._components: Dict[str, ComponentHealth] = {}
        self._checks: Dict[str, Callable] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def register_check(self, name: str, check_func: Callable):
        """注册健康检查函数"""
        self._checks[name] = check_func
        self._components[name] = ComponentHealth(name=name)

    async def start(self):
        """启动定期检查"""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._check_loop())
            logger.info("Health aggregator started")

    async def stop(self):
        """停止"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _check_loop(self):
        """定期检查循环"""
        while self._running:
            await self.check_all()
            await asyncio.sleep(self.check_interval)

    async def check_all(self):
        """执行所有检查"""
        # 使用快照避免迭代时字典被修改导致 RuntimeError
        checks_snapshot = list(self._checks.items())
        for name, check_func in checks_snapshot:
            await self._run_check(name, check_func)

    async def _run_check(self, name: str, check_func: Callable):
        """执行单个检查"""
        comp = self._components[name]
        start = time.time()

        try:
            if asyncio.iscoroutinefunction(check_func):
                result = await asyncio.wait_for(check_func(), timeout=10.0)
            else:
                result = check_func()

            comp.latency_ms = (time.time() - start) * 1000
            comp.last_check = time.time()
            comp.consecutive_failures = 0

            if isinstance(result, dict):
                comp.status = result.get("status", "healthy")
                comp.details = result
                comp.error = result.get("error")
            elif isinstance(result, bool):
                comp.status = "healthy" if result else "unhealthy"
            else:
                comp.status = "healthy"
            comp.error = None

        except asyncio.TimeoutError:
            comp.status = "unhealthy"
            comp.error = "Health check timeout"
            comp.consecutive_failures += 1
            comp.latency_ms = (time.time() - start) * 1000
            comp.last_check = time.time()

        except Exception as e:
            comp.status = "unhealthy"
            comp.error = str(e)
            comp.consecutive_failures += 1
            comp.latency_ms = (time.time() - start) * 1000
            comp.last_check = time.time()

    def get_status(self) -> dict:
        """获取聚合健康状态"""
        components = {}
        overall = "healthy"

        for name, comp in self._components.items():
            components[name] = {
                "status": comp.status,
                "latency_ms": round(comp.latency_ms, 2),
                "last_check": (
                    datetime.fromtimestamp(comp.last_check).isoformat()
                    if comp.last_check else None
                ),
                "error": comp.error,
                "consecutive_failures": comp.consecutive_failures,
            }

            if comp.status == "unhealthy":
                overall = "unhealthy"
            elif comp.status == "degraded" and overall == "healthy":
                overall = "degraded"

        return {
            "overall": overall,
            "components": components,
            "checked_at": datetime.now().isoformat(),
        }


# ============================================================================
# 3. 告警管理器
# ============================================================================

class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    """告警"""
    alert_id: str
    severity: AlertSeverity
    component: str
    message: str
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False
    resolved_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "severity": self.severity.value,
            "component": self.component,
            "message": self.message,
            "timestamp": datetime.fromtimestamp(self.timestamp).isoformat(),
            "resolved": self.resolved,
            "resolved_at": (
                datetime.fromtimestamp(self.resolved_at).isoformat()
                if self.resolved_at else None
            ),
        }


class AlertManager:
    """
    告警管理器

    功能：
      - 触发告警（去重）
      - 自动解除告警
      - 告警通知（回调）
      - 告警历史
    """

    def __init__(self, on_alert: Optional[Callable] = None):
        self._active_alerts: Dict[str, Alert] = {}
        self._history: deque = deque(maxlen=1000)
        self._on_alert = on_alert
        self._counter = 0

    def fire(self, severity: AlertSeverity, component: str, message: str, metadata: Optional[Dict] = None) -> str:
        """触发告警"""
        # 去重：相同组件+消息只保留一条
        dedup_key = f"{component}:{message}"
        if dedup_key in self._active_alerts and not self._active_alerts[dedup_key].resolved:
            return self._active_alerts[dedup_key].alert_id

        self._counter += 1
        alert_id = f"alert_{self._counter:05d}"

        alert = Alert(
            alert_id=alert_id,
            severity=severity,
            component=component,
            message=message,
            metadata=metadata or {},
        )

        self._active_alerts[dedup_key] = alert
        self._history.append(alert)

        logger.warning(f"[ALERT] {severity.value.upper()} [{component}] {message}")

        # 通知
        if self._on_alert:
            try:
                if asyncio.iscoroutinefunction(self._on_alert):
                    asyncio.create_task(self._on_alert(alert))
                else:
                    self._on_alert(alert)
            except Exception as e:
                logger.error(f"Alert notification failed: {e}")

        return alert_id

    def resolve(self, component: str, message: str):
        """解除告警"""
        dedup_key = f"{component}:{message}"
        alert = self._active_alerts.get(dedup_key)
        if alert and not alert.resolved:
            alert.resolved = True
            alert.resolved_at = time.time()
            logger.info(f"[RESOLVED] [{component}] {message}")

    def get_active_alerts(self) -> List[dict]:
        """获取活跃告警"""
        return [
            a.to_dict()
            for a in self._active_alerts.values()
            if not a.resolved
        ]

    def get_history(self, limit: int = 50) -> List[dict]:
        """获取告警历史"""
        return [a.to_dict() for a in list(self._history)[-limit:]]


# ============================================================================
# 4. 系统指标采集器
# ============================================================================

class MetricsCollector:
    """
    系统指标采集器

    采集：
      - CPU / Memory / Disk
      - 网络连接数
      - 事件总线吞吐
      - 命令路由延迟
    """

    def __init__(self):
        self._metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=300))
        self._start_time = time.time()

    def record(self, metric_name: str, value: float, labels: Optional[Dict] = None):
        """记录指标"""
        self._metrics[metric_name].append({
            "value": value,
            "timestamp": time.time(),
            "labels": labels or {},
        })

    async def collect_system_metrics(self):
        """采集系统指标"""
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            self.record("system.cpu_percent", cpu)
            self.record("system.memory_percent", mem.percent)
            self.record("system.memory_used_mb", mem.used / 1024 / 1024)
            self.record("system.disk_percent", disk.percent)
        except ImportError:
            # psutil not available, collect basic metrics
            pass

    def get_latest(self, metric_name: str) -> Optional[dict]:
        """获取最新指标"""
        data = self._metrics.get(metric_name)
        if data:
            return data[-1]
        return None

    def get_series(self, metric_name: str, limit: int = 60) -> List[dict]:
        """获取指标时间序列"""
        data = self._metrics.get(metric_name, deque())
        return list(data)[-limit:]

    def get_dashboard(self) -> dict:
        """获取指标仪表盘"""
        dashboard = {
            "uptime_seconds": round(time.time() - self._start_time, 0),
            "metrics": {},
        }

        for name, data in self._metrics.items():
            if data:
                values = [d["value"] for d in data]
                dashboard["metrics"][name] = {
                    "current": values[-1] if values else 0,
                    "avg": sum(values) / len(values) if values else 0,
                    "max": max(values) if values else 0,
                    "min": min(values) if values else 0,
                    "samples": len(values),
                }

        return dashboard


# ============================================================================
# 综合监控管理器
# ============================================================================

class MonitoringManager:
    """
    综合监控管理器

    整合所有监控组件，提供统一接口。
    """

    def __init__(self):
        self.health = HealthAggregator()
        self.alerts = AlertManager()
        self.metrics = MetricsCollector()
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._running = False
        self._tasks: List[asyncio.Task] = []

    def get_circuit_breaker(self, name: str, **kwargs) -> CircuitBreaker:
        """获取或创建熔断器"""
        if name not in self._circuit_breakers:
            self._circuit_breakers[name] = CircuitBreaker(name=name, **kwargs)
        return self._circuit_breakers[name]

    async def start(self):
        """启动所有监控"""
        if self._running:
            return
        self._running = True

        # 启动健康检查
        await self.health.start()

        # 启动指标采集循环
        self._tasks.append(asyncio.create_task(self._metrics_loop()))

        logger.info("Monitoring manager started")

    async def stop(self):
        """停止"""
        self._running = False
        await self.health.stop()
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _metrics_loop(self):
        """指标采集循环"""
        while self._running:
            try:
                await self.metrics.collect_system_metrics()
            except Exception as e:
                logger.error(f"Metrics collection error: {e}")
            await asyncio.sleep(15)

    def get_full_dashboard(self) -> dict:
        """获取完整监控仪表盘"""
        return {
            "health": self.health.get_status(),
            "alerts": {
                "active": self.alerts.get_active_alerts(),
                "recent": self.alerts.get_history(10),
            },
            "circuit_breakers": {
                name: cb.get_status()
                for name, cb in self._circuit_breakers.items()
            },
            "metrics": self.metrics.get_dashboard(),
            "timestamp": datetime.now().isoformat(),
        }


# ============================================================================
# 全局实例
# ============================================================================

_monitoring_manager: Optional[MonitoringManager] = None


def get_monitoring_manager() -> MonitoringManager:
    global _monitoring_manager
    if _monitoring_manager is None:
        _monitoring_manager = MonitoringManager()
    return _monitoring_manager
