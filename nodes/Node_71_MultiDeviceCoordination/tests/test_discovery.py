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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.device import Device, DeviceType, DeviceState, Capability, DiscoveryProtocol
from core.device_discovery import (
    DeviceDiscovery, DiscoveryConfig, DiscoveryEvent, DiscoveryEventType,
    BroadcastDiscovery, MDNSDiscovery, UPNPDiscovery
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
        config = DiscoveryConfig(
            mdns_enabled=False,
            broadcast_port=40000,
            heartbeat_timeout=120.0
        )
        
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
        return DiscoveryConfig(
            broadcast_port=37022,  # 使用不同端口避免冲突
            broadcast_interval=1.0
        )
    
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
            discovery_protocol=DiscoveryProtocol.BROADCAST
        )
        discovery._discovered[device.device_id] = device
        
        devices = discovery.get_discovered_devices()
        
        assert len(devices) == 1
        assert devices[0].device_id == "test-device-001"
    
    def test_remove_device(self, discovery):
        """测试移除设备"""
        device = Device(
            device_id="test-device-001",
            name="Test Device",
            device_type=DeviceType.SENSOR
        )
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
        """测试在没有 zeroconf 的情况下启动"""
        # 如果没有安装 zeroconf，应该返回 False
        with patch('core.device_discovery.MDNSDiscovery.start') as mock_start:
            mock_start.return_value = asyncio.sleep(0)
            # 实际测试会依赖环境


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
        return DiscoveryConfig(
            broadcast_port=37023,
            mdns_enabled=False,  # 禁用以简化测试
            upnp_enabled=False
        )
    
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
        device = Device(
            device_id="test-device-001",
            name="Test Device",
            device_type=DeviceType.SENSOR
        )
        discovery._devices[device.device_id] = device
        
        result = discovery.get_device("test-device-001")
        
        assert result is not None
        assert result.device_id == "test-device-001"
    
    def test_get_all_devices(self, discovery):
        """测试获取所有设备"""
        device1 = Device(
            device_id="device-001",
            name="Device 1",
            device_type=DeviceType.SENSOR
        )
        device2 = Device(
            device_id="device-002",
            name="Device 2",
            device_type=DeviceType.CAMERA
        )
        
        discovery._devices[device1.device_id] = device1
        discovery._devices[device2.device_id] = device2
        
        devices = discovery.get_all_devices()
        
        assert len(devices) == 2
    
    def test_get_devices_by_type(self, discovery):
        """测试按类型获取设备"""
        device1 = Device(
            device_id="device-001",
            name="Device 1",
            device_type=DeviceType.SENSOR
        )
        device2 = Device(
            device_id="device-002",
            name="Device 2",
            device_type=DeviceType.CAMERA
        )
        
        discovery._devices[device1.device_id] = device1
        discovery._devices[device2.device_id] = device2
        
        sensors = discovery.get_devices_by_type(DeviceType.SENSOR)
        
        assert len(sensors) == 1
        assert sensors[0].device_type == DeviceType.SENSOR
    
    def test_count(self, discovery):
        """测试设备计数"""
        assert discovery.count() == 0
        
        device = Device(
            device_id="device-001",
            name="Device 1",
            device_type=DeviceType.SENSOR
        )
        discovery._devices[device.device_id] = device
        
        assert discovery.count() == 1


class TestDiscoveryEvent:
    """发现事件测试"""
    
    def test_event_creation(self):
        """测试事件创建"""
        device = Device(
            device_id="test-device",
            name="Test Device",
            device_type=DeviceType.SENSOR
        )
        
        event = DiscoveryEvent(
            event_type=DiscoveryEventType.DEVICE_FOUND,
            device=device,
            message="Device discovered"
        )
        
        assert event.event_type == DiscoveryEventType.DEVICE_FOUND
        assert event.device.device_id == "test-device"
        assert event.message == "Device discovered"
    
    def test_event_to_dict(self):
        """测试事件转换为字典"""
        device = Device(
            device_id="test-device",
            name="Test Device",
            device_type=DeviceType.SENSOR
        )
        
        event = DiscoveryEvent(
            event_type=DiscoveryEventType.DEVICE_FOUND,
            device=device,
            message="Device discovered"
        )
        
        data = event.to_dict()
        
        assert data["event_type"] == "device_found"
        assert data["message"] == "Device discovered"
        assert "device" in data
        assert data["device"]["device_id"] == "test-device"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
