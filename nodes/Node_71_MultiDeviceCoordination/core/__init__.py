"""
Node 71 - MultiDeviceCoordination Core Module
核心模块导出

架构定位（PR-7）：Node_71 为编排/协调消费者，不充当对等的规范设备注册权威。
规范设备摄取路径：ingest_canonical_device_view() / canonical_device_view_adapter

Import note
-----------
Device / task model types (Device, DeviceType, DeviceState, etc.) are NOT
re-exported from this package to avoid a circular import:

    models.device → core.device_types (repo-root core)
                  → core.__init__ (this file) → models.device  (circular back to start)

Callers that need device / task model types should import from the models
package directly::

    from models.device import Device, DeviceType, DeviceState, ...
    from models.task import Task, TaskState, ...

This package exports only types that originate within the Node_71 core modules.
"""
from core.canonical_device_view_adapter import (
    CoordinationDeviceView,
    CoordinationDeviceStatus,
    adapt_registered_runtime_device,
    adapt_registered_runtime_device_dict,
    refresh_coordination_view,
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
    # Canonical Device Intake (PR-7)
    "CoordinationDeviceView", "CoordinationDeviceStatus",
    "adapt_registered_runtime_device", "adapt_registered_runtime_device_dict",
    "refresh_coordination_view",

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
