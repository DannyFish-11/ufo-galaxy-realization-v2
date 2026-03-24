"""
Node 71 - Test Configuration
pytest conftest 和共享 fixtures

Path setup (PR-7)
-----------------
Node_71 uses two ``core`` packages:
- top-level ``core.device_types`` (repo root) — needed by models/device.py
- local ``core/*.py`` (Node_71 core submodules) — device_discovery, scheduler, etc.

To resolve this conflict we:
1. Put the repo root FIRST in sys.path so ``core`` resolves to the top-level core
   (which has ``device_types``).
2. Pre-register Node_71's local core submodules into ``sys.modules`` under their
   expected dotted names (``core.device_discovery``, etc.) by loading them directly
   from their file paths with importlib.  This makes them importable as
   ``from core.device_discovery import ...`` within the test run without conflicting
   with the top-level ``core`` package.

Heavy model imports are deferred into fixture functions to keep conftest load clean.
"""
import sys
import os
import importlib.util
import pytest

# ─── Path setup ──────────────────────────────────────────────────────────────

_NODE71_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(os.path.dirname(_NODE71_DIR))
_N71_CORE = os.path.join(_NODE71_DIR, "core")

# Repo root FIRST → ``core`` = top-level Galaxy core (has device_types).
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
# Node_71 dir SECOND → ``models``, local imports.
if _NODE71_DIR not in sys.path:
    sys.path.insert(1, _NODE71_DIR)

# ─── Pre-register Node_71 core submodules ────────────────────────────────────
# Load each Node_71 core submodule from its file path and register it in
# sys.modules as ``core.<name>`` so that internal imports like
# ``from core.device_discovery import DiscoveryConfig`` resolve correctly,
# even though the top-level ``core`` package is now the repo-root one.

def _preload_n71_core_module(mod_name: str) -> None:
    """Load a Node_71 core submodule and register it in sys.modules."""
    full_name = f"core.{mod_name}"
    if full_name in sys.modules:
        return
    path = os.path.join(_N71_CORE, f"{mod_name}.py")
    if not os.path.exists(path):
        return
    spec = importlib.util.spec_from_file_location(full_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module  # register BEFORE exec to handle circular refs
    try:
        spec.loader.exec_module(module)
        # Also expose as attribute of the top-level core package
        import core as _core_pkg
        setattr(_core_pkg, mod_name, module)
    except Exception as exc:
        # Remove failed registration so future attempts can retry
        sys.modules.pop(full_name, None)
        raise exc


# Order matters: leaf modules first, dependents after.
_N71_CORE_MODULES = [
    "canonical_device_view_adapter",
    "fault_tolerance",
    "device_discovery",
    "state_synchronizer",
    "task_scheduler",
    "multi_device_coordinator_engine",
]

for _mod in _N71_CORE_MODULES:
    try:
        _preload_n71_core_module(_mod)
    except Exception:
        pass  # best-effort; individual tests will fail with clear errors if needed

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
