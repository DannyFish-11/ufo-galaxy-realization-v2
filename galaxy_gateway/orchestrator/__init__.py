"""
编排器模块

提供任务编排和多设备协同功能
"""

try:
    from .task_orchestrator import MultiDeviceOrchestrator, Task, TaskOrchestrator, TaskPriority
except Exception:  # noqa: BLE001
    pass

try:
    from .galaxy_orchestrator import (
        AIGateway,
    )
    from .galaxy_orchestrator import DeviceManager as GalaxyDeviceManager
    from .galaxy_orchestrator import (
        GalaxyOrchestrator,
        create_orchestrator,
    )
except Exception:  # noqa: BLE001
    pass

from .parallel_tracker import (
    ParallelGroupStatus,
    ParallelGroupTracker,
    ParallelSubtaskResult,
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
