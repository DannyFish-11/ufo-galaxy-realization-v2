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
        # Block-5 additions
        GalaxyErrorCode, ErrorPayload, Retryable, ErrorSeverity, ErrorDomain,
        is_retryable, get_error_descriptor,
        ErrorMapper,
        IdempotencyStore, IdempotencyEntry, IdempotencyStatus,
        DuplicateCommandError, IdempotencyConflictError,
        get_idempotency_store, reset_idempotency_store,
        check_idempotency, record_idempotency, make_payload_hash,
        ReleaseGate, FeatureDisabledError, RolloutBlockedError,
        get_release_gate, reset_release_gate,
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
# Block-5: error taxonomy
from .error_codes import (
    GalaxyErrorCode,
    ErrorPayload,
    Retryable,
    ErrorSeverity,
    ErrorDomain,
    is_retryable,
    get_descriptor as get_error_descriptor,
)
# Block-5: error mapper
from .error_mapper import ErrorMapper
# Block-5: idempotency
from .idempotency import (
    IdempotencyStore,
    IdempotencyEntry,
    IdempotencyStatus,
    DuplicateCommandError,
    IdempotencyConflictError,
    get_idempotency_store,
    reset_idempotency_store,
    check_idempotency,
    record_idempotency,
    make_payload_hash,
)
# Block-5: release gate
from .release_gate import (
    ReleaseGate,
    FeatureDisabledError,
    RolloutBlockedError,
    get_release_gate,
    reset_release_gate,
)

# PR-29: Registered Runtime Device Contract (re-exported from contracts package)
from contracts.registered_runtime_device import (  # noqa: E402
    RegisteredRuntimeDevice,
    RuntimeConnectionSummary,
    RuntimeCapabilityProfile,
    RuntimeAutonomySummary,
    RuntimeSessionPresence,
    RuntimeParticipationHints,
    RuntimeDevicePlatform,
    RuntimeDeviceFormFactor,
    RuntimeDeviceStatus,
    RuntimeConnectionState,
    build_registered_runtime_device,
    from_udm_device,
    from_router_device,
    from_android_registration,
    from_device_registry_record,
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
    # Block-5: error taxonomy
    "GalaxyErrorCode",
    "ErrorPayload",
    "Retryable",
    "ErrorSeverity",
    "ErrorDomain",
    "is_retryable",
    "get_error_descriptor",
    # Block-5: error mapper
    "ErrorMapper",
    # Block-5: idempotency
    "IdempotencyStore",
    "IdempotencyEntry",
    "IdempotencyStatus",
    "DuplicateCommandError",
    "IdempotencyConflictError",
    "get_idempotency_store",
    "reset_idempotency_store",
    "check_idempotency",
    "record_idempotency",
    "make_payload_hash",
    # Block-5: release gate
    "ReleaseGate",
    "FeatureDisabledError",
    "RolloutBlockedError",
    "get_release_gate",
    "reset_release_gate",
    # PR-29: Registered Runtime Device Contract
    "RegisteredRuntimeDevice",
    "RuntimeConnectionSummary",
    "RuntimeCapabilityProfile",
    "RuntimeAutonomySummary",
    "RuntimeSessionPresence",
    "RuntimeParticipationHints",
    "RuntimeDevicePlatform",
    "RuntimeDeviceFormFactor",
    "RuntimeDeviceStatus",
    "RuntimeConnectionState",
    "build_registered_runtime_device",
    "from_udm_device",
    "from_router_device",
    "from_android_registration",
    "from_device_registry_record",
]
