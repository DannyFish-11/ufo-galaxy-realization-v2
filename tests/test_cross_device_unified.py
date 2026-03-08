"""
Cross-Device Unified System Integration Tests
==============================================

验证以下全链路能力：
1. 统一 DeviceType 定义 — 所有子系统使用同一来源
2. 设备注册 → core.device_registry 持久化
3. Session Roaming 创建 → 迁移 → 恢复 → 持久化
4. device_router 注册同步到 core.device_registry
5. AIP v2 ↔ 统一类型转换
"""

import asyncio
import json
import os
import time
import pytest


def _run(coro):
    """Helper to run async coroutines in sync tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# 1. DeviceType 统一性测试
# ---------------------------------------------------------------------------


class TestDeviceTypeUnification:
    """验证所有子系统使用统一 DeviceType"""

    def test_core_device_types_has_iot_types(self):
        from core.device_types import DeviceType
        assert DeviceType.DRONE == "drone"
        assert DeviceType.PRINTER_3D == "printer_3d"
        assert DeviceType.ROBOT == "robot"
        assert DeviceType.CAMERA == "camera"
        assert DeviceType.SENSOR == "sensor"
        assert DeviceType.ACTUATOR == "actuator"
        assert DeviceType.DISPLAY == "display"
        assert DeviceType.SPEAKER == "speaker"
        assert DeviceType.EMBEDDED == "embedded"

    def test_core_device_types_has_platform_types(self):
        from core.device_types import DeviceType
        assert DeviceType.ANDROID == "android"
        assert DeviceType.IOS == "ios"
        assert DeviceType.WINDOWS == "windows"
        assert DeviceType.MACOS == "macos"
        assert DeviceType.LINUX == "linux"
        assert DeviceType.CLOUD == "cloud"

    def test_device_status_has_all_states(self):
        from core.device_types import DeviceStatus
        assert DeviceStatus.IDLE == "idle"
        assert DeviceStatus.MAINTENANCE == "maintenance"
        assert DeviceStatus.DISCOVERING == "discovering"
        assert DeviceStatus.DEGRADED == "degraded"

    def test_node71_device_model_uses_core_type(self):
        """Node_71 的 device.py 中 DeviceType 来自 core"""
        # 直接导入 device.py 模块（跳过 __init__.py 的相对导入问题）
        import importlib
        spec = importlib.util.spec_from_file_location(
            "n71_device",
            "nodes/Node_71_MultiDeviceCoordination/models/device.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        from core.device_types import DeviceType as CoreType
        assert mod.DeviceType is CoreType

    def test_resolve_device_type(self):
        from core.device_types import resolve_device_type, DeviceType
        assert resolve_device_type("android_phone") == DeviceType.ANDROID
        assert resolve_device_type("windows_desktop") == DeviceType.WINDOWS
        assert resolve_device_type("drone") == DeviceType.DRONE
        assert resolve_device_type("printer_3d") == DeviceType.PRINTER_3D
        assert resolve_device_type("linux_server") == DeviceType.LINUX
        assert resolve_device_type("embedded_esp32") == DeviceType.EMBEDDED

    def test_aip_v2_to_unified_conversion(self):
        from enhancements.multidevice.device_protocol import (
            DeviceType as V2Type,
            to_unified_device_type,
            from_unified_device_type,
        )
        from core.device_types import DeviceType

        assert to_unified_device_type(V2Type.ANDROID_PHONE) == DeviceType.ANDROID
        assert to_unified_device_type(V2Type.LINUX_SERVER) == DeviceType.LINUX
        assert to_unified_device_type(V2Type.EMBEDDED) == DeviceType.EMBEDDED
        v2 = from_unified_device_type(DeviceType.ANDROID)
        assert v2 == V2Type.ANDROID_PHONE


# ---------------------------------------------------------------------------
# 2. 设备注册统一测试
# ---------------------------------------------------------------------------


class TestDeviceRegistryUnified:

    @pytest.fixture(autouse=True)
    def _reset_registry(self, tmp_path):
        from core.device_registry import DeviceRegistry
        registry = DeviceRegistry.__new__(DeviceRegistry)
        registry.devices = {}
        registry.groups = {}
        registry.tag_index = {}
        registry.capability_index = {}
        registry.storage_path = tmp_path / "devices.json"
        registry._on_device_registered = []
        registry._on_device_offline = []
        registry._on_device_online = []
        self.registry = registry

    def test_register_and_persist(self):
        device = _run(self.registry.register(
            device_id="test_android_001",
            device_type="android",
            name="Test Phone",
            capabilities=["screen", "camera"],
            ip_address="192.168.1.100",
        ))
        assert device.device_id == "test_android_001"
        assert self.registry.storage_path.exists()

        with open(self.registry.storage_path) as f:
            data = json.load(f)
        assert "test_android_001" in data["devices"]

    def test_discover_by_type(self):
        _run(self.registry.register(device_id="a1", device_type="android", name="phone"))
        _run(self.registry.register(device_id="w1", device_type="windows", name="pc"))

        androids = _run(self.registry.discover(device_type="android"))
        assert len(androids) == 1
        assert androids[0].device_id == "a1"

    def test_discover_by_capability(self):
        _run(self.registry.register(
            device_id="d1", device_type="drone",
            name="Drone", capabilities=["camera", "gps"],
        ))
        _run(self.registry.register(
            device_id="s1", device_type="sensor",
            name="Sensor", capabilities=["temperature"],
        ))
        cam_devices = _run(self.registry.discover(capability="camera"))
        assert len(cam_devices) == 1
        assert cam_devices[0].device_id == "d1"

    def test_heartbeat_and_offline_check(self):
        _run(self.registry.register(device_id="h1", device_type="android", name="phone"))
        device = self.registry.get("h1")
        assert device.is_online()

        device.last_heartbeat = time.time() - 120
        _run(self.registry.check_offline_devices(timeout=60))
        assert not device.is_online()

    def test_capability_negotiation(self):
        _run(self.registry.register(
            device_id="c1", device_type="camera",
            name="Camera", capabilities=["video", "photo"],
        ))
        _run(self.registry.register(
            device_id="c2", device_type="camera",
            name="Camera2", capabilities=["video"],
        ))
        best = self.registry.negotiate_capability("photo")
        assert best is not None
        assert best.device_id == "c1"


# ---------------------------------------------------------------------------
# 3. Session Roaming 测试
# ---------------------------------------------------------------------------


class TestSessionRoaming:

    @pytest.fixture(autouse=True)
    def _reset_session_mgr(self, tmp_path):
        from galaxy_gateway.session_roaming import SessionRoamingManager
        mgr = SessionRoamingManager.__new__(SessionRoamingManager)
        mgr._sessions = {}
        mgr._device_session_map = {}
        mgr._on_migrated = None
        mgr.SESSIONS_FILE = str(tmp_path / "sessions.json")
        self.mgr = mgr

    def test_create_session(self):
        session = self.mgr.create_session("phone_001", wake_word="你好")
        assert session.device_id == "phone_001"
        assert session.context.meta["wake_word"] == "你好"
        assert os.path.exists(self.mgr.SESSIONS_FILE)

    def test_add_turn_persists(self):
        session = self.mgr.create_session("phone_001")
        self.mgr.add_turn(session.session_id, "user", "打开微信")
        self.mgr.add_turn(session.session_id, "assistant", "正在打开微信")

        with open(self.mgr.SESSIONS_FILE) as f:
            data = json.load(f)
        saved_session = list(data["sessions"].values())[0]
        assert len(saved_session["context"]["history"]) == 2

    def test_migrate_session(self):
        session = self.mgr.create_session("phone_001")
        self.mgr.add_turn(session.session_id, "user", "帮我查天气")

        ok = _run(self.mgr.migrate_session(session.session_id, "pc_001"))
        assert ok

        assert self.mgr._device_session_map.get("pc_001") == session.session_id
        assert "phone_001" not in self.mgr._device_session_map

        migrated = self.mgr.get_session(session.session_id)
        assert len(migrated.context.history) == 1
        assert migrated.device_id == "pc_001"

    def test_session_restore_from_file(self):
        session = self.mgr.create_session("phone_001")
        self.mgr.add_turn(session.session_id, "user", "Test message")
        sid = session.session_id

        from galaxy_gateway.session_roaming import SessionRoamingManager
        mgr2 = SessionRoamingManager.__new__(SessionRoamingManager)
        mgr2._sessions = {}
        mgr2._device_session_map = {}
        mgr2._on_migrated = None
        mgr2.SESSIONS_FILE = self.mgr.SESSIONS_FILE
        mgr2._load_sessions()

        restored = mgr2.get_session(sid)
        assert restored is not None
        assert len(restored.context.history) == 1
        assert restored.context.history[0].content == "Test message"

    def test_close_session(self):
        session = self.mgr.create_session("phone_001")
        self.mgr.close_session(session.session_id)
        assert "phone_001" not in self.mgr._device_session_map

    def test_session_stats(self):
        self.mgr.create_session("phone_001")
        self.mgr.create_session("pc_001")
        stats = self.mgr.get_stats()
        assert stats["total_sessions"] == 2


# ---------------------------------------------------------------------------
# 4. device_router → core.device_registry 同步测试
# ---------------------------------------------------------------------------


class TestDeviceRouterSync:

    def test_device_router_creates_device(self):
        from galaxy_gateway.device_router import DeviceRouter
        router = DeviceRouter()
        ok = router.register_device("dr_001", "android", ["screen", "camera"])
        assert ok
        device = router.get_device("dr_001")
        assert device is not None
        assert device.device_type == "android"

    def test_device_router_get_by_type(self):
        from galaxy_gateway.device_router import DeviceRouter
        from core.device_types import DeviceType
        router = DeviceRouter()
        router.register_device("a1", "android", ["screen"])
        router.register_device("w1", "windows", ["keyboard"])

        androids = router.get_devices_by_type(DeviceType.ANDROID)
        assert len(androids) == 1
        assert androids[0].device_id == "a1"

    def test_device_router_unregister(self):
        from galaxy_gateway.device_router import DeviceRouter
        router = DeviceRouter()
        router.register_device("u1", "android", [])
        assert router.get_device("u1") is not None
        router.unregister_device("u1")
        assert router.get_device("u1") is None


# ---------------------------------------------------------------------------
# 5. Cross-Device Coordinator 持久化测试
# ---------------------------------------------------------------------------


class TestCrossDeviceCoordinatorPersist:

    def test_shared_data_persists(self, tmp_path):
        from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator
        import galaxy_gateway.cross_device_coordinator as mod

        cdc = CrossDeviceCoordinator.__new__(CrossDeviceCoordinator)
        cdc.shared_clipboard = {}
        cdc.device_states = {}
        cdc._SHARED_DATA_PATH = str(tmp_path / "shared.json")

        cdc.set_shared_data("test_key", {"hello": "world"})
        assert os.path.exists(cdc._SHARED_DATA_PATH)

        val = cdc.get_shared_data("test_key")
        assert val == {"hello": "world"}

        # Simulate restart
        cdc2 = CrossDeviceCoordinator.__new__(CrossDeviceCoordinator)
        cdc2.shared_clipboard = {}
        cdc2.device_states = {}
        cdc2._SHARED_DATA_PATH = cdc._SHARED_DATA_PATH
        cdc2._load_shared_data()

        val2 = cdc2.get_shared_data("test_key")
        assert val2 == {"hello": "world"}
