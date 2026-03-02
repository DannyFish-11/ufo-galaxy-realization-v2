"""
Node 71 - Fault Tolerance Module
容错层实现：熔断器（Circuit Breaker）、重试管理器、故障切换（Failover）
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """熔断器状态"""
    CLOSED = "closed"        # 正常 - 请求正常通过
    OPEN = "open"            # 熔断 - 请求被拒绝
    HALF_OPEN = "half_open"  # 半开 - 允许少量探测请求


@dataclass
class CircuitBreakerConfig:
    """熔断器配置"""
    failure_threshold: int = 5          # 失败次数阈值，达到后打开熔断器
    success_threshold: int = 3          # 半开状态下连续成功次数阈值，达到后关闭熔断器
    timeout: float = 30.0               # 熔断器打开后等待多久进入半开状态（秒）
    half_open_max_calls: int = 3        # 半开状态下最大允许请求数
    window_size: float = 60.0           # 滑动窗口大小（秒），窗口内统计失败次数

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failure_threshold": self.failure_threshold,
            "success_threshold": self.success_threshold,
            "timeout": self.timeout,
            "half_open_max_calls": self.half_open_max_calls,
            "window_size": self.window_size,
        }


class CircuitBreaker:
    """
    熔断器实现

    状态转换:
    CLOSED --[failures >= threshold]--> OPEN
    OPEN   --[timeout elapsed]-------> HALF_OPEN
    HALF_OPEN --[success >= threshold]--> CLOSED
    HALF_OPEN --[any failure]----------> OPEN
    """

    def __init__(self, name: str, config: CircuitBreakerConfig = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0
        self._last_state_change: float = time.time()
        self._half_open_calls = 0
        self._failure_timestamps: deque = deque()
        self._total_calls = 0
        self._total_failures = 0
        self._total_successes = 0
        self._total_rejections = 0

    @property
    def state(self) -> CircuitState:
        """获取当前状态，自动检查是否应该从 OPEN 转换到 HALF_OPEN"""
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_state_change
            if elapsed >= self.config.timeout:
                self._transition_to(CircuitState.HALF_OPEN)
        return self._state

    def _transition_to(self, new_state: CircuitState) -> None:
        """状态转换"""
        old_state = self._state
        self._state = new_state
        self._last_state_change = time.time()

        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._success_count = 0
        elif new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
            self._failure_timestamps.clear()

        logger.info(
            f"CircuitBreaker[{self.name}] {old_state.value} -> {new_state.value}"
        )

    def _clean_window(self) -> None:
        """清理滑动窗口外的失败记录"""
        cutoff = time.time() - self.config.window_size
        while self._failure_timestamps and self._failure_timestamps[0] < cutoff:
            self._failure_timestamps.popleft()

    def can_execute(self) -> bool:
        """检查是否允许执行请求"""
        current = self.state  # 触发自动状态检查

        if current == CircuitState.CLOSED:
            return True
        elif current == CircuitState.HALF_OPEN:
            return self._half_open_calls < self.config.half_open_max_calls
        else:  # OPEN
            return False

    def record_success(self) -> None:
        """记录成功"""
        self._total_calls += 1
        self._total_successes += 1

        current = self.state
        if current == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED)

    def record_failure(self) -> None:
        """记录失败"""
        self._total_calls += 1
        self._total_failures += 1
        self._last_failure_time = time.time()
        self._failure_timestamps.append(time.time())

        current = self.state
        if current == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.OPEN)
        elif current == CircuitState.CLOSED:
            self._clean_window()
            self._failure_count = len(self._failure_timestamps)
            if self._failure_count >= self.config.failure_threshold:
                self._transition_to(CircuitState.OPEN)

    def record_rejection(self) -> None:
        """记录请求被拒绝"""
        self._total_rejections += 1

    async def execute(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        通过熔断器执行异步函数

        如果熔断器打开，立即抛出 CircuitBreakerOpenError
        """
        if not self.can_execute():
            self.record_rejection()
            raise CircuitBreakerOpenError(
                f"CircuitBreaker[{self.name}] is OPEN, request rejected"
            )

        if self.state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1

        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise

    def reset(self) -> None:
        """手动重置熔断器"""
        self._transition_to(CircuitState.CLOSED)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "total_rejections": self._total_rejections,
            "last_failure_time": self._last_failure_time,
            "last_state_change": self._last_state_change,
        }


class CircuitBreakerOpenError(Exception):
    """熔断器打开时抛出的异常"""
    pass


@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_backoff: bool = True
    backoff_multiplier: float = 2.0
    jitter: bool = True                 # 添加随机抖动
    retryable_exceptions: tuple = (Exception,)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_retries": self.max_retries,
            "base_delay": self.base_delay,
            "max_delay": self.max_delay,
            "exponential_backoff": self.exponential_backoff,
            "backoff_multiplier": self.backoff_multiplier,
            "jitter": self.jitter,
        }


class RetryManager:
    """
    重试管理器

    支持指数退避 + 随机抖动，避免重试风暴
    """

    def __init__(self, config: RetryConfig = None):
        self.config = config or RetryConfig()
        self._stats = {
            "total_attempts": 0,
            "total_retries": 0,
            "total_successes": 0,
            "total_failures": 0,
        }

    def _compute_delay(self, attempt: int) -> float:
        """计算重试延迟"""
        if self.config.exponential_backoff:
            delay = self.config.base_delay * (
                self.config.backoff_multiplier ** attempt
            )
        else:
            delay = self.config.base_delay

        delay = min(delay, self.config.max_delay)

        if self.config.jitter:
            import random
            delay = delay * (0.5 + random.random())

        return delay

    async def execute(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """带重试的异步函数执行"""
        last_exception = None

        for attempt in range(self.config.max_retries + 1):
            self._stats["total_attempts"] += 1

            try:
                result = await func(*args, **kwargs)
                self._stats["total_successes"] += 1
                return result
            except self.config.retryable_exceptions as e:
                last_exception = e
                if attempt < self.config.max_retries:
                    delay = self._compute_delay(attempt)
                    self._stats["total_retries"] += 1
                    logger.warning(
                        f"Retry {attempt + 1}/{self.config.max_retries} "
                        f"after {delay:.2f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    self._stats["total_failures"] += 1
                    logger.error(
                        f"All {self.config.max_retries} retries exhausted: {e}"
                    )

        raise last_exception

    def get_stats(self) -> Dict[str, Any]:
        return dict(self._stats)


@dataclass
class FailoverConfig:
    """故障切换配置"""
    max_failover_attempts: int = 3
    health_check_interval: float = 10.0
    recovery_timeout: float = 60.0
    enable_auto_recovery: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_failover_attempts": self.max_failover_attempts,
            "health_check_interval": self.health_check_interval,
            "recovery_timeout": self.recovery_timeout,
            "enable_auto_recovery": self.enable_auto_recovery,
        }


class FailoverManager:
    """
    故障切换管理器

    - 维护主/备设备列表
    - 主设备故障时自动切换到备用设备
    - 支持健康检查和自动恢复
    """

    def __init__(self, config: FailoverConfig = None):
        self.config = config or FailoverConfig()
        self._primary: Optional[str] = None
        self._secondaries: List[str] = []
        self._failed_devices: Dict[str, float] = {}  # device_id -> failure_time
        self._health_checkers: Dict[str, Callable] = {}
        self._running = False
        self._health_check_task: Optional[asyncio.Task] = None
        self._stats = {
            "failover_count": 0,
            "recovery_count": 0,
            "current_primary": None,
        }

    def set_primary(self, device_id: str) -> None:
        """设置主设备"""
        self._primary = device_id
        self._stats["current_primary"] = device_id

    def add_secondary(self, device_id: str) -> None:
        """添加备用设备"""
        if device_id not in self._secondaries:
            self._secondaries.append(device_id)

    def remove_secondary(self, device_id: str) -> None:
        """移除备用设备"""
        if device_id in self._secondaries:
            self._secondaries.remove(device_id)

    def register_health_checker(
        self, device_id: str, checker: Callable[..., Awaitable[bool]]
    ) -> None:
        """注册健康检查函数"""
        self._health_checkers[device_id] = checker

    async def failover(self) -> Optional[str]:
        """执行故障切换，返回新的主设备 ID"""
        if not self._secondaries:
            logger.error("No secondary devices available for failover")
            return None

        old_primary = self._primary

        for attempt in range(min(self.config.max_failover_attempts, len(self._secondaries))):
            candidate = self._secondaries[0]

            # 检查候选设备是否健康
            checker = self._health_checkers.get(candidate)
            if checker:
                try:
                    healthy = await checker()
                    if not healthy:
                        self._secondaries.append(self._secondaries.pop(0))
                        continue
                except Exception:
                    self._secondaries.append(self._secondaries.pop(0))
                    continue

            # 切换
            new_primary = self._secondaries.pop(0)
            self._primary = new_primary
            self._stats["current_primary"] = new_primary
            self._stats["failover_count"] += 1

            if old_primary:
                self._failed_devices[old_primary] = time.time()

            logger.info(
                f"Failover: {old_primary} -> {new_primary} "
                f"(attempt {attempt + 1})"
            )
            return new_primary

        logger.error(
            f"Failover failed after {self.config.max_failover_attempts} attempts"
        )
        return None

    async def start(self) -> None:
        """启动健康检查"""
        if self._running:
            return
        self._running = True
        if self.config.enable_auto_recovery:
            self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info("FailoverManager started")

    async def stop(self) -> None:
        """停止健康检查"""
        self._running = False
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        logger.info("FailoverManager stopped")

    async def _health_check_loop(self) -> None:
        """健康检查循环 + 自动恢复"""
        while self._running:
            try:
                # 检查主设备
                if self._primary and self._primary in self._health_checkers:
                    checker = self._health_checkers[self._primary]
                    try:
                        healthy = await checker()
                        if not healthy:
                            logger.warning(
                                f"Primary device {self._primary} unhealthy, "
                                f"triggering failover"
                            )
                            await self.failover()
                    except Exception as e:
                        logger.error(f"Health check failed for primary: {e}")
                        await self.failover()

                # 尝试恢复已失败设备
                recovered = []
                for device_id, fail_time in self._failed_devices.items():
                    elapsed = time.time() - fail_time
                    if elapsed < self.config.recovery_timeout:
                        continue

                    checker = self._health_checkers.get(device_id)
                    if checker:
                        try:
                            healthy = await checker()
                            if healthy:
                                recovered.append(device_id)
                        except Exception:
                            pass

                for device_id in recovered:
                    del self._failed_devices[device_id]
                    self._secondaries.append(device_id)
                    self._stats["recovery_count"] += 1
                    logger.info(f"Device {device_id} recovered, added as secondary")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check loop error: {e}")

            await asyncio.sleep(self.config.health_check_interval)

    def get_status(self) -> Dict[str, Any]:
        """获取故障切换状态"""
        return {
            "primary": self._primary,
            "secondaries": list(self._secondaries),
            "failed_devices": {
                k: v for k, v in self._failed_devices.items()
            },
            "stats": dict(self._stats),
            "running": self._running,
        }

    def get_stats(self) -> Dict[str, Any]:
        return dict(self._stats)


class FaultToleranceLayer:
    """
    容错层统一管理

    聚合熔断器、重试管理器和故障切换管理器
    """

    def __init__(
        self,
        circuit_config: CircuitBreakerConfig = None,
        retry_config: RetryConfig = None,
        failover_config: FailoverConfig = None,
    ):
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._default_circuit_config = circuit_config or CircuitBreakerConfig()
        self._retry_manager = RetryManager(retry_config)
        self._failover_manager = FailoverManager(failover_config)

    def get_circuit_breaker(self, name: str) -> CircuitBreaker:
        """获取或创建熔断器"""
        if name not in self._circuit_breakers:
            self._circuit_breakers[name] = CircuitBreaker(
                name, self._default_circuit_config
            )
        return self._circuit_breakers[name]

    @property
    def retry(self) -> RetryManager:
        return self._retry_manager

    @property
    def failover(self) -> FailoverManager:
        return self._failover_manager

    async def execute_with_resilience(
        self,
        name: str,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        带完整容错保护的执行

        顺序: 熔断器检查 -> 重试包装 -> 执行
        """
        cb = self.get_circuit_breaker(name)

        async def wrapped():
            return await cb.execute(func, *args, **kwargs)

        return await self._retry_manager.execute(wrapped)

    async def start(self) -> None:
        """启动容错层"""
        await self._failover_manager.start()
        logger.info("FaultToleranceLayer started")

    async def stop(self) -> None:
        """停止容错层"""
        await self._failover_manager.stop()
        logger.info("FaultToleranceLayer stopped")

    def get_status(self) -> Dict[str, Any]:
        """获取容错层状态"""
        return {
            "circuit_breakers": {
                name: cb.get_stats()
                for name, cb in self._circuit_breakers.items()
            },
            "retry": self._retry_manager.get_stats(),
            "failover": self._failover_manager.get_status(),
        }
