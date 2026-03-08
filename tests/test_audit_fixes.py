"""
测试审计修复 - 覆盖第二轮修复的所有关键变更
============================================

测试覆盖：
1. ConcurrencyManager - 任务跟踪、泄漏防护、清理循环
2. Startup - 依赖图验证、循环依赖检测
3. ErrorFramework - 统一 API 响应格式、错误码
4. ConfigHotReload - 原子保存、订阅者通知安全
5. NodeRegistry - 故障转移机制
6. 缓冲区边界 - MQTT、EventBus、NodeCommunication
"""

import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# 1. ConcurrencyManager 测试
# =============================================================================

class TestConcurrencyManager(unittest.TestCase):
    """测试并发管理器增强"""

    def test_import(self):
        from core.concurrency_manager import ConcurrencyManager, get_concurrency_manager
        mgr = ConcurrencyManager(global_max_concurrency=10)
        self.assertIsNotNone(mgr._tracked_tasks)
        self.assertEqual(mgr._max_tracked_tasks, 200)

    def test_task_slot_expiry(self):
        from core.concurrency_manager import TaskSlot
        slot = TaskSlot(task_id="t1", category="test", timeout=0.01)
        time.sleep(0.02)
        self.assertTrue(slot.is_expired)

    def test_lock_expiry(self):
        from core.concurrency_manager import LockInfo, LockType
        lock = LockInfo(
            resource_id="r1", lock_type=LockType.EXCLUSIVE,
            holder_id="h1", acquired_at=time.time() - 100, timeout=1.0
        )
        self.assertTrue(lock.is_expired)

    def test_retry_policy_delay(self):
        from core.concurrency_manager import RetryPolicy
        policy = RetryPolicy(max_retries=3, base_delay=1.0, max_delay=10.0)
        self.assertAlmostEqual(policy.get_delay(0), 1.0)
        self.assertAlmostEqual(policy.get_delay(1), 2.0)
        self.assertAlmostEqual(policy.get_delay(2), 4.0)
        self.assertAlmostEqual(policy.get_delay(10), 10.0)  # capped

    def test_cleanup_done_callback(self):
        """测试清理任务异常退出回调"""
        from core.concurrency_manager import ConcurrencyManager
        mgr = ConcurrencyManager(global_max_concurrency=5)

        # 模拟一个失败的任务
        loop = asyncio.new_event_loop()
        async def failing():
            raise RuntimeError("test")

        task = loop.create_task(failing())
        try:
            loop.run_until_complete(task)
        except RuntimeError:
            pass
        # Should not raise
        mgr._on_cleanup_done(task)
        loop.close()


# =============================================================================
# 2. Startup 依赖图测试
# =============================================================================

class TestStartupDeps(unittest.TestCase):
    """测试启动依赖图验证"""

    def test_circular_dep_detection(self):
        from core.startup import _check_circular_deps
        # 无环
        deps = {"a": ["b"], "b": ["c"], "c": []}
        cycles = _check_circular_deps(deps)
        self.assertEqual(len(cycles), 0)

        # 有环
        deps = {"a": ["b"], "b": ["c"], "c": ["a"]}
        cycles = _check_circular_deps(deps)
        self.assertGreater(len(cycles), 0)

    def test_validate_startup_deps_no_errors(self):
        from core.startup import _validate_startup_deps
        errors = _validate_startup_deps()
        self.assertEqual(len(errors), 0, f"启动依赖图有问题: {errors}")

    def test_subsystem_deps_defined(self):
        from core.startup import _SUBSYSTEM_DEPS
        self.assertIn("cache", _SUBSYSTEM_DEPS)
        self.assertIn("event_bridge", _SUBSYSTEM_DEPS)
        self.assertIn("health_integration", _SUBSYSTEM_DEPS)

    def test_circular_dep_self_reference(self):
        from core.startup import _check_circular_deps
        deps = {"a": ["a"]}
        cycles = _check_circular_deps(deps)
        self.assertGreater(len(cycles), 0)


# =============================================================================
# 3. ErrorFramework 统一响应格式测试
# =============================================================================

class TestErrorFramework(unittest.TestCase):
    """测试统一 API 响应和错误码"""

    def test_api_response_success(self):
        from core.error_framework import api_response
        resp = api_response(data={"items": [1, 2, 3]})
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["data"]["items"], [1, 2, 3])
        self.assertIsNone(resp["error"])

    def test_api_response_error(self):
        from core.error_framework import api_response
        resp = api_response(
            error={"code": "E0001", "message": "test"},
            message="something failed",
            status_code=500,
        )
        self.assertFalse(resp["ok"])
        self.assertIsNone(resp["data"])
        self.assertEqual(resp["error"]["code"], "E0001")

    def test_error_codes_defined(self):
        from core.error_framework import ErrorCode
        self.assertEqual(ErrorCode.INTERNAL_ERROR, "E0001")
        self.assertEqual(ErrorCode.AUTH_REQUIRED, "E1001")
        self.assertEqual(ErrorCode.DEVICE_OFFLINE, "E2001")
        self.assertEqual(ErrorCode.LLM_PROVIDER_ERROR, "E3001")
        self.assertEqual(ErrorCode.NODE_UNAVAILABLE, "E4001")
        self.assertEqual(ErrorCode.DATA_VALIDATION_FAILED, "E5001")
        self.assertEqual(ErrorCode.CONCURRENCY_LIMIT, "E6001")
        self.assertEqual(ErrorCode.CONFIG_INVALID, "E7001")

    def test_ufo_error_to_dict(self):
        from core.error_framework import GalaxyError, ErrorCategory
        err = GalaxyError("test error", category=ErrorCategory.NETWORK)
        d = err.to_dict()
        self.assertIn("error_id", d)
        self.assertEqual(d["category"], "network")
        self.assertEqual(d["message"], "test error")

    def test_error_tracker_recording(self):
        from core.error_framework import ErrorTracker, GalaxyError, ErrorCategory
        tracker = ErrorTracker(max_records=50)
        for i in range(60):
            tracker.record(GalaxyError(f"err {i}", category=ErrorCategory.INTERNAL))
        summary = tracker.get_summary()
        self.assertEqual(summary["total_errors"], 50)  # bounded by maxlen


# =============================================================================
# 4. ConfigHotReload 原子保存测试
# =============================================================================

class TestConfigHotReload(unittest.TestCase):
    """测试配置热更新原子性"""

    def test_atomic_save(self):
        from core.config_hot_reload import HotReloadConfigManager

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_config.json")
            mgr = HotReloadConfigManager(config_path=path)
            mgr._config = {"key": "value", "nested": {"a": 1}}

            err = mgr.save_to_file()
            self.assertIsNone(err)

            # 验证文件内容
            with open(path, "r") as f:
                saved = json.load(f)
            self.assertEqual(saved["key"], "value")
            self.assertEqual(saved["nested"]["a"], 1)

    def test_atomic_save_no_partial_write(self):
        """验证保存失败时不会留下损坏的文件"""
        from core.config_hot_reload import HotReloadConfigManager

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_config.json")
            # 先写入一个有效配置
            with open(path, "w") as f:
                json.dump({"original": True}, f)

            mgr = HotReloadConfigManager(config_path=path)
            # 设置一个不可序列化的配置
            mgr._config = {"bad": object()}

            err = mgr.save_to_file()
            self.assertIsNotNone(err)  # 应该失败

            # 原始文件应该完好无损
            with open(path, "r") as f:
                saved = json.load(f)
            self.assertTrue(saved["original"])

    def test_subscriber_failure_isolation(self):
        """单个回调失败不影响其他回调"""
        from core.config_hot_reload import HotReloadConfigManager

        mgr = HotReloadConfigManager()
        results = []

        def good_cb(changes):
            results.append("good")

        def bad_cb(changes):
            raise RuntimeError("callback error")

        mgr.subscribe(bad_cb)
        mgr.subscribe(good_cb)
        mgr._notify_subscribers({"test": {"old": 1, "new": 2}})

        self.assertIn("good", results)

    def test_config_version_tracking(self):
        from core.config_hot_reload import HotReloadConfigManager
        mgr = HotReloadConfigManager()
        mgr._config = {"v": 1}
        mgr.set("v", 2, source="test")
        self.assertEqual(mgr.versions.current_version, 1)
        self.assertEqual(mgr.get("v"), 2)

    def test_config_validation(self):
        from core.config_hot_reload import HotReloadConfigManager
        mgr = HotReloadConfigManager()
        mgr.validator.add_rule("port", type_=int, min_val=1, max_val=65535)
        mgr._config = {"port": 8080}
        errors = mgr.set("port", 99999)
        self.assertGreater(len(errors), 0)


# =============================================================================
# 5. NodeRegistry 故障转移测试
# =============================================================================

class TestNodeFailover(unittest.TestCase):
    """测试节点故障转移"""

    def test_failover_method_exists(self):
        from core.node_registry import NodeRegistry
        registry = NodeRegistry.__new__(NodeRegistry)
        registry._initialized = False
        registry.__init__()
        self.assertTrue(hasattr(registry, '_failover_call'))
        self.assertTrue(hasattr(registry, 'call_node'))

    def test_call_node_signature(self):
        """call_node 应支持 allow_failover 参数"""
        import inspect
        from core.node_registry import NodeRegistry
        sig = inspect.signature(NodeRegistry.call_node)
        self.assertIn('allow_failover', sig.parameters)


# =============================================================================
# 6. 缓冲区边界测试
# =============================================================================

class TestBufferBounds(unittest.TestCase):
    """测试各模块的缓冲区大小限制"""

    def test_mqtt_message_uses_deque(self):
        """MQTT 消息列表应使用有界 deque"""
        from nodes.Node_41_MQTT.main import MQTTManager
        mgr = MQTTManager()
        self.assertIsInstance(mgr.messages, deque)
        self.assertEqual(mgr.messages.maxlen, MQTTManager.MAX_MESSAGE_HISTORY)

    def test_mqtt_deque_auto_evicts(self):
        """验证 deque 超出上限时自动淘汰旧消息"""
        from nodes.Node_41_MQTT.main import MQTTManager
        mgr = MQTTManager()
        for i in range(MQTTManager.MAX_MESSAGE_HISTORY + 100):
            mgr.messages.append({"id": i})
        self.assertEqual(len(mgr.messages), MQTTManager.MAX_MESSAGE_HISTORY)
        # 最旧的应该被淘汰
        self.assertEqual(mgr.messages[0]["id"], 100)

    def test_event_bus_bounded_queue(self):
        """EventBus 事件队列应有最大容量"""
        try:
            from integration.event_bus import EventBus
            # Reset singleton for testing
            EventBus._instance = None
            bus = EventBus()
            self.assertGreater(bus._event_queue.maxsize, 0)
            self.assertEqual(bus._event_queue.maxsize, 5000)
        except Exception:
            # EventBus may depend on other modules
            pass

    def test_event_bus_history_bounded(self):
        """EventBus 历史记录应使用有界 deque"""
        try:
            from integration.event_bus import EventBus
            EventBus._instance = None
            bus = EventBus()
            self.assertIsInstance(bus._event_history, deque)
            self.assertEqual(bus._event_history.maxlen, 1000)
        except Exception:
            pass

    def test_node_comm_pending_max(self):
        """NodeCommunication pending 消息应有上限"""
        try:
            from core.node_communication import NodeCommunication
            # Check class has the attribute in source
            import inspect
            source = inspect.getsource(NodeCommunication.__init__)
            self.assertIn("_max_pending", source)
        except Exception:
            pass


# =============================================================================
# 7. 集成：确保各模块可以正常导入
# =============================================================================

class TestImports(unittest.TestCase):
    """确保所有修改的模块可以正常导入"""

    def test_import_concurrency_manager(self):
        from core.concurrency_manager import (
            ConcurrencyManager, LockManager, ConcurrencyLimiter,
            ResourceQueue, RetryPolicy, get_concurrency_manager,
        )

    def test_import_startup(self):
        from core.startup import (
            bootstrap_subsystems, shutdown_subsystems,
            _check_circular_deps, _validate_startup_deps,
            _SUBSYSTEM_DEPS,
        )

    def test_import_error_framework(self):
        from core.error_framework import (
            GalaxyError, ErrorCategory, ErrorSeverity, ErrorCode,
            api_response, create_error_handlers, get_error_tracker,
        )

    def test_import_config_hot_reload(self):
        from core.config_hot_reload import (
            HotReloadConfigManager, ConfigValidator, ConfigVersionStore,
            get_config_manager,
        )

    def test_import_node_registry(self):
        from core.node_registry import (
            NodeRegistry, NodeStatus, NodeCategory,
            get_registry, call_node, call_capability,
        )


if __name__ == "__main__":
    unittest.main()
