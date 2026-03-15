"""
Galaxy v5.0 - Multi-Device Coordination System (Legacy Compatibility Layer)

This package is the **legacy compatibility layer** for multi-device coordination.
It is **disabled by default** and must be explicitly enabled via:

    GALAXY_ENABLE_LEGACY_MULTIDEVICE=true

The canonical multi-device coordination engine is **Node_71**.
This layer exists only to support legacy AIP v2 binary clients.

Modules:
- device_protocol: AIP v2.0 protocol implementation
- device_manager: Device registration, discovery, and health monitoring
- device_coordinator: WebSocket-based real-time coordination
- cross_device_scheduler: Task scheduling with 6 load balancing strategies
- android_bridge: Android device integration via ADB
- failover_manager: Recovery mechanisms and circuit breaker pattern

Usage:
    # Enable legacy multi-device compat layer (disabled by default):
    export GALAXY_ENABLE_LEGACY_MULTIDEVICE=true

Author: Galaxy Team
Version: 5.0.0
License: MIT
"""

import os as _os

__version__ = "5.0.0"
__author__ = "Galaxy Team"

# ── Legacy compatibility gate ──────────────────────────────────────────────
# This module is disabled by default.  Set GALAXY_ENABLE_LEGACY_MULTIDEVICE=true
# to enable legacy AIP v2 multi-device coordination.
_LEGACY_ENABLED = _os.environ.get("GALAXY_ENABLE_LEGACY_MULTIDEVICE", "").lower() in ("1", "true", "yes")

if not _LEGACY_ENABLED:
    # Provide a clear notice when anyone imports from this package without the flag
    import warnings as _warnings
    _warnings.warn(
        "enhancements.multidevice (legacy compatibility layer) is DISABLED by default. "
        "Set GALAXY_ENABLE_LEGACY_MULTIDEVICE=true to enable it. "
        "The canonical multi-device engine is Node_71.",
        stacklevel=2,
    )

    # Export empty stubs so existing import sites don't hard-crash
    class _Disabled:
        """Stub class returned when the legacy multidevice layer is disabled."""
        def __init__(self, *a, **kw):
            raise RuntimeError(
                "enhancements.multidevice is disabled. "
                "Set GALAXY_ENABLE_LEGACY_MULTIDEVICE=true to enable."
            )

    # Minimal stub exports
    MessageType = DeviceType = DeviceStatus = TaskPriority = TaskState = _Disabled
    ErrorCode = DeviceCapabilities = DeviceInfo = TaskInfo = AIPMessage = _Disabled
    ProtocolError = ProtocolValidator = MessageBuilder = ProtocolHandler = _Disabled
    MessageRouter = DeviceManager = DeviceRegistrationRequest = _Disabled
    DeviceHeartbeatRequest = DeviceUpdateRequest = DeviceResponse = _Disabled
    DeviceListResponse = HealthMetrics = DeviceCoordinator = SessionManager = _Disabled
    DeviceSession = BroadcastRequest = SendRequest = SessionInfo = _Disabled
    CoordinatorStats = LoadBalancingStrategy = DeviceMetrics = TaskBatch = _Disabled
    LoadBalancer = RoundRobinBalancer = LeastConnectionsBalancer = _Disabled
    WeightedResponseTimeBalancer = ResourceBasedBalancer = GeographicBalancer = _Disabled
    AdaptiveBalancer = CrossDeviceScheduler = ADBError = DeviceNotFoundError = _Disabled
    InstallError = ScreenCaptureError = AndroidDeviceInfo = AppInfo = _Disabled
    TouchEvent = SwipeEvent = KeyEvent = ADBCommandExecutor = AndroidBridge = _Disabled
    RecoveryType = RecoveryStatus = Checkpoint = RecoveryResult = _Disabled
    RecoveryStrategy = RetryRecovery = FailoverRecovery = StateRecovery = _Disabled
    GracefulDegradation = FailoverManager = CircuitBreaker = CircuitState = _Disabled

    def create_device_manager_app(*a, **kw):
        raise RuntimeError(
            "enhancements.multidevice is disabled. "
            "Set GALAXY_ENABLE_LEGACY_MULTIDEVICE=true to enable."
        )
    create_coordinator_app = create_device_manager_app

else:
    # ── Full legacy layer (only when explicitly enabled) ───────────────────
    from .device_protocol import (
        MessageType,
        DeviceType,
        DeviceStatus,
        TaskPriority,
        TaskState,
        ErrorCode,
        DeviceCapabilities,
        DeviceInfo,
        TaskInfo,
        AIPMessage,
        ProtocolError,
        ProtocolValidator,
        MessageBuilder,
        ProtocolHandler,
        MessageRouter,
    )

    from .device_manager import (
        DeviceManager,
        DeviceRegistrationRequest,
        DeviceHeartbeatRequest,
        DeviceUpdateRequest,
        DeviceResponse,
        DeviceListResponse,
        HealthMetrics,
        create_app as create_device_manager_app
    )

    from .device_coordinator import (
        DeviceCoordinator,
        SessionManager,
        DeviceSession,
        BroadcastRequest,
        SendRequest,
        SessionInfo,
        CoordinatorStats,
        create_app as create_coordinator_app
    )

    from .cross_device_scheduler import (
        LoadBalancingStrategy,
        DeviceMetrics,
        TaskBatch,
        LoadBalancer,
        RoundRobinBalancer,
        LeastConnectionsBalancer,
        WeightedResponseTimeBalancer,
        ResourceBasedBalancer,
        GeographicBalancer,
        AdaptiveBalancer,
        CrossDeviceScheduler
    )

    from .android_bridge import (
        ADBError,
        DeviceNotFoundError,
        InstallError,
        ScreenCaptureError,
        AndroidDeviceInfo,
        AppInfo,
        TouchEvent,
        SwipeEvent,
        KeyEvent,
        ADBCommandExecutor,
        AndroidBridge
    )

    from .failover_manager import (
        RecoveryType,
        RecoveryStatus,
        Checkpoint,
        RecoveryResult,
        RecoveryStrategy,
        RetryRecovery,
        FailoverRecovery,
        StateRecovery,
        GracefulDegradation,
        FailoverManager
    )
    from core.monitoring import CircuitBreaker, CircuitState

__all__ = [
    # Version info
    '__version__',
    '__author__',
    
    # Protocol
    'MessageType',
    'DeviceType',
    'DeviceStatus',
    'TaskPriority',
    'TaskState',
    'ErrorCode',
    'DeviceCapabilities',
    'DeviceInfo',
    'TaskInfo',
    'AIPMessage',
    'ProtocolError',
    'ProtocolValidator',
    'MessageBuilder',
    'ProtocolHandler',
    'MessageRouter',
    'PROTOBUF_SCHEMA',
    
    # Device Manager
    'DeviceManager',
    'DeviceRegistrationRequest',
    'DeviceHeartbeatRequest',
    'DeviceUpdateRequest',
    'DeviceResponse',
    'DeviceListResponse',
    'HealthMetrics',
    'create_device_manager_app',
    
    # Device Coordinator
    'DeviceCoordinator',
    'SessionManager',
    'DeviceSession',
    'BroadcastRequest',
    'SendRequest',
    'SessionInfo',
    'CoordinatorStats',
    'create_coordinator_app',
    
    # Scheduler
    'LoadBalancingStrategy',
    'DeviceMetrics',
    'TaskBatch',
    'LoadBalancer',
    'RoundRobinBalancer',
    'LeastConnectionsBalancer',
    'WeightedResponseTimeBalancer',
    'ResourceBasedBalancer',
    'GeographicBalancer',
    'AdaptiveBalancer',
    'CrossDeviceScheduler',
    
    # Android Bridge
    'ADBError',
    'DeviceNotFoundError',
    'InstallError',
    'ScreenCaptureError',
    'AndroidDeviceInfo',
    'AppInfo',
    'TouchEvent',
    'SwipeEvent',
    'KeyEvent',
    'ADBCommandExecutor',
    'AndroidBridge',
    
    # Failover Manager
    'RecoveryType',
    'CircuitState',
    'RecoveryStatus',
    'Checkpoint',
    'RecoveryResult',
    'CircuitBreaker',
    'RecoveryStrategy',
    'RetryRecovery',
    'FailoverRecovery',
    'StateRecovery',
    'GracefulDegradation',
    'FailoverManager'
]
