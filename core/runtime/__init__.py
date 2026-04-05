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

PR package 1 (post-533 dual-repo runtime unification master plan, MAIN repo
side): exports posture contract canonicalization enforcement helpers from
``core.posture_contract_canonicalization``.

PR-5 (post-533 dual-repo runtime unification, MAIN repo side): exports
Android first-class runtime host classification and identity helpers from
``core.android_runtime_host``.

PR package 6 (post-533 dual-repo runtime unification master plan, MAIN repo
side): exports canonical device/host capability representation and
scheduling-basis normalization helpers from
``core.canonical_capability_scheduling_basis``.

PR package 7 (post-533 dual-repo runtime unification master plan, MAIN repo
side): exports canonical persistent attached-runtime session semantics from
``core.attached_runtime_session``.

PR package 9 (post-533 dual-repo runtime unification master plan, MAIN repo
side): exports canonical delegated-runtime handoff contract foundations from
``core.delegated_runtime_handoff_contract``.
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
    # PR-2 coordination-role alignment
    OBSERVER_ONLY_ROLE_BLOCKS_EXECUTION_POLICY,
    COORDINATION_ROLE_ALIGNED_DISPATCH_SENTINEL,
    SourceExecutionEligibility,
    check_source_execution_eligibility,
    is_source_eligible_for_local_execution,
    resolve_posture_for_eligibility,
    check_source_eligibility_with_coordination_role,
)

# PR-4 (post-533 dual-repo runtime host unification): canonical session truth
# and posture-aware result merge.  Re-exported here so callers can reach the
# session truth API from core.runtime without importing the module directly.
from core.canonical_session_truth import (  # noqa: E402
    CANONICAL_SESSION_TRUTH_AUTHORITY,
    CONTROL_ONLY_EXCLUDED_FROM_MERGE_POLICY,
    POSTURE_AWARE_RESULT_FILTER_POLICY,
    JOIN_RUNTIME_INCLUDED_IN_MERGE_POLICY,
    OBSERVER_ONLY_ROLE_EXCLUDED_FROM_MERGE_POLICY,
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

# PR package 1 (post-533 dual-repo runtime unification, MAIN repo side):
# posture contract canonicalization enforcement layer.
from core.posture_contract_canonicalization import (  # noqa: E402
    canonicalize_posture_in_payload,
    validate_posture_field_consistency,
    assert_posture_boundary_compliance,
    get_posture_from_payload,
    PostureBoundaryViolation,
    POSTURE_CONTRACT_CANONICALIZATION_AUTHORITY,
    POSTURE_BOUNDARY_NO_ENTRY_MODE_CONFLATION_POLICY,
    POSTURE_BOUNDARY_NO_CROSS_DEVICE_FLAG_CONFLATION_POLICY,
    POSTURE_BOUNDARY_NO_FORMATION_ROLE_CONFLATION_POLICY,
    POSTURE_CONTRACT_PR_PACKAGE_1_SENTINEL,
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

# PR-5 (post-533 dual-repo runtime unification, MAIN repo side): Android
# first-class runtime host classification and identity.  Re-exported here
# so callers can reach Android host typing from core.runtime without
# importing the module directly.
from core.android_runtime_host import (  # noqa: E402
    ANDROID_FIRST_CLASS_RUNTIME_HOST_PR5_SENTINEL,
    ANDROID_RUNTIME_HOST_DISTINCT_FROM_CONNECTED_DEVICE_PR5,
    ANDROID_RUNTIME_HOST_POSTURE_PRESERVED_PR5,
    AndroidRuntimeHostRole,
    AndroidRuntimeHostIdentity,
    classify_android_runtime_host,
    build_android_runtime_host_identity,
)

# PR package 6 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical device/host capability representation and scheduling-basis
# normalization.  Re-exported here so callers can reach the capability/
# scheduling API from core.runtime without importing the module directly.
from core.canonical_capability_scheduling_basis import (  # noqa: E402
    CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY,
    FULL_RUNTIME_TIER_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
    COMMAND_ONLY_TIER_BLOCKS_EXECUTION_PLACEMENT_POLICY,
    CAPABILITY_TIER_DRIVES_SURFACE_ELIGIBILITY_POLICY,
    OBSERVER_ONLY_ROLE_EXCLUDED_FROM_SCHEDULING_POLICY,
    ANDROID_HOST_CAPABILITY_LIFTED_FROM_PR5_POLICY,
    SCHEDULING_BASIS_NORMALISATION_IS_ADDITIVE_POLICY,
    CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL,
    CapabilityTier,
    ExecutionSurface,
    RuntimeCapabilityProfile,
    SchedulingBasisInputs,
    ExecutionSurfaceEligibility,
    build_runtime_capability_profile,
    build_scheduling_basis_inputs,
    evaluate_execution_surface_eligibility,
    normalize_scheduling_inputs,
)

# PR package 7 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical persistent attached-runtime session semantics.  Re-exported
# here so callers can reach the attached-runtime session API from core.runtime
# without importing the module directly.
from core.attached_runtime_session import (  # noqa: E402
    ATTACHED_RUNTIME_SESSION_AUTHORITY,
    ATTACHED_SESSION_PERSISTS_ACROSS_REQUESTS_POLICY,
    TRANSIENT_PRESENCE_DISTINCT_FROM_ATTACHED_SESSION_POLICY,
    DETACH_SIGNAL_REQUIRED_FOR_SESSION_TERMINATION_POLICY,
    ATTACH_IS_IDEMPOTENT_POLICY,
    DISCONNECTED_DOES_NOT_INVALIDATE_SESSION_POLICY,
    INVALIDATED_SESSION_IS_TERMINAL_POLICY,
    DISABLED_SESSION_NOT_ELIGIBLE_FOR_EXECUTION_POLICY,
    ATTACHED_SESSION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
    ATTACHMENT_LIFECYCLE_IS_POSTURE_AWARE_POLICY,
    ATTACHED_RUNTIME_SESSION_PR7_SENTINEL,
    AttachmentState,
    AttachmentLifecycleSignal,
    AttachedRuntimeSessionRecord,
    AttachedRuntimeSessionSnapshot,
    AttachedRuntimeSessionRuntime,
    attach_runtime_session,
    apply_lifecycle_signal,
    get_attached_runtime_session,
    list_active_attached_sessions,
    build_attached_runtime_session_snapshot,
    get_attached_runtime_session_runtime,
    reset_attached_runtime_session_runtime,
)

# PR package 8 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical delegated-runtime dispatch intent and handoff-preparation
# foundations.
from core.delegated_runtime_dispatch_intent import (  # noqa: E402
    DELEGATED_RUNTIME_DISPATCH_INTENT_AUTHORITY,
    DELEGATION_REQUIRES_ATTACHED_SESSION_POLICY,
    DELEGATION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
    OBSERVER_ONLY_ROLE_BLOCKS_DELEGATION_POLICY,
    TARGET_ONLY_EXECUTOR_CANNOT_DELEGATE_POLICY,
    COMMAND_ONLY_TIER_BLOCKS_FULL_DELEGATION_POLICY,
    HANDOFF_INPUTS_MUST_BE_SESSION_ANCHORED_POLICY,
    DELEGATION_INTENT_IS_ADDITIVE_TO_SESSION_POLICY,
    DISPATCH_RECORD_IS_IMMUTABLE_POLICY,
    PREPARATION_STATE_IS_MONOTONICALLY_ADVANCING_POLICY,
    DELEGATED_RUNTIME_DISPATCH_INTENT_PR8_SENTINEL,
    DelegationIntent,
    HandoffPreparationState,
    DelegatedRuntimeDispatchRecord,
    HandoffInputBundle,
    DispatchEligibilityOutcome,
    DelegatedRuntimeDispatchSnapshot,
    DelegatedRuntimeDispatchRuntime,
    build_delegated_dispatch_record,
    evaluate_dispatch_eligibility,
    prepare_handoff_inputs,
    record_delegated_dispatch_intent,
    get_delegated_dispatch_record,
    list_pending_delegated_dispatch_records,
    build_delegated_dispatch_snapshot,
    get_delegated_runtime_dispatch_runtime,
    reset_delegated_runtime_dispatch_runtime,
)

# PR package 9 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical delegated-runtime handoff contract foundations.  Re-exported
# here so callers can reach the handoff-contract API from core.runtime without
# importing the module directly.
from core.delegated_runtime_handoff_contract import (  # noqa: E402
    DELEGATED_RUNTIME_HANDOFF_CONTRACT_AUTHORITY,
    HANDOFF_CONTRACT_REQUIRES_DISPATCH_RECORD_POLICY,
    HANDOFF_CONTRACT_REQUIRES_ATTACHED_SESSION_POLICY,
    HANDOFF_CONTRACT_VERSION_MUST_BE_EXPLICIT_POLICY,
    HANDOFF_CONTRACT_IDENTITY_IS_IMMUTABLE_POLICY,
    HANDOFF_CONTRACT_STATUS_IS_MONOTONIC_POLICY,
    HANDOFF_CONTRACT_POSTURE_IS_PRESERVED_POLICY,
    SEALED_CONTRACT_IS_DISPATCH_READY_POLICY,
    HANDOFF_CONTRACT_PAYLOAD_MUST_BE_NON_EMPTY_POLICY,
    HANDOFF_CONTRACT_TRACE_ID_IS_PROPAGATED_POLICY,
    DELEGATED_RUNTIME_HANDOFF_CONTRACT_PR9_SENTINEL,
    HandoffContractVersion,
    HandoffContractStatus,
    DelegatedHandoffContractIdentity,
    DelegatedHandoffContractMeta,
    DelegatedHandoffContractPayload,
    DelegatedHandoffContractRecord,
    DelegatedHandoffContractSnapshot,
    DelegatedHandoffContractRuntime,
    build_delegated_handoff_contract,
    seal_handoff_contract,
    record_handoff_contract,
    get_handoff_contract,
    list_pending_handoff_contracts,
    build_handoff_contract_snapshot,
    get_handoff_contract_runtime,
    reset_handoff_contract_runtime,
)

# PR package 10 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical delegated-runtime execution-tracking and acknowledgment
# basis.  Re-exported here so callers can reach the execution-tracking API
# from core.runtime without importing the module directly.
from core.delegated_runtime_execution_tracker import (  # noqa: E402
    DELEGATED_RUNTIME_EXECUTION_TRACKER_AUTHORITY,
    EXECUTION_TRACKING_REQUIRES_CONTRACT_ID_POLICY,
    EXECUTION_TRACKING_REQUIRES_SESSION_ID_POLICY,
    EXECUTION_PHASE_IS_MONOTONIC_POLICY,
    ACK_SEQUENCE_IS_MONOTONICALLY_INCREASING_POLICY,
    RESULT_IS_IMMUTABLE_ONCE_RECORDED_POLICY,
    EXECUTION_TRACKING_POSTURE_IS_PROPAGATED_POLICY,
    TERMINAL_PHASE_BLOCKS_FURTHER_SIGNALS_POLICY,
    TRACKING_RECORD_IS_CONTRACT_ANCHORED_POLICY,
    PARTIAL_RESULT_DOES_NOT_CLOSE_TRACKING_POLICY,
    DELEGATED_RUNTIME_EXECUTION_TRACKER_PR10_SENTINEL,
    DelegatedExecutionPhase,
    AcknowledgmentSignal,
    DelegatedExecutionIdentity,
    DelegatedExecutionAcknowledgment,
    DelegatedExecutionResult,
    DelegatedExecutionTrackingRecord,
    DelegatedExecutionTrackingSnapshot,
    DelegatedExecutionTrackingRuntime,
    create_execution_tracking_record,
    apply_acknowledgment_signal,
    apply_result,
    record_execution_tracking,
    get_execution_tracking_record,
    list_active_execution_tracking_records,
    build_execution_tracking_snapshot,
    get_execution_tracking_runtime,
    reset_execution_tracking_runtime,
)

# PR package 11 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical MAIN-side attached-Android-runtime dispatch binding basis.
# Re-exported here so callers can reach the dispatch-binding API from
# core.runtime without importing the module directly.
from core.android_runtime_dispatch_binding import (  # noqa: E402
    ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY,
    BINDING_REQUIRES_ATTACHED_SESSION_POLICY,
    BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
    BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY,
    BINDING_SESSION_ID_MUST_MATCH_CONTRACT_POLICY,
    BINDING_STATE_IS_MONOTONIC_POLICY,
    RELEASED_BINDING_IS_TERMINAL_POLICY,
    BINDING_CONTRACT_ID_IS_IMMUTABLE_POLICY,
    DISPATCH_BINDING_REQUIRES_CONTRACT_ID_POLICY,
    BINDING_TRACKER_ID_IS_PROPAGATED_POLICY,
    ANDROID_RUNTIME_DISPATCH_BINDING_PR11_SENTINEL,
    AndroidRuntimeBindingState,
    AndroidRuntimeBindingSignal,
    AndroidRuntimeDispatchBindingIdentity,
    AndroidRuntimeDispatchBindingRecord,
    AndroidRuntimeDispatchBindingSnapshot,
    AndroidRuntimeDispatchBindingRuntime,
    create_android_dispatch_binding,
    advance_binding_state,
    resolve_dispatch_binding,
    record_dispatch_binding,
    get_dispatch_binding,
    get_dispatch_binding_by_contract,
    list_bound_dispatch_bindings,
    build_dispatch_binding_snapshot,
    get_dispatch_binding_runtime,
    reset_dispatch_binding_runtime,
)

# PR package 13 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical host-side Android execution signal reconciliation binding.
# Re-exported here so callers can reach the reconciler API from core.runtime
# without importing the module directly.
from core.android_execution_signal_reconciler import (  # noqa: E402
    ANDROID_EXECUTION_SIGNAL_RECONCILER_AUTHORITY,
    RECONCILER_REQUIRES_CONTRACT_ID_OR_SESSION_ID_POLICY,
    RECONCILER_SIGNAL_MAPPING_IS_CANONICAL_POLICY,
    RECONCILER_TERMINAL_RECORD_BLOCKS_FURTHER_SIGNALS_POLICY,
    RECONCILER_IDENTITY_IS_PRESERVED_ACROSS_RECONCILE_POLICY,
    RECONCILER_UNKNOWN_SIGNAL_DEFAULTS_TO_PROGRESS_POLICY,
    RECONCILER_TASK_STATUS_MAPS_TO_ACK_SIGNAL_CANONICALLY_POLICY,
    RECONCILER_ERROR_SIGNAL_CLOSES_TRACKING_RECORD_POLICY,
    RECONCILER_TIMEOUT_SIGNAL_CLOSES_TRACKING_RECORD_POLICY,
    RECONCILER_CANCELLED_SIGNAL_CLOSES_TRACKING_RECORD_POLICY,
    RECONCILER_RESULT_PAYLOAD_IS_FORWARDED_TO_TRACKER_POLICY,
    ANDROID_EXECUTION_SIGNAL_RECONCILER_PR13_SENTINEL,
    AndroidSignalKind,
    AndroidExecutionSignalEnvelope,
    AndroidSignalReconcileOutcome,
    normalize_android_message_to_signal_kind,
    extract_signal_envelope,
    reconcile_android_execution_signal,
    reconcile_inbound_message,
)

# PR package 14 (post-533 dual-repo runtime unification master plan, MAIN
# side): canonical persistent attached-runtime reuse binding.
# Re-exported here so callers can reach the reuse binding API from core.runtime
# without importing the module directly.
from core.attached_runtime_reuse_binding import (  # noqa: E402
    ATTACHED_RUNTIME_REUSE_BINDING_AUTHORITY,
    REUSE_BINDING_REQUIRES_ATTACHED_SESSION_POLICY,
    REUSE_BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
    REUSE_BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY,
    REUSE_ELIGIBILITY_REQUIRES_ACTIVE_SESSION_POLICY,
    REUSE_BINDING_INVALIDATED_ON_DETACH_POLICY,
    REUSE_BINDING_INVALIDATED_ON_DISCONNECT_POLICY,
    REUSE_BINDING_INVALIDATED_ON_DISABLE_POLICY,
    REUSE_BINDING_DISPATCH_BINDING_ID_IS_LATEST_POLICY,
    REUSE_BINDING_IS_STABLE_TARGETING_SURFACE_POLICY,
    ATTACHED_RUNTIME_REUSE_BINDING_PR14_SENTINEL,
    ReuseEligibilityStatus,
    ReuseInvalidationReason,
    AttachedRuntimeReuseBindingIdentity,
    AttachedRuntimeReuseBindingRecord,
    AttachedRuntimeReuseBindingSnapshot,
    AttachedRuntimeReuseBindingRuntime,
    establish_reuse_binding,
    evaluate_reuse_eligibility,
    invalidate_reuse_binding,
    register_dispatch_binding_id,
    record_reuse_binding,
    get_reuse_binding,
    get_reuse_binding_by_device,
    list_eligible_reuse_bindings,
    build_reuse_binding_snapshot,
    get_reuse_binding_runtime,
    reset_reuse_binding_runtime,
)

# PR package 16 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical ingress path for Android delegated execution signals.
# Re-exported here so callers can reach the ingress API from core.runtime
# without importing the module directly.
from core.android_delegated_signal_ingress import (  # noqa: E402
    ANDROID_DELEGATED_SIGNAL_INGRESS_AUTHORITY,
    INGRESS_DELEGATED_SIGNAL_TYPE_IS_CANONICAL_POLICY,
    INGRESS_SIGNAL_KIND_IS_EXPLICIT_FIELD_POLICY,
    INGRESS_RESULT_KIND_DISAMBIGUATES_RESULT_SIGNALS_POLICY,
    INGRESS_SIGNAL_ID_IS_PRESERVED_POLICY,
    INGRESS_EMISSION_SEQ_IS_PRESERVED_POLICY,
    INGRESS_IDENTITY_FIELDS_ARE_VERBATIM_POLICY,
    INGRESS_REQUIRES_LOOKUP_KEY_POLICY,
    INGRESS_DELEGATES_TO_RECONCILER_POLICY,
    INGRESS_TRACKER_PHASE_CONSISTENT_WITH_SIGNAL_KIND_POLICY,
    INGRESS_NON_DESTRUCTIVE_ON_MISS_POLICY,
    ANDROID_DELEGATED_SIGNAL_INGRESS_PR16_SENTINEL,
    DelegatedSignalKind,
    ResultKind,
    DelegatedExecutionSignalEnvelope,
    extract_delegated_signal_envelope,
    ingest_delegated_execution_signal,
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
    # PR-2 coordination-role alignment
    "OBSERVER_ONLY_ROLE_BLOCKS_EXECUTION_POLICY",
    "COORDINATION_ROLE_ALIGNED_DISPATCH_SENTINEL",
    "check_source_eligibility_with_coordination_role",
    "SourceExecutionEligibility",
    "check_source_execution_eligibility",
    "is_source_eligible_for_local_execution",
    "resolve_posture_for_eligibility",
    # PR-4: Canonical Runtime Session Truth and Result Merge
    "CANONICAL_SESSION_TRUTH_AUTHORITY",
    "CONTROL_ONLY_EXCLUDED_FROM_MERGE_POLICY",
    "POSTURE_AWARE_RESULT_FILTER_POLICY",
    "JOIN_RUNTIME_INCLUDED_IN_MERGE_POLICY",
    "OBSERVER_ONLY_ROLE_EXCLUDED_FROM_MERGE_POLICY",
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
    # PR package 1: Posture Contract Canonicalization (MAIN repo side)
    "POSTURE_CONTRACT_CANONICALIZATION_AUTHORITY",
    "POSTURE_BOUNDARY_NO_ENTRY_MODE_CONFLATION_POLICY",
    "POSTURE_BOUNDARY_NO_CROSS_DEVICE_FLAG_CONFLATION_POLICY",
    "POSTURE_BOUNDARY_NO_FORMATION_ROLE_CONFLATION_POLICY",
    "POSTURE_CONTRACT_PR_PACKAGE_1_SENTINEL",
    "PostureBoundaryViolation",
    "canonicalize_posture_in_payload",
    "validate_posture_field_consistency",
    "assert_posture_boundary_compliance",
    "get_posture_from_payload",
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
    # PR-5: Android First-Class Runtime Host (MAIN repo side)
    "ANDROID_FIRST_CLASS_RUNTIME_HOST_PR5_SENTINEL",
    "ANDROID_RUNTIME_HOST_DISTINCT_FROM_CONNECTED_DEVICE_PR5",
    "ANDROID_RUNTIME_HOST_POSTURE_PRESERVED_PR5",
    "AndroidRuntimeHostRole",
    "AndroidRuntimeHostIdentity",
    "classify_android_runtime_host",
    "build_android_runtime_host_identity",
    # PR package 6: Canonical Capability & Scheduling Basis (MAIN repo side)
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY",
    "FULL_RUNTIME_TIER_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY",
    "COMMAND_ONLY_TIER_BLOCKS_EXECUTION_PLACEMENT_POLICY",
    "CAPABILITY_TIER_DRIVES_SURFACE_ELIGIBILITY_POLICY",
    "OBSERVER_ONLY_ROLE_EXCLUDED_FROM_SCHEDULING_POLICY",
    "ANDROID_HOST_CAPABILITY_LIFTED_FROM_PR5_POLICY",
    "SCHEDULING_BASIS_NORMALISATION_IS_ADDITIVE_POLICY",
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL",
    "CapabilityTier",
    "ExecutionSurface",
    "RuntimeCapabilityProfile",
    "SchedulingBasisInputs",
    "ExecutionSurfaceEligibility",
    "build_runtime_capability_profile",
    "build_scheduling_basis_inputs",
    "evaluate_execution_surface_eligibility",
    "normalize_scheduling_inputs",
    # PR package 7: Canonical Persistent Attached-Runtime Session Semantics (MAIN repo side)
    "ATTACHED_RUNTIME_SESSION_AUTHORITY",
    "ATTACHED_SESSION_PERSISTS_ACROSS_REQUESTS_POLICY",
    "TRANSIENT_PRESENCE_DISTINCT_FROM_ATTACHED_SESSION_POLICY",
    "DETACH_SIGNAL_REQUIRED_FOR_SESSION_TERMINATION_POLICY",
    "ATTACH_IS_IDEMPOTENT_POLICY",
    "DISCONNECTED_DOES_NOT_INVALIDATE_SESSION_POLICY",
    "INVALIDATED_SESSION_IS_TERMINAL_POLICY",
    "DISABLED_SESSION_NOT_ELIGIBLE_FOR_EXECUTION_POLICY",
    "ATTACHED_SESSION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY",
    "ATTACHMENT_LIFECYCLE_IS_POSTURE_AWARE_POLICY",
    "ATTACHED_RUNTIME_SESSION_PR7_SENTINEL",
    "AttachmentState",
    "AttachmentLifecycleSignal",
    "AttachedRuntimeSessionRecord",
    "AttachedRuntimeSessionSnapshot",
    "AttachedRuntimeSessionRuntime",
    "attach_runtime_session",
    "apply_lifecycle_signal",
    "get_attached_runtime_session",
    "list_active_attached_sessions",
    "build_attached_runtime_session_snapshot",
    "get_attached_runtime_session_runtime",
    "reset_attached_runtime_session_runtime",
    # PR package 8: Canonical Delegated-Runtime Dispatch Intent and Handoff-Preparation (MAIN repo side)
    "DELEGATED_RUNTIME_DISPATCH_INTENT_AUTHORITY",
    "DELEGATION_REQUIRES_ATTACHED_SESSION_POLICY",
    "DELEGATION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY",
    "OBSERVER_ONLY_ROLE_BLOCKS_DELEGATION_POLICY",
    "TARGET_ONLY_EXECUTOR_CANNOT_DELEGATE_POLICY",
    "COMMAND_ONLY_TIER_BLOCKS_FULL_DELEGATION_POLICY",
    "HANDOFF_INPUTS_MUST_BE_SESSION_ANCHORED_POLICY",
    "DELEGATION_INTENT_IS_ADDITIVE_TO_SESSION_POLICY",
    "DISPATCH_RECORD_IS_IMMUTABLE_POLICY",
    "PREPARATION_STATE_IS_MONOTONICALLY_ADVANCING_POLICY",
    "DELEGATED_RUNTIME_DISPATCH_INTENT_PR8_SENTINEL",
    "DelegationIntent",
    "HandoffPreparationState",
    "DelegatedRuntimeDispatchRecord",
    "HandoffInputBundle",
    "DispatchEligibilityOutcome",
    "DelegatedRuntimeDispatchSnapshot",
    "DelegatedRuntimeDispatchRuntime",
    "build_delegated_dispatch_record",
    "evaluate_dispatch_eligibility",
    "prepare_handoff_inputs",
    "record_delegated_dispatch_intent",
    "get_delegated_dispatch_record",
    "list_pending_delegated_dispatch_records",
    "build_delegated_dispatch_snapshot",
    "get_delegated_runtime_dispatch_runtime",
    "reset_delegated_runtime_dispatch_runtime",
    # PR package 9: Canonical Delegated-Runtime Handoff Contract Foundations (MAIN repo side)
    "DELEGATED_RUNTIME_HANDOFF_CONTRACT_AUTHORITY",
    "HANDOFF_CONTRACT_REQUIRES_DISPATCH_RECORD_POLICY",
    "HANDOFF_CONTRACT_REQUIRES_ATTACHED_SESSION_POLICY",
    "HANDOFF_CONTRACT_VERSION_MUST_BE_EXPLICIT_POLICY",
    "HANDOFF_CONTRACT_IDENTITY_IS_IMMUTABLE_POLICY",
    "HANDOFF_CONTRACT_STATUS_IS_MONOTONIC_POLICY",
    "HANDOFF_CONTRACT_POSTURE_IS_PRESERVED_POLICY",
    "SEALED_CONTRACT_IS_DISPATCH_READY_POLICY",
    "HANDOFF_CONTRACT_PAYLOAD_MUST_BE_NON_EMPTY_POLICY",
    "HANDOFF_CONTRACT_TRACE_ID_IS_PROPAGATED_POLICY",
    "DELEGATED_RUNTIME_HANDOFF_CONTRACT_PR9_SENTINEL",
    "HandoffContractVersion",
    "HandoffContractStatus",
    "DelegatedHandoffContractIdentity",
    "DelegatedHandoffContractMeta",
    "DelegatedHandoffContractPayload",
    "DelegatedHandoffContractRecord",
    "DelegatedHandoffContractSnapshot",
    "DelegatedHandoffContractRuntime",
    "build_delegated_handoff_contract",
    "seal_handoff_contract",
    "record_handoff_contract",
    "get_handoff_contract",
    "list_pending_handoff_contracts",
    "build_handoff_contract_snapshot",
    "get_handoff_contract_runtime",
    "reset_handoff_contract_runtime",
    # PR package 10: Canonical Delegated-Runtime Execution-Tracking and Acknowledgment Basis (MAIN repo side)
    "DELEGATED_RUNTIME_EXECUTION_TRACKER_AUTHORITY",
    "EXECUTION_TRACKING_REQUIRES_CONTRACT_ID_POLICY",
    "EXECUTION_TRACKING_REQUIRES_SESSION_ID_POLICY",
    "EXECUTION_PHASE_IS_MONOTONIC_POLICY",
    "ACK_SEQUENCE_IS_MONOTONICALLY_INCREASING_POLICY",
    "RESULT_IS_IMMUTABLE_ONCE_RECORDED_POLICY",
    "EXECUTION_TRACKING_POSTURE_IS_PROPAGATED_POLICY",
    "TERMINAL_PHASE_BLOCKS_FURTHER_SIGNALS_POLICY",
    "TRACKING_RECORD_IS_CONTRACT_ANCHORED_POLICY",
    "PARTIAL_RESULT_DOES_NOT_CLOSE_TRACKING_POLICY",
    "DELEGATED_RUNTIME_EXECUTION_TRACKER_PR10_SENTINEL",
    "DelegatedExecutionPhase",
    "AcknowledgmentSignal",
    "DelegatedExecutionIdentity",
    "DelegatedExecutionAcknowledgment",
    "DelegatedExecutionResult",
    "DelegatedExecutionTrackingRecord",
    "DelegatedExecutionTrackingSnapshot",
    "DelegatedExecutionTrackingRuntime",
    "create_execution_tracking_record",
    "apply_acknowledgment_signal",
    "apply_result",
    "record_execution_tracking",
    "get_execution_tracking_record",
    "list_active_execution_tracking_records",
    "build_execution_tracking_snapshot",
    "get_execution_tracking_runtime",
    "reset_execution_tracking_runtime",
    # PR package 11: Canonical MAIN-Side Attached-Android-Runtime Dispatch Binding Basis (MAIN repo side)
    "ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY",
    "BINDING_REQUIRES_ATTACHED_SESSION_POLICY",
    "BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY",
    "BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY",
    "BINDING_SESSION_ID_MUST_MATCH_CONTRACT_POLICY",
    "BINDING_STATE_IS_MONOTONIC_POLICY",
    "RELEASED_BINDING_IS_TERMINAL_POLICY",
    "BINDING_CONTRACT_ID_IS_IMMUTABLE_POLICY",
    "DISPATCH_BINDING_REQUIRES_CONTRACT_ID_POLICY",
    "BINDING_TRACKER_ID_IS_PROPAGATED_POLICY",
    "ANDROID_RUNTIME_DISPATCH_BINDING_PR11_SENTINEL",
    "AndroidRuntimeBindingState",
    "AndroidRuntimeBindingSignal",
    "AndroidRuntimeDispatchBindingIdentity",
    "AndroidRuntimeDispatchBindingRecord",
    "AndroidRuntimeDispatchBindingSnapshot",
    "AndroidRuntimeDispatchBindingRuntime",
    "create_android_dispatch_binding",
    "advance_binding_state",
    "resolve_dispatch_binding",
    "record_dispatch_binding",
    "get_dispatch_binding",
    "get_dispatch_binding_by_contract",
    "list_bound_dispatch_bindings",
    "build_dispatch_binding_snapshot",
    "get_dispatch_binding_runtime",
    "reset_dispatch_binding_runtime",
    # PR package 13: Canonical Host-Side Android Execution Signal Reconciliation Binding (MAIN repo side)
    "ANDROID_EXECUTION_SIGNAL_RECONCILER_AUTHORITY",
    "RECONCILER_REQUIRES_CONTRACT_ID_OR_SESSION_ID_POLICY",
    "RECONCILER_SIGNAL_MAPPING_IS_CANONICAL_POLICY",
    "RECONCILER_TERMINAL_RECORD_BLOCKS_FURTHER_SIGNALS_POLICY",
    "RECONCILER_IDENTITY_IS_PRESERVED_ACROSS_RECONCILE_POLICY",
    "RECONCILER_UNKNOWN_SIGNAL_DEFAULTS_TO_PROGRESS_POLICY",
    "RECONCILER_TASK_STATUS_MAPS_TO_ACK_SIGNAL_CANONICALLY_POLICY",
    "RECONCILER_ERROR_SIGNAL_CLOSES_TRACKING_RECORD_POLICY",
    "RECONCILER_TIMEOUT_SIGNAL_CLOSES_TRACKING_RECORD_POLICY",
    "RECONCILER_CANCELLED_SIGNAL_CLOSES_TRACKING_RECORD_POLICY",
    "RECONCILER_RESULT_PAYLOAD_IS_FORWARDED_TO_TRACKER_POLICY",
    "ANDROID_EXECUTION_SIGNAL_RECONCILER_PR13_SENTINEL",
    "AndroidSignalKind",
    "AndroidExecutionSignalEnvelope",
    "AndroidSignalReconcileOutcome",
    "normalize_android_message_to_signal_kind",
    "extract_signal_envelope",
    "reconcile_android_execution_signal",
    "reconcile_inbound_message",
    # PR package 14: Canonical Persistent Attached-Runtime Reuse Binding (MAIN repo side)
    "ATTACHED_RUNTIME_REUSE_BINDING_AUTHORITY",
    "REUSE_BINDING_REQUIRES_ATTACHED_SESSION_POLICY",
    "REUSE_BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY",
    "REUSE_BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY",
    "REUSE_ELIGIBILITY_REQUIRES_ACTIVE_SESSION_POLICY",
    "REUSE_BINDING_INVALIDATED_ON_DETACH_POLICY",
    "REUSE_BINDING_INVALIDATED_ON_DISCONNECT_POLICY",
    "REUSE_BINDING_INVALIDATED_ON_DISABLE_POLICY",
    "REUSE_BINDING_DISPATCH_BINDING_ID_IS_LATEST_POLICY",
    "REUSE_BINDING_IS_STABLE_TARGETING_SURFACE_POLICY",
    "ATTACHED_RUNTIME_REUSE_BINDING_PR14_SENTINEL",
    "ReuseEligibilityStatus",
    "ReuseInvalidationReason",
    "AttachedRuntimeReuseBindingIdentity",
    "AttachedRuntimeReuseBindingRecord",
    "AttachedRuntimeReuseBindingSnapshot",
    "AttachedRuntimeReuseBindingRuntime",
    "establish_reuse_binding",
    "evaluate_reuse_eligibility",
    "invalidate_reuse_binding",
    "register_dispatch_binding_id",
    "record_reuse_binding",
    "get_reuse_binding",
    "get_reuse_binding_by_device",
    "list_eligible_reuse_bindings",
    "build_reuse_binding_snapshot",
    "get_reuse_binding_runtime",
    "reset_reuse_binding_runtime",
    # PR package 16: Canonical Ingress Path for Android Delegated Execution Signals (MAIN repo side)
    "ANDROID_DELEGATED_SIGNAL_INGRESS_AUTHORITY",
    "INGRESS_DELEGATED_SIGNAL_TYPE_IS_CANONICAL_POLICY",
    "INGRESS_SIGNAL_KIND_IS_EXPLICIT_FIELD_POLICY",
    "INGRESS_RESULT_KIND_DISAMBIGUATES_RESULT_SIGNALS_POLICY",
    "INGRESS_SIGNAL_ID_IS_PRESERVED_POLICY",
    "INGRESS_EMISSION_SEQ_IS_PRESERVED_POLICY",
    "INGRESS_IDENTITY_FIELDS_ARE_VERBATIM_POLICY",
    "INGRESS_REQUIRES_LOOKUP_KEY_POLICY",
    "INGRESS_DELEGATES_TO_RECONCILER_POLICY",
    "INGRESS_TRACKER_PHASE_CONSISTENT_WITH_SIGNAL_KIND_POLICY",
    "INGRESS_NON_DESTRUCTIVE_ON_MISS_POLICY",
    "ANDROID_DELEGATED_SIGNAL_INGRESS_PR16_SENTINEL",
    "DelegatedSignalKind",
    "ResultKind",
    "DelegatedExecutionSignalEnvelope",
    "extract_delegated_signal_envelope",
    "ingest_delegated_execution_signal",
]
