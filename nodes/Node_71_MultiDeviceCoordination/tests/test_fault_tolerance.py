"""
Node 71 - Fault Tolerance Tests
容错层单元测试：熔断器、重试管理器、故障切换
"""
import asyncio
import pytest
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.fault_tolerance import (
    CircuitBreaker, CircuitBreakerConfig, CircuitBreakerOpenError,
    CircuitState, RetryManager, RetryConfig,
    FailoverManager, FailoverConfig,
    FaultToleranceLayer
)


class TestCircuitBreaker:
    """熔断器测试"""

    def test_initial_state(self, circuit_breaker):
        """测试初始状态为 CLOSED"""
        assert circuit_breaker.state == CircuitState.CLOSED
        assert circuit_breaker.can_execute() is True

    def test_stays_closed_on_success(self, circuit_breaker):
        """测试成功请求保持 CLOSED"""
        for _ in range(10):
            circuit_breaker.record_success()
        assert circuit_breaker.state == CircuitState.CLOSED

    def test_opens_after_failures(self, circuit_breaker):
        """测试失败达到阈值后打开"""
        for _ in range(3):  # failure_threshold = 3
            circuit_breaker.record_failure()
        assert circuit_breaker.state == CircuitState.OPEN
        assert circuit_breaker.can_execute() is False

    def test_transitions_to_half_open(self, circuit_breaker):
        """测试超时后进入半开状态"""
        for _ in range(3):
            circuit_breaker.record_failure()
        assert circuit_breaker.state == CircuitState.OPEN

        # 等待超时（timeout=1.0s）
        time.sleep(1.1)
        assert circuit_breaker.state == CircuitState.HALF_OPEN

    def test_half_open_to_closed(self, circuit_breaker):
        """测试半开状态成功后关闭"""
        for _ in range(3):
            circuit_breaker.record_failure()
        time.sleep(1.1)
        assert circuit_breaker.state == CircuitState.HALF_OPEN

        # success_threshold = 2
        circuit_breaker.record_success()
        circuit_breaker.record_success()
        assert circuit_breaker.state == CircuitState.CLOSED

    def test_half_open_to_open(self, circuit_breaker):
        """测试半开状态失败后重新打开"""
        for _ in range(3):
            circuit_breaker.record_failure()
        time.sleep(1.1)
        assert circuit_breaker.state == CircuitState.HALF_OPEN

        circuit_breaker.record_failure()
        assert circuit_breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_execute_success(self, circuit_breaker):
        """测试通过熔断器成功执行"""
        async def success_func():
            return "ok"

        result = await circuit_breaker.execute(success_func)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_execute_rejected_when_open(self, circuit_breaker):
        """测试熔断器打开时拒绝请求"""
        for _ in range(3):
            circuit_breaker.record_failure()

        async def some_func():
            return "ok"

        with pytest.raises(CircuitBreakerOpenError):
            await circuit_breaker.execute(some_func)

    @pytest.mark.asyncio
    async def test_execute_propagates_exception(self, circuit_breaker):
        """测试异常被正确传播"""
        async def failing_func():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            await circuit_breaker.execute(failing_func)

    def test_reset(self, circuit_breaker):
        """测试手动重置"""
        for _ in range(3):
            circuit_breaker.record_failure()
        assert circuit_breaker.state == CircuitState.OPEN

        circuit_breaker.reset()
        assert circuit_breaker.state == CircuitState.CLOSED

    def test_stats(self, circuit_breaker):
        """测试统计信息"""
        circuit_breaker.record_success()
        circuit_breaker.record_success()
        circuit_breaker.record_failure()

        stats = circuit_breaker.get_stats()
        assert stats["total_calls"] == 3
        assert stats["total_successes"] == 2
        assert stats["total_failures"] == 1
        assert stats["name"] == "test-cb"


class TestRetryManager:
    """重试管理器测试"""

    @pytest.mark.asyncio
    async def test_success_no_retry(self, retry_manager):
        """测试成功不重试"""
        call_count = 0

        async def success_func():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_manager.execute(success_func)
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, retry_manager):
        """测试失败后重试"""
        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary error")
            return "ok"

        result = await retry_manager.execute(flaky_func)
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self, retry_manager):
        """测试重试次数耗尽"""
        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("persistent error")

        with pytest.raises(ValueError, match="persistent error"):
            await retry_manager.execute(always_fail)

        # max_retries=3, so total calls = 1 + 3 = 4
        assert call_count == 4

    @pytest.mark.asyncio
    async def test_stats_tracking(self, retry_manager):
        """测试统计跟踪"""
        async def success_func():
            return "ok"

        await retry_manager.execute(success_func)

        stats = retry_manager.get_stats()
        assert stats["total_attempts"] == 1
        assert stats["total_successes"] == 1
        assert stats["total_retries"] == 0

    def test_delay_calculation(self, retry_manager):
        """测试延迟计算"""
        d0 = retry_manager._compute_delay(0)
        d1 = retry_manager._compute_delay(1)
        d2 = retry_manager._compute_delay(2)

        # exponential backoff: base * 2^attempt
        assert d0 == pytest.approx(0.01, abs=0.001)
        assert d1 == pytest.approx(0.02, abs=0.001)
        assert d2 == pytest.approx(0.04, abs=0.001)


class TestFailoverManager:
    """故障切换管理器测试"""

    @pytest.mark.asyncio
    async def test_failover(self, failover_manager):
        """测试故障切换"""
        failover_manager.set_primary("device-A")
        failover_manager.add_secondary("device-B")
        failover_manager.add_secondary("device-C")

        new_primary = await failover_manager.failover()
        assert new_primary == "device-B"
        assert failover_manager._primary == "device-B"

    @pytest.mark.asyncio
    async def test_failover_no_secondary(self, failover_manager):
        """测试没有备用设备时失败"""
        failover_manager.set_primary("device-A")

        new_primary = await failover_manager.failover()
        assert new_primary is None

    @pytest.mark.asyncio
    async def test_failover_with_health_check(self, failover_manager):
        """测试带健康检查的故障切换"""
        failover_manager.set_primary("device-A")
        failover_manager.add_secondary("device-B")
        failover_manager.add_secondary("device-C")

        # device-B 不健康
        async def unhealthy():
            return False

        async def healthy():
            return True

        failover_manager.register_health_checker("device-B", unhealthy)
        failover_manager.register_health_checker("device-C", healthy)

        new_primary = await failover_manager.failover()
        assert new_primary == "device-C"

    @pytest.mark.asyncio
    async def test_start_stop(self, failover_manager):
        """测试启动和停止"""
        await failover_manager.start()
        assert failover_manager._running is True

        await failover_manager.stop()
        assert failover_manager._running is False

    def test_get_status(self, failover_manager):
        """测试状态获取"""
        failover_manager.set_primary("device-A")
        failover_manager.add_secondary("device-B")

        status = failover_manager.get_status()
        assert status["primary"] == "device-A"
        assert "device-B" in status["secondaries"]


class TestFaultToleranceLayer:
    """容错层集成测试"""

    @pytest.mark.asyncio
    async def test_execute_with_resilience(self):
        """测试带完整容错保护的执行"""
        layer = FaultToleranceLayer(
            circuit_config=CircuitBreakerConfig(failure_threshold=5),
            retry_config=RetryConfig(max_retries=2, base_delay=0.01, jitter=False)
        )

        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("temp error")
            return "success"

        result = await layer.execute_with_resilience("test", flaky_func)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_start_stop(self):
        """测试容错层启动和停止"""
        layer = FaultToleranceLayer()
        await layer.start()
        await layer.stop()

    def test_get_circuit_breaker(self):
        """测试获取或创建熔断器"""
        layer = FaultToleranceLayer()

        cb1 = layer.get_circuit_breaker("test")
        cb2 = layer.get_circuit_breaker("test")

        assert cb1 is cb2  # 同一实例

    def test_get_status(self):
        """测试状态获取"""
        layer = FaultToleranceLayer()
        layer.get_circuit_breaker("cb-1")
        layer.get_circuit_breaker("cb-2")

        status = layer.get_status()
        assert "circuit_breakers" in status
        assert "cb-1" in status["circuit_breakers"]
        assert "cb-2" in status["circuit_breakers"]
        assert "retry" in status
        assert "failover" in status


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
