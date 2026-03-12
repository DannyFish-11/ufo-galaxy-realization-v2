"""
编排器模块

提供任务编排和多设备协同功能
"""

try:
    from .task_orchestrator import (
        Task,
        TaskPriority,
        TaskOrchestrator,
        MultiDeviceOrchestrator
    )
except Exception:  # noqa: BLE001
    pass

try:
    from .galaxy_orchestrator import (
        GalaxyOrchestrator,
        AIGateway,
        DeviceManager as GalaxyDeviceManager,
        create_orchestrator,
    )
except Exception:  # noqa: BLE001
    pass

from .parallel_tracker import (
    ParallelSubtaskResult,
    ParallelGroupStatus,
    ParallelGroupTracker,
    get_tracker,
    record_parallel_fields,
)

__all__ = [
    "Task",
    "TaskPriority",
    "TaskOrchestrator",
    "MultiDeviceOrchestrator",
    "GalaxyOrchestrator",
    "AIGateway",
    "GalaxyDeviceManager",
    "create_orchestrator",
    "ParallelSubtaskResult",
    "ParallelGroupStatus",
    "ParallelGroupTracker",
    "get_tracker",
    "record_parallel_fields",
]
