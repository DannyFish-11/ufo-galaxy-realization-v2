"""
Node 71 - MultiDeviceCoordination Core Module
核心模块导出
"""
import sys
import os

# 确保模块路径正确
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from models.device import (
    Device, DeviceType, DeviceState, DeviceRegistry,
    Capability, ResourceConstraints, VectorClock, DiscoveryProtocol
)
from models.task import (
    Task, TaskState, TaskPriority, TaskType, TaskDependency,
    TaskResource, RetryPolicy, SubTask, TaskQueue, SchedulingStrategy
)
from core.device_discovery import (
    DeviceDiscovery, DiscoveryConfig, DiscoveryEvent, DiscoveryEventType,
    BroadcastDiscovery, MDNSDiscovery, UPNPDiscovery
)
from core.state_synchronizer import (
    StateSynchronizer, SyncConfig, StateEvent, SyncEventType,
    ConflictResolution, ConflictResolver, GossipProtocol
)
from core.task_scheduler import (
    TaskScheduler, SchedulerConfig, SchedulerEvent, SchedulerEventType,
    DeviceSelector, TaskExecutor, DependencyResolver
)
from core.multi_device_coordinator_engine import (
    MultiDeviceCoordinatorEngine, CoordinatorConfig, CoordinatorState,
    create_coordinator
)

# 尝试导入容错模块（可选）
try:
    from core.fault_tolerance import (
        CircuitBreaker, CircuitBreakerConfig, CircuitBreakerOpenError, CircuitState,
        RetryManager, RetryConfig,
        FailoverManager, FailoverConfig,
        FaultToleranceLayer
    )
    _has_fault_tolerance = True
except ImportError:
    _has_fault_tolerance = False

__all__ = [
    # Device Models
    "Device", "DeviceType", "DeviceState", "DeviceRegistry",
    "Capability", "ResourceConstraints", "VectorClock", "DiscoveryProtocol",

    # Task Models
    "Task", "TaskState", "TaskPriority", "TaskType", "TaskDependency",
    "TaskResource", "RetryPolicy", "SubTask", "TaskQueue", "SchedulingStrategy",

    # Device Discovery
    "DeviceDiscovery", "DiscoveryConfig", "DiscoveryEvent", "DiscoveryEventType",
    "BroadcastDiscovery", "MDNSDiscovery", "UPNPDiscovery",

    # State Synchronizer
    "StateSynchronizer", "SyncConfig", "StateEvent", "SyncEventType",
    "ConflictResolution", "ConflictResolver", "GossipProtocol",

    # Task Scheduler
    "TaskScheduler", "SchedulerConfig", "SchedulerEvent", "SchedulerEventType",
    "DeviceSelector", "TaskExecutor", "DependencyResolver",

    # Coordinator Engine
    "MultiDeviceCoordinatorEngine", "CoordinatorConfig", "CoordinatorState",
    "create_coordinator",
]

# 添加容错模块到导出（如果可用）
if _has_fault_tolerance:
    __all__.extend([
        "CircuitBreaker", "CircuitBreakerConfig", "CircuitBreakerOpenError", "CircuitState",
        "RetryManager", "RetryConfig",
        "FailoverManager", "FailoverConfig",
        "FaultToleranceLayer"
    ])
