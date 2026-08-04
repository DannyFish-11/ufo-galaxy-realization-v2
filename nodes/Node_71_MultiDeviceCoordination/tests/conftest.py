"""
Node 71 - Test Configuration
pytest conftest 和共享 fixtures

Path setup
----------
Node_71 用到两个叫 ``core`` 的东西：

- 仓库根的 ``core.device_types`` —— models/device.py 真的需要它；
- 本节点自己的 ``core/*.py`` —— device_discovery、task_scheduler 等。

**过去**这两者靠一个把戏共存：把节点的 core 子模块按文件路径加载，塞进
``sys.modules["core.<名字>"]``，于是节点内部的裸 ``from core.device_discovery import ...``
也能解析。那时节点模块写的就是裸导入，这个把戏是必需的。

**现在**节点已改成相对导入（``from .device_discovery import ...``、
``from ..models.device import ...``）—— 因为它要能被当作真包用：
``nodes.Node_71_MultiDeviceCoordination.core.X``。裸导入在那种用法下会撞上仓库根的
``core``，直接 ModuleNotFoundError。

改成相对导入之后，上面那个把戏就**反过来坏事**了：模块被安上 ``core.<名字>`` 这个
假名字加载，顶层包就成了 ``core``，于是 ``..models`` 越过顶层，报
"attempted relative import beyond top-level package"。而这个异常当时被
``except Exception: pass`` 吞掉，症状只剩下测试里一句莫名其妙的
``No module named 'core.multi_device_coordinator_engine'``。

所以这里改成：**按真实点分路径 import 一次**（不需要任何 sys.path 注入，各层
``__init__.py`` 都在），再把同一批模块对象登记成 ``core.<名字>`` / ``models`` 别名，
好让本目录下那五个测试文件里既有的裸 import 原样继续可用。

关键是"同一批模块对象"：如果别名指向重新加载的第二份，测试拿到的 ``Device`` 类
和引擎注册表里的就不是同一个类，isinstance 与枚举比较会静默走偏。

Heavy model imports are deferred into fixture functions to keep conftest load clean.
"""
import importlib
import os
import sys

import pytest

# ─── Path setup ──────────────────────────────────────────────────────────────

_NODE71_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(os.path.dirname(_NODE71_DIR))

# 仓库根要在 sys.path 上：节点是以 ``nodes.Node_71_MultiDeviceCoordination`` 这个
# 真实点分路径被 import 的，而 models/device.py 还要 ``from core.device_types import``。
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_N71_PKG = "nodes.Node_71_MultiDeviceCoordination"

# ─── 按真实路径 import，再登记向后兼容的别名 ─────────────────────────────────

# 顺序无所谓了 —— import 系统自己会按依赖拉齐；列表只是为了枚举要起别名的模块。
_N71_CORE_MODULES = [
    "canonical_device_view_adapter",
    "fault_tolerance",
    "device_discovery",
    "state_synchronizer",
    "task_scheduler",
    "multi_device_coordinator_engine",
]


def _alias_n71_module(kind: str, mod_name: str) -> None:
    """把 ``nodes.…​.<kind>.<mod_name>`` 同一个模块对象登记成裸 ``<kind>.<mod_name>``。"""
    module = importlib.import_module(f"{_N71_PKG}.{kind}.{mod_name}")
    sys.modules[f"{kind}.{mod_name}"] = module
    setattr(sys.modules[kind], mod_name, module)


# ``models`` 整个包也要起别名：``from models.device import X`` 会先 import 父包
# ``models``，而仓库根那个 models/ 是空的，撞上去只会给出一个没有 device 的命名空间包。
sys.modules["models"] = importlib.import_module(f"{_N71_PKG}.models")
for _mod in ("device", "task"):
    _alias_n71_module("models", _mod)

# ``core`` 不能整包替换 —— models/device.py 要的 ``core.device_types`` 在仓库根那个
# core 里。所以只登记子模块别名，和过去的做法一致。
importlib.import_module("core")
for _mod in _N71_CORE_MODULES:
    _alias_n71_module("core", _mod)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures (all imports deferred to fixture body)
# ─────────────────────────────────────────────────────────────────────────────


def _make_device(device_id, name, device_type_str, state_str="idle",
                 host="127.0.0.1", port=8080, capabilities=None,
                 location=None, resource_constraints=None):
    from models.device import Device, DeviceType, DeviceState, Capability, ResourceConstraints
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
    from models.device import ResourceConstraints
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
    from models.device import DeviceRegistry
    registry = DeviceRegistry()
    for device in sample_devices:
        registry.register(device)
    return registry


@pytest.fixture
def sample_task():
    from models.task import Task, TaskType, TaskPriority, RetryPolicy
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
    from models.task import Task, TaskType, TaskPriority
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
    from core.multi_device_coordinator_engine import CoordinatorConfig
    from core.device_discovery import DiscoveryConfig
    from core.state_synchronizer import SyncConfig
    from core.task_scheduler import SchedulerConfig
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
    from core.multi_device_coordinator_engine import MultiDeviceCoordinatorEngine
    return MultiDeviceCoordinatorEngine(coordinator_config)


@pytest.fixture
def circuit_breaker():
    from core.fault_tolerance import CircuitBreaker, CircuitBreakerConfig
    config = CircuitBreakerConfig(failure_threshold=3, success_threshold=2, timeout=1.0, half_open_max_calls=2, window_size=10.0)
    return CircuitBreaker("test-cb", config)


@pytest.fixture
def retry_manager():
    from core.fault_tolerance import RetryManager, RetryConfig
    config = RetryConfig(max_retries=3, base_delay=0.01, max_delay=0.1, exponential_backoff=True, jitter=False)
    return RetryManager(config)


@pytest.fixture
def failover_manager():
    from core.fault_tolerance import FailoverManager, FailoverConfig
    config = FailoverConfig(max_failover_attempts=3, health_check_interval=1.0, recovery_timeout=2.0)
    return FailoverManager(config)
