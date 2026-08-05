"""
Node 71 - Device Discovery Tests
设备发现模块单元测试
"""

import asyncio
import pytest
import time
from unittest.mock import Mock, AsyncMock, patch

import sys
import os

# 这里原先有一句 sys.path.insert(0, <节点目录>)。它是「裸顶层导入」时代的遗留:
# 把节点目录顶到 sys.path 最前面,好让 from core.X / from models.X 指到节点自己。
# 现在包内一律用相对导入,这句不但没用,而且**有害** —— 它让节点自己的 core/ 抢在
# 仓库根的 core/ 前面被解析,于是 models/device.py 里那句合法的
# from core.device_types import DeviceType(单一事实来源,确实指仓库根)会拐进
# 节点的 core/__init__.py,绕成循环导入,最终报 attempted relative import beyond top-level。

from ..models.device import Device, DeviceType, DeviceState, Capability, DiscoveryProtocol
from ..core.device_discovery import (
    DeviceDiscovery,
    DiscoveryConfig,
    DiscoveryEvent,
    DiscoveryEventType,
    BroadcastDiscovery,
    MDNSDiscovery,
    UPNPDiscovery,
)


class TestDiscoveryConfig:
    """发现配置测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = DiscoveryConfig()

        assert config.mdns_enabled == True
        assert config.upnp_enabled == True
        assert config.broadcast_enabled == True
        assert config.heartbeat_timeout == 60.0
        assert config.max_devices == 1000

    def test_custom_config(self):
        """测试自定义配置"""
        config = DiscoveryConfig(mdns_enabled=False, broadcast_port=40000, heartbeat_timeout=120.0)

        assert config.mdns_enabled == False
        assert config.broadcast_port == 40000
        assert config.heartbeat_timeout == 120.0

    def test_to_dict(self):
        """测试转换为字典"""
        config = DiscoveryConfig()
        data = config.to_dict()

        assert "mdns_enabled" in data
        assert "broadcast_port" in data
        assert data["mdns_enabled"] == config.mdns_enabled


class TestBroadcastDiscovery:
    """广播发现测试"""

    @pytest.fixture
    def config(self):
        return DiscoveryConfig(broadcast_port=37022, broadcast_interval=1.0)  # 使用不同端口避免冲突

    @pytest.fixture
    def discovery(self, config):
        return BroadcastDiscovery(config, "test-node-001")

    def test_init(self, discovery):
        """测试初始化"""
        assert discovery.node_id == "test-node-001"
        assert discovery._running == False
        assert len(discovery._discovered) == 0

    def test_add_event_handler(self, discovery):
        """测试添加事件处理器"""
        handler = Mock()
        discovery.add_event_handler(handler)

        assert handler in discovery._event_handlers

    @pytest.mark.asyncio
    async def test_start_stop(self, discovery):
        """测试启动和停止"""
        # 启动
        success = await discovery.start()
        assert success == True
        assert discovery._running == True
        assert discovery._socket is not None

        # 停止
        await discovery.stop()
        assert discovery._running == False
        assert discovery._socket is None

    def test_get_discovered_devices(self, discovery):
        """测试获取已发现设备"""
        # 添加测试设备
        device = Device(
            device_id="test-device-001",
            name="Test Device",
            device_type=DeviceType.SENSOR,
            state=DeviceState.IDLE,
            discovery_protocol=DiscoveryProtocol.BROADCAST,
        )
        discovery._discovered[device.device_id] = device

        devices = discovery.get_discovered_devices()

        assert len(devices) == 1
        assert devices[0].device_id == "test-device-001"

    def test_remove_device(self, discovery):
        """测试移除设备"""
        device = Device(device_id="test-device-001", name="Test Device", device_type=DeviceType.SENSOR)
        discovery._discovered[device.device_id] = device

        # 移除设备
        result = discovery.remove_device("test-device-001")

        assert result == True
        assert len(discovery._discovered) == 0


class TestMDNSDiscovery:
    """mDNS 发现测试"""

    @pytest.fixture
    def config(self):
        return DiscoveryConfig()

    @pytest.fixture
    def discovery(self, config):
        return MDNSDiscovery(config, "test-node-001")

    def test_init(self, discovery):
        """测试初始化"""
        assert discovery.node_id == "test-node-001"
        assert discovery._running == False

    def test_add_event_handler(self, discovery):
        """测试添加事件处理器"""
        handler = Mock()
        discovery.add_event_handler(handler)

        assert handler in discovery._event_handlers

    @pytest.mark.asyncio
    async def test_start_without_zeroconf(self, discovery):
        """没装 zeroconf 时 start() 必须返回 False,而不是抛异常。

        这一条原先是**空转**的:它 patch 掉 ``core.device_discovery.MDNSDiscovery.start``
        —— 也就是把被测方法本身换成 mock —— 然后函数体到此结束,一句断言也没有,
        末尾还留着一句 "实际测试会依赖环境"。既没有测到真实行为,连 mock 都没被调用。
        (顺带,那个 patch 目标 ``core.device_discovery`` 是伪造的模块名,节点改成
        相对导入之后它连解析都解析不了,于是这条空转的用例还会**报错**。)

        现在真的测:把 zeroconf 从 import 路径上摘掉,断言 start() 返回 False。
        真实的降级契约是 ``except ImportError: return False``(device_discovery.py),
        这条正对着它。
        """
        import builtins

        real_import = builtins.__import__

        def _no_zeroconf(name, *args, **kwargs):
            if name == "zeroconf" or name.startswith("zeroconf."):
                raise ImportError("zeroconf not installed (simulated)")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", _no_zeroconf):
            result = await discovery.start()

        assert result is False, "没装 zeroconf 时 mDNS 发现应安静降级返回 False,而不是抛异常或谎报成功"


class TestUPNPDiscovery:
    """UPnP 发现测试"""

    @pytest.fixture
    def config(self):
        return DiscoveryConfig()

    @pytest.fixture
    def discovery(self, config):
        return UPNPDiscovery(config, "test-node-001")

    def test_init(self, discovery):
        """测试初始化"""
        assert discovery.node_id == "test-node-001"
        assert discovery._running == False

    @pytest.mark.asyncio
    async def test_start_stop(self, discovery):
        """测试启动和停止"""
        success = await discovery.start()
        assert success == True
        assert discovery._running == True

        await discovery.stop()
        assert discovery._running == False


class TestDeviceDiscovery:
    """设备发现服务测试"""

    @pytest.fixture
    def config(self):
        return DiscoveryConfig(broadcast_port=37023, mdns_enabled=False, upnp_enabled=False)  # 禁用以简化测试

    @pytest.fixture
    def discovery(self, config):
        return DeviceDiscovery(config, "test-node-001")

    def test_init(self, discovery):
        """测试初始化"""
        assert discovery.node_id == "test-node-001"
        assert discovery._running == False
        assert len(discovery._devices) == 0

    def test_add_event_handler(self, discovery):
        """测试添加事件处理器"""
        handler = Mock()
        discovery.add_event_handler(handler)

        assert handler in discovery._event_handlers

    @pytest.mark.asyncio
    async def test_start_stop(self, discovery):
        """测试启动和停止"""
        success = await discovery.start()
        assert success == True
        assert discovery._running == True

        await discovery.stop()
        assert discovery._running == False

    def test_get_device(self, discovery):
        """测试获取设备"""
        device = Device(device_id="test-device-001", name="Test Device", device_type=DeviceType.SENSOR)
        discovery.add_device(device)

        result = discovery.get_device("test-device-001")

        assert result is not None
        assert result.device_id == "test-device-001"

    def test_get_all_devices(self, discovery):
        """测试获取所有设备"""
        device1 = Device(device_id="device-001", name="Device 1", device_type=DeviceType.SENSOR)
        device2 = Device(device_id="device-002", name="Device 2", device_type=DeviceType.CAMERA)

        discovery.add_device(device1)
        discovery.add_device(device2)

        devices = discovery.get_all_devices()

        assert len(devices) == 2

    def test_get_devices_by_type(self, discovery):
        """测试按类型获取设备"""
        device1 = Device(device_id="device-001", name="Device 1", device_type=DeviceType.SENSOR)
        device2 = Device(device_id="device-002", name="Device 2", device_type=DeviceType.CAMERA)

        discovery.add_device(device1)
        discovery.add_device(device2)

        sensors = discovery.get_devices_by_type(DeviceType.SENSOR)

        assert len(sensors) == 1
        assert sensors[0].device_type == DeviceType.SENSOR

    def test_count(self, discovery):
        """测试设备计数"""
        assert discovery.count() == 0

        device = Device(device_id="device-001", name="Device 1", device_type=DeviceType.SENSOR)
        discovery.add_device(device)

        assert discovery.count() == 1


class TestDiscoveryEvent:
    """发现事件测试"""

    def test_event_creation(self):
        """测试事件创建"""
        device = Device(device_id="test-device", name="Test Device", device_type=DeviceType.SENSOR)

        event = DiscoveryEvent(event_type=DiscoveryEventType.DEVICE_FOUND, device=device, message="Device discovered")

        assert event.event_type == DiscoveryEventType.DEVICE_FOUND
        assert event.device.device_id == "test-device"
        assert event.message == "Device discovered"

    def test_event_to_dict(self):
        """测试事件转换为字典"""
        device = Device(device_id="test-device", name="Test Device", device_type=DeviceType.SENSOR)

        event = DiscoveryEvent(event_type=DiscoveryEventType.DEVICE_FOUND, device=device, message="Device discovered")

        data = event.to_dict()

        assert data["event_type"] == "device_found"
        assert data["message"] == "Device discovered"
        assert "device" in data
        assert data["device"]["device_id"] == "test-device"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
