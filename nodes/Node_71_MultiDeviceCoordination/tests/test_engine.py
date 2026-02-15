"""
Node 71 - Coordinator Engine Tests
协调引擎核心功能测试
"""
import asyncio
import pytest
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.device import (
    Device, DeviceType, DeviceState, DeviceRegistry,
    Capability, ResourceConstraints
)
from models.task import (
    Task, TaskState, TaskPriority, TaskType
)
from core.multi_device_coordinator_engine import (
    MultiDeviceCoordinatorEngine, CoordinatorConfig, CoordinatorState
)
from core.device_discovery import DiscoveryConfig
from core.state_synchronizer import SyncConfig
from core.task_scheduler import SchedulerConfig


class TestCoordinatorConfig:
    """协调器配置测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = CoordinatorConfig()
        assert config.node_name == "MultiDeviceCoordinator"
        assert config.heartbeat_interval == 10.0
        assert config.heartbeat_timeout == 60.0
        assert config.enable_failover is True

    def test_custom_config(self):
        """测试自定义配置"""
        config = CoordinatorConfig(
            node_id="custom-node",
            node_name="CustomCoordinator",
            heartbeat_interval=5.0
        )
        assert config.node_id == "custom-node"
        assert config.node_name == "CustomCoordinator"
        assert config.heartbeat_interval == 5.0

    def test_to_dict(self):
        """测试配置序列化"""
        config = CoordinatorConfig(node_id="test-node")
        data = config.to_dict()
        assert data["node_id"] == "test-node"
        assert "discovery_config" in data
        assert "sync_config" in data
        assert "scheduler_config" in data
        assert "circuit_breaker_config" in data
        assert "retry_config" in data
        assert "failover_config" in data


class TestMultiDeviceCoordinatorEngine:
    """协调引擎测试"""

    def test_initialization(self, engine):
        """测试引擎初始化"""
        assert engine._state == CoordinatorState.INITIALIZING
        assert engine.config.node_id == "test-coordinator"
        assert engine._registry is not None
        assert engine._fault_tolerance is not None

    @pytest.mark.asyncio
    async def test_start_stop(self, engine):
        """测试引擎启动和停止"""
        success = await engine.start()
        assert success is True
        assert engine._state == CoordinatorState.RUNNING
        assert engine._started_at is not None

        await engine.stop()
        assert engine._state == CoordinatorState.STOPPED

    @pytest.mark.asyncio
    async def test_double_start(self, engine):
        """测试重复启动"""
        await engine.start()
        success = await engine.start()  # 第二次启动应该返回 True
        assert success is True
        await engine.stop()

    def test_register_device(self, engine, sample_device):
        """测试设备注册"""
        success = engine.register_device(sample_device)
        assert success is True
        assert engine._stats["devices_registered"] == 1

    def test_register_duplicate_device(self, engine, sample_device):
        """测试重复注册设备"""
        engine.register_device(sample_device)
        success = engine.register_device(sample_device)
        assert success is False

    def test_unregister_device(self, engine, sample_device):
        """测试注销设备"""
        engine.register_device(sample_device)
        success = engine.unregister_device(sample_device.device_id)
        assert success is True

    def test_unregister_nonexistent(self, engine):
        """测试注销不存在的设备"""
        success = engine.unregister_device("nonexistent")
        assert success is False

    def test_get_device(self, engine, sample_device):
        """测试获取设备"""
        engine.register_device(sample_device)
        device = engine.get_device(sample_device.device_id)
        assert device is not None
        assert device.device_id == sample_device.device_id

    def test_get_nonexistent_device(self, engine):
        """测试获取不存在的设备"""
        device = engine.get_device("nonexistent")
        assert device is None

    def test_list_devices(self, engine, sample_devices):
        """测试列出设备"""
        for device in sample_devices:
            engine.register_device(device)

        all_devices = engine.list_devices()
        assert len(all_devices) == len(sample_devices)

    def test_list_devices_by_type(self, engine, sample_devices):
        """测试按类型过滤设备"""
        for device in sample_devices:
            engine.register_device(device)

        sensors = engine.list_devices(device_type=DeviceType.SENSOR)
        assert len(sensors) == 1
        assert sensors[0].device_type == DeviceType.SENSOR

    def test_list_devices_by_state(self, engine, sample_devices):
        """测试按状态过滤设备"""
        for device in sample_devices:
            engine.register_device(device)

        idle_devices = engine.list_devices(state=DeviceState.IDLE)
        assert len(idle_devices) == len(sample_devices)

    def test_update_device_state(self, engine, sample_device):
        """测试更新设备状态"""
        engine.register_device(sample_device)
        success = engine.update_device_state(
            sample_device.device_id, DeviceState.BUSY
        )
        assert success is True

        device = engine.get_device(sample_device.device_id)
        assert device.state == DeviceState.BUSY

    def test_update_nonexistent_device_state(self, engine):
        """测试更新不存在的设备状态"""
        success = engine.update_device_state("nonexistent", DeviceState.BUSY)
        assert success is False

    def test_create_device_group(self, engine, sample_devices):
        """测试创建设备组"""
        for device in sample_devices:
            engine.register_device(device)

        device_ids = [d.device_id for d in sample_devices[:2]]
        group_id = engine.create_device_group("test-group", device_ids)

        assert group_id is not None
        assert group_id.startswith("group-")

    def test_get_device_group(self, engine, sample_devices):
        """测试获取设备组"""
        for device in sample_devices:
            engine.register_device(device)

        device_ids = [d.device_id for d in sample_devices[:2]]
        group_id = engine.create_device_group("test-group", device_ids)

        group = engine.get_device_group(group_id)
        assert group is not None
        assert len(group) == 2

    def test_get_nonexistent_group(self, engine):
        """测试获取不存在的设备组"""
        group = engine.get_device_group("nonexistent")
        assert group is None

    @pytest.mark.asyncio
    async def test_create_task(self, engine, sample_device):
        """测试创建任务"""
        await engine.start()
        engine.register_device(sample_device)

        task_id = await engine.create_task(
            name="Test Task",
            description="A test task",
            required_devices=[sample_device.device_id],
            priority=TaskPriority.NORMAL,
            timeout=30.0
        )

        assert task_id is not None
        assert engine._stats["tasks_submitted"] == 1

        await engine.stop()

    @pytest.mark.asyncio
    async def test_get_task(self, engine, sample_device):
        """测试获取任务"""
        await engine.start()
        engine.register_device(sample_device)

        task_id = await engine.create_task(
            name="Test Task",
            description="A test task",
            required_devices=[sample_device.device_id]
        )

        task = engine.get_task(task_id)
        assert task is not None
        assert task.name == "Test Task"

        await engine.stop()

    @pytest.mark.asyncio
    async def test_list_tasks(self, engine, sample_device):
        """测试列出任务"""
        await engine.start()
        engine.register_device(sample_device)

        for i in range(3):
            await engine.create_task(
                name=f"Task {i}",
                description=f"Task {i}",
                required_devices=[]
            )

        tasks = engine.list_tasks()
        assert len(tasks) == 3

        await engine.stop()

    @pytest.mark.asyncio
    async def test_cancel_task(self, engine, sample_device):
        """测试取消任务"""
        await engine.start()
        engine.register_device(sample_device)

        task_id = await engine.create_task(
            name="Cancellable Task",
            description="Will be cancelled",
            required_devices=[]
        )

        success = await engine.cancel_task(task_id)
        assert success is True

        await engine.stop()

    def test_get_status(self, engine):
        """测试获取状态"""
        status = engine.get_status()
        assert "node_id" in status
        assert "state" in status
        assert "version" in status
        assert "stats" in status
        assert "fault_tolerance" in status
        assert "config" in status

    def test_get_stats(self, engine, sample_device):
        """测试获取统计"""
        engine.register_device(sample_device)

        stats = engine.get_stats()
        assert stats["devices_registered"] == 1
        assert stats["total_devices"] == 1
        assert "online_devices" in stats
        assert "tasks_submitted" in stats

    @pytest.mark.asyncio
    async def test_broadcast_to_group(self, engine, sample_devices):
        """测试向设备组广播"""
        await engine.start()

        for device in sample_devices:
            engine.register_device(device)

        device_ids = [d.device_id for d in sample_devices[:2]]
        group_id = engine.create_device_group("broadcast-group", device_ids)

        result = await engine.broadcast_to_group(group_id, "ping", {})
        assert result["success"] is True
        assert len(result["results"]) == 2

        await engine.stop()

    @pytest.mark.asyncio
    async def test_broadcast_to_nonexistent_group(self, engine):
        """测试向不存在的组广播"""
        await engine.start()

        result = await engine.broadcast_to_group("nonexistent", "ping", {})
        assert result["success"] is False

        await engine.stop()

    def test_event_handler(self, engine, sample_device):
        """测试事件处理器"""
        events = []

        def handler(event_type, data):
            events.append((event_type, data))

        engine.add_event_handler(handler)
        engine.register_device(sample_device)

        assert len(events) == 1
        assert events[0][0] == "device_registered"

    @pytest.mark.asyncio
    async def test_coordinate_task(self, engine, sample_devices):
        """测试跨设备任务协调"""
        await engine.start()

        for device in sample_devices:
            engine.register_device(device)

        task_id = await engine.create_task(
            name="Coordination Task",
            description="Cross-device coordination",
            required_devices=[d.device_id for d in sample_devices[:2]]
        )

        result = await engine.coordinate_task(task_id, [
            {
                "subtask_id": "sub-1",
                "device_id": sample_devices[0].device_id,
                "action": "scan",
                "params": {}
            },
            {
                "subtask_id": "sub-2",
                "device_id": sample_devices[1].device_id,
                "action": "process",
                "params": {}
            }
        ])

        assert result["task_id"] == task_id
        assert result["status"] == "coordinated"
        assert len(result["results"]) == 2

        await engine.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
