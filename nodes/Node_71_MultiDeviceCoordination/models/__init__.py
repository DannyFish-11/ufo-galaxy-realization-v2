"""
Node 71 - Models Module
数据模型导出
"""
try:
    from nodes.Node_71_MultiDeviceCoordination.models.device import (
        Device, DeviceType, DeviceState, DeviceRegistry,
        Capability, ResourceConstraints, VectorClock, DiscoveryProtocol
    )
    from nodes.Node_71_MultiDeviceCoordination.models.task import (
        Task, TaskState, TaskPriority, TaskType, TaskDependency,
        TaskResource, RetryPolicy, SubTask, TaskQueue, SchedulingStrategy
    )
except ImportError:
    from models.device import (
        Device, DeviceType, DeviceState, DeviceRegistry,
        Capability, ResourceConstraints, VectorClock, DiscoveryProtocol
    )
    from models.task import (
        Task, TaskState, TaskPriority, TaskType, TaskDependency,
        TaskResource, RetryPolicy, SubTask, TaskQueue, SchedulingStrategy
    )

__all__ = [
    # Device Models
    "Device", "DeviceType", "DeviceState", "DeviceRegistry",
    "Capability", "ResourceConstraints", "VectorClock", "DiscoveryProtocol",

    # Task Models
    "Task", "TaskState", "TaskPriority", "TaskType", "TaskDependency",
    "TaskResource", "RetryPolicy", "SubTask", "TaskQueue", "SchedulingStrategy"
]
