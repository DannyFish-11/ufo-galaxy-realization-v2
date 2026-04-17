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
from .mesh_session_persistence import (
    SnapshotRecord,
    MeshSessionPersistenceStore,
    save_mesh_session_snapshot,
    load_mesh_session_snapshot,
    recover_mesh_sessions,
    list_recoverable_sessions,
    get_persistence_store,
    reset_persistence_store,
    MESH_SESSION_PERSISTENCE_IS_AUTHORITY,
    MESH_SESSION_PERSISTENCE_GAP_CLOSURE_SENTINEL,
    RECOVERY_RESTORES_NON_TERMINAL_SESSIONS_POLICY,
    PERSISTENCE_DOES_NOT_OWN_RUNTIME_TRUTH_POLICY,
)
from .mesh_session_lifecycle import (
    SessionRegistryEntry,
    MeshSessionLifecycleManager,
    get_lifecycle_manager,
    reset_lifecycle_manager,
    MESH_SESSION_LIFECYCLE_AUTHORITY,
    LIFECYCLE_PERSISTS_ON_EVERY_TRANSITION_POLICY,
    LIFECYCLE_DOES_NOT_OWN_RUNTIME_TRUTH_POLICY,
    DURABLE_FOUNDATION_FOR_RESTORE_ROAMING_REBALANCE_SENTINEL,
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
    # Persistence
    "SnapshotRecord",
    "MeshSessionPersistenceStore",
    "save_mesh_session_snapshot",
    "load_mesh_session_snapshot",
    "recover_mesh_sessions",
    "list_recoverable_sessions",
    "get_persistence_store",
    "reset_persistence_store",
    "MESH_SESSION_PERSISTENCE_IS_AUTHORITY",
    "MESH_SESSION_PERSISTENCE_GAP_CLOSURE_SENTINEL",
    "RECOVERY_RESTORES_NON_TERMINAL_SESSIONS_POLICY",
    "PERSISTENCE_DOES_NOT_OWN_RUNTIME_TRUTH_POLICY",
    # Lifecycle
    "SessionRegistryEntry",
    "MeshSessionLifecycleManager",
    "get_lifecycle_manager",
    "reset_lifecycle_manager",
    "MESH_SESSION_LIFECYCLE_AUTHORITY",
    "LIFECYCLE_PERSISTS_ON_EVERY_TRANSITION_POLICY",
    "LIFECYCLE_DOES_NOT_OWN_RUNTIME_TRUTH_POLICY",
    "DURABLE_FOUNDATION_FOR_RESTORE_ROAMING_REBALANCE_SENTINEL",
]
