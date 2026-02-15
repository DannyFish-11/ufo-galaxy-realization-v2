"""
Node 71 - Model Tests
数据模型单元测试：Device、Task、VectorClock、Registry
"""
import pytest
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.device import (
    Device, DeviceType, DeviceState, DeviceRegistry,
    Capability, ResourceConstraints, VectorClock, DiscoveryProtocol
)
from models.task import (
    Task, TaskState, TaskPriority, TaskType, TaskDependency,
    TaskResource, RetryPolicy, SubTask, TaskQueue, SchedulingStrategy
)


class TestVectorClock:
    """向量时钟测试"""

    def test_initialization(self):
        vc = VectorClock(node_id="node-1")
        assert vc.clock["node-1"] == 0

    def test_increment(self):
        vc = VectorClock(node_id="node-1")
        vc.increment()
        assert vc.clock["node-1"] == 1
        vc.increment()
        assert vc.clock["node-1"] == 2

    def test_update(self):
        vc1 = VectorClock(clock={"A": 2, "B": 1}, node_id="A")
        vc2 = VectorClock(clock={"A": 1, "B": 3, "C": 1}, node_id="B")

        vc1.update(vc2)
        assert vc1.clock["A"] == 2
        assert vc1.clock["B"] == 3
        assert vc1.clock["C"] == 1

    def test_compare_less(self):
        vc1 = VectorClock(clock={"A": 1, "B": 1})
        vc2 = VectorClock(clock={"A": 2, "B": 2})
        assert vc1.compare(vc2) == -1

    def test_compare_greater(self):
        vc1 = VectorClock(clock={"A": 3, "B": 2})
        vc2 = VectorClock(clock={"A": 1, "B": 1})
        assert vc1.compare(vc2) == 1

    def test_compare_concurrent(self):
        vc1 = VectorClock(clock={"A": 2, "B": 1})
        vc2 = VectorClock(clock={"A": 1, "B": 2})
        assert vc1.compare(vc2) == 0

    def test_copy(self):
        vc = VectorClock(clock={"A": 1}, node_id="A")
        vc_copy = vc.copy()
        vc_copy.increment()
        assert vc.clock["A"] == 1
        assert vc_copy.clock["A"] == 2

    def test_serialization(self):
        vc = VectorClock(clock={"A": 1, "B": 2}, node_id="A")
        data = vc.to_dict()
        restored = VectorClock.from_dict(data)
        assert restored.clock == vc.clock
        assert restored.node_id == vc.node_id


class TestCapability:
    """设备能力测试"""

    def test_creation(self):
        cap = Capability(name="camera", version="2.0")
        assert cap.name == "camera"
        assert cap.version == "2.0"
        assert cap.priority == 5

    def test_serialization(self):
        cap = Capability(name="lidar", version="1.0", parameters={"range": 100})
        data = cap.to_dict()
        restored = Capability.from_dict(data)
        assert restored.name == "lidar"
        assert restored.parameters["range"] == 100


class TestResourceConstraints:
    """资源约束测试"""

    def test_defaults(self):
        rc = ResourceConstraints()
        assert rc.max_cpu_percent == 100.0
        assert rc.max_memory_mb == 4096
        assert rc.max_concurrent_tasks == 10

    def test_serialization(self):
        rc = ResourceConstraints(max_cpu_percent=50.0, max_memory_mb=1024)
        data = rc.to_dict()
        restored = ResourceConstraints.from_dict(data)
        assert restored.max_cpu_percent == 50.0
        assert restored.max_memory_mb == 1024


class TestDevice:
    """设备模型测试"""

    def test_creation(self, sample_device):
        assert sample_device.device_id == "test-device-001"
        assert sample_device.device_type == DeviceType.SENSOR
        assert sample_device.state == DeviceState.IDLE

    def test_update_heartbeat(self, sample_device):
        old_hb = sample_device.last_heartbeat
        time.sleep(0.01)
        sample_device.update_heartbeat()
        assert sample_device.last_heartbeat > old_hb

    def test_update_heartbeat_revives(self):
        device = Device(
            device_id="dev-1", name="Dev", device_type=DeviceType.SENSOR,
            state=DeviceState.OFFLINE
        )
        device.update_heartbeat()
        assert device.state == DeviceState.IDLE

    def test_is_healthy(self, sample_device):
        assert sample_device.is_healthy(timeout=60.0) is True

    def test_is_unhealthy_offline(self):
        device = Device(
            device_id="dev-1", name="Dev", device_type=DeviceType.SENSOR,
            state=DeviceState.OFFLINE
        )
        assert device.is_healthy() is False

    def test_can_accept_task(self, sample_device):
        assert sample_device.can_accept_task() is True

    def test_cannot_accept_task_when_busy(self, sample_device):
        sample_device.state = DeviceState.BUSY
        assert sample_device.can_accept_task() is False

    def test_cannot_accept_task_when_full(self, sample_device):
        sample_device.assigned_tasks = [f"t{i}" for i in range(5)]  # max=5
        assert sample_device.can_accept_task() is False

    def test_has_capability(self, sample_device):
        assert sample_device.has_capability("temperature") is True
        assert sample_device.has_capability("gps") is False

    def test_get_capability(self, sample_device):
        cap = sample_device.get_capability("temperature")
        assert cap is not None
        assert cap.name == "temperature"

    def test_serialization(self, sample_device):
        data = sample_device.to_dict()
        restored = Device.from_dict(data)
        assert restored.device_id == sample_device.device_id
        assert restored.device_type == sample_device.device_type
        assert len(restored.capabilities) == len(sample_device.capabilities)

    def test_string_type_coercion(self):
        device = Device(
            device_id="dev-1", name="Dev",
            device_type="sensor", state="idle"
        )
        assert device.device_type == DeviceType.SENSOR
        assert device.state == DeviceState.IDLE


class TestDeviceRegistry:
    """设备注册表测试"""

    def test_register(self, device_registry, sample_devices):
        assert device_registry.count() == len(sample_devices)

    def test_register_duplicate(self, device_registry, sample_devices):
        success = device_registry.register(sample_devices[0])
        assert success is False

    def test_unregister(self, device_registry, sample_devices):
        success = device_registry.unregister(sample_devices[0].device_id)
        assert success is True
        assert device_registry.count() == len(sample_devices) - 1

    def test_get(self, device_registry, sample_devices):
        device = device_registry.get(sample_devices[0].device_id)
        assert device is not None

    def test_get_nonexistent(self, device_registry):
        device = device_registry.get("nonexistent")
        assert device is None

    def test_get_by_type(self, device_registry):
        sensors = device_registry.get_by_type(DeviceType.SENSOR)
        assert len(sensors) == 1

    def test_get_online_devices(self, device_registry):
        online = device_registry.get_online_devices()
        assert len(online) > 0

    def test_get_available_devices(self, device_registry):
        available = device_registry.get_available_devices()
        assert len(available) > 0

    def test_count_by_state(self, device_registry):
        idle_count = device_registry.count_by_state(DeviceState.IDLE)
        assert idle_count > 0

    def test_to_dict(self, device_registry):
        data = device_registry.to_dict()
        assert "devices" in data
        assert "count" in data


class TestTask:
    """任务模型测试"""

    def test_creation(self, sample_task):
        assert sample_task.task_id == "task-001"
        assert sample_task.name == "Test Task"
        assert sample_task.priority == TaskPriority.NORMAL

    def test_can_retry(self, sample_task):
        assert sample_task.can_retry() is True
        sample_task.retry_count = 2  # max_retries=2
        assert sample_task.can_retry() is False

    def test_get_next_retry_delay(self, sample_task):
        delay = sample_task.get_next_retry_delay()
        assert delay > 0

    def test_get_duration(self, sample_task):
        assert sample_task.get_duration() == 0.0

        sample_task.started_at = time.time() - 5.0
        duration = sample_task.get_duration()
        assert duration >= 4.9

    def test_update_progress(self, sample_task):
        sample_task.subtasks = [
            SubTask(subtask_id="s1", name="Sub 1", action="a1"),
            SubTask(subtask_id="s2", name="Sub 2", action="a2")
        ]
        sample_task.update_progress(1)
        assert sample_task.progress == 0.5

    def test_serialization(self, sample_task):
        data = sample_task.to_dict()
        restored = Task.from_dict(data)
        assert restored.task_id == sample_task.task_id
        assert restored.name == sample_task.name
        assert restored.priority == sample_task.priority


class TestRetryPolicy:
    """重试策略测试"""

    def test_defaults(self):
        rp = RetryPolicy()
        assert rp.max_retries == 3
        assert rp.retry_delay == 1.0
        assert rp.exponential_backoff is True

    def test_get_delay_exponential(self):
        rp = RetryPolicy(retry_delay=1.0, exponential_backoff=True)
        assert rp.get_delay(0) == 1.0
        assert rp.get_delay(1) == 2.0
        assert rp.get_delay(2) == 4.0

    def test_get_delay_fixed(self):
        rp = RetryPolicy(retry_delay=2.0, exponential_backoff=False)
        assert rp.get_delay(0) == 2.0
        assert rp.get_delay(5) == 2.0

    def test_get_delay_max(self):
        rp = RetryPolicy(retry_delay=1.0, max_delay=10.0)
        assert rp.get_delay(10) <= 10.0


class TestTaskQueue:
    """任务队列测试"""

    def test_enqueue_dequeue(self, sample_tasks):
        queue = TaskQueue()
        for task in sample_tasks:
            queue.enqueue(task)

        assert queue.count() == len(sample_tasks)

        task = queue.dequeue()
        assert task is not None
        assert queue.count() == len(sample_tasks) - 1

    def test_priority_ordering(self):
        queue = TaskQueue()

        low = Task(task_id="low", name="Low", priority=TaskPriority.LOW)
        high = Task(task_id="high", name="High", priority=TaskPriority.HIGH)
        critical = Task(task_id="crit", name="Critical", priority=TaskPriority.CRITICAL)

        queue.enqueue(low)
        queue.enqueue(high)
        queue.enqueue(critical)

        assert queue.dequeue().task_id == "crit"
        assert queue.dequeue().task_id == "high"
        assert queue.dequeue().task_id == "low"

    def test_peek(self, sample_tasks):
        queue = TaskQueue()
        queue.enqueue(sample_tasks[0])

        task = queue.peek()
        assert task is not None
        assert queue.count() == 1  # peek 不移除

    def test_remove(self, sample_tasks):
        queue = TaskQueue()
        for task in sample_tasks:
            queue.enqueue(task)

        removed = queue.remove(sample_tasks[2].task_id)
        assert removed is not None
        assert queue.count() == len(sample_tasks) - 1

    def test_get(self, sample_tasks):
        queue = TaskQueue()
        for task in sample_tasks:
            queue.enqueue(task)

        found = queue.get(sample_tasks[1].task_id)
        assert found is not None
        assert found.task_id == sample_tasks[1].task_id

    def test_clear(self, sample_tasks):
        queue = TaskQueue()
        for task in sample_tasks:
            queue.enqueue(task)

        queue.clear()
        assert queue.count() == 0
        assert queue.is_empty() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
