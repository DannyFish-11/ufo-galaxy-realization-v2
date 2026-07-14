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

# PR-36: Cross-Runtime Result Merge Contract (re-exported from contracts package)
from contracts.cross_runtime_result_merge import (
    MergedRuntimeResult,
    ResultMergeInput,
    ResultMergePolicy,
    ResultMergeSummary,
    RuntimeResultProvenance,
    RuntimeResultRole,
    RuntimeResultStatus,
    RuntimeResultUnit,
    build_merged_runtime_result,
    build_result_merge_summary,
)
from contracts.cross_runtime_result_merge import from_execution_output as merge_unit_from_execution_output
from contracts.cross_runtime_result_merge import (  # noqa: E402
    from_local_takeover_result as merge_unit_from_takeover_result,
)
from contracts.cross_runtime_result_merge import from_source_dispatch_result as merge_unit_from_dispatch_result
from contracts.cross_runtime_result_merge import (
    merge_runtime_results,
)

# PR-31: Handoff Envelope v2 Contract (re-exported from contracts package)
from contracts.handoff_envelope_v2 import (  # noqa: E402
    HandoffAgentSpec,
    HandoffEnvelopeV2,
    HandoffReturnContract,
    HandoffSessionContext,
    HandoffSourceSummary,
    HandoffTargetSummary,
    HandoffTaskSpec,
    LocalTakeoverPolicy,
    build_handoff_envelope_v2,
    from_bridge_inputs,
    from_legacy_handoff_contract,
    to_legacy_bridge_payload,
)

# PR-30: Local Runtime Host Contract (re-exported from contracts package)
from contracts.local_runtime_host import (  # noqa: E402
    LocalRuntimeExecutionMode,
    LocalRuntimeExecutionSupport,
    LocalRuntimeHandoffSupport,
    LocalRuntimeHost,
    LocalRuntimeHostCapabilities,
    LocalRuntimeHostStatus,
    LocalRuntimeSessionSupport,
    build_local_runtime_host,
    from_registered_runtime_device,
    from_runtime_bridge_config,
    summarize_local_runtime_host,
)

# PR-34: Local Takeover Result Contract (re-exported from contracts package)
from contracts.local_takeover_result import (
    LocalTakeoverResult,
    LocalTakeoverSessionContext,
    LocalTakeoverStatus,
    build_local_takeover_result,
)
from contracts.local_takeover_result import failure_result as takeover_failure_result
from contracts.local_takeover_result import from_execution_output as takeover_result_from_execution_output  # noqa: E402

# PR-32: Mesh Membership Contract (re-exported from contracts package)
from contracts.mesh_membership import (  # noqa: E402
    MeshAuthorityScope,
    MeshMemberRole,
    MeshMembership,
    MeshParticipationHints,
    MeshRoutingIntent,
    build_mesh_membership,
    from_body_mesh_entry,
    from_cross_device_routing_summary,
    from_device_formation_summary,
)

# PR-33: Mesh Session Contract (re-exported from contracts package)
from contracts.mesh_session import (
    MeshBarrierPosture,
    MeshMergePolicy,
    MeshSession,
    MeshSessionParticipant,
    MeshSessionStatus,
    MeshSubtaskAssignment,
    build_mesh_session,
    from_constellation_decomposition,
)
from contracts.mesh_session import from_cross_device_routing_summary as mesh_session_from_routing
from contracts.mesh_session import from_device_formation_summary as mesh_session_from_formation  # noqa: E402

# PR-37: Mesh Session Coordinator Contract
from contracts.mesh_session_coordinator import (
    MeshAssignmentState,
    MeshAssignmentStatus,
    MeshBarrierState,
    MeshBarrierStatus,
    MeshCoordinationEvent,
    MeshCoordinationEventKind,
    MeshCoordinatorStatus,
    MeshParticipantCoordinationState,
    MeshParticipantStatus,
    MeshSessionCoordinatorState,
    MeshSessionCoordinatorSummary,
    build_coordinator_summary,
    build_mesh_session_coordinator,
)
from contracts.mesh_session_coordinator import from_mesh_session as coordinator_from_mesh_session  # noqa: E402
from contracts.mesh_session_coordinator import (
    update_coordinator_with_dispatch_result,
    update_coordinator_with_merged_result,
    update_coordinator_with_takeover_result,
)

# PR-38: Unified Multi-Device Runtime Projection
from contracts.multi_device_runtime_projection import (  # noqa: E402
    MultiDeviceRuntimeProjection,
    RuntimeProjectionCoordinatorEntry,
    RuntimeProjectionDeviceEntry,
    RuntimeProjectionDispatchEntry,
    RuntimeProjectionHandoffEntry,
    RuntimeProjectionHostEntry,
    RuntimeProjectionMeshSessionEntry,
    RuntimeProjectionResultEntry,
    RuntimeProjectionTakeoverEntry,
    build_multi_device_runtime_projection,
    project_coordinator_state,
    project_handoffs,
    project_merged_results,
    project_mesh_sessions,
    project_runtime_devices,
    project_runtime_hosts,
    project_source_dispatches,
    project_takeovers,
)

# PR-29 / PR-5: Registered Runtime Device Contract (re-exported from contracts package)
# RegisteredRuntimeDevice is the sole canonical external single-device read contract.
from contracts.registered_runtime_device import (  # noqa: E402
    RegisteredRuntimeDevice,
    RuntimeAutonomySummary,
    RuntimeCapabilityProfile,
    RuntimeConnectionState,
    RuntimeConnectionSummary,
    RuntimeDeviceExecutionModel,
    RuntimeDeviceFormFactor,
    RuntimeDevicePlatform,
    RuntimeDeviceStatus,
    RuntimeParticipantIdentity,
    RuntimeParticipantTier,
    RuntimeParticipationHints,
    RuntimeSessionPresence,
    build_registered_runtime_device,
    from_android_registration,
    from_device_agent_manager_record,
    from_device_registry_record,
    from_router_device,
    from_udm_device,
)

# PR-39: Runtime Recovery and Reconciliation Contract
from contracts.runtime_recovery_reconciliation import (
    RecoveryActionRecommendation,
    RecoveryActionType,
    RecoveryBarrierState,
    RecoveryIncidentType,
    RecoveryParticipantState,
    RecoveryStatus,
    RecoverySummary,
    RuntimeReconciliationState,
    RuntimeRecoveryIncident,
    build_recovery_summary,
    build_runtime_reconciliation_state,
    build_runtime_recovery_incident,
)
from contracts.runtime_recovery_reconciliation import from_merged_runtime_result as recovery_from_merged_result
from contracts.runtime_recovery_reconciliation import from_mesh_session_coordinator as recovery_from_coordinator
from contracts.runtime_recovery_reconciliation import from_multi_device_projection as recovery_from_projection
from contracts.runtime_recovery_reconciliation import (  # noqa: E402
    from_source_dispatch_result as recovery_from_dispatch_result,
)
from contracts.runtime_recovery_reconciliation import from_target_takeover_result as recovery_from_takeover_result

# PR-40: Durable Runtime Session Snapshot Contract
from contracts.runtime_session_snapshot import (
    RuntimeSessionSnapshot,
    RuntimeSessionSnapshotCoordinatorState,
    RuntimeSessionSnapshotDispatchState,
    RuntimeSessionSnapshotIdentity,
    RuntimeSessionSnapshotRecoveryState,
    RuntimeSessionSnapshotResultState,
    RuntimeSessionSnapshotStatus,
    RuntimeSessionSnapshotSummary,
    RuntimeSessionSnapshotTakeoverState,
    build_runtime_session_snapshot,
    build_runtime_session_snapshot_summary,
)
from contracts.runtime_session_snapshot import from_mesh_session as session_snapshot_from_mesh_session  # noqa: E402
from contracts.runtime_session_snapshot import from_multi_device_runtime_projection as session_snapshot_from_projection
from contracts.runtime_session_snapshot import from_recovery_state as session_snapshot_from_recovery
from contracts.runtime_session_snapshot import from_result_merge as session_snapshot_from_merge
from contracts.runtime_session_snapshot import from_source_dispatch_result as session_snapshot_from_dispatch
from contracts.runtime_session_snapshot import from_target_takeover_result as session_snapshot_from_takeover

# PR-35: Source Dispatch Contracts (re-exported from contracts package)
from contracts.source_dispatch import (
    SourceDispatchDecision,
    SourceDispatchMode,
    SourceDispatchPlan,
    SourceDispatchResult,
    SourceDispatchSummary,
    SourceDispatchTarget,
    build_source_dispatch_decision,
)
from contracts.source_dispatch import build_source_dispatch_plan as source_dispatch_build_plan  # noqa: E402
from contracts.source_dispatch import (
    build_source_dispatch_result,
    build_source_dispatch_summary,
    failure_dispatch_result,
)

# PR-2: capability contract + resolver
from .capability_contract import (
    CapabilityContract,
    CapabilityContractError,
    CapabilitySource,
    is_valid_capability_contract,
    validate_capability_contract,
)
from .capability_resolver import (
    CapabilityResolver,
    get_capability_resolver,
    reset_capability_resolver,
)

# PR-2: command envelope
from .command_envelope import (
    ENVELOPE_VERSION,
    CancelReason,
    CommandEnvelope,
    CommandVerb,
    EnvelopeValidationError,
    ResultEnvelope,
    log_command_envelope,
    log_result_envelope,
    validate_command_envelope,
    validate_result_envelope,
)
from .config_manager import UnifiedConfigManager, get_unified_config_manager
from .connection_manager import UnifiedConnectionManager, get_unified_connection_manager

# PR-4: device health scorer
from .device_health import (
    DeviceHealthScorer,
    HealthScore,
    get_device_health_scorer,
    reset_device_health_scorer,
)
from .device_manager import UnifiedDeviceManager, get_unified_device_manager

# PR-1: entrypoint router
from .entrypoint_router import (
    EntrypointRouter,
    get_entrypoint_router,
    reset_entrypoint_router,
)

# Block-5: error taxonomy
from .error_codes import (
    ErrorDomain,
    ErrorPayload,
    ErrorSeverity,
    GalaxyErrorCode,
    Retryable,
)
from .error_codes import get_descriptor as get_error_descriptor
from .error_codes import (
    is_retryable,
)

# Block-5: error mapper
from .error_mapper import ErrorMapper
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

# Block-5: idempotency
from .idempotency import (
    DuplicateCommandError,
    IdempotencyConflictError,
    IdempotencyEntry,
    IdempotencyStatus,
    IdempotencyStore,
    check_idempotency,
    get_idempotency_store,
    make_payload_hash,
    record_idempotency,
    reset_idempotency_store,
)
from .llm_router import UnifiedLLMRouter, get_unified_llm_router
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

# Block-5: release gate
from .release_gate import (
    FeatureDisabledError,
    ReleaseGate,
    RolloutBlockedError,
    get_release_gate,
    reset_release_gate,
)

# PR-1: unified state schema
from .state_schema import (
    CognitiveState,
    DeviceState,
    EntryPath,
    ExecutionState,
    ExecutionStatus,
    PresencePhase,
    PresenceState,
    TaskState,
    TaskStatus,
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
    "RuntimeParticipantIdentity",
    "RuntimeParticipantTier",
    "RuntimeDevicePlatform",
    "RuntimeDeviceFormFactor",
    "RuntimeDeviceStatus",
    "RuntimeConnectionState",
    "RuntimeDeviceExecutionModel",
    "build_registered_runtime_device",
    "from_udm_device",
    "from_router_device",
    "from_android_registration",
    "from_device_registry_record",
    "from_device_agent_manager_record",
    # PR-30: Local Runtime Host Contract
    "LocalRuntimeHost",
    "LocalRuntimeHostStatus",
    "LocalRuntimeHostCapabilities",
    "LocalRuntimeSessionSupport",
    "LocalRuntimeHandoffSupport",
    "LocalRuntimeExecutionSupport",
    "LocalRuntimeExecutionMode",
    "from_registered_runtime_device",
    "from_runtime_bridge_config",
    "build_local_runtime_host",
    "summarize_local_runtime_host",
    # PR-31: Handoff Envelope v2 Contract
    "HandoffEnvelopeV2",
    "HandoffSourceSummary",
    "HandoffTargetSummary",
    "HandoffAgentSpec",
    "HandoffTaskSpec",
    "HandoffSessionContext",
    "LocalTakeoverPolicy",
    "HandoffReturnContract",
    "from_legacy_handoff_contract",
    "from_bridge_inputs",
    "to_legacy_bridge_payload",
    "build_handoff_envelope_v2",
    # PR-32: Mesh Membership Contract
    "MeshMembership",
    "MeshMemberRole",
    "MeshAuthorityScope",
    "MeshRoutingIntent",
    "MeshParticipationHints",
    "from_body_mesh_entry",
    "from_device_formation_summary",
    "from_cross_device_routing_summary",
    "build_mesh_membership",
    # PR-33: Mesh Session Contract
    "MeshSession",
    "MeshSessionParticipant",
    "MeshSubtaskAssignment",
    "MeshMergePolicy",
    "MeshBarrierPosture",
    "MeshSessionStatus",
    "mesh_session_from_formation",
    "mesh_session_from_routing",
    "from_constellation_decomposition",
    "build_mesh_session",
    # PR-34: Local Takeover Result Contract
    "LocalTakeoverResult",
    "LocalTakeoverStatus",
    "LocalTakeoverSessionContext",
    "build_local_takeover_result",
    "takeover_result_from_execution_output",
    "takeover_failure_result",
    # PR-35: Source Dispatch Contracts
    "SourceDispatchMode",
    "SourceDispatchDecision",
    "SourceDispatchTarget",
    "SourceDispatchPlan",
    "SourceDispatchResult",
    "SourceDispatchSummary",
    "build_source_dispatch_decision",
    "source_dispatch_build_plan",
    "build_source_dispatch_result",
    "build_source_dispatch_summary",
    "failure_dispatch_result",
    # PR-36: Cross-Runtime Result Merge Contract
    "RuntimeResultRole",
    "RuntimeResultStatus",
    "ResultMergePolicy",
    "RuntimeResultProvenance",
    "RuntimeResultUnit",
    "ResultMergeInput",
    "MergedRuntimeResult",
    "ResultMergeSummary",
    "merge_unit_from_takeover_result",
    "merge_unit_from_dispatch_result",
    "merge_unit_from_execution_output",
    "build_merged_runtime_result",
    "merge_runtime_results",
    "build_result_merge_summary",
    # PR-37: Mesh Session Coordinator Contract
    "MeshCoordinatorStatus",
    "MeshParticipantStatus",
    "MeshAssignmentStatus",
    "MeshBarrierStatus",
    "MeshCoordinationEventKind",
    "MeshParticipantCoordinationState",
    "MeshAssignmentState",
    "MeshBarrierState",
    "MeshCoordinationEvent",
    "MeshSessionCoordinatorState",
    "MeshSessionCoordinatorSummary",
    "build_mesh_session_coordinator",
    "coordinator_from_mesh_session",
    "update_coordinator_with_dispatch_result",
    "update_coordinator_with_takeover_result",
    "update_coordinator_with_merged_result",
    "build_coordinator_summary",
    # PR-38: Unified Multi-Device Runtime Projection
    "MultiDeviceRuntimeProjection",
    "RuntimeProjectionDeviceEntry",
    "RuntimeProjectionHostEntry",
    "RuntimeProjectionMeshSessionEntry",
    "RuntimeProjectionDispatchEntry",
    "RuntimeProjectionHandoffEntry",
    "RuntimeProjectionTakeoverEntry",
    "RuntimeProjectionCoordinatorEntry",
    "RuntimeProjectionResultEntry",
    "build_multi_device_runtime_projection",
    "project_runtime_devices",
    "project_runtime_hosts",
    "project_mesh_sessions",
    "project_source_dispatches",
    "project_handoffs",
    "project_takeovers",
    "project_coordinator_state",
    "project_merged_results",
    # PR-39: Runtime Recovery and Reconciliation Contract
    "RecoveryIncidentType",
    "RecoveryStatus",
    "RecoveryActionType",
    "RecoveryParticipantState",
    "RecoveryActionRecommendation",
    "RecoveryBarrierState",
    "RuntimeRecoveryIncident",
    "RuntimeReconciliationState",
    "RecoverySummary",
    "build_runtime_recovery_incident",
    "build_runtime_reconciliation_state",
    "build_recovery_summary",
    "recovery_from_dispatch_result",
    "recovery_from_takeover_result",
    "recovery_from_coordinator",
    "recovery_from_merged_result",
    "recovery_from_projection",
    # PR-40: Durable Runtime Session Snapshot Contract
    "RuntimeSessionSnapshotStatus",
    "RuntimeSessionSnapshotIdentity",
    "RuntimeSessionSnapshotDispatchState",
    "RuntimeSessionSnapshotTakeoverState",
    "RuntimeSessionSnapshotCoordinatorState",
    "RuntimeSessionSnapshotResultState",
    "RuntimeSessionSnapshotRecoveryState",
    "RuntimeSessionSnapshot",
    "RuntimeSessionSnapshotSummary",
    "build_runtime_session_snapshot",
    "build_runtime_session_snapshot_summary",
    "session_snapshot_from_mesh_session",
    "session_snapshot_from_dispatch",
    "session_snapshot_from_takeover",
    "session_snapshot_from_merge",
    "session_snapshot_from_recovery",
    "session_snapshot_from_projection",
]
