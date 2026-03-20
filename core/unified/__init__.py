"""
core/unified/__init__.py
=========================
Galaxy 统一模块公开导出入口。

使用方式：
    from core.unified import (
        UnifiedDevice, UnifiedDeviceType, UnifiedDeviceStatus,
        UnifiedConnectionManager, get_unified_connection_manager,
        UnifiedDeviceManager, get_unified_device_manager,
        UnifiedConfigManager, get_unified_config_manager,
        UnifiedLLMRouter, get_unified_llm_router,
        # PR-1 additions
        EntrypointRouter, get_entrypoint_router, reset_entrypoint_router,
        DeviceState, TaskState, CognitiveState, PresenceState, ExecutionState,
        EntryPath, TaskStatus, PresencePhase, ExecutionStatus,
        # PR-2 additions
        CommandEnvelope, ResultEnvelope, ENVELOPE_VERSION,
        EnvelopeValidationError, validate_command_envelope, validate_result_envelope,
        log_command_envelope, log_result_envelope,
        CapabilityContract, CapabilitySource, CapabilityContractError,
        validate_capability_contract, is_valid_capability_contract,
        CapabilityResolver, get_capability_resolver, reset_capability_resolver,
    )
"""

from .exceptions import (
    ConfigError,
    ConfigKeyNotFoundError,
    ConnectionError,
    DeviceAlreadyRegisteredError,
    DeviceManagerError,
    DeviceNotFoundError,
    DeviceRegistrationError,
    DeviceSendError,
    DeviceTimeoutError,
    GalaxyError,
    LLMProviderError,
    LLMRouterError,
    NoAvailableProviderError,
)
from .models import (
    DeviceCommand,
    DeviceCommandResult,
    LLMRequest,
    LLMResponse,
    LLMTaskType,
    UnifiedConnectionInfo,
    UnifiedConnectionState,
    UnifiedDevice,
    UnifiedDeviceStatus,
    UnifiedDeviceType,
    UnifiedMessage,
    UnifiedMessageType,
)
from .connection_manager import UnifiedConnectionManager, get_unified_connection_manager
from .device_manager import UnifiedDeviceManager, get_unified_device_manager
from .config_manager import UnifiedConfigManager, get_unified_config_manager
from .llm_router import UnifiedLLMRouter, get_unified_llm_router
# PR-1: entrypoint router
from .entrypoint_router import (
    EntrypointRouter,
    get_entrypoint_router,
    reset_entrypoint_router,
)
# PR-1: unified state schema
from .state_schema import (
    EntryPath,
    TaskStatus,
    PresencePhase,
    ExecutionStatus,
    DeviceState,
    TaskState,
    CognitiveState,
    PresenceState,
    ExecutionState,
)
# PR-2: command envelope
from .command_envelope import (
    CommandEnvelope,
    CommandVerb,
    CancelReason,
    ResultEnvelope,
    ENVELOPE_VERSION,
    EnvelopeValidationError,
    validate_command_envelope,
    validate_result_envelope,
    log_command_envelope,
    log_result_envelope,
)
# PR-4: device health scorer
from .device_health import (
    DeviceHealthScorer,
    HealthScore,
    get_device_health_scorer,
    reset_device_health_scorer,
)
# PR-2: capability contract + resolver
from .capability_contract import (
    CapabilityContract,
    CapabilitySource,
    CapabilityContractError,
    validate_capability_contract,
    is_valid_capability_contract,
)
from .capability_resolver import (
    CapabilityResolver,
    get_capability_resolver,
    reset_capability_resolver,
)

__all__ = [
    # exceptions
    "GalaxyError",
    "ConnectionError",
    "DeviceNotFoundError",
    "DeviceSendError",
    "DeviceTimeoutError",
    "DeviceManagerError",
    "DeviceAlreadyRegisteredError",
    "DeviceRegistrationError",
    "ConfigError",
    "ConfigKeyNotFoundError",
    "LLMRouterError",
    "NoAvailableProviderError",
    "LLMProviderError",
    # models
    "UnifiedDeviceType",
    "UnifiedDeviceStatus",
    "UnifiedConnectionState",
    "UnifiedMessageType",
    "UnifiedDevice",
    "UnifiedConnectionInfo",
    "UnifiedMessage",
    "DeviceCommand",
    "DeviceCommandResult",
    "LLMTaskType",
    "LLMRequest",
    "LLMResponse",
    # managers
    "UnifiedConnectionManager",
    "get_unified_connection_manager",
    "UnifiedDeviceManager",
    "get_unified_device_manager",
    "UnifiedConfigManager",
    "get_unified_config_manager",
    "UnifiedLLMRouter",
    "get_unified_llm_router",
    # PR-1: entrypoint router
    "EntrypointRouter",
    "get_entrypoint_router",
    "reset_entrypoint_router",
    # PR-1: state schema
    "EntryPath",
    "TaskStatus",
    "PresencePhase",
    "ExecutionStatus",
    "DeviceState",
    "TaskState",
    "CognitiveState",
    "PresenceState",
    "ExecutionState",
    # PR-2: command envelope
    "CommandEnvelope",
    "CommandVerb",
    "CancelReason",
    "ResultEnvelope",
    "ENVELOPE_VERSION",
    "EnvelopeValidationError",
    "validate_command_envelope",
    "validate_result_envelope",
    "log_command_envelope",
    "log_result_envelope",
    # PR-4: device health
    "DeviceHealthScorer",
    "HealthScore",
    "get_device_health_scorer",
    "reset_device_health_scorer",
    # PR-2: capability contract + resolver
    "CapabilityContract",
    "CapabilitySource",
    "CapabilityContractError",
    "validate_capability_contract",
    "is_valid_capability_contract",
    "CapabilityResolver",
    "get_capability_resolver",
    "reset_capability_resolver",
]
