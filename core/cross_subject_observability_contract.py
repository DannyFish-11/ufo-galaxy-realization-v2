#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/cross_subject_observability_contract.py
=============================================
PR-12V2: Unified Cross-Subject Observability / Diagnostics / Evidence Contract.

Purpose
-------
This module is the **single authoritative contract declaration** for the
4-level visibility taxonomy that all participants (V2 canonical center,
Android bounded subject, other bounded subjects) must use when classifying
their diagnostics, evidence, and observable outputs.

It builds directly on:

* PR-Task3 ``contracts/distributed_subject_contract_v1`` — DIAGNOSTICS
  dimension with local_visible_diagnostics / participant_diagnostics_uplink /
  operator_visible_diagnostics fields.
* PR-10V2 ``core.diagnostics_failure_explanation_convergence`` — five-kind
  diagnostics/failure/explanation taxonomy (AUTHORITY_EXECUTION_TRUTH /
  FAILURE_DIAGNOSTICS_TRUTH / ARTIFACT_EVIDENCE_TRUTH /
  OPERATOR_SUMMARY_EXPLANATION / AUDIT_POSTRUN_INTERPRETATION).
* PR-9V2 ``core.distributed_truth_ownership_convergence`` — four-domain
  ownership taxonomy.
* PR-Task3 ``contracts/distributed_subject_contract_v1.SubjectContractDimension``
  — DIAGNOSTICS dimension.

Problem addressed
-----------------
After PRs #10V2–#11V2 the system has a 5-kind diagnostics taxonomy and a
distributed subject contract with DIAGNOSTICS fields.  However:

1. There is no explicit **4-level visibility taxonomy** that every participant
   must use when classifying its diagnostics and evidence outputs.
2. The TRANSITIONAL ``participant_diagnostics_uplink`` field in
   distributed_subject_contract_v1 is now superseded by this formalised
   evidence uplink contract.
3. There is no single declaration of *which* evidence/diagnostics may travel
   *which* uplink path — allowing visibility semantics to drift across
   handler implementations.
4. ``runtime-visible`` and ``product-visible`` are not yet first-class
   categories in the contract, causing consumers to under-specify or
   over-promote their outputs.

This module resolves that ambiguity by:

1. Declaring four *visibility levels* with explicit constraints on what
   evidence may claim, promote to, or reverse-inject into.
2. Declaring five *evidence contract kinds* aligned with the PR-10V2
   diagnostics taxonomy.
3. Providing policy sentinels that prevent visibility level conflation.
4. Declaring the canonical evidence uplink path that supersedes the
   TRANSITIONAL ``participant_diagnostics_uplink`` field.
5. Registering every observable surface with its visibility level and
   evidence kind so that CI gates can detect drift.
6. Providing snapshot and classification helpers for operator / CI use.

Four Visibility Levels
-----------------------
LOCAL_VISIBLE
    Diagnostics / evidence visible only within the bounded subject runtime
    (e.g., on-device Android logs, on-device RuntimeController state).
    **Constraint**: MUST NOT be promoted to runtime-visible, operator-visible,
    or canonical truth without explicit uplink through the declared canonical
    evidence uplink path.

RUNTIME_VISIBLE
    Diagnostics / evidence visible to the V2 runtime infrastructure.  These
    may inform runtime routing, posture, and truth-chain decisions but MUST
    NOT be treated as canonical acceptance or closure decisions on their own.
    **Constraint**: runtime-visible evidence reaches V2 truth chain processing
    only through declared ingress modules (android_participant_truth_ingress,
    android_evaluator_artifact_ingress).

OPERATOR_VISIBLE
    Diagnostics / evidence projected to operator dashboards and surfaces.
    These are **read-only projections** of canonical / runtime truth.
    **Constraint**: MUST NOT feed back into canonical truth; operator
    visibility is a projection consumer, not a truth producer.

PRODUCT_VISIBLE
    Diagnostics / evidence surfaced to end users or product consumers.
    These are the outermost read-only consumers.
    **Constraint**: MUST only consume canonical / bounded outputs;
    product-visible surfaces have no write path to canonical truth.

Five Evidence Contract Kinds
-----------------------------
PARTICIPANT_EVIDENCE
    Evidence from a bounded participant (Android, external device, or
    sub-runtime).  Classified as evidence_only until V2 canonical governance
    validates and promotes.  Aligns with ContractFieldLabel.EVIDENCE_ONLY
    and DiagnosticsSemanticKind.artifact_evidence_truth.

DIAGNOSTICS_EVIDENCE
    Failure / degraded-state records describing what happened in a failure
    or degraded episode.  These records exist for operator and CI inspection;
    they MUST NOT be read back as acceptance / closure gate inputs.
    Aligns with DiagnosticsSemanticKind.failure_diagnostics_truth.

EXECUTION_ARTIFACT
    Evaluated artefacts from execution chains (Android evaluators, V2
    execution chain artefacts).  These are gate inputs, not gate decisions.
    Aligns with DiagnosticsSemanticKind.artifact_evidence_truth.

CONTINUITY_EVIDENCE
    State evidence from recovery / replay / handoff / takeover / formation
    paths.  Describes continuity state but is NOT continuity canonical truth;
    V2 unified_continuity_legality_authority makes the legality determination.
    Aligns with ContractFieldLabel.EVIDENCE_ONLY (continuity dimension).

RUNTIME_TRUTH
    V2-validated canonical runtime truth.  This is NOT evidence — it is
    truth produced by the canonical center after evidence has been ingested
    and validated.  It is the terminal point of an evidence promotion chain.

Canonical Evidence Uplink Path
-------------------------------
This contract supersedes the TRANSITIONAL ``participant_diagnostics_uplink``
field defined in distributed_subject_contract_v1.  The formalised uplink path
is::

    Android / participant evidence (LOCAL_VISIBLE)
        └─ declared uplink channel (GalaxyConnectionService / GalaxyWebSocketClient)
              └─ galaxy_gateway.android.handlers.*   (RUNTIME_VISIBLE ingress)
                    ├─ core.android_evaluator_artifact_ingress
                    │      EXECUTION_ARTIFACT → AndroidEvaluatorArtifactRegistry
                    └─ core.android_participant_truth_ingress
                           DIAGNOSTICS_EVIDENCE + PARTICIPANT_EVIDENCE
                                 └─ core.v2_android_truth_ssot  (SSOT build)
                                       └─ core.canonical_session_truth
                                             └─ Stage 1: compile_runtime_truth()
                                                   └─ Stage 2: compile_outward_truth()
                                                         └─ OPERATOR_VISIBLE
                                                               └─ PRODUCT_VISIBLE

Policy Invariants
-----------------
1. LOCAL_VISIBLE evidence MUST NOT be promoted to runtime-visible, canonical
   truth, or operator-visible without explicit uplink through the declared
   canonical evidence uplink path.
2. RUNTIME_VISIBLE evidence MUST NOT bypass the declared V2 truth-chain
   ingress modules (android_participant_truth_ingress,
   android_evaluator_artifact_ingress).
3. OPERATOR_VISIBLE surfaces are read-only projections; they MUST NOT
   feed back into canonical truth or act as authority sources.
4. PRODUCT_VISIBLE surfaces are the outermost consumers; they MUST ONLY
   consume canonical / bounded outputs and have no write path to canonical
   truth.
5. No new parallel observability center or diagnostics authority is
   introduced by this module.
6. RUNTIME_TRUTH is produced only by V2 canonical governance; no bounded
   participant may unilaterally declare its output as RUNTIME_TRUTH.
7. evidence_kind labels MUST align with distributed_subject_contract_v1
   labels (CANONICAL / EVIDENCE_ONLY / TRANSITIONAL / etc.) to prevent
   contract drift.

Alignment with distributed_subject_contract_v1
-----------------------------------------------
This module extends the DIAGNOSTICS dimension of distributed_subject_contract_v1
with explicit visibility labels:

* ``local_visible_diagnostics``   → visibility=LOCAL_VISIBLE,
                                     kind=DIAGNOSTICS_EVIDENCE
* ``runtime_visible_diagnostics`` → visibility=RUNTIME_VISIBLE,
                                     kind=PARTICIPANT_EVIDENCE /
                                                 EXECUTION_ARTIFACT
* ``operator_visible_diagnostics`` → visibility=OPERATOR_VISIBLE,
                                      kind=DIAGNOSTICS_EVIDENCE (read-only)
* ``product_visible_diagnostics``  → visibility=PRODUCT_VISIBLE,
                                      kind=DIAGNOSTICS_EVIDENCE (read-only)
* ``participant_diagnostics_uplink`` → superseded by this module's
                                        canonical uplink path declaration

This module does NOT modify any existing module.  It declares, classifies,
and provides snapshot helpers only.

Public API
----------
Authority sentinels::

    CROSS_SUBJECT_OBSERVABILITY_CONTRACT_AUTHORITY
    CROSS_SUBJECT_OBSERVABILITY_CONTRACT_PR12V2_SENTINEL

Policy sentinels::

    LOCAL_VISIBLE_MUST_NOT_SKIP_UPLINK_POLICY
    RUNTIME_VISIBLE_MUST_USE_DECLARED_INGRESS_POLICY
    OPERATOR_VISIBLE_IS_READ_ONLY_PROJECTION_POLICY
    PRODUCT_VISIBLE_CONSUMES_CANONICAL_OUTPUTS_ONLY_POLICY
    NO_PARALLEL_OBSERVABILITY_CENTER_POLICY
    RUNTIME_TRUTH_IS_V2_CANONICAL_CENTER_ONLY_POLICY

Enums::

    VisibilityLevel
    EvidenceContractKind

Data classes::

    ObservabilitySurface
    CrossSubjectObservabilitySnapshot

Functions::

    get_observability_surface_registry()
    classify_surface_visibility(surface_id)
    get_surfaces_by_visibility(level)
    build_cross_subject_observability_snapshot()
    get_canonical_evidence_uplink_path()

Registry (for direct inspection)::

    OBSERVABILITY_SURFACE_REGISTRY
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

__all__ = [
    # Authority sentinels
    "CROSS_SUBJECT_OBSERVABILITY_CONTRACT_AUTHORITY",
    "CROSS_SUBJECT_OBSERVABILITY_CONTRACT_PR12V2_SENTINEL",
    # Policy sentinels
    "LOCAL_VISIBLE_MUST_NOT_SKIP_UPLINK_POLICY",
    "RUNTIME_VISIBLE_MUST_USE_DECLARED_INGRESS_POLICY",
    "OPERATOR_VISIBLE_IS_READ_ONLY_PROJECTION_POLICY",
    "PRODUCT_VISIBLE_CONSUMES_CANONICAL_OUTPUTS_ONLY_POLICY",
    "NO_PARALLEL_OBSERVABILITY_CENTER_POLICY",
    "RUNTIME_TRUTH_IS_V2_CANONICAL_CENTER_ONLY_POLICY",
    # Enums
    "VisibilityLevel",
    "EvidenceContractKind",
    # Data classes
    "ObservabilitySurface",
    "CrossSubjectObservabilitySnapshot",
    # Functions
    "get_observability_surface_registry",
    "classify_surface_visibility",
    "get_surfaces_by_visibility",
    "build_cross_subject_observability_snapshot",
    "get_canonical_evidence_uplink_path",
    # Registry
    "OBSERVABILITY_SURFACE_REGISTRY",
]


# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

CROSS_SUBJECT_OBSERVABILITY_CONTRACT_AUTHORITY: str = (
    "CROSS_SUBJECT_OBSERVABILITY_CONTRACT_AUTHORITY_V1: "
    "core.cross_subject_observability_contract is the single authoritative "
    "contract declaration for the 4-level visibility taxonomy "
    "(local-visible / runtime-visible / operator-visible / product-visible) "
    "and 5-kind evidence contract (participant_evidence / diagnostics_evidence / "
    "execution_artifact / continuity_evidence / runtime_truth) used by all "
    "V2 ↔ Android (bounded relative subject) participants.  It supersedes the "
    "TRANSITIONAL participant_diagnostics_uplink field in "
    "distributed_subject_contract_v1 with a formalised canonical evidence "
    "uplink contract."
)
"""Module-level authority sentinel for the cross-subject observability /
diagnostics / evidence contract (PR-12V2)."""

CROSS_SUBJECT_OBSERVABILITY_CONTRACT_PR12V2_SENTINEL: str = (
    "cross_subject_observability_contract_pr12v2_boundary_locked"
)
"""PR-12V2 sentinel value.  Tests and CI gates locking this boundary must
assert the presence of this sentinel."""


# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

LOCAL_VISIBLE_MUST_NOT_SKIP_UPLINK_POLICY: str = (
    "LOCAL_VISIBLE_MUST_NOT_SKIP_UPLINK_POLICY_V1: "
    "local_visible diagnostics and evidence produced by bounded subject "
    "runtimes (e.g. Android RuntimeController, on-device logs) MUST NOT be "
    "promoted to runtime-visible, operator-visible, or canonical truth without "
    "explicit uplink through the declared canonical evidence uplink path "
    "(GalaxyConnectionService → galaxy_gateway.android.handlers → "
    "android_participant_truth_ingress / android_evaluator_artifact_ingress); "
    "treating local_visible evidence as runtime-visible or canonical without "
    "uplink is a visibility contract violation."
)
"""Policy: local-visible evidence requires explicit canonical uplink."""

RUNTIME_VISIBLE_MUST_USE_DECLARED_INGRESS_POLICY: str = (
    "RUNTIME_VISIBLE_MUST_USE_DECLARED_INGRESS_POLICY_V1: "
    "runtime_visible diagnostics and evidence reaching V2 infrastructure MUST "
    "enter the V2 truth chain only through declared ingress modules — "
    "core.android_participant_truth_ingress for failure/participant signals "
    "and core.android_evaluator_artifact_ingress for evaluator artefacts; "
    "runtime-visible evidence that bypasses these declared ingress modules "
    "MUST NOT be treated as part of the canonical truth chain; side-channel "
    "evidence injection is a visibility contract violation."
)
"""Policy: runtime-visible evidence must use the declared V2 ingress path."""

OPERATOR_VISIBLE_IS_READ_ONLY_PROJECTION_POLICY: str = (
    "OPERATOR_VISIBLE_IS_READ_ONLY_PROJECTION_POLICY_V1: "
    "operator_visible surfaces (operator_surface, routes/operator, "
    "operator_execution_observability_surface, routes/observability) are "
    "read-only projections of canonical / runtime truth; they MUST NOT "
    "feed back into canonical truth, override acceptance decisions, or act "
    "as authority inputs to the execution chain; an operator reading or "
    "acting on an operator-visible surface does so via the canonical "
    "governance action path (operator_action_contract), not by writing "
    "directly into execution truth."
)
"""Policy: operator-visible surfaces are read-only projections."""

PRODUCT_VISIBLE_CONSUMES_CANONICAL_OUTPUTS_ONLY_POLICY: str = (
    "PRODUCT_VISIBLE_CONSUMES_CANONICAL_OUTPUTS_ONLY_POLICY_V1: "
    "product_visible surfaces (outward-facing routes, final_acceptance_surface, "
    "unified_panel_aggregation, desktop_projection, desktop_status_board) MUST "
    "only consume canonical / bounded outputs produced by the Stage 2 "
    "outward truth chain (compile_outward_truth); product-visible surfaces "
    "MUST NOT read raw subsystem internals, local-visible evidence, or "
    "runtime-visible diagnostics directly; they are the outermost consumers "
    "and have no write path to canonical truth."
)
"""Policy: product-visible surfaces consume only canonical outward outputs."""

NO_PARALLEL_OBSERVABILITY_CENTER_POLICY: str = (
    "NO_PARALLEL_OBSERVABILITY_CENTER_POLICY_V1: "
    "this module consolidates and declares the cross-subject observability "
    "visibility contract; it does NOT introduce a new observability center, "
    "a new diagnostics authority, a new monitoring stack, or a new evidence "
    "ingress pipeline alongside the existing canonical chain; all new "
    "observability extensions must integrate into the existing declared "
    "uplink and truth-chain path, not alongside it; no module introduced "
    "after this contract may claim to be an alternative observability "
    "authority."
)
"""Policy: no new parallel observability center or diagnostics authority."""

RUNTIME_TRUTH_IS_V2_CANONICAL_CENTER_ONLY_POLICY: str = (
    "RUNTIME_TRUTH_IS_V2_CANONICAL_CENTER_ONLY_POLICY_V1: "
    "runtime_truth evidence kind is produced exclusively by V2 canonical "
    "governance after evidence has been ingested, validated, and accepted "
    "through the canonical truth chain; no bounded participant (Android, "
    "external device, or sub-runtime) may unilaterally declare its own "
    "output as runtime_truth; participant outputs are evidence_kinds "
    "(participant_evidence, diagnostics_evidence, execution_artifact, or "
    "continuity_evidence) until V2 governance promotes them."
)
"""Policy: only V2 canonical center produces runtime_truth."""


# ---------------------------------------------------------------------------
# Visibility level taxonomy
# ---------------------------------------------------------------------------


class VisibilityLevel(str, Enum):
    """Four-level visibility taxonomy for cross-subject observability.

    Every observable surface — whether on Android, in V2 runtime
    infrastructure, on operator dashboards, or in product-facing endpoints —
    is classified into exactly one of these four levels.
    """

    local_visible = "local_visible"
    """Visible only within the bounded subject runtime (e.g., Android device).
    Not promoted beyond the device boundary without explicit uplink.
    Examples: RuntimeController.kt logs, LocalLoopExecutor traces,
    AndroidContinuityIntegration local recovery state,
    OfflineTaskQueue local queue evidence.
    Constraint: MUST NOT be promoted to canonical truth without uplink."""

    runtime_visible = "runtime_visible"
    """Visible to the V2 runtime infrastructure after explicit uplink.
    These reach the V2 truth chain through declared ingress modules.
    Examples: android_participant_truth_ingress signals,
    android_evaluator_artifact_ingress artefacts,
    galaxy_gateway handler ingress records.
    Constraint: must use declared ingress path; MUST NOT bypass truth chain."""

    operator_visible = "operator_visible"
    """Visible to operators via operator dashboards and surfaces.
    These are read-only projections of canonical / runtime truth.
    Examples: operator_surface.py views, routes/operator endpoints,
    operator_execution_observability_surface snapshots,
    routes/observability execution evidence state,
    routes/projection explanation fields.
    Constraint: read-only; MUST NOT feed back into canonical truth."""

    product_visible = "product_visible"
    """Visible to end users or product consumers (outermost layer).
    These are the final outward-facing outputs of the canonical chain.
    Examples: outward_runtime_truth (compile_outward_truth output),
    final_acceptance_surface_boundary outputs,
    unified_panel_aggregation payload,
    desktop_projection outputs.
    Constraint: MUST only consume canonical / bounded Stage 2 outputs."""


# ---------------------------------------------------------------------------
# Evidence contract kind taxonomy
# ---------------------------------------------------------------------------


class EvidenceContractKind(str, Enum):
    """Five-kind evidence contract taxonomy for cross-subject observability.

    Every piece of evidence or diagnostics produced by any participant or
    surface is classified into exactly one of these five kinds.  This taxonomy
    aligns with the PR-10V2 DiagnosticsSemanticKind and the PR-Task3
    ContractFieldLabel.
    """

    participant_evidence = "participant_evidence"
    """Evidence from a bounded participant (Android, external device).
    Classified as evidence_only until V2 canonical governance validates it.
    Aligns with: ContractFieldLabel.EVIDENCE_ONLY,
                 DiagnosticsSemanticKind.artifact_evidence_truth.
    Examples: Android readiness signals, Android busy state,
    Android local execution mode decisions."""

    diagnostics_evidence = "diagnostics_evidence"
    """Failure / degraded-state records describing what happened.
    These are for operator and CI inspection only; MUST NOT be read
    back as acceptance / closure gate inputs.
    Aligns with: DiagnosticsSemanticKind.failure_diagnostics_truth.
    Examples: FailureClassification records, error_framework summaries,
    diagnostics route snapshots, Android failure signals."""

    execution_artifact = "execution_artifact"
    """Evaluated artefacts from execution chains.  These are gate inputs,
    not gate decisions.  A gate that consumes an artifact and produces
    accept/reject is producing acceptance_closure truth, not more artifact.
    Aligns with: DiagnosticsSemanticKind.artifact_evidence_truth.
    Examples: Android evaluator artefacts (readiness/acceptance/governance),
    V2 execution chain artefacts, ownership transfer proof quality records."""

    continuity_evidence = "continuity_evidence"
    """State evidence from recovery / replay / handoff / takeover / formation
    paths.  Describes continuity state but is NOT continuity canonical truth;
    V2 unified_continuity_legality_authority makes the legality decision.
    Aligns with: ContractFieldLabel.EVIDENCE_ONLY (continuity dimension).
    Examples: OfflineTaskQueue contents, Android local recovery state,
    AndroidContinuityIntegration local continuity records."""

    runtime_truth = "runtime_truth"
    """V2-validated canonical runtime truth.  This is NOT evidence — it is
    truth produced by the canonical center after evidence has been ingested,
    validated, and accepted.  No bounded participant may claim this kind.
    Aligns with: DiagnosticsSemanticKind.authority_execution_truth,
                 ContractFieldLabel.CANONICAL.
    Examples: canonical_session_truth records, compile_runtime_truth() output,
    compile_outward_truth() output, unified_result_ingress canonical outcomes."""


# ---------------------------------------------------------------------------
# Surface data class
# ---------------------------------------------------------------------------


@dataclass
class ObservabilitySurface:
    """Single surface entry in the cross-subject observability registry.

    Parameters
    ----------
    surface_id:
        Short stable identifier.
    module_path:
        Fully-qualified Python module path (V2 side) or Kotlin class
        (Android side, prefixed with ``android:``).
    surface_name:
        Human-readable surface name with brief role summary.
    visibility_level:
        :class:`VisibilityLevel` classification.
    evidence_kind:
        :class:`EvidenceContractKind` of this surface's primary output.
    is_uplink_path:
        ``True`` if this surface is part of the declared canonical evidence
        uplink path from local-visible into the V2 truth chain.
    may_not_write_canonical_truth:
        ``True`` for all non-authority surfaces — they MUST NOT write
        directly into canonical truth state.
    distributed_subject_contract_v1_field:
        Name of the corresponding field in distributed_subject_contract_v1
        DIAGNOSTICS dimension, if any.
    notes:
        Human-readable explanation including governance constraints and
        any boundary risks.
    """

    surface_id: str
    module_path: str
    surface_name: str
    visibility_level: VisibilityLevel
    evidence_kind: EvidenceContractKind
    is_uplink_path: bool = False
    may_not_write_canonical_truth: bool = True
    distributed_subject_contract_v1_field: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> Dict:
        return {
            "surface_id": self.surface_id,
            "module_path": self.module_path,
            "surface_name": self.surface_name,
            "visibility_level": self.visibility_level.value,
            "evidence_kind": self.evidence_kind.value,
            "is_uplink_path": self.is_uplink_path,
            "may_not_write_canonical_truth": self.may_not_write_canonical_truth,
            "distributed_subject_contract_v1_field": (
                self.distributed_subject_contract_v1_field
            ),
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Cross-subject observability snapshot
# ---------------------------------------------------------------------------


@dataclass
class CrossSubjectObservabilitySnapshot:
    """Aggregate snapshot produced by
    :func:`build_cross_subject_observability_snapshot`.
    """

    authority: str = ""
    sentinel: str = ""
    policies: Tuple[str, ...] = field(default_factory=tuple)
    total_surfaces: int = 0
    local_visible_count: int = 0
    runtime_visible_count: int = 0
    operator_visible_count: int = 0
    product_visible_count: int = 0
    uplink_path_surfaces: List[str] = field(default_factory=list)
    participant_evidence_count: int = 0
    diagnostics_evidence_count: int = 0
    execution_artifact_count: int = 0
    continuity_evidence_count: int = 0
    runtime_truth_count: int = 0
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "authority": self.authority,
            "sentinel": self.sentinel,
            "policies": list(self.policies),
            "total_surfaces": self.total_surfaces,
            "local_visible_count": self.local_visible_count,
            "runtime_visible_count": self.runtime_visible_count,
            "operator_visible_count": self.operator_visible_count,
            "product_visible_count": self.product_visible_count,
            "uplink_path_surfaces": self.uplink_path_surfaces,
            "participant_evidence_count": self.participant_evidence_count,
            "diagnostics_evidence_count": self.diagnostics_evidence_count,
            "execution_artifact_count": self.execution_artifact_count,
            "continuity_evidence_count": self.continuity_evidence_count,
            "runtime_truth_count": self.runtime_truth_count,
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Surface registry
# ---------------------------------------------------------------------------

#: Complete cross-subject observability surface registry.
#: Every surface that produces or consumes diagnostics / evidence /
#: visibility outputs across V2 ↔ Android is classified here.
OBSERVABILITY_SURFACE_REGISTRY: List[ObservabilitySurface] = [

    # =========================================================================
    # LOCAL_VISIBLE — on-device bounded subject surfaces
    # =========================================================================

    ObservabilitySurface(
        surface_id="android_runtime_controller_local",
        module_path="android:RuntimeController.kt",
        surface_name=(
            "Android RuntimeController (on-device local diagnostics — "
            "local_visible_diagnostics)"
        ),
        visibility_level=VisibilityLevel.local_visible,
        evidence_kind=EvidenceContractKind.diagnostics_evidence,
        is_uplink_path=False,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field="local_visible_diagnostics",
        notes=(
            "Android-local diagnostics visible only within the bounded subject "
            "runtime.  These are on-device logs, state traces, and local "
            "execution mode records from RuntimeController.  "
            "They MUST NOT be treated as operator-visible or canonical evidence "
            "without explicit uplink through the declared path."
        ),
    ),

    ObservabilitySurface(
        surface_id="android_local_loop_executor",
        module_path="android:LocalLoopExecutor.kt",
        surface_name=(
            "Android LocalLoopExecutor (on-device execution trace — "
            "local_visible)"
        ),
        visibility_level=VisibilityLevel.local_visible,
        evidence_kind=EvidenceContractKind.diagnostics_evidence,
        is_uplink_path=False,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field="local_visible_diagnostics",
        notes=(
            "On-device local execution loop traces.  These describe what the "
            "Android local executor did; they are local_visible_diagnostics "
            "only.  V2 does not see these unless uplinked."
        ),
    ),

    ObservabilitySurface(
        surface_id="android_offline_task_queue_evidence",
        module_path="android:OfflineTaskQueue.kt",
        surface_name=(
            "Android OfflineTaskQueue (continuity evidence — local_visible)"
        ),
        visibility_level=VisibilityLevel.local_visible,
        evidence_kind=EvidenceContractKind.continuity_evidence,
        is_uplink_path=False,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field="offline_task_queue",
        notes=(
            "Android-local offline task queue.  Contents are continuity_evidence "
            "— they document locally-queued work.  Does not imply cross-device "
            "continuity legality; V2 unified_continuity_legality_authority "
            "makes the legality determination after uplink."
        ),
    ),

    ObservabilitySurface(
        surface_id="android_local_execution_mode_gate",
        module_path="android:LocalExecutionModeGate.kt",
        surface_name=(
            "Android LocalExecutionModeGate (local mode decision — local_visible)"
        ),
        visibility_level=VisibilityLevel.local_visible,
        evidence_kind=EvidenceContractKind.participant_evidence,
        is_uplink_path=False,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field=None,
        notes=(
            "Android local execution mode gate decisions.  These are local "
            "participant_evidence: the Android device's own mode decision.  "
            "V2 does not adopt this as canonical mode truth without uplink "
            "and canonical governance validation."
        ),
    ),

    ObservabilitySurface(
        surface_id="android_continuity_integration_local",
        module_path="android:AndroidContinuityIntegration.kt",
        surface_name=(
            "Android AndroidContinuityIntegration (local continuity handling — "
            "local_visible)"
        ),
        visibility_level=VisibilityLevel.local_visible,
        evidence_kind=EvidenceContractKind.continuity_evidence,
        is_uplink_path=False,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field="local_continuity_handling",
        notes=(
            "Android-local continuity recovery and replay management.  "
            "continuity_evidence visible only on-device until explicitly "
            "uplinked via the declared path.  V2 cross-device continuation "
            "legality is determined separately."
        ),
    ),

    # =========================================================================
    # RUNTIME_VISIBLE — V2 runtime infrastructure ingress surfaces
    # =========================================================================

    ObservabilitySurface(
        surface_id="galaxy_gateway_android_handlers",
        module_path="galaxy_gateway.android.handlers",
        surface_name=(
            "galaxy_gateway.android.handlers (Android ingress gateway — "
            "runtime_visible uplink entry)"
        ),
        visibility_level=VisibilityLevel.runtime_visible,
        evidence_kind=EvidenceContractKind.participant_evidence,
        is_uplink_path=True,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field="participant_diagnostics_uplink",
        notes=(
            "The declared canonical ingress point where Android-originated "
            "evidence crosses from local_visible to runtime_visible.  "
            "This is the uplink entry for participant_evidence and "
            "diagnostics_evidence from Android.  "
            "Supersedes the TRANSITIONAL participant_diagnostics_uplink field "
            "in distributed_subject_contract_v1 with this formalised path."
        ),
    ),

    ObservabilitySurface(
        surface_id="android_participant_truth_ingress",
        module_path="core.android_participant_truth_ingress",
        surface_name=(
            "android_participant_truth_ingress (Android failure/participant "
            "signal ingress — runtime_visible → truth chain)"
        ),
        visibility_level=VisibilityLevel.runtime_visible,
        evidence_kind=EvidenceContractKind.diagnostics_evidence,
        is_uplink_path=True,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field="participant_diagnostics_uplink",
        notes=(
            "Canonical ingress for Android failure signals and participant "
            "truth.  Signals that reach build_v2_android_truth_block() are "
            "promoted from diagnostics_evidence to the V2 authority chain.  "
            "Signals that stop before reaching the SSOT remain "
            "diagnostics_evidence (advisory/local-only) and MUST NOT be "
            "treated as canonical truth."
        ),
    ),

    ObservabilitySurface(
        surface_id="android_evaluator_artifact_ingress_runtime",
        module_path="core.android_evaluator_artifact_ingress",
        surface_name=(
            "android_evaluator_artifact_ingress (Android evaluator artefact "
            "ingress — runtime_visible → artifact store)"
        ),
        visibility_level=VisibilityLevel.runtime_visible,
        evidence_kind=EvidenceContractKind.execution_artifact,
        is_uplink_path=True,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field="participant_diagnostics_uplink",
        notes=(
            "Canonical ingress for Android readiness/acceptance/governance/"
            "strategy evaluator artefacts.  Artefacts are execution_artifact "
            "— gate inputs, not gate decisions.  Storing an artefact here "
            "does not constitute closure or canonical acceptance."
        ),
    ),

    ObservabilitySurface(
        surface_id="android_participant_evidence_ingress",
        module_path="core.android_participant_evidence_ingress",
        surface_name=(
            "android_participant_evidence_ingress (Android participant evidence "
            "ingress — runtime_visible)"
        ),
        visibility_level=VisibilityLevel.runtime_visible,
        evidence_kind=EvidenceContractKind.participant_evidence,
        is_uplink_path=True,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field="participant_diagnostics_uplink",
        notes=(
            "Ingress for Android-originated participant evidence records "
            "(readiness, posture, busy, formation signals).  These are "
            "runtime_visible participant_evidence; V2 governance decides "
            "whether and how to promote them."
        ),
    ),

    ObservabilitySurface(
        surface_id="v2_android_truth_ssot_build",
        module_path="core.v2_android_truth_ssot",
        surface_name=(
            "v2_android_truth_ssot.build_v2_android_truth_block (SSOT build — "
            "runtime_visible → truth chain promotion)"
        ),
        visibility_level=VisibilityLevel.runtime_visible,
        evidence_kind=EvidenceContractKind.runtime_truth,
        is_uplink_path=True,
        may_not_write_canonical_truth=False,
        distributed_subject_contract_v1_field=None,
        notes=(
            "The canonical SSOT build step that promotes runtime_visible "
            "evidence into V2 canonical runtime truth.  This is the boundary "
            "where validated evidence transitions from diagnostics_evidence / "
            "participant_evidence to runtime_truth.  V2 authority: may write "
            "canonical truth."
        ),
    ),

    ObservabilitySurface(
        surface_id="routes_observability_execution_evidence",
        module_path="core.routes.observability",
        surface_name=(
            "core.routes.observability (execution evidence state endpoint — "
            "runtime_visible diagnostics surface)"
        ),
        visibility_level=VisibilityLevel.runtime_visible,
        evidence_kind=EvidenceContractKind.diagnostics_evidence,
        is_uplink_path=False,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field="operator_visible_diagnostics",
        notes=(
            "The /api/v1/observability/execution/evidence-state endpoint "
            "surfaces runtime-visible execution evidence for operator consumption.  "
            "It is a diagnostics_evidence surface; operator consumption via "
            "this endpoint moves the information to operator_visible.  "
            "This endpoint MUST NOT be used as an acceptance or closure gate input."
        ),
    ),

    # =========================================================================
    # OPERATOR_VISIBLE — operator dashboard and surface projections
    # =========================================================================

    ObservabilitySurface(
        surface_id="operator_surface_projections",
        module_path="core.operator_surface",
        surface_name=(
            "operator_surface (operator console / status board / topology — "
            "operator_visible projection)"
        ),
        visibility_level=VisibilityLevel.operator_visible,
        evidence_kind=EvidenceContractKind.diagnostics_evidence,
        is_uplink_path=False,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field="operator_visible_diagnostics",
        notes=(
            "Operator Surface enforces the projection-only principle: all "
            "views consume canonical runtime projections and MUST NOT infer "
            "system truth from raw subsystem internals.  "
            "operator_visible_diagnostics: read-only projection; must not "
            "feed back into canonical truth."
        ),
    ),

    ObservabilitySurface(
        surface_id="routes_operator_endpoints",
        module_path="core.routes.operator",
        surface_name=(
            "core.routes.operator (operator REST endpoints — operator_visible)"
        ),
        visibility_level=VisibilityLevel.operator_visible,
        evidence_kind=EvidenceContractKind.diagnostics_evidence,
        is_uplink_path=False,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field="operator_visible_diagnostics",
        notes=(
            "Operator REST API endpoints exposing governance action, snapshot, "
            "and board truth for operator consumption.  These are "
            "operator_visible_diagnostics; they surface canonical results "
            "and MUST NOT redefine them."
        ),
    ),

    ObservabilitySurface(
        surface_id="operator_execution_observability_surface",
        module_path="core.operator_execution_observability_surface",
        surface_name=(
            "operator_execution_observability_surface (operator execution "
            "evidence snapshot — operator_visible)"
        ),
        visibility_level=VisibilityLevel.operator_visible,
        evidence_kind=EvidenceContractKind.execution_artifact,
        is_uplink_path=False,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field="operator_visible_diagnostics",
        notes=(
            "Aggregates execution evidence and canonical result truth state "
            "into a unified operator-facing snapshot.  The snapshot is "
            "operator_visible / execution_artifact — it reads from the "
            "incomplete-result ledger, recent result ingress outcomes, and "
            "takeover tracking.  Read-only; MUST NOT feed back into truth."
        ),
    ),

    ObservabilitySurface(
        surface_id="routes_projection_explanation",
        module_path="core.routes.projection",
        surface_name=(
            "core.routes.projection (explanation fields — operator_visible "
            "runtime-truth projection)"
        ),
        visibility_level=VisibilityLevel.operator_visible,
        evidence_kind=EvidenceContractKind.diagnostics_evidence,
        is_uplink_path=False,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field="operator_visible_diagnostics",
        notes=(
            "The projection route assembles outward-facing runtime truth "
            "snapshots and operator explanations from Stage 2 outward truth.  "
            "Explanation / description fields are operator_visible diagnostics "
            "— they describe state, they do not define it.  Projection routes "
            "MUST NOT reverse-inject explanation text into authority truth."
        ),
    ),

    ObservabilitySurface(
        surface_id="diagnostics_failure_explanation_convergence_surface",
        module_path="core.diagnostics_failure_explanation_convergence",
        surface_name=(
            "diagnostics_failure_explanation_convergence (PR-10V2 five-kind "
            "boundary declaration — operator_visible meta-surface)"
        ),
        visibility_level=VisibilityLevel.operator_visible,
        evidence_kind=EvidenceContractKind.diagnostics_evidence,
        is_uplink_path=False,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field=None,
        notes=(
            "The PR-10V2 five-kind diagnostics/failure/explanation boundary "
            "declaration.  Its snapshot builder and classification helpers "
            "are operator_visible meta-surfaces for CI and monitoring "
            "consumption.  This contract builds on and is consistent with "
            "the PR-10V2 taxonomy."
        ),
    ),

    ObservabilitySurface(
        surface_id="android_delegated_runtime_audit_operator",
        module_path="core.android_delegated_runtime_audit",
        surface_name=(
            "android_delegated_runtime_audit (Android delegated audit — "
            "operator_visible post-hoc forensic)"
        ),
        visibility_level=VisibilityLevel.operator_visible,
        evidence_kind=EvidenceContractKind.diagnostics_evidence,
        is_uplink_path=False,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field=None,
        notes=(
            "Records Android delegated runtime audit events for post-hoc "
            "forensic analysis.  These are operator_visible "
            "diagnostics_evidence records; they describe what the Android "
            "runtime decided, they do not constitute a V2-side authority "
            "decision or canonical truth."
        ),
    ),

    # =========================================================================
    # PRODUCT_VISIBLE — outward-facing final consumers
    # =========================================================================

    ObservabilitySurface(
        surface_id="outward_runtime_truth_compile",
        module_path="core.outward_runtime_truth",
        surface_name=(
            "outward_runtime_truth.compile_outward_truth (Stage 2 outward "
            "truth — product_visible canonical output)"
        ),
        visibility_level=VisibilityLevel.product_visible,
        evidence_kind=EvidenceContractKind.runtime_truth,
        is_uplink_path=False,
        may_not_write_canonical_truth=False,
        distributed_subject_contract_v1_field="operator_visible_diagnostics",
        notes=(
            "Stage 2 of the canonical truth output chain: assembles the "
            "outward-facing truth snapshot from Stage 1 compile_runtime_truth.  "
            "This is the canonical boundary output that product-visible "
            "consumers MUST use.  May write canonical outward truth as a "
            "canonical center module."
        ),
    ),

    ObservabilitySurface(
        surface_id="final_acceptance_surface_boundary",
        module_path="core.final_acceptance_surface_boundary",
        surface_name=(
            "final_acceptance_surface_boundary (final acceptance layer — "
            "product_visible outward consumer)"
        ),
        visibility_level=VisibilityLevel.product_visible,
        evidence_kind=EvidenceContractKind.runtime_truth,
        is_uplink_path=False,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field=None,
        notes=(
            "The final acceptance surface boundary module.  Consumes "
            "canonical outputs and surfaces acceptance verdicts to "
            "product-facing consumers.  Read-only projection of "
            "acceptance_closure truth."
        ),
    ),

    ObservabilitySurface(
        surface_id="unified_panel_aggregation",
        module_path="core.unified_panel_aggregation",
        surface_name=(
            "unified_panel_aggregation (unified panel payload — "
            "product_visible outward aggregation)"
        ),
        visibility_level=VisibilityLevel.product_visible,
        evidence_kind=EvidenceContractKind.diagnostics_evidence,
        is_uplink_path=False,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field=None,
        notes=(
            "Aggregates canonical outputs into a unified panel payload for "
            "product-facing consumption.  MUST only consume canonical / "
            "bounded Stage 2 outputs.  Does not define or override "
            "canonical truth."
        ),
    ),

    ObservabilitySurface(
        surface_id="desktop_projection_outward",
        module_path="desktop_projection",
        surface_name=(
            "desktop_projection (desktop projection surface — "
            "product_visible outward)"
        ),
        visibility_level=VisibilityLevel.product_visible,
        evidence_kind=EvidenceContractKind.diagnostics_evidence,
        is_uplink_path=False,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field=None,
        notes=(
            "Desktop projection surface that surfaces canonical outward "
            "truth to desktop clients.  Product-visible consumer; MUST only "
            "consume canonical outputs from Stage 2 outward truth chain."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Registry accessor
# ---------------------------------------------------------------------------


def get_observability_surface_registry() -> List[ObservabilitySurface]:
    """Return the full cross-subject observability surface registry.

    Returns
    -------
    List[ObservabilitySurface]
        All surfaces classified within the PR-12V2 boundary.
    """
    return list(OBSERVABILITY_SURFACE_REGISTRY)


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def classify_surface_visibility(surface_id: str) -> str:
    """Return the :class:`VisibilityLevel` value for *surface_id*.

    Parameters
    ----------
    surface_id:
        The ``surface_id`` of a registered surface.

    Returns
    -------
    str
        The ``VisibilityLevel.value`` for the surface, or ``"unknown"``
        if *surface_id* is not in the registry.
    """
    for surface in OBSERVABILITY_SURFACE_REGISTRY:
        if surface.surface_id == surface_id:
            return surface.visibility_level.value
    return "unknown"


def get_surfaces_by_visibility(
    level: VisibilityLevel,
) -> List[ObservabilitySurface]:
    """Return all registry surfaces with the given visibility *level*.

    Parameters
    ----------
    level:
        :class:`VisibilityLevel` to filter by.

    Returns
    -------
    List[ObservabilitySurface]
        Surfaces whose ``visibility_level`` equals *level*.
    """
    return [s for s in OBSERVABILITY_SURFACE_REGISTRY if s.visibility_level == level]


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------


def build_cross_subject_observability_snapshot() -> (
    CrossSubjectObservabilitySnapshot
):
    """Build an aggregate observability snapshot for operator / CI visibility.

    Returns
    -------
    CrossSubjectObservabilitySnapshot
        Counts and metadata for all classified surfaces.
    """
    registry = OBSERVABILITY_SURFACE_REGISTRY
    uplink_surfaces = [s.surface_id for s in registry if s.is_uplink_path]
    return CrossSubjectObservabilitySnapshot(
        authority=CROSS_SUBJECT_OBSERVABILITY_CONTRACT_AUTHORITY,
        sentinel=CROSS_SUBJECT_OBSERVABILITY_CONTRACT_PR12V2_SENTINEL,
        policies=(
            LOCAL_VISIBLE_MUST_NOT_SKIP_UPLINK_POLICY,
            RUNTIME_VISIBLE_MUST_USE_DECLARED_INGRESS_POLICY,
            OPERATOR_VISIBLE_IS_READ_ONLY_PROJECTION_POLICY,
            PRODUCT_VISIBLE_CONSUMES_CANONICAL_OUTPUTS_ONLY_POLICY,
            NO_PARALLEL_OBSERVABILITY_CENTER_POLICY,
            RUNTIME_TRUTH_IS_V2_CANONICAL_CENTER_ONLY_POLICY,
        ),
        total_surfaces=len(registry),
        local_visible_count=sum(
            1 for s in registry
            if s.visibility_level == VisibilityLevel.local_visible
        ),
        runtime_visible_count=sum(
            1 for s in registry
            if s.visibility_level == VisibilityLevel.runtime_visible
        ),
        operator_visible_count=sum(
            1 for s in registry
            if s.visibility_level == VisibilityLevel.operator_visible
        ),
        product_visible_count=sum(
            1 for s in registry
            if s.visibility_level == VisibilityLevel.product_visible
        ),
        uplink_path_surfaces=uplink_surfaces,
        participant_evidence_count=sum(
            1 for s in registry
            if s.evidence_kind == EvidenceContractKind.participant_evidence
        ),
        diagnostics_evidence_count=sum(
            1 for s in registry
            if s.evidence_kind == EvidenceContractKind.diagnostics_evidence
        ),
        execution_artifact_count=sum(
            1 for s in registry
            if s.evidence_kind == EvidenceContractKind.execution_artifact
        ),
        continuity_evidence_count=sum(
            1 for s in registry
            if s.evidence_kind == EvidenceContractKind.continuity_evidence
        ),
        runtime_truth_count=sum(
            1 for s in registry
            if s.evidence_kind == EvidenceContractKind.runtime_truth
        ),
        generated_at=time.time(),
    )


# ---------------------------------------------------------------------------
# Canonical evidence uplink path declaration
# ---------------------------------------------------------------------------


def get_canonical_evidence_uplink_path() -> Tuple[str, ...]:
    """Return the declared canonical evidence uplink path.

    This path supersedes the TRANSITIONAL ``participant_diagnostics_uplink``
    field in ``distributed_subject_contract_v1`` with a formalised canonical
    contract.

    Returns
    -------
    Tuple[str, ...]
        Ordered sequence of module / class steps from Android local-visible
        evidence to V2 canonical runtime truth.
    """
    return (
        "Android/participant evidence (LOCAL_VISIBLE: RuntimeController.kt, "
        "LocalLoopExecutor.kt, AndroidContinuityIntegration.kt)",
        "Declared uplink channel: GalaxyConnectionService.kt / "
        "GalaxyWebSocketClient.kt",
        "galaxy_gateway.android.handlers (RUNTIME_VISIBLE ingress gateway)",
        "core.android_evaluator_artifact_ingress → "
        "AndroidEvaluatorArtifactRegistry (EXECUTION_ARTIFACT store)",
        "core.android_participant_truth_ingress → "
        "failure/participant signals (DIAGNOSTICS_EVIDENCE ingress)",
        "core.android_participant_evidence_ingress → "
        "participant readiness/posture/busy (PARTICIPANT_EVIDENCE ingress)",
        "core.v2_android_truth_ssot.build_v2_android_truth_block "
        "(SSOT build — RUNTIME_TRUTH promotion boundary)",
        "core.canonical_session_truth (merge + record)",
        "Stage 1: core.projection.runtime_truth_compiler.compile_runtime_truth()",
        "Stage 2: core.outward_runtime_truth.compile_outward_truth() "
        "(PRODUCT_VISIBLE boundary)",
        "Stage 3: core.routes.projection (OPERATOR_VISIBLE / PRODUCT_VISIBLE "
        "projection surfaces)",
    )
