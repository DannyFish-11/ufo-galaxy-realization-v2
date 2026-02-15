"""
Node 71 - Test Configuration
pytest conftest 和共享 fixtures
"""
import sys
import os
import asyncio
import pytest

# 确保模块路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.device import (
    Device, DeviceType, DeviceState, DeviceRegistry,
    Capability, ResourceConstraints, VectorClock, DiscoveryProtocol
)
from models.task import (
    Task, TaskState, TaskPriority, TaskType, TaskDependency,
    TaskResource, RetryPolicy, SubTask, TaskQueue, SchedulingStrategy
)
from core.device_discovery import DiscoveryConfig
from core.state_synchronizer import SyncConfig
from core.task_scheduler import SchedulerConfig, TaskScheduler
from core.fault_tolerance import (
    CircuitBreaker, CircuitBreakerConfig, RetryManager, RetryConfig,
    FailoverManager, FailoverConfig, FaultToleranceLayer
)
from core.multi_device_coordinator_engine import (
    MultiDeviceCoordinatorEngine, CoordinatorConfig
)


@pytest.fixture
def sample_device():
    """创建测试设备"""
    return Device(
        device_id="test-device-001",
        name="Test Device",
        device_type=DeviceType.SENSOR,
        state=DeviceState.IDLE,
        host="192.168.1.100",
        port=8080,
        capabilities=[
            Capability(name="temperature", version="1.0"),
            Capability(name="humidity", version="1.0")
        ],
        location="lab-A",
        resource_constraints=ResourceConstraints(
            max_cpu_percent=80.0,
            max_memory_mb=2048,
            max_concurrent_tasks=5
        )
    )


@pytest.fixture
def sample_devices():
    """创建多个测试设备"""
    devices = []
    types = [DeviceType.SENSOR, DeviceType.CAMERA, DeviceType.DRONE, DeviceType.ROBOT]
    for i, dt in enumerate(types):
        device = Device(
            device_id=f"device-{i:03d}",
            name=f"Test Device {i}",
            device_type=dt,
            state=DeviceState.IDLE,
            host=f"192.168.1.{100 + i}",
            port=8080 + i,
            capabilities=[Capability(name=f"cap-{dt.value}", version="1.0")],
            location=f"zone-{chr(65 + i)}"
        )
        devices.append(device)
    return devices


@pytest.fixture
def device_registry(sample_devices):
    """创建已注册设备的注册表"""
    registry = DeviceRegistry()
    for device in sample_devices:
        registry.register(device)
    return registry


@pytest.fixture
def sample_task():
    """创建测试任务"""
    return Task(
        task_id="task-001",
        name="Test Task",
        description="Test task for unit tests",
        task_type=TaskType.COMMAND,
        priority=TaskPriority.NORMAL,
        required_devices=["device-000"],
        params={"command": "test_cmd", "args": []},
        timeout=30.0,
        retry_policy=RetryPolicy(max_retries=2, retry_delay=0.1)
    )


@pytest.fixture
def sample_tasks():
    """创建多个测试任务"""
    tasks = []
    for i in range(5):
        task = Task(
            task_id=f"task-{i:03d}",
            name=f"Test Task {i}",
            description=f"Test task {i}",
            task_type=TaskType.COMMAND,
            priority=TaskPriority(5),
            timeout=30.0
        )
        tasks.append(task)
    return tasks


@pytest.fixture
def coordinator_config():
    """创建协调器配置（禁用网络发现以简化测试）"""
    return CoordinatorConfig(
        node_id="test-coordinator",
        node_name="TestCoordinator",
        discovery_config=DiscoveryConfig(
            mdns_enabled=False,
            upnp_enabled=False,
            broadcast_enabled=False
        ),
        sync_config=SyncConfig(
            gossip_interval=1.0,
            snapshot_interval=5.0
        ),
        scheduler_config=SchedulerConfig(
            task_timeout=10.0
        ),
        heartbeat_interval=2.0,
        heartbeat_timeout=10.0
    )


@pytest.fixture
def engine(coordinator_config):
    """创建协调引擎"""
    return MultiDeviceCoordinatorEngine(coordinator_config)


@pytest.fixture
def circuit_breaker():
    """创建熔断器"""
    config = CircuitBreakerConfig(
        failure_threshold=3,
        success_threshold=2,
        timeout=1.0,
        half_open_max_calls=2,
        window_size=10.0
    )
    return CircuitBreaker("test-cb", config)


@pytest.fixture
def retry_manager():
    """创建重试管理器"""
    config = RetryConfig(
        max_retries=3,
        base_delay=0.01,  # 测试时用极短延迟
        max_delay=0.1,
        exponential_backoff=True,
        jitter=False
    )
    return RetryManager(config)


@pytest.fixture
def failover_manager():
    """创建故障切换管理器"""
    config = FailoverConfig(
        max_failover_attempts=3,
        health_check_interval=1.0,
        recovery_timeout=2.0
    )
    return FailoverManager(config)
