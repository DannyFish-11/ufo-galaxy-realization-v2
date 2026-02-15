"""
UFO Galaxy v5.0 - Multi-Device Coordination System

This package provides comprehensive multi-device coordination capabilities
for the UFO Galaxy distributed intelligence platform.

Modules:
- device_protocol: AIP v2.0 protocol implementation
- device_manager: Device registration, discovery, and health monitoring
- device_coordinator: WebSocket-based real-time coordination
- cross_device_scheduler: Task scheduling with 6 load balancing strategies
- android_bridge: Android device integration via ADB
- failover_manager: Recovery mechanisms and circuit breaker pattern

Features:
- Device discovery and registration (<3s)
- Heartbeat monitoring (5s interval)
- Task scheduling across devices (500+ TPS)
- 6 load balancing strategies
- AIP v2.0 protocol
- Cross-platform support (Linux, Android)
- 4 recovery mechanisms
- Circuit breaker pattern

Usage:
    from multidevice import DeviceManager, DeviceCoordinator
    from multidevice import CrossDeviceScheduler, AndroidBridge
    from multidevice import FailoverManager

Author: UFO Galaxy Team
Version: 5.0.0
License: MIT
"""

__version__ = "5.0.0"
__author__ = "UFO Galaxy Team"

# Protocol module
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
    PROTOBUF_SCHEMA
)

# Device Manager module
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

# Device Coordinator module
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

# Cross-Device Scheduler module
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

# Android Bridge module
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

# Failover Manager module
from .failover_manager import (
    RecoveryType,
    CircuitState,
    RecoveryStatus,
    CircuitBreakerConfig,
    Checkpoint,
    RecoveryResult,
    CircuitBreaker,
    RecoveryStrategy,
    RetryRecovery,
    FailoverRecovery,
    StateRecovery,
    GracefulDegradation,
    FailoverManager
)

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
    'CircuitBreakerConfig',
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
