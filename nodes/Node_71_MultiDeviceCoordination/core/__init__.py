"""
Node 71 - MultiDeviceCoordination Core Module
核心模块导出
"""
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
from core.fault_tolerance import (
    CircuitBreaker, CircuitBreakerConfig, CircuitBreakerOpenError, CircuitState,
    RetryManager, RetryConfig,
    FailoverManager, FailoverConfig,
    FaultToleranceLayer
)

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

    # Fault Tolerance
    "CircuitBreaker", "CircuitBreakerConfig", "CircuitBreakerOpenError", "CircuitState",
    "RetryManager", "RetryConfig",
    "FailoverManager", "FailoverConfig",
    "FaultToleranceLayer"
]
