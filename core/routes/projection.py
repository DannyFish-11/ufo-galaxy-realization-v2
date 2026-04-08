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
from typing import Any, Dict, Optional

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
# canonical session truth snapshots when assembling runtime projections.
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

# Importing the PR-30 post-rollout observability and diagnostics hardening
# sentinels confirms that the V2 dispatch selection, registration/readiness/
# capability, delegated execution, fallback, and client-facing result surfaces
# expose actionable diagnostic signals for rollout safety within the existing
# single-system architecture after the PR-29 tightening baseline.
try:
    from core.runtime.source_dispatch_orchestrator import (  # noqa: F401
        POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_PR30_SENTINEL as _PR30_SENTINEL,
        DISPATCH_SELECTION_OBSERVABILITY_PR30_POLICY as _PR30_SELECTION_OBS,
        REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY as _PR30_REG_DIAG,
        DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY as _PR30_DELEGATED_OBS,
        CLIENT_RESULT_OBSERVABILITY_ROLLOUT_SAFETY_PR30_POLICY as _PR30_CLIENT_SAFETY,
        OPERATOR_DEVELOPER_DEBUG_CLARITY_PR30_POLICY as _PR30_DEBUG,
    )

    POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_ALIGNED_PR30: str = (
        "PROJECTION_ROUTES::POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_ALIGNED_PR30_V1: "
        "PR-30 post-rollout observability and diagnostics hardening is confirmed.  "
        "Dispatch-path selection observability (PR-24 scoring/gating/fallback signals), "
        "registration/readiness/capability/fallback diagnostics (PR-19/PR-22/PR-27 "
        "failure_kind vocabulary), delegated execution observable state transitions "
        "(PR-10/PR-16/PR-21/PR-23 phase signals), client/result rollout-safety signals "
        "(PR-26/PR-27/PR-29 dispatch_path+diagnostic_context), and operator/developer "
        "debug clarity (projection surfaces) are all hardened within the existing "
        "single-system V2 architecture.  No new diagnostics coordinator, alternate "
        "control authority, duplicate diagnostics subsystem, or parallel troubleshooting "
        "path is introduced."
    )
except ImportError:  # pragma: no cover
    POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_ALIGNED_PR30: str = (  # type: ignore[no-redef]
        "PROJECTION_ROUTES::POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_ALIGNED_PR30_UNAVAILABLE"
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

        The Status Board V2 polls this endpoint to render all its surfaces.

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
            try:
                coordinator = registry.get_mesh_session_coordinator(mesh_id="default_mesh")
                if coordinator is not None:
                    from contracts.mesh_session_coordinator import build_coordinator_summary

                    summary = build_coordinator_summary(coordinator=coordinator)
                    coordinator_summaries.append(summary.to_dict())
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
    async def get_desktop_status_board_integration() -> JSONResponse:
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
        payload = _assemble_desktop_status_board_payload()
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
        return snapshot.to_dict()
    except Exception as exc:
        logger.warning("_assemble_runtime_truth_payload: failed: %s", exc)
        from core.projection.runtime_truth_compiler import RUNTIME_TRUTH_COMPILER_AUTHORITY

        return {
            "compiled_at": time.time(),
            "compiler_authority": RUNTIME_TRUTH_COMPILER_AUTHORITY,
            "continuum": None,
            "topology": None,
            "oneapi": {"system_layer": "aggregator_integration", "configured": False},
            "system_resource": None,
            "device_presence": {"registered": 0, "online": 0},
            "has_canonical_topology": False,
            "tri_state_phase": None,
            "primary_model_id": None,
            "primary_provider_id": None,
            "oneapi_is_lower_horizon_only": True,
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
    continuum_state = _get_continuum_state()

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

    return payload


def _get_continuum_state():
    """Return the live ContinuumState, or a minimal silent state on failure."""
    try:
        # Try the cognitive field engine first (Block-3 integration).
        from core.cognitive.cognitive_field_engine import CognitiveFieldEngine

        engine = CognitiveFieldEngine.get_instance()
        if engine is not None and hasattr(engine, "get_continuum_state"):
            state = engine.get_continuum_state()
            if state is not None:
                return state
    except Exception:
        pass

    try:
        # Fallback: desktop presence runtime if available.
        from core.desktop_presence_runtime import get_presence_runtime

        runtime = get_presence_runtime()
        if runtime is not None and hasattr(runtime, "get_continuum_state"):
            state = runtime.get_continuum_state()
            if state is not None:
                return state
    except Exception:
        pass

    try:
        # Final fallback: minimal silent state so the board always renders.
        from core.continuum.types import ContinuumPhase, ContinuumState

        return ContinuumState(phase=ContinuumPhase.FORMLESS)
    except Exception:
        return None


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
            "desktop_status_endpoint": "/api/v1/projection/runtime",
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


def _assemble_desktop_status_board_payload() -> Dict[str, Any]:
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

    return result


def _minimal_desktop_status_board_fallback() -> Dict[str, Any]:
    """Return a minimal valid desktop status board integration payload for failure cases."""
    from contracts.desktop_status_projection import (
        DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
        TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY,
        TOPOLOGY_READINESS_CONTRACT_AUTHORITY,
        PROJECTION_CONTRACT_AUTHORITY,
    )

    return {
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
        "_assembled_at": time.time(),
    }
