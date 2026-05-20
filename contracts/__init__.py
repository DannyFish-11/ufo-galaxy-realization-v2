"""contracts — Shared contract types for Galaxy execution lifecycle.

Exports the canonical execution trace contract introduced in PR-25, the
Registered Runtime Device contract introduced in PR-29, the Local Runtime
Host contract introduced in PR-30, the Handoff Envelope v2 contract
introduced in PR-31, the Mesh Membership contract introduced in PR-32, the
Mesh Session contract introduced in PR-33, the Local Takeover Result
contract introduced in PR-34, the Source Dispatch contracts introduced
in PR-35, the Cross-Runtime Result Merge contracts introduced in PR-36,
the Mesh Session Coordinator contracts introduced in PR-37, the
Unified Multi-Device Runtime Projection introduced in PR-38, the
Runtime Recovery and Reconciliation Contract introduced in PR-39, the
Durable Runtime Session Snapshot Contract introduced in PR-40, the
Desktop Status Projection introduced in PR-22, the Canonical Device
Identity contract introduced in PR-56, the Runtime Presence Record
contract introduced in PR-56, and the Execution Target Policy contracts
introduced in PR-I.
"""

from contracts.execution_trace import (
    ExecutionTraceEnvelope,
    ExecutionTraceEvent,
    ExecutionTraceStage,
    ExecutionTraceStatus,
    build_trace_envelope,
    from_execution_intent,
    from_execution_result,
    from_fallback_trace,
    from_readiness_result,
)

# PR-29 / PR-5: Unified Registered Runtime Device Contract
# RegisteredRuntimeDevice is the sole canonical external single-device
# read contract.  All major device sources provide a stable adapter into it.
from contracts.registered_runtime_device import (
    RegisteredRuntimeDevice,
    RuntimeConnectionSummary,
    RuntimeCapabilityProfile,
    RuntimeAutonomySummary,
    RuntimeSessionPresence,
    RuntimeParticipationHints,
    RuntimeParticipantIdentity,
    RuntimeParticipantTier,
    RuntimeDevicePlatform,
    RuntimeDeviceFormFactor,
    RuntimeDeviceStatus,
    RuntimeConnectionState,
    RuntimeDeviceExecutionModel,
    build_registered_runtime_device,
    from_udm_device,
    from_router_device,
    from_android_registration,
    from_device_registry_record,
    from_device_agent_manager_record,
)

# PR-30: Local Runtime Host Contract
from contracts.local_runtime_host import (
    LocalRuntimeHost,
    LocalRuntimeHostStatus,
    LocalRuntimeHostCapabilities,
    LocalRuntimeSessionSupport,
    LocalRuntimeHandoffSupport,
    LocalRuntimeExecutionSupport,
    LocalRuntimeExecutionMode,
    from_registered_runtime_device,
    from_runtime_bridge_config,
    build_local_runtime_host,
    summarize_local_runtime_host,
)

# PR-31: Handoff Envelope v2 Contract
from contracts.handoff_envelope_v2 import (
    HandoffEnvelopeV2,
    HandoffSourceSummary,
    HandoffTargetSummary,
    HandoffAgentSpec,
    HandoffTaskSpec,
    HandoffSessionContext,
    LocalTakeoverPolicy,
    HandoffReturnContract,
    from_legacy_handoff_contract,
    from_bridge_inputs,
    to_legacy_bridge_payload,
    build_handoff_envelope_v2,
)

# PR-32: Mesh Membership Contract
from contracts.mesh_membership import (
    MeshMembership,
    MeshMemberRole,
    MeshAuthorityScope,
    MeshRoutingIntent,
    MeshParticipationHints,
    from_body_mesh_entry,
    from_device_formation_summary,
    from_cross_device_routing_summary,
    build_mesh_membership,
)

# PR-33: Mesh Session Contract
from contracts.mesh_session import (
    MeshSession,
    MeshSessionParticipant,
    MeshSubtaskAssignment,
    MeshMergePolicy,
    MeshBarrierPosture,
    MeshSessionStatus,
    from_device_formation_summary as mesh_session_from_formation,
    from_cross_device_routing_summary as mesh_session_from_routing,
    from_constellation_decomposition,
    build_mesh_session,
)

# PR-34: Local Takeover Result Contract
from contracts.local_takeover_result import (
    LocalTakeoverResult,
    LocalTakeoverStatus,
    LocalTakeoverSessionContext,
    build_local_takeover_result,
    from_execution_output as takeover_result_from_execution_output,
    failure_result as takeover_failure_result,
)

# PR-35: Source Dispatch Contracts
from contracts.source_dispatch import (
    SourceDispatchMode,
    SourceDispatchDecision,
    SourceDispatchTarget,
    SourceDispatchPlan,
    SourceDispatchResult,
    SourceDispatchSummary,
    build_source_dispatch_decision,
    build_source_dispatch_plan as _build_source_dispatch_plan,
    build_source_dispatch_result,
    build_source_dispatch_summary,
    failure_dispatch_result,
)

# Re-export with canonical name (the orchestrator module provides the full builder)
build_source_dispatch_plan = _build_source_dispatch_plan

# PR-36: Cross-Runtime Result Merge Contract
from contracts.cross_runtime_result_merge import (
    RuntimeResultRole,
    RuntimeResultStatus,
    ResultMergePolicy,
    RuntimeResultProvenance,
    RuntimeResultUnit,
    ResultMergeInput,
    MergedRuntimeResult,
    ResultMergeSummary,
    from_local_takeover_result as merge_unit_from_takeover_result,
    from_source_dispatch_result as merge_unit_from_dispatch_result,
    from_execution_output as merge_unit_from_execution_output,
    build_merged_runtime_result,
    merge_runtime_results,
    build_result_merge_summary,
)

# PR-37: Mesh Session Coordinator Contract
from contracts.mesh_session_coordinator import (
    MeshCoordinatorStatus,
    MeshParticipantStatus,
    MeshAssignmentStatus,
    MeshBarrierStatus,
    MeshCoordinationEventKind,
    MeshParticipantCoordinationState,
    MeshAssignmentState,
    MeshBarrierState,
    MeshCoordinationEvent,
    MeshSessionCoordinatorState,
    MeshSessionCoordinatorSummary,
    build_mesh_session_coordinator,
    from_mesh_session as coordinator_from_mesh_session,
    update_coordinator_with_dispatch_result,
    update_coordinator_with_takeover_result,
    update_coordinator_with_merged_result,
    build_coordinator_summary,
)

# PR-38: Unified Multi-Device Runtime Projection
from contracts.multi_device_runtime_projection import (
    CANONICAL_TOP_LEVEL_PROJECTION,
    MultiDeviceRuntimeProjection,
    RuntimeProjectionDeviceEntry,
    RuntimeProjectionHostEntry,
    RuntimeProjectionMeshSessionEntry,
    RuntimeProjectionDispatchEntry,
    RuntimeProjectionHandoffEntry,
    RuntimeProjectionTakeoverEntry,
    RuntimeProjectionCoordinatorEntry,
    RuntimeProjectionResultEntry,
    build_multi_device_runtime_projection,
    project_runtime_devices,
    project_runtime_hosts,
    project_mesh_sessions,
    project_source_dispatches,
    project_handoffs,
    project_takeovers,
    project_coordinator_state,
    project_merged_results,
    from_registered_runtime_device as projection_from_registered_runtime_device,
)

# PR-39: Runtime Recovery and Reconciliation Contract
from contracts.runtime_recovery_reconciliation import (
    RecoveryIncidentType,
    RecoveryStatus,
    RecoveryActionType,
    RecoveryParticipantState,
    RecoveryActionRecommendation,
    RecoveryBarrierState,
    RuntimeRecoveryIncident,
    RuntimeReconciliationState,
    RecoverySummary,
    build_runtime_recovery_incident,
    build_runtime_reconciliation_state,
    build_recovery_summary,
    from_source_dispatch_result as recovery_from_dispatch_result,
    from_target_takeover_result as recovery_from_takeover_result,
    from_mesh_session_coordinator as recovery_from_coordinator,
    from_merged_runtime_result as recovery_from_merged_result,
    from_multi_device_projection as recovery_from_projection,
)

# PR-40: Durable Runtime Session Snapshot Contract
from contracts.runtime_session_snapshot import (
    RuntimeSessionSnapshotStatus,
    RuntimeSessionSnapshotIdentity,
    RuntimeSessionSnapshotDispatchState,
    RuntimeSessionSnapshotTakeoverState,
    RuntimeSessionSnapshotCoordinatorState,
    RuntimeSessionSnapshotResultState,
    RuntimeSessionSnapshotRecoveryState,
    RuntimeSessionSnapshot,
    RuntimeSessionSnapshotSummary,
    build_runtime_session_snapshot,
    build_runtime_session_snapshot_summary,
    from_mesh_session as session_snapshot_from_mesh_session,
    from_source_dispatch_result as session_snapshot_from_dispatch,
    from_target_takeover_result as session_snapshot_from_takeover,
    from_result_merge as session_snapshot_from_merge,
    from_recovery_state as session_snapshot_from_recovery,
    from_multi_device_runtime_projection as session_snapshot_from_projection,
)

# PR-22: Desktop Status Projection Contract
from contracts.desktop_status_projection import (
    ProjectionHealthSeverity,
    LifecycleStage,
    ExecutionPathKind,
    PerceptionProjection,
    ModelRoutingProjection,
    ExecutionProjection,
    LifecycleProjection,
    ExplainabilityProjection,
    DesktopStatusProjection,
    build_desktop_status_projection,
    desktop_status_projection_summary,
)

# PR-56: Canonical Device Identity Contract
from contracts.canonical_device_identity import (
    CanonicalDeviceIdentity,
    build_canonical_device_identity,
    from_registered_runtime_device as canonical_identity_from_rrd,
    from_android_registration as canonical_identity_from_android,
)

# PR-56: Runtime Presence Record Contract
from contracts.runtime_presence_record import (
    RuntimePresenceRecord,
    RuntimeTransport,
    build_runtime_presence_record,
    from_registered_runtime_device as presence_record_from_rrd,
)

# PR-533 / PR-1 dual-repo unification: Source Runtime Posture Contract
from contracts.source_posture_contract import (
    SourcePostureValue,
    SourcePostureContractField,
    validate_source_posture_value,
    resolve_source_posture_value,
    build_source_posture_field,
    posture_value_to_str,
    normalize_posture_for_ingress,
    SOURCE_POSTURE_CONTRACT_AUTHORITY,
    SOURCE_POSTURE_CONTRACT_LAYER_POSITION,
    SOURCE_POSTURE_NO_ENTRYMODE_OVERLOAD_POLICY,
    SOURCE_POSTURE_NO_CROSS_DEVICE_ENABLED_OVERLOAD_POLICY,
    SOURCE_POSTURE_CONTRACT_PR1_UNIFICATION_SENTINEL,
    SOURCE_POSTURE_CONTRACT_PR_PACKAGE_1_CANONICALIZATION_SENTINEL,
    SOURCE_POSTURE_VALID_VALUES,
    CANONICAL_POSTURE_ADJACENT_FIELDS,
)

# PR-03 (post-533 dual-repo unification): Unified Dispatch Contract Metadata
from contracts.dispatch_contract_metadata import (
    DispatchContractMetadata,
    build_dispatch_contract_metadata,
    extract_dispatch_contract_metadata,
    UNIFIED_DISPATCH_CONTRACT_PR03_SENTINEL,
    DISPATCH_CONTRACT_METADATA_IS_STABLE_ANDROID_SURFACE_PR03_POLICY,
)

__all__ = [
    # PR-25: Execution Trace Contract
    "ExecutionTraceEnvelope",
    "ExecutionTraceEvent",
    "ExecutionTraceStage",
    "ExecutionTraceStatus",
    "build_trace_envelope",
    "from_execution_intent",
    "from_execution_result",
    "from_fallback_trace",
    "from_readiness_result",
    # PR-29 / PR-5: Registered Runtime Device Contract
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
    "build_source_dispatch_plan",
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
    # PR-8 consolidation: CANONICAL_TOP_LEVEL_PROJECTION marker and from_registered_runtime_device
    "CANONICAL_TOP_LEVEL_PROJECTION",
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
    "projection_from_registered_runtime_device",
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
    # PR-22: Desktop Status Projection
    "ProjectionHealthSeverity",
    "LifecycleStage",
    "ExecutionPathKind",
    "PerceptionProjection",
    "ModelRoutingProjection",
    "ExecutionProjection",
    "LifecycleProjection",
    "ExplainabilityProjection",
    "DesktopStatusProjection",
    "build_desktop_status_projection",
    "desktop_status_projection_summary",
    # PR-56: Canonical Device Identity Contract
    "CanonicalDeviceIdentity",
    "build_canonical_device_identity",
    "canonical_identity_from_rrd",
    "canonical_identity_from_android",
    # PR-56: Runtime Presence Record Contract
    "RuntimePresenceRecord",
    "RuntimeTransport",
    "build_runtime_presence_record",
    "presence_record_from_rrd",
    # PR-533 / PR-1 dual-repo unification: Source Runtime Posture Contract
    "SourcePostureValue",
    "SourcePostureContractField",
    "validate_source_posture_value",
    "resolve_source_posture_value",
    "build_source_posture_field",
    "posture_value_to_str",
    "SOURCE_POSTURE_CONTRACT_AUTHORITY",
    "SOURCE_POSTURE_CONTRACT_LAYER_POSITION",
    "SOURCE_POSTURE_NO_ENTRYMODE_OVERLOAD_POLICY",
    "SOURCE_POSTURE_NO_CROSS_DEVICE_ENABLED_OVERLOAD_POLICY",
    "SOURCE_POSTURE_CONTRACT_PR1_UNIFICATION_SENTINEL",
    "SOURCE_POSTURE_VALID_VALUES",
    # PR-03: Unified Dispatch Contract Metadata
    "DispatchContractMetadata",
    "build_dispatch_contract_metadata",
    "extract_dispatch_contract_metadata",
    "UNIFIED_DISPATCH_CONTRACT_PR03_SENTINEL",
    "DISPATCH_CONTRACT_METADATA_IS_STABLE_ANDROID_SURFACE_PR03_POLICY",
]

# PR-I: Execution Target Policy Contracts
from contracts.execution_target_policy import (
    EXECUTION_TARGET_POLICY_IS_AUTHORITY,
    TARGET_SELECTION_IS_POLICY_DRIVEN_POLICY,
    FAILURE_HANDLING_IS_EXPLICIT_POLICY,
    POLICY_SEPARATION_FROM_ROUTING_MECHANICS_POLICY,
    BACKWARD_COMPAT_DURING_POLICY_MIGRATION_POLICY,
    EXECUTION_TARGET_POLICY_PR_I_SENTINEL,
    TargetSelectionPolicyKind,
    FailureHandlingPolicyKind,
    DegradedReadinessPolicyKind,
    TargetSelectionDecision,
    FailureHandlingDecision,
    build_target_selection_decision,
    build_failure_handling_decision,
)

__all__ += [
    # PR-I: Execution Target Policy Contracts
    "EXECUTION_TARGET_POLICY_IS_AUTHORITY",
    "TARGET_SELECTION_IS_POLICY_DRIVEN_POLICY",
    "FAILURE_HANDLING_IS_EXPLICIT_POLICY",
    "POLICY_SEPARATION_FROM_ROUTING_MECHANICS_POLICY",
    "BACKWARD_COMPAT_DURING_POLICY_MIGRATION_POLICY",
    "EXECUTION_TARGET_POLICY_PR_I_SENTINEL",
    "TargetSelectionPolicyKind",
    "FailureHandlingPolicyKind",
    "DegradedReadinessPolicyKind",
    "TargetSelectionDecision",
    "FailureHandlingDecision",
    "build_target_selection_decision",
    "build_failure_handling_decision",
]

# PR-Task3: Distributed Subject Contract v1 and Participant Lifecycle Schema
from contracts.distributed_subject_contract_v1 import (
    DISTRIBUTED_SUBJECT_CONTRACT_V1_SENTINEL,
    PARTICIPANT_LIFECYCLE_IS_GOVERNED_BY_CENTER,
    SUBJECT_EVIDENCE_IS_NOT_CANONICAL_TRUTH,
    CONTRACT_FIELD_LABEL_IS_EXPLICIT_POLICY,
    ContractFieldLabel,
    SubjectContractDimension,
    SubjectContractField,
    DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS,
    DistributedSubjectContractVersion,
    get_fields_by_dimension,
    get_fields_by_label,
    get_field,
    build_contract_version,
    build_contract_manifest,
)

from contracts.participant_lifecycle_schema import (
    PARTICIPANT_LIFECYCLE_SCHEMA_SENTINEL,
    PARTICIPANT_ROLE_IS_ASSIGNED_BY_CENTER,
    PARTICIPANT_STATE_TRANSITIONS_ARE_AUTHORITATIVE,
    ParticipantRole,
    ParticipantLifecycleState,
    ParticipantTransitionTrigger,
    ParticipantStateTransition,
    PARTICIPANT_STATE_TRANSITIONS,
    ParticipantRecord,
    build_participant_record,
    get_allowed_transitions,
    build_lifecycle_schema_manifest,
)

__all__ += [
    # PR-Task3: Distributed Subject Contract v1
    "DISTRIBUTED_SUBJECT_CONTRACT_V1_SENTINEL",
    "PARTICIPANT_LIFECYCLE_IS_GOVERNED_BY_CENTER",
    "SUBJECT_EVIDENCE_IS_NOT_CANONICAL_TRUTH",
    "CONTRACT_FIELD_LABEL_IS_EXPLICIT_POLICY",
    "ContractFieldLabel",
    "SubjectContractDimension",
    "SubjectContractField",
    "DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS",
    "DistributedSubjectContractVersion",
    "get_fields_by_dimension",
    "get_fields_by_label",
    "get_field",
    "build_contract_version",
    "build_contract_manifest",
    # PR-Task3: Participant Lifecycle Schema
    "PARTICIPANT_LIFECYCLE_SCHEMA_SENTINEL",
    "PARTICIPANT_ROLE_IS_ASSIGNED_BY_CENTER",
    "PARTICIPANT_STATE_TRANSITIONS_ARE_AUTHORITATIVE",
    "ParticipantRole",
    "ParticipantLifecycleState",
    "ParticipantTransitionTrigger",
    "ParticipantStateTransition",
    "PARTICIPANT_STATE_TRANSITIONS",
    "ParticipantRecord",
    "build_participant_record",
    "get_allowed_transitions",
    "build_lifecycle_schema_manifest",
]
