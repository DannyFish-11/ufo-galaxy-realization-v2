"""core/mesh — Body Mesh model for device role allocation."""

from .body_mesh_registry import (
    BodyMeshRegistry,
    BodyEntry,
    DeviceRole,
    BodyAssignment,
    get_body_mesh_registry,
    reset_body_mesh_registry,
)
from .device_role_allocator import (
    DeviceRoleAllocator,
    AllocationResult,
    get_device_role_allocator,
    reset_device_role_allocator,
)

__all__ = [
    "BodyMeshRegistry",
    "BodyEntry",
    "DeviceRole",
    "BodyAssignment",
    "get_body_mesh_registry",
    "reset_body_mesh_registry",
    "DeviceRoleAllocator",
    "AllocationResult",
    "get_device_role_allocator",
    "reset_device_role_allocator",
]
