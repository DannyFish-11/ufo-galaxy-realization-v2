"""contracts — Shared contract types for Galaxy execution lifecycle.

Exports the canonical execution trace contract introduced in PR-25, the
Registered Runtime Device contract introduced in PR-29, the Local Runtime
Host contract introduced in PR-30, the Handoff Envelope v2 contract
introduced in PR-31, the Mesh Membership contract introduced in PR-32, the
Mesh Session contract introduced in PR-33, the Local Takeover Result
contract introduced in PR-34, the Source Dispatch contracts introduced
in PR-35, the Cross-Runtime Result Merge contracts introduced in PR-36,
and the Mesh Session Coordinator contracts introduced in PR-37.
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

# PR-29: Unified Registered Runtime Device Contract
from contracts.registered_runtime_device import (
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
]