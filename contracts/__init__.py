"""contracts — Shared contract types for Galaxy execution lifecycle.

Exports the canonical execution trace contract introduced in PR-25, the
Registered Runtime Device contract introduced in PR-29, the Local Runtime
Host contract introduced in PR-30, the Handoff Envelope v2 contract
introduced in PR-31, and the Mesh Membership contract introduced in PR-32.
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
]
