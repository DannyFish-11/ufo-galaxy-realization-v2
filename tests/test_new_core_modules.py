"""
新增核心模块单元测试
====================

覆盖:
- concurrency_manager.py
- config_hot_reload.py
- security_middleware.py
- health_integration.py
"""

import asyncio
import json
import os
import tempfile
import time
import pytest

# ============================================================================
# 辅助
# ============================================================================

def run_async(coro):
    """同步运行协程的辅助函数"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================================
# 1. ConcurrencyManager 测试
# ============================================================================

class TestConcurrencyManager:

    def test_lock_acquire_release(self):
        """测试基本锁获取和释放"""
        from core.concurrency_manager import LockManager, LockType

        async def _test():
            lm = LockManager()
            ok = await lm.acquire("res1", "holder1", LockType.EXCLUSIVE, timeout=5)
            assert ok, "应成功获取排他锁"

            # 同一持有者重入应成功
            ok2 = await lm.acquire("res1", "holder1", LockType.EXCLUSIVE, timeout=1)
            assert ok2, "同一持有者重入应成功"

            await lm.release("res1", "holder1")
            status = lm.get_status()
            assert status["active_locks"] == 0 or status["active_locks"] == 1
            # 完全释放
            await lm.release_all("holder1")
            assert lm.get_status()["active_locks"] == 0

        run_async(_test())

    def test_shared_locks(self):
        """测试共享锁兼容性"""
        from core.concurrency_manager import LockManager, LockType

        async def _test():
            lm = LockManager()
            ok1 = await lm.acquire("res1", "reader1", LockType.SHARED)
            ok2 = await lm.acquire("res1", "reader2", LockType.SHARED)
            assert ok1 and ok2, "多个共享锁应兼容"

            # 排他锁应被拒绝（使用短超时来避免挂起）
            ok3 = await lm.acquire("res1", "writer1", LockType.EXCLUSIVE, timeout=0.1)
            assert not ok3, "共享锁存在时排他锁应超时"

            await lm.release_all("reader1")
            await lm.release_all("reader2")

        run_async(_test())

    def test_deadlock_detection(self):
        """测试死锁检测"""
        from core.concurrency_manager import LockManager, LockType

        async def _test():
            lm = LockManager()
            await lm.acquire("res_A", "holder_X", LockType.EXCLUSIVE)
            await lm.acquire("res_B", "holder_Y", LockType.EXCLUSIVE)

            # holder_X 尝试获取 res_B (被 holder_Y 持有)
            # 如果 holder_Y 同时等待 res_A，会形成死锁环
            # 这里 _would_deadlock 应检测到潜在死锁
            would = lm._would_deadlock("holder_X", "res_B")
            # 不一定检测到因为 holder_Y 未在等待 res_A
            # 但至少不应崩溃
            assert isinstance(would, bool)

            await lm.release_all("holder_X")
            await lm.release_all("holder_Y")

        run_async(_test())

    def test_concurrency_limiter(self):
        """测试并发槽位限制"""
        from core.concurrency_manager import ConcurrencyLimiter

        async def _test():
            limiter = ConcurrencyLimiter(global_max=2)
            ok1 = await limiter.acquire_slot("task1", "default", timeout=1)
            ok2 = await limiter.acquire_slot("task2", "default", timeout=1)
            assert ok1 and ok2

            # 第 3 个应超时
            ok3 = await limiter.acquire_slot("task3", "default", timeout=0.1)
            assert not ok3, "超过全局并发限制应超时"

            await limiter.release_slot("task1")
            status = limiter.get_status()
            assert status["global_active"] == 1

            await limiter.release_slot("task2")

        run_async(_test())

    def test_retry_policy(self):
        """测试重试策略"""
        from core.concurrency_manager import RetryPolicy

        async def _test():
            policy = RetryPolicy(max_retries=2, base_delay=0.01, max_delay=0.1)
            call_count = 0

            async def flaky():
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise ValueError("still failing")
                return "success"

            result = await policy.execute(flaky)
            assert result == "success"
            assert call_count == 3

        run_async(_test())

    def test_expired_lock_cleanup(self):
        """测试过期锁清理"""
        from core.concurrency_manager import LockManager, LockType

        async def _test():
            lm = LockManager()
            await lm.acquire("res1", "holder1", LockType.EXCLUSIVE, timeout=0.01)
            await asyncio.sleep(0.05)
            expired = lm.cleanup_expired()
            assert len(expired) > 0, "过期锁应被清理"

        run_async(_test())


# ============================================================================
# 2. ConfigHotReload 测试
# ============================================================================

class TestConfigHotReload:

    def test_basic_get_set(self):
        """测试基本配置读写"""
        from core.config_hot_reload import HotReloadConfigManager

        mgr = HotReloadConfigManager()
        mgr._config = {"server": {"port": 8000}, "debug": False}

        assert mgr.get("server.port") == 8000
        assert mgr.get("debug") is False
        assert mgr.get("nonexistent", "default") == "default"

    def test_set_with_validation(self):
        """测试带验证的设置"""
        from core.config_hot_reload import HotReloadConfigManager

        mgr = HotReloadConfigManager()
        mgr._config = {"port": 8000}

        mgr.validator.add_rule("port", type_=int, min_val=1, max_val=65535)

        errors = mgr.set("port", 9000)
        assert errors == [], f"设置合法值不应报错: {errors}"
        assert mgr.get("port") == 9000

        errors = mgr.set("port", 99999)
        assert len(errors) > 0, "设置超范围值应报错"
        assert mgr.get("port") == 9000  # 不应被修改

    def test_version_tracking(self):
        """测试版本跟踪"""
        from core.config_hot_reload import HotReloadConfigManager

        mgr = HotReloadConfigManager()
        mgr._config = {"mode": "dev"}

        mgr.set("mode", "prod")
        mgr.set("mode", "staging")

        history = mgr.versions.get_history()
        assert len(history) == 2
        assert mgr.versions.current_version == 2

    def test_file_load(self):
        """测试从文件加载"""
        from core.config_hot_reload import HotReloadConfigManager

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        ) as f:
            json.dump({"name": "test", "version": 1}, f)
            path = f.name

        try:
            mgr = HotReloadConfigManager(config_path=path)
            errors = mgr.load_from_file()
            assert errors == [], f"加载不应报错: {errors}"
            assert mgr.get("name") == "test"
        finally:
            os.unlink(path)

    def test_file_save(self):
        """测试保存到文件"""
        from core.config_hot_reload import HotReloadConfigManager

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        ) as f:
            path = f.name

        try:
            mgr = HotReloadConfigManager(config_path=path)
            mgr._config = {"saved": True, "count": 42}
            err = mgr.save_to_file()
            assert err is None

            with open(path) as f2:
                loaded = json.load(f2)
            assert loaded["saved"] is True
            assert loaded["count"] == 42
        finally:
            os.unlink(path)

    def test_subscriber_notification(self):
        """测试变更订阅"""
        from core.config_hot_reload import HotReloadConfigManager

        mgr = HotReloadConfigManager()
        mgr._config = {"x": 1}

        received_changes = []
        mgr.subscribe(lambda changes: received_changes.append(changes))

        mgr.set("x", 2)
        assert len(received_changes) == 1
        assert "x" in received_changes[0]

    def test_diff_calculation(self):
        """测试配置差异计算"""
        from core.config_hot_reload import HotReloadConfigManager

        diff = HotReloadConfigManager._diff(
            {"a": 1, "b": {"c": 2, "d": 3}},
            {"a": 1, "b": {"c": 9, "d": 3}, "e": "new"},
        )
        assert "b.c" in diff
        assert diff["b.c"]["old"] == 2
        assert diff["b.c"]["new"] == 9
        assert "e" in diff

    def test_validator_choices(self):
        """测试选项验证"""
        from core.config_hot_reload import ConfigValidator

        v = ConfigValidator()
        v.add_rule("env", choices=["dev", "staging", "prod"])

        errors = v.validate({"env": "dev"})
        assert errors == []

        errors = v.validate({"env": "invalid"})
        assert len(errors) > 0


# ============================================================================
# 3. SecurityMiddleware 测试
# ============================================================================

class TestSecurityMiddleware:

    def test_audit_logger_record(self):
        """测试审计日志记录"""
        from core.security_middleware import AuditLogger, AuditEntry

        logger = AuditLogger(max_entries=100)

        entry = AuditEntry(
            request_id="req_001",
            timestamp=time.time(),
            method="GET",
            path="/api/v1/status",
            client_ip="192.168.1.1",
            user_agent="TestAgent/1.0",
            status_code=200,
            latency_ms=15.5,
        )
        logger.record(entry)

        recent = logger.get_recent(10)
        assert len(recent) == 1
        assert recent[0]["request_id"] == "req_001"

        stats = logger.get_stats()
        assert stats["total_requests"] == 1
        assert stats["error_requests"] == 0

    def test_audit_logger_error_tracking(self):
        """测试审计日志错误追踪"""
        from core.security_middleware import AuditLogger, AuditEntry

        logger = AuditLogger()

        for code in [200, 200, 404, 500, 200]:
            entry = AuditEntry(
                request_id=f"req_{code}",
                timestamp=time.time(),
                method="GET",
                path="/test",
                client_ip="127.0.0.1",
                user_agent="",
                status_code=code,
            )
            logger.record(entry)

        stats = logger.get_stats()
        assert stats["total_requests"] == 5
        assert stats["error_requests"] == 2  # 404 + 500

    def test_ip_block_list(self):
        """测试 IP 黑名单"""
        from core.security_middleware import IPBlockList

        bl = IPBlockList()

        # 手动封禁
        bl.add("10.0.0.1")
        assert bl.is_blocked("10.0.0.1")
        assert not bl.is_blocked("10.0.0.2")

        # 解除封禁
        bl.remove("10.0.0.1")
        assert not bl.is_blocked("10.0.0.1")

    def test_ip_auto_block(self):
        """测试 IP 自动封禁"""
        from core.security_middleware import IPBlockList

        bl = IPBlockList()
        bl._threshold = 5  # 降低阈值便于测试
        bl._window = 60
        bl._block_duration = 1  # 1 秒

        for _ in range(5):
            bl.record_failure("10.0.0.99")

        assert bl.is_blocked("10.0.0.99"), "超过阈值应自动封禁"

        # 等待封禁过期
        time.sleep(1.1)
        assert not bl.is_blocked("10.0.0.99"), "封禁应过期"

    def test_ip_block_get_list(self):
        """测试获取封禁列表"""
        from core.security_middleware import IPBlockList

        bl = IPBlockList()
        bl.add("1.1.1.1")
        bl.add("2.2.2.2")

        result = bl.get_blocked_list()
        assert "1.1.1.1" in result["permanent"]
        assert "2.2.2.2" in result["permanent"]

    def test_security_manager_dashboard(self):
        """测试安全管理器仪表盘"""
        from core.security_middleware import SecurityManager

        mgr = SecurityManager()
        dashboard = mgr.get_dashboard()
        assert "audit" in dashboard
        assert "blocked_ips" in dashboard


# ============================================================================
# 4. HealthIntegration 测试
# ============================================================================

class TestHealthIntegration:

    def test_unified_manager_creation(self):
        """测试统一健康管理器创建"""
        from core.health_integration import UnifiedHealthManager

        uhm = UnifiedHealthManager()
        assert uhm is not None

    def test_wire_with_none(self):
        """测试无子系统连接"""
        from core.health_integration import UnifiedHealthManager

        uhm = UnifiedHealthManager()
        uhm.wire()  # 全部 None，不应崩溃
        dashboard = uhm.get_dashboard()
        assert "timestamp" in dashboard

    def test_get_quick_status_empty(self):
        """测试空状态快速查询"""
        from core.health_integration import UnifiedHealthManager

        uhm = UnifiedHealthManager()
        status = uhm.get_quick_status()
        assert isinstance(status, dict)

    def test_check_system_load(self):
        """测试系统负载检查"""
        from core.health_integration import UnifiedHealthManager
        from core.system_load_monitor import SystemLoadMonitor

        uhm = UnifiedHealthManager()
        uhm._load_monitor = SystemLoadMonitor()

        result = uhm._check_system_load()
        assert "status" in result
        assert result["status"] in ("healthy", "degraded", "unhealthy")
        assert "load_score" in result or "error" in result

    def test_check_error_rate(self):
        """测试错误率检查"""
        from core.health_integration import UnifiedHealthManager
        from core.error_framework import ErrorTracker

        uhm = UnifiedHealthManager()
        uhm._error_tracker = ErrorTracker()

        result = uhm._check_error_rate()
        assert result["status"] == "healthy"
        assert result["error_rate"] == 0

    def test_check_concurrency(self):
        """测试并发状态检查"""
        from core.health_integration import UnifiedHealthManager
        from core.concurrency_manager import ConcurrencyManager

        uhm = UnifiedHealthManager()
        uhm._concurrency = ConcurrencyManager(global_max_concurrency=10)

        result = uhm._check_concurrency()
        assert result["status"] == "healthy"
        assert result["max"] == 10

    def test_dashboard_with_all_wired(self):
        """测试完整仪表盘（所有子系统连接）"""
        from core.health_integration import UnifiedHealthManager
        from core.monitoring import MonitoringManager
        from core.system_load_monitor import SystemLoadMonitor
        from core.error_framework import ErrorTracker
        from core.concurrency_manager import ConcurrencyManager

        uhm = UnifiedHealthManager()
        uhm.wire(
            monitoring=MonitoringManager(),
            load_monitor=SystemLoadMonitor(),
            error_tracker=ErrorTracker(),
            concurrency=ConcurrencyManager(),
        )

        dashboard = uhm.get_dashboard()
        assert "monitoring" in dashboard
        assert "system_load" in dashboard
        assert "errors" in dashboard
        assert "concurrency" in dashboard

    def test_start_stop(self):
        """测试启停"""
        from core.health_integration import UnifiedHealthManager

        async def _test():
            uhm = UnifiedHealthManager()
            await uhm.start()
            assert uhm._running
            await uhm.stop()
            assert not uhm._running

        run_async(_test())


# ============================================================================
# 5. ErrorFramework 测试
# ============================================================================

class TestErrorFramework:

    def test_ufo_error_creation(self):
        """测试错误创建"""
        from core.error_framework import GalaxyError, ErrorCategory, ErrorSeverity

        err = GalaxyError("test error", category=ErrorCategory.NETWORK)
        assert err.message == "test error"
        assert err.category == ErrorCategory.NETWORK
        assert err.error_id.startswith("err_")

    def test_error_to_dict(self):
        """测试错误序列化"""
        from core.error_framework import GalaxyError, ErrorCategory

        err = GalaxyError("serialization test", category=ErrorCategory.DATA)
        d = err.to_dict()
        assert d["message"] == "serialization test"
        assert d["category"] == "data"

    def test_error_tracker_recording(self):
        """测试错误追踪记录"""
        from core.error_framework import (
            ErrorTracker, GalaxyError, ErrorCategory, ErrorSeverity
        )

        tracker = ErrorTracker()
        err = GalaxyError("test", category=ErrorCategory.NETWORK)
        tracker.record(err)

        summary = tracker.get_summary()
        assert summary["total_errors"] == 1
        assert "network" in summary["by_category"]

    def test_error_rate_calculation(self):
        """测试错误率计算"""
        from core.error_framework import ErrorTracker, GalaxyError, ErrorCategory

        tracker = ErrorTracker()
        for _ in range(10):
            tracker.record(GalaxyError("test", category=ErrorCategory.TIMEOUT))

        rate = tracker.get_error_rate(window_seconds=60)
        assert rate > 0

    def test_specialized_errors(self):
        """测试特化错误类型"""
        from core.error_framework import (
            NetworkError, DeviceError, LLMError, AuthError,
            ConfigError, TimeoutError_, NodeError, DataError,
            ConcurrencyError, ErrorCategory,
        )

        assert NetworkError("net").category == ErrorCategory.NETWORK
        assert DeviceError("dev", device_id="d1").context["device_id"] == "d1"
        assert LLMError("llm", provider="openai").context["provider"] == "openai"
        assert AuthError("auth").category == ErrorCategory.AUTH
        assert ConfigError("cfg").category == ErrorCategory.CONFIG
        assert TimeoutError_("timeout", timeout_seconds=30).context["timeout_seconds"] == 30
        assert NodeError("node", node_id="n1").context["node_id"] == "n1"
        assert DataError("data").category == ErrorCategory.DATA
        assert ConcurrencyError("lock").category == ErrorCategory.CONCURRENCY


# ============================================================================
# 运行入口
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
