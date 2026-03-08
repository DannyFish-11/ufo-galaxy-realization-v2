"""
Tests for core.unified_coordinator — 统一设备协调器
"""

import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: run async in sync tests
# ---------------------------------------------------------------------------

def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================================
# 1. SharedDataStore
# ============================================================================

class TestSharedDataStore:

    def test_set_and_get(self, tmp_path):
        from core.shared_data_store import SharedDataStore
        store = SharedDataStore(path=str(tmp_path / "data.json"))

        store.set("key1", {"hello": "world"})
        assert store.get("key1") == {"hello": "world"}

    def test_persistence(self, tmp_path):
        from core.shared_data_store import SharedDataStore
        path = str(tmp_path / "data.json")

        store1 = SharedDataStore(path=path)
        store1.set("persist_key", 42)
        assert os.path.exists(path)

        # Simulate restart
        store2 = SharedDataStore(path=path)
        assert store2.get("persist_key") == 42

    def test_get_missing_key(self, tmp_path):
        from core.shared_data_store import SharedDataStore
        store = SharedDataStore(path=str(tmp_path / "data.json"))
        assert store.get("nonexistent") is None

    def test_overwrite(self, tmp_path):
        from core.shared_data_store import SharedDataStore
        store = SharedDataStore(path=str(tmp_path / "data.json"))
        store.set("k", "v1")
        store.set("k", "v2")
        assert store.get("k") == "v2"


# ============================================================================
# 2. TaskOrchestrator
# ============================================================================

class TestTaskOrchestrator:

    def test_analyze_task_clipboard(self):
        from core.task_orchestrator import TaskOrchestrator
        orch = TaskOrchestrator()
        assert orch._analyze_task("把手机剪贴板复制到电脑") == "clipboard_sync"

    def test_analyze_task_file(self):
        from core.task_orchestrator import TaskOrchestrator
        orch = TaskOrchestrator()
        assert orch._analyze_task("传输文件到手机") == "file_transfer"

    def test_analyze_task_media(self):
        from core.task_orchestrator import TaskOrchestrator
        orch = TaskOrchestrator()
        assert orch._analyze_task("暂停所有设备的音乐") == "media_control"

    def test_analyze_task_notification(self):
        from core.task_orchestrator import TaskOrchestrator
        orch = TaskOrchestrator()
        assert orch._analyze_task("通知所有设备") == "notification_sync"

    def test_analyze_task_generic(self):
        from core.task_orchestrator import TaskOrchestrator
        orch = TaskOrchestrator()
        assert orch._analyze_task("打开设置") == "generic"

    def test_parse_devices_default(self):
        from core.task_orchestrator import TaskOrchestrator
        from core.device_types import DeviceType
        orch = TaskOrchestrator()
        src, tgt = orch._parse_devices("做一些事情")
        assert src == DeviceType.ANDROID
        assert tgt == DeviceType.WINDOWS

    def test_parse_media_action(self):
        from core.task_orchestrator import TaskOrchestrator
        orch = TaskOrchestrator()
        assert orch._parse_media_action("暂停") == "pause_media"
        assert orch._parse_media_action("播放音乐") == "play_media"
        assert orch._parse_media_action("静音") == "mute"

    def test_clipboard_no_devices(self):
        from core.task_orchestrator import TaskOrchestrator
        mock_comm = MagicMock()
        mock_comm.list_connected_devices.return_value = []
        orch = TaskOrchestrator(device_comm=mock_comm)
        result = _run(orch.sync_clipboard("复制到电脑"))
        assert result["success"] is False

    def test_media_no_devices(self):
        from core.task_orchestrator import TaskOrchestrator
        mock_comm = MagicMock()
        mock_comm.list_connected_devices.return_value = []
        orch = TaskOrchestrator(device_comm=mock_comm)
        result = _run(orch.sync_media_control("暂停所有"))
        assert result["success"] is False

    def test_notification_no_devices(self):
        from core.task_orchestrator import TaskOrchestrator
        mock_comm = MagicMock()
        mock_comm.list_connected_devices.return_value = []
        orch = TaskOrchestrator(device_comm=mock_comm)
        result = _run(orch.broadcast_notification("测试通知"))
        assert result["success"] is False


# ============================================================================
# 3. SessionManager
# ============================================================================

class TestSessionManager:

    def test_create_and_remove_session(self):
        from core.unified_coordinator import SessionManager
        mgr = SessionManager()
        ws = MagicMock()
        session = _run(mgr.create_session(ws, "127.0.0.1"))

        assert session.session_id in mgr.sessions
        assert session.ip_address == "127.0.0.1"
        assert not session.is_authenticated

        removed = _run(mgr.remove_session(session.session_id))
        assert removed is session
        assert session.session_id not in mgr.sessions

    def test_authenticate_session(self):
        from core.unified_coordinator import SessionManager
        mgr = SessionManager()
        ws = MagicMock()
        session = _run(mgr.create_session(ws))

        ok = _run(mgr.authenticate_session(session.session_id, "device_001"))
        assert ok is True
        assert session.is_authenticated
        assert session.device_id == "device_001"
        assert mgr.device_sessions["device_001"] == session.session_id

    def test_authenticate_replaces_old_session(self):
        from core.unified_coordinator import SessionManager
        mgr = SessionManager()

        ws1 = MagicMock()
        ws2 = MagicMock()
        s1 = _run(mgr.create_session(ws1))
        s2 = _run(mgr.create_session(ws2))

        _run(mgr.authenticate_session(s1.session_id, "device_001"))
        _run(mgr.authenticate_session(s2.session_id, "device_001"))

        # Old session should be removed
        assert s1.session_id not in mgr.sessions
        assert mgr.device_sessions["device_001"] == s2.session_id

    def test_send_to_device(self):
        from core.unified_coordinator import SessionManager
        mgr = SessionManager()
        ws = MagicMock()
        ws.send_text = AsyncMock()

        session = _run(mgr.create_session(ws))
        _run(mgr.authenticate_session(session.session_id, "dev_1"))

        ok = _run(mgr.send_to_device("dev_1", {"action": "test"}))
        assert ok is True
        ws.send_text.assert_called_once()

    def test_send_to_unknown_device(self):
        from core.unified_coordinator import SessionManager
        mgr = SessionManager()
        ok = _run(mgr.send_to_device("nonexistent", {"action": "test"}))
        assert ok is False

    def test_broadcast(self):
        from core.unified_coordinator import SessionManager
        mgr = SessionManager()

        ws1 = MagicMock()
        ws1.send_text = AsyncMock()
        ws2 = MagicMock()
        ws2.send_text = AsyncMock()

        s1 = _run(mgr.create_session(ws1))
        s2 = _run(mgr.create_session(ws2))
        _run(mgr.authenticate_session(s1.session_id, "dev_1"))
        _run(mgr.authenticate_session(s2.session_id, "dev_2"))

        results = _run(mgr.broadcast({"action": "ping"}))
        assert results["dev_1"] is True
        assert results["dev_2"] is True

    def test_broadcast_with_exclude(self):
        from core.unified_coordinator import SessionManager
        mgr = SessionManager()

        ws1 = MagicMock()
        ws1.send_text = AsyncMock()
        ws2 = MagicMock()
        ws2.send_text = AsyncMock()

        s1 = _run(mgr.create_session(ws1))
        s2 = _run(mgr.create_session(ws2))
        _run(mgr.authenticate_session(s1.session_id, "dev_1"))
        _run(mgr.authenticate_session(s2.session_id, "dev_2"))

        results = _run(mgr.broadcast({"action": "ping"}, exclude_devices=["dev_1"]))
        assert "dev_1" not in results
        assert results["dev_2"] is True

    def test_cleanup_stale(self):
        from core.unified_coordinator import SessionManager
        import time as _time

        mgr = SessionManager(session_timeout=1)
        ws = MagicMock()
        session = _run(mgr.create_session(ws))
        _run(mgr.authenticate_session(session.session_id, "dev_stale"))

        # Manually expire the session
        session.last_activity = _time.time() - 100

        removed = _run(mgr.cleanup_stale())
        assert removed == 1
        assert session.session_id not in mgr.sessions
        assert "dev_stale" not in mgr.device_sessions

    def test_statistics(self):
        from core.unified_coordinator import SessionManager
        mgr = SessionManager()
        ws = MagicMock()
        ws.send_text = AsyncMock()
        s = _run(mgr.create_session(ws))
        _run(mgr.authenticate_session(s.session_id, "dev_x"))

        stats = mgr.get_statistics()
        assert stats["total_sessions"] == 1
        assert stats["authenticated_sessions"] == 1
        assert stats["active_devices"] == 1


# ============================================================================
# 4. UnifiedDeviceCoordinator
# ============================================================================

class TestUnifiedDeviceCoordinator:

    def _make_coordinator(self):
        """创建协调器实例（绕过单例）"""
        from core.unified_coordinator import UnifiedDeviceCoordinator
        # Reset singleton
        UnifiedDeviceCoordinator._instance = None
        coord = UnifiedDeviceCoordinator()
        return coord

    def test_instantiation(self):
        coord = self._make_coordinator()
        assert coord._orchestrator is not None
        assert coord._session_manager is not None
        assert coord._shared_data is not None

    def test_shared_data(self):
        coord = self._make_coordinator()
        coord.set_shared_data("test", {"value": 123})
        assert coord.get_shared_data("test") == {"value": 123}

    def test_device_state(self):
        coord = self._make_coordinator()
        coord.update_device_state("dev_1", {"battery": 80})
        state = coord.get_device_state("dev_1")
        assert state["battery"] == 80

    def test_get_status(self):
        coord = self._make_coordinator()
        status = coord.get_status()
        assert status["type"] == "unified_coordinator"
        assert "session_manager" in status

    def test_session_lifecycle(self):
        coord = self._make_coordinator()
        ws = MagicMock()
        ws.send_text = AsyncMock()

        session = _run(coord.create_session(ws, "192.168.1.1"))
        assert session is not None

        ok = _run(coord.authenticate_session(session.session_id, "dev_1"))
        assert ok is True

        removed = _run(coord.remove_session(session.session_id))
        assert removed is not None

    def test_cleanup(self):
        coord = self._make_coordinator()
        count = _run(coord.cleanup())
        assert count == 0  # No stale sessions

    def test_graceful_degradation_without_node71(self):
        """容错层不可用时应降级而非崩溃"""
        coord = self._make_coordinator()
        # fault_tolerance may or may not be available
        status = coord.get_status()
        assert "fault_tolerance_available" in status


# ============================================================================
# 5. 向后兼容性测试
# ============================================================================

class TestBackwardCompatibility:

    def test_cross_device_coordinator_import(self):
        """原有导入路径仍可用"""
        from galaxy_gateway.cross_device_coordinator import cross_device_coordinator
        assert cross_device_coordinator is not None
        assert hasattr(cross_device_coordinator, "execute_cross_device_task")
        assert hasattr(cross_device_coordinator, "set_shared_data")
        assert hasattr(cross_device_coordinator, "get_shared_data")

    def test_cross_device_coordinator_class_import(self):
        """CrossDeviceCoordinator 类仍可导入"""
        from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator
        assert CrossDeviceCoordinator is not None

    def test_shared_data_via_wrapper(self):
        """包装器的共享数据功能正常"""
        from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator
        cdc = CrossDeviceCoordinator.__new__(CrossDeviceCoordinator)
        cdc.shared_clipboard = {}
        cdc.device_states = {}
        cdc._delegate = None

        with tempfile.TemporaryDirectory() as tmp:
            cdc._SHARED_DATA_PATH = os.path.join(tmp, "test_shared.json")
            cdc.set_shared_data("compat_key", "compat_value")
            assert os.path.exists(cdc._SHARED_DATA_PATH)
            assert cdc.get_shared_data("compat_key") == "compat_value"

            # Simulate restart
            cdc2 = CrossDeviceCoordinator.__new__(CrossDeviceCoordinator)
            cdc2.shared_clipboard = {}
            cdc2.device_states = {}
            cdc2._delegate = None
            cdc2._SHARED_DATA_PATH = cdc._SHARED_DATA_PATH
            cdc2._load_shared_data()
            assert cdc2.get_shared_data("compat_key") == "compat_value"

    def test_device_protocol_importable(self):
        """AIP v2.0 协议模块仍可导入"""
        from enhancements.multidevice.device_protocol import AIPMessage, MessageType
        assert AIPMessage is not None
        assert MessageType is not None

    def test_unified_coordinator_singleton(self):
        """单例模式正确"""
        from core.unified_coordinator import get_unified_coordinator, UnifiedDeviceCoordinator
        UnifiedDeviceCoordinator._instance = None
        c1 = get_unified_coordinator()
        c2 = get_unified_coordinator()
        assert c1 is c2
        # Cleanup
        UnifiedDeviceCoordinator._instance = None


# ============================================================================
# 6. AIP v3.0 协议集成测试
# ============================================================================

class TestAIPv3Integration:

    def _make_coordinator(self):
        from core.unified_coordinator import UnifiedDeviceCoordinator
        UnifiedDeviceCoordinator._instance = None
        return UnifiedDeviceCoordinator()

    def test_protocol_info(self):
        """协议信息正确"""
        coord = self._make_coordinator()
        info = coord.get_protocol_info()
        assert info["canonical_version"] == "3.0"
        assert "1.0" in info["supported_versions"]
        assert "2.0" in info["supported_versions"]
        assert "3.0" in info["supported_versions"]
        assert info["message_types"] > 0

    def test_handle_v3_register_message(self):
        """处理 AIP v3.0 设备注册消息"""
        coord = self._make_coordinator()
        ws = MagicMock()
        ws.send_text = AsyncMock()

        session = _run(coord.create_session(ws, "192.168.1.1"))

        register_msg = {
            "version": "3.0",
            "type": "device_register",
            "device_id": "android_001",
            "device_type": "android_phone",
            "payload": {"device_info": {"model": "Pixel 8"}},
        }
        result = _run(coord.handle_device_message(session.session_id, register_msg))
        assert result is not None
        assert result["success"] is True
        assert result["device_id"] == "android_001"
        assert result["type"] == "device_register_ack"

    def test_handle_v3_heartbeat_message(self):
        """处理 AIP v3.0 心跳消息"""
        coord = self._make_coordinator()
        ws = MagicMock()
        ws.send_text = AsyncMock()

        session = _run(coord.create_session(ws))
        _run(coord.authenticate_session(session.session_id, "dev_hb"))

        heartbeat_msg = {
            "version": "3.0",
            "type": "heartbeat",
            "device_id": "dev_hb",
        }
        result = _run(coord.handle_device_message(session.session_id, heartbeat_msg))
        assert result is not None
        assert result["type"] == "heartbeat_ack"
        assert "timestamp" in result

    def test_handle_v2_message_compat(self):
        """处理 AIP v2.0 消息（自动转换到 v3.0）"""
        coord = self._make_coordinator()
        ws = MagicMock()
        ws.send_text = AsyncMock()

        session = _run(coord.create_session(ws))

        v2_msg = {
            "version": "2.0",
            "type": "device_register",
            "device_id": "legacy_device",
            "payload": {},
        }
        result = _run(coord.handle_device_message(session.session_id, v2_msg))
        assert result is not None
        assert result["success"] is True
        assert result["device_id"] == "legacy_device"

    def test_handle_v1_legacy_message(self):
        """处理 AIP v1.0 旧版消息（自动转换到 v3.0）"""
        coord = self._make_coordinator()
        ws = MagicMock()
        ws.send_text = AsyncMock()

        session = _run(coord.create_session(ws))

        v1_msg = {
            "type": "register",
            "device_id": "old_device",
            "payload": {},
        }
        result = _run(coord.handle_device_message(session.session_id, v1_msg))
        assert result is not None
        assert result["success"] is True
        assert result["device_id"] == "old_device"

    def test_handle_json_string_message(self):
        """支持 JSON 字符串输入"""
        import json as _json
        coord = self._make_coordinator()
        ws = MagicMock()
        ws.send_text = AsyncMock()

        session = _run(coord.create_session(ws))

        msg_str = _json.dumps({
            "version": "3.0",
            "type": "heartbeat",
            "device_id": "dev_str",
        })
        result = _run(coord.handle_device_message(session.session_id, msg_str))
        assert result is not None
        assert result["type"] == "heartbeat_ack"

    def test_send_aip_message(self):
        """发送 AIP v3.0 消息"""
        coord = self._make_coordinator()
        ws = MagicMock()
        ws.send_text = AsyncMock()

        session = _run(coord.create_session(ws))
        _run(coord.authenticate_session(session.session_id, "dev_aip"))

        from galaxy_gateway.protocol.aip_v3 import (
            AIPMessage, MessageType as AIPMessageType, create_heartbeat_message
        )
        aip_msg = create_heartbeat_message("dev_aip")
        ok = _run(coord.send_to_device("dev_aip", aip_msg))
        assert ok is True
        ws.send_text.assert_called_once()
        # Verify the sent data is valid AIP v3.0 JSON
        import json as _json
        sent_data = ws.send_text.call_args[0][0]
        parsed = _json.loads(sent_data)
        assert parsed["version"] == "3.0"
        assert parsed["type"] == "heartbeat"

    def test_handle_unknown_type_returns_ack(self):
        """未知消息类型返回默认 ACK"""
        coord = self._make_coordinator()
        ws = MagicMock()
        ws.send_text = AsyncMock()

        session = _run(coord.create_session(ws))

        msg = {
            "version": "3.0",
            "type": "gui_click",
            "device_id": "dev_x",
            "payload": {"x": 100, "y": 200},
        }
        result = _run(coord.handle_device_message(session.session_id, msg))
        assert result is not None
        assert result["type"] == "ack"
        assert result["version"] == "3.0"


# ============================================================================
# 7. Node_71 容错层集成测试
# ============================================================================

class TestNode71Integration:

    def test_fault_tolerance_importable(self):
        """Node_71 容错模块可从项目根导入"""
        from nodes.Node_71_MultiDeviceCoordination.core.fault_tolerance import (
            FaultToleranceLayer, CircuitBreakerConfig, RetryConfig, FailoverConfig,
        )
        ft = FaultToleranceLayer(
            circuit_config=CircuitBreakerConfig(),
            retry_config=RetryConfig(),
            failover_config=FailoverConfig(),
        )
        assert ft is not None

    def test_coordinator_has_fault_tolerance(self):
        """统一协调器成功加载容错层"""
        from core.unified_coordinator import UnifiedDeviceCoordinator
        UnifiedDeviceCoordinator._instance = None
        coord = UnifiedDeviceCoordinator()
        assert coord._fault_tolerance is not None
        status = coord.get_status()
        assert status["fault_tolerance_available"] is True
        UnifiedDeviceCoordinator._instance = None

    def test_circuit_breaker_functionality(self):
        """熔断器功能验证"""
        from nodes.Node_71_MultiDeviceCoordination.core.fault_tolerance import (
            CircuitBreaker, CircuitBreakerConfig, CircuitState,
        )
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=2))
        assert cb.state == CircuitState.CLOSED
        # Record failures
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
