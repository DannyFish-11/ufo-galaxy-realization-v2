"""
Node 71 - Test Configuration
pytest conftest 和共享 fixtures

为什么这里不再有 path 注入与模块预注册
--------------------------------------
这里原先有一整套 workaround，理由写的是"Node_71 有两个 core 包"：把仓库根和节点
目录**都**塞进 sys.path，再用 importlib 把节点自己的 ``core/*.py`` 以 ``core.<name>``
这个**伪造的名字**预注册进 sys.modules，好让节点内部的裸 ``from core.device_discovery``
解析得到自己的模块而不是仓库根那个 core。

那个"冲突"的根源是 Node_71 自己：它用裸顶层导入引用**包内**模块。这一点已经在
上游被修好了 —— 节点的 core/ 与 models/ 全部改成了规范的相对导入
(``from .device_discovery`` / ``from ..models.device``)。

改完之后，上面那套 workaround 从"补丁"变成了"毒药"：伪造的 ``core.xxx`` 名字让
相对导入按错误的包层级解析，``..models`` 直接越过顶层包，抛
"attempted relative import beyond top-level package"。而收尾那句
``except Exception: pass`` 的注释写着"individual tests will fail with clear errors"
—— 恰恰相反，它把真实原因吞掉，failure 以完全不相干的面貌出现在别处（仓库级的
tests/test_pr_a_multi_device_runtime_wiring.py 抄了同一套写法，红出来的是一句
``ModuleNotFoundError: No module named 'core.multi_device_coordinator_engine'``，
那个模块名在仓库历史里从来不存在）。

Node_71 本来就是个规规矩矩的包（nodes/、Node_71…/、core/、models/、tests/ 五层
都有 __init__.py），所以现在按**相对导入**取包内模块即可：不伪造名字、不动 sys.path、
不吞异常。pytest 以 rootdir 为仓库根收集时，模块名就是
``nodes.Node_71_MultiDeviceCoordination.tests.test_x``，``..core`` / ``..models``
自然解析得到。

Heavy model imports are deferred into fixture functions to keep conftest load clean.
"""

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures (all imports deferred to fixture body)
# ─────────────────────────────────────────────────────────────────────────────


def _make_device(device_id, name, device_type_str, state_str="idle",
                 host="127.0.0.1", port=8080, capabilities=None,
                 location=None, resource_constraints=None):
    from ..models.device import Device, DeviceType, DeviceState, Capability, ResourceConstraints
    caps = [Capability(name=c, version="1.0") for c in (capabilities or [])]
    rc = resource_constraints or ResourceConstraints()
    return Device(
        device_id=device_id,
        name=name,
        device_type=DeviceType(device_type_str),
        state=DeviceState(state_str),
        host=host,
        port=port,
        capabilities=caps,
        location=location,
        resource_constraints=rc,
    )


@pytest.fixture
def sample_device():
    from ..models.device import ResourceConstraints
    return _make_device(
        device_id="test-device-001",
        name="Test Device",
        device_type_str="sensor",
        state_str="idle",
        host="192.168.1.100",
        port=8080,
        capabilities=["temperature", "humidity"],
        location="lab-A",
        resource_constraints=ResourceConstraints(max_cpu_percent=80.0, max_memory_mb=2048, max_concurrent_tasks=5),
    )


@pytest.fixture
def sample_devices():
    devices = []
    for i, dt_str in enumerate(["sensor", "camera", "drone", "robot"]):
        dev = _make_device(
            device_id=f"device-{i:03d}",
            name=f"Test Device {i}",
            device_type_str=dt_str,
            state_str="idle",
            host=f"192.168.1.{100 + i}",
            port=8080 + i,
            capabilities=[f"cap-{dt_str}"],
            location=f"zone-{chr(65 + i)}",
        )
        devices.append(dev)
    return devices


@pytest.fixture
def device_registry(sample_devices):
    from ..models.device import DeviceRegistry
    registry = DeviceRegistry()
    for device in sample_devices:
        registry.register(device)
    return registry


@pytest.fixture
def sample_task():
    from ..models.task import Task, TaskType, TaskPriority, RetryPolicy
    return Task(
        task_id="task-001",
        name="Test Task",
        description="Test task for unit tests",
        task_type=TaskType.COMMAND,
        priority=TaskPriority.NORMAL,
        required_devices=["device-000"],
        params={"command": "test_cmd", "args": []},
        timeout=30.0,
        retry_policy=RetryPolicy(max_retries=2, retry_delay=0.1),
    )


@pytest.fixture
def sample_tasks():
    from ..models.task import Task, TaskType, TaskPriority
    tasks = []
    for i in range(5):
        tasks.append(Task(
            task_id=f"task-{i:03d}",
            name=f"Test Task {i}",
            description=f"Test task {i}",
            task_type=TaskType.COMMAND,
            priority=TaskPriority(5),
            timeout=30.0,
        ))
    return tasks


@pytest.fixture
def coordinator_config():
    from ..core.multi_device_coordinator_engine import CoordinatorConfig
    from ..core.device_discovery import DiscoveryConfig
    from ..core.state_synchronizer import SyncConfig
    from ..core.task_scheduler import SchedulerConfig
    return CoordinatorConfig(
        node_id="test-coordinator",
        node_name="TestCoordinator",
        discovery_config=DiscoveryConfig(mdns_enabled=False, upnp_enabled=False, broadcast_enabled=False),
        sync_config=SyncConfig(gossip_interval=1.0, snapshot_interval=5.0),
        scheduler_config=SchedulerConfig(task_timeout=10.0),
        heartbeat_interval=2.0,
        heartbeat_timeout=10.0,
    )


@pytest.fixture
def engine(coordinator_config):
    from ..core.multi_device_coordinator_engine import MultiDeviceCoordinatorEngine
    return MultiDeviceCoordinatorEngine(coordinator_config)


@pytest.fixture
def circuit_breaker():
    from ..core.fault_tolerance import CircuitBreaker, CircuitBreakerConfig
    config = CircuitBreakerConfig(failure_threshold=3, success_threshold=2, timeout=1.0, half_open_max_calls=2, window_size=10.0)
    return CircuitBreaker("test-cb", config)


@pytest.fixture
def retry_manager():
    from ..core.fault_tolerance import RetryManager, RetryConfig
    config = RetryConfig(max_retries=3, base_delay=0.01, max_delay=0.1, exponential_backoff=True, jitter=False)
    return RetryManager(config)


@pytest.fixture
def failover_manager():
    from ..core.fault_tolerance import FailoverManager, FailoverConfig
    config = FailoverConfig(max_failover_attempts=3, health_check_interval=1.0, recovery_timeout=2.0)
    return FailoverManager(config)
