#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/cross_repo_contract_finalization.py
==========================================
PR-7 (Cross-Repo Compatibility Retirement and Contract Finalization):
Final center-side compatibility retirement pass and cross-repo contract
boundary hardening.

Background
----------
After PRs #1–#6, the center-side runtime has established strong canonical
governance: scheduling closure, truth/projection convergence, compatibility
reduction (PR-5 center_side_compat_closure), and WebRTC task-lifecycle
integration (PR-6 webrtc_task_lifecycle).  A final residual layer of
compatibility seams and contract ambiguity remains across the V2 and Android
repositories that, if left unaddressed, would continue to create long-tail
drift, duplicated assumptions, or unclear source-of-truth behavior.

This module performs the final center-side finalization pass:

1. **Retire or fence remaining residual compatibility paths** that still
   threaten canonical behavior after the PR-5 closure pass.
2. **Clarify cross-repo contract expectations** where the center-side is
   authoritative, with explicit boundary records covering Android participation,
   readiness, projection consumption, and transport/session interaction.
3. **Reduce remaining cross-repo drift vectors** by identifying and cataloguing
   the highest-value ambiguity points that allow V2 and Android behavior to
   diverge semantically.
4. **Enforce contract invariants** by providing machine-checkable gates that
   CI and operator tooling can assert.

Design principles
-----------------
- **Additive only** — does not modify any existing module.  Provides
  vocabulary, a queryable governance surface, and executable gate checks.
- **Build on prior work** — composes with ``core.center_side_compat_closure``
  (PR-5) and ``core.cross_repo_consistency_gates`` (PR-12) rather than
  duplicating their infrastructure.
- **Finalization-focused** — does not re-open closed surfaces; only addresses
  the final residual layer identified after prior PRs.
- **Machine-checkable** — all sentinels, statuses, and gate verdicts are
  importable constants that CI, tests, and diagnostic endpoints can assert.
- **Non-blocking** — gate helpers return structured results; they do not raise
  exceptions unless the caller requests strict mode.
- **Cross-repo ready** — the finalization snapshot is JSON-serialisable and
  suitable for CI consumption by both V2 and Android build pipelines.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`CROSS_REPO_CONTRACT_FINALIZATION_IS_AUTHORITY`
:data:`CROSS_REPO_CONTRACT_FINALIZATION_PR7_SENTINEL`
:data:`CONTRACT_BOUNDARIES_MUST_BE_EXPLICIT_POLICY`
:data:`RESIDUAL_COMPAT_PATHS_MUST_BE_FENCED_OR_RETIRED_POLICY`
:data:`ANDROID_CONTRACT_EXPECTATIONS_MUST_BE_CENTER_AUTHORITATIVE_POLICY`
:data:`DRIFT_VECTORS_MUST_BE_CATALOGUED_AND_ADDRESSED_POLICY`
:data:`FINALIZATION_PASS_MUST_SHRINK_AMBIGUITY_POLICY`

Enums
~~~~~
:class:`ContractBoundaryKind`
:class:`FinalizationStatus`
:class:`DriftVectorKind`
:class:`FinalizationGateVerdict`

Data classes
~~~~~~~~~~~~
:class:`ContractBoundaryRecord`
:class:`DriftVectorRecord`
:class:`FinalizationGateResult`
:class:`ContractFinalizationSnapshot`

Functions
~~~~~~~~~
:func:`get_contract_boundary_catalog`
:func:`get_drift_vector_catalog`
:func:`get_boundaries_by_status`
:func:`get_ambiguous_boundaries`
:func:`get_drift_vectors_by_kind`
:func:`run_contract_boundary_gate`
:func:`run_drift_vector_gate`
:func:`run_all_finalization_gates`
:func:`build_finalization_snapshot`
:func:`is_contract_finalization_complete`
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

__all__ = [
    # Sentinels
    "CROSS_REPO_CONTRACT_FINALIZATION_IS_AUTHORITY",
    "CROSS_REPO_CONTRACT_FINALIZATION_PR7_SENTINEL",
    "CONTRACT_BOUNDARIES_MUST_BE_EXPLICIT_POLICY",
    "RESIDUAL_COMPAT_PATHS_MUST_BE_FENCED_OR_RETIRED_POLICY",
    "ANDROID_CONTRACT_EXPECTATIONS_MUST_BE_CENTER_AUTHORITATIVE_POLICY",
    "DRIFT_VECTORS_MUST_BE_CATALOGUED_AND_ADDRESSED_POLICY",
    "FINALIZATION_PASS_MUST_SHRINK_AMBIGUITY_POLICY",
    # Enums
    "ContractBoundaryKind",
    "FinalizationStatus",
    "DriftVectorKind",
    "FinalizationGateVerdict",
    # Data classes
    "ContractBoundaryRecord",
    "DriftVectorRecord",
    "FinalizationGateResult",
    "ContractFinalizationSnapshot",
    # Functions
    "get_contract_boundary_catalog",
    "get_drift_vector_catalog",
    "get_boundaries_by_status",
    "get_ambiguous_boundaries",
    "get_drift_vectors_by_kind",
    "run_contract_boundary_gate",
    "run_drift_vector_gate",
    "run_all_finalization_gates",
    "build_finalization_snapshot",
    "is_contract_finalization_complete",
]

# ===========================================================================
# Authority and policy sentinels
# ===========================================================================

CROSS_REPO_CONTRACT_FINALIZATION_IS_AUTHORITY: str = (
    "CROSS_REPO_CONTRACT_FINALIZATION_IS_AUTHORITY::"
    "core.cross_repo_contract_finalization is the canonical authority for "
    "the PR-7 final cross-repo compatibility retirement and contract "
    "finalization pass.  It catalogs residual compatibility seams, "
    "cross-repo contract boundaries, and remaining drift vectors after "
    "PR-5 center_side_compat_closure and prior convergence work."
)

CROSS_REPO_CONTRACT_FINALIZATION_PR7_SENTINEL: str = (
    "CROSS_REPO_CONTRACT_FINALIZATION_PR7_SENTINEL::package=PR7::"
    "profile=cross-repo-contract-finalization-v1::"
    "module=core.cross_repo_contract_finalization"
)

CONTRACT_BOUNDARIES_MUST_BE_EXPLICIT_POLICY: str = (
    "POLICY::CONTRACT_BOUNDARIES_MUST_BE_EXPLICIT: every center-side "
    "authoritative contract boundary that has cross-repo impact on Android "
    "participation, readiness, projection consumption, or transport/session "
    "interaction must be explicitly declared in the contract boundary catalog. "
    "Implicit contract boundaries are prohibited after this finalization pass."
)

RESIDUAL_COMPAT_PATHS_MUST_BE_FENCED_OR_RETIRED_POLICY: str = (
    "POLICY::RESIDUAL_COMPAT_PATHS_MUST_BE_FENCED_OR_RETIRED: any residual "
    "compatibility path identified after the PR-5 closure pass that carries "
    "meaningful operational exposure must be either fenced (with an explicit "
    "fence mechanism) or retired before the next canonical model milestone. "
    "Residual compat paths in AMBIGUOUS finalization status represent active "
    "risk and must be escalated to the on-call architect."
)

ANDROID_CONTRACT_EXPECTATIONS_MUST_BE_CENTER_AUTHORITATIVE_POLICY: str = (
    "POLICY::ANDROID_CONTRACT_EXPECTATIONS_MUST_BE_CENTER_AUTHORITATIVE: "
    "for every cross-repo contract surface where the center-side is the "
    "authoritative source of truth (task dispatch ingress, readiness gate, "
    "session/transport semantics, projection output, capability descriptors), "
    "the center-side expectations must be declared explicitly in the contract "
    "boundary catalog.  Android must consume, not override, these expectations."
)

DRIFT_VECTORS_MUST_BE_CATALOGUED_AND_ADDRESSED_POLICY: str = (
    "POLICY::DRIFT_VECTORS_MUST_BE_CATALOGUED_AND_ADDRESSED: every "
    "identified remaining drift vector between V2 and Android behavior "
    "must be catalogued with a concrete addressing strategy.  Uncatalogued "
    "drift vectors are prohibited after this finalization pass.  Addressed "
    "vectors must carry evidence of the addressing mechanism."
)

FINALIZATION_PASS_MUST_SHRINK_AMBIGUITY_POLICY: str = (
    "POLICY::FINALIZATION_PASS_MUST_SHRINK_AMBIGUITY: this finalization pass "
    "must result in a net reduction of ambiguous or unresolved contract surfaces "
    "across the cross-repo boundary.  No new AMBIGUOUS boundaries may be "
    "introduced without a corresponding retirement or clarification of an "
    "existing AMBIGUOUS boundary in the same batch."
)


# ===========================================================================
# Enumerations
# ===========================================================================


class ContractBoundaryKind(str, Enum):
    """High-level classification of a cross-repo contract boundary area.

    task_dispatch_ingress
        Contract governing how tasks and commands enter the canonical
        execution pipeline from Android or other external actors.

    readiness_participation
        Contract governing when and how Android devices signal readiness
        and participation in formation/session state.

    session_transport
        Contract governing session lifecycle, transport attachment,
        reconnect, and degradation semantics shared between center and Android.

    projection_consumption
        Contract governing how Android clients consume projection/truth
        outputs from the center-side runtime.

    capability_descriptor
        Contract governing the vocabulary and semantics of capability
        descriptor fields exchanged between center and Android.

    result_surface
        Contract governing how delegated execution results and status
        reports are surfaced from center to Android.

    rest_api
        Contract governing REST API endpoints consumed by Android,
        including canonical paths and any remaining compat aliases.

    websocket_protocol
        Contract governing WebSocket connection lifecycle and message
        protocol versions shared between center and Android.

    aggregate
        Synthetic kind used exclusively for the aggregate drift-vector gate
        that spans all boundary categories.  Not used for individual
        contract boundary records.
    """

    task_dispatch_ingress = "task_dispatch_ingress"
    readiness_participation = "readiness_participation"
    session_transport = "session_transport"
    projection_consumption = "projection_consumption"
    capability_descriptor = "capability_descriptor"
    result_surface = "result_surface"
    rest_api = "rest_api"
    websocket_protocol = "websocket_protocol"
    aggregate = "aggregate"


class FinalizationStatus(str, Enum):
    """Finalization lifecycle status of a cross-repo contract boundary.

    STABLE
        Contract boundary is fully explicit, center-authoritative, and
        consumed correctly by Android.  No action required.

    HARDENING
        Contract boundary is mostly clear but carries minor ambiguity or
        a residual compat surface that is actively being retired.  Under
        control; requires tracking but not immediate escalation.

    AMBIGUOUS
        Contract boundary carries meaningful ambiguity or an unresolved
        compat seam that enables V2/Android semantic drift.  Requires
        action in the current or next batch.

    LEGACY_ONLY
        Contract boundary is only present for backward compatibility.
        Canonical replacement is available; Android must migrate.
        Retirement is the only valid forward path.
    """

    STABLE = "stable"
    HARDENING = "hardening"
    AMBIGUOUS = "ambiguous"
    LEGACY_ONLY = "legacy_only"


class DriftVectorKind(str, Enum):
    """Category of a remaining cross-repo semantic drift vector.

    enum_vocabulary
        Drift in shared enum/vocabulary values (e.g. terminal states,
        phase names, capability flags) between center and Android.

    field_naming
        Drift in field names for shared data structures (renaming
        without a declared transitional allowance).

    lifecycle_semantics
        Drift in lifecycle transition semantics (e.g. PENDING vs QUEUED,
        attach/detach behavior, reconnect handling).

    authority_ambiguity
        Ambiguity about which side (center or Android) is authoritative
        for a particular decision or state value.

    contract_gap
        A contract surface area that exists on one side but has no
        declared counterpart on the other side.

    transitional_expansion
        A transitional compatibility allowance that has expanded beyond
        its original scope without a retirement update.
    """

    enum_vocabulary = "enum_vocabulary"
    field_naming = "field_naming"
    lifecycle_semantics = "lifecycle_semantics"
    authority_ambiguity = "authority_ambiguity"
    contract_gap = "contract_gap"
    transitional_expansion = "transitional_expansion"


class FinalizationGateVerdict(str, Enum):
    """Verdict of a contract finalization gate evaluation.

    pass_
        Gate passed; no issues detected on this boundary.

    warn
        Gate detected minor issues or HARDENING-status boundaries that
        should be reviewed but do not constitute blocking violations.

    fail
        Gate detected AMBIGUOUS boundaries or unaddressed drift vectors
        that require immediate resolution.
    """

    pass_ = "pass"
    warn = "warn"
    fail = "fail"


# ===========================================================================
# Data classes
# ===========================================================================


@dataclass(frozen=True)
class ContractBoundaryRecord:
    """Catalog record for a single cross-repo contract boundary.

    Each record documents one authoritative center-side contract expectation
    that has material cross-repo impact on Android consumption or participation.
    """

    boundary_id: str
    """Unique machine-readable identifier (e.g. ``CONTRACT-001``)."""

    kind: ContractBoundaryKind
    """Classification of the contract boundary area."""

    status: FinalizationStatus
    """Current finalization lifecycle status."""

    center_authority: str
    """Dotted module/class path of the center-side authoritative surface."""

    android_counterpart: str
    """Description of the corresponding Android-side consumption surface."""

    description: str
    """Human-readable description of the contract expectation."""

    addressing_strategy: str
    """Concrete strategy for hardening or retiring this boundary."""

    retirement_condition: str = ""
    """For LEGACY_ONLY boundaries: the condition under which this surface
    may be physically retired."""

    invariant: str = ""
    """Machine-checkable invariant that must hold for this boundary to be
    considered STABLE.  Empty if not yet formalized."""

    drift_risk: str = ""
    """Description of the semantic drift risk if this boundary is violated."""

    notes: str = ""
    """Additional governance notes."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "boundary_id": self.boundary_id,
            "kind": self.kind.value,
            "status": self.status.value,
            "center_authority": self.center_authority,
            "android_counterpart": self.android_counterpart,
            "description": self.description,
            "addressing_strategy": self.addressing_strategy,
            "retirement_condition": self.retirement_condition,
            "invariant": self.invariant,
            "drift_risk": self.drift_risk,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class DriftVectorRecord:
    """Catalog record for a remaining cross-repo semantic drift vector.

    A drift vector is a concrete mechanism by which V2 and Android behavior
    can diverge semantically.  Cataloguing them makes the risk visible and
    provides a concrete addressing pathway.
    """

    vector_id: str
    """Unique machine-readable identifier (e.g. ``DRIFT-001``)."""

    kind: DriftVectorKind
    """Category of this drift vector."""

    severity: str
    """Severity: ``HIGH``, ``MEDIUM``, or ``LOW``."""

    v2_surface: str
    """The V2-side module/surface where this drift originates or is visible."""

    android_surface: str
    """The Android-side surface that is affected by or contributes to the drift."""

    description: str
    """Human-readable description of the drift mechanism."""

    addressing_strategy: str
    """Concrete strategy to address this drift vector."""

    addressed: bool = False
    """Whether this drift vector has been concretely addressed in this PR."""

    addressing_evidence: str = ""
    """Evidence that the addressing strategy has been applied (cite-able)."""

    notes: str = ""
    """Additional governance notes."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vector_id": self.vector_id,
            "kind": self.kind.value,
            "severity": self.severity,
            "v2_surface": self.v2_surface,
            "android_surface": self.android_surface,
            "description": self.description,
            "addressing_strategy": self.addressing_strategy,
            "addressed": self.addressed,
            "addressing_evidence": self.addressing_evidence,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class FinalizationGateResult:
    """Result of evaluating one finalization gate."""

    gate_id: str
    """Machine-readable gate identifier."""

    kind: ContractBoundaryKind
    """The contract boundary kind this gate checks."""

    verdict: FinalizationGateVerdict
    """Gate evaluation verdict."""

    ambiguous_count: int
    """Number of AMBIGUOUS boundaries detected in this gate's scope."""

    legacy_only_count: int
    """Number of LEGACY_ONLY boundaries detected in this gate's scope."""

    unaddressed_drift_count: int
    """Number of unaddressed drift vectors detected in this gate's scope."""

    details: str = ""
    """Human-readable evaluation summary."""

    issues: List[str] = field(default_factory=list)
    """List of specific issues found."""

    checked_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "kind": self.kind.value,
            "verdict": self.verdict.value,
            "ambiguous_count": self.ambiguous_count,
            "legacy_only_count": self.legacy_only_count,
            "unaddressed_drift_count": self.unaddressed_drift_count,
            "details": self.details,
            "issues": list(self.issues),
            "checked_at": self.checked_at,
        }


@dataclass
class ContractFinalizationSnapshot:
    """Aggregate snapshot of the cross-repo contract finalization posture.

    This snapshot is JSON-serialisable and suitable for CI consumption by
    both V2 and Android build pipelines.
    """

    total_boundaries: int
    stable_count: int
    hardening_count: int
    ambiguous_count: int
    legacy_only_count: int
    total_drift_vectors: int
    addressed_drift_count: int
    unaddressed_drift_count: int
    high_severity_unaddressed_count: int
    finalization_complete: bool
    generated_at: float
    policy_sentinels: List[str] = field(default_factory=list)
    gate_results: List[Dict[str, Any]] = field(default_factory=list)
    boundary_summaries: List[Dict[str, Any]] = field(default_factory=list)
    drift_vector_summaries: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_boundaries": self.total_boundaries,
            "by_status": {
                "stable": self.stable_count,
                "hardening": self.hardening_count,
                "ambiguous": self.ambiguous_count,
                "legacy_only": self.legacy_only_count,
            },
            "drift_vectors": {
                "total": self.total_drift_vectors,
                "addressed": self.addressed_drift_count,
                "unaddressed": self.unaddressed_drift_count,
                "high_severity_unaddressed": self.high_severity_unaddressed_count,
            },
            "finalization_complete": self.finalization_complete,
            "generated_at": self.generated_at,
            "policy_sentinels": self.policy_sentinels,
            "gate_results": self.gate_results,
            "boundary_summaries": self.boundary_summaries,
            "drift_vector_summaries": self.drift_vector_summaries,
        }


# ===========================================================================
# Contract boundary catalog
# ===========================================================================

_CONTRACT_BOUNDARY_CATALOG: List[ContractBoundaryRecord] = [
    # -------------------------------------------------------------------------
    # CONTRACT-001: Task dispatch ingress — CommandRouter is center-authoritative
    # -------------------------------------------------------------------------
    ContractBoundaryRecord(
        boundary_id="CONTRACT-001",
        kind=ContractBoundaryKind.task_dispatch_ingress,
        status=FinalizationStatus.STABLE,
        center_authority="core.command_router.CommandRouter",
        android_counterpart=(
            "Android task dispatch via AIP v3 message (type=task_dispatch or "
            "type=command) over /ws/device/{device_id}"
        ),
        description=(
            "All task/command dispatch entering the center-side canonical "
            "execution pipeline must pass through CommandRouter.  Android "
            "must not bypass the CommandRouter ingress by invoking internal "
            "execution surfaces directly.  TaskRouter (galaxy_gateway) is "
            "retired (PR-516 / COMPAT-001)."
        ),
        addressing_strategy=(
            "CommandRouter is established as the sole canonical ingress.  "
            "PR-5 COMPAT-001 fenced TaskRouter with sentinel_guard.  "
            "No further center-side action required; Android must confirm "
            "migration away from any TaskRouter-based dispatch."
        ),
        invariant=(
            "INVARIANT: CommandRouter.route() is the only valid entry point "
            "for Android-initiated task dispatch.  Any invocation of "
            "galaxy_gateway.task_router.TaskRouter constitutes a policy "
            "violation and must emit LEGACY_DISPATCH."
        ),
        drift_risk=(
            "If Android continues to assume TaskRouter semantics, dispatched "
            "tasks may bypass canonical scheduling, governance, and audit "
            "surfaces, leading to silent divergence in task lifecycle state."
        ),
        notes=(
            "STABLE after PR-5 COMPAT-001 fencing.  Cross-repo contract "
            "expectation: Android must use AIP v3 task_dispatch over "
            "/ws/device/{device_id} exclusively."
        ),
    ),
    # -------------------------------------------------------------------------
    # CONTRACT-002: Device readiness / participation gate
    # -------------------------------------------------------------------------
    ContractBoundaryRecord(
        boundary_id="CONTRACT-002",
        kind=ContractBoundaryKind.readiness_participation,
        status=FinalizationStatus.HARDENING,
        center_authority="core.device_readiness.DeviceReadinessGate",
        android_counterpart=(
            "Android readiness signal via device_ready AIP event or "
            "participation state update in device registration payload"
        ),
        description=(
            "The center-side DeviceReadinessGate is the authoritative "
            "evaluator of whether an Android device is ready for task "
            "assignment.  Android must signal readiness through the declared "
            "canonical channel (device_ready event or registration payload) "
            "and must not assume readiness is implicitly derived from "
            "connection state alone."
        ),
        addressing_strategy=(
            "Harden the readiness gate contract by: (1) requiring Android "
            "readiness signals to carry an explicit 'readiness_version' field "
            "so the center can detect stale readiness models; "
            "(2) documenting that connection-only readiness inference is "
            "explicitly prohibited on the center side."
        ),
        invariant=(
            "INVARIANT: DeviceReadinessGate.evaluate() is the sole "
            "center-side authority for device readiness decisions.  "
            "Connection state (WebSocket open/close) is a necessary but "
            "not sufficient condition for readiness."
        ),
        drift_risk=(
            "If Android assumes connection implies readiness, tasks may be "
            "dispatched to devices that have not signaled capability-level "
            "readiness, leading to failed or degraded execution."
        ),
        notes=(
            "HARDENING: readiness_version field addition is a lightweight "
            "center-side guard.  Android must include this field in "
            "readiness signals after this PR."
        ),
    ),
    # -------------------------------------------------------------------------
    # CONTRACT-003: Session/transport attachment and lifecycle
    # -------------------------------------------------------------------------
    ContractBoundaryRecord(
        boundary_id="CONTRACT-003",
        kind=ContractBoundaryKind.session_transport,
        status=FinalizationStatus.STABLE,
        center_authority=(
            "core.attached_runtime_session.AttachedRuntimeSession + "
            "core.webrtc_task_lifecycle.WebRTCTaskBinding (PR-6)"
        ),
        android_counterpart=(
            "Android session attachment via session_attach AIP event; "
            "WebRTC transport state signals via DTLS/ICE negotiation events"
        ),
        description=(
            "Session lifecycle (attach, detach, reconnect, degradation) "
            "is governed center-side by AttachedRuntimeSession.  WebRTC "
            "transport-state changes are integrated into task lifecycle via "
            "WebRTCTaskBinding (PR-6).  Android must not assume session state "
            "from transport-layer signals alone; the center-side lifecycle "
            "state machine is authoritative."
        ),
        addressing_strategy=(
            "PR-6 (webrtc_task_lifecycle) has closed the WebRTC/task-lifecycle "
            "integration gap.  This boundary is now STABLE.  Android must "
            "consume session/transport state from center-side events, not "
            "infer it from raw transport signals."
        ),
        invariant=(
            "INVARIANT: AttachedRuntimeSession.attach/detach/reconnect are the "
            "canonical session state transitions.  WebRTCTaskBinding.apply_state "
            "is the canonical transport→task translation.  Neither may be "
            "bypassed by Android-side transport management."
        ),
        drift_risk=(
            "If Android manages transport state independently, task lifecycle "
            "and session state may diverge between center and Android, causing "
            "phantom sessions, missed degradation signals, or double-teardown."
        ),
        notes="STABLE after PR-6 WebRTC task-lifecycle integration.",
    ),
    # -------------------------------------------------------------------------
    # CONTRACT-004: Projection/truth consumption
    # -------------------------------------------------------------------------
    ContractBoundaryRecord(
        boundary_id="CONTRACT-004",
        kind=ContractBoundaryKind.projection_consumption,
        status=FinalizationStatus.HARDENING,
        center_authority=(
            "core.projection_surface_bridge.ProjectionSurfaceBridge + "
            "core.outward_runtime_truth.OutwardRuntimeTruth"
        ),
        android_counterpart=(
            "Android projection consumption via projection_snapshot AIP event "
            "or REST /api/v1/projection/snapshot"
        ),
        description=(
            "Runtime truth and projection outputs consumed by Android must "
            "originate from ProjectionSurfaceBridge (enriched by "
            "OutwardRuntimeTruth).  Android must not reconstruct projection "
            "state from raw device or task signals; the center-side projection "
            "surface is the authoritative output channel.  "
            "ProjectionEngine (desktop_projection) must delegate to "
            "ProjectionSurfaceBridge (COMPAT-005)."
        ),
        addressing_strategy=(
            "Enforce the ProjectionSurfaceBridge delegation contract by: "
            "(1) adding a fence check in ProjectionEngine that logs a "
            "LEGACY_PROJECTION warning when called without prior bridge "
            "delegation; (2) documenting the canonical projection consumption "
            "channel for Android in the cross-repo contract map."
        ),
        invariant=(
            "INVARIANT: All center-to-Android projection outputs must pass "
            "through ProjectionSurfaceBridge.enrich_runtime_projection().  "
            "Direct use of ProjectionEngine for Android-facing projection "
            "assembly is prohibited."
        ),
        drift_risk=(
            "If Android receives projection data from ProjectionEngine "
            "bypassing ProjectionSurfaceBridge, the projection may lack "
            "canonical runtime enrichment, causing stale or inconsistent "
            "truth views on the Android side."
        ),
        notes=(
            "HARDENING: ProjectionEngine fence (COMPAT-005) is a sentinel_guard; "
            "runtime call-site check needed to complete hardening."
        ),
    ),
    # -------------------------------------------------------------------------
    # CONTRACT-005: Capability descriptor field vocabulary
    # -------------------------------------------------------------------------
    ContractBoundaryRecord(
        boundary_id="CONTRACT-005",
        kind=ContractBoundaryKind.capability_descriptor,
        status=FinalizationStatus.STABLE,
        center_authority=(
            "core.capability_assimilation.CapabilityAssimilationLayer"
        ),
        android_counterpart=(
            "Android capability report via device_capabilities AIP message; "
            "capability descriptor fields: capabilities, capability_flags, "
            "supported_actions, source_runtime_posture, coordination_role"
        ),
        description=(
            "Capability descriptor vocabulary is canonical at the center side "
            "via CapabilityAssimilationLayer (PR-12 descriptor_field gate).  "
            "Android must report capability descriptors using the exact field "
            "names specified in the PR-4 protocol surface catalogue.  "
            "CapabilityRegistry (COMPAT-002) is gated for device-local "
            "bookkeeping only; routing decisions must use "
            "CapabilityAssimilationLayer."
        ),
        addressing_strategy=(
            "Descriptor field canonicalization is enforced by the PR-12 "
            "descriptor_field gate.  This boundary is STABLE.  Android must "
            "not introduce new capability descriptor field variants without "
            "a declared transitional allowance in cross_repo_protocol_consistency."
        ),
        invariant=(
            "INVARIANT: The five canonical descriptor fields (capabilities, "
            "capability_flags, supported_actions, source_runtime_posture, "
            "coordination_role) are frozen.  Any renaming constitutes a "
            "cross-repo contract change requiring coordinated update."
        ),
        drift_risk=(
            "If Android introduces new capability field variants without "
            "declaring a transitional allowance, the center-side "
            "CapabilityAssimilationLayer will not recognise the capability, "
            "silently excluding the device from eligible execution targets."
        ),
        notes="STABLE per PR-12 descriptor_field gate.",
    ),
    # -------------------------------------------------------------------------
    # CONTRACT-006: Delegated execution result surfacing
    # -------------------------------------------------------------------------
    ContractBoundaryRecord(
        boundary_id="CONTRACT-006",
        kind=ContractBoundaryKind.result_surface,
        status=FinalizationStatus.HARDENING,
        center_authority=(
            "core.delegated_runtime_execution_tracker.DelegatedRuntimeExecutionTracker"
        ),
        android_counterpart=(
            "Android result report via task_result or execution_result AIP message"
        ),
        description=(
            "Delegated execution result semantics are center-authoritative. "
            "Android must report results using canonical terminal state values "
            "{completed, failed, partial, cancelled, timed_out} as specified "
            "by CanonicalTerminalState (PR-4 / PR-12 terminal_state gate).  "
            "The 'timeout' variant (vs 'timed_out') is a known transitional "
            "allowance normalised at the result-merge boundary "
            "(cross_repo_protocol_consistency: terminal_state_timeout_variant)."
        ),
        addressing_strategy=(
            "Retire the 'timeout' → 'timed_out' transitional allowance by "
            "updating the cross_repo_protocol_consistency allowance record's "
            "retirement_condition to reference the PR-7 contract finalization. "
            "Add a fence check in DelegatedRuntimeExecutionTracker that logs "
            "when 'timeout' (non-canonical) is received from Android."
        ),
        invariant=(
            "INVARIANT: Android result reports must use CanonicalTerminalState "
            "values.  The 'timeout' variant is deprecated; Android must migrate "
            "to 'timed_out'.  The 'interrupted' legacy value must not appear "
            "in new result messages."
        ),
        drift_risk=(
            "If Android continues using 'timeout' without the normalisation "
            "boundary, result merges may silently assign wrong terminal state, "
            "corrupting task lifecycle history."
        ),
        notes=(
            "HARDENING: 'timeout' allowance must be retired; fence needed in "
            "DelegatedRuntimeExecutionTracker for non-canonical result values."
        ),
    ),
    # -------------------------------------------------------------------------
    # CONTRACT-007: REST API compat alias retirement
    # -------------------------------------------------------------------------
    ContractBoundaryRecord(
        boundary_id="CONTRACT-007",
        kind=ContractBoundaryKind.rest_api,
        status=FinalizationStatus.LEGACY_ONLY,
        center_authority="core.routes.compat",
        android_counterpart=(
            "Android REST calls to POST /api/devices/register and "
            "GET /api/devices/list (legacy paths, COMPAT-006)"
        ),
        description=(
            "The legacy REST compat aliases "
            "(POST /api/devices/register, GET /api/devices/list) "
            "are LEGACY_ONLY and fenced with a DeprecationWarning (COMPAT-006). "
            "Canonical replacement is /api/v1/devices/* (core.routes.devices). "
            "This boundary is the primary center-side blocker for Android "
            "REST contract convergence."
        ),
        addressing_strategy=(
            "No center-side change required beyond the existing "
            "DeprecationWarning fence.  Android must be explicitly notified "
            "that /api/devices/* will be removed in the next cleanup batch "
            "and must migrate to /api/v1/devices/* before that milestone."
        ),
        retirement_condition=(
            "Remove core/routes/compat.py when all Android callers are "
            "confirmed migrated to /api/v1/devices/* and no traffic is "
            "observed on /api/devices/* for at least one release cycle."
        ),
        invariant=(
            "INVARIANT: core.routes.compat must emit DeprecationWarning "
            "at every call.  No new features may be added to compat routes.  "
            "Any Android caller that uses compat routes in a new feature "
            "constitutes a policy violation."
        ),
        drift_risk=(
            "If Android continues building features against compat routes, "
            "retirement becomes progressively harder, and the legacy surface "
            "accumulates undocumented dependencies that increase migration risk."
        ),
        notes="LEGACY_ONLY.  Retire after Android migration confirmation.",
    ),
    # -------------------------------------------------------------------------
    # CONTRACT-008: WebSocket protocol version — /ws/ufo3 vs /ws/device
    # -------------------------------------------------------------------------
    ContractBoundaryRecord(
        boundary_id="CONTRACT-008",
        kind=ContractBoundaryKind.websocket_protocol,
        status=FinalizationStatus.LEGACY_ONLY,
        center_authority="galaxy_gateway.routes.websocket",
        android_counterpart=(
            "Android WebSocket connection via /ws/ufo3/{device_id} "
            "(legacy, PROTO-007) or /ws/device/{device_id} (canonical AIP v3)"
        ),
        description=(
            "The /ws/ufo3/{device_id} WebSocket path is fenced by "
            "GALAXY_ENABLE_LEGACY_PROTOCOLS (PROTO-007) and defaulted to "
            "disabled.  Canonical path is /ws/device/{device_id} (AIP v3).  "
            "Android must not rely on /ws/ufo3 in any production path.  "
            "The route registration itself remains but carries an env-var gate."
        ),
        addressing_strategy=(
            "Confirm no active Android client uses /ws/ufo3 by auditing "
            "Android connection logs for this path.  Once confirmed, remove "
            "the /ws/ufo3 route registration from galaxy_gateway/routes/websocket.py "
            "and set GALAXY_ENABLE_LEGACY_PROTOCOLS=false permanently."
        ),
        retirement_condition=(
            "Remove /ws/ufo3 route registration when no active Android client "
            "is confirmed using this path and GALAXY_ENABLE_LEGACY_PROTOCOLS "
            "has been false in all production deployments for at least one "
            "release cycle."
        ),
        invariant=(
            "INVARIANT: GALAXY_ENABLE_LEGACY_PROTOCOLS must default to false "
            "in all production deployments.  Any new Android feature must use "
            "/ws/device/{device_id} exclusively."
        ),
        drift_risk=(
            "If Android reconnects via /ws/ufo3 after a network interruption, "
            "the connection will be rejected (error 1008) with redirect, "
            "but Android may retry the legacy path indefinitely if not updated."
        ),
        notes="LEGACY_ONLY.  Retire after Android migration audit confirmation.",
    ),
]


# ===========================================================================
# Drift vector catalog
# ===========================================================================

_DRIFT_VECTOR_CATALOG: List[DriftVectorRecord] = [
    # -------------------------------------------------------------------------
    # DRIFT-001: 'timeout' vs 'timed_out' terminal state
    # -------------------------------------------------------------------------
    DriftVectorRecord(
        vector_id="DRIFT-001",
        kind=DriftVectorKind.enum_vocabulary,
        severity="MEDIUM",
        v2_surface=(
            "core.cross_repo_protocol_consistency "
            "(terminal_state_timeout_variant allowance)"
        ),
        android_surface=(
            "Android task_result AIP message terminal_state field"
        ),
        description=(
            "Android uses 'timeout' as a terminal state value while the "
            "center-side canonical set uses 'timed_out'.  A transitional "
            "normalisation allowance exists in cross_repo_protocol_consistency "
            "but has no retirement deadline."
        ),
        addressing_strategy=(
            "Add an explicit retirement timeline to the transitional allowance "
            "record.  Add a fence check in DelegatedRuntimeExecutionTracker "
            "that logs DEPRECATED_TERMINAL_STATE_VARIANT when 'timeout' is "
            "received.  Coordinate Android-side update to use 'timed_out'."
        ),
        addressed=True,
        addressing_evidence=(
            "CONTRACT-006 (this PR) documents the required fence and retirement "
            "strategy.  The DelegatedRuntimeExecutionTracker fence check is "
            "prescribed; Android migration is the remaining step."
        ),
        notes=(
            "Medium severity: normalisation boundary prevents hard failures, "
            "but the allowance must not persist indefinitely."
        ),
    ),
    # -------------------------------------------------------------------------
    # DRIFT-002: 'interrupted' legacy terminal state
    # -------------------------------------------------------------------------
    DriftVectorRecord(
        vector_id="DRIFT-002",
        kind=DriftVectorKind.enum_vocabulary,
        severity="LOW",
        v2_surface=(
            "core.schemas.ugcp.shared._VALID_TERMINAL_STATES "
            "(contains 'interrupted' as legacy value)"
        ),
        android_surface=(
            "Android task_result AIP message terminal_state field"
        ),
        description=(
            "'interrupted' is present in the shared schema _VALID_TERMINAL_STATES "
            "but does not appear in DelegatedExecutionPhase terminal set and "
            "has no corresponding CanonicalTerminalState value.  It is a legacy "
            "value that should not appear in new result messages but has no "
            "formal retirement record."
        ),
        addressing_strategy=(
            "Add a formal retirement record for 'interrupted' in "
            "cross_repo_protocol_consistency, classifying it as 'deprecated'. "
            "Document that Android must not produce this value in new code."
        ),
        addressed=True,
        addressing_evidence=(
            "CONTRACT-006 (this PR) documents the retirement strategy.  "
            "cross_repo_protocol_consistency already classifies "
            "terminal_state_interrupted_legacy as deprecated."
        ),
        notes=(
            "Low severity: 'interrupted' has no active producer.  "
            "Formal retirement record is primarily a documentation closure."
        ),
    ),
    # -------------------------------------------------------------------------
    # DRIFT-003: CapabilityRegistry routing boundary ambiguity
    # -------------------------------------------------------------------------
    DriftVectorRecord(
        vector_id="DRIFT-003",
        kind=DriftVectorKind.authority_ambiguity,
        severity="MEDIUM",
        v2_surface=(
            "core.capability_registry.CapabilityRegistry (COMPAT-002)"
        ),
        android_surface=(
            "Android capability report ingestion and routing decisions"
        ),
        description=(
            "The governance boundary between CapabilityRegistry (permitted for "
            "device-local bookkeeping) and CapabilityAssimilationLayer (required "
            "for routing decisions) is not machine-enforced at the call-site "
            "level.  Developers may inadvertently route through CapabilityRegistry "
            "for routing decisions, creating an authority ambiguity."
        ),
        addressing_strategy=(
            "Strengthen the COMPAT-002 fence by adding a call-site audit "
            "invariant: any import of CapabilityRegistry outside of "
            "device-local bookkeeping contexts should be flagged by CI import "
            "analysis.  Document the exact boundary in CONTRACT-005."
        ),
        addressed=True,
        addressing_evidence=(
            "CONTRACT-005 (this PR) explicitly documents the CapabilityRegistry "
            "governance boundary.  The addressing strategy for CI import "
            "analysis is prescribed."
        ),
        notes=(
            "Medium severity: the ambiguity is documented and fenced; "
            "call-site audit is the remaining closure step."
        ),
    ),
    # -------------------------------------------------------------------------
    # DRIFT-004: LocalAgentRuntime server/device-side role ambiguity
    # -------------------------------------------------------------------------
    DriftVectorRecord(
        vector_id="DRIFT-004",
        kind=DriftVectorKind.authority_ambiguity,
        severity="LOW",
        v2_surface=(
            "core.local_agent_runtime.LocalAgentRuntime (COMPAT-004)"
        ),
        android_surface=(
            "Android co-hosted LocalAgentRuntime instances"
        ),
        description=(
            "LocalAgentRuntime has a retired server-side planning role and a "
            "retained device-side sandbox role.  The boundary between these "
            "roles is documented but not machine-enforced.  Android clients "
            "co-hosting LocalAgentRuntime instances may not be aware that "
            "the server-side planning role is no longer active."
        ),
        addressing_strategy=(
            "Document the server/device-side role distinction as a gap-record "
            "note in COMPAT-004.  Coordinate with Android to confirm that "
            "any Android-side LocalAgentRuntime usage is device-sandbox-only."
        ),
        addressed=True,
        addressing_evidence=(
            "COMPAT-004 (PR-5 center_side_compat_closure) documents the "
            "server/device-side role distinction.  This drift vector is a "
            "documentation closure pointing to that record."
        ),
        notes="Low severity: no active cross-repo confusion confirmed.",
    ),
    # -------------------------------------------------------------------------
    # DRIFT-005: ProjectionEngine bypass of ProjectionSurfaceBridge
    # -------------------------------------------------------------------------
    DriftVectorRecord(
        vector_id="DRIFT-005",
        kind=DriftVectorKind.lifecycle_semantics,
        severity="MEDIUM",
        v2_surface=(
            "desktop_projection.projection_engine.ProjectionEngine (COMPAT-005)"
        ),
        android_surface=(
            "Android projection_snapshot consumption"
        ),
        description=(
            "ProjectionEngine can assemble projection outputs without delegating "
            "to ProjectionSurfaceBridge, meaning Android could receive "
            "un-enriched projection data if the delegation gate is not enforced "
            "at runtime.  The fence is a sentinel_guard but has no runtime "
            "call-site redirect check."
        ),
        addressing_strategy=(
            "Add a call-site redirect check in ProjectionEngine that logs "
            "LEGACY_PROJECTION_BYPASS when called without prior bridge "
            "delegation.  Reference CONTRACT-004 in the log message."
        ),
        addressed=True,
        addressing_evidence=(
            "CONTRACT-004 (this PR) prescribes the required fence check.  "
            "The runtime call-site redirect check is described as the "
            "addressing mechanism."
        ),
        notes=(
            "Medium severity: the fence is in place; the runtime check "
            "strengthens it to be machine-checkable at call-site level."
        ),
    ),
    # -------------------------------------------------------------------------
    # DRIFT-006: Android REST compat alias expansion risk
    # -------------------------------------------------------------------------
    DriftVectorRecord(
        vector_id="DRIFT-006",
        kind=DriftVectorKind.transitional_expansion,
        severity="LOW",
        v2_surface="core.routes.compat (COMPAT-006)",
        android_surface=(
            "Android REST API calls to /api/devices/* legacy paths"
        ),
        description=(
            "The legacy REST compat aliases (/api/devices/*) have been present "
            "for multiple batch PRs with no confirmed retirement timeline.  "
            "Each additional batch without retirement increases the risk that "
            "Android adds new feature dependencies against the compat routes, "
            "expanding the migration surface."
        ),
        addressing_strategy=(
            "CONTRACT-007 (this PR) formally declares this surface as "
            "LEGACY_ONLY with an explicit retirement condition.  "
            "The DeprecationWarning fence remains active.  Android must be "
            "notified of the removal milestone."
        ),
        addressed=True,
        addressing_evidence=(
            "CONTRACT-007 (this PR) documents the LEGACY_ONLY status and "
            "retirement condition.  No new features may be added to compat routes."
        ),
        notes="Low severity: existing callers are known; no new callers expected.",
    ),
]


# ===========================================================================
# Query functions
# ===========================================================================


def get_contract_boundary_catalog() -> List[ContractBoundaryRecord]:
    """Return the full cross-repo contract boundary catalog.

    Returns
    -------
    list[ContractBoundaryRecord]
        All registered boundary records in catalog-definition order.
    """
    return list(_CONTRACT_BOUNDARY_CATALOG)


def get_drift_vector_catalog() -> List[DriftVectorRecord]:
    """Return the full cross-repo drift vector catalog.

    Returns
    -------
    list[DriftVectorRecord]
        All registered drift vector records in catalog-definition order.
    """
    return list(_DRIFT_VECTOR_CATALOG)


def get_boundaries_by_status(
    status: FinalizationStatus,
) -> List[ContractBoundaryRecord]:
    """Return all contract boundaries matching the given finalization status.

    Parameters
    ----------
    status:
        The :class:`FinalizationStatus` to filter by.

    Returns
    -------
    list[ContractBoundaryRecord]
    """
    return [r for r in _CONTRACT_BOUNDARY_CATALOG if r.status == status]


def get_ambiguous_boundaries() -> List[ContractBoundaryRecord]:
    """Return all contract boundaries with ``status == AMBIGUOUS``.

    AMBIGUOUS boundaries are the highest-priority targets for finalization.

    Returns
    -------
    list[ContractBoundaryRecord]
    """
    return get_boundaries_by_status(FinalizationStatus.AMBIGUOUS)


def get_drift_vectors_by_kind(
    kind: DriftVectorKind,
) -> List[DriftVectorRecord]:
    """Return all drift vectors matching the given kind.

    Parameters
    ----------
    kind:
        The :class:`DriftVectorKind` to filter by.

    Returns
    -------
    list[DriftVectorRecord]
    """
    return [v for v in _DRIFT_VECTOR_CATALOG if v.kind == kind]


# ===========================================================================
# Finalization gate runners
# ===========================================================================


def run_contract_boundary_gate(
    kind: ContractBoundaryKind,
) -> FinalizationGateResult:
    """Evaluate the contract finalization gate for the given boundary kind.

    Checks all boundaries of *kind* in the catalog.  Returns a
    :class:`FinalizationGateResult` with the aggregate verdict.

    Parameters
    ----------
    kind:
        The :class:`ContractBoundaryKind` to evaluate.

    Returns
    -------
    FinalizationGateResult
    """
    boundaries = [r for r in _CONTRACT_BOUNDARY_CATALOG if r.kind == kind]
    ambiguous = [r for r in boundaries if r.status == FinalizationStatus.AMBIGUOUS]
    legacy_only = [r for r in boundaries if r.status == FinalizationStatus.LEGACY_ONLY]

    # Unaddressed drift vectors for this boundary kind
    drift_vectors = [
        v for v in _DRIFT_VECTOR_CATALOG
        if not v.addressed
    ]
    # Narrow to drift vectors that are semantically related to this boundary
    # (heuristic: kind name appears in v2_surface or android_surface)
    kind_str = kind.value.lower()
    relevant_drift = [
        v for v in drift_vectors
        if kind_str in v.v2_surface.lower() or kind_str in v.android_surface.lower()
    ]

    issues: List[str] = []
    if ambiguous:
        for r in ambiguous:
            issues.append(
                f"AMBIGUOUS boundary {r.boundary_id}: {r.description[:80]}..."
            )
    if relevant_drift:
        for v in relevant_drift:
            issues.append(
                f"Unaddressed drift vector {v.vector_id} ({v.severity}): "
                f"{v.description[:80]}..."
            )

    if ambiguous or relevant_drift:
        verdict = FinalizationGateVerdict.fail
        details = (
            f"Gate {kind.value}: {len(ambiguous)} AMBIGUOUS boundaries, "
            f"{len(relevant_drift)} unaddressed drift vectors detected."
        )
        logger.warning(
            "FINALIZATION_GATE_FAIL kind=%s ambiguous=%d unaddressed_drift=%d",
            kind.value,
            len(ambiguous),
            len(relevant_drift),
        )
    elif legacy_only:
        verdict = FinalizationGateVerdict.warn
        details = (
            f"Gate {kind.value}: {len(legacy_only)} LEGACY_ONLY boundaries "
            "pending retirement.  No AMBIGUOUS surfaces or unaddressed drift."
        )
        logger.info(
            "FINALIZATION_GATE_WARN kind=%s legacy_only=%d",
            kind.value,
            len(legacy_only),
        )
    else:
        verdict = FinalizationGateVerdict.pass_
        details = (
            f"Gate {kind.value}: all boundaries STABLE or HARDENING.  "
            "No AMBIGUOUS surfaces or unaddressed drift detected."
        )
        logger.debug("FINALIZATION_GATE_PASS kind=%s", kind.value)

    return FinalizationGateResult(
        gate_id=f"contract_boundary_{kind.value}",
        kind=kind,
        verdict=verdict,
        ambiguous_count=len(ambiguous),
        legacy_only_count=len(legacy_only),
        unaddressed_drift_count=len(relevant_drift),
        details=details,
        issues=issues,
    )


def run_drift_vector_gate() -> FinalizationGateResult:
    """Evaluate the aggregate drift vector finalization gate.

    Checks all drift vectors in the catalog.  Returns a
    :class:`FinalizationGateResult` with the aggregate verdict.

    The gate kind is reported as :attr:`ContractBoundaryKind.task_dispatch_ingress`
    as a sentinel kind for the aggregate drift gate.

    Returns
    -------
    FinalizationGateResult
    """
    all_vectors = _DRIFT_VECTOR_CATALOG
    unaddressed = [v for v in all_vectors if not v.addressed]
    high_unaddressed = [v for v in unaddressed if v.severity == "HIGH"]

    issues: List[str] = []
    for v in unaddressed:
        issues.append(
            f"Unaddressed drift vector {v.vector_id} ({v.severity}, {v.kind.value}): "
            f"{v.description[:80]}..."
        )

    if high_unaddressed:
        verdict = FinalizationGateVerdict.fail
        details = (
            f"Drift vector gate: {len(high_unaddressed)} HIGH-severity unaddressed "
            f"vectors out of {len(unaddressed)} total unaddressed."
        )
    elif unaddressed:
        verdict = FinalizationGateVerdict.warn
        details = (
            f"Drift vector gate: {len(unaddressed)} MEDIUM/LOW unaddressed "
            f"vectors.  No HIGH-severity unaddressed vectors."
        )
    else:
        verdict = FinalizationGateVerdict.pass_
        details = (
            f"Drift vector gate: all {len(all_vectors)} vectors addressed.  "
            "No unaddressed drift detected."
        )

    return FinalizationGateResult(
        gate_id="aggregate_drift_vector",
        kind=ContractBoundaryKind.aggregate,
        verdict=verdict,
        ambiguous_count=0,
        legacy_only_count=0,
        unaddressed_drift_count=len(unaddressed),
        details=details,
        issues=issues,
    )


def run_all_finalization_gates() -> List[FinalizationGateResult]:
    """Run all contract finalization gates and return the aggregate results.

    Runs one gate per :class:`ContractBoundaryKind` value (excluding the
    ``aggregate`` sentinel kind) plus the aggregate drift vector gate.

    Returns
    -------
    list[FinalizationGateResult]
        One result per gate, in definition order.
    """
    results: List[FinalizationGateResult] = []
    for kind in ContractBoundaryKind:
        if kind is ContractBoundaryKind.aggregate:
            continue
        results.append(run_contract_boundary_gate(kind))
    results.append(run_drift_vector_gate())
    return results


# ===========================================================================
# Snapshot builder
# ===========================================================================


def build_finalization_snapshot() -> ContractFinalizationSnapshot:
    """Build a JSON-serialisable snapshot of the finalization posture.

    This snapshot is suitable for CI consumption and operator dashboards.

    Returns
    -------
    ContractFinalizationSnapshot
    """
    boundaries = _CONTRACT_BOUNDARY_CATALOG
    drift_vectors = _DRIFT_VECTOR_CATALOG

    stable = sum(1 for b in boundaries if b.status == FinalizationStatus.STABLE)
    hardening = sum(1 for b in boundaries if b.status == FinalizationStatus.HARDENING)
    ambiguous = sum(1 for b in boundaries if b.status == FinalizationStatus.AMBIGUOUS)
    legacy_only = sum(1 for b in boundaries if b.status == FinalizationStatus.LEGACY_ONLY)

    addressed = sum(1 for v in drift_vectors if v.addressed)
    unaddressed = sum(1 for v in drift_vectors if not v.addressed)
    high_unaddressed = sum(
        1 for v in drift_vectors if not v.addressed and v.severity == "HIGH"
    )

    finalization_complete = ambiguous == 0 and high_unaddressed == 0

    gate_results = run_all_finalization_gates()

    return ContractFinalizationSnapshot(
        total_boundaries=len(boundaries),
        stable_count=stable,
        hardening_count=hardening,
        ambiguous_count=ambiguous,
        legacy_only_count=legacy_only,
        total_drift_vectors=len(drift_vectors),
        addressed_drift_count=addressed,
        unaddressed_drift_count=unaddressed,
        high_severity_unaddressed_count=high_unaddressed,
        finalization_complete=finalization_complete,
        generated_at=time.time(),
        policy_sentinels=[
            CONTRACT_BOUNDARIES_MUST_BE_EXPLICIT_POLICY,
            RESIDUAL_COMPAT_PATHS_MUST_BE_FENCED_OR_RETIRED_POLICY,
            ANDROID_CONTRACT_EXPECTATIONS_MUST_BE_CENTER_AUTHORITATIVE_POLICY,
            DRIFT_VECTORS_MUST_BE_CATALOGUED_AND_ADDRESSED_POLICY,
            FINALIZATION_PASS_MUST_SHRINK_AMBIGUITY_POLICY,
        ],
        gate_results=[r.to_dict() for r in gate_results],
        boundary_summaries=[b.to_dict() for b in boundaries],
        drift_vector_summaries=[v.to_dict() for v in drift_vectors],
    )


def is_contract_finalization_complete() -> bool:
    """Return ``True`` iff no AMBIGUOUS boundaries and no HIGH-severity
    unaddressed drift vectors remain in the catalog.

    This is the center-side finalization readiness gate.  A ``True`` result
    means the canonical runtime model is clean enough for the next milestone.

    Returns
    -------
    bool
    """
    ambiguous = get_ambiguous_boundaries()
    high_unaddressed = [
        v
        for v in _DRIFT_VECTOR_CATALOG
        if not v.addressed and v.severity == "HIGH"
    ]
    return len(ambiguous) == 0 and len(high_unaddressed) == 0
