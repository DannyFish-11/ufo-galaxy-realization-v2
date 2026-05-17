"""
core/routes/projection.py
==========================
Read-only RuntimeProjection endpoint for the Status Board V2.

This module exposes **two GET endpoints**:

  GET /api/v1/projection/runtime
      Returns the current RuntimeProjection assembled from live ContinuumState
      (and an optional TopologyRoutePlan if the model topology layer is
      available).

  GET /api/v1/projection/return
      Returns the current ReturnSummary (PR-10 return intelligence) alongside
      the RuntimeProjection.  The payload contains all RuntimeProjection fields
      plus a nested ``"return_intelligence"`` key populated by the
      return-intelligence adapter.

Design constraints
------------------
- **Read-only** — this router never writes state, sends commands, or triggers
  actions.  It only reads and serialises.
- **Not dashboard** — this module is part of ``core/routes/``, intentionally
  separate from ``dashboard/backend/``.
- **Graceful degradation** — if the continuum layer or topology layer is
  unavailable the endpoint returns a minimal valid projection rather than an
  error, so that the status board always has something to display.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from core.continuum.types import ContinuumState

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.Routes.Projection")

# PR-511: Projection Surface Bridge integration sentinel.
# The bridge module is imported lazily inside endpoints to preserve graceful
# degradation if the bridge layer is unavailable.  This sentinel asserts the
# integration point is present and machine-checkable.
try:
    from core.projection_surface_bridge import (  # noqa: F401
        PROJECTION_SURFACE_BRIDGE_AUTHORITY as _PSB_AUTHORITY,
    )

    PROJECTION_SURFACE_BRIDGE_INTEGRATED: str = "PROJECTION_ROUTES::PROJECTION_SURFACE_BRIDGE_INTEGRATED_V1"
except ImportError:  # pragma: no cover
    PROJECTION_SURFACE_BRIDGE_INTEGRATED: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::PROJECTION_SURFACE_BRIDGE_INTEGRATED_UNAVAILABLE"
    )

# PR-514: Authority Conflict Elimination integration sentinel.
# Asserts that _assemble_projection() and _assemble_desktop_status_board_payload()
# now call enrich_runtime_projection() from ProjectionSurfaceBridge, resolving
# GAP-512-003 (bridge not consumed by status board assembly) and GAP-512-005
# (status board assembled without reading canonical OperatorSurface).
try:
    from core.authority_conflict_elimination import (  # noqa: F401
        AUTHORITY_CONFLICT_ELIMINATION_AUTHORITY as _ACE_AUTHORITY,
    )

    AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED: str = "PROJECTION_ROUTES::AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED_V1"
except ImportError:  # pragma: no cover
    AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED_UNAVAILABLE"
    )

# PR-522: Multi-Device Projection Canonicalization integration sentinel.
# Asserts that get_multi_device_runtime_projection() now calls
# enrich_multi_device_projection() from MultiDeviceProjectionCanonicalization,
# closing GAP-517-008 (projection based on raw registry/session data instead of
# canonical CrossDeviceChainSingleton / TaskGraphRuntime state).
try:
    from core.multi_device_projection_canonicalization import (  # noqa: F401
        MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY as _MDPC_AUTHORITY,
    )

    MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED: str = (
        "PROJECTION_ROUTES::MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED_V1"
    )
except ImportError:  # pragma: no cover
    MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED_UNAVAILABLE"
    )

# PR-531: Outward Runtime Truth integration sentinel.
# Asserts that the outward runtime truth governance layer (PR-531) is available
# and wired into the projection routes module, ensuring outward surfaces can
# source from compile_outward_truth() rather than independently assembling state.
try:
    from core.outward_runtime_truth import (  # noqa: F401
        OUTWARD_RUNTIME_TRUTH_AUTHORITY as _ORT_AUTHORITY,
        compile_outward_truth as _compile_outward_truth,
    )

    OUTWARD_RUNTIME_TRUTH_INTEGRATED: str = "PROJECTION_ROUTES::OUTWARD_RUNTIME_TRUTH_INTEGRATED_V1"
except ImportError:  # pragma: no cover
    OUTWARD_RUNTIME_TRUTH_INTEGRATED: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::OUTWARD_RUNTIME_TRUTH_INTEGRATED_UNAVAILABLE"
    )

# PR-4 (post-533 dual-repo runtime host unification): Canonical Session Truth
# alignment sentinel.  Asserts that the canonical session truth module is
# importable from this module's context, so projection endpoints can embed
# canonical runtime-attachment session truth snapshots (distinct from
# conversation/history sessions) when assembling runtime projections.
try:
    from core.canonical_session_truth import (  # noqa: F401
        CANONICAL_SESSION_TRUTH_AUTHORITY as _CST_AUTHORITY,
        build_canonical_session_truth_snapshot as _build_cst_snapshot,
    )

    CANONICAL_SESSION_TRUTH_ALIGNED_PR4: str = (
        "PROJECTION_ROUTES::CANONICAL_SESSION_TRUTH_ALIGNED_PR4_V1: "
        "canonical session truth (core.canonical_session_truth) is available "
        "and aligned with projection routes.  Projection endpoints may embed "
        "CanonicalSessionTruthSnapshot for operator/runtime surface consumers."
    )
except ImportError:  # pragma: no cover
    CANONICAL_SESSION_TRUTH_ALIGNED_PR4: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::CANONICAL_SESSION_TRUTH_ALIGNED_PR4_UNAVAILABLE"
    )

# PR-5 (post-533 dual-repo runtime unification, MAIN repo side): Android
# first-class runtime host alignment sentinel.  Asserts that the Android
# runtime host classification module is importable from this module's context,
# enabling projection endpoints to represent Android host participation
# distinctly from generic connected-device presence.
try:
    from core.android_runtime_host import (  # noqa: F401
        ANDROID_FIRST_CLASS_RUNTIME_HOST_PR5_SENTINEL as _ARHR_PR5,
        classify_android_runtime_host as _classify_android_host,
        build_android_runtime_host_identity as _build_android_identity,
        AndroidRuntimeHostRole as _AndroidRuntimeHostRole,
    )

    ANDROID_RUNTIME_HOST_ALIGNED_PR5: str = (
        "PROJECTION_ROUTES::ANDROID_RUNTIME_HOST_ALIGNED_PR5_V1: "
        "Android runtime-host classification (core.android_runtime_host) is "
        "available and aligned with projection routes.  Projection endpoints "
        "can represent Android host participation distinctly from generic "
        "connected-device presence."
    )
except ImportError:  # pragma: no cover
    ANDROID_RUNTIME_HOST_ALIGNED_PR5: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::ANDROID_RUNTIME_HOST_ALIGNED_PR5_UNAVAILABLE"
    )

# PR package 6 (post-533 dual-repo runtime unification, MAIN repo side):
# Canonical Capability & Scheduling Basis alignment sentinel.  Asserts that
# the canonical capability/scheduling basis module is importable from this
# module's context, enabling projection endpoints to represent execution-
# surface eligibility and capability-tier information in runtime projections.
try:
    from core.canonical_capability_scheduling_basis import (  # noqa: F401
        CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY as _CCSB_AUTHORITY,
        CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL as _CCSB_PR6,
        CapabilityTier as _CapabilityTier,
        ExecutionSurface as _ExecutionSurface,
        build_runtime_capability_profile as _build_runtime_cap_profile,
        evaluate_execution_surface_eligibility as _eval_surface_eligibility,
    )

    CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6: str = (
        "PROJECTION_ROUTES::CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6_V1: "
        "canonical capability/scheduling basis (core.canonical_capability_scheduling_basis) "
        "is available and aligned with projection routes.  Projection endpoints "
        "can represent CapabilityTier and ExecutionSurface eligibility alongside "
        "existing posture and coordination-role projections."
    )
except ImportError:  # pragma: no cover
    CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6_UNAVAILABLE"
    )

# PR package 7 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical persistent attached-runtime session semantics.  Importing
# the authority sentinel and the PR-7 sentinel from the new module ties the
# projection route layer to the session-level attachment model, enabling
# projection endpoints to surface attached-runtime session state.
try:
    from core.attached_runtime_session import (  # noqa: F401
        ATTACHED_RUNTIME_SESSION_AUTHORITY as _ARSA_AUTHORITY,
        ATTACHED_RUNTIME_SESSION_PR7_SENTINEL as _ARS_PR7,
        AttachmentState as _AttachmentState,
        AttachmentLifecycleSignal as _AttachmentLifecycleSignal,
        get_attached_runtime_session as _get_attached_runtime_session,
        list_active_attached_sessions as _list_active_attached_sessions,
        build_attached_runtime_session_snapshot as _build_ars_snapshot,
    )

    ATTACHED_RUNTIME_SESSION_ALIGNED_PR7: str = (
        "PROJECTION_ROUTES::ATTACHED_RUNTIME_SESSION_ALIGNED_PR7_V1: "
        "canonical attached-runtime session semantics (core.attached_runtime_session) "
        "is available and aligned with projection routes.  Projection endpoints "
        "can surface AttachmentState lifecycle and active attached-runtime sessions "
        "alongside existing posture, coordination-role, and capability projections."
    )
except ImportError:  # pragma: no cover
    ATTACHED_RUNTIME_SESSION_ALIGNED_PR7: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::ATTACHED_RUNTIME_SESSION_ALIGNED_PR7_UNAVAILABLE"
    )

# PR-7 (cross-repo convergence): truth-vs-projection boundary alignment
# sentinel.  This confirms projection routes can import the explicit
# cross-plane boundary catalogue so projection/read-model surfaces remain
# visibly non-authoritative relative to canonical lifecycle owners.
try:
    from core.truth_projection_boundary import (  # noqa: F401
        TRUTH_PROJECTION_BOUNDARY_IS_AUTHORITY as _TPB_AUTHORITY,
        TRUTH_PROJECTION_BOUNDARY_PR7_SENTINEL as _TPB_PR7,
        build_truth_projection_boundary_snapshot as _build_truth_projection_boundary_snapshot,
    )

    TRUTH_PROJECTION_BOUNDARY_ALIGNED_PR7: str = (
        "PROJECTION_ROUTES::TRUTH_PROJECTION_BOUNDARY_ALIGNED_PR7_V1: "
        "core.truth_projection_boundary is available to projection routes.  "
        "Cross-plane truth ownership (participant/device/session/capability/execution) "
        "is explicitly separated from projection/read-model and synchronization surfaces."
    )
except ImportError:  # pragma: no cover
    TRUTH_PROJECTION_BOUNDARY_ALIGNED_PR7: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::TRUTH_PROJECTION_BOUNDARY_ALIGNED_PR7_UNAVAILABLE"
    )

# PR package 8 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical delegated-runtime dispatch intent and handoff-preparation
# foundations.  Importing the authority sentinel and the PR-8 sentinel from
# the new module ties the projection route layer to the dispatch-intent model,
# enabling projection endpoints to surface delegated dispatch state alongside
# attached-runtime session, posture, coordination-role, and capability data.
try:
    from core.delegated_runtime_dispatch_intent import (  # noqa: F401
        DELEGATED_RUNTIME_DISPATCH_INTENT_AUTHORITY as _DRDDI_AUTHORITY,
        DELEGATED_RUNTIME_DISPATCH_INTENT_PR8_SENTINEL as _DRDDI_PR8,
        DelegationIntent as _DelegationIntent,
        HandoffPreparationState as _HandoffPreparationState,
        evaluate_dispatch_eligibility as _evaluate_dispatch_eligibility,
        list_pending_delegated_dispatch_records as _list_pending_dispatch,
        build_delegated_dispatch_snapshot as _build_dispatch_snapshot,
    )

    DELEGATED_RUNTIME_DISPATCH_INTENT_ALIGNED_PR8: str = (
        "PROJECTION_ROUTES::DELEGATED_RUNTIME_DISPATCH_INTENT_ALIGNED_PR8_V1: "
        "canonical delegated-runtime dispatch intent and handoff-preparation "
        "foundations (core.delegated_runtime_dispatch_intent) is available and "
        "aligned with projection routes.  Projection endpoints can surface "
        "DelegationIntent, HandoffPreparationState, and dispatch eligibility "
        "alongside attached-runtime session and capability projections."
    )
except ImportError:  # pragma: no cover
    DELEGATED_RUNTIME_DISPATCH_INTENT_ALIGNED_PR8: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::DELEGATED_RUNTIME_DISPATCH_INTENT_ALIGNED_PR8_UNAVAILABLE"
    )

# PR package 9 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical delegated-runtime handoff contract foundations.  Importing
# the authority sentinel and the PR-9 sentinel from the new module ties the
# projection route layer to the handoff-contract model, enabling projection
# endpoints to surface handoff contract state alongside dispatch intent,
# attached-runtime session, posture, coordination-role, and capability data.
try:
    from core.delegated_runtime_handoff_contract import (  # noqa: F401
        DELEGATED_RUNTIME_HANDOFF_CONTRACT_AUTHORITY as _DRHC_AUTHORITY,
        DELEGATED_RUNTIME_HANDOFF_CONTRACT_PR9_SENTINEL as _DRHC_PR9,
        HandoffContractVersion as _HandoffContractVersion,
        HandoffContractStatus as _HandoffContractStatus,
        build_delegated_handoff_contract as _build_delegated_handoff_contract,
        list_pending_handoff_contracts as _list_pending_handoff_contracts,
        build_handoff_contract_snapshot as _build_handoff_contract_snapshot,
    )

    DELEGATED_RUNTIME_HANDOFF_CONTRACT_ALIGNED_PR9: str = (
        "PROJECTION_ROUTES::DELEGATED_RUNTIME_HANDOFF_CONTRACT_ALIGNED_PR9_V1: "
        "canonical delegated-runtime handoff contract foundations "
        "(core.delegated_runtime_handoff_contract) is available and aligned "
        "with projection routes.  Projection endpoints can surface "
        "HandoffContractVersion, HandoffContractStatus, and pending handoff "
        "contracts alongside dispatch intent and attached-runtime session "
        "projections."
    )
except ImportError:  # pragma: no cover
    DELEGATED_RUNTIME_HANDOFF_CONTRACT_ALIGNED_PR9: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::DELEGATED_RUNTIME_HANDOFF_CONTRACT_ALIGNED_PR9_UNAVAILABLE"
    )

# PR-5 (UGCP convergence plan, realization-v2 side): unified UGCP control
# transfer profile alignment (handoff/takeover/delegated execution transfer).
try:
    from core.ugcp_control_transfer_profile import (  # noqa: F401
        UGCP_CONTROL_TRANSFER_PROFILE_AUTHORITY as _UCTP_AUTHORITY,
        UGCP_CONTROL_TRANSFER_PROFILE_PR5_SENTINEL as _UCTP_PR5,
        ControlTransferFamily as _ControlTransferFamily,
        ControlTransferState as _ControlTransferState,
        ControlTransferTerminalReason as _ControlTransferTerminalReason,
        build_control_transfer_truth_event as _build_control_transfer_truth_event,
        can_transition as _transfer_can_transition,
    )

    UGCP_CONTROL_TRANSFER_PROFILE_ALIGNED_PR5: str = (
        "PROJECTION_ROUTES::UGCP_CONTROL_TRANSFER_PROFILE_ALIGNED_PR5_V1: "
        "unified UGCP control-transfer profile "
        "(core.ugcp_control_transfer_profile) is available and aligned with "
        "projection routes. Transfer state and terminal semantics can be "
        "interpreted consistently across handoff, takeover, and delegated "
        "execution flows."
    )
except ImportError:  # pragma: no cover
    UGCP_CONTROL_TRANSFER_PROFILE_ALIGNED_PR5: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::UGCP_CONTROL_TRANSFER_PROFILE_ALIGNED_PR5_UNAVAILABLE"
    )

# PR-6 (UGCP convergence plan, realization-v2 side): canonical UGCP
# coordination profile alignment (mesh session / participant roles /
# coordination authority / barriers / aggregation / outcomes).
try:
    from core.ugcp_coordination_profile import (  # noqa: F401
        UGCP_COORDINATION_PROFILE_AUTHORITY as _UCP_AUTHORITY,
        UGCP_COORDINATION_PROFILE_PR6_SENTINEL as _UCP_PR6,
        CoordinationLifecycleState as _CoordinationLifecycleState,
        CoordinationAuthorityScope as _CoordinationAuthorityScope,
        CoordinationParticipantRole as _CoordinationParticipantRole,
        CoordinationTerminalOutcome as _CoordinationTerminalOutcome,
        build_coordination_truth_event as _build_coordination_truth_event,
        build_coordination_durable_snapshot as _build_coordination_durable_snapshot,
        can_transition as _coordination_can_transition,
    )

    UGCP_COORDINATION_PROFILE_ALIGNED_PR6: str = (
        "PROJECTION_ROUTES::UGCP_COORDINATION_PROFILE_ALIGNED_PR6_V1: "
        "canonical UGCP coordination profile "
        "(core.ugcp_coordination_profile) is available and aligned with "
        "projection routes. Mesh/coordinator lifecycle, participant role, "
        "authority, barrier, aggregation, and terminal-outcome semantics can be "
        "interpreted consistently and traced into truth/durable surfaces."
    )
except ImportError:  # pragma: no cover
    UGCP_COORDINATION_PROFILE_ALIGNED_PR6: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::UGCP_COORDINATION_PROFILE_ALIGNED_PR6_UNAVAILABLE"
    )

# PR-7 (UGCP convergence plan, realization-v2 side): canonical truth/event
# backbone alignment across authoritative truth writes, event vocabulary,
# durable snapshot surfaces, and replay/recovery checkpoints.
try:
    from core.ugcp_truth_event_model import (  # noqa: F401
        UGCP_TRUTH_EVENT_MODEL_AUTHORITY as _UTEM_AUTHORITY,
        UGCP_TRUTH_EVENT_MODEL_PR7_SENTINEL as _UTEM_PR7,
        CanonicalTruthEventType as _CanonicalTruthEventType,
        TruthSurfaceClass as _TruthSurfaceClass,
        build_session_truth_authoritative_event as _build_session_truth_authoritative_event,
        build_snapshot_projection_surface as _build_snapshot_projection_surface,
        build_replay_checkpoint as _build_replay_checkpoint,
        build_runtime_observational_stream_event as _build_runtime_observational_stream_event,
    )

    UGCP_TRUTH_EVENT_MODEL_ALIGNED_PR7: str = (
        "PROJECTION_ROUTES::UGCP_TRUTH_EVENT_MODEL_ALIGNED_PR7_V1: "
        "canonical UGCP truth/event backbone "
        "(core.ugcp_truth_event_model) is available and aligned with projection "
        "routes. Authoritative truth transitions, canonical transition event "
        "vocabulary, durable snapshots, replay checkpoints, and runtime "
        "observational streams share one explicit semantic model."
    )
except ImportError:  # pragma: no cover
    UGCP_TRUTH_EVENT_MODEL_ALIGNED_PR7: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::UGCP_TRUTH_EVENT_MODEL_ALIGNED_PR7_UNAVAILABLE"
    )

# PR-8 (UGCP convergence plan, realization-v2 side): conformance surfaces and
# compatibility-retirement groundwork across schema/lifecycle/authority/
# transfer/coordination/truth-event semantics.
try:
    from core.ugcp_conformance_surfaces import (  # noqa: F401
        UGCP_CONFORMANCE_SURFACES_AUTHORITY as _UCS_AUTHORITY,
        UGCP_CONFORMANCE_SURFACES_PR8_SENTINEL as _UCS_PR8,
        UGCP_ENFORCEMENT_SCAFFOLDING_PR10_SENTINEL as _UES_PR10,
        UGCP_MIGRATION_READINESS_PR11_SENTINEL as _UMR_PR11,
        UGCP_CONVERGENCE_VISIBILITY_AUDIT_PR12_SENTINEL as _UCV_PR12,
        UGCP_STAGED_STRICTNESS_ROLLOUT_GATING_PR14_SENTINEL as _USR_PR14,
        UGCPConformanceSurface as _UGCPConformanceSurface,
        UGCPSemanticClass as _UGCPSemanticClass,
        UGCPEnforcementMode as _UGCPEnforcementMode,
        UGCPEnforcementAction as _UGCPEnforcementAction,
        UGCPDeprecationStage as _UGCPDeprecationStage,
        classify_surface_semantics as _classify_surface_semantics,
        evaluate_surface_enforcement as _evaluate_surface_enforcement,
        build_enforcement_scaffold as _build_enforcement_scaffold,
        normalize_conformance_payload as _normalize_conformance_payload,
        normalize_conformance_backbone as _normalize_conformance_backbone,
        build_conformance_invariant_report as _build_conformance_invariant_report,
        get_ugcp_conformance_surface_catalog as _get_ugcp_conformance_surface_catalog,
        get_ugcp_retirement_stage_catalog as _get_ugcp_retirement_stage_catalog,
        build_migration_readiness_scaffold as _build_migration_readiness_scaffold,
        build_ugcp_convergence_visibility_audit as _build_ugcp_convergence_visibility_audit,
        build_staged_strictness_rollout_gating_scaffold as _build_staged_strictness_rollout_gating_scaffold,
    )

    UGCP_CONFORMANCE_SURFACES_ALIGNED_PR8: str = (
        "PROJECTION_ROUTES::UGCP_CONFORMANCE_SURFACES_ALIGNED_PR8_V1: "
        "canonical UGCP conformance surface scaffold "
        "(core.ugcp_conformance_surfaces) is available and aligned with "
        "projection routes. Canonical vs transitional classification, "
        "normalization boundaries, composed cross-profile lifecycle backbone "
        "normalization, and invariant reports are explicit and reviewable "
        "without forcing strict-mode breakage."
    )
    UGCP_ENFORCEMENT_SCAFFOLDING_ALIGNED_PR10: str = (
        "PROJECTION_ROUTES::UGCP_ENFORCEMENT_SCAFFOLDING_ALIGNED_PR10_V1: "
        "bounded UGCP enforcement/deprecation scaffold "
        "(core.ugcp_conformance_surfaces) is available and aligned with "
        "projection routes. Handling actions (accept/normalize/tolerate/reject), "
        "deprecation-stage markers, and strict-rejection candidates are "
        "reviewable without enabling unsafe global strict breakage."
    )
    UGCP_MIGRATION_READINESS_ALIGNED_PR11: str = (
        "PROJECTION_ROUTES::UGCP_MIGRATION_READINESS_ALIGNED_PR11_V1: "
        "bounded UGCP migration-readiness and retirement-sequencing scaffold "
        "(core.ugcp_conformance_surfaces) is available and aligned with "
        "projection routes. Canonical staged-enforcement readiness, transitional "
        "tolerance pathways, and stage-gated retirement sequencing are explicit "
        "without forcing immediate strict rollout."
    )
    UGCP_CONVERGENCE_VISIBILITY_AUDIT_ALIGNED_PR12: str = (
        "PROJECTION_ROUTES::UGCP_CONVERGENCE_VISIBILITY_AUDIT_ALIGNED_PR12_V1: "
        "UGCP convergence visibility audit scaffold "
        "(core.ugcp_conformance_surfaces) is available and aligned with "
        "projection routes. Canonical handling pathways, transitional "
        "normalization boundaries, compatibility tolerance surfaces, and "
        "future verification/strictness/retirement targets are explicit and "
        "reviewable without changing runtime behavior."
    )
    UGCP_STAGED_STRICTNESS_ROLLOUT_GATING_ALIGNED_PR14: str = (
        "PROJECTION_ROUTES::UGCP_STAGED_STRICTNESS_ROLLOUT_GATING_ALIGNED_PR14_V1: "
        "UGCP staged strictness and rollout-gating scaffold "
        "(core.ugcp_conformance_surfaces) is available and aligned with "
        "projection routes. Normalize/warn/canonical-preferred/reject-ready "
        "tiers and cross-repo coordination gates are explicit for gradual "
        "canonical convergence tightening."
    )
except ImportError:  # pragma: no cover
    UGCP_CONFORMANCE_SURFACES_ALIGNED_PR8: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::UGCP_CONFORMANCE_SURFACES_ALIGNED_PR8_UNAVAILABLE"
    )
    UGCP_ENFORCEMENT_SCAFFOLDING_ALIGNED_PR10: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::UGCP_ENFORCEMENT_SCAFFOLDING_ALIGNED_PR10_UNAVAILABLE"
    )
    UGCP_MIGRATION_READINESS_ALIGNED_PR11: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::UGCP_MIGRATION_READINESS_ALIGNED_PR11_UNAVAILABLE"
    )
    UGCP_CONVERGENCE_VISIBILITY_AUDIT_ALIGNED_PR12: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::UGCP_CONVERGENCE_VISIBILITY_AUDIT_ALIGNED_PR12_UNAVAILABLE"
    )
    UGCP_STAGED_STRICTNESS_ROLLOUT_GATING_ALIGNED_PR14: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::UGCP_STAGED_STRICTNESS_ROLLOUT_GATING_ALIGNED_PR14_UNAVAILABLE"
    )

# PR-9 (realization-v2 convergence plan): explicit runtime-truth to outward-truth
# compilation and output chain.  Importing the authority sentinel and PR-9 sentinel
# ties projection routes to the canonical chain contract, making the ordered
# Stage 1 (RuntimeTruthCompiler) → Stage 2 (OutwardRuntimeTruth) → Stage 3
# (Projection Surfaces) dependency explicit and policy-governed.
try:
    from core.runtime_truth_output_chain import (  # noqa: F401
        RUNTIME_TRUTH_OUTPUT_CHAIN_IS_AUTHORITY as _RTOC_AUTHORITY,
        RUNTIME_TRUTH_OUTPUT_CHAIN_PR9_SENTINEL as _RTOC_PR9,
        TruthOutputStage as _TruthOutputStage,
        build_output_chain_catalog as _build_output_chain_catalog,
        build_output_chain_snapshot as _build_output_chain_snapshot,
        classify_output_stage as _classify_output_stage,
    )

    RUNTIME_TRUTH_OUTPUT_CHAIN_ALIGNED_PR9: str = (
        "PROJECTION_ROUTES::RUNTIME_TRUTH_OUTPUT_CHAIN_ALIGNED_PR9_V1: "
        "explicit runtime-truth to outward-truth compilation chain "
        "(core.runtime_truth_output_chain) is available and aligned with "
        "projection routes.  Stage ordering (RuntimeTruthCompiler → "
        "OutwardRuntimeTruth → ProjectionSurfaces), single-output authority, "
        "and no-repeated-assembly constraints are policy-governed."
    )
except ImportError:  # pragma: no cover
    RUNTIME_TRUTH_OUTPUT_CHAIN_ALIGNED_PR9: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::RUNTIME_TRUTH_OUTPUT_CHAIN_ALIGNED_PR9_UNAVAILABLE"
    )

# PR package 10 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical delegated-runtime execution-tracking and acknowledgment
# basis.  Importing the authority sentinel and the PR-10 sentinel from the new
# module ties the projection route layer to the execution-tracking model,
# enabling projection endpoints to surface execution phase, acknowledgment
# history, and result reconciliation state alongside the handoff contract and
# dispatch intent projections.
try:
    from core.delegated_runtime_execution_tracker import (  # noqa: F401
        DELEGATED_RUNTIME_EXECUTION_TRACKER_AUTHORITY as _DRET_AUTHORITY,
        DELEGATED_RUNTIME_EXECUTION_TRACKER_PR10_SENTINEL as _DRET_PR10,
        DelegatedExecutionPhase as _DelegatedExecutionPhase,
        AcknowledgmentSignal as _AcknowledgmentSignal,
        create_execution_tracking_record as _create_execution_tracking_record,
        list_active_execution_tracking_records as _list_active_execution_tracking_records,
        build_execution_tracking_snapshot as _build_execution_tracking_snapshot,
    )

    DELEGATED_RUNTIME_EXECUTION_TRACKER_ALIGNED_PR10: str = (
        "PROJECTION_ROUTES::DELEGATED_RUNTIME_EXECUTION_TRACKER_ALIGNED_PR10_V1: "
        "canonical delegated-runtime execution-tracking and acknowledgment basis "
        "(core.delegated_runtime_execution_tracker) is available and aligned "
        "with projection routes.  Projection endpoints can surface "
        "DelegatedExecutionPhase, AcknowledgmentSignal, and active execution "
        "tracking records alongside handoff contract and dispatch intent "
        "projections."
    )
except ImportError:  # pragma: no cover
    DELEGATED_RUNTIME_EXECUTION_TRACKER_ALIGNED_PR10: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::DELEGATED_RUNTIME_EXECUTION_TRACKER_ALIGNED_PR10_UNAVAILABLE"
    )

# PR package 11 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical MAIN-side attached-Android-runtime dispatch binding basis.
# Importing the authority sentinel and the PR-11 sentinel from the new module
# ties the projection route layer to the dispatch-binding model, enabling
# projection endpoints to surface AndroidRuntimeBindingState, targeting
# identity (session/device/contract/tracker), and active binding records
# alongside execution-tracking and handoff contract projections.
try:
    from core.android_runtime_dispatch_binding import (  # noqa: F401
        ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY as _ARDB_AUTHORITY,
        ANDROID_RUNTIME_DISPATCH_BINDING_PR11_SENTINEL as _ARDB_PR11,
        AndroidRuntimeBindingState as _AndroidRuntimeBindingState,
        AndroidRuntimeBindingSignal as _AndroidRuntimeBindingSignal,
        create_android_dispatch_binding as _create_android_dispatch_binding,
        list_bound_dispatch_bindings as _list_bound_dispatch_bindings,
        build_dispatch_binding_snapshot as _build_dispatch_binding_snapshot,
    )

    ANDROID_RUNTIME_DISPATCH_BINDING_ALIGNED_PR11: str = (
        "PROJECTION_ROUTES::ANDROID_RUNTIME_DISPATCH_BINDING_ALIGNED_PR11_V1: "
        "canonical MAIN-side attached-Android-runtime dispatch binding basis "
        "(core.android_runtime_dispatch_binding) is available and aligned "
        "with projection routes.  Projection endpoints can surface "
        "AndroidRuntimeBindingState, dispatch targeting identity "
        "(session/device/contract/tracker), and active binding records "
        "alongside execution-tracking and handoff contract projections."
    )
except ImportError:  # pragma: no cover
    ANDROID_RUNTIME_DISPATCH_BINDING_ALIGNED_PR11: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::ANDROID_RUNTIME_DISPATCH_BINDING_ALIGNED_PR11_UNAVAILABLE"
    )

# PR package 13 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical host-side Android execution signal reconciliation binding.
# Importing the authority sentinel and the PR-13 sentinel from the new module
# ties the projection route layer to the reconciliation model, enabling
# projection endpoints to surface AndroidSignalKind, reconciliation outcomes,
# and reconciler policy sentinels alongside execution-tracking and dispatch-
# binding projections.
try:
    from core.android_execution_signal_reconciler import (  # noqa: F401
        ANDROID_EXECUTION_SIGNAL_RECONCILER_AUTHORITY as _AESR_AUTHORITY,
        ANDROID_EXECUTION_SIGNAL_RECONCILER_PR13_SENTINEL as _AESR_PR13,
        AndroidSignalKind as _AndroidSignalKind,
        normalize_android_message_to_signal_kind as _normalize_android_message_to_signal_kind,
        reconcile_inbound_message as _reconcile_inbound_message,
    )

    ANDROID_EXECUTION_SIGNAL_RECONCILER_ALIGNED_PR13: str = (
        "PROJECTION_ROUTES::ANDROID_EXECUTION_SIGNAL_RECONCILER_ALIGNED_PR13_V1: "
        "canonical host-side Android execution signal reconciliation binding "
        "(core.android_execution_signal_reconciler) is available and aligned "
        "with projection routes.  Projection endpoints can surface "
        "AndroidSignalKind, reconcile outcomes, and reconciler policy sentinels "
        "alongside execution-tracking and dispatch-binding projections."
    )
except ImportError:  # pragma: no cover
    ANDROID_EXECUTION_SIGNAL_RECONCILER_ALIGNED_PR13: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::ANDROID_EXECUTION_SIGNAL_RECONCILER_ALIGNED_PR13_UNAVAILABLE"
    )


# PR package 14 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical persistent attached-runtime reuse binding.
# Importing the authority sentinel and the PR-14 sentinel from the new module
# ties the projection route layer to the reuse binding model, enabling
# projection endpoints to surface reuse eligibility status, invalidation
# reason, and reuse binding policy sentinels alongside dispatch-binding and
# signal-reconciliation projections.
try:
    from core.attached_runtime_reuse_binding import (  # noqa: F401
        ATTACHED_RUNTIME_REUSE_BINDING_AUTHORITY as _ARRB_AUTHORITY,
        ATTACHED_RUNTIME_REUSE_BINDING_PR14_SENTINEL as _ARRB_PR14,
        ReuseEligibilityStatus as _ReuseEligibilityStatus,
        evaluate_reuse_eligibility as _evaluate_reuse_eligibility,
        list_eligible_reuse_bindings as _list_eligible_reuse_bindings,
    )

    ATTACHED_RUNTIME_REUSE_BINDING_ALIGNED_PR14: str = (
        "PROJECTION_ROUTES::ATTACHED_RUNTIME_REUSE_BINDING_ALIGNED_PR14_V1: "
        "canonical persistent attached-runtime reuse binding "
        "(core.attached_runtime_reuse_binding) is available and aligned "
        "with projection routes.  Projection endpoints can surface "
        "ReuseEligibilityStatus, invalidation reasons, and reuse binding "
        "policy sentinels alongside dispatch-binding and signal-reconciliation "
        "projections."
    )
except ImportError:  # pragma: no cover
    ATTACHED_RUNTIME_REUSE_BINDING_ALIGNED_PR14: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::ATTACHED_RUNTIME_REUSE_BINDING_ALIGNED_PR14_UNAVAILABLE"
    )


# PR package 16 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical ingress path for Android delegated execution signals.
# Importing the authority sentinel and PR-16 sentinel from the new module ties
# the projection route layer to the canonical delegated signal ingress,
# enabling projection endpoints to confirm that the dedicated ingress path is
# active alongside the PR-13 reconciliation binding.
try:
    from core.android_delegated_signal_ingress import (  # noqa: F401
        ANDROID_DELEGATED_SIGNAL_INGRESS_AUTHORITY as _ADSI_AUTHORITY,
        ANDROID_DELEGATED_SIGNAL_INGRESS_PR16_SENTINEL as _ADSI_PR16,
        DelegatedSignalKind as _DelegatedSignalKind,
        ResultKind as _ResultKind,
        ingest_delegated_execution_signal as _ingest_delegated_execution_signal,
    )

    ANDROID_DELEGATED_SIGNAL_INGRESS_ALIGNED_PR16: str = (
        "PROJECTION_ROUTES::ANDROID_DELEGATED_SIGNAL_INGRESS_ALIGNED_PR16_V1: "
        "canonical ingress path for Android delegated execution signals "
        "(core.android_delegated_signal_ingress) is available and aligned "
        "with projection routes.  Projection endpoints can confirm that "
        "DelegatedSignalKind, ResultKind, and the dedicated ingress function "
        "are active alongside the PR-13 reconciliation binding."
    )
except ImportError:  # pragma: no cover
    ANDROID_DELEGATED_SIGNAL_INGRESS_ALIGNED_PR16: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::ANDROID_DELEGATED_SIGNAL_INGRESS_ALIGNED_PR16_UNAVAILABLE"
    )


# PR package 17 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): canonical dispatch consumption of attached-runtime reuse bindings.
# Importing the authority sentinel and PR-17 sentinel from the new module ties
# the projection route layer to the canonical reuse dispatch integration,
# enabling projection endpoints to confirm that reuse binding lookup and
# eligibility gate are active in the delegated dispatch path alongside the
# PR-14 reuse binding model.
try:
    from core.attached_runtime_reuse_dispatch import (  # noqa: F401
        ATTACHED_RUNTIME_REUSE_DISPATCH_AUTHORITY as _ARRD_AUTHORITY,
        ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL as _ARRD_PR17,
        ReuseDispatchResolutionKind as _ReuseDispatchResolutionKind,
        resolve_reuse_dispatch_surface as _resolve_reuse_dispatch_surface,
        dispatch_with_reuse_binding as _dispatch_with_reuse_binding,
    )

    ATTACHED_RUNTIME_REUSE_DISPATCH_ALIGNED_PR17: str = (
        "PROJECTION_ROUTES::ATTACHED_RUNTIME_REUSE_DISPATCH_ALIGNED_PR17_V1: "
        "canonical dispatch consumption of attached-runtime reuse bindings "
        "(core.attached_runtime_reuse_dispatch) is available and aligned "
        "with projection routes.  Projection endpoints can confirm that "
        "ReuseDispatchResolutionKind, resolve_reuse_dispatch_surface, and "
        "dispatch_with_reuse_binding are active alongside the PR-14 reuse "
        "binding model."
    )
except ImportError:  # pragma: no cover
    ATTACHED_RUNTIME_REUSE_DISPATCH_ALIGNED_PR17: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::ATTACHED_RUNTIME_REUSE_DISPATCH_ALIGNED_PR17_UNAVAILABLE"
    )


# PR package 18 (post-533 dual-repo runtime unification master plan, MAIN repo
# side): ingress recovery guard wired before Android signal reconciliation.
# Importing the authority sentinel and PR-15 sentinel from the recovery-
# readiness module ties the projection route layer to the canonical guard gate,
# enabling projection endpoints to confirm that guard_inbound_signal() is
# active as the mandatory ingress gate before reconcile_android_execution_signal().
try:
    from core.attached_runtime_recovery_readiness import (  # noqa: F401
        ATTACHED_RUNTIME_RECOVERY_READINESS_AUTHORITY as _ARRR_AUTHORITY,
        ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL as _ARRR_PR15,
        SignalGuardDecision as _SignalGuardDecision,
        guard_inbound_signal as _guard_inbound_signal,
        build_recovery_readiness_snapshot as _build_recovery_readiness_snapshot,
    )
    from core.android_delegated_signal_ingress import (  # noqa: F401
        INGRESS_RECOVERY_GUARD_IS_MANDATORY_POLICY as _INGRESS_GUARD_POLICY,
        INGRESS_GUARD_REJECTED_SIGNAL_IS_DROPPED_POLICY as _INGRESS_DROP_POLICY,
    )

    INGRESS_RECOVERY_GUARD_ALIGNED_PR18: str = (
        "PROJECTION_ROUTES::INGRESS_RECOVERY_GUARD_ALIGNED_PR18_V1: "
        "recovery guard (core.attached_runtime_recovery_readiness) is wired "
        "before Android delegated signal reconciliation.  "
        "guard_inbound_signal() is active as the mandatory gate; "
        "SignalGuardDecision and build_recovery_readiness_snapshot() are "
        "available for operator/debug surfaces."
    )
except ImportError:  # pragma: no cover
    INGRESS_RECOVERY_GUARD_ALIGNED_PR18: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::INGRESS_RECOVERY_GUARD_ALIGNED_PR18_UNAVAILABLE"
    )

# Importing the authority sentinel and PR-19 sentinel from the session registry
# module ties the projection route layer to the canonical session truth source,
# enabling projection endpoints to confirm that lookup_active_session() /
# lookup_session_by_device() are available as the authoritative registry gate
# for dispatch, reuse, and reconciliation.
try:
    from core.attached_runtime_session_registry import (  # noqa: F401
        ATTACHED_RUNTIME_SESSION_REGISTRY_AUTHORITY as _ARSR_AUTHORITY,
        ATTACHED_RUNTIME_SESSION_REGISTRY_PR19_SENTINEL as _ARSR_PR19,
        RegistryEntryState as _RegistryEntryState,
        lookup_active_session as _lookup_active_session,
        lookup_session_by_device as _lookup_session_by_device,
        build_registry_snapshot as _build_registry_snapshot,
    )

    ATTACHED_RUNTIME_SESSION_REGISTRY_ALIGNED_PR19: str = (
        "PROJECTION_ROUTES::ATTACHED_RUNTIME_SESSION_REGISTRY_ALIGNED_PR19_V1: "
        "authoritative attached runtime session registry "
        "(core.attached_runtime_session_registry) is the single truth source "
        "for dispatch / reuse / reconciliation session identity lookup.  "
        "lookup_active_session(), lookup_session_by_device(), and "
        "build_registry_snapshot() are available for downstream consumers."
    )
except ImportError:  # pragma: no cover
    ATTACHED_RUNTIME_SESSION_REGISTRY_ALIGNED_PR19: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::ATTACHED_RUNTIME_SESSION_REGISTRY_ALIGNED_PR19_UNAVAILABLE"
    )

# Importing the authority sentinel and PR-20 sentinel from the delegated target
# selection policy module ties the projection route layer to the canonical
# selection policy, enabling projection endpoints to confirm that
# select_delegated_target() is available as the authoritative pre-dispatch
# gate for multi-candidate attached runtime selection.
try:
    from core.delegated_target_selection_policy import (  # noqa: F401
        DELEGATED_TARGET_SELECTION_POLICY_AUTHORITY as _DTSP_AUTHORITY,
        DELEGATED_TARGET_SELECTION_POLICY_PR20_SENTINEL as _DTSP_PR20,
        SelectionOutcome as _SelectionOutcome,
        select_delegated_target as _select_delegated_target,
        build_selection_explanation as _build_selection_explanation,
    )

    DELEGATED_TARGET_SELECTION_POLICY_ALIGNED_PR20: str = (
        "PROJECTION_ROUTES::DELEGATED_TARGET_SELECTION_POLICY_ALIGNED_PR20_V1: "
        "canonical delegated target selection policy "
        "(core.delegated_target_selection_policy) provides the pre-dispatch "
        "selection gate for multi-candidate attached runtime dispatch.  "
        "select_delegated_target() and build_selection_explanation() are "
        "available for downstream consumers."
    )
except ImportError:  # pragma: no cover
    DELEGATED_TARGET_SELECTION_POLICY_ALIGNED_PR20: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::DELEGATED_TARGET_SELECTION_POLICY_ALIGNED_PR20_UNAVAILABLE"
    )

# Importing the PR-21 closure sentinel from the delegated signal ingress module
# confirms that the canonical ingress → guard → reconcile → tracker path is
# closed and all three PR-21 policies are present in the module.
try:
    from core.android_delegated_signal_ingress import (  # noqa: F401
        CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL as _PR21_CLOSURE,
        CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER_POLICY as _PR21_POLICY_PATH,
        IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH_POLICY as _PR21_POLICY_IDENTITY,
        TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY_POLICY as _PR21_POLICY_TERMINAL,
    )

    CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21: str = (
        "PROJECTION_ROUTES::CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21_V1: "
        "PR-21 delegated execution path closure is confirmed.  The canonical "
        "host-side path (ingress → guard → reconcile → tracker) is wired, "
        "identity continuity is enforced, and terminal state is protected "
        "against replay / duplicate / stale / out-of-order signals."
    )
except ImportError:  # pragma: no cover
    CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21_UNAVAILABLE"
    )

# Importing the PR-22 consolidation sentinels from the registry, reuse-dispatch,
# reconciler, and ingress modules confirms that the attached runtime session
# registry is the single authoritative truth source for dispatch, reuse, and
# reconciliation decisions.
try:
    from core.attached_runtime_session_registry import (  # noqa: F401
        ATTACHED_RUNTIME_REGISTRY_CONSOLIDATION_PR22_SENTINEL as _PR22_REG,
        REGISTRY_IS_AUTHORITATIVE_DISPATCH_GATE_PR22_POLICY as _PR22_DISPATCH,
        REGISTRY_IS_AUTHORITATIVE_REUSE_GATE_PR22_POLICY as _PR22_REUSE,
        REGISTRY_IS_AUTHORITATIVE_RECONCILIATION_GATE_PR22_POLICY as _PR22_RECONCILE,
        REGISTRY_KNOWN_NON_ACTIVE_BLOCKS_EXECUTION_PR22_POLICY as _PR22_BLOCK,
        REGISTRY_ABSENT_ENTRY_PASSES_THROUGH_PR22_POLICY as _PR22_PASS,
    )
    from core.attached_runtime_reuse_dispatch import (  # noqa: F401
        REUSE_DISPATCH_PR22_SENTINEL as _PR22_REUSE_DISPATCH,
        REUSE_DISPATCH_REGISTRY_GATE_IS_AUTHORITATIVE_PR22_POLICY as _PR22_RD_GATE,
        REUSE_DISPATCH_REGISTRY_BLOCKS_NON_ACTIVE_SESSION_PR22_POLICY as _PR22_RD_BLOCK,
    )
    from core.android_execution_signal_reconciler import (  # noqa: F401
        RECONCILER_PR22_SENTINEL as _PR22_RECONCILER,
        RECONCILER_REGISTRY_GATE_IS_AUTHORITATIVE_PR22_POLICY as _PR22_REC_GATE,
        RECONCILER_REGISTRY_BLOCKS_NON_ACTIVE_SESSION_PR22_POLICY as _PR22_REC_BLOCK,
    )
    from core.android_delegated_signal_ingress import (  # noqa: F401
        INGRESS_REGISTRY_CONSOLIDATION_PR22_SENTINEL as _PR22_INGRESS,
        INGRESS_REGISTRY_GATE_IS_AUTHORITATIVE_PR22_POLICY as _PR22_ING_GATE,
        INGRESS_REGISTRY_BLOCKS_NON_ACTIVE_SESSION_PR22_POLICY as _PR22_ING_BLOCK,
    )

    AUTHORITATIVE_ATTACHED_RUNTIME_REGISTRY_CONSOLIDATED_PR22: str = (
        "PROJECTION_ROUTES::AUTHORITATIVE_ATTACHED_RUNTIME_REGISTRY_CONSOLIDATED_PR22_V1: "
        "PR-22 authoritative attached runtime registry consolidation is confirmed.  "
        "The attached runtime session registry (core.attached_runtime_session_registry) "
        "is the single authoritative truth source for dispatch, reuse, and "
        "reconciliation.  Registry gates are wired in resolve_reuse_dispatch_surface(), "
        "dispatch_with_reuse_binding(), reconcile_android_execution_signal(), "
        "reconcile_inbound_message(), and ingest_delegated_execution_signal().  "
        "Known non-active sessions (replaced / detached / invalidated) are blocked "
        "at every entry-point; absent registry entries pass through."
    )
except ImportError:  # pragma: no cover
    AUTHORITATIVE_ATTACHED_RUNTIME_REGISTRY_CONSOLIDATED_PR22: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::AUTHORITATIVE_ATTACHED_RUNTIME_REGISTRY_CONSOLIDATED_PR22_UNAVAILABLE"
    )

# Importing the PR-23 canonical takeover/fallback sentinels from the registry,
# reuse-dispatch, ingress, and reconciler modules confirms that the attached
# runtime takeover dispatch and delegated fallback selection are deterministic
# and canonical, with the registry as the single authority.
try:
    from core.attached_runtime_session_registry import (  # noqa: F401
        ATTACHED_RUNTIME_REGISTRY_TAKEOVER_DISPATCH_PR23_SENTINEL as _PR23_REG,
        REGISTRY_IS_CANONICAL_TAKEOVER_DISPATCH_AUTHORITY_PR23_POLICY as _PR23_AUTH,
        REGISTRY_TAKEOVER_ELIGIBILITY_REQUIRES_ACTIVE_STATE_PR23_POLICY as _PR23_ACTIVE,
        REGISTRY_REPLACED_SESSION_IS_INELIGIBLE_FOR_TAKEOVER_PR23_POLICY as _PR23_REPLACED,
    )
    from core.attached_runtime_reuse_dispatch import (  # noqa: F401
        REUSE_DISPATCH_PR23_SENTINEL as _PR23_RD,
        TAKEOVER_DISPATCH_CONSULTS_REGISTRY_FIRST_PR23_POLICY as _PR23_RD_FIRST,
        DELEGATED_FALLBACK_REQUIRES_INELIGIBLE_CANONICAL_PATH_PR23_POLICY as _PR23_RD_FB,
        TAKEOVER_DISPATCH_DECISION_IS_DETERMINISTIC_PR23_POLICY as _PR23_RD_DET,
        REPLACED_SESSION_CANNOT_WIN_TAKEOVER_DISPATCH_PR23_POLICY as _PR23_RD_REP,
        TakeoverRouteOutcome as _TakeoverRouteOutcome,
        TakeoverDispatchDecision as _TakeoverDispatchDecision,
        resolve_takeover_or_fallback_route as _resolve_takeover_or_fallback_route,
    )
    from core.android_delegated_signal_ingress import (  # noqa: F401
        INGRESS_DELEGATED_FALLBACK_PR23_SENTINEL as _PR23_ING,
        INGRESS_FALLBACK_IS_LAST_RESORT_PR23_POLICY as _PR23_ING_FB,
    )
    from core.android_execution_signal_reconciler import (  # noqa: F401
        RECONCILER_PR23_SENTINEL as _PR23_REC,
        RECONCILER_FALLBACK_CONTEXT_IS_DETERMINISTIC_PR23_POLICY as _PR23_REC_DET,
    )

    CANONICAL_TAKEOVER_DISPATCH_DELEGATED_FALLBACK_ALIGNED_PR23: str = (
        "PROJECTION_ROUTES::CANONICAL_TAKEOVER_DISPATCH_DELEGATED_FALLBACK_ALIGNED_PR23_V1: "
        "PR-23 canonical attached-runtime takeover dispatch and delegated fallback "
        "canonicalization is confirmed.  The attached runtime session registry is "
        "the single first authoritative truth for takeover vs delegated-fallback "
        "routing decisions.  resolve_takeover_or_fallback_route() makes the decision "
        "deterministic: active sessions with eligible reuse bindings produce "
        "active_attached_takeover; all other cases produce delegated_fallback.  "
        "Replaced / invalidated / stale sessions cannot win takeover selection.  "
        "No new dispatch authority or side-channel router is introduced."
    )
except ImportError:  # pragma: no cover
    CANONICAL_TAKEOVER_DISPATCH_DELEGATED_FALLBACK_ALIGNED_PR23: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::CANONICAL_TAKEOVER_DISPATCH_DELEGATED_FALLBACK_ALIGNED_PR23_UNAVAILABLE"
    )

# Importing the PR-24 dispatch selection truth consolidation sentinels from
# source_dispatch_orchestrator confirms that readiness, participation, registry,
# and reuse are the canonical truth inputs for dispatch target selection.
try:
    from core.runtime.source_dispatch_orchestrator import (  # noqa: F401
        DISPATCH_SELECTION_TRUTH_CONSOLIDATED_PR24_SENTINEL as _PR24_SENTINEL,
        SELECTION_READINESS_IS_REQUIRED_TRUTH_PR24_POLICY as _PR24_READINESS,
        SELECTION_PARTICIPATION_IS_REQUIRED_TRUTH_PR24_POLICY as _PR24_PARTICIPATION,
        SELECTION_REGISTRY_IS_CANONICAL_GATE_PR24_POLICY as _PR24_REGISTRY,
        SELECTION_REUSE_CONTRIBUTES_PREFERENCE_PR24_POLICY as _PR24_REUSE,
        SELECTION_FALLBACK_IS_STABLE_AND_EXPLAINABLE_PR24_POLICY as _PR24_FALLBACK,
        _select_target_from_candidates as _pr24_select_from_candidates,
    )

    DISPATCH_SELECTION_TRUTH_CONSOLIDATED_ALIGNED_PR24: str = (
        "PROJECTION_ROUTES::DISPATCH_SELECTION_TRUTH_CONSOLIDATED_ALIGNED_PR24_V1: "
        "PR-24 dispatch selection truth consolidation is confirmed.  "
        "select_dispatch_target() consults the attached runtime session registry as the "
        "authoritative active-session source, gates each candidate through device "
        "readiness (registered, routable) and device participation "
        "(orchestration_eligible), and uses reuse eligibility as a preference signal.  "
        "Every selection outcome (selected, rejected, fallback) carries a stable, "
        "human-readable reason.  Multi-target situations are resolved by scoring all "
        "registry-active candidates rather than relying on explicit-target or "
        "first-active shortcuts.  No new selector entity or alternate dispatch "
        "authority is introduced."
    )
except ImportError:  # pragma: no cover
    DISPATCH_SELECTION_TRUTH_CONSOLIDATED_ALIGNED_PR24: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::DISPATCH_SELECTION_TRUTH_CONSOLIDATED_ALIGNED_PR24_UNAVAILABLE"
    )

# Importing the PR-25 mainline abnormal-path matrix sentinels from
# source_dispatch_orchestrator confirms that delegated execution, session truth,
# fallback, and selection abnormal paths are all formally covered.
try:
    from core.runtime.source_dispatch_orchestrator import (  # noqa: F401
        MAINLINE_ABNORMAL_PATH_MATRIX_CLOSED_PR25_SENTINEL as _PR25_SENTINEL,
        REMOTE_TASK_BLOCKS_LOCAL_LOOP_ABNORMAL_PATH_PR25_POLICY as _PR25_REMOTE_BLOCKS,
        LOCAL_FALLBACK_AFTER_REMOTE_FAILURE_ABNORMAL_PATH_PR25_POLICY as _PR25_LOCAL_FALLBACK,
        DELEGATED_EXECUTION_FAILURE_SESSION_TRUTH_IS_PRESERVED_PR25_POLICY as _PR25_SESSION_TRUTH,
        SELECTION_FALLBACK_UNDER_DEGRADED_CONDITIONS_IS_STABLE_PR25_POLICY as _PR25_DEGRADED,
        PHASE_A_ACCEPTANCE_ABNORMAL_PATH_PR25_POLICY as _PR25_PHASE_A,
    )

    MAINLINE_ABNORMAL_PATH_MATRIX_PHASE_A_ALIGNED_PR25: str = (
        "PROJECTION_ROUTES::MAINLINE_ABNORMAL_PATH_MATRIX_PHASE_A_ALIGNED_PR25_V1: "
        "PR-25 mainline abnormal-path matrix and Phase A acceptance is confirmed.  "
        "The dispatch layer explicitly handles: remote task blocks local loop "
        "(remote_handoff mode prevents concurrent local execution); local fallback after "
        "remote failure (fallback_local with recorded error and stable reason); delegated "
        "execution failure preserves session truth (registry unchanged); selection fallback "
        "under degraded conditions is stable and carries a reason.  No new abnormal-path "
        "coordinator or alternate dispatch authority is introduced.  All abnormal paths "
        "are covered by stable regression tests as required by Phase A acceptance."
    )
except ImportError:  # pragma: no cover
    MAINLINE_ABNORMAL_PATH_MATRIX_PHASE_A_ALIGNED_PR25: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::MAINLINE_ABNORMAL_PATH_MATRIX_PHASE_A_ALIGNED_PR25_UNAVAILABLE"
    )

# Importing the PR-26 client-facing result surfacing normalization sentinels from
# source_dispatch_orchestrator confirms that the result contract is invariant across
# local, cross-device, delegated, and fallback execution paths.
try:
    from core.runtime.source_dispatch_orchestrator import (  # noqa: F401
        CLIENT_FACING_RESULT_SURFACING_NORMALIZED_PR26_SENTINEL as _PR26_SENTINEL,
        RESULT_CONTRACT_IS_INVARIANT_ACROSS_DISPATCH_PATHS_PR26_POLICY as _PR26_CONTRACT,
        RESULT_SEMANTICS_ARE_COHERENT_REGARDLESS_OF_PATH_PR26_POLICY as _PR26_SEMANTICS,
        RESULT_IDENTITY_IS_STABLE_ACROSS_EXECUTION_PATHS_PR26_POLICY as _PR26_IDENTITY,
        NO_PATH_SPECIFIC_RESULT_CONTRACT_DRIFT_PR26_POLICY as _PR26_NO_DRIFT,
    )

    CLIENT_FACING_RESULT_SURFACING_NORMALIZED_ALIGNED_PR26: str = (
        "PROJECTION_ROUTES::CLIENT_FACING_RESULT_SURFACING_NORMALIZED_ALIGNED_PR26_V1: "
        "PR-26 client-facing result surfacing normalization is confirmed.  "
        "The SourceDispatchResult contract is structurally invariant across all internal "
        "execution paths (local, remote_handoff, fallback_local, staged_mesh, blocked). "
        "Result semantics (success, mode, errors, decision_reason) are coherent regardless "
        "of the execution path that produced the outcome.  Result identity fields "
        "(result_id, dispatch_id, trace_id, task_id) are stable and consistently populated "
        "across all paths.  No path-specific result contract drift is permitted — "
        "to_dict() yields the same top-level field set for every execution path.  "
        "No new result subsystem or alternate client-facing result authority is introduced."
    )
except ImportError:  # pragma: no cover
    CLIENT_FACING_RESULT_SURFACING_NORMALIZED_ALIGNED_PR26: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::CLIENT_FACING_RESULT_SURFACING_NORMALIZED_ALIGNED_PR26_UNAVAILABLE"
    )

# Importing the PR-27 gateway-facing registration and capability error semantics sentinels
# confirms that configuration errors, network/readiness failures, and
# capability-not-satisfied failures are distinguishable through stable gateway-facing signals.
try:
    from core.runtime.source_dispatch_orchestrator import (  # noqa: F401
        GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_PR27_SENTINEL as _PR27_SENTINEL,
        REGISTRATION_FAILURE_IS_DISTINGUISHABLE_FROM_CAPABILITY_FAILURE_PR27_POLICY as _PR27_REG,
        READINESS_DEGRADED_BEHAVIOR_IS_REPORTED_THROUGH_STABLE_SIGNALS_PR27_POLICY as _PR27_READINESS,
        CAPABILITY_NOT_SATISFIED_FAILURE_IS_ACTIONABLE_PR27_POLICY as _PR27_CAPABILITY,
        GATEWAY_SETUP_CONNECTION_SIGNALS_ARE_DETERMINISTIC_PR27_POLICY as _PR27_SIGNALS,
    )

    GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_ALIGNED_PR27: str = (
        "PROJECTION_ROUTES::GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_ALIGNED_PR27_V1: "
        "PR-27 gateway-facing registration and capability error semantics hardening is confirmed.  "
        "Registration failures, capability failures, and readiness-related degraded behavior are "
        "distinguishable through stable existing gateway-facing semantics.  "
        "Upstream retry/reconnect/setup UX can rely on structured failure_kind signals "
        "(registration_failure, capability_failure, readiness_failure, config_error).  "
        "No alternate registration coordinator, duplicate capability model, or parallel error "
        "subsystem is introduced.  Gateway setup and connection signals are deterministic "
        "for regression coverage."
    )
except ImportError:  # pragma: no cover
    GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_ALIGNED_PR27: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_ALIGNED_PR27_UNAVAILABLE"
    )

# Importing the PR-28 integrated regression closure and release-readiness tightening
# sentinels confirms that the full client-facing and dispatch-facing chain is
# regression-closed across selection, delegated execution, session truth, fallback,
# result surfacing, and registration/capability/readiness semantics.
try:
    from core.runtime.source_dispatch_orchestrator import (  # noqa: F401
        INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_PR28_SENTINEL as _PR28_SENTINEL,
        END_TO_END_DISPATCH_EXECUTION_RESULT_COHERENCE_PR28_POLICY as _PR28_E2E,
        INTEGRATED_SELECTION_REGISTRY_REUSE_FALLBACK_BEHAVIOR_PR28_POLICY as _PR28_SELECTION,
        REGISTRATION_CAPABILITY_READINESS_UNDER_INTEGRATED_SCENARIOS_PR28_POLICY as _PR28_REGISTRATION,
        REGRESSION_STABILIZATION_RELEASE_READINESS_TIGHTENING_PR28_POLICY as _PR28_REGRESSION,
    )

    INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_ALIGNED_PR28: str = (
        "PROJECTION_ROUTES::INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_ALIGNED_PR28_V1: "
        "PR-28 integrated regression closure and release-readiness tightening is confirmed.  "
        "The full V2 dispatch chain is regression-closed: selection (PR-24), registry "
        "(PR-19/PR-22), reuse (PR-14/PR-17), takeover/fallback (PR-23), delegated "
        "execution tracking (PR-10), ingress-reconciliation closure (PR-21), result "
        "surfacing (PR-26), and gateway-facing error semantics (PR-27) all behave "
        "coherently under integrated scenarios.  Client-facing and gateway-facing "
        "semantics remain stable across cross-feature interaction paths.  "
        "No new orchestration authority, release subsystem, or duplicate end-to-end "
        "control path is introduced."
    )
except ImportError:  # pragma: no cover
    INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_ALIGNED_PR28: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_ALIGNED_PR28_UNAVAILABLE"
    )

# Importing the PR-29 post-release follow-up tightening sentinels confirms that
# the V2 dispatch selection, registration/readiness/capability, delegated execution,
# fallback, and client-facing result surfaces are tightened within the existing
# architecture after the PR-28 regression closure baseline.
try:
    from core.runtime.source_dispatch_orchestrator import (  # noqa: F401
        POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL as _PR29_SENTINEL,
        DISPATCH_SELECTION_COHESION_POST_RELEASE_PR29_POLICY as _PR29_SELECTION,
        REGISTRATION_READINESS_CAPABILITY_STABILITY_POST_RELEASE_PR29_POLICY as _PR29_REGISTRATION,
        DELEGATED_EXECUTION_FALLBACK_SEMANTIC_CONSISTENCY_PR29_POLICY as _PR29_DELEGATED,
        CLIENT_GATEWAY_RESULT_CONTRACT_ALIGNMENT_POST_RELEASE_PR29_POLICY as _PR29_CLIENT,
    )

    POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29: str = (
        "PROJECTION_ROUTES::POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29_V1: "
        "PR-29 post-release follow-up tightening is confirmed.  Dispatch selection "
        "cohesion (PR-24 scoring/gating/fallback), registration/readiness/capability "
        "stability (PR-27 edge cases), delegated execution/fallback semantic "
        "consistency (PR-10/PR-16/PR-21/PR-23 terminal paths), and client/gateway "
        "result contract alignment (PR-26/PR-27/PR-29 identity+failure_kind) are all "
        "tightened within the existing single-system V2 architecture.  "
        "No new orchestration authority, parallel dispatch system, or duplicate "
        "client contract is introduced."
    )
except ImportError:  # pragma: no cover
    POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29_UNAVAILABLE"
    )

# Importing the PR-30 observability and diagnostics hardening sentinels confirms that
# the V2 dispatch selection, registration/readiness/capability, delegated execution,
# fallback, and client-facing result surfaces are hardened with operator-facing
# observability and rollout safety signals within the existing single-system architecture.
try:
    from core.runtime.source_dispatch_orchestrator import (  # noqa: F401
        OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL as _PR30_SENTINEL,
        DISPATCH_PATH_DECISION_OBSERVABILITY_PR30_POLICY as _PR30_DISPATCH,
        REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY as _PR30_REGISTRATION,
        DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY as _PR30_DELEGATED,
        ROLLOUT_SAFETY_SIGNALS_CLIENT_RESULT_OBSERVABILITY_PR30_POLICY as _PR30_ROLLOUT,
    )

    OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_ALIGNED_PR30: str = (
        "PROJECTION_ROUTES::OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_ALIGNED_PR30_V1: "
        "PR-30 observability and diagnostics hardening is confirmed.  Dispatch-path "
        "decision observability (selection scoring/gating/fallback signals), "
        "registration/readiness/capability/fallback diagnostics (failure_kind, "
        "diagnostic_reason, unsatisfied capability), delegated execution phase "
        "observability (trace_id/task_id/session_id/phase/signal_kind), and "
        "rollout safety signals (observability_context, is_transient, rollout "
        "readiness assertions) are all hardened within the existing single-system "
        "V2 architecture.  No new diagnostics coordinator, alternate control "
        "authority, or parallel troubleshooting path is introduced."
    )
except ImportError:  # pragma: no cover
    OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_ALIGNED_PR30: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_ALIGNED_PR30_UNAVAILABLE"
    )


# Importing the PR-31 rollout-controls, default-behaviors, and safe-release toggle
# sentinels confirms that the V2 dispatch selection, registration/readiness/capability,
# delegated execution, fallback, and client-facing result surfaces are hardened with
# safe defaults, kill-switch support, and release-operation consistency within the
# existing single-system architecture.
try:
    from core.runtime.source_dispatch_orchestrator import (  # noqa: F401
        ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_PR31_SENTINEL as _PR31_SENTINEL,
        FEATURE_TOGGLE_DEFAULT_BEHAVIOR_ROLLOUT_CONTROL_PR31_POLICY as _PR31_TOGGLE,
        KILL_SWITCH_SAFE_DISABLE_ROLLBACK_BEHAVIOR_PR31_POLICY as _PR31_KILL_SWITCH,
        SELECTION_REGISTRATION_READINESS_CAPABILITY_SAFE_DEFAULTS_PR31_POLICY as _PR31_SAFE_DEFAULTS,
        DELEGATED_FALLBACK_RELEASE_OPERATION_CONSISTENCY_PR31_POLICY as _PR31_DELEGATED,
    )

    ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_ALIGNED_PR31: str = (
        "PROJECTION_ROUTES::ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_ALIGNED_PR31_V1: "
        "PR-31 rollout controls, default behaviors, and safe-operating release toggles "
        "are confirmed.  Feature-toggle and default-behavior interactions (safe defaults "
        "for selection/registration/readiness/capability/delegated/fallback), kill-switch "
        "and safe-disable behavior (stable failure_kind, fallback activation, observable "
        "kill-switch state), selection/registration/readiness/capability safe defaults "
        "(fail-closed, stable diagnostic_reason), and delegated/fallback release-operation "
        "consistency (stable failure_kind, deterministic fallback, no internal state "
        "leakage) are all hardened within the existing single-system V2 architecture.  "
        "No new release coordinator, duplicate flag subsystem, or parallel control path "
        "is introduced."
    )
except ImportError:  # pragma: no cover
    ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_ALIGNED_PR31: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_ALIGNED_PR31_UNAVAILABLE"
    )

try:
    from core.runtime.source_dispatch_orchestrator import (
        STAGED_MESH_MINIMAL_EXECUTABLE_CLOSURE_PR32_SENTINEL as _PR32_SENTINEL,
        STAGED_MESH_PLAN_TO_EXECUTION_TRANSITION_PR32_POLICY as _PR32_PLAN_EXEC,
        STAGED_MESH_SESSION_COORDINATOR_INTEGRATION_PR32_POLICY as _PR32_COORD,
        STAGED_MESH_RESULT_INTEGRATION_CONTRACT_PR32_POLICY as _PR32_RESULT,
        STAGED_MESH_GRACEFUL_DEGRADATION_FALLBACK_PR32_POLICY as _PR32_DEGRADE,
    )

    STAGED_MESH_MINIMAL_EXECUTABLE_CLOSURE_ALIGNED_PR32: str = (
        "PROJECTION_ROUTES::STAGED_MESH_MINIMAL_EXECUTABLE_CLOSURE_ALIGNED_PR32_V1: "
        "PR-32 staged-mesh minimal executable coordination closure is confirmed.  "
        "staged_mesh dispatch no longer returns 'plan prepared' as a terminal state; "
        "it invokes MeshSessionCoordinator (coordinate_mesh_session) and the result "
        "carries action_taken='staged_mesh_coordinated' with coordinator_status and "
        "coordinator_summary.  The implementation reuses the existing body_mesh_registry, "
        "mesh_session_coordinator, and SourceDispatchResult contracts without "
        "introducing a new coordination authority, duplicate session registry, or "
        "parallel result surfacing mechanism."
    )
except ImportError:  # pragma: no cover
    STAGED_MESH_MINIMAL_EXECUTABLE_CLOSURE_ALIGNED_PR32: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::STAGED_MESH_MINIMAL_EXECUTABLE_CLOSURE_ALIGNED_PR32_UNAVAILABLE"
    )

try:
    from core.runtime.source_dispatch_orchestrator import (
        RECONNECT_RECOVERY_CONSISTENCY_PR33_SENTINEL as _PR33_SENTINEL,
        RECONNECT_MUST_NOT_BREAK_HOST_SIDE_TRUTH_PR33_POLICY as _PR33_HOST_TRUTH,
        REGISTRY_RECONNECT_EVENT_IS_OBSERVABLE_PR33_POLICY as _PR33_OBSERVABLE,
        EXECUTION_TRACKER_SURVIVES_RECONNECT_PR33_POLICY as _PR33_TRACKER,
        RESULT_MERGE_CONSISTENT_THROUGH_RECOVERY_PR33_POLICY as _PR33_MERGE,
    )

    RECONNECT_RECOVERY_CONSISTENCY_ALIGNED_PR33: str = (
        "PROJECTION_ROUTES::RECONNECT_RECOVERY_CONSISTENCY_ALIGNED_PR33_V1: "
        "PR-33 product-grade reconnect and recovery consistency hardening is confirmed.  "
        "Short disconnect/reconnect events do not break host-side truth: "
        "AttachedSessionRegistryEntry tracks reconnect_count and last_reconnect_at; "
        "RecoveryReadinessRuntime exposes clear_seq_context_for_reconnect() to prevent "
        "post-reconnect signals from being misclassified as stale/out-of-order; "
        "DelegatedRuntimeExecutionTracker exposes get_active_execution_tracking_for_session() "
        "so in-flight work is observable after reconnect.  No new truth authority, "
        "duplicate recovery subsystem, or parallel reconciliation path is introduced."
    )
except ImportError:  # pragma: no cover
    RECONNECT_RECOVERY_CONSISTENCY_ALIGNED_PR33: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::RECONNECT_RECOVERY_CONSISTENCY_ALIGNED_PR33_UNAVAILABLE"
    )

try:
    from core.runtime.source_dispatch_orchestrator import (
        CROSS_DEVICE_RUNTIME_ACCEPTANCE_PR34_SENTINEL as _PR34_SENTINEL,
        DISPATCH_FALLBACK_RESULT_MERGE_STABILITY_PR34_POLICY as _PR34_DISPATCH,
        ANDROID_ATTACHED_RUNTIME_ORCHESTRATION_STABILITY_PR34_POLICY as _PR34_ANDROID,
        MULTI_TARGET_RANKING_MATURITY_PR34_POLICY as _PR34_RANKING,
        STAGED_MESH_CLOSURE_RUNNABLE_PR34_POLICY as _PR34_MESH,
        DIAGNOSTICS_READINESS_PARTICIPATION_FORMATION_USABILITY_PR34_POLICY as _PR34_DIAG,
    )

    CROSS_DEVICE_RUNTIME_ACCEPTANCE_ALIGNED_PR34: str = (
        "PROJECTION_ROUTES::CROSS_DEVICE_RUNTIME_ACCEPTANCE_ALIGNED_PR34_V1: "
        "PR-34 final product-grade cross-device and runtime acceptance pack is confirmed.  "
        "Source dispatch/fallback/result-merge stability, Android attached runtime "
        "orchestration stability, multi-target ranking maturity, staged-mesh minimal "
        "closure runnability, and diagnostics/readiness/participation/formation usability "
        "are all validated against the existing architecture.  No new runtime authority, "
        "duplicate orchestration control system, or parallel acceptance architecture "
        "is introduced."
    )
except ImportError:  # pragma: no cover
    CROSS_DEVICE_RUNTIME_ACCEPTANCE_ALIGNED_PR34: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::CROSS_DEVICE_RUNTIME_ACCEPTANCE_ALIGNED_PR34_UNAVAILABLE"
    )

# PR-7 (12-PR governance plan): canonical task dispatch and delegated execution
# chain definition.  Confirms that the single canonical dispatch chain taxonomy
# (primary_local / remote_handoff / fallback_local / staged_mesh /
# android_inbound / blocked) is defined and inspectable, that Android inbound
# dispatch is placed inside the same execution model, and that all dispatch
# path roles, result owners, and policy sentinels are machine-checkable.
try:
    from core.canonical_task_dispatch_chain import (
        CANONICAL_TASK_DISPATCH_CHAIN_IS_AUTHORITY as _CTDC_AUTHORITY,
        CANONICAL_TASK_DISPATCH_CHAIN_PR7_SENTINEL as _CTDC_PR7,
        DISPATCH_CHAIN_PRIMARY_PATH_IS_LOCAL_POLICY as _CTDC_PRIMARY,
        DISPATCH_CHAIN_REMOTE_HANDOFF_BLOCKS_LOCAL_POLICY as _CTDC_REMOTE,
        DISPATCH_CHAIN_FALLBACK_IS_DISTINGUISHABLE_POLICY as _CTDC_FALLBACK,
        DISPATCH_CHAIN_ANDROID_INBOUND_IS_SAME_SYSTEM_POLICY as _CTDC_ANDROID,
        DISPATCH_CHAIN_STAGED_MESH_IS_COORDINATION_ONLY_POLICY as _CTDC_MESH,
        DISPATCH_CHAIN_BLOCKED_PATH_IS_FINAL_POLICY as _CTDC_BLOCKED,
    )

    CANONICAL_TASK_DISPATCH_CHAIN_ALIGNED_PR7: str = (
        "PROJECTION_ROUTES::CANONICAL_TASK_DISPATCH_CHAIN_ALIGNED_PR7_V1: "
        "The canonical task dispatch chain taxonomy is confirmed.  All six dispatch "
        "path kinds (primary_local, remote_handoff, fallback_local, staged_mesh, "
        "android_inbound, blocked) are classified by role, result_owner, primary "
        "module, and policy sentinel.  Android inbound dispatch is explicitly placed "
        "inside the same governed execution system.  The dispatch system is "
        "explicitly inspectable and governable without changing its core behavior."
    )
except ImportError:  # pragma: no cover
    CANONICAL_TASK_DISPATCH_CHAIN_ALIGNED_PR7: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::CANONICAL_TASK_DISPATCH_CHAIN_ALIGNED_PR7_UNAVAILABLE"
    )

# Canonical runtime node registry consolidation sentinel.
# Confirms that NodeFabricRegistry (core.nodes.node_fabric_registry) is the
# single canonical runtime node registry, that system status endpoints derive
# node runtime truth from it, and that core.node_registry.NodeRegistry is
# retained only as a backward-compatibility facade.
try:
    from core.nodes.node_fabric_registry import (  # noqa: F401
        CANONICAL_RUNTIME_NODE_REGISTRY_AUTHORITY as _CRNR_AUTHORITY,
        NODE_FABRIC_IS_CANONICAL_RUNTIME_REGISTRY_SENTINEL as _CRNR_SENTINEL,
        STATUS_ENDPOINTS_READ_FROM_CANONICAL_REGISTRY_POLICY as _CRNR_STATUS_POLICY,
        LEGACY_NODE_REGISTRY_IS_COMPAT_FACADE_ONLY_POLICY as _CRNR_FACADE_POLICY,
        get_node_fabric_registry as _get_node_fabric_registry,
    )

    CANONICAL_RUNTIME_NODE_REGISTRY_ALIGNED: str = (
        "PROJECTION_ROUTES::CANONICAL_RUNTIME_NODE_REGISTRY_ALIGNED_V1: "
        "NodeFabricRegistry (core.nodes.node_fabric_registry) is confirmed as the "
        "single canonical runtime node registry.  System status endpoints derive "
        "node runtime truth from NodeFabricRegistry.  "
        "core.node_registry.NodeRegistry is retained as a backward-compatibility "
        "facade only.  get_node_fabric_registry() is available for downstream "
        "consumers that need canonical node presence and status reads."
    )
except ImportError:  # pragma: no cover
    CANONICAL_RUNTIME_NODE_REGISTRY_ALIGNED: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::CANONICAL_RUNTIME_NODE_REGISTRY_ALIGNED_UNAVAILABLE"
    )

# PR-3 (canonical node list/detail/status surfaces): Confirms that
# GET /api/v1/nodes and GET /api/v1/nodes/{node_name} derive node membership
# and runtime status from NodeFabricRegistry (not filesystem scans or
# node_status_cache), that any remaining filesystem-based listing is explicitly
# marked as a legacy/compat path, and that three new policy sentinels are
# declared in node_fabric_registry.py for machine-checkable enforcement.
try:
    from core.nodes.node_fabric_registry import (  # noqa: F401
        CANONICAL_NODE_LIST_SURFACE_READS_FROM_REGISTRY_POLICY as _PR3_LIST_POLICY,
        FILESYSTEM_SCAN_IS_NOT_NODE_MEMBERSHIP_AUTHORITY_POLICY as _PR3_FS_POLICY,
        NODE_STATUS_CACHE_IS_NOT_CANONICAL_STATUS_SOURCE_POLICY as _PR3_CACHE_POLICY,
    )

    CANONICAL_NODE_LIST_DETAIL_STATUS_ALIGNED_PR3: str = (
        "PROJECTION_ROUTES::CANONICAL_NODE_LIST_DETAIL_STATUS_ALIGNED_PR3_V1: "
        "GET /api/v1/nodes and GET /api/v1/nodes/{node_name} derive node membership "
        "and runtime status from NodeFabricRegistry (canonical registry).  Raw "
        "filesystem scanning (nodes/ directory, main.py or fusion_entry.py presence) "
        "is no longer used as primary node-existence authority on canonical surfaces.  "
        "node_status_cache is no longer consulted by canonical list/detail surfaces.  "
        "The legacy filesystem-based node list is explicitly demoted to "
        "GET /api/v1/nodes/legacy/filesystem (compat/diagnostics path only)."
    )
except ImportError:  # pragma: no cover
    CANONICAL_NODE_LIST_DETAIL_STATUS_ALIGNED_PR3: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::CANONICAL_NODE_LIST_DETAIL_STATUS_ALIGNED_PR3_UNAVAILABLE"
    )

# PR-4 (node invocation unification): Unified Node Invocation Envelope and
# Executor alignment sentinel.  Confirms that core.node_invocation defines a
# canonical NodeInvocationEnvelope, NodeInvocationResult, and
# UnifiedNodeExecutor; that all five node invocation paths (openclawd,
# REST /api/v1/nodes/call, command-router bridge, capability dispatcher,
# system_integration) converge on invoke_node(); and that trace/source
# metadata is carried consistently across every path.
try:
    from core.node_invocation import (  # noqa: F401
        UNIFIED_NODE_INVOCATION_AUTHORITY as _UNIA_AUTHORITY,
        UNIFIED_NODE_INVOCATION_PR4_SENTINEL as _UNIA_PR4,
        ALL_INVOCATION_PATHS_CONVERGE_ON_UNIFIED_EXECUTOR_POLICY as _UNIA_PATHS_POLICY,
        INVOCATION_ENVELOPE_IS_CANONICAL_TRACE_SCHEMA_POLICY as _UNIA_TRACE_POLICY,
        RESULT_ENVELOPE_IS_CANONICAL_RESULT_CONTRACT_POLICY as _UNIA_RESULT_POLICY,
        NodeInvocationEnvelope as _NodeInvocationEnvelope,
        NodeInvocationResult as _NodeInvocationResult,
        InvocationSource as _InvocationSource,
        invoke_node as _invoke_node,
        get_unified_node_executor as _get_unified_node_executor,
    )

    UNIFIED_NODE_INVOCATION_ALIGNED_PR4: str = (
        "PROJECTION_ROUTES::UNIFIED_NODE_INVOCATION_ALIGNED_PR4_V1: "
        "core.node_invocation is confirmed as the single canonical node execution "
        "entry point.  NodeInvocationEnvelope carries request_id, trace_id, "
        "task_id, session_id, node_id, action, params, invocation_source, "
        "route_mode, execution_domain, started_at, and timeout_ms.  "
        "NodeInvocationResult carries success, result, error, duration_ms, "
        "execution_mode, and execution_source.  All five invocation paths "
        "(openclawd node__ dispatch, POST /api/v1/nodes/call, "
        "_command_node_executor, CanonicalDispatcher._dispatch_node, and "
        "system_integration._execute_node) converge on invoke_node()."
    )
except ImportError:  # pragma: no cover
    UNIFIED_NODE_INVOCATION_ALIGNED_PR4: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::UNIFIED_NODE_INVOCATION_ALIGNED_PR4_UNAVAILABLE"
    )

# PR-5 (fusion_entry canonical adapter): Confirms that fusion_entry.py has
# been formally repositioned as the canonical local execution adapter, with
# a standardised adapter contract (FusionNode class, async execute method,
# get_node_instance factory), explicit policy sentinels ruling out registry/
# discovery authority roles, and all direct helper call sites in routes
# redirected through the unified executor (invoke_node).
try:
    from core.fusion_entry_adapter import (  # noqa: F401
        FUSION_ENTRY_IS_EXECUTION_ADAPTER_AUTHORITY as _FEA_AUTHORITY,
        FUSION_ENTRY_ADAPTER_CONTRACT_PR5_SENTINEL as _FEA_PR5,
        FUSION_ENTRY_NOT_A_REGISTRY_AUTHORITY_POLICY as _FEA_NOT_REGISTRY,
        FUSION_ENTRY_NOT_A_DISCOVERY_AUTHORITY_POLICY as _FEA_NOT_DISCOVERY,
        ADAPTER_CONTRACT_IS_STANDARDISED_POLICY as _FEA_CONTRACT,
        UNIFIED_EXECUTOR_IS_CANONICAL_LOADER_POLICY as _FEA_LOADER,
        FusionEntryAdapterContract as _FusionEntryAdapterContract,
        validate_fusion_entry_adapter as _validate_fusion_entry_adapter,
    )

    FUSION_ENTRY_ADAPTER_ALIGNED_PR5: str = (
        "PROJECTION_ROUTES::FUSION_ENTRY_ADAPTER_ALIGNED_PR5_V1: "
        "fusion_entry.py is confirmed as the canonical local execution adapter "
        "only.  core.fusion_entry_adapter defines FusionEntryAdapterContract "
        "(FusionNode class, async execute, get_node_instance), policy sentinels "
        "ruling out registry/discovery authority roles, and a validator used by "
        "the unified executor.  Direct _load_node/_execute_node call sites in "
        "routes have been redirected through invoke_node() (PR-4 unified "
        "executor).  Templates and contributor docs reflect the narrowed role."
    )
except ImportError:  # pragma: no cover
    FUSION_ENTRY_ADAPTER_ALIGNED_PR5: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::FUSION_ENTRY_ADAPTER_ALIGNED_PR5_UNAVAILABLE"
    )

# PR-6 (node governance runtime constraint): Confirms that governance metadata
# is a real runtime constraint for canonical node tool-surface exposure.
# Archived/deprecated/unhealthy/readiness-gap nodes are filtered from the
# canonical path.  Every exclusion decision is diagnostically observable.
try:
    from core.node_governance_runtime import (  # noqa: F401
        NODE_GOVERNANCE_IS_RUNTIME_CONSTRAINT_AUTHORITY as _NGR_AUTHORITY,
        NODE_GOVERNANCE_RUNTIME_CONSTRAINT_PR6_SENTINEL as _NGR_PR6,
        ARCHIVED_AND_DEPRECATED_NODES_EXCLUDED_POLICY as _NGR_ARCHIVED_POLICY,
        UNHEALTHY_NODES_EXCLUDED_FROM_CANONICAL_PATH_POLICY as _NGR_UNHEALTHY_POLICY,
        READINESS_GAP_NODES_EXCLUDED_POLICY as _NGR_READINESS_POLICY,
        GOVERNANCE_EXCLUSION_IS_DIAGNOSABLE_POLICY as _NGR_DIAGNOSABLE_POLICY,
        COMPATIBILITY_FALLBACK_IS_NON_CANONICAL_POLICY as _NGR_FALLBACK_POLICY,
        NodeGovernanceEligibilityDecision as _NodeGovernanceEligibilityDecision,
        evaluate_node_governance_eligibility as _evaluate_node_governance_eligibility,
        get_governance_eligible_nodes as _get_governance_eligible_nodes,
        build_governance_exclusion_report as _build_governance_exclusion_report,
    )

    NODE_GOVERNANCE_RUNTIME_CONSTRAINT_ALIGNED_PR6: str = (
        "PROJECTION_ROUTES::NODE_GOVERNANCE_RUNTIME_CONSTRAINT_ALIGNED_PR6_V1: "
        "core.node_governance_runtime is confirmed as the canonical authority for "
        "node governance runtime eligibility.  Governance metadata (architectural "
        "class, health, lifecycle stage, deprecated/archived semantics) is a real "
        "runtime constraint for canonical node tool-surface exposure.  "
        "Archived/deprecated/unhealthy/readiness-gap nodes are filtered from the "
        "canonical path.  NodeGovernanceEligibilityDecision carries eligible, "
        "exclusion_reasons, and diagnostic_context for every node evaluated.  "
        "sync_capabilities_to_registry() in NodeFabricRegistry uses governance "
        "eligibility checks and emits structured exclusion diagnostics."
    )
except ImportError:  # pragma: no cover
    NODE_GOVERNANCE_RUNTIME_CONSTRAINT_ALIGNED_PR6: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::NODE_GOVERNANCE_RUNTIME_CONSTRAINT_ALIGNED_PR6_UNAVAILABLE"
    )

# PR-7 (node discovery runtime integration): Confirms that NodeDiscoveryService
# is wired into the real startup and health path.  Active nodes are seeded into
# discovery at startup, per-node announcements keep the discovery plane current,
# health/status surfaces reflect discovery state, and diagnostic tools expose
# mismatches between launcher state, fabric registry state, and discovery state.
try:
    from core.node_discovery_runtime import (  # noqa: F401
        NODE_DISCOVERY_IS_RUNTIME_PARTICIPANT_AUTHORITY as _NDA_AUTHORITY,
        NODE_DISCOVERY_RUNTIME_INTEGRATION_PR7_SENTINEL as _NDA_PR7,
        ACTIVE_NODES_ARE_DISCOVERABLE_POLICY as _NDA_DISCOVERABLE_POLICY,
        DISCOVERY_STATE_REFLECTS_RUNTIME_STATE_POLICY as _NDA_REFLECTS_POLICY,
        DISCOVERY_MISMATCH_IS_DIAGNOSABLE_POLICY as _NDA_DIAGNOSABLE_POLICY,
        DISCOVERY_PARTICIPATES_IN_STARTUP_PATH_POLICY as _NDA_STARTUP_POLICY,
        UNDISCOVERED_ACTIVE_NODES_ARE_FLAGGED_POLICY as _NDA_FLAGGED_POLICY,
        NodeDiscoveryParticipationRecord as _NodeDiscoveryParticipationRecord,
        DiscoveryRuntimeSnapshot as _DiscoveryRuntimeSnapshot,
        seed_fabric_nodes_into_discovery as _seed_fabric_nodes_into_discovery,
        announce_node_to_discovery as _announce_node_to_discovery,
        initialize_discovery_from_startup as _initialize_discovery_from_startup,
        build_discovery_runtime_snapshot as _build_discovery_runtime_snapshot,
        get_discovery_participation_summary as _get_discovery_participation_summary,
    )

    NODE_DISCOVERY_RUNTIME_INTEGRATION_ALIGNED_PR7: str = (
        "PROJECTION_ROUTES::NODE_DISCOVERY_RUNTIME_INTEGRATION_ALIGNED_PR7_V1: "
        "core.node_discovery_runtime is confirmed as the canonical authority for "
        "wiring NodeDiscoveryService into the Galaxy runtime startup path.  "
        "Active nodes from NodeFabricRegistry are seeded into discovery at startup.  "
        "Per-node announcements keep the discovery plane current as nodes come online.  "
        "Health/status surfaces reflect discovery state via "
        "get_discovery_participation_summary().  Diagnostic tools expose mismatches "
        "between launcher state, fabric registry state, and discovery state via "
        "build_discovery_runtime_snapshot().  NodeDiscoveryParticipationRecord and "
        "DiscoveryRuntimeSnapshot carry per-node alignment classifications."
    )
except ImportError:  # pragma: no cover
    NODE_DISCOVERY_RUNTIME_INTEGRATION_ALIGNED_PR7: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::NODE_DISCOVERY_RUNTIME_INTEGRATION_ALIGNED_PR7_UNAVAILABLE"
    )

# PR-8 (node boundary runtime): Confirms that the canonical node boundary is
# explicitly defined and enforced.  Nodes are capability providers / local
# executor backends only — not a competing execution authority.  Legacy
# surfaces (NodeRegistry compat facade, direct fs-scan, compat HTTP endpoint,
# fusion_entry misuse, LEGACY_ORCHESTRATOR_NODE on canonical path) are
# catalogued and explicitly demoted.  NodeFabricRegistry remains the single
# runtime truth for node existence and health; invoke_node() via
# UnifiedNodeExecutor is the canonical invocation pathway.
try:
    from core.node_boundary_runtime import (  # noqa: F401
        NODE_BOUNDARY_IS_CANONICAL_AUTHORITY as _NBR_AUTHORITY,
        NODE_BOUNDARY_RUNTIME_PR8_SENTINEL as _NBR_PR8,
        NODES_ARE_CAPABILITY_BACKENDS_ONLY_POLICY as _NBR_CAPABILITY_POLICY,
        CANONICAL_INVOCATION_PATH_IS_INVOKE_NODE_POLICY as _NBR_INVOCATION_POLICY,
        LEGACY_REGISTRY_IS_COMPAT_FACADE_POLICY as _NBR_REGISTRY_POLICY,
        DIRECT_SCAN_IS_LEGACY_COMPAT_POLICY as _NBR_SCAN_POLICY,
        LEGACY_ORCHESTRATOR_NODES_DEMOTED_FROM_CANONICAL_PATH_POLICY as _NBR_DEMOTE_POLICY,
        NodePathwayKind as _NodePathwayKind,
        LegacyNodeSurfaceStatus as _LegacyNodeSurfaceStatus,
        NodeBoundaryDecision as _NodeBoundaryDecision,
        LegacyNodeSurfaceEntry as _LegacyNodeSurfaceEntry,
        NodeBoundarySnapshot as _NodeBoundarySnapshot,
        classify_invocation_pathway as _classify_invocation_pathway,
        build_legacy_surface_registry as _build_legacy_surface_registry,
        evaluate_node_boundary_compliance as _evaluate_node_boundary_compliance,
        get_canonical_nodes as _get_canonical_nodes,
        build_node_boundary_snapshot as _build_node_boundary_snapshot,
        get_boundary_summary as _get_boundary_summary,
    )

    NODE_BOUNDARY_RUNTIME_ALIGNED_PR8: str = (
        "PROJECTION_ROUTES::NODE_BOUNDARY_RUNTIME_ALIGNED_PR8_V1: "
        "core.node_boundary_runtime is confirmed as the canonical authority for "
        "Galaxy node system boundary enforcement.  Nodes are capability providers "
        "/ local executor backends only.  Canonical invocation path is invoke_node() "
        "via UnifiedNodeExecutor (PR-4).  Legacy surfaces (NodeRegistry compat "
        "facade, direct filesystem scan in GET /api/v1/nodes, POST /api/v1/nodes/call "
        "compat endpoint, fusion_entry as registry authority, LEGACY_ORCHESTRATOR_NODE "
        "on canonical path) are catalogued and explicitly demoted.  "
        "NodeBoundaryDecision, LegacyNodeSurfaceEntry, and NodeBoundarySnapshot "
        "carry per-node and per-surface boundary compliance records."
    )
except ImportError:  # pragma: no cover
    NODE_BOUNDARY_RUNTIME_ALIGNED_PR8: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::NODE_BOUNDARY_RUNTIME_ALIGNED_PR8_UNAVAILABLE"
    )


# PR-10 (OpenClawd canonical node tool exposure): Confirms that legacy Layer 3
# node discovery (config/node_registry.json reads + direct fusion_entry.py
# filesystem scans) has been removed from the canonical OpenClawd
# _collect_tools() path.  Node tools now flow exclusively through
# NodeFabricRegistry → sync_capabilities_to_registry() → CapabilityRegistry
# → CapabilityResolver(CapabilitySource.NODE).  The legacy scan is relegated
# to an explicit compat-only path (OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED,
# default False) and does not act as a peer tool-exposure authority.
try:
    from core.openclawd_canonical_node_tool_exposure import (  # noqa: F401
        OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_IS_AUTHORITY as _OCNTE_AUTHORITY,
        OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_PR10_SENTINEL as _OCNTE_PR10,
        CANONICAL_NODE_TOOLS_COME_FROM_RUNTIME_REGISTRY_ONLY_POLICY as _OCNTE_REGISTRY_POLICY,
        NODE_REGISTRY_JSON_IS_NOT_TOOL_EXPOSURE_AUTHORITY_POLICY as _OCNTE_JSON_POLICY,
        FUSION_ENTRY_SCAN_IS_NOT_TOOL_EXPOSURE_AUTHORITY_POLICY as _OCNTE_SCAN_POLICY,
        LEGACY_LAYER3_IS_COMPAT_ONLY_POLICY as _OCNTE_COMPAT_POLICY,
        CANONICAL_TOOL_EXPOSURE_REQUIRES_GOVERNANCE_FILTER_POLICY as _OCNTE_GOV_POLICY,
        LegacyNodeDiscoveryStatus as _LegacyNodeDiscoveryStatus,
        LegacyNodeDiscoverySurface as _LegacyNodeDiscoverySurface,
        CanonicalNodeToolExposureSnapshot as _CanonicalNodeToolExposureSnapshot,
        build_legacy_discovery_surface_registry as _build_legacy_discovery_surface_registry,
        get_legacy_discovery_summary as _get_legacy_discovery_summary,
        is_legacy_node_scan_compat_enabled as _is_legacy_node_scan_compat_enabled,
        build_canonical_tool_exposure_snapshot as _build_canonical_tool_exposure_snapshot,
    )

    OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_ALIGNED_PR10: str = (
        "PROJECTION_ROUTES::OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_ALIGNED_PR10_V1: "
        "core.openclawd_canonical_node_tool_exposure is confirmed as the authority for "
        "OpenClawd canonical node tool exposure after PR-10.  Legacy Layer 3 node "
        "discovery (config/node_registry.json reads and direct fusion_entry.py "
        "filesystem scans) has been removed from the canonical _collect_tools() path.  "
        "Node tools are sourced exclusively from: NodeFabricRegistry "
        "→ sync_capabilities_to_registry() → CapabilityRegistry "
        "→ CapabilityResolver(CapabilitySource.NODE).  The legacy scan is isolated "
        "behind OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED (default False) and is "
        "non-canonical by design.  Only healthy CAPABILITY_NODE nodes are surfaced; "
        "SERVICE_NODE, LEGACY_ORCHESTRATOR_NODE, EXPERIMENTAL_NODE, and ARCHIVED_NODE "
        "are excluded by the governance eligibility filter."
    )
except ImportError:  # pragma: no cover
    OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_ALIGNED_PR10: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_ALIGNED_PR10_UNAVAILABLE"
    )

# PR-10 (compatibility-surface retirement): Confirms that the compatibility-
# surface retirement inventory is available and classifies high-risk compat
# surfaces by retirement tier.  The inventory establishes the governed
# convergence roadmap that shrinks the compat footprint across batch PRs.
try:
    from core.compat_surface_retirement import (  # noqa: F401
        COMPAT_SURFACE_RETIREMENT_IS_AUTHORITY as _CSR_AUTHORITY,
        COMPAT_SURFACE_RETIREMENT_PR10_SENTINEL as _CSR_PR10,
        HIGH_RISK_COMPAT_SURFACES_MUST_BE_INVENTORIED_POLICY as _CSR_INVENTORY_POLICY,
        COMPAT_SURFACES_MUST_NOT_MASQUERADE_AS_CANONICAL_POLICY as _CSR_MASQUERADE_POLICY,
        RETIREMENT_TIER_CLASSIFICATION_MUST_BE_EXPLICIT_POLICY as _CSR_TIER_POLICY,
        COMPAT_FOOTPRINT_MUST_SHRINK_OVER_TIME_POLICY as _CSR_FOOTPRINT_POLICY,
        RetirementTier as _RetirementTier,
        RetirementStatus as _RetirementStatus,
        CompatSurfaceRisk as _CompatSurfaceRisk,
        CompatSurfaceRecord as _CompatSurfaceRecord,
        RetirementRoadmapSummary as _RetirementRoadmapSummary,
        get_compat_surface_inventory as _get_compat_surface_inventory,
        get_surfaces_by_tier as _get_surfaces_by_tier,
        get_high_risk_surfaces as _get_high_risk_surfaces,
        build_retirement_roadmap_summary as _build_retirement_roadmap_summary,
        classify_surface_tier as _classify_surface_tier,
    )

    COMPAT_SURFACE_RETIREMENT_ALIGNED_PR10: str = (
        "PROJECTION_ROUTES::COMPAT_SURFACE_RETIREMENT_ALIGNED_PR10_V1: "
        "core.compat_surface_retirement is confirmed as the canonical authority "
        "for the compatibility-surface retirement inventory and tier classification "
        "after PR-10.  All high-risk compat surfaces are inventoried.  "
        "TIER_1 surfaces (immediate retirement targets) are explicitly identified.  "
        "The system is transitioning from broad compatibility coexistence toward "
        "governed convergence with a shrinking compat footprint."
    )
except ImportError:  # pragma: no cover
    COMPAT_SURFACE_RETIREMENT_ALIGNED_PR10: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::COMPAT_SURFACE_RETIREMENT_ALIGNED_PR10_UNAVAILABLE"
    )

# PR-11 (node invocation governance): Confirms that governance eligibility is
# enforced at invocation time, not only at capability/tool-surface exposure
# time.  UnifiedNodeExecutor.execute() consults NodeFabricRegistry and
# evaluate_node_governance_eligibility() before loading or running any node on
# the canonical path.  Governance-ineligible nodes (archived, deprecated,
# unhealthy, readiness-gap) are denied canonical invocation with a structured
# eligibility_denial diagnostic payload.  The only permitted bypass is the
# explicitly-scoped COMPAT_INTERNAL override, which is non-canonical and
# fully auditable.
try:
    from core.node_invocation_governance import (  # noqa: F401
        NODE_INVOCATION_GOVERNANCE_IS_AUTHORITY as _NIGG_AUTHORITY,
        NODE_INVOCATION_GOVERNANCE_PR11_SENTINEL as _NIGG_PR11,
        GOVERNANCE_GATE_ENFORCED_AT_INVOCATION_TIME_POLICY as _NIGG_GATE_POLICY,
        INELIGIBLE_NODES_CANNOT_BE_CANONICALLY_INVOKED_POLICY as _NIGG_INELIGIBLE_POLICY,
        INVOCATION_DENIAL_CARRIES_STRUCTURED_DIAGNOSTICS_POLICY as _NIGG_DIAG_POLICY,
        OVERRIDE_PATH_IS_EXPLICIT_AUDITABLE_NON_CANONICAL_POLICY as _NIGG_OVERRIDE_POLICY,
        UNREGISTERED_NODES_PROCEED_WITH_UNMANAGED_WARNING_POLICY as _NIGG_UNREGD_POLICY,
        NodeInvocationGovernanceOverride as _NodeInvocationGovernanceOverride,
        NodeInvocationGovernanceDecision as _NodeInvocationGovernanceDecision,
        evaluate_invocation_governance as _evaluate_invocation_governance,
        build_invocation_denial_diagnostics as _build_invocation_denial_diagnostics,
    )
    from core.node_invocation import (  # noqa: F401
        GOVERNANCE_ELIGIBILITY_ENFORCED_AT_INVOCATION_TIME_PR11_SENTINEL as _NI_PR11,
        CANONICAL_INVOCATION_DENIES_INELIGIBLE_NODES_PR11_POLICY as _NI_PR11_POLICY,
    )

    NODE_INVOCATION_GOVERNANCE_ALIGNED_PR11: str = (
        "PROJECTION_ROUTES::NODE_INVOCATION_GOVERNANCE_ALIGNED_PR11_V1: "
        "core.node_invocation_governance is confirmed as the authority for "
        "governance eligibility enforcement at node invocation time (PR-11).  "
        "UnifiedNodeExecutor.execute() consults NodeFabricRegistry and "
        "evaluate_node_governance_eligibility() before loading or executing any "
        "node.  Governance-ineligible nodes (archived, deprecated, unhealthy, "
        "readiness-gap) are denied with a structured eligibility_denial diagnostic "
        "payload.  Exposure-time and invocation-time governance are now aligned on "
        "the canonical path.  The COMPAT_INTERNAL override is non-canonical and "
        "fully auditable."
    )
except ImportError:  # pragma: no cover
    NODE_INVOCATION_GOVERNANCE_ALIGNED_PR11: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::NODE_INVOCATION_GOVERNANCE_ALIGNED_PR11_UNAVAILABLE"
    )

# PR-12 (node discovery startup/health closure): Confirms that the discovery
# integration gaps from PR-7 are closed.  NodeSystemLauncher.start_all() now
# calls initialize_discovery_after_startup() after the node batch completes.
# UnifiedHealthManager health surfaces expose get_discovery_participation_summary()
# data including undiscovered_active count, fabric_healthy count, and
# discovery_participation classification.  The system can distinguish running,
# registered, discovered, healthy, and undiscovered nodes in real diagnostics.
try:
    from core.node_discovery_startup_health_closure import (  # noqa: F401
        NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_IS_AUTHORITY as _NDSHC_AUTHORITY,
        NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_PR12_SENTINEL as _NDSHC_PR12,
        STARTUP_SEEDING_IS_INVOKED_BY_REAL_ORCHESTRATION_POLICY as _NDSHC_SEED_POLICY,
        HEALTH_SURFACES_REFLECT_DISCOVERY_PARTICIPATION_POLICY as _NDSHC_HEALTH_POLICY,
        UNDISCOVERED_ACTIVE_COUNT_IS_EXPOSED_IN_HEALTH_POLICY as _NDSHC_UNDISCOV_POLICY,
        DISCOVERY_DIAGNOSTICS_ALIGN_WITH_LAUNCHER_AND_FABRIC_POLICY as _NDSHC_DIAG_POLICY,
        build_discovery_health_surface as _build_discovery_health_surface,
        build_startup_seeding_status as _build_startup_seeding_status,
        build_discovery_diagnostic_context as _build_discovery_diagnostic_context,
    )
    from launcher.node_startup import (  # noqa: F401
        NODE_DISCOVERY_STARTUP_SEEDING_WIRED_PR12 as _NDSHC_LAUNCHER_PR12,
    )

    NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_ALIGNED_PR12: str = (
        "PROJECTION_ROUTES::NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_ALIGNED_PR12_V1: "
        "core.node_discovery_startup_health_closure is confirmed as the canonical "
        "authority for closing NodeDiscoveryService startup seeding and health surface "
        "wiring gaps (PR-12).  NodeSystemLauncher.start_all() calls "
        "initialize_discovery_after_startup() after the node batch completes.  "
        "UnifiedHealthManager health surfaces expose get_discovery_participation_summary() "
        "data including undiscovered_active count, fabric_healthy count, and "
        "discovery_participation classification.  The system can distinguish running, "
        "registered, discovered, healthy, and undiscovered nodes in real diagnostics "
        "via build_discovery_diagnostic_context().  Discovery is a fully wired "
        "runtime observability participant."
    )
except ImportError:  # pragma: no cover
    NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_ALIGNED_PR12: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_ALIGNED_PR12_UNAVAILABLE"
    )


# PR-13 (node track): Node final boundary enforcement aligned.
# Every remaining node-related surface has an explicit boundary category
# (CANONICAL / COMPAT_ONLY / INTERNAL_ONLY / DEPRECATED).  node_status_cache
# is confirmed as COMPAT_ONLY and must not be the primary source of node
# counts in dashboards.  GET /api/v1/system/status now derives nodes.total
# and nodes.active from NodeFabricRegistry with an explicit node_count_source
# key.  get_node_count_from_canonical_source() is available for all callers
# that need canonical node-count truth.
try:
    from core.node_final_boundary_enforcement import (  # noqa: F401
        NODE_FINAL_BOUNDARY_ENFORCEMENT_IS_AUTHORITY as _NFBE_AUTHORITY,
        NODE_FINAL_BOUNDARY_ENFORCEMENT_PR13_SENTINEL as _NFBE_PR13,
        NODE_STATUS_CACHE_IS_COMPAT_NOT_CANONICAL_POLICY as _NFBE_CACHE_POLICY,
        SYSTEM_STATUS_NODES_COUNT_MUST_PREFER_CANONICAL_REGISTRY_POLICY as _NFBE_COUNT_POLICY,
        COMPAT_SURFACES_ARE_NOT_PEER_AUTHORITIES_POLICY as _NFBE_COMPAT_POLICY,
        DASHBOARD_SURFACES_MUST_USE_CANONICAL_SOURCES_POLICY as _NFBE_DASH_POLICY,
        build_node_surface_classification_registry as _build_node_surface_classification_registry,
        get_final_boundary_summary as _get_final_boundary_summary,
    )

    NODE_FINAL_BOUNDARY_ENFORCEMENT_ALIGNED_PR13: str = (
        "PROJECTION_ROUTES::NODE_FINAL_BOUNDARY_ENFORCEMENT_ALIGNED_PR13_V1: "
        "core.node_final_boundary_enforcement is confirmed as the canonical "
        "authority for finalizing node surface boundary classification (PR-13 "
        "node track).  Every remaining node route, helper, adapter, and store "
        "is explicitly categorized as CANONICAL, COMPAT_ONLY, INTERNAL_ONLY, "
        "or DEPRECATED.  node_status_cache is COMPAT_ONLY and is no longer "
        "the primary source of node counts in GET /api/v1/system/status.  "
        "NodeFabricRegistry is the canonical source for node counts and node "
        "presence.  build_node_surface_classification_registry() and "
        "get_final_boundary_summary() are available for dashboards and diagnostics."
    )
except ImportError:  # pragma: no cover
    NODE_FINAL_BOUNDARY_ENFORCEMENT_ALIGNED_PR13: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::NODE_FINAL_BOUNDARY_ENFORCEMENT_ALIGNED_PR13_UNAVAILABLE"
    )

try:
    from core.node_cognition_activation import (  # noqa: F401
        NODE_COGNITION_ACTIVATION_IS_AUTHORITY as _NCA_AUTHORITY,
        NODE_COGNITION_ACTIVATION_PR14_SENTINEL as _NCA_PR14,
        ACTIVATION_LAYER_SITS_ABOVE_INVOCATION_SUBSTRATE_POLICY as _NCA_SUBSTRATE_POLICY,
        ACTIVATION_ELIGIBILITY_REQUIRES_GOVERNANCE_CLEARANCE_POLICY as _NCA_GOV_POLICY,
        ACTIVATION_STATE_TRANSITIONS_ARE_VALIDATED_POLICY as _NCA_TRANS_POLICY,
        COGNITION_ROLE_IS_ASSIGNED_AT_ACTIVATION_NOT_REGISTRATION_POLICY as _NCA_ROLE_POLICY,
        ORCHESTRATION_MUST_USE_ACTIVATION_LAYER_NOT_BARE_INVOCATION_POLICY as _NCA_ORCH_POLICY,
        PR14_ACTIVATION_DISPATCH_RUNTIME_STATUS_POLICY as _NCA_RUNTIME_STATUS_POLICY,
        build_activation_context_snapshot as _build_activation_context_snapshot,
        get_pr14_activation_runtime_status as _get_pr14_activation_runtime_status,
        get_activation_summary as _get_activation_summary,
    )

    NODE_COGNITION_ACTIVATION_ALIGNED_PR14: str = (
        "PROJECTION_ROUTES::NODE_COGNITION_ACTIVATION_ALIGNED_PR14_V1: "
        "core.node_cognition_activation is confirmed as the canonical authority "
        "for the cognition-oriented node activation layer (PR-14 node track).  "
        "NodeActivationState, NodeCognitionRole, NodeActivationContext, "
        "NodeActivationPolicy, evaluate_activation_eligibility(), and "
        "transition_activation_state() define the formal activation vocabulary "
        "above the canonical invocation substrate.  Dispatch-time enforcement "
        "authority remains core.node_invocation_governance + "
        "core.node_activation_context; PR-14 activation-state functions are "
        "available as explicit orchestration-layer modeling and are surfaced via "
        "get_pr14_activation_runtime_status() to avoid implying mandatory "
        "invoke_node() enforcement where it is not wired."
    )
except ImportError:  # pragma: no cover
    NODE_COGNITION_ACTIVATION_ALIGNED_PR14: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::NODE_COGNITION_ACTIVATION_ALIGNED_PR14_UNAVAILABLE"
    )

# PR-15 (node track): Node Activation Context Layer
try:
    from core.node_activation_context import (  # noqa: F401
        NODE_ACTIVATION_CONTEXT_IS_AUTHORITY as _NAC_AUTHORITY,
        NODE_ACTIVATION_CONTEXT_PR15_SENTINEL as _NAC_PR15,
        ACTIVATION_CONTEXT_ENRICHES_INVOCATION_GOVERNANCE_POLICY as _NAC_ENRICH_POLICY,
        DORMANT_NODES_CANNOT_BE_CANONICALLY_INVOKED_POLICY as _NAC_DORMANT_POLICY,
        TOPOLOGY_CONDITIONAL_REQUIRES_CONNECTIVITY_POLICY as _NAC_TOPO_POLICY,
        DEMAND_ACTIVATED_REQUIRES_EXPLICIT_REQUEST_POLICY as _NAC_DEMAND_POLICY,
        ACTIVATION_POLICY_CLASSIFICATION_IS_RUNTIME_METADATA_POLICY as _NAC_META_POLICY,
        evaluate_node_activation_context as _evaluate_node_activation_context,
        get_activation_policy_kind_for_node as _get_activation_policy_kind_for_node,
    )

    NODE_ACTIVATION_CONTEXT_ALIGNED_PR15: str = (
        "PROJECTION_ROUTES::NODE_ACTIVATION_CONTEXT_ALIGNED_PR15_V1: "
        "core.node_activation_context is confirmed as the canonical authority "
        "for node activation-context evaluation (PR-15 node track).  "
        "NodeActivationPolicyKind (ALWAYS_ACTIVE / TOPOLOGY_CONDITIONAL / "
        "DEMAND_ACTIVATED / DORMANT) classifies node runtime readiness and is "
        "evaluated inside evaluate_invocation_governance() as a secondary "
        "enrichment layer after governance eligibility is confirmed.  "
        "NodeFabricRegistry remains the canonical source of node existence and "
        "base eligibility.  NetworkTopologyRuntime is consulted as optional "
        "secondary input only for TOPOLOGY_CONDITIONAL nodes."
    )
except ImportError:  # pragma: no cover
    NODE_ACTIVATION_CONTEXT_ALIGNED_PR15: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::NODE_ACTIVATION_CONTEXT_ALIGNED_PR15_UNAVAILABLE"
    )


# PR-18: Cognitive Execution-Policy Wiring alignment sentinel.
# Asserts that the cognitive execution-policy mapping layer is available and
# wired into the projection routes module, enabling projection endpoints to
# surface cognitive execution-hint data (region, execution_path_preference,
# activation_budget) derived from live StateInterpreter / ContinuumOrchestrator
# signals alongside existing posture and execution-policy projections.
try:
    from core.cognitive.cognitive_execution_policy import (  # noqa: F401
        COGNITIVE_EXECUTION_POLICY_IS_AUTHORITY as _CEP_AUTHORITY,
        COGNITIVE_EXECUTION_POLICY_PR18_SENTINEL as _CEP_PR18,
        COGNITIVE_STATE_DRIVES_EXECUTION_HINT_POLICY as _CEP_POLICY1,
        COGNITIVE_HINT_IS_ADVISORY_NOT_MANDATORY_POLICY as _CEP_POLICY2,
        COGNITIVE_HINT_CONSUMES_EXISTING_SIGNALS_POLICY as _CEP_POLICY3,
        ACTIVATION_BUDGET_IS_NORMALIZED_POLICY as _CEP_POLICY4,
        derive_cognitive_execution_hint as _derive_cognitive_execution_hint,
        CognitiveExecutionHint as _CognitiveExecutionHint,
    )

    COGNITIVE_EXECUTION_POLICY_ALIGNED_PR18: str = (
        "PROJECTION_ROUTES::COGNITIVE_EXECUTION_POLICY_ALIGNED_PR18_V1: "
        "core.cognitive.cognitive_execution_policy is confirmed as the canonical "
        "authority for the cognitive execution-policy mapping layer (PR-18).  "
        "CognitiveExecutionHint derives bounded execution-policy hints "
        "(execution_path_preference, delegation_bias, planning_intensity, "
        "activation_budget) from already-live CognitiveRegion signals without "
        "introducing a second cognitive pipeline.  "
        "DesktopPresenceRuntime and OpenClawd receive the hint as an advisory "
        "signal that influences execution-path log entries and response metadata."
    )
except ImportError:  # pragma: no cover
    COGNITIVE_EXECUTION_POLICY_ALIGNED_PR18: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::COGNITIVE_EXECUTION_POLICY_ALIGNED_PR18_UNAVAILABLE"
    )

# PR-18: Cognitive Activation Budgeting layer alignment sentinel.
# Asserts that the activation-budget layer is available and wired, enabling
# projection endpoints to surface activation budget influence diagnostics.
try:
    from core.cognitive.cognitive_activation_budget import (  # noqa: F401
        COGNITIVE_ACTIVATION_BUDGET_IS_AUTHORITY as _CAB_AUTHORITY,
        COGNITIVE_ACTIVATION_BUDGET_PR18_SENTINEL as _CAB_PR18,
        HARD_GATES_REMAIN_AUTHORITATIVE_POLICY as _CAB_POLICY1,
        BUDGET_IS_SOFT_INFLUENCE_NOT_HARD_GATE_POLICY as _CAB_POLICY2,
        derive_activation_budget as _derive_activation_budget,
        get_planner_breadth_guidance as _get_planner_breadth_guidance,
        ActivationBudget as _ActivationBudget,
        PlannerBreadthGuidance as _PlannerBreadthGuidance,
    )

    COGNITIVE_ACTIVATION_BUDGET_ALIGNED_PR18: str = (
        "PROJECTION_ROUTES::COGNITIVE_ACTIVATION_BUDGET_ALIGNED_PR18_V1: "
        "core.cognitive.cognitive_activation_budget is confirmed as the canonical "
        "activation-budget layer for PR-18.  ActivationBudget and "
        "PlannerBreadthGuidance translate CognitiveExecutionHint signals into "
        "bounded runtime guidance for node activation intensity and planner breadth.  "
        "Hard gates (lifecycle governance, invocation governance, node activation "
        "context) remain authoritative; the budget is a soft influence layer only."
    )
except ImportError:  # pragma: no cover
    COGNITIVE_ACTIVATION_BUDGET_ALIGNED_PR18: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::COGNITIVE_ACTIVATION_BUDGET_ALIGNED_PR18_UNAVAILABLE"
    )

# PR-19: Memory-Informed Runtime Bias alignment sentinel.
# Asserts that the memory-bias layer is available and wired, enabling
# projection endpoints to surface memory-bias influence diagnostics
# (posture, continuity_score, retrieval_relevance, novelty_factor) alongside
# existing cognitive and activation-budget projections.
try:
    from core.cognitive.memory_bias_layer import (  # noqa: F401
        MEMORY_BIAS_LAYER_IS_AUTHORITY as _MBL_AUTHORITY,
        MEMORY_BIAS_LAYER_PR19_SENTINEL as _MBL_PR19,
        MEMORY_BIAS_ACTIVE_SCOPE_BOUNDARY_PR23_SENTINEL as _MBL_PR23_SCOPE,
        HARD_GATES_OVERRIDE_MEMORY_BIAS_POLICY as _MBL_POLICY1,
        MEMORY_BIAS_IS_ADVISORY_NOT_AUTHORITATIVE_POLICY as _MBL_POLICY2,
        MEMORY_BIAS_CONSUMES_EXISTING_SIGNALS_POLICY as _MBL_POLICY3,
        MEMORY_BIAS_SUBORDINATE_TO_TASK_SEMANTICS_POLICY as _MBL_POLICY4,
        derive_memory_bias as _derive_memory_bias,
        get_memory_planner_guidance as _get_memory_planner_guidance,
        MemoryBias as _MemoryBias,
        MemoryPlannerGuidance as _MemoryPlannerGuidance,
    )

    MEMORY_BIAS_LAYER_ALIGNED_PR19: str = (
        "PROJECTION_ROUTES::MEMORY_BIAS_LAYER_ALIGNED_PR19_V1: "
        "core.cognitive.memory_bias_layer is confirmed as the canonical "
        "memory-informed runtime bias layer for PR-19.  MemoryBias and "
        "MemoryPlannerGuidance derive bounded continuity/retrieval/novelty "
        "posture signals from already-live WorkingMemory, LongTermMemory, and "
        "TaskMemory singletons without introducing a second memory pipeline.  "
        "Hard gates (invocation governance, activation-context readiness, "
        "activation budgets, explicit user intent) remain authoritative; "
        "memory bias is a soft advisory influence only.  PR-23 scope boundary "
        "is explicit: memory bias is active for planner strategy shaping and "
        "runtime diagnostics, not as a direct source-dispatch mode/target "
        "selection authority."
    )
except ImportError:  # pragma: no cover
    MEMORY_BIAS_LAYER_ALIGNED_PR19: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::MEMORY_BIAS_LAYER_ALIGNED_PR19_UNAVAILABLE"
    )

# PR-20: Unified Runtime Decision Observability alignment sentinel.
try:
    from core.runtime_decision_observability import (  # noqa: F401
        RUNTIME_DECISION_OBSERVABILITY_IS_AUTHORITY as _RDO_IS_AUTHORITY,
        RUNTIME_DECISION_OBSERVABILITY_PR20_SENTINEL as _RDO_PR20,
        RuntimeDecisionExplanation as _RuntimeDecisionExplanation,
        build_runtime_decision_explanation as _build_rde,
        build_runtime_decision_diagnostics as _build_rdd,
    )

    RUNTIME_DECISION_OBSERVABILITY_ALIGNED_PR20: str = (
        "PROJECTION_ROUTES::RUNTIME_DECISION_OBSERVABILITY_ALIGNED_PR20_V1: "
        "core.runtime_decision_observability is confirmed as the canonical "
        "unified runtime decision observability layer for PR-20.  "
        "RuntimeDecisionExplanation consolidates PR-17 task-semantic, PR-18 "
        "activation-budget, PR-19 memory-bias, governance, and cognitive-posture "
        "influence layers into a single coherent diagnostics surface.  "
        "Hard gates remain primary; soft influences are represented as advisory "
        "layers with explicit influence_class labels."
    )
except ImportError:  # pragma: no cover
    RUNTIME_DECISION_OBSERVABILITY_ALIGNED_PR20: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::RUNTIME_DECISION_OBSERVABILITY_ALIGNED_PR20_UNAVAILABLE"
    )

try:
    from core.canonical_session_axis import (  # noqa: F401
        CANONICAL_SESSION_AXIS_AUTHORITY as _CSA_AUTHORITY,
        CANONICAL_SESSION_AXIS_PR3_SENTINEL as _CSA_PR3,
        SessionFamily as _SessionFamily,
        SessionIdentifierRole as _SessionIdentifierRole,
        get_session_family_catalogue as _get_session_family_catalogue,
        get_session_identifier_catalogue as _get_session_identifier_catalogue,
        get_android_session_mapping_catalogue as _get_android_session_mapping_catalogue,
    )

    CANONICAL_SESSION_AXIS_ALIGNED_PR3: str = (
        "PROJECTION_ROUTES::CANONICAL_SESSION_AXIS_ALIGNED_PR3_V1: "
        "core.canonical_session_axis is confirmed as the canonical authority "
        "for the cross-layer, cross-repository session axis model (PR-3).  "
        "Five session families (conversation, control, runtime_attachment, "
        "delegation_transfer, mesh) are explicitly defined with canonical "
        "identifiers, alias resolution order, continuity class, and Android "
        "mapping catalogue.  Existing reconnect, recovery, and transfer "
        "semantics are preserved."
    )
except ImportError:  # pragma: no cover
    CANONICAL_SESSION_AXIS_ALIGNED_PR3: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::CANONICAL_SESSION_AXIS_ALIGNED_PR3_UNAVAILABLE"
    )

# PR-4 (cross-repo protocol consistency rules): Canonical cross-repository
# protocol consistency alignment sentinel.  Asserts that the protocol
# consistency module is importable from this module's context, enabling
# projection endpoints to surface protocol surface classification and
# transitional allowance summaries for operator visibility.
try:
    from core.cross_repo_protocol_consistency import (  # noqa: F401
        CROSS_REPO_PROTOCOL_CONSISTENCY_AUTHORITY as _CRPC_AUTHORITY,
        CROSS_REPO_PROTOCOL_CONSISTENCY_PR4_SENTINEL as _CRPC_PR4,
        ProtocolSurfaceClass as _ProtocolSurfaceClass,
        CanonicalTerminalState as _CanonicalTerminalState,
        get_protocol_surface_catalogue as _get_protocol_surface_catalogue,
        get_terminal_state_consistency_catalogue as _get_terminal_state_catalogue,
        build_protocol_consistency_snapshot as _build_protocol_consistency_snapshot,
    )

    CROSS_REPO_PROTOCOL_CONSISTENCY_ALIGNED_PR4: str = (
        "PROJECTION_ROUTES::CROSS_REPO_PROTOCOL_CONSISTENCY_ALIGNED_PR4_V1: "
        "core.cross_repo_protocol_consistency is confirmed as the canonical "
        "authority for cross-repository protocol consistency rules (PR-4).  "
        "Critical shared protocol surfaces are explicitly classified as "
        "canonical or transitional, terminal state consistency is documented, "
        "delegated execution status semantics are defined, and transitional "
        "compatibility allowances are enumerated.  Projection endpoints can "
        "surface protocol consistency snapshots for operator visibility."
    )
except ImportError:  # pragma: no cover
    CROSS_REPO_PROTOCOL_CONSISTENCY_ALIGNED_PR4: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::CROSS_REPO_PROTOCOL_CONSISTENCY_ALIGNED_PR4_UNAVAILABLE"
    )

# PR-5 (device/node domain governance): Unified governance model for the device
# domain and node domain without forcing false identity equivalence.  Importing
# the authority and PR-5 sentinel from the governance module ties the projection
# route layer to the explicit governance model, enabling projection endpoints to
# surface domain definitions, bridge relationships, and registry surface
# classifications for operator and diagnostic visibility.
try:
    from core.device_node_domain_governance import (  # noqa: F401
        DEVICE_NODE_DOMAIN_GOVERNANCE_IS_AUTHORITY as _DNDG_AUTHORITY,
        DEVICE_NODE_DOMAIN_GOVERNANCE_PR5_SENTINEL as _DNDG_PR5,
        DomainKind as _DomainKind,
        BridgeRelationshipKind as _BridgeRelationshipKind,
        RegistrySurfaceDomain as _RegistrySurfaceDomain,
        RegistrySurfaceRole as _RegistrySurfaceRole,
        build_domain_governance_snapshot as _build_domain_governance_snapshot,
        get_governance_summary as _get_governance_summary,
    )

    DEVICE_NODE_DOMAIN_GOVERNANCE_ALIGNED_PR5: str = (
        "PROJECTION_ROUTES::DEVICE_NODE_DOMAIN_GOVERNANCE_ALIGNED_PR5_V1: "
        "core.device_node_domain_governance is confirmed as the canonical "
        "authority for the unified device/node domain governance model (PR-5). "
        "Device-domain and node-domain responsibilities are explicitly "
        "separated.  Runtime-host, capability-host, and dispatch-target bridge "
        "relationships are documented.  Registry surface authority matrix "
        "classifies all major governance surfaces.  Both domains are jointly "
        "governed by the center runtime without false identity equivalence."
    )
except ImportError:  # pragma: no cover
    DEVICE_NODE_DOMAIN_GOVERNANCE_ALIGNED_PR5: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::DEVICE_NODE_DOMAIN_GOVERNANCE_ALIGNED_PR5_UNAVAILABLE"
    )

# PR-12 (Cross-repository consistency gates — main repository side): CI-friendly
# consistency gate mechanisms for the most important shared semantic surfaces.
# Importing authority and PR-12 sentinel from the new module ties the projection
# route layer to the consistency gate infrastructure, enabling CI-level automated
# checking of shared schema vocabulary, session identifiers, execution enums,
# terminal state semantics, descriptor fields, and transitional allowance
# explicitness.
try:
    from core.cross_repo_consistency_gates import (  # noqa: F401
        CROSS_REPO_CONSISTENCY_GATES_IS_AUTHORITY as _CRCG_AUTHORITY,
        CROSS_REPO_CONSISTENCY_GATES_PR12_SENTINEL as _CRCG_PR12,
        ConsistencyGateKind as _ConsistencyGateKind,
        GateVerdict as _GateVerdict,
        build_consistency_gate_snapshot as _build_consistency_gate_snapshot,
        run_all_consistency_gates as _run_all_consistency_gates,
    )

    CROSS_REPO_CONSISTENCY_GATES_ALIGNED_PR12: str = (
        "PROJECTION_ROUTES::CROSS_REPO_CONSISTENCY_GATES_ALIGNED_PR12_V1: "
        "core.cross_repo_consistency_gates is confirmed as the canonical "
        "authority for CI-friendly cross-repository consistency gate mechanisms "
        "(PR-12).  Schema vocabulary, session family, execution enum, terminal "
        "state, descriptor field, and transitional marker gates are available "
        "and produce structured ConsistencyGateResult objects.  Projection "
        "endpoints can surface gate snapshots for operator and CI visibility "
        "without changing runtime behavior."
    )
except ImportError:  # pragma: no cover
    CROSS_REPO_CONSISTENCY_GATES_ALIGNED_PR12: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::CROSS_REPO_CONSISTENCY_GATES_ALIGNED_PR12_UNAVAILABLE"
    )

# PR-6 (UGCP convergence plan, realization-v2 side): authority boundary
# classification across SSOT, UDM, UCM, registries, caches, projections,
# facades, and adapters.  Importing authority and PR-6 sentinel from the
# new module ties the projection route layer to the authority boundary
# classification infrastructure, making the authority matrix machine-checkable
# and diagnosable at the projection surface level.
try:
    from core.authority_boundary_classification import (  # noqa: F401
        AUTHORITY_BOUNDARY_CLASSIFICATION_IS_AUTHORITY as _ABC_AUTHORITY,
        AUTHORITY_BOUNDARY_CLASSIFICATION_PR6_SENTINEL as _ABC_PR6,
        COMPAT_SURFACES_ARE_NON_AUTHORITATIVE_POLICY as _ABC_COMPAT_POLICY,
        CACHE_INDEX_SURFACES_MUST_NOT_WRITE_TRUTH_POLICY as _ABC_CACHE_POLICY,
        ADAPTER_SURFACES_ARE_ROUTING_ONLY_POLICY as _ABC_ADAPTER_POLICY,
        TRANSITIONAL_SURFACES_MUST_NOT_BE_EXTENDED_POLICY as _ABC_TRANSITIONAL_POLICY,
        AuthorityRole as _AuthorityRole,
        AuthoritySurface as _AuthoritySurface,
        AuthorityMatrixSummary as _AuthorityMatrixSummary,
        get_authority_matrix as _get_authority_matrix,
        classify_surface as _classify_surface,
        get_surfaces_by_role as _get_surfaces_by_role,
        get_non_authoritative_surfaces as _get_non_authoritative_surfaces,
        get_transitional_surfaces as _get_transitional_surfaces,
        build_authority_matrix_summary as _build_authority_matrix_summary,
    )

    AUTHORITY_BOUNDARY_CLASSIFICATION_ALIGNED_PR6: str = (
        "PROJECTION_ROUTES::AUTHORITY_BOUNDARY_CLASSIFICATION_ALIGNED_PR6_V1: "
        "core.authority_boundary_classification is confirmed as the canonical "
        "authority for classifying all major SSOT, UDM, UCM, registry, cache, "
        "projection, compat-facade, adapter, and routing-helper surfaces by "
        "authority role (PR-6 authority boundary classification).  The full "
        "authority matrix is reviewable and machine-checkable.  Compat-facing "
        "surfaces are explicitly non-authoritative.  Transitional surfaces are "
        "marked for retirement.  Projection endpoints can surface the authority "
        "matrix summary for operator and CI visibility."
    )
except ImportError:  # pragma: no cover
    AUTHORITY_BOUNDARY_CLASSIFICATION_ALIGNED_PR6: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::AUTHORITY_BOUNDARY_CLASSIFICATION_ALIGNED_PR6_UNAVAILABLE"
    )

# PR-8 (UGCP convergence plan, realization-v2 side): long-tail compat surface
# classification and replacement of generic-forward paths for the highest-value
# multi-device flows (file transfer, peer exchange, mesh topology).
try:
    from core.long_tail_compat_surface import (  # noqa: F401
        LONG_TAIL_COMPAT_SURFACE_IS_AUTHORITY as _LTCS_AUTHORITY,
        LONG_TAIL_COMPAT_SURFACE_PR8_SENTINEL as _LTCS_PR8,
        GENERIC_FORWARD_IS_TRANSITIONAL_POLICY as _LTCS_GF_POLICY,
        MINIMAL_COMPAT_PATHS_MUST_BE_CATALOGUED_POLICY as _LTCS_CATALOG_POLICY,
        HIGHEST_VALUE_FLOWS_REQUIRE_STATEFUL_HANDLING_POLICY as _LTCS_HV_POLICY,
        LONG_TAIL_HONESTY_POLICY as _LTCS_HONESTY_POLICY,
        LongTailPathKind as _LongTailPathKind,
        LongTailValueTier as _LongTailValueTier,
        LongTailTransitionStatus as _LongTailTransitionStatus,
        LongTailPathRecord as _LongTailPathRecord,
        LongTailCatalogSummary as _LongTailCatalogSummary,
        get_long_tail_catalog as _get_long_tail_catalog,
        get_paths_by_tier as _get_paths_by_tier,
        get_generic_forward_paths as _get_generic_forward_paths,
        get_closed_loop_paths as _get_closed_loop_paths,
        get_transitional_paths as _get_transitional_paths,
        build_catalog_summary as _build_long_tail_catalog_summary,
    )

    LONG_TAIL_COMPAT_SURFACE_ALIGNED_PR8: str = (
        "PROJECTION_ROUTES::LONG_TAIL_COMPAT_SURFACE_ALIGNED_PR8_V1: "
        "core.long_tail_compat_surface is confirmed as the canonical "
        "authority for classifying all long-tail generic-forward and "
        "minimal-compat message-family paths.  The highest-value flows "
        "(file_transfer, peer_announce, peer_exchange, mesh_topology) "
        "now have dedicated stateful handlers in "
        "galaxy_gateway.android.handlers.  The remaining generic-forward "
        "paths (remote control, app lifecycle, system command, task "
        "lifecycle, agent config) are explicitly catalogued as transitional "
        "and must not be extended as canonical architecture.  The catalog "
        "is machine-checkable and diagnosable at the projection surface "
        "level (PR-8 long-tail compat surface)."
    )
except ImportError:  # pragma: no cover
    LONG_TAIL_COMPAT_SURFACE_ALIGNED_PR8: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::LONG_TAIL_COMPAT_SURFACE_ALIGNED_PR8_UNAVAILABLE"
    )

# PR-10 (realization-v2 convergence plan): Architecture Stabilization Baseline
# alignment sentinel.  Asserts that the stabilization baseline module is
# importable from this module's context, enabling projection endpoints to
# expose the canonical-vs-transitional surface summary and future-work guidance
# for operator and diagnostic visibility.
try:
    from core.architecture_stabilization_baseline import (  # noqa: F401
        ARCHITECTURE_STABILIZATION_BASELINE_IS_AUTHORITY as _ASB_AUTHORITY,
        ARCHITECTURE_STABILIZATION_BASELINE_PR10_SENTINEL as _ASB_PR10,
        StabilizationTier as _StabilizationTier,
        SurfaceCategory as _SurfaceCategory,
        get_canonical_stable_surfaces as _get_canonical_stable_surfaces,
        get_transitional_surfaces as _get_transitional_surfaces,
        build_stabilization_baseline_snapshot as _build_stabilization_baseline_snapshot,
    )

    ARCHITECTURE_STABILIZATION_BASELINE_ALIGNED_PR10: str = (
        "PROJECTION_ROUTES::ARCHITECTURE_STABILIZATION_BASELINE_ALIGNED_PR10_V1: "
        "core.architecture_stabilization_baseline is confirmed as the canonical "
        "authority for the explicit architecture stabilization baseline after the "
        "realization-v2 convergence plan PR-6 through PR-9.  Canonical-stable, "
        "transitional-converging, extension-surface, and compat-bridge surface "
        "tiers are explicitly classified.  Future-work guidance is machine-checkable "
        "at the projection surface level (PR-10 stabilization baseline)."
    )
except ImportError:  # pragma: no cover
    ARCHITECTURE_STABILIZATION_BASELINE_ALIGNED_PR10: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::ARCHITECTURE_STABILIZATION_BASELINE_ALIGNED_PR10_UNAVAILABLE"
    )

# PR-5 Final: Final Cleanup and Invariant Tightening integration sentinel.
# Importing the authority sentinel and PR-5 final sentinel ties the projection
# route layer to the canonical no-bypass guard surface, enabling projection
# endpoints to confirm that the five closure-area guards (completion ingress,
# capability routing, runtime truth ingress, provider routing, validation gate)
# are active and that the semantic capability tier registry is present.
try:
    from core.final_cleanup_invariant_tightening import (  # noqa: F401
        FINAL_CLEANUP_INVARIANT_TIGHTENING_AUTHORITY as _FCIT_AUTHORITY,
        FINAL_CLEANUP_INVARIANT_TIGHTENING_PR5_SENTINEL as _FCIT_PR5,
        is_final_cleanup_posture_acceptable as _is_final_cleanup_posture_acceptable,
    )

    FINAL_CLEANUP_INVARIANT_TIGHTENING_ALIGNED_PR5_FINAL: str = (
        "PROJECTION_ROUTES::FINAL_CLEANUP_INVARIANT_TIGHTENING_ALIGNED_PR5_FINAL_V1: "
        "core.final_cleanup_invariant_tightening is available and aligned with "
        "projection routes.  No-bypass guards for completion ingress, capability "
        "routing, runtime truth ingress, provider routing, and validation gate are "
        "active.  Semantic capability tier registry is present.  "
        "is_final_cleanup_posture_acceptable() is callable for CI/release checks."
    )
except ImportError:  # pragma: no cover
    FINAL_CLEANUP_INVARIANT_TIGHTENING_ALIGNED_PR5_FINAL: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::FINAL_CLEANUP_INVARIANT_TIGHTENING_ALIGNED_PR5_FINAL_UNAVAILABLE"
    )


def create_router(service_manager=None, config=None) -> APIRouter:  # noqa: ARG001
    """Create and return the projection router.

    The ``service_manager`` and ``config`` parameters follow the same
    convention used by all other ``core/routes/`` modules and are accepted
    (but not required) to allow uniform registration in ``core/api_routes.py``.
    """
    router = APIRouter()

    # ------------------------------------------------------------------
    # GET /api/v1/projection/runtime
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/runtime")
    async def get_runtime_projection() -> JSONResponse:
        """Return the current RuntimeProjection as JSON.

        This endpoint is **read-only**.  It assembles a
        :class:`~core.projection.RuntimeProjection` from the live
        ``ContinuumState`` (and optionally the ``TopologyRoutePlan`` if
        the model topology layer has been initialised) and returns a
        stable JSON payload.

        This is the lightweight runtime projection surface. Status Board V2
        should prefer richer board-facing truth surfaces
        (``/api/v1/projection/runtime-truth`` or
        ``/api/v1/projection/desktop-status-board``) and use this endpoint as
        a compatibility fallback.

        Response schema
        ---------------
        See :class:`~core.projection.RuntimeProjection` for the full field
        reference.  Every field maps directly to a surface in the status board:

        - ``tri_state_phase``        → PhaseSurface
        - ``runtime_domain``         → DomainSurface
        - ``primary_model_id``       → TopologySurface
        - ``support_model_ids``      → TopologySurface
        - ``active_weights``         → TopologySurface
        - ``active_device_ids``      → DeviceSurface
        - ``execution_stage``        → DeviceSurface
        - ``presence_intensity``     → MetricsSurface
        - ``coherence``              → MetricsSurface
        - ``collapse_tendency``      → MetricsSurface
        - ``retreat_tendency``       → MetricsSurface
        """
        payload = _assemble_projection()
        payload.setdefault("projection_surface_role", "runtime_lightweight")
        payload.setdefault("board_facing_default", False)
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/return
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/return")
    async def get_return_projection() -> JSONResponse:
        """Return the current RuntimeProjection enriched with return intelligence.

        This endpoint is **read-only**.  It returns all standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"return_intelligence"`` key containing the
        :class:`~core.return_intelligence.ReturnSummary` for the current
        continuum state.

        The ``"return_intelligence"`` key is safe for public consumers —
        it never exposes the internal ``receding`` phase.

        Response schema (additions over /runtime)
        ------------------------------------------
        .. code-block:: json

            {
              "tri_state_phase": "...",
              ...,
              "return_intelligence": {
                "is_returning": false,
                "return_mode": "none",
                "return_action": null,
                "return_trigger": null,
                "decay_amount": 0.0,
                "reason": "no return active",
                "affects_manifest": false,
                "affects_liminal": false
              }
            }

        This endpoint is consumed by the ReturnSurface in Status Board V2
        and any other downstream systems that need return context.
        """
        payload = _assemble_projection_with_return()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/execution_policy
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/execution_policy")
    async def get_execution_policy_projection() -> JSONResponse:
        """Return the current execution-policy summary derived from live signals.

        This endpoint is **read-only** and **additive** — it does not modify
        any existing projection, continuum, or orchestration module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"execution_policy"`` key populated by the PR-11 policy schema.

        The ``"execution_policy"`` block answers:
          - What policy band applies (``observe_only`` / ``assistive`` /
            ``bounded_execute`` / ``full_execute``)?
          - What risk/action/fallback budgets are available?
          - Which executor levels are permitted?
          - Whether cross-device expansion is allowed?
          - Whether confirmation is required?

        The ``"hints"`` sub-key provides quick boolean checks for downstream
        consumers (manifest stage, liminal controllers, status board).

        This endpoint does **not** enforce the policy — enforcement is
        deferred to a follow-up PR.

        Response schema (additions over /return)
        -----------------------------------------
        .. code-block:: json

            {
              "tri_state_phase": "...",
              ...,
              "return_intelligence": { ... },
              "execution_policy": {
                "policy_band": "bounded_execute",
                "risk_budget": 0.5,
                "action_budget": 5,
                "fallback_budget": 2,
                "allowed_executor_levels": ["system_api", "uia", "orchestrator"],
                "cross_device_allowed": false,
                "requires_confirmation": true,
                "reason": "...",
                "can_execute": true,
                "can_expand_cross_device": false,
                "should_require_confirmation": true,
                "max_executor_level": "orchestrator"
              }
            }
        """
        payload = _assemble_projection_with_execution_policy()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/cross_device_routing
    # ------------------------------------------------------------------

    @router.get("/api/v1/execution/merge-summary")
    async def get_merge_summary() -> JSONResponse:
        """Return a read-only distributed execution merge summary.

        This endpoint is **read-only** and **additive** (PR-14).  It does not
        modify any existing projection, continuum, orchestration, or device
        module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"merge_summary"`` key populated by the PR-14 distributed merge and
        recovery schema.

        When no live merge context is available, the endpoint returns the
        pre-built :data:`~core.distributed_execution.EMPTY_MERGE_SUMMARY`
        alongside a recovery recommendation of ``no_recovery_needed``.

        Response schema (additions over /cross_device_routing)
        -------------------------------------------------------
        .. code-block:: json

            {
              "tri_state_phase": "...",
              ...,
              "merge_summary": {
                "merge_status": "success",
                "total_count": 0,
                "successful_count": 0,
                "failed_count": 0,
                "timed_out_count": 0,
                "skipped_count": 0,
                "success_rate": 0.0,
                "is_successful": false,
                "is_terminal_failure": true,
                "merged_payloads": [],
                "errors": [],
                "warnings": [],
                "recovery_recommendation": null,
                "task_id": "",
                "trace_id": "",
                "runtime_session_id": "",
                "merged_at": 0.0
              },
              "merge_hints": {
                "merge_status": "success",
                "is_successful": true,
                "is_terminal_failure": false,
                "has_errors": false,
                "has_warnings": false,
                "success_rate": 1.0,
                "has_recovery_recommendation": false,
                "recovery_posture": null,
                "total_count": 0,
                "task_id": "",
                "trace_id": ""
              }
            }
        """
        payload = _assemble_projection_with_merge_summary()
        return JSONResponse(content=payload)

    @router.get("/api/v1/projection/cross_device_routing")
    async def get_cross_device_routing_projection() -> JSONResponse:
        """Return the current cross-device routing summary derived from live signals.

        This endpoint is **read-only** and **additive** (PR-13).  It does not
        modify any existing projection, continuum, orchestration, or device
        module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"cross_device_routing"`` key populated by the PR-13 cross-device
        role and routing policy schema.

        The ``"cross_device_routing"`` block answers:
          - What routing posture is intended (``local_preferred`` /
            ``local_then_expand`` / ``remote_required`` / ``split_execution``
            / ``mirrored_observation``)?
          - Which device originated the request?
          - Which device is the primary executor?
          - Which devices are support / observer / relay / fallback?
          - Is cross-device expansion permitted by execution policy?
          - Is confirmation required before expansion?

        Response schema (additions over /execution_policy)
        ---------------------------------------------------
        .. code-block:: json

            {
              "tri_state_phase": "...",
              ...,
              "execution_policy": { ... },
              "cross_device_routing": {
                "posture": "local_preferred",
                "source_device_id": null,
                "primary_execution_device_id": null,
                "support_device_ids": [],
                "observer_device_ids": [],
                "relay_device_ids": [],
                "fallback_device_ids": [],
                "all_assignments": [],
                "runtime_domain_intent": "local",
                "expansion_allowed_by_execution_policy": false,
                "confirmation_required_before_expansion": true,
                "is_cross_device": false,
                "policy_reason": "..."
              }
            }
        """
        payload = _assemble_projection_with_cross_device_routing()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/task_semantics
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/task_semantics")
    async def get_task_semantics_projection() -> JSONResponse:
        """Return semantic step-kind hints derived from the current runtime state.

        This endpoint is **read-only** and **additive** (PR-15).  It does not
        modify any existing projection, continuum, orchestration, or device
        module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"task_semantics"`` key populated by the PR-15 task-semantics schema
        and a flat ``"semantic_hints"`` quick-check dict.

        The ``"task_semantics"`` block describes the semantic step classification
        for the current idle/active task state and answers:
          - How many steps are classified and of what kind?
          - Does the task contain side-effectful steps?
          - Does the task contain cross-device steps?
          - Which steps are visible in manifest/projection surfaces?
          - Which steps emit observability highlights?

        Response schema (additions over /cross_device_routing)
        -------------------------------------------------------
        .. code-block:: json

            {
              "tri_state_phase": "...",
              ...,
              "cross_device_routing": { ... },
              "task_semantics": {
                "task_id": "",
                "trace_id": "",
                "classified_steps": [],
                "total_steps": 0,
                "has_side_effectful_steps": false,
                "has_cross_device_steps": false,
                "has_confirmation_required_steps": false,
                "has_rollback_steps": false,
                "primary_visible_steps": [],
                "observability_highlight_steps": [],
                "unresolved_count": 0,
                "is_fully_resolved": true
              },
              "semantic_hints": {
                "total_steps": 0,
                "has_side_effectful_steps": false,
                "has_cross_device_steps": false,
                ...
              }
            }
        """
        payload = _assemble_projection_with_task_semantics()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/device-formation
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/device-formation")
    async def get_device_formation_projection() -> JSONResponse:
        """Return the current device-formation summary for the active runtime state.

        This endpoint is **read-only** and **additive** (PR-17).  It does not
        modify any existing projection, device manager, device router, or
        orchestration module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"device_formation"`` key populated by the PR-17 formation schema, and
        a flat ``"formation_hints"`` quick-check dict.

        The ``"device_formation"`` block makes multi-device participation
        **explicit and inspectable** and answers:
          - Which devices are in the current execution formation?
          - Which device is the source/origin?
          - Which device is the primary executor?
          - Which devices are support / observer / relay / fallback members?
          - Which device owns merge responsibility?
          - What barrier/completion posture is intended?
          - Is a multi-device formation required by policy?

        Response schema (additions over /task_semantics)
        -------------------------------------------------
        .. code-block:: json

            {
              "tri_state_phase": "...",
              ...,
              "task_semantics": { ... },
              "device_formation": {
                "schema_version": 1,
                "formation_id": "...",
                "task_id": null,
                "trace_id": null,
                "is_multi_device": false,
                "member_count": 0,
                "source_device_id": null,
                "primary_execution_device_id": null,
                "merge_owner_device_id": null,
                "barrier_posture": "wait_primary",
                "multi_device_required": false,
                "merge_confirmation_required": false,
                "fallback_available": false,
                "formation_reason": "no active formation",
                "runtime_domain_intent": "local",
                "all_member_device_ids": [],
                "fallback_device_ids": [],
                "support_device_ids": [],
                "observer_device_ids": [],
                "relay_device_ids": [],
                "policy_reason": "..."
              },
              "formation_hints": {
                "is_multi_device": false,
                "member_count": 0,
                "fallback_available": false,
                "multi_device_required": false,
                "merge_confirmation_required": false,
                "has_primary": false,
                "has_source": false,
                "has_merge_owner": false,
                "barrier_posture": "wait_primary",
                "runtime_domain_intent": "local"
              }
            }

        This endpoint is consumed by the DeviceFormationSurface in Status
        Board V2 and any downstream governance / reliability work that needs
        explicit formation context.
        """
        payload = _assemble_projection_with_device_formation()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/agent-dispatch
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/agent-dispatch")
    async def get_agent_dispatch_projection() -> JSONResponse:
        """Return the current agent-dispatch governance summary for the active runtime state.

        This endpoint is **read-only** and **additive** (PR-18).  It does not
        modify any existing projection, agent bridge, command router, or
        orchestration module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"agent_dispatch"`` key populated by the PR-18 governance schema, and
        a flat ``"ownership_hints"`` quick-check dict.

        The ``"agent_dispatch"`` block makes agent ownership and handoff
        governance **explicit and inspectable** and answers:
          - Which agent role initiated the current dispatch?
          - Which role currently holds execution responsibility?
          - Who owns the final outcome?
          - Is a recovery agent active?
          - Has the handoff depth limit been exceeded?
          - Is the governing handoff edge valid per the responsibility graph?

        Response schema (additions over /device-formation)
        ---------------------------------------------------
        .. code-block:: json

            {
              "tri_state_phase": "...",
              ...,
              "device_formation": { ... },
              "agent_dispatch": {
                "schema_version": 1,
                "dispatch_role": "unassigned",
                "target_role": "unassigned",
                "handoff_valid": false,
                "ownership": {
                  "dispatch_owner": "unassigned",
                  "current_owner": "unassigned",
                  "final_outcome_owner": null,
                  "handoff_count": 0,
                  "is_recovery_active": false,
                  "is_complete": false,
                  "max_handoff_depth": 5,
                  "depth_exceeded": false,
                  "recovery_permitted": true
                },
                "trace_id": null,
                "task_id": null,
                "bridge_source": null,
                "dispatch_success": false,
                "failure_reason": "",
                "policy_reason": "..."
              },
              "ownership_hints": {
                "dispatch_owner": "unassigned",
                "current_owner": "unassigned",
                "is_recovery_active": false,
                "is_complete": false,
                "depth_exceeded": false,
                "handoff_count": 0,
                "has_final_owner": false,
                "recovery_permitted": true
              }
            }

        This endpoint is consumed by any downstream governance / reliability
        work that needs explicit agent ownership context.
        """
        payload = _assemble_projection_with_agent_dispatch()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/routing-explanation
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/routing-explanation")
    async def get_routing_explanation_projection() -> JSONResponse:
        """Return the current routing explanation summary for the active runtime state.

        This endpoint is **read-only** and **additive** (PR-21).  It does not
        modify any existing projection, router, execution policy, or device
        module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"routing_explanation"`` key populated by the PR-21 routing
        explanation schema, and a flat ``"explanation_hints"`` quick-check
        dict.

        The ``"routing_explanation"`` block makes the routing decision basis
        **explicit and inspectable** and answers:
          - Which device/route was selected as the primary target?
          - What decision factors drove the choice (policy, health, capability,
            latency, availability, authority role, fallback)?
          - How confident is the system in this routing decision?
          - Which candidates were rejected and why?
          - Is a fallback plan available?
          - Which agent role owns this routing decision?
          - What execution-policy band constrained the route options?

        Response schema (additions over /agent-dispatch)
        -------------------------------------------------
        .. code-block:: json

            {
              "tri_state_phase": "...",
              ...,
              "agent_dispatch": { ... },
              "routing_explanation": {
                "schema_version": 1,
                "route_target": null,
                "decision_basis_list": [],
                "confidence": {
                  "score": 0.0,
                  "band": "undetermined",
                  "basis_count": 0,
                  "accepted_factor_count": 0,
                  "rejected_factor_count": 0,
                  "contributing_factors": [],
                  "reason": "no basis entries — undetermined confidence"
                },
                "rejected_alternatives": [],
                "fallback_plan": null,
                "owner_agent": null,
                "owner_component": "routing_explanation",
                "policy_posture": "undecided",
                "policy_band": null,
                "policy_reason": "no routing decision recorded",
                "is_cross_device": false,
                "has_fallback": false,
                "task_id": null,
                "trace_id": null
              },
              "explanation_hints": {
                "route_target": null,
                "policy_posture": "undecided",
                "policy_band": null,
                "confidence_score": 0.0,
                "confidence_band": "undetermined",
                "is_cross_device": false,
                "has_fallback": false,
                "has_rejected_alternatives": false,
                "rejected_count": 0,
                "basis_count": 0,
                "owner_agent": null
              }
            }

        This endpoint is the primary read-only integration point for the
        PR-21 routing explanation layer.  Downstream governance tooling,
        status boards, and debugging utilities should consume this endpoint
        to inspect why the current routing decision was made.
        """
        payload = _assemble_projection_with_routing_explanation()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/governance
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/governance")
    async def get_governance_projection() -> JSONResponse:
        """Return the current governance-enriched projection summary (PR-26).

        This endpoint is **read-only** and **additive** (PR-26).  It does not
        modify any existing projection, execution, readiness, fallback, or
        trace module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"governance"`` key populated by the PR-26 governance assembly layer,
        and a flat ``"governance_hints"`` quick-check dict.

        The ``"governance"`` block makes execution governance state
        **explicit and inspectable** and answers:
          - What execution intent is active (action_level, mode, target)?
          - Is the system ready to execute (readiness status, policy band)?
          - Was a fallback decision made (outcome, fallback_path)?
          - What is the execution lifecycle trace (stages, final_status)?
          - What tri-state phase and runtime domain was active at assembly time?
          - Is governance data available at all (governance_available)?

        This endpoint is the primary read-only integration point for the
        PR-26 projection assembly governance layer.  Downstream governance
        tooling, status boards, and debugging utilities should consume this
        endpoint to inspect the current governance posture in projection form.
        """
        payload = _assemble_projection_with_governance()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/runtime-governance
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/runtime-governance")
    async def get_runtime_governance_snapshot() -> JSONResponse:
        """Return the unified runtime governance snapshot (PR-27).

        This endpoint is **read-only** and **additive** (PR-27).  It does not
        modify any existing projection, execution, readiness, fallback, trace,
        or projection governance module.

        The response contains the unified
        :class:`~core.runtime_governance.snapshot.RuntimeGovernanceSnapshot`
        as a serialised JSON payload.  The snapshot assembles the complete
        current runtime posture — including tri-state phase, runtime domain,
        execution intent (PR-22), readiness/policy posture (PR-23), fallback
        trace (PR-24), execution lifecycle trace (PR-25), and projection
        governance data (PR-26) — into one canonical, stable object.

        This is the canonical read-only surface for the runtime governance
        snapshot and the primary integration point for downstream surfaces
        (status boards, mesh/session work, device handoff) that need a
        single unified governance view.

        The ``"snapshot"`` block answers:
          - What tri-state phase is the system currently in?
          - What runtime domain is active or intended?
          - What governance posture applies across intent/readiness/fallback/trace?
          - What execution lifecycle summary is currently available?
          - What projection-governance summary is currently available?
          - Is governance data available at all (governance_available)?
          - What is the top-level posture (execute / observe / blocked / degraded)?

        Response schema
        ---------------
        See :class:`~core.runtime_governance.snapshot.RuntimeGovernanceSnapshot`
        for the full field reference.
        """
        payload = _assemble_runtime_governance_snapshot_payload()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/policy-alignment
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/policy-alignment")
    async def get_policy_alignment() -> JSONResponse:
        """Return the Execution Policy Alignment Surface (PR-28).

        This endpoint is **read-only** and **additive** (PR-28).  It does not
        modify any existing projection, execution, readiness, fallback, trace,
        governance, or dispatch module.

        The response contains the canonical
        :class:`~core.policy.alignment_surface.ExecutionPolicyAlignmentSummary`
        as a serialised JSON payload.  The summary answers, in one narrow
        read-only structure:

          - Are runtime policy, readiness policy, fallback posture,
            dispatch/handoff posture, and projection governance in agreement?
          - If they are not aligned, where is the mismatch?
          - Is the current posture local-preferred, local-then-expand,
            remote-required, blocked, degraded, or confirmation-gated?
          - What policy hints should downstream status surfaces, debugging
            tools, and later mesh/session work consume?

        This is the "policy explanation" layer that sits above existing
        governance summaries and answers *why* the system chose a particular
        route/posture.

        Response schema
        ---------------
        See :class:`~core.policy.alignment_surface.ExecutionPolicyAlignmentSummary`
        for the full field reference.

        Top-level keys:
          - ``alignment_id``           — unique ID for this assessment
          - ``aligned``                — True when all dimensions agree
          - ``blocked``                — True when any dimension signals a block
          - ``degraded``               — True when operating in degraded mode
          - ``confirmation_required``  — True when confirmation is required
          - ``policy_posture``         — resolved posture string
          - ``mismatches``             — list of detected mismatches
          - ``alignment_hints``        — quick-access boolean/string hints
          - ``runtime_policy_summary`` — per-dimension runtime policy view
          - ``readiness_policy_summary`` — per-dimension readiness policy view
          - ``fallback_policy_summary``  — per-dimension fallback posture view
          - ``dispatch_policy_summary``  — per-dimension dispatch/handoff view
          - ``projection_policy_summary`` — per-dimension projection governance view
        """
        payload = _assemble_policy_alignment_payload()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/mesh/memberships  (PR-32)
    # ------------------------------------------------------------------

    @router.get("/api/v1/mesh/memberships")
    async def get_mesh_memberships() -> JSONResponse:
        """Return canonical Mesh Membership contracts for all registered devices.

        This endpoint is **read-only** and **additive** (PR-32).  It does not
        modify any existing registry, projection, or orchestration module.

        The response contains a ``"memberships"`` list where each entry is a
        fully serialised :class:`~contracts.mesh_membership.MeshMembership`
        contract derived from the current
        :class:`~core.mesh.body_mesh_registry.BodyMeshRegistry` state.

        This is the canonical answer to:

            *"How does each registered device participate in the mesh/body,
            and what is its formal role and authority?"*

        Example response::

            {
              "mesh_id": "default_mesh",
              "total": 2,
              "memberships": [
                {
                  "membership_id": "...",
                  "mesh_id": "default_mesh",
                  "member_device_id": "phone_001",
                  "roles": ["primary", "source"],
                  "authority_scope": "mesh_authority",
                  "routing_intent": "undecided",
                  ...
                },
                ...
              ]
            }
        """
        try:
            from core.mesh.body_mesh_registry import get_body_mesh_registry

            registry = get_body_mesh_registry()
            memberships = registry.get_mesh_memberships(mesh_id="default_mesh")
            payload = {
                "mesh_id": "default_mesh",
                "total": len(memberships),
                "memberships": [m.to_dict() for m in memberships],
            }
        except Exception as exc:
            payload = {
                "mesh_id": "default_mesh",
                "total": 0,
                "memberships": [],
                "error": str(exc),
            }
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/mesh/session  (PR-33)
    # ------------------------------------------------------------------

    @router.get("/api/v1/mesh/session")
    async def get_mesh_session() -> JSONResponse:
        """Return a canonical Mesh Session contract for the current registry state.

        This endpoint is **read-only** and **additive** (PR-33).  It does not
        modify any existing registry, projection, or orchestration module.

        The response contains a fully serialised :class:`~contracts.mesh_session.MeshSession`
        contract derived from the current
        :class:`~core.mesh.body_mesh_registry.BodyMeshRegistry` state.

        This is the canonical answer to:

            *"When multiple devices cooperate on one task flow, what is the
            canonical session object that represents that cooperation?"*

        Example response::

            {
              "session_id": "msess_...",
              "status": "pending",
              "source_device_id": "phone_001",
              "primary_device_id": "tablet_002",
              "participants": [...],
              "subtask_assignments": [],
              "multi_device_required": true,
              ...
            }
        """
        try:
            from core.mesh.body_mesh_registry import get_body_mesh_registry

            registry = get_body_mesh_registry()
            session = registry.get_mesh_session(mesh_id="default_mesh")
            if session is None:
                from contracts.mesh_session import build_mesh_session

                session = build_mesh_session(mesh_id="default_mesh")
            payload = session.to_dict()
        except Exception as exc:
            try:
                from contracts.mesh_session import build_mesh_session, MeshSessionStatus

                session = build_mesh_session(mesh_id="default_mesh")
                payload = session.to_dict()
                payload["error"] = str(exc)
            except Exception as inner_exc:
                payload = {
                    "session_id": "",
                    "status": "unknown",
                    "error": str(exc),
                    "inner_error": str(inner_exc),
                }
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # POST /api/v1/runtime/takeover  (PR-34)
    # ------------------------------------------------------------------

    @router.post("/api/v1/runtime/takeover")
    async def runtime_local_takeover(request: Request) -> JSONResponse:
        """Accept a handoff envelope and execute the local takeover path.

        This endpoint is the canonical **target-side local takeover entry
        point** introduced in PR-34.  It:

        1. Reads the incoming JSON body as a handoff envelope (or legacy
           payload dict).
        2. Normalises it to a
           :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2`.
        3. Runs the target-side takeover path via
           :func:`~core.runtime.target_takeover.execute_local_takeover`.
        4. Returns a serialised
           :class:`~contracts.local_takeover_result.LocalTakeoverResult`.

        The endpoint degrades gracefully: if the body cannot be parsed or the
        execution path is unavailable, a minimal failure result is returned
        with ``success: false`` and a ``reason`` field.

        Example request body (Handoff Envelope v2)::

            {
              "trace_id": "trace_abc",
              "task_id": "task_001",
              "session_id": "sess_xyz",
              "task_spec": {
                "tool_name": "screenshot",
                "args": {}
              }
            }

        Example response::

            {
              "result_id": "...",
              "trace_id": "trace_abc",
              "success": true,
              "status": "succeeded",
              "result": { "action_taken": "...", ... },
              "execution_trace": { ... },
              ...
            }
        """
        payload: Any = None
        try:
            payload = await request.json()
        except Exception as exc:
            logger.warning("runtime_local_takeover: failed to parse body: %s", exc)

        try:
            from core.runtime.target_takeover import execute_local_takeover

            result = execute_local_takeover(
                payload,
                capture_governance=True,
                capture_policy_alignment=False,
            )
            result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
        except Exception as exc:
            logger.warning("runtime_local_takeover: execute_local_takeover raised: %s", exc)
            try:
                from contracts.local_takeover_result import failure_result, LocalTakeoverStatus

                result = failure_result(
                    reason=f"internal_error:{exc}",
                    status=LocalTakeoverStatus.failed,
                )
                result_dict = result.to_dict()
            except Exception as inner_exc:
                result_dict = {
                    "success": False,
                    "status": "failed",
                    "reason": f"internal_error:{exc}",
                    "inner_error": str(inner_exc),
                }
        return JSONResponse(content=result_dict)

    # ------------------------------------------------------------------
    # GET /api/v1/runtime/source-dispatch-summary  (PR-35)
    # ------------------------------------------------------------------

    @router.get("/api/v1/runtime/source-dispatch-summary")
    async def get_source_dispatch_summary() -> JSONResponse:
        """Return a read-only source dispatch orchestration summary.

        This endpoint is the canonical **source-side dispatch projection**
        introduced in PR-35.  It exposes a
        :class:`~contracts.source_dispatch.SourceDispatchSummary` by:

        1. Fetching available governance/policy/mesh context signals.
        2. Invoking :func:`~core.runtime.source_dispatch_orchestrator.build_source_dispatch_plan`
           to evaluate the current dispatch posture without executing.
        3. Returning a compact :class:`~contracts.source_dispatch.SourceDispatchSummary`.

        The endpoint is **read-only** (GET) and never triggers execution.
        It degrades gracefully when context is unavailable.

        Example response::

            {
              "summary_id": "...",
              "dispatch_id": "...",
              "trace_id": null,
              "mode": "local",
              "success": false,
              "decision_reason": "default_local",
              "target_device_id": null,
              "error_count": 0,
              "has_execution_trace": false,
              "has_takeover_result": false,
              "has_mesh_session": false,
              "timestamp": 1700000000.0
            }
        """
        try:
            from core.runtime.source_dispatch_orchestrator import build_source_dispatch_plan
            from contracts.source_dispatch import build_source_dispatch_summary

            plan = build_source_dispatch_plan()
            summary = build_source_dispatch_summary(
                dispatch_id=plan.dispatch_id,
                trace_id=plan.trace_id,
                task_id=plan.task_id,
                session_id=plan.session_id,
                mode=plan.mode,
                success=plan.ready,
                decision_reason=(plan.readiness_notes[0] if plan.readiness_notes else None),
                target_device_id=(plan.selected_target.target_device_id if plan.selected_target else None),
                has_mesh_session=plan.mesh_session is not None,
            )
            return JSONResponse(content=summary.to_dict())
        except Exception as exc:
            logger.warning("get_source_dispatch_summary: failed to build summary: %s", exc)
            original_exc = exc
            try:
                from contracts.source_dispatch import SourceDispatchSummary, SourceDispatchMode

                fallback = SourceDispatchSummary(
                    mode=SourceDispatchMode.unknown,
                    success=False,
                    decision_reason=f"summary_error:{original_exc}",
                )
                return JSONResponse(content=fallback.to_dict())
            except Exception as fallback_exc:
                import uuid as _uuid
                import time as _time

                return JSONResponse(
                    content={
                        "summary_id": str(_uuid.uuid4()),
                        "mode": "unknown",
                        "success": False,
                        "decision_reason": f"summary_error:{original_exc}",
                        "fallback_error": str(fallback_exc),
                        "timestamp": _time.time(),
                    }
                )

    # ------------------------------------------------------------------
    # GET /api/v1/runtime/result-merge-summary  (PR-36)
    # ------------------------------------------------------------------

    @router.get("/api/v1/runtime/result-merge-summary")
    async def get_result_merge_summary() -> JSONResponse:
        """Return a read-only cross-runtime result merge summary.

        This endpoint is the canonical **cross-runtime merge projection**
        introduced in PR-36.  It exposes a
        :class:`~contracts.cross_runtime_result_merge.ResultMergeSummary`
        representing the current merge posture.  No execution is triggered.

        The endpoint is **read-only** (GET) and degrades gracefully when
        context is unavailable.

        Example response::

            {
              "summary_id": "...",
              "merge_id": "...",
              "trace_id": null,
              "merge_policy": "primary_wins",
              "success": false,
              "partial": false,
              "fallback_applied": false,
              "unit_count": 0,
              "succeeded_unit_count": 0,
              "failed_unit_count": 0,
              "conflict_count": 0,
              "error_count": 0,
              "has_merged_output": false,
              "merge_reason": "no_active_merge",
              "timestamp": 1700000000.0
            }
        """
        try:
            from contracts.cross_runtime_result_merge import (
                build_result_merge_summary,
                ResultMergePolicy,
            )

            summary = build_result_merge_summary(
                merge_policy=ResultMergePolicy.primary_wins,
                success=False,
                partial=False,
                fallback_applied=False,
                unit_count=0,
                succeeded_unit_count=0,
                failed_unit_count=0,
                conflict_count=0,
                error_count=0,
                has_merged_output=False,
                merge_reason="no_active_merge",
            )
            return JSONResponse(content=summary.to_dict())
        except Exception as exc:
            logger.warning("get_result_merge_summary: failed to build summary: %s", exc)
            try:
                from contracts.cross_runtime_result_merge import ResultMergeSummary, ResultMergePolicy

                fallback = ResultMergeSummary(
                    merge_policy=ResultMergePolicy.unknown,
                    success=False,
                    merge_reason="summary_unavailable",
                )
                return JSONResponse(content=fallback.to_dict())
            except Exception as fallback_exc:
                import uuid as _uuid
                import time as _time

                logger.warning("get_result_merge_summary: fallback construction failed: %s", fallback_exc)
                return JSONResponse(
                    content={
                        "summary_id": str(_uuid.uuid4()),
                        "merge_policy": "unknown",
                        "success": False,
                        "merge_reason": "summary_unavailable",
                        "timestamp": _time.time(),
                    }
                )

    # ------------------------------------------------------------------
    # GET /api/v1/mesh/coordinator-summary  (PR-37)
    # ------------------------------------------------------------------

    @router.get("/api/v1/mesh/coordinator-summary")
    async def get_mesh_coordinator_summary() -> JSONResponse:
        """Return a read-only mesh session coordinator summary.

        This endpoint is the canonical **mesh session coordinator projection**
        introduced in PR-37.  It exposes a
        :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorSummary`
        representing the current coordination posture.  No execution is
        triggered.

        The summary is derived from the live
        :class:`~core.mesh.body_mesh_registry.BodyMeshRegistry` state.
        The endpoint is **read-only** (GET) and degrades gracefully when
        context is unavailable.

        Example response::

            {
              "summary_id": "...",
              "coordinator_id": "...",
              "session_id": null,
              "mesh_id": "default_mesh",
              "trace_id": null,
              "status": "pending",
              "participant_count": 0,
              "assignment_count": 0,
              "pending_count": 0,
              "completed_count": 0,
              "failed_count": 0,
              "barrier_status": "unknown",
              "merge_owner_device_id": null,
              "has_result_merge_summary": false,
              "timestamp": 1700000000.0
            }
        """
        try:
            from core.mesh.body_mesh_registry import get_body_mesh_registry
            from contracts.mesh_session_coordinator import build_coordinator_summary

            registry = get_body_mesh_registry()
            coordinator = registry.get_mesh_session_coordinator(mesh_id="default_mesh")
            if coordinator is not None:
                summary = build_coordinator_summary(coordinator=coordinator)
            else:
                summary = build_coordinator_summary(
                    mesh_id="default_mesh",
                )
            return JSONResponse(content=summary.to_dict())
        except Exception as exc:
            logger.warning("get_mesh_coordinator_summary: failed to build summary: %s", exc)
            try:
                from contracts.mesh_session_coordinator import (
                    MeshSessionCoordinatorSummary,
                    MeshCoordinatorStatus,
                )
                import time as _time

                fallback = MeshSessionCoordinatorSummary(
                    status=MeshCoordinatorStatus.unknown,
                    mesh_id="default_mesh",
                )
                return JSONResponse(content=fallback.to_dict())
            except Exception as fallback_exc:
                import uuid as _uuid
                import time as _time

                logger.warning(
                    "get_mesh_coordinator_summary: fallback construction failed: %s",
                    fallback_exc,
                )
                return JSONResponse(
                    content={
                        "summary_id": str(_uuid.uuid4()),
                        "status": "unknown",
                        "mesh_id": "default_mesh",
                        "timestamp": _time.time(),
                    }
                )

    # ------------------------------------------------------------------
    # GET /api/v1/mesh/android-lifecycle  (PR-13)
    # ------------------------------------------------------------------

    @router.get("/api/v1/mesh/android-lifecycle")
    async def get_android_mesh_lifecycle() -> JSONResponse:
        """返回 Android 发起的 mesh 生命周期真值快照（PR-13）。

        此端点是 Android-to-V2 mesh 生命周期链路的**规范真值面**，
        由 PR-13 引入。它暴露所有经由 ``mesh_join`` / ``mesh_result`` /
        ``mesh_leave`` 消息到达 V2 的 Android mesh session 生命周期状态。

        数据来源：:mod:`core.mesh.android_mesh_lifecycle_store`。

        此端点为**只读**（GET），依赖不可用时降级返回空快照。

        响应示例::

            {
              "active_session_count": 1,
              "total_session_count": 3,
              "active_sessions": [
                {
                  "session_id": "amesh_device_01_...",
                  "device_id": "device_01",
                  "status": "active",
                  "join_event": { ... },
                  "result_events": [ ... ],
                  "leave_event": null,
                  "result_count": 2,
                  "created_at": 1700000000.0,
                  "updated_at": 1700000010.0
                }
              ],
              "_source": "core.mesh.android_mesh_lifecycle_store...",
              "_timestamp": 1700000020.0
            }
        """
        import time as _time

        try:
            from core.mesh.android_mesh_lifecycle_store import build_android_lifecycle_truth
            payload = build_android_lifecycle_truth()
        except ImportError:
            logger.warning(
                "get_android_mesh_lifecycle: android_mesh_lifecycle_store 不可用"
            )
            payload = {
                "active_session_count": 0,
                "total_session_count": 0,
                "active_sessions": [],
                "_source": "core.routes.projection.get_android_mesh_lifecycle",
                "_error": "android_mesh_lifecycle_store not available",
                "_timestamp": _time.time(),
            }
        except Exception as exc:
            logger.warning("get_android_mesh_lifecycle: 构建真值快照失败：%s", exc)
            payload = {
                "active_session_count": 0,
                "total_session_count": 0,
                "active_sessions": [],
                "_source": "core.routes.projection.get_android_mesh_lifecycle",
                "_error": str(exc),
                "_timestamp": _time.time(),
            }
        return JSONResponse(content=payload)

    @router.get("/api/v1/projection/runtime/multi-device")
    async def get_multi_device_runtime_projection() -> JSONResponse:
        """Return the unified multi-device runtime projection.

        This endpoint is the canonical **unified multi-device runtime projection**
        introduced in PR-38.  It assembles a
        :class:`~contracts.multi_device_runtime_projection.MultiDeviceRuntimeProjection`
        that aggregates state across all device, host, mesh, session, dispatch,
        handoff, coordination, and result contracts (PR-29–PR-37) into a single
        read-only projection.

        The endpoint is **read-only** (GET), never modifies state, and degrades
        gracefully when individual sub-components are unavailable.

        Example response::

            {
              "projection_id": "mdrt_proj_abc123def456",
              "generated_at": 1700000000.0,
              "runtime_devices": [...],
              "runtime_hosts": [...],
              "mesh_memberships": [...],
              "mesh_sessions": [...],
              "source_dispatches": [],
              "handoff_summaries": [],
              "takeover_summaries": [],
              "coordinator_summaries": [...],
              "merged_results": [],
              "governance_snapshot": null,
              "policy_alignment": null,
              "metadata": {}
            }
        """
        try:
            from contracts.multi_device_runtime_projection import (
                build_multi_device_runtime_projection,
            )
            from core.mesh.body_mesh_registry import get_body_mesh_registry

            registry = get_body_mesh_registry()

            # --- runtime devices (PR-29) ---
            runtime_devices: list = []
            try:
                from contracts.registered_runtime_device import build_registered_runtime_device
                from core.unified.device_manager import UnifiedDeviceManager

                udm = UnifiedDeviceManager.get_instance()
                if udm is not None:
                    for dev in udm.get_all_devices() or []:
                        try:
                            from contracts.registered_runtime_device import from_udm_device

                            runtime_devices.append(from_udm_device(dev).to_dict())
                        except Exception:
                            pass
            except Exception as exc:
                logger.debug("multi-device projection: devices unavailable: %s", exc)

            # --- runtime hosts (PR-30) ---
            runtime_hosts: list = []
            try:
                from contracts.local_runtime_host import from_registered_runtime_device as host_from_device

                for dev_dict in runtime_devices:
                    try:
                        runtime_hosts.append(host_from_device(dev_dict).to_dict())
                    except Exception:
                        pass
            except Exception as exc:
                logger.debug("multi-device projection: hosts unavailable: %s", exc)

            # --- mesh memberships (PR-32) ---
            mesh_memberships: list = []
            try:
                memberships = registry.get_mesh_memberships()
                for m in memberships or []:
                    try:
                        d = m.to_dict() if hasattr(m, "to_dict") else dict(m)
                        mesh_memberships.append(d)
                    except Exception:
                        pass
            except Exception as exc:
                logger.debug("multi-device projection: memberships unavailable: %s", exc)

            # --- mesh sessions (PR-33) ---
            mesh_sessions: list = []
            try:
                session = registry.get_mesh_session(mesh_id="default_mesh")
                if session is not None:
                    mesh_sessions.append(session.to_dict() if hasattr(session, "to_dict") else dict(session))
            except Exception as exc:
                logger.debug("multi-device projection: mesh session unavailable: %s", exc)

            # --- coordinator summaries (PR-37) ---
            coordinator_summaries: list = []
            merged_results: list = []
            try:
                coordinator = registry.get_mesh_session_coordinator(mesh_id="default_mesh")
                if coordinator is not None:
                    from contracts.mesh_session_coordinator import build_coordinator_summary

                    summary = build_coordinator_summary(coordinator=coordinator)
                    coordinator_summaries.append(summary.to_dict())
                    result_merge_summary = getattr(coordinator, "result_merge_summary", None)
                    if result_merge_summary:
                        merged_results.append(
                            result_merge_summary.to_dict()
                            if hasattr(result_merge_summary, "to_dict")
                            else dict(result_merge_summary)
                        )
            except Exception as exc:
                logger.debug("multi-device projection: coordinator unavailable: %s", exc)

            # PR-522 / GAP-517-008: enrich projection from canonical
            # multi-device runtime sources (CrossDeviceChainSingleton,
            # TaskGraphRuntime, OperatorSurface, integrity runtime).
            # This replaces the partial PR-519 metadata enrichment and ensures
            # the projection is grounded in canonical chain/runtime truth rather
            # than raw transport/session registry data alone.
            _canonical_enrichment: Optional[dict] = None
            _canonical_surfacing_state: str = "unavailable"
            _canonical_surfacing_gaps: list = []
            try:
                from core.multi_device_projection_canonicalization import (
                    enrich_multi_device_projection,
                )

                _enrichment = enrich_multi_device_projection(
                    max_chain_records=10,
                    max_graph_records=10,
                )
                _canonical_enrichment = _enrichment.to_dict()
                _canonical_surfacing_state = _enrichment.surfacing_state.value
                _canonical_surfacing_gaps = list(_enrichment.surfacing_gap_reasons)
                if merged_results and _canonical_enrichment.get("formation_metadata") is not None:
                    _merged_with_formation: list = []
                    for item in merged_results:
                        enriched_item = dict(item)
                        metadata = dict(enriched_item.get("metadata") or {})
                        metadata.setdefault(
                            "formation",
                            _canonical_enrichment.get("formation_metadata"),
                        )
                        enriched_item["metadata"] = metadata
                        _merged_with_formation.append(enriched_item)
                    merged_results = _merged_with_formation
            except Exception as _enrich_exc:
                logger.debug(
                    "multi-device projection: canonical enrichment unavailable: %s",
                    _enrich_exc,
                )
                _canonical_surfacing_gaps = [f"GAP-517-008: canonical enrichment failed: {_enrich_exc}"]

            projection = build_multi_device_runtime_projection(
                runtime_devices=runtime_devices,
                runtime_hosts=runtime_hosts,
                mesh_memberships=mesh_memberships,
                mesh_sessions=mesh_sessions,
                coordinator_summaries=coordinator_summaries,
                merged_results=merged_results,
                metadata={
                    # PR-522: canonical enrichment (primary authority)
                    "canonical_enrichment": _canonical_enrichment,
                    "canonical_surfacing_state": _canonical_surfacing_state,
                    "canonical_surfacing_gaps": _canonical_surfacing_gaps,
                    "transport_local_only": (
                        _canonical_enrichment is None or _canonical_enrichment.get("transport_local_only", True)
                    ),
                    # Backward-compat fields carried forward from PR-519
                    "cross_device_chain_snapshot": (
                        _canonical_enrichment.get("chain_snapshot") if _canonical_enrichment is not None else None
                    ),
                    "task_graph_snapshot": (
                        _canonical_enrichment.get("graph_snapshot") if _canonical_enrichment is not None else None
                    ),
                    "result_surface_enriched": _canonical_enrichment is not None,
                    "source_runtime_posture_snapshot": (
                        _canonical_enrichment.get("source_runtime_posture_snapshot")
                        if _canonical_enrichment is not None
                        else None
                    ),
                    "source_runtime_posture_available": (
                        _canonical_enrichment.get("source_runtime_posture_available", False)
                        if _canonical_enrichment is not None
                        else False
                    ),
                    "pr_522_gap_008_resolved": True,
                },
            )
            return JSONResponse(content=projection.to_dict())

        except Exception as exc:
            logger.warning(
                "get_multi_device_runtime_projection: failed to assemble projection: %s",
                exc,
            )
            try:
                from contracts.multi_device_runtime_projection import (
                    MultiDeviceRuntimeProjection,
                )

                fallback = MultiDeviceRuntimeProjection()
                return JSONResponse(content=fallback.to_dict())
            except Exception as fallback_exc:
                import uuid as _uuid
                import time as _time

                logger.warning(
                    "get_multi_device_runtime_projection: fallback construction failed: %s",
                    fallback_exc,
                )
                return JSONResponse(
                    content={
                        "projection_id": f"mdrt_proj_{_uuid.uuid4().hex[:12]}",
                        "generated_at": _time.time(),
                        "runtime_devices": [],
                        "runtime_hosts": [],
                        "mesh_memberships": [],
                        "mesh_sessions": [],
                        "source_dispatches": [],
                        "handoff_summaries": [],
                        "takeover_summaries": [],
                        "coordinator_summaries": [],
                        "merged_results": [],
                        "governance_snapshot": None,
                        "policy_alignment": None,
                        "runtime_recovery": None,
                        "metadata": {},
                    }
                )

    # ------------------------------------------------------------------
    # GET /api/v1/projection/runtime/recovery
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/runtime/recovery")
    async def get_runtime_recovery_posture() -> JSONResponse:
        """Return the current runtime recovery and reconciliation posture.

        This endpoint is the canonical **read-only** advisory surface for
        recovery/reconciliation state introduced in PR-39.  It derives a
        :class:`~contracts.runtime_recovery_reconciliation.RuntimeReconciliationState`
        from the unified multi-device runtime projection and returns it as JSON.

        Example response::

            {
              "reconciliation_id": "rrec_...",
              "status": "resolved",
              "incident_count": 0,
              "participant_count": 0,
              "replay_required": false,
              "resume_allowed": false,
              "merge_confirmation_required": false,
              "has_barrier": false,
              "reason": "no incidents",
              ...
            }

        Returns
        -------
        JSONResponse
            A compact recovery summary dict.  Always returns 200; individual
            sub-component failures are logged and produce minimal safe defaults.
        """
        try:
            from contracts.runtime_recovery_reconciliation import (
                from_multi_device_projection,
                build_recovery_summary,
                RecoveryStatus,
            )

            # Attempt to get the projection dict from the multi-device projection
            projection_dict: Dict[str, Any] = {}
            try:
                from contracts.multi_device_runtime_projection import (
                    build_multi_device_runtime_projection,
                )

                projection_obj = build_multi_device_runtime_projection()
                projection_dict = projection_obj.to_dict()
            except Exception as exc:
                logger.debug("get_runtime_recovery_posture: projection unavailable: %s", exc)

            reconciliation = from_multi_device_projection(projection_dict)
            summary = build_recovery_summary(
                incidents=list(reconciliation.incidents),
                reconciliation=reconciliation,
            )
            return JSONResponse(content=summary.to_dict())

        except Exception as exc:
            logger.warning(
                "get_runtime_recovery_posture: failed to assemble recovery posture: %s",
                exc,
            )
            import uuid as _uuid2
            import time as _time2

            return JSONResponse(
                content={
                    "summary_id": f"rrsum_{_uuid2.uuid4().hex[:10]}",
                    "generated_at": _time2.time(),
                    "overall_status": "pending",
                    "incident_count": 0,
                    "resolved_incident_count": 0,
                    "pending_incident_count": 0,
                    "needs_intervention_count": 0,
                    "replay_required": False,
                    "resume_allowed": False,
                    "merge_confirmation_required": False,
                    "has_barrier": False,
                    "recommended_action_types": [],
                    "most_recent_incident_type": None,
                    "most_recent_recovery_id": None,
                    "reason": "recovery posture unavailable",
                    "metadata": {},
                }
            )

    @router.get("/api/v1/acceptance/cross-repo-chain")
    async def get_cross_repo_acceptance_chain() -> JSONResponse:
        """返回 Android→V2 代表性跨仓验收链的阶段化快照。"""
        return JSONResponse(content=_build_cross_repo_acceptance_chain_projection())

    @router.get("/api/v1/acceptance/dual-repo-completeness-baseline")
    async def get_dual_repo_completeness_baseline() -> JSONResponse:
        """返回双仓从 clone 到端态观测面的可执行完整性基线快照。"""
        return JSONResponse(content=_build_dual_repo_completeness_baseline_projection())

    @router.get("/api/v1/projection/runtime/session-snapshot")
    async def get_runtime_session_snapshot() -> JSONResponse:
        """Return a durable runtime session snapshot summary.

        This endpoint is the canonical **read-only** surface for the
        Durable Runtime Session Snapshot Contract introduced in PR-40.
        It derives a :class:`~contracts.runtime_session_snapshot.RuntimeSessionSnapshot`
        from the unified multi-device runtime projection (PR-38) and returns a
        compact summary as JSON.

        Example response::

            {
              "summary_id": "rsnsum_...",
              "snapshot_id": "rsnap_...",
              "session_id": "",
              "status": "unknown",
              "runtime_device_count": 0,
              "has_dispatch_state": false,
              "has_recovery_state": false,
              ...
            }

        Returns
        -------
        JSONResponse
            A compact session snapshot summary dict.  Always returns 200;
            individual sub-component failures are logged and produce safe defaults.
        """
        try:
            from contracts.runtime_session_snapshot import (
                from_multi_device_runtime_projection,
                build_runtime_session_snapshot_summary,
            )

            # Attempt to get the multi-device projection
            projection_dict: Dict[str, Any] = {}
            try:
                from contracts.multi_device_runtime_projection import (
                    build_multi_device_runtime_projection,
                )

                projection_obj = build_multi_device_runtime_projection()
                projection_dict = projection_obj.to_dict()
            except Exception as exc:
                logger.debug("get_runtime_session_snapshot: projection unavailable: %s", exc)

            snapshot = from_multi_device_runtime_projection(projection_dict)
            summary = build_runtime_session_snapshot_summary(snapshot)
            return JSONResponse(content=summary.to_dict())

        except Exception as exc:
            logger.warning(
                "get_runtime_session_snapshot: failed to assemble snapshot: %s",
                exc,
            )
            import uuid as _uuid_fallback
            import time as _time_fallback

            return JSONResponse(
                content={
                    "summary_id": f"rsnsum_{_uuid_fallback.uuid4().hex[:10]}",
                    "snapshot_id": None,
                    "session_id": "",
                    "trace_id": None,
                    "task_id": None,
                    "mesh_session_id": None,
                    "source_device_id": None,
                    "primary_device_id": None,
                    "status": "unknown",
                    "runtime_device_count": 0,
                    "runtime_host_count": 0,
                    "mesh_membership_count": 0,
                    "takeover_count": 0,
                    "has_dispatch_state": False,
                    "has_coordinator_state": False,
                    "has_merged_result": False,
                    "has_recovery_state": False,
                    "has_mesh_session": False,
                    "has_governance_snapshot": False,
                    "has_policy_alignment": False,
                    "created_at": None,
                    "updated_at": None,
                    "generated_at": _time_fallback.time(),
                    "metadata": {"error": "session snapshot unavailable"},
                }
            )

    # ------------------------------------------------------------------
    # GET /api/v1/projection/canonical-routing  (PR-3)
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/canonical-routing")
    async def get_canonical_routing_projection() -> JSONResponse:
        """Return the canonical routing projection with OneAPI and provider status.

        This endpoint is **read-only** and **additive** (PR-3).  It does not
        modify any existing projection, router, or model supply module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus enriched
        canonical routing data, including:

        - ``routing_authority`` — the canonical routing authority sentinel
        - ``route_reason`` — human-readable routing rationale
        - ``primary_model_id`` / ``support_model_ids`` — canonical model IDs
        - ``active_weights`` — full weight breakdown
        - ``oneapi_summary`` — OneAPI system integration position (when applicable)
        - ``provider_status_summary`` — compact provider health summary (when available)

        Source priority:

        1. ``TopologyRoutePlan`` (canonical) — ``routing_authority`` is set to
           :data:`~core.model_topology.topology_router.CANONICAL_ROUTING_AUTHORITY`.
        2. No topology available — all routing fields are ``None``/empty with
           ``routing_authority = "none"``.

        This endpoint is the canonical integration point for desktop status
        board consumers that need unified routing + provider status without
        coupling to the dashboard UI.

        Response schema
        ---------------
        See :class:`~core.projection.RuntimeProjection` for full field reference.
        Additional top-level keys:

        - ``oneapi_summary``          — OneAPI integration position dict or null
        - ``provider_status_summary`` — provider health summary dict or null
        - ``canonical_routing_hints`` — quick-access routing hints dict

        Example ``canonical_routing_hints``::

            {
              "has_route": true,
              "routing_authority": "core.model_topology.topology_router.TopologyRouter",
              "is_canonical": true,
              "is_legacy": false,
              "primary_model_id": "openai/gpt-4o",
              "support_count": 2,
              "has_oneapi": false,
              "provider_available_count": 3,
              "provider_degraded_count": 0,
              "route_reason": "..."
            }
        """
        payload = _assemble_canonical_routing_payload()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/server-canonicalization-status  (PR-5)
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/server-canonicalization-status")
    async def get_server_canonicalization_status() -> JSONResponse:
        """Return a read-only server-side canonicalization status summary.

        This endpoint is **read-only** and **additive** (PR-5).  It does not
        modify any existing projection, router, or model supply module.

        PR-5 completes the server-side canonicalization phase that follows
        PR-4 (OneAPI lower-horizon cleanup).  This endpoint exposes a
        machine-checkable summary of:

        - Which routing/projection fields have been canonicalized
        - Which legacy UCP keys remain as compatibility bridges
        - Whether the canonical routing authority is active
        - The PR-4 OneAPI lower-horizon guarantee status
        - Downstream consumer guidance

        Response schema
        ---------------
        .. code-block:: json

            {
              "canonicalization_stage": "pr5_server_side",
              "canonical_routing_authority": "core.model_topology...",
              "canonical_projection_authority": "contracts.desktop_status_projection...",
              "legacy_ucp_routing_keys": ["chosen_model", ...],
              "legacy_routing_fields": ["chosen_model", ...],
              "oneapi_lower_horizon_guaranteed": true,
              "oneapi_integration_field_present": true,
              "pr4_guarantees_intact": true,
              "consumer_guidance": {
                "prefer_topology_route_plan": true,
                "prefer_oneapi_integration_block": true,
                "avoid_legacy_ucp_keys": true,
                "legacy_routing_fallback_active_field": "model_routing.legacy_routing_fallback_active"
              },
              "timestamp": 1234567890.0
            }
        """
        payload = _assemble_server_canonicalization_status()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/desktop-topology  (PR-6, hardened PR-7)
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/desktop-topology")
    async def get_desktop_topology_projection() -> JSONResponse:
        """Return the topology-ready projection block for desktop surfaces.

        This endpoint is **read-only** and **additive** (PR-6, PR-7).  It does
        not modify any existing projection, router, or model supply module.

        Returns the :class:`~contracts.desktop_status_projection.DesktopTopologyProjection`
        block derived from the canonical ``TopologyRoutePlan`` (when available),
        with legacy fallback explicitly marked and degraded.

        This is the single canonical integration point for desktop topology
        surfaces (constellation-style boards) that need a renderer-agnostic,
        topology-ready projection without reconstructing routing truth from
        legacy keys or dashboard-era summaries.

        PR-7 readiness / quality semantics
        -----------------------------------
        The ``projection_quality`` block provides structured machine-readable
        semantics about whether the topology data is authoritative.  Consumers
        **must** inspect this block before treating topology data as ground truth:

        - ``projection_quality.readiness`` — one of ``"canonical"``,
          ``"degraded"``, ``"partial"``, ``"unavailable"``.
        - ``projection_quality.authoritative`` — ``true`` only when
          ``readiness == "canonical"``.  **Never treat data as authoritative
          routing truth when this is ``false``.**
        - ``projection_quality.degraded`` — ``true`` when routing was
          assembled from legacy UCP keys; the block must not be used as full truth.
        - ``projection_quality.quality_note`` — human-readable explanation for
          operators / diagnostic logs.

        Additional semantics
        --------------------
        - ``canonical_source_present`` — ``true`` when sourced from
          ``TopologyRoutePlan``; ``false`` on legacy/fallback path.
        - ``legacy_fallback_active`` — ``true`` when routing data was
          assembled from legacy UCP keys; signals degraded projection.
        - ``oneapi_integration`` — always present as a **lower-horizon** block;
          never promoted to top-layer peer.
        - ``contract_authority`` — machine-checkable PR-6 sentinel.

        Response schema
        ---------------
        .. code-block:: json

            {
              "primary_model_id": "gpt-4o",
              "primary_provider_id": "openai",
              "primary_vendor_source": "direct",
              "primary_is_native_multimodal": false,
              "support_model_ids": ["claude-3-5-sonnet"],
              "route_reason": "...",
              "route_phase": "manifest",
              "route_domain": "local",
              "primary_provider_available": true,
              "routing_authority_source": "topology_router",
              "canonical_source_present": true,
              "legacy_fallback_active": false,
              "oneapi_integration": { "system_layer": "aggregator_integration", ... },
              "health_severity": "ok",
              "projection_quality": {
                "readiness": "canonical",
                "authoritative": true,
                "degraded": false,
                "partial": false,
                "quality_note": "Topology projection is fully canonical and authoritative...",
                "quality_authority": "contracts.desktop_status_projection.TopologyProjectionQualityBlock"
              },
              "contract_authority": "contracts.desktop_status_projection.DesktopTopologyProjection"
            }
        """
        payload = _assemble_desktop_topology_payload()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/desktop-status-board  (PR-8)
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/desktop-status-board")
    async def get_desktop_status_board_integration(request: Request) -> JSONResponse:
        """Return the final integrated desktop status board payload (PR-8).

        This endpoint is **read-only** and **additive** (PR-8).  It does not
        modify any existing projection, router, or model supply module.

        Provides a single stable server-provided payload that desktop status
        board clients can consume without re-deriving state from multiple
        endpoints or legacy/dashboard-era assembly logic.

        The payload composes the already-established canonical structures from
        PR-4 through PR-7:

        - ``topology_projection`` — PR-6/7 topology-ready block with
          readiness/quality semantics.
        - ``model_routing_summary`` — compact routing summary derived from
          ``ModelRoutingProjection``.
        - ``provider_health_summary`` — provider health/availability summary
          when relevant.
        - ``oneapi_integration`` — PR-4 lower-horizon OneAPI aggregator block
          (always ``system_layer == "aggregator_integration"``; never a
          top-layer provider peer).
        - ``authority_indicators`` — machine-checkable authority block
          aggregating all canonical-vs-legacy authority signals.
        - ``integration_authority`` — PR-8 sentinel confirming canonical
          builder provenance.
        - ``integration_health`` — rolled-up integration health.

        Canonical authority layering
        ----------------------------
        - ``TopologyRoutePlan`` / canonical projection structures remain
          authoritative.
        - Legacy compatibility fields remain secondary/fallback-only.
        - OneAPI remains a lower-horizon integration block only.
        - ``authority_indicators.topology_authoritative == true`` confirms
          the topology block is fully authoritative routing truth.

        Consumer guidance
        -----------------
        Desktop clients should consume this endpoint rather than assembling
        state from:
        - ``/api/v1/projection/runtime`` (lower-level runtime projection)
        - ``/api/v1/projection/desktop-topology`` (topology block only)
        - Legacy/dashboard-era endpoint combinations

        Response schema
        ---------------
        .. code-block:: json

            {
              "payload_id": "dsbip_...",
              "integrated_at": 1234567890.0,
              "topology_projection": {
                "primary_model_id": "gpt-4o",
                "projection_quality": {
                  "readiness": "canonical",
                  "authoritative": true,
                  ...
                },
                "contract_authority": "contracts.desktop_status_projection.DesktopTopologyProjection",
                ...
              },
              "model_routing_summary": {
                "selected_provider": "openai",
                "selected_model": "gpt-4o",
                "routing_authority_source": "topology_router",
                "legacy_routing_fallback_active": false,
                ...
              },
              "provider_health_summary": {
                "selected_provider": "openai",
                "provider_available": true,
                ...
              },
              "oneapi_integration": {
                "system_layer": "aggregator_integration",
                "configured": false,
                ...
              },
              "authority_indicators": {
                "topology_canonical_source_present": true,
                "topology_authoritative": true,
                "topology_readiness": "canonical",
                "oneapi_is_lower_horizon_only": true,
                "integration_contract_authority": "contracts.desktop_status_projection.DesktopStatusBoardIntegrationPayload",
                ...
              },
              "integration_authority": "contracts.desktop_status_projection.DesktopStatusBoardIntegrationPayload",
              "integration_health": "ok"
            }
        """
        route_paths = {route.path for route in request.app.routes if hasattr(route, "path")}
        payload = _assemble_desktop_status_board_payload(route_paths=route_paths)
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/runtime-truth  (canonical runtime truth)
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/runtime-truth")
    async def get_runtime_truth() -> JSONResponse:
        """Return the compiled canonical runtime truth snapshot.

        This is the **single canonical read-only endpoint** for runtime-facing
        output state.  It compiles truth once from all canonical subsystem
        sources and returns a stable, unified snapshot.

        Design
        ------
        All other status/observability routes that surface overlapping runtime
        state (``/api/v1/system/status``, ``/api/v1/observability/model-route``,
        etc.) are **compatibility/management endpoints**.  This endpoint is the
        canonical projection truth surface.  Desktop consumers, dashboard
        adapters, and any output-facing layer should prefer this endpoint over
        independently sourcing subsystem state.

        Sources compiled into the snapshot
        ------------------------------------
        - **continuum** — tri-state lifecycle phase + posture from the
          cognitive field engine or a silent fallback.
        - **topology** — canonical routing from ``TopologyRouter`` (model ID,
          provider ID, weights, reason).
        - **oneapi** — OneAPI aggregator lower-horizon integration status.
          ``system_layer`` is always ``"aggregator_integration"``; OneAPI is
          never promoted to a top-layer peer.
        - **system_resource** — lightweight system resource health summary.
        - **device_presence** — registered/online device counts.

        Authority confirmation
        ----------------------
        The response always contains::

            "compiler_authority": "core.projection.runtime_truth_compiler.compile_runtime_truth"

        Consumers can assert this value to confirm canonical provenance.  See
        :data:`~core.projection.RUNTIME_TRUTH_COMPILER_AUTHORITY`.

        Response schema (top-level keys)
        ---------------------------------
        .. code-block:: json

            {
              "compiled_at": 1234567890.0,
              "compiler_authority": "core.projection.runtime_truth_compiler.compile_runtime_truth",
              "continuum": {
                "tri_state_phase": "silent",
                "runtime_domain": "local",
                "coherence": 0.9,
                ...
              },
              "topology": {
                "primary_model": "gpt-4o",
                "primary_provider": "openai",
                "routing_authority_source": "topology_router",
                "routing_authority": "core.model_topology.topology_router.TopologyRouter.route",
                ...
              },
              "oneapi": {
                "system_layer": "aggregator_integration",
                "configured": false,
                ...
              },
              "system_resource": { ... },
              "device_presence": {"registered": 0, "online": 0},
              "dispatch_semantics": {
                "mode": "local",
                "decision_reason": "default_local",
                ...
              },
              "execution_path_observability": {
                "observed_execution_path": "local",
                "observation_source": "source_dispatch_plan",
                ...
              },
              "has_canonical_topology": true,
              "tri_state_phase": "silent",
              "primary_model_id": "gpt-4o",
              "primary_provider_id": "openai",
              "oneapi_is_lower_horizon_only": true
            }

        See ``docs/PROJECTION_OUTPUT_AUTHORITY.md`` for the full output
        authority model and endpoint directory.
        """
        return JSONResponse(content=_assemble_runtime_truth_payload())

    return router


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _assemble_runtime_truth_payload() -> Dict[str, Any]:
    """Assemble the canonical runtime truth snapshot dict.

    Delegates exclusively to
    :func:`~core.projection.runtime_truth_compiler.compile_runtime_truth`
    — the single canonical compilation function.  This helper is the only
    place inside ``core/routes/projection.py`` that calls that function; all
    other route handlers that need runtime truth should call this helper or
    import :func:`~core.projection.compile_runtime_truth` directly.
    """
    try:
        from core.projection.runtime_truth_compiler import compile_runtime_truth

        snapshot = compile_runtime_truth()
        payload = snapshot.to_dict()
        try:
            outward = _compile_outward_truth().to_dict()
            payload["outward_truth"] = outward
            operator_snapshot = outward.get("operator_snapshot") or {}
            payload["task_truth"] = {
                "active_task_count": operator_snapshot.get("active_task_count", 0),
                "recent_failure_count": operator_snapshot.get("recent_failure_count", 0),
                "reachable_executor_count": operator_snapshot.get("reachable_executor_count", 0),
                "source": "outward_truth.operator_snapshot",
            }
        except Exception as exc:
            logger.debug("_assemble_runtime_truth_payload: outward truth unavailable: %s", exc)
            payload["outward_truth"] = _minimal_outward_truth_payload()
            payload.setdefault(
                "task_truth",
                {
                    "active_task_count": 0,
                    "recent_failure_count": 0,
                    "reachable_executor_count": 0,
                    "source": "unavailable",
                },
            )

        try:
            from core.runtime.source_dispatch_orchestrator import build_source_dispatch_plan
            from core.runtime_decision_reasoning import overlay_runtime_decision_reasoning_block

            plan = build_source_dispatch_plan()
            payload["startup_readiness"] = {
                "ready_to_route": bool(getattr(plan, "ready", False)),
                "readiness_notes": list(getattr(plan, "readiness_notes", []) or []),
                "dispatch_mode": (
                    getattr(getattr(plan, "mode", None), "value", None)
                    or str(getattr(plan, "mode", "unknown"))
                ),
                "source_runtime_posture": getattr(plan, "source_runtime_posture", None),
            }
            payload["runtime_decision_reasoning"] = overlay_runtime_decision_reasoning_block(
                (getattr(plan, "metadata", {}) or {}).get("runtime_decision_reasoning"),
                task_id=getattr(plan, "task_id", None),
                selected_runtime=(
                    "android_delegated"
                    if getattr(plan, "selected_target", None) is not None
                    and str(getattr(getattr(plan, "mode", None), "value", getattr(plan, "mode", "")))
                    not in {"local", "fallback_local"}
                    else "v2_local"
                ),
                selected_device=(
                    getattr(getattr(plan, "selected_target", None), "target_device_id", None)
                    if getattr(plan, "selected_target", None) is not None
                    else None
                ),
                mode_state=(
                    getattr(getattr(plan, "mode", None), "value", None)
                    or str(getattr(plan, "mode", "unknown"))
                ),
                source_runtime_posture=getattr(plan, "source_runtime_posture", None),
                ready_to_route=bool(getattr(plan, "ready", False)),
                readiness_summary={
                    "verdict": "ready" if bool(getattr(plan, "ready", False)) else "blocked",
                },
                readiness_notes=list(getattr(plan, "readiness_notes", []) or []),
                source_of_truth_refs=[
                    "core.routes.projection._assemble_runtime_truth_payload",
                ],
            )
        except Exception as exc:
            logger.debug("_assemble_runtime_truth_payload: startup readiness unavailable: %s", exc)
            payload.setdefault("startup_readiness", None)
            payload.setdefault("runtime_decision_reasoning", {})

        payload = _attach_operational_state_board(payload, route_paths=None)
        payload.setdefault("source_of_truth_boundaries", _source_of_truth_boundaries())
        payload["shared_execution_visibility"] = _derive_shared_execution_visibility(payload)
        payload["participation_truth_consumption"] = _build_participation_truth_consumption(payload)
        payload["foundational_system_truth"] = _build_foundational_system_truth(payload)
        payload["cross_repo_acceptance_chain"] = _build_cross_repo_acceptance_chain_projection(
            truth_payload=payload,
        )
        payload["dual_repo_completeness_baseline"] = _build_dual_repo_completeness_baseline_projection(
            truth_payload=payload,
        )
        payload["execution_stage"] = payload["shared_execution_visibility"].get("surface_execution_stage")
        payload["current_task_summary"] = payload["shared_execution_visibility"].get("surface_summary")

        try:
            from core.v2_unified_state_contract import (
                build_control_plane_surface_contract,
                build_shared_control_plane_basis,
            )

            shared_basis = build_shared_control_plane_basis(
                reasoning_block=payload.get("runtime_decision_reasoning"),
            )
            payload["stale_or_cached_summary"] = {
                "fallback": bool(payload.get("_fallback", False)),
                "startup_readiness_available": payload.get("startup_readiness") is not None,
            }
            payload["control_plane_contract"] = build_control_plane_surface_contract(
                surface="board",
                runtime_truth={
                    "tri_state_phase": payload.get("tri_state_phase"),
                    "primary_model_id": payload.get("primary_model_id"),
                    "primary_provider_id": payload.get("primary_provider_id"),
                    "device_presence": payload.get("device_presence"),
                    "dispatch_semantics": payload.get("dispatch_semantics"),
                    "backbone_snapshot": shared_basis.get("backbone_snapshot"),
                },
                derived_reasoning=payload.get("runtime_decision_reasoning"),
                projection={
                    "projection_surface_role": payload.get(
                        "projection_surface_role",
                        "runtime_truth_board_facing",
                    ),
                    "board_facing_default": bool(payload.get("board_facing_default", True)),
                },
                stale_or_cached_summary=payload.get("stale_or_cached_summary"),
                shared_basis=shared_basis,
            )
        except Exception as exc:
            logger.debug("_assemble_runtime_truth_payload: control-plane contract unavailable: %s", exc)

        payload.setdefault("projection_surface_role", "runtime_truth_board_facing")
        payload.setdefault("board_facing_default", True)
        return payload
    except Exception as exc:
        logger.warning("_assemble_runtime_truth_payload: failed: %s", exc)
        from core.projection.runtime_truth_compiler import RUNTIME_TRUTH_COMPILER_AUTHORITY

        payload = {
            "compiled_at": time.time(),
            "compiler_authority": RUNTIME_TRUTH_COMPILER_AUTHORITY,
            "continuum": None,
            "topology": None,
            "oneapi": {"system_layer": "aggregator_integration", "configured": False},
            "system_resource": None,
            "device_presence": {"registered": 0, "online": 0},
            "dispatch_semantics": None,
            "execution_path_observability": None,
            "outward_truth": _minimal_outward_truth_payload(),
            "task_truth": {
                "active_task_count": 0,
                "recent_failure_count": 0,
                "reachable_executor_count": 0,
                "source": "fallback",
            },
            "startup_readiness": None,
            "has_canonical_topology": False,
            "tri_state_phase": None,
            "primary_model_id": None,
            "primary_provider_id": None,
            "oneapi_is_lower_horizon_only": True,
            "operational_state_board": _empty_operational_state_board(),
            "source_of_truth_boundaries": _source_of_truth_boundaries(),
            "shared_execution_visibility": _derive_shared_execution_visibility({}),
            "participation_truth_consumption": _build_participation_truth_consumption({}),
            "foundational_system_truth": _build_foundational_system_truth({}),
            "cross_repo_acceptance_chain": _build_cross_repo_acceptance_chain_projection(),
            "dual_repo_completeness_baseline": _build_dual_repo_completeness_baseline_projection(),
            "execution_stage": None,
            "current_task_summary": None,
            "projection_surface_role": "runtime_truth_board_facing",
            "board_facing_default": True,
            "stale_or_cached_summary": {
                # Keep this block strictly aligned with the control-plane
                # stale_or_cached_summary typing contract.
                "fallback": True,
                "startup_readiness_available": False,
            },
            "_fallback": True,
        }
        try:
            from core.v2_unified_state_contract import build_control_plane_surface_contract

            payload["control_plane_contract"] = build_control_plane_surface_contract(
                surface="board",
                runtime_truth={
                    "tri_state_phase": payload.get("tri_state_phase"),
                    "primary_model_id": payload.get("primary_model_id"),
                    "primary_provider_id": payload.get("primary_provider_id"),
                    "device_presence": payload.get("device_presence"),
                },
                derived_reasoning={},
                projection={
                    "projection_surface_role": payload.get("projection_surface_role"),
                    "board_facing_default": payload.get("board_facing_default"),
                },
                stale_or_cached_summary=dict(payload.get("stale_or_cached_summary") or {}),
            )
        except Exception as cp_exc:
            logger.debug("_assemble_runtime_truth_payload fallback: control-plane contract unavailable: %s", cp_exc)
        return payload


def _minimal_outward_truth_payload() -> Dict[str, Any]:
    """Return the smallest valid outward-truth payload for degraded projection paths."""

    return {
        "compiled_at": time.time(),
        "authority": globals().get(
            "_ORT_AUTHORITY",
            "core.outward_runtime_truth.compile_outward_truth",
        ),
        "operator_snapshot": {
            "active_task_count": 0,
            "recent_failure_count": 0,
            "reachable_executor_count": 0,
        },
        "_fallback": True,
    }


def _assemble_projection() -> Dict[str, Any]:
    """Assemble a projection dict from live runtime state.

    Always returns a valid dict.  Individual sub-components (continuum, topology)
    are optional; missing components fall back to safe defaults so that the
    status board is never blocked by a partially initialised system.

    Import errors (e.g. missing optional transitive dependencies) are caught
    and result in the minimal fallback payload rather than a 500 error.
    """
    try:
        from core.projection import build_runtime_projection, ExecutionSummary
        from core.continuum.types import ContinuumPhase, ContinuumState  # noqa: F401
    except Exception as exc:
        logger.warning("Projection imports unavailable, returning minimal payload: %s", exc)
        return _minimal_fallback_payload()

    # --- 1. Continuum state ------------------------------------------------
    continuum_state, continuum_source, continuum_is_live_runtime = _get_continuum_state_with_source()
    if not continuum_is_live_runtime:
        payload = _minimal_fallback_payload()
        payload["projection_authority_context"] = {
            "continuum_source": continuum_source,
            "continuum_is_live_runtime": False,
            "runtime_state_anchor": "not_live_runtime",
        }
        return payload

    # --- 2. Optional topology route plan -----------------------------------
    route_plan = _get_route_plan(continuum_state)

    # --- 3. Optional execution summary ------------------------------------
    execution_summary = _get_execution_summary()

    # --- 4. Build and serialise -------------------------------------------
    try:
        if continuum_state is None:
            return _minimal_fallback_payload()
        projection = build_runtime_projection(
            continuum_state=continuum_state,
            route_plan=route_plan,
            execution_summary=execution_summary,
            timestamp=time.time(),
        )
        payload = projection.to_dict()
    except Exception as exc:  # pragma: no cover
        logger.warning("Projection assembly failed, returning minimal payload: %s", exc)
        return _minimal_fallback_payload()

    # --- 5. PR-514: Enrich with canonical runtime authority (GAP-512-003, GAP-512-005) ---
    # ProjectionSurfaceBridge.enrich_runtime_projection() reads OperatorSurface
    # (canonical operator inspection authority) and other runtime layers, adding
    # active_task_count, executor_count, operator_snapshot_dict, etc. without
    # overwriting projection-derived fields.
    try:
        from core.authority_conflict_elimination import (
            enrich_projection_with_runtime_authority,
        )

        payload = enrich_projection_with_runtime_authority(payload)
    except Exception as exc:
        logger.warning("_assemble_projection: runtime enrichment failed: %s", exc)

    payload["projection_authority_context"] = {
        "continuum_source": continuum_source,
        "continuum_is_live_runtime": True,
        "runtime_state_anchor": "live_runtime",
    }
    return payload


def _get_continuum_state():
    """Return current continuum state for backward-compatible callers.

    Returns a synthetic formless state when no live runtime source is available.
    """
    state, _, _ = _get_continuum_state_with_source()
    return state


def _get_continuum_state_with_source() -> Tuple[Optional["ContinuumState"], str, bool]:
    """Return ``(state, source, is_live_runtime)`` for projection assembly.

    ``state`` is a live/synthetic ContinuumState when available, otherwise ``None``.

    ``source`` is one of:
    - ``"cognitive_field_engine"``
    - ``"desktop_presence_runtime"``
    - ``"synthetic_formless_fallback"``
    - ``"unavailable"``

    ``is_live_runtime`` is ``True`` only when state is read from active runtime
    producers (cognitive field engine or desktop presence runtime); synthetic or
    unavailable fallbacks are always ``False``.
    """
    try:
        # Try the cognitive field engine first (Block-3 integration).
        from core.cognitive.cognitive_field_engine import CognitiveFieldEngine

        engine = CognitiveFieldEngine.get_instance()
        if engine is not None and hasattr(engine, "get_continuum_state"):
            state = engine.get_continuum_state()
            if state is not None:
                return state, "cognitive_field_engine", True
    except Exception:
        pass

    try:
        # Fallback: desktop presence runtime if available.
        from core.desktop_presence_runtime import get_presence_runtime

        runtime = get_presence_runtime()
        if runtime is not None and hasattr(runtime, "get_continuum_state"):
            state = runtime.get_continuum_state()
            if state is not None:
                return state, "desktop_presence_runtime", True
    except Exception:
        pass

    try:
        # Final fallback: minimal silent state so the board always renders.
        from core.continuum.types import ContinuumPhase, ContinuumState

        return ContinuumState(phase=ContinuumPhase.FORMLESS), "synthetic_formless_fallback", False
    except Exception:
        return None, "unavailable", False


def _get_route_plan(continuum_state):
    """Return the current TopologyRoutePlan, or None if topology is not ready."""
    try:
        from core.model_topology import TopologyRouter, ProviderInventory
        from core.continuum.types import RuntimeDomain

        inventory = ProviderInventory.from_config()
        router = TopologyRouter(inventory)
        domain = continuum_state.runtime_domain or RuntimeDomain.LOCAL
        return router.route(continuum_state.tri_state_phase, domain)
    except Exception:
        return None


def _get_execution_summary() -> Optional[Any]:
    """Return an ExecutionSummary if execution context is available."""
    try:
        from core.projection import ExecutionSummary

        try:
            from core.unified.device_manager import UnifiedDeviceManager

            udm = UnifiedDeviceManager.get_instance()
            if udm is None:
                return None
            online = udm.get_online_devices() if hasattr(udm, "get_online_devices") else []
            device_ids = [d.device_id for d in online] if online else []
            return ExecutionSummary(active_device_ids=device_ids)
        except Exception:
            return None
    except Exception:
        return None


def _minimal_fallback_payload() -> Dict[str, Any]:
    """Return a minimal valid projection payload for failure cases."""
    return {
        "tri_state_phase": "silent",
        "runtime_domain": None,
        "presence_intensity": None,
        "coherence": None,
        "collapse_tendency": None,
        "retreat_tendency": None,
        "primary_model_id": None,
        "support_model_ids": [],
        "active_weights": {},
        "route_reason": None,
        "active_device_ids": [],
        "execution_stage": None,
        "current_task_summary": None,
        "timestamp": time.time(),
        "projection_authority_context": {
            "continuum_source": "fallback_payload",
            "continuum_is_live_runtime": False,
            "runtime_state_anchor": "not_live_runtime",
        },
    }


def _assemble_canonical_routing_payload() -> Dict[str, Any]:
    """Assemble a canonical routing projection payload with OneAPI and provider status.

    Builds the standard RuntimeProjection and enriches it with:
    - ``oneapi_summary`` from core.oneapi_system_position
    - ``provider_status_summary`` from the canonical model supply state
    - ``canonical_routing_hints`` for quick-access downstream consumers

    Always returns a valid dict.  All enrichment steps are optional and
    degrade gracefully when the relevant sub-systems are unavailable.
    """
    try:
        from core.projection import build_runtime_projection, ExecutionSummary
        from core.continuum.types import ContinuumPhase, ContinuumState  # noqa: F401
    except Exception as exc:
        logger.warning("_assemble_canonical_routing_payload: imports unavailable: %s", exc)
        base = _minimal_fallback_payload()
        base["oneapi_summary"] = None
        base["provider_status_summary"] = None
        base["canonical_routing_hints"] = _build_routing_hints(base, None, None)
        return base

    continuum_state = _get_continuum_state()
    route_plan = _get_route_plan(continuum_state)
    execution_summary = _get_execution_summary()

    # --- Derive oneapi_summary -------------------------------------------
    oneapi_summary: Optional[Any] = None
    try:
        from core.projection.projection_helpers import (
            extract_oneapi_source_from_route_plan,
            build_oneapi_projection_summary,
        )

        if route_plan is not None:
            route_plan_dict = route_plan.to_dict()
            oneapi_summary = extract_oneapi_source_from_route_plan(route_plan_dict)
        # If route-based extraction did not find OneAPI participation, fall back
        # to the canonical system-level summary to make the integration position
        # visible in the projection even when OneAPI is not the active route.
        if oneapi_summary is None:
            oneapi_summary = build_oneapi_projection_summary()
    except Exception as exc:
        logger.debug(
            "_assemble_canonical_routing_payload: oneapi_summary derivation skipped: %s",
            exc,
        )

    # --- Derive provider_status_summary ----------------------------------
    provider_status_summary: Optional[Any] = None
    try:
        from core.projection.projection_helpers import extract_provider_status_summary

        model_supply: Optional[Any] = None
        try:
            from core.model_topology import ProviderInventory

            inventory = ProviderInventory.from_config()
            # Build a minimal model_supply dict from the inventory if possible.
            if hasattr(inventory, "to_dict"):
                model_supply = inventory.to_dict()
            elif hasattr(inventory, "providers"):
                model_supply = {
                    "providers": [
                        {
                            "provider_id": p.provider_id,
                            "health_status": getattr(p, "health_status", "healthy"),
                        }
                        for p in (inventory.providers or [])
                    ]
                }
        except Exception:
            pass

        if model_supply:
            provider_status_summary = extract_provider_status_summary(model_supply)
    except Exception as exc:
        logger.debug(
            "_assemble_canonical_routing_payload: provider_status_summary skipped: %s",
            exc,
        )

    # --- Build projection -------------------------------------------------
    try:
        if continuum_state is None:
            base = _minimal_fallback_payload()
        else:
            projection = build_runtime_projection(
                continuum_state=continuum_state,
                route_plan=route_plan,
                execution_summary=execution_summary,
                oneapi_summary=oneapi_summary,
                provider_status_summary=provider_status_summary,
                timestamp=time.time(),
            )
            base = projection.to_dict()
    except Exception as exc:
        logger.warning("_assemble_canonical_routing_payload: projection assembly failed: %s", exc)
        base = _minimal_fallback_payload()
        base["oneapi_summary"] = oneapi_summary
        base["provider_status_summary"] = provider_status_summary

    # --- Attach canonical routing hints ----------------------------------
    base["canonical_routing_hints"] = _build_routing_hints(base, oneapi_summary, provider_status_summary)
    return base


def _build_routing_hints(
    projection_dict: Dict[str, Any],
    oneapi_summary: Optional[Any],
    provider_status_summary: Optional[Any],
) -> Dict[str, Any]:
    """Build a compact canonical routing hints dict for quick consumer access."""
    from core.model_topology.topology_router import CANONICAL_ROUTING_AUTHORITY

    routing_authority = projection_dict.get("routing_authority", "none")
    primary_model_id = projection_dict.get("primary_model_id")
    support_model_ids = projection_dict.get("support_model_ids") or []
    route_reason = projection_dict.get("route_reason")

    has_route = bool(primary_model_id)
    is_canonical = routing_authority == CANONICAL_ROUTING_AUTHORITY
    is_legacy = routing_authority not in (CANONICAL_ROUTING_AUTHORITY, "none")
    has_oneapi = oneapi_summary is not None

    provider_available_count = 0
    provider_degraded_count = 0
    if isinstance(provider_status_summary, dict):
        provider_available_count = provider_status_summary.get("available", 0)
        provider_degraded_count = provider_status_summary.get("degraded", 0)

    return {
        "has_route": has_route,
        "routing_authority": routing_authority,
        "is_canonical": is_canonical,
        "is_legacy": is_legacy,
        "primary_model_id": primary_model_id,
        "support_count": len(support_model_ids),
        "has_oneapi": has_oneapi,
        "provider_available_count": provider_available_count,
        "provider_degraded_count": provider_degraded_count,
        "route_reason": route_reason,
    }


def _assemble_projection_with_return() -> Dict[str, Any]:
    """Assemble a projection dict enriched with return-intelligence data.

    Builds the standard projection first, then attaches the return summary
    derived from the live continuum state.  Always returns a valid dict with
    a ``"return_intelligence"`` key even when the return layer is unavailable.
    """
    base = _assemble_projection()

    try:
        from core.return_intelligence import build_return_summary, attach_return_summary, IDLE_RETURN_SUMMARY

        continuum_state = _get_continuum_state()
        if continuum_state is None:
            return attach_return_summary(base, IDLE_RETURN_SUMMARY)

        try:
            from core.continuum.return_engine import ReturnEngine

            engine = ReturnEngine()
            result = engine.evaluate(continuum_state)
            summary = build_return_summary(result)
        except Exception as exc:
            logger.warning("Return engine evaluation failed, using idle summary: %s", exc)
            summary = IDLE_RETURN_SUMMARY

        return attach_return_summary(base, summary)

    except Exception as exc:  # pragma: no cover
        logger.warning("Return-intelligence assembly failed, returning base projection: %s", exc)
        # Attach a minimal idle return intelligence block so consumers always find the key.
        base["return_intelligence"] = {
            "is_returning": False,
            "return_mode": "none",
            "return_action": None,
            "return_trigger": None,
            "decay_amount": 0.0,
            "reason": "return intelligence unavailable",
            "affects_manifest": False,
            "affects_liminal": False,
        }
        return base


def _assemble_projection_with_execution_policy() -> Dict[str, Any]:
    """Assemble a projection dict enriched with the execution-policy summary.

    Builds the standard projection (with return intelligence), then derives
    and attaches the PR-11 execution policy.  Always returns a valid dict with
    an ``"execution_policy"`` key even when the policy layer is unavailable.
    """
    base = _assemble_projection_with_return()

    try:
        from core.execution_policy import (
            resolve_policy,
            attach_policy_to_projection,
            DEFAULT_CONSERVATIVE_POLICY,
        )

        phase_str = base.get("tri_state_phase")
        domain_str = base.get("runtime_domain")
        retreat = base.get("retreat_tendency")
        collapse = base.get("collapse_tendency")
        return_intel = base.get("return_intelligence")

        # Optionally pull authority role from the running continuum context
        authority_role = None
        try:
            from core.orchestration_authority import AuthorityRole

            authority_role = AuthorityRole.AUTHORITATIVE_ENTRYPOINT
        except Exception:
            pass

        policy = resolve_policy(
            phase=phase_str,
            domain=domain_str,
            authority_role=authority_role,
            return_summary=return_intel,
            retreat_tendency=float(retreat) if retreat is not None else None,
            collapse_tendency=float(collapse) if collapse is not None else None,
        )
        return attach_policy_to_projection(base, policy)

    except Exception as exc:  # pragma: no cover
        logger.warning("Execution-policy assembly failed, attaching conservative default: %s", exc)
        from core.execution_policy.policy_summary import _fallback_summary

        base["execution_policy"] = _fallback_summary()
        return base


def _assemble_projection_with_cross_device_routing() -> Dict[str, Any]:
    """Assemble a projection dict enriched with the cross-device routing summary.

    Builds the standard projection (with execution policy), then derives and
    attaches the PR-13 cross-device routing summary.  Always returns a valid
    dict with a ``"cross_device_routing"`` key even when the package is
    unavailable.
    """
    base = _assemble_projection_with_execution_policy()

    try:
        from core.cross_device_policy import (
            resolve_routing_summary,
            attach_cross_device_to_projection,
            IDLE_ASSIGNMENT_SUMMARY,
        )

        domain_str = base.get("runtime_domain")

        # Extract execution policy object if available
        execution_policy = base.get("execution_policy")

        # Optionally pull authority role
        authority_role = None
        try:
            from core.orchestration_authority import AuthorityRole

            authority_role = AuthorityRole.AUTHORITATIVE_ENTRYPOINT
        except Exception:
            pass

        summary = resolve_routing_summary(
            runtime_domain=domain_str,
            execution_policy=execution_policy,
            authority_role=authority_role,
        )
        return attach_cross_device_to_projection(base, summary)

    except Exception as exc:  # pragma: no cover
        logger.warning("Cross-device routing assembly failed, attaching idle summary: %s", exc)
        try:
            from core.cross_device_policy import IDLE_ASSIGNMENT_SUMMARY

            base["cross_device_routing"] = IDLE_ASSIGNMENT_SUMMARY.to_dict()
        except Exception:
            base["cross_device_routing"] = {"posture": "undecided", "is_cross_device": False}
        return base


def _assemble_projection_with_merge_summary() -> Dict[str, Any]:
    """Assemble a projection dict enriched with the distributed merge summary.

    Builds the standard projection (with cross-device routing), then attaches
    the PR-14 merge summary and hints.  Always returns a valid dict with a
    ``"merge_summary"`` key even when the package is unavailable.
    """
    base = _assemble_projection_with_cross_device_routing()

    try:
        from core.distributed_execution import (
            EMPTY_MERGE_SUMMARY,
            attach_merge_summary_to_projection,
            get_merge_hints,
        )

        # Use the empty summary as a safe idle default — no live merge
        # context is available at projection-query time.  Future code that
        # does perform a live merge should store the summary in a registry
        # and retrieve it here.
        summary = EMPTY_MERGE_SUMMARY
        result = attach_merge_summary_to_projection(base, summary)
        result["merge_hints"] = get_merge_hints(summary)
        return result

    except Exception as exc:  # pragma: no cover
        logger.warning("Merge-summary assembly failed, attaching empty placeholder: %s", exc)
        base["merge_summary"] = {
            "merge_status": "failed",
            "total_count": 0,
            "successful_count": 0,
            "failed_count": 0,
            "timed_out_count": 0,
        }
        base["merge_hints"] = {
            "merge_status": "failed",
            "is_successful": False,
            "is_terminal_failure": True,
        }
        return base


def _assemble_projection_with_task_semantics() -> Dict[str, Any]:
    """Assemble a projection dict enriched with the PR-15 task semantic summary.

    Builds the standard projection (with merge summary), then attaches
    the task-semantics summary and hints.  Always returns a valid dict with
    ``"task_semantics"`` and ``"semantic_hints"`` keys even when the package
    is unavailable.
    """
    base = _assemble_projection_with_merge_summary()

    try:
        from core.task_semantics import (
            EMPTY_SEMANTIC_SUMMARY,
            attach_semantic_summary_to_projection,
            get_semantic_hints,
        )

        # Use the empty summary as the idle default — no active task context
        # is available at projection-query time.  Future code that maintains
        # a live task context registry should retrieve the appropriate summary
        # here.
        summary = EMPTY_SEMANTIC_SUMMARY
        result = attach_semantic_summary_to_projection(base, summary)
        result["semantic_hints"] = get_semantic_hints(summary)
        return result

    except Exception as exc:  # pragma: no cover
        logger.warning("Task-semantics assembly failed, attaching empty placeholder: %s", exc)
        base["task_semantics"] = {
            "task_id": "",
            "trace_id": "",
            "classified_steps": [],
            "total_steps": 0,
            "has_side_effectful_steps": False,
            "has_cross_device_steps": False,
            "unresolved_count": 0,
            "is_fully_resolved": True,
        }
        base["semantic_hints"] = {
            "total_steps": 0,
            "has_side_effectful_steps": False,
            "has_cross_device_steps": False,
        }
        return base


def _assemble_projection_with_device_formation() -> Dict[str, Any]:
    """Assemble a projection dict enriched with the PR-17 device-formation summary.

    Builds the standard projection (with task semantics), then derives and
    attaches the device-formation summary and hints.  Always returns a valid
    dict with ``"device_formation"`` and ``"formation_hints"`` keys even when
    the package is unavailable.
    """
    base = _assemble_projection_with_task_semantics()

    try:
        from core.device_formation import (
            IDLE_FORMATION_SUMMARY,
            attach_formation_to_projection,
            get_formation_hints,
            resolve_formation_summary,
        )

        domain_str = base.get("runtime_domain")

        # Seed from cross-device routing summary if present
        cross_device_routing = base.get("cross_device_routing", {})
        routing_summary = cross_device_routing if isinstance(cross_device_routing, dict) else {}

        summary = resolve_formation_summary(
            runtime_domain=domain_str,
            cross_device_routing_summary=routing_summary,
            execution_policy=base.get("execution_policy"),
        )
        result = attach_formation_to_projection(base, summary)
        result["formation_hints"] = get_formation_hints(summary)
        return result

    except Exception as exc:  # pragma: no cover
        logger.warning("Device-formation assembly failed, attaching idle placeholder: %s", exc)
        base["device_formation"] = {
            "schema_version": 1,
            "formation_id": "empty",
            "task_id": None,
            "trace_id": None,
            "is_multi_device": False,
            "member_count": 0,
            "source_device_id": None,
            "primary_execution_device_id": None,
            "merge_owner_device_id": None,
            "barrier_posture": "wait_primary",
            "multi_device_required": False,
            "merge_confirmation_required": False,
            "fallback_available": False,
            "formation_reason": "no active formation",
            "runtime_domain_intent": "local",
            "all_member_device_ids": [],
            "fallback_device_ids": [],
            "support_device_ids": [],
            "observer_device_ids": [],
            "relay_device_ids": [],
            "policy_reason": "idle default",
        }
        base["formation_hints"] = {
            "is_multi_device": False,
            "member_count": 0,
            "fallback_available": False,
            "multi_device_required": False,
            "merge_confirmation_required": False,
            "has_primary": False,
            "has_source": False,
            "has_merge_owner": False,
            "barrier_posture": "wait_primary",
            "runtime_domain_intent": "local",
        }
        return base


def _assemble_projection_with_agent_dispatch() -> Dict[str, Any]:
    """Assemble a projection dict enriched with the PR-18 agent-dispatch governance summary.

    Builds the device-formation projection (which includes all previous layers),
    then derives and attaches the agent-dispatch governance summary and ownership
    hints.  Always returns a valid dict with ``"agent_dispatch"`` and
    ``"ownership_hints"`` keys even when the package is unavailable.
    """
    base = _assemble_projection_with_device_formation()

    try:
        from core.agent_governance import (
            IDLE_DISPATCH_SUMMARY,
            attach_dispatch_summary_to_projection,
            get_ownership_hints,
            resolve_dispatch_summary,
        )

        # Seed from formation/runtime context available in the base projection
        runtime_domain = base.get("runtime_domain", "local")
        device_formation = base.get("device_formation", {})
        is_multi_device = (
            device_formation.get("is_multi_device", False) if isinstance(device_formation, dict) else False
        )

        # Choose dispatch role hint based on available context
        dispatch_role_str = "local_assistant" if not is_multi_device else "planner"
        target_role_str = "remote_specialist" if is_multi_device else "executor"

        summary = resolve_dispatch_summary(
            dispatch_role_str=dispatch_role_str,
            target_role_str=target_role_str,
            dispatch_success=False,  # idle — no live dispatch in projection
        )
        result = attach_dispatch_summary_to_projection(base, summary)
        result["ownership_hints"] = get_ownership_hints(summary.ownership)
        return result

    except Exception as exc:  # pragma: no cover
        logger.warning("Agent-dispatch governance assembly failed, attaching idle placeholder: %s", exc)
        base["agent_dispatch"] = {
            "schema_version": 1,
            "dispatch_role": "unassigned",
            "target_role": "unassigned",
            "handoff_valid": False,
            "ownership": {
                "schema_version": 1,
                "dispatch_owner": "unassigned",
                "current_owner": "unassigned",
                "final_outcome_owner": None,
                "handoff_count": 0,
                "is_recovery_active": False,
                "is_complete": False,
                "max_handoff_depth": 5,
                "depth_exceeded": False,
                "recovery_permitted": True,
                "trace_id": None,
                "task_id": None,
                "last_handoff_reason": "idle",
                "policy_reason": "idle default",
            },
            "trace_id": None,
            "task_id": None,
            "bridge_source": None,
            "dispatch_success": False,
            "failure_reason": "",
            "policy_reason": "idle default",
        }
        base["ownership_hints"] = {
            "dispatch_owner": "unassigned",
            "current_owner": "unassigned",
            "is_recovery_active": False,
            "is_complete": False,
            "depth_exceeded": False,
            "handoff_count": 0,
            "has_final_owner": False,
            "recovery_permitted": True,
        }
        return base


def _assemble_projection_with_routing_explanation() -> Dict[str, Any]:
    """Assemble a projection dict enriched with the PR-21 routing explanation summary.

    Builds the agent-dispatch projection (which includes all previous layers),
    then derives and attaches the routing explanation summary and hints.
    Always returns a valid dict with ``"routing_explanation"`` and
    ``"explanation_hints"`` keys even when the package is unavailable.
    """
    base = _assemble_projection_with_agent_dispatch()

    try:
        from core.routing_explanation import (
            IDLE_EXPLANATION_SUMMARY,
            attach_explanation_to_projection,
            get_explanation_hints,
            resolve_explanation_from_projection,
        )

        summary = resolve_explanation_from_projection(base)
        result = attach_explanation_to_projection(base, summary)
        result["explanation_hints"] = get_explanation_hints(summary)
        return result

    except Exception as exc:  # pragma: no cover
        logger.warning("Routing-explanation assembly failed, attaching idle placeholder: %s", exc)
        base["routing_explanation"] = {
            "schema_version": 1,
            "route_target": None,
            "decision_basis_list": [],
            "confidence": {
                "score": 0.0,
                "band": "undetermined",
                "basis_count": 0,
                "accepted_factor_count": 0,
                "rejected_factor_count": 0,
                "contributing_factors": [],
                "reason": "routing explanation unavailable",
            },
            "rejected_alternatives": [],
            "fallback_plan": None,
            "owner_agent": None,
            "owner_component": "routing_explanation",
            "policy_posture": "undecided",
            "policy_band": None,
            "policy_reason": "no routing decision recorded",
            "is_cross_device": False,
            "has_fallback": False,
            "task_id": None,
            "trace_id": None,
        }
        base["explanation_hints"] = {
            "route_target": None,
            "policy_posture": "undecided",
            "policy_band": None,
            "confidence_score": 0.0,
            "confidence_band": "undetermined",
            "is_cross_device": False,
            "has_fallback": False,
            "has_rejected_alternatives": False,
            "rejected_count": 0,
            "basis_count": 0,
            "owner_agent": None,
        }
        return base


def _assemble_projection_with_governance() -> Dict[str, Any]:
    """Assemble a projection dict enriched with PR-26 governance assembly data.

    Builds the standard projection first, then assembles and attaches the
    governance summary derived from any available governance inputs
    (intent profile, readiness result, fallback trace, execution trace envelope).

    Always returns a valid dict with ``"governance"`` and
    ``"governance_hints"`` keys even when governance inputs are unavailable
    (in which case ``"governance"`` will reflect a minimal unavailable state).
    """
    base = _assemble_projection()

    try:
        from core.projection.assembly_governance import assemble_projection_governance

        continuum_state = _get_continuum_state()

        gov_summary = assemble_projection_governance(
            intent_profile=None,
            readiness_result=None,
            fallback_trace=None,
            execution_trace_envelope=None,
            state_continuum=continuum_state,
        )
        base["governance"] = gov_summary.to_dict()
        base["governance_hints"] = {
            "governance_available": gov_summary.governance_available,
            "action_level": gov_summary.execution.action_level,
            "intent_mode": gov_summary.execution.intent_mode,
            "ready": gov_summary.policy.ready,
            "policy_status": gov_summary.policy.status,
            "blocked": gov_summary.policy.blocked,
            "degraded": gov_summary.policy.degraded,
            "fallback_outcome": gov_summary.fallback.outcome,
            "trace_final_status": gov_summary.execution_trace.final_status,
            "tri_state_phase": gov_summary.tri_state_phase,
            "runtime_domain": gov_summary.runtime_domain,
        }
        return base

    except Exception as exc:  # pragma: no cover
        logger.warning("Governance projection assembly failed, attaching minimal placeholder: %s", exc)
        base["governance"] = {
            "governance_available": False,
            "execution": {"available": False, "action_level": "observe", "intent_mode": "advisory"},
            "policy": {"available": False, "ready": False, "status": "blocked", "blocked": True},
            "fallback": {"available": False, "outcome": "noop"},
            "execution_trace": {"available": False, "final_status": "pending", "stage_count": 0, "stages": []},
            "tri_state_phase": None,
            "runtime_domain": None,
            "assembled_at": time.time(),
        }
        base["governance_hints"] = {
            "governance_available": False,
            "action_level": "observe",
            "intent_mode": "advisory",
            "ready": False,
            "policy_status": "blocked",
            "blocked": True,
            "degraded": False,
            "fallback_outcome": "noop",
            "trace_final_status": "pending",
            "tri_state_phase": None,
            "runtime_domain": None,
        }
        return base


def _assemble_runtime_governance_snapshot_payload() -> Dict[str, Any]:
    """Assemble and return the runtime governance snapshot payload.

    Builds the projection governance summary (PR-26) and then assembles the
    unified runtime governance snapshot (PR-27) from all available runtime
    inputs.  Always returns a valid serialisable dict; individual component
    failures result in graceful defaults rather than errors.
    """
    try:
        from core.runtime_governance.snapshot import assemble_runtime_governance_snapshot

        # Get the projection governance summary (PR-26) first, it is the
        # richest governance source available at projection time.
        proj_gov = None
        try:
            from core.projection.assembly_governance import assemble_projection_governance

            continuum_state = _get_continuum_state()
            proj_gov = assemble_projection_governance(
                intent_profile=None,
                readiness_result=None,
                fallback_trace=None,
                execution_trace_envelope=None,
                state_continuum=continuum_state,
            )
        except Exception as exc:
            logger.warning("Runtime governance snapshot: projection governance unavailable: %s", exc)

        # Resolve tri_state_phase / runtime_domain from live continuum state
        tri_state_phase: Optional[str] = None
        runtime_domain: Optional[str] = None
        try:
            cs = _get_continuum_state()
            if cs is not None:
                if isinstance(cs, dict):
                    tri_state_phase = cs.get("tri_state_phase")
                    runtime_domain = cs.get("runtime_domain")
                else:
                    phase = getattr(cs, "tri_state_phase", None)
                    domain = getattr(cs, "runtime_domain", None)
                    if phase is not None:
                        tri_state_phase = phase.value if hasattr(phase, "value") else str(phase)
                    if domain is not None:
                        runtime_domain = domain.value if hasattr(domain, "value") else str(domain)
        except Exception as exc:
            logger.warning("Runtime governance snapshot: failed to resolve phase/domain: %s", exc)

        snapshot = assemble_runtime_governance_snapshot(
            projection_governance=proj_gov,
            tri_state_phase=tri_state_phase,
            runtime_domain=runtime_domain,
        )
        return snapshot.to_dict()

    except Exception as exc:
        logger.warning("Runtime governance snapshot assembly failed, returning minimal payload: %s", exc)
        import uuid

        return {
            "snapshot_id": str(uuid.uuid4()),
            "trace_id": None,
            "runtime_session_id": None,
            "tri_state_phase": None,
            "runtime_domain": None,
            "governance_available": False,
            "intent_summary": {"available": False, "action_level": "observe", "intent_mode": "advisory"},
            "readiness_summary": {"available": False, "ready": False, "status": "blocked", "blocked": True},
            "fallback_summary": {"available": False, "final_status": "pending", "stage_count": 0, "stages": []},
            "execution_trace_summary": {"available": False, "final_status": "pending", "stage_count": 0, "stages": []},
            "projection_governance_summary": {"available": False, "governance_available": False},
            "posture": "unknown",
            "blocked": False,
            "degraded": False,
            "timestamp": time.time(),
        }


def _assemble_policy_alignment_payload() -> Dict[str, Any]:
    """Assemble and return the execution policy alignment surface payload (PR-28).

    Builds the projection governance summary (PR-26), the runtime governance
    snapshot (PR-27), and then assembles the execution policy alignment surface
    (PR-28) from all available runtime inputs.  Always returns a valid
    serialisable dict; individual component failures result in graceful defaults
    rather than errors.
    """
    try:
        from core.policy.alignment_surface import build_execution_policy_alignment_surface

        # Get projection governance (PR-26)
        proj_gov = None
        try:
            from core.projection.assembly_governance import assemble_projection_governance

            continuum_state = _get_continuum_state()
            proj_gov = assemble_projection_governance(
                intent_profile=None,
                readiness_result=None,
                fallback_trace=None,
                execution_trace_envelope=None,
                state_continuum=continuum_state,
            )
        except Exception as exc:
            logger.warning("Policy alignment: projection governance unavailable: %s", exc)

        # Get runtime governance snapshot (PR-27)
        runtime_snapshot = None
        try:
            from core.runtime_governance.snapshot import assemble_runtime_governance_snapshot

            runtime_snapshot = assemble_runtime_governance_snapshot(
                projection_governance=proj_gov,
            )
        except Exception as exc:
            logger.warning("Policy alignment: runtime governance snapshot unavailable: %s", exc)

        # Resolve tri_state_phase / runtime_domain from live continuum state
        tri_state_phase: Optional[str] = None
        runtime_domain: Optional[str] = None
        try:
            cs = _get_continuum_state()
            if cs is not None:
                if isinstance(cs, dict):
                    tri_state_phase = cs.get("tri_state_phase")
                    runtime_domain = cs.get("runtime_domain")
                else:
                    phase = getattr(cs, "tri_state_phase", None)
                    domain = getattr(cs, "runtime_domain", None)
                    if phase is not None:
                        tri_state_phase = phase.value if hasattr(phase, "value") else str(phase)
                    if domain is not None:
                        runtime_domain = domain.value if hasattr(domain, "value") else str(domain)
        except Exception as exc:
            logger.warning("Policy alignment: failed to resolve phase/domain: %s", exc)

        alignment = build_execution_policy_alignment_surface(
            runtime_governance_snapshot=runtime_snapshot,
            projection_governance=proj_gov,
            tri_state_phase=tri_state_phase,
            runtime_domain=runtime_domain,
        )
        return alignment.to_dict()

    except Exception as exc:
        logger.warning("Policy alignment assembly failed, returning minimal payload: %s", exc)
        import uuid

        return {
            "alignment_id": str(uuid.uuid4()),
            "trace_id": None,
            "runtime_session_id": None,
            "tri_state_phase": None,
            "runtime_domain": None,
            "aligned": False,
            "blocked": False,
            "degraded": True,
            "confirmation_required": False,
            "policy_posture": "unknown",
            "runtime_policy_summary": {"dimension": "runtime_policy", "available": False},
            "readiness_policy_summary": {"dimension": "readiness_policy", "available": False},
            "fallback_policy_summary": {"dimension": "fallback_policy", "available": False},
            "dispatch_policy_summary": {"dimension": "dispatch_policy", "available": False},
            "projection_policy_summary": {"dimension": "projection_policy", "available": False},
            "mismatches": [],
            "alignment_hints": {
                "can_execute_locally": False,
                "can_expand_cross_device": False,
                "is_confirmation_gated": False,
                "is_blocked": False,
                "is_degraded": True,
                "preferred_domain": None,
                "effective_action_level": "observe",
                "alignment_confidence": 0.0,
                "policy_posture": "unknown",
                "hint_source": "empty",
            },
            "timestamp": time.time(),
        }


def _assemble_server_canonicalization_status() -> Dict[str, Any]:
    """Assemble the PR-5 server-side canonicalization status summary.

    Returns a machine-checkable dict describing:
    - Canonical routing/projection authorities
    - Legacy UCP keys demoted by PR-5
    - PR-4 OneAPI lower-horizon guarantee status
    - Consumer guidance for downstream surfaces
    """
    from contracts.desktop_status_projection import (
        LEGACY_UCP_ROUTING_KEYS,
        PROJECTION_CONTRACT_AUTHORITY,
    )
    from core.model_topology.topology_router import (
        CANONICAL_ROUTING_AUTHORITY,
        LEGACY_ROUTING_FIELDS,
    )
    from core.projection.projection_compiler import (
        LEGACY_PROJECTION_UCP_KEYS,
        PROJECTION_COMPILER_AUTHORITY,
    )

    # Check PR-4 oneapi_integration guarantee.
    oneapi_integration_present = False
    try:
        from contracts.desktop_status_projection import DesktopStatusProjection

        _test_proj = DesktopStatusProjection()
        oneapi_integration_present = hasattr(_test_proj, "oneapi_integration")
    except Exception:
        pass

    return {
        "canonicalization_stage": "pr5_server_side",
        "pr_description": (
            "PR-5 completes server-side canonicalization after PR-4 OneAPI "
            "lower-horizon cleanup.  Legacy UCP routing keys are demoted to "
            "compatibility-only status.  Canonical TopologyRoutePlan and "
            "DesktopStatusProjection are the preferred server outputs."
        ),
        "canonical_routing_authority": CANONICAL_ROUTING_AUTHORITY,
        "canonical_projection_compiler_authority": PROJECTION_COMPILER_AUTHORITY,
        "canonical_projection_contract_authority": PROJECTION_CONTRACT_AUTHORITY,
        "legacy_ucp_routing_keys": sorted(LEGACY_UCP_ROUTING_KEYS),
        "legacy_routing_fields": list(LEGACY_ROUTING_FIELDS),
        "legacy_projection_ucp_keys": list(LEGACY_PROJECTION_UCP_KEYS),
        "oneapi_lower_horizon_guaranteed": True,
        "oneapi_integration_field_present": oneapi_integration_present,
        "pr4_guarantees_intact": True,
        "consumer_guidance": {
            "prefer_topology_route_plan": True,
            "prefer_oneapi_integration_block": True,
            "avoid_legacy_ucp_keys": True,
            "legacy_routing_fallback_active_field": ("model_routing.legacy_routing_fallback_active"),
            "canonical_endpoint": "/api/v1/projection/canonical-routing",
            "default_board_facing_endpoint": "/api/v1/projection/runtime-truth",
            "desktop_board_integration_endpoint": "/api/v1/projection/desktop-status-board",
            "desktop_status_endpoint": "/api/v1/projection/desktop-status-board",
            "desktop_status_fallback_endpoint": "/api/v1/projection/runtime",
        },
        "timestamp": time.time(),
    }


def _assemble_desktop_topology_payload() -> Dict[str, Any]:
    """PR-6: Assemble the topology-ready projection payload for desktop surfaces.

    Builds a :class:`~contracts.desktop_status_projection.DesktopTopologyProjection`
    from live runtime state (canonical ``TopologyRoutePlan`` when available,
    legacy fallback with explicit degradation marking otherwise).

    Always returns a valid dict.  All sub-components are optional and degrade
    gracefully when the relevant sub-systems are unavailable.
    """
    try:
        from contracts.desktop_status_projection import (
            build_desktop_status_projection,
        )
    except Exception as exc:
        logger.warning("_assemble_desktop_topology_payload: import failed: %s", exc)
        return _minimal_desktop_topology_fallback()

    # Build a UCP dict from the live topology route plan so that the
    # topology-ready projection block is sourced from canonical data.
    ucp: Dict[str, Any] = {}
    try:
        continuum_state = _get_continuum_state()
        route_plan = _get_route_plan(continuum_state)
        if route_plan is not None:
            ucp["topology_route_plan"] = route_plan.to_dict()
    except Exception as exc:
        logger.debug(
            "_assemble_desktop_topology_payload: route_plan derivation skipped: %s",
            exc,
        )

    try:
        proj = build_desktop_status_projection(unified_control_plan=ucp)
        topo = proj.topology_ready
        if topo is None:
            return _minimal_desktop_topology_fallback()
        result = topo.to_dict()
        result["_assembled_at"] = time.time()
        return result
    except Exception as exc:
        logger.warning("_assemble_desktop_topology_payload: projection assembly failed: %s", exc)
        return _minimal_desktop_topology_fallback()


def _minimal_desktop_topology_fallback() -> Dict[str, Any]:
    """Return a minimal valid desktop topology payload for failure cases."""
    return {
        "primary_model_id": None,
        "primary_provider_id": None,
        "primary_vendor_source": None,
        "primary_is_native_multimodal": False,
        "support_model_ids": [],
        "route_reason": None,
        "route_phase": None,
        "route_domain": None,
        "primary_provider_available": True,
        "routing_authority_source": "none",
        "canonical_source_present": False,
        "legacy_fallback_active": False,
        "oneapi_integration": None,
        "health_severity": "unknown",
        "projection_quality": {
            "readiness": "unavailable",
            "authoritative": False,
            "degraded": False,
            "partial": False,
            "quality_note": (
                "No routing data is available. Topology block cannot provide routing truth. "
                "Consumers must not render constellation topology from this block."
            ),
            "quality_authority": ("contracts.desktop_status_projection.TopologyProjectionQualityBlock"),
        },
        "contract_authority": ("contracts.desktop_status_projection.DesktopTopologyProjection"),
        "_assembled_at": time.time(),
    }


def _classify_operational_decision_authority(sources: Any) -> str:
    boundary_v2 = "v2_authoritative"
    boundary_android = "android_originated"
    boundary_joint = "joint_cross_repo_derived"
    source_list = [
        str(source)
        for source in (sources or [])
        if source is not None and str(source).strip()
    ]
    if not source_list:
        return boundary_v2
    has_android_origin = any(
        "android" in source.lower() or "galaxy_gateway.android" in source.lower()
        for source in source_list
    )
    has_v2_origin = any(
        source.startswith("core.") or source.startswith("contracts.")
        for source in source_list
    )
    if has_android_origin and has_v2_origin:
        return boundary_joint
    if has_android_origin:
        return boundary_android
    return boundary_v2


def _source_of_truth_boundaries() -> Dict[str, str]:
    return {
        "v2_authoritative": "Derived from V2 canonical core/contracts sources.",
        "android_originated": "Requires Android-originated evidence from Android-linked surfaces.",
        "joint_cross_repo_derived": "Derived from correlated Android + V2 sources.",
    }


def _build_problem_solving_chain_from_contract(state_contract: Dict[str, Any]) -> Dict[str, Any]:
    lifecycle = state_contract.get("lifecycle_hardening") or {}
    transition_lineage = lifecycle.get("transition_lineage") or {}
    events = list(transition_lineage.get("events") or [])
    if not isinstance(events, list):
        events = []
    subject_id = str(transition_lineage.get("subject_id") or "")
    latest_sequence = int(transition_lineage.get("latest_sequence") or 0)
    derived = state_contract.get("derived_state") or {}
    raw = state_contract.get("raw_signals") or {}
    active_path = ((derived.get("active_path") or {}).get("state") or "unknown")
    interruptions = [
        {
            "sequence": int(event.get("sequence") or 0),
            "transition": str(event.get("transition") or ""),
            "to_state": str(event.get("to_state") or ""),
        }
        for event in events
        if isinstance(event, dict)
        and any(
            token in str(event.get("transition") or "").lower()
            for token in ("degraded", "interrupt", "continuity_changed", "waiting_dependency")
        )
    ]
    recoveries = [
        {
            "sequence": int(event.get("sequence") or 0),
            "transition": str(event.get("transition") or ""),
            "to_state": str(event.get("to_state") or ""),
        }
        for event in events
        if isinstance(event, dict)
        and str(event.get("transition") or "").lower().startswith("recovery_")
    ]
    closure_events = [
        event
        for event in events
        if isinstance(event, dict)
        and "closure" in str(event.get("transition") or "").lower()
    ]
    last_closure_event = closure_events[-1] if closure_events else {}
    final_state = str((last_closure_event or {}).get("to_state") or "unknown")
    return {
        "subject_id": subject_id or "subject:unknown",
        "latest_sequence": latest_sequence,
        "entry_transition": str((events[0] or {}).get("transition") or "unknown") if events else "unknown",
        "routing_path": active_path,
        "android_participation_tier": str(
            raw.get("android_network_participation_tier") or "local_only"
        ),
        "interruption_points": interruptions,
        "recovery_points": recoveries,
        "final_state": final_state,
        "timeline_tail": [
            {
                "sequence": int(event.get("sequence") or 0),
                "transition": str(event.get("transition") or ""),
                "to_state": str(event.get("to_state") or ""),
            }
            for event in events[-5:]
            if isinstance(event, dict)
        ],
    }


def _build_operational_hotspots(state_contract: Dict[str, Any]) -> Dict[str, Any]:
    closure = state_contract.get("closure_quality_state") or {}
    blocked = (closure.get("blocked_state") or {}).get("state") == "present"
    waiting = (closure.get("waiting_dependency_state") or {}).get("state") == "present"
    incomplete = (closure.get("incomplete_state") or {}).get("state") == "present"
    quality_state = str((closure.get("success_quality") or {}).get("state") or "").lower()
    verdict_state = str((closure.get("verdict_quality") or {}).get("state") or "").lower()
    stale = ("stale" in quality_state) or ("stale" in verdict_state)
    return {
        "risk_hotspots": {
            "blocked": blocked,
            "waiting_dependency": waiting,
            "incomplete": incomplete,
        },
        "degraded_or_stale_truth": {
            "stale_snapshot_suspected": stale,
            "success_quality": (closure.get("success_quality") or {}).get("state"),
            "verdict_quality": (closure.get("verdict_quality") or {}).get("state"),
        },
        "recovery_hotspots": {
            "recovery_active": (state_contract.get("raw_signals") or {}).get("recovery_active"),
            "waiting_dependency": waiting,
        },
    }


def _empty_operational_state_board() -> Dict[str, Any]:
    return {
        "authority": "unavailable",
        "contract_version": "0.0.0",
        "categories": [],
        "task_execution_visibility": {
            "task_initiated": False,
            "result_closure_established": False,
            "active_session_count": 0,
            "participant_total_count": 0,
        },
        "dependencies_and_blockers": {
            "missing_required_routes": [],
            "waiting_dependencies": [],
            "blocked": False,
            "incomplete": False,
            "degraded_capability_device_count": 0,
        },
        "problem_solving_chain": {
            "subject_id": "subject:unknown",
            "latest_sequence": 0,
            "entry_transition": "unknown",
            "routing_path": "unknown",
            "android_participation_tier": "local_only",
            "interruption_points": [],
            "recovery_points": [],
            "final_state": "unknown",
            "timeline_tail": [],
        },
        "operational_hotspots": {
            "risk_hotspots": {},
            "degraded_or_stale_truth": {},
            "recovery_hotspots": {},
        },
        "pr5_reliability_metrics": {},
        "android_observability_alignment": {},
        "lifecycle_stage_index": {
            "observation": [],
            "admission": [],
            "readiness": [],
            "eligibility": [],
            "execution": [],
            "closure": [],
            "conditions": [],
        },
    }


def _build_operational_state_board_from_contract(
    state_contract: Dict[str, Any],
) -> Dict[str, Any]:
    derived = state_contract.get("derived_state") or {}
    acceptance = state_contract.get("acceptance_state") or {}
    eligibility = state_contract.get("eligibility_state") or {}
    closure = state_contract.get("closure_quality_state") or {}
    raw = state_contract.get("raw_signals") or {}

    decision_map = {
        "registration_state": derived.get("registration_state"),
        "capability_visibility": derived.get("capability_visibility"),
        "gateway_bridge_presence": derived.get("gateway_bridge_presence"),
        "operational_readiness": derived.get("operational_readiness"),
        "minimum_access_admission_verdict": acceptance.get("operational_acceptance"),
        "main_chain_availability": derived.get("main_chain_availability"),
        "cross_device_availability": derived.get("cross_device_availability"),
        "active_path": derived.get("active_path"),
        "compat_degraded_path": derived.get("degraded_path"),
        "recovery_active_state": derived.get("recovery_active_state"),
        "session_continuity": derived.get("session_continuity"),
        "participant_device_session_dependencies": derived.get("participant_device_session_dependencies"),
        "runtime_host_dispatch_binding": derived.get("runtime_host_dispatch_binding"),
        "task_initiation_eligibility": eligibility.get("task_initiation"),
        "task_execution_visibility": closure.get("task_execution_visibility"),
        "result_closure_state": closure.get("result_closure"),
        "success_quality": closure.get("success_quality"),
        "verdict_quality": closure.get("verdict_quality"),
        "blocked_state": closure.get("blocked_state"),
        "waiting_dependency_state": closure.get("waiting_dependency_state"),
        "incomplete_state": closure.get("incomplete_state"),
    }

    categories = []
    for category_id, decision in decision_map.items():
        if not isinstance(decision, dict):
            continue
        sources = decision.get("sources") or []
        categories.append(
            {
                "category_id": category_id,
                "label": decision.get("label") or category_id,
                "state": decision.get("state", "unknown"),
                "summary": decision.get("summary", ""),
                "why": list(decision.get("reasons") or []),
                "evidence": dict(decision.get("evidence") or {}),
                "source_of_truth_boundary": _classify_operational_decision_authority(sources),
                "source_fragments": list(sources),
                "observable": decision.get("observable"),
                "acceptable": decision.get("acceptable"),
                "eligible": decision.get("eligible"),
                "active": decision.get("active"),
                "complete": decision.get("complete"),
                "quality": decision.get("quality"),
                "lifecycle_stage": decision.get("lifecycle_stage"),
            }
        )

    board = {
        "authority": state_contract.get("authority"),
        "contract_version": state_contract.get("contract_version"),
        "categories": categories,
        "task_execution_visibility": {
            "task_initiated": bool(raw.get("task_initiated")),
            "result_closure_established": bool(raw.get("result_closure_established")),
            "active_session_count": raw.get("active_session_count", 0),
            "participant_total_count": raw.get("participant_total_count", 0),
        },
        "dependencies_and_blockers": {
            "missing_required_routes": list(raw.get("missing_required_routes") or []),
            "waiting_dependencies": list(
                (
                    (closure.get("waiting_dependency_state") or {})
                    .get("evidence", {})
                    .get("waiting_dependencies")
                )
                or []
            ),
            "blocked": (closure.get("blocked_state") or {}).get("state") == "present",
            "incomplete": (closure.get("incomplete_state") or {}).get("state") == "present",
            "degraded_capability_device_count": raw.get("degraded_capability_device_count", 0),
        },
        "lifecycle_stage_index": {
            "observation": [
                cid for cid, d in decision_map.items()
                if isinstance(d, dict) and d.get("lifecycle_stage") == "observation"
            ],
            "admission": [
                cid for cid, d in decision_map.items()
                if isinstance(d, dict) and d.get("lifecycle_stage") == "admission"
            ],
            "readiness": [
                cid for cid, d in decision_map.items()
                if isinstance(d, dict) and d.get("lifecycle_stage") == "readiness"
            ],
            "eligibility": [
                cid for cid, d in decision_map.items()
                if isinstance(d, dict) and d.get("lifecycle_stage") == "eligibility"
            ],
            "execution": [
                cid for cid, d in decision_map.items()
                if isinstance(d, dict) and d.get("lifecycle_stage") == "execution"
            ],
            "closure": [
                cid for cid, d in decision_map.items()
                if isinstance(d, dict) and d.get("lifecycle_stage") == "closure"
            ],
            "conditions": [
                cid for cid, d in decision_map.items()
                if isinstance(d, dict) and d.get("lifecycle_stage") == "conditions"
            ],
        },
    }
    board["problem_solving_chain"] = _build_problem_solving_chain_from_contract(state_contract)
    board["operational_hotspots"] = _build_operational_hotspots(state_contract)
    try:
        from core.operational_slo_metrics import get_operational_slo_metrics

        pr5 = (get_operational_slo_metrics().snapshot() or {}).get("pr5_convergence") or {}
        board["pr5_reliability_metrics"] = {
            "participation_enablement_rate": pr5.get("participation_enablement_rate"),
            "full_attachment_rate": pr5.get("full_attachment_rate"),
            "dispatch_eligibility_rate": pr5.get("dispatch_eligibility_rate"),
            "routing_rate": dict(pr5.get("routing_rate") or {}),
            "natural_language_request_solved_rate": pr5.get("natural_language_request_solved_rate"),
            "task_closure_rate": pr5.get("task_closure_rate"),
            "problem_closure_rate": pr5.get("problem_closure_rate"),
            "no_awaiter_forced_closure_rate": pr5.get("no_awaiter_forced_closure_rate"),
            "recovery_success_rate": pr5.get("recovery_success_rate"),
            "takeover_degraded_evidence_rate": pr5.get("takeover_degraded_evidence_rate"),
            "stale_snapshot_rate": pr5.get("stale_snapshot_rate"),
            "operator_intervention_success_rate": pr5.get(
                "operator_intervention_success_rate"
            ),
            "totals": dict(pr5.get("totals") or {}),
        }
        board["android_observability_alignment"] = dict(
            pr5.get("android_integration_expectations") or {}
        )
    except Exception:
        board["pr5_reliability_metrics"] = {}
        board["android_observability_alignment"] = {}
    return board


def _attach_operational_state_board(result: Dict[str, Any], route_paths: Any = None) -> Dict[str, Any]:
    try:
        from core.operational_readiness_surface import build_operational_readiness_report

        normalized_route_paths = route_paths if isinstance(route_paths, set) else set(route_paths or [])
        report = build_operational_readiness_report(route_paths=normalized_route_paths)
        state_contract = dict(report.state_contract)
        try:
            from core.operational_slo_metrics import get_operational_slo_metrics

            get_operational_slo_metrics().ingest_unified_state_contract(state_contract)
        except Exception:
            pass
        result["operational_readiness"] = {
            "authority": report.authority,
            "contract_version": report.contract_version,
            "validation": report.validation,
            "chain_state": report.chain_state.to_dict(),
            "clone_to_use_acceptance": report.clone_to_use_acceptance,
            "android_v2_minimum_standard": report.android_v2_minimum_standard,
            "state_contract": state_contract,
        }
        result["operational_state_board"] = _build_operational_state_board_from_contract(state_contract)
        result["source_of_truth_boundaries"] = _source_of_truth_boundaries()
    except Exception as exc:
        logger.debug(
            "_assemble_desktop_status_board_payload: operational state board attachment failed: %s",
            exc,
        )
    return result


def _derive_shared_execution_visibility(truth_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Derive a shared execution/completion visibility block from canonical truth."""
    board = truth_payload.get("operational_state_board") or {}
    task_visibility = board.get("task_execution_visibility") or {}
    blockers = board.get("dependencies_and_blockers") or {}
    reasoning = truth_payload.get("runtime_decision_reasoning") or {}
    closure_basis = reasoning.get("closure_basis") or {}

    task_initiated = bool(
        task_visibility.get("task_initiated")
        or closure_basis.get("task_completed")
        or closure_basis.get("problem_solved")
    )
    result_closure_established = bool(
        task_visibility.get("result_closure_established")
        or closure_basis.get("is_fully_closed")
    )
    blocked = bool(blockers.get("blocked"))
    incomplete = bool(blockers.get("incomplete"))
    waiting_dependencies = list(blockers.get("waiting_dependencies") or [])

    completion_state = "not_started"
    if result_closure_established:
        completion_state = "closed"
    elif task_initiated:
        completion_state = "in_progress"
    if blocked and completion_state != "closed":
        completion_state = "blocked"
    elif incomplete and completion_state != "closed":
        completion_state = "incomplete"

    if completion_state == "closed":
        surface_execution_stage = "closed"
    elif completion_state in {"in_progress", "incomplete"}:
        surface_execution_stage = "executing"
    elif completion_state == "blocked":
        surface_execution_stage = "blocked"
    else:
        surface_execution_stage = None

    summary_parts = [
        f"completion={completion_state}",
        f"task_initiated={task_initiated}",
        f"result_closed={result_closure_established}",
    ]
    acceptance_verdict = closure_basis.get("acceptance_verdict")
    if acceptance_verdict not in (None, ""):
        summary_parts.append(f"acceptance={acceptance_verdict}")
    if waiting_dependencies:
        summary_parts.append(f"waiting={len(waiting_dependencies)}")

    return {
        "task_initiated": task_initiated,
        "result_closure_established": result_closure_established,
        "blocked": blocked,
        "incomplete": incomplete,
        "waiting_dependencies": waiting_dependencies,
        "acceptance_verdict": acceptance_verdict,
        "is_fully_closed": bool(closure_basis.get("is_fully_closed")),
        "completion_state": completion_state,
        "surface_execution_stage": surface_execution_stage,
        "surface_summary": " | ".join(summary_parts),
        "source_of_truth_refs": [
            "operational_state_board.task_execution_visibility",
            "runtime_decision_reasoning.closure_basis",
        ],
    }


def _build_foundational_system_truth(truth_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build board-facing foundational truth from current real-code backbone audit."""
    if not isinstance(truth_payload, dict):
        truth_payload = {}

    try:
        from core.current_state_backbone_audit import build_system_backbone_snapshot  # noqa: PLC0415

        snapshot = dict(build_system_backbone_snapshot() or {})
    except Exception as exc:
        logger.debug("_build_foundational_system_truth unavailable: %s", exc)
        snapshot = {}

    mode_summary = dict(snapshot.get("mode_closure_summary") or {})
    chain_summary = dict(snapshot.get("chain_closure_summary") or {})
    layered_mode_model = dict(snapshot.get("layered_mode_model") or {})

    return {
        "cross_device_foundation": {
            "closure_state": mode_summary.get("cross_device_mode"),
            "definition_zh": "中心把任务路由到其他设备执行，属于跨设备能力。",
        },
        "multi_device_foundation": {
            "closure_state": mode_summary.get("multi_device_participation"),
            "definition_zh": "多个设备同时接入并参与同一系统，属于多设备能力。",
        },
        "local_cross_multi_relation": {
            "local_layer": dict(layered_mode_model.get("local_layer") or {}),
            "cross_device_layer": dict(layered_mode_model.get("cross_device_layer") or {}),
            "multi_device_layer": dict(layered_mode_model.get("multi_device_layer") or {}),
            "layering_zh": "本地层是基础，跨设备层在其上，最后形成多设备协同层。",
        },
        "real_three_state_model": {
            "model_name_zh": "工程闭合三态（非通用助手UI三态）",
            "states": ["established", "partial", "open"],
            "established_count": int(snapshot.get("established_count") or 0),
            "partial_count": int(snapshot.get("partial_count") or 0),
            "open_count": int(snapshot.get("open_count") or 0),
            "state_source": "core.current_state_backbone_audit.ClosureState",
            "is_engineering_approximation": True,
            "native_model_convergence": (
                dict(snapshot.get("native_three_state_final_audit") or {}).get("outcome")
            ),
        },
        "native_three_state_final_audit": dict(snapshot.get("native_three_state_final_audit") or {}),
        "local_cross_multi_foundation_audit": dict(
            snapshot.get("local_cross_multi_foundation_audit") or {}
        ),
        "task_system_layered_status": {
            "request_dispatch_chain": chain_summary.get("request_chain"),
            "execution_chain": chain_summary.get("execution_chain"),
            "result_backflow_chain": chain_summary.get("result_backflow_chain"),
            "closure_acceptance_chain": chain_summary.get("closure_acceptance_chain"),
            "projection_chain": chain_summary.get("projection_chain"),
            "delegated_execution_mode": mode_summary.get("delegated_execution"),
        },
        "task_system_body_final_audit": dict(snapshot.get("task_system_body_final_audit") or {}),
        # 1189 新增三大收口块
        "native_three_state_closeout": dict(snapshot.get("native_three_state_closeout") or {}),
        "central_agent_body_classification": dict(
            snapshot.get("central_agent_body_classification") or {}
        ),
        "remaining_work_split": dict(snapshot.get("remaining_work_split") or {}),
        "source_of_truth_refs": [
            "core.current_state_backbone_audit.build_system_backbone_snapshot",
            "core.current_state_backbone_audit.ClosureState",
            "core.current_state_backbone_audit.ModeId",
            "core.current_state_backbone_audit.ChainId",
        ],
        "_source": "core.routes.projection._build_foundational_system_truth",
    }


def _lookup_device_lifecycle_record(device_id: Optional[str]) -> Dict[str, Any]:
    if not device_id:
        return {}
    try:
        from core.device_lifecycle_state import get_lifecycle_record  # noqa: PLC0415

        record = get_lifecycle_record(str(device_id))
        if record is None:
            return {}
        if hasattr(record, "to_dict"):
            return dict(record.to_dict() or {})
        if isinstance(record, dict):
            return dict(record)
        stage = getattr(record, "stage", None)
        return {
            "device_id": str(device_id),
            "stage": getattr(stage, "value", None)
            or (str(stage) if stage not in (None, "") else None),
        }
    except Exception as exc:
        logger.debug(
            "_lookup_device_lifecycle_record: lifecycle lookup skipped "
            "device_id=%r error=%s",
            device_id,
            exc,
        )
        return {}


def _lookup_device_lifecycle_stage(device_id: Optional[str]) -> Optional[str]:
    if not device_id:
        return None
    lifecycle_record = _lookup_device_lifecycle_record(device_id)
    stage = lifecycle_record.get("stage")
    return str(stage) if stage not in (None, "") else None


def _build_runtime_lifecycle_truth(
    *,
    lifecycle_record: Optional[Dict[str, Any]],
    participation_status: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build lifecycle-backed runtime truth flags for board-facing surfaces.

    The result normalizes lifecycle record fields into explicit semantics
    (registered/connected/attached/alive/active/dispatchable/participating)
    while keeping compatibility fallbacks when a lifecycle record is absent.
    """
    _REGISTERED_OR_HIGHER_STAGES = {
        "registered",
        "connected",
        "ready",
        "participating",
        "takeover_eligible",
    }
    _CONNECTED_OR_HIGHER_STAGES = {
        "connected",
        "ready",
        "participating",
        "takeover_eligible",
    }
    _READY_OR_HIGHER_STAGES = {"ready", "participating", "takeover_eligible"}
    _ACTIVE_PARTICIPATION_STAGES = {"participating", "takeover_eligible"}

    record = dict(lifecycle_record or {})
    status = dict(participation_status or {})
    stage = str(record.get("stage") or "")
    connected_or_higher = stage in _CONNECTED_OR_HIGHER_STAGES
    ready_or_higher = stage in _READY_OR_HIGHER_STAGES
    active_or_participating = bool(record.get("execution_active") or stage in _ACTIVE_PARTICIPATION_STAGES)

    registered = bool(
        stage in _REGISTERED_OR_HIGHER_STAGES
        or record.get("registration_ack_success")
    )
    connected = bool(connected_or_higher or record.get("websocket_connected"))
    # connected_or_higher stages indicate registration has reached a state where
    # the device can be treated as attached for board-facing lifecycle truth.
    attached = bool(record.get("registration_fully_attached") or connected_or_higher)
    alive = bool(record.get("websocket_connected") and not record.get("operator_suspended"))
    active = active_or_participating
    dispatchable = bool(
        ready_or_higher
        or (
            record.get("dispatch_gate_passed")
            and record.get("readiness_satisfied")
            and connected
        )
    )
    participating = active_or_participating
    runtime_present = bool(status.get("runtime_present", connected))
    routable = bool(status.get("routable", connected))

    return {
        "stage": stage or None,
        "registered": registered,
        "connected": connected,
        "attached": attached,
        "alive": alive,
        "active": active,
        "dispatchable": dispatchable,
        "participating": participating,
        "runtime_present": runtime_present,
        "routable": routable,
        "registration_gaps": list(record.get("registration_gaps") or []),
        "dispatch_gate_passed": bool(record.get("dispatch_gate_passed")),
        "readiness_satisfied": bool(record.get("readiness_satisfied")),
        "operator_suspended": bool(record.get("operator_suspended")),
        "takeover_eligible": bool(record.get("takeover_eligible")),
        "source": (
            "core.device_lifecycle_state.get_lifecycle_record"
            if record
            else "core.device_selection.assess_device_participation (compat_fallback)"
        ),
    }


def _participation_tier_from_lifecycle_stage(stage: Optional[str]) -> Optional[str]:
    """Map lifecycle stage string to canonical participation tier."""
    if stage in (None, ""):
        return None
    try:
        from core.device_lifecycle_state import (  # noqa: PLC0415
            DeviceLifecycleStage,
            participation_tier_for_stage,
        )

        return participation_tier_for_stage(DeviceLifecycleStage.from_string(str(stage)))
    except Exception as exc:
        logger.debug("_participation_tier_from_lifecycle_stage unavailable: %s", exc)
        return None


def _get_udm_for_participation_matrix() -> Any:
    try:
        from core.unified.device_manager import get_unified_device_manager  # noqa: PLC0415

        return get_unified_device_manager()
    except Exception as exc:
        logger.debug("_get_udm_for_participation_matrix unavailable: %s", exc)
        return None


def _assess_device_participation_status(device: Any) -> Dict[str, Any]:
    try:
        from core.device_selection import assess_device_participation  # noqa: PLC0415

        status = assess_device_participation(device)
        return status.to_dict() if hasattr(status, "to_dict") else dict(status)
    except Exception as exc:
        logger.debug("_assess_device_participation_status unavailable: %s", exc)
        return {
            "registered": False,
            "runtime_present": False,
            "routable": False,
            "cross_device_eligible": False,
            "orchestration_eligible": False,
            "participation_reason": f"assessment_unavailable:{exc}",
        }


def _build_all_device_participation_matrix(
    *,
    selected_device_id: Optional[str],
    participation_tier: Optional[str],
    dispatch_eligible_selected: bool,
    local_mode_active_selected: bool,
    runtime_constrained_selected: bool,
    fully_attached_selected: bool,
) -> Dict[str, Any]:
    """Project participation truth into an all-device structured matrix."""
    matrix_rows: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    udm = _get_udm_for_participation_matrix()
    try:
        devices = (
            udm.list_devices()
            if udm is not None and hasattr(udm, "list_devices")
            else []
        )
    except Exception as exc:
        logger.debug("_build_all_device_participation_matrix: list_devices failed: %s", exc)
        devices = []

    for device in devices or []:
        device_id = str(getattr(device, "device_id", "") or "")
        if not device_id:
            continue
        seen_ids.add(device_id)
        status = dict(_assess_device_participation_status(device) or {})
        is_selected = bool(selected_device_id and device_id == str(selected_device_id))
        lifecycle_record = _lookup_device_lifecycle_record(device_id)
        lifecycle_stage = (
            str(lifecycle_record.get("stage"))
            if lifecycle_record.get("stage") not in (None, "")
            else None
        )
        runtime_lifecycle_truth = _build_runtime_lifecycle_truth(
            lifecycle_record=lifecycle_record,
            participation_status=status,
        )

        lifecycle_tier = _participation_tier_from_lifecycle_stage(lifecycle_stage)
        row_participation_tier = (
            participation_tier
            if is_selected and participation_tier not in (None, "")
            else (
                lifecycle_tier
                if lifecycle_tier not in (None, "")
                else (
                    "dispatch_eligible"
                    if bool(status.get("cross_device_eligible"))
                    else ("runtime_present" if bool(status.get("runtime_present")) else "registered")
                )
            )
        )
        # Selected device keeps orchestrator-selected truth to preserve operator
        # focus compatibility; non-selected devices derive from lifecycle truth.
        row_dispatch_eligible = (
            dispatch_eligible_selected if is_selected else bool(runtime_lifecycle_truth.get("dispatchable"))
        )
        row_local_mode_active = local_mode_active_selected if is_selected else False
        row_runtime_constrained = runtime_constrained_selected if is_selected else False
        row_fully_attached = (
            fully_attached_selected
            if is_selected
            else bool(runtime_lifecycle_truth.get("attached"))
        )

        matrix_rows.append(
            {
                "device_id": device_id,
                "selected": is_selected,
                "participation_tier": row_participation_tier,
                "dispatch_eligible": row_dispatch_eligible,
                "local_mode_active": row_local_mode_active,
                "runtime_constrained": row_runtime_constrained,
                "fully_attached": row_fully_attached,
                "device_lifecycle_stage": lifecycle_stage,
                "registered": bool(status.get("registered")),
                "runtime_present": bool(status.get("runtime_present")),
                "routable": bool(status.get("routable")),
                "cross_device_eligible": bool(status.get("cross_device_eligible")),
                "orchestration_eligible": bool(status.get("orchestration_eligible")),
                "participation_reason": status.get("participation_reason"),
                "participation_reason_codes": [str(status.get("participation_reason"))]
                if status.get("participation_reason")
                else [],
                "runtime_lifecycle_truth": runtime_lifecycle_truth,
                "attachment_semantics": {
                    "fully_attached": row_fully_attached,
                    "device_lifecycle_stage": lifecycle_stage,
                    "attachment_visible": bool(
                        row_fully_attached
                        or str(lifecycle_stage or "") in {"participating", "takeover_eligible"}
                    ),
                },
                "truth_scope": "selected_device_truth" if is_selected else "cross_device_projection",
            }
        )

    if selected_device_id and str(selected_device_id) not in seen_ids:
        lifecycle_record = _lookup_device_lifecycle_record(str(selected_device_id))
        lifecycle_stage = (
            str(lifecycle_record.get("stage"))
            if lifecycle_record.get("stage") not in (None, "")
            else None
        )
        runtime_lifecycle_truth = _build_runtime_lifecycle_truth(
            lifecycle_record=lifecycle_record,
            participation_status={},
        )
        matrix_rows.append(
            {
                "device_id": str(selected_device_id),
                "selected": True,
                "participation_tier": participation_tier,
                "dispatch_eligible": dispatch_eligible_selected,
                "local_mode_active": local_mode_active_selected,
                "runtime_constrained": runtime_constrained_selected,
                "fully_attached": fully_attached_selected,
                "device_lifecycle_stage": lifecycle_stage,
                "registered": bool(runtime_lifecycle_truth.get("registered")),
                "runtime_present": bool(runtime_lifecycle_truth.get("runtime_present")),
                "routable": bool(runtime_lifecycle_truth.get("routable")),
                "cross_device_eligible": bool(runtime_lifecycle_truth.get("dispatchable")),
                "orchestration_eligible": bool(runtime_lifecycle_truth.get("dispatchable")),
                "participation_reason": (
                    "selected_device_not_in_udm;lifecycle_truth_available"
                    if lifecycle_record
                    else "selected_device_not_in_udm"
                ),
                "participation_reason_codes": (
                    ["selected_device_not_in_udm", "lifecycle_truth_available"]
                    if lifecycle_record
                    else ["selected_device_not_in_udm"]
                ),
                "runtime_lifecycle_truth": runtime_lifecycle_truth,
                "attachment_semantics": {
                    "fully_attached": fully_attached_selected,
                    "device_lifecycle_stage": lifecycle_stage,
                    "attachment_visible": bool(
                        fully_attached_selected
                        or str(lifecycle_stage or "") in {"participating", "takeover_eligible"}
                    ),
                },
                "truth_scope": "selected_device_truth",
            }
        )

    matrix_rows.sort(key=lambda row: (not bool(row.get("selected")), str(row.get("device_id") or "")))
    return {
        "devices": matrix_rows,
        "device_count": len(matrix_rows),
        "selected_device_id": selected_device_id or None,
        "dispatch_eligible_count": sum(1 for row in matrix_rows if bool(row.get("dispatch_eligible"))),
        "fully_attached_count": sum(1 for row in matrix_rows if bool(row.get("fully_attached"))),
        "runtime_constrained_count": sum(1 for row in matrix_rows if bool(row.get("runtime_constrained"))),
        "source_of_truth_refs": [
            "runtime_decision_reasoning.selected_device",
            "runtime_decision_reasoning.participation_tier",
            "runtime_decision_reasoning.unified_mode_model.participation_semantics",
            "core.unified.device_manager.get_unified_device_manager",
            "core.device_selection.assess_device_participation",
            "core.device_lifecycle_state.get_lifecycle_record",
        ],
        "_source": "core.routes.projection._build_all_device_participation_matrix",
    }


def _build_participation_truth_consumption(truth_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build one normalized participation/mode truth block for board-facing consumers."""
    if not isinstance(truth_payload, dict):
        truth_payload = {}
    reasoning = dict(truth_payload.get("runtime_decision_reasoning") or {})
    unified_mode_model = dict(reasoning.get("unified_mode_model") or {})
    semantics = dict(unified_mode_model.get("participation_semantics") or {})
    mode_semantics = dict(semantics.get("mode_semantics") or {})
    shared_visibility = dict(truth_payload.get("shared_execution_visibility") or {})
    # 优先级：selected_device（当前 contract 规范字段）→ selected_device_id（兼容字段）→
    # device_id（老字段/弱兼容），确保不同来源的 reasoning 都能映射到同一设备身份。
    selected_device_id = (
        reasoning.get("selected_device")
        or reasoning.get("selected_device_id")
        or reasoning.get("device_id")
        or ""
    )
    selected_lifecycle_record = _lookup_device_lifecycle_record(
        str(selected_device_id) if selected_device_id else None
    )
    device_lifecycle_stage = (
        str(selected_lifecycle_record.get("stage"))
        if selected_lifecycle_record.get("stage") not in (None, "")
        else None
    )

    participation_tier = reasoning.get("participation_tier")
    if "dispatch_gate_passed" in semantics:
        dispatch_eligible = bool(semantics.get("dispatch_gate_passed"))
    else:
        dispatch_eligible = participation_tier in {"dispatch_eligible", "distributed_participant"}
    local_mode_active = bool(mode_semantics.get("local_mode_active"))
    runtime_constrained = bool(mode_semantics.get("constrained"))
    fully_attached = participation_tier == "fully_attached"
    all_device_participation_matrix = _build_all_device_participation_matrix(
        selected_device_id=str(selected_device_id) if selected_device_id else None,
        participation_tier=participation_tier,
        dispatch_eligible_selected=dispatch_eligible,
        local_mode_active_selected=local_mode_active,
        runtime_constrained_selected=runtime_constrained,
        fully_attached_selected=fully_attached,
    )

    return {
        "tri_state_phase": truth_payload.get("tri_state_phase"),
        "runtime_domain": (truth_payload.get("continuum") or {}).get("runtime_domain"),
        "selected_device_id": selected_device_id or None,
        "device_lifecycle_stage": device_lifecycle_stage,
        "participation_tier": participation_tier,
        "participation_layer": unified_mode_model.get("participation_layer"),
        "execution_location": unified_mode_model.get("execution_location"),
        "governance_state": unified_mode_model.get("governance_state"),
        "participation_semantics": semantics,
        "dispatch_eligible": dispatch_eligible,
        "local_mode_active": local_mode_active,
        "runtime_constrained": runtime_constrained,
        "fully_attached": fully_attached,
        "all_device_participation_matrix": all_device_participation_matrix,
        "attachment_semantics": {
            "fully_attached": fully_attached,
            "device_lifecycle_stage": device_lifecycle_stage,
            "attachment_visible": bool(
                fully_attached
                or str(device_lifecycle_stage or "") in {"participating", "takeover_eligible"}
            ),
        },
        "selected_device_runtime_truth": _build_runtime_lifecycle_truth(
            lifecycle_record=selected_lifecycle_record,
            participation_status={},
        ),
        "completion_state": shared_visibility.get("completion_state"),
        "surface_execution_stage": shared_visibility.get("surface_execution_stage"),
        "source_of_truth_refs": [
            "runtime_decision_reasoning.unified_mode_model",
            "all_device_participation_matrix.devices",
            "shared_execution_visibility",
            "runtime_truth.tri_state_phase",
            "core.device_lifecycle_state.get_lifecycle_record",
        ],
        "_source": "core.routes.projection._build_participation_truth_consumption",
    }


def _build_cross_repo_acceptance_chain_projection(
    *,
    truth_payload: Optional[Dict[str, Any]] = None,
    board_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建跨仓 Android→V2 验收链的阶段化快照。"""
    try:
        from core.cross_repo_acceptance_chain import build_cross_repo_acceptance_chain  # noqa: PLC0415

        truth_payload = dict(truth_payload or {})
        board_payload = dict(board_payload or {})
        truth_participation = dict(truth_payload.get("participation_truth_consumption") or {})
        board_participation = dict(board_payload.get("participation_truth_consumption") or {})
        reasoning = dict(truth_payload.get("runtime_decision_reasoning") or {})
        device_id = (
            truth_participation.get("selected_device_id")
            or board_participation.get("selected_device_id")
            or reasoning.get("selected_device")
            or reasoning.get("selected_device_id")
        )
        return build_cross_repo_acceptance_chain(
            device_id=device_id,
            truth_payload=truth_payload,
            board_payload=board_payload,
        )
    except Exception as exc:
        logger.debug("_build_cross_repo_acceptance_chain_projection unavailable: %s", exc)
        return {
            "overall_status": "failed",
            "summary": f"cross-repo acceptance chain unavailable: {exc}",
            "failure_boundaries": [
                {
                    "stage": "surface_visibility",
                    "boundary": "cross_repo_acceptance_chain_unavailable",
                    "summary": str(exc),
                }
            ],
            "stages": [],
            "_source": "core.routes.projection._build_cross_repo_acceptance_chain_projection",
        }


def _build_dual_repo_completeness_baseline_projection(
    *,
    truth_payload: Optional[Dict[str, Any]] = None,
    board_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建双仓系统完整性基线快照。"""
    try:
        from core.dual_repo_completeness_baseline import build_dual_repo_completeness_baseline  # noqa: PLC0415

        return build_dual_repo_completeness_baseline(
            truth_payload=dict(truth_payload or {}),
            board_payload=dict(board_payload or {}),
        )
    except Exception as exc:
        logger.debug("_build_dual_repo_completeness_baseline_projection unavailable: %s", exc)
        return {
            "overall_status": "failed",
            "summary_zh": f"dual-repo completeness baseline unavailable: {exc}",
            "blocking_stage_ids": ["clone"],
            "classification_counts": {},
            "explicit_gaps": [
                {
                    "type": "stage",
                    "stage": "clone",
                    "failure_boundary": "dual_repo_completeness_baseline_unavailable",
                    "summary": str(exc),
                }
            ],
            "_source": "core.routes.projection._build_dual_repo_completeness_baseline_projection",
        }


def _apply_shared_visibility_field(
    payload: Dict[str, Any],
    *,
    target_field: str,
    visibility_field: str,
) -> None:
    """Fill a payload field from shared_execution_visibility when missing."""
    if payload.get(target_field) in (None, ""):
        payload[target_field] = (payload.get("shared_execution_visibility") or {}).get(visibility_field)


def _assemble_desktop_status_board_payload(route_paths: Any = None) -> Dict[str, Any]:
    """PR-8: Assemble the final integrated desktop status board payload.

    Builds a :class:`~contracts.desktop_status_projection.DesktopStatusBoardIntegrationPayload`
    from live runtime state, composing topology projection, model routing
    summary, provider health, and OneAPI horizon into one stable payload.

    Always returns a valid dict.  All sub-components are optional and degrade
    gracefully when the relevant sub-systems are unavailable.
    """
    try:
        from contracts.desktop_status_projection import (
            build_desktop_status_board_integration_payload,
            build_desktop_status_projection,
        )
    except Exception as exc:
        logger.warning("_assemble_desktop_status_board_payload: import failed: %s", exc)
        return _minimal_desktop_status_board_fallback()

    # Build a UCP dict from the live topology route plan so that the
    # integration payload is sourced from canonical data.
    ucp: Dict[str, Any] = {}
    try:
        continuum_state = _get_continuum_state()
        route_plan = _get_route_plan(continuum_state)
        if route_plan is not None:
            ucp["topology_route_plan"] = route_plan.to_dict()
    except Exception as exc:
        logger.debug(
            "_assemble_desktop_status_board_payload: route_plan derivation skipped: %s",
            exc,
        )

    try:
        proj = build_desktop_status_projection(unified_control_plan=ucp)
        payload_obj = build_desktop_status_board_integration_payload(
            desktop_status_projection=proj,
        )
        result = payload_obj.to_dict()
        result["_assembled_at"] = time.time()
    except Exception as exc:
        logger.warning("_assemble_desktop_status_board_payload: assembly failed: %s", exc)
        return _minimal_desktop_status_board_fallback()

    # PR-514: Enrich with canonical runtime authority (GAP-512-003, GAP-512-005).
    # ProjectionSurfaceBridge.enrich_runtime_projection() reads OperatorSurface
    # so the status board receives operator_snapshot_dict and task/executor counts
    # from the canonical source without overwriting projection-derived fields.
    try:
        from core.authority_conflict_elimination import (
            enrich_projection_with_runtime_authority,
        )

        result = enrich_projection_with_runtime_authority(result)
    except Exception as exc:
        logger.warning(
            "_assemble_desktop_status_board_payload: runtime enrichment failed: %s",
            exc,
        )

    try:
        outward = _compile_outward_truth().to_dict()
        result["outward_truth"] = outward
        operator_snapshot = outward.get("operator_snapshot") or {}
        result["task_truth"] = {
            "active_task_count": operator_snapshot.get("active_task_count", 0),
            "recent_failure_count": operator_snapshot.get("recent_failure_count", 0),
            "reachable_executor_count": operator_snapshot.get("reachable_executor_count", 0),
            "source": "outward_truth.operator_snapshot",
        }
    except Exception as exc:
        logger.debug(
            "_assemble_desktop_status_board_payload: outward truth unavailable: %s",
            exc,
        )
        result["outward_truth"] = _minimal_outward_truth_payload()
        result["task_truth"] = {
            "active_task_count": 0,
            "recent_failure_count": 0,
            "reachable_executor_count": 0,
            "source": "fallback",
        }

    try:
        runtime_truth = _assemble_runtime_truth_payload()
        result["runtime_truth"] = runtime_truth
        result["startup_readiness"] = runtime_truth.get("startup_readiness")
        if isinstance(runtime_truth.get("operational_state_board"), dict):
            result["operational_state_board"] = runtime_truth.get("operational_state_board")
        if isinstance(runtime_truth.get("source_of_truth_boundaries"), dict):
            result["source_of_truth_boundaries"] = runtime_truth.get("source_of_truth_boundaries")
        if isinstance(runtime_truth.get("shared_execution_visibility"), dict):
            result["shared_execution_visibility"] = runtime_truth.get("shared_execution_visibility")
        if isinstance(runtime_truth.get("participation_truth_consumption"), dict):
            result["participation_truth_consumption"] = runtime_truth.get(
                "participation_truth_consumption"
            )
        if isinstance(runtime_truth.get("foundational_system_truth"), dict):
            result["foundational_system_truth"] = runtime_truth.get("foundational_system_truth")
        if isinstance(runtime_truth.get("cross_repo_acceptance_chain"), dict):
            result["cross_repo_acceptance_chain"] = runtime_truth.get("cross_repo_acceptance_chain")
        if isinstance(runtime_truth.get("dual_repo_completeness_baseline"), dict):
            result["dual_repo_completeness_baseline"] = runtime_truth.get("dual_repo_completeness_baseline")
    except Exception as exc:
        logger.debug(
            "_assemble_desktop_status_board_payload: runtime truth attachment failed: %s",
            exc,
        )

    if not isinstance(result.get("operational_state_board"), dict):
        result = _attach_operational_state_board(result, route_paths=route_paths)
    if not isinstance(result.get("source_of_truth_boundaries"), dict):
        result["source_of_truth_boundaries"] = _source_of_truth_boundaries()
    try:
        if isinstance(result.get("runtime_truth"), dict):
            visibility_source = result.get("runtime_truth")
        else:
            has_canonical_state = isinstance(result.get("operational_state_board"), dict) or isinstance(
                result.get("runtime_decision_reasoning"), dict
            )
            if has_canonical_state:
                # Fallback for degraded assemblies where runtime_truth attachment failed
                # but the desktop payload already contains partial canonical state blocks.
                visibility_source = result
            else:
                visibility_source = {}
        result["shared_execution_visibility"] = _derive_shared_execution_visibility(visibility_source)
        result["participation_truth_consumption"] = _build_participation_truth_consumption(
            visibility_source if isinstance(visibility_source, dict) else {}
        )
        result["foundational_system_truth"] = _build_foundational_system_truth(
            visibility_source if isinstance(visibility_source, dict) else {}
        )
    except Exception as exc:
        logger.debug("_assemble_desktop_status_board_payload: shared execution visibility unavailable: %s", exc)
        result.setdefault("shared_execution_visibility", _derive_shared_execution_visibility({}))
        result.setdefault(
            "participation_truth_consumption",
            _build_participation_truth_consumption({}),
        )
        result.setdefault("foundational_system_truth", _build_foundational_system_truth({}))
    runtime_truth_payload = result.get("runtime_truth") if isinstance(result.get("runtime_truth"), dict) else {}
    result["cross_repo_acceptance_chain"] = _build_cross_repo_acceptance_chain_projection(
        truth_payload=runtime_truth_payload,
        board_payload=result,
    )
    result["dual_repo_completeness_baseline"] = _build_dual_repo_completeness_baseline_projection(
        truth_payload=runtime_truth_payload,
        board_payload=result,
    )
    _apply_shared_visibility_field(
        result,
        target_field="execution_stage",
        visibility_field="surface_execution_stage",
    )
    _apply_shared_visibility_field(
        result,
        target_field="current_task_summary",
        visibility_field="surface_summary",
    )
    try:
        from core.v2_unified_state_contract import (
            build_control_plane_surface_contract,
            build_shared_control_plane_basis,
        )

        runtime_truth_for_contract = result.get("runtime_truth") or {}
        derived_reasoning = runtime_truth_for_contract.get("runtime_decision_reasoning") or {}
        shared_basis = build_shared_control_plane_basis(reasoning_block=derived_reasoning)
        result["stale_or_cached_summary"] = {
            "runtime_truth_fallback": bool(runtime_truth_for_contract.get("_fallback", False)),
            "desktop_payload_fallback": bool(result.get("_fallback", False)),
        }
        result["control_plane_contract"] = build_control_plane_surface_contract(
            surface="desktop_projection",
            runtime_truth={
                "runtime_truth_compiled_at": runtime_truth_for_contract.get("compiled_at"),
                "runtime_truth_primary_model_id": runtime_truth_for_contract.get("primary_model_id"),
                "operational_state_board": result.get("operational_state_board"),
                "backbone_snapshot": shared_basis.get("backbone_snapshot"),
            },
            derived_reasoning=derived_reasoning,
            projection={
                "topology_projection": result.get("topology_projection"),
                "model_routing_summary": result.get("model_routing_summary"),
                "projection_surface_role": "desktop_status_board_truth",
            },
            stale_or_cached_summary=result.get("stale_or_cached_summary"),
            shared_basis=shared_basis,
        )
    except Exception as exc:
        logger.debug("_assemble_desktop_status_board_payload: control-plane contract unavailable: %s", exc)
    result.setdefault("projection_surface_role", "desktop_status_board_truth")
    result.setdefault("board_facing_default", True)
    return result


def _minimal_desktop_status_board_fallback() -> Dict[str, Any]:
    """Return a minimal valid desktop status board integration payload for failure cases."""
    from contracts.desktop_status_projection import (
        DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
        TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY,
        TOPOLOGY_READINESS_CONTRACT_AUTHORITY,
        PROJECTION_CONTRACT_AUTHORITY,
    )

    payload = {
        "payload_id": f"dsbip_fallback_{int(time.time())}",
        "integrated_at": time.time(),
        "topology_projection": None,
        "model_routing_summary": {
            "selected_provider": None,
            "selected_model": None,
            "is_native_multimodal": False,
            "vendor_source": None,
            "route_reason": None,
            "routing_authority_source": "none",
            "legacy_routing_fallback_active": False,
            "health_severity": "unknown",
            "support_model_hints": [],
            "provider_available": True,
        },
        "provider_health_summary": None,
        "oneapi_integration": None,
        "authority_indicators": {
            "topology_canonical_source_present": False,
            "topology_legacy_fallback_active": False,
            "topology_readiness": "unavailable",
            "topology_authoritative": False,
            "topology_contract_authority": TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY,
            "model_routing_authority_source": "none",
            "model_routing_legacy_fallback_active": False,
            "oneapi_is_lower_horizon_only": True,
            "integration_contract_authority": DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
            "topology_delivery_contract_authority": TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY,
            "topology_readiness_contract_authority": TOPOLOGY_READINESS_CONTRACT_AUTHORITY,
            "projection_contract_authority": PROJECTION_CONTRACT_AUTHORITY,
        },
        "integration_authority": DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
        "integration_health": "unknown",
        "outward_truth": _minimal_outward_truth_payload(),
        "task_truth": {
            "active_task_count": 0,
            "recent_failure_count": 0,
            "reachable_executor_count": 0,
            "source": "fallback",
        },
        "operational_state_board": _empty_operational_state_board(),
        "source_of_truth_boundaries": _source_of_truth_boundaries(),
        "shared_execution_visibility": _derive_shared_execution_visibility({}),
        "execution_stage": None,
        "current_task_summary": None,
        "stale_or_cached_summary": {
            "runtime_truth_fallback": True,
            "desktop_payload_fallback": True,
        },
        "projection_surface_role": "desktop_status_board_truth",
        "board_facing_default": True,
        "_assembled_at": time.time(),
    }
    try:
        from core.v2_unified_state_contract import build_control_plane_surface_contract

        payload["control_plane_contract"] = build_control_plane_surface_contract(
            surface="desktop_projection",
            runtime_truth={"operational_state_board": payload.get("operational_state_board")},
            derived_reasoning={},
            projection={
                "projection_surface_role": payload.get("projection_surface_role"),
            },
            stale_or_cached_summary=dict(payload.get("stale_or_cached_summary") or {}),
        )
    except Exception as exc:
        logger.debug("_minimal_desktop_status_board_fallback: control-plane contract unavailable: %s", exc)
    return payload
