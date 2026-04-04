"""core/runtime/__init__.py
============================
Galaxy runtime sub-package.

Exports the target-side local takeover path introduced in PR-34, the
source-side dispatch orchestrator introduced in PR-35, the cross-runtime
result merge helpers introduced in PR-36, and the mesh session coordinator
helpers introduced in PR-37.

PR-2 (post-533 dual-repo runtime host unification): exports posture-aware
source execution eligibility helpers from
``core.source_execution_eligibility``.
"""

from core.runtime.target_takeover import (
    TargetTakeoverHandler,
    adopt_handoff_session,
    build_local_takeover_context,
    resolve_or_create_runtime_session,
    normalize_handoff_envelope,
    execute_local_takeover,
)

# PR-35: Source Runtime Dispatch Orchestrator
from core.runtime.source_dispatch_orchestrator import (
    SourceDispatchOrchestrator,
    select_dispatch_mode,
    select_dispatch_target,
    build_source_dispatch_plan,
    orchestrate_source_runtime_dispatch,
)

# PR-36: Cross-Runtime Result Merge Contract helpers
from contracts.cross_runtime_result_merge import (
    RuntimeResultRole,
    RuntimeResultStatus,
    ResultMergePolicy,
    RuntimeResultUnit,
    MergedRuntimeResult,
    ResultMergeSummary,
    from_local_takeover_result as merge_unit_from_takeover_result,
    from_source_dispatch_result as merge_unit_from_dispatch_result,
    from_execution_output as merge_unit_from_execution_output,
    build_merged_runtime_result,
    merge_runtime_results,
    build_result_merge_summary,
)


# PR-37: Mesh Session Coordinator (mesh package)
# Imported here for convenience so consumers can reach the coordinator
# from either core.runtime or core.mesh.
from core.mesh.mesh_session_coordinator import (  # noqa: E402
    MeshSessionCoordinator,
    coordinate_mesh_session,
    get_coordinator_summary,
)

# PR-2 (post-533 dual-repo runtime host unification): posture-aware source
# execution eligibility.  Re-exported here so callers can reach the
# eligibility API from core.runtime without importing the module directly.
from core.source_execution_eligibility import (  # noqa: E402
    SOURCE_DISPATCH_POSTURE_AWARE_AUTHORITY,
    CONTROL_ONLY_SOURCE_INELIGIBLE_FOR_LOCAL_EXECUTION_POLICY,
    JOIN_RUNTIME_SOURCE_ELIGIBLE_FOR_LOCAL_EXECUTION_POLICY,
    POSTURE_GATED_LOCAL_EXECUTION_POLICY,
    POSTURE_AWARE_DISPATCH_INTEGRATED_SENTINEL,
    SourceExecutionEligibility,
    check_source_execution_eligibility,
    is_source_eligible_for_local_execution,
    resolve_posture_for_eligibility,
)

# PR-4 (post-533 dual-repo runtime host unification): canonical session truth
# and posture-aware result merge.  Re-exported here so callers can reach the
# session truth API from core.runtime without importing the module directly.
from core.canonical_session_truth import (  # noqa: E402
    CANONICAL_SESSION_TRUTH_AUTHORITY,
    CONTROL_ONLY_EXCLUDED_FROM_MERGE_POLICY,
    POSTURE_AWARE_RESULT_FILTER_POLICY,
    JOIN_RUNTIME_INCLUDED_IN_MERGE_POLICY,
    CANONICAL_SESSION_TRUTH_PR4_SENTINEL,
    SessionTruthSource,
    CanonicalSessionTruthRecord,
    CanonicalSessionTruthRuntime,
    CanonicalSessionTruthSnapshot,
    filter_result_units_by_posture,
    merge_session_truth,
    record_session_truth,
    build_canonical_session_truth_snapshot,
    get_canonical_session_truth_runtime,
    reset_canonical_session_truth_runtime,
)

# PR-6 (post-533 dual-repo runtime host unification): multi-device coordination
# authority and canonical role modelling.  Re-exported here so callers can
# reach the coordination role API from core.runtime without importing the
# module directly.
from core.multi_device_coordination_authority import (  # noqa: E402
    MULTI_DEVICE_COORDINATION_AUTHORITY,
    MULTI_DEVICE_COORDINATION_AUTHORITY_PR6_SENTINEL,
    SOURCE_CONTROLLER_OWNS_RUNTIME_AUTHORITY_POLICY,
    TARGET_ONLY_EXECUTOR_HAS_NO_CONTROL_AUTHORITY_POLICY,
    OBSERVER_ONLY_HAS_NO_EXECUTION_AUTHORITY_POLICY,
    COORDINATION_ROLE_DERIVATION_IS_POSTURE_DRIVEN_POLICY,
    CoordinationRole,
    CoordinationRoleRecord,
    CoordinationRoleSnapshot,
    CoordinationRoleRuntime,
    derive_coordination_role,
    build_coordination_role_record,
    build_coordination_role_snapshot,
    record_coordination_role,
    get_coordination_role_runtime,
    reset_coordination_role_runtime,
    get_source_controller_device_id,
)

__all__ = [
    # PR-34: Target Runtime Local Takeover Path
    "TargetTakeoverHandler",
    "adopt_handoff_session",
    "build_local_takeover_context",
    "resolve_or_create_runtime_session",
    "normalize_handoff_envelope",
    "execute_local_takeover",
    # PR-35: Source Runtime Dispatch Orchestrator
    "SourceDispatchOrchestrator",
    "select_dispatch_mode",
    "select_dispatch_target",
    "build_source_dispatch_plan",
    "orchestrate_source_runtime_dispatch",
    # PR-36: Cross-Runtime Result Merge Contract
    "RuntimeResultRole",
    "RuntimeResultStatus",
    "ResultMergePolicy",
    "RuntimeResultUnit",
    "MergedRuntimeResult",
    "ResultMergeSummary",
    "merge_unit_from_takeover_result",
    "merge_unit_from_dispatch_result",
    "merge_unit_from_execution_output",
    "build_merged_runtime_result",
    "merge_runtime_results",
    "build_result_merge_summary",
    # PR-37: Mesh Session Coordinator
    "MeshSessionCoordinator",
    "coordinate_mesh_session",
    "get_coordinator_summary",
    # PR-2: Posture-Aware Source Execution Eligibility
    "SOURCE_DISPATCH_POSTURE_AWARE_AUTHORITY",
    "CONTROL_ONLY_SOURCE_INELIGIBLE_FOR_LOCAL_EXECUTION_POLICY",
    "JOIN_RUNTIME_SOURCE_ELIGIBLE_FOR_LOCAL_EXECUTION_POLICY",
    "POSTURE_GATED_LOCAL_EXECUTION_POLICY",
    "POSTURE_AWARE_DISPATCH_INTEGRATED_SENTINEL",
    "SourceExecutionEligibility",
    "check_source_execution_eligibility",
    "is_source_eligible_for_local_execution",
    "resolve_posture_for_eligibility",
    # PR-4: Canonical Runtime Session Truth and Result Merge
    "CANONICAL_SESSION_TRUTH_AUTHORITY",
    "CONTROL_ONLY_EXCLUDED_FROM_MERGE_POLICY",
    "POSTURE_AWARE_RESULT_FILTER_POLICY",
    "JOIN_RUNTIME_INCLUDED_IN_MERGE_POLICY",
    "CANONICAL_SESSION_TRUTH_PR4_SENTINEL",
    "SessionTruthSource",
    "CanonicalSessionTruthRecord",
    "CanonicalSessionTruthRuntime",
    "CanonicalSessionTruthSnapshot",
    "filter_result_units_by_posture",
    "merge_session_truth",
    "record_session_truth",
    "build_canonical_session_truth_snapshot",
    "get_canonical_session_truth_runtime",
    "reset_canonical_session_truth_runtime",
    # PR-6: Multi-Device Coordination Authority and Role Modelling
    "MULTI_DEVICE_COORDINATION_AUTHORITY",
    "MULTI_DEVICE_COORDINATION_AUTHORITY_PR6_SENTINEL",
    "SOURCE_CONTROLLER_OWNS_RUNTIME_AUTHORITY_POLICY",
    "TARGET_ONLY_EXECUTOR_HAS_NO_CONTROL_AUTHORITY_POLICY",
    "OBSERVER_ONLY_HAS_NO_EXECUTION_AUTHORITY_POLICY",
    "COORDINATION_ROLE_DERIVATION_IS_POSTURE_DRIVEN_POLICY",
    "CoordinationRole",
    "CoordinationRoleRecord",
    "CoordinationRoleSnapshot",
    "CoordinationRoleRuntime",
    "derive_coordination_role",
    "build_coordination_role_record",
    "build_coordination_role_snapshot",
    "record_coordination_role",
    "get_coordination_role_runtime",
    "reset_coordination_role_runtime",
    "get_source_controller_device_id",
]
